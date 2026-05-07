"""
stream_registry.py
──────────────────
Active streams ko track karta hai — ek simple JSON file ke through.
cpu_governor.py isko read karta hai builder ko throttle karne ke liye.

Existing files mein changes:
  yt_streamer.py → stream start/stop pe 2 function calls add honge
                   (marked with # [STREAM REGISTRY HOOK])

Direct use:
    from stream_registry import stream_up, stream_down, get_active_count
"""

import os
import json
import time
import threading
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR       = Path(__file__).parent
REGISTRY_FILE  = BASE_DIR / "stream_registry.json"

# Agar stream X seconds tak heartbeat na bheje to dead maano
STREAM_TIMEOUT_SECONDS = 30

_lock = threading.Lock()

# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if REGISTRY_FILE.exists():
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"streams": {}}


def _save(data: dict):
    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[REGISTRY] ⚠️ Save failed: {e}")


def _purge_dead(data: dict) -> dict:
    """Timeout ho chuke streams ko registry se hata do."""
    now     = time.time()
    active  = {
        label: info
        for label, info in data.get("streams", {}).items()
        if now - info.get("last_heartbeat", 0) < STREAM_TIMEOUT_SECONDS
    }
    data["streams"] = active
    return data

# ── Public API ────────────────────────────────────────────────────────────────

def stream_up(label: str, pid: int = None):
    """
    Stream start hone pe call karo.

    yt_streamer.py mein use:
        from stream_registry import stream_up
        stream_up("LocalAiTV", process.pid)   # [STREAM REGISTRY HOOK]
    """
    with _lock:
        data = _load()
        data = _purge_dead(data)
        data["streams"][label] = {
            "pid":            pid,
            "started_at":     time.time(),
            "last_heartbeat": time.time(),
            "status":         "live",
        }
        _save(data)
    print(f"[REGISTRY] 🔴 Stream UP: {label} (PID={pid})")


def stream_down(label: str):
    """
    Stream stop/crash hone pe call karo.

    yt_streamer.py mein use:
        from stream_registry import stream_down
        stream_down("LocalAiTV")   # [STREAM REGISTRY HOOK]
    """
    with _lock:
        data = _load()
        data["streams"].pop(label, None)
        _save(data)
    print(f"[REGISTRY] ⚫ Stream DOWN: {label}")


def stream_heartbeat(label: str):
    """
    Stream alive hai — heartbeat bhejo (optional, har 10s pe call karo).
    Agar stream crash ho jaye to timeout ke baad automatically remove hoga.
    """
    with _lock:
        data = _load()
        if label in data.get("streams", {}):
            data["streams"][label]["last_heartbeat"] = time.time()
            _save(data)


def get_active_streams() -> dict:
    """
    Abhi live streams ka dict return karo.
    Dead/timed-out streams automatically exclude honge.
    """
    with _lock:
        data = _load()
        data = _purge_dead(data)
        _save(data)
        return dict(data.get("streams", {}))


def get_active_count() -> int:
    """Kitne streams abhi live hain."""
    return len(get_active_streams())


def is_any_stream_live() -> bool:
    """Koi bhi stream live hai?"""
    return get_active_count() > 0


def clear_all():
    """Sab streams reset karo — server restart pe use karo."""
    with _lock:
        _save({"streams": {}})
    print("[REGISTRY] 🔄 All streams cleared")


# ── Status print ──────────────────────────────────────────────────────────────

def print_status():
    streams = get_active_streams()
    if not streams:
        print("[REGISTRY] No active streams")
        return
    print(f"[REGISTRY] {len(streams)} active stream(s):")
    now = time.time()
    for label, info in streams.items():
        age = int(now - info.get("started_at", now))
        hb  = int(now - info.get("last_heartbeat", now))
        print(f"  • {label:<20} PID={info.get('pid')} | up={age}s | last_hb={hb}s ago")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        print_status()
    elif cmd == "clear":
        clear_all()
        print("[REGISTRY] Cleared.")
    elif cmd == "count":
        print(get_active_count())
    else:
        print("Usage: python stream_registry.py [status|clear|count]")