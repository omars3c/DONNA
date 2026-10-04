"""
Сценарный тест Cerebras + реальные tool calls DONNA.

Цикл: system-промпт DONNA + 17 tool-описаний → Cerebras возвращает tool_calls →
(dry-run: печать / --execute: реальный вызов через MicroserviceBridge, тот же,
что использует brain_orchestrator) → результат инструмента обратно в модель →
финальный текстовый ответ.

Gemini Live / brain_orchestrator не изменяются; client_bridge только импортируется.

Запуск:
    uv run python scripts/cerebras_tool_test.py                 # dry-run, все сценарии
    uv run python scripts/cerebras_tool_test.py --execute       # РЕАЛЬНО открывает приложения
    uv run python scripts/cerebras_tool_test.py --execute -s 4  # только сценарий №4
    uv run python scripts/cerebras_tool_test.py -q "открой калькулятор" --execute

--execute требует запущенных микросервисов (uv run python run_microservices.py).
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cerebras_check import build_donna_system_prompt, donna_tools_openai_format  # noqa: E402
from shared.llm import (  # noqa: E402
    CEREBRAS_DEFAULT_MODEL, CerebrasClient, CerebrasError, CerebrasRateLimitError,
)

SCENARIOS = [
    ("web_search", "Дай новостную сводку за последнюю неделю в сфере ИИ."),
    ("browser_control|open_app", "Открой вкладку в Firefox с YouTube."),
    ("open_app|browser_control", "Открой браузер Opera."),
    ("open_app", "Открой Notepad."),
]
MAX_ROUNDS = 4

# Tool name → bridge method name where they differ.
BRIDGE_ALIASES = {"system_status": "get_system_status", "autonomous_task": "agent_task"}


async def dispatch(name: str, args: dict, execute: bool) -> str:
    if not execute:
        return f"[DRY-RUN] {name} not executed; assume success."

    # 1. Try bridge (microservices) first if available
    from services.brain_orchestrator.client_bridge import bridge
    method = getattr(bridge, BRIDGE_ALIASES.get(name, name), None)
    if method is not None:
        try:
            sig = inspect.signature(method)
            filtered_args = args
            if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
                filtered_args = {k: v for k, v in args.items() if k in sig.parameters}
            bridge_res = await method(**filtered_args)
            bridge_str = bridge_res if isinstance(bridge_res, str) else json.dumps(bridge_res, ensure_ascii=False, default=str)
            if not any(err in bridge_str for err in ["unavailable", "ConnectError", "Connection refused"]):
                return bridge_str
            print(f"      [info] bridge returned '{bridge_str[:80]}', trying direct action fallback...")
        except Exception as e:
            print(f"      [info] bridge failed ({e}), trying direct action fallback...")

    # 2. Fallback to direct action from actions/ (works without full microservices stack running)
    try:
        if name == "open_app":
            from actions.open_app import open_app
            res = open_app(parameters=args)
        elif name == "browser_control":
            from actions.browser_control import browser_control
            res = browser_control(parameters=args)
        elif name == "web_search":
            from actions.web_search import web_search
            res = web_search(parameters=args)
        elif name == "system_status":
            from actions.system_monitor import get_system_status
            res = get_system_status()
        elif name == "reminder":
            from actions.reminder import reminder
            res = reminder(parameters=args)
        elif name == "computer_control":
            from actions.computer_control import computer_control
            res = computer_control(parameters=args)
        elif name == "computer_settings":
            from actions.computer_settings import computer_settings
            res = computer_settings(parameters=args)
        elif name == "youtube_video":
            from actions.youtube_video import youtube_video
            res = youtube_video(parameters=args)
        else:
            return f"Tool '{name}' executed with args: {args}"
    except Exception as e:
        return f"Direct action error ({name}): {e}"

    return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)


async def run_scenario(client: CerebrasClient, sys_prompt: str, tools: list,
                       question: str, expected: str, execute: bool) -> bool:
    print(f"\n▶ {question}   (ожидается: {expected})")
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": question}]
    called: list[str] = []
    t0 = time.perf_counter()
    for _ in range(MAX_ROUNDS):
        try:
            resp = await client.generate(messages, tools=tools, max_tokens=2048)
        except CerebrasRateLimitError as e:
            print(f"   ❌ RATE LIMIT: {e} (retry_after={e.retry_after})")
            return False
        except CerebrasError as e:
            print(f"   ❌ {type(e).__name__}: {e}")
            return False
        print(f"   · LLM {resp.latency_s:.2f}s, tokens prompt={resp.prompt_tokens} "
              f"completion={resp.completion_tokens}, finish={resp.finish_reason}")
        if not resp.tool_calls:
            print(f"   💬 {resp.text.strip()[:1500]}")
            break
        msg = resp.raw["choices"][0]["message"]
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": resp.tool_calls})
        for tc in resp.tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "?")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            called.append(name)
            print(f"   🔧 {name}({json.dumps(args, ensure_ascii=False)})")
            try:
                result = await dispatch(name, args, execute)
            except Exception as e:
                result = f"Tool error: {type(e).__name__}: {e}"
            print(f"      ↳ {str(result)[:400]}")
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": str(result)[:8000]})
    ok = expected == "any" or any(c in expected.split("|") for c in called)
    print(f"   {'✅' if ok else '⚠️'} tools={called or 'none'}  total {time.perf_counter() - t0:.2f}s")
    return ok


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="really dispatch tools to running microservices")
    ap.add_argument("--model", default=CEREBRAS_DEFAULT_MODEL)
    ap.add_argument("-s", "--scenario", type=int, help="1-based scenario index")
    ap.add_argument("-q", "--question", help="custom question instead of scenarios")
    args = ap.parse_args()

    sys_prompt = build_donna_system_prompt()
    tools = donna_tools_openai_format()
    client = CerebrasClient(model=args.model)
    print(f"Model={args.model}  mode={'EXECUTE' if args.execute else 'DRY-RUN'}  tools={len(tools)}")

    if args.question:
        scenarios = [("any", args.question)]
    elif args.scenario:
        scenarios = [SCENARIOS[args.scenario - 1]]
    else:
        scenarios = SCENARIOS

    results = []
    for expected, q in scenarios:
        results.append(await run_scenario(client, sys_prompt, tools, q, expected, args.execute))
    print(f"\n=== {sum(results)}/{len(results)} scenarios called the expected tool ===")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
