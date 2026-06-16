import sqlite3
import json
from collections import defaultdict

def get_tier(rank):
    if rank <= 4: return 'T1(1-4)'
    if rank <= 8: return 'T2(5-8)'
    if rank <= 12: return 'T3(9-12)'
    return 'T4(13-16)'

def get_md_chunk(md):
    if md <= 5: return 'MD 1-5'
    if md <= 10: return 'MD 6-10'
    if md <= 15: return 'MD 11-15'
    if md <= 20: return 'MD 16-20'
    if md <= 25: return 'MD 21-25'
    return 'MD 26-30'

conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-complete-data/vfl_odds.db')
conn.execute("ATTACH DATABASE '/home/ubuntu/faith-workspace/vfl-complete-data/history.db' AS h_db")
cursor = conn.cursor()

# Get all completed seasons
cursor.execute("SELECT season FROM h_db.matches ORDER BY id DESC LIMIT 15000")
recent_seasons = [r[0] for r in cursor.fetchall()]
from collections import Counter
c = Counter(recent_seasons)
completed_seasons = [s for s, count in c.items() if count == 240]

# Route format: (chunk, home_tier, away_tier) -> {'x2_hit': 0, 'total': 0}
routes = defaultdict(lambda: {'x2_hit': 0, 'total': 0})

for season in completed_seasons:
    cursor.execute("SELECT day, home, away, h, a FROM h_db.matches WHERE season = ? ORDER BY id ASC", (season,))
    matches = cursor.fetchall()
    
    team_pts = {t: 0 for t in set(m[1] for m in matches)}
    
    for m in matches:
        md = m[0]
        h, a = m[1], m[2]
        hg, ag = m[3], m[4]
        if hg is None or ag is None: continue
        
        ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
        h_t = 'Start' if md==1 else get_tier(ranks[h])
        a_t = 'Start' if md==1 else get_tier(ranks[a])
        chunk = get_md_chunk(md)
        
        if md > 1:
            route = (chunk, h_t, a_t)
            routes[route]['total'] += 1
            if ag >= hg:  # Away Win or Draw (X2)
                routes[route]['x2_hit'] += 1
                
        # update points
        if hg > ag: team_pts[h] += 3
        elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
        else: team_pts[a] += 3

print("--- TOP X2 (AWAY WIN/DRAW) TIER-ROUTING LOCKS ---")
for route, stats in routes.items():
    if stats['total'] >= 20:
        hit_rate = (stats['x2_hit'] / stats['total']) * 100
        if hit_rate >= 80.0:  # Find >80% hit rate
            print(f"Route: [{route[0]}] Home: {route[1]} vs Away: {route[2]} -> X2 Hit Rate: {hit_rate:.1f}% ({stats['x2_hit']}/{stats['total']})")
