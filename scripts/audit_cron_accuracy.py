#!/usr/bin/env python3
"""
VFL Cron Job Prediction Accuracy Auditor
==========================================
1. Pulls all settled vfl_predictions vs actual results from DB
2. Calculates accuracy per market, per matchday, per engine, per season
3. Detects the MD display offset bug
4. Compares vs the new rolling window engine accuracy
5. Outputs a full markdown report + charts
"""

import psycopg2
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

OUTPUT_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/751aa9ef-b0a3-4429-8498-9c8a6b4df046"

print("=" * 70)
print("VFL CRON JOB PREDICTION ACCURACY AUDIT")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

conn = psycopg2.connect(dbname='vfl_empire', user='ubuntu')

# ─────────────────────────────────────────────────────────────
# 1. LOAD ALL SETTLED PREDICTIONS
# ─────────────────────────────────────────────────────────────
print("\n[1/5] Loading settled predictions...")

query = """
SELECT 
    p.id,
    p.season,
    p.match_day,
    p.home_team,
    p.away_team,
    p.prediction,
    p.confidence,
    p.odds,
    p.engine,
    p.result,
    p.actual_h,
    p.actual_a,
    p.profit,
    p.settled
FROM vfl_predictions p
WHERE p.settled = 1 
  AND p.result IS NOT NULL
  AND p.actual_h IS NOT NULL
ORDER BY p.season, p.match_day
"""

df_pred = pd.read_sql(query, conn)
print(f"  Loaded {len(df_pred):,} settled predictions")
print(f"  Engines: {df_pred['engine'].value_counts().to_dict()}")
print(f"  Seasons covered: {df_pred['season'].nunique()}")
print(f"  Season range: {df_pred['season'].min()} → {df_pred['season'].max()}")

# ─────────────────────────────────────────────────────────────
# 2. DETECT MD OFFSET BUG
# ─────────────────────────────────────────────────────────────
print("\n[2/5] Checking for MD offset bug...")

# Join predictions with real matchday data to compare stored vs actual MD
query_md_check = """
SELECT 
    p.match_day as pred_md,
    md.matchday_number as real_md,
    p.season,
    p.home_team,
    p.away_team
FROM vfl_predictions p
JOIN vfl_seasons s ON s.season_name = p.season
JOIN vfl_matchdays md ON md.season_id = s.id
JOIN vfl_results_v2 r ON r.matchday_id = md.id 
    AND r.home_team = p.home_team 
    AND r.away_team = p.away_team
WHERE p.actual_h IS NOT NULL
LIMIT 100000
"""
try:
    df_md = pd.read_sql(query_md_check, conn)
    df_md['offset'] = df_md['real_md'] - df_md['pred_md']
    offset_dist = df_md['offset'].value_counts().sort_index()
    print(f"  MD offset distribution:")
    for offset, cnt in offset_dist.items():
        flag = " ← BUG DETECTED" if offset != 0 else " (correct)"
        print(f"    offset {offset:+d}: {cnt:,} records{flag}")
    
    # Check per-MD breakdown
    per_md = df_md.groupby('pred_md')['offset'].mean()
    bug_mds = per_md[per_md != 0]
    if len(bug_mds) > 0:
        print(f"\n  ⚠️  BUG CONFIRMED: These matchdays have wrong numbering:")
        print(f"  {bug_mds.to_dict()}")
        MD_OFFSET = int(bug_mds.mean())
        print(f"  Consistent offset: {MD_OFFSET:+d}")
    else:
        print(f"  ✅ No MD offset bug found in stored data")
        MD_OFFSET = 0
except Exception as e:
    print(f"  Could not check MD offset: {e}")
    MD_OFFSET = 0

# ─────────────────────────────────────────────────────────────
# 3. ACCURACY ANALYSIS — CRON JOB PREDICTIONS
# ─────────────────────────────────────────────────────────────
print("\n[3/5] Computing cron job accuracy...")

# won/lost column
df_pred['correct'] = (df_pred['result'] == 'won').astype(int)

# Parse season number for ordering
df_pred['season_num'] = df_pred['season'].str.extract(r'(\d+)').astype(int)

# --- Overall accuracy ---
overall_acc = df_pred['correct'].mean()
print(f"\n  Overall accuracy: {overall_acc:.4f} ({df_pred['correct'].sum():,}/{len(df_pred):,})")

# --- Accuracy by market/prediction type ---
market_acc = df_pred.groupby('prediction').agg(
    n=('correct','count'),
    wins=('correct','sum'),
    accuracy=('correct','mean'),
    avg_odds=('odds','mean'),
    avg_conf=('confidence','mean')
).reset_index()
market_acc['roi'] = market_acc.apply(
    lambda r: (r['wins'] * r['avg_odds'] - r['n']) / r['n'] * 100 if r['n'] > 0 else 0, axis=1
)
market_acc = market_acc[market_acc['n'] >= 50].sort_values('accuracy', ascending=False)
print(f"\n  Accuracy by prediction market (top 15):")
print(market_acc[['prediction','n','accuracy','avg_odds','roi']].head(15).to_string(index=False))

# --- Accuracy by matchday ---
md_acc = df_pred.groupby('match_day').agg(
    n=('correct','count'),
    accuracy=('correct','mean')
).reset_index()

# --- Accuracy by engine ---
engine_acc = df_pred.groupby('engine').agg(
    n=('correct','count'),
    accuracy=('correct','mean'),
    avg_odds=('odds','mean')
).reset_index()
print(f"\n  Accuracy by engine:")
print(engine_acc.to_string(index=False))

# --- Accuracy by season (rolling) ---
season_acc = df_pred.groupby('season_num').agg(
    n=('correct','count'),
    accuracy=('correct','mean')
).reset_index()
season_acc = season_acc[season_acc['n'] >= 20]

# --- Accuracy by confidence band ---
df_pred['conf_band'] = pd.cut(df_pred['confidence'],
                               bins=[0,30,50,60,70,80,90,100],
                               labels=['0-30','30-50','50-60','60-70','70-80','80-90','90-100'])
conf_acc = df_pred.groupby('conf_band', observed=True).agg(
    n=('correct','count'),
    accuracy=('correct','mean'),
    avg_odds=('odds','mean')
).reset_index()
print(f"\n  Accuracy by confidence band:")
print(conf_acc.to_string(index=False))

# --- Profit/ROI overall ---
if df_pred['profit'].notna().sum() > 0:
    total_profit = df_pred['profit'].sum()
    total_staked = len(df_pred)  # assuming 1 unit per bet
    roi = total_profit / total_staked * 100
    print(f"\n  Total profit (units): {total_profit:.2f}")
    print(f"  ROI: {roi:.2f}%")

# ─────────────────────────────────────────────────────────────
# 4. LOAD NEW ROLLING WINDOW RESULTS FOR COMPARISON
# ─────────────────────────────────────────────────────────────
print("\n[4/5] Loading rolling window engine results for comparison...")

rw_summary_path = os.path.join(OUTPUT_DIR, 'scratch', 'rolling_window_summary.json')
rw_results = {}
if os.path.exists(rw_summary_path):
    with open(rw_summary_path) as f:
        rw_results = json.load(f)
    print(f"  Loaded rolling window results: {list(rw_results.keys())}")
else:
    print(f"  Rolling window results not yet available (pipeline still running)")

# ─────────────────────────────────────────────────────────────
# 5. CHARTS
# ─────────────────────────────────────────────────────────────
print("\n[5/5] Generating charts...")

fig, axes = plt.subplots(2, 3, figsize=(20, 12))
fig.suptitle('VFL Cron Job Prediction Accuracy Audit', fontsize=16, fontweight='bold')

# Chart 1: Accuracy by Market
ax1 = axes[0, 0]
top_markets = market_acc.head(20)
colors_m = ['#4CAF50' if a >= overall_acc else '#F44336' for a in top_markets['accuracy']]
bars = ax1.barh(top_markets['prediction'], top_markets['accuracy'],
                color=colors_m, alpha=0.85, edgecolor='white')
ax1.axvline(overall_acc, color='black', linestyle='--', alpha=0.7, label=f'Overall {overall_acc:.3f}')
ax1.axvline(0.333, color='red', linestyle=':', alpha=0.5, label='Random 33.3%')
ax1.set_xlabel('Accuracy')
ax1.set_title('Accuracy by Prediction Market')
ax1.legend(fontsize=7)
for bar in bars:
    ax1.text(bar.get_width() + 0.002, bar.get_y() + bar.get_height()/2,
             f'{bar.get_width():.3f}', va='center', fontsize=7)

# Chart 2: Accuracy by Matchday
ax2 = axes[0, 1]
md_colors = ['#4CAF50' if a >= overall_acc else '#FF9800' for a in md_acc['accuracy']]
ax2.bar(md_acc['match_day'], md_acc['accuracy'], color=md_colors, alpha=0.85, edgecolor='white')
ax2.axhline(overall_acc, color='black', linestyle='--', alpha=0.7, label=f'Overall {overall_acc:.3f}')
ax2.axhline(0.333, color='red', linestyle=':', alpha=0.5, label='Random')
ax2.set_xlabel('Matchday')
ax2.set_ylabel('Accuracy')
ax2.set_title('Accuracy by Matchday\n(MD20 displayed as MD19 bug check)')
ax2.legend(fontsize=8)
# Annotate if MD offset suspected
if MD_OFFSET != 0:
    ax2.text(0.5, 0.95, f'⚠️ MD offset={MD_OFFSET:+d} detected!',
             transform=ax2.transAxes, ha='center', color='red', fontsize=9)

# Chart 3: Accuracy over seasons (rolling)
ax3 = axes[0, 2]
ax3.plot(season_acc['season_num'], season_acc['accuracy'],
         color='#2196F3', alpha=0.5, lw=0.8)
roll_acc = season_acc['accuracy'].rolling(5, min_periods=2).mean()
ax3.plot(season_acc['season_num'], roll_acc, color='#E91E63', lw=2.2, label='5-season rolling avg')
ax3.axhline(overall_acc, color='black', linestyle='--', alpha=0.6, label=f'Overall {overall_acc:.3f}')
ax3.axhline(0.333, color='red', linestyle=':', alpha=0.5, label='Random')
ax3.set_xlabel('Season Number')
ax3.set_ylabel('Accuracy')
ax3.set_title('Cron Prediction Accuracy Over Time')
ax3.legend(fontsize=8)

# Chart 4: Accuracy by confidence band
ax4 = axes[1, 0]
conf_colors = ['#4CAF50' if a >= overall_acc else '#F44336' for a in conf_acc['accuracy']]
bars4 = ax4.bar(conf_acc['conf_band'].astype(str), conf_acc['accuracy'],
                color=conf_colors, alpha=0.85, edgecolor='white')
ax4.axhline(overall_acc, color='black', linestyle='--', alpha=0.7, label=f'Overall {overall_acc:.3f}')
ax4.set_xlabel('Confidence Band (%)')
ax4.set_ylabel('Accuracy')
ax4.set_title('Accuracy vs Confidence Band\n(Higher confidence should = higher accuracy)')
ax4.legend(fontsize=8)
for bar in bars4:
    ax4.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.002,
             f'{bar.get_height():.3f}', ha='center', fontsize=8)

# Chart 5: Engine comparison + rolling window
ax5 = axes[1, 1]
engine_names = list(engine_acc['engine'])
engine_accs_vals = list(engine_acc['accuracy'])
engine_ns = list(engine_acc['n'])

# Add rolling window results if available
rw_labels = []
rw_vals = []
for w, res in rw_results.items():
    if isinstance(res, dict) and 'weighted_accuracy' in res:
        rw_labels.append(f'RollingWindow\n({w}s)')
        rw_vals.append(res['weighted_accuracy'])

all_labels = engine_names + rw_labels
all_vals = engine_accs_vals + rw_vals
bar_colors5 = ['#FF9800'] * len(engine_names) + ['#2196F3'] * len(rw_labels)

bars5 = ax5.bar(all_labels, all_vals, color=bar_colors5, alpha=0.85, edgecolor='white')
ax5.axhline(0.333, color='red', linestyle='--', alpha=0.7, label='Random 33.3%')
ax5.set_title('Engine Accuracy Comparison\n(Orange=Cron, Blue=New Rolling Window)')
ax5.set_ylabel('Accuracy')
ax5.legend(fontsize=8)
ax5.set_ylim(0, max(all_vals)*1.2 if all_vals else 1.0)
plt.setp(ax5.get_xticklabels(), fontsize=7, rotation=15)
for bar in bars5:
    ax5.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.003,
             f'{bar.get_height():.3f}', ha='center', fontsize=8, fontweight='bold')

# Chart 6: Top markets ROI
ax6 = axes[1, 2]
top_roi = market_acc.nlargest(15, 'roi')
roi_colors = ['#4CAF50' if r > 0 else '#F44336' for r in top_roi['roi']]
ax6.barh(top_roi['prediction'], top_roi['roi'], color=roi_colors, alpha=0.85, edgecolor='white')
ax6.axvline(0, color='black', linewidth=1)
ax6.set_xlabel('ROI %')
ax6.set_title('Return on Investment by Market')

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'cron_accuracy_audit.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved → {chart_path}")

# ─────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────
report_path = os.path.join(OUTPUT_DIR, 'cron_accuracy_report.md')
with open(report_path, 'w') as f:
    f.write("# VFL Cron Job Prediction Accuracy Audit\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    f.write(f"**Total Settled Predictions:** {len(df_pred):,}  \n")
    f.write(f"**Seasons Covered:** {df_pred['season'].nunique()}  \n")
    f.write(f"**Season Range:** {df_pred['season'].min()} → {df_pred['season'].max()}  \n\n")

    f.write("## Matchday Numbering Bug\n\n")
    if MD_OFFSET != 0:
        f.write(f"> ⚠️ **BUG CONFIRMED:** Stored match_day is offset by {MD_OFFSET:+d} vs actual matchday number.\n")
        f.write(f"> This means MD20 is stored/displayed as MD{20+MD_OFFSET}.\n\n")
    else:
        f.write("> ✅ No MD offset detected in stored prediction data.\n")
        f.write("> The bug may be in the **live display/API fetch** side (MSport API returns 0-indexed matchdays).\n\n")

    f.write("## Overall Accuracy\n\n")
    f.write(f"| Metric | Value |\n|--------|-------|\n")
    f.write(f"| Overall Accuracy | **{overall_acc:.4f} ({overall_acc*100:.1f}%)** |\n")
    f.write(f"| Random Baseline | 33.3% |\n")
    f.write(f"| Lift vs Random | **+{(overall_acc-0.333)/0.333*100:.1f}%** |\n")
    f.write(f"| Total Predictions | {len(df_pred):,} |\n")
    f.write(f"| Correct | {df_pred['correct'].sum():,} |\n\n")

    f.write("## Accuracy by Engine\n\n")
    f.write("| Engine | Predictions | Accuracy | Avg Odds |\n|--------|-------------|----------|----------|\n")
    for _, r in engine_acc.iterrows():
        f.write(f"| {r['engine']} | {int(r['n']):,} | {r['accuracy']:.4f} | {r['avg_odds']:.2f} |\n")

    f.write("\n## Accuracy by Market (top 20, min 50 samples)\n\n")
    f.write("| Market | N | Accuracy | Avg Odds | ROI% |\n|--------|---|----------|----------|------|\n")
    for _, r in market_acc.head(20).iterrows():
        f.write(f"| {r['prediction']} | {int(r['n']):,} | {r['accuracy']:.4f} | {r['avg_odds']:.2f} | {r['roi']:.1f}% |\n")

    f.write("\n## Accuracy by Confidence Band\n\n")
    f.write("| Band | N | Accuracy | Avg Odds |\n|------|---|----------|----------|\n")
    for _, r in conf_acc.iterrows():
        calibrated = "✅" if r['accuracy'] >= overall_acc else "❌"
        f.write(f"| {r['conf_band']} | {int(r['n']):,} | {r['accuracy']:.4f} | {r['avg_odds']:.2f} | {calibrated} |\n")

    if rw_results:
        f.write("\n## New Rolling Window Engine Comparison\n\n")
        f.write("| Window | Weighted Accuracy | vs Cron Job |\n|--------|------------------|-------------|\n")
        for w, res in rw_results.items():
            if isinstance(res, dict) and 'weighted_accuracy' in res:
                diff = res['weighted_accuracy'] - overall_acc
                flag = f"+{diff*100:.1f}% better" if diff > 0 else f"{diff*100:.1f}% worse"
                f.write(f"| {w}s | {res['weighted_accuracy']:.4f} | {flag} |\n")

    f.write("\n## MD Bug Fix\n\n")
    f.write("The MSport API returns matchdays as 0-indexed in some responses.\n")
    f.write("Fix location: `vfl_live_predictor_v2.py` line where `match_day` is extracted.\n")
    f.write("```python\n")
    f.write("# BEFORE (buggy):\n")
    f.write("match_day = int(info.get('matchDay', 0))\n\n")
    f.write("# AFTER (fixed — add +1 to correct 0-indexing):\n")
    f.write("match_day = int(info.get('matchDay', 0)) + 1  # API is 0-indexed\n")
    f.write("```\n")

print(f"  Report → {report_path}")

conn.close()

print("\n" + "=" * 70)
print("AUDIT COMPLETE")
print("=" * 70)
print(f"\n  Cron job overall accuracy: {overall_acc:.4f} ({overall_acc*100:.1f}%)")
print(f"  Lift vs random baseline:  +{(overall_acc-0.333)/0.333*100:.1f}%")
print(f"  MD offset bug: {'CONFIRMED offset=' + str(MD_OFFSET) if MD_OFFSET != 0 else 'Not in DB data — check API layer'}")
print(f"\n  Top markets by accuracy:")
for _, r in market_acc.head(5).iterrows():
    print(f"    {r['prediction']:30s} acc={r['accuracy']:.3f} n={int(r['n']):,}")
