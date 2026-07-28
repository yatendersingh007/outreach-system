"""Offline unit tests: style guard, ICP gate, template parser. No DB/LLM/network.

Run: python -m pytest tests/test_unit.py   (or: python tests/test_unit.py)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import parse_template  # noqa: E402
from src.drafting import style_guard  # noqa: E402
from src.researcher import icp_gate  # noqa: E402
from src.approval.telegram_queue import _strip_quotes  # noqa: E402
from src.prospect.competitor_engine import (  # noqa: E402
    _is_excluded, _leads_to_draft, _discovery_angles, _expand_regions,
    parse_aum, _firm_progress_line, _format_misses, _source_line, _event_texts,
)
from src.researcher import exa_client  # noqa: E402
from src.researcher.company_research import extract_domain  # noqa: E402
from src.drafting import pitch_deck  # noqa: E402


# --- pitch deck: slug + helpers (offline) ----------------------------------
def test_deck_slugify():
    assert pitch_deck.slugify("Monarch Investment & Management Group") == "Monarch_Investment_Management_Group"
    assert pitch_deck.slugify("A.B  C!") == "A_B_C"


def test_deck_short_name_and_roles():
    assert pitch_deck._short_name("Monarch Investment & Management Group") == "Monarch"
    assert "and" in pitch_deck._roles_line(["fund accountants", "property accountants", "underwriters"])
    assert pitch_deck._roles_line([]) != ""   # falls back to defaults


def test_deck_build_data_has_14_slides_worth():
    company = {"name": "Testco Capital", "icp_reason": "RE PE, AUM $500M", "last_researched_at": None}
    custom = {"firm_profile": {"lead_sentence": "x", "asset_class_focus": "multifamily",
                               "stats": [{"label": "AUM", "value": "$500M", "sublabel": ""}]},
              "fit_points": [{"bold_label": "A", "description": "d"}],
              "relevant_roles": ["fund accountants", "property accountants"]}
    d = pitch_deck._build_data(company, custom, "out.pptx")
    for k in ("coverTitle", "agenda", "profile", "comparison", "sixFunctions",
              "serviceDetails", "why", "engagement", "timeline", "fit", "pilot", "thankYou"):
        assert k in d, f"missing {k}"
    assert len(d["serviceDetails"]) == 3
    assert d["coverTitle"] == "Built for Testco."
    assert d["fit"]["points"][0]["boldLabel"] == "A"


def test_deck_strips_estimated_aum_stat():
    # For an ESTIMATED-AUM firm, NO big-dollar figure may render as a hard stat
    # box — under ANY label (incl. the GAV synonym the prompt endorses), and
    # regardless of whether it's the AUM itself or another $B figure (safe
    # direction). Counts survive; the estimate is surfaced softly in the lead.
    est = {"name": "EstCo", "icp_reason": "est. $1.2B from 6857 units x $175K",
           "aum_tag": "AUM_ESTIMATED"}
    custom = {"firm_profile": {"lead_sentence": "EstCo is a multifamily operator.",
              "stats": [{"label": "GAV", "value": "$1.2B", "sublabel": ""},
                        {"label": "Portfolio Acquisitions", "value": "$1.6B", "sublabel": ""},
                        {"label": "Units", "value": "6,857", "sublabel": ""}],
              "bullets": ["a", "b", "c"]}, "confidence": "high"}
    d = pitch_deck._build_data(est, custom, "out.pptx", research_raw="z" * 600)
    stats = d["profile"]["stats"]
    assert all("$" not in s["value"] for s in stats)   # no dollar figures survive
    assert "Units" in [s["label"] for s in stats]      # counts do survive
    assert "estimated portfolio of ~$1.2B" in d["profile"]["lead"]


def test_deck_drops_overlong_stat_value():
    # A value that would be sliced mid-digit is dropped, never truncated.
    company = {"name": "LongCo", "icp_reason": "RE, AUM $1.25B", "aum_tag": "AUM_CONFIRMED"}
    custom = {"firm_profile": {"lead_sentence": "x",
              "stats": [{"label": "AUM", "value": "$1,250,000,000", "sublabel": ""},
                        {"label": "Units", "value": "6,857", "sublabel": ""}],
              "bullets": ["a", "b", "c"]}, "confidence": "high"}
    d = pitch_deck._build_data(company, custom, "out.pptx", research_raw="z" * 600)
    vals = [s["value"] for s in d["profile"]["stats"]]
    assert "$1,250,000,000" not in vals and "$1,250,000,0" not in vals   # dropped, not sliced
    assert "6,857" in vals


def test_deck_confirmed_aum_kept():
    conf = {"name": "ConfCo", "aum_tag": "AUM_CONFIRMED",
            "icp_reason": "real estate, AUM $15.3B (AUM_CONFIRMED), qualifies"}
    custom = {"firm_profile": {"lead_sentence": "x",
              "stats": [{"label": "Assets Under Management", "value": "$15.3B", "sublabel": ""}],
              "bullets": ["a", "b", "c"]}, "confidence": "high"}
    d = pitch_deck._build_data(conf, custom, "out.pptx", research_raw="z" * 600)
    assert any(s["value"] == "$15.3B" for s in d["profile"]["stats"])


def test_deck_confidence_low_on_thin_data():
    company = {"name": "ThinCo", "icp_reason": "est. $300M", "aum_tag": "AUM_ESTIMATED"}
    custom = {"firm_profile": {"lead_sentence": "x", "stats": [],
                               "bullets": ["only one bullet"]}, "confidence": "high"}
    d = pitch_deck._build_data(company, custom, "out.pptx", research_raw="short")
    assert d["confidence"] == "low"   # <3 bullets AND 0 stats AND research < 500


def test_deck_strips_estimated_aum_all_money_forms():
    # The value backstop is currency-agnostic and covers MM / bn / B / no-symbol /
    # word forms, so an estimate can't slip onto slide 3 under a non-AUM label.
    est = {"name": "E", "icp_reason": "est. $1.2B from 7000 units", "aum_tag": "AUM_ESTIMATED"}
    for val in ["$500MM", "1.2B", "USD 1.2B", "1.2 billion", "$1.2bn", "1,200M", "$1.2T",
                "€1.2B", "$450mn", "$450mln", "$1.2bln", "1.2 mil"]:
        custom = {"firm_profile": {"lead_sentence": "x",
                  "stats": [{"label": "Portfolio", "value": val, "sublabel": ""},
                            {"label": "Units", "value": "6,857", "sublabel": ""}],
                  "bullets": ["a", "b", "c"]}, "confidence": "high"}
        kept = [s["value"] for s in
                pitch_deck._build_data(est, custom, "o", research_raw="z" * 600)["profile"]["stats"]]
        assert val not in kept, f"{val} leaked as a stat box"
        assert "6,857" in kept                          # the count survives


def test_deck_build_data_survives_malformed_llm():
    # Scalar stats/bullets, a non-string lead, and a non-list fit_points must not
    # crash _build_data (defense-in-depth beyond json_object mode).
    est = {"name": "E", "icp_reason": "est. $1.2B from 7000 units", "aum_tag": "AUM_ESTIMATED"}
    custom = {"firm_profile": {"lead_sentence": ["not", "a", "string"],
                               "stats": 5, "bullets": True},
              "fit_points": "nope", "relevant_roles": 7, "confidence": "high"}
    d = pitch_deck._build_data(est, custom, "o", research_raw="short")
    assert "profile" in d and isinstance(d["profile"]["stats"], list)
    assert d["confidence"] == "low"


def test_generate_deck_returns_valid_pptx_path():
    """generate_deck returns a real .pptx path for a mock company. Gated on node;
    the LLM extraction is stubbed so no network is needed."""
    import os
    import shutil
    import zipfile
    if not shutil.which("node") or not pitch_deck.config.DECK_BUILDER_JS.exists():
        print("SKIP test_generate_deck_returns_valid_pptx_path: node/renderer unavailable")
        return
    orig = pitch_deck._extract_custom
    pitch_deck._extract_custom = lambda company, rr: {
        "firm_profile": {"lead_sentence": "A mock multifamily operator.",
                         "asset_class_focus": "multifamily", "geographic_focus": "USA",
                         "stats": [{"label": "AUM", "value": "$450M", "sublabel": "confirmed"}],
                         "capital_stack_line": "LP, GP, Preferred Equity"},
        "fit_points": [{"bold_label": "Property accounting at scale", "description": "d1"},
                       {"bold_label": "Investor reporting", "description": "d2"},
                       {"bold_label": "Underwriting support", "description": "d3"}],
        "relevant_roles": ["property accountants", "fund accountants"],
    }
    try:
        company = {"name": "Mock Deck Co", "icp_reason": "RE, AUM $450M", "last_researched_at": None}
        path = pitch_deck.generate_deck(company, "mock research text", force=True)
        assert os.path.exists(path)
        assert path.endswith("XAnalyst_Mock_Deck_Co_Pitch.pptx")
        with zipfile.ZipFile(path) as z:      # valid pptx zip with 14 slides
            slides = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
        assert len(slides) == 14, f"expected 14 slides, got {len(slides)}"
        os.remove(path)
        sidecar = path.replace("_Pitch.pptx", "_data.json")
        if os.path.exists(sidecar):
            os.remove(sidecar)
    finally:
        pitch_deck._extract_custom = orig


# --- exa_client module (import + interface parity, no network) --------------
def test_exa_client_imports_and_interface():
    assert hasattr(exa_client, "search")
    assert hasattr(exa_client, "layered_search")
    assert hasattr(exa_client, "find_similar")
    assert issubclass(exa_client.SearchError, RuntimeError)


def test_discovery_provider_selection():
    from src import config
    from src.prospect import competitor_engine as ce
    from src.researcher import search_client
    expected = exa_client if config.EXA_API_KEY else search_client
    assert ce._discovery_provider() is expected

_GOOD_BODY = (
    "Hi Andy,\n\n"
    "Your multifamily portfolio has grown steadily, and with more doors comes a "
    "heavier month-end close, more bank reconciliations, and tighter lender "
    "reporting. Keeping all of that clean without overloading your controller is "
    "the hard part, especially as the number of properties climbs each year.\n\n"
    "I built the offshore property and fund accounting teams for Magnolia Capital "
    "and 29th Street Capital from scratch. The full stack: property-level books "
    "and month-end close, bank reconciliations, AP/AR and tenant billing, CAM "
    "reconciliations and true-ups, budget versus actual variance reporting, lender "
    "and covenant packages, owner distributions and monthly owner reports, all on "
    "Yardi, RealPage, and Entrata.\n\n"
    "Most mid-market firms either overpay a provider whose partners never open the "
    "ledger, or burn their controller's nights on work a dedicated accountant "
    "should own. We remove that friction with dedicated CA and CPA accountants "
    "from the top of the market, embedded in your systems and your close calendar, "
    "live within a couple of weeks.\n\n"
    "Can we do a short call next week? Our Head of Delivery, ex-Blackstone and "
    "Goldman Sachs, would join. A one-page case study is attached in case it "
    "helps before then.\n\n"
    "Harp\nFounder, X Analyst"
)


# --- style guard -----------------------------------------------------------
def test_em_dash_rejected():
    assert not style_guard.is_clean("We build systems — fast.")
    assert "contains em dash (—)" in style_guard.violations("a — b")


def test_double_hyphen_rejected():
    assert not style_guard.is_clean("cost effective -- always")


def test_cliches_rejected():
    assert not style_guard.is_clean("I hope this finds you well.")
    assert not style_guard.is_clean("I came across your profile yesterday.")


def test_clean_passes():
    assert style_guard.is_clean("Your recent acquisition caught my eye. Quick idea below.")


def test_sanitize_fixes_dashes():
    fixed = style_guard.sanitize("a — b -- c")
    assert "—" not in fixed and "--" not in fixed


def test_enforce_regenerates_until_clean():
    attempts = {"n": 0}

    def gen():
        attempts["n"] += 1
        return "bad — draft" if attempts["n"] < 2 else "good clean draft"

    assert style_guard.enforce(gen) == "good clean draft"
    assert attempts["n"] == 2


# --- ICP gate --------------------------------------------------------------
def test_gate_qualifies_in_band():
    r = icp_gate.gate_company("private equity", "USA", 450_000_000, "AUM_CONFIRMED")
    assert r["icp_result"] == "QUALIFIED"


def test_gate_disqualifies_below_floor():
    r = icp_gate.gate_company("real estate", "USA", 50_000_000, "AUM_CONFIRMED")
    assert r["icp_result"] == "DISQUALIFIED" and "below" in r["icp_reason"]


def test_gate_disqualifies_above_ceiling():
    r = icp_gate.gate_company("real estate", "USA", 5_000_000_000, "AUM_CONFIRMED")
    assert r["icp_result"] == "DISQUALIFIED" and "above" in r["icp_reason"]


def test_gate_parks_unverified_aum():
    r = icp_gate.gate_company("family office", "Canada", None, "AUM_UNVERIFIED")
    assert r["icp_result"] == "PARKED"


def test_gate_parks_unclassifiable_type():
    # POLICY (regression fix): a type we can't positively place ('software',
    # 'unknown', 'other') PARKS for human review — it is NEVER auto-disqualified.
    # A thin/failed research pass must not delete a real firm.
    for t in ("software", "unknown", "other", "", None):
        r = icp_gate.gate_company(t, "USA", 500_000_000, "AUM_CONFIRMED")
        assert r["icp_result"] == "PARKED", (t, r["icp_result"])
        assert "firm type unverified" in r["icp_reason"]


def test_gate_disqualifies_positively_excluded_type():
    # DQ only on a POSITIVE not-RE identification.
    for t, kw in [("brokerage", "brokerage"), ("broker", "brokerage"),
                  ("mortgage lender", "lender"), ("bank", "lender"),
                  ("insurance", "insurance"), ("retailer", "retailer"),
                  ("advisory", "advisory"), ("appraisal", "advisory")]:
        r = icp_gate.gate_company(t, "USA", 500_000_000, "AUM_CONFIRMED")
        assert r["icp_result"] == "DISQUALIFIED", (t, r["icp_result"])
        assert "positively identified" in r["icp_reason"]


def test_gate_qualifies_positively_identified_re_in_band():
    r = icp_gate.gate_company("real estate", "USA", 750_000_000, "AUM_CONFIRMED",
                              name="VennPoint Real Estate")
    assert r["icp_result"] == "QUALIFIED"


def test_company_angles_has_dedicated_aum_query():
    from src.researcher.company_research import _company_angles
    general, _news = _company_angles("Foo Capital")
    joined = " ".join(general).lower()
    assert "assets under management" in joined and "market cap" in joined
    # the size query must be quoted-anchored to the firm name
    assert any("assets under management" in g and '"Foo Capital"' in g for g in general)


def test_region_is_na_token_boundaries():
    # Review finding: substring matching wrongly DQ'd US 'Indiana' ('india' in it)
    # and wrongly passed foreign 'Australia' ('us' in it) as North America.
    assert icp_gate._region_is_na("Indiana") is not False          # US state, not India
    assert icp_gate._region_is_na("Indianapolis, Indiana") is not False
    assert icp_gate._region_is_na("Australia") is False            # foreign, not NA
    assert icp_gate._region_is_na("Sydney, Australia") is False
    assert icp_gate._region_is_na("USA") is True
    assert icp_gate._region_is_na("U.S.") is True
    assert icp_gate._region_is_na("Toronto, Canada") is True
    assert icp_gate._region_is_na("North America") is True
    assert icp_gate._region_is_na("United Kingdom") is False
    assert icp_gate._region_is_na("London, UK") is False
    # end-to-end: an in-band Indiana RE firm QUALIFIES (was wrongly DQ'd on region)
    r = icp_gate.gate_company("real estate", "Indiana", 500_000_000, "AUM_CONFIRMED")
    assert r["icp_result"] == "QUALIFIED", r
    # an Australian firm is DQ'd on region
    r2 = icp_gate.gate_company("real estate", "Australia", 500_000_000, "AUM_CONFIRMED")
    assert r2["icp_result"] == "DISQUALIFIED" and "North America" in r2["icp_reason"]


def test_gate_disqualifies_outside_na():
    r = icp_gate.gate_company("real estate", "United Kingdom", 500_000_000, "AUM_CONFIRMED")
    assert r["icp_result"] == "DISQUALIFIED" and "North America" in r["icp_reason"]


# --- PART 2: PREMIUM firm-type retry + errored-research handling (offline) --
def _cr_env(complete_json_stub, fresh=None, results=None):
    """Wire company_research's collaborators to offline stubs. Returns (restore_fn).
    `results` overrides the search results (default: one result; pass [] for a
    zero-source search outage)."""
    from src.researcher import company_research as cr
    from src import models
    saved = {"gfc": cr.db.get_fresh_company, "ls": cr.search_client.layered_search,
             "cj": cr.models.complete_json, "cjr": cr.models.complete_json_retry,
             "up": cr.db.upsert_company, "ed": cr.extract_domain}
    _res = [{"title": "src", "url": "https://x.com", "content": "multifamily investor",
             "score": 1.0}] if results is None else results
    cr.db.get_fresh_company = lambda name, days=None: fresh
    cr.search_client.layered_search = lambda *a, **k: list(_res)
    # research_company's MAIN extraction now uses complete_json_retry; the firm-type
    # premium retry still uses complete_json — stub both to the same call-counting stub.
    cr.models.complete_json = complete_json_stub
    cr.models.complete_json_retry = complete_json_stub
    cr.db.upsert_company = lambda **k: dict(k)
    cr.extract_domain = lambda name, results: "x.com"

    def restore():
        cr.db.get_fresh_company, cr.search_client.layered_search = saved["gfc"], saved["ls"]
        cr.models.complete_json, cr.models.complete_json_retry = saved["cj"], saved["cjr"]
        cr.db.upsert_company, cr.extract_domain = saved["up"], saved["ed"]
    return cr, models, restore


def test_premium_retry_rescues_unknown_re_name():
    calls = {"n": 0}
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        from src import models
        calls["n"] += 1
        if calls["n"] == 1:  # DEFAULT research: real summary but type 'unknown'
            return ({"summary": "Northwind Capital is a multifamily investor.",
                     "firm_type": "unknown", "region": "USA", "asset_classes": ["multifamily"],
                     "pain_points": [], "trigger_events": [],
                     "aum": {"value_usd": 500_000_000, "tag": "AUM_CONFIRMED", "basis": "site"},
                     "confidence": 70}, models.Usage())
        return ({"firm_type": "real estate"}, models.Usage())  # PREMIUM retry
    cr, models, restore = _cr_env(stub)
    try:
        _row, research, _u = cr.research_company("Northwind Capital")
        assert calls["n"] == 2, "premium retry should fire for unplaceable type on real research"
        assert research["firm_type"] == "real estate"
    finally:
        restore()


def test_premium_retry_skipped_when_type_already_placed():
    calls = {"n": 0}
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        from src import models
        calls["n"] += 1
        return ({"summary": "x", "firm_type": "real estate", "region": "USA",
                 "asset_classes": [], "pain_points": [], "trigger_events": [],
                 "aum": {"value_usd": 5e8, "tag": "AUM_CONFIRMED"}, "confidence": 80},
                models.Usage())
    cr, models, restore = _cr_env(stub)
    try:
        cr.research_company("Already RE Partners")
        assert calls["n"] == 1, "no premium retry when DEFAULT already placed the type"
    finally:
        restore()


def test_errored_research_not_cached_and_no_retry():
    calls = {"n": 0}
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        calls["n"] += 1
        raise RuntimeError("429 rate limit")   # research fails
    cr, models, restore = _cr_env(stub)
    try:
        row, research, _u = cr.research_company("Broken Firm")
        assert calls["n"] == 1, "failed research must NOT trigger a premium retry"
        assert research["firm_type"] == "unknown"
        assert row["last_researched_at"] is None, "errored research must not be cached fresh"
    finally:
        restore()


def test_errored_cache_row_is_not_served():
    poisoned = {"research_raw": {"summary": "research failed: 400 unavailable",
                                 "firm_type": "unknown"}, "name": "Poisoned Co"}
    calls = {"n": 0}
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        from src import models
        calls["n"] += 1
        return ({"summary": "Poisoned Co is a real estate owner.", "firm_type": "real estate",
                 "region": "USA", "asset_classes": [], "pain_points": [], "trigger_events": [],
                 "aum": {"value_usd": 5e8, "tag": "AUM_CONFIRMED"}, "confidence": 75},
                models.Usage())
    cr, models, restore = _cr_env(stub, fresh=poisoned)
    try:
        _row, research, _u = cr.research_company("Poisoned Co")
        assert calls["n"] >= 1, "a cached FAILED row must be re-researched, not served"
        assert research["firm_type"] == "real estate"
    finally:
        restore()


def test_cancelled_research_does_not_persist():
    # Fix 7 review: a worker abandoned by the per-firm timeout must NOT write to the
    # DB — a late upsert/verdict would clobber the PARKED 'research timeout' marker
    # and silently drop the firm. cancel_event set => no upsert, empty-row sentinel.
    import threading
    ev = threading.Event(); ev.set()
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        from src import models
        return ({"summary": "s", "firm_type": "real estate", "region": "USA",
                 "asset_classes": [], "pain_points": [], "trigger_events": [],
                 "aum": {"value_usd": 5e8, "tag": "AUM_CONFIRMED"}, "confidence": 80},
                models.Usage())
    cr, models, restore = _cr_env(stub)   # upsert would return a NON-empty dict
    try:
        row, _research, _u = cr.research_company("Ghost Co", cancel_event=ev)
        assert row == {}, "cancelled research must not persist (empty-row sentinel)"
    finally:
        restore()


def test_research_null_aum_does_not_crash():
    # Review finding: a successful response with "aum": null must not crash the
    # normalization (which would drop the firm instead of parking it).
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        from src import models
        return ({"summary": "Nullaum RE owns apartments.", "firm_type": "real estate",
                 "region": "USA", "asset_classes": [], "pain_points": [],
                 "trigger_events": [], "aum": None, "confidence": 60}, models.Usage())
    cr, models, restore = _cr_env(stub)
    try:
        _row, research, _u = cr.research_company("Nullaum RE")
        assert isinstance(research["aum"], dict)
        assert research["aum"]["value_usd"] is None
    finally:
        restore()


def test_zero_source_research_not_cached_fresh():
    # PART 5.2 finding: a search OUTAGE (Tavily 432 -> 0 sources) yields name-only
    # research; it must NOT be cached fresh, else the firm can never qualify for 30
    # days once search recovers. last_researched_at must be None.
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        from src import models
        return ({"summary": "Based on the name, likely a US real estate firm.",
                 "firm_type": "real estate", "region": "USA", "asset_classes": [],
                 "pain_points": [], "trigger_events": [], "aum": {"value_usd": None,
                 "tag": "AUM_UNVERIFIED"}, "confidence": 15}, models.Usage())
    cr, models, restore = _cr_env(stub, results=[])   # zero sources
    try:
        row, _research, _u = cr.research_company("No Sources RE")
        assert row["last_researched_at"] is None, "0-source research must not cache fresh"
    finally:
        restore()


def test_zero_source_cache_row_is_re_researched():
    stale = {"research_raw": {"summary": "name-only", "firm_type": "real estate"},
             "source_count": 0, "name": "Stale Co"}
    calls = {"n": 0}
    def stub(prompt, system=None, model=None, temperature=0.2, max_tokens=1500):
        from src import models
        calls["n"] += 1
        return ({"summary": "Real research now.", "firm_type": "real estate", "region": "USA",
                 "asset_classes": [], "pain_points": [], "trigger_events": [],
                 "aum": {"value_usd": 5e8, "tag": "AUM_CONFIRMED"}, "confidence": 80},
                models.Usage())
    cr, models, restore = _cr_env(stub, fresh=stale)   # cached row had 0 sources
    try:
        cr.research_company("Stale Co")
        assert calls["n"] >= 1, "a cached 0-source row must be re-researched, not served"
    finally:
        restore()


# --- AUM layered verification (public giants + unit/sqft proxy) -------------
def test_public_giant_disqualifies_without_aum_or_llm():
    # AvalonBay must DISQUALIFY even with no AUM (would otherwise PARK), no LLM
    r = icp_gate.gate_company("real estate", "USA", None, "AUM_UNVERIFIED", name="AvalonBay")
    assert r["icp_result"] == "DISQUALIFIED" and "public" in r["icp_reason"].lower()


def test_public_giant_name_normalization():
    assert icp_gate.is_public_giant("AvalonBay Communities, Inc.")
    assert icp_gate.is_public_giant("MAA")
    assert icp_gate.is_public_giant("Equity Residential")
    assert icp_gate.is_public_giant("Essex")
    assert not icp_gate.is_public_giant("Monarch Investment & Management Group")


def test_mega_firm_instant_kill_by_name():
    # Layer 1: globally-recognized mega firms are killed by NAME (token subset),
    # before any research call, even with no AUM data.
    for nm in ["KKR", "KKR & Co.", "Blackstone", "Brookfield Asset Management",
               "Carlyle Group", "Oxford Properties Group", "Clarion Partners",
               "Regency Centers, LP", "BXP", "Boston Properties",
               "Federal Realty Investment Trust", "LXP Industrial Trust",
               "Macerich (The Macerich Company)", "Starwood Capital Group"]:
        assert icp_gate.is_public_giant(nm), nm
    # gate: a mega firm DISQUALIFIES with no AUM (does not park)
    r = icp_gate.gate_company("private equity", "USA", None, "AUM_UNVERIFIED", name="KKR")
    assert r["icp_result"] == "DISQUALIFIED" and "above $2B" in r["icp_reason"]


def test_mega_firm_does_not_kill_midmarket():
    # Two-token sets never fire on an unrelated single word; distinctive names only.
    for nm in ["Tower 16 Capital Partners", "Excelsior Capital", "Scout Capital Group",
               "Marcus Partners", "CFH Group", "Monarch Investment & Management Group",
               "Regency Property Management",   # NOT Regency Centers
               "Timberlane Partners", "VennPoint Real Estate"]:
        assert not icp_gate.is_public_giant(nm), nm


def test_public_giant_by_listing_in_research():
    # Detection is via the STRUCTURED `listing` field (research prompt extracts the
    # SUBJECT firm's exchange), never free-text scanning.
    assert icp_gate.is_public_giant("Struct NYSE", {"listing": "NYSE"})
    assert icp_gate.is_public_giant("Struct NASDAQ", {"listing": "nasdaq"})
    assert not icp_gate.is_public_giant("Private Co", {"listing": "none",
                                        "summary": "privately held multifamily operator"})
    # Review finding: free-text exchange mentions in negations / peer comparisons
    # must NOT false-DQ a private firm (the summary is NOT scanned).
    assert not icp_gate.is_public_giant(
        "Priv RE", {"summary": "a private firm; unlike NYSE-listed REITs it is not publicly traded"})
    assert not icp_gate.is_public_giant(
        "Priv RE2", {"summary": "competes with NASDAQ-traded REITs but is privately held"})
    assert not icp_gate.is_public_giant(
        "Priv RE3", {"summary": "private owner-operator",
                     "trigger_events": [{"text": "a peer completed a NASDAQ listing", "url": ""}]})
    # end-to-end: a private, in-band, NA RE firm whose summary name-drops NYSE QUALIFIES
    r = icp_gate.gate_company("real estate", "USA", 800_000_000, "AUM_CONFIRMED",
                              name="Northwood Capital",
                              research_raw={"listing": "none",
                                            "summary": "privately held; unlike NYSE peers, not public"})
    assert r["icp_result"] == "QUALIFIED", r


def test_units_proxy_in_band_qualifies():
    val, basis = icp_gate.estimate_aum(unit_count=3000)   # 3000 * 175k = $525M
    assert val == 3000 * 175_000
    assert "units" in basis
    r = icp_gate.gate_company("real estate", "USA", val, "AUM_ESTIMATED",
                              name="Midtown Apartments", aum_basis=basis)
    assert r["icp_result"] == "QUALIFIED" and "units" in r["icp_reason"]


def test_units_proxy_below_floor_disqualifies():
    val, _ = icp_gate.estimate_aum(unit_count=500)        # $87.5M < $200M
    r = icp_gate.gate_company("real estate", "USA", val, "AUM_ESTIMATED", name="Tiny RE")
    assert r["icp_result"] == "DISQUALIFIED" and "below" in r["icp_reason"]


def test_units_proxy_above_ceiling_disqualifies():
    val, _ = icp_gate.estimate_aum(unit_count=20000)      # $3.5B > $2B
    r = icp_gate.gate_company("real estate", "USA", val, "AUM_ESTIMATED", name="Big RE")
    assert r["icp_result"] == "DISQUALIFIED" and "above" in r["icp_reason"]


def test_sqft_proxy():
    val, basis = icp_gate.estimate_aum(sqft=2_000_000)    # 2M * $200 = $400M
    assert val == 2_000_000 * 200
    assert "sqft" in basis
    r = icp_gate.gate_company("real estate", "USA", val, "AUM_ESTIMATED",
                              name="SqftCo", aum_basis=basis)
    assert r["icp_result"] == "QUALIFIED"


def test_proxy_parses_string_counts():
    assert icp_gate.estimate_aum(unit_count="3,000")[0] == 3000 * 175_000
    assert icp_gate.estimate_aum(unit_count="1.2 million")[0] == 1_200_000 * 175_000
    assert icp_gate.estimate_aum(unit_count=None, sqft=None) == (None, None)


# --- AUM proxy tier: invested-capital / portfolio-value / fund-size proxies ---
def test_gate_proxy_estimate_in_band_qualifies():
    # An ESTIMATED in-band value from an invested-capital proxy QUALIFIES, and the
    # reason carries the proxy basis (audit trail) — the Seyon Group case.
    r = icp_gate.gate_company("real estate", "USA", 800_000_000, "AUM_ESTIMATED",
                              name="Seyon Group",
                              aum_basis="cumulative invested capital, proxy")
    assert r["icp_result"] == "QUALIFIED"
    assert "proxy" in r["icp_reason"]


def test_gate_proxy_estimate_above_ceiling_disqualifies():
    # The $2B ceiling applies to ESTIMATES too (a ceiling is a ceiling).
    r = icp_gate.gate_company("real estate", "USA", 8_000_000_000, "AUM_ESTIMATED",
                              name="Big Proxy Co", aum_basis="portfolio value, proxy")
    assert r["icp_result"] == "DISQUALIFIED" and "above" in r["icp_reason"]


def test_gate_floor_proxy_below_band_parks_but_point_estimate_dqs():
    # A FLOOR-type proxy (invested capital) below the band PARKS (true AUM may be
    # higher) with a "verify manually" reason...
    r = icp_gate.gate_company("real estate", "USA", 150_000_000, "AUM_ESTIMATED",
                              name="Small Proxy Co",
                              aum_basis="cumulative invested capital, proxy")
    assert r["icp_result"] == "PARKED" and "verify manually" in r["icp_reason"]
    # ...but a POINT estimate (units) below the band still DISQUALIFIES (unchanged).
    r2 = icp_gate.gate_company("real estate", "USA", 150_000_000, "AUM_ESTIMATED",
                               name="Small Units Co",
                               aum_basis="est. $150M from 857 units x $175K")
    assert r2["icp_result"] == "DISQUALIFIED" and "below" in r2["icp_reason"]
    # ...and a CONFIRMED below-floor figure still DISQUALIFIES.
    r3 = icp_gate.gate_company("real estate", "USA", 150_000_000, "AUM_CONFIRMED",
                               name="Small Confirmed Co")
    assert r3["icp_result"] == "DISQUALIFIED" and "below" in r3["icp_reason"]


def test_gate_no_dollar_figure_still_parks():
    # No dollar figure at all (value_usd null) parks exactly as before — no change.
    r = icp_gate.gate_company("real estate", "USA", None, "AUM_UNVERIFIED",
                              name="No Dollar Co")
    assert r["icp_result"] == "PARKED"


def test_gate_floor_proxy_at_ceiling_disqualifies():
    # First National case: a FLOOR proxy ("over $2B invested") extracted as exactly
    # $2B is a lower bound AT the ceiling -> DISQUALIFY (was wrongly qualifying via
    # the strict '>' check).
    r = icp_gate.gate_company("private equity", "USA", 2_000_000_000, "AUM_ESTIMATED",
                              name="First National Realty Partners",
                              aum_basis="cumulative invested capital, proxy (over $2B closed)")
    assert r["icp_result"] == "DISQUALIFIED" and "ceiling" in r["icp_reason"]
    # Only FLOOR proxies flip: a CONFIRMED figure exactly at the ceiling, and a
    # non-floor point estimate at the ceiling, both still QUALIFY (policy: 'above' DQs).
    assert icp_gate.gate_company("real estate", "USA", 2_000_000_000, "AUM_CONFIRMED",
                                 name="Exactly2B Co")["icp_result"] == "QUALIFIED"
    assert icp_gate.gate_company("real estate", "USA", 2_000_000_000, "AUM_ESTIMATED",
                                 name="Units2B", aum_basis="est. $2.0B from 11,400 units x $175K"
                                 )["icp_result"] == "QUALIFIED"


def test_gate_no_sources_park_reason_is_distinct():
    # Phase 4.2: source_count=0 parks with a distinct "no web sources" reason (operator
    # re-runs later) vs "AUM not verified" (operator hand-hunts the size).
    r0 = icp_gate.gate_company("unknown", "USA", None, "AUM_UNVERIFIED",
                               name="Ghost Co", source_count=0)
    assert r0["icp_result"] == "PARKED" and "no web sources" in r0["icp_reason"]
    r5 = icp_gate.gate_company("real estate", "USA", None, "AUM_UNVERIFIED",
                               name="Found Co", source_count=5)
    assert r5["icp_result"] == "PARKED" and "AUM not verified" in r5["icp_reason"]
    # source_count unknown (None) must NOT falsely claim "no sources"
    rn = icp_gate.gate_company("real estate", "USA", None, "AUM_UNVERIFIED", name="Legacy Co")
    assert "no web sources" not in rn["icp_reason"]


# --- format guard ----------------------------------------------------------
def test_format_good_body_passes():
    assert style_guard.is_well_formed(_GOOD_BODY)
    assert style_guard.format_violations(_GOOD_BODY) == []


def test_format_missing_greeting_fails():
    body = _GOOD_BODY.replace("Hi Andy,\n\n", "Hey Andy.\n\n")
    v = style_guard.format_violations(body)
    assert any("start with 'Hi '" in x for x in v)


def test_format_missing_signoff_fails():
    body = _GOOD_BODY.rsplit("\n\nHarp", 1)[0]  # drop the sign-off block
    v = style_guard.format_violations(body)
    assert any("sign-off" in x for x in v)


def test_format_wrong_signoff_name_fails():
    body = _GOOD_BODY.replace("Harp\nFounder, X Analyst", "Harpreet\nFounder, X Analyst")
    assert not style_guard.is_well_formed(body)


def test_format_no_paragraph_breaks_fails():
    body = "Hi Andy, everything on one line. Harp\nFounder, X Analyst"
    v = style_guard.format_violations(body)
    assert any("blank-line paragraph breaks" in x for x in v)


def test_format_signoff_needs_blank_line_before():
    # closing sentence jammed into the sign-off (single newline) must fail
    body = ("Hi Andy,\n\nOpening about the firm.\n\n"
            "Closing with a soft ask.\nHarp\nFounder, X Analyst")
    v = style_guard.format_violations(body)
    assert any("preceded by a blank line" in x for x in v)


# --- format guard: length band (140-280 words) -----------------------------
def test_format_length_in_band_passes():
    wc = len(_GOOD_BODY.split())
    assert 140 <= wc <= 280, f"_GOOD_BODY is {wc} words, expected in-band"
    assert style_guard.format_violations(_GOOD_BODY) == []


def test_format_too_short_fails():
    body = ("Hi Andy,\n\nShort note about your multifamily firm.\n\n"
            "Quick ask here.\n\nHarp\nFounder, X Analyst")
    v = style_guard.format_violations(body)
    assert any("too short" in x for x in v)


def test_format_too_long_fails():
    filler = ("multifamily property accounting reconciliations reporting close " * 60).strip()
    body = f"Hi Andy,\n\n{filler}.\n\nA short closing ask goes here.\n\nHarp\nFounder, X Analyst"
    assert len(body.split()) > 350
    v = style_guard.format_violations(body)
    assert any("too long" in x for x in v)


def _wellformed_body(n_words: int) -> str:
    """A well-formed email body (greeting + blank-line breaks + exact sign-off)
    padded to exactly n_words, for exercising the length ceiling."""
    head, close, signoff = "Hi Andy,", "A short closing ask goes here.", "Harp\nFounder, X Analyst"
    fixed = len((head + " " + close + " " + signoff.replace("\n", " ")).split())
    filler = " ".join(["multifamily"] * max(0, n_words - fixed))
    return f"{head}\n\n{filler}\n\n{close}\n\n{signoff}"


def test_format_320_words_passes_under_350_ceiling():
    # A 320-word body (would have failed the old 300 ceiling) now passes.
    body = _wellformed_body(320)
    assert len(body.split()) == 320
    assert style_guard.format_violations(body) == []


def test_format_360_words_still_fails():
    # 360 > 350 still fails — the ceiling still prevents runaway essays.
    body = _wellformed_body(360)
    assert len(body.split()) == 360
    assert any("too long" in x for x in style_guard.format_violations(body))


# --- domain extraction (offline) -------------------------------------------
def test_extract_domain_prefers_name_match_over_higher_scored_decoy():
    # decoy is a NON-directory host with a HIGHER score but no name match;
    # the firm's own lower-scored site must still win (proves the preference,
    # not just the directory filter).
    results = [
        {"url": "https://someaggregator.com/monarch-profile", "score": 0.95},
        {"url": "https://monarchinvestment.com/about", "score": 0.30},
        {"url": "https://linkedin.com/company/monarch", "score": 0.9},
    ]
    assert extract_domain("Monarch Investment & Management Group", results) == "monarchinvestment.com"


def test_extract_domain_multi_part_tld():
    # .com.mx must NOT collapse to 'com.mx' (Mexico is an in-scope region)
    results = [{"url": "https://grupofirma.com.mx/nosotros", "score": 0.6}]
    assert extract_domain("Grupo Firma", results) == "grupofirma.com.mx"
    assert extract_domain("Acme", [{"url": "https://acme.co.uk/", "score": 0.5}]) == "acme.co.uk"


def test_extract_domain_skips_trade_press():
    # CRE trade press writes ABOUT firms; never the firm's own domain
    results = [
        {"url": "https://www.bisnow.com/article-about-redwood", "score": 0.95},
        {"url": "https://redwoodcapital.com/", "score": 0.4},
    ]
    assert extract_domain("Redwood Capital", results) == "redwoodcapital.com"


def test_extract_domain_skips_directories():
    results = [
        {"url": "https://linkedin.com/company/x", "score": 0.99},
        {"url": "https://acmecapital.com/", "score": 0.5},
    ]
    # no name match -> falls back to top-scored NON-directory result
    assert extract_domain("Totally Different Name LLC", results) == "acmecapital.com"


def test_extract_domain_none_when_all_directories():
    results = [
        {"url": "https://linkedin.com/x", "score": 0.9},
        {"url": "https://crunchbase.com/y", "score": 0.8},
    ]
    assert extract_domain("Whatever Firm", results) is None


# --- drafter scope: only this run's own lead ids (DB-backed) ----------------
def test_draft_scope_only_this_runs_lead_ids():
    """Drafting is scoped by the run's OWN qualified lead ids. A different
    lead - even qualified, email-bearing, and on the SAME shared company row
    (the cross-client hazard) - is never drafted. A qualified lead WITHOUT an
    email is also excluded."""
    import uuid
    from src import db
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:  # noqa: BLE001
        print("SKIP test_draft_scope_only_this_runs_lead_ids: no DB")
        return
    sfx = uuid.uuid4().hex[:8]
    # ONE shared company (client_name deliberately set to someone else).
    co = db.upsert_company(name=f"SharedFirm_{sfx}", client_name="SomeOtherClient")
    ids = [co["id"]]
    try:
        la = db.create_lead(co["id"], f"Alice A {sfx}", f"SharedFirm_{sfx}", email="alice@a.com")
        lb = db.create_lead(co["id"], f"Bob B {sfx}", f"SharedFirm_{sfx}", email="bob@b.com")
        lc = db.create_lead(co["id"], f"Cara C {sfx}", f"SharedFirm_{sfx}")  # no email
        for lead in (la, lb, lc):
            db.transition_lead(lead["id"], "qualified", "test")
        # This run "owns" only Alice's id.
        got = {r["id"] for r in _leads_to_draft([la["id"]])}
        assert la["id"] in got                       # own run's lead present
        assert lb["id"] not in got                   # same-company other lead excluded
        # Even if Cara's id is in the set, no email -> excluded.
        got2 = {r["id"] for r in _leads_to_draft([la["id"], lc["id"]])}
        assert la["id"] in got2 and lc["id"] not in got2
    finally:
        with db.conn() as c:
            with c.cursor() as cur:
                cur.execute("DELETE FROM lead_events WHERE lead_id IN "
                            "(SELECT id FROM leads WHERE company_id = ANY(%s))", (ids,))
                cur.execute("DELETE FROM leads WHERE company_id = ANY(%s)", (ids,))
                cur.execute("DELETE FROM companies WHERE id = ANY(%s)", (ids,))
            c.commit()


# --- multi-client: profile-driven angles + gate band (offline) -------------
def test_expand_regions_usa_fans_out():
    assert _expand_regions(["USA"]) == [
        "Northeast US", "Southeast US", "Midwest US", "West Coast US", "Texas"]
    assert _expand_regions(["Canada", "Mexico"]) == ["Canada", "Mexico"]
    assert _expand_regions(None)  # falls back to default set


_ICP_FRAMING = ("investment", "private equity", "owner operator", "fund sponsor",
                "family office", "management group", "competitors", "investor")


def test_angles_built_from_profile_two_asset_classes_and_regions():
    angles = _discovery_angles("Acme", "multifamily",
                               ["multifamily", "student housing"],
                               ["USA", "Canada", "Mexico"])
    qs = [q for q, _t in angles]
    region_angles = [q for q in qs if q.startswith("multifamily real estate investment firms ")]
    assert len(region_angles) == 7           # 5 US subregions + Canada + Mexico
    assert any("student housing real estate owner operator" in q for q in qs)
    assert any("multifamily real estate owner operator" in q for q in qs)
    # ICP framing is present on EVERY angle (never a bare/generic query).
    assert all(any(k in q.lower() for k in _ICP_FRAMING) for q in qs), \
        [q for q in qs if not any(k in q.lower() for k in _ICP_FRAMING)]


def test_angles_retail_never_bare():
    # A 'retail' asset class must be framed as retail REAL ESTATE + ICP role,
    # never a bare "retail firms" query that pulls in retailers.
    qs = [q.lower() for q, _t in _discovery_angles("Gold Triangle", "retail",
                                                    ["retail", "commercial"], ["North America"])]
    assert qs, "expected angles"
    assert all("retail" not in q or "retail real estate" in q for q in qs), \
        [q for q in qs if "retail" in q and "retail real estate" not in q]
    assert all(any(k in q for k in _ICP_FRAMING) for q in qs)


def test_gate_band_from_profile_overrides_default():
    r_def = icp_gate.gate_company("real estate", "USA", 250_000_000, "AUM_CONFIRMED")
    assert r_def["icp_result"] == "QUALIFIED"
    r_prof = icp_gate.gate_company("real estate", "USA", 250_000_000, "AUM_CONFIRMED",
                                   aum_floor=300_000_000, aum_ceiling=2_000_000_000)
    assert r_prof["icp_result"] == "DISQUALIFIED" and "below" in r_prof["icp_reason"]


def test_client_profile_roundtrip():
    import uuid
    from src import db
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:  # noqa: BLE001
        print("SKIP test_client_profile_roundtrip: no DB")
        return
    name = f"TestClient_{uuid.uuid4().hex[:8]}"
    try:
        db.upsert_client_profile(
            name, niche_description="test niche",
            asset_classes=["multifamily", "office"], target_regions=["USA", "Canada"],
            aum_floor=100_000_000, aum_ceiling=1_500_000_000,
            pitch_service_focus="fund accounting")
        p = db.get_client_profile(name)
        assert p["asset_classes"] == ["multifamily", "office"]
        assert p["target_regions"] == ["USA", "Canada"]
        assert float(p["aum_floor"]) == 100_000_000
        assert float(p["aum_ceiling"]) == 1_500_000_000
        assert p["pitch_service_focus"] == "fund accounting"
        db.upsert_client_profile(name, pitch_service_focus="property accounting")
        p2 = db.get_client_profile(name)
        assert p2["pitch_service_focus"] == "property accounting"
        assert p2["asset_classes"] == ["multifamily", "office"]   # unchanged by partial update
    finally:
        with db.conn() as c:
            with c.cursor() as cur:
                cur.execute("DELETE FROM client_profiles WHERE client_name = %s", (name,))
            c.commit()


def test_format_handles_crlf():
    assert style_guard.is_well_formed(_GOOD_BODY.replace("\n", "\r\n"))


# --- smart-quote stripping -------------------------------------------------
def test_strip_straight_quotes():
    assert _strip_quotes('"Kingbird Investments"') == "Kingbird Investments"
    assert _strip_quotes("'Kingbird'") == "Kingbird"


def test_strip_curly_double_quotes():
    assert _strip_quotes("“Kingbird Investments”") == "Kingbird Investments"


def test_strip_curly_single_quotes():
    assert _strip_quotes("‘Monarch’") == "Monarch"


def test_strip_mixed_and_nested_quotes():
    assert _strip_quotes("“'Acme Capital'”") == "Acme Capital"


def test_strip_quotes_noop_when_unquoted():
    assert _strip_quotes("Kingbird Investments") == "Kingbird Investments"


# --- competitor exclusion filter -------------------------------------------
def test_exclude_brokerages():
    assert _is_excluded("CBRE", "commercial real estate services")
    assert _is_excluded("Cushman & Wakefield", "owns and operates commercial properties")
    assert _is_excluded("Colliers", "")
    assert _is_excluded("RE/MAX", "brokerage")
    assert _is_excluded("SVN International Corp.", "property management company")


def test_exclude_lenders_and_services():
    assert _is_excluded("Walker & Dunlop", "commercial real estate finance and advisory")
    assert _is_excluded("Apollo Commercial Real Estate Finance, Inc.", "owns property")
    assert _is_excluded("Carmichael Engineering Ltd.", "engineering company")
    assert _is_excluded("Metta Coworking", "coworking operator")


def test_keep_owner_operators():
    assert not _is_excluded("Hines", "property management company")
    assert not _is_excluded("Greystar", "owns and operates rental housing")
    assert not _is_excluded("AION Partners", "owns and operates multifamily")
    assert not _is_excluded("Monarch Investment & Management Group", "multifamily owner")
    assert not _is_excluded("RPM Living", "multifamily owner operator and investment manager")
    assert not _is_excluded("Victory Real Estate Investments", "owns and operates retail shopping centers")
    # Owner-operators that ALSO run a third-party management arm must be KEPT
    # (the pure-3rd-party-manager filter must not drop them).
    assert not _is_excluded("Greystar",
                            "owner-operator and the largest third-party property management company in the US")
    assert not _is_excluded("RPM Living",
                            "multifamily owner, developer, and third-party property management")


def test_exclude_pure_third_party_manager():
    # A PURE fee/third-party manager with NO owner/investor signal is excluded.
    assert _is_excluded("SomeCo Realty Services", "third-party property management services for HOAs and condos")
    assert _is_excluded("FeeMgr LLC", "fee-based property management services")


def test_target_name_handling():
    # Bare 'Target' (retailer) is excluded; a real RE firm named 'Target ...' is kept.
    assert _is_excluded("Target", "general merchandise stores")
    assert _is_excluded("Target Inc", "retail stores")
    assert not _is_excluded("Target Realty Partners", "owns and operates industrial real estate")


def test_exclude_retailers_and_consumer_brands():
    # The exact garbage the bad run surfaced must never survive discovery.
    for nm, why in [("Amazon", "e-commerce and retail"),
                    ("Walmart", "multinational retail corporation"),
                    ("Target", "big-box retailer, department stores"),
                    ("Costco", "warehouse club retailer"),
                    ("Kroger", "supermarket chain / grocery retailer"),
                    ("IKEA", "furniture retailer"),
                    ("7-Eleven", "convenience store chain"),
                    ("Trader Joe's", "grocery chain"),
                    ("Sephora", "cosmetics retailer")]:
        assert _is_excluded(nm, why), f"{nm} should be excluded"


def test_exclude_lenders_retail_brokers_pure_pm():
    assert _is_excluded("Rocket Mortgage", "residential mortgage lender")
    assert _is_excluded("Atlantic Retail", "retail real estate brokerage and advisory services")
    assert _is_excluded("MacKenzie Commercial Real Estate", "commercial real estate brokerage services")
    assert _is_excluded("FirstService Residential", "third-party property management for HOAs")


def test_keep_retail_real_estate_investor():
    # A RETAIL REAL ESTATE owner/investor is ICP and must be KEPT even when its
    # rationale names its retail/grocery TENANTS (retailer keywords are matched
    # on the NAME only, never the why).
    assert not _is_excluded("Regency Centers",
                            "owns shopping centers leased to national grocery chains and retailers")
    assert not _is_excluded("Brixmor Property Group",
                            "owns and operates centers anchored by grocers and national retailers")
    assert not _is_excluded("Federal Realty",
                            "owns retail centers with department store and grocery anchors")


# --- profile approval gate --------------------------------------------------
def test_parse_profile_edits():
    from src.approval import telegram_queue as tq
    e = tq._parse_profile_edits(
        "type=real estate investment assets=commercial, office, retail "
        "regions=North America focus=property accounting")
    assert e["type"] == "real estate investment"
    assert e["assets"] == ["commercial", "office", "retail"]
    assert e["regions"] == ["North America"]
    assert e["focus"] == "property accounting"


def test_profile_approval_gate_routing():
    # New client (no saved profile) -> approval prompt, no search.
    # Existing client (has profile) -> straight to discovery, no approval.
    from src.approval import telegram_queue as tq
    started, msgs = [], []
    saved = {"send": tq.send, "start": tq._start_thread,
             "gap": tq.db.get_active_prospect,
             "lcr": tq.db.latest_completed_run_with_candidates,
             "gcp": tq.db.get_client_profile, "sap": tq.db.set_active_prospect}
    try:
        tq.send = lambda text, chat_id=None: msgs.append(text)
        tq._start_thread = lambda target, *a: started.append(target.__name__)
        tq.db.get_active_prospect = lambda: None
        tq.db.latest_completed_run_with_candidates = lambda c: None
        tq.db.set_active_prospect = lambda *a, **k: None

        tq.db.get_client_profile = lambda c: None            # NEW client
        started.clear(); msgs.clear()
        tq._handle_prospect("Brand New Co")
        assert started == ["_run_derive_profile"], started
        assert any("approval" in m.lower() or "deriving" in m.lower() for m in msgs)

        tq.db.get_client_profile = lambda c: {"client_name": c}   # EXISTING client
        started.clear(); msgs.clear()
        tq._handle_prospect("Kingbird Investments")
        assert started == ["_run_discovery"], started
        assert not any("approval" in m.lower() for m in msgs)
    finally:
        tq.send, tq._start_thread = saved["send"], saved["start"]
        tq.db.get_active_prospect = saved["gap"]
        tq.db.latest_completed_run_with_candidates = saved["lcr"]
        tq.db.get_client_profile = saved["gcp"]
        tq.db.set_active_prospect = saved["sap"]


# --- bot stability: /cancel, stale auto-clear, startup cleanup --------------
def test_worker_progress_aborts_on_cancel():
    from src.approval import telegram_queue as tq
    sent = []
    saved = tq.send
    try:
        tq.send = lambda t, chat_id=None: sent.append(t)
        tq._cancel.clear()
        tq._worker_progress("one")                 # normal -> forwards
        assert sent == ["one"]
        tq._cancel.set()
        raised = False
        try:
            tq._worker_progress("two")             # cancelled -> raises, no send
        except tq._Cancelled:
            raised = True
        assert raised and sent == ["one"]
    finally:
        tq.send = saved
        tq._cancel.clear()


def test_cancel_clears_all_state():
    import time
    from src.approval import telegram_queue as tq
    from src import db
    msgs, rec = [], []
    saved = {"send": tq.send, "gap": db.get_active_prospect, "cf": db.clear_active_prospect,
             "car": db.cancel_active_runs, "rl": db.release_poller_lock}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        db.get_active_prospect = lambda: {"client": "X"}
        db.clear_active_prospect = lambda: rec.append("clear_flag")
        db.cancel_active_runs = lambda: (rec.append("cancel_runs") or 2)
        db.release_poller_lock = lambda pid: rec.append("release_lock")
        tq._pending_profiles["u"] = {"client_name": "X"}
        tq._pending_ts["u"] = time.time()
        tq._cancel.clear()
        tq._handle_cancel()
        assert "clear_flag" in rec and "cancel_runs" in rec and "release_lock" in rec
        assert not tq._pending_profiles and not tq._pending_ts
        assert tq._cancel.is_set()                 # running worker will abort
        assert any("cancelled" in m.lower() for m in msgs)
    finally:
        tq.send = saved["send"]
        db.get_active_prospect = saved["gap"]; db.clear_active_prospect = saved["cf"]
        db.cancel_active_runs = saved["car"]; db.release_poller_lock = saved["rl"]
        tq._cancel.clear(); tq._pending_profiles.clear(); tq._pending_ts.clear()


def test_stale_run_auto_clears_and_fresh_run_is_kept():
    from src.approval import telegram_queue as tq
    from src import db
    msgs, rec = [], []
    saved = {"send": tq.send, "gap": db.get_active_prospect, "age": db.flag_age_seconds,
             "cf": db.clear_active_prospect, "car": db.cancel_active_runs}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        db.get_active_prospect = lambda: {"client": "X"}
        db.clear_active_prospect = lambda: rec.append("clear")
        db.cancel_active_runs = lambda: (rec.append("cancel") or 1)

        # STALE (7 min) with no live worker -> auto-cleared.
        db.flag_age_seconds = lambda k: 420.0
        assert not tq._busy.locked()
        tq._reap_stale_state()
        assert "clear" in rec and any("stale" in m.lower() for m in msgs)

        # FRESH (10 s) with a live worker -> kept (not cleared).
        rec.clear(); msgs.clear()
        db.flag_age_seconds = lambda k: 10.0
        tq._busy.acquire()
        try:
            tq._reap_stale_state()
        finally:
            tq._busy.release()
        assert "clear" not in rec
    finally:
        tq.send = saved["send"]; db.get_active_prospect = saved["gap"]
        db.flag_age_seconds = saved["age"]; db.clear_active_prospect = saved["cf"]
        db.cancel_active_runs = saved["car"]
        tq._cancel.clear()


def test_awaiting_confirmation_survives_short_idle_but_clears_after_30min():
    """PART 3 regression: a user-paced awaiting_confirmation run has NO worker by
    design; the stale-reap must not clear it on the short/no-worker check (that
    cancelled a 12s-old list and broke reuse->confirm). Only a 30-min idle clears it."""
    from src.approval import telegram_queue as tq
    from src import db
    msgs, rec = [], []
    saved = {"send": tq.send, "gap": db.get_active_prospect, "age": db.flag_age_seconds,
             "cf": db.clear_active_prospect, "car": db.cancel_active_runs, "gr": db.get_run}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        db.get_active_prospect = lambda: {"client": "X", "run_id": 42}
        db.get_run = lambda rid: {"id": rid, "status": "awaiting_confirmation"}
        db.clear_active_prospect = lambda: rec.append("clear")
        db.cancel_active_runs = lambda: (rec.append("cancel") or 1)
        assert not tq._busy.locked()          # awaiting => no worker (the trap condition)

        db.flag_age_seconds = lambda k: 12.0   # 12s old, no worker
        tq._reap_stale_state()
        assert "clear" not in rec, "awaiting list must survive a short idle with no worker"

        rec.clear(); msgs.clear()
        db.flag_age_seconds = lambda k: 1860.0  # 31 min old
        tq._reap_stale_state()
        assert "clear" in rec and any("stale" in m.lower() for m in msgs)
    finally:
        tq.send = saved["send"]; db.get_active_prospect = saved["gap"]
        db.flag_age_seconds = saved["age"]; db.clear_active_prospect = saved["cf"]
        db.cancel_active_runs = saved["car"]; db.get_run = saved["gr"]
        tq._cancel.clear()


def test_reuse_offer_sets_awaiting_and_confirm_with_trailing_words_proceeds():
    """PART 3: the reuse offer sets the SAME awaiting_confirmation state as a fresh
    list, and '/prospect confirm <trailing words>' proceeds with the cached list."""
    from src.approval import telegram_queue as tq
    from src import db
    from src.prospect import competitor_engine as ce
    msgs, started, updates = [], [], []
    saved = {"send": tq.send, "reap": tq._reap_stale_state, "wr": tq._worker_running,
             "gap": db.get_active_prospect, "lcr": db.latest_completed_run_with_candidates,
             "cr": db.create_run, "ur": db.update_run, "sap": db.set_active_prospect,
             "gcp": db.get_client_profile, "lawc": db.latest_run_awaiting_confirmation,
             "claim": db.claim_run_for_processing, "st": tq._start_thread, "excl": ce._is_excluded}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        tq._reap_stale_state = lambda: None
        tq._worker_running = lambda: False
        db.get_active_prospect = lambda: None
        db.latest_completed_run_with_candidates = lambda c: {
            "id": 1, "candidates": [{"name": "Foo RE", "why": ""}],
            "niche_summary": "n", "created_at": "2026-07-01"}
        db.create_run = lambda c: {"id": 99}
        db.update_run = lambda rid, **k: updates.append(k)
        db.set_active_prospect = lambda *a, **k: None
        db.get_client_profile = lambda c: {"client_name": c}
        ce._is_excluded = lambda name, why: False

        tq._begin_prospect("Test Client")
        assert any("previous run" in m.lower() for m in msgs), "reuse offer not sent"
        assert any(u.get("status") == "awaiting_confirmation" for u in updates), \
            "reuse offer must set awaiting_confirmation (same as a fresh list)"

        db.latest_run_awaiting_confirmation = lambda: {
            "id": 99, "candidates": [{"name": "Foo RE", "why": ""}]}
        db.claim_run_for_processing = lambda rid, names: {
            "id": rid, "client_name": "Test Client", "candidates": [{"name": "Foo RE"}]}
        tq._start_thread = lambda target, *a: started.append(target.__name__)
        tq._handle_prospect("confirm to proceed with all")   # trailing words tolerated
        assert "_run_processing" in started, "confirm must proceed with the awaiting run"
    finally:
        tq.send = saved["send"]; tq._reap_stale_state = saved["reap"]
        tq._worker_running = saved["wr"]; db.get_active_prospect = saved["gap"]
        db.latest_completed_run_with_candidates = saved["lcr"]; db.create_run = saved["cr"]
        db.update_run = saved["ur"]; db.set_active_prospect = saved["sap"]
        db.get_client_profile = saved["gcp"]; db.latest_run_awaiting_confirmation = saved["lawc"]
        db.claim_run_for_processing = saved["claim"]; tq._start_thread = saved["st"]
        ce._is_excluded = saved["excl"]


def test_new_prospect_supersedes_pending_profile():
    from src.approval import telegram_queue as tq
    from src import db
    saved = {"send": tq.send, "start": tq._start_thread, "gap": db.get_active_prospect,
             "age": db.flag_age_seconds, "lcr": db.latest_completed_run_with_candidates,
             "gcp": db.get_client_profile, "sap": db.set_active_prospect}
    try:
        tq.send = lambda t, chat_id=None: None
        tq._start_thread = lambda target, *a: None
        db.get_active_prospect = lambda: None
        db.flag_age_seconds = lambda k: None
        db.latest_completed_run_with_candidates = lambda c: None
        db.get_client_profile = lambda c: {"client_name": c}   # existing -> proceeds
        db.set_active_prospect = lambda *a, **k: None
        tq._pending_profiles[str(tq.config.TELEGRAM_USER_ID)] = {"client_name": "Old"}
        tq._pending_ts[str(tq.config.TELEGRAM_USER_ID)] = 1.0
        tq._handle_prospect("Some Existing Client")
        assert not tq._pending_profiles          # new /prospect dropped the stale pending
    finally:
        tq.send = saved["send"]; tq._start_thread = saved["start"]
        db.get_active_prospect = saved["gap"]; db.flag_age_seconds = saved["age"]
        db.latest_completed_run_with_candidates = saved["lcr"]
        db.get_client_profile = saved["gcp"]; db.set_active_prospect = saved["sap"]
        tq._pending_profiles.clear(); tq._pending_ts.clear()


def test_startup_cleanup_semantics_and_never_raises():
    from src import db
    saved = {"gap": db.get_active_prospect, "cf": db.clear_active_prospect,
             "car": db.cancel_active_runs}
    try:
        rec = []
        db.get_active_prospect = lambda: {"client": "X"}
        db.clear_active_prospect = lambda: rec.append("clear")
        db.cancel_active_runs = lambda: (rec.append("cancel") or 3)
        info = db.startup_cleanup()
        assert info["flag_cleared"] is True and info["runs_cancelled"] == 3
        assert "clear" in rec and "cancel" in rec

        # Must never raise even if an inner call blows up.
        def boom():
            raise RuntimeError("db down")
        db.get_active_prospect = boom
        db.cancel_active_runs = boom
        info2 = db.startup_cleanup()
        assert isinstance(info2, dict)             # swallowed, returned safely
    finally:
        db.get_active_prospect = saved["gap"]; db.clear_active_prospect = saved["cf"]
        db.cancel_active_runs = saved["car"]


# --- client comprehension: premium routing + ambiguity gate -----------------
def test_client_comprehension_uses_premium_model():
    # The CLIENT step routes to PREMIUM_MODEL; a competitor stays on DEFAULT_MODEL.
    from src.researcher import company_research as cr
    from src import config, models
    captured = {}
    saved = {"cj": models.complete_json, "cjr": models.complete_json_retry,
             "ls": cr.search_client.layered_search,
             "gfc": cr.db.get_fresh_company, "uc": cr.db.upsert_company}
    try:
        def fake_cj(prompt, model=None, **kw):
            captured["model"] = model
            return ({"resolved": True, "firm_name": "X", "summary": "s",
                     "firm_type": "real estate", "region": "USA",
                     "asset_classes": ["multifamily"], "aum": {"value_usd": None}}, models.Usage())
        models.complete_json = fake_cj
        models.complete_json_retry = fake_cj      # main extraction path
        cr.search_client.layered_search = lambda *a, **k: []
        cr.db.get_fresh_company = lambda name: None
        cr.db.upsert_company = lambda **kw: {"id": 1, "research_raw": kw.get("research_raw")}
        cr.research_company("Some Client", is_client=True)
        assert captured["model"] == config.PREMIUM_MODEL
        captured.clear()
        cr.research_company("Some Competitor", is_client=False)
        assert captured["model"] == config.DEFAULT_MODEL
    finally:
        models.complete_json = saved["cj"]; models.complete_json_retry = saved["cjr"]
        cr.search_client.layered_search = saved["ls"]
        cr.db.get_fresh_company = saved["gfc"]; cr.db.upsert_company = saved["uc"]


def test_client_comprehension_coerces_resolved_string():
    # A model returning the STRING "false" must yield a real bool False.
    from src.researcher import company_research as cr
    from src import models
    saved = {"cj": models.complete_json, "cjr": models.complete_json_retry,
             "ls": cr.search_client.layered_search,
             "gfc": cr.db.get_fresh_company, "uc": cr.db.upsert_company}
    try:
        _stub = lambda prompt, model=None, **kw: (
            {"resolved": "false", "firm_name": "X", "summary": "s",
             "asset_classes": [], "aum": {"value_usd": None},
             "alternatives": [{"name": "A", "description": "d"}]}, models.Usage())
        models.complete_json = _stub
        models.complete_json_retry = _stub
        cr.search_client.layered_search = lambda *a, **k: []
        cr.db.get_fresh_company = lambda name: None
        cr.db.upsert_company = lambda **kw: {"id": 1, "research_raw": kw.get("research_raw")}
        _r, research, _u = cr.research_company("Ambiguous", is_client=True)
        assert research["resolved"] is False   # coerced from the string
    finally:
        models.complete_json = saved["cj"]; models.complete_json_retry = saved["cjr"]
        cr.search_client.layered_search = saved["ls"]
        cr.db.get_fresh_company = saved["gfc"]; cr.db.upsert_company = saved["uc"]


def test_client_comprehension_survives_malformed_output():
    # Array-wrapped (non-dict) output and a non-string firm_name must not crash;
    # an errored client row must NOT be cached (so the next attempt re-runs premium).
    from src.researcher import company_research as cr
    from src import models
    up = {}
    saved = {"cj": models.complete_json, "cjr": models.complete_json_retry,
             "ls": cr.search_client.layered_search,
             "gfc": cr.db.get_fresh_company, "uc": cr.db.upsert_company}
    try:
        cr.search_client.layered_search = lambda *a, **k: []
        cr.db.get_fresh_company = lambda name: None
        cr.db.upsert_company = lambda **kw: (up.update(kw), {"id": 1, "research_raw": kw.get("research_raw")})[1]
        # (a) top-level list (parses fine, not a dict) -> fail-open + NOT cached
        _stub_a = lambda p, model=None, **k: ([{"resolved": True}], models.Usage())
        models.complete_json = _stub_a; models.complete_json_retry = _stub_a
        _r, res, _u = cr.research_company("Client A", is_client=True)
        assert res["resolved"] is True                      # fail-open, no crash
        assert up.get("last_researched_at") is None          # errored row left un-fresh
        # (b) truthy non-string firm_name -> falls back to the typed name; success caches
        up.clear()
        _stub_b = lambda p, model=None, **k: (
            {"resolved": True, "firm_name": ["X LLC"], "summary": "s",
             "asset_classes": [], "aum": {"value_usd": None}}, models.Usage())
        models.complete_json = _stub_b; models.complete_json_retry = _stub_b
        _r2, res2, _u2 = cr.research_company("Client B", is_client=True)
        assert res2["firm_name"] == "Client B"
        assert up.get("last_researched_at") is not None
    finally:
        models.complete_json = saved["cj"]; models.complete_json_retry = saved["cjr"]
        cr.search_client.layered_search = saved["ls"]
        cr.db.get_fresh_company = saved["gfc"]; cr.db.upsert_company = saved["uc"]


def test_ambiguity_gate_blocks_discovery():
    from src.approval import telegram_queue as tq
    msgs = []; called = {"discovery": False}
    saved = {"send": tq.send, "rc": tq.competitor_engine.resolve_client,
             "rd": tq.competitor_engine.run_discovery, "cf": tq.db.clear_active_prospect,
             "cr": tq.db.create_run}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        # resolve_client now returns (research, usage) so the premium comprehension
        # cost can be rolled into the run (Item 6).
        tq.competitor_engine.resolve_client = lambda c, progress=None: ({
            "resolved": False, "alternatives": [{"name": "A Co", "description": "x"},
                                                 {"name": "B Co", "description": "y"}]}, None)
        tq.competitor_engine.run_discovery = lambda *a, **k: called.__setitem__("discovery", True)
        tq.db.clear_active_prospect = lambda: None
        tq.db.create_run = lambda c: {"id": 999}
        tq._cancel.clear(); tq._pending_ambiguous.clear()
        tq._run_discovery("Ambiguous Co")
        assert called["discovery"] is False                       # discovery NOT started
        assert tq._pending_ambiguous.get(str(tq.config.TELEGRAM_USER_ID))
        assert any("couldn't confidently identify" in m.lower() for m in msgs)
    finally:
        tq.send = saved["send"]; tq.competitor_engine.resolve_client = saved["rc"]
        tq.competitor_engine.run_discovery = saved["rd"]; tq.db.clear_active_prospect = saved["cf"]
        tq.db.create_run = saved["cr"]
        tq._pending_ambiguous.clear(); tq._cancel.clear()


def test_prospect_pick_selects_alternative():
    from src.approval import telegram_queue as tq
    captured = {}
    saved = {"bp": tq._begin_prospect, "send": tq.send}
    try:
        tq.send = lambda t, chat_id=None: None
        # pick must go straight to _begin_prospect (NOT the command parser), so a
        # firm name starting with a command token can't be misrouted.
        tq._begin_prospect = lambda name: captured.__setitem__("name", name)
        key = str(tq.config.TELEGRAM_USER_ID)
        tq._pending_ambiguous[key] = {"client": "Ambiguous Co", "ts": tq.time.time(),
            "alternatives": [{"name": "Trimont Real Estate Advisors", "description": "x"},
                             {"name": "Yes Communities", "description": "y"}]}
        tq._handle_pick("1")
        assert captured.get("name") == "Trimont Real Estate Advisors"   # not misrouted by 'trim'
        assert key not in tq._pending_ambiguous                          # cleared after pick
    finally:
        tq._begin_prospect = saved["bp"]; tq.send = saved["send"]
        tq._pending_ambiguous.clear()


def test_ambiguity_pending_auto_clears_and_cancel_clears():
    from src.approval import telegram_queue as tq
    from src import db
    key = str(tq.config.TELEGRAM_USER_ID)
    saved = {"gap": db.get_active_prospect, "send": tq.send, "cf": db.clear_active_prospect,
             "car": db.cancel_active_runs, "rl": db.release_poller_lock}
    try:
        tq.send = lambda t, chat_id=None: None
        db.get_active_prospect = lambda: None
        db.clear_active_prospect = lambda: None
        db.cancel_active_runs = lambda: 0
        db.release_poller_lock = lambda pid: None
        # (a) stale ambiguity auto-expires on the next command
        tq._pending_ambiguous[key] = {"client": "X", "alternatives": [], "ts": tq.time.time() - 999}
        tq._reap_stale_state()
        assert key not in tq._pending_ambiguous
        # (b) /cancel clears a fresh ambiguity
        tq._pending_ambiguous[key] = {"client": "X", "alternatives": [], "ts": tq.time.time()}
        tq._handle_cancel()
        assert key not in tq._pending_ambiguous
    finally:
        db.get_active_prospect = saved["gap"]; tq.send = saved["send"]
        db.clear_active_prospect = saved["cf"]; db.cancel_active_runs = saved["car"]
        db.release_poller_lock = saved["rl"]
        tq._pending_ambiguous.clear(); tq._cancel.clear()


# --- active-prospect flag (DB-backed; skips cleanly if no DB) ---------------
def test_active_prospect_flag_cycle():
    from src import db
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:  # noqa: BLE001
        print("SKIP test_active_prospect_flag_cycle: no DB")
        return
    saved = db.get_active_prospect()  # preserve any real active run
    try:
        db.clear_active_prospect()
        assert db.get_active_prospect() is None            # cleared
        db.set_active_prospect("Test Client Co", 999)
        a = db.get_active_prospect()                        # set
        assert a is not None
        assert a["client"] == "Test Client Co"
        assert a["run_id"] == 999
        db.clear_active_prospect()
        assert db.get_active_prospect() is None            # cleared again
    finally:
        if saved:
            db.set_active_prospect(saved.get("client"), saved.get("run_id"))
        else:
            db.clear_active_prospect()


# --- template parser -------------------------------------------------------
def test_template_subject_first_line_blank_then_body():
    subject, body = parse_template("property accounting at [Firm]\n\nHi [First],\nBody here.")
    assert subject == "property accounting at [Firm]"
    assert body.startswith("Hi [First],")


def test_template_explicit_subject_prefix():
    subject, body = parse_template("Subject: quick idea\n\nHello there.")
    assert subject == "quick idea"
    assert body == "Hello there."


def test_template_no_subject():
    subject, body = parse_template("Just a body with no subject line and no blank.")
    assert subject is None and body.startswith("Just a body")


# --- Item 4: tolerant AUM parsing ------------------------------------------
def test_parse_aum_tolerant():
    assert parse_aum("800M") == 800_000_000
    assert parse_aum("1.2B") == 1_200_000_000
    assert parse_aum("$800M") == 800_000_000
    assert parse_aum("800 million") == 800_000_000
    assert parse_aum("1.2 billion") == 1_200_000_000
    assert parse_aum("~$1B") == 1_000_000_000
    assert parse_aum("500000000") == 500_000_000        # large bare number = raw dollars
    assert parse_aum("800") == 800_000_000              # small bare number = millions
    assert parse_aum("1,250,000,000") == 1_250_000_000  # commas stripped
    assert parse_aum("500k") == 500_000
    assert parse_aum("") is None
    assert parse_aum("not a number") is None
    assert parse_aum(None) is None


# --- Item 3: Apollo endpoint + domain hint reaches the payload -------------
def test_apollo_uses_people_match_not_bulk():
    from src.enrichment import apollo
    assert apollo.MATCH_URL.endswith("/people/match")
    assert "bulk_match" not in apollo.MATCH_URL
    assert not hasattr(apollo, "BULK_MATCH_URL")   # bulk path fully removed (403 on our plan)


def test_apollo_detail_includes_domain_hint():
    from src.enrichment import apollo
    lead = {"id": 1, "first_name": "Jane", "last_name": "Doe",
            "company": "Monarch Investment", "domain": "monarchinvestment.com"}
    d = apollo._detail_for(lead)
    assert d["domain"] == "monarchinvestment.com"      # domain reaches the request
    assert d["organization_name"] == "Monarch Investment"
    assert d["first_name"] == "Jane" and d["last_name"] == "Doe"
    # No domain on the lead -> key simply absent (no crash, no empty string).
    d2 = apollo._detail_for({"full_name": "No Domain", "company": "X"})
    assert "domain" not in d2 and d2["name"] == "No Domain"


# --- Item 1: live per-firm progress lines ----------------------------------
def test_firm_progress_line_formats():
    q = _firm_progress_line(12, 43, {
        "name": "Monarch Investment", "icp_result": "QUALIFIED",
        "aum_value": 1_000_000_000, "aum_tag": "AUM_ESTIMATED", "unit_count": 15000})
    assert q == "✅ [12/43] Monarch Investment — QUALIFIED (est. $1.0B, 15K units)"

    d = _firm_progress_line(13, 43, {
        "name": "CBRE", "icp_result": "DISQUALIFIED", "icp_reason": "brokerage"})
    assert d.startswith("❌ [13/43] CBRE — disqualified (brokerage")

    p = _firm_progress_line(14, 43, {
        "name": "Timberlane Partners", "icp_result": "PARKED",
        "icp_reason": "AUM unverified"})
    assert p.startswith("◐ [14/43] Timberlane Partners — parked (AUM unverified")

    f = _firm_progress_line(15, 43, {"name": "Boomco", "error": "timeout"})
    assert f.startswith("❌ [15/43] Boomco — failed (timeout")

    # A confirmed AUM shows no "est." prefix.
    q2 = _firm_progress_line(1, 1, {
        "name": "CFH", "icp_result": "QUALIFIED",
        "aum_value": 800_000_000, "aum_tag": "AUM_CONFIRMED", "unit_count": None})
    assert q2 == "✅ [1/1] CFH — QUALIFIED ($800M)"


# --- Item 2: aggregated no-email miss list ---------------------------------
def test_format_misses():
    out = _format_misses([
        {"full_name": "Jane Doe", "title": "CFO", "company": "Acme RE", "domain": "acme.com"},
        {"full_name": "Bob Roe", "title": None, "company": "Beta Capital", "domain": None},
    ])
    lines = out.split("\n")
    assert lines[0] == "No verified email (manual hunt needed):"
    assert lines[1] == "- Jane Doe — CFO, Acme RE (acme.com)"
    assert lines[2] == "- Bob Roe — —, Beta Capital"


# --- Item 5: trigger_events shape + source-link attribution ----------------
def test_event_texts_handles_both_shapes():
    events = [{"text": "Closed $1.1B acquisition", "url": "http://x.com/a"},
              "raised a new fund",                       # old bare-string row
              {"text": "", "url": "http://y.com"}]       # empty text dropped
    assert _event_texts(events) == ["Closed $1.1B acquisition", "raised a new fund"]
    assert _event_texts(None) == []


def test_source_line_cites_matching_event():
    events = [{"text": "Closed a $1.1B acquisition of 15 properties",
               "url": "https://news.example.com/deal"}]
    lead = {"first_name": "Brianna", "full_name": "Brianna Smith"}
    body = "Congrats on the recent acquisition of those properties."
    line = _source_line("Timberlane Partners", lead, body, events)
    assert line.startswith("Timberlane Partners (Brianna): draft cites")
    assert "source: https://news.example.com/deal" in line


def test_source_line_no_claim_cited():
    lead = {"first_name": "Sam", "full_name": "Sam Lee"}
    # No trigger events at all -> explicit "(no specific claim cited)".
    assert _source_line("Foo RE", lead, "generic note", []) == \
        "Foo RE (Sam): (no specific claim cited)"
    # Event exists but body references nothing from it -> also no claim cited.
    events = [{"text": "acquired a Dallas tower", "url": "http://z"}]
    assert "(no specific claim cited)" in _source_line("Foo RE", lead, "unrelated body", events)


def test_source_line_event_without_url():
    events = [{"text": "expanded into Texas", "url": ""}]   # old row, no source URL
    lead = {"first_name": "Dana", "full_name": "Dana Fox"}
    body = "Saw that you expanded into Texas recently."
    line = _source_line("Bar Capital", lead, body, events)
    assert "draft cites" in line and "(no link on file)" in line


def test_normalize_trigger_events():
    from src.researcher.company_research import _normalize_trigger_events
    out = _normalize_trigger_events([
        {"text": "acquisition", "url": "https://ok.com/1"},
        "bare string event",                    # old shape -> url ""
        {"text": "no url event", "url": "not-a-url"},  # bad url dropped to ""
        {"text": "", "url": "https://x.com"},   # empty text dropped entirely
        {"event": "alt key", "source": "http://alt.com"},  # alt keys honored
    ])
    assert out == [
        {"text": "acquisition", "url": "https://ok.com/1"},
        {"text": "bare string event", "url": ""},
        {"text": "no url event", "url": ""},
        {"text": "alt key", "url": "http://alt.com"},
    ]


# --- Item 4: manual_qualify gate outcomes (offline monkeypatch) ------------
def test_manual_qualify_in_band_qualifies_and_logs_operator_event():
    from src.prospect import competitor_engine as ce
    events = []
    saved = {"gbi": ce.db.get_company_by_id, "up": ce.db.upsert_company,
             "gcp": ce.db.get_client_profile, "gate": ce.icp_gate.gate_company,
             "sci": ce.db.set_company_icp, "roe": ce.db.record_operator_event,
             "pqc": ce.process_qualified_company}
    try:
        ce.db.get_company_by_id = lambda cid: {
            "id": cid, "name": "CFH Group", "research_raw": {"firm_type": "real estate"},
            "region": "USA", "client_name": "Someone", "aum_tag": "AUM_UNVERIFIED"}
        ce.db.upsert_company = lambda **k: {}
        ce.db.get_client_profile = lambda name: None
        ce.icp_gate.gate_company = lambda **k: {
            "icp_result": "QUALIFIED", "icp_reason": "in band", "aum_tag": "AUM_CONFIRMED"}
        icp_calls = []
        ce.db.set_company_icp = lambda cid, res, reason, tag=None: icp_calls.append((res, tag))
        ce.db.record_operator_event = lambda to_state, detail, lead_id=None: events.append((to_state, detail))
        ce.process_qualified_company = lambda cid, **k: (2, 1, 1)
        res = ce.manual_qualify(7, 800_000_000, progress=lambda m: None)
        assert res["verdict"] == "QUALIFIED"
        assert res["message"] == "CFH Group: QUALIFIED at $800M — 2 contacts, 1 email, 1 draft."
        assert icp_calls[0] == ("QUALIFIED", "AUM_CONFIRMED")
        assert events and events[0][0] == "qualified"      # operator event logged
        assert events[0][1]["name"] == "CFH Group"
    finally:
        (ce.db.get_company_by_id, ce.db.upsert_company, ce.db.get_client_profile,
         ce.icp_gate.gate_company, ce.db.set_company_icp, ce.db.record_operator_event,
         ce.process_qualified_company) = (saved["gbi"], saved["up"], saved["gcp"],
             saved["gate"], saved["sci"], saved["roe"], saved["pqc"])


def test_manual_qualify_out_of_band_disqualifies():
    from src.prospect import competitor_engine as ce
    events = []
    saved = {"gbi": ce.db.get_company_by_id, "up": ce.db.upsert_company,
             "gcp": ce.db.get_client_profile, "gate": ce.icp_gate.gate_company,
             "sci": ce.db.set_company_icp, "roe": ce.db.record_operator_event,
             "pqc": ce.process_qualified_company}
    try:
        ce.db.get_company_by_id = lambda cid: {
            "id": cid, "name": "Giant REIT", "research_raw": {"firm_type": "real estate"},
            "region": "USA", "client_name": "", "aum_tag": "AUM_UNVERIFIED"}
        ce.db.upsert_company = lambda **k: {}
        ce.db.get_client_profile = lambda name: None
        ce.icp_gate.gate_company = lambda **k: {
            "icp_result": "DISQUALIFIED", "icp_reason": "above $2B ceiling", "aum_tag": "AUM_CONFIRMED"}
        ce.db.set_company_icp = lambda *a, **k: None
        ce.db.record_operator_event = lambda to_state, detail, lead_id=None: events.append(to_state)
        called = {"pqc": False}
        ce.process_qualified_company = lambda *a, **k: called.__setitem__("pqc", True) or (0, 0, 0)
        res = ce.manual_qualify(9, 5_000_000_000, progress=lambda m: None)
        assert res["verdict"] == "DISQUALIFIED"
        assert "outside the ICP band" in res["message"]
        assert called["pqc"] is False                      # no contacts/draft work when OOB
        assert events == ["disqualified"]
    finally:
        (ce.db.get_company_by_id, ce.db.upsert_company, ce.db.get_client_profile,
         ce.icp_gate.gate_company, ce.db.set_company_icp, ce.db.record_operator_event,
         ce.process_qualified_company) = (saved["gbi"], saved["up"], saved["gcp"],
             saved["gate"], saved["sci"], saved["roe"], saved["pqc"])


# --- Item 4: /qualify handler guards (offline) -----------------------------
def test_qualify_handler_refuses_non_parked():
    from src.approval import telegram_queue as tq
    msgs = []; started = []
    saved = {"send": tq.send, "gcbn": tq.db.get_company_by_name, "st": tq._start_thread,
             "gap": tq.db.get_active_prospect}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        tq.db.get_company_by_name = lambda name, ci=False: {"name": "Acme RE", "id": 3,
                                                            "icp_result": "QUALIFIED"}
        tq.db.get_active_prospect = lambda: None
        tq._start_thread = lambda *a, **k: started.append(a)
        tq._handle_qualify('"Acme RE" 800M')
        assert not started                                  # no worker spawned
        assert any("not parked" in m.lower() for m in msgs)
    finally:
        tq.send, tq.db.get_company_by_name, tq._start_thread, tq.db.get_active_prospect = (
            saved["send"], saved["gcbn"], saved["st"], saved["gap"])


def test_qualify_handler_parked_routes_direct_with_exact_name():
    """The quoted firm name is looked up verbatim (case-insensitive) and passed
    straight to the worker — never re-dispatched through the command parser
    (the /prospect-pick collision class)."""
    from src.approval import telegram_queue as tq
    msgs = []; started = []; looked_up = []
    saved = {"send": tq.send, "gcbn": tq.db.get_company_by_name, "st": tq._start_thread,
             "gap": tq.db.get_active_prospect}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        def _lookup(name, ci=False):
            looked_up.append((name, ci))
            return {"name": "Go Realty", "id": 5, "icp_result": "PARKED"}
        tq.db.get_company_by_name = _lookup
        tq.db.get_active_prospect = lambda: None
        tq._start_thread = lambda target, *a: started.append((target.__name__, a))
        tq._handle_qualify('"Go Realty" 1.2B')
        assert looked_up == [("Go Realty", True)]           # exact name, case-insensitive
        assert started and started[0][0] == "_run_qualify"  # routed to the worker directly
        assert started[0][1] == (5, 1_200_000_000)          # company id + parsed AUM
    finally:
        tq.send, tq.db.get_company_by_name, tq._start_thread, tq.db.get_active_prospect = (
            saved["send"], saved["gcbn"], saved["st"], saved["gap"])


def test_qualify_handler_bad_aum_rejected():
    from src.approval import telegram_queue as tq
    msgs = []; started = []
    saved = {"send": tq.send, "gcbn": tq.db.get_company_by_name, "st": tq._start_thread}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        tq.db.get_company_by_name = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("lookup must not run when AUM is unparseable"))
        tq._start_thread = lambda *a, **k: started.append(a)
        tq._handle_qualify('"Some Firm" wat')
        assert not started
        assert any("could not read an aum" in m.lower() for m in msgs)
    finally:
        tq.send, tq.db.get_company_by_name, tq._start_thread = (
            saved["send"], saved["gcbn"], saved["st"])


def test_disqualify_handler_refuses_non_parked():
    from src.approval import telegram_queue as tq
    msgs = []
    saved = {"send": tq.send, "gcbn": tq.db.get_company_by_name,
             "mdq": tq.competitor_engine.manual_disqualify}
    try:
        tq.send = lambda t, chat_id=None: msgs.append(t)
        tq.db.get_company_by_name = lambda name, ci=False: {"name": "Acme RE",
                                                            "id": 3, "icp_result": "QUALIFIED"}
        called = {"mdq": False}
        tq.competitor_engine.manual_disqualify = lambda *a, **k: called.__setitem__("mdq", True)
        tq._handle_disqualify('"Acme RE"')
        assert called["mdq"] is False
        assert any("not parked" in m.lower() for m in msgs)
    finally:
        tq.send, tq.db.get_company_by_name, tq.competitor_engine.manual_disqualify = (
            saved["send"], saved["gcbn"], saved["mdq"])


# --- RELIABILITY HARDENING (Fixes 1,2,3,5,6,7) -----------------------------
def test_startup_aborts_on_missing_env():
    # Fix 1: a missing required env var aborts startup (SystemExit) naming the var,
    # and announces it — never boots half-configured.
    from src.approval import telegram_queue as tq
    from src import config
    saved_exa, saved_send = config.EXA_API_KEY, tq.send
    msgs = []
    try:
        config.EXA_API_KEY = ""                       # simulate missing key
        tq.send = lambda t, chat_id=None: msgs.append(t)
        raised = None
        try:
            tq.run_bot()
        except SystemExit as e:
            raised = str(e)
        assert raised and "EXA_API_KEY" in raised     # aborted, var named
        assert any("EXA_API_KEY" in m for m in msgs)  # announced to Telegram
    finally:
        config.EXA_API_KEY = saved_exa
        tq.send = saved_send


def test_search_wrapper_raises_searchapierror_on_quota():
    # Fix 2: a Tavily quota error is RAISED with the real message, not swallowed
    # into an empty result list.
    from src.researcher import search_client as sc
    from src import config
    saved_post, saved_key = sc.requests.post, config.TAVILY_API_KEY

    class _FakeResp:
        status_code = 432
        text = "quota"
        def json(self):
            return {"detail": {"error": "This request exceeds your plan's set "
                                        "usage limit. Please upgrade your plan."}}
    try:
        config.TAVILY_API_KEY = "x"
        sc.requests.post = lambda *a, **k: _FakeResp()
        raised = None
        try:
            sc.search("anything", max_results=1)
        except sc.SearchAPIError as e:
            raised = e
        assert raised is not None
        assert raised.provider == "Tavily"
        assert "exceeds your plan" in raised.message
        # layered_search must PROPAGATE it (not swallow into [])
        propagated = False
        try:
            sc.layered_search(["q"], max_results_each=1)
        except sc.SearchAPIError:
            propagated = True
        assert propagated
    finally:
        sc.requests.post, config.TAVILY_API_KEY = saved_post, saved_key


def test_empty_llm_retries_then_escalates_to_premium():
    # Fix 5: empty completion on DEFAULT is retried once, then escalated to PREMIUM.
    from src import models, config
    saved = models.complete
    calls = []
    try:
        def fake_complete(prompt, system=None, model=None, temperature=0.2,
                          max_tokens=2000, json_mode=False):
            calls.append(model)
            if model == config.PREMIUM_MODEL:
                return models.LLMResult(text='{"ok": true}', usage=models.Usage())
            return models.LLMResult(text="", usage=models.Usage())   # empty on default
        models.complete = fake_complete
        parsed, _u = models.complete_json_retry("p", model=config.DEFAULT_MODEL)
        assert parsed == {"ok": True}
        assert calls == [config.DEFAULT_MODEL, config.DEFAULT_MODEL, config.PREMIUM_MODEL]
    finally:
        models.complete = saved


def test_clear_locks_removes_both_flags():
    # Fix 6: clear_locks deletes poller + active-prospect flags and exits 0.
    from src import db, clear_locks
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1"); cur.fetchone()
    except Exception:  # noqa: BLE001
        print("SKIP test_clear_locks_removes_both_flags: no DB")
        return
    db.set_flag(db.POLLER_KEY, '{"pid": 1, "ts": 1}')
    db.set_flag(db.ACTIVE_PROSPECT_KEY, '{"client": "X"}')
    rc = clear_locks.main()
    assert rc == 0
    assert db.get_flag(db.POLLER_KEY) is None
    assert db.get_flag(db.ACTIVE_PROSPECT_KEY) is None


def test_firm_timeout_parks_and_loop_continues():
    # Fix 7: a firm whose research/gate exceeds FIRM_TIMEOUT_SECONDS is PARKED
    # "research timeout" and the loop moves on to the next firm.
    from src.prospect import competitor_engine as ce
    from src import config
    import time as _t
    lines, parked = [], []
    saved = {"po": ce._process_one, "gcbn": ce.db.get_company_by_name,
             "gcp": ce.db.get_client_profile, "ur": ce.db.update_run,
             "park": ce._park_research_timeout, "ft": config.FIRM_TIMEOUT_SECONDS,
             "rt": config.RUN_TIMEOUT_MINUTES, "rw": config.RESEARCH_WORKERS}
    try:
        config.FIRM_TIMEOUT_SECONDS = 1
        config.RUN_TIMEOUT_MINUTES = 60
        config.RESEARCH_WORKERS = 2          # both firms run concurrently (deterministic)

        def slow_or_fast(cand, *a, **k):
            base = {"company_id": 1, "icp_reason": "x", "error": None, "tokens": 0,
                    "aum_value": None, "aum_tag": None, "unit_count": None}
            if cand["name"] == "SlowCo":
                _t.sleep(3)                  # exceeds the 1s per-firm budget
                return {**base, "name": "SlowCo", "icp_result": "DISQUALIFIED"}
            return {**base, "name": "FastCo", "icp_result": "DISQUALIFIED",
                    "icp_reason": "brokerage"}
        ce._process_one = slow_or_fast
        ce.db.get_company_by_name = lambda n: None
        ce.db.get_client_profile = lambda n: {}
        ce.db.update_run = lambda *a, **k: None
        ce._park_research_timeout = lambda cand, cn, cid: parked.append(cand["name"])

        counts = ce.run_processing(999, "TestClient",
                                   [{"name": "SlowCo"}, {"name": "FastCo"}],
                                   progress=lambda m: lines.append(m), do_draft=False)
        assert "SlowCo" in parked                                   # slow firm parked
        assert counts["parked"] >= 1 and counts["disqualified"] >= 1  # loop continued
        assert any("research timeout" in l for l in lines)
        assert any("FastCo" in l for l in lines)                    # second firm processed
    finally:
        (ce._process_one, ce.db.get_company_by_name, ce.db.get_client_profile,
         ce.db.update_run, ce._park_research_timeout, config.FIRM_TIMEOUT_SECONDS,
         config.RUN_TIMEOUT_MINUTES, config.RESEARCH_WORKERS) = (
            saved["po"], saved["gcbn"], saved["gcp"], saved["ur"], saved["park"],
            saved["ft"], saved["rt"], saved["rw"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
