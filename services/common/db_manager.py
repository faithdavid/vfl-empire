"""Database manager — shared PostgreSQL connections for all services."""
import os, logging, psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger("db_manager")

# --- Postgres Config ---
PG_CONFIG = {
    "dbname": "vfl_empire",
    "user": "vfl_user",
    "password": "vfl_user_pass", # I will use the one I created: vfl_pass
    "host": "localhost",
    "port": "5432"
}
# Note: In a real prod environment, use env vars. For the "Empire" local VM, hardcoding is fine.
PG_CONFIG["password"] = "vfl_pass" 

# Initialize connection pool
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        try:
            _pool = psycopg2.pool.SimpleConnectionPool(1, 20, **PG_CONFIG)
            logger.info("PostgreSQL connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Postgres pool: {e}")
            raise
    return _pool

@contextmanager
def get_db(name: str = "vfl"):
    """Context manager yielding a Postgres connection from the pool."""
    p = get_pool()
    conn = p.getconn()
    conn.autocommit = False
    try:
        # Use DictCursor for backward compatibility with sqlite3.Row
        from psycopg2.extras import DictCursor
        with conn.cursor(cursor_factory=DictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)

def execute(sql: str, params: tuple = ()):
    with get_db() as cur:
        cur.execute(sql, params)
        return cur

def fetch_one(sql: str, params: tuple = ()):
    with get_db() as cur:
        cur.execute(sql, params)
        return cur.fetchone()

def fetch_all(sql: str, params: tuple = ()):
    with get_db() as cur:
        cur.execute(sql, params)
        return cur.fetchall()

def get_db_path(name: str = "") -> str:
    return "postgresql://vfl_user:vfl_pass@localhost/vfl_empire"
