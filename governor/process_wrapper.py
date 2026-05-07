


"""
process_wrapper.py
──────────────────
OS-level priority manager. Streamer aur builder ko alag CPU priority
ke saath launch karta hai. Existing files (yt_streamer.py, video_builder.py)
mein koi changes nahi.

Usage:
    # Streamer start karo (high priority)
    python process_wrapper.py streamer

    # Builder start karo (low priority)
    python process_wrapper.py builder  <bulletin_dir> [logo] [intro]

    # Direct import karke bhi use kar sakte ho
    from process_wrapper import launch_streamer, launch_builder
"""

import os
import sys
import platform
import subprocess
import signal
import time
from pathlib import Path


# ── Priority Settings ─────────────────────────────────────────────────────────
#
#   nice values (Linux only):
#     -20 = highest priority  |  +19 = lowest priority
#     Default process = 0
#
#   Streamer ko high priority — agar CPU tight ho to streamer pehle milega
#   Builder ko low priority  — encoding slow chalegi lekin stream buffer nahi hoga
#
STREAMER_NICE   = -5    # High priority  (stream kabhi buffer nahi hoga)
BUILDER_NICE    = 15    # Low priority   (encoding slow chalegi, koi dikkat nahi)

#   cpulimit: builder ko maximum kitna CPU dena hai (percentage)
#   2 streams chal rahe hain to builder ko ~35% se zyada nahi dena
#   0 = disabled (cpulimit use nahi hoga)
#
BUILDER_CPU_LIMIT = 0 # percent — 0 to disable

# ── Script Paths ──────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
STREAMER_SCRIPT = BASE_DIR.parent / "yt_streamer.py"
# BUILDER_SCRIPT  = BASE_DIR / "video_builder.py"
BUILDER_SCRIPT = BASE_DIR.parent / "video_builder.py"


IS_LINUX   = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _cpulimit_available() -> bool:
    """Check karo ki cpulimit installed hai ya nahi."""
    try:
        result = subprocess.run(
            ["which", "cpulimit"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return result.returncode == 0
    except Exception:
        return False


def _set_nice(pid: int, nice_value: int):
    """
    Running process ki nice value set karo.
    Linux only — Windows pe silently skip hoga.
    """
    if not IS_LINUX:
        return
    try:
        os.setpriority(os.PRIO_PROCESS, pid, nice_value)
        print(f"  [WRAPPER] PID {pid} → nice={nice_value}")
    except PermissionError:
        # nice -5 (negative) ke liye sudo chahiye hota hai
        # Agar permission nahi hai to sirf positive nice set karo
        if nice_value < 0:
            print(f"  [WRAPPER] ⚠️  nice={nice_value} ke liye sudo chahiye — skipping")
        else:
            print(f"  [WRAPPER] ⚠️  nice set failed for PID {pid}")
    except Exception as e:
        print(f"  [WRAPPER] ⚠️  nice error: {e}")


def _build_builder_cmd(args: list) -> list:
    """
    Builder command banao — taskset se cores 4-7 pe pin karo.
    """
    python      = sys.executable
    script_args = [str(BUILDER_SCRIPT)] + args

    if IS_LINUX:
        cmd = [
            "taskset", "-c", "4,5,6,7",
            python, *script_args
        ]
        print(f"  [WRAPPER] taskset cores=4,5,6,7 applied on builder")
    else:
        cmd = [python, *script_args]

    return cmd


# ── Public API ────────────────────────────────────────────────────────────────

def launch_streamer() -> subprocess.Popen:
    """
    yt_streamer.py ko high CPU priority ke saath launch karo.
    Returns: Popen process handle
    """
    python = sys.executable
    cmd    = [python, str(STREAMER_SCRIPT)]

    print(f"[WRAPPER] 🔴 Streamer launch ho raha hai (nice={STREAMER_NICE})...")

    # Windows: ABOVE_NORMAL_PRIORITY_CLASS | Linux: nice value baad mein set hogi
    popen_kwargs = dict(stdout=sys.stdout, stderr=sys.stderr)
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.ABOVE_NORMAL_PRIORITY_CLASS
        print(f"[WRAPPER] 🪟 Windows: ABOVE_NORMAL_PRIORITY_CLASS applied on streamer")

    process = subprocess.Popen(cmd, **popen_kwargs)

    # Linux: nice value set karo streamer ke liye
    if IS_LINUX:
        _set_nice(process.pid, STREAMER_NICE)

    print(f"[WRAPPER] ✅ Streamer started | PID={process.pid}")
    return process


def launch_builder(bulletin_dir: str = None,
                   logo_path: str = None,
                   intro_path: str = None) -> subprocess.Popen:
    """
    video_builder.py ko low CPU priority + cpulimit ke saath launch karo.

    Parameters:
        bulletin_dir : bulletin directory path (optional — latest auto-detect hogi)
        logo_path    : logo file path (optional)
        intro_path   : intro video path (optional)

    Returns: Popen process handle
    """
    args = []
    if bulletin_dir:
        args.append(bulletin_dir)
    if logo_path:
        args.append(logo_path)
    if intro_path:
        args.append(intro_path)

    cmd = _build_builder_cmd(args)

    print(f"[WRAPPER] 🔨 Builder launch ho raha hai (nice={BUILDER_NICE}, cpu_limit={BUILDER_CPU_LIMIT}%)...")
    print(f"[WRAPPER]    CMD: {' '.join(cmd[:4])}...")

    # Windows: BELOW_NORMAL_PRIORITY_CLASS | Linux: nice value baad mein set hogi
    popen_kwargs = dict(stdout=sys.stdout, stderr=sys.stderr)
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS
        print(f"[WRAPPER] 🪟 Windows: BELOW_NORMAL_PRIORITY_CLASS applied on builder")

    process = subprocess.Popen(cmd, **popen_kwargs)

    # Linux: nice value set karo — builder ko low priority
    if IS_LINUX:
        _set_nice(process.pid, BUILDER_NICE)

    print(f"[WRAPPER] ✅ Builder started | PID={process.pid}")
    return process


def run_both(bulletin_dir: str = None,
             logo_path: str = None,
             intro_path: str = None):
    """
    Dono ko saath launch karo — streamer high priority, builder low priority.
    Streamer crash kare to restart kare. Builder khatam ho to exit.
    """
    print("[WRAPPER] 🚀 Streamer + Builder dono start ho rahe hain...")

    streamer_proc = launch_streamer()
    time.sleep(3)  # Streamer ko settle hone do pehle
    builder_proc  = launch_builder(bulletin_dir, logo_path, intro_path)

    def _handle_signal(sig, frame):
        print("\n[WRAPPER] 🛑 Stop signal received...")
        if streamer_proc.poll() is None:
            streamer_proc.terminate()
        if builder_proc.poll() is None:
            builder_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Monitor loop
    while True:
        time.sleep(5)

        # Builder khatam? — exit karo
        if builder_proc.poll() is not None:
            rc = builder_proc.returncode
            print(f"[WRAPPER] ✅ Builder khatam hua (exit={rc})")
            break

        # Streamer crash? — restart karo
        if streamer_proc.poll() is not None:
            rc = streamer_proc.returncode
            print(f"[WRAPPER] 💀 Streamer crash hua (exit={rc}) — 5s mein restart...")
            time.sleep(5)
            streamer_proc = launch_streamer()

    print("[WRAPPER] 🏁 Done.")


# ── CLI Entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python process_wrapper.py streamer")
        print("  python process_wrapper.py builder [bulletin_dir] [logo] [intro]")
        print("  python process_wrapper.py both    [bulletin_dir] [logo] [intro]")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "streamer":
        proc = launch_streamer()
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()

    elif mode == "builder":
        bdir  = sys.argv[2] if len(sys.argv) > 2 else None
        logo  = sys.argv[3] if len(sys.argv) > 3 else None
        intro = sys.argv[4] if len(sys.argv) > 4 else None
        proc  = launch_builder(bdir, logo, intro)
        try:
            rc = proc.wait()
            sys.exit(rc)          # ← video_builder ka exit code parent ko do
        except KeyboardInterrupt:
            proc.terminate()
            sys.exit(1)

    elif mode == "both":
        bdir  = sys.argv[2] if len(sys.argv) > 2 else None
        logo  = sys.argv[3] if len(sys.argv) > 3 else None
        intro = sys.argv[4] if len(sys.argv) > 4 else None
        run_both(bdir, logo, intro)

    else:
        print(f"❌ Unknown mode: {mode}")
        sys.exit(1)