import sys
import json
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire')

codes = {
    'Manchester Blue': 'MBL', 'Liverpool': 'LIV', 'Chelsea': 'CHE', 'London Guns': 'LOG',
    'Aston Villa': 'AVL', 'Wolverhampton': 'WOL', 'Crystal Palace': 'CRY', 'Leeds': 'LEE',
    'Manchester Red': 'MRE', 'Tottenham': 'TOT', 'West Ham': 'WHU', 'Everton': 'EVE',
    'Newcastle': 'NEW', 'Brighton': 'BHA', 'Fulham': 'FUL', 'Bournemouth': 'BOU'
}

def get_code(team):
    return codes.get(team, team[:3].upper())

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/predictions_latest.json') as f:
    live_data = json.load(f)

md20_fixtures = []
for md in live_data.get('matchdays', []):
    if md.get('matchday') == 20:
        md20_fixtures = md.get('fixtures', [])
        break

try:
    from services.common.db_manager import get_db
    with get_db() as cur:
        # Get MD 19 standings
        cur.execute("""
            SELECT team_name, rank, points, won, draw, lost, goals_for, goals_against, goal_diff 
            FROM vfl_league_snapshots 
            WHERE played = 19
            ORDER BY id DESC
            LIMIT 16;
        """)
        rows = cur.fetchall()
        rows.sort(key=lambda x: x[1]) # Sort by rank ascending
        
        print("### 🏆 LIVE AUGMENTED LEAGUE TABLE (AFTER MD 19)")
        print("| Rank | Team | Points | W | D | L | GF | GA | GD | Form (Placeholder for live DB missing opponents) |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in rows:
            print(f"| **{r[1]}** | **{r[0]}** | **{r[2]}** | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]:+d} | |")
            
    print("\n### ⚽ LIVE MATCHDAY 20 FIXTURES & ODDS")
    for i, fix in enumerate(md20_fixtures, 1):
        h = fix.get('home')
        a = fix.get('away')
        odds = fix.get('odds', {})
        print(f"{i}. {h} vs {a} | 1: {odds.get('home_win')} | X: {odds.get('draw')} | 2: {odds.get('away_win')}")

except Exception as e:
    print(f"Error: {e}")
