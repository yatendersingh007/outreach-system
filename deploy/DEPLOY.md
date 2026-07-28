# X Analyst Outreach — VPS Deployment Runbook

Target: Ubuntu 22.04/24.04 VPS. App path: `/opt/outreach-system`. Runs as a
non-root `outreach` user under systemd. One Telegram poller only (systemd single
instance + DB heartbeat lock).

Do all of this as root (or with sudo) unless noted.

## 1. System packages
```bash
apt update
apt install -y python3.12 python3.12-venv postgresql
adduser --system --group outreach          # non-root service account
```

## 2. Database
```bash
# create role + database
sudo -u postgres psql -c "CREATE USER outreach_app WITH PASSWORD 'CHANGE_ME';"
sudo -u postgres psql -c "CREATE DATABASE outreach OWNER outreach_app;"
# (or reuse the postgres superuser; either way put the DSN in .env DATABASE_URL)
```
Then apply schema + migrations (run as the outreach user from the app dir, step 3
first so the venv exists — or run with any python that has psycopg + the repo):
```bash
cd /opt/outreach-system
sudo -u outreach .venv/bin/python -m src.db init      # fresh DB -> schema applies
sudo -u outreach .venv/bin/python -m src.db migrate   # client_profiles + seed
```
`init` is NON-DESTRUCTIVE: on an already-populated DB it refuses (use
`python -m src.db reset` only to intentionally wipe). `migrate` is idempotent.

## 3. Code + virtualenv
```bash
# rsync from your machine, or git clone, into /opt/outreach-system
rsync -av --exclude .venv --exclude .env --exclude token.json \
      ./ root@VPS:/opt/outreach-system/
cd /opt/outreach-system
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.lock.txt   # pinned, reproducible
# Pitch-deck generator needs Node.js + pptxgenjs (runtime dependency):
apt install -y nodejs npm
( cd deck_gen && npm install )                    # installs pptxgenjs into deck_gen/node_modules
chown -R outreach:outreach /opt/outreach-system
# NOTE: deck gen shells out to `node`; if node is absent or generation fails, the
# drafter automatically falls back to the static assets/*.pdf (never blocks a draft).
```

## 4. Environment (.env) — copy via SCP, NEVER git
`scp .env root@VPS:/opt/outreach-system/.env` then `chmod 600` and
`chown outreach:outreach`. Required variables (mask/rotate real values):

| Variable | Description |
|---|---|
| `LLM_BASE_URL` | Primary LLM endpoint (Azure Foundry model catalog for DeepSeek/premium) |
| `LLM_API_KEY` | Primary endpoint key |
| `DEFAULT_MODEL` | Research/gate/extraction model (e.g. `gpt-5-mini`) |
| `PREMIUM_MODEL` | Draft model (e.g. `DeepSeek-V3.2-Speciale`) |
| `LLM_API_VERSION` | Optional; auto-defaults to `2024-05-01-preview` for `*.azure.com` |
| `SECONDARY_LLM_BASE_URL` | Optional; endpoint for DEFAULT_MODEL if it lives on a separate Azure resource |
| `SECONDARY_LLM_API_KEY` | Optional; key for the secondary endpoint |
| `SECONDARY_LLM_API_VERSION` | Optional; api-version override for the secondary endpoint |
| `TAVILY_API_KEY` | Per-firm research search |
| `EXA_API_KEY` | Competitor discovery (semantic). If unset, discovery falls back to Tavily |
| `APOLLO_API_KEY` | Email enrichment (required for drafts) |
| `DATABASE_URL` | `postgresql://user:pass@localhost:5432/outreach` (percent-encode `@`/`:` in the password, e.g. `@`→`%40`) |
| `TELEGRAM_BOT_TOKEN` | Harpreet's NEW bot token (from @BotFather) |
| `TELEGRAM_USER_ID` | Harpreet's numeric chat id (capture in step 6) |
| `GMAIL_CREDENTIALS_PATH` | `credentials.json` (ROOT-anchored; resolves under /opt/outreach-system) |
| `GMAIL_TOKEN_PATH` | `token.json` (ROOT-anchored) |
| `MAX_COMPETITORS` | Hard safety cap (default 100) |
| `DISCOVERY_REVIEW_MAX` | Soft per-run candidate cap presented for confirmation (default 50) |
| `RESEARCH_WORKERS` | **Set to `1`** for Azure Foundry's 20K TPM limit (higher tiers can raise) |

## 5. Gmail auth (Harpreet's account) — do this LOCALLY, then copy
On a LOCAL machine with a browser:
```bash
# put Harpreet's credentials.json in the repo root, then:
.venv/bin/python -m src.drafting.gmail_drafter --auth   # opens browser, writes token.json
scp credentials.json token.json root@VPS:/opt/outreach-system/
```
Scope is `gmail.compose` only (drafts, never send). Paths are ROOT-anchored, so
they resolve at `/opt/outreach-system/{credentials.json,token.json}` regardless
of the service's working directory.

## 6. Capture Harpreet's Telegram chat id
Ensure the bot is NOT yet running. Have Harpreet send any message to the bot,
then:
```bash
cd /opt/outreach-system
sudo -u outreach .venv/bin/python -m src.approval.telegram_queue --whoami
```
Put the printed `chat_id` into `.env` as `TELEGRAM_USER_ID`.

## 7. systemd
```bash
cp deploy/outreach-bot.service /etc/systemd/system/outreach-bot.service
systemctl daemon-reload
systemctl enable --now outreach-bot
journalctl -u outreach-bot -f          # watch; expect "Bot polling (pid ...)"
```

## 8. Smoke test (from Harpreet's Telegram)
- `/status` → dashboard renders.
- `/clients` → lists Kingbird + Gold Triangle.
- `/prospect "<small test client>"` → staged progress → candidate list →
  `/prospect confirm` → qualify/park/DQ tally → drafts in Gmail → "Done".
- Check Gmail Drafts for the created draft(s) with the case study attached.

## 9. Backups
```bash
mkdir -p /opt/backups && chown outreach:outreach /opt/backups
cp deploy/backup.sh /opt/outreach-system/deploy/ && chmod +x /opt/outreach-system/deploy/backup.sh
crontab -u outreach -e
# add: 30 2 * * * PGPASSWORD='...' DB_NAME=outreach DB_USER=postgres /opt/outreach-system/deploy/backup.sh >> /opt/backups/backup.log 2>&1
```

---

## Data migration: local DB → VPS (optional)
The local DB is mostly test runs. **Recommended: start fresh on the VPS** — run
`db init` + `db migrate` (step 2). Client profiles reseed automatically via the
migration, so nothing is lost that matters.

If you DO want to carry local data over:
```bash
# on the local machine
pg_dump "postgresql://postgres:PW@localhost:5432/outreach" --no-owner --no-privileges | gzip > outreach_local.sql.gz
scp outreach_local.sql.gz root@VPS:/tmp/

# on the VPS (into a freshly created, EMPTY outreach DB)
gunzip -c /tmp/outreach_local.sql.gz | sudo -u postgres psql -d outreach
sudo -u outreach /opt/outreach-system/.venv/bin/python -m src.db migrate   # apply migrations on top
```
Do NOT run `db init`/`db reset` after restoring — those apply the destructive
`schema.sql`. Use `migrate` only.
