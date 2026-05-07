# import sqlite3
# import os
# import threading
# from datetime import datetime

# DB_PATH = os.path.join(os.path.dirname(__file__), 'item_events.db')
# _lock = threading.Lock()

# def _conn():
#     c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
#     c.row_factory = sqlite3.Row
#     return c

# def init_db():
#     with _lock:
#         with _conn() as c:
#             c.execute("""
#                 CREATE TABLE IF NOT EXISTS item_events (
#                     id              INTEGER PRIMARY KEY AUTOINCREMENT,
#                     incident_id     TEXT,
#                     counter         INTEGER,
#                     media_type      TEXT,
#                     event           TEXT NOT NULL,
#                     at              TEXT NOT NULL,
#                     bulletin_name   TEXT,
#                     api_item_id     TEXT,
#                     api_status      TEXT,
#                     api_response    TEXT,
#                     extra           TEXT
#                 )
#             """)
#             c.execute("CREATE INDEX IF NOT EXISTS idx_incident ON item_events(incident_id)")
#             c.execute("CREATE INDEX IF NOT EXISTS idx_counter  ON item_events(counter, media_type)")
#             c.execute("""
#                 CREATE TABLE IF NOT EXISTS bulletin_events (
#                     id              INTEGER PRIMARY KEY AUTOINCREMENT,
#                     bulletin_name   TEXT,
#                     event           TEXT NOT NULL,
#                     at              TEXT NOT NULL,
#                     api_bulletin_id TEXT,
#                     api_status      TEXT,
#                     api_response    TEXT
#                 )
#             """)
#             c.execute("CREATE INDEX IF NOT EXISTS idx_bul_name ON bulletin_events(bulletin_name)")
#             c.commit()
#             c.execute("""
#                 CREATE TABLE IF NOT EXISTS incidents (
#                     id            INTEGER PRIMARY KEY AUTOINCREMENT,
#                     counter       INTEGER,
#                     title         TEXT,
#                     description   TEXT,
#                     category_id   TEXT,
#                     location_id   TEXT,
#                     post_location TEXT,
#                     user_id       TEXT,
#                     timestamp     TEXT,
#                     cover_image_path TEXT,
#                     video_path    TEXT,
#                     segments_path TEXT,
#                     incident_id   TEXT,
#                     received_at   REAL
#                 )""")

# # Auto-init on import
# # init_db()

# def log_event(event, counter=None, media_type=None, incident_id=None,
#               bulletin_name=None, api_item_id=None, api_status=None,
#               api_response=None, extra=None):
#     try:
#         with _lock:
#             with _conn() as c:
#                 c.execute("""
#                     INSERT INTO item_events
#                         (incident_id, counter, media_type, event, at,
#                          bulletin_name, api_item_id, api_status, api_response, extra)
#                     VALUES (?,?,?,?,?,?,?,?,?,?)
#                 """, (incident_id, counter, media_type, event,
#                       datetime.now().isoformat(),
#                       bulletin_name, api_item_id, api_status, api_response, extra))
#                 c.commit()
#     except Exception as e:
#         print(f"⚠️ event_logger warning: {e}")

# def log_bulletin_event(
#     event: str,
#     bulletin_name: str   = None,
#     api_bulletin_id: str = None,
#     api_status: str      = None,
#     api_response: str    = None,
# ):
#     with _lock:
#         with _conn() as c:
#             c.execute("""
#                 INSERT INTO bulletin_events
#                     (bulletin_name, event, at, api_bulletin_id, api_status, api_response)
#                 VALUES (?,?,?,?,?,?)
#             """, (
#                 bulletin_name, event, datetime.now().isoformat(),
#                 api_bulletin_id, api_status, api_response
#             ))
#             c.commit()

# def update_incident_id(counter: int, media_type: str, incident_id: str):
#     with _lock:
#         with _conn() as c:
#             c.execute("""
#                 UPDATE item_events 
#                 SET incident_id = ?
#                 WHERE counter = ? AND media_type = ?
#             """, (incident_id, counter, media_type))
#             c.commit()

# def save_incident(payload: dict, incident_id: str = None):
#     import time
#     with _conn() as c:
#         c.execute("""
#             INSERT INTO incidents
#             (counter, title, description, category_id, location_id, post_location,
#              user_id, timestamp, cover_image_path, video_path, segments_path, incident_id, received_at)
#             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
#         """, (
#             payload.get('counter'),
#             payload.get('title'),
#             payload.get('description'),
#             payload.get('category_id'),
#             payload.get('location_id'),
#             payload.get('post_location'),
#             payload.get('user_id'),
#             payload.get('timestamp'),
#             payload.get('cover_image_path'),
#             payload.get('video_path'),
#             payload.get('segments_path'),
#             incident_id,
#             time.time()
#         ))









# ── SQLite version (commented out — replaced by PostgreSQL/CloudSQL) ──────────
# import sqlite3
# import os
# import threading
# from datetime import datetime
#
# DB_PATH = os.path.join(os.path.dirname(__file__), 'item_events.db')
# _lock = threading.Lock()
#
# def _conn():
#     c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
#     c.row_factory = sqlite3.Row
#     return c
#
# def init_db(): ...  # tables already exist in CloudSQL schema
#
# def log_event(event, counter=None, media_type=None, incident_id=None,
#               bulletin_name=None, api_item_id=None, api_status=None,
#               api_response=None, extra=None):
#     with _lock:
#         with _conn() as c:
#             c.execute("INSERT INTO item_events ... VALUES (?,?,?,?,?,?,?,?,?,?)", (...))
#             c.commit()
#
# def log_bulletin_event(event, bulletin_name=None, api_bulletin_id=None,
#                        api_status=None, api_response=None):
#     with _lock:
#         with _conn() as c:
#             c.execute("INSERT INTO bulletin_events ... VALUES (?,?,?,?,?,?)", (...))
#             c.commit()
#
# def update_incident_id(counter, media_type, incident_id):
#     with _lock:
#         with _conn() as c:
#             c.execute("UPDATE item_events SET incident_id=? WHERE counter=? AND media_type=?", (...))
#             c.commit()
#
# def save_incident(payload, incident_id=None):
#     with _conn() as c:
#         c.execute("INSERT INTO incidents (...) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (...))
#         c.commit()
# ─────────────────────────────────────────────────────────────────────────────

# ── PostgreSQL/CloudSQL version ───────────────────────────────────────────────
import time
from datetime import datetime
import db

def init_db():
    pass  # tables already exist in CloudSQL

def log_event(event, counter=None, media_type=None, incident_id=None,
              bulletin_name=None, api_item_id=None, api_status=None,
              api_response=None, extra=None):
    try:
        db.execute("""
            INSERT INTO item_events
                (incident_id, counter, media_type, event, at,
                 bulletin_name, api_item_id, api_status, api_response, extra)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (incident_id, counter, media_type, event,
              datetime.now().isoformat(),
              bulletin_name, api_item_id, api_status, api_response, extra))
    except Exception as e:
        print(f"⚠️ event_logger warning: {e}")

def log_bulletin_event(
    event: str,
    bulletin_name: str   = None,
    api_bulletin_id: str = None,
    api_status: str      = None,
    api_response: str    = None,
):
    try:
        db.execute("""
            INSERT INTO bulletin_events
                (bulletin_name, event, at, api_bulletin_id, api_status, api_response)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (bulletin_name, event, datetime.now().isoformat(),
              api_bulletin_id, api_status, api_response))
    except Exception as e:
        print(f"⚠️ log_bulletin_event warning: {e}")

def update_incident_id(counter: int, media_type: str, incident_id: str):
    try:
        db.execute("""
            UPDATE item_events
            SET incident_id = %s
            WHERE counter = %s AND media_type = %s
        """, (incident_id, counter, media_type))
    except Exception as e:
        print(f"⚠️ update_incident_id warning: {e}")

def save_incident(payload: dict, incident_id: str = None):
    try:
        db.execute("""
            INSERT INTO incidents
                (incident_id, title, description, category_id, location_id,
                 post_location, user_id, timestamp, cover_image_path,
                 video_path, segments_path, received_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            incident_id,
            payload.get('title'),
            payload.get('description'),
            payload.get('category_id'),
            payload.get('location_id'),
            payload.get('post_location'),
            payload.get('user_id'),
            payload.get('timestamp'),
            payload.get('cover_image_path'),
            payload.get('video_path'),
            payload.get('segments_path'),
            time.time()
        ))
    except Exception as e:
        print(f"⚠️ save_incident warning: {e}")
# ─────────────────────────────────────────────────────────────────────────────