-- Canonical aligned fixture dataset: results + best normal odds snapshot.
-- Populated by scripts/align_dataset.py (not hand-maintained).

CREATE TABLE IF NOT EXISTS vfl_fixture_aligned (
    result_id           INTEGER PRIMARY KEY REFERENCES vfl_results_v2(id) ON DELETE CASCADE,
    season_name         TEXT NOT NULL,
    season_id           TEXT NOT NULL,
    matchday_id         INTEGER NOT NULL REFERENCES vfl_matchdays(id),
    matchday_number     INTEGER NOT NULL,
    event_id            TEXT,
    home_team           TEXT NOT NULL,
    away_team           TEXT NOT NULL,
    home_goals          INTEGER NOT NULL,
    away_goals          INTEGER NOT NULL,
    total_goals         INTEGER NOT NULL,
    o15                 REAL,
    o25                 REAL,
    u25                 REAL,
    u35                 REAL,
    gg                  REAL,
    ng                  REAL,
    odds_captured_at    TIMESTAMPTZ,
    has_core_odds       BOOLEAN NOT NULL DEFAULT FALSE,
    has_league_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    over_15             BOOLEAN NOT NULL,
    over_25             BOOLEAN NOT NULL,
    under_25            BOOLEAN NOT NULL,
    under_35            BOOLEAN NOT NULL,
    gg_yes              BOOLEAN NOT NULL,
    ng_yes              BOOLEAN NOT NULL,
    home_win            BOOLEAN NOT NULL,
    draw                BOOLEAN NOT NULL,
    away_win            BOOLEAN NOT NULL,
    aligned_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vfl_fixture_aligned_season_md
    ON vfl_fixture_aligned (season_name, matchday_number);

CREATE INDEX IF NOT EXISTS idx_vfl_fixture_aligned_season_id
    ON vfl_fixture_aligned (season_id, matchday_number);

CREATE INDEX IF NOT EXISTS idx_vfl_fixture_aligned_core_odds
    ON vfl_fixture_aligned (has_core_odds) WHERE has_core_odds;

CREATE TABLE IF NOT EXISTS vfl_aligned_seasons (
    season_name     TEXT PRIMARY KEY,
    season_id       TEXT NOT NULL,
    matchdays       INTEGER NOT NULL,
    fixtures        INTEGER NOT NULL,
    core_odds_fixtures INTEGER NOT NULL,
    snapshot_fixtures INTEGER NOT NULL,
    complete_both   BOOLEAN NOT NULL DEFAULT TRUE,
    first_matchday  INTEGER,
    last_matchday   INTEGER,
    aligned_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);