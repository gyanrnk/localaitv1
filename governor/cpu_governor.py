"""
cpu_governor.py
───────────────
CPU usage monitor — stream count ke hisaab se builder ko throttle karta hai.

video_builder.py mein _run() function ke andar ek hook add hoga:
    governor.wait_for_slot()   # [CPU GOVERNOR HOOK]
    ... ffmpeg call ...

Yeh file khud kuch launch nahi karta — sirf signal deta hai.

Direct use:
    from cpu_governor import CpuGovernor
    governor = CpuGovernor()
    governor.wait_for_slot()   # block karega jab CPU tight ho
"""

import time
import threading
import platform

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[GOVERNOR] ⚠️  psutil not found — install: pip install psutil")
    print("[GOVERNOR]    CPU monitoring disabled, throttle based on stream count only")

from stream_registry import get_active_count, is_any_stream_live

# ── Thresholds ────────────────────────────────────────────────────────────────
#
#  Stream count ke hisaab se builder ko kitna CPU milega:
#
#  active_streams=0  → Builder freely chalega (CPU < CPU_FREE_THRESHOLD tak)
#  active_streams=1  → Builder slow hoga (FFmpeg calls ke beech sleep)
#  active_streams=2  → Builder aur slow hoga
#  active_streams=3+ → Builder minimum speed pe chalega
#
CPU_FREE_THRESHOLD  = 75   # % — agar CPU < yeh hai aur koi stream nahi to free run
CPU_WARN_THRESHOLD  = 85   # % — agar CPU > yeh hai to builder wait karega
CPU_HARD_THRESHOLD  = 92   # % — agar CPU > yeh hai to builder zyada wait karega

# Stream count ke hisaab se FFmpeg calls ke beech delay (seconds)
STREAM_DELAY_MAP = {
    0: 0.0,    # No streams — no delay
    1: 2.0,    # 1 stream — 2s delay between FFmpeg calls
    2: 4.0,    # 2 streams — 4s delay
    3: 7.0,    # 3+ streams — 7s delay
}

# CPU high hone pe extra wait (seconds)
CPU_WAIT_INTERVAL = 3.0    # kitni der baad dobara check kare
CPU_MAX_WAIT      = 60.0   # maximum kitna wait kare ek FFmpeg call ke pehle

IS_LINUX = platform.system() == "Linux"


# ── Governor Class ────────────────────────────────────────────────────────────

class CpuGovernor:
    """
    Builder ke har FFmpeg call se pehle yeh check karta hai:
      1. Kitne streams live hain?
      2. CPU kitna busy hai?
      → Dono ke hisaab se wait karta hai ya proceed karta hai.
    """

    def __init__(self):
        self._enabled   = True
        self._lock      = threading.Lock()
        self._last_cpu  = 0.0
        self._cpu_thread_running = False

        # Background mein CPU monitor karo (psutil blocking avoid karne ke liye)
        if PSUTIL_AVAILABLE:
            self._start_cpu_monitor()

    def _start_cpu_monitor(self):
        """Background thread — har 2s pe CPU usage update karo."""
        def _loop():
            self._cpu_thread_running = True
            while self._cpu_thread_running:
                try:
                    # interval=2 means it measures over 2 seconds — accurate
                    self._last_cpu = psutil.cpu_percent(interval=2)
                except Exception:
                    self._last_cpu = 0.0
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def get_cpu(self) -> float:
        """Current CPU usage % return karo."""
        if not PSUTIL_AVAILABLE:
            return 0.0
        return self._last_cpu

    def get_delay(self) -> float:
        """
        Current stream count ke hisaab se base delay return karo.
        """
        count = get_active_count()
        # 3 ya zyada streams — max delay
        key   = min(count, 3)
        return STREAM_DELAY_MAP.get(key, 7.0)

    def wait_for_slot(self, desc: str = ""):
        """
        FFmpeg call se pehle yeh call karo.
        Zaroorat hone pe block karega — CPU/stream situation theek hone tak.

        video_builder.py ke _run() mein:
            governor.wait_for_slot(desc)   # [CPU GOVERNOR HOOK]
        """
        if not self._enabled:
            return

        # ── Step 1: Stream count based delay ─────────────────────────────────
        base_delay = self.get_delay()
        if base_delay > 0:
            stream_count = get_active_count()
            print(f"  [GOVERNOR] 💤 {base_delay}s wait ({stream_count} stream(s) live) | {desc}")
            time.sleep(base_delay)

        # ── Step 2: CPU threshold check ───────────────────────────────────────
        if not PSUTIL_AVAILABLE:
            return

        waited      = 0.0
        cpu         = self.get_cpu()

        while cpu > CPU_WARN_THRESHOLD and waited < CPU_MAX_WAIT:
            wait_time = CPU_WAIT_INTERVAL * (2.0 if cpu > CPU_HARD_THRESHOLD else 1.0)
            print(f"  [GOVERNOR] ⏸️  CPU={cpu:.0f}% (>{CPU_WARN_THRESHOLD}%) — waiting {wait_time:.0f}s | {desc}")
            time.sleep(wait_time)
            waited += wait_time
            cpu     = self.get_cpu()

        if waited > 0:
            print(f"  [GOVERNOR] ▶️  CPU={cpu:.0f}% — proceeding after {waited:.0f}s wait")

    def disable(self):
        """Governor band karo — builder full speed chalega."""
        self._enabled = False
        print("[GOVERNOR] ⚡ Disabled — builder running at full speed")

    def enable(self):
        """Governor wapas on karo."""
        self._enabled = True
        print("[GOVERNOR] ✅ Enabled")

    def status(self):
        """Current status print karo."""
        cpu          = self.get_cpu()
        stream_count = get_active_count()
        delay        = self.get_delay()
        print(f"[GOVERNOR] CPU={cpu:.0f}% | Streams={stream_count} | Delay={delay}s | Enabled={self._enabled}")


# ── Singleton — video_builder.py import karke use karega ─────────────────────
#
#  video_builder.py mein:
#      from cpu_governor import governor
#      ...
#      governor.wait_for_slot(desc)   # [CPU GOVERNOR HOOK]
#
governor = CpuGovernor()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        governor.status()

    elif cmd == "monitor":
        # Continuously CPU + stream status dikhao
        print("[GOVERNOR] Monitoring... (Ctrl+C to stop)")
        try:
            while True:
                cpu    = governor.get_cpu()
                count  = get_active_count()
                delay  = governor.get_delay()
                bar    = "█" * int(cpu / 5) + "░" * (20 - int(cpu / 5))
                live   = "🔴 LIVE" if is_any_stream_live() else "⚫ no stream"
                print(f"\r  CPU [{bar}] {cpu:5.1f}% | {live} ({count}) | builder_delay={delay}s", end="", flush=True)
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n[GOVERNOR] Stopped.")

    else:
        print("Usage: python cpu_governor.py [status|monitor]")