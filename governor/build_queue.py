"""
build_queue.py
──────────────
Bulletin build requests ko queue mein rakhta hai — ek ek karke chalata hai.
Ek time pe sirf ek build hoga — streams ke saath CPU contention nahi hogi.

webhook_server.py mein sirf ek function swap hoga:
    PEHLE:  video_path = build_bulletin_video(bulletin_dir, logo, intro)
    BAAD:   video_path = queue_bulletin_build(bulletin_dir, logo, intro)
            (marked with # [BUILD QUEUE HOOK])

Direct use:
    from build_queue import queue_bulletin_build, get_queue_status
"""

import os
import sys
import time
import threading
import subprocess
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from governor.stream_registry import get_active_count

# ── Config ────────────────────────────────────────────────────────────────────

# BASE_DIR       = Path(__file__).parent
# BUILDER_SCRIPT = BASE_DIR / "video_builder.py"

BASE_DIR       = Path(__file__).resolve().parent
BUILDER_SCRIPT = BASE_DIR.parent / "video_builder.py"

# Queue mein max kitne builds rakh sakte hain
MAX_QUEUE_SIZE = 10

# Builder subprocess ka timeout (seconds) — bahut bada bulletin bhi 30min se zyada nahi lega
BUILD_TIMEOUT = 3600

# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class BuildJob:
    bulletin_dir : str
    logo_path    : str
    intro_path   : str
    ticker_text  : str = ''
    job_id       : str = field(default_factory=lambda: str(int(time.time() * 1000)))
    queued_at    : float = field(default_factory=time.time)
    status       : str = "queued"   # queued | building | done | failed
    result_path  : Optional[str] = None
    error        : Optional[str] = None

    # Blocking — caller wait karega result ke liye
    _event       : threading.Event = field(default_factory=threading.Event)


# ── Queue Manager ─────────────────────────────────────────────────────────────

class BuildQueue:

    def __init__(self):
        self._queue   : deque[BuildJob] = deque()
        self._lock    = threading.Lock()
        self._trigger = threading.Event()
        self._current : Optional[BuildJob] = None

        # Worker thread start karo
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()
        print("[QUEUE] ✅ Build queue worker started")

    # ── Submit ────────────────────────────────────────────────────────────────

    # def submit(self, bulletin_dir: str, logo_path: str,
    #            intro_path: str, block: bool = True) -> Optional[str]:
    def submit(self, bulletin_dir: str, logo_path: str,
               intro_path: str, ticker_text: str = '', block: bool = True) -> Optional[str]:
        """
        Build job queue mein daalo.

        block=True  → caller wait karega result ke liye (webhook_server ke liye)
        block=False → fire-and-forget (background mein chalega)

        Returns: final video path ya None (failed)
        """
        with self._lock:
            if len(self._queue) >= MAX_QUEUE_SIZE:
                print(f"[QUEUE] ❌ Queue full ({MAX_QUEUE_SIZE}) — job rejected")
                return None

        job = BuildJob(
            bulletin_dir=bulletin_dir,
            logo_path=logo_path,
            intro_path=intro_path,
            ticker_text=ticker_text,
        )

        with self._lock:
            self._queue.append(job)

        qsize = len(self._queue)
        print(f"[QUEUE] 📥 Job {job.job_id} queued | queue_size={qsize} | {Path(bulletin_dir).name}")

        # Worker ko trigger karo
        self._trigger.set()

        if block:
            # Caller wait karega — job complete hone tak
            job._event.wait()
            return job.result_path
        else:
            return None

    # ── Worker ───────────────────────────────────────────────────────────────

    def _worker(self):
        """Background thread — queue se ek ek job chalata hai."""
        while True:
            self._trigger.wait()
            self._trigger.clear()

            while True:
                with self._lock:
                    if not self._queue:
                        break
                    job = self._queue.popleft()

                self._current = job
                self._run_job(job)
                self._current = None

    def _run_job(self, job: BuildJob):
        """Ek build job chalao — subprocess ke through (low priority)."""
        job.status = "building"
        streams    = get_active_count()
        print(f"\n[QUEUE] 🔨 Building: {Path(job.bulletin_dir).name} | active_streams={streams}")
        print(f"[QUEUE]    job_id={job.job_id}")

        # process_wrapper ke through chalao taaki nice/cpulimit apply ho
        python = sys.executable
        # cmd    = [
        #     python, str(BASE_DIR / "process_wrapper.py"),
        #     "builder",
        #     job.bulletin_dir,
        #     job.logo_path,
        #     job.intro_path,
        # ]

        cmd = [
            python, str(BASE_DIR / "process_wrapper.py"),
            "builder",
            job.bulletin_dir,
        ]
        if job.logo_path:
            cmd.append(job.logo_path)
        if job.intro_path:
            cmd.append(job.intro_path)

        # Agar process_wrapper nahi hai to directly chalao
        if not (BASE_DIR / "process_wrapper.py").exists():
            cmd = [python, str(BUILDER_SCRIPT),
                   job.bulletin_dir, job.logo_path, job.intro_path]
            print("[QUEUE] ⚠️  process_wrapper.py not found — running builder directly")

        # try:
        #     result = subprocess.run(
        #         cmd,
        #         timeout=BUILD_TIMEOUT,
        #         stdout=sys.stdout,
        #         stderr=sys.stderr,
        #     )

        #     if result.returncode == 0:
        #         # Builder success — video path find karo manifest se
        #         video_path = self._find_video(job.bulletin_dir)
        #         job.status      = "done"
        #         job.result_path = video_path
        #         print(f"[QUEUE] ✅ Done: {Path(job.bulletin_dir).name} → {video_path}")
        #     else:
        #         job.status = "failed"
        #         job.error  = f"exit code {result.returncode}"
        #         print(f"[QUEUE] ❌ Failed: {Path(job.bulletin_dir).name} (exit={result.returncode})")

        # governor/build_queue.py ~line 153 — _run_job mein subprocess.run ke baad

        # try:
        #     result = subprocess.run(
        #         cmd,
        #         timeout=BUILD_TIMEOUT,
        #         stdout=sys.stdout,
        #         stderr=sys.stderr,
        #     )
        #     print(f"[QUEUE] 🔚 process_wrapper exited: returncode={result.returncode}")  # ← ADD
            
        #     if result.returncode == 0:
        #         video_path = self._find_video(job.bulletin_dir)
        #         if not video_path:  # ← ADD: manifest check
        #             print(f"[QUEUE] ⚠️  returncode=0 but final_video not in manifest!")
        #             print(f"[QUEUE]    manifest: {os.path.join(job.bulletin_dir, 'bulletin_manifest.json')}")
        #         job.status      = "done"
        #         job.result_path = video_path
        #         print(f"[QUEUE] ✅ Done: {Path(job.bulletin_dir).name} → {video_path}")
        #     else:
        #         job.status = "failed"
        #         job.error  = f"exit code {result.returncode}"
        #         print(f"[QUEUE] ❌ Failed: returncode={result.returncode}")
        #         # ← ADD: CMD print for debug
        #         print(f"[QUEUE]    CMD was: {' '.join(str(c) for c in cmd)}")

        # except subprocess.TimeoutExpired:
        #     job.status = "failed"
        #     job.error  = f"timeout after {BUILD_TIMEOUT}s"
        #     print(f"[QUEUE] ⏰ Timeout: {Path(job.bulletin_dir).name}")

        # except Exception as e:
        #     job.status = "failed"
        #     job.error  = str(e)
        #     print(f"[QUEUE] ❌ Error: {e}")

        # REPLACE the existing try/except starting at line 189
        import logging
        log = logging.getLogger(__name__)

        stdout_log = os.path.join(job.bulletin_dir, 'builder_stdout.log')
        stderr_log = os.path.join(job.bulletin_dir, 'builder_stderr.log')
        os.makedirs(job.bulletin_dir, exist_ok=True)

        log.info(f"[QUEUE] 🔧 Launching subprocess | job_id={job.job_id} | cmd={' '.join(str(c) for c in cmd)}")
        log.info(f"[QUEUE]    stdout → {stdout_log}")
        log.info(f"[QUEUE]    stderr → {stderr_log}")

        t_start = time.time()
        try:
            _env = os.environ.copy()
            _env['PYTHONIOENCODING'] = 'utf-8'
            _env['PYTHONUTF8'] = '1'

            with open(stdout_log, 'w', encoding='utf-8') as _so, \
                open(stderr_log, 'w', encoding='utf-8') as _se:
                result = subprocess.run(cmd, timeout=BUILD_TIMEOUT,
                                        stdout=_so, stderr=_se, env=_env)
            elapsed = round(time.time() - t_start, 1)
            log.info(f"[QUEUE] 🔚 Subprocess exited | returncode={result.returncode} | elapsed={elapsed}s")

            if result.returncode == 0:
                video_path = self._find_video(job.bulletin_dir)
                manifest_path = os.path.join(job.bulletin_dir, "bulletin_manifest.json")
                if not video_path:
                    log.error(f"[QUEUE] ⚠️ returncode=0 BUT final_video missing in manifest")
                    log.error(f"[QUEUE]    manifest_path={manifest_path} exists={os.path.exists(manifest_path)}")
                    # Dump manifest keys for debug
                    try:
                        import json as _j
                        with open(manifest_path) as _mf:
                            _m = _j.load(_mf)
                        log.error(f"[QUEUE]    manifest_keys={list(_m.keys())}")
                        log.error(f"[QUEUE]    actual_duration_s={_m.get('actual_duration_s')} | target_duration_s={_m.get('target_duration_s')}")
                    except Exception as _me:
                        log.error(f"[QUEUE]    manifest read error: {_me}")
                    # Dump last 30 lines of stderr
                    try:
                        with open(stderr_log) as _se:
                            tail = _se.readlines()[-30:]
                        log.error(f"[QUEUE]    stderr tail:\n{''.join(tail)}")
                    except Exception:
                        pass
                else:
                    log.info(f"[QUEUE] ✅ Done | final_video={video_path}")
                job.status = "done"
                job.result_path = video_path
            else:
                job.status = "failed"
                job.error = f"exit code {result.returncode}"
                log.error(f"[QUEUE] ❌ Subprocess FAILED | returncode={result.returncode} | elapsed={elapsed}s")
                try:
                    with open(stderr_log) as _se:
                        tail = _se.readlines()[-50:]
                    log.error(f"[QUEUE]    stderr tail (last 50 lines):\n{''.join(tail)}")
                except Exception:
                    pass

        except subprocess.TimeoutExpired:
            job.status = "failed"
            job.error = f"timeout after {BUILD_TIMEOUT}s"
            log.error(f"[QUEUE] ⏰ Timeout after {BUILD_TIMEOUT}s | dir={Path(job.bulletin_dir).name}")

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            log.error(f"[QUEUE] ❌ Unexpected error: {e}", exc_info=True)

        finally:
            job._event.set()


    def _find_video(self, bulletin_dir: str) -> Optional[str]:
        """Manifest se final video path nikalo."""
        import json
        manifest_path = os.path.join(bulletin_dir, "bulletin_manifest.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("final_video")
        except Exception:
            return None

    # ── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        with self._lock:
            queued = [
                {"job_id": j.job_id, "dir": Path(j.bulletin_dir).name,
                 "queued_ago": f"{int(time.time() - j.queued_at)}s"}
                for j in self._queue
            ]
        current = None
        if self._current:
            current = {
                "job_id": self._current.job_id,
                "dir":    Path(self._current.bulletin_dir).name,
            }
        return {
            "queue_size":    len(queued),
            "current_build": current,
            "queued_jobs":   queued,
            "active_streams": get_active_count(),
        }

    def print_status(self):
        s = self.get_status()
        print(f"[QUEUE] Queue size : {s['queue_size']}")
        print(f"[QUEUE] Building   : {s['current_build']}")
        print(f"[QUEUE] Streams    : {s['active_streams']}")
        if s["queued_jobs"]:
            for j in s["queued_jobs"]:
                print(f"  • {j['job_id']} | {j['dir']} | queued {j['queued_ago']} ago")


# ── Singleton ─────────────────────────────────────────────────────────────────
#
#  webhook_server.py mein:
#      from build_queue import build_queue_instance
#      video_path = build_queue_instance.submit(bulletin_dir, logo, intro)
#                                                               # [BUILD QUEUE HOOK]
#
build_queue_instance = BuildQueue()


# ── Convenience function — webhook_server mein direct drop-in ─────────────────

def queue_bulletin_build(bulletin_dir: str,
                         logo_path: str,
                         intro_path: str, ticker_text='') -> Optional[str]:
    """
    webhook_server.py mein build_bulletin_video() ki jagah yeh use karo.

    PEHLE:
        video_path = build_bulletin_video(bulletin_dir, logo_path, intro_path)

    BAAD (sirf yeh ek line change):
        video_path = queue_bulletin_build(bulletin_dir, logo_path, intro_path)
    """
    return build_queue_instance.submit(bulletin_dir, logo_path, intro_path, ticker_text=ticker_text, block=True)



def get_queue_status() -> dict:
    return build_queue_instance.get_status()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        build_queue_instance.print_status()
    else:
        print("Usage: python build_queue.py [status]")