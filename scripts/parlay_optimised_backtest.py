#!/usr/bin/env python3
"""
VFL OPTIMISED PARLAY — Finding the Profitable Configuration
============================================================
Tests multiple parlay configurations to find what actually works:
  A) 2-leg lock parlay (highest confidence only)
  B) 3-leg lock parlay
  C) 4-leg mixed: 2 high-confidence low-odds + 2 lock home wins (higher odds)
  D) Single high-confidence bets compounded (no parlay)

The key equation: win_rate × parlay_odds MUST be > 1 to profit.
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
print("VFL OPTIMISED PARLAY — FINDING THE PROFITABLE CONFIG")
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
df['over_25']  = (df['total_goals'] > 2.5).astype(int)
df['gg']       = ((df['home_goals'] > 0) & (df['away_goals'] > 0)).astype(int)
df['home_win'] = (df['home_goals'] > df['away_goals']).astype(int)
df['away_win'] = (df['home_goals'] < df['away_goals']).astype(int)
df['draw']     = (df['home_goals'] == df['away_goals']).astype(int)

seasons_sorted = sorted(df['season_num'].unique())
split_idx = int(len(seasons_sorted) * 0.40)
train_seasons = set(seasons_sorted[:split_idx])
test_seasons  = set(seasons_sorted[split_idx:])

df_train = df[df['season_num'].isin(train_seasons)]
df_test  = df[df['season_num'].isin(test_seasons)]

print(f"  Loaded {len(df):,} matches | Train: {len(train_seasons)}s | Test: {len(test_seasons)}s")

MARKETS = {
    'over_15':  {'name': 'Over 1.5 Goals',  'odds': 1.25},
    'under_35': {'name': 'Under 3.5 Goals', 'odds': 1.28},
    'over_25':  {'name': 'Over 2.5 Goals',  'odds': 1.85},
    'gg':       {'name': 'BTTS Yes',        'odds': 1.90},
    'home_win': {'name': 'Home Win',        'odds': 2.20},
    'away_win': {'name': 'Away Win',        'odds': 3.10},
}

global_rates = {mkt: df_train[mkt].mean() for mkt in MARKETS}

# Build fixture confidence
fixture_conf = {}
for (ht, at, md), grp in df_train.groupby(['home_team', 'away_team', 'matchday_number']):
    n = len(grp)
    if n < 5:
        continue
    for mkt in MARKETS:
        rate = grp[mkt].mean()
        shrunk = (rate * n + global_rates[mkt] * 8) / (n + 8)
        fixture_conf[(ht, at, md, mkt)] = {'rate': shrunk, 'raw': rate, 'n': n}

print(f"  Fixture-market entries: {len(fixture_conf):,}")

# ── EV TABLE: what win rate do we need for each parlay size? ──
print("\n  EV analysis — what win rate needed to break even:")
print("  " + "-"*55)
print(f"  {'Config':<30} {'Typical Odds':>12} {'Need Win%':>10}")
print("  " + "-"*55)
configs_ev = [
    ("Single O1.5",         1.25, 1),
    ("Single HW (lock)",    2.20, 1),
    ("2-leg O1.5+U3.5",     1.25*1.28, 2),
    ("2-leg lock HW×2",     2.20*2.20, 2),
    ("3-leg O1.5+U35+HW",   1.25*1.28*2.20, 3),
    ("4-leg O1.5+U35+HW+HW",1.25*1.28*2.20*2.20, 4),
    ("4-leg O1.5+U35+HW+AW",1.25*1.28*2.20*3.10, 4),
]
for name, odds, legs in configs_ev:
    need = 1.0 / odds
    print(f"  {name:<30} {odds:>12.2f}x {need*100:>9.1f}%")

# ── RUN BACKTEST FOR EACH CONFIGURATION ──
STARTING_BANK = 1000.0
STAKE = 0.02

def run_parlay_config(name, min_conf, n_legs, market_priority, min_n=5):
    """Run a parlay configuration and return results."""
    bankroll = STARTING_BANK
    results = []
    test_df_sorted = df_test.sort_values(['season_num', 'matchday_number'])

    for (season, md), md_group in test_df_sorted.groupby(['season_num', 'matchday_number']):
        fixtures = md_group.to_dict('records')
        candidates = []

        for fix in fixtures:
            ht, at = fix['home_team'], fix['away_team']
            for mkt in market_priority:
                key = (ht, at, md, mkt)
                if key in fixture_conf:
                    fc = fixture_conf[key]
                    if fc['rate'] >= min_conf and fc['n'] >= min_n:
                        candidates.append({
                            'home': ht, 'away': at,
                            'market': mkt,
                            'odds': MARKETS[mkt]['odds'],
                            'confidence': fc['rate'],
                            'n': fc['n'],
                            'actual': fix[mkt],
                        })

        if not candidates:
            continue

        # Sort by confidence, pick diverse legs
        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        selected = []
        used_fix = set()
        for c in candidates:
            fk = (c['home'], c['away'])
            if fk not in used_fix and len(selected) < n_legs:
                selected.append(c)
                used_fix.add(fk)

        if len(selected) < n_legs:
            continue  # strict: only full parlays

        parlay_odds = np.prod([c['odds'] for c in selected])
        all_hit = all(c['actual'] == 1 for c in selected)
        n_hit = sum(c['actual'] for c in selected)

        stake = min(bankroll * STAKE, bankroll * 0.05)
        profit = stake * (parlay_odds - 1) if all_hit else -stake
        bankroll = max(bankroll + profit, 0.01)

        results.append({
            'season': season, 'md': md,
            'parlay_odds': parlay_odds,
            'all_hit': int(all_hit),
            'n_hit': n_hit,
            'n_legs': len(selected),
            'profit': profit,
            'bankroll': bankroll,
            'avg_conf': np.mean([c['confidence'] for c in selected]),
            'best_conf': max(c['confidence'] for c in selected),
        })

    rdf = pd.DataFrame(results) if results else pd.DataFrame()
    return rdf, bankroll

print("\n" + "=" * 70)
print("BACKTEST RESULTS BY CONFIGURATION")
print("=" * 70)

all_configs = {}

# Config A: 2-leg lock (only fixtures with ≥75% on any market)
cfg_a, bank_a = run_parlay_config(
    "2-leg lock (≥75%)", min_conf=0.75, n_legs=2,
    market_priority=['home_win', 'over_15', 'under_35', 'over_25', 'gg']
)
all_configs['2-leg Lock (≥75%)'] = (cfg_a, bank_a)

# Config B: 3-leg lock (≥72%)
cfg_b, bank_b = run_parlay_config(
    "3-leg (≥72%)", min_conf=0.72, n_legs=3,
    market_priority=['home_win', 'over_15', 'under_35', 'over_25', 'gg']
)
all_configs['3-leg Lock (≥72%)'] = (cfg_b, bank_b)

# Config C: 2-leg high-odds (home_win + away_win locks)
cfg_c, bank_c = run_parlay_config(
    "2-leg HW/AW locks", min_conf=0.70, n_legs=2,
    market_priority=['home_win', 'away_win']
)
all_configs['2-leg HW/AW (≥70%)'] = (cfg_c, bank_c)

# Config D: Singles — no parlay, just best bet per matchday compounded
def run_singles(min_conf=0.75, min_n=8):
    bankroll = STARTING_BANK
    results = []
    test_df_sorted = df_test.sort_values(['season_num', 'matchday_number'])

    for (season, md), md_group in test_df_sorted.groupby(['season_num', 'matchday_number']):
        fixtures = md_group.to_dict('records')
        best = None
        for fix in fixtures:
            ht, at = fix['home_team'], fix['away_team']
            for mkt in ['home_win', 'away_win', 'over_15', 'under_35']:
                key = (ht, at, md, mkt)
                if key in fixture_conf:
                    fc = fixture_conf[key]
                    if fc['rate'] >= min_conf and fc['n'] >= min_n:
                        if best is None or fc['rate'] > best['confidence']:
                            best = {
                                'confidence': fc['rate'], 'odds': MARKETS[mkt]['odds'],
                                'actual': fix[mkt], 'n': fc['n'],
                                'home': ht, 'away': at, 'market': mkt
                            }
        if best is None:
            continue
        stake = min(bankroll * STAKE, bankroll * 0.05)
        profit = stake * (best['odds'] - 1) if best['actual'] == 1 else -stake
        bankroll = max(bankroll + profit, 0.01)
        results.append({'bankroll': bankroll, 'profit': profit,
                        'hit': best['actual'], 'conf': best['confidence'],
                        'odds': best['odds'], 'season': season, 'md': md})
    return pd.DataFrame(results) if results else pd.DataFrame(), bankroll

cfg_d, bank_d = run_singles(min_conf=0.75)
all_configs['Singles (≥75% best pick)'] = (cfg_d, bank_d)

# Config E: 2-leg with home_win only on confirmed dominant fixtures
cfg_e, bank_e = run_parlay_config(
    "2-leg dominant HW (≥78%)", min_conf=0.78, n_legs=2,
    market_priority=['home_win'],
    min_n=10
)
all_configs['2-leg Dom HW (≥78%)'] = (cfg_e, bank_e)

# ── RESULTS TABLE ──
print(f"\n{'Config':<28} {'MDs':>6} {'WinRate':>8} {'AvgOdds':>8} {'FinalBank':>11} {'ROI':>8} {'EV/bet':>8}")
print("-" * 80)
for cname, (rdf, final_bank) in all_configs.items():
    if len(rdf) == 0:
        print(f"  {cname:<26} {'No data':>6}")
        continue
    win_col = 'all_hit' if 'all_hit' in rdf.columns else 'hit'
    odds_col = 'parlay_odds' if 'parlay_odds' in rdf.columns else 'odds'
    wr = rdf[win_col].mean()
    avg_odds = rdf[odds_col].mean()
    roi = (final_bank / STARTING_BANK - 1) * 100
    ev = wr * avg_odds - 1  # expected value per unit staked
    star = ' ★' if ev > 0 else ''
    print(f"  {cname:<26} {len(rdf):>6,} {wr*100:>7.1f}% {avg_odds:>8.2f}x "
          f"£{final_bank:>9,.0f} {roi:>7.1f}% {ev:>+7.3f}{star}")

# ── CHART ──
fig, axes = plt.subplots(2, 2, figsize=(18, 11))
fig.suptitle('VFL Optimised Parlay — Finding Profitable Configuration\n'
             f'Test: {len(test_seasons)} seasons | Start £{STARTING_BANK:,.0f}',
             fontsize=14, fontweight='bold')

COLORS = ['#2196F3','#4CAF50','#FF9800','#E91E63','#9C27B0']

# Chart 1: Bankroll growth for all configs
ax1 = axes[0, 0]
for (cname, (rdf, _)), col in zip(all_configs.items(), COLORS):
    if len(rdf) > 0:
        ax1.semilogy(range(len(rdf)), rdf['bankroll'].values,
                     color=col, lw=1.8, label=cname, alpha=0.85)
ax1.axhline(STARTING_BANK, color='black', linestyle='--', alpha=0.5, label='Start £1,000')
ax1.set_xlabel('Matchday (chronological)')
ax1.set_ylabel('Bankroll £ (log scale)')
ax1.set_title('Compound Bankroll Growth — All Configs')
ax1.legend(fontsize=7)
ax1.grid(True, alpha=0.3)

# Chart 2: EV per bet for each config
ax2 = axes[0, 1]
config_names, evs, win_rates, avg_odds_list = [], [], [], []
for cname, (rdf, _) in all_configs.items():
    if len(rdf) == 0:
        continue
    win_col = 'all_hit' if 'all_hit' in rdf.columns else 'hit'
    odds_col = 'parlay_odds' if 'parlay_odds' in rdf.columns else 'odds'
    wr = rdf[win_col].mean()
    ao = rdf[odds_col].mean()
    ev = wr * ao - 1
    config_names.append(cname.replace('(','').replace(')',''))
    evs.append(ev)
    win_rates.append(wr)
    avg_odds_list.append(ao)

bar_cols = ['#4CAF50' if e > 0 else '#F44336' for e in evs]
bars = ax2.bar(range(len(config_names)), evs, color=bar_cols, alpha=0.85, edgecolor='white')
ax2.axhline(0, color='black', lw=1.5)
ax2.set_xticks(range(len(config_names)))
ax2.set_xticklabels(config_names, rotation=20, ha='right', fontsize=8)
ax2.set_ylabel('Expected Value per Bet')
ax2.set_title('EV per Bet by Configuration\n(Green = profitable)')
for bar, ev in zip(bars, evs):
    ax2.text(bar.get_x()+bar.get_width()/2,
             bar.get_height() + (0.002 if ev >= 0 else -0.008),
             f'{ev:+.3f}', ha='center', fontsize=9, fontweight='bold')

# Chart 3: Win rate vs odds needed (break-even chart)
ax3 = axes[1, 0]
ax3.scatter(avg_odds_list, [w*100 for w in win_rates],
            s=200, c=bar_cols, zorder=5, edgecolors='white', linewidth=2)
for i, name in enumerate(config_names):
    ax3.annotate(name, (avg_odds_list[i], win_rates[i]*100),
                 textcoords="offset points", xytext=(5,5), fontsize=7)
x_range = np.linspace(1.0, max(avg_odds_list)*1.1, 200)
ax3.plot(x_range, 100/x_range, 'r--', lw=2, label='Break-even line (1/odds)')
ax3.set_xlabel('Average Parlay Odds')
ax3.set_ylabel('Actual Win Rate %')
ax3.set_title('Win Rate vs Odds — Points ABOVE red line = profitable')
ax3.legend()
ax3.grid(True, alpha=0.3)

# Chart 4: Best config — per-season bankroll
best_cfg_name = max(all_configs, key=lambda k: all_configs[k][1])
best_rdf, best_bank = all_configs[best_cfg_name]
ax4 = axes[1, 1]
if len(best_rdf) > 0:
    ax4.plot(range(len(best_rdf)), best_rdf['bankroll'].values,
             color='#2196F3', lw=1.8)
    ax4.axhline(STARTING_BANK, color='red', linestyle='--', alpha=0.7)
    ax4.fill_between(range(len(best_rdf)), STARTING_BANK,
                     best_rdf['bankroll'].values,
                     where=best_rdf['bankroll'].values >= STARTING_BANK,
                     alpha=0.2, color='#4CAF50')
    ax4.fill_between(range(len(best_rdf)), STARTING_BANK,
                     best_rdf['bankroll'].values,
                     where=best_rdf['bankroll'].values < STARTING_BANK,
                     alpha=0.2, color='#F44336')
ax4.set_xlabel('Matchday')
ax4.set_ylabel('Bankroll £')
ax4.set_title(f'Best Config: {best_cfg_name}\nFinal: £{best_bank:,.0f}')
ax4.grid(True, alpha=0.3)

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'parlay_optimised_backtest.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"\n  Chart saved → {chart_path}")

# ── REPORT ──
report_path = os.path.join(OUTPUT_DIR, 'parlay_optimised_report.md')
with open(report_path, 'w') as f:
    f.write("# VFL Optimised Parlay — Configuration Comparison\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    f.write(f"**Test Seasons:** {len(test_seasons)} | **Start:** £{STARTING_BANK:,.0f}  \n\n")
    f.write("## Break-Even Rule\n\n")
    f.write("> For any parlay to be profitable: **Win Rate × Parlay Odds > 1**\n\n")
    f.write("| Config | Matchdays | Win Rate | Avg Odds | Final Bank | ROI | EV |\n")
    f.write("|--------|-----------|----------|----------|------------|-----|----|\n")
    for cname, (rdf, final_bank) in all_configs.items():
        if len(rdf) == 0:
            continue
        win_col = 'all_hit' if 'all_hit' in rdf.columns else 'hit'
        odds_col = 'parlay_odds' if 'parlay_odds' in rdf.columns else 'odds'
        wr = rdf[win_col].mean()
        ao = rdf[odds_col].mean()
        ev = wr * ao - 1
        roi = (final_bank / STARTING_BANK - 1) * 100
        star = " ★ **PROFITABLE**" if ev > 0 else ""
        f.write(f"| {cname} | {len(rdf):,} | {wr*100:.1f}% | {ao:.2f}x | £{final_bank:,.0f} | {roi:.1f}% | {ev:+.3f}{star} |\n")

    f.write(f"\n## Best Configuration: {best_cfg_name}\n\n")
    if len(best_rdf) > 0:
        win_col = 'all_hit' if 'all_hit' in best_rdf.columns else 'hit'
        wr = best_rdf[win_col].mean()
        f.write(f"- Win rate: **{wr*100:.1f}%**\n")
        f.write(f"- Final bankroll: **£{best_bank:,.0f}**\n")
        f.write(f"- ROI: **{(best_bank/STARTING_BANK-1)*100:.1f}%**\n\n")

print(f"  Report → {report_path}")
print(f"\n  ★ Best config: {best_cfg_name} → £{best_bank:,.0f} from £{STARTING_BANK:,.0f}")
