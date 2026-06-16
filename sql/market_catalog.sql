-- MSport default market metadata (from default-market-info/v2)
CREATE TABLE IF NOT EXISTS market_catalog (
    id BIGSERIAL PRIMARY KEY,
    sport_id TEXT NOT NULL DEFAULT 'vf:sport:1',
    market_group TEXT NOT NULL DEFAULT 'main',
    market_name TEXT NOT NULL,
    market_id TEXT,
    title TEXT,
    outcome_number INTEGER,
    optional_status INTEGER,
    raw_json JSONB,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (sport_id, market_group, market_name, market_id)
);

CREATE INDEX IF NOT EXISTS idx_market_catalog_sport ON market_catalog (sport_id);