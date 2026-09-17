"""
OpenClaw Skill Runtime Engine & Semantic Router (Tool RAG) for D.O.N.N.A. / J.A.R.V.I.S.
Dynamically routes requests to 51 OpenClaw skills without polluting the LLM context window.
Provides real execution backends (Mermaid diagram renderer, web summarizer, weather, git/vault ops).
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import shutil
import asyncio
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from core.model_pool import model_pool, FAST_TEXT_MODEL

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
SKILLS_DIR = BASE_DIR / "openclaw-main" / "skills"
DOCUMENTS_DIR = BASE_DIR / "documents"
DIAGRAMS_DIR = DOCUMENTS_DIR / "diagrams"
DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)


class SkillMetadata:
    def __init__(self, name: str, description: str, emoji: str, requires: dict, raw_content: str, path: Path):
        self.name = name
        self.description = description
        self.emoji = emoji
        self.requires = requires
        self.raw_content = raw_content
        self.path = path

    def is_available(self) -> bool:
        bins = self.requires.get("bins", [])
        if not bins:
            return True
        for b in bins:
            if not shutil.which(b):
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "emoji": self.emoji,
            "requires": self.requires,
            "available": self.is_available(),
            "path": str(self.path),
        }


# Quick lookup aliases to route user intents to exact OpenClaw skill names
SKILL_ALIASES: Dict[str, str] = {
    "diagram": "diagram-maker",
    "chart": "diagram-maker",
    "flowchart": "diagram-maker",
    "architecture": "diagram-maker",
    "схема": "diagram-maker",
    "диаграмма": "diagram-maker",
    "граф": "diagram-maker",
    "summary": "summarize",
    "summarizer": "summarize",
    "саммари": "summarize",
    "выжимка": "summarize",
    "кратко": "summarize",
    "weather": "weather",
    "погода": "weather",
    "прогноз": "weather",
    "wttr": "weather",
    "git": "github",
    "github": "github",
    "issues": "gh-issues",
    "pdf": "nano-pdf",
    "notes": "obsidian",
    "заметки": "obsidian",
    "obsidian": "obsidian",
    "tasks": "taskflow",
    "задачи": "taskflow",
    "todo": "taskflow",
    "whisper": "openai-whisper",
    "camera": "camsnap",
    "камера": "camsnap",
    "spotify": "spotify-player",
}


class OpenClawSkillEngine:
    _instance: Optional[OpenClawSkillEngine] = None

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or SKILLS_DIR
        self._skills: Dict[str, SkillMetadata] = {}
        self.load_all_skills()

    @classmethod
    def get_instance(cls) -> OpenClawSkillEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_all_skills(self) -> int:
        self._skills.clear()
        if not self.skills_dir.exists():
            return 0

        for skill_folder in self.skills_dir.iterdir():
            if not skill_folder.is_dir():
                continue
            skill_md = skill_folder / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                content = skill_md.read_text(encoding="utf-8", errors="ignore")
                meta = self._parse_skill_md(content, skill_folder.name, skill_md)
                if meta:
                    self._skills[meta.name.lower()] = meta
            except Exception as e:
                print(f"[OpenClawEngine] Error loading skill {skill_folder.name}: {e}")

        print(f"[OpenClawEngine] Indexed {len(self._skills)} skills into Semantic Router")
        return len(self._skills)

    def _parse_skill_md(self, content: str, folder_name: str, path: Path) -> Optional[SkillMetadata]:
        name = folder_name
        description = ""
        emoji = "🛠️"
        requires: dict = {}

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                m_name = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
                if m_name:
                    name = m_name.group(1).strip().strip('"\'')

                m_desc = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
                if m_desc:
                    description = m_desc.group(1).strip().strip('"\'')

                m_emoji = re.search(r'"emoji":\s*"([^"]+)"', frontmatter)
                if m_emoji:
                    emoji = m_emoji.group(1)

                m_bins = re.search(r'"bins":\s*\[([^\]]+)\]', frontmatter)
                if m_bins:
                    bin_list = [b.strip().strip('"\'') for b in m_bins.group(1).split(",") if b.strip()]
                    requires["bins"] = bin_list

        if not description:
            lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#") and not l.startswith("---")]
            if lines:
                description = lines[0][:150]

        return SkillMetadata(
            name=name,
            description=description,
            emoji=emoji,
            requires=requires,
            raw_content=content,
            path=path,
        )

    def match_skill(self, name_or_query: str) -> Optional[SkillMetadata]:
        """
        Tool RAG Router: Matches user input or tool name to best OpenClaw skill.
        Prevents hallucinated or near-miss skill invocations.
        """
        q = (name_or_query or "").strip().lower()
        if not q:
            return None

        # 1. Exact match by name
        if q in self._skills:
            return self._skills[q]

        # 2. Alias match & prefix/stem match
        for alias, target in SKILL_ALIASES.items():
            if alias in q or q in alias:
                if target in self._skills:
                    return self._skills[target]
            stem = alias[:5] if len(alias) >= 5 else alias
            if stem in q:
                if target in self._skills:
                    return self._skills[target]

        # 3. Partial / Token containment match
        for skill_name, meta in self._skills.items():
            if skill_name in q or q in skill_name:
                return meta
            desc_lower = meta.description.lower()
            if any(term in desc_lower for term in q.split() if len(term) > 3):
                return meta

        return None

    def get_skills_summary_for_prompt(self, max_skills: int = 10) -> str:
        """
        Compact context injection for J.A.R.V.I.S.
        Does NOT dump 51 raw skills. Injects a high-density, low-token capability index.
        """
        return (
            "[OPENCLAW EXTENSIONS & SKILL DISPATCHER]\n"
            "You have access to 51 specialized OpenClaw skills via the 'openclaw_skill' tool.\n"
            "Major functional domains:\n"
            "- Engineering & Visuals: diagram-maker (Mermaid charts/architecture), github (PRs, issues, CI)\n"
            "- Research & Knowledge: summarize (deep URL / text analysis), obsidian (local vault notes), nano-pdf\n"
            "- Utilities: weather (wttr.in reports), taskflow, spotify-player, camsnap\n"
            "To use: call openclaw_skill(skill_name='<name>', query='<params>') — the router automatically "
            "resolves aliases and executes the operational handler."
        )

    async def execute_skill_action(self, skill_name: str, query: str, context: Optional[dict] = None) -> str:
        meta = self.match_skill(skill_name) or self.match_skill(query)
        target_name = meta.name.lower() if meta else skill_name.lower().strip()

        # Operational execution branches
        if target_name in ("diagram-maker", "diagram"):
            return await self._handle_diagram(query or skill_name)

        if target_name in ("summarize", "summary"):
            return await self._handle_summarize(query)

        if target_name in ("weather", "wttr"):
            return await self._handle_weather(query)

        if target_name in ("github", "gh-issues"):
            return await self._handle_github(query)

        if target_name in ("obsidian", "notes"):
            return await self._handle_obsidian(query)

        if meta:
            return (
                f"[{meta.emoji} OpenClaw Skill: {meta.name}]\n"
                f"Description: {meta.description}\n"
                f"Executable guidelines:\n{meta.raw_content[:800]}"
            )

        avail = ", ".join(list(SKILL_ALIASES.keys())[:12])
        return f"Unknown skill '{skill_name}'. Common available skills: {avail}..."

    async def _handle_diagram(self, prompt: str) -> str:
        """
        Real Mermaid Diagram Renderer:
        1. Uses model_pool (gemini-2.0-flash) to write valid, aesthetically clean Mermaid code.
        2. Wraps in a standalone dark-mode HTML page with Mermaid.js CDN.
        3. Saves to documents/diagrams/ and launches in default browser.
        """
        system_instruction = (
            "You are an expert systems software architect. Convert the user request into "
            "valid, modern Mermaid.js diagram code (flowchart TD/LR, sequenceDiagram, classDiagram, or gitGraph). "
            "Output ONLY the Mermaid code inside a fenced code block: ```mermaid ... ```. "
            "Do not include any other markdown or explanation."
        )

        try:
            from google.genai import types
            resp = model_pool.generate_content(
                contents=f"Generate an architecture or process diagram for: {prompt}",
                config=types.GenerateContentConfig(system_instruction=system_instruction),
            )
            raw = resp.text.strip() if resp and resp.text else ""
            m = re.search(r"```(?:mermaid)?\s*([\s\S]+?)\s*```", raw)
            mermaid_code = m.group(1).strip() if m else raw.strip()
            if not mermaid_code:
                mermaid_code = "flowchart TD\n  A[User Request] --> B[Processing]\n  B --> C[Done]"

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"diagram_{ts}.html"
            filepath = DIAGRAMS_DIR / filename

            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>JARVIS Tactical Architecture: {prompt[:40]}</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body {{
      background-color: #0b0f19;
      color: #e2e8f0;
      font-family: 'Segoe UI', -apple-system, sans-serif;
      margin: 0;
      padding: 30px;
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
    }}
    .header {{
      text-align: center;
      margin-bottom: 25px;
      border-bottom: 1px solid #1e293b;
      padding-bottom: 15px;
      width: 90%;
      max-width: 1000px;
    }}
    .header h1 {{
      margin: 0 0 8px 0;
      font-size: 20px;
      letter-spacing: 1.5px;
      color: #38bdf8;
      text-transform: uppercase;
    }}
    .header p {{
      margin: 0;
      color: #94a3b8;
      font-size: 14px;
    }}
    .mermaid-container {{
      background: #131b2e;
      border: 1px solid #1e293b;
      border-radius: 12px;
      padding: 30px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
      max-width: 95%;
      overflow-x: auto;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Tactical Visual Artifact: {prompt}</h1>
    <p>Generated by D.O.N.N.A. / J.A.R.V.I.S. Core Engine • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </div>
  <div class="mermaid-container">
    <pre class="mermaid">
{mermaid_code}
    </pre>
  </div>
  <script>
    mermaid.initialize({{
      startOnLoad: true,
      theme: 'dark',
      themeVariables: {{
        darkMode: true,
        background: '#131b2e',
        primaryColor: '#38bdf8',
        primaryTextColor: '#f8fafc',
        primaryBorderColor: '#0284c7',
        lineColor: '#64748b',
        secondaryColor: '#f59e0b',
        tertiaryColor: '#1e293b'
      }}
    }});
  </script>
</body>
</html>
"""
            filepath.write_text(html_content, encoding="utf-8")
            webbrowser.open(filepath.as_uri())
            return f"Диаграмма успешно сгенерирована и открыта в браузере: {filepath.name}"
        except Exception as e:
            return f"Ошибка построения диаграммы: {e}"

    async def _handle_summarize(self, text_or_url: str) -> str:
        """
        Real Content & Web Summarizer:
        1. If URL, fetches HTML, cleans markup and extracts readable body.
        2. Generates structured executive summary via model_pool (gemini-2.0-flash).
        """
        target = (text_or_url or "").strip()
        if not target:
            return "Укажите текст или URL для анализа."

        raw_content = target
        if target.startswith("http://") or target.startswith("https://"):
            import urllib.request
            try:
                req = urllib.request.Request(
                    target,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
                # Strip scripts and styles
                clean_html = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", "", html, flags=re.IGNORECASE)
                clean_text = re.sub(r"<[^>]+>", " ", clean_html)
                clean_text = re.sub(r"\s+", " ", clean_text).strip()
                raw_content = clean_text[:25000]
            except Exception as e:
                return f"Не удалось загрузить веб-страницу: {e}"

        prompt = (
            f"Analyze and synthesize the following content. "
            f"Provide an executive summary in the same language as the content.\n\n"
            f"Structure:\n"
            f"- Главная суть (1-2 предложения)\n"
            f"- Ключевые тезисы (3-5 буллетов)\n"
            f"- Вывод или практическое значение\n\n"
            f"Content:\n{raw_content}"
        )

        try:
            resp = model_pool.generate_content(contents=prompt)
            return resp.text.strip() if resp and resp.text else "Не удалось сформировать выжимку."
        except Exception as e:
            return f"Ошибка суммаризации: {e}"

    async def _handle_weather(self, location: str) -> str:
        loc = (location or "").strip() or "Moscow"
        import urllib.request
        url = f"https://wttr.in/{urllib.parse.quote(loc)}?format=j2"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            loop = asyncio.get_event_loop()

            def _fetch():
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.read().decode("utf-8")

            raw = await loop.run_in_executor(None, _fetch)
            data = json.loads(raw)
            current = data.get("current_condition", [{}])[0]
            desc = current.get("weatherDesc", [{}])[0].get("value", "Clear")
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", temp)
            humidity = current.get("humidity", "?")
            wind = current.get("windspeedKmph", "?")
            return f"Погода в {loc}: {desc}, {temp}°C (ощущается как {feels}°C), влажность {humidity}%, ветер {wind} км/ч."
        except Exception as e:
            return f"Ошибка получения погоды для '{loc}': {e}"

    async def _handle_github(self, query: str) -> str:
        """Fast GitHub CLI status or local git branch info."""
        if shutil.which("gh"):
            try:
                proc = subprocess.run(["gh", "status"], capture_output=True, text=True, timeout=5)
                if proc.returncode == 0:
                    return f"GitHub Status:\n{proc.stdout[:800]}"
            except Exception:
                pass

        # Fallback to local git repository status
        try:
            proc = subprocess.run(["git", "status", "-s"], cwd=BASE_DIR, capture_output=True, text=True, timeout=5)
            branch = subprocess.run(["git", "branch", "--show-current"], cwd=BASE_DIR, capture_output=True, text=True, timeout=5).stdout.strip()
            changes = len([l for l in proc.stdout.splitlines() if l.strip()])
            return f"Локальный Git: ветка '{branch}', измененных файлов: {changes}."
        except Exception as e:
            return f"Git/GitHub статус недоступен: {e}"

    async def _handle_obsidian(self, query: str) -> str:
        """Search notes in documents/ directory."""
        notes = list(DOCUMENTS_DIR.glob("**/*.md"))
        if not notes:
            return "В хранилище документов пока нет файлов заметок (.md)."
        matched = []
        q = (query or "").lower()
        for p in notes:
            if not q or q in p.name.lower():
                matched.append(p.name)
        if matched:
            return f"Найдено заметок ({len(matched)}): {', '.join(matched[:8])}"
        return f"По запросу '{query}' заметок не найдено. Всего заметок в базе: {len(notes)}."


openclaw_engine = OpenClawSkillEngine.get_instance()
