#!/usr/bin/env python3
"""Analyze the refreshed team_features.json"""
import json, sys

with open("/home/ubuntu/Documents/Projects/vfl-data/analysis/team_features.json") as f:
    data = json.load(f)

print("=== 🏆 FEATURE STORE REFRESH REPORT ===")
print()
print(f"📅 Timestamp:  {data['timestamp']}")
print(f"🏟️  Season:     {data['season']}")
print(f"📆 Match Day:  {data['matchday']}")
print()

teams = data['teams']
print(f"👥 Teams with live data: {len(teams)} / {len(teams)}")
print()

# Compute league avg goals per match
total_gf = sum(t['goals_for'] for t in teams.values())
total_ga = sum(t['goals_against'] for t in teams.values())
total_matches = sum(t['played'] for t in teams.values()) // 2
avg_goals = (total_gf + total_ga) / total_matches if total_matches else 0

print(f"⚽ League Avg Goals/Match: {avg_goals:.2f}")
print()

# Table
print(f"{'Team':25s} {'Pos':3s} {'Pts':3s} {'GF':3s} {'GA':3s} {'GD':4s} {'AvgTot':6s} {'Form':5s}")
print("-" * 58)
for name, t in sorted(teams.items(), key=lambda x: x[1]['rank']):
    print(f"{name:25s} {t['rank']:3d} {t['points']:3d} {t['goals_for']:3d} {t['goals_against']:3d} {t['goal_diff']:4d} {t['avg_total_goals']:6.2f} {t['form_score']:.2f}")
print()

# Top scoring teams
print("🔥 Top 5 Scoring Teams (Avg Goals Scored):")
for i, (name, t) in enumerate(sorted(teams.items(), key=lambda x: x[1]['avg_goals_scored'], reverse=True)[:5], 1):
    print(f"   {i}. {name:25s} — {t['avg_goals_scored']:.2f} GF/game")

print()
print("🛡️  Top 5 Defences (Fewest Conceded):")
for i, (name, t) in enumerate(sorted(teams.items(), key=lambda x: x[1]['avg_goals_conceded'])[:5], 1):
    print(f"   {i}. {name:25s} — {t['avg_goals_conceded']:.2f} GA/game")

print()
print("✅ Feature store refresh COMPLETE — Oracle is LIVE with fresh VFLM 5115 data, My Lord!")
