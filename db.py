# db.py
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import threading
from dotenv import load_dotenv

load_dotenv()

_raw = os.getenv("DATABASE_URL", "")
# psycopg2 needs postgresql:// not postgresql+psycopg2:// (SQLAlchemy format)
DATABASE_URL = _raw.replace("postgresql+psycopg2://", "postgresql://", 1)

# ── Connection pool (min=2, max=10) ──────────────────────────────────────────
_pool: psycopg2.pool.ThreadedConnectionPool = None
_pool_lock = threading.Lock()

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
    return _pool


def _reset_pool():
    """Close stale pool and create a fresh one."""
    global _pool
    with _pool_lock:
        old = _pool
        _pool = None          # None karo pehle — takay get_pool retry kare
        if old is not None:
            try:
                old.closeall()
            except Exception:
                pass
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
            print("[DB] Pool recreated successfully.")
        except Exception as e:
            print(f"[DB] Pool recreation failed: {e} — will retry on next query")


def get_conn():
    conn = _get_pool().getconn()
    conn.autocommit = False
    return conn


def release_conn(conn):
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


_CONN_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError,
                psycopg2.pool.PoolError)


def fetchall(query: str, params=None):
    for attempt in range(2):
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params or ())
                rows = [dict(r) for r in cur.fetchall()]
            conn.commit()
            release_conn(conn)
            return rows
        except _CONN_ERRORS:
            try: conn.rollback()
            except Exception: pass
            release_conn(conn)
            if attempt == 0:
                print("[DB] Connection lost — resetting pool and retrying...")
                _reset_pool()
                import time; time.sleep(1)
            else:
                raise
        except Exception:
            try: conn.rollback()
            except Exception: pass
            release_conn(conn)
            raise


def execute(query: str, params=None):
    for attempt in range(2):
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params or ())
            conn.commit()
            release_conn(conn)
            return
        except _CONN_ERRORS:
            try: conn.rollback()
            except Exception: pass
            release_conn(conn)
            if attempt == 0:
                print("[DB] Connection lost — resetting pool and retrying...")
                _reset_pool()
                import time; time.sleep(1)
            else:
                raise
        except Exception:
            try: conn.rollback()
            except Exception: pass
            release_conn(conn)
            raise


def executemany(query: str, params_list):
    for attempt in range(2):
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, query, params_list)
            conn.commit()
            release_conn(conn)
            return
        except _CONN_ERRORS:
            try: conn.rollback()
            except Exception: pass
            release_conn(conn)
            if attempt == 0:
                print("[DB] Connection lost — resetting pool and retrying...")
                _reset_pool()
                import time; time.sleep(1)
            else:
                raise
        except Exception:
            try: conn.rollback()
            except Exception: pass
            release_conn(conn)
            raise


# ── app_state key-value table — ticker cursor, cleanup timestamps, etc. ───────

def _ensure_app_state_table():
    execute("""
        CREATE TABLE IF NOT EXISTS app_state (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)


def get_state(key: str, default=None):
    """Read a value from app_state by key. Returns default if missing."""
    try:
        rows = fetchall("SELECT value FROM app_state WHERE key = %s", (key,))
        if rows:
            return rows[0]['value']
        return default
    except Exception as e:
        print(f"[DB] get_state({key}) error: {e}")
        return default


def set_state(key: str, value: str):
    """Upsert a value in app_state."""
    try:
        execute("""
            INSERT INTO app_state (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, (key, value))
    except Exception as e:
        print(f"[DB] set_state({key}) error: {e}")


# ── Init: ensure app_state table exists on import ─────────────────────────────
try:
    _ensure_app_state_table()
except Exception as _e:
    print(f"[DB] app_state table init warning: {_e}")
