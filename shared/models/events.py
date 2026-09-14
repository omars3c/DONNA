"""Shared event and streaming models."""

from typing import Optional, Dict, Any
from pydantic import BaseModel


class HUDStateEvent(BaseModel):
    state: str  # SLEEPING | STANDBY | LISTENING | THINKING | SPEAKING | MUTED
    details: Optional[str] = ""


class LogMessageEvent(BaseModel):
    level: str = "SYS"  # SYS | NET | ERR | AI | TOOL
    message: str
    source: Optional[str] = "SYSTEM"


class AudioPacket(BaseModel):
    data_b64: str
    sample_rate: int = 16000
    channels: int = 1
