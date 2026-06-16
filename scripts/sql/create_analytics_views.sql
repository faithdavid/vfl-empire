-- Analytics marts (silver -> gold). Idempotent.
-- Run: sudo -u postgres psql -d vfl_empire -f scripts/sql/create_analytics_views.sql

CREATE OR REPLACE VIEW v_season_completeness AS
SELECT
    vs.season_id,
    vs.season_name,
    COUNT(DISTINCT md.matchday_number) AS matchdays_seen,
    COUNT(r.id) AS result_rows,
    (SELECT COUNT(DISTINCT event_id) FROM vfl_prematch_odds p WHERE p.season_id = vs.season_id) AS fixtures_with_prematch,
    (SELECT COUNT(DISTINCT market_name) FROM vfl_prematch_odds p WHERE p.season_id = vs.season_id) AS distinct_market_families,
    CASE
        WHEN COUNT(DISTINCT md.matchday_number) >= 30 AND COUNT(r.id) >= 240 THEN true
        ELSE false
    END AS season_results_complete_30x240
FROM vfl_seasons vs
LEFT JOIN vfl_matchdays md ON md.season_id = vs.id
LEFT JOIN vfl_results_v2 r ON r.matchday_id = md.id
GROUP BY vs.season_id, vs.season_name;

CREATE OR REPLACE VIEW v_fixture_results AS
SELECT
    vs.season_id,
    vs.season_name,
    md.matchday_number,
    r.event_id,
    r.home_team,
    r.away_team,
    r.home_goals,
    r.away_goals,
    r.total_goals,
    r.captured_at AS result_captured_at
FROM vfl_results_v2 r
JOIN vfl_matchdays md ON md.id = r.matchday_id
JOIN vfl_seasons vs ON vs.id = md.season_id;

COMMENT ON VIEW v_fixture_results IS 'Canonical finished fixtures with season/matchday labels';