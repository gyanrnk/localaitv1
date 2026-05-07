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









import sqlite3
import os
import threading
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'item_events.db')
_lock = threading.Lock()

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _lock:
        with _conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS item_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id     TEXT,
                    counter         INTEGER,
                    media_type      TEXT,
                    event           TEXT NOT NULL,
                    at              TEXT NOT NULL,
                    bulletin_name   TEXT,
                    api_item_id     TEXT,
                    api_status      TEXT,
                    api_response    TEXT,
                    extra           TEXT
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_incident ON item_events(incident_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_counter  ON item_events(counter, media_type)")
            c.execute("""
                CREATE TABLE IF NOT EXISTS bulletin_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    bulletin_name   TEXT,
                    event           TEXT NOT NULL,
                    at              TEXT NOT NULL,
                    api_bulletin_id TEXT,
                    api_status      TEXT,
                    api_response    TEXT
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_bul_name ON bulletin_events(bulletin_name)")
            c.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    counter          INTEGER,
                    title            TEXT,
                    description      TEXT,
                    category_id      TEXT,
                    location_id      TEXT,
                    post_location    TEXT,
                    user_id          TEXT,
                    timestamp        TEXT,
                    cover_image_path TEXT,
                    video_path       TEXT,
                    segments_path    TEXT,
                    incident_id      TEXT,
                    received_at      REAL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_incidents_received ON incidents(received_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_incidents_user     ON incidents(user_id)")
            c.commit()

# Auto-init on import
# init_db()

def log_event(event, counter=None, media_type=None, incident_id=None,
              bulletin_name=None, api_item_id=None, api_status=None,
              api_response=None, extra=None):
    try:
        with _lock:
            with _conn() as c:
                c.execute("""
                    INSERT INTO item_events
                        (incident_id, counter, media_type, event, at,
                         bulletin_name, api_item_id, api_status, api_response, extra)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (incident_id, counter, media_type, event,
                      datetime.now().isoformat(),
                      bulletin_name, api_item_id, api_status, api_response, extra))
                c.commit()
    except Exception as e:
        print(f"⚠️ event_logger warning: {e}")

def log_bulletin_event(
    event: str,
    bulletin_name: str   = None,
    api_bulletin_id: str = None,
    api_status: str      = None,
    api_response: str    = None,
):
    with _lock:
        with _conn() as c:
            c.execute("""
                INSERT INTO bulletin_events
                    (bulletin_name, event, at, api_bulletin_id, api_status, api_response)
                VALUES (?,?,?,?,?,?)
            """, (
                bulletin_name, event, datetime.now().isoformat(),
                api_bulletin_id, api_status, api_response
            ))
            c.commit()

def update_incident_id(counter: int, media_type: str, incident_id: str):
    with _lock:
        with _conn() as c:
            c.execute("""
                UPDATE item_events 
                SET incident_id = ?
                WHERE counter = ? AND media_type = ?
            """, (incident_id, counter, media_type))
            c.commit()

def save_incident(payload: dict, incident_id: str = None):
    import time
    with _lock:
        with _conn() as c:
            # ✅ REMOVE counter from INSERT
            c.execute("""
                INSERT INTO incidents
                    (incident_id, title, description, category_id, location_id, 
                     post_location, user_id, timestamp, cover_image_path, 
                     video_path, segments_path, received_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
            c.commit()