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

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    results_data = json.load(f)
    
matches = results_data.get('matches', [])

def get_augmented_form(team, current_md):
    # Get last 5 matches for this team before current_md
    team_matches = [m for m in matches if m.get('match_day') <= current_md and (m.get('home_team') == team or m.get('away_team') == team)]
    team_matches.sort(key=lambda x: x.get('match_day'))
    recent = team_matches[-5:]
    
    pieces = []
    for m in recent:
        is_home = (m['home_team'] == team)
        opp = m['away_team'] if is_home else m['home_team']
        opp_code = get_code(opp)
        
        # Determine result. Wait, does results_last12h_compiled have home_goals/away_goals?
        # Let's check structure: usually it has 'score' like "3:1" or home_goals/away_goals
        score = m.get('score', '')
        if score:
            parts = score.split(':')
            hg, ag = int(parts[0]), int(parts[1])
            gf = hg if is_home else ag
            ga = ag if is_home else hg
            if gf > ga: res = 'W'
            elif gf == ga: res = 'D'
            else: res = 'L'
            pieces.append(f"{res}({opp_code})")
        else:
            pieces.append(f"?({opp_code})")
    
    return " - ".join(pieces)

try:
    from services.common.db_manager import get_db
    with get_db() as cur:
        # Get MD 15 standings
        cur.execute("""
            SELECT team_name, rank, points, won, draw, lost, goals_for, goals_against, goal_diff 
            FROM vfl_league_snapshots 
            WHERE played = 15
            ORDER BY id DESC
            LIMIT 16;
        """)
        rows = cur.fetchall()
        rows.sort(key=lambda x: x[1]) # Sort by rank ascending
        print("### 🏆 AUGMENTED LEAGUE TABLE (AFTER MD 15)")
        print("| Rank | Team | Points | W | D | L | GF | GA | GD | Augmented Form |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in rows:
            team = r[0]
            aug_form = get_augmented_form(team, 15)
            print(f"| **{r[1]}** | **{r[0]}** | **{r[2]}** | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]:+d} | `{aug_form}` |")
            
    # Get MD 16 fixtures
    print("\n### ⚽ MATCHDAY 16 FIXTURES")
    md16_matches = [m for m in matches if m.get('match_day') == 16]
    for i, m in enumerate(md16_matches, 1):
        print(f"{i}. {m['home_team']} vs {m['away_team']}")

except Exception as e:
    print(f"Error: {e}")
