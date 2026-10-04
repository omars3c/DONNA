"""
Ручная проверка интеграции Cerebras (текстовый провайдер).

Отправляет в Cerebras РЕАЛЬНЫЙ system-промпт DONNA — собранный из тех же
источников и в том же порядке, что и в services/brain_orchestrator/app.py
(время, identity, ambient, cortex, openclaw, core/prompt.txt) — плюс тестовый
вопрос. Печатает латентность, токены и ответ.

Gemini Live / brain_orchestrator НЕ импортируется и НЕ изменяется.

Запуск:
    uv run python scripts/cerebras_check.py
    uv run python scripts/cerebras_check.py --with-tools          # + 17 tool-описаний DONNA
    uv run python scripts/cerebras_check.py --model gpt-oss-120b  # ручной тест запасной модели
    uv run python scripts/cerebras_check.py -q "Кратко: что ты умеешь?"

Ключ: переменная окружения CEREBRAS_API_KEY или config/api_keys.json → cerebras_api_key.
Код выхода: 0 — успех, 1 — ошибка провайдера, 2 — rate limit (429).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.config import API_KEYS_PATH  # noqa: E402
from shared.llm import (  # noqa: E402
    CEREBRAS_DEFAULT_MODEL,
    CerebrasClient,
    CerebrasError,
    CerebrasRateLimitError,
)

CONTEXT_WINDOW = 131072
PROMPT_PATH = ROOT / "core" / "prompt.txt"
DEFAULT_QUESTION = "Представься в двух предложениях и скажи, какие задачи ты можешь выполнять."


def build_donna_system_prompt() -> str:
    """Mirror of BrainOrchestrator.run_gemini_session prompt assembly (keep in sync)."""
    try:
        cfg = json.loads(API_KEYS_PATH.read_text(encoding="utf-8")) if API_KEYS_PATH.exists() else {}
    except Exception:
        cfg = {}
    asst_name = cfg.get("assistant_name") or "D.O.N.N.A"
    user_name = cfg.get("user_name") or "Сэр"

    time_str = datetime.now().strftime("%A, %B %d, %Y — %H:%M")
    parts = [
        f"[CURRENT DATE & TIME]\nRight now it is: {time_str}\nUse this to calculate exact times and dates.\n\n",
        f"[IDENTITY]\nYour name is {asst_name}. Always refer to yourself as {asst_name}.\n"
        f"Always address the user as '{user_name}'.\n\n",
        f"[LANGUAGE & DIALOGUE PROTOCOL]\n"
        f"Respond EXCLUSIVELY in Russian (Русский язык) when addressing Сэр. "
        f"Never mix Arabic, Chinese, English filler words or foreign particles (e.g. never use words like 'إليك'). "
        f"All explanations, answers, and summaries must be completely in Russian.\n\n",
    ]
    for label, loader in (
        ("ambient", lambda: __import__("core.ambient_context", fromlist=["x"]).format_ambient_for_prompt()),
        ("cortex", lambda: __import__("memory.cortex_engine", fromlist=["x"]).cortex.get_cortex_summary_for_prompt()),
        ("openclaw", lambda: __import__("core.openclaw_engine", fromlist=["x"]).openclaw_engine.get_skills_summary_for_prompt()),
    ):
        try:
            ctx = loader()
            if ctx:
                parts.append(ctx)
        except Exception as e:
            print(f"  [warn] {label} context unavailable: {e}")

    try:
        parts.append(PROMPT_PATH.read_text(encoding="utf-8"))
    except Exception:
        parts.append("You are D.O.N.N.A., an advanced AI assistant. Always use tools to complete tasks.")
    return "\n".join(parts)


def _lower_types(schema):
    """Gemini schema uses 'OBJECT'/'STRING'; OpenAI JSON-schema wants lowercase."""
    if isinstance(schema, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _lower_types(v)) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_lower_types(x) for x in schema]
    return schema


def donna_tools_openai_format() -> list:
    from shared.tool_declarations import TOOL_DECLARATIONS
    tools = []
    for d in copy.deepcopy(TOOL_DECLARATIONS):
        fn = {"name": d["name"], "description": d.get("description", "")}
        fn["parameters"] = _lower_types(d.get("parameters") or {"type": "object", "properties": {}})
        tools.append({"type": "function", "function": fn})
    return tools


async def main() -> int:
    ap = argparse.ArgumentParser(description="Manual Cerebras integration check with DONNA system prompt")
    ap.add_argument("--model", default=CEREBRAS_DEFAULT_MODEL)
    ap.add_argument("-q", "--question", default=DEFAULT_QUESTION)
    ap.add_argument("--with-tools", action="store_true", help="attach DONNA tool declarations (OpenAI format)")
    ap.add_argument("--max-tokens", type=int, default=1024)
    args = ap.parse_args()

    sys_prompt = build_donna_system_prompt()
    tools = donna_tools_openai_format() if args.with_tools else None

    print("=" * 70)
    print(f"Model:          {args.model}")
    print(f"System prompt:  {len(sys_prompt)} chars")
    if tools:
        print(f"Tools:          {len(tools)} declarations ({len(json.dumps(tools, ensure_ascii=False))} chars JSON)")
    print(f"Question:       {args.question}")
    print("=" * 70)

    client = CerebrasClient(model=args.model)
    try:
        resp = await client.generate(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": args.question}],
            max_tokens=args.max_tokens,
            tools=tools,
        )
    except CerebrasRateLimitError as e:
        print(f"\n❌ RATE LIMIT: {e} (retry_after={e.retry_after})")
        return 2
    except CerebrasError as e:
        print(f"\n❌ {type(e).__name__}: {e}")
        return 1

    pct = 100.0 * resp.prompt_tokens / CONTEXT_WINDOW
    print(f"Latency:        {resp.latency_s:.2f}s")
    print(f"Tokens:         prompt={resp.prompt_tokens} ({pct:.1f}% of {CONTEXT_WINDOW} ctx), "
          f"completion={resp.completion_tokens}, total={resp.total_tokens}")
    print(f"Finish reason:  {resp.finish_reason}")
    if resp.tool_calls:
        print(f"Tool calls:     {json.dumps(resp.tool_calls, ensure_ascii=False)[:500]}")
    print("-" * 70)
    print(resp.text or "(empty text)")
    print("-" * 70)
    print("✅ OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
