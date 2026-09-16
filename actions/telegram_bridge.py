"""
Telegram Gateway Sidecar for D.O.N.N.A. (Ported from OpenClaw Telegram Extension)
Runs as an isolated, asynchronous gateway service.
Supports:
- Remote text and voice message interaction
- Voice note audio transcription via Gemini
- Automated file dispatch (Word .docx, PDFs, diagrams, screenshots)
- Proactive alerts and reminder pushes
- Strict owner authentication / pairing security
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Callable, Dict, Any

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
CONFIG_FILE = BASE_DIR / "config" / "api_keys.json"


def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


class TelegramBridge:
    _instance: Optional[TelegramBridge] = None

    def __init__(self, token: Optional[str] = None, owner_id: Optional[str] = None):
        cfg = _load_config()
        self.token: str = token or cfg.get("telegram_bot_token", "")
        self.owner_id: str = str(owner_id or cfg.get("telegram_owner_id", ""))
        self._running: bool = False
        self._last_update_id: int = 0
        self._on_message_callback: Optional[Callable] = None
        self._gemini_key: str = cfg.get("gemini_api_key", "")

    @classmethod
    def get_instance(cls) -> TelegramBridge:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_message_handler(self, callback: Callable):
        self._on_message_callback = callback

    @property
    def is_configured(self) -> bool:
        return bool(self.token and len(self.token) > 20)

    async def _api_call(self, method: str, params: Optional[dict] = None, files: Optional[dict] = None) -> dict:
        """Async helper to execute Telegram Bot API calls."""
        if not self.is_configured:
            return {"ok": False, "description": "Telegram bot token is not configured."}

        url = f"https://api.telegram.org/bot{self.token}/{method}"
        loop = asyncio.get_event_loop()

        def _do_req():
            try:
                if files:
                    import mimetypes
                    boundary = "----DonnaTelegramBoundary" + os.urandom(8).hex()
                    body = bytearray()
                    # Add form fields
                    if params:
                        for k, v in params.items():
                            body.extend(f"--{boundary}\r\n".encode("utf-8"))
                            body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
                            body.extend(f"{v}\r\n".encode("utf-8"))
                    # Add files
                    for field_name, file_path in files.items():
                        fp = Path(file_path)
                        if not fp.exists():
                            continue
                        mime = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
                        body.extend(f"--{boundary}\r\n".encode("utf-8"))
                        body.extend(f'Content-Disposition: form-data; name="{field_name}"; filename="{fp.name}"\r\n'.encode("utf-8"))
                        body.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
                        body.extend(fp.read_bytes())
                        body.extend(b"\r\n")
                    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

                    req = urllib.request.Request(
                        url,
                        data=bytes(body),
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    )
                else:
                    data_bytes = json.dumps(params or {}).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=data_bytes,
                        headers={"Content-Type": "application/json"},
                    )

                with urllib.request.urlopen(req, timeout=25) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                return {"ok": False, "error": str(e)}

        return await loop.run_in_executor(None, _do_req)

    async def send_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        target = chat_id or self.owner_id
        if not target or not self.is_configured:
            return False
        res = await self._api_call("sendMessage", {"chat_id": target, "text": text, "parse_mode": "Markdown"})
        return res.get("ok", False)

    async def send_document(self, file_path: str, caption: str = "", chat_id: Optional[str] = None) -> bool:
        target = chat_id or self.owner_id
        if not target or not self.is_configured:
            return False
        res = await self._api_call("sendDocument", {"chat_id": target, "caption": caption}, files={"document": file_path})
        return res.get("ok", False)

    async def send_photo(self, photo_path: str, caption: str = "", chat_id: Optional[str] = None) -> bool:
        target = chat_id or self.owner_id
        if not target or not self.is_configured:
            return False
        res = await self._api_call("sendPhoto", {"chat_id": target, "caption": caption}, files={"photo": photo_path})
        return res.get("ok", False)

    async def _download_file(self, file_id: str, dest_path: Path) -> bool:
        """Download file from Telegram by file_id."""
        res = await self._api_call("getFile", {"file_id": file_id})
        if not res.get("ok"):
            return False
        file_path = res["result"].get("file_path", "")
        if not file_path:
            return False

        download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        loop = asyncio.get_event_loop()

        def _do_download():
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(download_url, str(dest_path))
                return True
            except Exception:
                return False

        return await loop.run_in_executor(None, _do_download)

    async def transcribe_voice(self, voice_file_path: Path) -> str:
        """Transcribe Telegram voice message (.ogg) using Gemini."""
        if not self._gemini_key or not voice_file_path.exists():
            return ""
        loop = asyncio.get_event_loop()

        def _transcribe():
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=self._gemini_key)
                audio_bytes = voice_file_path.read_bytes()
                resp = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"),
                        "Transcribe this voice message accurately in the original language. Output ONLY the transcription text, nothing else.",
                    ]
                )
                return (resp.text or "").strip()
            except Exception as e:
                print(f"[TelegramBridge] Voice transcription error: {e}")
                return ""

        return await loop.run_in_executor(None, _transcribe)

    async def run_polling(self):
        """Long polling service loop."""
        if not self.is_configured:
            print("[TelegramBridge] Telegram Bot Token not set. (Set 'telegram_bot_token' in config/api_keys.json to activate)")
            return

        print("[TelegramBridge] Connected and polling for updates...")
        self._running = True

        while self._running:
            try:
                updates = await self._api_call("getUpdates", {"offset": self._last_update_id + 1, "timeout": 20})
                if updates.get("ok") and updates.get("result"):
                    for item in updates["result"]:
                        self._last_update_id = item["update_id"]
                        msg = item.get("message") or item.get("edited_message")
                        if not msg:
                            continue

                        chat_id = str(msg["chat"]["id"])
                        from_user = msg.get("from", {})
                        username = from_user.get("username") or from_user.get("first_name", "User")
                        text = msg.get("text", "")
                        voice = msg.get("voice") or msg.get("audio")

                        # Pairing logic: if no owner is set, pair on /start or first command
                        if not self.owner_id:
                            self.owner_id = chat_id
                            cfg = _load_config()
                            cfg["telegram_owner_id"] = chat_id
                            _save_config(cfg)
                            await self.send_message(
                                f"🛡️ *D.O.N.N.A. TACTICAL OS CONNECTED*\n"
                                f"Device paired successfully with Operator: @{username} (ID: `{chat_id}`).\n"
                                f"You can now send text or voice commands from anywhere.",
                                chat_id=chat_id
                            )
                            continue

                        # Security check
                        if self.owner_id and chat_id != self.owner_id:
                            await self._api_call("sendMessage", {
                                "chat_id": chat_id,
                                "text": "⛔ Access Denied. This D.O.N.N.A. instance is paired to an authorized operator."
                            })
                            continue

                        # Handle Voice Messages
                        if voice:
                            file_id = voice["file_id"]
                            tmp_voice = BASE_DIR / "temp" / f"voice_{file_id}.ogg"
                            if await self._download_file(file_id, tmp_voice):
                                transcript = await self.transcribe_voice(tmp_voice)
                                if tmp_voice.exists():
                                    try:
                                        tmp_voice.unlink()
                                    except Exception:
                                        pass

                                if transcript:
                                    print(f"[TelegramBridge] 🎤 Voice from @{username}: '{transcript}'")
                                    await self.send_message(f"🎙️ *«{transcript}»*", chat_id=chat_id)
                                    if self._on_message_callback:
                                        resp = await self._on_message_callback(transcript, chat_id=chat_id)
                                        if resp:
                                            await self.send_message(resp, chat_id=chat_id)
                            continue

                        # Handle Text Messages
                        if text:
                            print(f"[TelegramBridge] 💬 Msg from @{username}: '{text}'")
                            if text == "/start":
                                await self.send_message(
                                    f"◈ *D.O.N.N.A. Online*\n"
                                    f"Operator: @{username}\n"
                                    f"Send any question, command, or voice note to control your PC.",
                                    chat_id=chat_id
                                )
                                continue

                            if self._on_message_callback:
                                resp = await self._on_message_callback(text, chat_id=chat_id)
                                if resp:
                                    await self.send_message(resp, chat_id=chat_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TelegramBridge] Polling exception: {e}")
                await asyncio.sleep(3)

        self._running = False


telegram_bridge = TelegramBridge.get_instance()
