"""
BackgroundMonitor — user-configured topic watching.
Checks DDG news once per day per topic; alerts D.O.N.N.A. when a new specific headline appears.
No crypto, no finance, no uninvited tracking.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


# ── Blocked categories (never monitor regardless of what user says) ────────────

_BLOCKED = {
    "bitcoin", "ethereum", "dogecoin", "solana", "binance",
    "nft", "blockchain", "defi", "altcoin", "memecoin", "coin", "token",
    "crypto", "kripto", "cripto", "krypto", "крипто", "仮想通貨", "暗号資産",
    "cryptocurrency",
}

def _is_blocked(topic: str) -> bool:
    t = topic.lower()
    return any(word in t for word in _BLOCKED)


# ── Slug / hash helpers ────────────────────────────────────────────────────────

def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower().strip())[:40].strip("_")

def _title_hash(title: str) -> str:
    return hashlib.md5(title.encode("utf-8", errors="ignore")).hexdigest()[:12]


# ── Memory I/O ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    from memory.memory_manager import load_memory
    data = load_memory().get("monitors", {})
    return data if isinstance(data, dict) else {}

def _save(monitors: dict) -> None:
    from memory.memory_manager import load_memory, MEMORY_PATH, _lock
    memory = load_memory()
    memory["monitors"] = monitors
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ── Generic hub/aggregator filter ──────────────────────────────────────────────

def _is_generic_hub(title: str, snippet: str) -> bool:
    """Returns True if the result is just a generic news hub landing page rather than a specific article."""
    t_low = title.lower()
    s_low = snippet.lower()
    hub_patterns = [
        "google news - ",
        " - latest",
        " - top stories",
        "latest artificial intelligence news & updates",
        "read full articles, watch videos",
        "explore the latest",
        "all the latest news",
        "trending news, latest updates",
    ]
    return any(p in t_low or p in s_low for p in hub_patterns)


# ── Public API ─────────────────────────────────────────────────────────────────

def add_monitor(topic: str) -> str:
    topic = topic.strip()
    if not topic:
        return "Please specify a topic to monitor."
    if _is_blocked(topic):
        return "I don't monitor crypto or financial topics."
    monitors = _load()
    slug = _slug(topic)
    if slug in monitors:
        return f"Already monitoring: {monitors[slug]['topic']}"
    monitors[slug] = {
        "topic":      topic,
        "added":      datetime.now().strftime("%Y-%m-%d"),
        "last_check": "",
        "last_hash":  "",
    }
    _save(monitors)
    print(f"[Monitor] ➕ Added: {topic}")
    return f"Now monitoring: {topic}"


def remove_monitor(topic: str) -> str:
    topic = topic.strip().lower()
    monitors = _load()
    slug = _slug(topic)
    if slug in monitors:
        label = monitors.pop(slug)["topic"]
        _save(monitors)
        return f"Stopped monitoring: {label}"
    for key, val in list(monitors.items()):
        if topic in val.get("topic", "").lower():
            label = monitors.pop(key)["topic"]
            _save(monitors)
            return f"Stopped monitoring: {label}"
    return f"Not found in monitored topics: {topic}"


def list_monitors() -> list[str]:
    return [v.get("topic", k) for k, v in _load().items()]


def check_all() -> list[dict]:
    """
    Run all pending topic checks.
    Returns a list of alert dicts:
    [
        {
            "topic": topic,
            "headline": title,
            "snippet": snippet,
            "source": source,
            "url": url,
            "formatted_alert": str
        }, ...
    ]
    """
    from actions.web_search import _ddg_news

    monitors = _load()
    if not monitors:
        return []

    today   = datetime.now().strftime("%Y-%m-%d")
    alerts  = []
    changed = False

    for slug, data in monitors.items():
        if data.get("last_check") == today:
            continue

        topic = data.get("topic", slug)
        try:
            results = _ddg_news(topic, max_results=8)
            if not results:
                monitors[slug]["last_check"] = today
                changed = True
                continue

            # Pick the best non-generic news article
            selected_item = None
            for r in results:
                t = r.get("title", "").strip()
                s = r.get("snippet", "").strip()
                if t and not _is_generic_hub(t, s):
                    selected_item = r
                    break
            if not selected_item and results:
                selected_item = results[0]

            title   = selected_item.get("title", "").strip()
            snippet = selected_item.get("snippet", "").strip()
            source  = selected_item.get("source", "").strip()
            url     = selected_item.get("url", "").strip()

            if not title:
                continue

            h = _title_hash(title)
            monitors[slug]["last_check"] = today
            changed = True

            if h == data.get("last_hash"):
                continue

            monitors[slug]["last_hash"] = h
            monitors[slug]["last_headline"] = title
            monitors[slug]["last_snippet"] = snippet
            monitors[slug]["last_url"] = url

            alert_lines = [
                f"[MONITOR_ALERT] Тема: {topic}",
                f"Заголовок: {title}",
            ]
            if snippet:
                alert_lines.append(f"Суть / Детали: {snippet}")
            if source:
                alert_lines.append(f"Источник: {source}")
            if url:
                alert_lines.append(f"Ссылка: {url}")

            formatted_text = "\n".join(alert_lines)
            alerts.append({
                "topic": topic,
                "headline": title,
                "snippet": snippet,
                "source": source,
                "url": url,
                "formatted_alert": formatted_text,
            })
            print(f"[Monitor] 🔔 New specific headline for '{topic}': {title[:70]}")

        except Exception as e:
            print(f"[Monitor] ⚠️ Check failed for '{topic}': {e}")

    if changed:
        _save(monitors)

    return alerts
