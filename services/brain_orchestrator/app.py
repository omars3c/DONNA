"""
Brain Orchestrator Microservice (Port 8001)
Central gateway managing Gemini Live WebSocket streaming, dialog state,
and asynchronous tool dispatching to downstream microservices.
"""

import sys
import json
import time
import base64
import asyncio
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    except Exception:
        pass

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import Request, FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai: Any = None
    types: Any = None

from shared.config import (
    BRAIN_PORT,
    BRAIN_HOST,
    CONFIG_DIR,
    API_KEYS_PATH,
    BASE_DIR as ROOT_DIR,
    ALLOWED_ORIGINS,
    verify_internal_token,
)
from services.brain_orchestrator.client_bridge import bridge

@asynccontextmanager
async def lifespan(app: FastAPI):
    brain._loop = asyncio.get_running_loop()
    asyncio.create_task(brain.run_gemini_session())
    yield


app = FastAPI(
    title="DONNA Brain Orchestrator",
    description="Central LLM Gateway, Gemini Live Duplex Streamer, and Service Router",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def verify_token_middleware(request: Request, call_next):
    from shared.config import verify_internal_token
    try:
        await verify_internal_token(request)
    except HTTPException as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


from shared.error_reporter import install_sentinel, report, report_exception
install_sentinel(app, "brain_orchestrator")

LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
PROMPT_PATH = ROOT_DIR / "core" / "prompt.txt"


def _read_config() -> dict:
    try:
        if API_KEYS_PATH.exists():
            return json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _get_api_key() -> str:
    return _read_config().get("gemini_api_key", "").strip()


def _load_prompt() -> str:
    try:
        if PROMPT_PATH.exists():
            return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return "You are D.O.N.N.A., an advanced AI assistant. Always use tools to complete tasks."


# ── Tool Declarations for Gemini Function Calling ─────────────────────────────
from shared.tool_declarations import TOOL_DECLARATIONS

class BrainOrchestrator:
    def __init__(self):
        self.session = None
        self.state = "STANDBY"
        self._active_until = 0.0
        self.hud_clients: List[WebSocket] = []
        self.audio_client: Optional[WebSocket] = None
        self._out_audio_queue = asyncio.Queue()
        self._in_audio_queue = asyncio.Queue()
        self._loop = None
        self._turn_done_event = asyncio.Event()
        self._speech_done_event = asyncio.Event()
        self._briefing_sent = False
        self._last_content = None
        self._tool_in_progress = False
        # Set to True after open_app returns AMBIGUOUS_BROWSER; cleared after the
        # next open_app call so the chosen browser is saved as default.
        self._pending_browser_disambiguation = False

    def wake_up(self, duration: float = 15.0, reason: str = ""):
        self._active_until = time.monotonic() + duration
        self.set_state("LISTENING")
        print(f"[Brain] 🟢 Woke up ({reason or 'active'}). Listening for {duration}s...")
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self.broadcast_hud({"type": "log", "speaker": "sys", "text": "SYS: Донна слушает вас..."}),
                self._loop
            )

    def go_to_sleep(self):
        self._active_until = 0.0
        self.set_state("STANDBY")
        print("[Brain] 💤 Returning to STANDBY mode.")
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self.broadcast_hud({"type": "log", "speaker": "sys", "text": "SYS: Режим ожидания (скажите 'Донна')."}),
                self._loop
            )

    async def broadcast_hud(self, event: dict):
        dead = []
        for ws in self.hud_clients:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.hud_clients:
                self.hud_clients.remove(ws)

    def set_state(self, new_state: str):
        if self.state == new_state:
            return
        self.state = new_state
        print(f"[Brain] State changed -> {new_state}")
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self.broadcast_state(new_state),
                self._loop,
            )

    async def broadcast_state(self, new_state: str):
        await self.broadcast_hud({"type": "state", "state": new_state})
        if self.audio_client:
            try:
                await self.audio_client.send_json({"type": "state", "state": new_state})
            except Exception:
                pass

    async def dispatch_tool_call(self, fc) -> Any:
        name = fc.name
        args = fc.args or {}
        print(f"[Brain] 🛠️ Dispatching Tool Call: {name}({args})")
        self.set_state("THINKING")
        await self.broadcast_hud({"type": "log", "speaker": "sys", "text": f"🔧 Tool Call: {name}"})

        result = "Done"
        try:
            if name == "open_app":
                _app_name = args.get("app_name", "")
                _disambig = self._pending_browser_disambiguation
                # Reset flag before the call so it's always cleaned up
                self._pending_browser_disambiguation = False
                result = await bridge.open_app(_app_name, pending_disambiguation=_disambig)
                # If this call returned AMBIGUOUS_BROWSER, arm the flag for the next call
                if isinstance(result, str) and result.startswith("AMBIGUOUS_BROWSER:"):
                    self._pending_browser_disambiguation = True
            elif name == "web_search":
                result = await bridge.web_search(args.get("query", ""), mode=args.get("mode", "search"))
            elif name == "deep_research_report":
                result = await bridge.deep_research_report(args.get("task", ""), user_instructions=args.get("user_instructions", ""))
            elif name in ("agent_task", "autonomous_task"):
                result = await bridge.agent_task(args.get("task", ""))
            elif name == "recall_memory":
                result = await bridge.recall_memory(args.get("query", ""), category=args.get("category", "all"))
            elif name == "save_knowledge":
                result = await bridge.save_knowledge(args.get("title", ""), args.get("content", ""), category=args.get("category", "notes"))
            elif name == "manage_cortex_tasks":
                result = await bridge.manage_cortex_tasks(
                    action=args.get("action", "list"),
                    task=args.get("task"),
                    task_id=args.get("task_id"),
                    priority=args.get("priority", "normal"),
                )
            elif name == "log_journal":
                result = await bridge.log_journal(args.get("entry", ""))
            elif name == "computer_control":
                action_val = args.get("action", "click")
                c_kwargs = {k: v for k, v in args.items() if k != "action"}
                result = await bridge.computer_control(action_val, **c_kwargs)
            elif name == "computer_settings":
                result = await bridge.computer_settings(args.get("action", ""), value=args.get("value"), app_name=args.get("app_name"))
            elif name == 'screen_process':
                angle = args.get("angle", "screen")
                img_bytes, mime_type = await bridge.capture_screenshot()
                if img_bytes:
                    try:
                        if self.session:
                            await self.session.send_realtime_input(
                                media=types.Blob(data=img_bytes, mime_type=mime_type or "image/jpeg")
                            )
                    except Exception as _e:
                        print(f"[Brain] Note: realtime media send: {_e}")
                    result = "Screenshot captured successfully and transmitted to vision analysis."
                else:
                    result = "Unable to capture screenshot at this moment."
            elif name == "system_status":
                status_dict = await bridge.get_system_status()
                result = json.dumps(status_dict, ensure_ascii=False)
            elif name == "browser_control":
                result = await bridge.browser_control(
                    action=args.get("action", "open"),
                    browser=args.get("browser"),
                    url=args.get("url"),
                    target=args.get("target"),
                )
            elif name == "reminder":
                result = await bridge.reminder(
                    action=args.get("action", "set"),
                    date=args.get("date"),
                    time=args.get("time"),
                    message=args.get("message"),
                    query=args.get("query"),
                    reminder_id=args.get("reminder_id"),
                )
            elif name == "youtube_video":
                result = await bridge.youtube_video(
                    action=args.get("action", "play"),
                    query=args.get("query"),
                    url=args.get("url"),
                    save=args.get("save", False),
                )
            elif name == "openclaw_skill":
                result = await bridge.openclaw_skill(
                    skill_name=args.get("skill_name", ""),
                    query=args.get("query", ""),
                    context=args,
                )

            else:
                result = f"Tool '{name}' is not recognized."
        except Exception as e:
            result = f"Error executing tool '{name}': {e}"
            traceback.print_exc()
            report_exception("tool_dispatch", e, tool=name)

        print(f"[Brain] 📤 Tool Result: {result[:80]}")
        await self.broadcast_hud({"type": "content", "title": f"TOOL: {name.upper()}", "text": result})
        if types and hasattr(types, "FunctionResponse"):
            return types.FunctionResponse(id=fc.id, name=name, response={"result": result})
        return {"id": fc.id, "name": name, "response": {"result": result}}

    async def run_gemini_session(self):
        if not genai or not types:
            print("[Brain] ⚠️ 'google-genai' library not installed. Install with: pip install google-genai")
            return
        api_key = _get_api_key()
        if not api_key:
            print("[Brain] ⚠️ No GEMINI_API_KEY found. Configure in config/api_keys.json.")
            return

        cfg = _read_config()
        voice_name = cfg.get("gemini_voice") or "Kore"
        asst_name = cfg.get("assistant_name") or "D.O.N.N.A"
        user_name = cfg.get("user_name") or "Сэр"

        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %H:%M")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times and dates.\n\n"
        )
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {asst_name}. "
            f"Always refer to yourself as {asst_name}.\n"
            f"Always address the user as '{user_name}'.\n\n"
        )
        # Injections: Ambient workspace context (active window, process, clipboard)
        ambient_ctx = ""
        try:
            from core.ambient_context import format_ambient_for_prompt
            ambient_ctx = format_ambient_for_prompt()
        except Exception as e:
            print(f"[Brain] Ambient context warning: {e}")

        # Injections: Cortex Knowledge & active tasks summary
        cortex_ctx = ""
        try:
            from memory.cortex_engine import cortex
            cortex_ctx = cortex.get_cortex_summary_for_prompt()
        except Exception as e:
            print(f"[Brain] Cortex context warning: {e}")

        # Injections: OpenClaw skills capabilities
        openclaw_ctx = ""
        try:
            from core.openclaw_engine import openclaw_engine
            openclaw_ctx = openclaw_engine.get_skills_summary_for_prompt()
        except Exception as e:
            print(f"[Brain] OpenClaw context warning: {e}")

        prompt_parts = [time_ctx, identity_ctx]
        if ambient_ctx:
            prompt_parts.append(ambient_ctx)
        if cortex_ctx:
            prompt_parts.append(cortex_ctx)
        if openclaw_ctx:
            prompt_parts.append(openclaw_ctx)
        prompt_parts.append(_load_prompt())

        sys_prompt = "\n".join(prompt_parts)

        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            speech_config=types.SpeechConfig(
                language_code="ru-RU",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            system_instruction=types.Content(parts=[types.Part.from_text(text=sys_prompt)]),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
        )

        reconnect_attempts = 0
        while True:
            try:
                print("[Brain] Connecting to Gemini Live WebSocket...")
                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    self.session = session
                    self.set_state("STANDBY")
                    print("[Brain] 🟢 Connected to Gemini Live.")

                    if not self._briefing_sent and cfg.get("morning_brief_enabled", True):
                        async def _wait_and_brief():
                            # ждём подключения audio_client до 10 секунд
                            for _ in range(100):
                                if self.audio_client is not None:
                                    break
                                await asyncio.sleep(0.1)
                            self._briefing_sent = True
                            await self.send_startup_briefing()
                        asyncio.create_task(_wait_and_brief())

                    async def send_mic_loop():
                        while True:
                            pcm_chunk = await self._in_audio_queue.get()
                            # Anti-lag: drop stale audio backlog if queue size grows (> 20 chunks = ~0.3s)
                            if self._in_audio_queue.qsize() > 20:
                                while self._in_audio_queue.qsize() > 2:
                                    try:
                                        self._in_audio_queue.get_nowait()
                                    except Exception:
                                        break

                            # Send mic audio ONLY when LISTENING and NOT during tool execution (prevents 1008 policy violation)
                            if self.state == "LISTENING" and not getattr(self, "_tool_in_progress", False):
                                try:
                                    await session.send_realtime_input(
                                        audio=types.Blob(data=pcm_chunk, mime_type="audio/pcm;rate=16000")
                                    )
                                except Exception as e:
                                    err_s = str(e)
                                    if "1008" in err_s or "policy violation" in err_s.lower():
                                        print(f"[Brain] Live WebSocket policy/session reset (1008), reconnecting: {e}")
                                    else:
                                        print(f"[Brain] Gemini session dead, forcing reconnect: {e}")
                                        report_exception("gemini_session", e, action="send_audio")
                                    raise  # Trigger outer reconnect loop

                    async def receive_gemini_loop():
                        while True:
                            out_buf, in_buf = [], []
                            async for response in session.receive():
                                # Audio chunks from Gemini Live
                                raw_audio = response.data
                                if not raw_audio and response.server_content and response.server_content.model_turn:
                                    if response.server_content.model_turn.parts:
                                        for part in response.server_content.model_turn.parts:
                                            if part.inline_data and part.inline_data.data:
                                                raw_audio = part.inline_data.data
                                                break

                                if raw_audio:
                                    self.set_state("SPEAKING")
                                    self._speech_done_event.clear()
                                    if self.audio_client:
                                        _SLICE = 2400
                                        for _i in range(0, len(raw_audio), _SLICE):
                                            slice_bytes = raw_audio[_i : _i + _SLICE]
                                            b64 = base64.b64encode(slice_bytes).decode("ascii")
                                            try:
                                                await self.audio_client.send_json({"type": "audio", "data": b64})
                                            except Exception as e:
                                                print(f"[Brain] Error sending audio to AudioService: {e}")
                                                report("WARNING", "audio_playback", str(e))

                                if response.server_content:
                                    sc = response.server_content
                                    if sc.output_transcription and sc.output_transcription.text:
                                        txt = sc.output_transcription.text
                                        if txt and txt != (out_buf[-1] if out_buf else ""):
                                            out_buf.append(txt)

                                    if sc.input_transcription and sc.input_transcription.text:
                                        txt = sc.input_transcription.text
                                        if txt:
                                            in_buf.append(txt)

                                    if sc.turn_complete:
                                        if self._turn_done_event:
                                            self._turn_done_event.set()

                                        full_in = " ".join(in_buf).strip()
                                        if full_in:
                                            await self.broadcast_hud({"type": "log", "speaker": "user", "text": full_in})
                                        in_buf = []

                                        full_out = " ".join(out_buf).strip()
                                        if full_out:
                                            await self.broadcast_hud({"type": "log", "speaker": "jarvis", "text": full_out})
                                        out_buf = []

                                        # If Gemini completed without generating any audio, revert to LISTENING
                                        if self.state != "SPEAKING":
                                            self.wake_up(duration=15.0, reason="Turn Complete No Audio")

                                # Tool Calls
                                tool_call = response.tool_call
                                if tool_call and tool_call.function_calls:
                                    self._tool_in_progress = True
                                    try:
                                        fn_responses = []
                                        for fc in tool_call.function_calls:
                                            fr = await self.dispatch_tool_call(fc)
                                            fn_responses.append(fr)
                                        try:
                                            await session.send_tool_response(function_responses=fn_responses)
                                        except Exception as e:
                                            print(f"[Brain] Error sending tool response: {e}")
                                            report("ERROR", "tool_dispatch", f"Failed to send tool response: {e}")
                                    finally:
                                        self._tool_in_progress = False

                    async def inactivity_watchdog():
                        while True:
                            await asyncio.sleep(1.0)
                            if self.state == "LISTENING" and self._active_until > 0 and time.monotonic() > self._active_until:
                                self.go_to_sleep()

                    gather_task = asyncio.gather(send_mic_loop(), receive_gemini_loop(), inactivity_watchdog())
                    try:
                        await gather_task
                    finally:
                        gather_task.cancel()

            except Exception as e:
                err_s = str(e)
                try:
                    print(f"[Brain] Session connection dropped: {e}. Reconnecting in 3s...")
                except Exception:
                    pass
                if "1008" not in err_s and "policy violation" not in err_s.lower() and not isinstance(e, (BrokenPipeError, OSError)):
                    report_exception("gemini_session", e, model=LIVE_MODEL)
                self.session = None
                self.set_state("STANDBY")
                reconnect_attempts += 1
                backoff_delay = min(2 * (2 ** min(reconnect_attempts, 4)), 30)
                print(f"[Brain] Next reconnect attempt in {backoff_delay}s (attempt {reconnect_attempts})...")
                await asyncio.sleep(backoff_delay)

    async def send_startup_briefing(self):
        """
        Two-phase startup briefing matching monolithic Donna:
          Phase 1 — instant greeting with current time & notification that news is loading
          Phase 2 — news pre-fetched in background, shown on Tactical HUD, and spoken aloud
        """
        # Wait up to 4.0s for Tactical HUD UI to connect so greeting and content are displayed properly
        for _ in range(40):
            if self.hud_clients:
                break
            await asyncio.sleep(0.1)

        await asyncio.sleep(0.3)
        if not self.session:
            return

        cfg = _read_config()
        user_name = cfg.get("user_name", "Сэр")
        asst_name = cfg.get("assistant_name", "D.O.N.N.A")
        now = datetime.now()
        time_str = now.strftime("%H:%M")

        # Fetch news in background task while Phase 1 plays
        async def _fetch_news():
            try:
                res = await bridge.web_search("главные мировые новости сегодня", mode="news")
                if res and not res.startswith("Research agent unavailable") and not res.startswith("Search service error") and len(res) > 50:
                    return res
            except Exception:
                pass
            try:
                from actions.web_search import _news
                return await asyncio.to_thread(_news, "главные мировые новости сегодня")
            except Exception as e:
                print(f"[Brain] Error fetching news: {e}")
                return ""

        news_task = asyncio.create_task(_fetch_news())

        # Check last session summary if available
        session_clause = ""
        try:
            from memory.memory_manager import pop_last_session
            last = await asyncio.to_thread(pop_last_session)
            if last and last.get("summary"):
                session_clause = f" Также кратко и естественно упомяни, что в прошлый раз: {last['summary']}."
        except Exception:
            pass

        # Phase 1: Warm greeting + time + announcement
        p1 = (
            f"[STARTUP_BRIEFING] Поприветствуй пользователя тепло и уважительно. "
            f"Обращайся к нему '{user_name}'. Назови текущее точное время ({time_str}) "
            f"и скажи, что ты сейчас загружаешь для него свежие мировые новости.{session_clause} "
            f"Говори на русском языке. Ответ максимум 2 коротких предложения. Не вызывай никаких инструментов."
        )

        if self._turn_done_event:
            self._turn_done_event.clear()
        self._speech_done_event.clear()

        try:
            self.set_state("THINKING")
            await self.session.send_client_content(
                turns=[types.Content(parts=[types.Part.from_text(text=p1)], role="user")],
                turn_complete=True,
            )
            await self.broadcast_hud({"type": "log", "speaker": "sys", "text": "SYS: Приветствие отправлено (Фаза 1)"})
        except Exception as e:
            print(f"[Brain] Error sending phase 1 briefing: {e}")
            return

        # Phase 2: Await speech finish and deliver news
        async def _deliver_news():
            try:
                # Wait until Donna ACTUALLY finishes speaking Phase 1 through the speakers!
                try:
                    await asyncio.wait_for(self._speech_done_event.wait(), timeout=12.0)
                except asyncio.TimeoutError:
                    pass

                # Brief natural pause between greeting and news delivery
                await asyncio.sleep(0.5)

                try:
                    news_text = await asyncio.wait_for(news_task, timeout=6.0)
                except Exception:
                    news_text = ""

                if not self.session:
                    return

                if news_text and len(news_text) > 40:
                    content_event = {
                        "type": "content",
                        "title": "ГЛАВНЫЕ МИРОВЫЕ НОВОСТИ",
                        "text": news_text,
                    }
                    self._last_content = content_event
                    await self.broadcast_hud(content_event)
                    clean_news = news_text[:650]
                    p2 = (
                        f"[BRIEFING] Сводка сегодняшних мировых новостей:\n{clean_news}\n\n"
                        f"Выбери 1 главную новость и кратко озвучь её в 1 предложении, "
                        f"а затем обязательно скажи: '{user_name}, полный список новостей выведен на экран'. "
                        f"Отвечай только голосом на русском языке. Не вызывай никаких инструментов."
                    )
                else:
                    p2 = (
                        f"Кратко сообщи пользователю '{user_name}', что мировые новости "
                        f"сейчас обновляются, и спроси, чем можешь помочь. Отвечай голосом на русском языке. Не вызывай инструментов."
                    )

                self.set_state("THINKING")
                self._speech_done_event.clear()
                print(f"[Brain] 📰 Sending Phase 2 news briefing ({len(news_text)} chars)...")
                await self.session.send_client_content(
                    turns=[types.Content(parts=[types.Part.from_text(text=p2)], role="user")],
                    turn_complete=True,
                )
                print("[Brain] 🟢 Phase 2 news briefing dispatched.")
                await self.broadcast_hud({"type": "log", "speaker": "sys", "text": "SYS: Сводка новостей отправлена (Фаза 2)"})
            except Exception as e:
                print(f"[Brain] ❌ Phase 2 error: {e}")
                traceback.print_exc()

        asyncio.create_task(_deliver_news())


brain = BrainOrchestrator()


class CommandRequest(BaseModel):
    text: str


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "brain_orchestrator",
        "port": BRAIN_PORT,
        "state": brain.state,
    }


@app.post("/v1/command")
async def api_command(req: CommandRequest):
    if not brain.session:
        raise HTTPException(status_code=503, detail="Gemini Live session not connected")
    try:
        brain.wake_up(duration=15.0, reason="Text Command")
        brain.set_state("THINKING")
        await brain.session.send_client_content(
            turns=[types.Content(parts=[types.Part.from_text(text=req.text)], role="user")],
            turn_complete=True,
        )
        return {"status": "dispatched", "command": req.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/interrupt")
async def api_interrupt():
    brain.wake_up(duration=15.0, reason="Interrupt")
    if brain.session:
        try:
            await brain.session.send_client_content(
                turns=[types.Content(parts=[types.Part.from_text(text="[USER INTERRUPTED - STOP TALKING AND STANDBY]")], role="user")],
                turn_complete=True,
            )
        except Exception:
            pass
    if brain.audio_client:
        try:
            await brain.audio_client.send_json({"type": "interrupt", "phrase": "manual_interrupt"})
        except Exception:
            pass
    await brain.broadcast_hud({"type": "state", "state": "LISTENING"})
    return {"status": "interrupted"}


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    await websocket.accept()
    brain.audio_client = websocket
    print("[Brain] Audio Stream Service connected to /ws/audio.")
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "wake":
                brain.wake_up(duration=15.0, reason=data.get("keyword", "wake word"))
            elif msg_type == "speech_done":
                brain._speech_done_event.set()
                if brain.state == "SPEAKING":
                    brain.wake_up(duration=15.0, reason="Speech Finished")
            elif msg_type == "interrupt":
                brain.wake_up(duration=15.0, reason="Voice Interrupt")
                if brain.session:
                    try:
                        await brain.session.send_client_content(
                            turns=[types.Content(parts=[types.Part.from_text(text="[USER INTERRUPTED - STOP TALKING AND STANDBY]")], role="user")],
                            turn_complete=True,
                        )
                    except Exception:
                        pass
                await brain.broadcast_hud({"type": "state", "state": "LISTENING"})
            elif msg_type == "audio":
                b64 = data.get("data")
                if b64:
                    chunk = base64.b64decode(b64)
                    await brain._in_audio_queue.put(chunk)
                    print(f"[Brain][DEBUG] Received audio chunk, queue size={brain._in_audio_queue.qsize()}")
    except WebSocketDisconnect:
        print("[Brain] Audio Stream Service disconnected.")
        brain.audio_client = None


@app.websocket("/ws/hud")
async def ws_hud(websocket: WebSocket):
    await websocket.accept()
    brain.hud_clients.append(websocket)
    await websocket.send_json({"type": "state", "state": brain.state})
    if brain._last_content:
        try:
            await websocket.send_json(brain._last_content)
        except Exception:
            pass
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in brain.hud_clients:
            brain.hud_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    from shared.port_manager import free_port
    free_port(BRAIN_PORT, "BrainOrchestrator")
    print(f"Starting Brain Orchestrator on {BRAIN_HOST}:{BRAIN_PORT}...")
    uvicorn.run(app, host=BRAIN_HOST, port=BRAIN_PORT)
