#!/usr/bin/env python3
"""
VFL 4-LEG PARLAY SELECTOR & BACKTESTER
========================================
Strategy: Each matchday, pick the 4 highest-confidence legs
from the historical lock/dominance data and parlay them.
Backtest compound growth across 50+ seasons.

Confidence sources (in priority order):
  1. H2H Fixture Locks (≥75% dominance rate across seasons)
  2. Under 3.5 Goals — 73.6% historical hit rate (any fixture)
  3. Over 1.5 Goals  — 73.3% historical hit rate
  4. Home Win for top-tier dominance fixtures

For each matchday across all seasons:
  → Pick top 4 legs by confidence score
  → Simulate parlay payout at given odds
  → Track compound bankroll growth
"""

import psycopg2
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUTPUT_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/751aa9ef-b0a3-4429-8498-9c8a6b4df046"

print("=" * 70)
print("VFL 4-LEG PARLAY SELECTOR & COMPOUND BACKTEST")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

conn = psycopg2.connect(dbname='vfl_empire', user='ubuntu')

# ─────────────────────────────────────────────────────────────
# 1. LOAD ALL HISTORICAL RESULTS
# ─────────────────────────────────────────────────────────────
print("\n[1/5] Loading historical data...")

query = """
SELECT 
    s.season_name,
    md.matchday_number,
    r.home_team,
    r.away_team,
    r.home_goals,
    r.away_goals,
    r.total_goals
FROM vfl_results_v2 r
JOIN vfl_matchdays md ON r.matchday_id = md.id
JOIN vfl_seasons s ON md.season_id = s.id
WHERE r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL
ORDER BY s.season_name, md.matchday_number, r.home_team
"""
df = pd.read_sql(query, conn)
conn.close()

df['season_num'] = df['season_name'].str.extract(r'(\d+)').astype(int)
df = df.sort_values(['season_num', 'matchday_number', 'home_team']).reset_index(drop=True)

# Compute markets
df['over_15']  = (df['total_goals'] > 1.5).astype(int)
df['over_25']  = (df['total_goals'] > 2.5).astype(int)
df['under_35'] = (df['total_goals'] < 3.5).astype(int)
df['gg']       = ((df['home_goals'] > 0) & (df['away_goals'] > 0)).astype(int)
df['home_win'] = (df['home_goals'] > df['away_goals']).astype(int)
df['away_win'] = (df['home_goals'] < df['away_goals']).astype(int)
df['draw']     = (df['home_goals'] == df['away_goals']).astype(int)

print(f"  Loaded {len(df):,} matches | {df['season_num'].nunique()} seasons")

# ─────────────────────────────────────────────────────────────
# 2. BUILD H2H FIXTURE CONFIDENCE TABLE
# ─────────────────────────────────────────────────────────────
print("\n[2/5] Building fixture confidence table...")

# For each (home, away, matchday) triple, compute hit rates for each market
# using ONLY seasons BEFORE the current one (walk-forward, no lookahead)

seasons_sorted = sorted(df['season_num'].unique())

# Pre-compute H2H stats for all pairs and markets
# We'll use a rolling approach: train on first 60% of seasons, test on last 40%
split_idx = int(len(seasons_sorted) * 0.40)
train_seasons = set(seasons_sorted[:split_idx])
test_seasons  = set(seasons_sorted[split_idx:])

df_train = df[df['season_num'].isin(train_seasons)]
df_test  = df[df['season_num'].isin(test_seasons)]

print(f"  Train: {len(train_seasons)} seasons | Test: {len(test_seasons)} seasons")

# Build fixture-level confidence for each market from training data
MARKETS = {
    'over_15':  {'name': 'Over 1.5 Goals',  'typical_odds': 1.25},
    'under_35': {'name': 'Under 3.5 Goals', 'typical_odds': 1.28},
    'over_25':  {'name': 'Over 2.5 Goals',  'typical_odds': 1.85},
    'gg':       {'name': 'BTTS Yes',        'typical_odds': 1.90},
    'home_win': {'name': 'Home Win',        'typical_odds': 2.10},
    'away_win': {'name': 'Away Win',        'typical_odds': 2.80},
}

fixture_confidence = {}  # (home, away, md, market) -> hit_rate, n

for (ht, at, md), grp in df_train.groupby(['home_team', 'away_team', 'matchday_number']):
    n = len(grp)
    if n < 3:
        continue
    for mkt, minfo in MARKETS.items():
        rate = grp[mkt].mean()
        fixture_confidence[(ht, at, md, mkt)] = {'rate': rate, 'n': n}

print(f"  Built {len(fixture_confidence):,} fixture-market confidence entries")

# Global market rates (league baseline from training data)
global_rates = {mkt: df_train[mkt].mean() for mkt in MARKETS}
print(f"  Global market rates: {json.dumps({k: round(v,3) for k,v in global_rates.items()})}")

# ─────────────────────────────────────────────────────────────
# 3. PARLAY BACKTEST
# ─────────────────────────────────────────────────────────────
print("\n[3/5] Running parlay backtest...")

MIN_CONFIDENCE  = 0.65   # minimum hit rate to consider a leg
MIN_N           = 5      # minimum historical meetings to trust
TOP_N_LEGS      = 4      # legs per parlay
STAKE_FRACTION  = 0.02   # 2% of bankroll per matchday parlay
STARTING_BANK   = 1000.0 # starting bankroll

bankroll = STARTING_BANK
bankroll_history = []
matchday_results = []

# Walk through test seasons, matchday by matchday
test_df_sorted = df_test.sort_values(['season_num', 'matchday_number'])

for (season, md), md_group in test_df_sorted.groupby(['season_num', 'matchday_number']):
    fixtures_this_md = md_group.to_dict('records')
    
    # Score every fixture-market combination for this matchday
    candidates = []
    for fix in fixtures_this_md:
        ht, at = fix['home_team'], fix['away_team']
        for mkt, minfo in MARKETS.items():
            key = (ht, at, md, mkt)
            
            # Get confidence: fixture-specific if available, else global
            if key in fixture_confidence:
                conf_data = fixture_confidence[key]
                rate = conf_data['rate']
                n    = conf_data['n']
                # Bayesian shrinkage toward global rate
                global_r = global_rates[mkt]
                rate_shrunk = (rate * n + global_r * 8) / (n + 8)
            else:
                rate_shrunk = global_rates[mkt]
                n = 0
            
            if rate_shrunk < MIN_CONFIDENCE or n < MIN_N:
                continue
            
            candidates.append({
                'home': ht, 'away': at,
                'market': mkt,
                'market_name': minfo['name'],
                'odds': minfo['typical_odds'],
                'confidence': rate_shrunk,
                'n': n,
                'actual_result': fix[mkt],  # 1=hit, 0=miss
                'season': season,
                'matchday': md,
            })
    
    if not candidates:
        continue
    
    # Sort by confidence descending, pick top N legs
    # Ensure diversity: max 1 leg per fixture to avoid correlated bets
    candidates.sort(key=lambda x: x['confidence'], reverse=True)
    
    selected = []
    used_fixtures = set()
    for c in candidates:
        fix_key = (c['home'], c['away'])
        if fix_key not in used_fixtures:
            selected.append(c)
            used_fixtures.add(fix_key)
        if len(selected) == TOP_N_LEGS:
            break
    
    if len(selected) < TOP_N_LEGS:
        # Fill remaining slots allowing same fixture, different market
        for c in candidates:
            if c not in selected:
                selected.append(c)
            if len(selected) == TOP_N_LEGS:
                break
    
    if len(selected) < 2:  # need at least 2 legs
        continue
    
    # Compute parlay
    parlay_odds = np.prod([c['odds'] for c in selected])
    all_hit = all(c['actual_result'] == 1 for c in selected)
    n_hit = sum(c['actual_result'] for c in selected)
    
    stake = bankroll * STAKE_FRACTION
    stake = min(stake, bankroll * 0.05)  # hard cap 5% of bank
    
    if all_hit:
        profit = stake * (parlay_odds - 1)
        bankroll += profit
        outcome = 'WIN'
    else:
        profit = -stake
        bankroll += profit
        outcome = 'LOSS'
    
    bankroll = max(bankroll, 1.0)  # don't go below 1
    
    matchday_results.append({
        'season': season,
        'matchday': md,
        'n_legs': len(selected),
        'parlay_odds': parlay_odds,
        'avg_confidence': np.mean([c['confidence'] for c in selected]),
        'n_hit': n_hit,
        'all_hit': int(all_hit),
        'stake': stake,
        'profit': profit,
        'bankroll': bankroll,
        'outcome': outcome,
        'legs': [(c['home'], c['away'], c['market_name'], c['confidence']) for c in selected],
    })
    
    bankroll_history.append(bankroll)

results_df = pd.DataFrame(matchday_results)
print(f"\n  Matchdays tested: {len(results_df):,}")
print(f"  Parlays won: {results_df['all_hit'].sum():,} ({results_df['all_hit'].mean()*100:.1f}%)")
print(f"  Starting bankroll: £{STARTING_BANK:,.0f}")
print(f"  Final bankroll:    £{bankroll:,.2f}")
print(f"  Net profit:        £{bankroll - STARTING_BANK:,.2f}")
print(f"  ROI:               {(bankroll/STARTING_BANK - 1)*100:.1f}%")
print(f"  Avg parlay odds:   {results_df['parlay_odds'].mean():.2f}x")
print(f"  Avg confidence/leg:{results_df['avg_confidence'].mean()*100:.1f}%")

# By n_hit breakdown
print(f"\n  Legs correct distribution (out of {TOP_N_LEGS}):")
for i in range(TOP_N_LEGS + 1):
    cnt = (results_df['n_hit'] == i).sum()
    pct = cnt / len(results_df) * 100
    bar = '█' * int(pct / 2)
    print(f"    {i}/{TOP_N_LEGS} correct: {cnt:4d} ({pct:.1f}%) {bar}")

# ─────────────────────────────────────────────────────────────
# 4. WHAT IF WE USE ONLY LOCKS (≥75%) AS LEGS?
# ─────────────────────────────────────────────────────────────
print("\n[4/5] Testing LOCK-ONLY parlay (≥75% confidence legs only)...")

bankroll_lock = STARTING_BANK
lock_results = []

for (season, md), md_group in test_df_sorted.groupby(['season_num', 'matchday_number']):
    fixtures_this_md = md_group.to_dict('records')
    
    lock_candidates = []
    for fix in fixtures_this_md:
        ht, at = fix['home_team'], fix['away_team']
        for mkt, minfo in MARKETS.items():
            key = (ht, at, md, mkt)
            if key in fixture_confidence:
                conf_data = fixture_confidence[key]
                rate = conf_data['rate']
                n    = conf_data['n']
                global_r = global_rates[mkt]
                rate_shrunk = (rate * n + global_r * 8) / (n + 8)
                
                if rate_shrunk >= 0.75 and n >= 8:  # strict lock threshold
                    lock_candidates.append({
                        'home': ht, 'away': at,
                        'market': mkt,
                        'market_name': minfo['name'],
                        'odds': minfo['typical_odds'],
                        'confidence': rate_shrunk,
                        'n': n,
                        'actual_result': fix[mkt],
                    })
    
    if len(lock_candidates) < 2:
        continue
    
    lock_candidates.sort(key=lambda x: x['confidence'], reverse=True)
    
    # Diverse selection
    selected = []
    used_fix = set()
    for c in lock_candidates:
        fk = (c['home'], c['away'])
        if fk not in used_fix and len(selected) < 4:
            selected.append(c)
            used_fix.add(fk)
    
    if len(selected) < 2:
        continue
    
    parlay_odds = np.prod([c['odds'] for c in selected])
    all_hit = all(c['actual_result'] == 1 for c in selected)
    n_hit = sum(c['actual_result'] for c in selected)
    
    stake = bankroll_lock * STAKE_FRACTION
    stake = min(stake, bankroll_lock * 0.05)
    
    if all_hit:
        profit = stake * (parlay_odds - 1)
        bankroll_lock += profit
    else:
        profit = -stake
        bankroll_lock += profit
    
    bankroll_lock = max(bankroll_lock, 1.0)
    
    lock_results.append({
        'season': season, 'matchday': md,
        'n_legs': len(selected),
        'parlay_odds': parlay_odds,
        'avg_confidence': np.mean([c['confidence'] for c in selected]),
        'n_hit': n_hit,
        'all_hit': int(all_hit),
        'profit': profit,
        'bankroll': bankroll_lock,
    })

lock_df = pd.DataFrame(lock_results) if lock_results else pd.DataFrame()
if len(lock_df) > 0:
    print(f"  Matchdays with lock parlays: {len(lock_df):,}")
    print(f"  Lock parlay win rate: {lock_df['all_hit'].mean()*100:.1f}%")
    print(f"  Final bankroll (locks only): £{bankroll_lock:,.2f}")
    print(f"  ROI (locks only): {(bankroll_lock/STARTING_BANK-1)*100:.1f}%")

# ─────────────────────────────────────────────────────────────
# 5. CHARTS
# ─────────────────────────────────────────────────────────────
print("\n[5/5] Generating charts...")

fig, axes = plt.subplots(2, 2, figsize=(18, 12))
fig.suptitle(f'VFL 4-Leg Parlay Compound Backtest\n'
             f'Start £{STARTING_BANK:,.0f} | {len(test_seasons)} seasons tested',
             fontsize=15, fontweight='bold')

# Chart 1: Compound bankroll growth
ax1 = axes[0, 0]
seasons_x = results_df['season'].values
ax1.semilogy(range(len(bankroll_history)), bankroll_history,
             color='#2196F3', lw=1.5, alpha=0.8, label='4-leg parlay')
if len(lock_df) > 0:
    ax1.semilogy(range(len(lock_df)), lock_df['bankroll'].values,
                 color='#4CAF50', lw=1.8, label='Lock-only parlay')
ax1.axhline(STARTING_BANK, color='red', linestyle='--', alpha=0.6, label=f'Start £{STARTING_BANK:,.0f}')
ax1.set_xlabel('Matchday (chronological)')
ax1.set_ylabel('Bankroll £ (log scale)')
ax1.set_title('Compound Bankroll Growth (Log Scale)')
ax1.legend(fontsize=9)
ax1.grid(True, alpha=0.3)

# Chart 2: Parlay win rate by avg confidence
ax2 = axes[0, 1]
results_df['conf_band'] = pd.cut(results_df['avg_confidence'],
                                   bins=[0.60, 0.65, 0.70, 0.75, 0.80, 1.0],
                                   labels=['60-65%','65-70%','70-75%','75-80%','80%+'])
conf_win = results_df.groupby('conf_band', observed=True).agg(
    win_rate=('all_hit','mean'),
    n=('all_hit','count')
).reset_index()
bars = ax2.bar(conf_win['conf_band'].astype(str), conf_win['win_rate'],
               color='#FF9800', alpha=0.85, edgecolor='white')
ax2.set_xlabel('Avg Leg Confidence Band')
ax2.set_ylabel('Parlay Win Rate')
ax2.set_title('Parlay Win Rate by Confidence Level')
for bar in bars:
    ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.005,
             f'{bar.get_height():.3f}', ha='center', fontsize=10, fontweight='bold')

# Chart 3: Hit distribution (how many legs correct per parlay)
ax3 = axes[1, 0]
hit_counts = results_df['n_hit'].value_counts().sort_index()
colors3 = ['#F44336','#FF9800','#FFC107','#8BC34A','#4CAF50']
bars3 = ax3.bar(hit_counts.index.astype(str), hit_counts.values,
                color=colors3[:len(hit_counts)], alpha=0.85, edgecolor='white')
ax3.set_xlabel(f'Legs Correct (out of {TOP_N_LEGS})')
ax3.set_ylabel('Frequency')
ax3.set_title(f'How Many Legs Hit Per Parlay\n(Need ALL {TOP_N_LEGS} for payout)')
for bar in bars3:
    pct = bar.get_height() / len(results_df) * 100
    ax3.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
             f'{pct:.1f}%', ha='center', fontsize=10, fontweight='bold')

# Chart 4: Monthly P&L
ax4 = axes[1, 1]
results_df['season_group'] = results_df['season'] // 10 * 10
pnl_by_group = results_df.groupby('season_group')['profit'].sum()
bar_colors4 = ['#4CAF50' if v >= 0 else '#F44336' for v in pnl_by_group.values]
ax4.bar(pnl_by_group.index, pnl_by_group.values, color=bar_colors4, alpha=0.85, edgecolor='white')
ax4.axhline(0, color='black', lw=1)
ax4.set_xlabel('Season Group')
ax4.set_ylabel('Net P&L (units)')
ax4.set_title('P&L by Season Block (10-season groups)')

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'parlay_compound_backtest.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved → {chart_path}")

# ─────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────
report_path = os.path.join(OUTPUT_DIR, 'parlay_backtest_report.md')
with open(report_path, 'w') as f:
    f.write("# VFL 4-Leg Parlay Compound Backtest Report\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    f.write(f"**Test Seasons:** {len(test_seasons)} seasons  \n")
    f.write(f"**Starting Bankroll:** £{STARTING_BANK:,.0f}  \n\n")

    f.write("## Strategy\n\n")
    f.write(f"- Pick **{TOP_N_LEGS} legs** per matchday (max 1 per fixture)\n")
    f.write(f"- Minimum confidence threshold: **{MIN_CONFIDENCE*100:.0f}%**\n")
    f.write(f"- Stake: **{STAKE_FRACTION*100:.0f}% of bankroll** per matchday\n")
    f.write(f"- Selection: highest H2H historical hit rate first\n\n")

    f.write("## Results — 4-Leg Parlay\n\n")
    f.write(f"| Metric | Value |\n|--------|-------|\n")
    f.write(f"| Matchdays tested | {len(results_df):,} |\n")
    f.write(f"| Parlay win rate | **{results_df['all_hit'].mean()*100:.1f}%** |\n")
    f.write(f"| Starting bankroll | £{STARTING_BANK:,.0f} |\n")
    f.write(f"| Final bankroll | **£{bankroll:,.2f}** |\n")
    f.write(f"| Net profit | **£{bankroll-STARTING_BANK:,.2f}** |\n")
    f.write(f"| Total ROI | **{(bankroll/STARTING_BANK-1)*100:.1f}%** |\n")
    f.write(f"| Avg parlay odds | {results_df['parlay_odds'].mean():.2f}x |\n")
    f.write(f"| Avg confidence/leg | {results_df['avg_confidence'].mean()*100:.1f}% |\n\n")

    f.write("## Results — Lock-Only Parlay (≥75% confidence)\n\n")
    if len(lock_df) > 0:
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Matchdays with locks | {len(lock_df):,} |\n")
        f.write(f"| Lock parlay win rate | **{lock_df['all_hit'].mean()*100:.1f}%** |\n")
        f.write(f"| Final bankroll | **£{bankroll_lock:,.2f}** |\n")
        f.write(f"| Total ROI | **{(bankroll_lock/STARTING_BANK-1)*100:.1f}%** |\n\n")

    f.write("## Legs Correct Distribution\n\n")
    f.write(f"| Legs Correct | Count | % of Parlays |\n|---|---|---|\n")
    for i in range(TOP_N_LEGS + 1):
        cnt = (results_df['n_hit'] == i).sum()
        f.write(f"| {i}/{TOP_N_LEGS} | {cnt:,} | {cnt/len(results_df)*100:.1f}% |\n")

    f.write("\n## Top Confirmed Lock Fixtures (≥75% historical dominance)\n\n")
    f.write("| Home | Away | Market | Confidence | n |\n|------|------|--------|-----------|---|\n")
    top_locks = sorted(
        [(k, v) for k, v in fixture_confidence.items() if v['rate'] >= 0.75 and v['n'] >= 10],
        key=lambda x: x[1]['rate'], reverse=True
    )[:20]
    for (ht, at, md, mkt), data in top_locks:
        f.write(f"| {ht} | {at} | {MARKETS[mkt]['name']} | {data['rate']*100:.1f}% | {data['n']} |\n")

print(f"  Report → {report_path}")

print("\n" + "=" * 70)
print("PARLAY BACKTEST COMPLETE")
print("=" * 70)
print(f"\n  Strategy: 4-leg parlay | 2% stake | ≥65% confidence legs")
print(f"  Matchdays tested: {len(results_df):,}")
print(f"  Parlay win rate:  {results_df['all_hit'].mean()*100:.1f}%")
print(f"  Starting bank:    £{STARTING_BANK:,.0f}")
print(f"  Final bank:       £{bankroll:,.2f}")
print(f"  ROI:              {(bankroll/STARTING_BANK-1)*100:.1f}%")
if len(lock_df) > 0:
    print(f"\n  Lock-only parlay win rate: {lock_df['all_hit'].mean()*100:.1f}%")
    print(f"  Lock-only final bank:      £{bankroll_lock:,.2f}")
