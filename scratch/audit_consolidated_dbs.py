import sqlite3
import sys
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/services")
from common.db_manager import get_db

paths = {
    "docs_history": "/home/ubuntu/Documents/Projects/vfl-data/vfl-empire/data/databases/history.db",
    "docs_sovereign": "/home/ubuntu/Documents/Projects/vfl-data/vfl-empire/data/databases/sovereign.db",
    "fw_history": "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db",
    "fw_sovereign": "/home/ubuntu/faith-workspace/vfl-complete-data/databases/sovereign.db",
}

def history_stats(path, label):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM matches WHERE outcome IS NOT NULL AND h IS NOT NULL")
    with_results = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM matches")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT season) FROM matches")
    seasons = cur.fetchone()[0]
    cur.execute("""
        SELECT season, COUNT(*) n, COUNT(DISTINCT day) days,
               SUM(CASE WHEN oh IS NOT NULL OR o_o25 IS NOT NULL OR o_gg IS NOT NULL THEN 1 ELSE 0 END) odds_n
        FROM matches GROUP BY season
    """)
    rows = cur.fetchall()
    complete = [r for r in rows if r[2] >= 30 and r[1] >= 240]
    odds_all = sum(r[3] for r in rows)
    odds_complete = sum(r[3] for r in complete)
    cur.execute("SELECT MIN(season), MAX(season) FROM matches")
    rng = cur.fetchone()
    print(f"{label}:")
    print(f"  total rows: {total}, with outcome+h: {with_results}")
    print(f"  seasons: {seasons}, complete 30-day: {len(complete)}")
    print(f"  season range: {rng}")
    print(f"  matches with shallow odds: {odds_all}, in complete seasons: {odds_complete}")
    conn.close()
    return h_seasons if False else {r[0] for r in rows}

for k, p in [("Documents history", paths["docs_history"]), ("faith-workspace history", paths["fw_history"])]:
    history_stats(p, k)

conn = sqlite3.connect(paths["fw_history"])
cur = conn.cursor()
cur.execute("SELECT DISTINCT season FROM matches")
h_seasons = {r[0] for r in cur.fetchall()}
conn.close()

with get_db() as pg:
    pg.execute("SELECT season_id FROM vfl_seasons")
    pg_ids = {r["season_id"] for r in pg.fetchall()}
    print("\nOverlap history.season vs PG vfl_seasons.season_id:")
    print("  overlap:", len(h_seasons & pg_ids), "history-only:", len(h_seasons - pg_ids))
    print("  sample history-only:", sorted(h_seasons - pg_ids)[:6])