import sys
import os
import json
import logging
from typing import List, Dict, Tuple
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

from common.db_manager import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SeasonFingerprinter")

class SeasonFingerprinter:
    def __init__(self):
        self.cached_seasons = {}

    def get_season_snapshot(self, season_id: int, matchday: int) -> Dict[str, Tuple[int, int]]:
        """Returns {team_name: (rank, points)}"""
        try:
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT team_name, rank, points 
                    FROM vfl_league_snapshots 
                    WHERE matchday_id = (
                        SELECT id FROM vfl_matchdays 
                        WHERE season_id = %s AND matchday_number = %s
                    )
                    """,
                    (season_id, matchday)
                )
                rows = cur.fetchall()
                return {r['team_name']: (r['rank'], r['points']) for r in rows}
        except Exception as e:
            logger.error(f"Error fetching snapshot: {e}")
            return {}

    def find_mirror_seasons(self, current_season_name: str, matchday: int, top_n: int = 5) -> List[Dict]:
        """Finds historical seasons that match the current one at the given matchday."""
        try:
            with get_db() as cur:
                # Get current season internal ID
                cur.execute("SELECT id FROM vfl_seasons WHERE season_name = %s", (current_season_name,))
                row = cur.fetchone()
                if not row:
                    return []
                curr_id = row['id']

                # Get current snapshot
                curr_snap = self.get_season_snapshot(curr_id, matchday)
                if not curr_snap:
                    logger.warning(f"No snapshot found for {current_season_name} MD {matchday}")
                    return []

                # Get all historical snapshots at the same matchday
                cur.execute(
                    """
                    SELECT s.id, s.season_name, ls.team_name, ls.rank, ls.points
                    FROM vfl_league_snapshots ls
                    JOIN vfl_matchdays m ON ls.matchday_id = m.id
                    JOIN vfl_seasons s ON m.season_id = s.id
                    WHERE m.matchday_number = %s AND s.id != %s
                    """,
                    (matchday, curr_id)
                )
                all_rows = cur.fetchall()

                # Group by season
                historical_snaps = {}
                for r in all_rows:
                    sid = r['id']
                    if sid not in historical_snaps:
                        historical_snaps[sid] = {"name": r['season_name'], "data": {}}
                    historical_snaps[sid]["data"][r['team_name']] = (r['rank'], r['points'])

                # Calculate similarity score
                results = []
                for sid, s_info in historical_snaps.items():
                    h_snap = s_info["data"]
                    if len(h_snap) < 16: continue # Skip partial snapshots

                    score = 0
                    matches = 0
                    pts_diff = 0
                    
                    for team, (c_rank, c_pts) in curr_snap.items():
                        if team in h_snap:
                            h_rank, h_pts = h_snap[team]
                            if c_rank == h_rank:
                                matches += 1
                            score += abs(c_rank - h_rank)
                            pts_diff += abs(c_pts - h_pts)

                    results.append({
                        "id": sid,
                        "season_name": s_info["name"],
                        "rank_matches": matches,
                        "rank_distance": score,
                        "pts_distance": pts_diff,
                        "similarity": matches * 10 - score - pts_diff
                    })

                # Sort by similarity (highest matches, lowest distance)
                results.sort(key=lambda x: (x['rank_matches'], -x['rank_distance'], -x['pts_distance']), reverse=True)
                return results[:top_n]

        except Exception as e:
            logger.error(f"Error finding mirror seasons: {e}")
            return []

    def get_mirrored_predictions(self, mirror_season_id: int, next_matchday: int) -> List[Dict]:
        """Gets results of a historical season to use as guidance."""
        try:
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT r.home_team, r.away_team, r.home_goals, r.away_goals, 
                           (r.home_goals + r.away_goals) as total
                    FROM vfl_results_v2 r
                    JOIN vfl_matchdays m ON r.matchday_id = m.id
                    WHERE m.season_id = %s AND m.matchday_number = %s
                    """,
                    (mirror_season_id, next_matchday)
                )
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error fetching mirrored results: {e}")
            return []

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 season_fingerprinter.py <season_name> <matchday>")
        sys.exit(1)

    name = sys.argv[1]
    md = int(sys.argv[2])
    
    fp = SeasonFingerprinter()
    mirrors = fp.find_mirror_seasons(name, md)
    
    print(f"\n--- Mirror Candidates for {name} MD {md} ---")
    for m in mirrors:
        print(f"Season: {m['season_name']} | Rank Matches: {m['rank_matches']} | Rank Dist: {m['rank_distance']} | Pts Dist: {m['pts_distance']}")
        
        # Guidance for next matchday
        next_md = md + 1
        guidance = fp.get_mirrored_predictions(m['id'], next_md)
        if guidance:
            o25_count = sum(1 for g in guidance if g['total'] > 2.5)
            avg_goals = sum(g['total'] for g in guidance) / len(guidance)
            print(f"  -> Next MD ({next_md}) Guidance: O2.5 Rate: {o25_count}/8 | Avg Goals: {avg_goals:.2f}")
