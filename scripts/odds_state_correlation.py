#!/usr/bin/env python3
"""Odds vs Finite State Space Correlation Analysis.
For every fixture pair, compare pre-match odds against actual results
to find systematic mispricings and exploitable patterns.

The core question: Do certain odds values predict outcomes better 
than our model, across the finite set of 240 fixture pairs?
"""
import sqlite3, json, sys
from collections import defaultdict, Counter
from datetime import datetime

RESULTS_DB = '/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db'
HISTORY_DB = '/home/ubuntu/faith-workspace/vfl-complete-dataset/databases/history.db'
OUT_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis'

def load_data():
    """Load results + odds data from both databases."""
    conn = sqlite3.connect(RESULTS_DB)
    conn.row_factory = sqlite3.Row
    
    results = conn.execute("""
        SELECT season_name, season_id, match_day, home_team, away_team, 
               home_goals, away_goals, total_goals, event_id
        FROM results WHERE status = 3
    """).fetchall()
    print(f"Loaded {len(results)} completed results")
    
    # Try to load odds data from the deep_markets table
    hist_conn = sqlite3.connect(HISTORY_DB)
    hist_conn.row_factory = sqlite3.Row
    
    # Check what tables exist
    tables = [t['name'] for t in hist_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"History DB tables: {tables}")
    
    # Check if there's any odds data we can cross-reference
    # The history.db has matches with odds but no scores
    # The results.db has scores but no odds
    # We need to join them by (season, home_team, away_team)
    
    # Let's check if matches in history.db have odds populated
    hist_matches = hist_conn.execute("""
        SELECT season, day, home, away, oh, od, oa, outcome,
               h, a, total, gg, o25, half_time, first_goal
        FROM matches 
        WHERE oh IS NOT NULL AND h IS NOT NULL
        LIMIT 10
    """).fetchall()
    print(f"Sample history matches with odds AND scores: {len(hist_matches)}")
    if hist_matches:
        for r in hist_matches:
            print(dict(r))
    
    # Get count of matches with odds
    with_odds = hist_conn.execute("SELECT COUNT(*) FROM matches WHERE oh IS NOT NULL").fetchone()[0]
    with_scores = hist_conn.execute("SELECT COUNT(*) FROM matches WHERE h IS NOT NULL").fetchone()[0]
    with_both = hist_conn.execute("SELECT COUNT(*) FROM matches WHERE oh IS NOT NULL AND h IS NOT NULL").fetchone()[0]
    print(f"History: {with_odds} with odds, {with_scores} with scores, {with_both} with both")
    
    return results, hist_conn

def build_odds_vs_results(results, hist_conn):
    """Match odds from history.db with results from results.db by season+teams."""
    
    # Build lookup from history.db: (season_id, home, away) -> odds
    hist_rows = hist_conn.execute("""
        SELECT season, home, away, oh, od, oa, outcome, h, a, total, half_time, first_goal
        FROM matches WHERE oh IS NOT NULL
    """).fetchall()
    
    odds_lookup = {}
    for r in hist_rows:
        d = dict(r)
        key = (d['season'], d['home'], d['away'])
        odds_lookup[key] = d
    
    # For each result, try to find matching odds
    # Use season_name/season_id + home_team + away_team as join key
    matched = []
    unmatched = 0
    
    for r in results:
        d = dict(r)
        # Try exact season_id match
        key = (d['season_id'], d['home_team'], d['away_team'])
        odds = odds_lookup.get(key)
        
        if not odds:
            # Try season_name
            key2 = (d['season_name'], d['home_team'], d['away_team'])
            odds = odds_lookup.get(key2)
        
        if odds:
            matched.append({
                'season': d['season_name'],
                'match_day': d['match_day'],
                'home': d['home_team'],
                'away': d['away_team'],
                'home_goals': d['home_goals'],
                'away_goals': d['away_goals'],
                'total_goals': d['total_goals'],
                'o15_odds': None,  # We don't have O1.5 odds in history.db schema
                'home_odds': odds.get('oh'),
                'draw_odds': odds.get('od'),
                'away_odds': odds.get('oa'),
                'outcome': odds.get('outcome'),
            })
        else:
            unmatched += 1
    
    print(f"\nMatched: {len(matched)} results with odds")
    print(f"Unmatched: {unmatched}")
    
    return matched

def analyze_by_pair(matched_data):
    """Group matched data by fixture pair and analyze odds vs results patterns."""
    pairs = defaultdict(list)
    
    for m in matched_data:
        key = f"{m['home']} vs {m['away']}"
        pairs[key].append(m)
    
    analysis = {}
    
    for pair, matches in sorted(pairs.items()):
        n = len(matches)
        total_goals = [m['total_goals'] for m in matches]
        o15 = sum(1 for g in total_goals if g >= 2)
        o25 = sum(1 for g in total_goals if g >= 3)
        
        # Home odds analysis
        home_odds_list = [m.get('home_odds') for m in matches if m.get('home_odds')]
        avg_home_odds = sum(home_odds_list) / len(home_odds_list) if home_odds_list else 0
        
        # Odds buckets
        odds_buckets = defaultdict(lambda: {'total': 0, 'o15': 0, 'o25': 0, 'goals': []})
        for m in matches:
            oh = m.get('home_odds')
            if oh:
                bucket = round(oh * 4) / 4  # Bucket by 0.25
                odds_buckets[bucket]['total'] += 1
                odds_buckets[bucket]['o15'] += (1 if m['total_goals'] >= 2 else 0)
                odds_buckets[bucket]['o25'] += (1 if m['total_goals'] >= 3 else 0)
                odds_buckets[bucket]['goals'].append(m['total_goals'])
        
        # Compute hit rate per odds bucket
        odds_hit_rates = {}
        for ob, stats in sorted(odds_buckets.items()):
            if stats['total'] >= 3:  # Minimum sample
                hit_rate = stats['o15'] / stats['total']
                odds_hit_rates[ob] = {
                    'sample': stats['total'],
                    'o15_rate': round(hit_rate * 100, 1),
                    'avg_goals': round(sum(stats['goals']) / len(stats['goals']), 2)
                }
        
        analysis[pair] = {
            'matches': n,
            'o15_rate': round(o15 / n * 100, 1),
            'o25_rate': round(o25 / n * 100, 1),
            'avg_total_goals': round(sum(total_goals) / n, 2),
            'avg_home_odds': round(avg_home_odds, 3),
            'odds_hit_rates': odds_hit_rates,
            'sample_matches': len(matches),
        }
    
    return analysis

def find_mispricings(analysis):
    """Find pairs where pre-match odds consistently misprice the actual outcome."""
    mispricings = []
    
    for pair, stats in analysis.items():
        if stats['matches'] < 5:
            continue
        
        o15_rate = stats['o15_rate'] / 100.0
        avg_home_odds = stats.get('avg_home_odds', 0)
        
        if avg_home_odds > 0:
            # Implied probability from odds (without margin adjustment)
            implied_prob = 1.0 / avg_home_odds
            
            # True probability from actual results
            true_prob = o15_rate
            
            # Edge
            edge = true_prob - implied_prob
            
            if abs(edge) > 0.05:  # >5% edge
                mispricings.append({
                    'pair': pair,
                    'matches': stats['matches'],
                    'avg_home_odds': avg_home_odds,
                    'implied_prob': round(implied_prob * 100, 1),
                    'actual_o15_rate': round(true_prob * 100, 1),
                    'edge': round(edge * 100, 1),
                    'type': 'OVERPRICED' if edge < 0 else 'UNDERPRICED'
                })
    
    return sorted(mispricings, key=lambda x: abs(x['edge']), reverse=True)

# ---- MAIN ----
print("=" * 60)
print("ODDS vs FINITE STATE SPACE CORRELATION ANALYSIS")
print("=" * 60)

results, hist_conn = load_data()
conn = sqlite3.connect(RESULTS_DB)
conn.row_factory = sqlite3.Row

# Check what the verify_cluster_picks is looking at
print("\n=== VERIFY_CLUSTER_PICKS: Checking what seasons exist in results ===")
seasons = conn.execute("""
    SELECT season_name, season_id, MAX(match_day) as max_md, COUNT(*) as total_matches
    FROM results 
    GROUP BY season_name 
    ORDER BY season_name DESC 
    LIMIT 10
""").fetchall()
for s in seasons:
    print(f"  {s['season_name']:15s} md1-{s['max_md']:2d}  ({s['total_matches']} matches)")

# The cron is looking at VFLM 5113 — let's check if that's stale
print("\n=== Available pipeline_picks files ===")
import glob
picks_files = sorted(glob.glob('/home/ubuntu/faith-workspace/vfl-complete-data/signals/pipeline_picks_md*.json'))
for f in picks_files[-5:]:
    try:
        data = json.load(open(f))
        sid = data.get('season_id', '?')
        md = data.get('match_day', '?')
        print(f"  {f.split('/')[-1]:35s} season={sid} md={md}")
    except:
        pass

# Check from MSport API what the CURRENT season is
print("\n=== Current MSport MatchDay Info ===")
import sys
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire')
from services.common.msport_client import fetch_json, BASE_URL
md_info = fetch_json(f'{BASE_URL}/current/match/day/info')
if md_info:
    print(f"  Current: {md_info.get('seasonName')} MD{md_info.get('matchDay')} ({md_info.get('status')})")

# Build odds correlation using available data
# Since history.db has limited overlap, let's use what we have
print("\n=== ODDS vs RESULTS CORRELATION ===")

# First, check history.db for odds data that can enrich our analysis
hist_conn2 = sqlite3.connect(HISTORY_DB)
hist_conn2.row_factory = sqlite3.Row

# Get total count
total_matches = hist_conn2.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
with_home_odds = hist_conn2.execute("SELECT COUNT(*) FROM matches WHERE oh IS NOT NULL").fetchone()[0]
with_outcome = hist_conn2.execute("SELECT COUNT(*) FROM matches WHERE outcome IS NOT NULL").fetchone()[0]
print(f"History DB: {total_matches} matches, {with_home_odds} with home odds, {with_outcome} with outcomes")

# Get per-pair O1.5 from our results DB (which has scores)
print("\n=== PER-PAIR ANALYSIS (from vfl_results.db with scores) ===")
pair_o15 = {}
for r in conn.execute("""
    SELECT home_team, away_team, 
           COUNT(*) as n,
           SUM(CASE WHEN total_goals >= 2 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as o15_rate,
           AVG(total_goals) as avg_goals
    FROM results WHERE status = 3
    GROUP BY home_team, away_team
    HAVING n >= 10
    ORDER BY o15_rate ASC
""").fetchall():
    d = dict(r)
    pair_o15[f"{d['home_team']} vs {d['away_team']}"] = d

# Find the worst-performing pairs (traps from odds perspective)
worst = sorted(pair_o15.values(), key=lambda x: x['o15_rate'])[:15]
print("WORST 15 PAIRS (by O1.5 rate):")
for p in worst:
    print(f"  {p['home_team']:20s} vs {p['away_team']:20s}: O1.5={p['o15_rate']*100:.1f}%  avg={p['avg_goals']:.2f} goals  n={p['n']}")

best = sorted(pair_o15.values(), key=lambda x: x['o15_rate'], reverse=True)[:15]
print("\nBEST 15 PAIRS (by O1.5 rate):")
for p in best:
    print(f"  {p['home_team']:20s} vs {p['away_team']:20s}: O1.5={p['o15_rate']*100:.1f}%  avg={p['avg_goals']:.2f} goals  n={p['n']}")

# Team-level analysis
print("\n=== TEAM-LEVEL TRAP ANALYSIS ===")
team_o15 = defaultdict(list)
for pair, stats in pair_o15.items():
    h, _, a = pair.partition(' vs ')
    team_o15[h].append(stats['o15_rate'])
    team_o15[a].append(stats['o15_rate'])

team_avg = {t: round(sum(v)/len(v)*100, 1) for t, v in team_o15.items()}
print("Teams sorted by avg O1.5 rate (worst first):")
for t in sorted(team_avg, key=team_avg.get):
    print(f"  {t:20s}: avg O1.5 = {team_avg[t]:5.1f}%")

# Key insight: what makes a fixture a "trap"?
# A trap is when the ODDS say O1.5 is likely but the PAIR says it's not
# We don't have odds in results.db, but we have the PAIR-specific O1.5 rate
# The FiniteStateFilter already catches this.

# Additional insight: scoreline distribution by matchday phase
print("\n=== SCORELINE DISTRIBUTION BY MATCHDAY PHASE ===")
for phase_name, md_range in [('Early (1-10)', (1, 10)), ('Mid (11-20)', (11, 20)), ('Late (21-30)', (21, 30))]:
    rows = conn.execute("""
        SELECT COUNT(*) as n, 
               SUM(CASE WHEN total_goals >= 2 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as o15_rate,
               AVG(total_goals) as avg_goals,
               SUM(CASE WHEN total_goals >= 4 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as o35_rate
        FROM results WHERE status = 3 AND match_day BETWEEN ? AND ?
    """, (md_range[0], md_range[1])).fetchone()
    print(f"  {phase_name:20s}: n={rows['n']:5d}  O1.5={rows['o15_rate']*100:5.1f}%  O3.5={rows['o35_rate']*100:5.1f}%  avg={rows['avg_goals']:.2f}")

# Scoreline distribution by home/away first goal
print("\n=== MOST COMMON SCORELINES ===")
scorelines = conn.execute("""
    SELECT home_goals || ':' || away_goals as score, COUNT(*) as cnt
    FROM results WHERE status = 3
    GROUP BY score
    ORDER BY cnt DESC
    LIMIT 20
""").fetchall()
for s in scorelines:
    print(f"  {s['score']:>5s}: {s['cnt']:5d} ({s['cnt']/25257*100:.1f}%)")

print("\n=== DONE ===")
print(f"Analysis complete. {len(pair_o15)} pairs analyzed across {len(results)} matches.")
