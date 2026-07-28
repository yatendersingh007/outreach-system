"""Per-company research: layered Tavily search -> DEFAULT_MODEL summary ->
companies row. Cache-aware (reuse research < RESEARCH_FRESH_DAYS old).

Output feeds the ICP firm gate (firm_type, region, AUM) and the drafter
(summary, pain_points, trigger_events).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from .. import config, db, models
from . import icp_gate, search_client

# Aggregators / directories / media / CRE trade press: never a firm's own site.
_NON_FIRM_DOMAINS = {
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "crunchbase.com", "bloomberg.com", "wikipedia.org", "glassdoor.com",
    "indeed.com", "zoominfo.com", "dnb.com", "yelp.com", "youtube.com",
    "apollo.io", "pitchbook.com", "reuters.com", "sec.gov", "prnewswire.com",
    "businesswire.com", "medium.com", "wsj.com", "forbes.com", "google.com",
    "yahoo.com", "mapquest.com", "bbb.org", "manta.com", "buzzfile.com",
    "tiktok.com", "threads.net", "reddit.com", "prweb.com", "globenewswire.com",
    # CRE trade press / data aggregators (write ABOUT firms; not the firm site)
    "bisnow.com", "globest.com", "costar.com", "therealdeal.com",
    "commercialobserver.com", "rebusinessonline.com", "multihousingnews.com",
    "connectcre.com", "bizjournals.com", "loopnet.com", "crexi.com",
    "realtor.com", "zillow.com", "apartments.com", "yardimatrix.com",
    # generic single-token portals: a firm-name token (capital/partners/realty/
    # group/...) can substring-match these, so never treat them as a firm site
    "realty.com", "properties.com", "realestate.com", "capital.com",
    "partners.com", "group.com", "estate.com", "commercial.com",
}

# Two-label public suffixes so multi-part TLDs collapse correctly
# (e.g. grupofoo.com.mx -> grupofoo.com.mx, NOT com.mx). Mexico (.com.mx) is an
# in-scope discovery region, so this matters for Apollo domain hints.
_MULTI_TLDS = {
    "com.mx", "com.br", "com.ar", "com.co", "com.au", "com.sg", "com.hk",
    "co.uk", "org.uk", "co.nz", "co.jp", "co.in", "net.au", "com.pe",
}


def _norm_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _bare_domain(url: str) -> Optional[str]:
    try:
        net = urlparse(url).netloc.lower()
    except (ValueError, TypeError):
        return None
    if not net:
        return None
    net = net.split("@")[-1].split(":")[0]
    if net.startswith("www."):
        net = net[4:]
    return net or None


def _registrable(domain: str) -> str:
    parts = domain.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def _sld_label(domain: str) -> str:
    parts = domain.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_TLDS:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def extract_domain(name: str, results: list[dict]) -> Optional[str]:
    """Pick the firm's own website domain from search results.

    Prefer a URL whose domain label matches a normalized form of the firm name;
    otherwise the top-scored non-directory result. Returns bare registrable
    domain (e.g. 'monarchinvestment.com') or None.
    """
    nn = _norm_alnum(name)
    best_match = best_any = None
    best_match_score = best_any_score = -1.0
    for r in results:
        dom = _bare_domain(r.get("url", ""))
        if not dom:
            continue
        reg = _registrable(dom)
        if reg in _NON_FIRM_DOMAINS:
            continue
        score = float(r.get("score", 0) or 0)
        label = _norm_alnum(_sld_label(dom))
        matched = (
            len(label) >= 4
            and (label in nn or (len(nn) >= 4 and (nn.startswith(label) or nn in label)))
        )
        if matched and score > best_match_score:
            best_match, best_match_score = reg, score
        if score > best_any_score:
            best_any, best_any_score = reg, score
    return best_match or best_any


def _company_angles(name: str) -> tuple[list[str], list[str]]:
    # Anchor EVERY query with the full firm name AND real-estate context so a
    # same-name company in another industry does not pollute the results.
    ctx = "real estate OR multifamily OR commercial property"
    general = [
        f'"{name}" commercial real estate firm',
        # Dedicated FINANCIAL-SIZE query: the gate parks a firm when no AUM/size is
        # found, so search explicitly for the dollar figures that decide the gate
        # (AUM band + the $2B public-giant ceiling). This is the query that was
        # missing — a generic "overview" search rarely surfaces a size number.
        f'"{name}" ("assets under management" OR AUM OR "market cap" OR '
        f'"total assets" OR "portfolio value") (billion OR million OR "$")',
        f'"{name}" ({ctx}) assets under management portfolio value',
        f'"{name}" real estate investments asset classes headquarters',
    ]
    news = [
        f'"{name}" real estate (acquisition OR fund OR raise OR expansion)',
    ]
    return general, news


def _client_angles(name: str) -> tuple[list[str], list[str]]:
    # For the CLIENT-comprehension step: layer a broad unquoted query (so a close
    # name variant like "Gold Triangle" -> "Gold Triangle Property Management" is
    # surfaced) with RE-context variants and one exact-quoted query for precision.
    # This gives the premium model enough context to resolve the client confidently.
    general = [
        f'{name} real estate',
        f'{name} property management',
        f'{name} real estate investment firm',
        f'"{name}" commercial real estate firm',
    ]
    news = [
        f'{name} real estate (acquisition OR fund OR raise OR expansion)',
    ]
    return general, news


def _normalize_trigger_events(events) -> list[dict]:
    """Store trigger_events as a stable list of {"text","url"} dicts.

    The research prompt now asks for objects carrying a source URL, but be
    tolerant of the old shape (bare strings) and of stray model output: coerce
    each entry, drop anything without text, and only keep http(s) URLs.
    """
    out: list[dict] = []
    for e in events if isinstance(events, list) else []:
        if isinstance(e, dict):
            text = (e.get("text") or e.get("event") or "").strip()
            url = (e.get("url") or e.get("source") or "").strip()
        else:
            text, url = str(e or "").strip(), ""
        if not text:
            continue
        if not url.lower().startswith(("http://", "https://")):
            url = ""
        out.append({"text": text, "url": url})
    return out


def _research_failed(research: Optional[dict]) -> bool:
    """True if a cached research row is a stored FAILURE (its summary is the
    'research failed: ...' sentinel). Such rows must not be cache-served."""
    s = str((research or {}).get("summary") or "")
    return s.startswith("research failed")


_TYPE_RETRY_SYS = (
    "You classify a firm's business TYPE for a real-estate outreach pipeline. "
    "Infer the most likely type from the firm NAME and any research. Reply with a "
    "single JSON object only."
)


def _classify_firm_type_premium(name: str, parsed: dict,
                                results: list[dict]) -> tuple[Optional[str], models.Usage]:
    """One cheap PREMIUM call to place a firm type the DEFAULT model left as
    unknown/other (Part 2). Returns (firm_type|None, usage)."""
    hint = {
        "summary": parsed.get("summary"),
        "asset_classes": parsed.get("asset_classes"),
        "region": parsed.get("region"),
        "sample_sources": [r.get("title") for r in (results or [])[:6]],
    }
    prompt = (
        f"Firm name: {name}\n"
        f"Research so far (JSON): {json.dumps(hint, ensure_ascii=False)[:1400]}\n\n"
        "Classify this firm's TYPE, inferring the MOST LIKELY type from the NAME and "
        "research together. Name endings like 'Capital', 'Partners', 'Properties', "
        "'Realty', 'Investment Group', 'Real Estate', 'Residential', 'Communities' are "
        "strong real-estate-side signals even when research is thin. Only use an "
        "excluded type when clearly supported. Return JSON "
        '{"firm_type": "<one of: real estate | family office | private equity | '
        "property management | brokerage | lender | insurance | retailer | advisory | "
        'unknown>"}. Use "unknown" ONLY when name AND research give genuinely zero signal.'
    )
    try:
        parsed2, u = models.complete_json(prompt, system=_TYPE_RETRY_SYS,
                                          model=config.PREMIUM_MODEL,
                                          temperature=0.0, max_tokens=120)
        ft = (parsed2.get("firm_type") or "").strip().lower() if isinstance(parsed2, dict) else ""
        if ft and ft not in ("unknown", "other", ""):
            return ft, u
        return None, u
    except Exception:  # noqa: BLE001
        return None, models.Usage()


def _trim_results(results: list[dict], max_items: int = 12, max_chars: int = 800) -> list[dict]:
    trimmed = []
    for r in results[:max_items]:
        trimmed.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": (r.get("content", "") or "")[:max_chars],
        })
    return trimmed


def research_company(
    name: str,
    region_hint: Optional[str] = None,
    client_name: Optional[str] = None,
    competitor_of: Optional[int] = None,
    force: bool = False,
    is_client: bool = False,
    cancel_event=None,
) -> tuple[dict, dict, models.Usage]:
    """Research one firm. Returns (company_row, research_dict, usage).

    Reuses fresh cached research unless force=True. When `is_client` is True this
    is the CLIENT-comprehension step (the foundation of a run): it uses layered
    client queries, the PREMIUM model, and a synthesize-first comprehension prompt
    that also returns {resolved, firm_name, alternatives} for the ambiguity gate.
    Competitor research (is_client=False) is unchanged: DEFAULT model + the standard
    research prompt.
    """
    usage = models.Usage()

    if not force:
        cached = db.get_fresh_company(name)
        if cached:
            research = cached.get("research_raw") or {}
            # Never serve a cache row whose research FAILED (a transient 429/400/
            # empty poisoned it) OR was produced with ZERO web sources (a search
            # outage, e.g. Tavily quota HTTP 432 — name-only, low confidence).
            # Re-research instead: otherwise one bad call keeps a real firm
            # unverified for the whole 30-day fresh window and it can never
            # qualify once search recovers. (Regression audit finding 0.3a.)
            if _research_failed(research) or (not is_client and not (cached.get("source_count") or 0)):
                pass  # fall through and re-research
            # For the client, only reuse cache that already carries a resolution
            # (i.e. produced by this comprehension path); otherwise re-run premium.
            elif not is_client or "resolved" in research:
                return cached, research, usage

    general, news = _client_angles(name) if is_client else _company_angles(name)
    # A hard search outage (Tavily quota/auth) must not crash a whole run: degrade
    # to zero sources so this firm parks (source_count=0 rows are not cached fresh,
    # so they re-research once search recovers). The outage is announced once at
    # discovery + startup, not per firm.
    try:
        results = search_client.layered_search(general, news_angles=news, max_results_each=5)
    except search_client.SearchAPIError:
        results = []
    source_count = len(results)

    prompt_file = "client_comprehension.md" if is_client else "company_research.md"
    model = config.PREMIUM_MODEL if is_client else config.DEFAULT_MODEL
    prompt_tpl = config.load_prompt(prompt_file)
    prompt = prompt_tpl.format(
        name=name,
        region_hint=region_hint or "unknown",
        results=json.dumps(_trim_results(results), ensure_ascii=False),
    )
    errored = False
    try:
        # Retry an EMPTY/unparseable completion once, then escalate to the premium
        # model. The DEFAULT reasoning model (gpt-5-mini) intermittently returns
        # empty content on the research prompt (reasoning tokens exhaust the budget);
        # plain complete_json turned that into "research failed" -> parked, which
        # sent real firms (NADG, Lincoln, Alexandria, Armada, Seyon...) to the parked
        # pile despite findable data. Escalation rescues them. (Same fix discovery
        # already had via complete_json_retry.)
        parsed, u = models.complete_json_retry(prompt, model=model,
                                               temperature=0.2, max_tokens=1500)
        usage.add(u)
        if not isinstance(parsed, dict):
            # parse_json can return a syntactically-valid top-level LIST without
            # raising; treat that non-object output as a failed response.
            raise ValueError("model returned a non-object JSON value")
    except Exception as e:  # noqa: BLE001
        # Research failed: build a minimal row so the firm is still auditable. For
        # the client, fail OPEN (resolved=True below) so a transient error never
        # blocks a run; but the errored row is NOT cached (see last_researched_at)
        # so the next attempt re-runs premium instead of serving a bad foundation.
        errored = True
        parsed = {
            "summary": f"research failed: {e}",
            "firm_type": "unknown",
            "region": region_hint or "unknown",
            "asset_classes": [],
            "pain_points": [],
            "trigger_events": [],
            "aum": {"value_usd": None, "tag": "AUM_UNVERIFIED", "basis": "research error"},
            "confidence": 0,
        }

    if is_client:
        # Normalize the resolution fields so the gate can rely on real types.
        rv = parsed.get("resolved", True)
        parsed["resolved"] = rv if isinstance(rv, bool) else \
            str(rv).strip().lower() not in ("false", "no", "0", "none", "")
        fn = parsed.get("firm_name")
        parsed["firm_name"] = fn.strip() if isinstance(fn, str) and fn.strip() else name
        alts = parsed.get("alternatives")
        parsed["alternatives"] = alts if isinstance(alts, list) else []

    # Normalize the AUM number in place so the gate reads a float/None directly.
    # firm_type and AUM live in research_raw (no dedicated companies columns).
    aum = parsed.get("aum") or {}
    aum_value = aum.get("value_usd")
    try:
        aum_value = float(aum_value) if aum_value is not None else None
    except (TypeError, ValueError):
        aum_value = None
    # A successful model response can carry "aum": null (json mode has no sub-field
    # schema). setdefault does NOT replace an existing None, so rewrite the attribute
    # to a real dict — otherwise `parsed["aum"]["value_usd"] = ...` below crashes and
    # the firm is dropped instead of parked (review finding).
    if not isinstance(parsed.get("aum"), dict):
        parsed["aum"] = {}
    # Layer 2: no stated AUM -> estimate from unit count or square footage.
    if aum_value is None:
        est, basis = icp_gate.estimate_aum(parsed.get("unit_count"), parsed.get("sqft"))
        if est is not None:
            aum_value = est
            parsed["aum"]["tag"] = "AUM_ESTIMATED"
            parsed["aum"]["basis"] = basis
    parsed["aum"]["value_usd"] = aum_value

    # Part 2: if the DEFAULT model could NOT positively place the firm type
    # (unknown / other / unrecognized) on real research, make ONE cheap PREMIUM
    # reclassification call inferring the type from the NAME + research. This
    # rescues obvious RE firms ('X Capital/Partners/Properties') the small model
    # left as 'unknown'. Skipped for the client path and for failed research.
    if not is_client and not errored:
        placed = icp_gate._normalize_firm_type(parsed.get("firm_type"))
        if placed not in icp_gate.ALLOWED_FIRM_TYPES and placed not in icp_gate.EXCLUDED_FIRM_TYPES:
            ft2, u2 = _classify_firm_type_premium(name, parsed, results)
            usage.add(u2)
            if ft2:
                parsed["firm_type"] = ft2

    # Trigger events carry a source URL each ({"text","url"}); normalize the
    # model output to that stable shape before persisting (Item 5).
    parsed["trigger_events"] = _normalize_trigger_events(parsed.get("trigger_events"))

    # Abandoned by the per-firm timeout guard: do NOT persist. The caller has
    # already written a PARKED 'research timeout' marker (un-fresh) and a late
    # write here would clobber it, defeating the re-research + dropping the firm.
    if cancel_event is not None and cancel_event.is_set():
        return {}, parsed, usage

    row = db.upsert_company(
        name=name,
        domain=extract_domain(name, results),
        region=parsed.get("region"),
        summary=parsed.get("summary"),
        pain_points=parsed.get("pain_points") or [],
        trigger_events=parsed["trigger_events"],
        competitor_of=competitor_of,
        client_name=client_name,
        research_raw=parsed,
        research_confidence=parsed.get("confidence") or 0,
        source_count=source_count,
        tokens_used=usage.total_tokens,
        research_cost_usd=round(usage.cost_usd, 4),
        # ANY failed research — or a search that returned ZERO sources (Tavily
        # quota/outage: name-only, low confidence) — is left un-fresh (NULL) so it
        # is never cache-served; the next attempt re-researches instead of serving
        # a poisoned/name-only row for 30 days (regression audit finding 0.3a;
        # previously only the client path did this, so competitor 429/400/empty
        # AND search-outage rows poisoned the cache and blocked later qualification).
        last_researched_at=None if (errored or (source_count == 0 and not is_client))
        else datetime.now(timezone.utc),
    )
    return row, parsed, usage
