from asyncio import log
import gc
import glob
import os
import json
import random
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
 
# [CPU GOVERNOR HOOK] — FFmpeg calls ko throttle karne ke liye
try:
    from governor.cpu_governor import governor as _governor
    _GOVERNOR_OK = True
except ImportError:
    _GOVERNOR_OK = False
    class _DummyGovernor:
        def wait_for_slot(self, desc=""): pass
    _governor = _DummyGovernor()
 
import logging
log = logging.getLogger('video_builder')
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('%(asctime)s VIDEO_BUILDER %(levelname)s: %(message)s'))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
 
WIDTH       = 1920
HEIGHT      = 1080
FPS         = 25
VIDEO_CODEC = 'libx264'
AUDIO_CODEC = 'aac'
# Stream-ready CBR encoding — YouTube Live compatible (-c copy se direct stream)
PRESET      = 'veryfast'
VIDEO_BITRATE   = '4000k'
MAXRATE         = '4000k'
BUFSIZE         = '8000k'
GOP_SIZE        = str(FPS * 2)   # keyframe har 2 sec = 50 frames at 25fps
AUDIO_BITRATE   = '128k'
 
CLIP_MAX = 20.0  # FIX: was `CLIP_MAX >= 10.0` (comparison, not assignment)
REPORTER_DURATION = 5  # seconds — reporter card show duration
GIF_DURATION      = 5  # seconds — GIF overlay show duration (reporter ke baad)
TICKER_HEIGHT     = 90 # pixels — bottom ticker bar height (reporter card/GIF ko upar shift karne ke liye)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
 
from PIL import Image, ImageDraw, ImageFont
from ticker_overlay import add_ticker_overlay
from config import BASE_OUTPUT_DIR, ITEM_VIDEO_CACHE_DIR as _ITEM_VIDEO_CACHE_DIR, S3_INJECT_LOCAL_DIR
 
def _save_to_item_cache(counter, src_path: str):
    """Copy a freshly-built item video to local cache and upload to S3 asynchronously."""
    if not src_path or not os.path.exists(src_path):
        return
    os.makedirs(_ITEM_VIDEO_CACHE_DIR, exist_ok=True)
    dst = os.path.join(_ITEM_VIDEO_CACHE_DIR, f'item_{counter}_video.mp4')
    try:
        import shutil as _sh
        _sh.copy2(src_path, dst)
        print(f"  💾 [CACHE] item_{counter}_video.mp4 saved locally")
    except Exception as _e:
        print(f"  ⚠️  [CACHE] local copy failed counter={counter}: {_e}")
        dst = src_path  # still try S3 upload from source

    # Async S3 upload — non-blocking
    try:
        import s3_storage as _s3
        _s3.upload_file_async(dst, _s3.key_for_item_cache(counter))
    except Exception as _e:
        print(f"  ⚠️  [CACHE] S3 upload enqueue failed counter={counter}: {_e}")
 
_NOTO_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansTelugu-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifTelugu-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansTelugu-Bold.ttf",
]
 
TELUGU_FONT = os.environ.get('TELUGU_FONT', '')
if not TELUGU_FONT or not os.path.exists(TELUGU_FONT):
    for _f in _NOTO_CANDIDATES:
        if os.path.exists(_f):
            TELUGU_FONT = _f
            print(f"✓ Noto Telugu font: {_f}")
            break
        
if not TELUGU_FONT or not os.path.exists(TELUGU_FONT):
    for _local in [
        os.path.join(os.path.dirname(__file__), 'NotoSansTelugu.ttf'),
        os.path.join(os.path.dirname(__file__), 'assets', 'Gidugu Regular.otf'),
    ]:
        if os.path.exists(_local):
            TELUGU_FONT = _local
            print(f"✓ Local font: {_local}")
            break
if not TELUGU_FONT or not os.path.exists(TELUGU_FONT):
    for _f in [r'C:\Windows\Fonts\NirmalaB.ttf', r'C:\Windows\Fonts\gautamib.ttf']:
        if os.path.exists(_f):
            TELUGU_FONT = _f
            break
if not TELUGU_FONT or not os.path.exists(TELUGU_FONT):
    print("❌ No Telugu font found! Run: apt-get install fonts-noto")
    TELUGU_FONT = 'Arial'
 
_pw_instance = None
_pw_browser  = None
 
# ── ffprobe result cache — same file ko baar baar probe karne se bachao ──────
# Key: file path | Value: dict with width, height, rotation, aspect,
#                          needs_blur, scale_filter, fps, duration
_media_info_cache: dict = {}
 
def _probe_media(path: str) -> dict:
    """
    Ek hi baar ffprobe chalao — result cache mein rakh lo.
    _get_scale_filter, _needs_blur_fill, _get_fps sab yahan se data lete hain.
    """
    if path in _media_info_cache:
        return _media_info_cache[path]
 
    info = {
        'width': 1920, 'height': 1080, 'rotation': 0,
        'aspect': 16/9, 'needs_blur': False,
        'scale_filter': f'scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p,setsar=1,setpts=PTS-STARTPTS',
        'fps': '25', 'duration': None,
    }
 
    try:
        import json as _j
        # Single ffprobe call — streams + format dono ek saath
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_streams', '-show_entries', 'format=duration',
             '-of', 'json', path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        data   = _j.loads(r.stdout.decode())
        streams = data.get('streams') or [{}]   # FIX: empty list [] bhi [{}] se replace hoga
        stream = streams[0]
        fmt    = data.get('format', {})
 
        w = stream.get('width',  1920)
        h = stream.get('height', 1080)
 
        rotation = 0
        for sd in stream.get('side_data_list', []):
            if 'rotation' in sd:
                rotation = abs(int(sd['rotation']))
                break
        if rotation == 0:
            rotation = abs(int(stream.get('tags', {}).get('rotate', 0)))
        if rotation in (90, 270):
            w, h = h, w
 
        aspect      = w / h if h else 16/9
        target_asp  = WIDTH / HEIGHT
        needs_blur  = abs(aspect - target_asp) > 0.05
 
        if abs(aspect - target_asp) <= 0.05:
            scale_filter = f'scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p,setsar=1,setpts=PTS-STARTPTS'
        else:
            scale_filter = (f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
                            f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,'
                            f'fps={FPS},format=yuv420p,setsar=1,setpts=PTS-STARTPTS')
 
        raw_fps = stream.get('r_frame_rate', '25/1')
        try:
            num, den = raw_fps.split('/')
            fps_val  = str(round(float(num) / float(den)))
        except Exception:
            fps_val = '25'
 
        dur = None
        try:
            dur = float(fmt.get('duration') or stream.get('duration', ''))
        except Exception:
            pass
 
        info.update({
            'width': w, 'height': h, 'rotation': rotation,
            'aspect': aspect, 'needs_blur': needs_blur,
            'scale_filter': scale_filter, 'fps': fps_val, 'duration': dur,
        })
    except Exception as e:
        print(f"  ⚠️ ffprobe cache miss ({path}): {e}")
 
    _media_info_cache[path] = info
    return info
 
 
def _get_browser():
    global _pw_instance, _pw_browser
    try:
        from playwright.sync_api import sync_playwright
        if _pw_browser is None or not _pw_browser.is_connected():
            _pw_instance = sync_playwright().start()
            _pw_browser  = _pw_instance.chromium.launch(args=[
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu-compositing',
            ])
        return _pw_browser
    except Exception as e:
        print(f"  ❌ Browser init error: {e}")
        return None
 
 
def _get_scale_filter(path: str) -> str:
    """Cache se scale filter return karo — ffprobe dobara nahi chalega."""
    return _probe_media(path)['scale_filter']
 
def _blur_fill_filter(src_label: str, out_label: str) -> str:
    """Blur background + sharp original centered. No black bars, no crop."""
    tag = src_label.strip('[]').replace(':', '_')
    bg  = f'bf_bg_{tag}'
    fg  = f'bf_fg_{tag}'
    return (
        f'{src_label}split=2[{bg}_r][{fg}_r];'
        f'[{bg}_r]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,'
        f'crop={WIDTH}:{HEIGHT},boxblur=40:8[{bg}];'
        f'[{fg}_r]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[{fg}];'
        f'[{bg}][{fg}]overlay=(W-w)/2:(H-h)/2,'
        # f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS{out_label}'
        f'fps={FPS},format=yuv420p,setsar=1,setpts=PTS-STARTPTS{out_label}'
    )
 
def _needs_blur_fill(path: str) -> bool:
    """Cache se blur check return karo — ffprobe dobara nahi chalega."""
    return _probe_media(path)['needs_blur']
    
def _get_fps(video_path: str) -> str:
    """Cache se fps return karo — ffprobe dobara nahi chalega."""
    return _probe_media(video_path)['fps']
    
def _logo_input_args(logo_path: str, duration: float) -> list:
    """Return correct FFmpeg input args for logo based on file type."""
    ext = Path(logo_path).suffix.lower()
    if ext == '.gif':
        return ['-ignore_loop', '0', '-t', str(duration), '-i', logo_path]
    elif ext in ('.mov', '.mp4', '.webm', '.avi'):
        return ['-stream_loop', '-1', '-t', str(duration), '-i', logo_path]
    else:
        return ['-i', logo_path]


def _logo_is_animated(logo_path: str) -> bool:
    """True for video and GIF logos (need fps/setpts filter treatment)."""
    ext = Path(logo_path).suffix.lower() if logo_path else ''
    return ext in ('.mov', '.mp4', '.webm', '.avi', '.gif')


def _run(cmd: List[str], desc: str = '') -> bool:
    print(f"  🔧 {desc or ' '.join(cmd[:4])}")
    
    # Stream-ready: inject CBR + GOP flags if encoding (not concat/copy)
    if 'ffmpeg' in cmd and '-c:v' in cmd and 'copy' not in cmd:
        # Replace any existing -crf with CBR flags
        if '-crf' in cmd:
            idx = cmd.index('-crf')
            cmd.pop(idx)   # remove -crf value
            cmd.pop(idx)   # remove CRF number
        # Inject CBR flags after -c:v libx264 if not already present
        if '-b:v' not in cmd:
            try:
                cv_idx = cmd.index('-c:v') + 2
                cmd[cv_idx:cv_idx] = [
                    '-b:v', VIDEO_BITRATE,
                    '-maxrate', MAXRATE,
                    '-bufsize', BUFSIZE,
                    '-g', GOP_SIZE,
                    '-keyint_min', GOP_SIZE,
                    '-sc_threshold', '0',
                    '-preset', PRESET,
                ]
            except (ValueError, IndexError):
                pass
        if '-b:a' not in cmd and '-c:a' in cmd:
            try:
                ca_idx = cmd.index('-c:a') + 2
                cmd[ca_idx:ca_idx] = ['-b:a', AUDIO_BITRATE]
            except (ValueError, IndexError):
                pass
        # Thread optimization
        # if '-threads' not in cmd:
        #     cmd.insert(1, '-threads')
        #     cmd.insert(2, '0')
        # if '-filter_threads' not in cmd:
        #     cmd.insert(1, '-filter_threads')
        #     cmd.insert(2, '2')
        if '-threads' not in cmd:
            # Insert after 'ffmpeg' (position 1)
            cmd[1:1] = ['-threads', '4']
        if '-filter_threads' not in cmd:
            cmd[1:1] = ['-filter_threads', '2']
 
    _governor.wait_for_slot(desc)
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2700)
    except subprocess.TimeoutExpired:
        print(f"  ⏰ FFMPEG TIMEOUT (2700s): {' '.join(str(x) for x in cmd[:4])}")
        return False
    
    gc.collect()
    
    stderr_out = result.stderr.decode()
    if result.returncode != 0:
        print(f"  ❌ FFMPEG FAILED (code={result.returncode}):\n{stderr_out[-2000:]}")
        return False
    return True
 
 
def _audio_duration(audio_path: str) -> float:
    """Cache se duration return karo — ffprobe dobara nahi chalega."""
    info = _probe_media(audio_path)
    if info['duration'] is not None:
        return info['duration']
    # Fallback: direct ffprobe (audio-only files ke liye video stream nahi hoti)
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        dur = float(r.stdout.decode().strip())
        _media_info_cache[audio_path]['duration'] = dur
        return dur
    except Exception as e:
        print(f"  ⚠️ duration parse failed ({audio_path}): {e} — using fallback")
        return 5.0
 
def _video_duration(video_path: str) -> float:
    """Cache se duration return karo — ffprobe dobara nahi chalega."""
    info = _probe_media(video_path)
    if info['duration'] is not None:
        return info['duration']
    return 15.4
 
 
def calculate_script_budget(
    target_seconds: float,
    intro_path: str,
    headline_audio_paths: List[str],
    n_scripts: int,
    min_script_seconds: float = 10.0,
) -> Tuple[float, float, float]:
    intro_dur       = _video_duration(intro_path)
    headline_total  = sum(_audio_duration(p) for p in headline_audio_paths)
    remaining       = target_seconds - intro_dur - headline_total
    per_script_cap  = max(min_script_seconds, remaining / n_scripts) if n_scripts > 0 else min_script_seconds
 
    print(f"\n⏱️  DURATION BUDGET")
    print(f"   Target          : {target_seconds:.1f}s ({target_seconds/60:.1f} min)")
    print(f"   Intro           : {intro_dur:.1f}s")
    print(f"   Headlines total : {headline_total:.1f}s  ({len(headline_audio_paths)} items)")
    print(f"   Scripts budget  : {remaining:.1f}s  → {per_script_cap:.1f}s per item")
    print(f"   Estimated total : {intro_dur + headline_total + per_script_cap * n_scripts:.1f}s")
 
    return intro_dur, headline_total, per_script_cap
 
def build_intro_segment(intro_path: str, out_path: str) -> bool:
    return _run([
        'ffmpeg', '-y', '-i', intro_path,
        '-vf', f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
               f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,'
               f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
        '-af', 'asetpts=PTS-STARTPTS',
        '-r', str(FPS),
        '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
        '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
        '-video_track_timescale', '12800',
        out_path
    ], 'Building intro segment')
 
_reporter_png_cache: dict = {} 
def _create_reporter_card_png(name: str, photo_path: str = None) -> Optional[str]:
    import hashlib
 
    # HTML pehle banao, uska hash cache key banega
    has_photo = bool(photo_path and os.path.exists(photo_path))
    
    # Cache key: name + photo file content hash (not path)
    if has_photo:
        with open(photo_path, 'rb') as f:
            photo_hash = hashlib.md5(f.read()).hexdigest()[:8]
    else:
        photo_hash = "nophoto"
    
    # Code version bhi add karo — jab bhi HTML change karo, ye bump karo
    CARD_VERSION = "v5"
    cache_key = f"{CARD_VERSION}|{name}|{photo_hash}"
    
    if cache_key in _reporter_png_cache and os.path.exists(_reporter_png_cache[cache_key]):
        return _reporter_png_cache[cache_key]
    try:
        from playwright.sync_api import sync_playwright
        import base64
 
 
        if has_photo:
            with open(photo_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = Path(photo_path).suffix.lstrip('.') or 'png'
            img_tag = f'<img src="data:image/{ext};base64,{b64}">'
            photo_css = """
            .circle { width:120px; height:120px; border-radius:50%;
                      overflow:hidden; border:4px solid white; flex-shrink:0; }
            .circle img { width:100%; height:100%; object-fit:cover; }
            """
            photo_html = f'<div class="circle">{img_tag}</div>'
        else:
            img_tag = ""
 
        _card_bottom = -55 + TICKER_HEIGHT   # 140px from bottom
        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    html, body {{ width:1920px; height:1080px; background:rgba(0,0,0,0); }}
    .wrapper {{
        position:absolute; bottom:{_card_bottom}px; left:30px;
        display:flex; align-items:center;
    }}
    .circle {{
    width:120px; height:120px; border-radius:50%;
    overflow:hidden; border:4px solid #e63946;
    box-shadow: 0 0 0 3px rgba(230,57,70,0.4), 0 0 20px rgba(230,57,70,0.6);
    flex-shrink:0; z-index:2; position:relative;
    background: rgba(40,20,20,0.92);  
    }}
    .circle img {{ width:100%; height:100%; object-fit:cover; }}
    .pill {{
        display:flex; align-items:center;
        background:linear-gradient(135deg, rgba(40,20,20,0.92), rgba(60,30,30,0.88));
        border-radius:50px;
        padding:0 30px 0 60px;  
        margin-left:-25px;
        height:70px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        backdrop-filter:blur(8px);
    }}
    .name {{
        font-family:'Noto Sans Telugu','Nirmala UI',sans-serif;
        font-size:38px; font-weight:700; color:white;
        letter-spacing:0.5px;
        text-shadow: 1px 1px 6px rgba(0,0,0,0.9);
        white-space:nowrap;
    }}
    </style></head><body>
    <div class="wrapper">
        <div class="circle">{img_tag}</div>
        <div class="pill"><div class="name">{name}</div></div>
    </div>
    </body></html>"""
 
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='_reporter.png')
        tmp.close()
        out_png = tmp.name
 
        html_file = tempfile.mktemp(suffix='.html')
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html)
 
        # [PLAYWRIGHT REUSE] — singleton browser use karo, har baar launch nahi
        browser = _get_browser()
        if browser is None:
            raise RuntimeError("Browser not available")
 
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        try:
            page.goto(f"file:///{html_file}", wait_until="networkidle")
            page.screenshot(path=out_png, omit_background=True)
        finally:
            page.close()
            context.close()
 
        os.unlink(html_file)
        _reporter_png_cache[cache_key] = out_png
        return out_png
 
    except Exception as e:
        print(f"  ❌ Reporter card error: {e}")
        return None
    
_location_telugu_cache: dict = {}
 
def _location_display_text(location_name: str) -> str:
    """
    'Kurnool' → 'Kurnool | కర్నూల్'
    Already Telugu → as-is
    """
    if not location_name:
        return ''
    if location_name in _location_telugu_cache:
        return _location_telugu_cache[location_name]
    try:
        if any('\u0C00' <= ch <= '\u0C7F' for ch in location_name):
            result = location_name
        else:
            from openai_handler import OpenAIHandler
            _oai = OpenAIHandler()
            telugu = _oai.translate_to_telugu(location_name).strip()
            result = telugu if telugu and telugu != location_name else location_name
    except Exception as e:
        print(f"  ⚠️ Location translation failed: {e}")
        result = location_name
    _location_telugu_cache[location_name] = result
    return result
 
_location_card_cache: dict = {}
 
def _create_location_card_png(display_text: str) -> Optional[str]:
    """
    Playwright se styled location pill PNG banao (1920x1080 transparent).
    Position: reporter card ke theek neeche — bottom:50px left:30px,
    GIF (80x80) ke baad pill text.
    """
    import hashlib
    cache_key = hashlib.md5(display_text.encode()).hexdigest()[:10]
    if cache_key in _location_card_cache and os.path.exists(_location_card_cache[cache_key]):
        return _location_card_cache[cache_key]
    try:
        from playwright.sync_api import sync_playwright
 
        # GIF placeholder width ~80px + gap — pill starts after GIF
        _loc_bottom = -55 + TICKER_HEIGHT   # 154px from bottom
        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:1920px; height:1080px; background:rgba(0,0,0,0); }}
.loc-wrapper {{
    position:absolute; bottom:{_loc_bottom}px; left:93px;
    display:flex; align-items:center; height:52px;
}}
.loc-pill {{
    display:flex; align-items:center;
    background:linear-gradient(135deg, rgba(20,20,60,0.92), rgba(30,30,80,0.88));
    border-radius:50px;
    padding:0 28px;
    height:52px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    backdrop-filter:blur(8px);
    border-left: 4px solid #e63946;
}}
.loc-text {{
    font-family:'Noto Sans Telugu','Nirmala UI',sans-serif;
    font-size:30px; font-weight:600; color:white;
    letter-spacing:0.5px;
    text-shadow: 1px 1px 6px rgba(0,0,0,0.9);
    white-space:nowrap;
}}
</style></head><body>
<div class="loc-wrapper">
    <div class="loc-pill"><div class="loc-text">{display_text}</div></div>
</div>
</body></html>"""
 
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='_loccard.png')
        tmp.close()
        out_png = tmp.name
        html_file = tempfile.mktemp(suffix='.html')
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html)
 
        browser = _get_browser()
        if browser is None:
            raise RuntimeError("Browser not available")
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(f"file:///{html_file}", wait_until="networkidle")
            page.screenshot(path=out_png, omit_background=True)
        finally:
            page.close()
        os.unlink(html_file)
        _location_card_cache[cache_key] = out_png
        print(f"  ✓ Location card PNG: {out_png}")
        return out_png
    except Exception as e:
        print(f"  ❌ Location card PNG error: {e}")
        return None
 
 
#     """
#     GIF ke har frame ko 1920x1080 transparent canvas pe paste karo
#     position: left=30, bottom=50 (reporter card ke neeche).
#     Agar location_display_text diya hai toh Playwright location card PNG
#     bhi har frame pe composite karo.
#     """
 
 
 
 
 
#                 canvas.paste(pin, (x, y), pin)
#                     canvas.alpha_composite(loc_png_img)
#                 frames.append(canvas)
#                 durations.append(src.info.get("duration", 100))
#                 src.seek(src.tell() + 1)
 
 
#         tmp.close()
#             tmp.name,
#         )
#     finally:
#             src.close()
#                 loc_png_img.close()
#                 im.close()
#         frames.clear()
 
def _create_location_pill_png(display_text: str, pill_x: int, y_circle: int, circle_size: int) -> Optional[str]:
    """Same pill style as reporter card — for GIF+location overlay."""
    import hashlib
    cache_key = hashlib.md5(f"{display_text}{pill_x}{y_circle}".encode()).hexdigest()[:10]
    if cache_key in _location_card_cache and os.path.exists(_location_card_cache[cache_key]):
        return _location_card_cache[cache_key]
    try:
        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:1920px; height:1080px; background:rgba(0,0,0,0); }}
.wrapper {{
    position:absolute;
    left:{pill_x}px;
    top:{y_circle}px;
    display:flex; align-items:center;
}}
.circle-spacer {{ width:{circle_size}px; height:{circle_size}px; flex-shrink:0; }}
.pill {{
    display:flex; align-items:center;
    background:linear-gradient(135deg, rgba(40,20,20,0.92), rgba(60,30,30,0.88));
    border-radius:50px;
    padding:0 30px 0 60px;
    margin-left:-25px;
    height:70px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    backdrop-filter:blur(8px);
}}
.name {{
    font-family:'Noto Sans Telugu','Nirmala UI',sans-serif;
    font-size:38px; font-weight:700; color:white;
    letter-spacing:0.5px;
    text-shadow: 1px 1px 6px rgba(0,0,0,0.9);
    white-space:nowrap;
}}
</style></head><body>
<div class="wrapper">
    <div class="circle-spacer"></div>
    <div class="pill"><div class="name">{display_text}</div></div>
</div>
</body></html>"""
 
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='_locpill.png')
        tmp.close()
        html_file = tempfile.mktemp(suffix='.html')
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html)
 
        browser = _get_browser()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(f"file:///{html_file}", wait_until="networkidle")
            page.screenshot(path=tmp.name, omit_background=True)
        finally:
            page.close()
        os.unlink(html_file)
        _location_card_cache[cache_key] = tmp.name
        return tmp.name
    except Exception as e:
        print(f"  ❌ Location pill PNG error: {e}")
        return None
    
def _create_gif_overlay(gif_path: str, location_display_text: str = '') -> Optional[str]:
    """
    Reporter card jaisi pill — GIF animated left circle + location text right.
    Same position/size as reporter card.
    """
    try:
        from PIL import Image
 
        # GIF frames load
        src = Image.open(gif_path)
        frames, durations = [], []
 
        try:
            while True:
                frame = src.copy().convert("RGBA")
                
                TARGET = 120
                pin = frame.crop((844, 408, 974, 604))  # 130x196
                pin = pin.resize((TARGET, TARGET), Image.LANCZOS)
 
                # 1920x1080 transparent canvas
                canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
 
                # Same position as reporter card
                _card_bottom = 50  # match reporter card
                x_circle = 30
                pill_x = x_circle + TARGET - 80  # = 30 + 120 - 45 = 105
                y_circle = HEIGHT - _card_bottom - TARGET
 
                # Circle mask
                mask = Image.new("L", (TARGET, TARGET), 0)
                from PIL import ImageDraw as _ID
                _ID.Draw(mask).ellipse((0, 0, TARGET, TARGET), fill=255)
 
                canvas.paste(pin, (x_circle, y_circle), mask)
 
                # Location text pill (same as reporter name pill)
                if location_display_text:
                    loc_png = _create_location_pill_png(location_display_text, pill_x, y_circle, TARGET)
                    if loc_png:
                        loc_img = Image.open(loc_png).convert("RGBA")
                        canvas.alpha_composite(loc_img)
                        loc_img.close()
 
                frames.append(canvas)
                durations.append(src.info.get("duration", 100))
                src.seek(src.tell() + 1)
        except EOFError:
            pass
 
        if not frames:
            return None
 
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_gif_overlay.gif")
        tmp.close()
        frames[0].save(tmp.name, save_all=True, append_images=frames[1:],
                      loop=0, duration=durations, disposal=2)
        return tmp.name
 
    finally:
        try: src.close()
        except: pass
        for im in frames:
            try: im.close()
            except: pass
        frames.clear()
 
FADE_DUR = 0.5
 
def _reporter_gif_filter_suffix(reporter_index, gif_index, duration):
    """
    Returns filter_complex suffix + map_out label for reporter→gif fade.
    Apply karo build_news_segment, build_image_slideshow (single+multi) mein.
    """
    if reporter_index is None and gif_index is None:
        return '', '[outv]'
 
    suffix = ''
    
    if reporter_index is not None:
        suffix += (
            f";[{reporter_index}:v]scale={WIDTH}:{HEIGHT},format=rgba"
            f",fade=t=out:st={REPORTER_DURATION - FADE_DUR}:d={FADE_DUR}:alpha=1[rep_faded]"
            f";[outv]format=rgba[outv_r]"
            f";[outv_r][rep_faded]overlay=0:0:enable='lte(t,{REPORTER_DURATION})'[after_reporter]"
        )
        last = '[after_reporter]'
    else:
        suffix += f";[outv]format=rgba[after_reporter]"
        last = '[after_reporter]'
 
    if gif_index is not None:
        gif_end = REPORTER_DURATION + 5  # GIF 5 sec dikhega
        suffix += (
            f";[{gif_index}:v]format=rgba"
            f",fade=t=in:st={REPORTER_DURATION}:d={FADE_DUR}:alpha=1"
            f",fade=t=out:st={gif_end - FADE_DUR}:d={FADE_DUR}:alpha=1[gif_faded]"
            f";{last}[gif_faded]overlay=0:0:enable='between(t,{REPORTER_DURATION},{gif_end})'[final]"
        )
        return suffix, '[final]'
    else:
        suffix += f";{last}copy[final]"
        return suffix, '[final]'
    
 
def _create_headline_overlay(headline_text: str, width: int, height: int,
                              font_path: str) -> Optional[str]:
    # [PLAYWRIGHT REUSE] — singleton browser use karo
    import time as _t
    _tov = _t.time()
 
    pass
 
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='_hl.png')
    tmp.close()
    overlay_png = tmp.name
    html_file   = None
 
    try:
        words = headline_text.strip().split()
        if len(words) <= 3:
            lines = [" ".join(words)]
        else:
            lines = [" ".join(words[:3])]          # Line 1: 3 words
            remaining = words[3:]
            mid = (len(remaining) + 1) // 2
            lines.append(" ".join(remaining[:mid])) # Line 2
            if remaining[mid:]:
                lines.append(" ".join(remaining[mid:])) # Line 3
        if not lines:
            lines = [headline_text.strip()]
 
        # Template layout (1920x1080) — pixel-measured from template.mp4:
        # Left black panel : x=117, y=0,  w=658, h=808
        # Right red panel  : x=785, y=88, w=970, h=718
        # Text zone: right panel with 30px inner padding
        RIGHT_X = 815   # 785 + 30px padding
        RIGHT_Y = 108   # 88  + 20px padding
        RIGHT_W = 910   # 970 - 60px padding
        RIGHT_H = 678   # 718 - 40px padding
 
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
* {{ margin:0; padding:0; }}
html, body {{ width:{width}px; height:{height}px; background:rgba(0,0,0,0); }}
.zone {{
  position:absolute;
  left:{RIGHT_X}px; top:{RIGHT_Y}px; width:{RIGHT_W}px; height:{RIGHT_H}px;
  display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:10px;
  overflow:hidden;
}}
.t {{
  font-family:'Noto Sans Telugu','Nirmala UI','Gautami',sans-serif;
  font-size:72px; font-weight:bold; color:white;
  text-shadow:-2px -2px 0 #000,2px -2px 0 #000,
              -2px  2px 0 #000,2px  2px 0 #000;
  line-height:1.25;
  white-space:normal; word-break:break-word;
  text-align:center; width:100%;
}}
</style></head><body>
<div class="zone">
{"".join(f'<div class="t">{l}</div>' for l in lines)}
</div>
</body></html>"""
 
        html_file = os.path.abspath(tempfile.mktemp(suffix='.html'))
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html)
 
        # [PLAYWRIGHT REUSE] — singleton browser use karo, har baar launch nahi
        browser = _get_browser()
        if browser is None:
            raise RuntimeError("Browser not available")
        page = browser.new_page(
            viewport={"width": width, "height": height},
            extra_http_headers={"Content-Type": "text/html; charset=utf-8"}
        )
        try:
            page.goto(f"file:///{html_file}", wait_until="networkidle")
            page.screenshot(path=overlay_png, omit_background=True)
        finally:
            page.close()
 
        if os.path.exists(overlay_png):
            print(f"  ✓ Playwright Telugu overlay: {overlay_png}")
            log.info(f"[OVERLAY-TIMER] elapsed={_t.time()-_tov:.2f}s")
            return overlay_png
        
        else:
            print(f"  ❌ Screenshot failed")
            return None
 
    except Exception as e:
        print(f"  ❌ Playwright error: {e}")
        import traceback
        traceback.print_exc()
        if os.path.exists(overlay_png):
            os.unlink(overlay_png)
        return None
    finally:
        if html_file and os.path.exists(html_file):
            try:
                os.unlink(html_file)
            except:
                pass
 
 
 
def build_headline_card(headline_text: str, audio_path: str, out_path: str,
                        template_path: str = None, media_path: str = None) -> bool:
    """
    Build headline card segment.
 
    Layout (matches template.mp4):
      Left  panel (black box) : media/image/video  — x=100, y=86, w=682, h=723
      Right panel (red box)   : headline text       — x=815, y=108, w=910, h=678
 
    If media_path provided → composited layout (media left + text right).
    Otherwise             → template/red background with text overlay only.
    """
    import time as _t
    _t_start = _t.time()
    log.info(f"[HL-TIMER] START | text={headline_text[:40]}")
 
    duration     = _audio_duration(audio_path)
    has_template = bool(template_path and os.path.exists(template_path))
    has_media    = bool(media_path and os.path.exists(media_path))
 
    overlay_png = _create_headline_overlay(headline_text, WIDTH, HEIGHT, TELUGU_FONT)
 
    out_flags = [
        '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
        '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
        '-video_track_timescale', '12800',
        '-t', str(duration),
        out_path
    ]
 
    try:
        if has_template:
            bg_inputs = ['-stream_loop', '-1', '-t', str(duration), '-i', template_path]
            bg_vf = f'scale={WIDTH}:{HEIGHT},fps={FPS},format=yuva420p,setpts=PTS-STARTPTS'
        else:
            bg_inputs = ['-f', 'lavfi',
                         '-i', f'color=c=0x780000:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}']
            bg_vf = f'fps={FPS},format=yuva420p,setpts=PTS-STARTPTS'
 
        # ── Composited: media left + headline text right ──────────────────────
        if has_media and overlay_png and os.path.exists(overlay_png):
            media_ext    = Path(media_path).suffix.lower()
            is_img_media = media_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
 
            if is_img_media:
                media_inputs = ['-loop', '1', '-t', str(duration), '-i', media_path]
            else:
                media_inputs = ['-stream_loop', '-1', '-t', str(duration), '-i', media_path]
 
            # LEFT_X, LEFT_Y, LEFT_W, LEFT_H = 100, 86, 682, 723
            LEFT_X, LEFT_Y, LEFT_W, LEFT_H = 133, 77, 653, 730
 
            cmd = [
                'ffmpeg', '-y',
                *bg_inputs,            # [0] template/bg
                *media_inputs,         # [1] news media
                '-i', overlay_png,     # [2] headline text PNG
                '-i', audio_path,      # [3] audio
                '-filter_complex',
                f'[0:v]{bg_vf}[bg];'
                f'[1:v]scale={LEFT_W}:{LEFT_H}:force_original_aspect_ratio=increase,'
                f'crop={LEFT_W}:{LEFT_H}:(iw-ow)/2:(ih-oh)/2,'
                f'fps={FPS},setpts=PTS-STARTPTS[media_scaled];'
                f'[bg][media_scaled]overlay=x={LEFT_X}:y={LEFT_Y}[bg_media];'
                f'[bg_media][2:v]overlay=0:0,fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]',
                '-map', '[outv]', '-map', '3:a',
                '-af', 'asetpts=PTS-STARTPTS',
                *out_flags
            ]
            print(f"  🎬 Headline card: media={os.path.basename(media_path)} + text right panel")
            _result = _run(cmd, f'Headline+Media: {headline_text[:40]}')
            log.info(f"[HL-TIMER] END | elapsed={_t.time()-_t_start:.2f}s | text={headline_text[:40]}")
            return _result
 
        # ── Text-only overlay (no media) ──────────────────────────────────────
        elif overlay_png and os.path.exists(overlay_png):
            cmd = [
                'ffmpeg', '-y',
                *bg_inputs,
                '-i', overlay_png,
                '-i', audio_path,
                '-filter_complex',
                f'[0:v]{bg_vf}[bg];'
                f'[bg][1:v]overlay=0:0,fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]',
                '-map', '[outv]', '-map', '2:a',
                '-af', 'asetpts=PTS-STARTPTS',
                *out_flags
            ]
            _result = _run(cmd, f'Headline (text-only): {headline_text[:40]}')
            log.info(f"[HL-TIMER] END | elapsed={_t.time()-_t_start:.2f}s | text={headline_text[:40]}")
            return _result
 
        # ── Fallback: bg + audio only ─────────────────────────────────────────
        else:
            cmd = [
                'ffmpeg', '-y',
                *bg_inputs,
                '-i', audio_path,
                '-vf', f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
                '-af', 'asetpts=PTS-STARTPTS',
                '-map', '0:v', '-map', '1:a',
                *out_flags
            ]
            _result = _run(cmd, f'Headline (fallback): {headline_text[:40]}')
            log.info(f"[HL-TIMER] END | elapsed={_t.time()-_t_start:.2f}s | text={headline_text[:40]}")
            return _result
 
    finally:
        if overlay_png and os.path.exists(overlay_png):
            try:
                os.unlink(overlay_png)
            except:
                pass
 
def build_news_segment(media_path: str, script_audio_path: str,
                       logo_path: str, out_path: str,
                       max_duration: Optional[float] = None,
                       reporter_info: dict = None) -> bool:
    raw_duration = _audio_duration(script_audio_path)
 
    if max_duration is not None and raw_duration > max_duration:
        print(f"    ✂️  Audio {raw_duration:.1f}s → {max_duration:.1f}s")
        duration = max_duration
    else:
        duration = raw_duration + 0.3
 
    ext      = Path(media_path).suffix.lower()
    is_image = ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
 
    logo_ext      = Path(logo_path).suffix.lower() if logo_path else ''
    logo_is_video = _logo_is_animated(logo_path)
    has_logo      = bool(logo_path and os.path.exists(logo_path))

    scale_filter = _get_scale_filter(media_path)

    inputs      = []
    input_index = 0

    if is_image:
        inputs += ['-loop', '1', '-t', str(duration), '-i', media_path]
    else:
        inputs += ['-stream_loop', '-1', '-t', str(duration), '-i', media_path]
    media_index  = input_index
    input_index += 1

    logo_index = None
    if has_logo:
        inputs += _logo_input_args(logo_path, duration)
        logo_index   = input_index
        input_index += 1
 
    reporter_png = None
    reporter_index = None
    if reporter_info:
        rname  = reporter_info.get('name', '').strip()
        rphoto = reporter_info.get('photo_path', '').strip()
        print(f"  [REPORTER] name='{rname}' | photo_path='{rphoto}' | photo_exists={os.path.exists(rphoto) if rphoto else False}")
        if not rname and not rphoto:
            print(f"  ⏭️  Reporter card skipped — name aur photo dono empty hain")
        else:
            reporter_png = _create_reporter_card_png(rname, rphoto)
        if reporter_png and os.path.exists(reporter_png):
            print(f"  🖼️  reporter_png bana: {reporter_png}")
            inputs += ['-loop', '1', '-t', str(duration), '-i', reporter_png]
            reporter_index = input_index
            input_index += 1
        else:
            print(f"  ❌ reporter_png nahi bana (None ya file missing)")
    else:
        print(f"  [REPORTER] reporter_info=None — card skip")
 
    inputs += ['-i', script_audio_path]
    audio_index = input_index
    input_index += 1
 
    use_blur = _needs_blur_fill(media_path)
    if has_logo:
        if use_blur:
            filter_complex = (
                _blur_fill_filter(f'[{media_index}:v]', '[blurred_base]') + ';'
                f'[{logo_index}:v]scale=500:-1[logo];'
                f'[blurred_base][logo]overlay=x=W-overlay_w-10:y=10,'
                f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
            )
        else:
            filter_complex = (
                f'[{media_index}:v]{scale_filter}[scaled];'
                f'[{logo_index}:v]scale=500:-1[logo];'
                f'[scaled][logo]overlay=x=W-overlay_w-10:y=10,'
                f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
            )
    else:
        if use_blur:
            filter_complex = _blur_fill_filter(f'[{media_index}:v]', '[outv]')
        else:
            filter_complex = (
                f'[{media_index}:v]{scale_filter},'
                f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
            )
 
    gif_overlay_path  = None
    gif_index         = None
    location_text     = ''
    if reporter_info:
        _gif_src = reporter_info.get('gif_path', '').strip()
        location_text = reporter_info.get('location_name', '').strip()
        _loc_display  = _location_display_text(location_text) if location_text else ''
        if _gif_src and os.path.exists(_gif_src):
            gif_overlay_path = _create_gif_overlay(_gif_src, _loc_display)
        if gif_overlay_path and os.path.exists(gif_overlay_path):
            inputs += ['-stream_loop', '-1', '-t', str(duration), '-i', gif_overlay_path]
            gif_index   = input_index
            input_index += 1
            print(f"  🎞️  GIF overlay ready: {gif_overlay_path}")
 
    #         f";[{reporter_index}:v]scale={WIDTH}:{HEIGHT},format=rgba[reporter_layer]"
    #         f";[outv]format=rgba[outv_rgba]"
    #         f";[outv_rgba][reporter_layer]overlay=0:0:enable='lte(t,{REPORTER_DURATION})'[after_reporter]"
    #     )
 
    #             f";[{gif_index}:v]format=rgba[gif_layer]"
    #             f";[after_reporter][gif_layer]overlay=0:0:"
    #             f"enable='gte(t,{REPORTER_DURATION})'[final]"
    #         )
 
 
    #             f";[outv]format=rgba[outv_rgba_g]"
    #             f";[{gif_index}:v]format=rgba[gif_layer_g]"
    #             f";[outv_rgba_g][gif_layer_g]overlay=0:0[final]"
    #         )
 
    _suffix, map_out = _reporter_gif_filter_suffix(reporter_index, gif_index, duration)
    filter_complex += _suffix
 
    _gif_overlay_to_cleanup = gif_overlay_path
 
    cmd = [
        'ffmpeg', '-y',
        *inputs,
        '-filter_complex', filter_complex,
        '-map', map_out,
        '-map', f'{audio_index}:a',
        '-af', 'asetpts=PTS-STARTPTS',
        '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
        '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
        '-video_track_timescale', '12800',
        '-t', str(duration),
        out_path
    ]
    result = _run(cmd, f'News: {Path(media_path).name}  [{duration:.1f}s]')
    if _gif_overlay_to_cleanup and os.path.exists(_gif_overlay_to_cleanup):
        try: os.unlink(_gif_overlay_to_cleanup)
        except: pass
    return result
 
def build_filler_segment(logo_path: str, duration: float, out_path: str) -> bool:
    if duration <= 0:
        return False
 
    logo_ext = Path(logo_path).suffix.lower() if logo_path else ''
    is_gif   = logo_ext == '.gif'
    is_video = logo_ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']
    is_image = logo_ext in ['.png', '.jpg', '.jpeg', '.webp']
    has_logo_gif   = bool(logo_path and os.path.exists(logo_path) and is_gif)
    has_logo_img   = bool(logo_path and os.path.exists(logo_path) and is_image)
    has_logo_video = bool(logo_path and os.path.exists(logo_path) and is_video)

    if has_logo_gif:
        return _run([
            'ffmpeg', '-y',
            '-ignore_loop', '0', '-t', str(duration), '-i', logo_path,
            '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
            '-vf', f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
                   f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,'
                   f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
            '-map', '0:v', '-map', '1:a',
            '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
            '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration),
            out_path
        ], f'Break (gif) [{duration:.2f}s]')

    if has_logo_video:
        return _run([
            'ffmpeg', '-y',
            '-stream_loop', '-1', '-t', str(duration), '-i', logo_path,
            '-vf', f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
                   f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,'
                   f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
            '-af', 'asetpts=PTS-STARTPTS',
            '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
            '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration),
            out_path
        ], f'Break (video) [{duration:.2f}s]')

    if has_logo_img:
        return _run([
            'ffmpeg', '-y',
            '-loop', '1', '-t', str(duration), '-i', logo_path,
            '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
            '-vf', f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
                   f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,'
                   f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
            '-af', 'asetpts=PTS-STARTPTS',
            '-map', '0:v', '-map', '1:a',
            '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
            '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration),
            out_path
        ], f'Break (image) [{duration:.2f}s]')
    else:
        return _run([
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}',
            '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
            '-vf', f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
            '-af', 'asetpts=PTS-STARTPTS',
            '-map', '0:v', '-map', '1:a',
            '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
            '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration),
            out_path
        ], f'Break (black) [{duration:.2f}s]')
 
def _concat_demuxer(segment_paths: List[str], out_path: str) -> bool:
    import time
    import gc
    import subprocess
 
    # ── DEBUG START ──
    print(f"  [DEBUG-CONCAT] {len(segment_paths)} segments → {os.path.basename(out_path)}")
    for s in segment_paths:
        exists = os.path.exists(s)
        dur = _video_duration(s) if exists else 0.0
        print(f"    [DEBUG-SEG] {os.path.basename(s)} | exists={exists} | dur={dur:.2f}s")
    # ── DEBUG END ──
 
    valid_paths = [s for s in segment_paths if os.path.exists(s) and os.path.getsize(s) > 0]
    if not valid_paths:
        return False
 
    list_fd, list_path = tempfile.mkstemp(suffix='.txt')
 
    try:
        with os.fdopen(list_fd, 'w', encoding='utf-8') as f:
            for seg in valid_paths:
                abs_path = os.path.abspath(seg).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
 
        # 🔥 CRITICAL: small delay before FFmpeg
        time.sleep(0.2)
 
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_path,
            '-c', 'copy',
            '-movflags', '+faststart',
            out_path
        ]
 
        # ✅ FORCE synchronous execution (NO parallel)
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            print(f"  ❌ concat failed:\n{result.stderr.decode()[-1000:]}")
 
        success = (result.returncode == 0)
 
        # 🔥 cleanup memory pressure
        time.sleep(0.2)
        gc.collect()
 
        return success
 
    finally:
        if os.path.exists(list_path):
            os.unlink(list_path)
 
 
def add_background_music(video_path: str, bgm_path: str,
                         bgm_volume: float = 0.08,
                         fade_seconds: float = 2.5,
                         intro_duration: float = 0.0,
                         mute_after_time: float = None,
                         filler_volume_boost: float = 1.0,
                         filler_start_time: float = None) -> bool:
    if not os.path.exists(bgm_path):
        print(f"  ⚠️  BGM not found: {bgm_path}")
        return False
 
    duration       = _video_duration(video_path)
    fade_out_start = max(0.0, duration - fade_seconds)
    bgm_start      = max(0.0, intro_duration)
    bgm_fade_start = bgm_start
    tmp_path       = video_path + '_bgm.mp4'
 
    if mute_after_time is None and filler_start_time is None:
        print(f"  📊 BGM: Sidechain for entire video")
        bgm_filter = (
            f"[1:a]"
            f"aloop=loop=-1:size=2147483647,"
            f"atrim=duration={duration:.3f},"
            f"volume={bgm_volume:.4f},"
            f"volume=enable='lte(t,{bgm_start:.3f})':volume=0,"
            f"afade=t=in:st={bgm_fade_start:.3f}:d={fade_seconds:.2f},"
            f"afade=t=out:st={fade_out_start:.2f}:d={fade_seconds:.2f}"
            f"[bgm_raw];"
            f"[0:a]asplit=2[voice_out][sc];"
            f"[bgm_raw][sc]sidechaincompress="
            f"threshold=0.015:ratio=12:attack=8:release=700:level_sc=1.0[bgm_ducked];"
            f"[voice_out][bgm_ducked]amix=inputs=2:duration=first:normalize=0[outa]"
        )
 
    elif filler_start_time is not None:
        print(f"  📊 BGM: Sidechain until {mute_after_time:.2f}s, MUTED until filler at {filler_start_time:.2f}s, BOOSTED during filler")
        filler_volume = bgm_volume * filler_volume_boost
        bgm_filter = (
            f"[1:a]"
            f"aloop=loop=-1:size=2147483647,"
            f"atrim=duration={duration:.3f},"
            f"volume={bgm_volume:.4f},"
            f"volume=enable='lte(t,{bgm_start:.3f})':volume=0,"
            f"afade=t=in:st={bgm_fade_start:.3f}:d={fade_seconds:.2f},"
            f"afade=t=out:st={fade_out_start:.2f}:d={fade_seconds:.2f}"
            f"[bgm_base];"
            f"[0:a]asplit=2[voice_out][sc];"
            f"[bgm_base][sc]sidechaincompress="
            f"threshold=0.015:ratio=12:attack=8:release=700:level_sc=1.0[bgm_sc];"
            f"[bgm_sc]volume=enable='gte(t,{mute_after_time:.3f})*lt(t,{filler_start_time:.3f})':volume=0[bgm_muted];"
            f"[bgm_muted]volume=enable='gte(t,{filler_start_time:.3f})':volume={filler_volume:.4f}[bgm_final];"
            f"[voice_out][bgm_final]amix=inputs=2:duration=first:normalize=0[outa]"
        )
    else:
        print(f"  📊 BGM: Sidechain until {mute_after_time:.2f}s, MUTED after")
        bgm_filter = (
            f"[1:a]"
            f"aloop=loop=-1:size=2147483647,"
            f"atrim=duration={duration:.3f},"
            f"volume={bgm_volume:.4f},"
            f"volume=enable='lte(t,{bgm_start:.3f})':volume=0,"
            f"afade=t=in:st={bgm_fade_start:.3f}:d={fade_seconds:.2f},"
            f"afade=t=out:st={fade_out_start:.2f}:d={fade_seconds:.2f}"
            f"[bgm_base];"
            f"[0:a]asplit=2[voice_out][sc];"
            f"[bgm_base][sc]sidechaincompress="
            f"threshold=0.015:ratio=12:attack=8:release=700:level_sc=1.0[bgm_sc];"
            f"[bgm_sc]volume=enable='gte(t,{mute_after_time:.3f})':volume=0[bgm_final];"
            f"[voice_out][bgm_final]amix=inputs=2:duration=first:normalize=0[outa]"
        )
 
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', bgm_path,
        '-filter_complex', bgm_filter,
        '-map', '0:v',
        '-map', '[outa]',
        '-c:v', 'copy',
        '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
        tmp_path
    ]
 
    print(f"\n🎵 Mixing BGM (volume={bgm_volume:.0%})...")
    success = _run(cmd, 'BGM mixing')
 
    if success and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 10_000:
        import time as _time
        for _a in range(6):
            try:
                os.replace(tmp_path, video_path)
                break
            except PermissionError:
                if _a < 5:
                    _time.sleep(1.5)
        print(f"  ✅ BGM mixed")
        return True
    else:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return False
 
 
def concatenate_segments(segment_paths: List[str], out_path: str,
                         target_duration: float = 0,
                         chunk_size: int = 6) -> bool:
    valid_paths = [s for s in segment_paths if os.path.exists(s)]
    if not valid_paths:
        return False
 
    n = len(valid_paths)
    print(f"  🔗 Joining {n} segments...")
 
    if n <= chunk_size:
        success = _concat_demuxer(valid_paths, out_path)
        if success and target_duration > 0:
            tmp = out_path + '_trim.mp4'
            if _run(['ffmpeg', '-y', '-i', out_path, '-t', str(target_duration),
                     '-c', 'copy', tmp], f'Trim to {target_duration:.1f}s'):
                if os.path.exists(tmp):
                    import time as _time
                    for _a in range(6):
                        try:
                            os.replace(tmp, out_path)
                            break
                        except PermissionError:
                            if _a < 5:
                                _time.sleep(1.5)
        return success
 
    chunks     = [valid_paths[i:i+chunk_size] for i in range(0, n, chunk_size)]
    tmp_dir    = tempfile.mkdtemp(prefix='bulletin_chunks_')
    chunk_files = []
 
    try:
 
        #         _media_info_cache.pop(chunk_out, None)
        #         chunk_files.append(chunk_out)
 
        
        import time
        import gc
 
        for idx, chunk in enumerate(chunks):
            chunk_out = os.path.join(tmp_dir, f'chunk_{idx:03d}.mp4')
 
            for c in chunk_files:
                exists = os.path.exists(c)
                dur = _video_duration(c) if exists else 0.0
                print(f"  [DEBUG-CHUNK] {os.path.basename(c)} | exists={exists} | dur={dur:.2f}s")
 
            print(f"  [SAFE-CONCAT] {len(chunk)} segments → {os.path.basename(chunk_out)}")
 
            if not _concat_demuxer(chunk, chunk_out):
                print(f"  ⚠️ Chunk {idx:03d} failed — skipping")
                continue
 
            if os.path.exists(chunk_out) and os.path.getsize(chunk_out) > 0:
                _media_info_cache.pop(chunk_out, None)
                chunk_files.append(chunk_out)
 
            # 🔥 CRITICAL FIXES
            time.sleep(0.3)     # throttle FFmpeg
            gc.collect()        # free Python memory
 
        time.sleep(0.5)  # let system breathe before final concat
 
        success = _concat_demuxer(chunk_files, out_path)
 
        gc.collect()
 
        if success and target_duration > 0:
            actual = _video_duration(out_path)
            # 5s tak overshoot allow karo — atempo drift normal hai
            # Sirf tab trim karo jab bohot zyada over ho
            if actual > target_duration + 5.0:
                tmp      = out_path + '_trim.mp4'
                trim_dur = target_duration - 0.2
                if _run(['ffmpeg', '-y', '-i', out_path, '-t', str(trim_dur),
                        '-af', 'asetpts=PTS-STARTPTS', '-c:v', 'copy', '-c:a', AUDIO_CODEC,
                        tmp], f'Trim to {trim_dur:.1f}s'):
                    if os.path.exists(tmp):
                        os.replace(tmp, out_path)
        return success
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
 
 
def build_freeze_frame_segment(video_path: str, out_path: str, duration: float = 2.0) -> bool:
    frame_path = None
    try:
        frame_path      = tempfile.mktemp(suffix='.png')
        duration_actual = _video_duration(video_path)
        frame_time      = max(0, duration_actual - 0.1)
 
        _run([
            'ffmpeg', '-y', '-ss', str(frame_time), '-i', video_path,
            '-vframes', '1', '-vf', 'scale=iw:ih', frame_path
        ], f'Extract last frame')
 
        if os.path.exists(frame_path):
            return _run([
                'ffmpeg', '-y',
                '-loop', '1', '-i', frame_path,
                '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo',
                '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
                '-c:a', 'aac', '-ar', '44100', '-ac', '2',
                '-vf', f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
                f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,'
                f'fps={FPS},format=yuv420p',
                '-t', str(duration),
                out_path
            ], f'Freeze frame {duration}s')
        return False
    except Exception as e:
        print(f"  ❌ Freeze frame error: {e}")
        return False
    finally:
        if frame_path and os.path.exists(frame_path):
            try:
                os.unlink(frame_path)
            except:
                pass
 
 
def build_image_slideshow(image_paths: List[str], audio_path: str,
                           logo_path: str, out_path: str,
                           max_duration: Optional[float] = None,
                           reporter_info: dict = None) -> bool:
    """
    Build a slideshow segment: images displayed evenly across audio duration.
    Each image shown for equal time. Logo overlay included.
    """
    if not image_paths:
        raw_dur  = _audio_duration(audio_path)
        duration = min(raw_dur, max_duration) if max_duration else raw_dur
        return _run([
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}',
            '-i', audio_path,
            '-vf', f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
            '-af', 'asetpts=PTS-STARTPTS',
            '-map', '0:v', '-map', '1:a',
            '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
            '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration), out_path
        ], f'Black fallback slideshow [{duration:.1f}s]')
 
    raw_dur  = _audio_duration(audio_path)
    duration = min(raw_dur, max_duration) if max_duration else raw_dur
 
    n_imgs        = len(image_paths)
    per_img_dur   = duration / n_imgs
 
    logo_ext      = Path(logo_path).suffix.lower() if logo_path else ''
    logo_is_video = _logo_is_animated(logo_path)
    has_logo      = bool(logo_path and os.path.exists(logo_path))

    if n_imgs == 1:
        # Single image — simple case
        scale = _get_scale_filter(image_paths[0])
        inputs      = ['-loop', '1', '-t', str(duration), '-i', image_paths[0]]
        input_index = 1

        logo_index = None
        if has_logo:
            inputs += _logo_input_args(logo_path, duration)
            logo_index   = input_index
            input_index += 1
 
        reporter_png   = None
        reporter_index = None
        if reporter_info:
            rname  = reporter_info.get('name', '').strip()
            rphoto = reporter_info.get('photo_path', '').strip()
            print(f"  [REPORTER-SLIDE1] name='{rname}' | photo='{rphoto}'")
            if rname or rphoto:
                reporter_png = _create_reporter_card_png(rname, rphoto)
            if reporter_png and os.path.exists(reporter_png):
                inputs += ['-loop', '1', '-t', str(duration), '-i', reporter_png]
                reporter_index = input_index
                input_index += 1
 
        _slide_gif_path    = None
        _slide_gif_index   = None
        _slide_location    = ''
        if reporter_info:
            _gif_src = reporter_info.get('gif_path', '').strip()
            _slide_location = reporter_info.get('location_name', '').strip()
            _slide_loc_display = _location_display_text(_slide_location) if _slide_location else ''
            if _gif_src and os.path.exists(_gif_src):
                _slide_gif_path = _create_gif_overlay(_gif_src, _slide_loc_display)
            if _slide_gif_path and os.path.exists(_slide_gif_path):
                inputs += ['-stream_loop', '-1', '-t', str(duration), '-i', _slide_gif_path]
                _slide_gif_index = input_index
                input_index += 1
                print(f"  🎞️  GIF overlay (slideshow) ready: {_slide_gif_path}")
 
        inputs += ['-i', audio_path]
        audio_index = input_index
 
        use_blur = _needs_blur_fill(image_paths[0])
        if has_logo:
            if use_blur:
                fc = (
                    _blur_fill_filter('[0:v]', '[blurred_base]') + ';'
                    f'[{logo_index}:v]scale=500:-1[logo];'
                    f'[blurred_base][logo]overlay=x=W-overlay_w-30:y=30,'
                    f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
                )
            else:
                fc = (f'[0:v]{scale}[scaled];'
                      f'[{logo_index}:v]scale=500:-1[logo];'
                      f'[scaled][logo]overlay=x=W-overlay_w-30:y=30,'
                      f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]')
        else:
            fc = _blur_fill_filter('[0:v]', '[outv]') if use_blur else f'[0:v]{scale},fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
 
        #            f";[outv]format=rgba[outv_rgba]"
        #            f";[outv_rgba][reporter_layer]overlay=0:0:enable='lte(t,{REPORTER_DURATION})'[after_reporter_s]")
 
        #                f";[after_reporter_s][gif_layer_s]overlay=0:0:"
        #                f"enable='gte(t,{REPORTER_DURATION})'[final_s]")
 
 
 
 
        _suffix, map_out = _reporter_gif_filter_suffix(reporter_index, _slide_gif_index, duration)
        fc += _suffix
 
        cmd = [
            'ffmpeg', '-y', *inputs,
            '-filter_complex', fc,
            '-map', map_out, '-map', f'{audio_index}:a',
            '-af', 'asetpts=PTS-STARTPTS',
            '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
            '-r', str(FPS),
            '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration), out_path
        ]
        result = _run(cmd, f'Slideshow 1 image [{duration:.1f}s]')
        if reporter_png and os.path.exists(reporter_png):
            try: os.unlink(reporter_png)
            except: pass
        if _slide_gif_path and os.path.exists(_slide_gif_path):
            try: os.unlink(_slide_gif_path)
            except: pass
        return result
 
    # Multiple images — render each image as separate silent segment, then concat + add audio
    tmp_dir  = tempfile.mkdtemp(prefix='slideshow_')
 
    try:
        img_segs = []
        for i, img_path in enumerate(image_paths):
            seg_path = os.path.join(tmp_dir, f'img_{i:03d}.mp4')
            scale    = _get_scale_filter(img_path)
            use_blur = _needs_blur_fill(img_path)
 
            if use_blur:
                fc_seg = _blur_fill_filter('[0:v]', '[blurred]') + f';[blurred]fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
            else:
                fc_seg = f'[0:v]{scale}[outv]'
 
            ok = _run([
                'ffmpeg', '-y',
                '-loop', '1', '-t', str(per_img_dur), '-i', img_path,
                '-filter_complex', fc_seg,
                '-map', '[outv]',
                '-an',
                '-r', str(FPS),
                '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
                '-video_track_timescale', '12800',
                '-t', str(per_img_dur), seg_path
            ], f'Slideshow img {i+1}/{n_imgs}')
            if ok and os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
                img_segs.append(seg_path)
            else:
                print(f'  ⚠️ Slideshow img {i+1}/{n_imgs} failed — skipping')
 
        if not img_segs:
            return False
 
        combined_path = os.path.join(tmp_dir, 'combined_silent.mp4')
        if not _concat_demuxer(img_segs, combined_path):
            return False
 
        logo_idx  = 0
        input_idx = 1
 
        inputs_final = ['-i', combined_path]
 
        if has_logo:
            if logo_is_video:
                inputs_final += ['-stream_loop', '-1', '-t', str(duration), '-i', logo_path]
            else:
                inputs_final += ['-i', logo_path]
            logo_in = input_idx
            input_idx += 1
        else:
            logo_in = None
 
        _multi_reporter_png   = None
        _multi_reporter_idx   = None
        _multi_gif_path       = None
        _multi_gif_idx        = None
        if reporter_info:
            rname  = reporter_info.get('name', '').strip()
            rphoto = reporter_info.get('photo_path', '').strip()
            print(f"  [REPORTER-SLIDEMULTI] name='{rname}' | photo='{rphoto}'")
            if rname or rphoto:
                _multi_reporter_png = _create_reporter_card_png(rname, rphoto)
            if _multi_reporter_png and os.path.exists(_multi_reporter_png):
                inputs_final += ['-loop', '1', '-t', str(duration), '-i', _multi_reporter_png]
                _multi_reporter_idx = input_idx
                input_idx += 1
 
            _gif_src  = reporter_info.get('gif_path', '').strip()
            _loc      = reporter_info.get('location_name', '').strip()
            _loc_disp = _location_display_text(_loc) if _loc else ''
            if _gif_src and os.path.exists(_gif_src):
                _multi_gif_path = _create_gif_overlay(_gif_src, _loc_disp)
            if _multi_gif_path and os.path.exists(_multi_gif_path):
                inputs_final += ['-stream_loop', '-1', '-t', str(duration), '-i', _multi_gif_path]
                _multi_gif_idx = input_idx
                input_idx += 1
                print(f"  🎞️  GIF overlay (slideshow-multi) ready: {_multi_gif_path}")
 
        inputs_final += ['-i', audio_path]
        audio_in = input_idx
 
        if logo_in is not None:
            fc_final = (
                f'[{logo_in}:v]scale=450:-1[logo];'
                f'[0:v][logo]overlay=x=W-overlay_w-20:y=20,'
                f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
            )
        else:
            fc_final = f'[0:v]fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
 
        #         f';[{_multi_reporter_idx}:v]scale={WIDTH}:{HEIGHT},format=rgba[rep_ml]'
        #         f';[outv]format=rgba[outv_ml_r]'
        #         f';[outv_ml_r][rep_ml]overlay=0:0:enable=\'lte(t,{REPORTER_DURATION})\'[after_rep_ml]'
        #     )
 
        #             f';[{_multi_gif_idx}:v]format=rgba[gif_ml]'
        #             f';[after_rep_ml][gif_ml]overlay=0:0:enable=\'gte(t,{REPORTER_DURATION})\'[final_ml]'
        #         )
 
 
 
        _suffix, map_out_multi = _reporter_gif_filter_suffix(_multi_reporter_idx, _multi_gif_idx, duration)
        fc_final += _suffix
 
        result = _run([
            'ffmpeg', '-y',
            *inputs_final,
            '-filter_complex', fc_final,
            '-map', map_out_multi,
            '-map', f'{audio_in}:a',
            '-af', 'asetpts=PTS-STARTPTS',
            '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
            '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration), out_path
        ], f'Slideshow {n_imgs} images + audio [{duration:.1f}s]')
 
        if _multi_reporter_png and os.path.exists(_multi_reporter_png):
            try: os.unlink(_multi_reporter_png)
            except: pass
        if _multi_gif_path and os.path.exists(_multi_gif_path):
            try: os.unlink(_multi_gif_path)
            except: pass
        return result
 
    finally:
        import shutil as _sh
        _sh.rmtree(tmp_dir, ignore_errors=True)
 
 
def build_multi_media_news_segment(
    intro_audio_path: str,
    analysis_audio_path: str,
    clip_video_path: str,
    clip_start: float,
    clip_end: float,
    intro_images: List[str],
    analysis_images: List[str],
    logo_path: str,
    out_path: str,
    seg_idx_start: int = 0,
    segments_dir: str = None,
    allocated_duration: float = None,
    reporter_info: dict = None,         # [FIX] reporter card ke liye
) -> Optional[List[str]]:
    """
    Build a multi-media news item with structure:
      [TTS Intro + image slideshow]
      → [Real video clip with original audio]
      → [TTS Analysis + image slideshow]
 
    Gap fill: if allocated_duration > intro+clip+analysis, extend clip into gap
    rather than using a logo filler.
    """
    if not segments_dir:
        segments_dir = tempfile.mkdtemp(prefix='multi_news_')
 
    # ── Measure actual TTS audio durations (post-atempo) ─────────────────────
    intro_tts_dur    = _audio_duration(intro_audio_path)    if intro_audio_path    else 0.0
    analysis_tts_dur = _audio_duration(analysis_audio_path) if analysis_audio_path else 0.0
 
    # ── Clip duration: base window, then extend to fill any gap ───────────────
    CLIP_MIN     = 3.0
    CLIP_DEFAULT = clip_end - clip_start   # use full editorial window
 
    if allocated_duration and allocated_duration > 0:
        # Remaining time after TTS = budget available for the clip
        clip_budget = allocated_duration - intro_tts_dur - analysis_tts_dur
        clip_budget = max(CLIP_MIN, clip_budget)
    else:
        clip_budget = CLIP_DEFAULT
 
    # Cap by actual video duration available after clip_start
    if clip_video_path and os.path.exists(clip_video_path):
        video_total_dur   = _video_duration(clip_video_path)
        max_from_video    = max(0.0, video_total_dur - clip_start)
        clip_final_dur    = min(clip_budget, max_from_video)
    else:
        clip_final_dur = min(clip_budget, CLIP_DEFAULT)
 
    clip_final_dur = max(CLIP_MIN, clip_final_dur)
    clip_use_end   = clip_start + clip_final_dur
 
    print(f"  📐 Clip budget: intro={intro_tts_dur:.1f}s + analysis={analysis_tts_dur:.1f}s "
          f"+ clip={clip_final_dur:.1f}s (allocated={allocated_duration or 'n/a'}s)")
 
    seg_idx    = seg_idx_start
    built_segs = []
 
    # ── [A] TTS Intro + image slideshow ──────────────────────────────────────
    if intro_audio_path and os.path.exists(intro_audio_path):
        intro_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mm_intro.mp4')
        seg_idx += 1
        ok = build_image_slideshow(intro_images, intro_audio_path, logo_path, intro_seg,
                                   reporter_info=reporter_info)   # FIX: reporter_info pass karo
        if ok and os.path.exists(intro_seg):
            built_segs.append(intro_seg)
            print(f"  ✅ Multi-media intro segment [{len(intro_images)} images]")
        else:
            print(f"  ❌ Multi-media intro segment failed")
 
    # ── [B] Real video clip (original audio) ─────────────────────────────────
    if clip_video_path and os.path.exists(clip_video_path) and clip_final_dur >= 3.0:
        clip_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mm_clip.mp4')
        seg_idx += 1
        #     'ffmpeg', '-y',
        #     '-ss', str(clip_start), '-to', str(clip_use_end),
        #     '-i', clip_video_path,
        #     *(
        #         ['-filter_complex', _blur_fill_filter('[0:v]', '[outv]'), '-map', '[outv]', '-map', '0:a']
        #     ),
        #     '-af', 'asetpts=PTS-STARTPTS',
        #     '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
        #     '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
        #     '-video_track_timescale', '12800',
        #     clip_seg
        # ], f'Multi-media real clip [{clip_start:.1f}s→{clip_use_end:.1f}s]')
 
        # BAAD:
        _has_logo   = bool(logo_path and os.path.exists(logo_path))
        _logo_ext   = Path(logo_path).suffix.lower() if logo_path else ''
        _logo_video = _logo_is_animated(logo_path)

        if _has_logo:
            _logo_inputs = _logo_input_args(logo_path, clip_final_dur)
            # Logo input index: clip is input 0, logo is input 1
            _logo_in_idx = 1
            _logo_scale = (
                f'[{_logo_in_idx}:v]scale=500:-1,fps={FPS},setpts=PTS-STARTPTS,format=yuva420p[logo];'
                if _logo_video else
                f'[{_logo_in_idx}:v]scale=500:-1,format=yuva420p[logo];'
            )
            _clip_trim = f'trim={clip_start}:{clip_use_end},setpts=PTS-STARTPTS'
            if _needs_blur_fill(clip_video_path):
                _fc = (
                    f'[0:v]{_clip_trim}[cliptrimmed];'
                    + _blur_fill_filter('[cliptrimmed]', '[base]') + ';'
                    + _logo_scale +
                    f'[base][logo]overlay=x=W-overlay_w-10:y=10,format=yuv420p,setpts=PTS-STARTPTS[outv]'
                )
            else:
                _fc = (
                    f'[0:v]{_clip_trim},scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p[base];'
                    + _logo_scale +
                    f'[base][logo]overlay=x=W-overlay_w-10:y=10,format=yuv420p,setpts=PTS-STARTPTS[outv]'
                )
            ok = _run([
                'ffmpeg', '-y',
                '-i', clip_video_path,
                *_logo_inputs,
                '-filter_complex', _fc,
                '-map', '[outv]', '-map', '0:a',
                '-af', f'atrim={clip_start}:{clip_use_end},asetpts=PTS-STARTPTS',
                '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
                '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
                '-video_track_timescale', '12800',
                clip_seg
            ], f'Multi-media real clip + logo [{clip_start:.1f}s→{clip_use_end:.1f}s]')
        else:
            ok = _run([
                'ffmpeg', '-y',
                '-ss', str(clip_start), '-to', str(clip_use_end),
                '-i', clip_video_path,
                *(
                    ['-filter_complex', _blur_fill_filter('[0:v]', '[outv]'), '-map', '[outv]', '-map', '0:a']
                    if _needs_blur_fill(clip_video_path)
                    else ['-vf', f'scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p,setpts=PTS-STARTPTS']
                ),
                '-af', 'asetpts=PTS-STARTPTS',
                '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
                '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
                '-video_track_timescale', '12800',
                clip_seg
            ], f'Multi-media real clip [{clip_start:.1f}s→{clip_use_end:.1f}s]')
        if ok and os.path.exists(clip_seg):
            built_segs.append(clip_seg)
            print(f"  ✅ Real clip [{clip_start:.1f}s→{clip_use_end:.1f}s]")
        else:
            print(f"  ❌ Real clip failed")
 
    # ── [C] TTS Analysis + image slideshow ───────────────────────────────────
    if analysis_audio_path and os.path.exists(analysis_audio_path):
        analysis_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mm_analysis.mp4')
        seg_idx += 1
        ok = build_image_slideshow(analysis_images, analysis_audio_path, logo_path, analysis_seg)
        if ok and os.path.exists(analysis_seg):
            built_segs.append(analysis_seg)
            print(f"  ✅ Multi-media analysis segment [{len(analysis_images)} images]")
        else:
            print(f"  ❌ Multi-media analysis segment failed")
 
    return built_segs if built_segs else None
 
 
def build_bulletin_video(bulletin_dir: str, logo_path: str,
                         intro_path: str,ticker_text: str = None) -> Optional[str]:
    print("\n" + "=" * 60)
    print("🎬 BUILDING BULLETIN VIDEO")
    print("=" * 60)
 
    manifest_path = os.path.join(bulletin_dir, 'bulletin_manifest.json')
    if not os.path.exists(manifest_path):
        print(f"❌ manifest not found")
        return None
 
    # Race condition fix: watcher manifest mein items add karta hai — retry karo agar abhi empty hai
    import time as _time
    for _retry in range(30):  # max 30s wait
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        items = manifest.get('items', [])
        if items:
            break
        print(f"⏳ Manifest items empty — retry {_retry+1}/30, 1s wait...")
        _time.sleep(1)
 
    duration_min  = manifest.get('duration_minutes', 0)
    bulletin_name = manifest.get('bulletin_name', 'bulletin')
 
    if not items:
        print("❌ Manifest items still empty after 30s — aborting")
        return None
 
    print(f"📋 {bulletin_name} | ⏱️  {duration_min}min | Items: {len(items)}")
    log.info(f"[CHECKPOINT-1] Manifest loaded | bulletin={bulletin_name} | duration_min={duration_min} | items={len(items)}")
    from config import INPUT_IMAGE_DIR, INPUT_VIDEO_DIR, PREFIX_IMAGE, PREFIX_VIDEO, BREAK_DURATION
 
    headlines_dir = os.path.join(bulletin_dir, 'headlines')
    scripts_dir   = os.path.join(bulletin_dir, 'scripts')
    segments_dir  = os.path.join(bulletin_dir, 'segments')
    os.makedirs(segments_dir, exist_ok=True)
 
    # ── Stale/corrupt segments clean karo (previous failed build se bach gayi files) ──
    for _seg in glob.glob(os.path.join(segments_dir, '*.mp4')):
        _probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', _seg],
            capture_output=True, text=True
        )
        if _probe.returncode != 0 or '"duration"' not in _probe.stdout:
            print(f"  🗑️  Corrupt segment removed: {os.path.basename(_seg)}")
            os.remove(_seg)
   
    # ── Helper: webhook_server ke liye item-ready marker likhna ──────────────
    # Ye marker webhook_server ka watcher thread pick up karta hai —
    # turant concat + incident API fire karne ke liye. Subprocess boundary
    # cross karne ka sabse clean tarika yahi hai.
    def _write_item_ready_marker(rank: int, item: dict, segments: list, reused: bool = False):
        if not reused and len(segments) == 1 and item.get('counter'):
            _save_to_item_cache(item.get('counter'), segments[0])
        marker_path = os.path.join(segments_dir, f'item_{rank:02d}_ready.json')
        try:
            with open(marker_path, 'w', encoding='utf-8') as _mf:
                json.dump({
                    'rank':       rank,
                    'counter':    item.get('counter'),
                    'media_type': item.get('media_type'),
                    'segments':   segments,
                    'reused':     reused,
                    'item':       item,   # full item dict — incident payload ke liye
                }, _mf, ensure_ascii=False)
            print(f"  📌 [rank={rank}] Item-ready marker written {'(reused)' if reused else ''} → {os.path.basename(marker_path)}")
        except Exception as _me:
            print(f"  ⚠️ [rank={rank}] Could not write item-ready marker: {_me}")
    # ─────────────────────────────────────────────────────────────────────────
 
    if not os.path.exists(intro_path):
        return None
 
    def find_input_media(counter: int, media_type: str) -> Optional[str]:
        type_map = {
            'image': (INPUT_IMAGE_DIR, PREFIX_IMAGE, ['.jpg', '.jpeg', '.png', '.webp', '.gif']),
            'video': (INPUT_VIDEO_DIR, PREFIX_VIDEO, ['.mp4', '.mov', '.avi', '.mkv', '.webm']),
        }
        if media_type not in type_map:
            return None
        directory, prefix, exts = type_map[media_type]
        for ext in exts:
            candidate = os.path.join(directory, f"{prefix}{counter}{ext}")
            if os.path.exists(candidate):
                return candidate
        # S3 fallback — download if missing locally
        try:
            import s3_storage as _s3
            for ext in exts:
                filename = f"{prefix}{counter}{ext}"
                local_path = os.path.join(directory, filename)
                s3_key = _s3.key_for_input(media_type, filename)
                if _s3.download_file(s3_key, local_path):
                    return local_path
        except Exception:
            pass
        return None
 
    valid_items = []
    for item in items:
        if item.get('type') == 'injection':   # ← YEH ADD KARO
            continue
        ha_p = os.path.join(headlines_dir, item.get('headline_audio', ''))
        sa_p = os.path.join(scripts_dir,   item.get('script_audio', ''))
        if os.path.exists(ha_p) and os.path.exists(sa_p):
            valid_items.append((item, ha_p, sa_p))
        else:
            print(f"⚠️ Skipping item rank={item.get('rank')} — audio files missing")
 
    if not valid_items:
        return None
 
    # ── target_seconds: total - injections (bulletin_builder ne manifest mein save kiya hai) ──
    _inject_items  = [it for it in items if it.get('type') == 'injection']
    _inject_total  = sum(it.get('duration', 0.0) for it in _inject_items)
    news_target_seconds  = duration_min * 60 - _inject_total   # news loop ke liye
    total_target_seconds = duration_min * 60                    # filler ke liye
    target_seconds       = news_target_seconds                  # existing code same rehta hai
    print(f"  [TARGET] total={total_target_seconds}s | injections={_inject_total:.1f}s → news_target={news_target_seconds:.1f}s")
 
    per_script_cap = None
    all_segments: List[str] = []
    seg_idx = 0
 
    # ── [1/4] Intro ──────────────────────────────────────────────────────────
    print("\n[1/4] Intro...")
    intro_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_intro.mp4')
    seg_idx += 1
    if not build_intro_segment(intro_path, intro_seg):
        return None
    all_segments.append(intro_seg)
    log.info(f"[CHECKPOINT-2] Intro built | seg={intro_seg} | dur={_video_duration(intro_seg):.2f}s")
    filler_png  = os.path.join(BASE_DIR, 'assets', 'filler.mp4')
    break_video = os.path.join(BASE_DIR, 'assets', 'break.mp4')
    break_news  = os.path.join(BASE_DIR, 'assets', 'cap1.mp4')
    break_media = break_video if os.path.exists(break_video) else filler_png

    intro_break_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_break_after_intro.mp4')
    seg_idx += 1
    if build_filler_segment(break_media, BREAK_DURATION, intro_break_seg):
        all_segments.append(intro_break_seg)

    from config import BASE_DIR as _BASE_DIR
    template_path = os.path.join(_BASE_DIR, 'assets', 'template4.mp4')
    if not os.path.exists(template_path):
        template_path = None
 
    # ── [2/4] News segments (FIRST — to know which items succeed) ────────────
    # FIX: Build news segments before headlines so we can skip orphan headlines
    print(f"\n[2/4] News ({len(valid_items)})...")
    news_seg_map: dict = {}   # rank → news_seg path (only if built successfully)
 
    for idx, (item, _, sa_p) in enumerate(valid_items):
        rank       = item['rank']
        counter    = item.get('counter')
        media_type = item.get('media_type', 'image')
        structure  = item.get('clip_structure', 'intro_clip_analysis')
        clip_start = item.get('clip_start')
        clip_end   = item.get('clip_end')

        # ── Cache reuse: skip rebuild if item video already exists ────────
        _cached = os.path.join(_ITEM_VIDEO_CACHE_DIR, f'item_{counter}_video.mp4')
        if counter and os.path.exists(_cached) and os.path.getsize(_cached) > 100_000:
            news_seg_map[rank] = [_cached]
            print(f"  ♻️  Item rank={rank} counter={counter} — reused from cache")
            _write_item_ready_marker(rank, item, [_cached], reused=True)
            continue
        # ─────────────────────────────────────────────────────────────────

        media_file = find_input_media(counter, media_type)
        
        intro_audio_name    = item.get('intro_audio_filename', '')
        analysis_audio_name = item.get('analysis_audio_filename', '')
        intro_ap    = os.path.join(scripts_dir, intro_audio_name)    if intro_audio_name    else None
        analysis_ap = os.path.join(scripts_dir, analysis_audio_name) if analysis_audio_name else None
 
        # Validate intro/analysis paths
        if intro_ap and not os.path.exists(intro_ap):
            print(f"  ⚠️ Intro audio missing: {intro_audio_name}")
            intro_ap = None
        if analysis_ap and not os.path.exists(analysis_ap):
            print(f"  ⚠️ Analysis audio missing: {analysis_audio_name}")
            analysis_ap = None
 
        clip_dur      = (clip_end - clip_start) if (clip_start is not None and clip_end is not None) else 0
        has_real_clip = (
            media_type == 'video' and media_file and
            clip_start is not None and clip_end is not None and
            clip_dur >= 5.0 and
            intro_ap is not None   # intro audio must exist for clip structure
        )
 
        # ── Multi-media item (has image slideshow list OR multiple videos) ──────
        multi_image_paths = item.get('multi_image_paths', [])
        multi_video_paths = item.get('multi_video_paths', [])
        clip_video_path   = item.get('clip_video_path')   # specific video file for clip
        is_multi_media    = bool(multi_image_paths) or bool(multi_video_paths)
 
        # ── Case: Multi-video only (no images) ───────────────────────────────
        # Guard: sirf tab jab 2+ videos ho (single video normal flow se handle hota hai)
        if multi_video_paths and len(multi_video_paths) >= 2 and not multi_image_paths:
            print(f"  🎬 Multi-video item rank={rank} | {len(multi_video_paths)} videos")
            all_vids = multi_video_paths  # primary already index-0 mein hai
 
            built = []
            n_vids = len(all_vids)
 
            for vi, vpath in enumerate(all_vids):
                if not vpath or not os.path.exists(vpath):
                    print(f"  ⚠️ Video {vi+1} not found: {vpath}")
                    continue
 
                v_seg_name = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mv_{rank:02d}_v{vi}.mp4')
                seg_idx += 1
 
                # First video → intro audio + reporter card
                # Last video  → analysis audio
                # Middle      → script audio
                if vi == 0 and intro_ap:
                    _ri = {
                        'name':          item.get('sender_name', ''),
                        'photo_path':    item.get('photo_path', ''),
                        'gif_path':      item.get('gif_path', ''),
                        'location_name': item.get('location_name', ''),
                    }
                    ok = build_news_segment(vpath, intro_ap, logo_path, v_seg_name,
                                            reporter_info=_ri)
                elif vi == n_vids - 1 and analysis_ap:
                    ok = build_news_segment(vpath, analysis_ap, logo_path, v_seg_name,
                                            reporter_info=None)
                else:
                    ok = build_news_segment(vpath, sa_p, logo_path, v_seg_name,
                                            reporter_info=None)
 
                if ok and os.path.exists(v_seg_name):
                    built.append(v_seg_name)
                    print(f"  ✅ Multi-video seg {vi+1}/{n_vids} rank={rank}")
                else:
                    print(f"  ❌ Multi-video seg {vi+1}/{n_vids} rank={rank} FAILED")
 
            if built:
                news_seg_map[rank] = built
                print(f"  ✅ Multi-video item rank={rank} | {len(built)} sub-segments")
                _write_item_ready_marker(rank, item, built)
            else:
                print(f"  ❌ Multi-video item rank={rank} FAILED — all video segments failed")
            continue
 
        if is_multi_media and has_real_clip:
            # Image distribution: split images between intro and analysis
            import math
            n_imgs        = len(multi_image_paths)
            half          = math.ceil(n_imgs / 2)          # 3→2, 4→2, 5→3
            intro_imgs    = multi_image_paths[:half] if n_imgs > 0 else []
            analysis_imgs = multi_image_paths[half:] if n_imgs > 1 else multi_image_paths[:]
 
            clip_vpath = clip_video_path if (clip_video_path and os.path.exists(clip_video_path)) else media_file
 
            print(f"  🗂️ Multi-media item rank={rank} | {n_imgs} images | clip: {os.path.basename(clip_vpath or '')} [{clip_start:.1f}s→{clip_end:.1f}s]")
 
            built = build_multi_media_news_segment(
                intro_audio_path=intro_ap,
                analysis_audio_path=analysis_ap,
                clip_video_path=clip_vpath,
                clip_start=clip_start,
                clip_end=clip_end,
                intro_images=intro_imgs,
                analysis_images=analysis_imgs,
                logo_path=logo_path,
                out_path=None,
                seg_idx_start=seg_idx,
                segments_dir=segments_dir,
                allocated_duration=float(item.get('allocated_duration') or 0.0),
                reporter_info={                          # FIX: reporter_info ab pass hoga
                    'name':          item.get('sender_name', ''),
                    'photo_path':    item.get('photo_path', ''),
                    'gif_path':      item.get('gif_path', ''),
                    'location_name': item.get('location_name', ''),
                },
            )
            if built:
                seg_idx += len(built)
                news_seg_map[rank] = built
                print(f"  ✅ Multi-media item rank={rank} | {len(built)} sub-segments")
                _write_item_ready_marker(rank, item, built)
            else:
                print(f"  ❌ Multi-media item rank={rank} FAILED")
            continue
 
        elif is_multi_media and not has_real_clip:
            _ri = {
                'name':          item.get('sender_name', ''),
                'photo_path':    item.get('photo_path', ''),
                'gif_path':      item.get('gif_path', ''),
                'location_name': item.get('location_name', ''),
            }
 
            # ── Mixed: images + video → Option A flow ────────────────────────
            # [intro TTS + image slideshow] → [video original audio] → [analysis TTS + image slideshow]
            if multi_image_paths and multi_video_paths:
                vpath_mixed = multi_video_paths[0] if os.path.exists(multi_video_paths[0]) else None
                print(f"  🗂️ Mixed image+video rank={rank} | {len(multi_image_paths)} images + video")
                built = []
 
                # [A] Intro TTS + image slideshow
                if intro_ap and os.path.exists(intro_ap):
                    intro_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mix_intro_{rank:02d}.mp4')
                    seg_idx += 1
                    ok = build_image_slideshow(multi_image_paths, intro_ap, logo_path, intro_seg, reporter_info=_ri)
                    if ok and os.path.exists(intro_seg):
                        built.append(intro_seg)
 
                # [B] Video with original audio
                if vpath_mixed and os.path.exists(vpath_mixed):
                    vid_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mix_vid_{rank:02d}.mp4')
                    seg_idx += 1
                    ok = build_news_segment(vpath_mixed, sa_p, logo_path, vid_seg, reporter_info=None)
                    if ok and os.path.exists(vid_seg):
                        built.append(vid_seg)
 
                # [C] Analysis TTS + image slideshow
                if analysis_ap and os.path.exists(analysis_ap):
                    analysis_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mix_analysis_{rank:02d}.mp4')
                    seg_idx += 1
                    ok = build_image_slideshow(multi_image_paths, analysis_ap, logo_path, analysis_seg, reporter_info=None)
                    if ok and os.path.exists(analysis_seg):
                        built.append(analysis_seg)
 
                # Fallback: agar intro/analysis audio nahi toh sirf video
                if not built:
                    fallback_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_mix_fallback_{rank:02d}.mp4')
                    seg_idx += 1
                    ok = build_news_segment(vpath_mixed or multi_video_paths[0], sa_p, logo_path, fallback_seg, reporter_info=_ri)
                    if ok and os.path.exists(fallback_seg):
                        built.append(fallback_seg)
 
                if built:
                    news_seg_map[rank] = built
                    print(f"  ✅ Mixed image+video rank={rank} | {len(built)} sub-segments")
                    _write_item_ready_marker(rank, item, built)
                else:
                    print(f"  ❌ Mixed image+video rank={rank} FAILED")
                continue
 
            # ── Images only → full slideshow with complete script audio ───────
            news_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_news_{rank:02d}.mp4')
            seg_idx += 1
            print(f"  [REPORTER-SLIDESHOW] name='{_ri['name']}' | photo='{_ri['photo_path']}'")
            ok = build_image_slideshow(multi_image_paths, sa_p, logo_path, news_seg, reporter_info=_ri)
            if ok and os.path.exists(news_seg):
                news_seg_map[rank] = [news_seg]
                print(f"  ✅ Images-only slideshow rank={rank} | {len(multi_image_paths)} images")
                _write_item_ready_marker(rank, item, [news_seg])
            else:
                print(f"  ❌ Images-only slideshow rank={rank} FAILED")
            continue
 
        hdur  = float(item.get('headline_duration', 0.0))
        alloc = float(item.get('allocated_duration') or 0.0)
 
        if has_real_clip:
            intro_tts_dur    = _audio_duration(intro_ap)    if intro_ap    else 0.0
            analysis_tts_dur = _audio_duration(analysis_ap) if analysis_ap else 0.0
 
            if alloc > 0:
                clip_budget = max(5.0, alloc - hdur - intro_tts_dur - analysis_tts_dur)
            else:
                clip_budget = clip_dur
 
            video_total_dur = _video_duration(media_file)
            max_from_video  = max(0.0, video_total_dur - clip_start)
            final_clip_dur  = max(5.0, min(clip_budget, max_from_video))
            clip_use_end    = clip_start + final_clip_dur
 
            # Intro TTS — reporter card CHAHIYE
            tts_intro_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_intro_{rank:02d}.mp4')
            seg_idx += 1
            clip_reporter_info = {
                'name':          item.get('sender_name', ''),
                'photo_path':    item.get('photo_path', ''),
                'gif_path':      item.get('gif_path', ''),       # FIX: missing tha
                'location_name': item.get('location_name', ''),  # FIX: missing tha
            }
            intro_ok = build_news_segment(media_file, intro_ap, logo_path, tts_intro_seg,
                                        reporter_info=clip_reporter_info)
 
            # Real clip — logo WITH fix
            clip_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_clip_{rank:02d}.mp4')
            seg_idx += 1
 
            _has_logo   = bool(logo_path and os.path.exists(logo_path))
            _logo_ext   = Path(logo_path).suffix.lower() if logo_path else ''
            _logo_video = _logo_is_animated(logo_path)

            if _has_logo:
                _logo_inputs = _logo_input_args(logo_path, final_clip_dur)
                _logo_scale  = (f'[1:v]scale=500:-1,fps={FPS},format=yuva420p[logo];'
                                if _logo_video else f'[1:v]scale=500:-1,format=yuva420p[logo];')
                _clip_trim   = f'trim={clip_start}:{clip_use_end},setpts=PTS-STARTPTS'
 
                if _needs_blur_fill(media_file):
                    _fc = (
                        f'[0:v]{_clip_trim}[ct];'
                        + _blur_fill_filter('[ct]', '[base]') + ';'
                        + _logo_scale +
                        f'[base][logo]overlay=x=W-overlay_w-10:y=10,format=yuv420p[outv]'
                    )
                else:
                    _fc = (
                        f'[0:v]{_clip_trim},scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p[base];'
                        + _logo_scale +
                        f'[base][logo]overlay=x=W-overlay_w-10:y=10,format=yuv420p[outv]'
                    )
 
                clip_ok = _run([
                    'ffmpeg', '-y',
                    '-i', media_file,
                    *_logo_inputs,
                    '-filter_complex', _fc,
                    '-map', '[outv]', '-map', '0:a',
                    '-af', f'atrim={clip_start}:{clip_use_end},asetpts=PTS-STARTPTS',
                    '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
                    '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
                    '-video_track_timescale', '12800',
                    clip_seg
                ], f'Real clip + logo [{clip_start:.1f}s→{clip_use_end:.1f}s]')
            else:
                clip_ok = _run([
                    'ffmpeg', '-y',
                    '-ss', str(clip_start), '-to', str(clip_use_end),
                    '-i', media_file,
                    *(
                        ['-filter_complex', _blur_fill_filter('[0:v]', '[outv]'), '-map', '[outv]', '-map', '0:a']
                        if _needs_blur_fill(media_file)
                        else ['-vf', f'scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p,setpts=PTS-STARTPTS']
                    ),
                    '-af', 'asetpts=PTS-STARTPTS',
                    '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
                    '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
                    '-video_track_timescale', '12800',
                    clip_seg
                ], f'Real clip [{clip_start:.1f}s→{clip_use_end:.1f}s]')
 
            # Analysis TTS — reporter card NAHI (None pass karo)
            tts_analysis_seg = None
            if analysis_ap:
                tts_analysis_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_analysis_{rank:02d}.mp4')
                seg_idx += 1
                build_news_segment(media_file, analysis_ap, logo_path, tts_analysis_seg,
                                reporter_info=None)  # ← FIX
 
            if structure == 'clip_intro_analysis':
                order = [clip_seg, tts_intro_seg, tts_analysis_seg]
            elif structure == 'intro_analysis_clip':
                order = [tts_intro_seg, tts_analysis_seg, clip_seg]
            else:
                order = [tts_intro_seg, clip_seg, tts_analysis_seg]
 
            built_segs = [s for s in order if s and os.path.exists(s)]
            if built_segs:
                news_seg_map[rank] = built_segs
                print(f"  ✅ Item rank={rank} | clip structure={structure} | {len(built_segs)} sub-segments")
                _write_item_ready_marker(rank, item, built_segs)
            else:
                print(f"  ❌ Item rank={rank} — all clip segments failed")
 
        else:
            # Image or video without valid clip — variable name change to avoid shadow
            news_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_news_{rank:02d}.mp4')
            seg_idx += 1
            item_reporter_info = {   # ← 'reporter_info' se rename kiya (Fault 3 fix)
                'name':          item.get('sender_name', ''),
                'photo_path':    item.get('photo_path', ''),
                'gif_path':      item.get('gif_path', ''),       # FIX: missing tha
                'location_name': item.get('location_name', ''),  # FIX: missing tha
            }
            if media_file:
                alloc_dur = (alloc - hdur) if alloc > 0 else None
                ok = build_news_segment(media_file, sa_p, logo_path, news_seg, alloc_dur,
                        reporter_info=item_reporter_info)
            else:
                raw_dur  = _audio_duration(sa_p)
                duration = min(raw_dur, per_script_cap) if per_script_cap else raw_dur
                ok = _run([
                    'ffmpeg', '-y',
                    '-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}',
                    '-i', sa_p,
                    '-vf', f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
                    '-af', 'asetpts=PTS-STARTPTS',
                    '-c:v', VIDEO_CODEC, '-b:v', VIDEO_BITRATE, '-maxrate', MAXRATE, '-bufsize', BUFSIZE, '-g', GOP_SIZE, '-keyint_min', GOP_SIZE, '-sc_threshold', '0', '-preset', PRESET,
                    '-c:a', AUDIO_CODEC, '-b:a', AUDIO_BITRATE, '-ar', '44100', '-ac', '2',
                    '-video_track_timescale', '12800',
                    '-map', '0:v', '-map', '1:a',
                    '-t', str(duration),
                    news_seg
                ], f'Black fallback rank={rank}')
 
            if ok and os.path.exists(news_seg):
                news_seg_map[rank] = [news_seg]
                print(f"  ✅ Item rank={rank} built")
                _write_item_ready_marker(rank, item, [news_seg])
            else:
                print(f"  ❌ Item rank={rank} FAILED — will skip its headline too")
 
    # ── [3/4] Headlines — only for items whose news segment succeeded ─────────
    print(f"\n[3/4] Headlines...")
    headline_segs: List[str] = []
 
    for idx, (item, ha_p, _) in enumerate(valid_items):
        rank         = item['rank']
        headline_text = item.get('headline', '')
 
        # Skip headline if news segment failed
        if rank not in news_seg_map:
            print(f"  ⏭️  Skipping headline rank={rank} (news segment failed)")
            continue
 
        if idx > 0:
            hl_break_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_hl_break_{rank:02d}.mp4')
            seg_idx += 1
            if build_filler_segment(break_media, BREAK_DURATION, hl_break_seg):
                headline_segs.append(hl_break_seg)
 
        card_path = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_headline_{rank:02d}.mp4')
        seg_idx += 1
 
        # FIX — item ka media_path resolve karke pass karo:
        item_media_for_card = None
        _mm_imgs = item.get('multi_image_paths', [])
        if _mm_imgs:
            item_media_for_card = _mm_imgs[0]  # pehli image left panel mein
        else:
            item_media_for_card = find_input_media(item.get('counter'), item.get('media_type', 'image'))
 
        if build_headline_card(headline_text, ha_p, card_path, template_path,
                            media_path=item_media_for_card):
            headline_segs.append(card_path)
 
    all_segments.extend(headline_segs)
    headlines_end_time = sum(_video_duration(seg) for seg in all_segments)
    log.info(f"[CHECKPOINT-3] Headlines done | count={sum(1 for s in all_segments if '_headline_' in s)} | headlines_end={headlines_end_time:.2f}s")
    hl_seg_count = len(all_segments)
    print(f"  📊 Headlines end: {headlines_end_time:.2f}s")
 
    # ── DEBUG START ──────────────────────────────────────────────
    print(f"  [DEBUG-BUDGET] target={target_seconds:.2f}s | headlines_end={headlines_end_time:.2f}s | remaining_budget={target_seconds - headlines_end_time:.2f}s")
    print(f"  [DEBUG-NEWSMAP] news_seg_map keys: {sorted(news_seg_map.keys())}")
    for r, segs in news_seg_map.items():
        total = sum(_video_duration(s) for s in segs if os.path.exists(s))
        print(f"    rank={r} → {len(segs)} seg(s), total={total:.2f}s")
    # ── DEBUG END ────────────────────────────────────────────────
 
    # 2-second break between news items (same as headlines)
    running = sum(_video_duration(s) for s in all_segments)
    added_news_count = 0  # track how many news items were added (for break insertion)
    for idx, (item, _, _) in enumerate(valid_items):
        rank = item['rank']
        if rank not in news_seg_map:
            continue
        segs = news_seg_map[rank]
        seg_total = sum(_video_duration(s) for s in segs)
 
        # ── DEBUG START ──────────────────────────────────────────────
        print(f"  [DEBUG-ADD] rank={rank} | seg_total={seg_total:.2f}s | running={running:.2f}s | target={target_seconds:.2f}s | will_fit={running + (BREAK_DURATION if added_news_count > 0 else 0) + seg_total <= target_seconds}")
        for s in segs:
            exists = os.path.exists(s)
            dur    = _video_duration(s) if exists else 0.0
            print(f"    [DEBUG-SEG] {os.path.basename(s)} | exists={exists} | dur={dur:.2f}s")
        # ── DEBUG END ────────────────────────────────────────────────
 
        # Break before this item (not before the first item)
        break_dur = BREAK_DURATION if added_news_count > 0 else 0.0
 
        if running + break_dur + seg_total <= target_seconds:
            # Insert break segment before this news item (except the first)
            #         all_segments.append(news_break_seg)
 
            news_break_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_news_break_{rank:02d}.mp4')
            seg_idx += 1
            if build_filler_segment(break_news, BREAK_DURATION, news_break_seg):
                all_segments.append(news_break_seg)
                running += BREAK_DURATION
 
            all_segments.extend(segs)
            running += seg_total
            added_news_count += 1
            print(f"  [ADD] rank={rank} | dur={seg_total:.2f}s | cumulative={running:.2f}s")
        else:
            print(f"  [SKIP] rank={rank} dropped — {running + break_dur + seg_total:.2f}s > {target_seconds}s")
    
    # Duration audit
    running = 0.0
    for seg_path in all_segments:
        dur = _video_duration(seg_path)
        running += dur
        name = os.path.basename(seg_path)
 
    print(f"\n  TARGET        = {target_seconds:.2f}s")
    print(f"  ACTUAL TOTAL  = {running:.2f}s")
    print(f"  DIFFERENCE    = {running - target_seconds:+.2f}s")
 
    # ── [3.5/4] Injections — manifest order mein, news items ke beech ──────────
    # bulletin_builder ne final_slots mein injections interleave kar diye hain.
    # Yahan hum un injections ko track karte hain taaki:
    #   1. Sahi position pe all_segments mein insert kar sakein
    #   2. Ticker skip_ranges calculate kar sakein (injection pe ticker OFF)
    #
    # NOTE: valid_items mein sirf 'news' type items hain — injections alag hain.
    # Injections ko news items ke beech insert karne ke liye:
    #   aur us position ke corresponding all_segments index pe insert karo.
 
    injection_skip_ranges = []   # ticker ke liye: [(start_sec, end_sec), ...]
 
    _news_rank_to_seg_end_idx = {}  # rank → all_segments index (last seg of that news item)
    _running_seg_idx = 0
    for _seg in all_segments:
        _running_seg_idx += 1
 
    # Manifest items iterate karo — injection slots ke liye position calculate karo
    _news_counter = 0  # kitne news items all_segments mein add hue
    _inj_queue    = [] # (insert_after_news_count, injection_dict)
 
    _manifest_items_ordered = manifest.get('items', [])
    _news_count_at_inj = 0
    for _mitem in _manifest_items_ordered:
        if _mitem.get('type') == 'news':
            _news_count_at_inj += 1
        elif _mitem.get('type') == 'injection':
            _inj_queue.append((_news_count_at_inj, _mitem))
 
    # all_segments rebuild with injections at correct positions
    # Current all_segments = [intro, intro_break, headlines..., news_items..., (filler pending)]
    # We need to inject between news items according to _inj_queue
 
    # Find where news items start in all_segments (after headlines)
    # Build a new segments list with injections interleaved
 
    # Collect only news segments (post-headlines portion, pre-filler)
    _news_segments_portion = all_segments[hl_seg_count:]  # news items + breaks
    _pre_news_segs         = all_segments[:hl_seg_count]  # intro + breaks + headlines
 
    # Count news "groups" (each news item may have multiple segs + 1 break seg)
    # We track by cumulative news item count using added_news_count (already computed above)
    # Simpler: rebuild from news_seg_map in order
 
    _rebuilt_news = []
    _news_done    = 0
    _inj_ptr      = 0
    _running_time_inj = sum(_video_duration(s) for s in _pre_news_segs)
 
    for _vi, (_vitem, _, _) in enumerate(valid_items):
        _rank = _vitem['rank']
        if _rank not in news_seg_map:
            continue
        _vsegs     = news_seg_map[_rank]
        _break_seg = None
 
        # Find the break seg for this rank in _news_segments_portion
        _break_name = f'_news_break_{_rank:02d}.mp4'
        for _s in _news_segments_portion:
            if _break_name in os.path.basename(_s):
                _break_seg = _s
                break
 
        if _break_seg:
            _rebuilt_news.append(_break_seg)
            _running_time_inj += _video_duration(_break_seg)
 
        for _vs in _vsegs:
            _rebuilt_news.append(_vs)
            _running_time_inj += _video_duration(_vs)
 
        _news_done += 1
 
        # Injection after this news item?
        while _inj_ptr < len(_inj_queue) and _inj_queue[_inj_ptr][0] == _news_done:
            _, _inj = _inj_queue[_inj_ptr]
            _inj_path = _inj.get('path', '')
            _inj_dur  = _inj.get('duration', 0.0)
            _inj_lbl  = _inj.get('label', 'injection')
 
            #     _rebuilt_news.append(_inj_path)
            #     injection_skip_ranges.append((_running_time_inj, _running_time_inj + _inj_dur))
 
            if _inj_path and os.path.exists(_inj_path) and _inj_dur > 0:
                _reenc_filename = os.path.basename(_inj_path).replace('.mp4', '_reenc.mp4')
                _reenc_path = os.path.join(S3_INJECT_LOCAL_DIR, _reenc_filename) 
                _reenc_stale = (
                    not os.path.exists(_reenc_path) or
                    os.path.getsize(_reenc_path) <= 100_000 or
                    os.path.getmtime(_inj_path) > os.path.getmtime(_reenc_path)
                )
                if _reenc_stale:
                    print(f"  [INJECT] Re-encoding {_inj_lbl} (cache stale or missing)...")
                    subprocess.run([
                        'ffmpeg', '-y', '-i', _inj_path,
                        '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,'
                            'pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
                        '-r', '25', '-c:v', 'libx264', '-preset', 'veryfast', '-b:v', '4000k', '-maxrate', '4000k', '-bufsize', '8000k', '-g', '50', '-keyint_min', '50', '-sc_threshold', '0',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '44100', '-ac', '2',
                        '-video_track_timescale', '12800',
                        '-movflags', '+faststart', _reenc_path
                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(_reenc_path) and os.path.getsize(_reenc_path) > 100_000:
                    _inj_path = _reenc_path
                    _inj_dur  = _video_duration(_reenc_path)
                _rebuilt_news.append(_inj_path)
                injection_skip_ranges.append((_running_time_inj, _running_time_inj + _inj_dur))
                _running_time_inj += _inj_dur
                print(f"  [INJECT] ✅ {_inj_lbl} | {_inj_dur:.1f}s after news#{_news_done} | ticker OFF [{_running_time_inj-_inj_dur:.1f}s→{_running_time_inj:.1f}s]")
            _inj_ptr += 1
 
    # Remaining injections at end
    while _inj_ptr < len(_inj_queue):
        _, _inj = _inj_queue[_inj_ptr]
        _inj_path = _inj.get('path', '')
        _inj_dur  = _inj.get('duration', 0.0)
        _inj_lbl  = _inj.get('label', 'injection')
        #     _rebuilt_news.append(_inj_path)
        #     injection_skip_ranges.append((_running_time_inj, _running_time_inj + _inj_dur))
        if _inj_path and os.path.exists(_inj_path) and _inj_dur > 0:
            _reenc_filename = os.path.basename(_inj_path).replace('.mp4', '_reenc.mp4')
            _reenc_path = os.path.join(S3_INJECT_LOCAL_DIR, _reenc_filename) 
            _reenc_stale = (
                not os.path.exists(_reenc_path) or
                os.path.getsize(_reenc_path) <= 100_000 or
                os.path.getmtime(_inj_path) > os.path.getmtime(_reenc_path)
            )
            if _reenc_stale:
                print(f"  [INJECT] Re-encoding {_inj_lbl} (cache stale or missing)...")
                subprocess.run([
                    'ffmpeg', '-y', '-i', _inj_path,
                    '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,'
                        'pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
                    '-r', '25', '-c:v', 'libx264', '-preset', 'veryfast', '-b:v', '4000k', '-maxrate', '4000k', '-bufsize', '8000k', '-g', '50', '-keyint_min', '50', '-sc_threshold', '0',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '44100', '-ac', '2',
                    '-video_track_timescale', '12800',
                    '-movflags', '+faststart', _reenc_path
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(_reenc_path) and os.path.getsize(_reenc_path) > 100_000:
                _inj_path = _reenc_path
                _inj_dur  = _video_duration(_reenc_path)
            _rebuilt_news.append(_inj_path)
            injection_skip_ranges.append((_running_time_inj, _running_time_inj + _inj_dur))
            _running_time_inj += _inj_dur
            print(f"  [INJECT] ✅ {_inj_lbl} (tail) | {_inj_dur:.1f}s | ticker OFF")
        _inj_ptr += 1
 
    all_segments = _pre_news_segs + _rebuilt_news
    print(f"  [INJECT] Done — {len(injection_skip_ranges)} injection ranges for ticker")
    # ─────────────────────────────────────────────────────────────────────────
 
    # ── [4/4] Filler ─────────────────────────────────────────────────────────
    log.info(f"[CHECKPOINT-4] News+injections done | total_segments={len(all_segments)}")
    actual_so_far    = sum(_video_duration(seg) for seg in all_segments)
    filler_start_time = actual_so_far
 
    filler_duration  = total_target_seconds - actual_so_far
 
    print(f"\n[4/4] Filler ({filler_duration:.1f}s)...")
 
    if filler_duration > 0.5:
        filler_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_filler.mp4')
        if build_filler_segment(filler_png, filler_duration, filler_seg):
            all_segments.append(filler_seg)
    elif filler_duration < -0.5:
        # Atempo drift se actual > target hua — trim mat karo, as-is accept karo
        print(f"  ⚠️  Actual content ({actual_so_far:.1f}s) slightly over target ({total_target_seconds}s) — accepting as-is")
 
        filler_start_time = None  # BGM boost nahi hoga
 
    if not all_segments:
        return None
 
    final_path     = os.path.join(bulletin_dir, f'{bulletin_name}.mp4')
    final_path_tmp = final_path + '_tmp.mp4'
 
    # ── DEBUG: all_segments order verify karo ──
    print(f"\n[DEBUG-ALL-SEGMENTS] Total={len(all_segments)}")
    for i, s in enumerate(all_segments):
        print(f"  [{i:02d}] {os.path.basename(s)} | dur={_video_duration(s):.2f}s")
    # ─────────────────────────────────────────
 
    if not concatenate_segments(all_segments, final_path_tmp, target_duration=0):
        log.info(f"[CHECKPOINT-5] Concat done | final_path_tmp={final_path_tmp} | exists={os.path.exists(final_path_tmp)}")
        return None
 
    import time as _time
    for _attempt in range(6):
        try:
            os.replace(final_path_tmp, final_path)
            break
        except PermissionError:
            if _attempt < 5:
                _time.sleep(1.5)
 
    from config import BGM_PATH, BGM_VOLUME, BGM_ENABLED, BGM_FADE_SECONDS
    if BGM_ENABLED:
        intro_dur_actual = _video_duration(intro_seg)
        add_background_music(
            video_path=final_path,
            bgm_path=BGM_PATH,
            bgm_volume=BGM_VOLUME,
            fade_seconds=BGM_FADE_SECONDS,
            intro_duration=intro_dur_actual,
            mute_after_time=headlines_end_time,
            filler_volume_boost=2.0,
            filler_start_time=filler_start_time,
        )
        log.info(f"[CHECKPOINT-6] BGM applied | final_path={final_path} | dur={_video_duration(final_path):.2f}s")
 
    # ── Ticker overlay (after BGM, final step) ───────────────────────────────
    #     subprocess.run([
    #         'ffmpeg', '-y', '-i', final_path,
    #         '-c:v', 'copy', '-c:a', 'copy',
    #         '-video_track_timescale', '12800',
    #         _norm_path
    #     ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #                 os.replace(_norm_path, final_path)
    #         _media_info_cache.pop(final_path, None)
 
            
    #                 os.replace(tickered_path, final_path)
    #             _sh.copy2(tickered_path, final_path)
    #             os.unlink(tickered_path)
 
    from config import TICKER_ENABLED
    if TICKER_ENABLED:
        # Step 1: Normalize raw → staging (hide final name from watchers)
        staging_path = final_path.replace('.mp4', '_staging.mp4')
        subprocess.run([
            'ffmpeg', '-y', '-i', final_path,
            '-c:v', 'copy', '-c:a', 'copy',
            '-video_track_timescale', '12800',
            staging_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
 
        if os.path.exists(staging_path) and os.path.getsize(staging_path) > 100_000:
            # Raw final ko delete — live system ko ab yeh nahi milega
            try:
                os.unlink(final_path)
            except Exception:
                pass
            _media_info_cache.pop(final_path, None)
 
            tickered_path = final_path.replace('.mp4', '_tickered.mp4')
 
            if add_ticker_overlay(staging_path, tickered_path,
                                filler_start=filler_start_time,
                                skip_ranges=injection_skip_ranges if injection_skip_ranges else None):
                # Ticker done → atomic rename to final name
                import time as _t2
                for _ta in range(6):
                    try:
                        os.replace(tickered_path, final_path)
                        break
                    except PermissionError:
                        if _ta < 5: _t2.sleep(1.5)
                else:
                    import shutil as _sh
                    _sh.copy2(tickered_path, final_path)
                    os.unlink(tickered_path)
                # Staging cleanup
                try:
                    os.unlink(staging_path)
                except Exception:
                    pass
            else:
                # Ticker failed → restore staging as final (fallback)
                print("  ⚠️  Ticker overlay failed — saving without ticker")
                os.replace(staging_path, final_path)
                
    log.info(f"[CHECKPOINT-7] Ticker stage done | final_path_exists={os.path.exists(final_path)} | size_mb={os.path.getsize(final_path)/1048576:.2f}")
    actual_dur = _video_duration(final_path)
    size_mb    = os.path.getsize(final_path) / (1024 * 1024)
 
    print(f"\n✅ Ready!")
    print(f"   📁 {final_path}")
    print(f"   ⏱️  {actual_dur:.1f}s ({actual_dur/60:.2f}min)")
    print("=" * 60)
 
    manifest['final_video']        = final_path
    manifest['segments_path']      = segments_dir
    manifest['actual_duration_s']  = round(actual_dur, 2)
    manifest['target_duration_s']  = target_seconds
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log.info(f"[CHECKPOINT-8] Manifest written with final_video={final_path} | actual_dur={actual_dur:.1f}s | target={target_seconds:.1f}s")
 
    _media_info_cache.clear()
 
    global _pw_instance, _pw_browser
    try:
        if _pw_browser is not None:
            _pw_browser.close()
            _pw_browser = None
        if _pw_instance is not None:
            _pw_instance.stop()
            _pw_instance = None
    except Exception:
        pass
 
    for _tmp_file in [
        final_path + '_tmp.mp4',
        final_path + '_bgm.mp4',
        final_path.replace('.mp4', '_tickered.mp4'),
    ]:
        if os.path.exists(_tmp_file):
            try:
                os.unlink(_tmp_file)
            except Exception:
                pass
 
    return final_path
 
 
#         os.path.join(bulletins_root, d)
#         and os.path.exists(os.path.join(bulletins_root, d, 'bulletin_manifest.json'))
#     ]
 
def _latest_bulletin_dir():
    from config import BASE_OUTPUT_DIR
    bulletins_root = os.path.join(BASE_OUTPUT_DIR, 'bulletins')
    if not os.path.exists(bulletins_root):
        return None
 
    folders = []
    # Scan 2 levels: bulletins/<location>/bul_<timestamp>/
    for loc_dir in os.listdir(bulletins_root):
        loc_path = os.path.join(bulletins_root, loc_dir)
        if not os.path.isdir(loc_path):
            continue
        # Check if loc_path itself has manifest (old flat structure)
        if os.path.exists(os.path.join(loc_path, 'bulletin_manifest.json')):
            folders.append(loc_path)
            continue
        # Otherwise scan inside (new location-wise structure)
        for bul_dir in os.listdir(loc_path):
            bul_path = os.path.join(loc_path, bul_dir)
            if (os.path.isdir(bul_path) and
                os.path.exists(os.path.join(bul_path, 'bulletin_manifest.json'))):
                folders.append(bul_path)
 
    return max(folders, key=os.path.getctime) if folders else None
 
if __name__ == '__main__':
    import sys
    from config import BASE_DIR
 
    if len(sys.argv) >= 2:
        bulletin_dir = sys.argv[1]
    else:
        bulletin_dir = _latest_bulletin_dir()
        if not bulletin_dir:
            from bulletin_builder import build_bulletin
            bulletin_dir = build_bulletin(5)
        if not bulletin_dir:
            sys.exit(1)
 
    logo  = sys.argv[2] if len(sys.argv) >= 3 else os.path.join(BASE_DIR, 'assets', 'logo3.mov')
    intro = sys.argv[3] if len(sys.argv) >= 4 else os.path.join(BASE_DIR, 'assets', 'intro4.mp4')
 
    result = build_bulletin_video(bulletin_dir, logo, intro)
    if result:
        print(f"Done: {result}")
    else:
        sys.exit(1)