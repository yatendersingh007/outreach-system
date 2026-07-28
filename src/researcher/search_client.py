"""Tavily wrapper: layered queries (search + news + site angles) + extract.

Single provider, single key (HARD RULE: all research uses open-web search APIs;
research never visits LinkedIn). This is the clean interface a browser-agent
researcher could replace later without touching callers.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from .. import config

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"
_TIMEOUT = 40


class SearchError(RuntimeError):
    pass


class SearchAPIError(SearchError):
    """A HARD, reportable search-provider error (quota/auth/explicit error body).
    Carries the provider + real message so the caller can tell the operator the
    truth instead of silently reporting 'Found 0 candidates'."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"{provider} error: {message}")


def _error_message(r: "requests.Response") -> str:
    """Pull a human error string out of a Tavily error response body."""
    try:
        j = r.json()
        if isinstance(j, dict):
            d = j.get("detail")
            if isinstance(d, dict) and d.get("error"):
                return str(d["error"])
            if isinstance(d, str) and d.strip():
                return d.strip()
            if j.get("error"):
                return str(j["error"])
    except ValueError:
        pass
    return (r.text or f"HTTP {r.status_code}").strip()[:200]


def _post(url: str, payload: dict, retries: int = 3) -> dict:
    if not config.TAVILY_API_KEY:
        raise SearchAPIError("Tavily", "TAVILY_API_KEY is empty. Set it in .env.")
    payload = {"api_key": config.TAVILY_API_KEY, **payload}
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, timeout=_TIMEOUT)
            if r.status_code == 429:
                time.sleep(2 ** attempt + 1)
                continue
            # Client errors (quota 432, auth 401/403) are PERMANENT — do not
            # retry, do not swallow: raise the real message so the operator sees it.
            if 400 <= r.status_code < 500:
                raise SearchAPIError("Tavily", _error_message(r))
            r.raise_for_status()   # 5xx -> HTTPError -> retried
            data = r.json()
            if isinstance(data, dict) and (data.get("error")
                                           or isinstance(data.get("detail"), dict)):
                raise SearchAPIError("Tavily", _error_message(r))
            return data
        except SearchAPIError:
            raise
        except requests.RequestException as e:  # noqa: PERF203
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise SearchError(f"Tavily request failed: {last_err}")


def search(
    query: str,
    max_results: int = 8,
    topic: str = "general",       # 'general' or 'news'
    search_depth: str = "basic",  # 'basic' or 'advanced'
    include_raw_content: bool = False,
    days: Optional[int] = None,   # for topic='news'
) -> list[dict]:
    """Run one Tavily query. Returns normalized [{title, url, content, score}]."""
    payload: dict = {
        "query": query,
        "max_results": max_results,
        "topic": topic,
        "search_depth": search_depth,
        "include_raw_content": include_raw_content,
    }
    if days is not None:
        payload["days"] = days
    data = _post(SEARCH_URL, payload)
    out = []
    for r in data.get("results", []):
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("raw_content") or r.get("content", ""),
            "score": r.get("score", 0.0),
        })
    return out


def layered_search(angles: list[str], max_results_each: int = 6,
                   news_angles: Optional[list[str]] = None) -> list[dict]:
    """Run several query angles, merge, and dedupe by URL. Preserves best score.

    `angles` run as general search; `news_angles` run against the news topic
    (recent entrants / signals). Returns a single deduped result list.
    """
    seen: dict[str, dict] = {}

    def _absorb(results: list[dict]) -> None:
        for r in results:
            url = r.get("url")
            if not url:
                continue
            if url not in seen or r.get("score", 0) > seen[url].get("score", 0):
                seen[url] = r

    for q in angles:
        try:
            _absorb(search(q, max_results=max_results_each, topic="general"))
        except SearchAPIError:
            raise                       # HARD error (quota/auth): surface the truth
        except SearchError:
            continue                    # soft/transient: skip this one angle
    for q in (news_angles or []):
        try:
            _absorb(search(q, max_results=max_results_each, topic="news", days=180))
        except SearchAPIError:
            raise
        except SearchError:
            continue

    return sorted(seen.values(), key=lambda r: r.get("score", 0), reverse=True)


def extract(urls: list[str]) -> dict[str, str]:
    """Pull clean text for specific URLs. Returns {url: text}. Best-effort."""
    if not urls:
        return {}
    try:
        data = _post(EXTRACT_URL, {"urls": urls[:20]})
    except SearchError:
        return {}
    out = {}
    for r in data.get("results", []):
        out[r.get("url", "")] = r.get("raw_content", "")
    return out
