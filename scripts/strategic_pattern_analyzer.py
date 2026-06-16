#!/usr/bin/env python3
"""
strategic_pattern_analyzer.py — Advanced VFL Trend Discovery.
Analyzes results based on relative league position at the time of match.
"""

import sys, os, logging
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

try:
    from common.db_manager import get_db
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

def analyze_patterns():
    with get_db() as cur:
        # 1. Underdog Spikes (Bottom 4 vs Top 4)
        logger.info("🔍 Analyzing Underdog Spikes (Rank 13-16 vs Rank 1-4)...")
        cur.execute("""
            WITH match_context AS (
                SELECT 
                    r.id, r.home_team, r.away_team, r.home_goals, r.away_goals,
                    s1.rank as home_rank, s2.rank as away_rank,
                    m.matchday_number
                FROM vfl_results_v2 r
                JOIN vfl_matchdays m ON r.matchday_id = m.id
                -- Get home team rank from PREVIOUS matchday (or MD1 if MD1)
                JOIN vfl_league_snapshots s1 ON s1.matchday_id = 
                    (SELECT id FROM vfl_matchdays WHERE season_id = m.season_id AND matchday_number = CASE WHEN m.matchday_number > 1 THEN m.matchday_number - 1 ELSE 1 END)
                    AND s1.team_name = r.home_team
                JOIN vfl_league_snapshots s2 ON s2.matchday_id = 
                    (SELECT id FROM vfl_matchdays WHERE season_id = m.season_id AND matchday_number = CASE WHEN m.matchday_number > 1 THEN m.matchday_number - 1 ELSE 1 END)
                    AND s2.team_name = r.away_team
                WHERE m.matchday_number > 5 -- Ignore early season noise
            )
            SELECT 
                COUNT(*) as total_matches,
                SUM(CASE WHEN (home_rank >= 13 AND away_rank <= 4 AND home_goals > away_goals) OR (away_rank >= 13 AND home_rank <= 4 AND away_goals > home_goals) THEN 1 ELSE 0 END) as underdog_wins,
                ROUND(CAST(SUM(CASE WHEN (home_rank >= 13 AND away_rank <= 4 AND home_goals > away_goals) OR (away_rank >= 13 AND home_rank <= 4 AND away_goals > home_goals) THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) as spike_rate
            FROM match_context
            WHERE (home_rank >= 13 AND away_rank <= 4) OR (away_rank >= 13 AND home_rank <= 4);
        """)
        spike = cur.fetchone()
        logger.info(f"   Total Top-vs-Bottom matches: {spike[0]}")
        logger.info(f"   Underdog Wins: {spike[1]} ({spike[2]}%)")

        # 2. The High-Draw Trap (Top 4 vs Mid 8-12)
        logger.info("\n🔍 Analyzing The High-Draw Trap (Rank 1-4 vs Rank 8-12)...")
        cur.execute("""
            WITH match_context AS (
                SELECT 
                    r.home_team, r.away_team, r.home_goals, r.away_goals,
                    s1.rank as home_rank, s2.rank as away_rank
                FROM vfl_results_v2 r
                JOIN vfl_matchdays m ON r.matchday_id = m.id
                JOIN vfl_league_snapshots s1 ON s1.matchday_id = 
                    (SELECT id FROM vfl_matchdays WHERE season_id = m.season_id AND matchday_number = CASE WHEN m.matchday_number > 1 THEN m.matchday_number - 1 ELSE 1 END)
                    AND s1.team_name = r.home_team
                JOIN vfl_league_snapshots s2 ON s2.matchday_id = 
                    (SELECT id FROM vfl_matchdays WHERE season_id = m.season_id AND matchday_number = CASE WHEN m.matchday_number > 1 THEN m.matchday_number - 1 ELSE 1 END)
                    AND s2.team_name = r.away_team
                WHERE m.matchday_number > 5
            )
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END) as draws,
                ROUND(CAST(SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) as draw_rate
            FROM match_context
            WHERE (home_rank <= 4 AND away_rank BETWEEN 8 AND 12) OR (away_rank <= 4 AND home_rank BETWEEN 8 AND 12);
        """)
        trap = cur.fetchone()
        logger.info(f"   Total Elite-vs-Mid matches: {trap[0]}")
        logger.info(f"   Draws: {trap[1]} ({trap[2]}%)")

        # 3. Identify specific fixtures that are "Draw Magnets"
        logger.info("\n🔍 Identifying Fixture-Specific Draw Magnets...")
        cur.execute("""
            SELECT 
                home_team, away_team, 
                COUNT(*) as matches,
                SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END) as draws,
                ROUND(CAST(SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) as draw_rate
            FROM vfl_results_v2
            GROUP BY home_team, away_team
            HAVING COUNT(*) >= 5 AND ROUND(CAST(SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END) AS NUMERIC) / COUNT(*) * 100, 2) >= 35
            ORDER BY draw_rate DESC;
        """)
        magnets = cur.fetchall()
        for m in magnets:
            logger.info(f"   🧲 {m[0]} vs {m[1]}: {m[3]}/{m[2]} draws ({m[4]}%)")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("strategic_analyzer")
    analyze_patterns()
