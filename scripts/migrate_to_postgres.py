#!/usr/bin/env python3
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import os
import sys

# Add common to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services"))
from common.db_manager import PG_CONFIG

SQLITE_DIR = "/home/ubuntu/faith-workspace/vfl-complete-data/databases"

DB_MAP = {
    "vfl_results.db": "results",
    "vfl_odds.db": "odds_history",
    "history.db": "matches",
    "empire_events.db": ["messages", "vfl_predictions", "vfl_settlements", "cron_events", "agent_actions", "lord_decrees", "system_health"]
}

def migrate_table(sqlite_conn, pg_conn, table_name):
    print(f"Migrating table: {table_name}...")
    
    # Get SQLite data
    cursor = sqlite_conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {table_name}")
    except sqlite3.OperationalError:
        print(f"  Table {table_name} not found in SQLite. Skipping.")
        return
        
    rows = cursor.fetchall()
    if not rows:
        print(f"  Table {table_name} is empty. Skipping.")
        return
        
    # Get column names
    cols = [description[0] for description in cursor.description]
    
    # Data Cleaning: Handle mixed types or bad formats
    clean_rows = []
    for row in rows:
        row_list = list(row)
        if table_name == "vfl_predictions":
            # Clean 'confidence' column (index 9 usually, but let's find it)
            if "confidence" in cols:
                idx = cols.index("confidence")
                val = row_list[idx]
                if isinstance(val, str) and "%" in val:
                    try:
                        row_list[idx] = int(val.replace("%", ""))
                    except ValueError:
                        row_list[idx] = None
        clean_rows.append(tuple(row_list))
    
    pg_cur = pg_conn.cursor()
    
    # Construct INSERT statement
    col_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    insert_query = f"INSERT INTO {table_name} ({col_str}) VALUES %s ON CONFLICT DO NOTHING"
    
    execute_values(pg_cur, insert_query, clean_rows)
    pg_conn.commit()
    print(f"  Successfully migrated {len(rows)} rows to {table_name}.")

def create_postgres_schema(pg_conn):
    print("Creating Postgres schema...")
    cur = pg_conn.cursor()
    
    # results
    cur.execute("""
        CREATE TABLE IF NOT EXISTS results (
            event_id TEXT PRIMARY KEY,
            season_id TEXT,
            season_name TEXT,
            match_day INTEGER,
            home_team TEXT,
            away_team TEXT,
            home_goals INTEGER,
            away_goals INTEGER,
            total_goals INTEGER,
            under_35 INTEGER,
            status BIGINT,
            captured_at TEXT
        );
    """)
    
    # odds_history
    cur.execute("""
        CREATE TABLE IF NOT EXISTS odds_history (
            id BIGSERIAL PRIMARY KEY,
            event_id TEXT,
            season_id TEXT,
            season_name TEXT,
            match_day INTEGER,
            home_team TEXT,
            away_team TEXT,
            u35_odds REAL,
            ng_odds REAL,
            home_rank INTEGER,
            away_rank INTEGER,
            home_stratum TEXT,
            away_stratum TEXT,
            predicted_prob REAL,
            captured_at TEXT,
            UNIQUE(event_id, captured_at)
        );
    """)
    
    # matches (history)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id BIGINT PRIMARY KEY,
            season TEXT,
            day INTEGER,
            home TEXT, away TEXT,
            oh REAL, od REAL, oa REAL,
            o_o25 REAL, o_u25 REAL, o_gg REAL, o_ng REAL,
            outcome TEXT, h INTEGER, a INTEGER,
            total INTEGER, gg INTEGER, o25 INTEGER,
            half_time TEXT, first_goal TEXT,
            season_start_time TEXT,
            har_timestamp TEXT,
            source_file TEXT,
            UNIQUE(season, day, home, away)
        );
    """)
    
    # vfl_predictions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vfl_predictions (
            id BIGSERIAL PRIMARY KEY,
            timestamp REAL,
            iso_time TEXT,
            season TEXT NOT NULL,
            match_day INTEGER NOT NULL,
            match_num INTEGER,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            prediction TEXT NOT NULL,
            confidence INTEGER,
            odds REAL,
            engine TEXT NOT NULL,
            tier_home TEXT,
            tier_away TEXT,
            cv_1x2 REAL,
            settled INTEGER DEFAULT 0,
            result TEXT,
            actual_h INTEGER,
            actual_a INTEGER,
            profit REAL,
            metadata TEXT
        );
    """)
    
    # vfl_settlements
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vfl_settlements (
            id BIGSERIAL PRIMARY KEY,
            timestamp REAL,
            iso_time TEXT,
            season TEXT NOT NULL,
            match_day INTEGER NOT NULL,
            match_num INTEGER,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            actual_h INTEGER,
            actual_a INTEGER,
            total_goals INTEGER,
            outcome TEXT,
            first_goal TEXT,
            ht_h INTEGER,
            ht_a INTEGER,
            source TEXT DEFAULT 'api'
        );
    """)

    # messages
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            timestamp REAL,
            iso_time TEXT,
            platform TEXT,
            channel_id TEXT,
            thread_id TEXT,
            sender TEXT,
            sender_id TEXT,
            content TEXT,
            msg_type TEXT,
            tags TEXT,
            metadata TEXT
        );
    """)

    # cron_events
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cron_events (
            id BIGSERIAL PRIMARY KEY,
            timestamp REAL,
            iso_time TEXT,
            job_name TEXT,
            job_id TEXT,
            status TEXT,
            output_size INTEGER,
            output_hash TEXT,
            runtime_sec REAL,
            deliver_to TEXT,
            error_msg TEXT,
            metadata TEXT
        );
    """)

    # agent_actions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_actions (
            id BIGSERIAL PRIMARY KEY,
            timestamp REAL,
            iso_time TEXT,
            agent_name TEXT,
            action TEXT,
            target TEXT,
            result TEXT,
            runtime_sec REAL,
            metadata TEXT
        );
    """)

    # lord_decrees
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lord_decrees (
            id BIGSERIAL PRIMARY KEY,
            timestamp REAL,
            iso_time TEXT,
            decree TEXT,
            source TEXT,
            priority INTEGER,
            executed INTEGER,
            executed_at TEXT,
            metadata TEXT
        );
    """)

    # system_health
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_health (
            id BIGSERIAL PRIMARY KEY,
            timestamp REAL,
            iso_time TEXT,
            disk_used TEXT,
            disk_avail TEXT,
            disk_pct INTEGER,
            active_jobs INTEGER,
            vfl_procs INTEGER,
            db_history_rows INTEGER,
            db_sovereign_rows INTEGER,
            metadata TEXT
        );
    """)

    pg_conn.commit()
    print("Postgres schema created.")

def main():
    pg_conn = psycopg2.connect(**PG_CONFIG)
    create_postgres_schema(pg_conn)
    
    for db_name, tables in DB_MAP.items():
        db_path = os.path.join(SQLITE_DIR, db_name)
        if not os.path.exists(db_path):
            print(f"SQLite DB {db_name} not found at {db_path}. Skipping.")
            continue
            
        print(f"Opening SQLite DB: {db_name}")
        sqlite_conn = sqlite3.connect(db_path)
        
        if isinstance(tables, str):
            migrate_table(sqlite_conn, pg_conn, tables)
        else:
            for table in tables:
                migrate_table(sqlite_conn, pg_conn, table)
                
        sqlite_conn.close()
        
    pg_conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    main()
