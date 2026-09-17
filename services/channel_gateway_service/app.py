"""
Channel Gateway Microservice (Port 8000)
Hosts the mobile remote web dashboard, QR pairing, Telegram Bridge, Cron Engine, and RSS News Monitor.
"""

import sys
import asyncio
from pathlib import Path

if sys.platform == "win32":
    try:
        for _stream in (sys.stdout, sys.stderr):
            _reconf = getattr(_stream, "reconfigure", None)
            if callable(_reconf):
                _reconf(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from shared.config import CHANNEL_GATEWAY_PORT, CHANNEL_GATEWAY_HOST, BRAIN_SERVICE_URL
from dashboard.server import DashboardServer
from actions.telegram_bridge import telegram_bridge
from core.cron_engine import cron_daemon
from actions.background_monitor import check_all as monitor_check_all


class ChannelGatewayService:
    def __init__(self):
        self.dashboard = DashboardServer()
        self._loop = None

    async def _forward_command_to_brain(self, text: str):
        """Sends command to Brain Orchestrator."""
        try:
            url = f"{BRAIN_SERVICE_URL}/v1/command"
            token = os.getenv("DONNA_INTERNAL_TOKEN", "")
            headers = {"X-Donna-Internal-Token": token} if token else {}
            await asyncio.to_thread(requests.post, url, json={"text": text}, headers=headers, timeout=5)
            print(f"[ChannelGateway] Forwarded command to Brain: '{text[:50]}'")
        except Exception as e:
            print(f"[ChannelGateway] Failed to forward command to Brain: {e}")
            report("ERROR", "forward_command", str(e))

    async def _process_dashboard_commands(self):
        while True:
            try:
                text = await self.dashboard._command_queue.get()
                if text:
                    await self._forward_command_to_brain(text)
            except Exception as e:
                await asyncio.sleep(1)

    async def _run_rss_monitor(self):
        """Periodic background RSS monitor."""
        while True:
            await asyncio.sleep(300)  # Check every 5 minutes
            try:
                alerts = await asyncio.to_thread(monitor_check_all)
                for alert in alerts or []:
                    msg = f"[MONITOR_ALERT] {alert}"
                    await self._forward_command_to_brain(msg)
            except Exception as e:
                print(f"[ChannelGateway] Monitor check error: {e}")
                report_exception("rss_monitor", e)

    async def start(self):
        self._loop = asyncio.get_running_loop()

        # Connect Telegram command callback to forward to Brain
        async def _on_telegram_msg(user_id: str, text: str):
            print(f"[ChannelGateway] Telegram message from {user_id}: {text}")
            await self._forward_command_to_brain(text)

        telegram_bridge.set_message_handler(_on_telegram_msg)

        # Launch background tasks
        asyncio.create_task(self.dashboard.serve())
        asyncio.create_task(self._process_dashboard_commands())
        asyncio.create_task(telegram_bridge.run_polling())
        asyncio.create_task(cron_daemon.run())
        asyncio.create_task(self._run_rss_monitor())
        print(f"[ChannelGateway] All channel daemons started on port {CHANNEL_GATEWAY_PORT}.")


gateway_svc = ChannelGatewayService()
app = gateway_svc.dashboard.app

from shared.error_reporter import install_sentinel, report, report_exception
install_sentinel(app, "channel_gateway_service")


@app.get("/gateway/health")
def health():
    return {
        "status": "healthy",
        "service": "channel_gateway_service",
        "port": CHANNEL_GATEWAY_PORT,
    }


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Channel Gateway on {CHANNEL_GATEWAY_HOST}:{CHANNEL_GATEWAY_PORT}...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(gateway_svc.start())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
