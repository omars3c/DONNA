"""
run_microservices.py — D.O.N.N.A. Unified Microservices Orchestrator

Launches and supervises all 8 microservices as isolated processes:
  [0] Sentinel Service          (:8006)  ← starts first to catch startup errors
  [1] Cortex Memory Service     (:8002)
  [2] Research Agent Service    (:8003)
  [3] Windows Host Agent        (:8004)
  [4] Channel Gateway Service   (:8000)
  [5] Brain Orchestrator        (:8001)
  [6] Autonomous Agent Service  (:8007)
  [7] Audio Stream Service      (:8005)

Usage:
  py run_microservices.py
  py run_microservices.py --no-audio   (run without microphone/speakers)
  py run_microservices.py --with-ui    (also launch PyQt6 Tactical HUD)
"""

import sys
import os

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import signal
import subprocess
import threading
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parent

SERVICES = [
    {
        "name": "SENTINEL",
        "module": "services.sentinel_service.app",
        "port": 8006,
        "color": "\033[31;1m",  # Bright Red
    },
    {
        "name": "CORTEX",
        "module": "services.cortex_memory_service.app",
        "port": 8002,
        "color": "\033[94m",  # Blue
    },
    {
        "name": "RESEARCH",
        "module": "services.research_agent_service.app",
        "port": 8003,
        "color": "\033[96m",  # Cyan
    },
    {
        "name": "WIN_HOST",
        "module": "services.windows_host_agent.app",
        "port": 8004,
        "color": "\033[93m",  # Yellow
    },
    {
        "name": "GATEWAY",
        "module": "services.channel_gateway_service.app",
        "port": 8000,
        "color": "\033[95m",  # Magenta
    },
    {
        "name": "BRAIN",
        "module": "services.brain_orchestrator.app",
        "port": 8001,
        "color": "\033[92m",  # Green
    },
    {
        "name": "AUTONOMOUS",
        "module": "services.autonomous_agent.app",
        "port": 8007,
        "color": "\033[35;1m",  # Bright Magenta
    },
    {
        "name": "AUDIO",
        "module": "services.audio_stream_service.app",
        "port": 8005,
        "color": "\033[91m",  # Red
        "optional": True,
    },
]

RESET_COLOR = "\033[0m"


class MicroserviceRunner:
    def __init__(self, include_audio: bool = True, include_ui: bool = False):
        self.include_audio = include_audio
        self.include_ui = include_ui
        self.processes: Dict[str, subprocess.Popen] = {}
        self.running = True

    def _stream_output(self, name: str, color: str, pipe):
        """Stream child process stdout to console with optional Sentinel scraping."""
        prefix = f"{color}[{name:8}]{RESET_COLOR} "
        _ERROR_MARKERS = ("Traceback", "ERROR", "CRITICAL", "Exception", "Failed")
        _is_sentinel = (name == "SENTINEL")
        try:
            for line in iter(pipe.readline, ""):
                if not line:
                    break
                clean = line.rstrip("\r\n")
                if clean:
                    try:
                        print(f"{prefix}{clean}")
                    except Exception:
                        pass
                    # Stdout scraper: forward error-like lines to Sentinel
                    if not _is_sentinel:
                        try:
                            if any(m in clean for m in _ERROR_MARKERS):
                                import requests as _req
                                import time as _time
                                _req.post(
                                    "http://127.0.0.1:8006/v1/errors",
                                    json={
                                        "service": name.lower(),
                                        "severity": "ERROR",
                                        "source": "stdout_scrape",
                                        "message": clean[:2000],
                                        "ts": _time.time(),
                                    },
                                    timeout=1,
                                )
                        except Exception:
                            pass
        except Exception:
            pass

    def start_service(self, svc: dict):
        name = svc["name"]
        mod = svc["module"]
        color = svc.get("color", "")

        cmd = [sys.executable, "-m", mod]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        print(f"🚀 Starting {name} on port {svc['port']}...")
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self.processes[name] = proc

        t = threading.Thread(
            target=self._stream_output,
            args=(name, color, proc.stdout),
            daemon=True,
        )
        t.start()

    def start_all(self):
        print("=" * 65)
        print("🧠 D.O.N.N.A. STARK OS — MICROSERVICE ORCHESTRATOR")
        print("=" * 65)

        for svc in SERVICES:
            if svc.get("optional") and not self.include_audio:
                print(f"⏭️ Skipping {svc['name']} (--no-audio specified)")
                continue
            self.start_service(svc)
            time.sleep(0.8)  # Staggered startup

        if self.include_ui:
            print("🖥️ Starting PyQt6 Tactical HUD...")
            ui_cmd = [sys.executable, "ui.py"]
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(ui_cmd, cwd=str(BASE_DIR), env=env)
            self.processes["UI"] = proc

        print("\n✅ All microservices launched and operating.")
        print("Press Ctrl+C to terminate all services.\n" + "-" * 65)

    def stop_all(self):
        print("\n🛑 Stopping all microservices...")
        self.running = False
        for name, proc in self.processes.items():
            try:
                print(f"   Terminating {name} (PID: {proc.pid})...")
                proc.terminate()
            except Exception:
                pass

        time.sleep(1)
        for name, proc in self.processes.items():
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        print("👋 All services stopped.")


def main():
    include_audio = "--no-audio" not in sys.argv
    include_ui = "--no-ui" not in sys.argv

    runner = MicroserviceRunner(include_audio=include_audio, include_ui=include_ui)

    def sig_handler(sig, frame):
        runner.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    runner.start_all()

    reported_exits = set()
    try:
        while runner.running:
            time.sleep(1)
            # Check for crashed processes
            for name, proc in list(runner.processes.items()):
                code = proc.poll()
                if code is not None and name not in reported_exits and runner.running:
                    reported_exits.add(name)
                    print(f"⚠️ Service '{name}' exited with code {code}")
    except KeyboardInterrupt:
        runner.stop_all()


if __name__ == "__main__":
    main()
