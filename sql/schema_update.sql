-- vfl_chronological_schema.sql
-- Normalized schema for tracking VFL seasons, matchdays, and league snapshots.

-- 1. Seasons
CREATE TABLE IF NOT EXISTS vfl_seasons (
    id SERIAL PRIMARY KEY,
    season_id TEXT UNIQUE NOT NULL, -- The MSport/Betradar UUID
    season_name TEXT NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. MatchDays
CREATE TABLE IF NOT EXISTS vfl_matchdays (
    id SERIAL PRIMARY KEY,
    season_id INTEGER REFERENCES vfl_seasons(id) ON DELETE CASCADE,
    matchday_number INTEGER NOT NULL,
    status TEXT DEFAULT 'FINISHED', -- 'FINISHED', 'UPCOMING', 'ACTIVE'
    UNIQUE(season_id, matchday_number)
);

-- 3. Enhanced Results (Link to MatchDay)
CREATE TABLE IF NOT EXISTS vfl_results_v2 (
    id SERIAL PRIMARY KEY,
    matchday_id INTEGER REFERENCES vfl_matchdays(id) ON DELETE CASCADE,
    event_id TEXT UNIQUE NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_goals INTEGER NOT NULL,
    away_goals INTEGER NOT NULL,
    total_goals INTEGER GENERATED ALWAYS AS (home_goals + away_goals) STORED,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. League Table Snapshots (Chronological)
CREATE TABLE IF NOT EXISTS vfl_league_snapshots (
    id SERIAL PRIMARY KEY,
    matchday_id INTEGER REFERENCES vfl_matchdays(id) ON DELETE CASCADE,
    team_name TEXT NOT NULL,
    rank INTEGER NOT NULL,
    points INTEGER NOT NULL,
    played INTEGER NOT NULL,
    won INTEGER NOT NULL,
    draw INTEGER NOT NULL,
    lost INTEGER NOT NULL,
    goals_for INTEGER NOT NULL,
    goals_against INTEGER NOT NULL,
    goal_diff INTEGER NOT NULL,
    form TEXT, -- e.g. 'WWDLD'
    UNIQUE(matchday_id, team_name)
);

-- Indices for fast lookups
CREATE INDEX IF NOT EXISTS idx_snapshots_team ON vfl_league_snapshots(team_name);
CREATE INDEX IF NOT EXISTS idx_results_teams ON vfl_results_v2(home_team, away_team);
