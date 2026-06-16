import sqlite3
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

cursor.execute("SELECT season FROM h_db.matches ORDER BY id DESC LIMIT 15000")
recent_seasons = [r[0] for r in cursor.fetchall()]
from collections import Counter
c = Counter(recent_seasons)
completed_seasons = [s for s, count in c.items() if count == 240]

routes = defaultdict(lambda: {'1x_hit': 0, 'total': 0})

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
            if hg >= ag:  # Home Win or Draw (1X)
                routes[route]['1x_hit'] += 1
                
        if hg > ag: team_pts[h] += 3
        elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
        else: team_pts[a] += 3

print("--- ANALYZING THE TIER 4 vs TIER 2 SWAP ---")

targets = [
    # Original MD 11-15
    ("MD 11-15", "T4(13-16)", "T3(9-12)"), # Original: Home T4
    ("MD 11-15", "T2(5-8)", "T3(9-12)"),   # Swapped: Home T2
    
    # Original MD 6-10
    ("MD 6-10", "T2(5-8)", "T4(13-16)"),   # Original: Away T4
    ("MD 6-10", "T2(5-8)", "T2(5-8)"),     # Swapped: Away T2
]

for t in targets:
    chunk, ht, at = t
    stats = routes.get((chunk, ht, at), {'total': 0, '1x_hit': 0})
    if stats['total'] > 0:
        hr = (stats['1x_hit'] / stats['total']) * 100
        print(f"[{chunk}] Home {ht} vs Away {at} -> 1X Hit Rate: {hr:.1f}% ({stats['1x_hit']}/{stats['total']})")
    else:
        print(f"[{chunk}] Home {ht} vs Away {at} -> No Data")
