import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "services"))
from common.db_manager import get_db

def repair():
    with get_db() as cur:
        # Find all unsettled bets with missing season_name
        cur.execute("""
            SELECT id, match, matchday FROM vfl_bets
            WHERE settled = False AND season_name IS NULL
        """)
        bets = cur.fetchall()
        print(f"Found {len(bets)} unsettled bets with missing season_name")
        
        repaired = 0
        for bid, match_str, matchday in bets:
            if not match_str:
                continue
            # Get first match
            first_fixture = match_str.split(",")[0].strip()
            if " vs " not in first_fixture:
                continue
            home, away = first_fixture.split(" vs ")
            home, away = home.strip(), away.strip()
            
            # Find matching prediction
            cur.execute("""
                SELECT season FROM vfl_predictions
                WHERE match_day = %s 
                  AND (
                    (home_team = %s AND away_team = %s)
                    OR
                    (home_team ILIKE %s AND away_team ILIKE %s)
                  )
                LIMIT 1
            """, (matchday, home, away, f"%{home}%", f"%{away}%"))
            row = cur.fetchone()
            if row and row[0]:
                season_name = row[0]
                cur.execute("""
                    UPDATE vfl_bets
                    SET season_name = %s
                    WHERE id = %s
                """, (season_name, bid))
                repaired += 1
            else:
                # If not found via prediction, let's try finding the season active around the bet's timestamp
                cur.execute("SELECT timestamp FROM vfl_bets WHERE id = %s", (bid,))
                ts_row = cur.fetchone()
                if ts_row and ts_row[0]:
                    ts = ts_row[0]
                    # Find season with captured_at closest before ts
                    cur.execute("""
                        SELECT season_name FROM vfl_seasons
                        WHERE captured_at <= %s
                        ORDER BY captured_at DESC LIMIT 1
                    """, (ts,))
                    s_row = cur.fetchone()
                    if s_row and s_row[0]:
                        season_name = s_row[0]
                        cur.execute("""
                            UPDATE vfl_bets
                            SET season_name = %s
                            WHERE id = %s
                        """, (season_name, bid))
                        repaired += 1
                        
        print(f"Successfully repaired {repaired} bets")

if __name__ == "__main__":
    repair()
