"""
Obsidian & Markdown Notes Agent for D.O.N.N.A. (Ported from OpenClaw Obsidian Skill)
Integrates local markdown knowledge vaults with Cortex semantic memory.
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
DEFAULT_VAULT = BASE_DIR / "documents" / "vault"


def _ensure_vault() -> Path:
    DEFAULT_VAULT.mkdir(parents=True, exist_ok=True)
    return DEFAULT_VAULT


def notes_agent(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "search").lower().strip()
    title  = params.get("title", "").strip()
    content = params.get("content", "").strip()
    query  = params.get("query", "").strip()

    vault_dir = _ensure_vault()

    if action in ("create", "add", "write", "new"):
        if not title:
            return "Please specify a title for the note."
        fname = title if title.endswith(".md") else f"{title}.md"
        note_path = vault_dir / fname
        note_path.write_text(content or f"# {title}\n\n", encoding="utf-8")

        # Also log to Cortex memory
        try:
            from memory.cortex_engine import cortex
            cortex.save_knowledge(f"Note '{title}': {content}", category="notes", tags=["note", "obsidian"])
        except Exception:
            pass

        return f"Note '{title}' saved successfully in vault ({note_path.name})."

    if action in ("read", "view", "get"):
        if not title and not query:
            return "Please provide note title or query to read."
        target_name = (title or query).lower()
        for f in vault_dir.rglob("*.md"):
            if target_name in f.name.lower():
                text = f.read_text(encoding="utf-8", errors="ignore")
                return f"📄 [{f.name}]\n{text[:2000]}"
        return f"Note '{title or query}' not found in vault."

    if action in ("search", "find", "list"):
        files = list(vault_dir.rglob("*.md"))
        if not files:
            return "Vault is currently empty. Use notes_agent(action='create', title='...', content='...') to add notes."

        if not query:
            lines = ["📚 Notes in Vault:"]
            for f in files[:15]:
                lines.append(f"- {f.name}")
            return "\n".join(lines)

        q_lower = query.lower()
        matched = []
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if q_lower in f.name.lower() or q_lower in text.lower():
                matched.append(f.name)

        if not matched:
            return f"No notes matching '{query}' found."
        return f"Found {len(matched)} note(s) matching '{query}':\n- " + "\n- ".join(matched[:10])

    return f"Unknown action: '{action}'. Available: create, read, search, list."
