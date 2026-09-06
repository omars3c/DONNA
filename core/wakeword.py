"""
Offline Wake Word & Voice Barge-in / Interrupt Detection Engine for D.O.N.N.A.
Listens for 'Донна', 'Donna', 'Пятница', 'Friday', 'Джарвис', 'Jarvis' (wake words) 
and 'Стоп', 'Хватит', 'Молчи', 'Тихо' (interrupts) offline via Vosk.
"""
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from core.sfx import sfx


def _get_configured_assistant_name() -> str:
    try:
        base_dir = Path(__file__).resolve().parent.parent
        cfg_path = base_dir / "config" / "api_keys.json"
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            return (data.get("assistant_name") or "донна").strip().lower()
    except Exception:
        pass
    return "донна"


class OfflineWakeWordEngine:
    """
    Offline keyword spotter using Kaldi/Vosk with grammar optimization.
    Zero cloud calls. Runs in real-time on 16 kHz mono PCM stream.
    Supports both Standby Wake Word detection and In-Speech Voice Interrupts (Barge-In).
    """

    def __init__(
        self,
        on_wake: Optional[Callable[[str], None]] = None,
        on_interrupt: Optional[Callable[[str], None]] = None,
    ):
        self.on_wake = on_wake
        self.on_interrupt = on_interrupt
        self._enabled = True
        self._last_wake_time = 0.0
        self._last_interrupt_time = 0.0
        self._cooldown = 1.5  # seconds between wake triggers
        self._interrupt_cooldown = 0.8  # seconds between interrupts
        self._lock = threading.Lock()
        self._rec = None
        self._rec_interrupt = None
        self._model = None
        self._asst_name = _get_configured_assistant_name()
        self._init_vosk()

    def _init_vosk(self) -> None:
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)  # Silence verbose C++ logging
            base_dir = Path(__file__).resolve().parent.parent
            candidate_paths = [
                base_dir / "models" / "vosk-model-small-ru-0.22",
                base_dir / "models" / "vosk-model-ru-0.42",
                base_dir / "core" / "models" / "vosk-model-small-ru-0.22",
            ]
            loaded_model = None
            for p in candidate_paths:
                if p.exists():
                    try:
                        loaded_model = Model(str(p))
                        break
                    except Exception:
                        pass
            if loaded_model is None:
                try:
                    loaded_model = Model(lang="ru")
                except Exception:
                    pass
            if loaded_model is None:
                raise RuntimeError("Could not find or load a valid Russian Vosk model.")

            self._model = loaded_model
            self._rec = KaldiRecognizer(self._model, 16000)
            self._rec_interrupt = KaldiRecognizer(self._model, 16000)
            print("[WakeWord] Offline Vosk engine ready (listening for wake words & interrupts).")
        except Exception as e:
            print(f"[WakeWord] Vosk init fallback: {e}")
            self._model = None
            self._rec = None
            self._rec_interrupt = None

    def _match_wake_keyword(self, clean_text: str) -> bool:
        if not clean_text:
            return False
        exact_triggers = {
            "донна", "донны", "донне", "донну", "донной", "доно", "donna", "дона", "доня",
            "пятница", "пятницы", "пятнице", "пятницу", "пятницей", "friday", "фрайдей",
            "джарвис", "джарвиса", "джарвису", "jarvis",
        }
        words = clean_text.split()
        for w in words:
            w_clean = w.strip(".,!?:;\"' ")
            if w_clean in exact_triggers:
                return True
            for t in exact_triggers:
                if len(w_clean) >= 4 and (w_clean.startswith(t) or t.startswith(w_clean)):
                    return True
        return False

    def process_audio(self, pcm_bytes: bytes) -> tuple[bool, str]:
        """
        Processes 16 kHz int16 mono PCM chunk in STANDBY mode.
        Returns (True, keyword) if wake word detected, else (False, '').
        """
        if not self._enabled or not self._rec or not pcm_bytes:
            return False, ""

        try:
            matched_text = ""
            if self._rec.AcceptWaveform(pcm_bytes):
                res = json.loads(self._rec.Result())
                matched_text = res.get("text", "")
            else:
                partial = json.loads(self._rec.PartialResult())
                matched_text = partial.get("partial", "")

            if matched_text:
                clean = matched_text.lower().strip()
                if self._match_wake_keyword(clean):
                    now = time.monotonic()
                    with self._lock:
                        if now - self._last_wake_time >= self._cooldown:
                            self._last_wake_time = now
                            self._rec.Reset()
                            print(f"[WakeWord] ⚡ Detected wake word: '{clean}' -> Waking up D.O.N.N.A.!")
                            sfx.play_wake()
                            if self.on_wake:
                                try:
                                    self.on_wake(clean)
                                except Exception:
                                    pass
                            return True, clean
        except Exception:
            pass

        return False, ""

    def process_interrupt_audio(self, pcm_bytes: bytes) -> tuple[bool, str]:
        """
        Processes 16 kHz int16 mono PCM chunk during active SPEECH (Barge-In).
        Listens for interrupt keywords ('стоп', 'хватит', 'молчи') OR wake words ('донна', 'пятница').
        Returns (True, keyword) if interrupt/wake word detected, else (False, '').
        """
        if not self._enabled or not self._rec_interrupt or not pcm_bytes:
            return False, ""

        try:
            matched_text = ""
            if self._rec_interrupt.AcceptWaveform(pcm_bytes):
                res = json.loads(self._rec_interrupt.Result())
                matched_text = res.get("text", "")
            else:
                partial = json.loads(self._rec_interrupt.PartialResult())
                matched_text = partial.get("partial", "")

            if matched_text:
                clean = matched_text.lower().strip()
                interrupt_triggers = (
                    "стоп", "донна стоп", "донна, стоп", "хватит", "молчи", "замолчи",
                    "тихо", "отбой", "прекрати", "остановись", "заткнись", "все хватит",
                    "всё хватит", "подожди", "погоди", "отмена", "слушай",
                    "stop", "donna stop", "shut up", "enough", "quiet",
                    "halt", "pause", "cancel"
                )
                is_interrupt = any(w in clean for w in interrupt_triggers)
                is_wake = self._match_wake_keyword(clean)

                if is_interrupt or is_wake:
                    now = time.monotonic()
                    with self._lock:
                        if now - self._last_interrupt_time >= self._interrupt_cooldown:
                            self._last_interrupt_time = now
                            self._rec_interrupt.Reset()
                            if self._rec:
                                self._rec.Reset()
                            if self.on_interrupt:
                                try:
                                    self.on_interrupt(clean)
                                except Exception:
                                    pass
                            return True, clean
        except Exception:
            pass

        return False, ""


def is_wake_word(text: str) -> tuple[bool, str]:
    if not text:
        return False, ""
    clean = text.lower().strip()
    triggers = (
        "донн", "donna", "hey donna", "доно", "дон", "доня",
        "пятниц", "фрайдей", "friday", "hey friday",
        "джарвис", "jarvis", "hey jarvis"
    )
    for w in triggers:
        if w in clean:
            return True, w
    return False, ""


def strip_wake_word(text: str) -> str:
    if not text:
        return ""
    pattern = re.compile(
        r"\b(донн[аеыуой]|donna|hey\s+donna|привет\s+донна|эй\s+донна|слушай\s+донна|"
        r"пятниц[аеыуой]|фрайдей|friday|hey\s+friday|привет\s+пятница|эй\s+пятница|"
        r"джарвис[аеуом]?|jarvis|hey\s+jarvis|привет\s+джарвис|эй\s+джарвис)\b",
        re.IGNORECASE
    )
    res = pattern.sub("", text)
    return re.sub(r"^[\s,.:!?-]+", "", res).strip()
