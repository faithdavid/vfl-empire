-- Canonical pre-match odds: every market selection per fixture (deep markets).
CREATE TABLE IF NOT EXISTS vfl_prematch_odds (
    id              BIGSERIAL PRIMARY KEY,
    event_id        TEXT NOT NULL,
    season_id       TEXT,
    matchday_number INTEGER,
    home_team       TEXT,
    away_team       TEXT,
    market_name     TEXT NOT NULL,
    specifiers      TEXT NOT NULL DEFAULT '',
    selection_name  TEXT NOT NULL,
    odds            NUMERIC(10,4),
    source          TEXT NOT NULL DEFAULT 'api',
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, market_name, specifiers, selection_name)
);

CREATE INDEX IF NOT EXISTS idx_vfl_prematch_odds_season_md
    ON vfl_prematch_odds (season_id, matchday_number);

CREATE INDEX IF NOT EXISTS idx_vfl_prematch_odds_event
    ON vfl_prematch_odds (event_id);

CREATE INDEX IF NOT EXISTS idx_vfl_prematch_odds_captured
    ON vfl_prematch_odds (captured_at DESC);