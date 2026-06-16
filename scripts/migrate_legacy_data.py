#!/usr/bin/env python3
import sys, logging
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

from common.db_manager import get_db
from common.msport_client import _normalise_team_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MIGRATOR")

def reconstruct_table(cur, db_season_id, target_md):
    from collections import defaultdict
    col = defaultdict(lambda: {"played": 0, "won": 0, "draw": 0, "lost": 0, "gf": 0, "ga": 0, "lastFive": []})
    cur.execute("""
        SELECT home_team, away_team, home_goals, away_goals
        FROM vfl_results_v2 r JOIN vfl_matchdays m ON r.matchday_id = m.id
        WHERE m.season_id = %s AND m.matchday_number <= %s ORDER BY m.matchday_number ASC
    """, (db_season_id, target_md))
    for r in cur.fetchall():
        h, a, hg, ag = r[0], r[1], r[2], r[3]
        col[h]["played"] += 1; col[h]["gf"] += hg; col[h]["ga"] += ag
        col[a]["played"] += 1; col[a]["gf"] += ag; col[a]["ga"] += hg
        if hg > ag:
            col[h]["won"] += 1; col[h]["lastFive"].append("W"); col[a]["lost"] += 1; col[a]["lastFive"].append("L")
        elif ag > hg:
            col[a]["won"] += 1; col[a]["lastFive"].append("W"); col[h]["lost"] += 1; col[h]["lastFive"].append("L")
        else:
            col[h]["draw"] += 1; col[h]["lastFive"].append("D"); col[a]["draw"] += 1; col[a]["lastFive"].append("D")
    table = []
    for team, s in col.items():
        table.append({"team": team, "points": s["won"] * 3 + s["draw"], "played": s["played"], "won": s["won"], "draw": s["draw"], "lost": s["lost"], "gf": s["gf"], "ga": s["ga"], "gd": s["gf"] - s["ga"], "form": "".join(s["lastFive"][-5:])})
    table.sort(key=lambda x: (-x["points"], -x["gd"], -x["gf"]))
    for i, entry in enumerate(table, 1): entry["rank"] = i
    return table

def main():
    logger.info("Starting legacy data migration (results -> vfl_results_v2)...")
    with get_db() as cur:
        # Get all distinct seasons from the old results table
        cur.execute("SELECT DISTINCT season_id, season_name FROM results WHERE season_id != ''")
        seasons = cur.fetchall()
        logger.info(f"Found {len(seasons)} seasons to migrate.")
        
        for sid, sname in seasons:
            logger.info(f"Processing {sname} ({sid})...")
            cur.execute("INSERT INTO vfl_seasons (season_id, season_name) VALUES (%s, %s) ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name RETURNING id", (sid, sname))
            db_sid = cur.fetchone()[0]
            
            # Get matchdays for this season
            cur.execute("SELECT DISTINCT match_day FROM results WHERE season_id = %s ORDER BY match_day ASC", (sid,))
            mds = [r[0] for r in cur.fetchall()]
            
            for md in mds:
                cur.execute("INSERT INTO vfl_matchdays (season_id, matchday_number, status) VALUES (%s, %s, 'FINISHED') ON CONFLICT (season_id, matchday_number) DO UPDATE SET status = 'FINISHED' RETURNING id", (db_sid, md))
                db_md_id = cur.fetchone()[0]
                
                cur.execute("SELECT event_id, home_team, away_team, home_goals, away_goals FROM results WHERE season_id = %s AND match_day = %s", (sid, md))
                results = cur.fetchall()
                for eid, h, a, hg, ag in results:
                    h_norm = _normalise_team_name(h)
                    a_norm = _normalise_team_name(a)
                    cur.execute("INSERT INTO vfl_results_v2 (matchday_id, event_id, home_team, away_team, home_goals, away_goals) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (db_md_id, eid, h_norm, a_norm, hg, ag))
                
                # Reconstruct table and snapshots
                table = reconstruct_table(cur, db_sid, md)
                for e in table:
                    cur.execute("INSERT INTO vfl_league_snapshots (matchday_id, team_name, rank, points, played, won, draw, lost, goals_for, goals_against, goal_diff, form) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (matchday_id, team_name) DO UPDATE SET rank=EXCLUDED.rank, points=EXCLUDED.points, form=EXCLUDED.form", (db_md_id, e["team"], e["rank"], e["points"], e["played"], e["won"], e["draw"], e["lost"], e["gf"], e["ga"], e["gd"], e["form"]))
            logger.info(f"   ✅ Finished migrating {sname}")
            
    logger.info("Migration complete!")

if __name__ == "__main__":
    main()
