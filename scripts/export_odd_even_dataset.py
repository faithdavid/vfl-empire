#!/usr/bin/env python3
"""Export canonical results + Odd/Even labels for offline DS."""
import sys
from pathlib import Path
EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

OUT = EMPIRE / "models" / "odd_even"
OUT.mkdir(parents=True, exist_ok=True)

def main():
    with get_db() as cur:
        cur.execute("SELECT * FROM v_results_odd_even_ready ORDER BY vflm_num, matchday_number, event_id")
        rows = [dict(r) for r in cur.fetchall()]
    import pandas as pd
    df = pd.DataFrame(rows)
    csv_path = OUT / "v_results_odd_even_ready.csv"
    df.to_csv(csv_path, index=False)
    print(f"rows={len(df)} with_odds={df['odd_odds'].notna().sum()} -> {csv_path}")

if __name__ == "__main__":
    main()