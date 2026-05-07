# db.py
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

_raw = os.getenv("DATABASE_URL", "")
# psycopg2 needs postgresql:// not postgresql+psycopg2:// (SQLAlchemy format)
DATABASE_URL = _raw.replace("postgresql+psycopg2://", "postgresql://", 1)

def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def fetchall(query: str, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return [dict(r) for r in cur.fetchall()]

def execute(query: str, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
        conn.commit()

def executemany(query: str, params_list):
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, query, params_list)
        conn.commit()