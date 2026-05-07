"""
report_state_manager.py
-----------------------
Tracks per-report processing state to disk so that:
  - If a crash happens mid-pipeline, the report is NOT silently lost
  - On retry, already-completed stages are skipped (checkpoint resume)

State file: <BASE_DIR>/report_state.json
Schema per entry:
  {
    "status":   "processing" | "failed" | "complete",
    "stage":    "download" | "transcribe" | "script" | "tts" | "save" | "done",
    "attempts": 1,
    "last_attempt": "<iso timestamp>",
    "checkpoint": { ...partial results... },
    "original_report": { ...full API payload... }
  }
"""

import json
import os
import threading
from datetime import datetime

_lock = threading.Lock()

try:
    from config import BASE_DIR
except ImportError:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STATE_FILE = os.path.join(BASE_DIR, 'report_state.json')

# How many minutes a "processing" entry must be stale before we treat it as stuck/crashed
STUCK_THRESHOLD_MINUTES = 10


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"[ReportState] ⚠️ Could not save state file: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def mark_processing(report_id: str, original_report: dict):
    """Call when we first pick up a report. Saves original payload."""
    with _lock:
        data = _load()
        existing = data.get(report_id, {})
        data[report_id] = {
            'status':          'processing',
            'stage':           'download',
            'attempts':        existing.get('attempts', 0) + 1,
            'last_attempt':    datetime.now().isoformat(),
            'checkpoint':      existing.get('checkpoint', {}),  # keep any prior checkpoint
            'original_report': original_report,
        }
        _save(data)


def update_stage(report_id: str, stage: str, checkpoint: dict = None):
    """
    Call after each pipeline stage completes.
    checkpoint dict is MERGED into existing checkpoint (not replaced).
    """
    with _lock:
        data = _load()
        entry = data.get(report_id, {})
        entry['stage'] = stage
        entry['last_attempt'] = datetime.now().isoformat()
        if checkpoint:
            existing_cp = entry.get('checkpoint', {})
            existing_cp.update(checkpoint)
            entry['checkpoint'] = existing_cp
        data[report_id] = entry
        _save(data)


def mark_complete(report_id: str):
    """Call when bulletin item has been appended successfully."""
    with _lock:
        data = _load()
        entry = data.get(report_id, {})
        entry['status'] = 'complete'
        entry['stage']  = 'done'
        entry['last_attempt'] = datetime.now().isoformat()
        data[report_id] = entry
        _save(data)


def mark_failed(report_id: str, reason: str = ''):
    """Call when processing fails and should be retried later."""
    with _lock:
        data = _load()
        entry = data.get(report_id, {})
        entry['status'] = 'failed'
        entry['fail_reason'] = reason
        entry['last_attempt'] = datetime.now().isoformat()
        data[report_id] = entry
        _save(data)


def get_state(report_id: str) -> dict:
    with _lock:
        return _load().get(report_id, {})


def get_checkpoint(report_id: str) -> dict:
    return get_state(report_id).get('checkpoint', {})


def get_retryable_reports() -> list:
    """
    Returns list of original_report dicts that need retry:
      - status == 'failed'
      - OR status == 'processing' and last_attempt > STUCK_THRESHOLD_MINUTES ago (stuck/crashed)
    Only returns reports with attempts < 5 (give up after 5 tries).
    """
    from datetime import timedelta
    now = datetime.now()
    retryable = []

    with _lock:
        data = _load()

    for report_id, entry in data.items():
        status   = entry.get('status')
        attempts = entry.get('attempts', 0)

        if attempts >= 5:
            continue  # give up after 5 tries

        if status == 'failed':
            retryable.append(entry.get('original_report', {}))

        elif status == 'processing':
            last_str = entry.get('last_attempt')
            if last_str:
                try:
                    last_dt = datetime.fromisoformat(last_str)
                    if now - last_dt > timedelta(minutes=STUCK_THRESHOLD_MINUTES):
                        retryable.append(entry.get('original_report', {}))
                except Exception:
                    pass

    return retryable