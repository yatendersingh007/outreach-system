"""End-to-end smoke test of the /prospect flow (Workflow A).

This exercises the real pipeline against live services (Postgres, Tavily, LLM,
Apollo). It is GATED on a live database being reachable so a plain unit run
never fails in an environment without one. Gmail drafting is skipped here
(--no-draft) because OAuth needs a one-time interactive browser step; the
smoke test proves discovery -> gate -> contacts -> enrichment end to end.

Run explicitly:
    python tests/test_e2e_workflow_a.py "Kingbird Investments"
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, db  # noqa: E402
from src.prospect import competitor_engine  # noqa: E402


def _db_reachable() -> bool:
    try:
        with db.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


def run_smoke(client: str, limit: int = 3) -> None:
    missing = config.missing_keys(config.REQUIRED_FOR_PROSPECT)
    if missing:
        print(f"SKIP: missing config {missing}")
        return
    if not _db_reachable():
        print("SKIP: database not reachable (run `python -m src.db init`)")
        return

    print(f"=== Discovery: {client} ===")
    run = db.create_run(client)
    candidates = competitor_engine.run_discovery(run["id"], client, progress=print)
    assert isinstance(candidates, list)
    print(f"Discovered {len(candidates)} candidates")
    if not candidates:
        print("No candidates found; discovery ran but returned nothing.")
        return

    subset = candidates[:limit]
    db.update_run(run["id"], status="processing",
                  confirmed_names=[c["name"] for c in subset])
    print(f"\n=== Processing {len(subset)} (draft skipped) ===")
    counts = competitor_engine.run_processing(run["id"], client, subset,
                                              progress=print, do_draft=False)
    assert "researched" in counts
    print(f"\nRESULT: {counts}")
    print("SMOKE OK")


if __name__ == "__main__":
    client = " ".join(sys.argv[1:]).strip() or "Kingbird Investments"
    run_smoke(client)
