"""Models for Windows Host Agent: OS control, apps, settings, screen, telemetry."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class OSActionRequest(BaseModel):
    action: str  # click | double_click | right_click | type_text | hotkey | scroll | key_press
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    keys: Optional[str] = None
    direction: Optional[str] = "down"
    amount: Optional[int] = 3


class AppLaunchRequest(BaseModel):
    app_name: str
    # Set to True when this call follows an AMBIGUOUS_BROWSER response, i.e. the
    # user explicitly chose this browser — so it should be saved as the default.
    pending_disambiguation: bool = False


class OSSettingsRequest(BaseModel):
    action: str  # volume_set | volume_mute | volume_up | volume_down | brightness_set | close_app | wifi_toggle | list_processes
    value: Optional[Any] = None
    app_name: Optional[str] = None


class TelemetryResponse(BaseModel):
    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    gpu_percent: Optional[float] = None
    gpu_memory_used_gb: Optional[float] = None
    gpu_name: Optional[str] = None
    cpu_temp: Optional[float] = None
    battery_percent: Optional[float] = None
    battery_plugged: Optional[bool] = None
    network_sent_mb: Optional[float] = None
    network_recv_mb: Optional[float] = None


class GenericResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


class BrowserActionRequest(BaseModel):
    action: str = "open"  # open | close | close_all | switch | list_browsers | navigate | new_tab | close_tab | click | type | scroll | etc.
    browser: Optional[str] = None
    url: Optional[str] = None
    target: Optional[str] = None
    query: Optional[str] = None
    engine: Optional[str] = "google"
    selector: Optional[str] = None
    text: Optional[str] = None
    clear_first: Optional[bool] = True
    direction: Optional[str] = "down"
    amount: Optional[int] = 500
    fields: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    key: Optional[str] = "Enter"
    path: Optional[str] = None

    model_config = {"extra": "allow"}


class ReminderActionRequest(BaseModel):
    action: str = "set"  # set | list | cancel | cancel_all
    date: Optional[str] = None
    time: Optional[str] = None
    message: Optional[str] = None
    query: Optional[str] = None
    reminder_id: Optional[str] = None

    model_config = {"extra": "allow"}

