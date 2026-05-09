#!/usr/bin/env python3
"""
VFL Engine Structure Discovery — Final
========================================
Uses Bayesian Network structure learning (Hattrick paper method)
to discover the VFL engine's hidden parameter dependencies.

Output: The engine's architecture + probability distributions
"""
import numpy as np, pandas as pd, sqlite3, json, warnings
from collections import defaultdict
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.estimators import HillClimbSearch
from pgmpy.parameter_estimator import DiscreteBayesianEstimator
from pgmpy.inference import VariableElimination

warnings.filterwarnings('ignore')

# Load data
def load():
    rows = []
    def nt(t): return t.strip().title() if t else ''
    def oc(o):
        o=str(o).upper().strip()
        if o in ('HOME','H','1'): return 'H'
        if o in ('DRAW','D','X'): return 'D'
        if o in ('AWAY','A','2'): return 'A'
        return None
    
    conn=sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
    for r in conn.execute("SELECT season,day,home,away,oh,od,oa,outcome FROM matches WHERE oh>0 AND od>0 AND oa>0 AND outcome IS NOT NULL AND outcome!=''"):
        o=oc(r[7]); 
        if o: rows.append({'season':r[0],'md':r[1],'home':nt(r[2]),'away':nt(r[3]),'oh':float(r[4]),'od':float(r[5]),'oa':float(r[6]),'outcome':o})
    conn.close()
    conn2=sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/sovereign.db')
    exist=set((m['season'],m['md'],m['home'],m['away']) for m in rows)
    for r in conn2.execute("SELECT season_id,match_day,home_team,away_team,odds_h,odds_d,odds_a,outcome FROM master_ledger WHERE odds_h>0 AND odds_d>0 AND odds_a>0 AND outcome IS NOT NULL AND outcome!=''"):
        o=oc(r[7]);
        if o and (r[0],r[1],nt(r[2]),nt(r[3])) not in exist:
            rows.append({'season':r[0],'md':r[1],'home':nt(r[2]),'away':nt(r[3]),'oh':float(r[4]),'od':float(r[5]),'oa':float(r[6]),'outcome':o})
    conn2.close()
    return rows

matches = load()
print(f"Loaded {len(matches)} matches\n")

# Build discrete features
def make_features(ms):
    # Compute team tiers from average odds
    team_odds = defaultdict(list)
    for m in ms:
        team_odds[m['home']].append(m['oh'])
        team_odds[m['away']].append(m['oa'])
    tiers = {}
    for t, odds in team_odds.items():
        a = np.mean(odds)
        if a < 1.8: tiers[t] = 'ELITE'
        elif a < 2.5: tiers[t] = 'STRONG'
        elif a < 3.5: tiers[t] = 'MID'
        elif a < 5.0: tiers[t] = 'WEAK'
        else: tiers[t] = 'UNDER'
    
    rows = []
    for m in ms:
        oh, od, oa = m['oh'], m['od'], m['oa']
        ti = 1/oh + 1/od + 1/oa
        ph, pd_, pa = 1/oh/ti, 1/od/ti, 1/oa/ti
        
        # Odds favorite type
        mo = min(oh, od, oa)
        fav = 'H_FAV' if mo==oh else 'D_FAV' if mo==od else 'A_FAV'
        
        # Favorite strength
        fp = max(ph, pd_, pa)
        strength = 'HEAVY' if fp>=0.60 else 'CLEAR' if fp>=0.50 else 'SLIGHT' if fp>=0.40 else 'EVEN'
        
        # Draw zone
        dr = pd_ / ((ph+pa)/2)
        draw_z = 'HIGH_D' if dr>=1.15 else 'NORM_D' if dr>=0.90 else 'LOW_D'
        
        # Shortened variables to reduce state space
        spread = max(oh,od,oa)-min(oh,od,oa)
        tight = 'OPEN' if spread>=3.0 else 'CLOSE'
        
        home_t = tiers.get(m['home'], 'MID')
        away_t = tiers.get(m['away'], 'MID')
        
        rows.append({
            'fav': fav,
            'str': strength,
            'draw': draw_z,
            'tight': tight,
            'ht': home_t,
            'at': away_t,
            'md_phase': 'EARLY' if m['md']<=10 else 'MID' if m['md']<=20 else 'LATE',
            'outcome': m['outcome'],
        })
    return pd.DataFrame(rows)

df = make_features(matches)
print(f"Features: {df.shape[1]-1} variables, {df.shape[0]} rows")
for c in df.columns:
    if c != 'outcome':
        print(f"  {c}: {sorted(df[c].unique())}")

print("\n=== DISCOVERING ENGINE STRUCTURE ===")
hc = HillClimbSearch(df)
best = hc.estimate(scoring_method='bic-d', max_indegree=3, max_iter=20000)

print(f"\nLearned {len(best.edges())} parameter dependencies:")
edges_by_target = defaultdict(list)
for a, b in best.edges():
    edges_by_target[b].append(a)
for target, parents in sorted(edges_by_target.items()):
    print(f"  {target:10s} ← {', '.join(parents)}")

# Fit parameters
model = DiscreteBayesianNetwork(best.edges())
model.fit(df, estimator=DiscreteBayesianEstimator(prior_type='BDeu', equivalent_sample_size=10))

print("\n=== ENGINE'S PROBABILITY DISTRIBUTIONS (CPDs) ===")
infer = VariableElimination(model)

# Key queries - how does the engine weight outcomes?
print("\n1. Odds Favorite Type → Outcome")
for ftype in ['H_FAV', 'A_FAV', 'D_FAV']:
    q = infer.query(['outcome'], evidence={'fav': ftype})
    print(f"   {ftype:8s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")

print("\n2. Favorite Strength → Outcome")
for s in ['HEAVY', 'CLEAR', 'SLIGHT', 'EVEN']:
    q = infer.query(['outcome'], evidence={'str': s})
    print(f"   {s:8s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")

print("\n3. Draw Zone → Outcome")
for dz in ['HIGH_D', 'NORM_D', 'LOW_D']:
    if dz in df['draw'].unique():
        q = infer.query(['outcome'], evidence={'draw': dz})
        print(f"   {dz:8s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")

print("\n4. Match Tightness → Outcome")
for t in ['OPEN', 'CLOSE']:
    q = infer.query(['outcome'], evidence={'tight': t})
    print(f"   {t:8s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")

print("\n5. MD Phase → Outcome")
for mp in ['EARLY', 'MID', 'LATE']:
    q = infer.query(['outcome'], evidence={'md_phase': mp})
    print(f"   {mp:8s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")

# The key insight: QUERY for DRAW conditions
print("\n=== WHEN DOES THE ENGINE PRODUCE DRAWS? ===")
# Best draw conditions
best_draw = infer.query(['outcome'], evidence={'draw': 'HIGH_D', 'tight': 'CLOSE', 'str': 'EVEN'})
print(f"   Even match + close + high draw odds: → H:{best_draw.values[0]:.3f} D:{best_draw.values[1]:.3f} A:{best_draw.values[2]:.3f}")

worst_draw = infer.query(['outcome'], evidence={'str': 'HEAVY', 'tight': 'OPEN'})
print(f"   Heavy fav + open spread:              → H:{worst_draw.values[0]:.3f} D:{worst_draw.values[1]:.3f} A:{worst_draw.values[2]:.3f}")

print("\n=== KEY FINDING: Draw probability by conditions ===")
for s in ['HEAVY', 'CLEAR', 'SLIGHT', 'EVEN']:
    for dz in ['HIGH_D', 'NORM_D', 'LOW_D']:
        for t in ['CLOSE', 'OPEN']:
            try:
                q = infer.query(['outcome'], evidence={'str': s, 'draw': dz, 'tight': t})
                print(f"   str={s:6s} draw={dz:7s} tight={t:5s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")
            except: pass
