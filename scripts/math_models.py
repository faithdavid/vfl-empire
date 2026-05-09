#!/usr/bin/env python3
"""Sage's VFL Mathematical Prediction Engine v2
   Optimized for 50k+ matches
"""
import sqlite3, json, math, sys, os, time
import numpy as np
from collections import defaultdict, Counter
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss

DB = '/home/faith/Documents/Projects/vfl-data/databases/history.db'
OUT = '/home/faith/Documents/Projects/vfl-data/analysis/math-models.json'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("Loading data...", flush=True)
rows_all = conn.execute("""
    SELECT season, day, home, away, oh, od, oa, outcome, h, a
    FROM matches
    WHERE outcome IS NOT NULL AND oh IS NOT NULL AND h IS NOT NULL
    AND outcome IN ('HOME','DRAW','AWAY')
    ORDER BY season, day
""").fetchall()

print(f"Total matches: {len(rows_all)}", flush=True)

# ============================================================
# 1. TEAM STATS & TIERS
# ============================================================
team_goals_for = defaultdict(list)
team_goals_against = defaultdict(list)
team_results = defaultdict(list)

for r in rows_all:
    hg, ag = r['h'], r['a']
    team_goals_for[r['home']].append(hg)
    team_goals_for[r['away']].append(ag)
    team_goals_against[r['home']].append(ag)
    team_goals_against[r['away']].append(hg)
    team_results[r['home']].append(1 if r['outcome'] == 'HOME' else (0.5 if r['outcome'] == 'DRAW' else 0))
    team_results[r['away']].append(1 if r['outcome'] == 'AWAY' else (0.5 if r['outcome'] == 'DRAW' else 0))

all_teams = sorted(set(r['home'] for r in rows_all) | set(r['away'] for r in rows_all))
print(f"Teams: {len(all_teams)}", flush=True)

team_win_rate = {t: np.mean(team_results[t]) for t in all_teams}
wrs = sorted(team_win_rate.values())
p25, p50, p75 = np.percentile(wrs, [25, 50, 75])
tier_map = {}
for t in all_teams:
    wr = team_win_rate[t]
    if wr >= p75: tier_map[t] = 1
    elif wr >= p50: tier_map[t] = 2
    elif wr >= p25: tier_map[t] = 3
    else: tier_map[t] = 4
print(f"Tier dist: {dict(Counter(tier_map.values()))}", flush=True)

# ============================================================
# 2. TRAIN/TEST SPLIT
# ============================================================
split_idx = int(len(rows_all) * 0.7)
train_rows = rows_all[:split_idx]
test_rows = rows_all[split_idx:]
n_train, n_test = len(train_rows), len(test_rows)
print(f"Train: {n_train}, Test: {n_test}", flush=True)

# ---- Global stats ----
avg_home_goals = np.mean([r['h'] for r in rows_all])
avg_away_goals = np.mean([r['a'] for r in rows_all])
team_attack = {t: np.mean(team_goals_for[t]) / avg_home_goals for t in all_teams}
team_defense = {t: np.mean(team_goals_against[t]) / avg_away_goals for t in all_teams}

# ---- Train-only stats for unbiased backtest ----
tr_gf = defaultdict(list); tr_ga = defaultdict(list)
for r in train_rows:
    tr_gf[r['home']].append(r['h']); tr_gf[r['away']].append(r['a'])
    tr_ga[r['home']].append(r['a']); tr_ga[r['away']].append(r['h'])
tr_avg_hg = np.mean([r['h'] for r in train_rows])
tr_avg_ag = np.mean([r['a'] for r in train_rows])
tr_attack = {t: np.mean(tr_gf[t])/tr_avg_hg if tr_gf[t] else 1.0 for t in all_teams}
tr_defense = {t: np.mean(tr_ga[t])/tr_avg_ag if tr_ga[t] else 1.0 for t in all_teams}

# ============================================================
# 3. POISSON MODEL (vectorized test prediction)
# ============================================================
print("\n=== POISSON ===", flush=True)

def poisson_vec(home, away, ha=1.10):
    """Poisson probs using train stats"""
    lh = tr_avg_hg * tr_attack.get(home, 1.0) * tr_defense.get(away, 1.0) * ha
    la = tr_avg_ag * tr_attack.get(away, 1.0) * tr_defense.get(home, 1.0) / ha
    return lh, la

def pmf_grid(lam_h, lam_a, max_g=10):
    """Compute P(H), P(D), P(A) from Poisson grid"""
    hs = np.arange(max_g+1)
    as_ = np.arange(max_g+1)
    ph_grid = poisson.pmf(hs[:, None], lam_h)
    pa_grid = poisson.pmf(as_[None, :], lam_a)
    joint = ph_grid * pa_grid
    p_home = joint[np.triu_indices(max_g+1, 1)].sum()
    p_draw = np.diag(joint).sum()
    p_away = joint[np.tril_indices(max_g+1, -1)].sum()
    return p_home, p_draw, p_away

poisson_correct = 0
poisson_brier = 0.0
for idx, r in enumerate(test_rows):
    lh, la = poisson_vec(r['home'], r['away'])
    ph, pd, pa = pmf_grid(lh, la, 10)
    pred = 'HOME' if ph >= max(ph, pd, pa) else ('DRAW' if pd >= max(ph, pa) else 'AWAY')
    if pred == r['outcome']: poisson_correct += 1
    a = r['outcome']
    if a == 'HOME': b = (ph-1)**2+pd**2+pa**2
    elif a == 'DRAW': b = ph**2+(pd-1)**2+pa**2
    else: b = ph**2+pd**2+(pa-1)**2
    poisson_brier += b

poisson_acc = poisson_correct / n_test
poisson_brier_avg = poisson_brier / n_test
print(f"Accuracy: {poisson_acc:.4f}, Brier: {poisson_brier_avg:.4f}", flush=True)

# Market baseline
market_correct = 0
for r in test_rows:
    imp = np.array([1/r['oh'], 1/r['od'], 1/r['oa']])
    imp /= imp.sum()
    if imp.argmax() == 0: pred = 'HOME'
    elif imp.argmax() == 1: pred = 'DRAW'
    else: pred = 'AWAY'
    if pred == r['outcome']: market_correct += 1
market_acc = market_correct / n_test
print(f"Market accuracy: {market_acc:.4f}, Poisson edge: {poisson_acc-market_acc:+.4f}", flush=True)

# ============================================================
# 4. BAYESIAN MODEL
# ============================================================
print("\n=== BAYESIAN ===", flush=True)

# Tier priors
tier_prior = defaultdict(lambda: {'H': 0, 'D': 0, 'A': 0, 't': 0})
for r in train_rows:
    k = f"{tier_map[r['home']]}-{tier_map[r['away']]}"
    tier_prior[k][r['outcome'][0]] += 1
    tier_prior[k]['t'] += 1
for k in tier_prior:
    t = tier_prior[k]['t']
    if t > 0:
        tier_prior[k]['Hp'] = tier_prior[k]['H']/t
        tier_prior[k]['Dp'] = tier_prior[k]['D']/t
        tier_prior[k]['Ap'] = tier_prior[k]['A']/t

# Precompute team match indices
team_match_idx = defaultdict(list)
for i, r in enumerate(rows_all):
    team_match_idx[r['home']].append(i)
    team_match_idx[r['away']].append(i)

# Build rolling form efficiently: precompute outcome arrays per team
# outcome_code: 2=win, 1=draw, 0=loss (from team's perspective)
team_seq = defaultdict(list)
for i, r in enumerate(rows_all):
    # Home perspective
    if r['outcome'] == 'HOME': team_seq[r['home']].append(2)
    elif r['outcome'] == 'DRAW': team_seq[r['home']].append(1)
    else: team_seq[r['home']].append(0)
    # Away perspective
    if r['outcome'] == 'AWAY': team_seq[r['away']].append(2)
    elif r['outcome'] == 'DRAW': team_seq[r['away']].append(1)
    else: team_seq[r['away']].append(0)

# Map match_idx -> position in team's sequence
team_seq_pos = defaultdict(dict)
team_pos_count = defaultdict(int)
for i, r in enumerate(rows_all):
    team_seq_pos[r['home']][i] = team_pos_count[r['home']]
    team_pos_count[r['home']] += 1
    team_seq_pos[r['away']][i] = team_pos_count[r['away']]
    team_pos_count[r['away']] += 1

fw = 0.35
bayes_correct = 0
bayes_brier = 0.0
prior_only_correct = 0

for idx, r in enumerate(test_rows):
    ti = split_idx + idx
    home, away = r['home'], r['away']
    ht, at = tier_map.get(home, 2), tier_map.get(away, 2)
    k = f"{ht}-{at}"

    # Prior
    p = tier_prior.get(k, {'Hp': 0.45, 'Dp': 0.25, 'Ap': 0.30})
    ph_p, pd_p, pa_p = p['Hp'], p['Dp'], p['Ap']

    # Prior-only baseline
    mx = max(ph_p, pd_p, pa_p)
    if ph_p == mx: ppred = 'HOME'
    elif pd_p == mx: ppred = 'DRAW'
    else: ppred = 'AWAY'
    if ppred == r['outcome']: prior_only_correct += 1

    # Form evidence
    h_seq = team_seq[home]; a_seq = team_seq[away]
    h_pos = team_seq_pos[home].get(ti, len(h_seq))
    a_pos = team_seq_pos[away].get(ti, len(a_seq))

    h_form = np.mean(h_seq[max(0, h_pos-5):h_pos]) / 2.0 if h_pos > 0 else 0.5
    a_form = np.mean(a_seq[max(0, a_pos-5):a_pos]) / 2.0 if a_pos > 0 else 0.5

    if h_pos >= 3 and a_pos >= 3:
        if h_form > a_form + 0.2: fe = {'H': 0.6, 'D': 0.25, 'A': 0.15}
        elif a_form > h_form + 0.2: fe = {'H': 0.2, 'D': 0.25, 'A': 0.55}
        else: fe = {'H': 0.4, 'D': 0.3, 'A': 0.3}
        ph = (1-fw)*ph_p + fw*fe['H']
        pd = (1-fw)*pd_p + fw*fe['D']
        pa = (1-fw)*pa_p + fw*fe['A']
    else:
        ph, pd, pa = ph_p, pd_p, pa_p

    tot = ph+pd+pa; ph/=tot; pd/=tot; pa/=tot
    pred = 'HOME' if ph >= max(ph, pd, pa) else ('DRAW' if pd >= max(ph, pa) else 'AWAY')
    if pred == r['outcome']: bayes_correct += 1

    a = r['outcome']
    if a == 'HOME': b = (ph-1)**2+pd**2+pa**2
    elif a == 'DRAW': b = ph**2+(pd-1)**2+pa**2
    else: b = ph**2+pd**2+(pa-1)**2
    bayes_brier += b

bayes_acc = bayes_correct / n_test
prior_acc = prior_only_correct / n_test
print(f"Prior: {prior_acc:.4f}, Posterior: {bayes_acc:.4f}, Edge: {bayes_acc-prior_acc:+.4f}", flush=True)

# ============================================================
# 5. LOGISTIC REGRESSION (optimized feature building)
# ============================================================
print("\n=== LOGISTIC REGRESSION ===", flush=True)

# Precompute recent wins using cumulative sums
# For each team, track cumulative wins at each position
team_cum_wins = defaultdict(list)
team_cum_matches = defaultdict(list)
for i, r in enumerate(rows_all):
    for team, is_home in [(r['home'], True), (r['away'], False)]:
        if is_home:
            pts = 3 if r['outcome'] == 'HOME' else (1 if r['outcome'] == 'DRAW' else 0)
        else:
            pts = 3 if r['outcome'] == 'AWAY' else (1 if r['outcome'] == 'DRAW' else 0)
        prev_wins = team_cum_wins[team][-1] if team_cum_wins[team] else 0
        prev_n = team_cum_matches[team][-1] if team_cum_matches[team] else 0
        team_cum_wins[team].append(prev_wins + (1 if pts == 3 else 0))
        team_cum_matches[team].append(prev_n + 1)

# Build features efficiently
print("Building features...", flush=True)
season_days = {}
for r in rows_all:
    s = r['season']
    season_days[s] = max(season_days.get(s, 0), r['day'])

# Precompute index for each team match for fast lookup
team_pos_map = defaultdict(list)
for i, r in enumerate(rows_all):
    team_pos_map[r['home']].append(i)
    team_pos_map[r['away']].append(i)

def get_recent_wins_at(team, match_idx, last_n=5):
    """Get team's wins in last N matches before match_idx"""
    positions = team_pos_map[team]
    # Binary search for position
    import bisect
    pos = bisect.bisect_left(positions, match_idx)
    if pos == 0:
        return 0
    start = max(0, pos - last_n)
    end = pos
    if start == 0:
        return team_cum_wins[team][end - 1]
    else:
        return team_cum_wins[team][end - 1] - team_cum_wins[team][start - 1]

import bisect

X_list, y_list = [], []
for i, r in enumerate(rows_all):
    ht = tier_map[r['home']]
    at = tier_map[r['away']]

    imp_h = 1/r['oh']; imp_d = 1/r['od']; imp_a = 1/r['oa']
    imp_sum = imp_h + imp_d + imp_a

    h_rw = get_recent_wins_at(r['home'], i, 5)
    a_rw = get_recent_wins_at(r['away'], i, 5)

    feat = [
        ht, at, ht-at, abs(ht-at),
        imp_h/imp_sum, imp_d/imp_sum, imp_a/imp_sum,
        r['oh'], r['od'], r['oa'],
        r['day'] / max(season_days.get(r['season'], 30), 1),
        h_rw, a_rw, h_rw - a_rw
    ]
    X_list.append(feat)
    y_list.append(0 if r['outcome'] == 'HOME' else (1 if r['outcome'] == 'DRAW' else 2))

X = np.array(X_list, dtype=np.float64)
y = np.array(y_list)
print(f"Features: {X.shape}", flush=True)

# Split
X_tr, y_tr = X[:split_idx], y[:split_idx]
X_te, y_te = X[split_idx:], y[split_idx:]

scaler = StandardScaler()
X_tr_s = scaler.fit_transform(X_tr)
X_te_s = scaler.transform(X_te)

print("Training LR...", flush=True)
lr = LogisticRegression(multi_class='multinomial', max_iter=5000, solver='lbfgs', C=1.0, random_state=42)
lr.fit(X_tr_s, y_tr)
y_pred_lr = lr.predict(X_te_s)
y_proba_lr = lr.predict_proba(X_te_s)

lr_acc = accuracy_score(y_te, y_pred_lr)
lr_ll = log_loss(y_te, y_proba_lr)
print(f"LR Accuracy: {lr_acc:.4f}, LogLoss: {lr_ll:.4f}", flush=True)

feat_names = ['home_tier','away_tier','tier_diff','abs_tier_gap',
              'imp_home','imp_draw','imp_away','odds_h','odds_d','odds_a',
              'season_pos','h_recent_wins','a_recent_wins','form_diff']
coef_imp = {}
for j, name in enumerate(feat_names):
    coef_imp[name] = float(np.mean(np.abs(lr.coef_[:, j])))
print("Top features:", {k: round(v,4) for k,v in sorted(coef_imp.items(), key=lambda x:-x[1])[:5]}, flush=True)

# ============================================================
# 6. KELLY CRITERION
# ============================================================
print("\n=== KELLY ===", flush=True)
bankroll = 10000.0
init_br = bankroll
frac = 0.25
kelly_bets = []

for idx, r in enumerate(test_rows):
    lh, la = poisson_vec(r['home'], r['away'])
    ph, pd, pa = pmf_grid(lh, la, 10)

    for pick, odds, prob in [('HOME', r['oh'], ph), ('DRAW', r['od'], pd), ('AWAY', r['oa'], pa)]:
        b = odds - 1
        if b > 0 and prob > 0:
            kelly = (b*prob - (1-prob)) / b
            if kelly > 0 and prob > 0.35:
                stake = bankroll * kelly * frac
                win = (pick == r['outcome'])
                pnl = stake*b if win else -stake
                bankroll += pnl
                kelly_bets.append({
                    'match': f"{r['home']} vs {r['away']}",
                    'pick': pick, 'odds': round(odds,2), 'prob': round(prob,4),
                    'kelly': round(kelly,4), 'stake': round(stake,2),
                    'win': win, 'pnl': round(pnl,2)
                })

kw = sum(1 for b in kelly_bets if b['win'])
nb = len(kelly_bets)
kelly_roi = (bankroll - init_br) / init_br
total_staked = sum(b['stake'] for b in kelly_bets)
rot = (bankroll - init_br) / total_staked if total_staked else 0
print(f"Bets: {nb}, Wins: {kw} ({kw/nb*100:.1f}%)\nBankroll: ${bankroll:.2f}, ROI: {kelly_roi:+.2%}, ROT: {rot:+.2%}", flush=True)

# ============================================================
# 7. MARKOV CHAINS
# ============================================================
print("\n=== MARKOV ===", flush=True)

# Transition counts
streak_stats = {'HOME': {'HOME': 0, 'DRAW': 0, 'AWAY': 0, 't': 0},
                'DRAW': {'HOME': 0, 'DRAW': 0, 'AWAY': 0, 't': 0},
                'AWAY': {'HOME': 0, 'DRAW': 0, 'AWAY': 0, 't': 0}}

for team in all_teams:
    seq = team_seq[team]
    for i in range(len(seq)-1):
        po = 'HOME' if seq[i]==2 else ('DRAW' if seq[i]==1 else 'AWAY')
        no = 'HOME' if seq[i+1]==2 else ('DRAW' if seq[i+1]==1 else 'AWAY')
        streak_stats[po][no] += 1
        streak_stats[po]['t'] += 1

markov_res = {}
for prev in ['HOME','DRAW','AWAY']:
    t = streak_stats[prev]['t']
    if t > 0:
        row = {n: round(streak_stats[prev][n]/t, 4) for n in ['HOME','DRAW','AWAY']}
        markov_res[f"after_{prev}"] = row
        print(f"P(*|prev={prev}): {row}", flush=True)

# Streak analysis
streak_probs = defaultdict(lambda: {'wins': [], 'total': 0})
for team in all_teams:
    seq = team_seq[team]
    streak = 0
    for i in range(len(seq)):
        if seq[i] == 2:
            if i > 0 and seq[i-1] == 2:
                streak += 1
            else:
                streak = 0
        else:
            streak = 0
        if i < len(seq) - 1:
            streak_probs[streak]['wins'].append(1 if seq[i+1]==2 else 0)
            streak_probs[streak]['total'] += 1

baseline_wr = np.mean([1 if s==2 else 0 for team in all_teams for s in team_seq[team]])
print(f"\nBaseline win rate: {baseline_wr:.3f}", flush=True)
for sl in sorted(streak_probs.keys())[:6]:
    wins = streak_probs[sl]['wins']
    if wins:
        p = np.mean(wins)
        print(f"  Streak={sl}: P(next win)={p:.3f} (n={len(wins)})", flush=True)
        markov_res[f"streak_{sl}"] = {'p_next_win': round(float(p),4), 'n': len(wins)}

hot_hand = np.mean(streak_probs[1]['wins']) - baseline_wr if streak_probs[1]['wins'] else 0

# ============================================================
# 8. COMPILE & WRITE
# ============================================================
results = {
    "poisson": {
        "accuracy": round(float(poisson_acc), 4),
        "brier_score": round(float(poisson_brier_avg), 4),
        "market_accuracy": round(float(market_acc), 4),
        "edge_vs_market": round(float(poisson_acc - market_acc), 4),
        "test_matches": n_test,
        "avg_home_goals": round(float(avg_home_goals), 3),
        "avg_away_goals": round(float(avg_away_goals), 3)
    },
    "bayesian": {
        "prior_accuracy": round(float(prior_acc), 4),
        "posterior_accuracy": round(float(bayes_acc), 4),
        "posterior_brier": round(float(bayes_brier_avg/n_test), 4),
        "edge_vs_prior": round(float(bayes_acc - prior_acc), 4),
        "form_weight": fw
    },
    "logistic": {
        "accuracy": round(float(lr_acc), 4),
        "log_loss": round(float(lr_ll), 4),
        "feature_importance": {k: round(v,4) for k,v in sorted(coef_imp.items(), key=lambda x:-x[1])}
    },
    "kelly": {
        "total_bets": nb,
        "wins": kw,
        "win_rate": round(float(kw/nb), 4) if nb else 0,
        "roi": round(float(kelly_roi), 4),
        "roi_on_turnover": round(float(rot), 4),
        "final_bankroll": round(float(bankroll), 2),
        "kelly_fraction": frac
    },
    "markov": {
        "baseline_win_rate": round(float(baseline_wr), 4),
        "hot_hand_effect": round(float(hot_hand), 4),
        "transitions": markov_res
    },
    "summary": {
        "total_matches": len(rows_all),
        "unique_teams": len(all_teams),
        "train_size": n_train,
        "test_size": n_test,
        "tier_cutoffs": {"t1": round(float(p75),3), "t2": round(float(p50),3), "t3": round(float(p25),3)}
    }
}

models_ranked = [
    ("Poisson", poisson_acc),
    ("Bayesian Posterior", bayes_acc),
    ("Logistic Regression", lr_acc),
    ("Market Implied", market_acc),
    ("Tier Prior", prior_acc)
]
models_ranked.sort(key=lambda x: -x[1])
best = models_ranked[0]

results["verdict"] = (
    f"The best mathematical model is {best[0]} with {best[1]*100:.1f}% accuracy. "
    f"Kelly betting achieved {kelly_roi:+.1%} ROI. "
    f"Hot hand effect: {hot_hand:+.3f} (positive = momentum exists)."
)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*60}", flush=True)
print(f"Results → {OUT}", flush=True)
print(f"\n🏆 VERDICT: {results['verdict']}", flush=True)
print(f"\nModel ranking:", flush=True)
for i, (name, acc) in enumerate(models_ranked):
    print(f"  {i+1}. {name}: {acc*100:.1f}%", flush=True)

conn.close()
print("\nDone.", flush=True)
