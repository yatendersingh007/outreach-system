"""Binary ICP firm gate. QUALIFIED / DISQUALIFIED / PARKED. No scoring, no tiers.

The rules live in prompts/icp_scoring_v2_2.md (owner-editable source of truth).
They are fully deterministic, so they are ENFORCED IN CODE here (consistent with
the HARD RULE that hard limits are enforced in code, not by prompt judgment).
The LLM's job (in company_research) is to extract firm_type / region / AUM from
sources; this gate then decides, and records a one-line, auditable icp_reason.

Three conditions, ALL must hold to QUALIFY:
  1. Firm type in {real estate, family office, private equity, property management}
  2. AUM between $200M and $2B (below or above => DISQUALIFIED)
  3. Headquartered / primarily operating in North America
AUM that cannot be verified => PARKED (never guessed).
"""
from __future__ import annotations

import re
from typing import Optional

from .. import config

ALLOWED_FIRM_TYPES = {
    "real estate", "family office", "private equity", "property management",
}
# Types that are POSITIVELY outside the ICP (owner/investor side). Only these
# disqualify on firm type; an unclassifiable firm ('unknown'/'other') is PARKED
# for human review, never dropped (a transient research miss must not delete a
# real RE firm — see the regression audit). The classifier may emit these labels
# directly; _normalize_firm_type also maps common synonyms onto them.
EXCLUDED_FIRM_TYPES = {
    "brokerage", "lender/bank", "insurance", "retailer", "advisory/services",
}
_EXCLUDED_SYNONYMS = (
    ("brokerage", ("brokerage", "broker", "brokers")),
    ("lender/bank", ("lender", "lending", "bank", "banking", "mortgage",
                     "credit union", "debt fund")),
    ("insurance", ("insurance", "insurer", "reinsurance")),
    ("retailer", ("retailer", "retail chain", "grocery", "e-commerce",
                  "ecommerce", "consumer brand", "department store")),
    ("advisory/services", ("advisory", "advisor", "consultant", "consulting",
                           "appraisal", "valuation", "engineering", "coworking",
                           "law firm", "accounting firm", "staffing")),
)
NON_NA_HINTS = (
    "europe", "uk", "united kingdom", "asia", "india", "australia", "africa",
    "middle east", "singapore", "germany", "france", "china", "japan", "brazil",
    "dubai", "uae", "south america",
)

# Unit-count / sqft AUM proxies (Layer-2 verification when no stated AUM).
AUM_PER_UNIT_USD = 175_000
AUM_PER_SQFT_USD = 200

# Public / institutional giants: always above the $2B ceiling. DISQUALIFY on
# name alone (no research, no LLM), before any Exa/Tavily call (zero API cost).
# The structured research `listing` field (a major exchange) is treated the same.
_PUBLIC_GIANTS_RAW = [
    "AvalonBay", "AvalonBay Communities", "MAA", "Mid-America Apartment Communities",
    "Equity Residential", "Essex", "Essex Property Trust", "UDR", "Camden",
    "Camden Property Trust", "AIR Communities", "Apartment Income REIT",
    "Invitation Homes", "American Homes 4 Rent", "Greystar", "Prologis", "Hines",
]

# Globally-recognized mega asset managers / PE / institutional RE / large public
# REITs — effectively always >$2B, so instant-DISQUALIFY by NAME before research.
# Matched by TOKEN SUBSET (every token of the set must appear as a whole token in
# the firm name) — NOT substring — so 'india' can never match 'indiana' and a
# two-token set can't fire on an unrelated single word. Two-token sets are used
# for anything whose lone word is common; lone-token entries are distinctive names.
_MEGA_FIRM_TOKEN_SETS = [
    # Global PE / asset managers ($10B+) that kept slipping through as "parked"
    {"kkr"}, {"blackstone"}, {"brookfield"}, {"carlyle"}, {"tpg"}, {"cerberus"},
    {"oaktree"}, {"pimco"}, {"pgim"}, {"nuveen"},
    {"apollo", "global"}, {"starwood", "capital"}, {"ares", "management"},
    {"angelo", "gordon"}, {"fortress", "investment"}, {"lone", "star"},
    {"invesco", "real"},
    # Global institutional real estate ($10B+)
    {"oxford", "properties"}, {"clarion", "partners"}, {"bentallgreenoak"},
    {"heitman"}, {"tishman", "speyer"}, {"lasalle", "investment"},
    {"northwood", "investors"},
    # Large public REITs (major exchanges, >$2B) — disqualified on SIZE, not type
    {"vornado"}, {"macerich"}, {"brixmor"}, {"kimco"},
    {"simon", "property"}, {"boston", "properties"}, {"bxp"},
    {"federal", "realty"}, {"regency", "centers"}, {"agree", "realty"},
    {"phillips", "edison"}, {"realty", "income"}, {"digital", "realty"},
    {"kilroy", "realty"}, {"lexington", "realty"}, {"lxp", "industrial"},
    {"rmr", "group"}, {"crown", "castle"},
]
# Entity-suffix tokens stripped for normalized name matching.
_SUFFIX_TOKENS = {
    "inc", "incorporated", "llc", "lp", "llp", "corp", "corporation", "company",
    "co", "trust", "group", "holdings", "communities", "community", "reit",
    "the", "and",
}


def _norm_firm(name: str) -> str:
    tokens = re.split(r"[^a-z0-9]+", (name or "").lower())
    kept = [t for t in tokens if t and t not in _SUFFIX_TOKENS]
    return "".join(kept)


_PUBLIC_GIANTS_NORM = {_norm_firm(n) for n in _PUBLIC_GIANTS_RAW}


def is_public_giant(name: Optional[str], research_raw: Optional[dict] = None) -> bool:
    """True if the firm is a known public/institutional giant, or its research's
    STRUCTURED `listing` field names a major exchange. These are above the $2B ceiling.

    Detection uses ONLY unambiguous signals — a known name, or the structured
    `listing` field (the research prompt extracts the SUBJECT firm's exchange, or
    'none'). It deliberately does NOT scan free text: a private firm's summary that
    contrasts itself against public REITs ('unlike NYSE-listed REITs', 'not publicly
    traded', 'competes with NASDAQ-traded peers') would otherwise be wrongly DQ'd —
    the exact private-RE ICP the restored funnel protects. A genuinely public firm
    still gets caught by the name list, the structured field, or the AUM ceiling."""
    if name:
        if _norm_firm(name) in _PUBLIC_GIANTS_NORM:
            return True
        tokens = {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}
        if any(mega <= tokens for mega in _MEGA_FIRM_TOKEN_SETS):
            return True
    if not research_raw:
        return False
    listing = str((research_raw or {}).get("listing") or "").strip().upper()
    return listing in ("NYSE", "NASDAQ", "NYSE AMERICAN", "AMEX", "TSX")


def _to_number(value) -> Optional[float]:
    """Parse a count that may be int, '3,000', '3000', or '1.2 million'/'450k'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower().replace(",", "")
    m = re.search(r"([0-9]*\.?[0-9]+)\s*(million|thousand|m|k|b|billion)?", s)
    if not m:
        return None
    num = float(m.group(1))
    mult = {"million": 1e6, "m": 1e6, "b": 1e9, "billion": 1e9,
            "thousand": 1e3, "k": 1e3}.get(m.group(2) or "", 1)
    return num * mult


def estimate_aum(unit_count=None, sqft=None) -> tuple[Optional[float], Optional[str]]:
    """Layer-2 AUM proxy: units x $175K, else sqft x $200. Returns (value, basis)."""
    units = _to_number(unit_count)
    if units and units > 0:
        value = units * AUM_PER_UNIT_USD
        return value, f"est. {_fmt_usd(value)} from {int(units):,} units x $175K"
    sf = _to_number(sqft)
    if sf and sf > 0:
        value = sf * AUM_PER_SQFT_USD
        return value, f"est. {_fmt_usd(value)} from {int(sf):,} sqft x $200"
    return None, None


def _fmt_usd(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.0f}M"
    return f"${value:,.0f}"


def _region_is_na(region: Optional[str]) -> Optional[bool]:
    """True=North America, False=clearly outside, None=unknown/unestablished.

    Matches on WHOLE TOKENS, never raw substrings: substring matching wrongly
    disqualified 'Indiana' ('india' in 'indiana') and wrongly passed 'Australia'/
    'Cyprus' as NA ('us' in 'aUStralia'). Tokens are split on non-letters after
    dropping dots so 'U.S.' -> {'u','s'} -> normalized 'us'."""
    if not region:
        return None
    r = region.strip().lower()
    if r in ("", "unknown", "n/a", "none"):
        return None
    tokens = {t for t in re.split(r"[^a-z]+", r.replace(".", "")) if t}
    # North America: whole-token country hints, or the two multi-word phrases.
    if tokens & {"usa", "us", "canada", "canadian", "mexico", "mexican"}:
        return True
    if {"united", "states"} <= tokens or {"north", "america"} <= tokens \
            or {"north", "american"} <= tokens:
        return True
    # Clearly outside NA: every word of a NON_NA hint must be present as a token
    # (so 'india' matches 'India' but NOT 'Indiana').
    for h in NON_NA_HINTS:
        parts = h.split()
        if all(p in tokens for p in parts):
            return False
    return None


def _normalize_firm_type(firm_type: Optional[str]) -> str:
    t = (firm_type or "").strip().lower()
    if t in ALLOWED_FIRM_TYPES or t in EXCLUDED_FIRM_TYPES:
        return t
    # tolerate near-synonyms from the researcher (RE-side first: an "X Capital"
    # that also mentions lending should read as RE, not lender)
    if "real estate" in t or "reit" in t or "developer" in t or "owner" in t:
        return "real estate"
    if "family office" in t:
        return "family office"
    if "private equity" in t or t == "pe":
        return "private equity"
    if "property management" in t or "property manager" in t:
        return "property management"
    # positively-excluded types (brokerage / lender / insurance / retailer / advisory)
    for label, kws in _EXCLUDED_SYNONYMS:
        if any(k in t for k in kws):
            return label
    return t  # 'other' / 'unknown' / unrecognized -> PARK (never auto-DQ)


# A "floor-type" proxy (cumulative invested/deployed capital, transaction volume
# since inception) is a LOWER BOUND on size — the true AUM is at least this and
# likely higher — so a below-band value must PARK for verification, not drop. A
# point estimate (units/sqft/portfolio value) or a confirmed figure does not.
_FLOOR_PROXY_HINTS = ("invested", "deployed", "transaction volume",
                      "since inception", "cumulative")


def _is_floor_proxy(aum_basis: Optional[str]) -> bool:
    b = (aum_basis or "").lower()
    return any(h in b for h in _FLOOR_PROXY_HINTS)


def gate_company(
    firm_type: Optional[str],
    region: Optional[str],
    aum_value_usd: Optional[float],
    aum_tag: Optional[str],
    name: Optional[str] = None,
    research_raw: Optional[dict] = None,
    aum_basis: Optional[str] = None,
    aum_floor: Optional[float] = None,
    aum_ceiling: Optional[float] = None,
    source_count: Optional[int] = None,
) -> dict:
    """Return {icp_result, icp_reason, firm_type, aum_tag, aum_value_usd}.

    aum_floor/aum_ceiling default to the global config band but can be overridden
    per client (from the client profile). `source_count` (when known) lets a PARK
    reason distinguish 'no web sources found' (search thin/down -> re-run later)
    from 'sources found but no AUM' (hunt the size by hand) — different operator
    actions (Phase 4.2)."""
    floor = aum_floor if aum_floor is not None else config.AUM_MIN_USD
    ceiling = aum_ceiling if aum_ceiling is not None else config.AUM_MAX_USD
    ftype = _normalize_firm_type(firm_type)
    aum_str = _fmt_usd(aum_value_usd)
    no_sources = source_count == 0   # only True when explicitly told 0 (None => unknown)
    NO_SOURCES_REASON = ("no web sources found (search may be down or the firm is "
                         "obscure) — re-run later or verify manually")

    # Layer 0: public/institutional giants disqualify on identity alone (always
    # above the $2B ceiling); no AUM lookup, no parking.
    if is_public_giant(name, research_raw):
        return {
            "icp_result": "DISQUALIFIED",
            "icp_reason": "public/institutional/mega-firm, above $2B ceiling",
            "firm_type": ftype,
            "aum_tag": aum_tag,
            "aum_value_usd": aum_value_usd,
        }

    # Condition 1a: POSITIVELY-excluded firm type -> DISQUALIFY. Only a confident
    # not-RE identification (brokerage / lender / insurance / retailer / advisory)
    # drops a firm on type.
    if ftype in EXCLUDED_FIRM_TYPES:
        return {
            "icp_result": "DISQUALIFIED",
            "icp_reason": f"positively identified as {ftype}, outside the owner/investor ICP",
            "firm_type": ftype,
            "aum_tag": aum_tag,
            "aum_value_usd": aum_value_usd,
        }

    # Condition 3: region (only disqualify when clearly outside North America;
    # a confident foreign HQ is a valid drop even for an unclassified firm type).
    na = _region_is_na(region)
    if na is False:
        return {
            "icp_result": "DISQUALIFIED",
            "icp_reason": f"{ftype or 'firm'}, region '{region}' outside North America",
            "firm_type": ftype,
            "aum_tag": aum_tag,
            "aum_value_usd": aum_value_usd,
        }
    region_note = "" if na else " (region unconfirmed)"

    # Condition 1b: firm type could NOT be positively classified (unknown / other /
    # unrecognized) -> PARK for human review. NEVER auto-disqualify — a thin or
    # failed research pass must not delete a real RE firm; parking feeds /qualify.
    if ftype not in ALLOWED_FIRM_TYPES:
        return {
            "icp_result": "PARKED",
            "icp_reason": NO_SOURCES_REASON if no_sources else
                          ("firm type unverified, parked for human review"
                           + (f" (region {region})" if region else "")),
            "firm_type": ftype or "unknown",
            "aum_tag": "AUM_UNVERIFIED",
            "aum_value_usd": aum_value_usd,
        }

    # Condition 2: AUM. Unverified => PARK (never guess).
    unverified = (aum_tag == "AUM_UNVERIFIED") or (aum_value_usd is None)
    if unverified:
        return {
            "icp_result": "PARKED",
            "icp_reason": NO_SOURCES_REASON if no_sources else
                          f"{ftype}, AUM not verified, parked for human review{region_note}",
            "firm_type": ftype,
            "aum_tag": "AUM_UNVERIFIED",
            "aum_value_usd": aum_value_usd,
        }
    basis_note = f"; {aum_basis}" if aum_basis else ""
    if aum_value_usd < floor:
        # A FLOOR-type ESTIMATE (cumulative invested capital, etc.) below the band
        # is a lower bound, not a size ceiling — the real AUM could be in-band, so
        # PARK for manual verification. A CONFIRMED figure or a point-estimate
        # (units/sqft/portfolio value) below the floor still disqualifies.
        if aum_tag == "AUM_ESTIMATED" and _is_floor_proxy(aum_basis):
            return {
                "icp_result": "PARKED",
                "icp_reason": f"{ftype}, proxy {aum_str} below {_fmt_usd(floor)} floor "
                              f"— verify manually{basis_note}",
                "firm_type": ftype,
                "aum_tag": aum_tag,
                "aum_value_usd": aum_value_usd,
            }
        return {
            "icp_result": "DISQUALIFIED",
            "icp_reason": f"{ftype}, AUM {aum_str} below {_fmt_usd(floor)} floor{basis_note}",
            "firm_type": ftype,
            "aum_tag": aum_tag,
            "aum_value_usd": aum_value_usd,
        }
    # A FLOOR-type proxy is a LOWER bound: if even the lower bound reaches the
    # ceiling, the true AUM is at/above it -> DISQUALIFY. ("over $2B invested" =>
    # value 2.0B AT the ceiling must drop, not squeak through the strict >.)
    floor_proxy = (aum_tag == "AUM_ESTIMATED") and _is_floor_proxy(aum_basis)
    if aum_value_usd > ceiling or (floor_proxy and aum_value_usd >= ceiling):
        return {
            "icp_result": "DISQUALIFIED",
            "icp_reason": f"{ftype}, AUM {aum_str} at/above {_fmt_usd(ceiling)} ceiling{basis_note}",
            "firm_type": ftype,
            "aum_tag": aum_tag,
            "aum_value_usd": aum_value_usd,
        }

    return {
        "icp_result": "QUALIFIED",
        "icp_reason": f"{ftype}, AUM {aum_str} ({aum_tag or 'AUM_ESTIMATED'}), North America, qualifies{region_note}{basis_note}",
        "firm_type": ftype,
        "aum_tag": aum_tag or "AUM_ESTIMATED",
        "aum_value_usd": aum_value_usd,
    }
