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
