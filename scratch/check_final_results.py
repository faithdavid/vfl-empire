import sys, os, json
sys.path.insert(0, os.path.expanduser("~/faith-workspace/vfl-empire/services"))
from common import db_manager

def check_results():
    # Check MD 5 and 6 for Season 5148
    query = """
        SELECT match_day, home_team, away_team, home_goals, away_goals, total_goals
        FROM results
        WHERE season_name = 'VFLM 5148' AND match_day IN (5, 6)
        ORDER BY match_day, home_team
    """
    rows = db_manager.fetch_all(query)
    for r in rows:
        print(f"MD{r['match_day']} | {r['home_team']} vs {r['away_team']} | {r['home_goals']}-{r['away_goals']} (Total: {r['total_goals']})")

if __name__ == "__main__":
    check_results()
