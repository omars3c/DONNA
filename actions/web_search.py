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

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
    "gemini-flash-latest",
]


def _gemini_search(query: str) -> str:
    global _gemini_quota_failed
    if _gemini_quota_failed:
        raise ValueError("Gemini API quota already exceeded in this session.")

    key = _get_api_key()
    if not key:
        raise ValueError("No Gemini API key available.")

    from google import genai

    client = genai.Client(api_key=key)

    last_err = None
    for model_name in GEMINI_MODELS:
        try:
            chat = client.chats.create(
                model=model_name,
                config={"tools": [{"google_search": {}}]},
            )
            response = chat.send_message(query)

            text = ""
            if response.candidates and len(response.candidates) > 0:
                first_cand = response.candidates[0]
                if first_cand.content and first_cand.content.parts:
                    for part in first_cand.content.parts:
                        if hasattr(part, "text") and part.text:
                            text += part.text

            text = text.strip()
            if text:
                return text
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "resource_exhausted" in err_str or "429" in err_str or "quota" in err_str:
                _gemini_quota_failed = True
                raise ValueError("Gemini API quota exhausted.") from e
            continue

    raise ValueError(f"Gemini search failed: {last_err}")


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


# ── 3. DuckDuckGo Search (Library + HTTP HTML/Lite Scraping) ─────────────────

def _ddg_library_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            try:
                from ddgs import DDGS  # type: ignore
            except ImportError:
                DDGS = None
        if DDGS is None:
            return []

        results = []
        is_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]", query))
        region = "ru-ru" if is_cyrillic else "wt-wt"

        for backend in ["auto", "html", "lite"]:
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(query, region=region, backend=backend, max_results=max_results):
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "url": r.get("href", ""),
                        })
                if results:
                    return results
            except Exception:
                continue
    except Exception:
        pass
    return []


def _ddg_lite_search(query: str, max_results: int = 6) -> list[dict]:
    """Direct HTTP POST to DuckDuckGo Lite without external library dependencies."""
    results = []
    try:
        url = "https://lite.duckduckgo.com/lite/"
        r = requests.post(url, data={"q": query}, headers=HEADERS, timeout=4)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for tr in soup.select("table tr"):
                link_el = tr.select_one("a.result-link")
                if link_el:
                    title = link_el.get_text(strip=True)
                    href_val = link_el.get("href", "")
                    url_link = str(href_val) if href_val else ""
                    if "duckduckgo.com/l/?uddg=" in url_link:
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url_link).query)
                        if "uddg" in parsed:
                            url_link = parsed["uddg"][0]
                    snippet = ""
                    nxt = tr.find_next_sibling("tr")
                    if nxt:
                        snippet = nxt.get_text(strip=True)
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": url_link,
                    })
                    if len(results) >= max_results:
                        break
    except Exception as e:
        _safe_log(f"[WebSearch] DDG Lite HTTP failed: {e}")
    return results


def _ddg_html_search(query: str, max_results: int = 6) -> list[dict]:
    """Direct HTTP POST to DuckDuckGo HTML."""
    results = []
    try:
        url = "https://html.duckduckgo.com/html/"
        r = requests.post(url, data={"q": query, "b": ""}, headers=HEADERS, timeout=4)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for el in soup.select(".result"):
                title_el = el.select_one(".result__title a")
                snippet_el = el.select_one(".result__snippet")
                if title_el and snippet_el:
                    title = title_el.get_text(strip=True)
                    href_val = title_el.get("href", "")
                    url_link = str(href_val) if href_val else ""
                    if "duckduckgo.com/l/?uddg=" in url_link:
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url_link).query)
                        if "uddg" in parsed:
                            url_link = parsed["uddg"][0]
                    snippet = snippet_el.get_text(strip=True)
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": url_link,
                    })
                    if len(results) >= max_results:
                        break
    except Exception as e:
        _safe_log(f"[WebSearch] DDG HTML HTTP failed: {e}")
    return results


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    """Robust multi-layer search: Lite HTTP -> HTML HTTP -> Library."""
    results = _ddg_lite_search(query, max_results=max_results)
    if not results:
        results = _ddg_html_search(query, max_results=max_results)
    if not results:
        results = _ddg_library_search(query, max_results=max_results)
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search with fast HTTP fallback."""
    results = []
    # Fast news query via Lite HTTP
    is_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]", query))
    news_q = f"{query} новости сегодня свежие" if is_cyrillic else f"{query} news today latest"
    results = _ddg_lite_search(news_q, max_results=max_results)

    if not results:
        try:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                try:
                    from ddgs import DDGS  # type: ignore
                except ImportError:
                    DDGS = None

            if DDGS is None:
                return results

            region = "ru-ru" if is_cyrillic else "wt-wt"
            with DDGS() as ddgs:
                for r in ddgs.news(query, region=region, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url": r.get("url", ""),
                        "source": r.get("source", ""),
                    })
        except Exception:
            pass

    if not results:
        results = _ddg_search(news_q, max_results=max_results)

    return results


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
            key = _get_api_key()
            if key:
                from google import genai
                client = genai.Client(api_key=key)
                for m in GEMINI_MODELS:
                    try:
                        chat = client.chats.create(
                            model=m,
                            config={"tools": [{"google_search": {}}]},
                        )
                        response = chat.send_message(
                            f"Current world and local news: {n} headlines in Russian. Numbered list, titles only."
                        )
                        raw = ""
                        if response.candidates and len(response.candidates) > 0:
                            first_cand = response.candidates[0]
                            if first_cand.content and first_cand.content.parts:
                                for part in first_cand.content.parts:
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
                            break
                        continue
        except Exception:
            pass

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
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query = str(params.get("query") or "").strip()
    mode = str(params.get("mode") or "search").lower().strip()
    items = params.get("items") or []
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
