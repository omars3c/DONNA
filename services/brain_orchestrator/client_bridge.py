"""
Client bridge for dispatching tool calls from Brain Orchestrator to downstream microservices.
"""

import json
import httpx
from typing import Dict, Any, Optional

from shared.config import (
    CORTEX_SERVICE_URL,
    RESEARCH_SERVICE_URL,
    AUTONOMOUS_SERVICE_URL,
    HOST_AGENT_SERVICE_URL,
)


class MicroserviceBridge:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        from shared.config import INTERNAL_TOKEN_HEADER, INTERNAL_API_TOKEN
        headers = {}
        if INTERNAL_API_TOKEN:
            headers[INTERNAL_TOKEN_HEADER] = INTERNAL_API_TOKEN
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0, headers=headers)
        return self._client

    # в”Ђв”Ђ Cortex Memory Service Calls в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def recall_memory(self, query: str, category: str = "all", limit: int = 5) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{CORTEX_SERVICE_URL}/v1/memory/recall",
                json={"query": query, "category": category, "limit": limit},
            )
            if resp.status_code == 200:
                return resp.json().get("formatted", "No memory found.")
            return f"Cortex error ({resp.status_code}): {resp.text}"
        except Exception as e:
            return f"Memory service unavailable: {e}"

    async def save_knowledge(self, title: str, content: str, category: str = "notes", tags: str = "", importance: int = 3) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{CORTEX_SERVICE_URL}/v1/memory/save",
                json={"title": title, "content": content, "category": category, "tags": tags, "importance": importance},
            )
            if resp.status_code == 200:
                return resp.json().get("message", "Knowledge saved.")
            return f"Cortex error: {resp.text}"
        except Exception as e:
            return f"Memory service error: {e}"

    async def manage_cortex_tasks(self, action: str = "list", task: Optional[str] = None, task_id: Optional[int] = None, status: Optional[str] = None, priority: str = "normal", due_date: Optional[str] = None, project: Optional[str] = None) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{CORTEX_SERVICE_URL}/v1/tasks",
                json={
                    "action": action,
                    "task": task,
                    "task_id": task_id,
                    "status": status,
                    "priority": priority,
                    "due_date": due_date,
                    "project": project,
                },
            )
            if resp.status_code == 200:
                return resp.json().get("message", "Tasks updated.")
            return f"Task service error: {resp.text}"
        except Exception as e:
            return f"Task service error: {e}"

    async def log_journal(self, entry: str, mood: str = "neutral", tags: str = "") -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{CORTEX_SERVICE_URL}/v1/journal",
                json={"entry": entry, "mood": mood, "tags": tags},
            )
            if resp.status_code == 200:
                return resp.json().get("message", "Journal entry saved.")
            return f"Journal error: {resp.text}"
        except Exception as e:
            return f"Journal error: {e}"

    # в”Ђв”Ђ Research Agent Service Calls в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def web_search(self, query: str, mode: str = "search", items: Optional[list] = None, aspect: Optional[str] = None) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{RESEARCH_SERVICE_URL}/v1/research/search",
                json={"query": query, "mode": mode, "items": items or [], "aspect": aspect or "general"},
            )
            if resp.status_code == 200:
                return resp.json().get("result", "No results.")
            return f"Search service error ({resp.status_code})"
        except Exception as e:
            return f"Research agent unavailable: {e}"

    async def agent_task(self, task: str, user_instructions: str = "") -> str:
        client = await self.get_client()
        try:
            full_task = f"{task} (Instructions: {user_instructions})" if user_instructions else task
            resp = await client.post(
                f"{AUTONOMOUS_SERVICE_URL}/v1/task",
                json={"task": full_task, "wait": True, "timeout": 85.0},
                timeout=95.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("result"):
                    return data.get("result")
                elif data.get("status") == "running":
                    return f"Задача принята (ID: {data.get('task_id')}). Выполнение продолжается в фоновом режиме."
                elif data.get("error"):
                    return f"Ошибка выполнения агента: {data.get('error')}"
                return "Автономная задача успешно завершена."
            return f"Agent task error: {resp.text}"
        except Exception as e:
            return f"Autonomous agent error: {e}"

    async def deep_research_report(self, task: str, user_instructions: str = "") -> str:
        """Executes deep research and generates a Word (.docx) document via Research Agent Service."""
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{RESEARCH_SERVICE_URL}/v1/research/task",
                json={"task": task, "user_instructions": user_instructions},
                timeout=180.0,
            )
            if resp.status_code == 200:
                return resp.json().get("result", "Research report generated and opened.")
            return f"Research agent error: {resp.text}"
        except Exception as e:
            return f"Research agent error: {e}"

    async def youtube_video(self, action: str = "play", query: Optional[str] = None, url: Optional[str] = None, save: bool = False) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{RESEARCH_SERVICE_URL}/v1/research/youtube",
                json={"action": action, "query": query, "url": url, "save": save},
            )
            if resp.status_code == 200:
                return resp.json().get("result", "YouTube action completed.")
            return f"YouTube error: {resp.text}"
        except Exception as e:
            return f"YouTube service error: {e}"

    # в”Ђв”Ђ Windows Host Agent Calls в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def open_app(self, app_name: str, pending_disambiguation: bool = False) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{HOST_AGENT_SERVICE_URL}/v1/os/launch-app",
                json={"app_name": app_name, "pending_disambiguation": pending_disambiguation},
            )
            if resp.status_code == 200:
                return resp.json().get("message", f"Opened {app_name}")
            return f"Host Agent error: {resp.text}"
        except Exception as e:
            return f"Windows host agent unavailable: {e}"

    async def computer_control(self, *args, **kwargs) -> str:
        client = await self.get_client()
        try:
            action = "click"
            if args:
                action = args[0]
            elif "action" in kwargs:
                action = kwargs.pop("action")
            if "action" in kwargs:
                kwargs.pop("action")
            payload = {"action": action, **kwargs}
            resp = await client.post(
                f"{HOST_AGENT_SERVICE_URL}/v1/os/control",
                json=payload,
            )
            if resp.status_code == 200:
                return resp.json().get("message", "Done.")
            return f"Host Agent error: {resp.text}"
        except Exception as e:
            return f"Host agent error: {e}"

    async def computer_settings(self, action: str, value: Any = None, app_name: Optional[str] = None) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{HOST_AGENT_SERVICE_URL}/v1/os/settings",
                json={"action": action, "value": value, "app_name": app_name},
            )
            if resp.status_code == 200:
                return resp.json().get("message", "Setting updated.")
            return f"Host Agent error: {resp.text}"
        except Exception as e:
            return f"Host agent error: {e}"

    async def browser_control(self, action: str = "open", browser: Optional[str] = None, url: Optional[str] = None, target: Optional[str] = None) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{HOST_AGENT_SERVICE_URL}/v1/os/browser",
                json={"action": action, "browser": browser, "url": url, "target": target},
            )
            if resp.status_code == 200:
                return resp.json().get("message", "Browser action completed.")
            return f"Browser control error: {resp.text}"
        except Exception as e:
            return f"Host agent unavailable: {e}"

    async def reminder(self, action: str = "set", date: Optional[str] = None, time: Optional[str] = None, message: Optional[str] = None, query: Optional[str] = None, reminder_id: Optional[str] = None) -> str:
        client = await self.get_client()
        try:
            resp = await client.post(
                f"{HOST_AGENT_SERVICE_URL}/v1/os/reminder",
                json={"action": action, "date": date, "time": time, "message": message, "query": query, "reminder_id": reminder_id},
            )
            if resp.status_code == 200:
                return resp.json().get("message", "Reminder action completed.")
            return f"Reminder error: {resp.text}"
        except Exception as e:
            return f"Host agent unavailable: {e}"

    async def openclaw_skill(self, skill_name: str, query: str = "", context: Optional[dict] = None) -> str:
        try:
            from actions.openclaw_skills import openclaw_skill as oc_skill
            params = {"skill_name": skill_name, "query": query}
            if context:
                params.update(context)
            res = await oc_skill(parameters=params)
            return str(res)
        except Exception as e:
            return f"OpenClaw skill error: {e}"

    async def get_system_status(self) -> Dict[str, Any]:
        client = await self.get_client()
        try:
            resp = await client.get(f"{HOST_AGENT_SERVICE_URL}/v1/os/telemetry")
            if resp.status_code == 200:
                return resp.json()
            return {}
        except Exception:
            return {}

    async def capture_screenshot(self) -> tuple[Optional[bytes], str]:
        client = await self.get_client()
        try:
            resp = await client.get(f"{HOST_AGENT_SERVICE_URL}/v1/os/screenshot")
            if resp.status_code == 200:
                return resp.content, resp.headers.get("content-type", "image/jpeg")
            return None, ""
        except Exception:
            return None, ""


bridge = MicroserviceBridge()


