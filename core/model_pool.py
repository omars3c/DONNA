"""
Centralized Resilient Gemini Model & Key Pool for D.O.N.N.A. / J.A.R.V.I.S.
Guarantees high-quota operation on Google AI Studio Free Tier (gemini-2.0-flash: 1500 RPD, 15 RPM).
Provides multi-key rotation and automatic failover when 429 RESOURCE_EXHAUSTED occurs.
"""

from __future__ import annotations

import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("DonnaModelPool")

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

# Operational models on Google AI Studio Free Tier
FAST_TEXT_MODEL = "gemini-3.6-flash"
LITE_TEXT_MODEL = "gemini-2.5-flash-lite"
BACKUP_TEXT_MODEL = "gemini-3.7-flash"
LEGACY_FALLBACK = "gemini-3.6-flash"
LIVE_AUDIO_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

CANDIDATE_MODELS = [
    FAST_TEXT_MODEL,
    "gemini-3.8-flash",
    BACKUP_TEXT_MODEL,
    LITE_TEXT_MODEL,
]

DEPRECATED_MODEL_MAP = {
    "gemini-1.5-flash": "gemini-3.6-flash",
    "gemini-1.5-flash-8b": "gemini-2.5-flash-lite",
    "gemini-1.5-pro": "gemini-3.8-flash",
    "gemini-2.0-flash": "gemini-3.6-flash",
    "gemini-2.0-flash-exp": "gemini-3.6-flash",
    "gemini-2.0-flash-lite": "gemini-2.5-flash-lite",
    "gemini-2.5-flash": "gemini-3.6-flash",
    "gemini-flash-latest": "gemini-3.6-flash",
}


class KeyStatus:
    def __init__(self, key: str):
        self.key: str = key
        self.cooldown_until: float = 0.0
        self.error_count: int = 0
        self.last_used: float = 0.0
        self.total_requests: int = 0

    @property
    def is_available(self) -> bool:
        return time.monotonic() >= self.cooldown_until

    def mark_rate_limited(self, cooldown_seconds: float = 60.0):
        self.cooldown_until = time.monotonic() + cooldown_seconds
        self.error_count += 1
        logger.warning(
            f"[ModelPool] Key ending in ...{self.key[-6:] if len(self.key) >= 6 else '***'} "
            f"hit 429/quota limit. Cooldown set for {cooldown_seconds}s."
        )

    def mark_success(self):
        self.error_count = 0
        self.last_used = time.monotonic()
        self.total_requests += 1


class GeminiKeyPool:
    _instance: Optional[GeminiKeyPool] = None

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or CONFIG_PATH
        self._keys: List[KeyStatus] = []
        self._clients: Dict[str, Any] = {}
        self._current_index: int = 0
        self.reload_keys()

    @classmethod
    def get_instance(cls) -> GeminiKeyPool:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reload_keys(self) -> int:
        raw_keys: List[str] = []

        # 1. From config JSON
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                primary = data.get("gemini_api_key", "").strip()
                if primary:
                    raw_keys.append(primary)
                backups = data.get("gemini_backup_keys", [])
                if isinstance(backups, list):
                    for b in backups:
                        if isinstance(b, str) and b.strip():
                            raw_keys.append(b.strip())
            except Exception as e:
                logger.error(f"[ModelPool] Failed to read keys from {self.config_path}: {e}")

        # 2. From environment variables
        env_primary = os.environ.get("GEMINI_API_KEY", "").strip()
        if env_primary:
            raw_keys.append(env_primary)
        for i in range(1, 10):
            env_backup = os.environ.get(f"GEMINI_API_KEY_{i}", "").strip()
            if env_backup:
                raw_keys.append(env_backup)

        # Deduplicate preserving order
        seen = set()
        clean_keys = []
        for k in raw_keys:
            if k and k not in seen:
                seen.add(k)
                clean_keys.append(k)

        # Preserve status of existing keys
        existing_map = {ks.key: ks for ks in self._keys}
        self._keys = [existing_map.get(k, KeyStatus(k)) for k in clean_keys]

        if not self._keys:
            logger.warning("[ModelPool] No Gemini API keys found in config or environment.")

        return len(self._keys)

    def get_active_key(self) -> str:
        if not self._keys:
            self.reload_keys()
        if not self._keys:
            raise RuntimeError("No Gemini API keys configured. Check config/api_keys.json.")

        # Find first available key starting from current index
        n = len(self._keys)
        for i in range(n):
            idx = (self._current_index + i) % n
            if self._keys[idx].is_available:
                self._current_index = idx
                return self._keys[idx].key

        # If all keys are in cooldown, pick the one that clears soonest
        earliest = min(self._keys, key=lambda ks: ks.cooldown_until)
        wait_time = max(0.0, earliest.cooldown_until - time.monotonic())
        if wait_time > 0:
            logger.warning(f"[ModelPool] All keys in cooldown. Earliest key clears in {wait_time:.1f}s.")
        return earliest.key

    def get_client(self, api_key: Optional[str] = None) -> Any:
        from google import genai

        key = api_key or self.get_active_key()
        if key not in self._clients:
            self._clients[key] = genai.Client(api_key=key)
        return self._clients[key]

    def rotate_key(self, reason: str = "Quota Exceeded") -> str:
        if len(self._keys) <= 1:
            return self._keys[0].key if self._keys else ""

        current_key = self._keys[self._current_index]
        current_key.mark_rate_limited(cooldown_seconds=60.0)

        # Advance to next available
        self._current_index = (self._current_index + 1) % len(self._keys)
        new_key = self.get_active_key()
        logger.info(
            f"[ModelPool] Rotated Gemini key due to {reason}. "
            f"Active: ...{new_key[-6:] if len(new_key) >= 6 else '***'}"
        )
        return new_key

    def generate_content(
        self,
        contents: Any,
        model: Optional[str] = None,
        config: Optional[Any] = None,
        max_retries: int = 3,
    ) -> Any:
        if model:
            mapped_model = DEPRECATED_MODEL_MAP.get(model, model)
            target_models = [mapped_model]
            for cm in CANDIDATE_MODELS:
                if cm not in target_models:
                    target_models.append(cm)
        else:
            target_models = list(CANDIDATE_MODELS)

        last_err: Optional[Exception] = None

        for attempt in range(max_retries):
            key = self.get_active_key()
            client = self.get_client(key)
            status = next((ks for ks in self._keys if ks.key == key), None)

            for model_name in target_models:
                try:
                    kwargs: Dict[str, Any] = {"model": model_name, "contents": contents}
                    if config is not None:
                        kwargs["config"] = config

                    resp = client.models.generate_content(**kwargs)
                    if resp and (getattr(resp, "text", None) or getattr(resp, "candidates", None)):
                        if status:
                            status.mark_success()
                        return resp
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                        logger.warning(f"[ModelPool] Quota hit on model '{model_name}' (attempt {attempt+1}): {e}")
                        if status:
                            status.mark_rate_limited(cooldown_seconds=60.0)
                        # Rotate to next key if available
                        self.rotate_key(reason=f"429 on {model_name}")
                        break  # Break inner model loop to retry with new key
                    elif "404" in err_str or "not found" in err_str or "no longer available" in err_str:
                        # Model not available in this tier or deprecated, try next fallback model
                        logger.info(f"[ModelPool] Model '{model_name}' not available (404/retired), trying fallback...")
                        continue
                    else:
                        # Other API or network error
                        time.sleep(0.5)
                        continue

            time.sleep(0.5 * (attempt + 1))

        if last_err:
            raise last_err
        raise RuntimeError("Failed to generate content: all models and keys exhausted.")


model_pool = GeminiKeyPool.get_instance()
