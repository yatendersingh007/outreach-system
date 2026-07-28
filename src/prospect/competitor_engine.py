"""Workflow A entry: /prospect "Client Firm Name".

Phase 1 (discovery): research the client firm, then paginated layered search for
ALL competing firms in the same CRE niche across North America. No hardcoded cap
(stops when two consecutive iterations add nothing new, or MAX_COMPETITORS).
Ends by handing a candidate list to the confirmation checkpoint.

Phase 2 (processing): for each CONFIRMED competitor, apply the ICP firm gate
FIRST (type + AUM $200M-$2B). Qualifying firms get full research + 2-4
management contacts + Apollo email enrichment + a personalized Gmail draft with
the case study attached. Disqualified firms are dropped; unverified-AUM firms
are parked. Progress is reported in stages throughout.

All research is open-web (Tavily). Research never visits LinkedIn.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import config, db, models
from ..drafting import gmail_drafter, pitch_deck
from ..enrichment import apollo
from ..researcher import company_research, exa_client, icp_gate, search_client


def _discovery_provider():
    """Competitor discovery uses Exa (semantic 'find similar firms') when
    EXA_API_KEY is set; otherwise falls back to Tavily. Key presence is the
    switch. Per-firm research always stays on Tavily (company_research)."""
    return exa_client if config.EXA_API_KEY else search_client

Progress = Callable[[str], None]

_SUFFIXES = re.compile(
    r"\b(llc|inc|inc\.|lp|l\.p\.|corp|corporation|co|company|group|capital|partners|"
    r"management|mgmt|realty|properties|property|holdings|ventures|advisors|"
    r"real estate|reit)\b",
    re.IGNORECASE,
)

# Hard exclusion filter (enforced in code; the prompt alone is not enough with a
# small model). These are brokerages, lenders/banks, insurers, and pure service
# firms. Match against the firm name and the model's "why" rationale.
_EXCLUDED_NAME_HINTS = (
    "cbre", "jll", "jones lang", "cushman", "wakefield", "colliers", "newmark",
    "knight frank", "marcus & millichap", "marcus and millichap", "savills",
    "avison young", "walker & dunlop", "walker and dunlop", "re/max", "remax",
    "keller williams", "svn", "nai ", "berkadia", "eastdil", "kidder mathews",
    "lee & associates", "transwestern", "matthews real estate",
    "apollo commercial real estate finance", "blackstone mortgage",
    "starwood property trust", "arbor realty", "ladder capital", "ready capital",
    "granite point", "kkr real estate finance", "jpmorgan", "jp morgan",
    "wells fargo", "morgan stanley", "goldman sachs", " ubs",
    # named retail/commercial BROKERAGES from the regression (name gives no
    # keyword signal, so hard-block them)
    "atlantic retail", "mackenzie commercial",
)

# Broker / lender / insurer / advisory / service keywords — matched on name+why
# (these do NOT appear in a genuine owner/investor rationale).
_EXCLUDE_KEYWORDS = (
    "brokerage", "broker", "real estate services", "commercial real estate services",
    "real estate advisory", "advisory", "advisor", "tenant representation", "tenant rep",
    "investment sales", "leasing services", "consulting", "appraisal", "valuation",
    "mortgage", "real estate finance", "capital markets", "lender", "lending",
    "debt fund", "financing", "funding", "insurance", "insurer", "title company",
    "wealth management", "asset allocation",
    "engineering", "coworking", "co-working", "co working",
)

# PURE third-party managers: excluded ONLY when the rationale shows no ownership/
# investment. An owner-operator that ALSO runs a third-party management line
# (Greystar, RPM Living) is KEPT — the owner-term override below protects it.
_PURE_MGR_KEYWORDS = (
    "third-party property management", "third party property management",
    "fee-based property management", "fee management",
)
_OWNER_TERMS = (
    "owner", "owns", "owned", "own and", "operate", "operator", "operating",
    "invest", "acquir", "portfolio", "developer", "develop", "sponsor",
    "vertically integrated", "landlord", "reit",
)

# Retailer / consumer-brand keywords — matched on the NAME ONLY. A retail-REAL-
# ESTATE owner's rationale legitimately names its retail/grocery TENANTS ("leased
# to grocery chains", "anchored by national retailers"), so matching these against
# the why would drop the very owners we must keep (Regency, Brixmor, Federal Realty).
_RETAILER_KEYWORDS_NAME = (
    "retailer", "retail chain", "retail corporation", "retail company",
    "e-commerce", "ecommerce", "consumer goods", "consumer brand", "department store",
    "convenience store", "grocery chain", "grocery retailer", "supermarket chain",
    "warehouse club", "quick service restaurant", "quick-service restaurant",
    "fast food", "apparel brand", "footwear brand",
)

# Well-known retailers / consumer brands, matched on NAME (word-boundary so a real
# firm name is never clipped). Bare "Target" is caught, but a negative lookahead
# spares RE firms like "Target Realty" / "Target Residential".
_RETAILER_NAME_RE = re.compile(
    r"\b(amazon|walmart|wal-mart|"
    r"target\b(?!\s+(?:realty|properties|property|capital|residential|communities|homes|partners|management|investment|trust|holdings|group))|"
    r"costco|kroger|ikea|7-eleven|seven[- ]eleven|trader joe|sephora|ulta|best buy|"
    r"home depot|lowe'?s|cvs|walgreens|publix|aldi|wegmans|safeway|whole foods|"
    r"starbucks|mcdonald'?s?|nike|adidas|macy'?s|nordstrom|kohl'?s|dollar general|"
    r"dollar tree|autozone)\b",
    re.IGNORECASE,
)


def _is_excluded(name: str, why: str) -> bool:
    """True if the candidate is NOT a real-estate owner/investor: a broker,
    lender, insurer, PURE third-party manager, retailer, or consumer brand.
    Backstops the prompt's exclusions (a small model can't be trusted alone).
    Owner-operators/investors — INCLUDING those that self-manage, run a
    third-party arm, or invest in RETAIL REAL ESTATE — are KEPT."""
    n = (name or "").lower()
    blob = f"{name or ''} {why or ''}".lower()
    if any(h in n for h in _EXCLUDED_NAME_HINTS):
        return True
    if _RETAILER_NAME_RE.search(name or ""):
        return True
    if any(k in n for k in _RETAILER_KEYWORDS_NAME):   # NAME only — see note above
        return True
    if any(k in blob for k in _EXCLUDE_KEYWORDS):
        return True
    # Pure third-party manager only if there's NO owner/investor signal anywhere.
    if any(k in blob for k in _PURE_MGR_KEYWORDS) and not any(t in blob for t in _OWNER_TERMS):
        return True
    return False


def _re_frame(term: str) -> str:
    """Ensure an asset-class / niche term carries real-estate context so a search
    angle never pulls in retailers/consumer brands. 'retail' -> 'retail real
    estate', 'office' -> 'office real estate'; terms already RE-explicit
    ('multifamily real estate', 'commercial property') pass through unchanged."""
    t = (term or "").strip()
    if not t:
        return "commercial real estate"
    if re.search(r"real estate|realty|\breit\b|propert(y|ies)", t, re.IGNORECASE):
        return t
    return f"{t} real estate"


def _print_progress(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# trigger_events normalization (each event carries a source URL; Item 5).
# New rows store [{"text","url"}]; old rows store bare strings — read both.
# ---------------------------------------------------------------------------
def _event_text(e) -> str:
    if isinstance(e, dict):
        return (e.get("text") or e.get("event") or "").strip()
    return str(e or "").strip()


def _event_url(e) -> str:
    if isinstance(e, dict):
        return (e.get("url") or e.get("source") or "").strip()
    return ""


def _event_texts(events) -> list[str]:
    if not isinstance(events, list):
        return []
    return [t for t in (_event_text(e) for e in events) if t]


# ---------------------------------------------------------------------------
# Live per-firm progress lines (Item 1) + no-email miss list (Item 2).
# ---------------------------------------------------------------------------
_VERDICT_EMOJI = {"QUALIFIED": "✅", "DISQUALIFIED": "❌", "PARKED": "◐"}


def _human_usd(v) -> Optional[str]:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:,.0f}"


def _human_int(v) -> Optional[str]:
    try:
        v = int(float(v))
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 1000:
        return f"{v / 1000:.0f}K"
    return str(v)


def _short_reason(reason: Optional[str], limit: int = 60) -> str:
    r = (reason or "").strip().replace("\n", " ")
    if not r:
        return "no reason given"
    return r if len(r) <= limit else r[:limit - 1].rstrip() + "…"


def _qualified_detail(aum_value, aum_tag, unit_count) -> str:
    """The parenthetical after a QUALIFIED verdict, e.g. ' (est. $1.0B, 15K units)'."""
    parts = []
    usd = _human_usd(aum_value)
    if usd:
        prefix = "est. " if (aum_tag or "").upper() == "AUM_ESTIMATED" else ""
        parts.append(f"{prefix}{usd}")
    units = _human_int(unit_count)
    if units:
        parts.append(f"{units} units")
    return f" ({', '.join(parts)})" if parts else ""


def _firm_progress_line(idx: int, total: int, res: dict) -> str:
    """One live line per firm as it finishes research+gate (Item 1)."""
    name = res.get("name", "?")
    tag = f"[{idx}/{total}]"
    if res.get("error"):
        return f"❌ {tag} {name} — failed ({_short_reason(res['error'])})"
    verdict = res.get("icp_result")
    if verdict == "QUALIFIED":
        detail = _qualified_detail(res.get("aum_value"), res.get("aum_tag"),
                                   res.get("unit_count"))
        return f"✅ {tag} {name} — QUALIFIED{detail}"
    if verdict == "PARKED":
        return f"◐ {tag} {name} — parked ({_short_reason(res.get('icp_reason'))})"
    return f"❌ {tag} {name} — disqualified ({_short_reason(res.get('icp_reason'))})"


def _format_misses(misses: list[dict]) -> str:
    """ONE aggregated 'no verified email' message across a run (Item 2)."""
    lines = ["No verified email (manual hunt needed):"]
    for m in misses:
        title = m.get("title") or "—"
        dom = f" ({m['domain']})" if m.get("domain") else ""
        lines.append(f"- {m.get('full_name', '?')} — {title}, {m.get('company', '?')}{dom}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source-link attribution after a draft (Item 5).
# ---------------------------------------------------------------------------
_CITE_STOP = {
    "the", "and", "for", "with", "its", "their", "from", "into", "that", "this",
    "real", "estate", "firm", "company", "new", "recent", "year", "will", "has",
    "have", "was", "were", "which", "about", "over", "than", "more",
    "2021", "2022", "2023", "2024", "2025", "2026",
}


def _cited_event(body: str, events):
    """Best-guess which trigger_event a draft body references: the event whose
    distinctive words most overlap the body. Returns the event (dict/str) or None."""
    if not isinstance(events, list) or not events:
        return None
    bl = (body or "").lower()
    best, best_score = None, 0
    for e in events:
        text = _event_text(e)
        if not text:
            continue
        words = {w for w in re.findall(r"[a-z0-9$]+", text.lower())
                 if len(w) >= 4 and w not in _CITE_STOP}
        score = sum(1 for w in words if w in bl)
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 1 else None


def _lead_first_name(lead: dict) -> str:
    fn = (lead.get("first_name") or "").strip()
    if fn:
        return fn
    full = (lead.get("full_name") or "").strip()
    return full.split(" ")[0] if full else "contact"


def _source_line(firm: str, lead: dict, body: str, events) -> str:
    """Plain-text Telegram attribution line for a draft (NOT part of the email
    body): what 'why now' claim the draft cites and its source URL (Item 5)."""
    who = _lead_first_name(lead)
    cited = _cited_event(body, events)
    if cited is None:
        return f"{firm} ({who}): (no specific claim cited)"
    label = _short_reason(_event_text(cited), 50)
    url = _event_url(cited)
    if url:
        return f"{firm} ({who}): draft cites {label} — source: {url}"
    return f"{firm} ({who}): draft cites {label} — source: (no link on file)"


# ---------------------------------------------------------------------------
# Tolerant AUM parsing for the operator /qualify command (Item 4).
# ---------------------------------------------------------------------------
_AUM_UNITS = {
    "trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3,
    "bn": 1e9, "bil": 1e9, "mm": 1e6, "mil": 1e6, "mn": 1e6,
    "t": 1e12, "b": 1e9, "m": 1e6, "k": 1e3,
}


def parse_aum(s) -> Optional[float]:
    """Parse a human-typed AUM into US dollars. Accepts '800M', '1.2B',
    '500000000', '$800M', '800 million', '1.2 bn', '~$1B', etc. Returns the
    dollar value, or None if no number is present."""
    if s is None:
        return None
    t = str(s).strip().lower()
    t = t.replace(",", "")   # join digit groups (1,250,000,000 -> 1250000000)
    for junk in ("$", "usd", "aum", "~", "approximately", "approx", "about"):
        t = t.replace(junk, " ")
    t = t.strip()
    if not t:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*([a-z]+)?", t)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "").strip()
    if unit:
        mult = None
        for u, factor in sorted(_AUM_UNITS.items(), key=lambda kv: -len(kv[0])):
            if unit == u or unit.startswith(u):
                mult = factor
                break
        num *= (mult if mult is not None else 1.0)
    elif num < 100_000:
        # A bare small number in this domain means millions ('800' -> $800M);
        # a large bare number ('500000000') is already dollars.
        num *= 1e6
    return num if num > 0 else None


def _normalize_name(name: str) -> str:
    n = name.lower()
    n = _SUFFIXES.sub("", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    return n


def _split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


# ---------------------------------------------------------------------------
# Phase 1: discovery
# ---------------------------------------------------------------------------
_DISCOVERY_REGIONS = (
    "Northeast US", "Southeast US", "Midwest US", "West Coast US",
    "Texas", "Canada", "Mexico",
)
_US_SUBREGIONS = ["Northeast US", "Southeast US", "Midwest US", "West Coast US", "Texas"]


def _expand_regions(target_regions: Optional[list[str]]) -> list[str]:
    """Expand a profile's coarse regions into query-friendly angles. 'USA' fans
    out into US sub-regions so volume stays high; Canada/Mexico pass through."""
    if not target_regions:
        return list(_DISCOVERY_REGIONS)
    out: list[str] = []
    for r in target_regions:
        rl = (r or "").strip().lower()
        if rl in ("usa", "us", "united states", "u.s.", "u.s"):
            out.extend(_US_SUBREGIONS)
        elif rl in ("north america", "na"):
            out.extend(list(_DISCOVERY_REGIONS))
        elif r:
            out.append(r)
    # dedupe preserving order
    seen, deduped = set(), []
    for r in out:
        if r not in seen:
            seen.add(r)
            deduped.append(r)
    return deduped or list(_DISCOVERY_REGIONS)


def _discovery_angles(client_name: str, niche: str, asset_classes: list[str],
                      target_regions: Optional[list[str]] = None) -> list[tuple[str, str]]:
    """Ordered (query, topic) angle list. Deterministic, finite, EXHAUSTIVE.

    Built from the client PROFILE (asset_classes x role, target_regions) plus
    base + size-targeted + news angles. Every angle runs every time.
    """
    # ICP framing is NON-NEGOTIABLE and applies on TOP of the profile: the profile
    # adds asset-class/region specificity, it never replaces the investment/ownership
    # framing. asset classes are RE-framed (retail -> retail real estate) so a bare
    # or consumer term can never leak in. `core` (first RE-framed asset class) is the
    # deterministic subject; the free-text `niche` is intentionally not used raw to
    # avoid clunky/generic queries. Never emit a bare "retail companies" / "property
    # management companies" angle.
    acs = [_re_frame(ac) for ac in (asset_classes or []) if ac][:3] or ["commercial real estate"]
    core = acs[0]
    regions = _expand_regions(target_regions)

    angles: list[tuple[str, str]] = [
        (f'{client_name} competitors real estate investment firms', "general"),
        (f'real estate investment and ownership firms similar to {client_name}', "general"),
        (f'top {core} investment firms United States', "general"),
        (f'{core} private equity and fund sponsors North America', "general"),
        (f'{core} owner operator firms United States', "general"),
        (f'{core} investment and management groups North America', "general"),
        (f'family office {core} investors North America', "general"),
    ]

    # Asset-class x ICP role (owner-operator, PE/fund sponsor, investment+mgmt group)
    for ac in acs:
        angles.append((f'{ac} owner operator firms United States', "general"))
        angles.append((f'{ac} private equity fund sponsor', "general"))
        angles.append((f'{ac} investment and management group North America', "general"))

    # Region-targeted x core, still ICP-framed (from the profile's target regions)
    for region in regions:
        angles.append((f'{core} investment firms {region}', "general"))

    # Size-targeted (surfaces mid-market/boutique that big-name queries miss)
    angles.append((f'mid-market {core} investment firms United States', "general"))
    angles.append((f'boutique {core} private equity North America', "general"))

    # News angles (recent entrants / signals) — framed toward owners/investors
    angles.append((f'new {core} investment firm fund launch North America', "news"))
    angles.append((f'{core} investment firm acquisition expansion United States', "news"))
    return angles


def resolve_client(client_name: str,
                   progress: Progress = _print_progress) -> tuple[dict, models.Usage]:
    """CLIENT comprehension (the foundation of a run): premium-model, synthesize-
    first identification of the client. Returns (research, usage): research
    includes `resolved` (bool), `firm_name`, and `alternatives` for the ambiguity
    gate; usage is the PREMIUM comprehension cost so the caller can roll it into
    the run's accounting (Item 6 — it used to be discarded, under-reporting spend).
    Persists + caches like research_company, so a later run_discovery/derive_profile
    for the same client reuses it (no duplicate premium call)."""
    progress(f"Researching {client_name}...")
    _row, research, usage = company_research.research_company(client_name, is_client=True)
    return research, usage


def derive_profile(client_name: str, progress: Progress = _print_progress) -> dict:
    """Research the client and return a PROPOSED profile — NOT saved. The caller
    (Telegram) presents it for human approval before saving + searching, so a
    wrong auto-derived profile can't poison the whole run. `type` maps to
    niche_description on save; the AUM band defaults to the global config band."""
    progress(f"Researching {client_name} to derive a profile for approval...")
    _row, research, _usage = company_research.research_company(client_name, is_client=True)
    acs = [a for a in (research.get("asset_classes") or []) if a] or ["commercial real estate"]
    ftype = (research.get("firm_type") or "real estate investment / management").strip()
    # Use the firm's own SPECIFIC service regions when comprehension found them
    # (e.g. "Maryland, Virginia, Washington D.C."), same as the saved-profile path
    # in run_discovery — otherwise this always fell back to the literal default,
    # regardless of what the firm actually serves.
    service_regions = [str(r).strip() for r in (research.get("service_regions") or [])
                       if r and str(r).strip()]
    return {
        "client_name": client_name,
        "type": ftype,                        # display + editable; saved as niche_description
        "asset_classes": acs,
        "target_regions": service_regions or ["North America"],
        "aum_floor": config.AUM_MIN_USD,
        "aum_ceiling": config.AUM_MAX_USD,
        "pitch_service_focus": "property accounting",
    }


def run_discovery(run_id: int, client_name: str, progress: Progress = _print_progress,
                  seed_usage: Optional[models.Usage] = None) -> list[dict]:
    """Research the client, discover competitor candidates, persist to the run.

    Uses the client PROFILE (client_profiles) for asset classes / target regions /
    niche. If no profile exists, researches the client, derives one, and saves it.

    `seed_usage` seeds this run's token/cost accounting with the PREMIUM client
    comprehension already spent by resolve_client (Item 6): the comprehension
    caches, so the research_company call below is a 0-token cache hit and the
    real premium cost would otherwise be lost."""
    usage = models.Usage()
    if seed_usage is not None:
        usage.add(seed_usage)
    progress(f"Researching {client_name}...")
    client_row, client_research, cu = company_research.research_company(client_name, is_client=True)
    usage.add(cu)

    # Fix 4: the SPECIFIC regions the comprehension surfaced (e.g. Maryland /
    # Virginia / D.C.) narrow discovery to the firm's real market instead of a
    # broad North-America sweep that dragged in national mega-firms. Guard the
    # type: a string value ("Maryland, Virginia") must NOT char-explode into
    # single-letter "regions".
    _sr = client_research.get("service_regions")
    service_regions = ([str(r).strip() for r in _sr if r and str(r).strip()]
                       if isinstance(_sr, list) else [])

    profile = db.get_client_profile(client_name)
    if profile:
        niche_bits = profile.get("asset_classes") or client_research.get("asset_classes") or []
        target_regions = profile.get("target_regions") or None
        niche = profile.get("niche_description") or (
            (f"{niche_bits[0]} " if niche_bits else "")
            + (client_research.get("firm_type") or "commercial real estate"))
        progress(f"Loaded profile: {niche} | regions {target_regions or 'North America'}")
    else:
        niche_bits = client_research.get("asset_classes") or []
        firm_type = client_research.get("firm_type") or "commercial real estate"
        niche = (f"{niche_bits[0]} " if niche_bits else "") + firm_type
        target_regions = service_regions or ["USA", "Canada", "Mexico"]
        db.upsert_client_profile(
            client_name,
            niche_description=(client_research.get("summary") or niche)[:500],
            asset_classes=niche_bits or ["commercial real estate"],
            target_regions=target_regions,
        )
        progress(f"Derived + saved new client profile: {niche}")

    niche_summary = client_research.get("summary") or niche
    progress(f"Understood: {niche_summary[:280]}")
    db.update_run(run_id, niche_summary=niche_summary, tokens_used=usage.total_tokens,
                  cost_usd=round(usage.cost_usd, 4))

    # Prefer the firm's specific service regions; fall back to the profile band /
    # broad North America only when none were surfaced.
    regions_for_query = service_regions or target_regions or ["North America"]
    disc = _discovery_provider()
    provider_name = "Exa" if disc is exa_client else "Tavily"
    region_label = ", ".join(regions_for_query) if regions_for_query else "North America"
    progress(f"Searching for competitors across {region_label} (via {provider_name})...")
    angles = _discovery_angles(client_name, niche, niche_bits, regions_for_query)
    known: dict[str, dict] = {}
    client_norm = _normalize_name(client_name)
    filtered_total = 0

    tpl = config.load_prompt("competitor_analysis.md")
    # EXHAUSTIVE + DETERMINISTIC: run EVERY angle chunk to completion, every run.
    # No adaptive early-exit (removed dry_iterations); only MAX_COMPETITORS caps.
    for i in range(0, len(angles), 3):
        if len(known) >= config.MAX_COMPETITORS:
            progress(f"Reached MAX_COMPETITORS ({config.MAX_COMPETITORS}); stopping search.")
            break
        chunk = angles[i:i + 3]
        general = [q for q, t in chunk if t == "general"]
        news = [q for q, t in chunk if t == "news"]
        try:
            results = disc.layered_search(general, news_angles=news, max_results_each=6)
        except search_client.SearchAPIError as e:
            # Fix 3: loud Exa -> Tavily fallback (once); Fix 2: report the TRUTH and
            # stop instead of silently reporting "Found 0 candidates".
            if disc is exa_client:
                progress(f"⚠ Exa failed ({e.message}) — falling back to Tavily. "
                         "Results may be weaker.")
                disc, provider_name = search_client, "Tavily"
                try:
                    results = disc.layered_search(general, news_angles=news, max_results_each=6)
                except search_client.SearchAPIError as e2:
                    progress(f"⚠ {e2}")
                    break
            else:
                progress(f"⚠ {e}")
                break
        if not results:
            continue

        trimmed = [{"title": r["title"], "url": r["url"], "content": (r["content"] or "")[:600]}
                   for r in results[:12]]
        prompt = tpl.format(
            client_name=client_name,
            client_niche=niche,
            asset_classes=", ".join(niche_bits) or "commercial real estate",
            client_region=client_research.get("region") or "North America",
            known_names=", ".join(k["name"] for k in known.values()) or "(none yet)",
            results=json.dumps(trimmed, ensure_ascii=False),
        )
        before = len(known)
        try:
            # temperature 0.0: extraction as deterministic as the model allows.
            # Fix 5: retry an empty response once, then escalate to PREMIUM before
            # giving up on a chunk (an empty completion is silent otherwise).
            parsed, u = models.complete_json_retry(prompt, model=config.DEFAULT_MODEL,
                                                   temperature=0.0, max_tokens=1500)
            usage.add(u)
            for comp in parsed.get("competitors", []):
                name = (comp.get("name") or "").strip()
                if not name:
                    continue
                norm = _normalize_name(name)
                if not norm or norm == client_norm or norm in known:
                    continue
                if _is_excluded(name, comp.get("why") or ""):
                    filtered_total += 1
                    continue  # broker/lender/insurer/service firm, not owner/operator
                known[norm] = {
                    "name": name,
                    "domain": comp.get("domain"),
                    "region": comp.get("region"),
                    "why": comp.get("why"),
                }
                if len(known) >= config.MAX_COMPETITORS:
                    break
        except models.LLMError as e:  # empty twice + premium escalation all failed
            progress(f"⚠ Extraction failed (retry + premium) — chunk skipped: {e}")
        except Exception as e:  # noqa: BLE001
            progress(f"(extraction issue this iteration: {e})")

        if len(known) > before:
            progress(f"Found {len(known)} candidates so far...")

    candidates = list(known.values())
    total_found = len(candidates)
    if total_found > config.DISCOVERY_REVIEW_MAX:
        candidates = candidates[:config.DISCOVERY_REVIEW_MAX]
        progress(f"Found {total_found} candidates; presenting the top "
                 f"{config.DISCOVERY_REVIEW_MAX} for review (raise DISCOVERY_REVIEW_MAX "
                 f"in .env to see more).")
    db.update_run(run_id, candidates=candidates, status="awaiting_confirmation",
                  tokens_used=usage.total_tokens, cost_usd=round(usage.cost_usd, 4))
    tail = f" (filtered {filtered_total} brokers/lenders/service firms)" if filtered_total else ""
    progress(f"Found {len(candidates)} candidates.{tail}")
    return candidates


# ---------------------------------------------------------------------------
# Contact discovery (open-web, never LinkedIn)
# ---------------------------------------------------------------------------
_CONTACTS_SYS = (
    "You extract real named executives from web search results. Only use names "
    "that explicitly appear in the provided results. Never invent a person."
)


def _find_contacts(company_name: str) -> tuple[list[dict], models.Usage]:
    usage = models.Usage()
    angles = [
        f'"{company_name}" (CFO OR "Chief Financial Officer" OR "VP Finance" OR '
        f'Controller OR "Managing Director" OR "Managing Partner" OR "Head of Finance")',
        f'"{company_name}" leadership team finance executives',
    ]
    try:
        results = search_client.layered_search(angles, max_results_each=6)
    except search_client.SearchAPIError:
        results = []            # search outage -> no contacts this firm (announced elsewhere)
    if not results:
        return [], usage
    trimmed = [{"title": r["title"], "url": r["url"], "content": (r["content"] or "")[:700]}
               for r in results[:12]]
    prompt = (
        f"Firm: {company_name}\n"
        "Target roles: CFO, VP Finance / Finance Director, Controller, Managing "
        "Director / Managing Partner, Head of Finance / Head of Operations.\n"
        f"Search results (JSON): {json.dumps(trimmed, ensure_ascii=False)}\n\n"
        'Return JSON {"contacts":[{"full_name":"...","title":"..."}]}. Include a '
        "person ONLY if BOTH their name and a target-role title appear in the "
        "results. Max 4. If none, return an empty list."
    )
    try:
        parsed, u = models.complete_json(prompt, system=_CONTACTS_SYS,
                                         model=config.DEFAULT_MODEL,
                                         temperature=0.1, max_tokens=800)
        usage.add(u)
    except Exception:  # noqa: BLE001
        return [], usage

    contacts = []
    for c in parsed.get("contacts", [])[:config.TARGET_CONTACTS_PER_FIRM[1]]:
        name = (c.get("full_name") or "").strip()
        title = (c.get("title") or "").strip()
        if not name:
            continue
        if not any(h in title.lower() for h in config.MGMT_TITLE_HINTS):
            continue
        contacts.append({"full_name": name, "title": title})
    return contacts, usage


# ---------------------------------------------------------------------------
# Phase 2: per-competitor processing (research -> gate -> contacts)
# ---------------------------------------------------------------------------
def _process_one(candidate: dict, run_id: int, client_name: str,
                 client_company_id: Optional[int],
                 aum_floor: Optional[float] = None,
                 aum_ceiling: Optional[float] = None,
                 cancel_event=None) -> dict:
    """Research + GATE one firm (no contacts/leads here). Returns a summary
    including company_id and the AUM/units used for the live progress line.

    Contact discovery, Apollo enrichment and drafting for QUALIFIED firms are
    owned by `process_qualified_company` — one copy of that logic, shared by the
    batch pipeline and by the operator /qualify command.

    `cancel_event` (set by the per-firm timeout guard) makes this a NO-OP once the
    caller has abandoned it: research is not persisted and the gate verdict is not
    written, so a late-finishing worker can't clobber the PARKED 'research timeout'
    marker (Fix 7 review finding).

    Never raises: a single-firm failure is captured and reported, not fatal.
    aum_floor/aum_ceiling come from the client profile (default 200M/2B).
    """
    name = candidate["name"]
    out = {"name": name, "company_id": None, "icp_result": None, "icp_reason": None,
           "aum_value": None, "aum_tag": None, "unit_count": None,
           "error": None, "tokens": 0}
    try:
        # Layer 0: known public/institutional giant OR mega asset-manager/PE/REIT
        # -> disqualify by NAME WITHOUT spending a research call (zero API cost).
        # (A structured NYSE/NASDAQ listing is also caught post-research in the gate.)
        if icp_gate.is_public_giant(name):
            row = db.upsert_company(
                name=name, client_name=client_name, competitor_of=client_company_id,
                research_raw={"public_giant": True},
                last_researched_at=datetime.now(timezone.utc),
            )
            reason = "public/institutional/mega-firm, above $2B ceiling"
            db.set_company_icp(row["id"], "DISQUALIFIED", reason, None)
            out["company_id"] = row["id"]
            out["icp_result"] = "DISQUALIFIED"
            out["icp_reason"] = reason
            return out

        row, research, usage = company_research.research_company(
            name, region_hint=candidate.get("region"), client_name=client_name,
            competitor_of=client_company_id, cancel_event=cancel_event,
        )
        # Abandoned by the per-firm timeout: research_company already skipped its
        # write; do NOT write the gate verdict either. The caller owns the marker.
        if cancel_event is not None and cancel_event.is_set():
            return out
        out["tokens"] += usage.total_tokens
        out["company_id"] = row["id"]

        aum = research.get("aum") or {}
        out["aum_value"] = aum.get("value_usd")
        out["aum_tag"] = aum.get("tag")
        out["unit_count"] = research.get("unit_count")

        gate = icp_gate.gate_company(
            firm_type=research.get("firm_type"),
            region=research.get("region") or row.get("region"),
            aum_value_usd=aum.get("value_usd"),
            aum_tag=aum.get("tag"),
            name=name,
            research_raw=research,
            aum_basis=aum.get("basis"),
            aum_floor=aum_floor,
            aum_ceiling=aum_ceiling,
            source_count=row.get("source_count"),   # distinguishes 'no web sources' parks
        )
        db.set_company_icp(row["id"], gate["icp_result"], gate["icp_reason"],
                           gate.get("aum_tag"))
        out["icp_result"] = gate["icp_result"]
        out["icp_reason"] = gate["icp_reason"]
        if gate.get("aum_tag"):
            out["aum_tag"] = gate["aum_tag"]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def process_qualified_company(company_id: int, run_id: Optional[int] = None,
                              progress: Progress = _print_progress,
                              do_draft: bool = True,
                              misses: Optional[list] = None,
                              service=None) -> tuple[int, int, int]:
    """The qualified-firm funnel TAIL for ONE company, in one place: discover
    contacts -> create leads -> Apollo email enrichment -> Gmail draft (with a
    source-link line per draft). Returns (contacts_found, emails_enriched,
    drafts_created).

    The batch pipeline (run_processing) and the operator /qualify command BOTH
    call this — a single copy of the logic. If `misses` is provided it is
    appended with {full_name,title,company,domain} for each qualified contact
    Apollo could not find an email for, so the caller can send ONE aggregated
    'No verified email' message across the whole run.
    """
    company = db.get_company_by_id(company_id)
    if not company:
        progress(f"(skip: company id {company_id} not found)")
        return (0, 0, 0)
    name = company["name"]

    # 1) Contacts -> qualified leads.
    contacts, _cu = _find_contacts(name)
    if not contacts:
        progress(f"{name}: no management contacts found on the open web.")
        return (0, 0, 0)

    signals_text = "; ".join(_event_texts(company.get("trigger_events")))
    icp_reason = company.get("icp_reason")
    lead_ids: list[int] = []
    for c in contacts:
        first, last = _split_name(c["full_name"])
        lead = db.create_lead(
            company_id=company_id, full_name=c["full_name"], company=name,
            first_name=first, last_name=last, designation=c["title"],
        )
        if not lead:
            continue
        db.transition_lead(
            lead["id"], "qualified", "researcher",
            detail={"icp_reason": icp_reason},
            icp_result="QUALIFIED", icp_reason=icp_reason,
            company_summary=company.get("summary"),
            recent_signals=signals_text,
        )
        lead_ids.append(lead["id"])
    contacts_found = len(lead_ids)
    if not lead_ids:
        return (0, 0, 0)

    # 2) Apollo email enrichment (sequential people/match, domain hint included).
    emails_enriched = 0
    leads = _load_leads(lead_ids)
    if leads:
        try:
            r = apollo.enrich_leads(leads, progress=progress)
            emails_enriched = r["enriched"]
        except apollo.ApolloUnavailable as e:
            progress(f"Enrichment skipped: {e}")

    # Miss list (Item 2): reload to see which contacts now have an email.
    refreshed = _load_leads(lead_ids)
    if misses is not None:
        for lead in refreshed:
            if not lead.get("email"):
                misses.append({
                    "full_name": lead.get("full_name"),
                    "title": lead.get("designation"),
                    "company": name,
                    "domain": lead.get("domain") or company.get("domain"),
                })

    # 3) Drafting (+ source-link line per draft, Item 5).
    drafts_created = 0
    if do_draft:
        drafts_created = _draft_company(company, lead_ids, progress, service=service)

    return (contacts_found, emails_enriched, drafts_created)


# ---------------------------------------------------------------------------
# Operator overrides for PARKED firms (Item 4): /qualify + /disqualify.
# ---------------------------------------------------------------------------
def manual_qualify(company_id: int, aum_value: float,
                   progress: Progress = _print_progress, do_draft: bool = True) -> dict:
    """Operator override: an AUM has been manually verified for a PARKED firm.
    Persist it (AUM_CONFIRMED into research_raw), re-run the ICP gate, and — if
    it now qualifies — run the full qualified-firm tail (contacts -> Apollo ->
    draft) via the shared process_qualified_company. Out-of-band AUM disqualifies.

    Returns a result dict with a ready-to-send `message`. The caller is expected
    to have already confirmed the firm is PARKED and looked it up by id.
    """
    company = db.get_company_by_id(company_id)
    if not company:
        return {"verdict": "ERROR", "message": "Firm not found.",
                "contacts": 0, "emails": 0, "drafts": 0}
    name = company["name"]
    research = dict(company.get("research_raw") or {})
    human = _human_usd(aum_value) or f"${aum_value:,.0f}"
    basis = f"manually verified by operator: {human}"

    # 1) Store the confirmed AUM in research_raw (no dedicated aum column).
    research["aum"] = {"value_usd": float(aum_value), "tag": "AUM_CONFIRMED",
                       "basis": basis}
    db.upsert_company(name=name, research_raw=research)

    # 2) Re-run the gate with the confirmed number + the client's band if known.
    profile = db.get_client_profile(company.get("client_name") or "") or {}
    aum_floor = float(profile["aum_floor"]) if profile.get("aum_floor") is not None else None
    aum_ceiling = float(profile["aum_ceiling"]) if profile.get("aum_ceiling") is not None else None
    gate = icp_gate.gate_company(
        firm_type=research.get("firm_type"),
        region=research.get("region") or company.get("region"),
        aum_value_usd=float(aum_value),
        aum_tag="AUM_CONFIRMED",
        name=name, research_raw=research, aum_basis=basis,
        aum_floor=aum_floor, aum_ceiling=aum_ceiling,
    )

    if gate["icp_result"] == "QUALIFIED":
        db.set_company_icp(company_id, "QUALIFIED", basis, "AUM_CONFIRMED")
        db.record_operator_event("qualified", {
            "company_id": company_id, "name": name,
            "aum_usd": float(aum_value), "action": "qualify",
        })
        misses: list[dict] = []
        cf, ee, dc = process_qualified_company(
            company_id, progress=progress, do_draft=do_draft, misses=misses)
        if misses:
            progress(_format_misses(misses))
        msg = (f"{name}: QUALIFIED at {human} — "
               f"{cf} contact{'' if cf == 1 else 's'}, "
               f"{ee} email{'' if ee == 1 else 's'}, "
               f"{dc} draft{'' if dc == 1 else 's'}.")
        return {"verdict": "QUALIFIED", "message": msg,
                "contacts": cf, "emails": ee, "drafts": dc}

    # Out of band -> disqualify, but keep the operator's verified number on record.
    reason = f"{basis}; {gate['icp_reason']}"
    db.set_company_icp(company_id, "DISQUALIFIED", reason,
                       gate.get("aum_tag") or "AUM_CONFIRMED")
    db.record_operator_event("disqualified", {
        "company_id": company_id, "name": name,
        "aum_usd": float(aum_value), "action": "qualify->out_of_band",
    })
    msg = (f"{name}: {human} is outside the ICP band — {gate['icp_reason']}. "
           "Marked disqualified.")
    return {"verdict": "DISQUALIFIED", "message": msg,
            "contacts": 0, "emails": 0, "drafts": 0}


def manual_disqualify(company_id: int, progress: Progress = _print_progress) -> dict:
    """Operator override: reject a PARKED firm outright. Returns a result dict
    with a ready-to-send `message`. Caller confirms the firm is PARKED first."""
    company = db.get_company_by_id(company_id)
    if not company:
        return {"verdict": "ERROR", "message": "Firm not found."}
    name = company["name"]
    reason = "manually rejected by operator"
    db.set_company_icp(company_id, "DISQUALIFIED", reason, company.get("aum_tag"))
    db.record_operator_event("disqualified", {
        "company_id": company_id, "name": name, "action": "disqualify",
    })
    return {"verdict": "DISQUALIFIED", "message": f"{name}: DISQUALIFIED ({reason})."}


def _run_with_timeout(fn, timeout_s: float, *args):
    """Run fn(*args, cancel_event=...) with a HARD wall-clock timeout. On timeout,
    raise concurrent.futures.TimeoutError and ABANDON the worker (shutdown(wait=
    False)) so the caller advances immediately — a slow/hung firm can never block
    the next one. Because a running thread cannot be force-cancelled, we ALSO set
    `cancel_event`: the worker checks it and skips its (now-late) DB writes, so it
    can't clobber the PARKED 'research timeout' marker the caller writes. `fn` must
    accept a `cancel_event` keyword."""
    cancel_event = threading.Event()
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(fn, *args, cancel_event=cancel_event).result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        cancel_event.set()      # the abandoned worker must NOT persist its late result
        raise
    finally:
        ex.shutdown(wait=False)


def _park_research_timeout(cand: dict, client_name: str,
                           client_company_id: Optional[int]) -> None:
    """Persist a firm that blew the per-firm time budget as PARKED 'research
    timeout' (left un-fresh so it re-researches next run). Never raises."""
    try:
        row = db.upsert_company(
            name=cand["name"], client_name=client_name,
            competitor_of=client_company_id, research_raw={"timeout": True},
            last_researched_at=None,
        )
        db.set_company_icp(row["id"], "PARKED", "research timeout", "AUM_UNVERIFIED")
    except Exception:  # noqa: BLE001
        pass


def run_processing(run_id: int, client_name: str, candidates: list[dict],
                   progress: Progress = _print_progress, do_draft: bool = True) -> dict:
    """Gate + research + enrich + draft the confirmed competitor list.

    Phase A researches + gates every firm (one live line per firm as it lands).
    Phase B runs each QUALIFIED firm through process_qualified_company (contacts
    -> Apollo -> draft), the SAME function /qualify uses.
    """
    progress(f"Proceeding with {len(candidates)} firms.")
    counts = {"researched": 0, "qualified": 0, "disqualified": 0, "parked": 0,
              "contacts": 0, "emails": 0, "drafts": 0, "failed": 0}
    total_tokens = 0

    client_row = db.get_company_by_name(client_name)
    client_company_id = client_row["id"] if client_row else None
    qualified_company_ids: list[int] = []

    # AUM band from the client profile (defaults to config 200M/2B).
    profile = db.get_client_profile(client_name) or {}
    aum_floor = float(profile["aum_floor"]) if profile.get("aum_floor") is not None else None
    aum_ceiling = float(profile["aum_ceiling"]) if profile.get("aum_ceiling") is not None else None

    # Fix 7: whole-run ceiling. Past it, stop cleanly and save partial results.
    deadline = time.monotonic() + config.RUN_TIMEOUT_MINUTES * 60
    timed_out = False

    # Phase A: research + gate, one firm at a time. Each firm runs under a HARD
    # per-firm budget (Fix 7): if it exceeds FIRM_TIMEOUT_SECONDS it is PARKED
    # "research timeout" and the loop moves on — the slow firm's worker is
    # abandoned (see _run_with_timeout), so it can NEVER block or cascade into the
    # next firm, even at RESEARCH_WORKERS=1. One live progress line per firm (Item 1).
    total = len(candidates)
    done = 0
    for cand in candidates:
        if time.monotonic() > deadline:
            timed_out = True
            progress(f"⚠ Run timed out after {config.RUN_TIMEOUT_MINUTES}m at firm "
                     f'{done}/{total}. Partial results saved. /status "{client_name}" '
                     "for detail.")
            break
        try:
            res = _run_with_timeout(_process_one, config.FIRM_TIMEOUT_SECONDS, cand,
                                    run_id, client_name, client_company_id,
                                    aum_floor, aum_ceiling)
        except concurrent.futures.TimeoutError:
            _park_research_timeout(cand, client_name, client_company_id)
            res = {"name": cand["name"], "company_id": None, "icp_result": "PARKED",
                   "icp_reason": "research timeout", "aum_value": None,
                   "aum_tag": None, "unit_count": None, "error": None, "tokens": 0}
        done += 1
        counts["researched"] += 1
        total_tokens += res.get("tokens", 0)

        if res["error"]:
            counts["failed"] += 1
        elif res["icp_result"] == "QUALIFIED":
            counts["qualified"] += 1
            if res.get("company_id"):
                qualified_company_ids.append(res["company_id"])
        elif res["icp_result"] == "PARKED":
            counts["parked"] += 1
        else:
            counts["disqualified"] += 1

        progress(_firm_progress_line(done, total, res))
        time.sleep(0.3)  # gentle pacing so Telegram doesn't rate-limit the burst

    db.update_run(run_id, counts=counts, tokens_used=total_tokens)

    # Phase B: contacts -> Apollo -> draft for each qualified firm (one function,
    # shared with /qualify). Resolve the Gmail service ONCE and reuse it. If auth
    # fails, report it ONCE here and disable drafting for the per-firm calls so
    # _draft_company doesn't re-attempt get_service (and re-warn) for every firm.
    misses: list[dict] = []
    service = None
    draft_ok = do_draft
    if do_draft and qualified_company_ids:
        try:
            service = gmail_drafter.get_service(interactive=False)
        except Exception as e:  # noqa: BLE001
            progress(f"Gmail not authorized, drafts skipped: {e}")
            draft_ok = False

    for cid in qualified_company_ids:
        if time.monotonic() > deadline:
            if not timed_out:
                timed_out = True
                progress(f"⚠ Run timed out after {config.RUN_TIMEOUT_MINUTES}m during "
                         f'drafting. Partial results saved. /status "{client_name}" for detail.')
            break
        cf, ee, dc = process_qualified_company(
            cid, run_id=run_id, progress=progress, do_draft=draft_ok,
            misses=misses, service=service,
        )
        counts["contacts"] += cf
        counts["emails"] += ee
        counts["drafts"] += dc

    # Item 2: ONE aggregated 'no verified email' message (skip if all matched).
    if misses:
        progress(_format_misses(misses))

    db.update_run(run_id, counts=counts, status="done", tokens_used=total_tokens)
    progress(
        "Done. "
        f"Researched {counts['researched']}, qualified {counts['qualified']}, "
        f"disqualified {counts['disqualified']}, parked {counts['parked']}, "
        f"failed {counts['failed']}. Contacts {counts['contacts']}, "
        f"emails {counts['emails']}/{counts['contacts']}, drafts {counts['drafts']}."
    )
    return counts


def _load_leads(lead_ids: list[int]) -> list[dict]:
    """Load leads with their company's domain joined on, so Apollo enrichment
    always gets the domain hint (raises match hit rate)."""
    if not lead_ids:
        return []
    with db.cursor() as cur:
        cur.execute(
            "SELECT l.*, c.domain AS domain "
            "FROM leads l JOIN companies c ON c.id = l.company_id "
            "WHERE l.id = ANY(%s) ORDER BY l.id",
            (lead_ids,),
        )
        return cur.fetchall()


def _leads_to_draft(lead_ids: list[int]) -> list[dict]:
    """Qualified, email-bearing leads restricted to THIS run's own lead ids.

    Scoping by lead id (the leads created/qualified during this run) is the only
    reliable run boundary: company rows are shared across clients (UNIQUE name)
    and companies.client_name is stale on research cache hits, so a client_name
    filter can drop this run's leads or leak another client's. Enrichment
    already scopes by these ids; drafting must match.
    """
    if not lead_ids:
        return []
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM leads WHERE id = ANY(%s) "
            "AND state = 'qualified' AND email IS NOT NULL ORDER BY id",
            (lead_ids,),
        )
        return cur.fetchall()


def _draft_company(company: dict, lead_ids: list[int], progress: Progress,
                   service=None) -> int:
    """Create Gmail drafts for ONE company's enriched leads (scoped to lead_ids).
    Emits the deck-confidence banner AND a plain-text source-link line per draft
    (Item 5). `service` may be reused across firms to avoid re-auth per firm."""
    leads = _leads_to_draft(lead_ids)
    if not leads:
        return 0

    if service is None:
        try:
            service = gmail_drafter.get_service(interactive=False)
        except Exception as e:  # noqa: BLE001
            progress(f"Gmail not authorized, drafts skipped: {e}")
            return 0

    templates = db.load_templates("gmail_draft")
    firm = company.get("name") or "?"
    events = company.get("trigger_events")
    made = 0
    for lead in leads:
        try:
            res = gmail_drafter.draft_for_lead(lead, company, templates,
                                               service=service, progress=progress)
            if res["status"] == "drafted":
                made += 1
                # Deck-confidence flag so Harpreet knows which drafts need a
                # careful slide-3 review before sending.
                if res.get("attachment_kind") == "deck":
                    banner = pitch_deck.confidence_banner(firm)
                else:
                    banner = (f"📎 Attached: {res.get('attachment_kind', 'none')} "
                              "(no firm-specific deck) — review before sending")
                progress(f"📋 Draft ready: {lead['full_name']} ({firm})\n{banner}")
                # Item 5: which 'why now' claim the draft cites + its source URL.
                progress(_source_line(firm, lead, res.get("body", ""), events))
        except Exception as e:  # noqa: BLE001
            progress(f"Draft failed for {lead['full_name']}: {str(e)[:120]}")
    return made


def _gate_from_research(name: str, research: dict, region_fallback: Optional[str]) -> dict:
    aum = research.get("aum") or {}
    return icp_gate.gate_company(
        firm_type=research.get("firm_type"),
        region=research.get("region") or region_fallback,
        aum_value_usd=aum.get("value_usd"),
        aum_tag=aum.get("tag"),
        name=name, research_raw=research, aum_basis=aum.get("basis"),
    )


def _deep_reverify(name: str) -> Optional[dict]:
    """One targeted search to recover AUM / unit-count / listing for a PARKED
    firm, re-extracted with the units proxy. Returns an updated research dict or
    None. Uses DEFAULT_MODEL (gpt-5-mini)."""
    angles = [f'"{name}" assets under management OR portfolio units OR '
              f'"apartment homes" OR AUM OR "square feet"']
    try:
        results = search_client.layered_search(angles, max_results_each=6)
    except search_client.SearchAPIError:
        results = []            # search outage -> cannot re-verify now
    if not results:
        return None
    trimmed = [{"title": r["title"], "url": r["url"], "content": (r["content"] or "")[:700]}
               for r in results[:10]]
    prompt = (
        f"Firm (a commercial real estate company): {name}\n"
        "From these search results, extract portfolio scale for THIS real estate "
        "firm only. Return JSON with keys: "
        '{"aum_value_usd": number|null, "unit_count": number|null, '
        '"sqft": number|null, "firm_type": "real estate|family office|private '
        'equity|property management|other|unknown", "region": "USA|Canada|Mexico|'
        'other|unknown", "listing": "NYSE|NASDAQ|none"}\n'
        f"Results (JSON): {json.dumps(trimmed, ensure_ascii=False)}"
    )
    try:
        parsed, _u = models.complete_json(prompt, model=config.DEFAULT_MODEL,
                                          temperature=0.0, max_tokens=1500)
    except Exception:  # noqa: BLE001
        return None

    research: dict = {
        "firm_type": parsed.get("firm_type"),
        "region": parsed.get("region"),
        "unit_count": parsed.get("unit_count"),
        "sqft": parsed.get("sqft"),
    }
    listing = (parsed.get("listing") or "").strip().lower()
    if listing in ("nyse", "nasdaq"):
        research["listing"] = listing.upper()  # is_public_giant scans for this
    aum: dict = {}
    val = icp_gate._to_number(parsed.get("aum_value_usd"))
    if val:
        aum = {"value_usd": val, "tag": "AUM_CONFIRMED", "basis": "stated AUM from targeted search"}
    else:
        est, basis = icp_gate.estimate_aum(parsed.get("unit_count"), parsed.get("sqft"))
        if est is not None:
            aum = {"value_usd": est, "tag": "AUM_ESTIMATED", "basis": basis}
        else:
            aum = {"value_usd": None, "tag": "AUM_UNVERIFIED", "basis": "still unverified after targeted search"}
    research["aum"] = aum
    return research


def requalify_all(deep: bool = True, progress: Progress = _print_progress) -> dict:
    """Re-gate every company from stored research (applies the public-giant rule
    and the units proxy). For firms that remain PARKED, run one targeted search
    (deep=True) to recover AUM/units and re-gate. Returns a before/after report."""
    def _tally(results):
        t = {"QUALIFIED": 0, "DISQUALIFIED": 0, "PARKED": 0, "PENDING": 0}
        for r in results:
            t[r.get("icp_result") or "PENDING"] = t.get(r.get("icp_result") or "PENDING", 0) + 1
        return t

    with db.cursor() as cur:
        cur.execute("SELECT id, name, region, icp_result, research_raw FROM companies")
        rows = cur.fetchall()
    before = _tally(rows)
    transitions = []
    deep_count = 0

    for row in rows:
        name = row["name"]
        research = row.get("research_raw") or {}
        old = row.get("icp_result")
        gate = _gate_from_research(name, research, row.get("region"))

        if deep and gate["icp_result"] == "PARKED":
            progress(f"Deep re-verify: {name}...")
            updated = _deep_reverify(name)
            if updated:
                # preserve prior fields the targeted extract did not set
                merged = {**research, **{k: v for k, v in updated.items() if v is not None}}
                merged["aum"] = updated.get("aum") or research.get("aum")
                research = merged
                db.upsert_company(name=name, research_raw=research)
                gate = _gate_from_research(name, research, row.get("region"))
                deep_count += 1

        db.set_company_icp(row["id"], gate["icp_result"], gate["icp_reason"], gate.get("aum_tag"))
        if gate["icp_result"] != old:
            transitions.append({"name": name, "before": old or "PENDING",
                                "after": gate["icp_result"], "reason": gate["icp_reason"]})

    with db.cursor() as cur:
        cur.execute("SELECT icp_result FROM companies")
        after = _tally(cur.fetchall())
    return {"before": before, "after": after, "transitions": transitions,
            "deep_searched": deep_count, "updated": len(rows)}


def format_requalify(report: dict) -> str:
    b, a = report["before"], report["after"]
    lines = [
        f"Requalify: {report['updated']} companies re-gated, "
        f"{report['deep_searched']} deep-searched.",
        "",
        "                 QUALIFIED  DISQUALIFIED  PARKED",
        f"  before          {b.get('QUALIFIED',0):>8}  {b.get('DISQUALIFIED',0):>12}  {b.get('PARKED',0):>6}",
        f"  after           {a.get('QUALIFIED',0):>8}  {a.get('DISQUALIFIED',0):>12}  {a.get('PARKED',0):>6}",
    ]
    if report["transitions"]:
        lines.append("")
        lines.append("Transitions:")
        for t in report["transitions"]:
            lines.append(f"  {t['name']}: {t['before']} -> {t['after']} ({t['reason']})")
    else:
        lines.append("")
        lines.append("No transitions.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (headless test path; Hermes-style `python -m src.<entrypoint>`)
# ---------------------------------------------------------------------------
def _cli() -> None:
    # Progress/draft notifications now carry emoji; keep the CLI printable on a
    # Windows cp1252 console (the bot sends over Telegram/HTTP, so it's unaffected).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - not every stream supports reconfigure
        pass
    args = sys.argv[1:]
    if not args:
        print('usage: python -m src.prospect.competitor_engine "<client firm>" '
              '[--auto-confirm] [--limit N] [--no-draft]')
        print('       python -m src.prospect.competitor_engine --requalify')
        return
    if args[0] == "--requalify":
        print(format_requalify(requalify_all()))
        return
    client = args[0]
    auto = "--auto-confirm" in args
    no_draft = "--no-draft" in args
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])

    run = db.create_run(client)
    candidates = run_discovery(run["id"], client)
    if limit:
        candidates = candidates[:limit]
    print(f"\nCandidates ({len(candidates)}):")
    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c['name']} [{c.get('region') or '?'}]")
    if not auto:
        print("\nRun again with --auto-confirm to process, or use the Telegram bot "
              "for the confirm/trim checkpoint.")
        db.update_run(run["id"], confirmed_names=[c["name"] for c in candidates])
        return
    db.update_run(run["id"], status="processing",
                  confirmed_names=[c["name"] for c in candidates])
    run_processing(run["id"], client, candidates, do_draft=not no_draft)


if __name__ == "__main__":
    _cli()
