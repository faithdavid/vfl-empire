#!/usr/bin/env python3
import sys, logging
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

from common.db_manager import get_db

def main():
    print("="*60)
    print("  Under 3.5 Goals — Fixture Pattern Intelligence (123 Seasons)")
    print("="*60)
    
    with get_db() as cur:
        # We look for home_team, away_team permutations that are often U3.5
        # We require at least 50 occurrences for statistical significance
        query = """
            SELECT home_team, away_team, 
                   COUNT(*) as total_matches,
                   SUM(CASE WHEN (home_goals + away_goals) <= 3 THEN 1 ELSE 0 END) as u35_count,
                   ROUND(CAST(SUM(CASE WHEN (home_goals + away_goals) <= 3 THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) as hit_rate
            FROM vfl_results_v2
            GROUP BY home_team, away_team
            HAVING COUNT(*) >= 50
            ORDER BY hit_rate DESC, total_matches DESC
            LIMIT 30;
        """
        cur.execute(query)
        rows = cur.fetchall()
        
        print(f"{'Home Team':<20} | {'Away Team':<20} | {'Matches':>7} | {'U3.5 Rate':>9}")
        print("-" * 65)
        for h, a, total, u35, rate in rows:
            print(f"{h:<20} | {a:<20} | {total:>7} | {rate:>8}%")
            
        print("\n" + "="*60)
        print("  Switched Fixtures (Home or Away) — Under 3.5 Combined Rate")
        print("="*60)
        
        query_switched = """
            SELECT LEAST(home_team, away_team) as t1, GREATEST(home_team, away_team) as t2,
                   COUNT(*) as total_matches,
                   SUM(CASE WHEN (home_goals + away_goals) <= 3 THEN 1 ELSE 0 END) as u35_count,
                   ROUND(CAST(SUM(CASE WHEN (home_goals + away_goals) <= 3 THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) as hit_rate
            FROM vfl_results_v2
            GROUP BY LEAST(home_team, away_team), GREATEST(home_team, away_team)
            HAVING COUNT(*) >= 100
            ORDER BY hit_rate DESC, total_matches DESC
            LIMIT 30;
        """
        cur.execute(query_switched)
        rows = cur.fetchall()
        
        print(f"{'Team 1':<20} | {'Team 2':<20} | {'Matches':>7} | {'U3.5 Rate':>9}")
        print("-" * 65)
        for t1, t2, total, u35, rate in rows:
            print(f"{t1:<20} | {t2:<20} | {total:>7} | {rate:>8}%")

if __name__ == "__main__":
    main()
