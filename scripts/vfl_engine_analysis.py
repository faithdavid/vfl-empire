#!/usr/bin/env python3
"""VFL Engine Structure — Fixed queries + raw verification."""
import numpy as np, pandas as pd, sqlite3, json, warnings
from collections import defaultdict, Counter
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.estimators import HillClimbSearch
from pgmpy.parameter_estimator import DiscreteBayesianEstimator
from pgmpy.inference import VariableElimination
warnings.filterwarnings('ignore')

def load():
    rows=[]
    def nt(t): return t.strip().title() if t else ''
    def oc(o):
        o=str(o).upper().strip()
        return 'H' if o in ('HOME','H','1') else 'D' if o in ('DRAW','D','X') else 'A' if o in ('AWAY','A','2') else None
    conn=sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
    for r in conn.execute("SELECT season,day,home,away,oh,od,oa,outcome FROM matches WHERE oh>0 AND od>0 AND oa>0 AND outcome IS NOT NULL AND outcome!=''"):
        o=oc(r[7])
        if o: rows.append({'season':r[0],'md':r[1],'home':nt(r[2]),'away':nt(r[3]),'oh':float(r[4]),'od':float(r[5]),'oa':float(r[6]),'outcome':o})
    conn.close()
    conn2=sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/sovereign.db')
    exist=set((m['season'],m['md'],m['home'],m['away']) for m in rows)
    for r in conn2.execute("SELECT season_id,match_day,home_team,away_team,odds_h,odds_d,odds_a,outcome FROM master_ledger WHERE odds_h>0 AND odds_d>0 AND odds_a>0 AND outcome IS NOT NULL AND outcome!=''"):
        o=oc(r[7])
        if o and (r[0],r[1],nt(r[2]),nt(r[3])) not in exist:
            rows.append({'season':r[0],'md':r[1],'home':nt(r[2]),'away':nt(r[3]),'oh':float(r[4]),'od':float(r[5]),'oa':float(r[6]),'outcome':o})
    conn2.close()
    return rows

matches = load()
print(f"Loaded {len(matches)} matches\n")

# Build DataFrame
team_odds = defaultdict(list)
for m in matches:
    team_odds[m['home']].append(m['oh'])
    team_odds[m['away']].append(m['oa'])
tiers = {}
for t, o in team_odds.items():
    a = np.mean(o)
    tiers[t] = 'ELITE' if a<1.8 else 'STRONG' if a<2.5 else 'MID' if a<3.5 else 'WEAK' if a<5.0 else 'UNDER'

rows = []
for m in matches:
    oh, od, oa = m['oh'], m['od'], m['oa']
    ti = 1/oh + 1/od + 1/oa
    ph, pd_, pa = 1/oh/ti, 1/od/ti, 1/oa/ti
    mo = min(oh, od, oa)
    fav = 'H_FAV' if mo==oh else 'D_FAV' if mo==od else 'A_FAV'
    fp = max(ph, pd_, pa)
    strength = 'HEAVY' if fp>=0.60 else 'CLEAR' if fp>=0.50 else 'SLIGHT' if fp>=0.40 else 'EVEN'
    dr = pd_ / ((ph+pa)/2)
    draw_z = 'HIGH_D' if dr>=1.15 else 'NORM_D' if dr>=0.90 else 'LOW_D'
    spread = max(oh,od,oa)-min(oh,od,oa)
    tight = 'OPEN' if spread>=3.0 else 'CLOSE'
    rows.append({'fav':fav,'str':strength,'draw':draw_z,'tight':tight,
                 'ht':tiers.get(m['home'],'MID'),'at':tiers.get(m['away'],'MID'),
                 'md':m['md'],'outcome':m['outcome']})
df = pd.DataFrame(rows)

# RAW CONDITIONAL PROBABILITIES (direct from data — no BN needed)
print("=== RAW CONDITIONAL PROBABILITIES (from data) ===")

print("\n1. P(outcome | fav_type):")
for fav_val in ['H_FAV', 'A_FAV', 'D_FAV']:
    subset = df[df['fav']==fav_val]
    counts = subset['outcome'].value_counts()
    total = len(subset)
    h = counts.get('H',0)/total
    d = counts.get('D',0)/total
    a = counts.get('A',0)/total
    print(f"   {fav_val:8s} (n={total:4d}) → H:{h:.3f} D:{d:.3f} A:{a:.3f}")

print("\n2. P(outcome | fav_type, tightness):")
for fav_val in ['H_FAV', 'A_FAV']:
    for t in ['CLOSE', 'OPEN']:
        subset = df[(df['fav']==fav_val) & (df['tight']==t)]
        if len(subset) < 5: continue
        counts = subset['outcome'].value_counts()
        total = len(subset)
        h = counts.get('H',0)/total
        d = counts.get('D',0)/total
        a = counts.get('A',0)/total
        print(f"   {fav_val:8s} + {t:5s} (n={total:4d}) → H:{h:.3f} D:{d:.3f} A:{a:.3f}")

print("\n3. P(outcome | strength):")
for s in ['HEAVY', 'CLEAR', 'SLIGHT', 'EVEN']:
    subset = df[df['str']==s]
    counts = subset['outcome'].value_counts()
    total = len(subset)
    h = counts.get('H',0)/total
    d = counts.get('D',0)/total
    a = counts.get('A',0)/total
    print(f"   {s:8s} (n={total:4d}) → H:{h:.3f} D:{d:.3f} A:{a:.3f}")

print("\n4. P(outcome | tightness):")
for t in ['CLOSE', 'OPEN']:
    subset = df[df['tight']==t]
    counts = subset['outcome'].value_counts()
    total = len(subset)
    h = counts.get('H',0)/total
    d = counts.get('D',0)/total
    a = counts.get('A',0)/total
    print(f"   {t:5s} (n={total:4d}) → H:{h:.3f} D:{d:.3f} A:{a:.3f}")

print("\n5. P(outcome | draw_zone):")
for dz in ['HIGH_D', 'NORM_D', 'LOW_D']:
    subset = df[df['draw']==dz]
    if len(subset) < 5: continue
    counts = subset['outcome'].value_counts()
    total = len(subset)
    h = counts.get('H',0)/total
    d = counts.get('D',0)/total
    a = counts.get('A',0)/total
    print(f"   {dz:8s} (n={total:4d}) → H:{h:.3f} D:{d:.3f} A:{a:.3f}")

# THE KEY FINDING: Where does the engine most favor draws?
print("\n=== WHERE THE ENGINE PRODUCES DRAWS ===")
# Group by (fav, tight, str) and find highest draw rates
grouped = df.groupby(['fav', 'tight', 'str'])['outcome'].value_counts(normalize=True).reset_index()
grouped.columns = ['fav', 'tight', 'str', 'outcome', 'pct']
draw_groups = grouped[grouped['outcome']=='D'].sort_values('pct', ascending=False)
print("   Conditions producing highest draw rates:")
for _, r in draw_groups.head(10).iterrows():
    n = len(df[(df['fav']==r['fav'])&(df['tight']==r['tight'])&(df['str']==r['str'])])
    print(f"   fav={r['fav']:8s} tight={r['tight']:5s} str={r['str']:8s} → DRAW: {r['pct']:.1%} (n={n})")

# Condition for HOME FAVORITE LOSS (predicted H, actual A)
print("\n=== HOME FAVORITE LOSS CONDITIONS ===")
# When fav=H_FAV and outcome=A, what were the conditions?
home_loss = df[(df['fav']=='H_FAV') & (df['outcome']=='A')]
print(f"   Home fav that LOST: {len(home_loss)} matches")
print(f"   Tightness distribution when home fav loses:")
print(f"     {home_loss['tight'].value_counts().to_dict()}")
print(f"   Strength distribution when home fav loses:")
print(f"     {home_loss['str'].value_counts(normalize=True).to_dict()}")

# Condition for DRAW SURPRISE (predicted H/A, actual D)
print("\n=== DRAW SURPRISE CONDITIONS ===")
draw_surprise = df[(df['fav'].isin(['H_FAV','A_FAV'])) & (df['outcome']=='D')]
print(f"   Fav that DREW: {len(draw_surprise)} matches")
print(f"   Draw zone distribution when fav draws:")
print(f"     {draw_surprise['draw'].value_counts().to_dict()}")
print(f"   Strength distribution when fav draws:")
print(f"     {draw_surprise['str'].value_counts(normalize=True).to_dict()}")

# The engine's key rule: what combination most predicts each outcome?
print("\n=== ENGINE'S PREDICTIVE SIGNATURES ===")
for outcome in ['H', 'D', 'A']:
    sub = df[df['outcome']==outcome].groupby(['fav','tight','str']).size().reset_index(name='count')
    sub = sub.sort_values('count', ascending=False)
    top = sub.head(3)
    total_outcome = len(df[df['outcome']==outcome])
    print(f"\n   Most common conditions for {outcome} ({total_outcome} total):")
    for _, r in top.iterrows():
        pct = r['count']/total_outcome
        print(f"     fav={r['fav']:8s} tight={r['tight']:5s} str={r['str']:8s} → {r['count']:4d} ({pct:.1%})")
