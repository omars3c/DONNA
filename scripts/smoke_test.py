"""
Smoke-test: проверяет микросервисы DONNA.

1. Режим импортов (по умолчанию):
   Проверяет, что каждый микросервис и общий модуль импортируется БЕЗ ОШИБОК.
   Запуск:
       python scripts/smoke_test.py

2. Режим проверки доступности запущенных сервисов (--health / --live):
   Выполняет dry-run HTTP GET /health запросы ко всем 8 сервисам.
   Запуск:
       python scripts/smoke_test.py --health

3. Полный режим (--all):
   Выполняет проверку импортов + проверку доступности эндпоинтов.
   Запуск:
       python scripts/smoke_test.py --all
"""
import os
import sys
import subprocess
import argparse
import urllib.request
import urllib.error
from pathlib import Path

# Ensure UTF-8 output on Windows consoles to avoid charmap UnicodeEncodeError
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent

SERVICES = [
    "services.cortex_memory_service.app",
    "services.brain_orchestrator.app",
    "services.research_agent_service.app",
    "services.channel_gateway_service.app",
    "services.windows_host_agent.app",   # запускать реально только на Windows
    "services.audio_stream_service.app", # запускать реально только на Windows
    "services.sentinel_service.app",
    "services.autonomous_agent.app",
    "shared.error_reporter",
    "shared.tool_declarations",
    "shared.port_manager",
    "shared.config",
]

# 8 microservices and their health check endpoints
HEALTH_TARGETS = [
    ("GATEWAY",    "Channel Gateway",    "http://127.0.0.1:8000/health"),
    ("BRAIN",      "Brain Orchestrator", "http://127.0.0.1:8001/health"),
    ("CORTEX",     "Cortex Memory",      "http://127.0.0.1:8002/health"),
    ("RESEARCH",   "Research Agent",     "http://127.0.0.1:8003/health"),
    ("WIN_HOST",   "Windows Host Agent", "http://127.0.0.1:8004/health"),
    ("AUDIO",      "Audio Stream",       "http://127.0.0.1:8005/health"),
    ("SENTINEL",   "Sentinel Service",   "http://127.0.0.1:8006/health"),
    ("AUTONOMOUS", "Autonomous Agent",   "http://127.0.0.1:8007/health"),
]


def check_import(module_path: str, python_exe: str = sys.executable) -> tuple[bool, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [python_exe, "-c", f"import sys; sys.path.insert(0, '.'); import {module_path}; print('OK')"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    ok = result.returncode == 0 and "OK" in result.stdout
    output = result.stdout + result.stderr
    return ok, output


def run_import_tests() -> bool:
    print(f"Проверка импортов из: {ROOT}\n", flush=True)
    failures = []
    for svc in SERVICES:
        print(f"Тестирование {svc}...", end="\r", flush=True)
        ok, output = check_import(svc)
        status = "✅ OK" if ok else "❌ FAIL"
        print(f"{status:10} {svc}", flush=True)
        if not ok:
            failures.append((svc, output))

    if failures:
        print("\n=== ДЕТАЛИ ОШИБОК ===", flush=True)
        for svc, output in failures:
            print(f"\n--- {svc} ---", flush=True)
            print(output.strip()[-1500:], flush=True)  # последние 1500 символов traceback
        return False
    else:
        print("\nВсе модули импортируются без ошибок.", flush=True)
        return True


def check_endpoint_health(url: str, timeout: float = 1.5) -> tuple[bool, str]:
    """Probe /health endpoint via HTTP GET with X-Donna-Internal-Token if configured."""
    headers = {}
    token = os.getenv("DONNA_INTERNAL_TOKEN")
    if token:
        headers["X-Donna-Internal-Token"] = token

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if resp.status == 200:
                return True, f"HTTP 200: {body[:60]}"
            return False, f"HTTP {resp.status}: {body[:60]}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        err_str = str(e.reason)
        if "timed out" in err_str.lower():
            return False, "Таймаут подключения"
        return False, "Недоступен (unreachable)"
    except Exception as e:
        return False, str(e)


def run_health_checks() -> bool:
    print("Проверка доступности (health check) микросервисов:\n", flush=True)
    all_ok = True
    for tag, name, url in HEALTH_TARGETS:
        ok, detail = check_endpoint_health(url)
        status = "✅ UP" if ok else "❌ DOWN"
        print(f"{status:8} [{tag:10}] {name:20} -> {detail}", flush=True)
        if not ok:
            all_ok = False

    if all_ok:
        print("\n✅ Все 8 микросервисов работают и отвечают на /health.", flush=True)
    else:
        print("\n⚠️ Некоторые сервисы недоступны. Запустите их через: .\\run.ps1 all или py run_microservices.py", flush=True)
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="DONNA Microservices Smoke Test & Health Checker")
    parser.add_argument(
        "--health",
        "--live",
        action="store_true",
        dest="health",
        help="Проверить доступность запущенных микросервисов (/health эндпоинты)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Запустить полную проверку: импорты + health check запущенных сервисов",
    )

    args = parser.parse_args()

    if args.all:
        imports_ok = run_import_tests()
        print("\n" + "=" * 60 + "\n")
        health_ok = run_health_checks()
        if not (imports_ok and health_ok):
            sys.exit(1)
    elif args.health:
        health_ok = run_health_checks()
        if not health_ok:
            sys.exit(1)
    else:
        imports_ok = run_import_tests()
        if not imports_ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
