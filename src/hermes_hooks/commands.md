# Hermes command wiring (Workflow A only)

Hermes is a dispatcher only. It is installed separately from this repo. Today's
build ships a self-contained Telegram polling bot
(`python -m src.approval.telegram_queue`) that implements every command
in-process, so the system runs end-to-end without Hermes. When Hermes is wired
in later, each command shells out to a `python -m src.<entrypoint>` and Hermes
relays stdout back to Telegram. Telegram runs in POLLING mode, not webhooks.

## Commands
| Command | Entry point | Notes |
|---|---|---|
| `/prospect "<client firm>"` | `python -m src.prospect.competitor_engine "<client>"` | Phase 1 discovery -> confirmation checkpoint |
| `/prospect confirm` | (resumes latest awaiting-confirmation run) | Phase 2: gate + research + enrich + draft |
| `/prospect trim <names\|numbers>` | (drops firms, then proceeds) | Comma-separated names or list numbers |
| `/requalify` | `python -m src.prospect.competitor_engine --requalify` | Re-run the ICP gate on stored research_raw, no re-research |
| `/status` | `python -m src.status` | Dashboard: last run, totals, parked, spend |
| `/status "<client>"` | `python -m src.status "<client>"` | Full per-company detail with icp_reason |

## Weekly cron (later)
Search qualified companies for fundraise/acquisition/hiring news, write to
`companies.trigger_events`, send a Monday brief to Telegram.
