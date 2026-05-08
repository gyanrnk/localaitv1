



import os 
import re
import time
import threading
import subprocess
from pathlib import Path
from datetime import datetime
import pytz
import requests
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
import platform

load_dotenv()

# ── [STREAM REGISTRY HOOK] ────────────────────────────────────────────────────
try:
    from governor.stream_registry import stream_up, stream_down
    _REGISTRY_OK = True
except ImportError:
    _REGISTRY_OK = False
    def stream_up(label, pid=None): pass
    def stream_down(label): pass


INTRO_SEC = 20

# ── Per-channel bulletin directories ─────────────────────────────────────────
if platform.system() == "Windows":
    _BASE = os.getenv("WATCH_DIR_BASE", r"C:\\Users\\Gyanaranjan kabi\\Desktop\\temp_copy\\outputs\\bulletins")
else:
    _BASE = os.getenv("WATCH_DIR_BASE", "/root/localaitv1/outputs/bulletins")

def _wdir(name):
    return os.getenv(f"WATCH_DIR_{name.upper()}", f"{_BASE}/{name}")

RTMPS_URL = "rtmps://a.rtmps.youtube.com/live2"
IST       = pytz.timezone("Asia/Kolkata")
YT_API_KEY  = os.getenv("YT_DATA_API_KEY")
YT_VIDEO_ID = os.getenv("YT_VIDEO_ID")

MAX_BULLETINS_IN_ROTATION = 30
VIEWER_COUNT_FILE         = Path("yt_viewers.txt")
VIEWER_COUNT_FILE_FFMPEG  = "yt_viewers.txt"
IST_TIME_FILE             = Path("ist_time.txt")
IST_TIME_FILE_FFMPEG      = "ist_time.txt"
VIEWER_FETCH_INTERVAL     = 30
DRY_RUN      = False
STREAM_COUNT = int(os.getenv("STREAM_COUNT", "3"))

# ── Channel definitions — add new channels here only ─────────────────────────
CHANNEL_DEFS = [
    {"name": "Khammam",    "label": "LocalAiTV",    "key_env": "YT_STREAM_KEY",            "concat": Path("concat_list_p1.txt")},
    {"name": "Kurnool",    "label": "KurnoolTV",    "key_env": "YT_STREAM_KEY_KURNOOL",    "concat": Path("concat_list_p2.txt")},
    {"name": "Karimnagar", "label": "KarimnagarTV", "key_env": "YT_STREAM_KEY_KARIMNAGAR", "concat": Path("concat_list_p3.txt")},
    {"name": "Anatpur",    "label": "AnatpurTV",    "key_env": "YT_STREAM_KEY_ANATPUR",    "concat": Path("concat_list_p4.txt")},
    {"name": "Kakinada",   "label": "KakinadaTV",   "key_env": "YT_STREAM_KEY_KAKINADA",   "concat": Path("concat_list_p5.txt")},
    {"name": "Nalore",     "label": "NaloreTV",     "key_env": "YT_STREAM_KEY_NALORE",     "concat": Path("concat_list_p6.txt")},
    {"name": "Tirupati",   "label": "TirupatiTV",   "key_env": "YT_STREAM_KEY_TIRUPATI",   "concat": Path("concat_list_p7.txt")},
]
for _ch in CHANNEL_DEFS:
    _ch["watch_dir"] = _wdir(_ch["name"])
    _ch["stream_key"] = os.getenv(_ch["key_env"])

INJECT_MAX_SEC = 5 * 60  # 5 minutes

# ── S3 Config ─────────────────────────────────────────────────────────────────
S3_BUCKET = os.getenv("S3_BUCKET_NAME_M", "localaitv1-689186650531-ap-south-2-an")
S3_REGION = os.getenv("AWS_REGION_M", "ap-south-2")

VEGE_PREFIX     = "vegetableprices/outputs/4/"
TRAIN_PREFIX    = "trainroutes/outputs/"
BIRTHDAY_PREFIX = "birthdays/outputs/"
MARRIAGE_PREFIX = "marriages/outputs/"

INJECT_CACHE_DIR = Path("s3_inject_cache")
INJECT_CACHE_DIR.mkdir(exist_ok=True)

_train_rotation_idx = 0

# ── Fixed daily broadcast schedule (IST) ─────────────────────────────────────
DAILY_SCHEDULE = [
    ("00:00","news"),("00:10","birthday"),("00:15","news"),("00:25","vege"),
    ("00:30","news"),("00:40","train"),   ("00:45","news"),("00:55","marriage"),
    ("01:00","news"),("01:10","birthday"),("01:15","news"),("01:25","vege"),
    ("01:30","news"),("01:40","train"),   ("01:45","news"),("01:55","marriage"),
    ("02:00","news"),("02:10","birthday"),("02:15","news"),("02:25","vege"),
    ("02:30","news"),("02:40","train"),   ("02:45","news"),("02:55","marriage"),
    ("03:00","news"),("03:10","birthday"),("03:15","news"),("03:25","vege"),
    ("03:30","news"),("03:40","train"),   ("03:45","news"),("03:55","marriage"),
    ("04:00","news"),("04:10","birthday"),("04:15","news"),("04:25","vege"),
    ("04:30","news"),("04:40","train"),   ("04:45","news"),("04:55","marriage"),
    ("05:00","news"),("05:10","birthday"),("05:15","news"),("05:25","vege"),
    ("05:30","news"),("05:40","train"),   ("05:45","news"),("05:55","marriage"),
    ("06:00","news"),("06:10","birthday"),("06:15","news"),("06:25","vege"),
    ("06:30","news"),("06:40","train"),   ("06:45","news"),("06:55","marriage"),
    ("07:00","news"),("07:10","birthday"),("07:15","news"),("07:25","vege"),
    ("07:30","news"),("07:40","train"),   ("07:45","news"),("07:55","marriage"),
    ("08:00","news"),("08:10","birthday"),("08:15","news"),("08:25","vege"),
    ("08:30","news"),("08:40","train"),   ("08:45","news"),("08:55","marriage"),
    ("09:00","news"),("09:10","birthday"),("09:15","news"),("09:25","vege"),
    ("09:30","news"),("09:40","train"),   ("09:45","news"),("09:55","marriage"),
    ("10:00","news"),("10:10","birthday"),("10:15","news"),("10:25","vege"),
    ("10:30","news"),("10:40","train"),   ("10:45","news"),("10:55","marriage"),
    ("11:00","news"),("11:10","birthday"),("11:15","news"),("11:25","vege"),
    ("11:30","news"),("11:40","train"),   ("11:45","news"),("11:55","marriage"),
    ("12:00","news"),("12:10","birthday"),("12:15","news"),("12:25","vege"),
    ("12:30","news"),("12:40","train"),   ("12:45","news"),("12:55","marriage"),
    ("13:00","news"),("13:10","birthday"),("13:15","news"),("13:25","vege"),
    ("13:30","news"),("13:40","train"),   ("13:45","news"),("13:55","marriage"),
    ("14:00","news"),("14:10","birthday"),("14:15","news"),("14:25","vege"),
    ("14:30","news"),("14:40","train"),   ("14:45","news"),("14:55","marriage"),
    ("15:00","news"),("15:10","birthday"),("15:15","news"),("15:25","vege"),
    ("15:30","news"),("15:40","train"),   ("15:45","news"),("15:55","marriage"),
    ("16:00","news"),("16:10","birthday"),("16:15","news"),("16:25","vege"),
    ("16:30","news"),("16:40","train"),   ("16:45","news"),("16:55","marriage"),
    ("17:00","news"),("17:10","birthday"),("17:15","news"),("17:25","vege"),
    ("17:30","news"),("17:40","train"),   ("17:45","news"),("17:55","marriage"),
    ("18:00","news"),("18:10","birthday"),("18:15","news"),("18:25","vege"),
    ("18:30","news"),("18:40","train"),   ("18:45","news"),("18:55","marriage"),
    ("19:00","news"),("19:10","birthday"),("19:15","news"),("19:25","vege"),
    ("19:30","news"),("19:40","train"),   ("19:45","news"),("19:55","marriage"),
    ("20:00","news"),("20:10","birthday"),("20:15","news"),("20:25","vege"),
    ("20:30","news"),("20:40","train"),   ("20:45","news"),("20:55","marriage"),
    ("21:00","news"),("21:10","birthday"),("21:15","news"),("21:25","vege"),
    ("21:30","news"),("21:40","train"),   ("21:45","news"),("21:55","marriage"),
    ("22:00","news"),("22:10","birthday"),("22:15","news"),("22:25","vege"),
    ("22:30","news"),("22:40","train"),   ("22:45","news"),("22:55","marriage"),
    ("23:00","news"),("23:10","birthday"),("23:15","news"),("23:25","vege"),
    ("23:30","news"),("23:40","train"),   ("23:45","news"),("23:55","marriage"),
]

_played_slots: set = set()
_slot_lock = threading.Lock()
_stop_event = threading.Event()


# ── Helpers ───────────────────────────────────────────────────────────────────

def kill_ffmpeg():
    if platform.system() == "Windows":
        subprocess.run(["taskkill","/F","/IM","ffmpeg.exe"], capture_output=True)
    else:
        subprocess.run(["pkill","-f","ffmpeg"], capture_output=True)


def debug(msg):
    print(f"[{datetime.now(IST).strftime('%H:%M:%S')}] {msg}")


def get_all_bulletins(folder):
    p = Path(folder)
    if not p.exists():
        debug(f"Folder missing: {folder}")
        return []

    bulletin_dirs = [
        d for d in p.iterdir()
        if d.is_dir() and d.name.startswith("bul_")
    ]

    bulletin_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)

    files = []
    for bul in bulletin_dirs[:MAX_BULLETINS_IN_ROTATION]:
        # Only accept the exact final video: <bul_name>/<bul_name>.mp4
        # Skip intermediates like _staging.mp4, _tickered.mp4, _tmp.mp4
        final = bul / f"{bul.name}.mp4"
        if final.exists() and final.stat().st_size > 100_000:
            files.append(final)

    return files


# ── S3 helpers ────────────────────────────────────────────────────────────────

def _s3_client():
    return boto3.client("s3", region_name=S3_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID_M"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY_M"))


def _get_video_duration(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",str(path)],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _trim_to_max(path: Path, max_sec: int = INJECT_MAX_SEC) -> Path:
    if _get_video_duration(path) <= max_sec:
        return path
    trimmed = path.parent / (path.stem + f"_trim{max_sec}s.mp4")
    if trimmed.exists() and trimmed.stat().st_size > 100_000:
        return trimmed
    debug(f"Trimming {path.name} to {max_sec}s...")
    r = subprocess.run(["ffmpeg","-y","-i",str(path),"-t",str(max_sec),"-c","copy",str(trimmed)],
        capture_output=True)
    return trimmed if r.returncode == 0 else path


def _download_if_needed(s3_key: str, apply_trim: bool = False):
    local     = INJECT_CACHE_DIR / Path(s3_key).name
    gop_fixed = INJECT_CACHE_DIR / (Path(s3_key).stem + "_gop.mp4")

    if not (local.exists() and local.stat().st_size > 100_000):
        try:
            _s3_client().download_file(S3_BUCKET, s3_key, str(local))
            debug(f"Downloaded: {local.name}")
            if gop_fixed.exists():
                gop_fixed.unlink()
        except (BotoCoreError, ClientError) as e:
            debug(f"S3 download failed [{s3_key}]: {e}")
            for f in [gop_fixed, local]:
                if f.exists() and f.stat().st_size > 100_000:
                    return _trim_to_max(f) if apply_trim else f
            return None
    else:
        if gop_fixed.exists() and gop_fixed.stat().st_size > 100_000:
            return _trim_to_max(gop_fixed) if apply_trim else gop_fixed

    debug(f"GOP fix: {local.name}...")
    r = subprocess.run([
        "ffmpeg","-y","-i",str(local),
        "-c:v","libx264","-preset","veryfast","-profile:v","high","-level","4.0",
        "-pix_fmt","yuv420p","-b:v","4500k","-maxrate","4500k","-bufsize","9000k",
        "-g","50","-keyint_min","50","-sc_threshold","0","-r","25",
        "-video_track_timescale","12800",
        "-vf","scale=1920:1080:force_original_aspect_ratio=decrease,"
              "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:a","aac","-ar","44100","-ac","2",str(gop_fixed)
    ], capture_output=True)
    out = gop_fixed if r.returncode == 0 else local
    if r.returncode != 0:
        debug(f"GOP fix failed: {r.stderr.decode()[-300:]}")
    return _trim_to_max(out) if apply_trim else out


def fetch_latest_vege():
    try:
        res  = _s3_client().list_objects_v2(Bucket=S3_BUCKET, Prefix=VEGE_PREFIX)
        mp4s = [o for o in res.get("Contents", []) if o["Key"].endswith(".mp4") and o["Size"] > 0]
        if not mp4s:
            return None

        latest = max(mp4s, key=lambda o: o["LastModified"])
        debug(f"Vege: {Path(latest['Key']).name}")

        return _download_if_needed(latest["Key"], apply_trim=True)

    except (BotoCoreError, ClientError) as e:
        debug(f"Vege fetch error: {e}")
        return None


def _natural_sort_key(key):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\\d+)", key)]


def fetch_train_clips():
    try:
        res  = _s3_client().list_objects_v2(Bucket=S3_BUCKET, Prefix=TRAIN_PREFIX)
        keys = sorted([o["Key"] for o in res.get("Contents",[])
                       if o["Key"].endswith(".mp4") and o["Size"]>0], key=_natural_sort_key)
        clips = [c for c in (_download_if_needed(k, apply_trim=True) for k in keys) if c]
        debug(f"Train clips: {len(clips)}")
        return clips
    except (BotoCoreError, ClientError) as e:
        debug(f"Train fetch error: {e}"); return []


def fetch_todays_birthday():
    try:
        res  = _s3_client().list_objects_v2(Bucket=S3_BUCKET, Prefix=BIRTHDAY_PREFIX)
        mp4s = [o for o in res.get("Contents", []) if o["Key"].endswith(".mp4") and o["Size"] > 0]
        if not mp4s:
            return None

        latest = max(mp4s, key=lambda o: o["LastModified"])
        debug(f"Birthday: {Path(latest['Key']).name}")

        return _download_if_needed(latest["Key"], apply_trim=True)

    except (BotoCoreError, ClientError) as e:
        debug(f"Birthday fetch error: {e}")
        return None


def fetch_todays_marriage():
    try:
        res  = _s3_client().list_objects_v2(Bucket=S3_BUCKET, Prefix=MARRIAGE_PREFIX)
        mp4s = [o for o in res.get("Contents", []) if o["Key"].endswith(".mp4") and o["Size"] > 0]
        if not mp4s:
            return None

        latest = max(mp4s, key=lambda o: o["LastModified"])
        debug(f"Marriage: {Path(latest['Key']).name}")

        return _download_if_needed(latest["Key"], apply_trim=True)

    except (BotoCoreError, ClientError) as e:
        debug(f"Marriage fetch error: {e}")
        return None


SEGMENT_FETCHERS = {
    "birthday": fetch_todays_birthday,
    "vege":     fetch_latest_vege,
    "marriage": fetch_todays_marriage,
}


# ── Schedule checker ──────────────────────────────────────────────────────────

def get_pending_slot():
    now      = datetime.now(IST)
    date_str = now.strftime("%Y-%m-%d")
    hhmm     = now.strftime("%H:%M")

    with _slot_lock:
        for slot_time, seg_type in DAILY_SCHEDULE:
            play_key = f"{date_str}_{slot_time}"
            if play_key in _played_slots or hhmm != slot_time:
                continue

            debug(f"Schedule slot hit: {slot_time} -> {seg_type}")
            _played_slots.add(play_key)

            if seg_type == "news":
                return ("news", None)

            if seg_type == "train":
                clips = fetch_train_clips()
                if clips: return ("train", clips)
                vege = fetch_latest_vege()
                if vege: return ("vege", vege)
                return ("news", None)

            if seg_type == "vege":
                vege = fetch_latest_vege()
                if vege: return ("vege", vege)
                clips = fetch_train_clips()
                if clips: return ("train", clips)
                return ("news", None)

            fetcher = SEGMENT_FETCHERS.get(seg_type)
            path    = fetcher() if fetcher else None
            if path: return (seg_type, path)
            vege = fetch_latest_vege()
            if vege: return ("vege", vege)
            clips = fetch_train_clips()
            if clips: return ("train", clips)
            return ("news", None)

    return None


def reset_played_slots_at_midnight():
    while not _stop_event.is_set():
        now = datetime.now(IST)
        secs = (24 - now.hour)*3600 - now.minute*60 - now.second
        _stop_event.wait(secs)
        with _slot_lock:
            _played_slots.clear()
        debug("Midnight reset — schedule cleared")


# ── Concat list builder ───────────────────────────────────────────────────────

def build_concat_list(bulletins, concat_path, label="", inject_type=None, inject_payload=None):
    global _train_rotation_idx
    if not bulletins:
        debug(f"[{label}] No bulletins — skipping concat build")
        return concat_path

    vege_path   = fetch_latest_vege()
    train_clips = [t for t in fetch_train_clips() if t]
    lines       = []

    if inject_type and inject_type != "news" and inject_payload:
        if inject_type == "train" and isinstance(inject_payload, list):
            clip = inject_payload[_train_rotation_idx % len(inject_payload)]
            _train_rotation_idx += 1
            lines.append(f"file \'{str(clip)}\'")
            debug(f"[{label}] Inject train: {clip.name}")
        elif isinstance(inject_payload, Path):
            lines.append(f"file \'{str(inject_payload)}\'")
            debug(f"[{label}] Inject {inject_type}: {inject_payload.name}")

    for i, news in enumerate(bulletins):
        lines.append(f"file \'{str(news)}\'")
        if i % 2 == 0 and vege_path:
            lines.append(f"file \'{str(vege_path)}\'")
        elif i % 2 == 1 and train_clips:
            t = train_clips[_train_rotation_idx % len(train_clips)]
            _train_rotation_idx += 1
            lines.append(f"file \'{str(t)}\'")

    repeated = lines * 10
    # concat_path.write_text("\\n".join(repeated) + "\\n", encoding="utf-8")
    concat_path.write_text("\n".join(repeated) + "\n", encoding="utf-8")
    debug(f"[{label}] {concat_path.name}: {len(bulletins)} bulletins | {len(repeated)} entries")
    return concat_path


# ── Background threads ────────────────────────────────────────────────────────

def _fetch_viewer_loop():
    while not _stop_event.is_set():
        try:
            if YT_API_KEY and YT_VIDEO_ID:
                r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                    params={"part":"liveStreamingDetails","id":YT_VIDEO_ID,"key":YT_API_KEY},
                    timeout=10)
                items = r.json().get("items",[])
                count = items[0].get("liveStreamingDetails",{}).get("concurrentViewers","–") if items else "–"
            else:
                count = "–"
            VIEWER_COUNT_FILE.write_text(str(count), encoding="utf-8")
        except Exception as e:
            debug(f"viewer fetch error: {e}")
            try: VIEWER_COUNT_FILE.write_text("–", encoding="utf-8")
            except: pass
        _stop_event.wait(VIEWER_FETCH_INTERVAL)


def _fetch_time_loop():
    while not _stop_event.is_set():
        try:
            IST_TIME_FILE.write_text(datetime.now(IST).strftime("%H:%M:%S") + " IST", encoding="utf-8")
        except: pass
        time.sleep(1)


def start_background_threads():
    _stop_event.clear()
    VIEWER_COUNT_FILE.write_text("– watching", encoding="utf-8")
    IST_TIME_FILE.write_text("--:--:-- IST", encoding="utf-8")
    threading.Thread(target=_fetch_viewer_loop,             daemon=True).start()
    threading.Thread(target=_fetch_time_loop,               daemon=True).start()
    threading.Thread(target=reset_played_slots_at_midnight, daemon=True).start()
    debug("Background threads started")


def stop_background_threads():
    _stop_event.set()
    debug("Background threads stopped")


# ── Overlay ───────────────────────────────────────────────────────────────────

def prepare_overlay():
    import shutil
    font_src = Path("NotoSansTelugu-VariableFont_wdth,wght.ttf")
    font_tmp = Path("NotoTelugu.ttf")
    if not font_tmp.exists() and font_src.exists():
        shutil.copy2(font_src, font_tmp)
    Path("yt_overlay.filter").write_text(
        "drawtext=fontfile=NotoTelugu.ttf:"
        f"textfile={VIEWER_COUNT_FILE_FFMPEG}:reload=1:"
        f"enable=\'gte(t,{INTRO_SEC})\':fontcolor=white:fontsize=30:"
        "x=30:y=30:box=1:boxcolor=black@0.5:boxborderw=8",
        encoding="utf-8"
    )


# ── FFmpeg launcher ───────────────────────────────────────────────────────────

STREAM_MODE = os.getenv("STREAM_MODE", "copy").lower()


def start_ffmpeg_concat(stream_key, label, concat_path):
    if STREAM_MODE == "copy":
        cmd = ["ffmpeg","-re","-f","concat","-safe","0","-i",str(concat_path),
               "-c","copy","-f","flv",
               "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","30",
               f"{RTMPS_URL}/{stream_key}"]
    else:
        cmd = ["ffmpeg","-re","-f","concat","-safe","0","-i",str(concat_path),
               "-filter_script:v","yt_overlay.filter",
               "-c:v","libx264","-preset","veryfast","-profile:v","high","-level","4.0",
               "-pix_fmt","yuv420p","-b:v","4500k","-maxrate","4500k","-bufsize","9000k",
               "-r","25","-g","50","-keyint_min","50","-sc_threshold","0",
               "-c:a","copy","-f","flv",
               "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","30",
               f"{RTMPS_URL}/{stream_key}"]

    if DRY_RUN:
        debug(f"DRY_RUN [{label}]: {cmd[-6:]}"); return None

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    debug(f"[{label}] ffmpeg PID={proc.pid} | {concat_path.name}")
    stream_up(label, proc.pid)
    return proc


def monitor_ffmpeg(process, label=""):
    def _reader():
        fc, last = 0, []
        for line in process.stderr:
            line = line.strip()
            if not line: continue
            last.append(line)
            if len(last) > 10: last.pop(0)
            if line.startswith("frame="):
                fc += 1
                if fc % 100 == 0: debug(f"[{label}] {line}")
            elif any(x in line.lower() for x in ["error","invalid","failed","broken","refused","timeout"]):
                if "Failed to update header" not in line:
                    debug(f"[{label}] FFMPEG_ERR: {line}")
            elif any(x in line.lower() for x in ["opening","stream #","encoder"]):
                debug(f"[{label}] {line}")
        process.wait()
        rc = process.returncode
        if rc == 0:
            debug(f"[{label}] ffmpeg exited cleanly")
        else:
            debug(f"[{label}] ffmpeg DIED (exit={rc})")
            for l in last: debug(f"[{label}]  >> {l}")
    threading.Thread(target=_reader, daemon=True).start()


def _exit_reason(rc):
    return {1:"General error",255:"RTMP refused/bad key",-15:"SIGTERM",-9:"SIGKILL",
            4294957243:"Network aborted",-10053:"WSAECONNABORTED"}.get(rc, f"exit={rc}")


# ── Stream launch / teardown ──────────────────────────────────────────────────

# def _launch_streams(inject_type=None, inject_payload=None):
#     """
#     LocalAiTV (p1)  <-  bulletins/Khammam  ->  concat_list_p1.txt  ->  YT_STREAM_KEY
#     KurnoolTV (p2)  <-  bulletins/Kurnool   ->  concat_list_p2.txt  ->  YT_STREAM_KEY_KURNOOL
#     """
#     bk = get_all_bulletins(WATCH_DIR_KHAMMAM)
#     bn = get_all_bulletins(WATCH_DIR_KURNOOL)
#     if not bk: debug("[LocalAiTV] No Khammam bulletins")
#     if not bn: debug("[KurnoolTV] No Kurnool bulletins")

#     prepare_overlay()

#     build_concat_list(bk, CONCAT_LIST_P1, "LocalAiTV", inject_type, inject_payload)
#     if STREAM_COUNT >= 2 and STREAM_KEY_KURNOOL:
#         build_concat_list(bn, CONCAT_LIST_P2, "KurnoolTV", inject_type, inject_payload)

#     p1 = start_ffmpeg_concat(STREAM_KEY, "LocalAiTV", CONCAT_LIST_P1) if bk else None
#     p2 = (start_ffmpeg_concat(STREAM_KEY_KURNOOL, "KurnoolTV", CONCAT_LIST_P2)
#           if (STREAM_COUNT >= 2 and STREAM_KEY_KURNOOL and bn) else None)

#     if p1: monitor_ffmpeg(p1, "LocalAiTV")
#     if p2: monitor_ffmpeg(p2, "KurnoolTV")
#     return p1, p2, bk, bn

def _launch_streams(inject_type=None, inject_payload=None):
    MIN_BULLETINS = 5

    def _with_fallback(folder):
        primary = get_all_bulletins(folder)
        if len(primary) >= MIN_BULLETINS:
            return primary
        fallback = get_all_bulletins(_BASE)
        seen, merged = set(), []
        for f in primary + fallback:
            if str(f) not in seen:
                seen.add(str(f)); merged.append(f)
        return merged

    active = CHANNEL_DEFS[:STREAM_COUNT]
    procs  = []
    prepare_overlay()

    for i, ch in enumerate(active):
        bulletins = _with_fallback(ch["watch_dir"])
        if not bulletins:
            debug(f"[{ch['label']}] No bulletins")
        inj_t = inject_type    if i == 0 else None
        inj_p = inject_payload if i == 0 else None
        build_concat_list(bulletins, ch["concat"], ch["label"], inj_t, inj_p)
        p = start_ffmpeg_concat(ch["stream_key"], ch["label"], ch["concat"]) \
            if (bulletins and ch["stream_key"]) else None
        if p:
            monitor_ffmpeg(p, ch["label"])
        procs.append(p)

    return procs


def _terminate_streams(procs):
    for proc, ch in zip(procs, CHANNEL_DEFS):
        if proc and proc.poll() is None:
            try: proc.terminate(); stream_down(ch["label"])
            except: pass


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_streamer():
    kill_ffmpeg()
    time.sleep(2)
    debug("=== Streamer Started ===")
    for ch in CHANNEL_DEFS[:STREAM_COUNT]:
        debug(f"  {ch['label']} ← {ch['watch_dir']}")

    if not CHANNEL_DEFS[0]["stream_key"]:
        raise RuntimeError("YT_STREAM_KEY not set!")

    start_background_threads()

    active     = CHANNEL_DEFS[:STREAM_COUNT]
    procs      = [None] * STREAM_COUNT
    last_buls  = [[] for _ in active]
    last_check = time.time()
    inject_type = inject_payload = None

    try:
        while True:
            cur_buls = [get_all_bulletins(ch["watch_dir"]) or get_all_bulletins(_BASE)
                        for ch in active]

            if not any(cur_buls):
                debug("No bulletins in any folder — 10s wait...")
                time.sleep(10); continue

            procs      = _launch_streams(inject_type, inject_payload)
            last_buls  = cur_buls
            last_check = time.time()
            inject_type = inject_payload = None

            while True:
                time.sleep(10)

                pending = get_pending_slot()
                if pending:
                    seg_type, payload = pending
                    if seg_type == "news":
                        debug("News slot — silent refresh")
                        last_buls  = [get_all_bulletins(ch["watch_dir"]) or get_all_bulletins(_BASE)
                                      for ch in active]
                        last_check = time.time()
                    else:
                        debug(f"Slot [{seg_type}] — restarting to inject")
                        _terminate_streams(procs)
                        procs = [None] * STREAM_COUNT
                        inject_type = seg_type; inject_payload = payload
                        break

                if time.time() - last_check > 60:
                    new_buls = [get_all_bulletins(ch["watch_dir"]) or get_all_bulletins(_BASE)
                                for ch in active]
                    if new_buls != last_buls:
                        debug("New bulletins — restarting streams")
                        _terminate_streams(procs)
                        procs = [None] * STREAM_COUNT; break
                    last_check = time.time()

                # Crash recovery per channel
                for i, (proc, ch) in enumerate(zip(procs, active)):
                    if proc and proc.poll() is not None:
                        debug(f"{ch['label']} DOWN ({_exit_reason(proc.returncode)}) — restart in 3s")
                        stream_down(ch["label"]); time.sleep(3)
                        if last_buls[i] and ch["stream_key"]:
                            procs[i] = start_ffmpeg_concat(ch["stream_key"], ch["label"], ch["concat"])
                            if procs[i]: monitor_ffmpeg(procs[i], ch["label"])

                if all(p is None or p.poll() is not None for p in procs):
                    debug("All streams down — outer relaunch"); break

    except KeyboardInterrupt:
        debug("Stopped by user")
        _terminate_streams(procs)
    finally:
        for ch in CHANNEL_DEFS:
            stream_down(ch["label"])
        stop_background_threads(); kill_ffmpeg()
        debug("=== Streamer Stopped ===")


if __name__ == "__main__":
    run_streamer()
