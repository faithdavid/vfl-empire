-- Maps (season, matchday, teams) -> canonical MSport event_id (vf:match:NNNNNNNN)
CREATE TABLE IF NOT EXISTS fixture_event_map (
    id BIGSERIAL PRIMARY KEY,
    season_id TEXT NOT NULL,
    season_name TEXT,
    matchday_number INTEGER NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    event_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'event_list',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (season_id, matchday_number, home_team, away_team)
);

CREATE INDEX IF NOT EXISTS idx_fixture_event_map_event_id ON fixture_event_map(event_id);
CREATE INDEX IF NOT EXISTS idx_fixture_event_map_season_md ON fixture_event_map(season_id, matchday_number);