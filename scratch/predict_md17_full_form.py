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

# The first season's matches
matches = results_data.get('matches', [])[:240]

def get_full_form(team, current_md):
    team_matches = [m for m in matches if m.get('match_day') <= current_md and (m.get('home_team') == team or m.get('away_team') == team)]
    team_matches.sort(key=lambda x: x.get('match_day'))
    
    pieces = []
    for m in team_matches:
        is_home = (m['home_team'] == team)
        opp = m['away_team'] if is_home else m['home_team']
        opp_code = get_code(opp)
        
        hg = m.get('home_goals', None)
        ag = m.get('away_goals', None)
        if hg is not None and ag is not None:
            gf = hg if is_home else ag
            ga = ag if is_home else hg
            if gf > ga: res = 'W'
            elif gf == ga: res = 'D'
            else: res = 'L'
            loc = "H" if is_home else "A"
            pieces.append(f"{res}{loc}({opp_code})")
        else:
            pieces.append(f"?({opp_code})")
    
    return " ".join(pieces)

team_stats = {t: {'pts': 0, 'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0} for t in codes.keys()}

for m in matches:
    if m.get('match_day') > 16: continue
    h = m['home_team']
    a = m['away_team']
    hg = m.get('home_goals', 0)
    ag = m.get('away_goals', 0)
    
    team_stats[h]['gf'] += hg
    team_stats[h]['ga'] += ag
    team_stats[a]['gf'] += ag
    team_stats[a]['ga'] += hg
    
    if hg > ag:
        team_stats[h]['pts'] += 3
        team_stats[h]['w'] += 1
        team_stats[a]['l'] += 1
    elif hg == ag:
        team_stats[h]['pts'] += 1
        team_stats[h]['d'] += 1
        team_stats[a]['pts'] += 1
        team_stats[a]['d'] += 1
    else:
        team_stats[a]['pts'] += 3
        team_stats[a]['w'] += 1
        team_stats[h]['l'] += 1

sorted_teams = sorted(team_stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga'], x[1]['gf']), reverse=True)

print("### 🏆 FULL AUGMENTED LEAGUE TABLE (AFTER MD 16)")
print("| Rank | Team | Pts | W | D | L | GF | GA | GD | Full 16-Match Form String |")
print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
for rank, (team, stats) in enumerate(sorted_teams, 1):
    gd = stats['gf'] - stats['ga']
    full_form = get_full_form(team, 16)
    print(f"| **{rank}** | **{team}** | **{stats['pts']}** | {stats['w']} | {stats['d']} | {stats['l']} | {stats['gf']} | {stats['ga']} | {gd:+d} | `{full_form}` |")

print("\n### ⚽ MATCHDAY 17 FIXTURES")
md17 = [m for m in matches if m.get('match_day') == 17]
for i, fix in enumerate(md17, 1):
    h = fix.get('home_team')
    a = fix.get('away_team')
    print(f"{i}. {h} vs {a}")
