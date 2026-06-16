#!/usr/bin/env python3
"""
industrial_data_collector.py — Deep Historical VFL Scanner.
Reconstructs the entire VFL history matchday-by-matchday.
"""

import sys, os, time, logging, json
from pathlib import Path
from datetime import datetime, timezone

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

try:
    from common.db_manager import get_db
    from msport_api import get_season_list, get_results, _normalise_team_name
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("/home/ubuntu/faith-workspace/vfl-empire/logs/industrial_collector.log"), logging.StreamHandler()]
)
logger = logging.getLogger("industrial_collector")

def reconstruct_table(results_list):
    """Computes a standings table from a list of match results."""
    from collections import defaultdict
    col = defaultdict(lambda: {
        "played": 0, "won": 0, "draw": 0, "lost": 0,
        "goalsFor": 0, "goalsAgainst": 0, "lastFive": []
    })
    
    # Sort results by matchday to ensure lastFive is chronological
    # (Assuming results_list is already in MD order)
    for r in results_list:
        home = _normalise_team_name(r.get("home_team", ""))
        away = _normalise_team_name(r.get("away_team", ""))
        hg = r.get("home_goals", 0)
        ag = r.get("away_goals", 0)
        
        col[home]["played"] += 1
        col[home]["goalsFor"] += hg
        col[home]["goalsAgainst"] += ag
        col[away]["played"] += 1
        col[away]["goalsFor"] += ag
        col[away]["goalsAgainst"] += hg
        
        if hg > ag:
            col[home]["won"] += 1
            col[home]["lastFive"].append("W")
            col[away]["lost"] += 1
            col[away]["lastFive"].append("L")
        elif ag > hg:
            col[away]["won"] += 1
            col[away]["lastFive"].append("W")
            col[home]["lost"] += 1
            col[home]["lastFive"].append("L")
        else:
            col[home]["draw"] += 1
            col[home]["lastFive"].append("D")
            col[away]["draw"] += 1
            col[away]["lastFive"].append("D")
            
    table = []
    for team, s in col.items():
        gd = s["goalsFor"] - s["goalsAgainst"]
        pts = s["won"] * 3 + s["draw"]
        table.append({
            "team": team, "points": pts, "played": s["played"],
            "won": s["won"], "draw": s["draw"], "lost": s["lost"],
            "gf": s["goalsFor"], "ga": s["goalsAgainst"], "gd": gd,
            "form": "".join(s["lastFive"][-5:])
        })
    
    # Sort: Points, GD, GF
    table.sort(key=lambda x: (-x["points"], -x["gd"], -x["gf"]))
    for i, entry in enumerate(table, 1):
        entry["rank"] = i
    return table

def run_deep_scan(season_limit=None):
    logger.info("🚀 Starting Industrial VFL Deep Scan...")
    
    seasons = get_season_list()
    if not seasons:
        logger.error("Could not fetch season list.")
        return
    
    logger.info(f"Found {len(seasons)} seasons in MSport API.")
    if season_limit:
        seasons = seasons[:season_limit]
        logger.info(f"Limited to first {season_limit} seasons.")

    # Sort seasons by time ascending to build history chronologically
    seasons.sort(key=lambda x: x.get("startTime", 0))

    with get_db() as cur:
        for s_idx, s_data in enumerate(seasons):
            s_id_uuid = s_data["seasonId"]
            s_name = s_data.get("seasonName", f"Season {s_id_uuid[:6]}")
            
            logger.info(f"Processing {s_name} ({s_id_uuid})...")
            
            # 1. Upsert Season
            cur.execute("""
                INSERT INTO vfl_seasons (season_id, season_name, start_time)
                VALUES (%s, %s, %s)
                ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name
                RETURNING id
            """, (s_id_uuid, s_name, datetime.fromtimestamp(s_data.get("startTime", 0)/1000, tz=timezone.utc)))
            db_season_id = cur.fetchone()[0]
            
            md_list = s_data.get("matchDay", [])
            if not md_list:
                logger.warning(f"No matchdays found for {s_name}")
                continue
                
            all_season_results = []
            
            for md_num in range(1, max(md_list) + 1):
                # 2. Upsert MatchDay
                cur.execute("""
                    INSERT INTO vfl_matchdays (season_id, matchday_number)
                    VALUES (%s, %s)
                    ON CONFLICT (season_id, matchday_number) DO UPDATE SET status = 'FINISHED'
                    RETURNING id
                """, (db_season_id, md_num))
                db_md_id = cur.fetchone()[0]
                
                # 3. Fetch and Insert Results
                results = get_results(s_id_uuid, md_num)
                if not results:
                    continue
                
                current_md_results = []
                for r in results:
                    home = _normalise_team_name(r.get("homeTeam", ""))
                    away = _normalise_team_name(r.get("awayTeam", ""))
                    event_id = (
                        r.get("eventId")
                        or r.get("id")
                        or f"{s_id_uuid}:{md_num}:{home}:{away}"
                    )
                    ft = r.get("fullTime", "0:0")
                    try:
                        hg, ag = map(int, str(ft).split(":"))
                    except: hg, ag = 0, 0
                    
                    cur.execute("""
                        INSERT INTO vfl_results_v2 (matchday_id, event_id, home_team, away_team, home_goals, away_goals)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (matchday_id, home_team, away_team) DO NOTHING
                    """, (db_md_id, event_id, home, away, hg, ag))
                    
                    res_obj = {"home_team": home, "away_team": away, "home_goals": hg, "away_goals": ag}
                    current_md_results.append(res_obj)
                    all_season_results.append(res_obj)
                
                # 4. Compute and Insert Snapshot for this MD
                logger.info(f"   MD {md_num}: {len(current_md_results)} results. Reconstructing table...")
                md_table = reconstruct_table(all_season_results)
                
                for entry in md_table:
                    cur.execute("""
                        INSERT INTO vfl_league_snapshots 
                        (matchday_id, team_name, rank, points, played, won, draw, lost, goals_for, goals_against, goal_diff, form)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (matchday_id, team_name) DO UPDATE SET
                        rank = EXCLUDED.rank, points = EXCLUDED.points, form = EXCLUDED.form
                    """, (db_md_id, entry["team"], entry["rank"], entry["points"], entry["played"], 
                          entry["won"], entry["draw"], entry["lost"], entry["gf"], entry["ga"], entry["gd"], entry["form"]))
            
            logger.info(f"✅ Finished processing {s_name}")
            # Commit per season
            cur.connection.commit()

    logger.info("🏁 Deep Scan Complete.")

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_deep_scan(season_limit=limit)
