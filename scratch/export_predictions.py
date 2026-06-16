import os
import sys
import pandas as pd
import psycopg2

PG_CONFIG = {
    "dbname": "vfl_empire",
    "user": "vfl_user",
    "password": "vfl_pass",
    "host": "localhost",
    "port": "5432"
}

def export_predictions():
    print("Exporting settled predictions from Postgres to vfl_training_data.csv...")
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        query = """
            SELECT 
                UPPER(home_team) as home_team,
                UPPER(away_team) as away_team,
                prediction,
                confidence,
                odds,
                engine,
                tier_home,
                tier_away,
                cv_1x2,
                match_day,
                season,
                actual_h,
                actual_a,
                CASE WHEN result = 'won' THEN 1 ELSE 0 END as label
            FROM vfl_predictions
            WHERE settled = 1 AND result IN ('won', 'lost');
        """
        df = pd.read_sql(query, conn)
        conn.close()
        
        out_path = '/home/ubuntu/faith-workspace/vfl-empire/data/vfl_training_data.csv'
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"Successfully exported {len(df):,} rows to {out_path}")
    except Exception as e:
        print(f"Error exporting predictions: {e}")
        sys.exit(1)

if __name__ == "__main__":
    export_predictions()
