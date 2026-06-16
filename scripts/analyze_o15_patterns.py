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
    print("  Over 1.5 Goals — Fixture Pattern Intelligence (123 Seasons)")
    print("="*60)
    
    with get_db() as cur:
        # Check Leeds vs Chelsea specifically
        cur.execute("""
            SELECT LEAST(home_team, away_team) as t1, GREATEST(home_team, away_team) as t2,
                   COUNT(*) as total_matches,
                   SUM(CASE WHEN (home_goals + away_goals) >= 2 THEN 1 ELSE 0 END) as o15_count,
                   ROUND(CAST(SUM(CASE WHEN (home_goals + away_goals) >= 2 THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) as hit_rate
            FROM vfl_results_v2
            WHERE (home_team = 'Leeds' AND away_team = 'Chelsea') OR (home_team = 'Chelsea' AND away_team = 'Leeds')
            GROUP BY LEAST(home_team, away_team), GREATEST(home_team, away_team);
        """)
        row = cur.fetchone()
        if row:
            print(f"Leeds vs Chelsea | Matches: {row[2]} | O1.5 Rate: {row[4]}%")
        
        print("\nTop Over 1.5 Pairs:")
        query_o15 = """
            SELECT LEAST(home_team, away_team) as t1, GREATEST(home_team, away_team) as t2,
                   COUNT(*) as total_matches,
                   SUM(CASE WHEN (home_goals + away_goals) >= 2 THEN 1 ELSE 0 END) as o15_count,
                   ROUND(CAST(SUM(CASE WHEN (home_goals + away_goals) >= 2 THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) as hit_rate
            FROM vfl_results_v2
            GROUP BY LEAST(home_team, away_team), GREATEST(home_team, away_team)
            HAVING COUNT(*) >= 100
            ORDER BY hit_rate DESC
            LIMIT 20;
        """
        cur.execute(query_o15)
        rows = cur.fetchall()
        
        print(f"{'Team 1':<20} | {'Team 2':<20} | {'Matches':>7} | {'O1.5 Rate':>9}")
        print("-" * 65)
        for t1, t2, total, o15, rate in rows:
            print(f"{t1:<20} | {t2:<20} | {total:>7} | {rate:>8}%")

if __name__ == "__main__":
    main()
