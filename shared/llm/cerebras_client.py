"""
Cerebras text LLM client (OpenAI-compatible Chat Completions API).

Scope: secondary TEXT provider for tests and background text jobs
(research summarisation, Sentinel log triage, ...). It is NOT used by the
Gemini Live voice pipeline.

Deliberately no automatic retry / key rotation / provider fallback here:
callers get explicit, typed exceptions so a rotation layer can be added later.

Usage:
    from shared.llm import CerebrasClient, CerebrasRateLimitError

    client = CerebrasClient()                     # key from env / api_keys.json
    resp = await client.generate([
        {"role": "system", "content": "You are DONNA."},
        {"role": "user", "content": "Привет"},
    ])
    print(resp.text, resp.total_tokens, resp.latency_s)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from shared.config import API_KEYS_PATH

logger = logging.getLogger("DonnaCerebras")

CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"

# Default: high quota (450 req/min, ~1.08B tokens/day), ctx 131072, max completion 40960.
CEREBRAS_DEFAULT_MODEL = "qwen-3.8-27b"
# Manual tests only: same ctx, but just 5 req/min / 2400 req/day. Never use as default.
CEREBRAS_FALLBACK_MODEL = "gpt-oss-120b"

DEFAULT_TIMEOUT_S = 60.0


# ── Exceptions ────────────────────────────────────────────────────────────────

class CerebrasError(Exception):
    """Base error for any Cerebras provider failure (network, HTTP, malformed body)."""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 model: Optional[str] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.model = model
        self.body = body


class CerebrasRateLimitError(CerebrasError):
    """HTTP 429 — quota / rate limit hit. `retry_after` in seconds if the server sent it."""

    def __init__(self, message: str, retry_after: Optional[float] = None, **kw: Any):
        super().__init__(message, **kw)
        self.retry_after = retry_after


class CerebrasAuthError(CerebrasError):
    """Missing API key, or HTTP 401/403."""


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class CerebrasResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: Optional[str] = None
    latency_s: float = 0.0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


# ── Key resolution (same order as core/model_pool.py: env, then api_keys.json) ──

def get_cerebras_api_key() -> str:
    env_key = os.environ.get("CEREBRAS_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        if API_KEYS_PATH.exists():
            data = json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
            return str(data.get("cerebras_api_key", "") or "").strip()
    except Exception as e:
        logger.error(f"[Cerebras] Failed to read key from {API_KEYS_PATH}: {e}")
    return ""


def _report(level: str, message: str, context: Dict[str, Any]) -> None:
    """Forward to Sentinel; error_reporter itself never raises, but guard the import."""
    try:
        from shared.error_reporter import report
        report(level, "cerebras_client", message, context=context)
    except Exception:
        pass


# ── Client ────────────────────────────────────────────────────────────────────

class CerebrasClient:
    def __init__(self, api_key: Optional[str] = None,
                 model: str = CEREBRAS_DEFAULT_MODEL,
                 base_url: str = CEREBRAS_BASE_URL,
                 timeout: float = DEFAULT_TIMEOUT_S):
        self.api_key = (api_key or get_cerebras_api_key()).strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def generate(self, messages: List[Dict[str, Any]], *,
                       model: Optional[str] = None,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None,
                       tools: Optional[List[Dict[str, Any]]] = None,
                       extra: Optional[Dict[str, Any]] = None) -> CerebrasResponse:
        """Non-streaming chat completion. Raises CerebrasError subclasses on failure."""
        use_model = model or self.model
        if not self.api_key:
            msg = "CEREBRAS_API_KEY is not set (env or config/api_keys.json: cerebras_api_key)"
            logger.error(f"[Cerebras] {msg}")
            raise CerebrasAuthError(msg, model=use_model)

        payload: Dict[str, Any] = {"model": use_model, "messages": messages, "stream": False}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if extra:
            payload.update(extra)

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                resp = await http.post(url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            msg = f"Network error calling Cerebras ({type(e).__name__}): {e}"
            logger.error(f"[Cerebras] {msg}")
            _report("ERROR", msg, {"model": use_model})
            raise CerebrasError(msg, model=use_model) from e
        latency = time.perf_counter() - t0

        if resp.status_code != 200:
            self._raise_for_status(resp, use_model)

        try:
            data = resp.json()
            choice = data["choices"][0]
            message = choice.get("message") or {}
        except (ValueError, KeyError, IndexError, TypeError) as e:
            msg = f"Malformed Cerebras response: {e}"
            logger.error(f"[Cerebras] {msg}; body={resp.text[:500]}")
            _report("ERROR", msg, {"model": use_model})
            raise CerebrasError(msg, status_code=resp.status_code, model=use_model,
                                body=resp.text[:2000]) from e

        usage = data.get("usage") or {}
        return CerebrasResponse(
            text=message.get("content") or "",
            model=data.get("model", use_model),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
            finish_reason=choice.get("finish_reason"),
            latency_s=latency,
            tool_calls=message.get("tool_calls") or [],
            raw=data,
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response, model: str) -> None:
        body = resp.text[:2000]
        try:
            err = resp.json().get("message") or resp.json().get("error") or body
        except Exception:
            err = body
        status = resp.status_code
        ctx = {"model": model, "status": status}

        if status == 429:
            retry_after: Optional[float] = None
            ra = resp.headers.get("retry-after")
            if ra:
                try:
                    retry_after = float(ra)
                except ValueError:
                    pass
            msg = f"Cerebras rate limit (429) for model {model}: {err}"
            logger.warning(f"[Cerebras] {msg} retry_after={retry_after}")
            _report("WARNING", msg, {**ctx, "retry_after": retry_after})
            raise CerebrasRateLimitError(msg, retry_after=retry_after,
                                         status_code=status, model=model, body=body)
        if status in (401, 403):
            msg = f"Cerebras auth error ({status}): {err}"
            logger.error(f"[Cerebras] {msg}")
            _report("ERROR", msg, ctx)
            raise CerebrasAuthError(msg, status_code=status, model=model, body=body)

        msg = f"Cerebras API error ({status}) for model {model}: {err}"
        logger.error(f"[Cerebras] {msg}")
        _report("ERROR", msg, ctx)
        raise CerebrasError(msg, status_code=status, model=model, body=body)
