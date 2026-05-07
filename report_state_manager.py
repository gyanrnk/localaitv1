"""
report_state_manager.py
-----------------------
Tracks per-report processing state in PostgreSQL/CloudSQL so that:
  - If a crash happens mid-pipeline, the report is NOT silently lost
  - On retry, already-completed stages are skipped (checkpoint resume)
  - Multiple worker instances share the same state (horizontal scaling)

Uses: processed_reports table
  report_id   TEXT PK
  status      TEXT  — processing | failed | complete
  source      TEXT
  created_at  TEXT
  payload     TEXT  — JSON: {stage, attempts, last_attempt, checkpoint, original_report}
"""

# ── JSON file version (commented out — replaced by PostgreSQL/CloudSQL) ───────
# import json, os, threading
# from datetime import datetime
# STATE_FILE = os.path.join(BASE_DIR, 'report_state.json')
# _lock = threading.Lock()
#
# def _load() -> dict:
#     with open(STATE_FILE, 'r') as f: return json.load(f)
#
# def _save(data): ...
#
# def mark_processing(report_id, original_report):
#     with _lock: data = _load(); data[report_id] = {...}; _save(data)
#
# def update_stage(report_id, stage, checkpoint=None):
#     with _lock: data = _load(); entry = data[report_id]; entry['stage']=stage; _save(data)
#
# def mark_complete(report_id):
#     with _lock: data = _load(); data[report_id]['status']='complete'; _save(data)
#
# def mark_failed(report_id, reason=''):
#     with _lock: data = _load(); data[report_id]['status']='failed'; _save(data)
#
# def get_state(report_id): return _load().get(report_id, {})
# def get_checkpoint(report_id): return get_state(report_id).get('checkpoint', {})
# def get_retryable_reports(): ... # reads full JSON, filters by status+attempts
# ─────────────────────────────────────────────────────────────────────────────

# ── PostgreSQL/CloudSQL version ───────────────────────────────────────────────
import json
from datetime import datetime, timedelta
import db

STUCK_THRESHOLD_MINUTES = 10


def _get_row(report_id: str) -> dict:
    rows = db.fetchall(
        "SELECT * FROM processed_reports WHERE report_id = %s",
        (report_id,)
    )
    return rows[0] if rows else {}


def _parse_payload(row: dict) -> dict:
    try:
        return json.loads(row.get('payload') or '{}')
    except Exception:
        return {}


def _upsert(report_id: str, status: str, payload: dict, created_at: str = None):
    payload_str = json.dumps(payload, default=str)
    db.execute("""
        INSERT INTO processed_reports (report_id, status, created_at, payload)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (report_id) DO UPDATE
            SET status     = EXCLUDED.status,
                payload    = EXCLUDED.payload
    """, (report_id, status, created_at or datetime.now().isoformat(), payload_str))


def mark_processing(report_id: str, original_report: dict):
    row     = _get_row(report_id)
    payload = _parse_payload(row)
    payload.update({
        'status':          'processing',
        'stage':           'download',
        'attempts':        payload.get('attempts', 0) + 1,
        'last_attempt':    datetime.now().isoformat(),
        'checkpoint':      payload.get('checkpoint', {}),
        'original_report': original_report,
    })
    _upsert(report_id, 'processing', payload)


def update_stage(report_id: str, stage: str, checkpoint: dict = None):
    row     = _get_row(report_id)
    payload = _parse_payload(row)
    payload['stage']        = stage
    payload['last_attempt'] = datetime.now().isoformat()
    if checkpoint:
        existing_cp = payload.get('checkpoint', {})
        existing_cp.update(checkpoint)
        payload['checkpoint'] = existing_cp
    _upsert(report_id, row.get('status', 'processing'), payload)


def mark_complete(report_id: str):
    row     = _get_row(report_id)
    payload = _parse_payload(row)
    payload['stage']        = 'done'
    payload['last_attempt'] = datetime.now().isoformat()
    _upsert(report_id, 'complete', payload)


def mark_failed(report_id: str, reason: str = ''):
    row     = _get_row(report_id)
    payload = _parse_payload(row)
    payload['fail_reason']  = reason
    payload['last_attempt'] = datetime.now().isoformat()
    _upsert(report_id, 'failed', payload)


def get_state(report_id: str) -> dict:
    row     = _get_row(report_id)
    payload = _parse_payload(row)
    if row:
        payload['status'] = row.get('status', '')
    return payload


def get_checkpoint(report_id: str) -> dict:
    return get_state(report_id).get('checkpoint', {})


def get_retryable_reports() -> list:
    rows = db.fetchall(
        "SELECT * FROM processed_reports WHERE status IN ('failed', 'processing')"
    )
    now       = datetime.now()
    retryable = []
    for row in rows:
        payload  = _parse_payload(row)
        attempts = payload.get('attempts', 0)
        status   = row.get('status')

        if attempts >= 5:
            continue

        if status == 'failed':
            retryable.append(payload.get('original_report', {}))

        elif status == 'processing':
            last_str = payload.get('last_attempt')
            if last_str:
                try:
                    last_dt = datetime.fromisoformat(last_str)
                    if now - last_dt > timedelta(minutes=STUCK_THRESHOLD_MINUTES):
                        retryable.append(payload.get('original_report', {}))
                except Exception:
                    pass

    return retryable
# ─────────────────────────────────────────────────────────────────────────────