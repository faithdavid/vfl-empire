"""Settlement Service (port 8004) — settles bets, updates bankroll, P&L tracking."""
import json, logging, os, sys
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query, BackgroundTasks
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.msport_client import get_results
from common.db_manager import get_db

logger = logging.getLogger("[SETTLEMENT]")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

DATA_DIR = os.path.expanduser("~/faith-workspace/vfl-complete-data")
SIGNALS_DIR = os.path.join(DATA_DIR, "signals")
LEDGER_PATH = os.path.join(SIGNALS_DIR, "bet_ledger.json")
BANKROLL_PATH = os.path.join(SIGNALS_DIR, "bankroll.json")

def _load_ledger() -> dict:
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH) as f:
            return json.load(f)
    return {"bets": [], "bankroll": {"initial": 100.0, "current": 100.0}}

def _save_ledger(data: dict):
    with open(LEDGER_PATH, "w") as f:
        json.dump(data, f, indent=2)

def _load_bankroll() -> dict:
    try:
        with get_db() as cur:
            cur.execute("SELECT current_balance, initial_balance FROM bankroll ORDER BY updated_at DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return {"current": float(row[0]), "initial": float(row[1])}
    except Exception as e:
        logger.error(f"Error loading bankroll from DB: {e}")
    return {"initial": 100.0, "current": 100.0}

def _save_bankroll(br: dict):
    try:
        with get_db() as cur:
            cur.execute(
                "UPDATE bankroll SET current_balance = %s, initial_balance = %s, updated_at = NOW()",
                (br["current"], br["initial"])
            )
    except Exception as e:
        logger.error(f"Error saving bankroll to DB: {e}")

def _determine_outcome(market: str, home_score: int, away_score: int) -> Optional[bool]:
    """Return True=won, False=lost, None=push/unknown."""
    total = home_score + away_score
    market_lower = market.strip().lower()
    
    # Over / Under markets
    if "over" in market_lower:
        threshold = 0.0
        for t in ["4.5", "3.5", "2.5", "1.5", "0.5"]:
            if t in market_lower:
                threshold = float(t)
                break
        return total > threshold
    elif "under" in market_lower:
        threshold = 10.0
        for t in ["4.5", "3.5", "2.5", "1.5", "0.5"]:
            if t in market_lower:
                threshold = float(t)
                break
        return total < threshold
        
    # Draw / X / D
    if "draw" in market_lower or market_lower in ("x", "d"):
        return home_score == away_score
        
    # DNB (Draw No Bet)
    if "dnb" in market_lower:
        if home_score == away_score:
            return None  # Push
        if "home" in market_lower or market_lower.endswith("1") or "h" in market_lower:
            return home_score > away_score
        if "away" in market_lower or market_lower.endswith("2") or "a" in market_lower:
            return away_score > home_score
            
    # Home Win / 1 / H
    if "home" in market_lower or market_lower in ("1", "h", "home win"):
        return home_score > away_score
        
    # Away Win / 2 / A
    if "away" in market_lower or market_lower in ("2", "a", "away win"):
        return home_score < away_score
        
    return None

def settle_predictions() -> dict:
    """Settle all unsettled predictions against actual results."""
    try:
        with get_db() as cur:
            # Fetch unsettled predictions from DB
            cur.execute(
                "SELECT id, season, match_day, home_team, away_team, prediction, odds FROM vfl_predictions WHERE settled = 0"
            )
            unsettled = cur.fetchall()
            
            if not unsettled:
                logger.info("No unsettled predictions found in DB")
                return {"settled": 0, "message": "no_unsettled_predictions"}

            logger.info(f"Found {len(unsettled)} unsettled predictions in DB")
            
            # Group by season/match_day
            batches = {}
            for pred in unsettled:
                season = pred[1] or "VFLM 5150"
                md = pred[2]
                key = (season, md)
                if key not in batches:
                    batches[key] = []
                batches[key].append(pred)

            settled_count = 0
            won_count = 0
            lost_count = 0
            push_count = 0
            total_profit = 0.0

            # Cache for API results to avoid duplicate calls in the same request
            api_results_cache = {}

            for (season, md), preds in batches.items():
                for pred in preds:
                    pred_id, _, _, home, away, prediction, odds = pred
                    odds_val = float(odds) if odds is not None else 1.0

                    # 1. Try local lookup first
                    local_score = None
                    try:
                        # Try vfl_results_v2
                        cur.execute(
                            """
                            SELECT r.home_goals, r.away_goals 
                            FROM vfl_results_v2 r
                            JOIN vfl_matchdays m ON r.matchday_id = m.id
                            JOIN vfl_seasons s ON m.season_id = s.id
                            WHERE (s.season_name = %s OR s.season_id = %s)
                              AND m.matchday_number = %s
                              AND LOWER(r.home_team) = LOWER(%s)
                              AND LOWER(r.away_team) = LOWER(%s)
                            """,
                            (season, season, md, home, away)
                        )
                        row = cur.fetchone()
                        if row is not None:
                            local_score = (row[0], row[1])
                        else:
                            # Try matches
                            cur.execute(
                                """
                                SELECT h, a 
                                FROM matches 
                                WHERE (season = %s OR season = (
                                    SELECT season_id FROM vfl_seasons WHERE season_name = %s LIMIT 1
                                ))
                                  AND day = %s
                                  AND LOWER(home) = LOWER(%s)
                                  AND LOWER(away) = LOWER(%s)
                                  AND h IS NOT NULL
                                """,
                                (season, season, md, home, away)
                            )
                            row = cur.fetchone()
                            if row is not None:
                                local_score = (row[0], row[1])
                    except Exception as db_err:
                        logger.error(f"Local lookup error: {db_err}")

                    h_score, a_score = None, None
                    if local_score is not None:
                        h_score, a_score = local_score
                    else:
                        # 2. Fallback to API
                        cache_key = (season, md)
                        if cache_key not in api_results_cache:
                            api_results_cache[cache_key] = get_results(season, md) or []
                        
                        results = api_results_cache[cache_key]
                        match_result = None
                        for r in results:
                            rh = (r.get("homeTeam") or "").strip().lower()
                            ra = (r.get("awayTeam") or "").strip().lower()
                            if rh == home.lower() and ra == away.lower():
                                match_result = r
                                break

                        if match_result:
                            ft = match_result.get("fullTime") or "0:0"
                            try:
                                h_score, a_score = map(int, ft.split(":"))
                            except Exception:
                                pass

                    if h_score is None or a_score is None:
                        continue

                    outcome = _determine_outcome(prediction, h_score, a_score)
                    
                    status = "pending"
                    profit = 0.0
                    is_settled = False

                    if outcome is False:
                        status = "lost"
                        profit = -1.0
                        is_settled = True
                    elif outcome is True:
                        status = "won"
                        profit = odds_val - 1.0
                        is_settled = True
                    elif outcome is None:
                        if "dnb" in prediction.lower() and h_score == a_score:
                            status = "push"
                            profit = 0.0
                            is_settled = True

                    if is_settled:
                        cur.execute(
                            """
                            UPDATE vfl_predictions 
                            SET settled = 1, result = %s, actual_h = %s, actual_a = %s, profit = %s 
                            WHERE id = %s
                            """,
                            (status, h_score, a_score, profit, pred_id)
                        )
                        
                        total_profit += profit
                        if status == "won":
                            won_count += 1
                        elif status == "lost":
                            lost_count += 1
                        elif status == "push":
                            push_count += 1
                        settled_count += 1
                        if settled_count % 1000 == 0:
                            cur.connection.commit()

            return {
                "settled": settled_count,
                "won": won_count,
                "lost": lost_count,
                "push": push_count,
                "total_profit": round(total_profit, 2)
            }
    except Exception as e:
        logger.error(f"Prediction settlement failed: {e}", exc_info=True)
        return {"error": str(e)}

def settle_bets() -> dict:
    """Settle all unsettled bets against actual results."""
    try:
        with get_db() as cur:
            # Fetch unsettled bets from DB
            cur.execute(
                "SELECT id, matchday, match, market, odds, stake, bet_type, season_name FROM vfl_bets WHERE settled = False AND success = True"
            )
            unsettled = cur.fetchall()
            
            if not unsettled:
                logger.info("No unsettled bets found in DB")
                return {"settled": 0, "message": "no_unsettled_bets"}

            logger.info(f"Found {len(unsettled)} unsettled bets in DB")
            
            # Group by season/matchday
            batches = {}
            for bet in unsettled:
                season = bet[7] or "VFLM 5150" 
                md = bet[1]
                key = (season, md)
                if key not in batches:
                    batches[key] = []
                batches[key].append(bet)

            settled_count = 0
            won_count = 0
            lost_count = 0
            total_profit = 0.0

            for (season, md), bets in batches.items():
                results = get_results(season, md)
                if not results:
                    logger.warning(f"Results not available yet for {season} MD {md}")
                    continue

                for bet in bets:
                    bet_id, md, match_str, market, odds, stake, bet_type, _ = bet
                    odds = float(odds)
                    stake = float(stake)

                    matches = [m.strip() for m in match_str.split(",")]
                    markets = [m.strip() for m in market.split(",")] if market else []
                    leg_outcomes = []
                    
                    for idx, m_name in enumerate(matches):
                        if " vs " not in m_name:
                            leg_outcomes.append(None)
                            continue
                        home, away = [x.strip() for x in m_name.split(" vs ")]
                        
                        leg_market = "Over 1.5 Goals"
                        if bet_type == "single":
                            leg_market = market
                        elif idx < len(markets):
                            leg_market = markets[idx]
                            if leg_market.lower() == "parlay":
                                leg_market = "Over 1.5 Goals"

                        match_result = None
                        for r in results:
                            rh = (r.get("homeTeam") or "").strip().lower()
                            ra = (r.get("awayTeam") or "").strip().lower()
                            if rh == home.lower() and ra == away.lower():
                                match_result = r
                                break
                        
                        if not match_result:
                            leg_outcomes.append(None)
                            continue

                        ft = match_result.get("fullTime") or "0:0"
                        try:
                            h_score, a_score = map(int, ft.split(":"))
                        except:
                            leg_outcomes.append(None)
                            continue
                            
                        outcome = _determine_outcome(leg_market, h_score, a_score)
                        leg_outcomes.append(outcome)

                    # Settle logic
                    status = "pending"
                    profit = 0.0
                    payout = 0.0
                    is_settled = False

                    if any(o is False for o in leg_outcomes):
                        status = "lost"
                        profit = -stake
                        payout = 0.0
                        is_settled = True
                    elif all(o is True for o in leg_outcomes):
                        status = "won"
                        payout = round(stake * odds, 2)
                        profit = round(payout - stake, 2)
                        is_settled = True
                    elif all(o is not None for o in leg_outcomes):
                        status = "push"
                        payout = stake
                        profit = 0.0
                        is_settled = True

                    if is_settled:
                        cur.execute(
                            """
                            UPDATE vfl_bets 
                            SET settled = True, status = %s, profit = %s, payout = %s 
                            WHERE id = %s
                            """,
                            (status, profit, payout, bet_id)
                        )
                        # Update bankroll if won or push
                        if payout > 0:
                            cur.execute("UPDATE bankroll SET current_balance = current_balance + %s, updated_at = NOW()", (payout,))
                        
                        total_profit += profit
                        if status == "won": won_count += 1
                        else: lost_count += 1
                        settled_count += 1

        return {
            "settled": settled_count,
            "won": won_count,
            "lost": lost_count,
            "total_profit": round(total_profit, 2)
        }
    except Exception as e:
        logger.error(f"Settlement failed: {e}")
        return {"error": str(e)}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Settlement Service starting on :8004")
    yield
    logger.info("Settlement Service shutting down")

app = FastAPI(title="VFL Settlement Service", version="1.0.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"service": "settlement", "status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/settle")
async def settle(background_tasks: BackgroundTasks):
    bets_res = settle_bets()
    background_tasks.add_task(settle_predictions)
    return {"bets": bets_res, "predictions": "started_in_background"}

@app.get("/ledger")
async def get_ledger(unsettled_only: bool = False):
    ledger = _load_ledger()
    if unsettled_only:
        ledger["bets"] = [b for b in ledger["bets"] if not b.get("settled")]
    return ledger

@app.get("/ledger/summary")
async def ledger_summary():
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*),
                    COUNT(*) FILTER (WHERE settled = True),
                    COUNT(*) FILTER (WHERE status = 'won'),
                    COUNT(*) FILTER (WHERE status = 'lost'),
                    COALESCE(SUM(stake) FILTER (WHERE settled = True), 0),
                    COALESCE(SUM(profit) FILTER (WHERE settled = True), 0)
                FROM vfl_bets
            """)
            stats = cur.fetchone()
            
            total, settled, won, lost, total_stake, total_profit = stats
            
            # Get bankroll
            cur.execute("SELECT initial_balance, current_balance FROM bankroll ORDER BY updated_at DESC LIMIT 1")
            br_row = cur.fetchone()
            br = {"initial": float(br_row[0]), "current": float(br_row[1])} if br_row else {"initial": 100.0, "current": 100.0}

        return {
            "total_bets": total,
            "settled_bets": settled,
            "won": won,
            "lost": lost,
            "win_rate": round(won / (won + lost) * 100, 1) if (won + lost) > 0 else 0,
            "total_stake": round(float(total_stake), 2),
            "total_profit": round(float(total_profit), 2),
            "roi": round(float(total_profit) / float(total_stake) * 100, 1) if float(total_stake) > 0 else 0,
            "bankroll": br,
        }
    except Exception as e:
        logger.error(f"Summary failed: {e}")
        return {"error": str(e)}

@app.get("/bankroll")
async def get_bankroll():
    return _load_bankroll()

@app.post("/bankroll/reset")
async def reset_bankroll(amount: float = 100.0):
    br = {"initial": amount, "current": amount}
    _save_bankroll(br)
    return br

def main():
    uvicorn.run(app, host="0.0.0.0", port=8004, log_level="info")

if __name__ == "__main__":
    main()
