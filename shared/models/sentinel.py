"""
Shared Pydantic models for DONNA Sentinel error tracking service.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ErrorSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ErrorReport(BaseModel):
    """Payload sent by services to Sentinel."""
    service: str
    severity: ErrorSeverity
    source: str
    message: str
    traceback: Optional[str] = None
    correlation_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    ts: float


class ErrorRecord(BaseModel):
    """Stored error record returned by Sentinel API."""
    id: int
    service: str
    severity: ErrorSeverity
    source: str
    message: str
    traceback: Optional[str] = None
    correlation_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    ts: float
    received_ts: float
    fingerprint: str
    incident_id: Optional[str] = None


class ServiceStatusEvent(BaseModel):
    """Health-poller state change event."""
    service: str
    status: str  # "UP" | "DOWN"
    ts: float
    detail: Optional[str] = None


class IncidentSummary(BaseModel):
    """Grouped incident summary."""
    incident_id: str
    started_ts: float
    ended_ts: Optional[float] = None
    services: List[str] = Field(default_factory=list)
    root_cause: Optional[ErrorRecord] = None
    error_count: int = 0
    severity: ErrorSeverity = ErrorSeverity.ERROR
