-- 001: per-client profiles (multi-client generalization).
-- Non-destructive: CREATE TABLE IF NOT EXISTS + idempotent seed. Applied by
-- `python -m src.db migrate` (tracked in schema_migrations); never dropped.

CREATE TABLE IF NOT EXISTS client_profiles (
    id                  SERIAL PRIMARY KEY,
    client_name         TEXT NOT NULL UNIQUE,
    niche_description   TEXT,
    asset_classes       JSONB DEFAULT '[]',      -- e.g. ["multifamily","student housing"]
    target_regions      JSONB DEFAULT '[]',      -- e.g. ["USA","Canada","Mexico"]
    aum_floor           NUMERIC(16,0) DEFAULT 200000000,
    aum_ceiling         NUMERIC(16,0) DEFAULT 2000000000,
    pitch_service_focus TEXT DEFAULT 'property accounting',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Seed the two existing clients (Part 3d). Idempotent.
INSERT INTO client_profiles
    (client_name, niche_description, asset_classes, target_regions,
     aum_floor, aum_ceiling, pitch_service_focus)
VALUES
    ('Kingbird Investments',
     'multifamily and student housing real estate investment management',
     '["multifamily","student housing"]'::jsonb,
     '["USA","Canada","Mexico"]'::jsonb,
     200000000, 2000000000, 'property accounting'),
    ('Gold Triangle Property Management',
     'commercial property management',
     '["commercial","multifamily"]'::jsonb,
     '["USA","Canada","Mexico"]'::jsonb,
     200000000, 2000000000, 'property accounting')
ON CONFLICT (client_name) DO NOTHING;
