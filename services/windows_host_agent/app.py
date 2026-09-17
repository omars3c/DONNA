"""
Windows Host Agent Microservice (Port 8004)
Runs natively as a Windows daemon to provide direct OS control, mouse/keyboard automation,
application launching, screen/webcam capture, and hardware telemetry.
"""

import sys
import base64
from pathlib import Path
from typing import Optional, Dict, Any

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import Request, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from shared.models.os_control import (
    OSActionRequest,
    AppLaunchRequest,
    OSSettingsRequest,
    GenericResponse,
)
from shared.config import HOST_AGENT_PORT, HOST_AGENT_HOST, ALLOWED_ORIGINS, verify_internal_token

from actions.computer_control import computer_control
from actions.computer_settings import computer_settings
from actions.open_app import open_app
from actions.screen_capture import _capture_screen, _capture_camera
from actions.system_monitor import get_system_status, SystemMonitor

app = FastAPI(
    title="DONNA Windows Host Agent",
    description="Native OS Automation, Win32 Bridge, and Telemetry Daemon",
    version="2.0.0",
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


_monitor = SystemMonitor()

from shared.error_reporter import install_sentinel
install_sentinel(app, "windows_host_agent")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "windows_host_agent",
        "port": HOST_AGENT_PORT,
    }


@app.post("/v1/os/control", response_model=GenericResponse)
def api_computer_control(req: OSActionRequest):
    try:
        params = {
            "action": req.action,
            "x": req.x,
            "y": req.y,
            "text": req.text,
            "keys": req.keys,
            "direction": req.direction,
            "amount": req.amount,
        }
        res_text = computer_control(parameters=params)
        return GenericResponse(success=True, message=res_text or "Done")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/os/launch-app", response_model=GenericResponse)
def api_launch_app(req: AppLaunchRequest):
    try:
        params = {
            "app_name": req.app_name,
            "pending_disambiguation": req.pending_disambiguation,
        }
        res_text = open_app(parameters=params)
        failed = (
            res_text.startswith("Failed to open")
            or res_text.startswith("Could not confirm")
            or res_text.startswith("Started a launch attempt")
            or res_text.startswith("AMBIGUOUS_BROWSER")
            or not res_text.startswith("Opened ")
        )
        return GenericResponse(success=not failed, message=res_text or f"Launched {req.app_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/os/settings", response_model=GenericResponse)
def api_computer_settings(req: OSSettingsRequest):
    try:
        params = {
            "action": req.action,
            "value": req.value,
            "app_name": req.app_name,
        }
        res_text = computer_settings(parameters=params)
        return GenericResponse(success=True, message=res_text or "Setting adjusted")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/os/telemetry")
def api_get_telemetry():
    try:
        return get_system_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/os/check-alerts")
def api_check_alerts():
    try:
        alert = _monitor.check()
        return {"alert": alert}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/os/screenshot")
def api_capture_screenshot(format: str = "binary"):
    try:
        img_bytes, mime_type = _capture_screen()
        if format == "base64":
            b64_str = base64.b64encode(img_bytes).decode("ascii")
            return {"mime_type": mime_type, "data_b64": b64_str}
        return Response(content=img_bytes, media_type=mime_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/os/camera")
def api_capture_camera(format: str = "binary"):
    try:
        img_bytes, mime_type = _capture_camera()
        if format == "base64":
            b64_str = base64.b64encode(img_bytes).decode("ascii")
            return {"mime_type": mime_type, "data_b64": b64_str}
        return Response(content=img_bytes, media_type=mime_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Windows Host Agent on {HOST_AGENT_HOST}:{HOST_AGENT_PORT}...")
    uvicorn.run(app, host=HOST_AGENT_HOST, port=HOST_AGENT_PORT)
