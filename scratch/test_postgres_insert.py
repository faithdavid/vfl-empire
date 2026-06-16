import sys, os
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db
from datetime import datetime, timezone

def test_insert():
    try:
        with get_db() as cur:
            now = datetime.now(timezone.utc).isoformat()
            cur.execute("""
                INSERT INTO vfl_odds_v2
                (event_id, season_id, matchday_number, home_team, away_team, o15, o25, u25, u35, gg, ng, captured_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, ("test_eid", "test_sid", 1, "Home", "Away", 1.2, 1.8, 2.0, 1.15, 1.9, 1.8, now))
            print("Insert successful")
    except Exception as e:
        print(f"Insert failed: {e}")

if __name__ == "__main__":
    test_insert()
