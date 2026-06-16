import sqlite3

codes = {
    'Manchester Blue': 'MBL', 'Liverpool': 'LIV', 'Chelsea': 'CHE', 'London Guns': 'LOG',
    'Aston Villa': 'AVL', 'Wolverhampton': 'WOL', 'Crystal Palace': 'CRY', 'Leeds': 'LEE',
    'Manchester Red': 'MRE', 'Tottenham': 'TOT', 'West Ham': 'WHU', 'Everton': 'EVE',
    'Newcastle': 'NEW', 'Brighton': 'BHA', 'Fulham': 'FUL', 'Bournemouth': 'BOU'
}

def get_code(team):
    return codes.get(team, team[:3].upper())

conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/vfl_results.db')
c = conn.cursor()

# Get matches for a specific team in Season 1, up to Matchday 10
team = 'Manchester Blue'
c.execute("""
    SELECT match_day, home_team, away_team, home_goals, away_goals 
    FROM results 
    WHERE season_id = 1 AND match_day <= 10 AND (home_team = ? OR away_team = ?)
    ORDER BY match_day DESC
    LIMIT 5
""", (team, team))

matches = c.fetchall()
form_pieces = []
# matches are DESC (latest first). Let's process them and reverse at the end
for m in matches:
    md, home, away, hg, ag = m
    is_home = (home == team)
    opp = away if is_home else home
    opp_code = get_code(opp)
    
    gf = hg if is_home else ag
    ga = ag if is_home else hg
    
    if gf > ga: res = 'W'
    elif gf == ga: res = 'D'
    else: res = 'L'
    
    form_pieces.append(f"{res}({opp_code})")

form_pieces.reverse() # oldest to newest
print(f"Augmented Form for {team} (MD6 to MD10):", "-".join(form_pieces))

conn.close()
