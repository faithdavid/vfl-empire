#!/usr/bin/env python3
import sys, time, logging
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

from common.msport_client import get_results, fetch_json, BASE_URL, _normalise_team_name
from common.db_manager import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DEEP_BACKFILL")

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

def backfill_season(season_id, season_name):
    logger.info(f"🚀 Backfilling {season_name} ({season_id})...")
    with get_db() as cur:
        cur.execute("INSERT INTO vfl_seasons (season_id, season_name) VALUES (%s, %s) ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name RETURNING id", (season_id, season_name))
        db_sid = cur.fetchone()[0]
        
        for md in range(1, 31):
            results = get_results(season_id, md)
            if not results:
                logger.warning(f"   MD {md} empty, skipping season.")
                break
            
            cur.execute("INSERT INTO vfl_matchdays (season_id, matchday_number, status) VALUES (%s, %s, 'FINISHED') ON CONFLICT (season_id, matchday_number) RETURNING id", (db_sid, md))
            db_md_id = cur.fetchone()[0]
            
            for r in results:
                h, a, ft = _normalise_team_name(r.get("homeTeam", "")), _normalise_team_name(r.get("awayTeam", "")), r.get("fullTime", "0:0")
                try: hg, ag = map(int, str(ft).split(":"))
                except: hg, ag = 0, 0
                eid = r.get("eventId") or r.get("id") or f"{season_id}:{md}:{h}:{a}"
                cur.execute("INSERT INTO vfl_results_v2 (matchday_id, event_id, home_team, away_team, home_goals, away_goals) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (db_md_id, str(eid), h, a, hg, ag))
            
            table = reconstruct_table(cur, db_sid, md)
            for e in table:
                cur.execute("INSERT INTO vfl_league_snapshots (matchday_id, team_name, rank, points, played, won, draw, lost, goals_for, goals_against, goal_diff, form) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (matchday_id, team_name) DO NOTHING", (db_md_id, e["team"], e["rank"], e["points"], e["played"], e["won"], e["draw"], e["lost"], e["gf"], e["ga"], e["gd"], e["form"]))
        logger.info(f"   ✅ Finished {season_name}")

def main():
    # Start from known oldest in DB
    with get_db() as cur:
        cur.execute("SELECT season_id, season_name FROM vfl_seasons ORDER BY captured_at ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            logger.error("No seasons in DB to start from.")
            return
        
        # vf:season:3091832 -> VFLM 5108
        curr_id_num = int(row[0].split(":")[-1])
        curr_name_num = int(row[1].replace("VFLM", "").strip())
        
    logger.info(f"Starting deep scan backwards from VFLM {curr_name_num} ({curr_id_num})...")
    
    failures = 0
    while failures < 5:
        # Try to find the next season ID
        # We know they are ~25-30 apart.
        found = False
        for step in range(20, 40):
            test_id = f"vf:season:{curr_id_num - step}"
            res = get_results(test_id, 1)
            if res:
                curr_id_num -= step
                curr_name_num -= 1
                backfill_season(test_id, f"VFLM {curr_name_num}")
                found = True
                failures = 0
                break
        
        if not found:
            logger.warning(f"Could not find season before {curr_name_num} at expected steps.")
            # Try a broader search? 
            # Actually, let's just stop if we hit a gap.
            failures += 1
            curr_id_num -= 30 # Skip a bit and try again
            curr_name_num -= 1

if __name__ == "__main__":
    main()
