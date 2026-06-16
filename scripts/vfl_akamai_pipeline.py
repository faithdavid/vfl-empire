#!/usr/bin/env python3
"""
vfl_akamai_pipeline.py — VFL Akamai CDN Data Pipeline.

A high-performance pipeline and CLI tool to query unencrypted VFL data
from Akamai CDN and MSport REST endpoints, synchronize matchdays, 
format outputs for the Predictor Engine, and track live scores in real-time.
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

# ─── Logging Setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("VFLAkamaiPipeline")

# ─── Constants & Endpoints ───────────────────────────────────────────────────
AKAMAI_DOMAINS = {
    "direct_live": "https://vfdirectdatalive-vs001.akamaized.net",
    "gismo": "https://vglslive-vs001.akamaized.net",
    "vfel2": "https://vflive-vs001.akamaized.net",
}

# Team Name Aliases matching convention across the codebase
TEAM_ALIASES = {
    "MANCHESTER BLUE": "Manchester Blue",
    "MANCHESTER RED": "Manchester Red",
    "LIVERPOOL": "Liverpool",
    "CHELSEA": "Chelsea",
    "LONDON GUNS": "London Guns",
    "TOTTENHAM": "Tottenham",
    "ASTON VILLA": "Aston Villa",
    "WEST HAM": "West Ham",
    "EVERTON": "Everton",
    "WOLVERHAMPTON": "Wolverhampton",
    "BRIGHTON": "Brighton",
    "NEWCASTLE": "Newcastle",
    "LEEDS": "Leeds",
    "CRYSTAL PALACE": "Crystal Palace",
    "FULHAM": "Fulham",
    "BOURNEMOUTH": "Bournemouth",
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Origin": "https://www.msport.com",
    "Referer": "https://www.msport.com/ng/virtual/soccer",
    "operId": "2",
    "operid": "2",
    "clientid": "wap",
    "platform": "WAP",
    "apilevel": "2",
}

# ─── Database Discovery ──────────────────────────────────────────────────────
def resolve_db_path(db_name: str) -> str:
    """Resolve database path from typical locations."""
    candidates = [
        os.path.expanduser(f"~/{db_name}"),
        os.path.expanduser(f"~/faith-workspace/vfl-complete-data/databases/{db_name}"),
        os.path.expanduser(f"~/faith-workspace/vfl-empire/{db_name}"),
        os.path.expanduser(f"~/faith-workspace/vfl-empire/databases/{db_name}"),
        os.path.expanduser(f"~/faith-workspace/vfl-empire/dbs/{db_name}"),
        f"/home/ubuntu/faith-workspace/vfl-complete-data/databases/{db_name}",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    # Fallback to current directory
    return db_name


# ─── Akamai Pipeline Client ──────────────────────────────────────────────────
class AkamaiVFLPipeline:
    def __init__(self, rate_limit_delay: float = 1.0):
        self.rate_limit_delay = rate_limit_delay
        self.cache: Dict[str, Tuple[float, Any]] = {}  # URL -> (timestamp, data)
        self.cache_ttl = 30.0  # 30 seconds cache TTL for transient feeds

    def normalize_team_name(self, name: str) -> str:
        """Standardize team names based on aliases."""
        if not name:
            return ""
        return TEAM_ALIASES.get(name.strip().upper(), name.strip().title())

    def _fetch(self, url: str, use_cache: bool = True) -> Optional[Any]:
        """Perform HTTP GET request with retries and caching."""
        now = time.time()
        if use_cache and url in self.cache:
            ts, cached_data = self.cache[url]
            if now - ts < self.cache_ttl:
                logger.debug(f"Cache hit: {url}")
                return cached_data

        logger.debug(f"Fetching: {url}")
        
        # Build headers - attach dynamic deviceid on MSport REST API hits
        headers = dict(DEFAULT_HEADERS)
        if "msport.com/api/" in url:
            headers["deviceid"] = str(uuid.uuid4())
            
        req = urllib.request.Request(url, headers=headers)
        
        last_err = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    body = response.read().decode("utf-8")
                    data = json.loads(body)
                    if use_cache:
                        self.cache[url] = (now, data)
                    time.sleep(self.rate_limit_delay)
                    return data
            except urllib.error.HTTPError as e:
                last_err = e
                logger.warning(f"HTTP Error {e.code} for {url} (Attempt {attempt}/3)")
                if e.code in [429, 502, 503, 504]:
                    time.sleep(2.0 * attempt)
                    continue
                break
            except Exception as e:
                last_err = e
                logger.warning(f"Error fetching {url}: {e} (Attempt {attempt}/3)")
                time.sleep(1.0 * attempt)
                continue

        logger.error(f"Failed to fetch {url} after 3 attempts: {last_err}")
        return None

    # ── Akamai Endpoints ──
    def get_live_events(self, season_id: str, matchday: int) -> Optional[Dict[str, Any]]:
        """Get live match events (start, goals, cards, etc.)."""
        clean_sid = str(season_id).replace("vf:season:", "")
        url = f"{AKAMAI_DOMAINS['direct_live']}//46215/msportnigeriavflm/en/Europe:Berlin/vf_liveevents/{clean_sid}/league/{matchday}"
        return self._fetch(url)

    def get_live_scores(self, season_id: str, matchday: int) -> Optional[Dict[str, Any]]:
        """Get live scores (FT/HT scores per match)."""
        clean_sid = str(season_id).replace("vf:season:", "")
        url = f"{AKAMAI_DOMAINS['direct_live']}//46215/msportnigeriavflm/en/Europe:Berlin/vf_livescore/{clean_sid}/league/{matchday}"
        return self._fetch(url)

    def get_full_feed(self, season_id: str, matchday: int) -> Optional[Dict[str, Any]]:
        """Get complete GISMO feed for upcoming / active matches."""
        clean_sid = str(season_id).replace("vf:season:", "")
        url = f"{AKAMAI_DOMAINS['gismo']}/vfl/feeds/?/msportnigeriavflm/en/Europe:Berlin/gismo/vfl_event_fullfeed/{clean_sid}/{matchday}"
        return self._fetch(url)

    def get_tournament_table(self, season_id: str, matchday: int) -> Optional[Dict[str, Any]]:
        """Get tournament live standings by season and round."""
        clean_sid = str(season_id).replace("vf:season:", "")
        url = f"{AKAMAI_DOMAINS['gismo']}/vfl/feeds/?/msportnigeriavflm/en/Europe:Berlin/gismo/vfl_tournament_livetablebyseasonandround/{clean_sid}/{matchday}"
        return self._fetch(url)

    def get_vfel2_events(self, season_id: str, matchday: int) -> Optional[Dict[str, Any]]:
        """Get VFEL2 event IDs matching the current matchday."""
        clean_sid = str(season_id).replace("vf:season:", "")
        url = f"{AKAMAI_DOMAINS['vfel2']}/vfel2/mobile/eventIds.json?clientid=4731&lang=en&seasonid={clean_sid}&stagetype=1&matchset={matchday}"
        return self._fetch(url)

    def get_vfel2_config(self) -> Optional[Dict[str, Any]]:
        """Get VFEL2 config, team translations, and tournament details."""
        url = f"{AKAMAI_DOMAINS['vfel2']}/vfel2/mobile/settings?clientid=4731&lang=en"
        return self._fetch(url)

    def get_vfel2_phases(self) -> Optional[Dict[str, Any]]:
        """Get VFEL2 phase descriptions (pre-match, match, etc.)."""
        url = f"{AKAMAI_DOMAINS['vfel2']}/vfel2/mobile/phases?clientid=4731&lang=en"
        return self._fetch(url)

    def get_vfel2_teams(self) -> Optional[Dict[str, Any]]:
        """Get VFEL2 team jersey assignments and video setups."""
        url = f"{AKAMAI_DOMAINS['vfel2']}/vfel2/mobile/teamJerseyAssignments.json?clientid=4731"
        return self._fetch(url)

    def get_vfel2_timings(self) -> Optional[Dict[str, Any]]:
        """Get VFEL2 current timeline clocks and phase offsets."""
        url = f"{AKAMAI_DOMAINS['vfel2']}/vfel2/mobile/timings?clientid=4731&lang=en"
        return self._fetch(url)

    # ── MSport unencrypted REST endpoints ──
    def get_msport_matchday_info(self) -> Optional[Dict[str, Any]]:
        """Get active MSport matchday metadata."""
        url = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/current/match/day/info"
        res = self._fetch(url, use_cache=False)
        return res.get("data") if res else None

    def get_msport_event_list(self) -> Optional[List[Dict[str, Any]]]:
        """Get upcoming fixtures along with all markets and odds."""
        url = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/event/list?sportId=vf:sport:1"
        res = self._fetch(url, use_cache=False)
        if res and res.get("bizCode") == 10000:
            return res.get("data", {}).get("matchDays", [])
        return None

    def get_msport_balance(self) -> Optional[float]:
        """Get virtual pocket financial account balance."""
        url = "https://www.msport.com/api/ng/pocket/financialAccounts/balance"
        res = self._fetch(url, use_cache=False)
        if res and res.get("bizCode") == 10000:
            return float(res.get("data", {}).get("balance", 0))
        return None

    # ── Data Synchronizer ──
    def sync_matchday(self) -> Optional[Dict[str, Any]]:
        """
        Builds a comprehensive real-time snapshot of the current active matchday
        fixtures, current live scores, and all raw odds data.
        """
        logger.info("Synchronizing active VFL Matchday snapshot...")
        info = self.get_msport_matchday_info()
        if not info:
            logger.error("Failed to sync: current matchday info unavailable.")
            return None

        season_id = info.get("seasonId")
        matchday = info.get("matchDay")
        season_name = info.get("seasonName", "")
        
        if not season_id or not matchday:
            logger.error("Failed to sync: invalid season_id or matchday.")
            return None

        logger.info(f"Active Season: {season_name} ({season_id}) | Matchday: {matchday}")

        # Fetch Akamai sources for events, live scores, config, and timings
        timings = self.get_vfel2_timings()
        config = self.get_vfel2_config()
        scores_feed = self.get_live_scores(season_id, matchday) or {}
        events_feed = self.get_live_events(season_id, matchday) or {}
        event_list = self.get_msport_event_list() or []

        # Find our target matchday events from the event list
        md_events = []
        for md_entry in event_list:
            if md_entry.get("matchDay") == matchday:
                md_events = md_entry.get("events", [])
                break
        
        if not md_events and event_list:
            # Fallback to the first available matchday in the list
            md_events = event_list[0].get("events", [])
            logger.info(f"Using fallback matchday {event_list[0].get('matchDay')} from event list.")

        # Build Normalized Matches Snapshots
        parsed_matches = []
        raw_scores = scores_feed.get("data", {}).get("matches", {})

        for event in md_events:
            event_id = event.get("eventId")
            home = self.normalize_team_name(event.get("homeTeam", ""))
            away = self.normalize_team_name(event.get("awayTeam", ""))
            
            # Retrieve live score if active/finished
            score_data = raw_scores.get(str(event_id), {}) if event_id else {}
            ht_score = score_data.get("periods", {}).get("ht", {})
            ft_score = score_data.get("periods", {}).get("ft", {})

            # Extract Odds Markets
            odds = self._extract_markets_odds(event)

            parsed_matches.append({
                "match_id": event_id,
                "home_team": home,
                "away_team": away,
                "status": score_data.get("status", "UPCOMING"),
                "period": score_data.get("period", "NOT_STARTED"),
                "scores": {
                    "ht": f"{ht_score.get('home', 0)}:{ht_score.get('away', 0)}" if ht_score else "0:0",
                    "ft": f"{ft_score.get('home', 0)}:{ft_score.get('away', 0)}" if ft_score else "0:0"
                },
                "odds": odds
            })

        snapshot = {
            "season_id": season_id,
            "season_name": season_name,
            "matchday": matchday,
            "server_time": timings.get("server_datetime") if timings else int(time.time()),
            "matches": parsed_matches,
        }
        return snapshot

    def _extract_markets_odds(self, event: Dict[str, Any]) -> Dict[str, float]:
        """Extract Over 1.5, Under 3.5, GG, and Double Chance odds from event dict."""
        odds = {
            "Over 1.5": 1.0,
            "Under 3.5": 1.0,
            "GG": 1.0,
            "Double Chance Home/Draw (1X)": 1.0,
            "Double Chance Draw/Away (X2)": 1.0,
        }
        
        for market in event.get("markets", []):
            m_id = market.get("id")
            spec = market.get("specifiers", "")
            outcomes = market.get("outcomes", [])
            
            # Market ID 18: Over/Under
            if m_id == 18:
                if spec == "total=1.5":
                    for out in outcomes:
                        if "Over" in out.get("description", ""):
                            odds["Over 1.5"] = float(out.get("odds", 1.0))
                elif spec == "total=3.5":
                    for out in outcomes:
                        if "Under" in out.get("description", ""):
                            odds["Under 3.5"] = float(out.get("odds", 1.0))
            
            # Market ID 29: GG/NG (BTTS)
            elif m_id == 29:
                for out in outcomes:
                    if out.get("description") == "Yes":
                        odds["GG"] = float(out.get("odds", 1.0))

            # Market ID 10: Double Chance
            elif m_id == 10:
                for out in outcomes:
                    desc = out.get("description")
                    if desc == "1 X":
                        odds["Double Chance Home/Draw (1X)"] = float(out.get("odds", 1.0))
                    elif desc == "X 2":
                        odds["Double Chance Draw/Away (X2)"] = float(out.get("odds", 1.0))

        return odds

    # ── Predictor Exporter ──
    def export_predictor_format(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Formats normalized snapshotted odds per match to are ready to be ingested
        directly by `fixture_intelligence.py`.
        """
        records = []
        for m in snapshot.get("matches", []):
            odds = m.get("odds", {})
            
            # Map into the structure that fixture_intelligence.py or DB expectations
            records.append({
                "match_id": m.get("match_id"),
                "season_id": snapshot.get("season_id"),
                "match_day": snapshot.get("matchday"),
                "home_team": m.get("home_team"),
                "away_team": m.get("away_team"),
                "market_odds": {
                    "Over 1.5": odds.get("Over 1.5"),
                    "Under 3.5": odds.get("Under 3.5"),
                    "GG": odds.get("GG"),
                    "Double Chance 1X": odds.get("Double Chance Home/Draw (1X)"),
                    "Double Chance X2": odds.get("Double Chance Draw/Away (X2)")
                }
            })
        return records

    def write_odds_to_db(self, export_records: List[Dict[str, Any]]):
        """Insert deep market odds into vfl_odds.db."""
        db_path = resolve_db_path("vfl_odds.db")
        logger.info(f"Writing parsed deep markets to {db_path}...")
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            now_str = datetime.now(timezone.utc).isoformat()
            
            for rec in export_records:
                event_id = str(rec["match_id"])
                
                # 1. Insert Event Detail
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO event_details 
                    (event_id, season_id, match_day, home_team, away_team, detail_json, captured_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        rec["season_id"],
                        rec["match_day"],
                        rec["home_team"],
                        rec["away_team"],
                        json.dumps(rec),
                        now_str
                    )
                )

                # 2. Insert Deep Markets Odds
                markets_to_write = [
                    ("Over/Under", "total=1.5", "Over 1.5", rec["market_odds"]["Over 1.5"]),
                    ("Over/Under", "total=3.5", "Under 3.5", rec["market_odds"]["Under 3.5"]),
                    ("GG/NG", "", "Yes", rec["market_odds"]["GG"]),
                    ("Double Chance", "", "1 X", rec["market_odds"]["Double Chance 1X"]),
                    ("Double Chance", "", "X 2", rec["market_odds"]["Double Chance X2"]),
                ]

                for m_name, spec, sel, val in markets_to_write:
                    cursor.execute(
                        """
                        INSERT INTO deep_markets (event_id, market_name, specifiers, selection_name, odds, captured_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (event_id, m_name, spec, sel, val, now_str)
                    )

            conn.commit()
            conn.close()
            logger.info("Successfully updated deep markets database.")
        except Exception as e:
            logger.error(f"Error writing odds to SQLite: {e}")


# ─── Live Score Tracker Loop ──────────────────────────────────────────────────
def run_live_tracker(pipeline: AkamaiVFLPipeline, season_id: str, matchday: int):
    """Poll vf_livescore periodically on a timer to track live goals/match events."""
    logger.info(f"Starting VFL Live Score Tracker for Season {season_id} Matchday {matchday}...")
    tracked_states = {}  # event_id -> score_string

    try:
        while True:
            scores_feed = pipeline.get_live_scores(season_id, matchday)
            if not scores_feed or "data" not in scores_feed:
                logger.warning("Could not fetch live scores feed.")
                time.sleep(5)
                continue

            matches = scores_feed["data"].get("matches", {})
            active_or_finished = False

            for m_id, m_data in matches.items():
                home = pipeline.normalize_team_name(m_data.get("home_team_name", f"Team {m_id}")) # Fallback if missing
                away = pipeline.normalize_team_name(m_data.get("away_team_name", f"Team {m_id}"))
                status = m_data.get("status")
                period = m_data.get("period")
                
                # Fetch FT goals
                ft = m_data.get("periods", {}).get("ft", {})
                home_g = ft.get("home", 0)
                away_g = ft.get("away", 0)
                current_score = f"{home_g}:{away_g}"

                old_score = tracked_states.get(m_id)
                if old_score is None:
                    # Match start tracking
                    logger.info(f"⚽ Match {m_id} Started: {home} vs {away}")
                    tracked_states[m_id] = current_score
                elif old_score != current_score:
                    # Goal event tracking
                    logger.info(f"🔥 GOAL! Match {m_id}: {home} {home_g} - {away_g} {away} (Score Changed from {old_score})")
                    tracked_states[m_id] = current_score

                if status == 20 or period == "ft":
                    logger.info(f"🏁 Match {m_id} Finished (FT): {home} {home_g} - {away_g} {away}")
                else:
                    active_or_finished = True

            if not active_or_finished and tracked_states:
                logger.info("All matches for this matchday have finished. Stopping live tracker.")
                break

            time.sleep(5)  # Poll every 5s
    except KeyboardInterrupt:
        logger.info("Live Score Tracker stopped by user.")


# ─── Latency & Consistency Comparison ───────────────────────────────────────
def compare_latency_and_consistency(pipeline: AkamaiVFLPipeline):
    """Measure request round-trip times (RTT) for Akamai vs MSport REST API."""
    logger.info("Starting speed and odds consistency comparison...")
    
    # Measure MSport REST RTT
    t0 = time.time()
    md_info = pipeline.get_msport_matchday_info()
    rtt_msport = (time.time() - t0) * 1000

    if not md_info:
        logger.error("Could not run benchmark: MSport REST endpoint is offline.")
        return

    season_id = md_info["seasonId"]
    matchday = md_info["matchDay"]

    # Measure Akamai CDN RTT
    t0 = time.time()
    livescores = pipeline.get_live_scores(season_id, matchday)
    rtt_akamai = (time.time() - t0) * 1000

    logger.info("=" * 60)
    logger.info("🏎️  LATENCY BENCHMARK RESULTS")
    logger.info("=" * 60)
    logger.info(f"MSport REST API RTT: {rtt_msport:.2f} ms")
    logger.info(f"Akamai CDN RTT:      {rtt_akamai:.2f} ms")
    speedup = (rtt_msport - rtt_akamai) / rtt_msport * 100
    logger.info(f"Speedup Percentage:   {speedup:.2f}% faster using Akamai CDN")
    logger.info("=" * 60)


# ─── CLI Entry Point ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="VFL Akamai CDN Data Pipeline CLI")
    parser.add_argument("--fetch-all", action="store_true", help="Probe and dump all Akamai CDN endpoints")
    parser.add_argument("--sync", action="store_true", help="Build and display a complete matchday snapshot")
    parser.add_argument("--compare-odds", action="store_true", help="Measure latencies and compare consistency")
    parser.add_argument("--track-scores", action="store_true", help="Track active goals and score outcomes")
    parser.add_argument("--write-db", action="store_true", help="Save synchronized odds back into vfl_odds.db")
    args = parser.parse_args()

    pipeline = AkamaiVFLPipeline(rate_limit_delay=0.1)

    if args.fetch_all:
        logger.info("Probing raw Akamai and unencrypted endpoints...")
        info = pipeline.get_msport_matchday_info()
        if info:
            season_id = info["seasonId"]
            matchday = info["matchDay"]
            logger.info(f"Fetched Season: {season_id}, MD: {matchday}")
            pipeline.get_live_events(season_id, matchday)
            pipeline.get_live_scores(season_id, matchday)
            pipeline.get_full_feed(season_id, matchday)
            pipeline.get_vfel2_events(season_id, matchday)
        pipeline.get_vfel2_config()
        pipeline.get_vfel2_phases()
        pipeline.get_vfel2_teams()
        pipeline.get_vfel2_timings()
        logger.info("✅ Finished probing all raw endpoints.")

    elif args.sync:
        snapshot = pipeline.sync_matchday()
        if snapshot:
            print(json.dumps(snapshot, indent=2))
            if args.write_db:
                recs = pipeline.export_predictor_format(snapshot)
                pipeline.write_odds_to_db(recs)

    elif args.compare_odds:
        compare_latency_and_consistency(pipeline)

    elif args.track_scores:
        info = pipeline.get_msport_matchday_info()
        if info:
            run_live_tracker(pipeline, info["seasonId"], info["matchDay"])

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
