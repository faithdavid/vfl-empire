#!/usr/bin/env python3
"""
VFL EXPANDED LOCK TABLE — Finding 20+ Stakes Per Season
=========================================================
Expands dominant fixture discovery from 75% to lower thresholds
to find enough qualifying fixtures for 20+ stakes per season.
Then backtests the single-bet compounding strategy.
"""

import psycopg2
import pandas as pd
import numpy as np
import os
from datetime import datetime
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUTPUT_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/751aa9ef-b0a3-4429-8498-9c8a6b4df046"

print("=" * 70)
print("VFL EXPANDED LOCK TABLE — 20+ STAKES PER SEASON")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

conn = psycopg2.connect(dbname='vfl_empire', user='ubuntu')
query = """
SELECT s.season_name, md.matchday_number, r.home_team, r.away_team,
       r.home_goals, r.away_goals, r.total_goals
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
df['over_15']  = (df['total_goals'] > 1.5).astype(int)
df['under_35'] = (df['total_goals'] < 3.5).astype(int)
df['home_win'] = (df['home_goals'] > df['away_goals']).astype(int)

seasons_sorted = sorted(df['season_num'].unique())
split_idx = int(len(seasons_sorted) * 0.40)
train_seasons = set(seasons_sorted[:split_idx])
test_seasons  = set(seasons_sorted[split_idx:])
df_train = df[df['season_num'].isin(train_seasons)]
df_test  = df[df['season_num'].isin(test_seasons)]

print(f"  {len(df):,} matches | Train: {len(train_seasons)}s | Test: {len(test_seasons)}s")

# ─────────────────────────────────────────────────────────────
# 1. DISCOVER ALL DOMINANT FIXTURES AT MULTIPLE THRESHOLDS
# ─────────────────────────────────────────────────────────────
print("\n[1/4] Discovering all dominant H2H fixtures from training data...")

fixture_hw_rates = {}
for (ht, at), grp in df_train.groupby(['home_team', 'away_team']):
    n = len(grp)
    if n < 10:
        continue
    hw_rate = grp['home_win'].mean()
    o15_rate = grp['over_15'].mean()
    u35_rate = grp['under_35'].mean()
    fixture_hw_rates[(ht, at)] = {
        'hw_rate': hw_rate,
        'o15_rate': o15_rate,
        'u35_rate': u35_rate,
        'n': n
    }

# Show distribution of HW rates
all_hw = [v['hw_rate'] for v in fixture_hw_rates.values()]
print(f"\n  Total fixture pairs with ≥10 meetings: {len(fixture_hw_rates)}")
for thresh in [0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]:
    count = sum(1 for r in all_hw if r >= thresh)
    print(f"  ≥{thresh*100:.0f}% HW rate: {count:3d} fixtures")

# Build lock tables at each threshold
thresholds = [0.75, 0.70, 0.65, 0.60]
lock_tables = {}
for thresh in thresholds:
    locks = {(ht, at): v for (ht, at), v in fixture_hw_rates.items()
             if v['hw_rate'] >= thresh}
    lock_tables[thresh] = locks

print(f"\n  Lock table sizes:")
for thresh, locks in lock_tables.items():
    print(f"    ≥{thresh*100:.0f}%: {len(locks)} fixture pairs")

# ─────────────────────────────────────────────────────────────
# 2. MATCHDAY COVERAGE — HOW MANY STAKES PER SEASON?
# ─────────────────────────────────────────────────────────────
print("\n[2/4] Computing stakes per season at each threshold...")

for thresh, locks in lock_tables.items():
    lock_set = set(locks.keys())
    season_stakes = defaultdict(int)
    total_fires = 0

    for (season, md), grp in df_test.groupby(['season_num', 'matchday_number']):
        fixtures_this_md = set(zip(grp['home_team'], grp['away_team']))
        matching = [fix for fix in lock_set if fix in fixtures_this_md]
        if matching:
            # Pick the highest confidence one
            best = max(matching, key=lambda x: locks[x]['hw_rate'])
            season_stakes[season] += 1
            total_fires += 1

    stakes_per_season = list(season_stakes.values())
    if stakes_per_season:
        print(f"\n  Threshold ≥{thresh*100:.0f}%:")
        print(f"    Total fires: {total_fires:,} over {len(test_seasons)} seasons")
        print(f"    Avg stakes/season: {np.mean(stakes_per_season):.1f}")
        print(f"    Min: {min(stakes_per_season)} | Max: {max(stakes_per_season)}")
        print(f"    Seasons with ≥20 stakes: {sum(1 for s in stakes_per_season if s >= 20)}/{len(stakes_per_season)}")
        print(f"    Seasons with ≥10 stakes: {sum(1 for s in stakes_per_season if s >= 10)}/{len(stakes_per_season)}")

# ─────────────────────────────────────────────────────────────
# 3. FULL COMPOUND BACKTEST AT EACH THRESHOLD
# ─────────────────────────────────────────────────────────────
print("\n[3/4] Compound backtest at each threshold (single best HW per matchday)...")

STARTING_BANK = 1000.0
STAKE_PCT = 0.02
HW_ODDS = 2.20

def run_single_hw_compound(locks, df_test, thresh):
    lock_set = set(locks.keys())
    bankroll = STARTING_BANK
    results = []
    wins = losses = 0

    test_sorted = df_test.sort_values(['season_num', 'matchday_number'])
    for (season, md), md_grp in test_sorted.groupby(['season_num', 'matchday_number']):
        fixtures_this_md = {}
        for _, row in md_grp.iterrows():
            fixtures_this_md[(row['home_team'], row['away_team'])] = row

        # Find qualifying fixtures this matchday
        matching = [(fix, locks[fix]) for fix in lock_set if fix in fixtures_this_md]
        if not matching:
            continue

        # Pick highest confidence
        best_fix, best_data = max(matching, key=lambda x: x[1]['hw_rate'])
        actual_hw = int(fixtures_this_md[best_fix]['home_win'])
        conf = best_data['hw_rate']

        stake = min(bankroll * STAKE_PCT, bankroll * 0.05)
        if actual_hw == 1:
            profit = stake * (HW_ODDS - 1)
            wins += 1
        else:
            profit = -stake
            losses += 1

        bankroll = max(bankroll + profit, 0.01)
        results.append({
            'season': season, 'md': md,
            'home': best_fix[0], 'away': best_fix[1],
            'confidence': conf,
            'actual': actual_hw,
            'profit': profit,
            'bankroll': bankroll,
        })

    rdf = pd.DataFrame(results)
    return rdf, bankroll, wins, losses

all_thresh_results = {}
for thresh, locks in lock_tables.items():
    rdf, final, wins, losses = run_single_hw_compound(locks, df_test, thresh)
    all_thresh_results[thresh] = (rdf, final, wins, losses)
    if len(rdf) == 0:
        print(f"  ≥{thresh*100:.0f}%: No data")
        continue
    wr = rdf['actual'].mean()
    per_szn = len(rdf) / len(test_seasons)
    roi = (final / STARTING_BANK - 1) * 100
    ev = wr * HW_ODDS - 1
    print(f"\n  ≥{thresh*100:.0f}% threshold:")
    print(f"    Total bets: {len(rdf):,} | Per season: {per_szn:.1f}")
    print(f"    Win rate:   {wr*100:.1f}% ({wins}W / {losses}L)")
    print(f"    EV/bet:     {ev:+.4f}")
    print(f"    Final bank: £{final:,.2f}")
    print(f"    ROI:        {roi:.1f}%")
    # Season breakdown
    per_szn_dist = rdf.groupby('season').size()
    szn_ge_20 = (per_szn_dist >= 20).sum()
    szn_ge_10 = (per_szn_dist >= 10).sum()
    print(f"    Seasons ≥20 bets: {szn_ge_20}/{len(test_seasons)}")
    print(f"    Seasons ≥10 bets: {szn_ge_10}/{len(test_seasons)}")

# ─────────────────────────────────────────────────────────────
# 4. FULL LOCK TABLE — ALL PROFITABLE FIXTURES
# ─────────────────────────────────────────────────────────────
print("\n[4/4] Printing full profitable fixture lock table (≥65% HW)...")

locks_65 = lock_tables[0.65]
sorted_locks = sorted(locks_65.items(), key=lambda x: x[1]['hw_rate'], reverse=True)

print(f"\n  {'Home':<22} {'Away':<22} {'HW%':>5} {'O1.5%':>6} {'U3.5%':>6} {'N':>4}")
print(f"  " + "-"*65)
for (ht, at), data in sorted_locks[:40]:
    print(f"  {ht:<22} {at:<22} {data['hw_rate']*100:>5.1f}% "
          f"{data['o15_rate']*100:>5.1f}% {data['u35_rate']*100:>5.1f}% {data['n']:>4}")

# ── CHARTS ──
fig, axes = plt.subplots(2, 2, figsize=(18, 12))
fig.suptitle('VFL Expanded Lock Table — Finding 20+ Stakes Per Season\n'
             'Single Best Home Win per Matchday, Compounded',
             fontsize=14, fontweight='bold')

COLORS = {0.75:'#2196F3', 0.70:'#4CAF50', 0.65:'#FF9800', 0.60:'#E91E63'}

# Chart 1: Bankroll growth by threshold
ax1 = axes[0, 0]
for thresh, (rdf, final, *_) in all_thresh_results.items():
    if len(rdf) < 5: continue
    ax1.semilogy(range(len(rdf)), rdf['bankroll'].values,
                 color=COLORS[thresh], lw=1.8,
                 label=f'≥{thresh*100:.0f}% ({len(rdf):,} bets → £{final:,.0f})',
                 alpha=0.85)
ax1.axhline(STARTING_BANK, color='black', linestyle='--', alpha=0.5)
ax1.set_xlabel('Bet Number')
ax1.set_ylabel('Bankroll £ (log scale)')
ax1.set_title('Compound Growth by Confidence Threshold')
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.3)

# Chart 2: Win rate by threshold
ax2 = axes[0, 1]
threshs = [t for t in thresholds if len(all_thresh_results[t][0]) > 0]
wrs = [all_thresh_results[t][0]['actual'].mean() for t in threshs]
bets = [len(all_thresh_results[t][0]) / len(test_seasons) for t in threshs]
ax2_twin = ax2.twinx()
bars = ax2.bar([f'≥{t*100:.0f}%' for t in threshs], wrs,
               color=[COLORS[t] for t in threshs], alpha=0.75, label='Win Rate')
ax2_twin.plot([f'≥{t*100:.0f}%' for t in threshs], bets,
              'ko--', lw=2, ms=8, label='Stakes/Season')
ax2.axhline(1/HW_ODDS, color='red', linestyle='--', lw=1.5,
            label=f'Break-even at {HW_ODDS}x odds')
ax2.set_ylabel('Win Rate', color='#333')
ax2_twin.set_ylabel('Stakes per Season', color='black')
ax2.set_title('Win Rate vs Stakes per Season\nby Confidence Threshold')
ax2.set_ylim(0.4, 0.9)
ax2.legend(loc='upper left', fontsize=8)
ax2_twin.legend(loc='upper right', fontsize=8)
for bar, wr in zip(bars, wrs):
    ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.005,
             f'{wr*100:.1f}%', ha='center', fontsize=10, fontweight='bold')

# Chart 3: Stakes per season histogram for 65% threshold
ax3 = axes[1, 0]
if len(all_thresh_results[0.65][0]) > 0:
    rdf_65 = all_thresh_results[0.65][0]
    per_szn_65 = rdf_65.groupby('season').size()
    ax3.hist(per_szn_65.values, bins=20, color='#FF9800', alpha=0.85, edgecolor='white')
    ax3.axvline(20, color='red', lw=2.5, linestyle='--', label='Target: 20 stakes')
    ax3.axvline(per_szn_65.mean(), color='blue', lw=2, linestyle=':',
                label=f'Mean: {per_szn_65.mean():.1f}')
    ax3.set_xlabel('Stakes per Season')
    ax3.set_ylabel('Number of Seasons')
    ax3.set_title(f'Stakes per Season (≥65% threshold)\n'
                  f'{(per_szn_65 >= 20).sum()}/{len(test_seasons)} seasons hit ≥20 stakes')
    ax3.legend(fontsize=9)

# Chart 4: Top 20 lock fixtures by HW rate
ax4 = axes[1, 1]
top20 = sorted_locks[:20]
top_names = [f'{ht[:8]} vs {at[:8]}' for (ht, at), _ in top20]
top_rates = [data['hw_rate']*100 for _, data in top20]
top_n = [data['n'] for _, data in top20]
colors_top = ['#2196F3' if r >= 75 else '#4CAF50' if r >= 70 else '#FF9800' for r in top_rates]
bars4 = ax4.barh(top_names[::-1], top_rates[::-1], color=colors_top[::-1], alpha=0.85, edgecolor='white')
ax4.axvline(75, color='blue', linestyle='--', lw=1.5, alpha=0.7, label='75% (9 fixtures)')
ax4.axvline(65, color='orange', linestyle='--', lw=1.5, alpha=0.7, label='65% threshold')
ax4.axvline(1/HW_ODDS*100, color='red', linestyle=':', lw=1.5, label=f'Break-even ({100/HW_ODDS:.0f}%)')
ax4.set_xlabel('Home Win Rate %')
ax4.set_title('Top 20 Lock Fixtures by HW Rate\n(Blue=≥75%, Green=≥70%, Orange=≥65%)')
ax4.legend(fontsize=8)

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'expanded_lock_compound.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()

# ── FINAL RECOMMENDATION REPORT ──
report_path = os.path.join(OUTPUT_DIR, 'expanded_lock_report.md')
with open(report_path, 'w') as f:
    f.write("# VFL Expanded Lock Table — 20-Stake Strategy\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n\n")

    f.write("## Strategy: Single Best Home Win Per Matchday, Compounded\n\n")
    f.write("Each matchday: pick the fixture with the highest historical home win rate from the lock table. Bet Home Win. Compound 2% of bankroll.\n\n")

    f.write("## Results by Confidence Threshold\n\n")
    f.write("| Threshold | Fixtures | Bets/Season | Win Rate | EV | ROI | Final Bank |\n")
    f.write("|-----------|----------|-------------|----------|----|-----|------------|\n")
    for thresh, (rdf, final, wins, losses) in all_thresh_results.items():
        if len(rdf) == 0: continue
        wr = rdf['actual'].mean()
        per_szn = len(rdf)/len(test_seasons)
        ev = wr * HW_ODDS - 1
        roi = (final/STARTING_BANK-1)*100
        n_locks = len(lock_tables[thresh])
        p = "✅" if ev > 0 else "❌"
        f.write(f"| ≥{thresh*100:.0f}% | {n_locks} | {per_szn:.1f} | {wr*100:.1f}% | {ev:+.3f} {p} | {roi:.0f}% | £{final:,.0f} |\n")

    f.write("\n## Full Lock Table (≥65% Home Win Rate, ≥10 historical meetings)\n\n")
    f.write("| # | Home | Away | HW% | O1.5% | U3.5% | N Meetings |\n")
    f.write("|---|------|------|-----|-------|-------|------------|\n")
    for i, ((ht, at), data) in enumerate(sorted_locks, 1):
        f.write(f"| {i} | {ht} | {at} | {data['hw_rate']*100:.1f}% | "
                f"{data['o15_rate']*100:.1f}% | {data['u35_rate']*100:.1f}% | {data['n']} |\n")

print(f"\n  Chart → {chart_path}")
print(f"  Report → {report_path}")
print(f"\n  Full lock table ({len(sorted_locks)} fixtures at ≥65%) saved to report")
print("\n" + "="*70)
print("EXPANDED LOCK ANALYSIS COMPLETE")
print("="*70)
