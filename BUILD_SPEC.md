# X Analyst Outreach Automation: BUILD SPEC (WORKFLOW A ONLY)

Read this file fully before writing any code. This spec is the single source of truth.
Do not substitute your own architecture decisions. Where this spec is silent, ask before assuming.

## SCOPE: WORKFLOW A ONLY

This spec covers ONE workflow: competitor prospecting -> Gmail drafts.

DO NOT BUILD, reference, stub, or scaffold any of the following. They belong to a future
Workflow B that is explicitly OUT OF SCOPE for this build:
- LinkedIn anything: no LinkedIn sender, no LinkedIn drafter, no Playwright, no browser
  automation, no invite/message caps, no send windows, no kill-switch flags
- CSV lead import / CSV batch research (`/research <csv>`)
- Connections matching (no connections CSV, no rapidfuzz matcher, no network status)
- Telegram per-message approve/edit/skip queue (Workflow A approval = Harpreet reviewing
  Gmail drafts; nothing needs a Telegram approval button)
If you find yourself writing any of the above, stop: you have drifted out of scope.

## Mission

Replace hours/day of manual Gmail outreach with one pipeline:

Workflow A: Competitor prospecting -> GMAIL DRAFTS. The user provides an existing
client/firm name via Telegram. The system:
1. Researches the client firm to understand its CRE niche.
2. Finds ALL competitors in that niche across USA + Canada + Mexico (full North America).
   No hardcoded cap on competitor count.
3. Sends the competitor list to Telegram for confirmation (proceed / trim).
4. Runs each confirmed competitor through the binary ICP FIRM GATE (see below).
5. For qualifying firms: finds higher-level management (CFO, VP Finance, Controller, MD),
   enriches emails via Apollo, drafts personalized emails referencing competitor pain
   points and X Analyst fit, and creates DRAFTS in Gmail with the case study PDF attached.
6. Harpreet reviews the drafts in Gmail and sends manually. The system never sends.

One client at a time.

ICP QUALIFICATION GATE (binary, applies to every company). No scoring, no HOT/WARM/COLD
tiers. A firm either QUALIFIES or is DROPPED:
- Firm type must be one of: real estate (owners/operators/developers/REITs),
  family office (with RE allocation), private equity (RE-focused or with RE portfolio),
  property management.
- AUM between $200M and $2B. Below $200M or above $2B = DISQUALIFIED at company level.
- AUM discovery: search stated AUM, portfolio value, units/sqft under management,
  fund sizes, SEC/RIA filings. Tag every company: AUM_CONFIRMED, AUM_ESTIMATED,
  or AUM_UNVERIFIED. UNVERIFIED companies are PARKED (state 'parked'), not
  auto-disqualified; surfaced in Telegram summaries for a human call.
- Companies failing the gate never proceed to executive search
  (saves tokens and keeps lists clean).

A human reviews every draft before anything is sent. The system creates drafts only.

## HARD RULES (never violate, never "improve")

1. NOTHING sends automatically. Gmail: drafts only. The API scope must be gmail.compose,
   never gmail.send.
2. Research NEVER visits LinkedIn. All research uses open-web search APIs (Tavily).
3. Two models only, via an OpenAI-compatible endpoint switchable by .env alone:
   - DEFAULT_MODEL for research, classification, firm qualification gating
   - PREMIUM_MODEL for final outbound email drafts only
   TESTING (now): DeepSeek direct. PRODUCTION (later): Azure AI Foundry deployments
   (billed to Azure startup credits, no OpenRouter). Pin deployments. Never auto-upgrade.
4. No Redis, no Qdrant, no LangChain, no CrewAI, no vector DB, no knowledge graph.
   Postgres is the queue (SELECT ... FOR UPDATE SKIP LOCKED), the state store, and the log.
5. Style rule for ALL generated outbound text: zero em dashes. Add a post-generation
   regex check that rejects/regenerates any draft containing an em dash (—) or double
   hyphen used as one. Outbound copy must read human: no "I hope this finds you well",
   no "I came across your profile", vary openers.
6. All secrets in .env, never committed. Provide .env.example.
7. No silent failures. Any single-firm failure is reported to Telegram by name and
   reason; the batch continues.

## Repo structure

```
outreach-system/
├── BUILD_SPEC.md              # this file
├── .env.example
├── docker-compose.yml         # postgres only (hermes installed separately)
├── schema.sql
├── requirements.txt
├── src/
│   ├── db.py                  # connection pool, queue helpers, state transitions
│   ├── models.py              # OpenAI-compatible client wrapper, retry, cost logging
│   ├── config.py              # env loading, constants
│   ├── researcher/
│   │   ├── company_research.py# per-company research, writes companies table
│   │   ├── icp_gate.py        # binary ICP qualification (prompt in prompts/)
│   │   └── search_client.py   # Tavily wrapper: layered queries (search + news + site angles)
│   ├── enrichment/
│   │   └── apollo.py          # bulk email enrichment via Apollo API
│   ├── drafting/
│   │   ├── gmail_drafter.py   # personalized email + PDF attach -> Gmail drafts
│   │   └── style_guard.py     # em-dash and cliché rejection
│   ├── prospect/
│   │   └── competitor_engine.py # /prospect flow (Workflow A end-to-end)
│   └── hermes_hooks/
│       └── commands.md        # command definitions for Hermes wiring
├── prompts/
│   ├── icp_scoring_v2_2.md    # binary ICP qualification gate (owner-provided)
│   ├── company_research.md
│   ├── gmail_draft.md
│   └── competitor_analysis.md
├── templates/
│   └── (owner drops real past outreach emails here as .txt; may be EMPTY at first)
├── assets/
│   └── case_study.pdf         # owner provides; may be MISSING at first
└── tests/
    └── test_e2e_workflow_a.py # small end-to-end smoke test of the /prospect flow
```

templates/ and assets/case_study.pdf are not yet populated. Handle both gracefully:
draft without few-shot examples if templates/ is empty; skip the attachment with a
logged warning if case_study.pdf is missing. Never crash on their absence.

## Database

Use schema.sql in repo root. Key points:

- `companies` table separate from `leads`. Research a company once; all its people inherit.
  Columns: id, name, domain, region TEXT, summary, pain_points JSONB,
  competitor_of INTEGER (self-FK, points to the client firm), client_name TEXT (which client
  this competitor was found for), trigger_events JSONB, last_researched_at.
  Region stores 'USA', 'Canada', 'Mexico' etc for filtering.
- RESEARCH METADATA on every companies row: research_confidence NUMERIC (0-100),
  source_count INTEGER, tokens_used INTEGER, research_cost_usd NUMERIC(8,4).
  Invaluable for deciding when to refresh stale research and for /status.
- Company ICP result lives on the company: icp_result, icp_reason, aum_tag.
- `leads` table: state machine. States:
  new -> researched -> qualified | disqualified | parked -> drafted
  ('drafted' is the terminal system state in Workflow A; the human sends from Gmail)
- `companies.research_raw` JSONB kept separate so the gate can be re-run without
  re-researching if the ICP criteria change (/requalify).
- `lead_events` audit table: every transition logged with agent name.
- `outreach_templates` table: past outreach examples loaded from /templates at setup.

## Services

### 1. Competitor engine (Workflow A entry)
- `/prospect "Client Firm Name"`: research the client firm first (niche, geography, services,
  asset classes) to understand what "competitor" means for THIS firm.
- Then paginated search for ALL competing firms in same CRE niche across North America
  (USA + Canada + Mexico). No hardcoded cap. Search iterates: broad query first, then
  niche-specific queries, then regional queries, until results dry up or repeat.
- LAYERED SEARCH via Tavily (single provider, single key):
  * Each iteration runs multiple query ANGLES, not one query: "[client] competitors",
    "[niche] firms North America", "top [niche] companies USA", "[niche] property
    managers Canada", plus news-angle queries for recent entrants.
  * Use Tavily's include_raw_content / extract endpoint to pull competitor homepages
    as clean text when the summary needs it.
  Deduplicate merged results with DEFAULT_MODEL.
- STOPPING RULE: stop when two consecutive search iterations return zero new
  high-confidence competitors, OR configurable max reached (default MAX_COMPETITORS=100
  in .env). Never run indefinitely.
- Region filter enforced in search queries (append "USA" / "North America" / "Canada").
- CONFIRMATION CHECKPOINT: after collecting the competitor list, Hermes sends to Telegram:
  "Found [N] competitors for [Firm]. Here's the list: [names]. Proceed with all / trim?"
  User confirms or replies with names to remove. Only confirmed firms proceed.
- For each confirmed competitor: apply ICP FIRM GATE (type + AUM $200M-$2B) FIRST.
  Failing firms marked disqualified, unverified-AUM firms parked. For qualifying firms:
  research (pain points, signals, news) -> find 2-4 higher-level management contacts
  (CFO, VP Finance, Controller, MD) via open-web search -> create leads rows
  -> Apollo email enrichment -> hand qualified leads to gmail_drafter. Workflow A ends
  in Gmail drafts with case study PDF.
- All open-web. Browser-agent research may replace search_client LATER; v1 uses search
  APIs for speed. Leave a clean interface.
- Progress updates to Telegram every 10 competitors researched (see section 5).

### 2. Company researcher / ICP gate
- For each firm: check if company already in companies table and fresh (<30 days).
  If not, run company research via Tavily (3-5 layered searches: general + news +
  site-specific angles), summarize with DEFAULT_MODEL into: summary, what they do,
  recent signals.
- Apply ICP FIRM GATE to the company (type: RE/family office/PE/property mgmt;
  AUM $200M-$2B; tag AUM_CONFIRMED/ESTIMATED/UNVERIFIED). Gate failures disqualify
  all leads at that company; UNVERIFIED parks them.
- No lead scoring or tiering. If the firm QUALIFIES (passes the binary gate), keep only
  its higher-level management contacts (CFO, VP Finance, Controller, MD, or equivalent);
  everyone at a qualified firm who holds such a title proceeds. Others dropped.
- A run of ~30 firms must complete in well under ~30 min; parallelize with a small
  worker pool (4-6), respect search API rate limits.

### 3. Apollo enrichment
- Apollo bulk people enrichment endpoint (POST /api/v1/people/bulk_match, batches of 10).
- Input: leads missing email. Output: email + confidence written back to leads.
- If APOLLO_API_KEY missing, print instructions for manual CSV fallback and exit cleanly.

### 4. Gmail drafter (Workflow A finale)
- For each qualified lead with an enriched email: draft with PREMIUM_MODEL using:
  company summary + pain points/signals + lead designation + relevant examples from
  outreach_templates table (skip few-shot cleanly if the table is empty).
- Create draft via Gmail API (scope: gmail.compose ONLY) with assets/case_study.pdf
  attached (skip attach with a logged warning if the file is missing).
- Subject line included. Mark lead state 'drafted'. Log Gmail draft id on the lead row.
- OAuth: standard installed-app flow, token cached to disk, refresh handled.
- Style guard applied to every draft: reject/regenerate on em dash or clichés.

### 5. Progress messaging (applies to /prospect)
Every long-running command sends staged Telegram updates, not just a final result.
Pattern for /prospect "<client>":
  1. "Researching <client>..." -> "Understood: <one-line niche summary>"
  2. "Searching for competitors across North America..." -> "Found N candidates"
  3. Full numbered competitor list -> "Reply 'proceed' for all, or list names to remove"
  4. After confirmation: "Proceeding with N firms"
  5. Progress checkpoint every 10 firms processed: "[X/N] researching..." with a running
     tally of qualified/disqualified/parked so far (not one message per firm)
  6. On any single-firm failure: report which firm and why, continue with the rest,
     never fail silently and never abort the whole batch for one bad firm
  7. Final summary: total researched, qualified/disqualified/parked counts, contacts found,
     emails enriched (X/Y), drafts created, explicit "Done."
Same staged pattern applies to enrichment and drafting sub-steps within the same command,
not separate commands the user has to trigger manually.

### 6. /status dashboard command
`/status` (no args) returns a snapshot, not a log dump:
  - Last run: client name, timestamp, qualified/disqualified/parked counts
  - Running totals across all runs to date: companies researched, qualified, drafts created
  - Average research_confidence across QUALIFIED companies (flags if trending low, e.g. <60)
  - Count of PARKED companies awaiting human review (AUM_UNVERIFIED), with names, so the
    user can manually confirm or drop them
  - Total tokens_used and research_cost_usd across all runs (running spend visibility)
`/status <client name>` returns the detail for that one run: full company list with
  icp_result + icp_reason per company, confidence tag, and draft status per contact.
This is the audit trail: every qualify/disqualify decision must be traceable back to
its icp_reason without re-running anything.

### 7. Hermes wiring
- Hermes is dispatcher only. Commands (documented in src/hermes_hooks/commands.md):
  /prospect "<client firm name>", /prospect confirm, /prospect trim <names>,
  /requalify, /status, /status "<client>"
- Each command shells out to `python -m src.<entrypoint>`; Hermes reports stdout back
  to Telegram. Telegram runs in POLLING mode, not webhooks.
- Weekly cron: search qualified companies for fundraise/acquisition/hiring news,
  write to companies.trigger_events, send Monday brief to Telegram.

## .env.example keys

# LLM provider: OpenAI-compatible, switchable via BASE_URL only.
# TESTING (now): DeepSeek direct free grant
#   LLM_BASE_URL=https://api.deepseek.com
#   LLM_API_KEY=sk-...
#   DEFAULT_MODEL=deepseek-chat        (V4 Flash)
#   PREMIUM_MODEL=deepseek-v4-pro
# PRODUCTION (later): Azure AI Foundry, billed to Azure startup credits
#   LLM_BASE_URL=https://<project>.services.ai.azure.com/models
#   LLM_API_KEY=<foundry key>
#   DEFAULT_MODEL=DeepSeek-V4-Flash
#   PREMIUM_MODEL=DeepSeek-V4-Pro
LLM_BASE_URL, LLM_API_KEY, DEFAULT_MODEL, PREMIUM_MODEL,
TAVILY_API_KEY (free tier, 1000 searches/month),
APOLLO_API_KEY (REQUIRED day one: Workflow A produces contacts with no emails;
enrichment is the bridge to Gmail drafts),
DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID,
GMAIL_CREDENTIALS_PATH (test mode: owner's own Gmail; production: Harpreet's, re-auth only),
MAX_COMPETITORS=100

## Test mode notes
- The models wrapper (src/models.py) must read LLM_BASE_URL from env so provider
  switching (DeepSeek direct <-> Azure Foundry) is a .env edit only.
- Gmail OAuth in test mode targets the owner's personal Gmail. Production switch =
  re-run the OAuth authorization with Harpreet's account and replace the cached token.
- templates/ is data: templates arriving later drop in without code changes.

## Build order for TODAY

1. schema.sql applied, db.py, config.py, models.py (LLM_BASE_URL switchable)
2. search_client.py (Tavily layered wrapper) + competitor_engine.py (discovery
   + firm gate + confirmation checkpoint)
3. Researcher/ICP qualification gate + Apollo enrichment module
4. Gmail drafter with PDF attach (owner's own Gmail in test mode; skip attach
   gracefully with a warning if case_study.pdf is missing; draft without few-shot
   examples if templates/ is empty)
5. Telegram bot (polling mode): /prospect, /status wired end-to-end, with staged
   progress messaging per section 5 (not a single silent run with only a final message)
6. Smoke test: /prospect "<real client name>" from Telegram -> staged progress updates
   -> competitor list -> confirm -> qualify/disqualify/park progress -> drafts in
   owner's Gmail -> final "Done" summary
7. /status returns the dashboard per section 6

There is no step 8. When the build order above is done, you are done. Do not start
building CSV import, LinkedIn modules, connection matchers, or send queues.

## Definition of done (today, TEST MODE, Workflow A)

- `/prospect "<client name>"` from Telegram shows staged progress (researching client ->
  searching competitors -> competitor list -> confirmation prompt), not a single
  long silent wait
- After confirmation: staged progress continues (periodic checkpoint every ~10 firms
  with running qualify/disqualify/park tally), firm gate visibly disqualifies/parks
  non-fitting firms (type + AUM $200M-$2B, AUM confidence tags shown)
- Any single-firm failure is reported by name and reason; the batch continues, never
  aborts or fails silently
- Qualifying firms produce management contacts, Apollo-enriched emails, and
  personalized drafts with case_study.pdf (if present) in the OWNER'S OWN Gmail
  drafts folder
- Final Telegram message is an explicit "Done" with full counts (researched,
  qualified/disqualified/parked, contacts found, emails enriched X/Y, drafts created)
- `/status` returns last-run summary + running totals + parked-firms list + token/cost
  totals; `/status "<client>"` returns full per-company detail with icp_reason
- Every company and lead row shows full state history via lead_events
- No em dash anywhere in any generated draft
- Switching LLM_BASE_URL between DeepSeek and a second provider requires zero code edits
- Zero LinkedIn, CSV-import, or connections code anywhere in the repo

## Owner-provided inputs (blockers, gather before coding)

- prompts/icp_scoring_v2_2.md (binary qualification gate: RE / family office / PE /
  property management, AUM $200M-$2B, North America; no scoring, no tiers)
- templates/ folder: real past outreach emails (arriving later; system must work with
  0 templates and improve as more are added)
- assets/case_study.pdf (arriving later; handle absence gracefully)
- Gmail OAuth credentials.json (TEST: owner's own Gmail; PROD: Harpreet re-auths)
- DeepSeek API key (free 5M-token grant) for testing; Azure Foundry deployment for prod
- Tavily API key (free tier)
- Apollo API key (REQUIRED: Workflow A contacts arrive without emails)
- Telegram bot token + numeric user id (DONE)
