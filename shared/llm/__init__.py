"""
Text-only LLM provider clients shared across DONNA microservices.

NOTE: The realtime voice channel (Gemini Live in brain_orchestrator) does NOT
use this package and must stay independent of it.
"""

from shared.llm.cerebras_client import (
    CEREBRAS_BASE_URL,
    CEREBRAS_DEFAULT_MODEL,
    CEREBRAS_FALLBACK_MODEL,
    CerebrasAuthError,
    CerebrasClient,
    CerebrasError,
    CerebrasRateLimitError,
    CerebrasResponse,
    get_cerebras_api_key,
)

__all__ = [
    "CEREBRAS_BASE_URL",
    "CEREBRAS_DEFAULT_MODEL",
    "CEREBRAS_FALLBACK_MODEL",
    "CerebrasAuthError",
    "CerebrasClient",
    "CerebrasError",
    "CerebrasRateLimitError",
    "CerebrasResponse",
    "get_cerebras_api_key",
]
