#!/usr/bin/env python3
import psycopg2
from collections import defaultdict
import sys
import os

# Connect to DB
conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")
cur = conn.cursor()

# 1. How many unique fixtures per season?
cur.execute("""
    SELECT season, count(*) as total_matches, count(DISTINCT home || '-' || away) as unique_fixtures
    FROM matches
    GROUP BY season
    LIMIT 5;
""")
print("=== Matches per Season ===")
for row in cur.fetchall():
    print(f"Season: {row[0]}, Total Matches: {row[1]}, Unique H-A Pairings: {row[2]}")

# 2. Check for shifting patterns
# Let's get the fixtures for the first 5 matchdays across a sequence of seasons.
# We need to sort seasons chronologically. We can use the minimum ID or timestamp.
cur.execute("""
    SELECT season, min(id) as first_id 
    FROM matches 
    GROUP BY season 
    ORDER BY first_id DESC 
    LIMIT 10;
""")
seasons = [row[0] for row in cur.fetchall()]
seasons.reverse() # chronological

if len(seasons) < 2:
    print("Not enough seasons to compare.")
    sys.exit()

def get_schedule(season):
    cur.execute("SELECT day, home, away FROM matches WHERE season = %s ORDER BY day, home", (season,))
    schedule = defaultdict(set)
    for day, h, a in cur.fetchall():
        # Treat as sorted pair to ignore home/away for a moment, or keep strict.
        # Let's keep strict Home-Away first.
        schedule[day].add(f"{h}-{a}")
    return schedule

print("\n=== Fixture Rotation Analysis ===")
schedules = {s: get_schedule(s) for s in seasons}

# Let's compare Season N vs Season N+1
for i in range(len(seasons) - 1):
    s1 = seasons[i]
    s2 = seasons[i+1]
    
    sch1 = schedules[s1]
    sch2 = schedules[s2]
    
    # Check where MD1 of Season 1 went in Season 2
    md1_s1 = sch1[1]
    if not md1_s1: continue
    
    found_in_md = None
    for md in range(1, 31):
        if len(md1_s1.intersection(sch2[md])) > 4: # If more than 4 matches overlap, it's a shifted matchday
            found_in_md = md
            break
            
    if found_in_md:
        print(f"MD1 of {s1} became MD{found_in_md} of {s2}")
    else:
        # Check if it flipped (Away-Home)
        md1_s1_flipped = set(f"{x.split('-')[1]}-{x.split('-')[0]}" for x in md1_s1)
        found_flipped = None
        for md in range(1, 31):
            if len(md1_s1_flipped.intersection(sch2[md])) > 4:
                found_flipped = md
                break
        if found_flipped:
            print(f"MD1 of {s1} became MD{found_flipped} of {s2} (Roles Reversed)")
        else:
            print(f"MD1 of {s1} is scattered randomly in {s2}")

conn.close()
