"""
OpenClaw Autonomous Cron & Heartbeat Daemon for D.O.N.N.A.
Executes scheduled background workflows (morning reports, repo syncs, backups, system audits)
and dispatches proactive updates to Telegram / Voice.
"""

from __future__ import annotations

import os
import sys
import time
import json
import asyncio
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Dict, Any, List, Callable, Optional

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
CONFIG_FILE = BASE_DIR / "config" / "api_keys.json"


class CronJob:
    def __init__(
        self,
        job_id: str,
        name: str,
        interval_seconds: Optional[int] = None,
        daily_time: Optional[str] = None,   # "08:30"
        handler: Optional[Callable] = None,
        description: str = "",
    ):
        self.job_id = job_id
        self.name = name
        self.interval_seconds = interval_seconds
        self.daily_time = daily_time
        self.handler = handler
        self.description = description
        self.last_run: float = 0.0
        self.enabled: bool = True

    def is_due(self, now_dt: datetime, now_mono: float) -> bool:
        if not self.enabled:
            return False

        if self.interval_seconds:
            if now_mono - self.last_run >= self.interval_seconds:
                return True

        if self.daily_time:
            target_h, target_m = map(int, self.daily_time.split(":"))
            if now_dt.hour == target_h and now_dt.minute == target_m:
                # Run once per minute window
                if now_mono - self.last_run >= 65:
                    return True

        return False


class CronDaemon:
    _instance: Optional[CronDaemon] = None

    def __init__(self):
        self._jobs: Dict[str, CronJob] = {}
        self._running: bool = False
        self._register_default_jobs()

    @classmethod
    def get_instance(cls) -> CronDaemon:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_job(self, job: CronJob):
        self._jobs[job.job_id] = job
        print(f"[CronDaemon] Registered job: '{job.name}' ({job.daily_time or f'{job.interval_seconds}s'})")

    def _register_default_jobs(self):
        # 1. Daily morning briefing
        self.register_job(CronJob(
            job_id="daily_morning_briefing",
            name="Daily Morning Briefing",
            daily_time="09:00",
            description="Compiles daily weather, top tech news and tasks, sent to Telegram.",
        ))

        # 2. Hourly Cortex DB backup & maintenance
        self.register_job(CronJob(
            job_id="cortex_maintenance",
            name="Cortex DB Auto-Save & Vacuum",
            interval_seconds=3600,
            description="Performs database optimization and rolling journal snapshot.",
        ))

    def list_jobs(self) -> List[dict]:
        return [
            {
                "id": j.job_id,
                "name": j.name,
                "schedule": j.daily_time or f"every {j.interval_seconds}s",
                "last_run": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(j.last_run)) if j.last_run > 0 else "Never",
                "enabled": j.enabled,
                "description": j.description,
            }
            for j in self._jobs.values()
        ]

    async def run(self):
        print("[CronDaemon] Background scheduler started.")
        self._running = True

        while self._running:
            try:
                now_dt = datetime.now()
                now_mono = time.monotonic()

                for job in list(self._jobs.values()):
                    if job.is_due(now_dt, now_mono):
                        job.last_run = now_mono
                        print(f"[CronDaemon] ⏰ Triggering scheduled job: '{job.name}'")
                        if job.handler:
                            try:
                                if asyncio.iscoroutinefunction(job.handler):
                                    await job.handler()
                                else:
                                    job.handler()
                            except Exception as e:
                                print(f"[CronDaemon] Error running job {job.name}: {e}")

                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[CronDaemon] Loop exception: {e}")
                await asyncio.sleep(10)

        self._running = False


cron_daemon = CronDaemon.get_instance()
