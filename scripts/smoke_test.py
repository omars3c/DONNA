"""
Smoke-test: проверяет, что каждый микросервис DONNA импортируется
БЕЗ ОШИБОК, используя только зависимости из его собственного requirements.txt.

Запуск (с корня репозитория, после установки нужных venv):
    python scripts/smoke_test.py

Для каждого сервиса лучше иметь ОТДЕЛЬНЫЙ venv, иначе тест не поймает
"скрытые" зависимости, которые реально притянулись только потому,
что в общем venv уже стоит лишний пакет.
"""
import os
import subprocess
import sys
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
    "shared.error_reporter",
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


def main():
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
        sys.exit(1)
    else:
        print("\nВсе сервисы импортируются без ошибок.", flush=True)


if __name__ == "__main__":
    main()

