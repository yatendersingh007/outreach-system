"""Startup lock reset (run as systemd ExecStartPre, and safe to run by hand).

Deletes the poller and active-prospect flags so a crashed/killed process can
never leave the bot 'permanently in progress'. Idempotent; always exits 0.
"""
from __future__ import annotations

from . import db


def main() -> int:
    with db.conn() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM system_flags WHERE key IN (%s, %s)",
                        (db.POLLER_KEY, db.ACTIVE_PROSPECT_KEY))
            n = cur.rowcount
        c.commit()
    print(f"locks cleared ({n} flag(s) removed)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
