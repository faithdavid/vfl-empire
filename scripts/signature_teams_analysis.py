#!/usr/bin/env python3
"""
VFL Behavioral Signature Analysis
Tests Lord FaithDavid's hypotheses about engine patterns across all VFL seasons.
"""

import sqlite3
import json
import sys
import math
from collections import defaultdict, Counter

# ── Config ──────────────────────────────────────────────────────────────
DB_PATH = "~/Documents/Projects/vfl-data/databases/history.db"
SIGNATURE_TEAMS = {"SOUTHAMPTON", "WOLVERHAMPTON", "WEST HAM"}
TOP_TEAMS = {"MANCHESTER BLUE", "MANCHESTER RED", "LIVERPOOL", "CHELSEA", "LONDON GUNS", "TOTTENHAM"}
MAN_BLUE = "MANCHESTER BLUE"

# ── Team name normalization ─────────────────────────────────────────────
NAME_MAP = {
    "Aston Villa": "ASTON VILLA",
    "Bournemouth": "BOURNEMOUTH",
    "Brighton": "BRIGHTON",
    "Chelsea": "CHELSEA",
    "Crystal Palace": "CRYSTAL PALACE",
    "Everton": "EVERTON",
    "Fulham": "FULHAM",
    "Leeds": "LEEDS",
    "Liverpool": "LIVERPOOL",
    "London Guns": "LONDON GUNS",
    "Manchester Blue": "MANCHESTER BLUE",
    "Manchester Red": "MANCHESTER RED",
    "Newcastle": "NEWCASTLE",
    "Tottenham": "TOTTENHAM",
    "West Ham": "WEST HAM",
    "Wolverhampton": "WOLVERHAMPTON",
}

def normalize(name):
    return NAME_MAP.get(name, name.upper() if name.isalpha() and name[0].isupper() else name)

# ── Load data ───────────────────────────────────────────────────────────
print("=" * 72)
print("VFL BEHAVIORAL SIGNATURE ANALYSIS — Lord FaithDavid's Hypotheses")
print("=" * 72)

import os
db_path = os.path.expanduser(DB_PATH)
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Load all matches with scores, only 'vf:season:' prefixed seasons
c.execute("""
    SELECT season, day, home, away, outcome, h, a
    FROM matches
    WHERE season LIKE 'vf:season:%'
      AND h IS NOT NULL
      AND a IS NOT NULL
      AND outcome IS NOT NULL
    ORDER BY season, day
""")
rows = c.fetchall()
print(f"\nLoaded {len(rows)} match results from history.db")

# Build per-season data
# Structure: seasons[season_id] = {team: {'pts': int, 'w': int, 'd': int, 'l': int, 'gf': int, 'ga': int, 'matches': []}}
seasons = {}
all_matches = []

for row in rows:
    season = normalize(row["season"])
    day = row["day"]
    home = normalize(row["home"])
    away = normalize(row["away"])
    outcome = row["outcome"]
    hg = row["h"]
    ag = row["a"]

    if season not in seasons:
        seasons[season] = defaultdict(lambda: {"pts": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "matches": []})

    rec = seasons[season]
    # Home team
    if hg > ag:
        rec[home]["pts"] += 3
        rec[home]["w"] += 1
        rec[away]["l"] += 1
        result_h = "W"
        result_a = "L"
    elif hg == ag:
        rec[home]["pts"] += 1
        rec[away]["pts"] += 1
        rec[home]["d"] += 1
        rec[away]["d"] += 1
        result_h = "D"
        result_a = "D"
    else:
        rec[away]["pts"] += 3
        rec[away]["w"] += 1
        rec[home]["l"] += 1
        result_h = "L"
        result_a = "W"

    rec[home]["gf"] += hg
    rec[home]["ga"] += ag
    rec[away]["gf"] += ag
    rec[away]["ga"] += hg

    match_entry = {
        "season": season, "day": day, "home": home, "away": away,
        "hg": hg, "ag": ag, "result_h": result_h, "outcome": outcome
    }
    rec[home]["matches"].append(match_entry)
    rec[away]["matches"].append(match_entry)
    all_matches.append(match_entry)

# Only keep seasons with at least 10 teams having > 1 match (i.e., proper seasons)
valid_seasons = {}
for sid, sdata in seasons.items():
    active_teams = [t for t, d in sdata.items() if d["w"] + d["d"] + d["l"] >= 3 and t != ""]
    if len(active_teams) >= 8:
        valid_seasons[sid] = sdata

print(f"Valid seasons: {len(valid_seasons)} (from {len(seasons)} raw)")
print(f"Total matches in valid seasons: {sum(sum(d['w']+d['d']+d['l'] for t,d in sd.items() if t!='' and d['w']+d['d']+d['l']>=1)//2 for sd in valid_seasons.values())}")

# ─────────────────────────────────────────────────────────────────────
# HYPOTHESIS 1: SIGNATURE TEAMS — Actual vs Expected Performance
# ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("HYPOTHESIS 1: SIGNATURE TEAMS — Actual vs Expected Performance")
print("=" * 72)

# For each signature team, across all seasons, calculate:
# - Actual points per game (PPG)
# - Expected PPG based on final table position
# - Deviation from expectation

# Build per-season table positions
from collections import OrderedDict

team_season_ppg = defaultdict(list)  # team -> list of (season, ppg, final_pos, total_teams)
signature_teams_found = set()

for sid, sdata in valid_seasons.items():
    # Sort teams by points (desc), then GD
    standings = []
    for team, stats in sdata.items():
        if team == "" or stats["w"] + stats["d"] + stats["l"] < 3:
            continue
        standings.append((team, stats["pts"], stats["gf"] - stats["ga"], stats))
    
    standings.sort(key=lambda x: (-x[1], -x[2]))
    total_teams = len(standings)
    
    for pos, (team, pts, gd, stats) in enumerate(standings, 1):
        team_upper = team.upper() if team.isalpha() and team[0].isupper() else team
        team_season_ppg[team].append({
            "season": sid,
            "ppg": pts / (stats["w"] + stats["d"] + stats["l"]),
            "total_pts": pts,
            "total_games": stats["w"] + stats["d"] + stats["l"],
            "pos": pos,
            "total_teams": total_teams,
            "w": stats["w"],
            "d": stats["d"],
            "l": stats["l"],
            "gf": stats["gf"],
            "ga": stats["ga"]
        })
        if team.upper() in {t.upper() for t in SIGNATURE_TEAMS}:
            signature_teams_found.add(team)

print(f"\nSignature teams found in data: {signature_teams_found}")

# For each signature team, compare PPG to league average and expected PPG at their position
for team in sorted(signature_teams_found):
    records = team_season_ppg[team]
    if not records:
        continue
    
    # Calculate actual stats
    total_pts = sum(r["total_pts"] for r in records)
    total_games = sum(r["total_games"] for r in records)
    actual_ppg = total_pts / total_games if total_games else 0
    
    # League average PPG across all teams in same seasons
    all_ppgs = []
    pos_ppgs = defaultdict(list)  # PPG by table position
    for tid, trecs in team_season_ppg.items():
        for r in trecs:
            if r["season"] in {s["season"] for s in records}:
                all_ppgs.append(r["ppg"])
                pos_ppgs[r["pos"]].append(r["ppg"])
    
    league_avg_ppg = sum(all_ppgs) / len(all_ppgs) if all_ppgs else 0
    
    # Expected PPG based on positions held
    expected_ppg_sum = 0
    expected_count = 0
    pos_counts = Counter()
    for r in records:
        pos = r["pos"]
        total_t = r["total_teams"]
        pos_ppg_vals = pos_ppgs.get(pos, [])
        if pos_ppg_vals:
            expected_ppg_sum += sum(pos_ppg_vals) / len(pos_ppg_vals)
            expected_count += 1
        pos_counts[pos] += 1
    
    expected_ppg = expected_ppg_sum / expected_count if expected_count else league_avg_ppg
    
    # Also calculate using a regression: how many positions above/below their PPG would predict
    # Simpler: compute "expected position" from PPG
    # Build mapping of avg PPG per position
    pos_avg_ppg = {}
    for pos in sorted(pos_ppgs.keys()):
        pos_avg_ppg[pos] = sum(pos_ppgs[pos]) / len(pos_ppgs[pos])
    
    # Find expected position for this team's actual PPG
    # Also find expected PPG for actual position
    actual_positions = [r["pos"] for r in records]
    avg_actual_pos = sum(actual_positions) / len(actual_positions)
    
    # Deviation: actual PPG vs average PPG of teams in same position
    pos_expected_ppg = sum(pos_avg_ppg.get(r["pos"], league_avg_ppg) for r in records) / len(records)
    
    deviation = actual_ppg - pos_expected_ppg
    deviation_pct = (deviation / pos_expected_ppg * 100) if pos_expected_ppg else 0
    
    print(f"\n── {team} (over {len(records)} seasons) ──")
    print(f"  Actual PPG:         {actual_ppg:.4f} ({total_pts} pts in {total_games} games)")
    print(f"  Expected PPG (pos): {pos_expected_ppg:.4f}")
    print(f"  Deviation:          {deviation:+.4f} ({deviation_pct:+.2f}%)")
    print(f"  Avg final position: {avg_actual_pos:.1f}")
    
    # Position distribution
    pos_dist = ", ".join(f"#{p} x{c}" for p, c in sorted(pos_counts.items()))
    print(f"  Position distrib:   {pos_dist}")
    
    # Win rate vs expected win rate
    actual_wr = sum(r["w"] for r in records) / total_games * 100
    loss_rate = sum(r["l"] for r in records) / total_games * 100
    draw_rate = sum(r["d"] for r in records) / total_games * 100
    print(f"  Win rate:  {actual_wr:.1f}%  |  Draw: {draw_rate:.1f}%  |  Loss: {loss_rate:.1f}%")
    
    # Compare to overall league win rates at same positions
    pos_wr = defaultdict(list)
    for tid, trecs in team_season_ppg.items():
        for r in trecs:
            if r["total_games"] > 0:
                pos_wr[r["pos"]].append(r["w"] / r["total_games"] * 100)
    
    expected_wr = sum(
        sum(pos_wr.get(r["pos"], [actual_wr])) / max(len(pos_wr.get(r["pos"], [1])), 1)
        for r in records
    ) / len(records)
    
    print(f"  Expected win rate:  {expected_wr:.1f}%")
    print(f"  WR deviation:       {actual_wr - expected_wr:+.1f} pp")
    
    # Statistical significance: normal approximation
    # Z-score = (obs - exp) / sqrt(exp * (1-exp) / n)
    p_exp = expected_wr / 100
    n = total_games
    p_obs = actual_wr / 100
    if p_exp > 0 and p_exp < 1 and n > 0:
        se = math.sqrt(p_exp * (1 - p_exp) / n)
        z = (p_obs - p_exp) / se
        print(f"  Z-score (win rate): {z:+.3f}  {'*** SIGNIFICANT' if abs(z) > 3.29 else '**' if abs(z) > 2.58 else '*' if abs(z) > 1.96 else 'not significant'}")
        if abs(z) > 1.96:
            print(f"  → Statistical evidence of anomalous performance")

# ─────────────────────────────────────────────────────────────────────
# HYPOTHESIS 2: WIN QUOTA — Do top teams' win totals cluster?
# ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("HYPOTHESIS 2: WIN QUOTA — Win Distribution Analysis")
print("=" * 72)

# For top teams, analyze distribution of wins per season
# If a quota exists, we'd expect low variance around some "cap" value

for team in sorted(TOP_TEAMS):
    records = team_season_ppg[team]
    if len(records) < 5:
        continue
    
    wins = [r["w"] for r in records]
    games = [r["total_games"] for r in records]
    win_pcts = [r["w"] / r["total_games"] * 100 if r["total_games"] > 0 else 0 for r in records]
    
    mean_wins = sum(wins) / len(wins)
    var_wins = sum((w - mean_wins)**2 for w in wins) / len(wins)
    std_wins = math.sqrt(var_wins)
    cv_wins = std_wins / mean_wins if mean_wins > 0 else 0  # Coefficient of variation
    
    mean_pct = sum(win_pcts) / len(win_pcts)
    var_pct = sum((p - mean_pct)**2 for p in win_pcts) / len(win_pcts)
    std_pct = math.sqrt(var_pct)
    
    min_wins = min(wins)
    max_wins = max(wins)
    
    # Also check PPG variance
    ppgs = [r["ppg"] for r in records]
    mean_ppg = sum(ppgs) / len(ppgs)
    var_ppg = sum((p - mean_ppg)**2 for p in ppgs) / len(ppgs)
    std_ppg = math.sqrt(var_ppg)
    
    # Season count
    n = len(records)
    
    print(f"\n── {team} ({n} seasons) ──")
    print(f"  Wins per season: {min_wins}-{max_wins} (range), mean={mean_wins:.1f}, σ={std_wins:.1f}")
    print(f"  Win %:           {mean_pct:.1f}% ± {std_pct:.1f}%  (CV: {std_pct/mean_pct*100:.1f}%)")
    print(f"  PPG:             {mean_ppg:.3f} ± {std_ppg:.3f}")
    print(f"  Distribution:    {Counter(wins)}")
    
    # Hypothesis test: is variance unusually low?
    # If there were no quota, we'd expect win counts to follow a binomial-like distribution
    # For a binomial with p=mean_pct/100 and n=~38 games:
    # Expected variance = n * p * (1-p) ≈ 38 * 0.5 * 0.5 ≈ 9.5
    # Expected std = ~3.1
    # If actual std is much lower, that supports quota hypothesis
    
    avg_games = sum(games) / len(games)
    p_est = mean_pct / 100
    expected_binomial_var = avg_games * p_est * (1 - p_est)
    expected_binomial_std = math.sqrt(expected_binomial_var)
    
    print(f"  Expected σ (binomial): {expected_binomial_std:.2f}")
    print(f"  Ratio σ_actual / σ_binomial: {std_wins / expected_binomial_std:.3f}")
    
    if std_wins < expected_binomial_std * 0.7:
        print(f"  → Variance LOWER than binomial expectation — consistent with win quota hypothesis")
    elif std_wins < expected_binomial_std * 0.85:
        print(f"  → Variance somewhat lower — possible mild quota effect")
    else:
        print(f"  → Variance near or above binomial — no strong quota evidence")

# Also check if ANY team has suspiciously low win variation
print("\n── All teams: Win variance analysis ──")
team_variance_data = []
for team, records in team_season_ppg.items():
    if len(records) < 10:
        continue
    wins = [r["w"] for r in records]
    games_played = [r["total_games"] for r in records]
    if sum(games_played) < 100:
        continue
    mean_wins = sum(wins) / len(wins)
    var_wins = sum((w - mean_wins)**2 for w in wins) / len(wins)
    std_wins = math.sqrt(var_wins)
    cv = std_wins / mean_wins if mean_wins else 0
    team_variance_data.append((team, len(records), mean_wins, std_wins, cv))

team_variance_data.sort(key=lambda x: x[3])  # Sort by std_wins ascending
print(f"{'Team':<20} {'Seasons':<8} {'Mean W':<8} {'Std W':<8} {'CV':<8}")
print("-" * 52)
for team, n, mw, sw, cv in team_variance_data[:15]:
    print(f"{team:<20} {n:<8} {mw:<8.1f} {sw:<8.2f} {cv:<8.3f}")
print("  ...")
for team, n, mw, sw, cv in team_variance_data[-5:]:
    print(f"{team:<20} {n:<8} {mw:<8.1f} {sw:<8.2f} {cv:<8.3f}")

# ─────────────────────────────────────────────────────────────────────
# HYPOTHESIS 3: NEED-BASED ADJUSTMENT — Man Blue table position urgency
# ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("HYPOTHESIS 3: NEED-BASED ADJUSTMENT — Man Blue by Table Urgency")
print("=" * 72)

# We need per-MATCHDAY table positions, not just final
# Re-query with match-level detail to build week-by-week standings

c.execute("""
    SELECT season, day, home, away, h, a
    FROM matches
    WHERE season LIKE 'vf:season:%'
      AND h IS NOT NULL
      AND a IS NOT NULL
    ORDER BY season, day
""")
all_match_data = c.fetchall()

# Build week-by-week standings for each season
man_blue_matches_by_urgency = []
man_blue_matches_detail = []

current_season = None
season_standings = defaultdict(lambda: {"pts": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "matches_played": 0})

for row in all_match_data:
    season = normalize(row["season"])
    day = row["day"]
    home = normalize(row["home"])
    away = normalize(row["away"])
    hg = row["h"]
    ag = row["a"]
    
    if season != current_season and current_season is not None:
        # Season ended, reset
        season_standings = defaultdict(lambda: {"pts": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "matches_played": 0})
    
    current_season = season
    
    # Update standings
    if hg > ag:
        season_standings[home]["pts"] += 3
        season_standings[home]["w"] += 1
        season_standings[away]["l"] += 1
    elif hg == ag:
        season_standings[home]["pts"] += 1
        season_standings[away]["pts"] += 1
        season_standings[home]["d"] += 1
        season_standings[away]["d"] += 1
    else:
        season_standings[away]["pts"] += 3
        season_standings[away]["w"] += 1
        season_standings[home]["l"] += 1
    
    season_standings[home]["gf"] += hg
    season_standings[home]["ga"] += ag
    season_standings[away]["gf"] += ag
    season_standings[away]["ga"] += hg
    season_standings[home]["matches_played"] += 1
    season_standings[away]["matches_played"] += 1
    
    # Check if Man Blue is involved
    if home == MAN_BLUE or away == MAN_BLUE:
        # Compute current table position for all teams
        table = [(t, d["pts"], d["matches_played"], d["gf"] - d["ga"]) 
                 for t, d in season_standings.items() if d["matches_played"] > 0]
        table.sort(key=lambda x: (-x[1], -x[3]))
        
        man_blue_pos = None
        total_teams = len(table)
        man_blue_pts = None
        leader_pts = None
        points_behind = None
        
        for i, (t, pts, mp, gd) in enumerate(table, 1):
            if t == MAN_BLUE:
                man_blue_pos = i
                man_blue_pts = pts
            if i == 1:
                leader_pts = pts
        
        if man_blue_pos and leader_pts is not None:
            points_behind = leader_pts - man_blue_pts
        
        # Categorize urgency
        if man_blue_pos is not None:
            if man_blue_pos <= 2:
                urgency = "TOP_2"
                need_score = 5 - man_blue_pos  # 3 or 4
            elif man_blue_pos <= 4:
                urgency = "TOP_4"
                need_score = 5 - man_blue_pos
            elif man_blue_pos <= 8:
                urgency = "MID"
                need_score = 1
            else:
                urgency = "LOW"
                need_score = 0
        else:
            urgency = "UNKNOWN"
            need_score = 0
        
        # Did Man Blue win?
        if home == MAN_BLUE:
            man_blue_won = hg > ag
            man_blue_drew = hg == ag
            man_blue_lost = hg < ag
            mb_gf = hg
            mb_ga = ag
        else:
            man_blue_won = ag > hg
            man_blue_drew = ag == hg
            man_blue_lost = ag < hg
            mb_gf = ag
            mb_ga = hg
        
        man_blue_matches_detail.append({
            "season": season,
            "day": day,
            "home": home,
            "away": away,
            "hg": hg,
            "ag": ag,
            "mb_won": man_blue_won,
            "mb_drew": man_blue_drew,
            "mb_lost": man_blue_lost,
            "pos": man_blue_pos,
            "total_teams": total_teams,
            "pts": man_blue_pts,
            "leader_pts": leader_pts,
            "pts_behind": points_behind,
            "urgency": urgency,
            "need_score": need_score
        })

# Analyze by urgency
print(f"\nMan Blue has {len(man_blue_matches_detail)} tracked matches with positional data")

urgency_groups = defaultdict(lambda: {"wins": 0, "draws": 0, "losses": 0, "total": 0, "gf": 0, "ga": 0})
for m in man_blue_matches_detail:
    ug = urgency_groups[m["urgency"]]
    ug["total"] += 1
    if m["mb_won"]:
        ug["wins"] += 1
    elif m["mb_drew"]:
        ug["draws"] += 1
    else:
        ug["losses"] += 1
    ug["gf"] += m["hg"] if m["home"] == MAN_BLUE else m["ag"]
    ug["ga"] += m["ag"] if m["home"] == MAN_BLUE else m["hg"]

print(f"\n{'Urgency':<12} {'Matches':<8} {'Wins':<6} {'Draws':<6} {'Losses':<6} {'Win%':<8} {'GF':<5} {'GA':<5} {'GD':<5}")
print("-" * 65)
for urg in ["TOP_2", "TOP_4", "MID", "LOW"]:
    g = urgency_groups[urg]
    wr = g["wins"] / g["total"] * 100 if g["total"] else 0
    print(f"{urg:<12} {g['total']:<8} {g['wins']:<6} {g['draws']:<6} {g['losses']:<6} {wr:<8.1f} {g['gf']:<5} {g['ga']:<5} {g['gf']-g['ga']:<+5}")

# Also analyze by points behind leader
print("\n── Man Blue Win Rate by Points Behind Leader ──")
pts_behind_groups = defaultdict(lambda: {"wins": 0, "total": 0})
for m in man_blue_matches_detail:
    pb = m["pts_behind"]
    if pb is None:
        continue
    # Bucket: 0, 1-3, 4-6, 7-9, 10+
    if pb == 0:
        bucket = "0 (level)"
    elif pb <= 3:
        bucket = "1-3 behind"
    elif pb <= 6:
        bucket = "4-6 behind"
    elif pb <= 9:
        bucket = "7-9 behind"
    else:
        bucket = "10+ behind"
    
    pts_behind_groups[bucket]["total"] += 1
    if m["mb_won"]:
        pts_behind_groups[bucket]["wins"] += 1

for bucket in ["0 (level)", "1-3 behind", "4-6 behind", "7-9 behind", "10+ behind"]:
    g = pts_behind_groups[bucket]
    if g["total"] > 0:
        wr = g["wins"] / g["total"] * 100
        print(f"  {bucket:<16}  {g['total']:>4} matches  {g['wins']:>3} wins  {wr:>6.1f}%")

# Chi-square test for independence
print("\n── Chi-Square Test: Man Blue Win Rate × Urgency ──")
import math

# Build contingency table: urgency x outcome (win / not_win)
observed = {}
for urg in ["TOP_2", "TOP_4", "MID", "LOW"]:
    g = urgency_groups[urg]
    observed[urg] = {"win": g["wins"], "not_win": g["total"] - g["wins"]}

total_all = sum(g["total"] for g in urgency_groups.values())
total_wins = sum(g["wins"] for g in urgency_groups.values())
total_not_wins = total_all - total_wins

# Expected under independence
chi2 = 0
for urg in ["TOP_2", "TOP_4", "MID", "LOW"]:
    g = urgency_groups[urg]
    row_total = g["total"]
    if row_total == 0:
        continue
    exp_win = row_total * total_wins / total_all
    exp_not_win = row_total * total_not_wins / total_all
    chi2 += (g["wins"] - exp_win)**2 / exp_win
    chi2 += ((g["total"] - g["wins"]) - exp_not_win)**2 / exp_not_win

print(f"  χ² = {chi2:.3f} (df=3)")
print(f"  Critical values: 7.81 (p=0.05), 11.34 (p=0.01), 16.27 (p=0.001)")
if chi2 > 16.27:
    print(f"  → Highly significant (p<0.001) — Man Blue win rates DO depend on table urgency")
elif chi2 > 11.34:
    print(f"  → Significant (p<0.01)")
elif chi2 > 7.81:
    print(f"  → Significant (p<0.05)")
else:
    print(f"  → Not statistically significant")

# ─────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("SUMMARY OF FINDINGS")
print("=" * 72)

print("""
HYPOTHESIS 1: SIGNATURE TEAMS (Southampton, Wolves, West Ham)
  → Check deviation values above for statistical significance
  → Teams that consistently outperform/underperform their table position are "trap teams"

HYPOTHESIS 2: WIN QUOTA
  → Teams with unusually low win variance across seasons support quota hypothesis
  → Check variance ratio vs binomial expectation above

HYPOTHESIS 3: NEED-BASED ADJUSTMENT (Man Blue)
  → Win rate by table urgency tested
  → Chi-square test indicates whether urgency affects outcomes
""")

conn.close()
print("\nAnalysis complete. Results displayed above.")
