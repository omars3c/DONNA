"""
Sentinel Error Tracking Microservice (Port 8006)
Central error collector, incident analyzer, and diagnostic dashboard
for all DONNA microservices.

NOTE: This service does NOT instrument itself with install_sentinel()
to avoid feedback loops.
"""

import sys
import asyncio
import json
import time
import threading
from pathlib import Path
from typing import List, Optional, TypedDict
from contextlib import asynccontextmanager

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests as req_lib
from fastapi import Request, FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from shared.config import SENTINEL_PORT, SENTINEL_HOST, ALLOWED_ORIGINS, verify_internal_token
from shared.models.sentinel import (
    ErrorReport,
    ErrorSeverity,
    ServiceStatusEvent,
)
from services.sentinel_service.store import SentinelStore

# ── Health targets ────────────────────────────────────────────────────────────

class MonitoredService(TypedDict):
    name: str
    url: str
    port: int


MONITORED_SERVICES: list[MonitoredService] = [
    {"name": "channel_gateway_service", "url": "http://127.0.0.1:8000/gateway/health", "port": 8000},
    {"name": "brain_orchestrator",      "url": "http://127.0.0.1:8001/health",         "port": 8001},
    {"name": "cortex_memory_service",   "url": "http://127.0.0.1:8002/health",         "port": 8002},
    {"name": "research_agent_service",  "url": "http://127.0.0.1:8003/health",         "port": 8003},
    {"name": "windows_host_agent",      "url": "http://127.0.0.1:8004/health",         "port": 8004},
    {"name": "audio_stream_service",    "url": "http://127.0.0.1:8005/health",         "port": 8005},
]

# ── Globals ───────────────────────────────────────────────────────────────────

store = SentinelStore()
ws_clients: list[WebSocket] = []
_service_states: dict[str, str] = {}  # service_name -> "UP" | "DOWN"
_health_poller_task: Optional[asyncio.Task] = None
_rotation_task: Optional[asyncio.Task] = None

# ── Dashboard HTML ────────────────────────────────────────────────────────────

_DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _load_dashboard() -> str:
    try:
        return _DASHBOARD_PATH.read_text(encoding="utf-8")
    except Exception:
        return "<html><body><h1>Sentinel Dashboard — file not found</h1></body></html>"


# ── WebSocket broadcast ──────────────────────────────────────────────────────

async def _broadcast_ws(payload: dict):
    dead = []
    data = json.dumps(payload, ensure_ascii=False, default=str)
    for ws in ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)


# ── Health Poller ─────────────────────────────────────────────────────────────

async def _health_poller():
    """Polls /health on all 6 services every 10s. Records state transitions."""
    # Initialize all as unknown
    for svc in MONITORED_SERVICES:
        _service_states[svc["name"]] = "UNKNOWN"

    while True:
        for svc in MONITORED_SERVICES:
            name = svc["name"]
            try:
                resp = await asyncio.to_thread(
                    req_lib.get, svc["url"], timeout=2
                )
                new_status = "UP" if resp.status_code == 200 else "DOWN"
            except Exception:
                new_status = "DOWN"

            old_status = _service_states.get(name, "UNKNOWN")

            if old_status != new_status and old_status != "UNKNOWN":
                # State transition — record it
                now = time.time()
                event = ServiceStatusEvent(
                    service=name,
                    status=new_status,
                    ts=now,
                    detail=f"{name} went {old_status} → {new_status}",
                )
                store.insert_status(event)

                # Also create a synthetic error record
                sev = ErrorSeverity.CRITICAL if new_status == "DOWN" else ErrorSeverity.INFO
                msg = f"{name} went {new_status}" if new_status == "DOWN" else f"{name} recovered (UP)"
                report = ErrorReport(
                    service=name,
                    severity=sev,
                    source="health_monitor",
                    message=msg,
                    ts=now,
                )
                record = store.insert_error(report)
                await _broadcast_ws({
                    "type": "error",
                    "record": record.model_dump(),
                })
                await _broadcast_ws({
                    "type": "status",
                    "service": name,
                    "status": new_status,
                    "ts": now,
                })
                print(f"[Sentinel] ⚡ {name}: {old_status} → {new_status}")

            _service_states[name] = new_status

        await asyncio.sleep(10)


async def _rotation_worker():
    """Run store rotation every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            store.rotate()
            print("[Sentinel] 🗑️ Rotation complete.")
        except Exception as e:
            print(f"[Sentinel] Rotation error: {e}")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _health_poller_task, _rotation_task
    _health_poller_task = asyncio.create_task(_health_poller())
    _rotation_task = asyncio.create_task(_rotation_worker())
    print(f"[Sentinel] 🟢 Health poller and rotation worker started.")
    yield
    if _health_poller_task:
        _health_poller_task.cancel()
    if _rotation_task:
        _rotation_task.cancel()
    store.close()


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="DONNA Sentinel",
    description="Centralized Error Tracking, Incident Analysis, and Diagnostic Dashboard",
    version="1.0.0",
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



# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "sentinel_service",
        "port": SENTINEL_PORT,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=_load_dashboard(), status_code=200)


@app.post("/v1/errors")
async def post_error(report: ErrorReport):
    record = store.insert_error(report)
    await _broadcast_ws({"type": "error", "record": record.model_dump()})
    return {"status": "ok", "id": record.id}


@app.post("/v1/errors/batch")
async def post_error_batch(reports: List[ErrorReport]):
    records = store.insert_error_batch(reports)
    for rec in records:
        await _broadcast_ws({"type": "error", "record": rec.model_dump()})
    return {"status": "ok", "count": len(records)}


@app.get("/v1/errors")
def get_errors(
    service: Optional[str] = None,
    severity: Optional[str] = None,
    since: Optional[float] = None,
    correlation_id: Optional[str] = None,
    incident_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=200, le=1000),
    group: bool = False,
):
    results = store.query_errors(
        service=service,
        severity=severity,
        since=since,
        correlation_id=correlation_id,
        incident_id=incident_id,
        search=search,
        limit=limit,
        group=group,
    )
    if group:
        return {"errors": results, "count": len(results)}
    return {
        "errors": [r.model_dump() for r in results],
        "count": len(results),
    }


@app.get("/v1/incidents")
def get_incidents(limit: int = Query(default=50, le=200)):
    incidents = store.get_incidents(limit=limit)
    return {
        "incidents": [i.model_dump() for i in incidents],
        "count": len(incidents),
    }


@app.get("/v1/incidents/{incident_id}")
def get_incident(incident_id: str):
    result = store.get_incident(incident_id)
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Incident not found"})
    return result


@app.get("/v1/trace/{correlation_id}")
def get_trace(correlation_id: str):
    records = store.get_trace(correlation_id)
    return {
        "correlation_id": correlation_id,
        "events": [r.model_dump() for r in records],
        "count": len(records),
    }


@app.get("/v1/stats")
def get_stats(window: int = Query(default=3600, le=86400)):
    stats = store.get_stats(window_sec=window)
    # Merge live poller statuses
    for svc in MONITORED_SERVICES:
        name = svc["name"]
        if name not in stats["service_statuses"]:
            stats["service_statuses"][name] = {
                "status": _service_states.get(name, "UNKNOWN"),
                "ts": time.time(),
            }
        else:
            # Override with live poller state
            current_svc_stat = stats["service_statuses"][name]
            fallback_status = str(current_svc_stat.get("status", "UNKNOWN")) if isinstance(current_svc_stat, dict) else "UNKNOWN"
            stats["service_statuses"][name]["status"] = _service_states.get(name, fallback_status)
    return stats


@app.delete("/v1/errors")
def delete_errors():
    store.clear_all()
    return {"status": "cleared"}


@app.websocket("/ws/errors")
async def ws_errors(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        # Send current service states immediately
        for svc in MONITORED_SERVICES:
            name = svc["name"]
            await websocket.send_text(json.dumps({
                "type": "status",
                "service": name,
                "status": _service_states.get(name, "UNKNOWN"),
                "ts": time.time(),
            }, ensure_ascii=False))
        while True:
            # Keep connection alive, ignore incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Sentinel Service on {SENTINEL_HOST}:{SENTINEL_PORT}...")
    uvicorn.run(app, host=SENTINEL_HOST, port=SENTINEL_PORT)
