#!/usr/bin/env python3
"""Cassandra stress test — are bracket edges real or noise?"""

import sqlite3
import json
import statistics

DB = "/home/faith/Documents/Projects/vfl-data/databases/history.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all data with odds
cur.execute("""
    SELECT season, oh, od, oa, outcome FROM matches 
    WHERE oh IS NOT NULL AND outcome IS NOT NULL 
      AND oh > 0 AND od > 0 AND oa > 0
    ORDER BY season
""")
rows = [dict(r) for r in cur.fetchall()]
conn.close()

print(f"Total matches with valid odds: {len(rows)}")
print(f"Season range: {rows[0]['season']} - {rows[-1]['season']}")
print()

def implied_rate(oh, od, oa, pick):
    """Compute implied win rate from odds"""
    total = 1/oh + 1/od + 1/oa
    if pick == 'H':
        return (1/oh) / total
    elif pick == 'D':
        return (1/od) / total
    elif pick == 'A':
        return (1/oa) / total

def normalize_outcome(outcome):
    """Normalize outcome to H/D/A."""
    if outcome is None:
        return None
    outcome = outcome.strip().upper()
    if outcome in ('H', 'HOME'):
        return 'H'
    elif outcome in ('D', 'DRAW'):
        return 'D'
    elif outcome in ('A', 'AWAY'):
        return 'A'
    return None

def analyze_bracket(bracket_name, oh_min, oh_max, pick, rows):
    """Analyze a bracket for a specific pick edge."""
    filtered = [r for r in rows if oh_min <= r['oh'] < oh_max and normalize_outcome(r['outcome']) is not None]
    if len(filtered) < 10:
        return {"error": "insufficient data", "count": len(filtered)}
    
    # Split into two halves by match index
    mid = len(filtered) // 2
    halves = [("FIRST HALF", filtered[:mid]), ("SECOND HALF", filtered[mid:])]
    
    results = {}
    for label, chunk in halves:
        if not chunk:
            results[label] = {"error": "empty half"}
            continue
        
        total = len(chunk)
        picks = [r for r in chunk if normalize_outcome(r['outcome']) == pick]
        wins = len(picks)
        win_rate = wins / total
        
        # Average implied rate for this pick across all matches in the chunk
        implied_rates = [implied_rate(r['oh'], r['od'], r['oa'], pick) for r in chunk]
        avg_implied = statistics.mean(implied_rates)
        
        edge = win_rate - avg_implied
        
        pick_name = {'H': 'HOME', 'D': 'DRAW', 'A': 'AWAY'}[pick]
        
        # Show season range for context
        seasons = sorted(set(r['season'] for r in chunk))
        season_str = f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0])
        
        results[label] = {
            "matches": total,
            "seasons": season_str,
            f"{pick_name}_WINS": wins,
            f"{pick_name}_RATE": round(win_rate, 4),
            "AVG_IMPLIED_RATE": round(avg_implied, 4),
            "EDGE": round(edge, 4),
            "EDGE_PCT": f"{edge*100:+.2f}%"
        }
    
    return results

def verdict(results):
    """Determine if edge is real or noise."""
    if "error" in results or "error" in results.get("FIRST HALF", {}):
        return "INCONCLUSIVE — insufficient data"
    
    first_edge = results["FIRST HALF"]["EDGE"]
    second_edge = results["SECOND HALF"]["EDGE"]
    
    if first_edge > 0 and second_edge > 0:
        return "EDGE IS REAL ✅ — positive in BOTH halves"
    elif first_edge < 0 and second_edge < 0:
        return "EDGE IS INVERTED 🔄 — negative in BOTH halves (might be anti-value)"
    else:
        return "EDGE IS NOISE ❌ — positive in only ONE half"

# === MOD DOG (OH 4-5) → AWAY edge ===
print("=" * 65)
print("BRACKET: MOD DOG (OH 4-5) — AWAY EDGE")
print("=" * 65)
mod_dog = analyze_bracket("Mod Dog", 4, 5, 'A', rows)
for label, data in mod_dog.items():
    print(f"  {label}:")
    if "error" in data:
        print(f"    {data['error']}")
    else:
        print(f"    Matches: {data['matches']} ({data['seasons']})")
        print(f"    AWAY wins: {data['AWAY_WINS']} — rate: {data['AWAY_RATE']*100:.2f}%")
        print(f"    Avg implied rate: {data['AVG_IMPLIED_RATE']*100:.2f}%")
        print(f"    Edge: {data['EDGE_PCT']}")
print(f"  VERDICT: {verdict(mod_dog)}")
print()

# === HEAVY DOG (OH > 5) → DRAW edge ===
print("=" * 65)
print("BRACKET: HEAVY DOG (OH > 5) — DRAW EDGE")
print("=" * 65)
heavy_dog = analyze_bracket("Heavy Dog", 5, 999, 'D', rows)
for label, data in heavy_dog.items():
    print(f"  {label}:")
    if "error" in data:
        print(f"    {data['error']}")
    else:
        print(f"    Matches: {data['matches']} ({data['seasons']})")
        print(f"    DRAW wins: {data['DRAW_WINS']} — rate: {data['DRAW_RATE']*100:.2f}%")
        print(f"    Avg implied rate: {data['AVG_IMPLIED_RATE']*100:.2f}%")
        print(f"    Edge: {data['EDGE_PCT']}")
print(f"  VERDICT: {verdict(heavy_dog)}")
print()

# === SLIGHT DOG (OH 3-4) → HOME edge ===
print("=" * 65)
print("BRACKET: SLIGHT DOG (OH 3-4) — HOME EDGE")
print("=" * 65)
slight_dog = analyze_bracket("Slight Dog", 3, 4, 'H', rows)
for label, data in slight_dog.items():
    print(f"  {label}:")
    if "error" in data:
        print(f"    {data['error']}")
    else:
        print(f"    Matches: {data['matches']} ({data['seasons']})")
        print(f"    HOME wins: {data['HOME_WINS']} — rate: {data['HOME_RATE']*100:.2f}%")
        print(f"    Avg implied rate: {data['AVG_IMPLIED_RATE']*100:.2f}%")
        print(f"    Edge: {data['EDGE_PCT']}")
print(f"  VERDICT: {verdict(slight_dog)}")
print()

# === Bonus: MOD DOG — DRAW edge ===
print("=" * 65)
print("BONUS: MOD DOG (OH 4-5) — DRAW EDGE")
print("=" * 65)
mod_dog_draw = analyze_bracket("Mod Dog Draw", 4, 5, 'D', rows)
for label, data in mod_dog_draw.items():
    print(f"  {label}:")
    if "error" in data:
        print(f"    {data['error']}")
    else:
        print(f"    Matches: {data['matches']} ({data['seasons']})")
        print(f"    DRAW wins: {data['DRAW_WINS']} — rate: {data['DRAW_RATE']*100:.2f}%")
        print(f"    Avg implied rate: {data['AVG_IMPLIED_RATE']*100:.2f}%")
        print(f"    Edge: {data['EDGE_PCT']}")
print(f"  VERDICT: {verdict(mod_dog_draw)}")
print()

# Also output JSON
output = {
    "mod_dog_away": mod_dog,
    "mod_dog_away_verdict": verdict(mod_dog),
    "heavy_dog_draw": heavy_dog,
    "heavy_dog_draw_verdict": verdict(heavy_dog),
    "slight_dog_home": slight_dog,
    "slight_dog_home_verdict": verdict(slight_dog),
    "mod_dog_draw": mod_dog_draw,
    "mod_dog_draw_verdict": verdict(mod_dog_draw),
}

with open("/home/faith/Documents/Projects/vfl-data/analysis/cassandra-stress.json", "w") as f:
    json.dump(output, f, indent=2)

print("✅ Results written to cassandra-stress.json")
