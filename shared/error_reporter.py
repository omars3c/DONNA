"""
DONNA Sentinel — Client Error Reporter Library

Fire-and-forget error reporting from any DONNA microservice to Sentinel.
This module MUST NEVER raise exceptions to the caller or block the calling thread.

Usage in any service:
    from shared.error_reporter import install_sentinel
    install_sentinel(app, "brain_orchestrator")    # that's it

Manual reporting:
    from shared.error_reporter import report, report_exception
    report("ERROR", "gemini_session", "Session dropped", context={"model": "live"})
    report_exception("tool_dispatch", exc, context={"tool": "web_search"})
"""

import atexit
import contextvars
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback as tb_module
import uuid
from pathlib import Path
from typing import Any, Optional

# ── Lazy import to avoid circular deps at module level ──
_config_loaded = False
_sentinel_url = "http://127.0.0.1:8006"
_sentinel_enabled = True

def _ensure_config():
    global _config_loaded, _sentinel_url, _sentinel_enabled
    if _config_loaded:
        return
    try:
        from shared.config import SENTINEL_SERVICE_URL, SENTINEL_ENABLED
        _sentinel_url = SENTINEL_SERVICE_URL
        _sentinel_enabled = SENTINEL_ENABLED
    except Exception:
        pass
    _config_loaded = True


# ── Module state ──
_service_name: str = "unknown"
_initialized: bool = False
_queue: queue.Queue = queue.Queue(maxsize=1000)
_worker_thread: Optional[threading.Thread] = None
_shutdown_event = threading.Event()
_correlation_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("donna_correlation_id", default=None)
_BASE_DIR = Path(__file__).resolve().parent.parent
_FALLBACK_DIR = _BASE_DIR / "logs"
_FALLBACK_PATH = _FALLBACK_DIR / "sentinel_fallback.jsonl"

# Guard against recursion in logging handler
_REPORTER_LOGGER_NAMES = frozenset({
    "shared.error_reporter",
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "requests.adapters",
    "httpx",
    "httpcore",
    "httpcore.http11",
    "httpcore.connection",
    "uvicorn.error",
})
_in_reporter = threading.local()


# ── Public API ────────────────────────────────────────────────────────────────

def init_reporter(service_name: str) -> None:
    """Initialize the reporter for a given service. Safe to call multiple times."""
    global _service_name, _initialized, _worker_thread
    _service_name = service_name
    _ensure_config()

    if _initialized:
        return
    _initialized = True

    try:
        _FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    _worker_thread = threading.Thread(target=_sender_loop, name="sentinel-reporter", daemon=True)
    _worker_thread.start()


def report(
    severity: str,
    source: str,
    message: str,
    exc: Optional[BaseException] = None,
    correlation_id: Optional[str] = None,
    **context: Any,
) -> None:
    """Report an error/warning to Sentinel. Never raises, never blocks."""
    try:
        _ensure_config()
        if not _sentinel_enabled:
            return

        cid = correlation_id or get_correlation_id()
        tb_str = None
        if exc:
            try:
                tb_str = "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
            except Exception:
                tb_str = str(exc)

        payload = {
            "service": _service_name,
            "severity": severity,
            "source": source,
            "message": message[:4000],
            "traceback": tb_str[:8000] if tb_str else None,
            "correlation_id": cid,
            "context": context if context else None,
            "ts": time.time(),
        }

        try:
            _queue.put_nowait(payload)
        except queue.Full:
            # Drop oldest to make room
            try:
                _queue.get_nowait()
            except queue.Empty:
                pass
            try:
                _queue.put_nowait(payload)
            except Exception:
                pass
    except Exception:
        pass


def report_exception(
    source: str,
    exc: BaseException,
    correlation_id: Optional[str] = None,
    **context: Any,
) -> None:
    """Report an exception with auto-extracted traceback. Never raises."""
    try:
        severity = "CRITICAL" if isinstance(exc, (SystemExit, KeyboardInterrupt, MemoryError)) else "ERROR"
        report(severity, source, str(exc), exc=exc, correlation_id=correlation_id, **context)
    except Exception:
        pass


def set_correlation_id(cid: str) -> None:
    try:
        _correlation_var.set(cid)
    except Exception:
        pass


def get_correlation_id() -> Optional[str]:
    try:
        return _correlation_var.get()
    except Exception:
        return None


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex[:16]
    set_correlation_id(cid)
    return cid


def donna_headers() -> dict:
    """Returns headers dict with current correlation ID for inter-service HTTP calls."""
    cid = get_correlation_id()
    if cid:
        return {"X-Donna-Correlation-ID": cid}
    return {}


# ── install_sentinel — the "2 lines" integration ─────────────────────────────

def install_sentinel(app, service_name: str) -> None:
    """
    Instrument a FastAPI app with full Sentinel integration:
    - HTTP middleware (correlation ID, exception catching, 5xx reporting)
    - sys.excepthook / threading.excepthook
    - asyncio exception handler
    - Logging handler (WARNING+)
    - Startup/shutdown lifecycle events
    """
    init_reporter(service_name)

    _ensure_config()
    if not _sentinel_enabled:
        return

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    # ── 1. HTTP Middleware ──

    class SentinelMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Read or generate correlation ID
            cid = request.headers.get("X-Donna-Correlation-ID") or uuid.uuid4().hex[:16]
            _correlation_var.set(cid)

            try:
                response = await call_next(request)
            except Exception as exc:
                # Report CRITICAL but re-raise
                report_exception("http_unhandled", exc, correlation_id=cid,
                                 method=request.method, path=request.url.path)
                raise

            # Report 5xx responses
            if response.status_code >= 500:
                report("ERROR", "http_5xx",
                       f"{request.method} {request.url.path} → {response.status_code}",
                       correlation_id=cid)

            response.headers["X-Donna-Correlation-ID"] = cid
            return response

    app.add_middleware(SentinelMiddleware)

    # ── 2. sys.excepthook ──
    _original_excepthook = sys.excepthook

    def _sentinel_excepthook(exc_type, exc_value, exc_tb):
        try:
            tb_str = "".join(tb_module.format_exception(exc_type, exc_value, exc_tb))
            report("CRITICAL", "unhandled_exception", str(exc_value), exc=exc_value)
        except Exception:
            pass
        if _original_excepthook:
            _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _sentinel_excepthook

    # ── 3. threading.excepthook ──
    _original_threading_excepthook = getattr(threading, "excepthook", None)

    def _sentinel_threading_excepthook(args):
        try:
            report("CRITICAL", "thread_exception",
                   f"Unhandled in thread '{args.thread.name if args.thread else '?'}': {args.exc_value}",
                   exc=args.exc_value)
        except Exception:
            pass
        if _original_threading_excepthook:
            _original_threading_excepthook(args)

    threading.excepthook = _sentinel_threading_excepthook

    # ── 4. Logging Handler ──

    class SentinelLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord):
            # Guard against recursion
            if getattr(_in_reporter, "active", False):
                return
            if record.name in _REPORTER_LOGGER_NAMES:
                return
            # Also skip if any parent logger matches
            parts = record.name.split(".")
            for i in range(len(parts)):
                if ".".join(parts[:i+1]) in _REPORTER_LOGGER_NAMES:
                    return

            try:
                _in_reporter.active = True
                sev = "WARNING"
                if record.levelno >= logging.CRITICAL:
                    sev = "CRITICAL"
                elif record.levelno >= logging.ERROR:
                    sev = "ERROR"

                msg = record.getMessage()
                tb_str = None
                if record.exc_info and record.exc_info[1]:
                    tb_str = "".join(tb_module.format_exception(*record.exc_info))

                report(sev, f"log:{record.name}", msg[:2000], correlation_id=get_correlation_id())
            except Exception:
                pass
            finally:
                _in_reporter.active = False

    handler = SentinelLogHandler()
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)

    # ── 5. Startup / Shutdown events + asyncio exception handler ──

    @app.on_event("startup")
    async def _sentinel_startup():
        report("INFO", "lifecycle", f"{service_name} started")
        # Set asyncio exception handler
        try:
            import asyncio
            loop = asyncio.get_running_loop()

            def _asyncio_exc_handler(loop, context):
                exc = context.get("exception")
                msg = context.get("message", "asyncio exception")
                if exc:
                    report_exception("asyncio_unhandled", exc)
                else:
                    report("ERROR", "asyncio_unhandled", msg)
                # Call default handler too
                loop.default_exception_handler(context)

            loop.set_exception_handler(_asyncio_exc_handler)
        except Exception:
            pass

    @app.on_event("shutdown")
    async def _sentinel_shutdown():
        report("INFO", "lifecycle", f"{service_name} shutting down")


# ── Background sender loop ───────────────────────────────────────────────────

def _sender_loop():
    """Background daemon thread: batches payloads and sends to Sentinel."""
    import requests as req_lib

    while not _shutdown_event.is_set():
        try:
            batch = []
            # Block up to 0.5s for the first item
            try:
                item = _queue.get(timeout=0.5)
                batch.append(item)
            except queue.Empty:
                _try_resend_fallback(req_lib)
                continue

            # Drain up to 49 more items without blocking
            while len(batch) < 50:
                try:
                    batch.append(_queue.get_nowait())
                except queue.Empty:
                    break

            # Send batch
            try:
                _in_reporter.active = True
                resp = req_lib.post(
                    f"{_sentinel_url}/v1/errors/batch",
                    json=batch,
                    timeout=2,
                )
                if resp.status_code == 200:
                    _try_resend_fallback(req_lib)
                else:
                    _write_fallback(batch)
            except Exception:
                _write_fallback(batch)
            finally:
                _in_reporter.active = False

        except Exception:
            # Top-level catch: reporter must never crash
            pass


def _write_fallback(batch: list):
    """Write failed payloads to fallback JSONL file."""
    try:
        with open(_FALLBACK_PATH, "a", encoding="utf-8") as f:
            for item in batch:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _try_resend_fallback(req_lib):
    """If fallback file exists, try to resend its contents."""
    try:
        if not _FALLBACK_PATH.exists() or _FALLBACK_PATH.stat().st_size == 0:
            return

        lines = _FALLBACK_PATH.read_text(encoding="utf-8").strip().split("\n")
        if not lines:
            return

        batch = []
        for line in lines:
            try:
                batch.append(json.loads(line))
            except Exception:
                continue

        if not batch:
            _FALLBACK_PATH.write_text("", encoding="utf-8")
            return

        # Send in chunks of 50
        for i in range(0, len(batch), 50):
            chunk = batch[i:i+50]
            try:
                _in_reporter.active = True
                resp = req_lib.post(
                    f"{_sentinel_url}/v1/errors/batch",
                    json=chunk,
                    timeout=2,
                )
                if resp.status_code != 200:
                    return  # Stop trying, will retry later
            except Exception:
                return
            finally:
                _in_reporter.active = False

        # All sent successfully, clear fallback
        _FALLBACK_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass
