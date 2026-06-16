import sys
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

with get_db() as cur:
    cur.execute("""
        SELECT COUNT(*)
        FROM vfl_results_v2 r
        JOIN vfl_matchdays m ON r.matchday_id = m.id
        JOIN vfl_seasons s ON m.season_id = s.id
        JOIN vfl_odds_v2 o ON (
            o.season_id = s.season_id
            AND o.matchday_number = m.matchday_number
            AND o.home_team = r.home_team
            AND o.away_team = r.away_team
        )
        WHERE o.o15 IS NOT NULL AND o.o25 IS NOT NULL AND o.u35 IS NOT NULL AND o.gg IS NOT NULL
          AND r.total_goals IS NOT NULL
    """)
    print(f"Total matching matches with complete odds + results: {cur.fetchone()[0]}")

