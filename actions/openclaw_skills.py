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
    skill_name = params.get("skill_name", "").strip().lower()
    query      = params.get("query", "").strip()

    if not skill_name:
        skills = openclaw_engine.list_skills()
        return f"Please specify a skill_name. Available skills ({len(skills)}): {', '.join([s['name'] for s in skills[:20]])}..."

    result = await openclaw_engine.execute_skill_action(skill_name, query, context=params)
    return result
