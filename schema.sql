-- X Analyst Outreach Automation: Postgres Schema (WORKFLOW A ONLY)
-- Drop and recreate for fresh start. Remove DROP statements in production.
-- Workflow B (LinkedIn/CSV) tables and columns are intentionally absent;
-- they will be added by migration when that workflow is built.

-- Fresh start: drop existing objects (reverse dependency order). Remove in prod.
DROP TABLE IF EXISTS lead_events CASCADE;
DROP TABLE IF EXISTS leads CASCADE;
DROP TABLE IF EXISTS outreach_templates CASCADE;
DROP TABLE IF EXISTS prospect_runs CASCADE;
DROP TABLE IF EXISTS system_flags CASCADE;
DROP TABLE IF EXISTS companies CASCADE;
DROP TYPE IF EXISTS channel CASCADE;
DROP TYPE IF EXISTS aum_tag CASCADE;
DROP TYPE IF EXISTS icp_status CASCADE;
DROP TYPE IF EXISTS lead_state CASCADE;

-- Lead state machine (Workflow A)
-- States: new > researched > qualified|disqualified|parked > drafted
-- 'drafted' is the terminal system state: the human reviews and sends from Gmail.
CREATE TYPE lead_state AS ENUM (
    'new',
    'researched',
    'qualified',
    'disqualified',
    'parked',
    'drafted'
);

CREATE TYPE icp_status AS ENUM ('QUALIFIED', 'DISQUALIFIED', 'PARKED');

CREATE TYPE aum_tag AS ENUM ('AUM_CONFIRMED', 'AUM_ESTIMATED', 'AUM_UNVERIFIED');

CREATE TYPE channel AS ENUM ('gmail_draft');
-- Future channels (LinkedIn etc.) added later via ALTER TYPE channel ADD VALUE.

-- Companies: research once, all leads at the firm inherit
CREATE TABLE companies (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    domain              TEXT,
    region              TEXT,                -- 'USA', 'Canada', 'Mexico' etc
    summary             TEXT,
    pain_points         JSONB,
    trigger_events      JSONB,               -- fundraise/acquisition/hiring signals
    competitor_of       INTEGER REFERENCES companies(id),
    client_name         TEXT,                -- which client this competitor was found for

    -- ICP gate result (company-level; leads inherit)
    icp_result          icp_status,
    icp_reason          TEXT,                -- e.g. 'RE PE fund, AUM ~$450M confirmed, qualifies'
    aum_tag             aum_tag,

    -- Research metadata
    research_raw        JSONB,               -- full researcher output; gate re-runnable without re-research
    research_confidence NUMERIC(5,2),        -- 0-100 confidence score
    source_count        INTEGER DEFAULT 0,   -- how many sources found
    tokens_used         INTEGER DEFAULT 0,   -- total tokens for this research
    research_cost_usd   NUMERIC(8,4),        -- cost in USD
    last_researched_at  TIMESTAMPTZ,

    CONSTRAINT unique_company UNIQUE (name)
);

CREATE INDEX idx_companies_client ON companies (client_name);
CREATE INDEX idx_companies_icp ON companies (icp_result);

-- System flags: generic key/value (run locks, counters, feature flags)
CREATE TABLE system_flags (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Prospect runs: one row per /prospect invocation. Powers the confirmation
-- checkpoint (candidates held between discovery and processing) and the
-- /status run history (last run + running totals).
CREATE TABLE prospect_runs (
    id              SERIAL PRIMARY KEY,
    client_name     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'discovering',
                    -- discovering | awaiting_confirmation | processing | done | failed
    niche_summary   TEXT,
    candidates      JSONB,               -- discovered competitors [{name,domain,region,why}]
    confirmed_names JSONB,               -- names kept after confirm/trim
    counts          JSONB DEFAULT '{}',  -- {researched,qualified,disqualified,parked,contacts,emails,drafts}
    tokens_used     INTEGER DEFAULT 0,
    cost_usd        NUMERIC(10,4) DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_prospect_runs_client ON prospect_runs (client_name);
CREATE INDEX idx_prospect_runs_status ON prospect_runs (status);

-- Core leads table: one row per person (management contact at a qualified firm)
CREATE TABLE leads (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),

    -- Contact identity (found via open-web search, never LinkedIn scraping)
    full_name       TEXT NOT NULL,
    first_name      TEXT,
    last_name       TEXT,
    designation     TEXT,                -- CFO, VP Finance, Controller, MD, etc
    company         TEXT NOT NULL,
    email           TEXT,
    email_confidence TEXT,               -- from Apollo enrichment
    enriched_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),

    -- Researcher output
    state           lead_state DEFAULT 'new',
    icp_result      icp_status,          -- inherited from company
    icp_reason      TEXT,
    company_summary TEXT,                -- 2-3 sentence what they do
    recent_signals  TEXT,                -- fundraise, acquisition, hiring etc
    research_raw    JSONB,               -- full researcher output for debugging
    researched_at   TIMESTAMPTZ,

    -- Draft (Gmail only in Workflow A)
    draft_channel   channel,
    draft_message   TEXT,
    draft_subject   TEXT,
    drafted_at      TIMESTAMPTZ,
    drafted_model   TEXT,                -- which model wrote it
    gmail_draft_id  TEXT,                -- Gmail API draft id for traceability

    -- Housekeeping
    updated_at      TIMESTAMPTZ DEFAULT now(),
    notes           TEXT,

    CONSTRAINT unique_person UNIQUE (full_name, company)
);

-- Indexes for pipeline queries
CREATE INDEX idx_leads_state ON leads (state);
CREATE INDEX idx_leads_icp ON leads (icp_result);
CREATE INDEX idx_leads_company ON leads (company_id);

-- Outreach templates: few-shot examples for the drafter (loaded from /templates)
CREATE TABLE outreach_templates (
    id              SERIAL PRIMARY KEY,
    channel         channel NOT NULL DEFAULT 'gmail_draft',
    template_name   TEXT NOT NULL,
    subject         TEXT,
    body            TEXT NOT NULL,
    context_notes   TEXT,                -- when to use this template
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Audit log: every state transition
CREATE TABLE lead_events (
    id              SERIAL PRIMARY KEY,
    lead_id         INTEGER REFERENCES leads(id),
    from_state      lead_state,
    to_state        lead_state NOT NULL,
    agent           TEXT NOT NULL,        -- 'researcher', 'gate', 'enricher', 'drafter', 'human'
    detail          JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_events_lead ON lead_events (lead_id);

-- Trigger: auto-update updated_at on leads
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leads_updated
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();
