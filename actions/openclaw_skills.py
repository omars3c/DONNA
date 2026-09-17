"""
OpenClaw Skill Dispatcher Tool Action for D.O.N.N.A.
Exposes all 51 OpenClaw skills (Weather, Diagram Maker, Summarizer, etc.) as a live tool in Gemini.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any
from core.openclaw_engine import openclaw_engine


async def openclaw_skill(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    skill_name = params.get("skill_name", "").strip()
    query      = params.get("query", "").strip() or params.get("task", "").strip()

    if not skill_name and query:
        skill_name = query

    if not skill_name:
        return "Укажите название навыка или задачу (например, 'diagram-maker', 'summarize', 'weather')."

    result = await openclaw_engine.execute_skill_action(skill_name, query or skill_name, context=params)
    return result
