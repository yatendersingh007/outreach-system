"""/status reporting: dashboard + per-client detail.

Snapshot, not a log dump. This is the audit trail: every qualify/disqualify/park
decision is traceable back to its icp_reason without re-running anything. Used by
both the Telegram bot and the `python -m src.status` CLI (Hermes entrypoint).
"""
from __future__ import annotations

import sys

from . import db


def dashboard_text() -> str:
    t = db.running_totals()
    last = db.latest_run()
    parked = db.parked_companies()
    lines = ["STATUS", ""]
    if last:
        c = last.get("counts") or {}
        lines.append(f"Last run: {last['client_name']} ({str(last.get('created_at'))[:16]})")
        lines.append(f"  status: {last['status']} | qualified {c.get('qualified', 0)}, "
                     f"disqualified {c.get('disqualified', 0)}, parked {c.get('parked', 0)}")
    else:
        lines.append("Last run: none yet")
    lines.append("")
    lines.append("Running totals (all runs):")
    lines.append(f"  companies researched: {t['companies']}")
    lines.append(f"  qualified: {t['qualified']}")
    lines.append(f"  drafts created: {t['drafts']}")
    conf = t["avg_confidence_qualified"]
    flag = "  (LOW - review)" if conf and conf < 60 else ""
    lines.append(f"  avg research confidence (qualified): {conf}{flag}")
    lines.append(f"  spend: {t['tokens_used']} tokens, ${t['cost_usd']:.4f}")
    lines.append("")

    # Drafted leads with their deck-confidence flag (Harpreet's review signal).
    drafted = db.drafted_leads()
    lines.append(f"Drafted: {len(drafted)}")
    if drafted:
        from .drafting import pitch_deck  # lazy import: avoids load-time coupling
        emoji = {"high": "✅", "medium": "☑️", "low": "⚠️", "unknown": "⚠️"}
        for ld in drafted:
            comp = ld.get("company") or ""
            conf = pitch_deck.deck_meta(comp)["confidence"]
            short = pitch_deck._short_name(comp) if comp else "?"
            lines.append(f"  {ld['full_name']} ({short}) — deck: {conf.upper()} {emoji.get(conf, '⚠️')}")
    lines.append("")

    lines.append(f"⏸ PARKED — needs your review: {len(parked)}")
    lines.append("  (the reason tells you why: 'no web sources' = search was thin/down, "
                 "re-run later · 'AUM not verified' = hunt the size by hand · "
                 "'firm type unverified' = check what they are)")
    for p in parked[:50]:
        lines.append(f"  - {p['name']}: {p.get('icp_reason') or ''}")
    if parked:
        lines.append("  → Rescue:  /qualify \"<firm>\" <AUM>     Reject:  /disqualify \"<firm>\"")
    return "\n".join(lines)


def detail_text(client: str) -> str:
    run = db.latest_run_for_client(client)
    name = run["client_name"] if run else client
    companies = db.companies_for_client(name)
    if not companies:
        return f"No companies on record for '{client}'."
    lines = [f"STATUS: {name}", ""]
    if run:
        c = run.get("counts") or {}
        lines.append(f"Run status: {run['status']} | qualified {c.get('qualified', 0)}, "
                     f"disqualified {c.get('disqualified', 0)}, parked {c.get('parked', 0)}, "
                     f"drafts {c.get('drafts', 0)}")
        lines.append("")
    for co in companies:
        lines.append(f"{co['name']} - {co.get('icp_result') or 'PENDING'} "
                     f"[{co.get('aum_tag') or '?'}, conf {co.get('research_confidence') or 0}]")
        lines.append(f"   reason: {co.get('icp_reason') or ''}")
        for lead in db.leads_for_company(co["id"]):
            email = lead.get("email") or "no-email"
            lines.append(f"     - {lead['full_name']} ({lead.get('designation') or '?'}) "
                         f"| {lead['state']} | {email}")
    return "\n".join(lines)


def _band(p: dict) -> str:
    lo = float(p.get("aum_floor") or 0) / 1e6
    hi = float(p.get("aum_ceiling") or 0)
    hi_s = f"${hi/1e9:.1f}B" if hi >= 1e9 else f"${hi/1e6:.0f}M"
    return f"${lo:.0f}M-{hi_s}"


def clients_text() -> str:
    profs = db.all_client_profiles()
    if not profs:
        return "No client profiles yet. Run /prospect \"<client>\" to create one."
    lines = ["CLIENTS", ""]
    for p in profs:
        lines.append(f"- {p['client_name']} | {_band(p)} | focus: {p.get('pitch_service_focus')}")
    return "\n".join(lines)


def client_text(name: str) -> str:
    p = db.get_client_profile(name)
    if not p:
        return f"No profile for '{name}'. Run /prospect \"{name}\" to create one."
    return "\n".join([
        p["client_name"],
        f"  niche: {p.get('niche_description') or '(none)'}",
        f"  asset classes: {', '.join(p.get('asset_classes') or []) or '(none)'}",
        f"  target regions: {', '.join(p.get('target_regions') or []) or '(none)'}",
        f"  AUM band: {_band(p)}",
        f"  pitch focus: {p.get('pitch_service_focus')}",
    ])


if __name__ == "__main__":
    # The dashboard carries emoji (confidence markers). Telegram sends UTF-8 and
    # the Linux VPS is UTF-8, but a Windows cp1252 console would crash on print —
    # make the CLI robust so the dashboard is always printable.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - not every stream supports reconfigure
        pass
    arg = " ".join(sys.argv[1:]).strip().strip('"').strip("'")
    print(detail_text(arg) if arg else dashboard_text())
