



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
    _BASE = os.getenv("WATCH_DIR_BASE", "/app/outputs/bulletins")
    if not os.path.isdir(_BASE):
        _BASE = os.getenv("WATCH_DIR_BASE", "/root/localaitv1/localaitv1/outputs/bulletins")

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
    {"name": "Khammam",    "label": "LocalAiTV",    "key_env": "YT_STREAM_KEY",             "concat": Path("concat_list_p1.txt")},
    {"name": "Kurnool",    "label": "KurnoolTV",    "key_env": "YT_STREAM_KEY_KURNOOL",     "concat": Path("concat_list_p2.txt")},
    {"name": "Karimnagar", "label": "KarimnagarTV", "key_env": "YT_STREAM_KEY_KARIMNAGAR",  "concat": Path("concat_list_p3.txt")},
    {"name": "Anatpur",    "label": "AnatpurTV",    "key_env": "YT_STREAM_KEY_ANATPUR",     "concat": Path("concat_list_p4.txt")},
    {"name": "Kakinada",   "label": "KakinadaTV",   "key_env": "YT_STREAM_KEY_KAKINADA",    "concat": Path("concat_list_p5.txt")},
    {"name": "Nalore",     "label": "NaloreTV",     "key_env": "YT_STREAM_KEY_NALORE",      "concat": Path("concat_list_p6.txt")},
    {"name": "Tirupati",   "label": "TirupatiTV",   "key_env": "YT_STREAM_KEY_TIRUPATI",    "concat": Path("concat_list_p7.txt")},
    {"name": "Guntur",     "label": "GunturTV",     "key_env": "YT_STREAM_KEY_GUNTUR",      "concat": Path("concat_list_p8.txt")},
    {"name": "Warangal",   "label": "WarangalTV",   "key_env": "YT_STREAM_KEY_WARANGAL",    "concat": Path("concat_list_p9.txt")},
    {"name": "Nalgonda",   "label": "NalgondaTV",   "key_env": "YT_STREAM_KEY_NALGONDA",    "concat": Path("concat_list_p10.txt")},
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

NOTEBOOKLM_CACHE_DIR = Path("outputs/notebooklm_cache")
NOTEBOOKLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)

FILLER_FILE = Path(os.getenv("FILLER_FILE", "assets/filler.mp4"))

_SCRIPT_DIR = Path(__file__).parent

def _get_intro_path(channel_name: str) -> Path | None:
    """Return channel-specific intro, falling back to intro4.mp4."""
    key = channel_name.lower().replace(' ', '_').replace('-', '_')
    specific = _SCRIPT_DIR / 'assets' / f'intro_{key}.mp4'
    if specific.exists():
        return specific
    default = _SCRIPT_DIR / 'assets' / 'intro4.mp4'
    return default if default.exists() else None


def _normalize_for_stream(src: Path) -> Path | None:
    """Return a stream-ready normalized copy of src (25fps, 1920x1080, aac 44100).
    Cached in outputs/notebooklm_cache/ — only runs once per file.
    Returns None if normalization fails. Does NOT affect bulletins/ads/programs."""
    norm = NOTEBOOKLM_CACHE_DIR.resolve() / (src.stem + "_norm.mp4")
    if norm.exists() and norm.stat().st_size > 100_000:
        return norm
    debug(f"Normalizing {src.name} → {norm.name} ...")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-level", "4.0",
        "-pix_fmt", "yuv420p", "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
        "-r", "25", "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "0",
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
               "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart",
        str(norm)
    ], capture_output=True)
    if r.returncode == 0 and norm.exists() and norm.stat().st_size > 100_000:
        debug(f"Normalized: {norm.name}")
        return norm
    debug(f"Normalization failed for {src.name}: {r.stderr.decode()[-200:]}")
    return None


def _get_notebooklm_path(channel_name: str) -> Path | None:
    """Return a stream-normalized NotebookLM video for the channel, or None."""
    key = channel_name.lower().replace(' ', '_').replace('-', '_')
    for candidate in [
        _SCRIPT_DIR / 'assets' / f'notebooklm_{key}.mp4',
        _SCRIPT_DIR / 'assets' / 'notebooklm.mp4',
    ]:
        if candidate.exists():
            return _normalize_for_stream(candidate)
    return None


def _build_combined_filler(channel_name: str) -> Path | None:
    """Pre-encode intro + notebooklm into one seamless file via filter_complex concat.
    Stored in NOTEBOOKLM_CACHE_DIR. Returns None if notebooklm doesn't exist for this channel.
    Cache is invalidated when either source file is newer than the combined output."""
    key     = channel_name.lower().replace(' ', '_').replace('-', '_')
    nlm_src = next(
        (c for c in [
            _SCRIPT_DIR / 'assets' / f'notebooklm_{key}.mp4',
            _SCRIPT_DIR / 'assets' / 'notebooklm.mp4',
        ] if c.exists()),
        None
    )
    if nlm_src is None:
        return None

    intro = _get_intro_path(channel_name)
    out   = NOTEBOOKLM_CACHE_DIR.resolve() / f"combined_{key}.mp4"

    # Cache hit: combined file is newer than both sources
    if out.exists() and out.stat().st_size > 100_000:
        src_mtime = max(
            intro.stat().st_mtime if intro else 0.0,
            nlm_src.stat().st_mtime
        )
        if src_mtime <= out.stat().st_mtime:
            return out
        out.unlink()

    if intro is None:
        debug(f"[{channel_name}] No intro — normalizing notebooklm only")
        return _normalize_for_stream(nlm_src)

    debug(f"[{channel_name}] Building combined filler: {intro.name} + {nlm_src.name}")
    vf_segment = (
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(intro),
        "-i", str(nlm_src),
        "-filter_complex",
        f"[0:v]{vf_segment}[v0];"
        "[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];"
        f"[1:v]{vf_segment}[v1];"
        "[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][aout]",
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-level", "4.0",
        "-pix_fmt", "yuv420p", "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
        "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "0",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out)
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode == 0 and out.exists() and out.stat().st_size > 100_000:
        debug(f"[{channel_name}] Combined filler ready: {out.name} ({out.stat().st_size // 1024} KB)")
        return out
    debug(f"[{channel_name}] Combined filler failed: {r.stderr.decode()[-300:]}")
    return None


# ════════════════════════════════════════════════════════════════════════════
# NotebookLM BULLETIN  (Intro -> Namaste -> NotebookLM -> Thanks)
# ════════════════════════════════════════════════════════════════════════════
# NotebookLM ab static filler nahi — dynamic location-wise bulletin hai.
# Operator MAIN bucket (S3_BUCKET_NAME) me `notebooklm/{Channel}/*.mp4` upload
# karta hai. Yahan latest file fetch karke flow assemble karte hain:
#   Intro (channel) -> Namaste (welcome anchor) -> NotebookLM -> Thanks (ending anchor)
# Namaste/Thanks = anchors/anchor{i} <-> anchors_end/anchor_end{i} (SAME person, §13).
S3_BUCKET_MAIN = os.getenv("S3_BUCKET_NAME", "")


def _s3_client_main():
    """MAIN bucket client (notebooklm bulletins). yt_streamer ka default _s3_client
    EXT bucket (_M creds) use karta hai; notebooklm MAIN bucket me hai."""
    return boto3.client(
        "s3", region_name=os.getenv("AWS_REGION", "ap-south-2"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def fetch_latest_program(channel_name: str, kind: str) -> "Path | None":
    """Latest notebooklm .mp4 for a channel+kind, downloaded + cached locally.
    Reads the NEW geo/ district path FIRST
    (geo/states/{state}/districts/{channel}/{kind}/notebooklm/), then falls back to the
    LEGACY notebooklm/{Channel}/{kind}/ path. 'Latest' = filename natural-sort, tie on
    LastModified (dated names like notebooklm_2026-06-07.mp4 win; multiple files kept).
    kind = 'local' | 'district'. Returns Path or None."""
    if not S3_BUCKET_MAIN:
        debug("program: S3_BUCKET_NAME not set"); return None

    from config import geo_district_prefix
    prefixes = []
    gp = geo_district_prefix(channel_name)
    if gp:
        prefixes.append(f"{gp}/{kind}/notebooklm/")        # geo (new — primary)
    prefixes.append(f"notebooklm/{channel_name}/{kind}/")  # legacy (fallback)

    for prefix in prefixes:
        try:
            res  = _s3_client_main().list_objects_v2(Bucket=S3_BUCKET_MAIN, Prefix=prefix)
            mp4s = [o for o in res.get("Contents", []) if o["Key"].endswith(".mp4") and o["Size"] > 0]
            if not mp4s:
                continue
            latest   = max(mp4s, key=lambda o: (_natural_sort_key(o["Key"]), o["LastModified"]))
            # cache name me channel+kind taaki same filename alag kinds me na takraye
            safe     = f"{channel_name.lower()}_{kind}_" + Path(latest["Key"]).name
            local    = NOTEBOOKLM_CACHE_DIR.resolve() / safe
            s3_mtime = latest["LastModified"].timestamp()
            fresh = (local.exists() and local.stat().st_size > 100_000
                     and local.stat().st_mtime >= s3_mtime)
            if not fresh:
                _s3_client_main().download_file(S3_BUCKET_MAIN, latest["Key"], str(local))
                debug(f"[{channel_name}/{kind}] downloaded (fresh): {local.name} [{prefix}]")
            else:
                debug(f"[{channel_name}/{kind}] cache hit: {local.name} [{prefix}]")
            return local
        except (BotoCoreError, ClientError) as e:
            debug(f"[{channel_name}/{kind}] program fetch error [{prefix}]: {e}")
            continue
    debug(f"[{channel_name}/{kind}] no notebooklm in geo or legacy path")
    return None


def build_program_bulletin(channel_name: str, kind: str,
                           out_dir: str = "outputs/program_bulletins") -> "Path | None":
    """NotebookLM-sourced program bulletin flow:
        Intro -> Namaste(welcome anchor) -> Main file(kind) -> Thanks(ending anchor)
    kind = 'local' | 'district' (notebooklm/{Channel}/{kind}/ se main file).
    Intro abhi channel intro (Intro1) — Intro2/Intro3 aate hi swap. 1920x1080 bulletin quality.
    Returns assembled video Path, or None."""
    main = fetch_latest_program(channel_name, kind)
    if main is None:
        debug(f"[{channel_name}/{kind}] No source file — skipping {kind} bulletin")
        return None

    key      = channel_name.lower().replace(' ', '_').replace('-', '_')
    out_base = Path(out_dir) / channel_name
    out_base.mkdir(parents=True, exist_ok=True)
    out      = out_base / f"{kind}_bulletin_{key}.mp4"

    # ── Cache: agar output source (S3 file) se naya hai to dobara concat mat karo ──
    # (streamer har cycle me ise call karega — bina cache ke har baar 1-min rebuild)
    if (out.exists() and out.stat().st_size > 100_000
            and out.stat().st_mtime >= main.stat().st_mtime):
        debug(f"[{channel_name}/{kind}] bulletin cache hit: {out.name}")
        return out

    intro = _get_intro_path(channel_name)                 # channel intro (Kurnool -> intro4.mp4)
    from config import get_anchor_pair
    namaste, thanks = get_anchor_pair(str(_SCRIPT_DIR))   # welcome + ending anchor (SAME person, §13)

    # Ordered flow segments — missing ko gracefully skip
    segs = []
    if intro and Path(intro).exists():     segs.append(Path(intro))
    if namaste and Path(namaste).exists(): segs.append(Path(namaste))
    segs.append(main)
    if thanks and Path(thanks).exists():   segs.append(Path(thanks))

    # ⚠️ Stream -f concat ke liye format INJECTIONS (vege/train) jaisa hona chahiye:
    # 1280x720, H.264 BASELINE, level 4.0. Citizen + vege sab baseline hain — agar
    # notebooklm High-profile/1080 me ho to concat demuxer use skip/glitch kar deta
    # hai (logs me add hota hai par stream me nahi dikhta). _normalize_for_stream
    # ke params se exact match.
    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,format=yuv420p")
    inputs, fc = [], []
    for i, s in enumerate(segs):
        inputs += ["-i", str(s)]
        fc.append(f"[{i}:v]{vf}[v{i}];")
        fc.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}];")
    concat_in = "".join(f"[v{i}][a{i}]" for i in range(len(segs)))
    fc.append(f"{concat_in}concat=n={len(segs)}:v=1:a=1[vout][aout]")

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", "".join(fc),
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "veryfast",
           "-profile:v", "baseline", "-level", "4.0",
           "-pix_fmt", "yuv420p", "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
           "-r", "25", "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "0",
           "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
           "-movflags", "+faststart", str(out)]
    debug(f"[{channel_name}/{kind}] Building program bulletin: {' + '.join(s.name for s in segs)}")
    r = subprocess.run(cmd, capture_output=True, timeout=1200)
    if r.returncode == 0 and out.exists() and out.stat().st_size > 100_000:
        debug(f"[{channel_name}/{kind}] bulletin ready: {out.name} ({out.stat().st_size//1024} KB)")
        return out
    debug(f"[{channel_name}/{kind}] bulletin failed: {r.stderr.decode()[-400:]}")
    return None


# Backward-compatible thin wrapper (notebooklm == 'local' kind)
def build_notebooklm_bulletin(channel_name: str) -> "Path | None":
    return build_program_bulletin(channel_name, "local")


_PROGRAM_KIND_TE = {"local": "స్థానిక వార్తలు", "district": "జిల్లా వార్తలు"}


def _maybe_send_program_to_api(channel_name: str, kind: str, video_path) -> None:
    """NotebookLM program bulletin ko /api/bulletins POST karo — once per build.
    Citizen bulletins jaise hi UI me dikhe. Marker (.sent) se duplicate-send avoid:
    sirf tab bhejo jab ye build pehle nahi bheja gaya (output source se naya)."""
    # Explicit opt-in: sirf jab PROGRAM_BULLETIN_API_ENABLED=true ho (prod compose me).
    # Local test (flag absent) is se PRODUCTION /api/bulletins pe accidental POST +
    # S3 upload NAHI karega — kyunki local .env me real BULLETIN_API_TOKEN hota hai.
    if os.getenv("PROGRAM_BULLETIN_API_ENABLED", "").lower() not in ("1", "true", "yes"):
        return
    video_path = Path(video_path)
    if not video_path.exists():
        return
    marker = video_path.with_suffix(".sent")
    # Is build ke liye already bhej diya? (marker output se naya/barabar)
    if marker.exists() and marker.stat().st_mtime >= video_path.stat().st_mtime:
        return

    token = os.getenv("BULLETIN_API_TOKEN", "") or os.getenv("LOCALAITV_API_TOKEN", "")
    if not (token and S3_BUCKET_MAIN):
        debug(f"[{channel_name}/{kind}] API send skip — token/bucket missing")
        return
    try:
        import requests
        from datetime import datetime
        from config import LOCATION_TELUGU_MAP, LOCATION_MAP

        # 1. S3 pe upload (video_url ke liye)
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_key = f"bulletins/{channel_name}/nlm_{kind}_{ts}.mp4"
        _s3_client_main().upload_file(str(video_path), S3_BUCKET_MAIN, s3_key)
        region    = os.getenv("AWS_REGION", "ap-south-2")
        video_url = f"https://{S3_BUCKET_MAIN}.s3.{region}.amazonaws.com/{s3_key}"

        # 2. Title (channel telugu + kind) + location_id
        ckey    = channel_name.lower()
        loc_te  = LOCATION_TELUGU_MAP.get(ckey, channel_name)
        loc_id  = LOCATION_MAP.get(ckey, 0)
        kind_te = _PROGRAM_KIND_TE.get(kind, kind)
        now_t   = datetime.now().strftime('%I:%M %p').lstrip('0')
        title   = f"{loc_te} {kind_te} | 🕒 {now_t}"

        payload = {
            "title":          title,
            "content":        f"NotebookLM {kind} bulletin",
            "priority_level": "low",
            "expiry_time":    None,
            "location_id":    int(loc_id) if loc_id else 0,
            "image_url":      None,
            "audio_url":      None,
            "video_url":      video_url,
        }
        r = requests.post("https://localaitv.com/api/bulletins", json=payload,
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"}, timeout=20)
        if r.status_code in (200, 201):
            debug(f"[{channel_name}/{kind}] ✅ sent to API: {r.json().get('id','?')} | {title}")
            marker.write_text(video_url)        # is build ko 'sent' mark karo
        else:
            debug(f"[{channel_name}/{kind}] ⚠️ Bulletin API {r.status_code}: {r.text[:140]}")
    except Exception as e:
        debug(f"[{channel_name}/{kind}] API send error: {e}")


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


def _is_valid_mp4(path: Path, min_size: int = 100_000) -> bool:
    """Return True only if the file exists, has minimum size, and ffprobe can read both
    video stream and duration (catches truncated/missing-moov-atom files)."""
    try:
        if not path.exists() or path.stat().st_size < min_size:
            return False
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=codec_type:format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            return False
        out = r.stdout.strip()
        # Must have both a duration value and confirm it decoded at least one stream
        return bool(out) and "N/A" not in out
    except Exception:
        return False


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
        final = bul / f"{bul.name}.mp4"
        if not _is_valid_mp4(final):
            if final.exists():
                debug(f"⚠️ Skipping corrupt bulletin: {final.name}")
            continue
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
    # FIX: tha r"(\\d+)" (double backslash) → digit pe split hi nahi karta tha.
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", key)]


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


# ── Classified-form LOCATION bulletins (EXT bucket) ─────────────────────────
# Flag-gated (default OFF). Forms with per-location content (vege excluded — old
# injection covers loc 4; whoiswho/trainroutes are flat/non-location).
LOCATION_BULLETINS_ENABLED = os.getenv("LOCATION_BULLETINS_ENABLED", "").lower() in ("1", "true", "yes")
CLASSIFIED_FORMS        = ["birthdays", "marriages", "jobpostings", "carsales", "localevents", "shopping"]
CLASSIFIED_MAX_PER_FORM = 6      # latest N candidates per form (raised for 10-min supply)
CLASSIFIED_MAX_CLIPS    = 40     # total DISTINCT candidate cap
CLASSIFIED_CLIP_MAX_SEC = 60.0   # per-clip trim (intro/anchors NOT trimmed)
CLASSIFIED_CLIP_MIN_SEC = 8.0    # near-empty clips drop kar do
CLASSIFIED_TARGET_SEC   = 600.0  # Rule 11: 10-min target
CLASSIFIED_MAX_SEGS     = 60     # Rule 12: same-channel filler-loop guard (no infinite)


def _list_all_mp4(prefix):
    """Paginated list of all non-empty .mp4 objects under prefix (EXT bucket)."""
    out, token = [], None
    while True:
        kw = dict(Bucket=S3_BUCKET, Prefix=prefix)
        if token:
            kw["ContinuationToken"] = token
        res = _s3_client().list_objects_v2(**kw)
        for o in res.get("Contents", []):
            if o["Key"].endswith(".mp4") and o["Size"] > 0:
                out.append(o)
        if res.get("IsTruncated"):
            token = res.get("NextContinuationToken")
        else:
            break
    return out


def _download_classified(s3_key):
    """Collision-safe RAW download (no 1080 GOP — assembler re-encodes to 720).
    Cache name uses full key (slashes→_) so shopping '1_Store.mp4' across dates
    /locations don't overwrite each other."""
    safe  = s3_key.replace("/", "_")
    local = INJECT_CACHE_DIR / safe
    if local.exists() and local.stat().st_size > 50_000:
        return local
    try:
        _s3_client().download_file(S3_BUCKET, s3_key, str(local))
        return local if (local.exists() and local.stat().st_size > 50_000) else None
    except (BotoCoreError, ClientError) as e:
        debug(f"classified dl failed [{s3_key}]: {e}")
        return None


def _select_classified_keys(location_id):
    """Selected S3 keys (latest-per-form) for a backend location_id, newest by
    LastModified. DELETION-AWARE: live S3 list — backend ne expired/sold item delete
    kiya to wo yahan aata hi nahi (flow me alag se filter ki zaroorat nahi)."""
    picked = []
    for form in CLASSIFIED_FORMS:
        prefix = f"{form}/outputs/{location_id}/"
        try:
            objs = _list_all_mp4(prefix)
        except (BotoCoreError, ClientError) as e:
            debug(f"classified list err [{prefix}]: {e}")
            continue
        objs.sort(key=lambda o: o["LastModified"], reverse=True)
        picked += [o["Key"] for o in objs[:CLASSIFIED_MAX_PER_FORM]]
    return picked[:CLASSIFIED_MAX_CLIPS]


def fetch_classified_clips(location_id):
    """Download the latest classified clips for a backend location_id (same-channel)."""
    clips = []
    for k in _select_classified_keys(location_id):
        p = _download_classified(k)
        if p:
            clips.append(p)
    debug(f"classified[{location_id}]: {len(clips)} clips")
    return clips


def build_location_classified_bulletin(channel_name, out_dir="outputs/program_bulletins",
                                       min_rebuild_interval=300):
    """LOCATION classified bulletin: Intro -> Namaste -> [same-channel clips filled
    to a ~10-min target] -> Thanks. 1280x720 baseline (stream -c copy concat compat).

    Rule 11 (10-min): clip durations ffprobe se naape jaate hain; greedily
    CLASSIFIED_TARGET_SEC tak fill. Rule 12 (same-channel filler): distinct clips
    kam pade to SAME channel ke clips loop hote hain (kabhi dusra channel nahi).
    Deletion-aware cache: .keys manifest se clip-set track — backend ne expired/sold
    item S3 se delete kiya to agle rebuild (<= min_rebuild_interval=5min) me drop ho
    jata, flow me alag filter ki zaroorat nahi. Returns Path | None."""
    import hashlib
    from config import channel_backend_ids
    ids = channel_backend_ids(channel_name)
    if not ids:
        return None

    key       = channel_name.lower().replace(' ', '_').replace('-', '_')
    out_base  = Path(out_dir) / channel_name
    out       = out_base / f"classified_bulletin_{key}.mp4"
    keys_file = out.with_suffix(".keys")

    # Throttle: recent output → cached fast (per-cycle S3 re-list avoid)
    if (out.exists() and out.stat().st_size > 100_000
            and (time.time() - out.stat().st_mtime) < min_rebuild_interval):
        return out

    # Current SAME-CHANNEL selection keys (live S3 → backend-deleted items gone)
    keys = []
    for bid in ids:
        keys += _select_classified_keys(bid)
    if not keys:
        debug(f"[{channel_name}] no classified clips — skip location bulletin")
        return None
    keys_sig = hashlib.md5("\n".join(sorted(set(keys))).encode()).hexdigest()

    # Deletion/addition-aware cache: clip-set same hai to re-encode mat karo
    if (out.exists() and out.stat().st_size > 100_000 and keys_file.exists()
            and keys_file.read_text(encoding="utf-8").strip() == keys_sig):
        os.utime(out, None)   # touch → throttle reset (content unchanged)
        debug(f"[{channel_name}] classified cache hit (clip-set unchanged)")
        return out

    out_base.mkdir(parents=True, exist_ok=True)

    # Download same-channel clips
    clips = [p for p in (_download_classified(k) for k in keys) if p]
    clips = [c for c in clips if _is_valid_mp4(c)]
    if not clips:
        debug(f"[{channel_name}] no valid classified clips")
        return None

    intro = _get_intro_path(channel_name)
    from config import get_anchor_pair
    namaste, thanks = get_anchor_pair(str(_SCRIPT_DIR))

    head, tail = [], []
    if intro and Path(intro).exists():     head.append(Path(intro))
    if namaste and Path(namaste).exists(): head.append(Path(namaste))
    if thanks and Path(thanks).exists():   tail.append(Path(thanks))
    overhead = sum(_get_video_duration(p) for p in head + tail)

    # Measure each clip (effective dur capped at CLIP_MAX); near-empty drop
    measured = []
    for c in clips:
        d = min(_get_video_duration(c), CLASSIFIED_CLIP_MAX_SEC)
        if d >= CLASSIFIED_CLIP_MIN_SEC:
            measured.append((c, d))
    if not measured:
        debug(f"[{channel_name}] all classified clips too short")
        return None

    # Rule 11: greedily add DISTINCT clips toward 10-min target
    chosen, running = [], overhead
    for c, d in measured:
        if running >= CLASSIFIED_TARGET_SEC:
            break
        chosen.append(c); running += d
    # Rule 12: still short → LOOP SAME-CHANNEL clips (never other channels)
    looped = 0
    if running < CLASSIFIED_TARGET_SEC:
        i = 0
        while running < CLASSIFIED_TARGET_SEC and len(chosen) < CLASSIFIED_MAX_SEGS:
            c, d = measured[i % len(measured)]
            chosen.append(c); running += d; i += 1; looped += 1

    clip_set = set(str(c) for c in chosen)
    segs = head + chosen + tail

    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,format=yuv420p")
    inputs, fc = [], []
    for i, s in enumerate(segs):
        if str(s) in clip_set:
            inputs += ["-t", str(CLASSIFIED_CLIP_MAX_SEC), "-i", str(s)]
        else:
            inputs += ["-i", str(s)]
        fc.append(f"[{i}:v]{vf}[v{i}];")
        fc.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}];")
    concat_in = "".join(f"[v{i}][a{i}]" for i in range(len(segs)))
    fc.append(f"{concat_in}concat=n={len(segs)}:v=1:a=1[vout][aout]")

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", "".join(fc),
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "veryfast",
           "-profile:v", "baseline", "-level", "4.0",
           "-pix_fmt", "yuv420p", "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
           "-r", "25", "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "0",
           "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
           "-movflags", "+faststart", str(out)]
    debug(f"[{channel_name}] Building classified: {len(chosen)} segs "
          f"({len(measured)} distinct +{looped} looped) ~{running:.0f}s / {CLASSIFIED_TARGET_SEC:.0f}s")
    r = subprocess.run(cmd, capture_output=True, timeout=1800)
    if r.returncode == 0 and out.exists() and out.stat().st_size > 100_000:
        keys_file.write_text(keys_sig, encoding="utf-8")
        debug(f"[{channel_name}] classified bulletin ready: {out.name} ({out.stat().st_size//1024} KB)")
        return out
    debug(f"[{channel_name}] classified bulletin failed: {r.stderr.decode()[-400:]}")
    return None


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

def build_concat_list(bulletins, concat_path, label="", inject_type=None, inject_payload=None,
                      channel_name=None):
    global _train_rotation_idx
    if not bulletins:
        debug(f"[{label}] No bulletins — skipping concat build")
        return None

    # ── Filler loop mode: intro/notebooklm/filler assets — no bulletin mixing ──
    # Real bulletins always have 'bul_' in their filename; assets never do.
    if not any('bul_' in b.name for b in bulletins):
        valid = [b for b in bulletins if _is_valid_mp4(b)]
        if not valid:
            debug(f"[{label}] All filler files invalid — nothing to write")
            return None
        lines = [f"file '{str(b)}'" for b in valid]
        reps  = max(1, 500 // len(valid))
        concat_path.write_text("\n".join(lines * reps) + "\n", encoding="utf-8")
        debug(f"[{label}] {concat_path.name}: filler loop — {[b.name for b in valid]} ×{reps}")
        return concat_path

    vege_path   = fetch_latest_vege()
    train_clips = [t for t in fetch_train_clips() if t]

    # Validate inject and filler candidates up front
    if vege_path and not _is_valid_mp4(vege_path):
        debug(f"[{label}] ⚠️ vege file invalid — skipping")
        vege_path = None
    train_clips = [t for t in train_clips if _is_valid_mp4(t)]

    lines = []

    if inject_type and inject_type != "news" and inject_payload:
        if inject_type == "train" and isinstance(inject_payload, list):
            valid_inject = [c for c in inject_payload if _is_valid_mp4(c)]
            if valid_inject:
                clip = valid_inject[_train_rotation_idx % len(valid_inject)]
                _train_rotation_idx += 1
                lines.append(f"file \'{str(clip)}\'")
                debug(f"[{label}] Inject train: {clip.name}")
            else:
                debug(f"[{label}] ⚠️ All inject train clips invalid — skipping inject")
        elif isinstance(inject_payload, Path):
            if _is_valid_mp4(inject_payload):
                lines.append(f"file \'{str(inject_payload)}\'")
                debug(f"[{label}] Inject {inject_type}: {inject_payload.name}")
            else:
                debug(f"[{label}] ⚠️ Inject file invalid ({inject_payload.name}) — skipping")

    # ── NotebookLM program bulletins (cached build) — agar channel ke liye ho ──
    nlm_local = nlm_district = None
    if channel_name:
        try:
            nlm_local    = build_program_bulletin(channel_name, "local")
            nlm_district = build_program_bulletin(channel_name, "district")
            # /api/bulletins POST — notebooklm bulletin ko UI feed me bhejo (citizen
            # bulletins jaise). build_program_bulletin ka cache + .sent marker mil ke
            # ensure karte hain: POST sirf EK BAAR per NAYA notebooklm (har cycle nahi).
            # Gate: PROGRAM_BULLETIN_API_ENABLED=true (sirf prod compose) — local test
            # me flag absent hone se accidental production POST nahi hota.
            if nlm_local:    _maybe_send_program_to_api(channel_name, "local",    nlm_local)
            if nlm_district: _maybe_send_program_to_api(channel_name, "district", nlm_district)
        except Exception as e:
            debug(f"[{label}] program bulletin build error: {e}")

    # ── Location-wise CLASSIFIED bulletin (EXT bucket, per-channel, flag-gated) ──
    # UI/API send NAHI — sirf stream weave (vege/train ki jagah, har notebooklm ke baad).
    classified = None
    if channel_name and LOCATION_BULLETINS_ENABLED:
        try:
            classified = build_location_classified_bulletin(channel_name)
        except Exception as e:
            debug(f"[{label}] classified build error: {e}")
    _cls_ok = bool(classified and _is_valid_mp4(classified))

    skipped = 0
    valid_news = []
    for news in bulletins:
        if _is_valid_mp4(news):
            valid_news.append(news)
        else:
            skipped += 1
    _nlm_l_ok = bool(nlm_local and _is_valid_mp4(nlm_local))
    _nlm_d_ok = bool(nlm_district and _is_valid_mp4(nlm_district))

    if _cls_ok:
        # ── CLASSIFIED flow (flag ON + content) — user ka exact flow: ──
        #   news → notebooklm(local)    → classified →
        #   news → notebooklm(district) → classified → loop
        # local/district 2 news me split; classified vege/train ki jagah.
        def _append_after(idx):
            if idx % 2 == 0:
                if _nlm_l_ok:
                    lines.append(f"file \'{str(nlm_local)}\'")
            else:
                if _nlm_d_ok:
                    lines.append(f"file \'{str(nlm_district)}\'")
            lines.append(f"file \'{str(classified)}\'")

        if valid_news:
            for idx, n in enumerate(valid_news):
                lines.append(f"file \'{str(n)}\'")
                _append_after(idx)
        else:
            _append_after(0)   # local-block
            _append_after(1)   # district-block
        debug(f"[{label}] + CLASSIFIED flow news={len(valid_news)} "
              f"local={_nlm_l_ok} district={_nlm_d_ok} classified=True")

    elif nlm_local or nlm_district:
        # ── Existing notebooklm flow (UNCHANGED) — har news ke baad poora block: ──
        #   news → notebooklm(local) → vege/train → notebooklm(district) → loop
        def _append_program_block():
            if _nlm_l_ok:
                lines.append(f"file \'{str(nlm_local)}\'")
            if vege_path:
                lines.append(f"file \'{str(vege_path)}\'")
            elif train_clips:
                global _train_rotation_idx
                t = train_clips[_train_rotation_idx % len(train_clips)]
                _train_rotation_idx += 1
                lines.append(f"file \'{str(t)}\'")
            if _nlm_d_ok:
                lines.append(f"file \'{str(nlm_district)}\'")

        if valid_news:
            for n in valid_news:
                lines.append(f"file \'{str(n)}\'")
                _append_program_block()
        else:
            _append_program_block()
        debug(f"[{label}] + notebooklm SEQUENTIAL news={len(valid_news)} "
              f"local={_nlm_l_ok} district={_nlm_d_ok}")
    else:
        # ── Default interleave (channels without notebooklm) — pehle jaisa ──
        skipped = 0   # is path me apna count (upar valid_news ka pre-count double na ho)
        for i, news in enumerate(bulletins):
            if not _is_valid_mp4(news):
                debug(f"[{label}] ⚠️ Corrupt bulletin skipped: {news.name}")
                skipped += 1
                continue
            lines.append(f"file \'{str(news)}\'")
            if i % 2 == 0 and vege_path:
                lines.append(f"file \'{str(vege_path)}\'")
            elif i % 2 == 1 and train_clips:
                t = train_clips[_train_rotation_idx % len(train_clips)]
                _train_rotation_idx += 1
                lines.append(f"file \'{str(t)}\'")

    if skipped:
        debug(f"[{label}] ⚠️ {skipped}/{len(bulletins)} bulletins skipped (corrupt)")

    if not lines:
        debug(f"[{label}] No valid files after validation — concat list empty")
        return None

    repeated = lines * 10
    concat_path.write_text("\n".join(repeated) + "\n", encoding="utf-8")
    debug(f"[{label}] {concat_path.name}: {len(bulletins)-skipped} bulletins | {len(repeated)} entries")
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


def start_ffmpeg_concat(stream_key, label, concat_path, force_encode=False):
    if STREAM_MODE == "copy" and not force_encode:
        cmd = ["ffmpeg","-re","-f","concat","-safe","0","-i",str(concat_path),
               "-c","copy","-f","flv",
               "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","30",
               f"{RTMPS_URL}/{stream_key}"]
    elif force_encode:
        # Filler mode (intro/notebooklm): ultrafast preset to keep CPU load low
        # across multiple simultaneous filler channels on the same VPS
        cmd = ["ffmpeg","-re","-fflags","+genpts",
               "-f","concat","-safe","0","-i",str(concat_path),
               "-c:v","libx264","-preset","ultrafast","-profile:v","baseline","-level","4.0",
               "-pix_fmt","yuv420p","-b:v","2500k","-maxrate","2500k","-bufsize","5000k",
               "-r","25","-g","50","-keyint_min","50","-sc_threshold","0",
               "-vf","scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25",
               "-c:a","aac","-ar","44100","-ac","2","-b:a","128k","-f","flv",
               "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","30",
               f"{RTMPS_URL}/{stream_key}"]
    else:
        # Full encode mode with viewer overlay
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

MIN_BULLETINS = 5


def _get_filler_path(channel_name):
    """Per-location filler from geo/ (MAIN bucket), cached locally + cache-fresh.
    geo/states/{state}/districts/{channel}/filler/filler.mp4 → mile to wahi, warna
    global FILLER_FILE (assets/filler.mp4) fallback. Returns Path | None."""
    from config import geo_district_prefix
    pref = geo_district_prefix(channel_name)
    if pref and S3_BUCKET_MAIN:
        key   = f"{pref}/filler/filler.mp4"
        dist  = channel_name.lower().replace(' ', '_').replace('-', '_')
        local = INJECT_CACHE_DIR / f"geo_filler_{dist}.mp4"
        try:
            head     = _s3_client_main().head_object(Bucket=S3_BUCKET_MAIN, Key=key)
            s3_mtime = head["LastModified"].timestamp()
            fresh    = (local.exists() and local.stat().st_size > 50_000
                        and local.stat().st_mtime >= s3_mtime)
            if not fresh:
                _s3_client_main().download_file(S3_BUCKET_MAIN, key, str(local))
                debug(f"[{channel_name}] geo filler (fresh): {local.name}")
            if local.exists() and local.stat().st_size > 50_000:
                return local
        except (BotoCoreError, ClientError):
            debug(f"[{channel_name}] no geo filler — global fallback")
    return FILLER_FILE if FILLER_FILE.exists() else None


def _with_fallback(folder, channel_name):
    primary = get_all_bulletins(folder)
    if len(primary) >= MIN_BULLETINS:
        return primary
    # Supplement with other channels' bulletins if we have some but not enough
    if primary:
        fallback = get_all_bulletins(_BASE)
        seen, merged = set(), []
        for f in primary + fallback:
            if str(f) not in seen:
                seen.add(str(f)); merged.append(f)
        if merged:
            return merged
    # No content at all — play pre-encoded combined filler (intro+notebooklm) in a loop.
    # Combined file is a single seamless MP4, so no concat-switching issues.
    combined = _build_combined_filler(channel_name)
    if combined:
        debug(f"[{channel_name}] No bulletins — combined filler: {combined.name}")
        return [combined]
    intro = _get_intro_path(channel_name)
    if intro:
        debug(f"[{channel_name}] No bulletins — intro-only loop: {intro.name}")
        return [intro]
    filler = _get_filler_path(channel_name)   # per-location geo filler, global fallback
    if filler:
        debug(f"[{channel_name}] No intro — filler loop: {filler.name}")
        return [filler]
    return []


def _launch_streams(inject_type=None, inject_payload=None):
    active = CHANNEL_DEFS[:STREAM_COUNT]
    procs  = []
    prepare_overlay()

    for i, ch in enumerate(active):
        bulletins = _with_fallback(ch["watch_dir"], ch["name"])
        if not bulletins:
            debug(f"[{ch['label']}] No bulletins and no intro — skipping")
        inj_t = inject_type    if i == 0 else None
        inj_p = inject_payload if i == 0 else None
        wrote = build_concat_list(bulletins, ch["concat"], ch["label"], inj_t, inj_p,
                                  channel_name=ch["name"])
        # Combined filler is pre-encoded (720p/25fps/baseline/no-B-frames) — copy mode is safe.
        p = start_ffmpeg_concat(ch["stream_key"], ch["label"], ch["concat"]) \
            if (wrote and ch["stream_key"]) else None
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

            if not any(cur_buls) and not FILLER_FILE.exists():
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
                        # New bulletins mila — sirf concat list silently update karo
                        # Stream restart NAHI karo — current playback continue rahegi
                        # Next FFmpeg crash/restart pe naya bulletin pick up hoga
                        for i, ch in enumerate(active):
                            if new_buls[i]:
                                build_concat_list(new_buls[i], ch["concat"], ch["label"],
                                                  channel_name=ch["name"])
                                debug(f"[{ch['label']}] Concat list updated silently ({len(new_buls[i])} bulletins) — no restart")
                        last_buls = new_buls
                    last_check = time.time()

                # Crash recovery per channel
                for i, (proc, ch) in enumerate(zip(procs, active)):
                    if proc and proc.poll() is not None:
                        debug(f"{ch['label']} DOWN ({_exit_reason(proc.returncode)}) — rebuild concat + restart in 3s")
                        stream_down(ch["label"]); time.sleep(3)
                        # Re-fetch and re-validate bulletins before rebuilding concat list
                        fresh_buls = _with_fallback(ch["watch_dir"], ch["name"])
                        last_buls[i] = fresh_buls
                        if (fresh_buls or FILLER_FILE.exists()) and ch["stream_key"]:
                            wrote = build_concat_list(fresh_buls, ch["concat"], ch["label"],
                                                      channel_name=ch["name"])
                            if wrote:
                                procs[i] = start_ffmpeg_concat(ch["stream_key"], ch["label"], ch["concat"])
                                if procs[i]: monitor_ffmpeg(procs[i], ch["label"])
                            else:
                                debug(f"[{ch['label']}] concat list empty after rebuild — skipping restart")
                                procs[i] = None
                        else:
                            procs[i] = None

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
