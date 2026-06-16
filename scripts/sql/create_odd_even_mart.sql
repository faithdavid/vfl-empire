-- Gold mart: MSport Odd/Even market + canonical results (816 complete seasons).
-- Run: sudo -u postgres psql -d vfl_empire -f scripts/sql/create_odd_even_mart.sql

CREATE OR REPLACE VIEW v_results_odd_even_ready AS
WITH complete_season AS (
    SELECT s.id AS season_pk,
           s.season_id AS season_key,
           s.season_name,
           CAST(REGEXP_REPLACE(s.season_name, '[^0-9]', '', 'g') AS INTEGER) AS vflm_num
    FROM vfl_seasons s
    JOIN vfl_matchdays md ON md.season_id = s.id
    JOIN vfl_results_v2 r ON r.matchday_id = md.id
    WHERE s.season_name ~ '^VFLM'
    GROUP BY s.id, s.season_id, s.season_name
    HAVING COUNT(DISTINCT md.matchday_number) = 30
       AND COUNT(r.id) = 240
),
odds_pivot AS (
    SELECT
        event_id,
        MAX(CASE WHEN selection_name = 'Odd'  THEN odds END) AS odd_odds,
        MAX(CASE WHEN selection_name = 'Even' THEN odds END) AS even_odds,
        MAX(captured_at) AS odds_captured_at
    FROM vfl_prematch_odds
    WHERE market_name = 'Odd/Even'
    GROUP BY event_id
)
SELECT
    vs.season_name,
    cs.vflm_num,
    md.matchday_number,
    r.event_id,
    r.home_team,
    r.away_team,
    r.home_goals,
    r.away_goals,
    r.total_goals,
    (r.total_goals % 2) AS total_goals_odd,  -- 1 = Odd wins, 0 = Even wins
    o.odd_odds,
    o.even_odds,
    CASE WHEN r.event_id LIKE 'vf:match:%' THEN 'live'
         WHEN r.event_id LIKE 'history:%' THEN 'history'
         ELSE 'other' END AS result_source,
    r.captured_at AS result_captured_at,
    o.odds_captured_at
FROM vfl_results_v2 r
JOIN vfl_matchdays md ON md.id = r.matchday_id
JOIN complete_season cs ON cs.season_pk = md.season_id
JOIN vfl_seasons vs ON vs.id = cs.season_pk
LEFT JOIN odds_pivot o ON o.event_id = r.event_id;

COMMENT ON VIEW v_results_odd_even_ready IS
'Canonical 240-fixture seasons; label total_goals_odd (MSport Odd/Even settlement); optional prematch Odd/Even odds';