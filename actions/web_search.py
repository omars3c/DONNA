import json
import re
import sys
import threading
import urllib.parse
import warnings
from pathlib import Path
from typing import Any, Optional

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
from bs4 import BeautifulSoup

# Ensure safe output on Windows / non-UTF-8 terminals
def _safe_log(msg: str) -> None:
    try:
        print(msg)
    except Exception:
        try:
            enc = sys.stdout.encoding or "utf-8"
            print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))
        except Exception:
            pass


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

_gemini_quota_failed = False


def _get_api_key() -> str:
    try:
        if API_CONFIG_PATH.exists():
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("gemini_api_key", "").strip()
    except Exception:
        pass
    return ""


# ── 1. Gemini Grounded Search (with model fallback) ──────────────────────────

from core.model_pool import model_pool, FAST_TEXT_MODEL, CANDIDATE_MODELS

GEMINI_MODELS = CANDIDATE_MODELS


def _gemini_search(query: str) -> str:
    global _gemini_quota_failed
    if _gemini_quota_failed:
        raise ValueError("Gemini API quota already exceeded in this session.")

    try:
        response = model_pool.generate_content(
            contents=query,
            config={"tools": [{"google_search": {}}]},
        )
        text = ""
        if response and response.candidates and len(response.candidates) > 0:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text
        text = text.strip()
        if text:
            return text
        raise ValueError("Empty response from grounded search.")
    except Exception as e:
        err_str = str(e).lower()
        if "resource_exhausted" in err_str or "429" in err_str or "quota" in err_str:
            _gemini_quota_failed = True
        raise ValueError(f"Gemini search failed: {e}") from e


# ── 2. Wikipedia API Search (Russian + English) ──────────────────────────────

def _wikipedia_search(query: str) -> Optional[dict]:
    """Fetches high-accuracy encyclopedic summary for entities/concepts."""
    clean_q = re.sub(
        r"^(кто так(ой|ая|ое|ие)|что так(ое|ой|ая|ие)|расскажи (мне )?(про|о)|найди информацию (про|о)|what is|who is)\s+",
        "",
        query,
        flags=re.IGNORECASE
    ).strip(" ?.!:,")
    if not clean_q:
        clean_q = query.strip(" ?.!:,")

    is_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]", clean_q))
    langs = ["ru", "en"] if is_cyrillic else ["en", "ru"]

    for lang in langs:
        try:
            url = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote(clean_q)}&limit=3&namespace=0&format=json"
            r = requests.get(url, headers={"User-Agent": "FridayAssistant/1.0"}, timeout=3)
            data = r.json()
            if data and len(data) > 1 and data[1]:
                title = data[1][0]
                sum_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
                sr = requests.get(sum_url, headers={"User-Agent": "FridayAssistant/1.0"}, timeout=3)
                sdata = sr.json()
                extract = sdata.get("extract", "").strip()
                if extract and len(extract) > 40:
                    page_url = sdata.get("content_urls", {}).get("desktop", {}).get("page", "")
                    return {
                        "title": sdata.get("title", title),
                        "snippet": extract,
                        "url": page_url,
                        "source": f"Wikipedia ({lang.upper()})",
                    }
        except Exception:
            continue
    return None


# ── 3. News RSS Fallbacks (Yandex/Dzen, RBC, Lenta, Google News) ─────────────

def _rss_news_search(query: str, max_results: int = 8) -> list[dict]:
    """Fetches high-quality news headlines from Yandex/Dzen, RBC, Lenta, and Google News RSS."""
    import xml.etree.ElementTree as ET
    results = []

    # 1. Yandex / Dzen Topics / Feed API
    try:
        q_lower = query.lower()
        rubric = "computers" if any(k in q_lower for k in ["ии", "ai", "нейросет", "интеллект", "технолог", "it", "софт"]) else "world"
        dzen_url = f"https://dzen.ru/api/v3/launcher/more?rubric={rubric}"
        dr = requests.get(dzen_url, headers=HEADERS, timeout=4)
        if dr.status_code == 200:
            ddata = dr.json()
            for it in ddata.get("items", []):
                t = it.get("title", "").strip()
                link = it.get("link", "").strip()
                summary = it.get("snippet", "") or it.get("text", "") or ""
                src = it.get("source_name", "") or "Дзен Новости"
                if t and link and not any(r["url"] == link for r in results):
                    results.append({
                        "title": t,
                        "snippet": summary,
                        "url": link,
                        "source": src,
                    })
                if len(results) >= max_results:
                    return results
    except Exception as e:
        _safe_log(f"[WebSearch] Dzen news fallback failed: {e}")

    # 2. Google News RSS Search
    try:
        safe_q = urllib.parse.quote(query)
        gn_url = f"https://news.google.com/rss/search?q={safe_q}&hl=ru&gl=RU&ceid=RU:ru"
        gr = requests.get(gn_url, headers=HEADERS, timeout=4)
        if gr.status_code == 200:
            root = ET.fromstring(gr.content)
            for item in root.findall(".//item"):
                t = item.find("title")
                l = item.find("link")
                s = item.find("source")
                title_text = t.text.strip() if t is not None and t.text else ""
                link_text = l.text.strip() if l is not None and l.text else ""
                src_text = s.text.strip() if s is not None and s.text else "Google News"
                if title_text and link_text:
                    results.append({
                        "title": title_text,
                        "snippet": "",
                        "url": link_text,
                        "source": src_text,
                    })
                if len(results) >= max_results:
                    return results
    except Exception as e:
        _safe_log(f"[WebSearch] Google News RSS fallback failed: {e}")

    # 3. RBC & Lenta RSS general fallback if still empty
    if not results:
        feed_urls = [
            ("https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "РБК"),
            ("https://lenta.ru/rss/news", "Лента.ру"),
        ]
        for f_url, f_name in feed_urls:
            try:
                fr = requests.get(f_url, headers=HEADERS, timeout=4)
                if fr.status_code == 200:
                    froot = ET.fromstring(fr.content)
                    for item in froot.findall(".//item"):
                        t = item.find("title")
                        l = item.find("link")
                        desc = item.find("description")
                        t_text = t.text.strip() if t is not None and t.text else ""
                        l_text = l.text.strip() if l is not None and l.text else ""
                        desc_text = desc.text.strip() if desc is not None and desc.text else ""
                        if t_text and l_text:
                            results.append({
                                "title": t_text,
                                "snippet": desc_text,
                                "url": l_text,
                                "source": f_name,
                            })
                        if len(results) >= max_results:
                            return results
            except Exception:
                continue

    return results


# ── 4. DuckDuckGo Search (via modern ddgs library with Fallback) ──────────────

def _ddg_library_search(query: str, max_results: int = 6) -> list[dict]:
    """Modern DDGS text search."""
    try:
        import ddgs
        is_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]", query))
        region = "ru-ru" if is_cyrillic else "wt-wt"

        with ddgs.DDGS() as client:
            raw_res = list(client.text(query, region=region, max_results=max_results))
            results = []
            for r in raw_res:
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
            if results:
                return results
    except Exception as e:
        _safe_log(f"[WebSearch] ddgs text search failed: {e}")

    return []


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    """Primary web search with ddgs and RSS fallback."""
    results = _ddg_library_search(query, max_results=max_results)
    if not results:
        # Fallback to Google / RSS news search if standard DDG is blocked
        results = _rss_news_search(query, max_results=max_results)
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """Dedicated news search: ddgs.news() -> RSS fallback (Yandex/Dzen, Google, RBC, Lenta)."""
    results = []
    is_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]", query))
    region = "ru-ru" if is_cyrillic else "wt-wt"

    # 1. Try modern ddgs news
    try:
        import ddgs
        with ddgs.DDGS() as client:
            raw_news = list(client.news(query, region=region, max_results=max_results))
            for r in raw_news:
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("url", ""),
                    "source": r.get("source", ""),
                })
        if results:
            return results
    except Exception as e:
        _safe_log(f"[WebSearch] ddgs.news() failed: {e}")

    # 2. Resilient RSS News Fallback (Yandex/Dzen + Google News + RBC + Lenta)
    rss_res = _rss_news_search(query, max_results=max_results)
    if rss_res:
        return rss_res

    # 3. Last resort: ddgs text query
    return _ddg_library_search(f"{query} новости", max_results=max_results)


# ── 4. Web Page Content Extractor (for Deep Research) ─────────────────────────

def _fetch_page_text(url: str, max_chars: int = 1200) -> str:
    """Fetches text content from a web page to provide detailed answers."""
    try:
        if not url or not url.startswith("http"):
            return ""
        r = requests.get(url, headers=HEADERS, timeout=3)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                tag.decompose()
            paragraphs = [p.get_text(strip=True) for p in soup.select("p") if len(p.get_text(strip=True)) > 40]
            if paragraphs:
                full = " ".join(paragraphs)
                return re.sub(r"\s+", " ", full)[:max_chars].strip()
    except Exception:
        pass
    return ""


# ── Formatters ───────────────────────────────────────────────────────────────

def _format_ddg(query: str, results: list[dict], wiki_entry: Optional[dict] = None) -> str:
    lines = []
    if wiki_entry:
        lines.append(f"[{wiki_entry.get('source', 'Wikipedia')}] {wiki_entry['title']}")
        lines.append(wiki_entry["snippet"])
        if wiki_entry.get("url"):
            lines.append(f"Источник: {wiki_entry['url']}\n")

    if results:
        lines.append(f"Результаты поиска по запросу: {query}\n")
        for i, r in enumerate(results, 1):
            if r.get("title"):
                lines.append(f"{i}. {r['title']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            if r.get("url"):
                lines.append(f"   Источник: {r['url']}")
            lines.append("")
    elif not wiki_entry:
        return f"По запросу «{query}» ничего не найдено."

    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"Свежих новостей по запросу «{query}» не найдено."

    lines = [f"Последние новости: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f" [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        if r.get("url"):
            lines.append(f"   Источник: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing Helper ──────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """Fetches current headlines via Gemini grounded search or DDG news."""
    global _gemini_quota_failed
    if not _gemini_quota_failed:
        try:
            response = model_pool.generate_content(
                contents=f"Current world and local news: {n} headlines in Russian. Numbered list, titles only.",
                config={"tools": [{"google_search": {}}]},
            )
            raw = ""
            if response and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        raw += part.text
            raw = raw.strip()
            if raw:
                headlines = []
                for line in raw.split("\n"):
                    line = line.strip()
                    if re.match(r"^[\d]+[.\)\-]", line):
                        clean = re.sub(r"^[\d]+[.\)\-]\s*", "", line)
                        clean = re.sub(r"^\*+\s*", "", clean).strip()
                        if len(clean) > 10:
                            headlines.append(clean)
                if headlines:
                    return headlines[:n], raw
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower() or "resource_exhausted" in str(e).lower():
                _gemini_quota_failed = True

    news_items = _ddg_news("главные новости сегодня", max_results=n)
    headlines = [item["title"] for item in news_items if item.get("title")]
    raw_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    return headlines[:n], raw_text


# ── Modes ────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search: Gemini Grounded -> DDG Search + Wikipedia."""
    try:
        return _gemini_search(query)
    except Exception as e:
        _safe_log(f"[WebSearch] Gemini search unavailable ({e}) -> using resilient fallback...")

    wiki_entry = _wikipedia_search(query)
    results = _ddg_search(query, max_results=5)

    return _format_ddg(query, results, wiki_entry=wiki_entry)


def _news(query: str) -> str:
    """News search: Gemini Grounded -> DDG News."""
    gemini_query = f"главные новости сегодня: {query}" if query else "топ мировых и российских новостей сегодня"
    try:
        return _gemini_search(gemini_query)
    except Exception as e:
        _safe_log(f"[WebSearch] Gemini news unavailable ({e}) -> using DDG news...")

    ddg_query = query if query else "новости сегодня"
    results = _ddg_news(ddg_query, max_results=8)
    return _format_news(ddg_query, results)


def _research(query: str) -> str:
    """Deep research: Gemini comprehensive explanation -> DDG + Web page content extraction."""
    research_query = (
        f"Подробная и структурированная информация по теме: {query}. "
        "Включи контекст, ключевые факты, актуальное состояние и важные детали."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        _safe_log(f"[WebSearch] Gemini research unavailable ({e}) -> deep crawling web...")

    wiki_entry = _wikipedia_search(query)
    results = _ddg_search(query, max_results=5)

    deep_snippets = []
    for r in results[:2]:
        url = r.get("url")
        if url:
            text = _fetch_page_text(url, max_chars=700)
            if text:
                deep_snippets.append(f"[Статья: {r.get('title', '')}]\n{text}\n(Источник: {url})")

    lines = []
    if wiki_entry:
        lines.append(f"[{wiki_entry.get('source', 'Wikipedia')}] {wiki_entry['title']}")
        lines.append(wiki_entry["snippet"])
        if wiki_entry.get("url"):
            lines.append(f"Источник: {wiki_entry['url']}\n")

    if deep_snippets:
        lines.append("[Подробные выдержки из источников]")
        lines.extend(deep_snippets)
        lines.append("")

    if results:
        lines.append("Дополнительные источники:")
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', '')} - {r.get('url', '')}")

    return "\n".join(lines).strip() if lines else f"Не удалось найти подробную информацию по запросу: {query}"


def _price(query: str) -> str:
    """Product price lookup."""
    price_query = f"актуальная цена {query} — сколько стоит сегодня в магазинах"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        _safe_log(f"[WebSearch] Gemini price lookup unavailable ({e}) -> DDG fallback...")

    results = _ddg_search(f"{query} цена купить стоимость", max_results=6)
    return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    """Comparison mode across items."""
    query = f"Сравни {', '.join(items)} по аспекту: {aspect}. Приведи конкретные характеристики, плюсы и минусы."
    try:
        return _gemini_search(query)
    except Exception as e:
        _safe_log(f"[WebSearch] Gemini comparison unavailable ({e}) -> DDG fallback...")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Сравнение: {aspect.upper()}", "-" * 40]
    for item in items:
        lines.append(f"\n* {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  - {r['snippet']}")
            if r.get("url"):
                lines.append(f"    Источник: {r['url']}")
    return "\n".join(lines)


# ── Public Entry Point ────────────────────────────────────────────────────────

def web_search(
    parameters: Optional[Any] = None,
    response=None,
    player=None,
    session_memory=None,
    **kwargs,
) -> str:
    if isinstance(parameters, str):
        parameters_str = parameters.strip()
        if parameters_str.startswith("{") and parameters_str.endswith("}"):
            try:
                parsed = json.loads(parameters_str)
                params = parsed if isinstance(parsed, dict) else {"query": parameters_str}
            except Exception:
                params = {"query": parameters_str}
        else:
            params = {"query": parameters_str}
    elif isinstance(parameters, dict):
        params = dict(parameters)
    else:
        params = {}

    for k, v in kwargs.items():
        if k not in params or params[k] is None:
            params[k] = v

    query = str(params.get("query") or "").strip()
    mode = str(params.get("mode") or "search").lower().strip()
    raw_items = params.get("items")
    if isinstance(raw_items, list):
        items: list[str] = [str(x) for x in raw_items]
    elif isinstance(raw_items, str) and raw_items.strip():
        items: list[str] = [x.strip() for x in raw_items.split(",") if x.strip()]
    else:
        items: list[str] = []
    aspect = str(params.get("aspect") or "general").strip() or "general"

    if not query and not items:
        return "Пожалуйста, укажите поисковый запрос."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        try:
            player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")
        except Exception:
            pass

    _safe_log(f"[WebSearch] mode={mode!r} query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)

    except Exception as e:
        _safe_log(f"[WebSearch] Error: {e}")
        try:
            res = _ddg_search(query, max_results=4)
            if res:
                return _format_ddg(query, res)
        except Exception:
            pass
        return f"Поиск завершился с ошибкой: {e}"
