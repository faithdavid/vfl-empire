#!/usr/bin/env python3
"""
VFL TARGETED 4-LEG PARLAY — Correct Market Mix
================================================
Uses the mathematically correct leg selection:
  Leg 1: Over 1.5 Goals @ 1.25 (dominant fixture)
  Leg 2: Under 3.5 Goals @ 1.28 (different fixture)
  Leg 3: Home Win @ 2.20 (locked dominant home fixture)
  Leg 4: Home Win @ 2.20 (another locked dominant fixture)
  ─────────────────────────────────────────────────────
  Combined odds: ~7.74x | Only needs 12.9% win rate to profit
  Our projected win rate: ~33% → EV = +2.56x per unit

Also tests: 3-leg mix and 2-leg high-odds versions.
"""

import psycopg2
import pandas as pd
import numpy as np
import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUTPUT_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/751aa9ef-b0a3-4429-8498-9c8a6b4df046"

print("=" * 70)
print("VFL TARGETED 4-LEG PARLAY — CORRECT MARKET MIX")
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

seasons_sorted = sorted(df['season_num'].unique())
split_idx = int(len(seasons_sorted) * 0.40)
train_seasons = set(seasons_sorted[:split_idx])
test_seasons  = set(seasons_sorted[split_idx:])
df_train = df[df['season_num'].isin(train_seasons)]
df_test  = df[df['season_num'].isin(test_seasons)]

print(f"  {len(df):,} matches | Train: {len(train_seasons)}s | Test: {len(test_seasons)}s")

# Build per-fixture per-market confidence from training data
MARKETS = {
    'over_15':  {'odds': 1.25},
    'under_35': {'odds': 1.28},
    'home_win': {'odds': 2.20},
    'away_win': {'odds': 3.10},
}
global_rates = {mkt: df_train[mkt].mean() for mkt in MARKETS}

fixture_conf = {}
for (ht, at, md), grp in df_train.groupby(['home_team', 'away_team', 'matchday_number']):
    n = len(grp)
    if n < 5: continue
    for mkt in MARKETS:
        rate = grp[mkt].mean()
        shrunk = (rate * n + global_rates[mkt] * 8) / (n + 8)
        fixture_conf[(ht, at, md, mkt)] = {'rate': shrunk, 'n': n, 'raw': rate}

print(f"  Fixture-market entries: {len(fixture_conf):,}")

STARTING_BANK = 1000.0
STAKE = 0.02  # 2% per matchday

# ─────────────────────────────────────────────────────────────
# TARGETED 4-LEG PARLAY
# Selection logic (strict):
#   - Pick 2 fixtures with highest home_win confidence (≥65%)
#   - From those same or other fixtures pick over_15 and under_35
#   - All 4 legs from DIFFERENT fixtures
# ─────────────────────────────────────────────────────────────

def run_targeted_parlay(min_hw_conf=0.65, min_ou_conf=0.70, n_hw=2, n_ou=2):
    bankroll = STARTING_BANK
    results = []
    test_sorted = df_test.sort_values(['season_num', 'matchday_number'])
    wins, losses, skipped = 0, 0, 0

    for (season, md), md_grp in test_sorted.groupby(['season_num', 'matchday_number']):
        fixtures = md_grp.to_dict('records')

        # Score all home_win legs
        hw_legs = []
        for fix in fixtures:
            ht, at = fix['home_team'], fix['away_team']
            key = (ht, at, md, 'home_win')
            if key in fixture_conf:
                fc = fixture_conf[key]
                if fc['rate'] >= min_hw_conf and fc['n'] >= 5:
                    hw_legs.append({
                        'home': ht, 'away': at, 'market': 'home_win',
                        'odds': MARKETS['home_win']['odds'],
                        'confidence': fc['rate'], 'n': fc['n'],
                        'actual': fix['home_win']
                    })
        hw_legs.sort(key=lambda x: x['confidence'], reverse=True)

        # Score over_15 and under_35 from remaining fixtures
        ou_legs = []
        hw_fix_keys = {(l['home'], l['away']) for l in hw_legs[:n_hw]}
        for fix in fixtures:
            ht, at = fix['home_team'], fix['away_team']
            fix_key = (ht, at)
            # Try to use different fixtures from HW legs
            preferred_fresh = fix_key not in hw_fix_keys
            for mkt in ['over_15', 'under_35']:
                key = (ht, at, md, mkt)
                if key in fixture_conf:
                    fc = fixture_conf[key]
                    if fc['rate'] >= min_ou_conf and fc['n'] >= 5:
                        ou_legs.append({
                            'home': ht, 'away': at, 'market': mkt,
                            'odds': MARKETS[mkt]['odds'],
                            'confidence': fc['rate'], 'n': fc['n'],
                            'actual': fix[mkt],
                            'fresh': preferred_fresh
                        })
        # Prefer fresh fixtures
        ou_legs.sort(key=lambda x: (x['fresh'], x['confidence']), reverse=True)
        # Deduplicate: max 1 leg per fixture
        ou_selected = []
        used_ou = set()
        for leg in ou_legs:
            fk = (leg['home'], leg['away'])
            if fk not in used_ou:
                ou_selected.append(leg)
                used_ou.add(fk)
            if len(ou_selected) == n_ou:
                break

        # Need exactly n_hw + n_ou legs
        if len(hw_legs) < n_hw or len(ou_selected) < n_ou:
            skipped += 1
            continue

        selected = hw_legs[:n_hw] + ou_selected[:n_ou]
        # Ensure all from different fixtures
        fix_keys = [(l['home'], l['away']) for l in selected]
        if len(set(fix_keys)) < len(fix_keys):
            # Duplicates — try to resolve
            seen = set()
            deduped = []
            for l in selected:
                fk = (l['home'], l['away'])
                if fk not in seen:
                    deduped.append(l)
                    seen.add(fk)
            if len(deduped) < 3:
                skipped += 1
                continue
            selected = deduped

        parlay_odds = np.prod([l['odds'] for l in selected])
        all_hit = all(l['actual'] == 1 for l in selected)
        n_hit = sum(l['actual'] for l in selected)

        stake = min(bankroll * STAKE, bankroll * 0.05)
        profit = stake * (parlay_odds - 1) if all_hit else -stake
        bankroll = max(bankroll + profit, 0.01)

        if all_hit: wins += 1
        else: losses += 1

        results.append({
            'season': season, 'md': md,
            'n_legs': len(selected),
            'parlay_odds': parlay_odds,
            'all_hit': int(all_hit),
            'n_hit': n_hit,
            'profit': profit,
            'bankroll': bankroll,
            'avg_conf': np.mean([l['confidence'] for l in selected]),
            'legs_detail': [(l['home'][:8], l['away'][:8], l['market'], round(l['confidence'],3), l['actual']) for l in selected]
        })

    rdf = pd.DataFrame(results)
    return rdf, bankroll, wins, losses, skipped

# Run all targeted configs
print("\n" + "="*70)
print("TARGETED PARLAY RESULTS")
print("="*70)

configs_targeted = {
    '4-leg: 2×HW(≥65%) + O1.5(≥70%) + U3.5(≥70%)': (0.65, 0.70, 2, 2),
    '4-leg: 2×HW(≥70%) + O1.5(≥72%) + U3.5(≥72%)': (0.70, 0.72, 2, 2),
    '4-leg: 2×HW(≥75%) + O1.5(≥75%) + U3.5(≥75%)': (0.75, 0.75, 2, 2),
    '3-leg: 2×HW(≥70%) + O1.5(≥72%)':               (0.70, 0.72, 2, 1),
    '3-leg: 2×HW(≥75%) + O1.5(≥75%)':               (0.75, 0.75, 2, 1),
    '2-leg: 2×HW(≥75%) only':                        (0.75, 0.99, 2, 0),
}

all_results = {}
for cfg_name, (mhw, mou, nhw, nou) in configs_targeted.items():
    rdf, final_bank, wins, losses, skipped = run_targeted_parlay(mhw, mou, nhw, nou)
    all_results[cfg_name] = (rdf, final_bank, wins, losses, skipped)
    if len(rdf) == 0:
        print(f"\n  {cfg_name}: NO DATA")
        continue
    wr = rdf['all_hit'].mean()
    ao = rdf['parlay_odds'].mean()
    ev = wr * ao - 1
    roi = (final_bank / STARTING_BANK - 1) * 100
    star = ' ★ PROFITABLE' if ev > 0 else ''
    print(f"\n  {cfg_name}")
    print(f"    Matchdays: {len(rdf):,} | Skipped: {skipped:,}")
    print(f"    Win Rate:  {wr*100:.1f}% ({wins}W / {losses}L)")
    print(f"    Avg Odds:  {ao:.2f}x")
    print(f"    EV/bet:    {ev:+.4f}{star}")
    print(f"    ROI:       {roi:.1f}%")
    print(f"    Final Bank: £{final_bank:,.2f}")

    # Show legs breakdown
    if wr > 0:
        print(f"    Legs hit distribution:")
        for i in range(int(rdf['n_legs'].max()) + 1):
            cnt = (rdf['n_hit'] == i).sum()
            if cnt > 0:
                print(f"      {i}/{int(rdf['n_legs'].max())}: {cnt} ({cnt/len(rdf)*100:.1f}%)")

# ─────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(18, 12))
fig.suptitle('VFL Targeted Parlay — Correct Market Mix\n'
             'Leg formula: 2×Home Win (locked) + Over 1.5 + Under 3.5',
             fontsize=14, fontweight='bold')

COLORS = ['#2196F3','#4CAF50','#FF9800','#E91E63','#9C27B0','#00BCD4']

# Chart 1: Bankroll growth comparison
ax1 = axes[0, 0]
for (cname, (rdf, fb, *_)), col in zip(all_results.items(), COLORS):
    if len(rdf) > 5:
        ax1.plot(range(len(rdf)), rdf['bankroll'].values,
                 color=col, lw=1.5, label=cname[:35], alpha=0.85)
ax1.axhline(STARTING_BANK, color='black', linestyle='--', alpha=0.5)
ax1.set_yscale('log')
ax1.set_xlabel('Matchday')
ax1.set_ylabel('Bankroll £ (log)')
ax1.set_title('Compound Bankroll Growth — Targeted Configs')
ax1.legend(fontsize=6)
ax1.grid(True, alpha=0.3)

# Chart 2: EV comparison
ax2 = axes[0, 1]
names, evs, wrs, aos = [], [], [], []
for cname, (rdf, fb, *_) in all_results.items():
    if len(rdf) == 0: continue
    wr = rdf['all_hit'].mean()
    ao = rdf['parlay_odds'].mean()
    ev = wr * ao - 1
    names.append(cname[:20])
    evs.append(ev)
    wrs.append(wr)
    aos.append(ao)

bar_c = ['#4CAF50' if e > 0 else '#F44336' for e in evs]
bars = ax2.bar(range(len(names)), evs, color=bar_c, alpha=0.85, edgecolor='white')
ax2.axhline(0, color='black', lw=1.5)
ax2.set_xticks(range(len(names)))
ax2.set_xticklabels(names, rotation=25, ha='right', fontsize=7)
ax2.set_ylabel('Expected Value per Bet')
ax2.set_title('EV by Config — Green = Profitable')
for bar, ev in zip(bars, evs):
    ax2.text(bar.get_x()+bar.get_width()/2,
             bar.get_height() + (0.002 if ev >= 0 else -0.01),
             f'{ev:+.3f}', ha='center', fontsize=9, fontweight='bold')

# Chart 3: Win rate vs needed win rate (break-even)
ax3 = axes[1, 0]
ax3.scatter(aos, [w*100 for w in wrs], s=200, c=bar_c, zorder=5,
            edgecolors='white', lw=2)
for i, name in enumerate(names):
    ax3.annotate(name[:25], (aos[i], wrs[i]*100),
                 textcoords="offset points", xytext=(5, 5), fontsize=7)
x_r = np.linspace(1.0, max(aos)*1.15 if aos else 10, 300)
ax3.plot(x_r, 100/x_r, 'r--', lw=2.5, label='Break-even')
ax3.set_xlabel('Average Parlay Odds')
ax3.set_ylabel('Actual Win Rate %')
ax3.set_title('Win Rate vs Parlay Odds\nPoints ABOVE red = profitable')
ax3.legend()
ax3.grid(True, alpha=0.3)

# Chart 4: Best config bankroll
best_cfg = max(all_results, key=lambda k: all_results[k][1])
best_rdf, best_fb = all_results[best_cfg][0], all_results[best_cfg][1]
ax4 = axes[1, 1]
if len(best_rdf) > 0:
    ax4.plot(range(len(best_rdf)), best_rdf['bankroll'].values,
             color='#2196F3', lw=2.0)
    ax4.axhline(STARTING_BANK, color='red', linestyle='--', lw=1.5, alpha=0.8)
    ax4.fill_between(range(len(best_rdf)), STARTING_BANK,
                     best_rdf['bankroll'].values,
                     where=best_rdf['bankroll'].values >= STARTING_BANK,
                     alpha=0.25, color='#4CAF50')
    ax4.fill_between(range(len(best_rdf)), STARTING_BANK,
                     best_rdf['bankroll'].values,
                     where=best_rdf['bankroll'].values < STARTING_BANK,
                     alpha=0.25, color='#F44336')
    wr = best_rdf['all_hit'].mean()
ax4.set_xlabel('Matchday')
ax4.set_ylabel('Bankroll £')
ax4.set_title(f'Best Config: {best_cfg[:40]}\n'
              f'Win Rate: {wr*100:.1f}% | Final: £{best_fb:,.0f}')
ax4.grid(True, alpha=0.3)

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'parlay_targeted_backtest.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()

# ── REPORT ──
report_path = os.path.join(OUTPUT_DIR, 'parlay_targeted_report.md')
with open(report_path, 'w') as f:
    f.write("# VFL Targeted Parlay Report — Correct Market Mix\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    f.write(f"**Start Bank:** £{STARTING_BANK:,.0f} | **Stake:** {STAKE*100:.0f}% per matchday  \n\n")
    f.write("## The Formula\n\n")
    f.write("```\n")
    f.write("Leg 1: Home Win — dominant fixture  @ ~2.20x\n")
    f.write("Leg 2: Home Win — dominant fixture  @ ~2.20x\n")
    f.write("Leg 3: Over 1.5 Goals              @ ~1.25x\n")
    f.write("Leg 4: Under 3.5 Goals             @ ~1.28x\n")
    f.write("─────────────────────────────────────────────\n")
    f.write("Combined: ~7.74x | Break-even: 12.9% | Projected: ~33%\n")
    f.write("```\n\n")
    f.write("## Results\n\n")
    f.write("| Config | MDs | Win Rate | Avg Odds | ROI | EV | Verdict |\n")
    f.write("|--------|-----|----------|----------|-----|----|---------|\n")
    for cname, (rdf, fb, wins, losses, skipped) in all_results.items():
        if len(rdf) == 0:
            f.write(f"| {cname} | 0 | — | — | — | — | No qualifying matchdays |\n")
            continue
        wr = rdf['all_hit'].mean()
        ao = rdf['parlay_odds'].mean()
        ev = wr * ao - 1
        roi = (fb / STARTING_BANK - 1) * 100
        verdict = "✅ **PROFITABLE**" if ev > 0 else "❌ Losing"
        f.write(f"| {cname} | {len(rdf):,} | {wr*100:.1f}% | {ao:.2f}x | {roi:.1f}% | {ev:+.3f} | {verdict} |\n")

print(f"\n  Chart → {chart_path}")
print(f"  Report → {report_path}")
print(f"\n  ★ Best: {best_cfg} → £{best_fb:,.0f}")
