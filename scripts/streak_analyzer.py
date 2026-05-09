#!/usr/bin/env python3
"""
Historical VFL Form Streak Analyzer
Analyzes all 223 complete 30-MD seasons for winning/losing streaks, 
best starts, collapses, comebacks, and H2H streaks.
"""
import sqlite3, os, json, sys
from collections import defaultdict
from datetime import datetime

DB = os.path.expanduser("~/Documents/Projects/vfl-data/databases/history.db")
OUT = os.path.expanduser("~/Documents/Projects/vfl-data/streaks")
os.makedirs(OUT, exist_ok=True)

conn = sqlite3.connect(DB)

# Get all seasons with complete data (240 matches = 8 × 30 MDs)
seasons = conn.execute("""
    SELECT season, COUNT(*) as cnt, MIN(day) as min_md, MAX(day) as max_md
    FROM matches WHERE outcome IN ('HOME','AWAY','DRAW')
    GROUP BY season
    HAVING cnt = 240 AND min_md = 1 AND max_md = 30
    ORDER BY season
""").fetchall()

print(f"Found {len(seasons)} complete seasons\n")

# For each season, build team form across 30 MDs
all_streaks = {
    "win_streaks": [],       # (team, season, length, start_md, end_md)
    "loss_streaks": [],      # (team, season, length, start_md, end_md)
    "unbeaten_runs": [],     # W+D streaks
    "winless_runs": [],      # L+D streaks
    "best_starts_5": [],     # points in first 5 MDs
    "best_starts_10": [],    # points in first 10 MDs
    "worst_starts_5": [],
    "worst_starts_10": [],
    "comebacks": [],         # bottom 5 after MD10 → top 5 finish
    "collapses": [],         # top 5 after MD10 → bottom 5 finish
    "h2h_streaks": [],       # one team beating another consecutively
}

# Track per-team across ALL seasons
team_records = defaultdict(lambda: {
    "total_seasons": 0,
    "longest_win_streak": 0,
    "longest_loss_streak": 0,
    "longest_unbeaten": 0,
    "longest_winless": 0,
    "total_wins": 0,
    "total_losses": 0,
    "best_start_5": 0,
    "worst_start_5": 15,
    "championships": 0,
    "top4": 0,
    "relegations": 0,
    "avg_pts": 0,
    "total_pts": 0,
    "win_streaks_ge5": 0,
    "loss_streaks_ge5": 0,
})

# Track H2H streaks
h2h_streaks = defaultdict(lambda: {"current": 0, "longest": 0, "longest_team": "", "longest_season": ""})

for idx, (season_id, cnt, min_md, max_md) in enumerate(seasons):
    if idx % 20 == 0:
        print(f"  Processing season {idx+1}/{len(seasons)}...")
    
    # Get all matches ordered by day
    matches = conn.execute("""
        SELECT day, home, away, h, a, outcome FROM matches 
        WHERE season = ? AND outcome IN ('HOME','AWAY','DRAW')
        ORDER BY day
    """, (season_id,)).fetchall()
    
    # Build team form per MD
    team_form = defaultdict(list)  # team -> list of (md, result)
    for md, home, away, h, a, outcome in matches:
        if outcome == "HOME":
            team_form[home].append((md, "W"))
            team_form[away].append((md, "L"))
        elif outcome == "AWAY":
            team_form[home].append((md, "L"))
            team_form[away].append((md, "W"))
        else:
            team_form[home].append((md, "D"))
            team_form[away].append((md, "D"))
    
    # For each team, analyze streaks
    for team, form_list in team_form.items():
        form_list.sort()  # sort by MD
        form_str = "".join(r for _, r in form_list)
        team_upper = team.upper()
        
        tr = team_records[team_upper]
        tr["total_seasons"] += 1
        
        # --- Win/loss streaks ---
        current_win = 0; current_loss = 0; current_unbeaten = 0; current_winless = 0
        best_win = 0; best_loss = 0; best_unbeaten = 0; best_winless = 0
        best_win_md = 0; best_loss_md = 0
        
        for i, result in enumerate(form_str):
            md_num = i + 1
            
            if result == "W":
                current_win += 1; current_loss = 0
                current_unbeaten += 1; current_winless = 0
                if current_win > best_win:
                    best_win = current_win
                    best_win_md = md_num
            elif result == "L":
                current_loss += 1; current_win = 0
                current_winless += 1; current_unbeaten = 0
                if current_loss > best_loss:
                    best_loss = current_loss
                    best_loss_md = md_num
            else:  # DRAW
                current_win = 0; current_loss = 0
                current_unbeaten += 1; current_winless += 1
                if current_unbeaten > best_unbeaten:
                    best_unbeaten = current_unbeaten
                if current_winless > best_winless:
                    best_winless = current_winless
        
        if current_win > best_win: best_win = current_win
        if current_loss > best_loss: best_loss = current_loss
        if current_unbeaten > best_unbeaten: best_unbeaten = current_unbeaten
        if current_winless > best_winless: best_winless = current_winless
        
        # Save notable streaks
        if best_win >= 5:
            all_streaks["win_streaks"].append([team, season_id, best_win, best_win_md-best_win+1 if best_win > 0 else 0, best_win_md])
            tr["win_streaks_ge5"] += 1
        if best_loss >= 5:
            all_streaks["loss_streaks"].append([team, season_id, best_loss, best_loss_md-best_loss+1 if best_loss > 0 else 0, best_loss_md])
            tr["loss_streaks_ge5"] += 1
        
        tr["longest_win_streak"] = max(tr["longest_win_streak"], best_win)
        tr["longest_loss_streak"] = max(tr["longest_loss_streak"], best_loss)
        tr["longest_unbeaten"] = max(tr["longest_unbeaten"], best_unbeaten)
        tr["longest_winless"] = max(tr["longest_winless"], best_winless)
        
        # Points per segment
        pts_5 = 0; pts_10 = 0
        for i, r in enumerate(form_str[:5]):
            if r == "W": pts_5 += 3
            elif r == "D": pts_5 += 1
        for i, r in enumerate(form_str[:10]):
            if r == "W": pts_10 += 3
            elif r == "D": pts_10 += 1
        
        # Total points
        total_pts = 0
        for r in form_str:
            if r == "W": total_pts += 3
            elif r == "D": total_pts += 1
        
        all_streaks["best_starts_5"].append([team, season_id, pts_5])
        all_streaks["best_starts_10"].append([team, season_id, pts_10])
        all_streaks["worst_starts_5"].append([team, season_id, pts_5])
        all_streaks["worst_starts_10"].append([team, season_id, pts_10])
        
        tr["best_start_5"] = max(tr["best_start_5"], pts_5)
        tr["worst_start_5"] = min(tr["worst_start_5"], pts_5)
        tr["total_pts"] += total_pts
    
    # --- Comback/Collapse analysis ---
    # Get standings at MD 10 and final (MD 30)
    def get_standings_at(season_id, target_md):
        t = defaultdict(lambda: {"pts": 0, "gd": 0, "gf": 0, "ga": 0})
        for md, home, away, h, a, outcome in matches:
            if md > target_md: break
            if outcome == "HOME":
                t[home]["pts"] += 3; t[home]["gf"] += h; t[home]["ga"] += a
                t[away]["gf"] += a; t[away]["ga"] += h
            elif outcome == "AWAY":
                t[away]["pts"] += 3; t[away]["gf"] += a; t[away]["ga"] += h
                t[home]["gf"] += h; t[home]["ga"] += a
            else:
                t[home]["pts"] += 1; t[home]["gf"] += h; t[home]["ga"] += a
                t[away]["pts"] += 1; t[away]["gf"] += a; t[away]["ga"] += h
        for team in t:
            t[team]["gd"] = t[team]["gf"] - t[team]["ga"]
        return sorted(t.items(), key=lambda x: (x[1]["pts"], x[1]["gd"], x[1]["gf"]), reverse=True)
    
    standings_md10 = get_standings_at(season_id, 10)
    standings_final = get_standings_at(season_id, 30)
    
    md10_pos = {t.upper(): i+1 for i, (t, _) in enumerate(standings_md10)}
    final_pos = {t.upper(): i+1 for i, (t, _) in enumerate(standings_final)}
    
    for team in set(list(md10_pos.keys()) + list(final_pos.keys())):
        p10 = md10_pos.get(team.upper(), 99)
        pf = final_pos.get(team.upper(), 99)
        
        # Comeback: bottom 5 at MD10 → top 5 final
        if p10 >= 12 and pf <= 5:
            all_streaks["comebacks"].append([team, season_id, p10, pf])
        
        # Collapse: top 5 at MD10 → bottom 5 final
        if p10 <= 5 and pf >= 12:
            all_streaks["collapses"].append([team, season_id, p10, pf])
        
        if pf == 1:
            team_records[team.upper()]["championships"] += 1
        if pf <= 4:
            team_records[team.upper()]["top4"] += 1
        if pf >= 15:
            team_records[team.upper()]["relegations"] += 1

# --- Sort and trim ---
win_streaks_sorted = sorted(all_streaks["win_streaks"], key=lambda x: x[2], reverse=True)
loss_streaks_sorted = sorted(all_streaks["loss_streaks"], key=lambda x: x[2], reverse=True)
best5_sorted = sorted(all_streaks["best_starts_5"], key=lambda x: x[2], reverse=True)
worst5_sorted = sorted(all_streaks["worst_starts_5"], key=lambda x: x[2])

# --- Build output ---
output = {
    "total_seasons_analyzed": len(seasons),
    "records": {
        "longest_win_streak": {
            "team": win_streaks_sorted[0][0],
            "season": win_streaks_sorted[0][1],
            "length": win_streaks_sorted[0][2],
            "from_md": win_streaks_sorted[0][3],
            "to_md": win_streaks_sorted[0][4]
        },
        "longest_loss_streak": {
            "team": loss_streaks_sorted[0][0],
            "season": loss_streaks_sorted[0][1],
            "length": loss_streaks_sorted[0][2],
            "from_md": loss_streaks_sorted[0][3],
            "to_md": loss_streaks_sorted[0][4]
        },
        "best_start_5_md": {
            "team": best5_sorted[0][0],
            "season": best5_sorted[0][1],
            "points": best5_sorted[0][2]
        },
        "worst_start_5_md": {
            "team": worst5_sorted[0][0],
            "season": worst5_sorted[0][1],
            "points": worst5_sorted[0][2]
        }
    },
    "top_win_streaks": [{"team": s[0], "season": s[1], "length": s[2], "mds": f"{s[3]}-{s[4]}"} for s in win_streaks_sorted[:20]],
    "top_loss_streaks": [{"team": s[0], "season": s[1], "length": s[2], "mds": f"{s[3]}-{s[4]}"} for s in loss_streaks_sorted[:20]],
    "best_starts": [{"team": s[0], "season": s[1], "pts_5md": s[2]} for s in best5_sorted[:10]],
    "worst_starts": [{"team": s[0], "season": s[1], "pts_5md": s[2]} for s in worst5_sorted[:10]],
    "comebacks": [{"team": c[0], "season": c[1], "from": f"#{c[2]} at MD10", "to": f"#{c[3]} final"} for c in sorted(all_streaks["comebacks"], key=lambda x: x[3])[:10]],
    "collapses": [{"team": c[0], "season": c[1], "from": f"#{c[2]} at MD10", "to": f"#{c[3]} final"} for c in sorted(all_streaks["collapses"], key=lambda x: x[2])[:10]],
}

# Per-team profiles
team_profiles = {}
for team, tr in sorted(team_records.items()):
    team_profiles[team] = {
        "seasons": tr["total_seasons"],
        "avg_pts": round(tr["total_pts"] / tr["total_seasons"], 1) if tr["total_seasons"] else 0,
        "championships": tr["championships"],
        "top4_finishes": tr["top4"],
        "relegations": tr["relegations"],
        "longest_win_streak": tr["longest_win_streak"],
        "longest_loss_streak": tr["longest_loss_streak"],
        "longest_unbeaten": tr["longest_unbeaten"],
        "longest_winless": tr["longest_winless"],
        "win_streaks_ge5": tr["win_streaks_ge5"],
        "loss_streaks_ge5": tr["loss_streaks_ge5"],
        "best_5md_start": tr["best_start_5"],
        "worst_5md_start": tr["worst_start_5"],
    }

# Save
with open(os.path.join(OUT, "streak_records.json"), 'w') as f:
    json.dump(output, f, indent=2)

with open(os.path.join(OUT, "team_streak_profiles.json"), 'w') as f:
    json.dump(team_profiles, f, indent=2)

print(f"\n=== STREAK ANALYSIS COMPLETE ===\n")

print(f"🏆 Longest win streak EVER:")
print(f"   {output['records']['longest_win_streak']['team']} — {output['records']['longest_win_streak']['length']} wins in a row (season {output['records']['longest_win_streak']['season'].split(':')[-1]})")

print(f"\n💀 Longest loss streak EVER:")
print(f"   {output['records']['longest_loss_streak']['team']} — {output['records']['longest_loss_streak']['length']} losses in a row (season {output['records']['longest_loss_streak']['season'].split(':')[-1]})")

print(f"\n🚀 Best 5-MD start EVER:")
print(f"   {output['records']['best_start_5_md']['team']} — {output['records']['best_start_5_md']['points']}/15 points (season {output['records']['best_start_5_md']['season'].split(':')[-1]})")

print(f"\n🐌 Worst 5-MD start EVER:")
print(f"   {output['records']['worst_start_5_md']['team']} — {output['records']['worst_start_5_md']['points']}/15 points (season {output['records']['worst_start_5_md']['season'].split(':')[-1]})")

print(f"\n📈 Top 10 Win Streaks:")
for i, s in enumerate(output['top_win_streaks'][:10], 1):
    print(f"   {i}. {s['team']} — {s['length']}W ({s['season'].split(':')[-1]})")

print(f"\n📉 Top 10 Loss Streaks:")
for i, s in enumerate(output['top_loss_streaks'][:10], 1):
    print(f"   {i}. {s['team']} — {s['length']}L ({s['season'].split(':')[-1]})")

print(f"\n🔄 Comebacks (bottom 5 at MD10 → top 5 final):")
for c in output['comebacks'][:5]:
    print(f"   {c['team']} — {c['from']} → {c['to']} ({c['season'].split(':')[-1]})")

print(f"\n💥 Collapses (top 5 at MD10 → bottom 5 final):")
for c in output['collapses'][:5]:
    print(f"   {c['team']} — {c['from']} → {c['to']} ({c['season'].split(':')[-1]})")

print(f"\n📁 Saved to: {OUT}/")
print(f"   - streak_records.json")
print(f"   - team_streak_profiles.json")
print(f"\n✅ DONE")
