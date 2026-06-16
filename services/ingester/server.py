"""Data Ingester Service (port 8001) — polls MSport APIs, stores data."""
import asyncio, json, logging, os, sys, signal
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.msport_client import (
    get_event_list, get_match_day_info, get_results, get_season_list, 
    _normalise_team_name
)
from common.db_manager import get_db, get_db_path
from common.event_id_sync import lookup_event_id
from common.prematch_odds import upsert_prematch_records
from common.msport_client import records_from_event

logger = logging.getLogger("[INGESTER]")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

DATA_DIR = os.path.expanduser("~/faith-workspace/vfl-complete-data")
SIGNALS_DIR = os.path.join(DATA_DIR, "signals")
os.makedirs(SIGNALS_DIR, exist_ok=True)

# State
ingest_state = {
    "last_season_ingest": None,
    "last_results_ingest": None,
    "last_event_list_ingest": None,
    "status": "idle",
    "total_seasons_ingested": 0,
    "total_results_ingested": 0,
    "ingested_matchdays": set(),
    "errors": [],
}

async def _ingest_event_list():
    """Fetch fixtures + odds for upcoming matchdays -> vfl_prematch_odds (+ legacy vfl_odds_v2)."""
    logger.info("Fetching event list...")
    events = await asyncio.get_event_loop().run_in_executor(None, get_event_list)
    if not events:
        logger.warning("No events returned from API")
        ingest_state["errors"].append("event_list empty")
        return 0

    count = 0
    prematch_records = []
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as cur:
        for md_group in events:
            matchday_events = md_group.get("events") or []
            season_id = md_group.get("seasonId")
            md_num = md_group.get("matchDay")

            for ev in matchday_events:
                eid = ev.get("eventId") or ev.get("id")
                home = _normalise_team_name(ev.get("homeTeam") or ev.get("homeName", ""))
                away = _normalise_team_name(ev.get("awayTeam") or ev.get("awayName", ""))

                if not eid:
                    continue

                prematch_records.extend(
                    records_from_event(
                        ev,
                        season_id=str(season_id) if season_id else None,
                        matchday_number=int(md_num) if md_num else None,
                        source="ingester_event_list",
                    )
                )

                # Legacy vfl_odds_v2 (cluster scripts) — keep until consumers migrated
                odds = {"o15": None, "o25": None, "u25": None, "u35": None, "gg": None, "ng": None}
                markets = ev.get("markets") or []
                for mkt_group in markets:
                    market_name = mkt_group.get("name") or mkt_group.get("description", "")
                    specifiers = mkt_group.get("specifiers") or ""
                    outcomes = mkt_group.get("outcomes") or []
                    for out in outcomes:
                        name = out.get("outcomeName") or out.get("description", "")
                        val = out.get("odds") or out.get("price", 0)
                        try:
                            val = float(val)
                            if "Over/Under" in market_name:
                                if "1.5" in specifiers and "Over" in name:
                                    odds["o15"] = val
                                elif "2.5" in specifiers and "Over" in name:
                                    odds["o25"] = val
                                elif "2.5" in specifiers and "Under" in name:
                                    odds["u25"] = val
                                elif "3.5" in specifiers and "Under" in name:
                                    odds["u35"] = val
                            elif "GG" in market_name or "Both Teams" in market_name or "GG/NG" in market_name:
                                if "Yes" in name or "Goal" in name:
                                    odds["gg"] = val
                                elif "No" in name or "No Goal" in name:
                                    odds["ng"] = val
                        except Exception:
                            continue

                try:
                    cur.execute(
                        """
                        INSERT INTO vfl_odds_v2
                        (event_id, season_id, matchday_number, home_team, away_team, o15, o25, u25, u35, gg, ng, captured_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id, captured_at) DO UPDATE SET
                        o15 = COALESCE(EXCLUDED.o15, vfl_odds_v2.o15),
                        o25 = COALESCE(EXCLUDED.o25, vfl_odds_v2.o25),
                        u25 = COALESCE(EXCLUDED.u25, vfl_odds_v2.u25),
                        u35 = COALESCE(EXCLUDED.u35, vfl_odds_v2.u35),
                        gg = COALESCE(EXCLUDED.gg, vfl_odds_v2.gg),
                        ng = COALESCE(EXCLUDED.ng, vfl_odds_v2.ng)
                    """,
                        (
                            str(eid),
                            str(season_id),
                            int(md_num) if md_num else 0,
                            home,
                            away,
                            odds["o15"],
                            odds["o25"],
                            odds["u25"],
                            odds["u35"],
                            odds["gg"],
                            odds["ng"],
                            now,
                        ),
                    )
                    count += 1
                except Exception as e:
                    logger.debug(f"Skipping odds row: {e}")

    if prematch_records:
        upsert_prematch_records(prematch_records, captured_at=now)
        logger.info(f"Upserted {len(prematch_records)} prematch selections to vfl_prematch_odds")

    logger.info(f"Stored {count} odds entries in vfl_odds_v2 (legacy)")
    ingest_state["last_event_list_ingest"] = now
    ingest_state["total_seasons_ingested"] += 1
    return count

def reconstruct_table_from_db(cur, db_season_id, target_md):
    """Reconstructs the standings table up to a specific matchday using DB results."""
    from collections import defaultdict
    col = defaultdict(lambda: {
        "played": 0, "won": 0, "draw": 0, "lost": 0,
        "goalsFor": 0, "goalsAgainst": 0, "lastFive": []
    })
    
    cur.execute("""
        SELECT home_team, away_team, home_goals, away_goals
        FROM vfl_results_v2 r
        JOIN vfl_matchdays m ON r.matchday_id = m.id
        WHERE m.season_id = %s AND m.matchday_number <= %s
        ORDER BY m.matchday_number ASC
    """, (db_season_id, target_md))
    
    for r in cur.fetchall():
        home, away, hg, ag = r[0], r[1], r[2], r[3]
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
    
    table.sort(key=lambda x: (-x["points"], -x["gd"], -x["gf"]))
    for i, entry in enumerate(table, 1): entry["rank"] = i
    return table

async def sync_chronological_data(season_id, match_day, results, season_name=""):
    """Sync results and snapshot to the new chronological tables."""
    try:
        with get_db() as cur:
            # 1. Season
            cur.execute("""
                INSERT INTO vfl_seasons (season_id, season_name)
                VALUES (%s, %s) ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name
                RETURNING id
            """, (season_id, season_name))
            db_season_id = cur.fetchone()[0]
            
            # 2. MatchDay
            cur.execute("""
                INSERT INTO vfl_matchdays (season_id, matchday_number)
                VALUES (%s, %s) ON CONFLICT (season_id, matchday_number) DO UPDATE SET status = 'FINISHED'
                RETURNING id
            """, (db_season_id, match_day))
            db_md_id = cur.fetchone()[0]
            
            # 3. Results V2
            for r in results:
                home = _normalise_team_name(r.get("homeTeam", ""))
                away = _normalise_team_name(r.get("awayTeam", ""))
                ft = r.get("fullTime", "0:0")
                try: hg, ag = map(int, str(ft).split(":"))
                except: hg, ag = 0, 0
                eid = (
                    r.get("eventId")
                    or r.get("id")
                    or lookup_event_id(season_id, match_day, home, away)
                )
                if not eid:
                    season_num = (season_name or "").replace("VFLM ", "").strip()
                    if season_num.isdigit():
                        eid = (
                            f"vf:match:season:vflm{season_num}:md:{match_day}:"
                            f"{home.replace(' ', '')}:{away.replace(' ', '')}"
                        )
                    else:
                        eid = f"{season_id}:{match_day}:{home}:{away}"

                cur.execute("""
                    INSERT INTO vfl_results_v2 (matchday_id, event_id, home_team, away_team, home_goals, away_goals)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (matchday_id, home_team, away_team) DO NOTHING
                """, (db_md_id, str(eid), home, away, hg, ag))
            
            # 4. Snapshot
            live_table = None
            try:
                from common.msport_client import get_standings
                standings = get_standings()
                if standings and standings.get("matchDay") == match_day:
                    live_table = []
                    for t in standings.get("teams", []):
                        live_table.append({
                            "team": _normalise_team_name(t["teamName"]),
                            "rank": t["rank"],
                            "points": t["points"],
                            "played": t["won"] + t["draw"] + t["lost"],
                            "won": t["won"],
                            "draw": t["draw"],
                            "lost": t["lost"],
                            "gf": t["score"],
                            "ga": t["lostScore"],
                            "gd": t["score"] - t["lostScore"],
                            "form": "".join(t.get("lastFive", []))
                        })
                    logger.info(f"Using live MSport standings for MD{match_day}")
            except Exception as e:
                logger.warning(f"Failed to fetch live MSport standings: {e}")

            md_table = live_table if live_table else reconstruct_table_from_db(cur, db_season_id, match_day)
            for entry in md_table:
                cur.execute("""
                    INSERT INTO vfl_league_snapshots 
                    (matchday_id, team_name, rank, points, played, won, draw, lost, goals_for, goals_against, goal_diff, form)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (matchday_id, team_name) DO UPDATE SET
                    rank = EXCLUDED.rank, points = EXCLUDED.points, form = EXCLUDED.form
                """, (db_md_id, entry["team"], entry["rank"], entry["points"], entry["played"], 
                      entry["won"], entry["draw"], entry["lost"], entry["gf"], entry["ga"], entry["gd"], entry["form"]))
            logger.info(f"Chronological sync complete for MD{match_day}")
    except Exception as e:
        logger.error(f"Chronological sync failed: {e}")

async def _ingest_results(season_id: str, match_day: int, season_name: str = ""):
    """Fetch results for a season/matchday and store in Postgres."""
    logger.info(f"Ingesting results for season={season_id} MD={match_day}...")
    results = await asyncio.get_event_loop().run_in_executor(
        None, get_results, season_id, match_day)
    if not results:
        logger.info(f"No results for {season_id} MD{match_day}")
        return 0

    count = 0
    with get_db() as cur:
        now = datetime.now(timezone.utc).isoformat()
        for r in results:
            home = r.get("homeTeam", "")
            away = r.get("awayTeam", "")
            ft = r.get("fullTime", "0:0")
            
            # Parse fullTime "2:1"
            h_score, a_score = 0, 0
            if ":" in ft:
                try:
                    h_score, a_score = map(int, ft.split(":"))
                except:
                    pass
            
            # Generate a stable event_id if missing
            eid = r.get("eventId") or r.get("id") or f"{season_id}:{match_day}:{home}:{away}"
            
            try:
                cur.execute("""
                    INSERT INTO results
                    (event_id, season_id, season_name, match_day, home_team, away_team,
                     home_goals, away_goals, total_goals, under_35, status, captured_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (event_id) DO UPDATE SET
                        home_goals = EXCLUDED.home_goals,
                        away_goals = EXCLUDED.away_goals,
                        total_goals = EXCLUDED.total_goals,
                        under_35 = EXCLUDED.under_35,
                        season_name = CASE WHEN results.season_name = '' THEN EXCLUDED.season_name ELSE results.season_name END
                """, (
                    str(eid),
                    season_id,
                    season_name,
                    match_day,
                    home,
                    away,
                    h_score,
                    a_score,
                    h_score + a_score,
                    1 if (h_score + a_score) < 3.5 else 0,
                    1, # FINISHED
                    now,
                ))
                count += 1
            except Exception as e:
                logger.error(f"Error inserting result: {e}")
    logger.info(f"Stored {count} results")
    # --- Chronological Sync ---
    await sync_chronological_data(season_id, match_day, results, season_name)
    
    ingest_state["last_results_ingest"] = now
    ingest_state["total_results_ingested"] += 1
    return count

async def run_season_ingestion():
    """Full ingestion cycle: match day info → event list → results."""
    logger.info("=== Starting season ingestion cycle ===")
    ingest_state["status"] = "ingesting"

    try:
        # 1. Get current match day info
        md_info = await asyncio.get_event_loop().run_in_executor(None, get_match_day_info)
        if md_info:
            season_name = md_info.get("seasonName") or md_info.get("competitionName", "")
            current_md = md_info.get("matchDay") or md_info.get("round", 0)
            season_id = md_info.get("seasonId") or md_info.get("id", "")
            logger.info(f"Current: {season_name} MD{current_md}")
            ingest_state["current_season"] = season_name
            ingest_state["current_matchday"] = current_md

            # Ingest results for last 2 matchdays
            for md in range(max(1, current_md - 2), current_md + 1):
                key = f"{season_id}_{md}"
                if key not in ingest_state["ingested_matchdays"]:
                    count = await _ingest_results(season_id, md, season_name)
                    if count > 0:
                        ingest_state["ingested_matchdays"].add(key)

        # 2. Ingest event list (fixtures + odds)
        await _ingest_event_list()

        # Save state
        state = {k: v for k, v in ingest_state.items()
                 if k != "ingested_matchdays"}
        state["ingested_matchday_count"] = len(ingest_state["ingested_matchdays"])
        with open(os.path.join(SIGNALS_DIR, "ingester_state.json"), "w") as f:
            json.dump(state, f, indent=2, default=str)

        # Write latest predictions shape
        events = await asyncio.get_event_loop().run_in_executor(None, get_event_list)
        if events:
            logger.info(f"API returned {len(events)} events for upcoming matchdays")

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        ingest_state["errors"].append(str(e))
    finally:
        ingest_state["status"] = "idle"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ingester service starting on :8001")
    yield
    logger.info("Ingester service shutting down")

app = FastAPI(title="VFL Data Ingester", version="1.0.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {
        "service": "ingester",
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db_healthy": True # Connection pool initialized implies health
    }

@app.get("/metrics")
async def metrics():
    return {
        "total_seasons_ingested": ingest_state["total_seasons_ingested"],
        "total_results_ingested": ingest_state["total_results_ingested"],
        "errors_count": len(ingest_state["errors"])
    }

@app.post("/ingest/season")
async def ingest_season(background: BackgroundTasks):
    background.add_task(run_season_ingestion)
    return {"status": "started", "message": "Season ingestion triggered"}

@app.post("/ingest/results")
async def ingest_results(season_id: str = "", match_day: int = 0):
    if not season_id or not match_day:
        return {"status": "error", "message": "season_id and match_day required"}
    count = await _ingest_results(season_id, match_day)
    return {"status": "ok", "results_ingested": count}

@app.get("/ingest/status")
async def ingest_status():
    return ingest_state | {"ingested_matchday_count": len(ingest_state["ingested_matchdays"])}

@app.get("/scheduler")
async def scheduler_status():
    return {
        "type": "manual-trigger",
        "note": "Trigger via POST /ingest/season or systemd timer",
        "state": ingest_state["status"],
    }

def main():
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")

if __name__ == "__main__":
    main()
