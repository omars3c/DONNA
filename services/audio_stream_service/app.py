"""
Audio Stream Microservice (Port 8005)
Host-level audio capture and playback daemon.
Runs sounddevice audio streams (16kHz in, 24kHz out), Vosk offline wake word,
and duplex audio streaming to the Brain Orchestrator over WebSocket.
"""

import sys
import time
import base64
import asyncio
import collections
from pathlib import Path
from contextlib import asynccontextmanager

if sys.platform == "win32":
    try:
        for _stream in (sys.stdout, sys.stderr):
            _reconf = getattr(_stream, "reconfigure", None)
            if callable(_reconf):
                _reconf(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import sounddevice as sd
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config import AUDIO_PORT, AUDIO_HOST, BRAIN_HOST, BRAIN_PORT
from core.wakeword import OfflineWakeWordEngine
from core.sfx import sfx
from shared.error_reporter import install_sentinel, report, report_exception

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
CHANNELS = 1
CHUNK_SIZE = 1024


class AudioDaemon:
    def __init__(self):
        self.is_active = False
        self.is_speaking = False
        self._speaking_until = 0.0
        self.output_queue = asyncio.Queue()
        self.ws = None
        self._loop = None
        self._pre_roll = collections.deque(maxlen=16)
        self.mic_stream = None
        self.out_stream = None

        def _on_wake(keyword: str):
            print(f"[AudioService] ⚡ Wake word triggered: '{keyword}'")
            sfx.play_wake()
            self.is_active = True
            if self.ws and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.ws.send_json({"type": "wake", "keyword": keyword}),
                    self._loop,
                )
                # Flush rolling pre-roll audio so words following the wake word are not lost
                while self._pre_roll:
                    pre_chunk = self._pre_roll.popleft()
                    b64_pre = base64.b64encode(pre_chunk).decode("ascii")
                    asyncio.run_coroutine_threadsafe(
                        self.ws.send_json({"type": "audio", "data": b64_pre}),
                        self._loop,
                    )

        def _on_interrupt(phrase: str):
            print(f"[AudioService] 🛑 Barge-in interrupt: '{phrase}'")
            self.is_speaking = False
            self._speaking_until = 0.0
            # Drain output audio buffer immediately
            while not self.output_queue.empty():
                try:
                    self.output_queue.get_nowait()
                except Exception:
                    break
            if self.ws and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.ws.send_json({"type": "interrupt", "phrase": phrase}),
                    self._loop,
                )

        self.wake_engine = OfflineWakeWordEngine(
            on_wake=_on_wake,
            on_interrupt=_on_interrupt,
        )

    @property
    def speaking_active(self) -> bool:
        return self.is_speaking or (time.monotonic() < self._speaking_until) or not self.output_queue.empty()

    def audio_input_callback(self, indata, frames, time_info, status):
        pcm_raw = bytes(indata)

        if self.speaking_active:
            # During speaking: check for barge-in stop words only (e.g. "стоп", "хватит", "тихо")
            matched, phrase = self.wake_engine.process_interrupt_audio(pcm_raw)
            if matched and self.wake_engine.on_interrupt:
                self.wake_engine.on_interrupt(phrase)
            # CRITICAL: Return immediately! Never process wake words or forward mic audio to Gemini while speaking!
            return

        # Software pre-amp gain boost (3.5x) with clipping limiter for clear sensitivity
        try:
            raw_samples = np.frombuffer(indata, dtype=np.int16)
            boosted = raw_samples.astype(np.float32) * 3.5
            clipped = np.clip(boosted, -32767, 32767).astype(np.int16)
            pcm_bytes = clipped.tobytes()
        except Exception:
            pcm_bytes = pcm_raw

        if not self.is_active:
            # During standby: buffer pre-roll and check for wake word
            self._pre_roll.append(pcm_bytes)
            self.wake_engine.process_audio(pcm_raw)
            return

        # Active listening session: send microphone audio to Brain
        if self.ws and self._loop:
            b64_pcm = base64.b64encode(pcm_bytes).decode("ascii")
            try:
                asyncio.run_coroutine_threadsafe(
                    self.ws.send_json({"type": "audio", "data": b64_pcm}),
                    self._loop,
                )
            except Exception:
                pass

    async def playback_worker(self):
        """Streams audio to speakers at 24 kHz."""
        while True:
            try:
                self.out_stream = sd.RawOutputStream(
                    samplerate=OUTPUT_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                )
                self.out_stream.start()
                print(f"[AudioService] 🔊 Speaker stream active ({OUTPUT_SAMPLE_RATE}Hz).")
                while True:
                    try:
                        chunk = await asyncio.wait_for(self.output_queue.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        if self.output_queue.empty() and self.is_speaking:
                            self.is_speaking = False
                            self._speaking_until = 0.0
                            if self.ws and self._loop:
                                asyncio.run_coroutine_threadsafe(
                                    self.ws.send_json({"type": "speech_done"}),
                                    self._loop,
                                )
                        continue

                    if not chunk or not self.out_stream:
                        continue

                    self.is_speaking = True
                    self._speaking_until = time.monotonic() + 0.6
                    # Smoothly batch chunks up to ~100ms (4800 bytes)
                    batch = bytearray(chunk)
                    while len(batch) < 4800:
                        try:
                            batch.extend(self.output_queue.get_nowait())
                        except (asyncio.QueueEmpty, Exception):
                            break

                    try:
                        await asyncio.to_thread(self.out_stream.write, bytes(batch))
                    except (RuntimeError, asyncio.CancelledError):
                        return
                    except Exception as stream_err:
                        print(f"[AudioService] ⚠️ Audio stream error: {stream_err}")
                        report("WARNING", "audio_playback", str(stream_err))
                        break

                    self._speaking_until = time.monotonic() + 0.3

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[AudioService] Playback stream error: {e}. Reopening in 1s...")
                report_exception("audio_playback", e)
                self.is_speaking = False
                self._speaking_until = 0.0
                if self.out_stream:
                    try:
                        self.out_stream.stop()
                        self.out_stream.close()
                    except Exception:
                        pass
                    self.out_stream = None
                await asyncio.sleep(1.0)

    async def connect_to_brain(self):
        """Connects to Brain Orchestrator WebSocket."""
        import aiohttp
        brain_ws_url = f"ws://{BRAIN_HOST}:{BRAIN_PORT}/ws/audio"
        while True:
            try:
                print(f"[AudioService] Connecting to Brain at {brain_ws_url}...")
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(brain_ws_url) as ws:
                        self.ws = ws
                        print("[AudioService] Connected to Brain Orchestrator.")
                        try:
                            sfx.play_startup()
                        except Exception:
                            pass
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.json()
                                msg_type = data.get("type")
                                if msg_type == "audio":
                                    b64 = data.get("data")
                                    if b64:
                                        chunk = base64.b64decode(b64)
                                        self.is_speaking = True
                                        self._speaking_until = time.monotonic() + 1.0
                                        await self.output_queue.put(chunk)
                                elif msg_type == "state":
                                    st = data.get("state")
                                    if st == "SPEAKING":
                                        self.is_speaking = True
                                    elif st == "LISTENING":
                                        self.is_active = True
                                        if self.output_queue.empty():
                                            self.is_speaking = False
                                            self._speaking_until = 0.0
                                    elif st == "THINKING":
                                        self.is_active = True
                                    elif st in ("SLEEPING", "STANDBY"):
                                        self.is_active = False
                                        self.is_speaking = False
                                        self._speaking_until = 0.0
                                elif msg_type == "interrupt":
                                    while not self.output_queue.empty():
                                        try:
                                            self.output_queue.get_nowait()
                                        except Exception:
                                            break
                                    self.is_speaking = False
                                    self._speaking_until = 0.0

            except Exception as e:
                print(f"[AudioService] Brain connection lost: {e}. Reconnecting in 3s...")
                report("ERROR", "brain_connection", str(e))
                self.ws = None
                await asyncio.sleep(3)


daemon = AudioDaemon()


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    daemon._loop = asyncio.get_running_loop()
    asyncio.create_task(daemon.connect_to_brain())
    asyncio.create_task(daemon.playback_worker())

    # Start mic stream and keep persistent reference on daemon to prevent GC crash
    try:
        daemon.mic_stream = sd.RawInputStream(
            samplerate=INPUT_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
            callback=daemon.audio_input_callback,
        )
        daemon.mic_stream.start()
        print("[AudioService] Microphone stream active (16kHz Mono).")
    except Exception as e:
        print(f"[AudioService] Could not open microphone: {e}")
        report_exception("mic_capture", e)

    yield

    if daemon.mic_stream:
        try:
            daemon.mic_stream.stop()
            daemon.mic_stream.close()
        except Exception:
            pass
    if daemon.out_stream:
        try:
            daemon.out_stream.stop()
            daemon.out_stream.close()
        except Exception:
            pass


app = FastAPI(
    title="DONNA Audio Stream Service",
    description="Microphone Capture, Speaker Playback, Vosk Wake Word & Barge-In",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_sentinel(app, "audio_stream_service")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "audio_stream_service",
        "port": AUDIO_PORT,
        "is_active": daemon.is_active,
        "is_speaking": daemon.is_speaking,
    }


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Audio Stream Service on {AUDIO_HOST}:{AUDIO_PORT}...")
    uvicorn.run(app, host=AUDIO_HOST, port=AUDIO_PORT)
