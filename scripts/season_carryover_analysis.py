#!/usr/bin/env python3
import psycopg2
import pandas as pd
import sys

# Connect to DB
conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

# Get seasons chronologically based on their first match ID to ensure we map Season N to Season N+1 accurately
query_seasons = """
    SELECT season, MIN(id) as first_match
    FROM matches
    GROUP BY season
    ORDER BY first_match ASC
"""
df_seasons = pd.read_sql_query(query_seasons, conn)

if len(df_seasons) < 2:
    print("Not enough seasons for carryover analysis.")
    sys.exit()

print(f"Loaded {len(df_seasons)} consecutive seasons. Analyzing carryover from MD30 to MD1...")

# We will track the performance in Season N+1 MD1 for teams based on their final rank in Season N
tier_performance = {
    "T1 (Rank 1-4)": {"W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Matches": 0},
    "T2 (Rank 5-8)": {"W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Matches": 0},
    "T3 (Rank 9-12)": {"W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Matches": 0},
    "T4 (Rank 13-16)": {"W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Matches": 0},
}

for i in range(len(df_seasons) - 1):
    s1_id = df_seasons.iloc[i]['season']
    s2_id = df_seasons.iloc[i+1]['season']
    
    # Calculate S1 final standings (MD30) manually from matches table
    query_s1 = f"""
        SELECT home, away, h, a 
        FROM matches 
        WHERE season = '{s1_id}'
    """
    try:
        df_s1 = pd.read_sql_query(query_s1, conn)
    except Exception:
        continue
        
    if df_s1.empty:
        continue
        
    points = {}
    gd = {}
    for _, row in df_s1.iterrows():
        h_t, a_t, hg, ag = row['home'], row['away'], row['h'], row['a']
        if hg is None or pd.isna(hg): hg = 0
        if ag is None or pd.isna(ag): ag = 0
        
        if h_t not in points: points[h_t] = 0; gd[h_t] = 0
        if a_t not in points: points[a_t] = 0; gd[a_t] = 0
        
        gd[h_t] += (hg - ag)
        gd[a_t] += (ag - hg)
        
        if hg > ag: points[h_t] += 3
        elif ag > hg: points[a_t] += 3
        else: points[h_t] += 1; points[a_t] += 1
        
    standings = sorted(points.keys(), key=lambda t: (-points[t], -gd[t]))
    rank_map = {t: rank+1 for rank, t in enumerate(standings)}
    
    # Get MD1 results for S2
    query_s2 = f"""
        SELECT home as home_team, away as away_team, h as home_goals, a as away_goals
        FROM matches
        WHERE season = '{s2_id}' AND day = 1
    """
    df_s2 = pd.read_sql_query(query_s2, conn)
    
    if df_s2.empty:
        continue
        
    for _, row in df_s2.iterrows():
        h_team, a_team = row['home_team'], row['away_team']
        hg, ag = row['home_goals'], row['away_goals']
        
        if hg is None or pd.isna(hg): hg = 0
        if ag is None or pd.isna(ag): ag = 0
        
        # Determine tiers from previous season
        h_rank = rank_map.get(h_team)
        a_rank = rank_map.get(a_team)
        
        if not h_rank or not a_rank:
            continue
            
        def get_tier(rank):
            if rank <= 4: return "T1 (Rank 1-4)"
            if rank <= 8: return "T2 (Rank 5-8)"
            if rank <= 12: return "T3 (Rank 9-12)"
            return "T4 (Rank 13-16)"
            
        h_tier = get_tier(h_rank)
        a_tier = get_tier(a_rank)
        
        # Update Home Team Stats
        tier_performance[h_tier]["Matches"] += 1
        tier_performance[h_tier]["GF"] += hg
        tier_performance[h_tier]["GA"] += ag
        if hg > ag: tier_performance[h_tier]["W"] += 1
        elif hg == ag: tier_performance[h_tier]["D"] += 1
        else: tier_performance[h_tier]["L"] += 1
            
        # Update Away Team Stats
        tier_performance[a_tier]["Matches"] += 1
        tier_performance[a_tier]["GF"] += ag
        tier_performance[a_tier]["GA"] += hg
        if ag > hg: tier_performance[a_tier]["W"] += 1
        elif ag == hg: tier_performance[a_tier]["D"] += 1
        else: tier_performance[a_tier]["L"] += 1

print("\n=== Previous Season MD30 Rank vs Next Season MD1 Performance ===")
for tier, stats in tier_performance.items():
    matches = stats["Matches"]
    if matches == 0: continue
    win_rate = (stats["W"] / matches) * 100
    avg_gf = stats["GF"] / matches
    avg_ga = stats["GA"] / matches
    
    print(f"{tier}:")
    print(f"  Win Rate: {win_rate:.1f}% | W: {stats['W']}, D: {stats['D']}, L: {stats['L']}")
    print(f"  Avg Goals For: {avg_gf:.2f} | Avg Goals Against: {avg_ga:.2f}")

# Check if T1 teams get nerfed and T4 teams get buffed (Rubber-banding effect)
t1_win = tier_performance["T1 (Rank 1-4)"]["W"] / max(1, tier_performance["T1 (Rank 1-4)"]["Matches"])
t4_win = tier_performance["T4 (Rank 13-16)"]["W"] / max(1, tier_performance["T4 (Rank 13-16)"]["Matches"])

print("\n=== Carryover Conclusion ===")
if t1_win > 0.45:
    print("MOMENTUM ENGINE: Top teams from last season retain high hidden form into MD1.")
elif t4_win > t1_win:
    print("RUBBER-BAND ENGINE: Bottom teams from last season are mathematically buffed in MD1 (Nerf/Buff Cycle detected).")
else:
    print("RESET ENGINE: The engine appears to hard-reset form. All tiers perform at an average 30-40% win rate in MD1.")

conn.close()
