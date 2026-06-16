#!/usr/bin/env python3
import sqlite3
import psycopg2
import os
import sys
import csv
import tempfile
import time
from datetime import datetime

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

LOG_FILE = "/home/ubuntu/faith-workspace/vfl-empire/logs/migration_fast.log"

def log_action(pg_conn, action, target, result, runtime_sec):
    # Log to file
    msg = f"[{datetime.now().isoformat()}] {action} on {target}: {result} (in {runtime_sec:.2f}s)"
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")
    print(msg)
    
    # Log to Postgres agent_actions table
    try:
        cur = pg_conn.cursor()
        cur.execute("""
            INSERT INTO agent_actions (timestamp, iso_time, agent_name, action, target, result, runtime_sec, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            time.time(),
            datetime.now().isoformat(),
            "Antigravity",
            action,
            target,
            result,
            runtime_sec,
            '{"method": "COPY FROM STDIN"}'
        ))
        pg_conn.commit()
    except Exception as e:
        print(f"Failed to log to agent_actions: {e}")
        pg_conn.rollback()

def migrate_table_fast(sqlite_conn, pg_conn, table_name):
    start_time = time.time()
    print(f"Migrating table: {table_name} via COPY...")
    
    cursor = sqlite_conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {table_name}")
    except sqlite3.OperationalError:
        print(f"  Table {table_name} not found in SQLite. Skipping.")
        return
        
    cols = [description[0] for description in cursor.description]
    
    # Create a temporary file to hold CSV data
    fd, temp_path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        
        row_count = 0
        while True:
            rows = cursor.fetchmany(50000)
            if not rows:
                break
                
            clean_rows = []
            for row in rows:
                row_list = list(row)
                if table_name == "vfl_predictions" and "confidence" in cols:
                    idx = cols.index("confidence")
                    val = row_list[idx]
                    if isinstance(val, str) and "%" in val:
                        try:
                            row_list[idx] = int(val.replace("%", ""))
                        except ValueError:
                            row_list[idx] = None
                clean_rows.append(row_list)
            
            writer.writerows(clean_rows)
            row_count += len(rows)

    if row_count == 0:
        print(f"  Table {table_name} is empty. Skipping.")
        os.remove(temp_path)
        return

    # Use COPY for fast insertion
    pg_cur = pg_conn.cursor()
    
    # Truncate to ensure clean import (optional, but good for bulk migration)
    # Actually, let's not TRUNCATE unless we want to replace. We will rely on unique constraints?
    # COPY will fail if there are duplicates. Let's create a temp table, COPY into it, then INSERT ON CONFLICT DO NOTHING.
    temp_table = f"temp_{table_name}"
    
    try:
        # Create temp table matching the target
        pg_cur.execute(f"CREATE TEMP TABLE {temp_table} (LIKE {table_name} INCLUDING DEFAULTS)")
        
        col_str = ", ".join(cols)
        
        # Copy into temp table, explicitly mapping columns
        with open(temp_path, 'r', encoding='utf-8') as f:
            pg_cur.copy_expert(f"COPY {temp_table} ({col_str}) FROM STDIN WITH CSV HEADER", f)
        
        # Insert from temp to actual with ON CONFLICT DO NOTHING
        insert_query = f"""
            INSERT INTO {table_name} ({col_str})
            SELECT {col_str} FROM {temp_table}
            ON CONFLICT DO NOTHING
        """
        pg_cur.execute(insert_query)
        pg_cur.execute(f"DROP TABLE {temp_table}")
        
        pg_conn.commit()
        runtime = time.time() - start_time
        log_action(pg_conn, "MIGRATE_POSTGRES", table_name, f"Successfully migrated {row_count} rows", runtime)
        
    except Exception as e:
        pg_conn.rollback()
        runtime = time.time() - start_time
        log_action(pg_conn, "MIGRATE_ERROR", table_name, f"Error: {str(e)}", runtime)
    finally:
        os.remove(temp_path)


def main():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    pg_conn = psycopg2.connect(**PG_CONFIG)
    
    # Ensure agent_actions table exists
    cur = pg_conn.cursor()
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
    pg_conn.commit()

    total_start = time.time()
    
    for db_name, tables in DB_MAP.items():
        db_path = os.path.join(SQLITE_DIR, db_name)
        if not os.path.exists(db_path):
            print(f"SQLite DB {db_name} not found at {db_path}. Skipping.")
            continue
            
        print(f"Opening SQLite DB: {db_name}")
        sqlite_conn = sqlite3.connect(db_path)
        
        if isinstance(tables, str):
            migrate_table_fast(sqlite_conn, pg_conn, tables)
        else:
            for table in tables:
                migrate_table_fast(sqlite_conn, pg_conn, table)
                
        sqlite_conn.close()
        
    total_runtime = time.time() - total_start
    log_action(pg_conn, "MIGRATE_COMPLETE", "ALL", "Finished full SQLite to Postgres bulk migration", total_runtime)
    pg_conn.close()

if __name__ == "__main__":
    main()
