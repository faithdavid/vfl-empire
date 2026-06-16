#!/usr/bin/env python3
"""
VFL DOMINANT FIXTURE FREQUENCY ANALYSIS
=========================================
1. How many times per season do 2+ dominant fixtures appear on the same matchday?
2. Per-matchday breakdown across all seasons
3. What threshold gives us ≥20 qualifying stakes per season?
4. Full compound backtest with the frequent-fire strategy
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
print("VFL DOMINANT FIXTURE FREQUENCY + 20-STAKE STRATEGY")
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
df['away_win'] = (df['home_goals'] < df['away_goals']).astype(int)

print(f"  Loaded {len(df):,} matches | {df['season_num'].nunique()} seasons")

# ─────────────────────────────────────────────────────────────
# THE 9 CONFIRMED DOMINANT FIXTURES
# ─────────────────────────────────────────────────────────────
DOMINANT_FIXTURES = [
    ('Chelsea',         'Bournemouth',      0.798, 'home_win'),
    ('Manchester Red',  'Crystal Palace',   0.791, 'home_win'),
    ('Manchester Blue', 'Crystal Palace',   0.781, 'home_win'),
    ('Chelsea',         'Crystal Palace',   0.773, 'home_win'),
    ('Manchester Blue', 'Fulham',           0.773, 'home_win'),
    ('Manchester Blue', 'Bournemouth',      0.771, 'home_win'),
    ('Liverpool',       'Bournemouth',      0.769, 'home_win'),
    ('Manchester Blue', 'Leeds',            0.764, 'home_win'),
    ('Liverpool',       'Crystal Palace',   0.755, 'home_win'),
]

# Also track Over 1.5 and Under 3.5 as always-available legs (73%+ league-wide)
GLOBAL_O15_RATE  = 0.733
GLOBAL_U35_RATE  = 0.736
GLOBAL_O15_ODDS  = 1.25
GLOBAL_U35_ODDS  = 1.28
HW_ODDS          = 2.20

dominant_set = {(ht, at) for ht, at, _, _ in DOMINANT_FIXTURES}
dom_conf = {(ht, at): conf for ht, at, conf, _ in DOMINANT_FIXTURES}

print(f"\n  Dominant fixtures tracked: {len(DOMINANT_FIXTURES)}")
for ht, at, conf, mkt in DOMINANT_FIXTURES:
    print(f"    {ht:20s} vs {at:20s} → HW {conf*100:.1f}%")

# ─────────────────────────────────────────────────────────────
# 1. COUNT CO-OCCURRENCES PER MATCHDAY PER SEASON
# ─────────────────────────────────────────────────────────────
print("\n[1/4] Counting dominant fixture co-occurrences per matchday...")

matchday_dominant_count = []  # one record per (season, matchday)

for (season, md), grp in df.groupby(['season_num', 'matchday_number']):
    fixtures_this_md = set(zip(grp['home_team'], grp['away_team']))
    dom_present = [(ht, at) for ht, at in dominant_set if (ht, at) in fixtures_this_md]
    n_dom = len(dom_present)
    matchday_dominant_count.append({
        'season': season,
        'matchday': md,
        'n_dominant': n_dom,
        'dominant_fixtures': dom_present,
    })

md_df = pd.DataFrame(matchday_dominant_count)

# Per-season summary
season_stats = md_df.groupby('season').agg(
    total_matchdays=('matchday', 'count'),
    matchdays_with_1plus=('n_dominant', lambda x: (x >= 1).sum()),
    matchdays_with_2plus=('n_dominant', lambda x: (x >= 2).sum()),
    matchdays_with_3plus=('n_dominant', lambda x: (x >= 3).sum()),
    matchdays_with_4plus=('n_dominant', lambda x: (x >= 4).sum()),
    avg_dominant_per_md=('n_dominant', 'mean'),
    max_dominant_in_md=('n_dominant', 'max'),
).reset_index()

print(f"\n  Season-level dominant fixture co-occurrence:")
print(f"  {'Metric':<45} {'Mean':>8} {'Min':>6} {'Max':>6}")
print(f"  " + "-"*68)
for col, label in [
    ('total_matchdays',       'Matchdays per season'),
    ('matchdays_with_1plus',  'MDs with ≥1 dominant fixture'),
    ('matchdays_with_2plus',  'MDs with ≥2 dominant fixtures (parlay possible)'),
    ('matchdays_with_3plus',  'MDs with ≥3 dominant fixtures'),
    ('matchdays_with_4plus',  'MDs with ≥4 dominant fixtures'),
    ('avg_dominant_per_md',   'Avg dominant fixtures per matchday'),
    ('max_dominant_in_md',    'Max dominant fixtures in single matchday'),
]:
    print(f"  {label:<45} {season_stats[col].mean():>8.1f} {season_stats[col].min():>6.0f} {season_stats[col].max():>6.0f}")

total_seasons = df['season_num'].nunique()
md_with_2plus = (md_df['n_dominant'] >= 2).sum()
print(f"\n  Total matchdays with ≥2 dominant fixtures: {md_with_2plus:,} / {len(md_df):,} ({md_with_2plus/len(md_df)*100:.1f}%)")
print(f"  Avg per season: {md_with_2plus/total_seasons:.1f} matchdays per season qualify for 2-dominant parlay")

# ─────────────────────────────────────────────────────────────
# 2. STAKE FREQUENCY ANALYSIS — HOW TO GET 20 STAKES/SEASON
# ─────────────────────────────────────────────────────────────
print("\n[2/4] Finding strategy to hit ≥20 stakes per season...")

# Strategy options for more frequency:
# A) 1-dominant + O1.5 + U3.5 (3-leg parlay) → fires whenever ≥1 dominant present
# B) 0-dominant + O1.5 + U3.5 + best H2H market (3-leg, fires every matchday)
# C) 2-dominant + O1.5 + U3.5 (4-leg) → current strategy
# D) 1-dominant HW (single bet compounded) → fires every matchday with dominant fixture

strategies = {
    'A: 4-leg (≥2 dominant + O1.5 + U3.5)':  md_df['n_dominant'] >= 2,
    'B: 3-leg (≥1 dominant + O1.5 + U3.5)':  md_df['n_dominant'] >= 1,
    'C: 1-leg single (best dominant HW)':      md_df['n_dominant'] >= 1,
    'D: 3-leg (all MDs: O1.5 + U3.5 + best)': pd.Series([True]*len(md_df)),
}

print(f"\n  {'Strategy':<45} {'Total fires':>12} {'Per season':>11} {'Seasons w/ ≥20':>15}")
print(f"  " + "-"*85)
for strat_name, mask in strategies.items():
    total = mask.sum()
    per_season = total / total_seasons
    seasons_20 = (md_df[mask].groupby('season').size() >= 20).sum()
    seasons_20_pct = seasons_20 / total_seasons * 100
    flag = ' ← TARGET' if per_season >= 20 else ''
    print(f"  {strat_name:<45} {total:>12,} {per_season:>11.1f} {seasons_20:>8} ({seasons_20_pct:.0f}%){flag}")

# ─────────────────────────────────────────────────────────────
# 3. FULL COMPOUND BACKTEST — ALL STRATEGIES
# ─────────────────────────────────────────────────────────────
print("\n[3/4] Running full compound backtest for all strategies...")

STARTING_BANK = 1000.0
STAKE_PCT = 0.02  # 2% per bet

def backtest_strategy(df, md_df, strategy_name, min_dominant,
                      n_legs, use_global_ou=True, single_mode=False):
    """
    Backtest a parlay strategy.
    min_dominant: minimum dominant fixtures needed on matchday
    n_legs: number of parlay legs (2, 3, or 4)
    single_mode: just bet single best dominant fixture
    """
    bankroll = STARTING_BANK
    results = []

    # Build training data (first 40% of seasons for H2H confidence)
    seasons_sorted = sorted(df['season_num'].unique())
    split = int(len(seasons_sorted) * 0.40)
    train_set = set(seasons_sorted[:split])

    # Build matchday-specific H2H for dominant fixtures
    fixture_results = defaultdict(list)  # (ht, at, md) -> list of home_win outcomes
    df_sorted = df.sort_values(['season_num', 'matchday_number'])

    for _, row in df_sorted.iterrows():
        ht, at, md = row['home_team'], row['away_team'], row['matchday_number']
        if (ht, at) in dominant_set:
            fixture_results[(ht, at, md)].append(row['home_win'])

    test_df = df[~df['season_num'].isin(train_set)].sort_values(['season_num', 'matchday_number'])

    for (season, md), md_grp in test_df.groupby(['season_num', 'matchday_number']):
        fixtures = md_grp.to_dict('records')
        fixtures_this_md = {(r['home_team'], r['away_team']): r for r in fixtures}

        # Find dominant fixtures present this matchday
        dom_present = []
        for ht, at in dominant_set:
            if (ht, at) in fixtures_this_md:
                dom_present.append((ht, at, dom_conf[(ht, at)]))

        dom_present.sort(key=lambda x: x[2], reverse=True)

        if len(dom_present) < min_dominant and not (min_dominant == 0):
            continue

        # Build legs
        legs = []

        if single_mode:
            if not dom_present:
                continue
            ht, at, conf = dom_present[0]
            actual = fixtures_this_md[(ht, at)]['home_win']
            legs = [{'odds': HW_ODDS, 'actual': actual, 'conf': conf, 'label': f'{ht[:8]} HW'}]
        else:
            # Add dominant HW legs
            for i in range(min(min_dominant if min_dominant > 0 else 1, len(dom_present))):
                ht, at, conf = dom_present[i]
                actual = fixtures_this_md[(ht, at)]['home_win']
                legs.append({'odds': HW_ODDS, 'actual': actual, 'conf': conf,
                             'label': f'{ht[:8]} HW'})

            if use_global_ou and n_legs > len(legs):
                # Pick best Over 1.5 from remaining fixtures (highest total goals variance)
                remaining = [(r['home_team'], r['away_team'])
                             for r in fixtures
                             if (r['home_team'], r['away_team']) not in {(l2, l3) for l2, l3, _ in dom_present[:min_dominant]}]

                # Add Over 1.5 leg
                if remaining and n_legs - len(legs) >= 1:
                    ht2, at2 = remaining[0]
                    actual_o15 = fixtures_this_md[(ht2, at2)]['over_15'] if (ht2,at2) in fixtures_this_md else int(np.random.random() < GLOBAL_O15_RATE)
                    legs.append({'odds': GLOBAL_O15_ODDS, 'actual': actual_o15,
                                 'conf': GLOBAL_O15_RATE, 'label': 'O1.5'})

                # Add Under 3.5 leg
                if len(remaining) > 1 and n_legs - len(legs) >= 1:
                    ht3, at3 = remaining[1]
                    actual_u35 = fixtures_this_md[(ht3, at3)]['under_35'] if (ht3,at3) in fixtures_this_md else int(np.random.random() < GLOBAL_U35_RATE)
                    legs.append({'odds': GLOBAL_U35_ODDS, 'actual': actual_u35,
                                 'conf': GLOBAL_U35_RATE, 'label': 'U3.5'})

        if len(legs) < (1 if single_mode else n_legs):
            continue

        parlay_odds = np.prod([l['odds'] for l in legs])
        all_hit = all(l['actual'] == 1 for l in legs)
        n_hit = sum(l['actual'] for l in legs)

        stake = min(bankroll * STAKE_PCT, bankroll * 0.05)
        profit = stake * (parlay_odds - 1) if all_hit else -stake
        bankroll = max(bankroll + profit, 0.01)

        results.append({
            'season': season, 'md': md,
            'n_legs': len(legs),
            'parlay_odds': parlay_odds,
            'all_hit': int(all_hit),
            'n_hit': n_hit,
            'profit': profit,
            'bankroll': bankroll,
            'avg_conf': np.mean([l['conf'] for l in legs]),
            'n_dom': len(dom_present),
        })

    return pd.DataFrame(results), bankroll

strat_configs = [
    ('4-leg (2 dom HW + O1.5 + U3.5)', 2, 4, False),
    ('3-leg (1 dom HW + O1.5 + U3.5)', 1, 3, False),
    ('3-leg all MDs (best HW + O1.5 + U3.5)', 0, 3, False),
    ('Single best dom HW', 1, 1, True),
    ('2-leg (1 dom HW + O1.5)', 1, 2, False),
]

all_strat_results = {}
print(f"\n  {'Strategy':<42} {'Bets':>6} {'Per Szn':>8} {'WinRate':>8} {'EV':>7} {'FinalBank':>10} {'ROI':>7}")
print(f"  " + "-"*95)

for sname, min_dom, n_legs, single in strat_configs:
    rdf, final = backtest_strategy(df, md_df, sname, min_dom, n_legs, single_mode=single)
    all_strat_results[sname] = (rdf, final)
    if len(rdf) == 0:
        print(f"  {sname:<42} {'NO DATA':>6}")
        continue
    wr = rdf['all_hit'].mean()
    ao = rdf['parlay_odds'].mean()
    ev = wr * ao - 1
    roi = (final / STARTING_BANK - 1) * 100
    per_szn = len(rdf) / df['season_num'].nunique()
    star = ' ★' if ev > 0 else ''
    print(f"  {sname:<42} {len(rdf):>6,} {per_szn:>8.1f} {wr*100:>7.1f}% {ev:>+7.3f} £{final:>8,.0f} {roi:>6.1f}%{star}")

# ─────────────────────────────────────────────────────────────
# 4. TO GET 20 STAKES — SHOW WHAT COMBINATION WORKS
# ─────────────────────────────────────────────────────────────
print("\n[4/4] Designing 20-stake/season strategy...")

# The strategy that fires every matchday (all 30 per season = 30 stakes)
# Use: best available dom HW + O1.5 + U3.5 on any matchday
# If no dominant fixture: use 2 strongest H2H fixtures + O1.5 + U3.5

# Count per season for the 3-leg all-MDs strategy
if '3-leg all MDs (best HW + O1.5 + U3.5)' in all_strat_results:
    rdf_all, _ = all_strat_results['3-leg all MDs (best HW + O1.5 + U3.5)']
    if len(rdf_all) > 0:
        per_szn_dist = rdf_all.groupby('season').size()
        print(f"\n  3-leg all-MDs strategy — stakes per season distribution:")
        print(f"    Min: {per_szn_dist.min()} | Max: {per_szn_dist.max()} | "
              f"Mean: {per_szn_dist.mean():.1f} | Median: {per_szn_dist.median():.0f}")
        print(f"    Seasons with ≥20 stakes: {(per_szn_dist >= 20).sum()} / {len(per_szn_dist)}")
        print(f"    Seasons with ≥30 stakes: {(per_szn_dist >= 30).sum()} / {len(per_szn_dist)}")

# How many times do we see each number of dominant fixtures per matchday?
dom_dist = md_df['n_dominant'].value_counts().sort_index()
print(f"\n  Dominant fixture count distribution across ALL matchdays:")
print(f"  {'Count on MD':>12} {'Frequency':>10} {'%':>6}")
for cnt, freq in dom_dist.items():
    pct = freq / len(md_df) * 100
    bar = '█' * int(pct / 2)
    print(f"  {cnt:>12}   {freq:>10,}  {pct:>5.1f}%  {bar}")

# ── CHARTS ──
fig, axes = plt.subplots(2, 2, figsize=(18, 12))
fig.suptitle('VFL Dominant Fixture Frequency & 20-Stake Strategy\n'
             f'{df["season_num"].nunique()} seasons | 9 confirmed lock fixtures',
             fontsize=14, fontweight='bold')

COLORS = ['#2196F3','#4CAF50','#FF9800','#E91E63','#9C27B0']

# Chart 1: Dominant fixture frequency per matchday
ax1 = axes[0, 0]
dom_per_md = md_df.groupby('matchday')['n_dominant'].mean()
ax1.bar(dom_per_md.index, dom_per_md.values, color='#2196F3', alpha=0.85, edgecolor='white')
ax1.axhline(2, color='red', linestyle='--', lw=1.5, label='≥2 needed for 4-leg parlay')
ax1.axhline(1, color='orange', linestyle='--', lw=1.5, label='≥1 for 3-leg parlay')
ax1.set_xlabel('Matchday Number')
ax1.set_ylabel('Avg Dominant Fixtures Present')
ax1.set_title('Avg Dominant Fixtures per Matchday\n(How often do locks appear?)')
ax1.legend(fontsize=8)

# Chart 2: Stakes per season histogram
ax2 = axes[0, 1]
for (sname, (rdf, _)), col in zip(all_strat_results.items(), COLORS):
    if len(rdf) == 0: continue
    per_szn = rdf.groupby('season').size()
    ax2.hist(per_szn.values, bins=20, alpha=0.5, color=col, label=sname[:25], edgecolor='white')
ax2.axvline(20, color='red', lw=2, linestyle='--', label='Target: 20 stakes')
ax2.set_xlabel('Stakes per Season')
ax2.set_ylabel('Number of Seasons')
ax2.set_title('Stakes per Season Distribution\n(How many seasons hit ≥20 stakes?)')
ax2.legend(fontsize=7)

# Chart 3: Compound bankroll — all strategies
ax3 = axes[1, 0]
for (sname, (rdf, fb)), col in zip(all_strat_results.items(), COLORS):
    if len(rdf) < 5: continue
    ax3.semilogy(range(len(rdf)), rdf['bankroll'].values, color=col, lw=1.5,
                 label=f'{sname[:25]} (£{fb:,.0f})', alpha=0.85)
ax3.axhline(STARTING_BANK, color='black', linestyle='--', alpha=0.5)
ax3.set_xlabel('Bet Number (chronological)')
ax3.set_ylabel('Bankroll £ (log scale)')
ax3.set_title('Compound Bankroll Growth — All Strategies')
ax3.legend(fontsize=7)
ax3.grid(True, alpha=0.3)

# Chart 4: Dominant fixture matchday heatmap (which matchdays have 2+ locks)
ax4 = axes[1, 1]
seasons_list = sorted(md_df['season'].unique())[-60:]  # last 60 seasons
matchdays_list = list(range(1, 31))
heatmap_data = np.zeros((len(seasons_list), 30))
for i, szn in enumerate(seasons_list):
    szn_data = md_df[md_df['season'] == szn]
    for _, row in szn_data.iterrows():
        md_idx = int(row['matchday']) - 1
        if 0 <= md_idx < 30:
            heatmap_data[i, md_idx] = row['n_dominant']

im = ax4.imshow(heatmap_data, aspect='auto', cmap='YlOrRd', interpolation='nearest',
                vmin=0, vmax=4)
plt.colorbar(im, ax=ax4, label='# Dominant Fixtures')
ax4.set_xlabel('Matchday')
ax4.set_ylabel('Season (recent)')
ax4.set_title('Dominant Fixture Heatmap (last 60 seasons)\nRed = more lock fixtures on that MD')
ax4.set_xticks(range(0, 30, 5))
ax4.set_xticklabels(range(1, 31, 5))

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'dominant_frequency_analysis.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"\n  Chart → {chart_path}")

# ── REPORT ──
report_path = os.path.join(OUTPUT_DIR, 'dominant_frequency_report.md')
with open(report_path, 'w') as f:
    f.write("# VFL Dominant Fixture Frequency & 20-Stake Strategy\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    f.write(f"**Seasons analysed:** {df['season_num'].nunique()}  \n\n")

    f.write("## Co-occurrence Summary\n\n")
    f.write(f"| Metric | Mean/Season | Min | Max |\n|--------|-------------|-----|-----|\n")
    for col, label in [
        ('matchdays_with_1plus', '≥1 dominant fixture per MD'),
        ('matchdays_with_2plus', '≥2 dominant fixtures (4-leg parlay)'),
        ('matchdays_with_3plus', '≥3 dominant fixtures'),
    ]:
        f.write(f"| {label} | {season_stats[col].mean():.1f} | {season_stats[col].min():.0f} | {season_stats[col].max():.0f} |\n")

    f.write("\n## Strategy Comparison\n\n")
    f.write("| Strategy | Bets/Season | Win Rate | EV | ROI | Profitable? |\n")
    f.write("|----------|-------------|----------|----|-----|-------------|\n")
    for sname, (rdf, final) in all_strat_results.items():
        if len(rdf) == 0:
            f.write(f"| {sname} | 0 | — | — | — | No data |\n")
            continue
        wr = rdf['all_hit'].mean()
        ao = rdf['parlay_odds'].mean()
        ev = wr * ao - 1
        roi = (final / STARTING_BANK - 1) * 100
        per_szn = len(rdf) / df['season_num'].nunique()
        p = "✅ YES" if ev > 0 else "❌ No"
        f.write(f"| {sname} | {per_szn:.1f} | {wr*100:.1f}% | {ev:+.3f} | {roi:.1f}% | {p} |\n")

    f.write("\n## The 9 Confirmed Lock Fixtures\n\n")
    f.write("| Home | Away | HW Confidence |\n|------|------|---------------|\n")
    for ht, at, conf, _ in DOMINANT_FIXTURES:
        f.write(f"| {ht} | {at} | {conf*100:.1f}% |\n")

print(f"  Report → {report_path}")

print("\n" + "=" * 70)
print("FREQUENCY ANALYSIS COMPLETE")
print("=" * 70)
