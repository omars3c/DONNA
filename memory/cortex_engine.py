"""
Cortex Knowledge & Semantic Vector Memory Engine for D.O.N.N.A. (Stark OS)
Features:
  - SQLite persistent knowledge graph (nodes, tasks, journal)
  - 3072D Vector Embeddings via Gemini API with offline BM25/Cosine fallback
  - Hybrid Semantic Search (Cosine Similarity 70% + Keyword 20% + Recency/Importance 10%)
  - Task & Todo tracking with project linking
  - Daily Journal & Episodic memory logging
  - Auto-migration from legacy long_term.json
"""
import io
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
DB_PATH = BASE_DIR / "memory" / "cortex.db"
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
LEGACY_MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"

_DB_LOCK = threading.Lock()
_EMBED_CACHE: Dict[str, np.ndarray] = {}
_FALLBACK_VOCAB: Dict[str, int] = {}


def _get_api_key() -> str:
    try:
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return cfg.get("gemini_api_key", "").strip()
    except Exception:
        pass
    return ""


# ── Embedding Engine (Gemini 3072D + Fast Local Cosine Fallback) ──────────────

def _get_embedding(text: str) -> np.ndarray:
    """Compute 3072D embedding via Gemini API (models/gemini-embedding-2) or fallback to deterministic local normalized vector."""
    clean_text = (text or "").strip()
    if not clean_text:
        return np.zeros(3072, dtype=np.float32)

    if clean_text in _EMBED_CACHE:
        return _EMBED_CACHE[clean_text]

    api_key = _get_api_key()
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            for emb_model in ["models/gemini-embedding-2", "models/gemini-embedding-001"]:
                try:
                    resp = client.models.embed_content(
                        model=emb_model,
                        contents=clean_text[:4000],
                    )
                    if hasattr(resp, "embeddings") and resp.embeddings and hasattr(resp.embeddings[0], "values"):
                        vec = np.array(resp.embeddings[0].values, dtype=np.float32)
                        norm = np.linalg.norm(vec)
                        if norm > 0:
                            vec = vec / norm
                        if len(_EMBED_CACHE) > 1000:
                            _EMBED_CACHE.clear()
                        _EMBED_CACHE[clean_text] = vec
                        return vec
                except Exception:
                    continue
        except Exception:
            pass

    # Deterministic local TF-IDF & Character N-gram embedding fallback (SHA256 3072D)
    import hashlib
    vec = np.zeros(3072, dtype=np.float32)
    words = re.findall(r"\w+", clean_text.lower())
    for w in words:
        idx = int.from_bytes(hashlib.sha256(w.encode("utf-8")).digest()[:4], "big") % 3072
        vec[idx] += 1.0
    for i in range(len(clean_text) - 2):
        trigram = clean_text[i : i + 3].lower()
        idx = (int.from_bytes(hashlib.sha256(trigram.encode("utf-8")).digest()[:4], "big") + 1024) % 3072
        vec[idx] += 0.5
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    _EMBED_CACHE[clean_text] = vec
    return vec


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    if vec_a is None or vec_b is None or len(vec_a) == 0 or len(vec_b) == 0:
        return 0.0
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


# ── SQLite Cortex Database Setup ──────────────────────────────────────────────

class CortexEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_memory()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn

    def _init_db(self):
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cortex_nodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags TEXT DEFAULT '',
                        importance INTEGER DEFAULT 3,
                        metadata TEXT DEFAULT '{}',
                        embedding BLOB,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cortex_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task TEXT NOT NULL,
                        project TEXT DEFAULT '',
                        priority TEXT DEFAULT 'normal',
                        status TEXT DEFAULT 'pending',
                        due_date TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        completed_at TEXT DEFAULT ''
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cortex_journal (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        entry_date TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        key_events TEXT DEFAULT '',
                        sentiment TEXT DEFAULT 'neutral',
                        created_at TEXT NOT NULL
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    def _migrate_legacy_memory(self):
        """Automatically migrate existing long_term.json into cortex_nodes if empty."""
        if not LEGACY_MEMORY_PATH.exists():
            return
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM cortex_nodes")
                count = cursor.fetchone()[0]
                if count > 0:
                    return  # Already initialized

                try:
                    data = json.loads(LEGACY_MEMORY_PATH.read_text(encoding="utf-8"))
                except Exception:
                    return

                print("[Cortex] 🔄 Migrating legacy long_term.json into Cortex Knowledge Graph...")
                now_str = datetime.now().isoformat()

                for cat, items in data.items():
                    if cat in ("sessions", "monitors") or not isinstance(items, dict):
                        continue
                    for key, val_obj in items.items():
                        val = val_obj.get("value", "") if isinstance(val_obj, dict) else str(val_obj)
                        updated = val_obj.get("updated", now_str) if isinstance(val_obj, dict) else now_str
                        title = key.replace("_", " ").title()
                        content = str(val)
                        vec = _get_embedding(f"{title}: {content}")
                        blob = vec.tobytes()
                        cursor.execute("""
                            INSERT INTO cortex_nodes (category, title, content, tags, importance, metadata, embedding, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (cat, title, content, key, 3, json.dumps({"legacy_key": key}), blob, updated, updated))

                conn.commit()
                print("[Cortex] ✅ Migration complete.")
            except Exception as e:
                print(f"[Cortex] Migration notice: {e}")
            finally:
                conn.close()

    # ── Knowledge Nodes Operations ────────────────────────────────────────────

    def store_node(
        self,
        title: str,
        content: str,
        category: str = "notes",
        tags: str = "",
        importance: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Store or update a knowledge node with embedding."""
        title = (title or "").strip()
        content = (content or "").strip()
        if not title and not content:
            raise ValueError("Title or content must be provided.")
        if not title:
            title = content[:40]

        now_str = datetime.now().isoformat()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        embed_text = f"{category} | {title} | {tags} | {content}"
        vec = _get_embedding(embed_text)
        blob = vec.tobytes()

        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                # Check for existing node with same title and category to update
                cursor.execute(
                    "SELECT id FROM cortex_nodes WHERE LOWER(title) = LOWER(?) AND category = ?",
                    (title, category),
                )
                existing = cursor.fetchone()
                if existing:
                    node_id = existing["id"]
                    cursor.execute("""
                        UPDATE cortex_nodes
                        SET content = ?, tags = ?, importance = ?, metadata = ?, embedding = ?, updated_at = ?
                        WHERE id = ?
                    """, (content, tags, importance, meta_json, blob, now_str, node_id))
                else:
                    cursor.execute("""
                        INSERT INTO cortex_nodes (category, title, content, tags, importance, metadata, embedding, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (category, title, content, tags, importance, meta_json, blob, now_str, now_str))
                    node_id = cursor.lastrowid
                conn.commit()
                return node_id
            finally:
                conn.close()

    def search_nodes(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 5,
        min_similarity: float = 0.25,
    ) -> List[Dict[str, Any]]:
        """Semantic & Hybrid search across Cortex Knowledge nodes."""
        query = (query or "").strip()
        if not query:
            return self.get_recent_nodes(category=category, limit=limit)

        q_vec = _get_embedding(query)
        q_words = set(re.findall(r"\w+", query.lower()))

        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                if category and category.lower() != "all":
                    cursor.execute(
                        "SELECT id, category, title, content, tags, importance, metadata, embedding, updated_at FROM cortex_nodes WHERE category = ?",
                        (category,),
                    )
                else:
                    cursor.execute(
                        "SELECT id, category, title, content, tags, importance, metadata, embedding, updated_at FROM cortex_nodes"
                    )
                rows = cursor.fetchall()
            finally:
                conn.close()

        results = []
        for row in rows:
            blob = row["embedding"]
            if blob:
                doc_vec = np.frombuffer(blob, dtype=np.float32)
                sem_score = _cosine_similarity(q_vec, doc_vec)
            else:
                sem_score = 0.0

            # Keyword lexical overlap
            doc_text = f"{row['title']} {row['tags']} {row['content']}".lower()
            doc_words = set(re.findall(r"\w+", doc_text))
            lex_score = len(q_words & doc_words) / max(1, len(q_words)) if q_words else 0.0

            # Importance factor
            imp_factor = (row["importance"] or 3) / 5.0 * 0.1

            # Combined hybrid score (70% Semantic + 20% Lexical + 10% Importance)
            hybrid_score = (sem_score * 0.7) + (lex_score * 0.2) + imp_factor

            if hybrid_score >= min_similarity or lex_score > 0.4:
                results.append({
                    "id": row["id"],
                    "category": row["category"],
                    "title": row["title"],
                    "content": row["content"],
                    "tags": row["tags"],
                    "importance": row["importance"],
                    "updated_at": row["updated_at"],
                    "score": round(float(hybrid_score), 3),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def get_recent_nodes(self, category: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                if category and category.lower() != "all":
                    cursor.execute(
                        "SELECT id, category, title, content, tags, importance, updated_at FROM cortex_nodes WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                        (category, limit),
                    )
                else:
                    cursor.execute(
                        "SELECT id, category, title, content, tags, importance, updated_at FROM cortex_nodes ORDER BY updated_at DESC LIMIT ?",
                        (limit,),
                    )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def delete_node(self, node_id: int) -> bool:
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cortex_nodes WHERE id = ?", (node_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    # ── Tasks & To-Dos Operations ─────────────────────────────────────────────

    def create_task(
        self,
        task: str,
        project: str = "",
        priority: str = "normal",
        due_date: str = "",
    ) -> int:
        task = (task or "").strip()
        if not task:
            raise ValueError("Task description cannot be empty.")
        now_str = datetime.now().isoformat()
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO cortex_tasks (task, project, priority, status, due_date, created_at)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                """, (task, project.strip(), priority.lower(), due_date.strip(), now_str))
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def list_tasks(
        self,
        status: str = "pending",
        project: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                query = "SELECT * FROM cortex_tasks WHERE 1=1"
                params: List[Any] = []
                if status and status.lower() != "all":
                    query += " AND status = ?"
                    params.append(status.lower())
                if project:
                    query += " AND LOWER(project) LIKE ?"
                    params.append(f"%{project.lower()}%")
                query += " ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, id DESC LIMIT ?"
                params.append(limit)
                cursor.execute(query, params)
                return [dict(r) for r in cursor.fetchall()]
            finally:
                conn.close()

    def update_task(
        self,
        task_id: int,
        status: Optional[str] = None,
        task_text: Optional[str] = None,
        priority: Optional[str] = None,
        due_date: Optional[str] = None,
    ) -> bool:
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                updates = []
                params: List[Any] = []
                if status:
                    updates.append("status = ?")
                    params.append(status.lower())
                    if status.lower() == "completed":
                        updates.append("completed_at = ?")
                        params.append(datetime.now().isoformat())
                if task_text:
                    updates.append("task = ?")
                    params.append(task_text.strip())
                if priority:
                    updates.append("priority = ?")
                    params.append(priority.lower())
                if due_date is not None:
                    updates.append("due_date = ?")
                    params.append(due_date.strip())

                if not updates:
                    return False
                params.append(task_id)
                cursor.execute(f"UPDATE cortex_tasks SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def delete_task(self, task_id: int) -> bool:
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cortex_tasks WHERE id = ?", (task_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    # ── Journal & Episodic Memory ─────────────────────────────────────────────

    def log_journal(self, summary: str, key_events: str = "", sentiment: str = "neutral") -> int:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        now_str = now.isoformat()
        with _DB_LOCK:
            conn = self._get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO cortex_journal (entry_date, summary, key_events, sentiment, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str, summary.strip(), key_events.strip(), sentiment.strip(), now_str))
                conn.commit()
                # Also index into knowledge nodes for semantic recall
                self.store_node(
                    title=f"Дневник за {date_str}",
                    content=f"События: {key_events}\nИтог: {summary}",
                    category="journal",
                    tags="journal, diary, events",
                    importance=3,
                )
                return cursor.lastrowid
            finally:
                conn.close()

    # ── Context Generation for Live Session ───────────────────────────────────

    def get_cortex_summary_for_prompt(self) -> str:
        """Builds a rich, concise context block of active tasks, goals, and core identity."""
        lines = []

        # Active tasks
        tasks = self.list_tasks(status="pending", limit=6)
        if tasks:
            lines.append("⚡ АКТИВНЫЕ ЗАДАЧИ И ПЛАНЫ:")
            for t in tasks:
                p_tag = f"[{t['priority'].upper()}]" if t['priority'] != 'normal' else ""
                proj = f" (Проект: {t['project']})" if t['project'] else ""
                due = f" [Срок: {t['due_date']}]" if t['due_date'] else ""
                lines.append(f"  • #{t['id']}: {t['task']}{proj}{due} {p_tag}".strip())

        # Key Projects
        projects = self.get_recent_nodes(category="projects", limit=4)
        if projects:
            lines.append("\n📁 ТЕКУЩИЕ ПРОЕКТЫ:")
            for p in projects:
                lines.append(f"  • {p['title']}: {p['content']}")

        # Key Notes / Habits
        notes = self.get_recent_nodes(category="notes", limit=5)
        if notes:
            lines.append("\n📌 ВАЖНЫЕ ЗАМЕТКИ И ПРИВЫЧКИ:")
            for n in notes:
                lines.append(f"  • {n['title']}: {n['content']}")

        if not lines:
            return ""

        return "\n[CORTEX KNOWLEDGE & CONTEXT]\n" + "\n".join(lines) + "\n"


# Global singleton instance
cortex = CortexEngine()
