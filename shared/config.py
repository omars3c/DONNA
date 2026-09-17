"""
Configuration settings and service endpoints for DONNA Microservices.
"""

import os
from pathlib import Path
from typing import List
from fastapi import Request, HTTPException

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
API_KEYS_PATH = CONFIG_DIR / "api_keys.json"

# Service Ports & Hosts
BRAIN_HOST = os.getenv("DONNA_BRAIN_HOST", "127.0.0.1")
BRAIN_PORT = int(os.getenv("DONNA_BRAIN_PORT", "8001"))

CORTEX_HOST = os.getenv("DONNA_CORTEX_HOST", "127.0.0.1")
CORTEX_PORT = int(os.getenv("DONNA_CORTEX_PORT", "8002"))

RESEARCH_HOST = os.getenv("DONNA_RESEARCH_HOST", "127.0.0.1")
RESEARCH_PORT = int(os.getenv("DONNA_RESEARCH_PORT", "8003"))

HOST_AGENT_HOST = os.getenv("DONNA_HOST_AGENT_HOST", "127.0.0.1")
HOST_AGENT_PORT = int(os.getenv("DONNA_HOST_AGENT_PORT", "8004"))

AUDIO_HOST = os.getenv("DONNA_AUDIO_HOST", "127.0.0.1")
AUDIO_PORT = int(os.getenv("DONNA_AUDIO_PORT", "8005"))

CHANNEL_GATEWAY_HOST = os.getenv("DONNA_CHANNEL_HOST", "127.0.0.1")
CHANNEL_GATEWAY_PORT = int(os.getenv("DONNA_CHANNEL_PORT", "8000"))

SENTINEL_HOST = os.getenv("DONNA_SENTINEL_HOST", "127.0.0.1")
SENTINEL_PORT = int(os.getenv("DONNA_SENTINEL_PORT", "8006"))
SENTINEL_ENABLED = os.getenv("DONNA_SENTINEL_ENABLED", "1") == "1"

# Service URLs
BRAIN_SERVICE_URL = f"http://{BRAIN_HOST}:{BRAIN_PORT}"
CORTEX_SERVICE_URL = f"http://{CORTEX_HOST}:{CORTEX_PORT}"
RESEARCH_SERVICE_URL = f"http://{RESEARCH_HOST}:{RESEARCH_PORT}"
HOST_AGENT_SERVICE_URL = f"http://{HOST_AGENT_HOST}:{HOST_AGENT_PORT}"
AUDIO_SERVICE_URL = f"http://{AUDIO_HOST}:{AUDIO_PORT}"
CHANNEL_GATEWAY_SERVICE_URL = f"http://{CHANNEL_GATEWAY_HOST}:{CHANNEL_GATEWAY_PORT}"
SENTINEL_SERVICE_URL = f"http://{SENTINEL_HOST}:{SENTINEL_PORT}"

AUTONOMOUS_HOST = os.getenv("DONNA_AUTONOMOUS_HOST", "127.0.0.1")
AUTONOMOUS_PORT = int(os.getenv("DONNA_AUTONOMOUS_PORT", "8007"))
AUTONOMOUS_SERVICE_URL = f"http://{AUTONOMOUS_HOST}:{AUTONOMOUS_PORT}"

# Security & CORS Configuration
ALLOWED_ORIGINS: List[str] = [
    f"http://127.0.0.1:{CHANNEL_GATEWAY_PORT}",
    f"http://localhost:{CHANNEL_GATEWAY_PORT}",
    f"http://{CHANNEL_GATEWAY_HOST}:{CHANNEL_GATEWAY_PORT}",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]

INTERNAL_TOKEN_HEADER = "X-Donna-Internal-Token"
INTERNAL_API_TOKEN = os.getenv("DONNA_INTERNAL_TOKEN", "")


async def verify_internal_token(request: Request):
    """
    Verifies inter-service call authenticity.
    If DONNA_INTERNAL_TOKEN is set in environment, incoming requests
    must provide the matching X-Donna-Internal-Token header.
    Health checks, docs, and public dashboard endpoints are allowed.
    """
    path = request.url.path
    if path in ("/health", "/docs", "/openapi.json", "/", "/redoc", "/gateway/health"):
        return True

    if not INTERNAL_API_TOKEN:
        return True

    token = request.headers.get(INTERNAL_TOKEN_HEADER)
    if not token or token != INTERNAL_API_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Invalid or missing X-Donna-Internal-Token header",
        )
    return True
