"""
Video Builder - Playwright-based Telugu text rendering (HarfBuzz shaping)
Integrated Playwright for headline overlay only. Rest of pipeline untouched.
"""

import os
import json
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

WIDTH       = 1920
HEIGHT      = 1080
FPS         = 25
VIDEO_CODEC = 'libx264'
AUDIO_CODEC = 'aac'
PRESET      = 'fast'
CRF         = 23

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from PIL import Image, ImageDraw, ImageFont

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
    _local = os.path.join(os.path.dirname(__file__), 'NotoSansTelugu-VariableFont_wdth,wght.ttf')
    if os.path.exists(_local):
        TELUGU_FONT = _local
        print(f"✓ Local font: {_local}")
if not TELUGU_FONT or not os.path.exists(TELUGU_FONT):
    for _f in [r'C:\Windows\Fonts\NirmalaB.ttf', r'C:\Windows\Fonts\gautamib.ttf']:
        if os.path.exists(_f):
            TELUGU_FONT = _f
            break
if not TELUGU_FONT or not os.path.exists(TELUGU_FONT):
    print("❌ No Telugu font found! Run: apt-get install fonts-noto")
    TELUGU_FONT = 'Arial'


def _run(cmd: List[str], desc: str = '') -> bool:
    """Run an ffmpeg command, print output on failure."""
    print(f"  🔧 {desc or ' '.join(cmd[:4])}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"  ❌ ffmpeg error:\n{result.stderr.decode()[-800:]}")
        return False
    return True


def _audio_duration(audio_path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        audio_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(result.stdout.decode().strip())
    except Exception:
        return 5.0


def _video_duration(video_path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(result.stdout.decode().strip())
    except Exception:
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
        '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
        '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
        '-video_track_timescale', '12800',
        out_path
    ], 'Building intro segment')


def _create_headline_overlay(headline_text: str, width: int, height: int,
                              font_path: str) -> Optional[str]:
    """
    Playwright-based Telugu rendering via browser HarfBuzz shaping.
    Creates HTML, renders via Chromium, screenshots to PNG with transparency.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ Playwright not installed!")
        print("     pip install playwright && playwright install chromium")
        return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='_hl.png')
    tmp.close()
    overlay_png = tmp.name

    try:
        # Wrap long lines manually
        raw_lines = headline_text.strip().split('\n')
        lines = []
        MAX_CHARS = 18
        for raw in raw_lines:
            raw = raw.strip()
            if not raw:
                continue
            if len(raw) > MAX_CHARS:
                words = raw.split()
                cur = ""
                for w in words:
                    test = (cur + " " + w).strip() if cur else w
                    if len(test) <= MAX_CHARS:
                        cur = test
                    else:
                        if cur:
                            lines.append(cur)
                        cur = w
                if cur:
                    lines.append(cur)
            else:
                lines.append(raw)
        if not lines:
            lines = [headline_text.strip()]

        # Build HTML with proper transparent background
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
* {{ margin:0; padding:0; }}
html, body {{
  width:{width}px; height:{height}px;
  background:rgba(0,0,0,0);
  margin:0; padding:0;
}}
body {{
  display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:8px;
}}
.t {{
  font-family:'Noto Sans Telugu','Nirmala UI','Gautami',sans-serif;
  font-size:130px; font-weight:bold; color:white;
  text-shadow:-3px -3px 0 #000,3px -3px 0 #000,
              -3px 3px 0 #000,3px 3px 0 #000;
  line-height:1.2;
  white-space:nowrap;
}}
</style></head><body>
{"".join(f'<div class="t">{l}</div>' for l in lines)}
</body></html>"""

        html_file = os.path.abspath(tempfile.mktemp(suffix='.html'))
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html)

        with sync_playwright() as p:
            browser = p.chromium.launch()
            # omit_background=True for transparency support
            page = browser.new_page(
                viewport={"width": width, "height": height},
                extra_http_headers={"Content-Type": "text/html; charset=utf-8"}
            )
            page.goto(f"file:///{html_file}", wait_until="networkidle")
            # Screenshot with transparency
            page.screenshot(
                path=overlay_png,
                omit_background=True
            )
            browser.close()

        if os.path.exists(overlay_png):
            print(f"  ✓ Playwright Telugu overlay: {overlay_png}")
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
        if os.path.exists(html_file):
            try:
                os.unlink(html_file)
            except:
                pass


def build_headline_card(headline_text: str, audio_path: str, out_path: str,
                        template_path: str = None) -> bool:
    """PIL-based headline card with Playwright text rendering."""
    duration = _audio_duration(audio_path)
    has_template = bool(template_path and os.path.exists(template_path))

    overlay_png = _create_headline_overlay(headline_text, WIDTH, HEIGHT, TELUGU_FONT)

    out_flags = [
        '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
        '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
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

        if overlay_png and os.path.exists(overlay_png):
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

        return _run(cmd, f'Headline: {headline_text[:40]}')

    finally:
        if overlay_png and os.path.exists(overlay_png):
            try:
                os.unlink(overlay_png)
            except:
                pass


def build_news_segment(media_path: str, script_audio_path: str,
                       logo_path: str, out_path: str,
                       max_duration: Optional[float] = None) -> bool:
    raw_duration = _audio_duration(script_audio_path)

    if max_duration is not None and raw_duration > max_duration:
        print(f"    ✂️  Audio {raw_duration:.1f}s → {max_duration:.1f}s")
        duration = max_duration
    else:
        duration = raw_duration

    ext = Path(media_path).suffix.lower()
    is_image = ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']

    logo_ext = Path(logo_path).suffix.lower() if logo_path else ''
    logo_is_video = logo_ext in ['.mov', '.mp4', '.webm', '.avi']
    has_logo = bool(logo_path and os.path.exists(logo_path))

    scale_filter = (
        f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,'
        f'crop={WIDTH}:{HEIGHT}'
    )

    inputs = []
    input_index = 0

    if is_image:
        inputs += ['-loop', '1', '-t', str(duration), '-i', media_path]
    else:
        inputs += ['-stream_loop', '-1', '-t', str(duration), '-i', media_path]
    media_index = input_index
    input_index += 1

    logo_index = None
    if has_logo:
        if logo_is_video:
            inputs += ['-stream_loop', '-1', '-t', str(duration), '-i', logo_path]
        else:
            inputs += ['-i', logo_path]
        logo_index = input_index
        input_index += 1

    inputs += ['-i', script_audio_path]
    audio_index = input_index

    if has_logo:
        filter_complex = (
            f'[{media_index}:v]{scale_filter}[scaled];'
            f'[{logo_index}:v]scale=350:-1[logo];'
            f'[scaled][logo]overlay=x=W-overlay_w-20:y=20,'
            f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
        )
    else:
        filter_complex = (
            f'[{media_index}:v]{scale_filter},'
            f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[outv]'
        )

    cmd = [
        'ffmpeg', '-y',
        *inputs,
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-map', f'{audio_index}:a',
        '-af', 'asetpts=PTS-STARTPTS',
        '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
        '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
        '-video_track_timescale', '12800',
        '-t', str(duration),
        out_path
    ]
    return _run(cmd, f'News: {Path(media_path).name}  [{duration:.1f}s]')


def build_filler_segment(logo_path: str, duration: float, out_path: str) -> bool:
    if duration <= 0:
        return False

    logo_ext = Path(logo_path).suffix.lower() if logo_path else ''
    is_video = logo_ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']
    is_image = logo_ext in ['.png', '.jpg', '.jpeg', '.webp']
    has_logo_img = bool(logo_path and os.path.exists(logo_path) and is_image)
    has_logo_video = bool(logo_path and os.path.exists(logo_path) and is_video)

    if has_logo_video:
        return _run([
            'ffmpeg', '-y',
            '-stream_loop', '-1', '-t', str(duration), '-i', logo_path,
            '-vf', f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
                   f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,'
                   f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
            '-af', 'asetpts=PTS-STARTPTS',
            '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
            '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
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
            '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
            '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
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
            '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
            '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
            '-video_track_timescale', '12800',
            '-t', str(duration),
            out_path
        ], f'Break (black) [{duration:.2f}s]')


def _concat_demuxer(segment_paths: List[str], out_path: str) -> bool:
    valid_paths = [s for s in segment_paths if os.path.exists(s)]
    if not valid_paths:
        return False

    list_fd, list_path = tempfile.mkstemp(suffix='.txt')
    try:
        with os.fdopen(list_fd, 'w', encoding='utf-8') as f:
            for seg in valid_paths:
                abs_path = os.path.abspath(seg).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")

        return _run([
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_path,
            '-c', 'copy',
            out_path
        ], f'Concat {len(valid_paths)} segments')
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
    """Mix BGM with selective muting after headlines."""
    if not os.path.exists(bgm_path):
        print(f"  ⚠️  BGM not found: {bgm_path}")
        return False

    duration = _video_duration(video_path)
    fade_out_start = max(0.0, duration - fade_seconds)
    bgm_start = max(0.0, intro_duration)
    bgm_fade_start = bgm_start
    tmp_path = video_path + '_bgm.mp4'

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
        '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
        tmp_path
    ]

    print(f"\n🎵 Mixing BGM (volume={bgm_volume:.0%})...")
    success = _run(cmd, 'BGM mixing')

    if success and os.path.exists(tmp_path):
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

    chunks = [valid_paths[i:i+chunk_size] for i in range(0, n, chunk_size)]
    tmp_dir = tempfile.mkdtemp(prefix='bulletin_chunks_')
    chunk_files = []

    try:
        for idx, chunk in enumerate(chunks):
            chunk_out = os.path.join(tmp_dir, f'chunk_{idx:03d}.mp4')
            if not _concat_demuxer(chunk, chunk_out):
                return False
            chunk_files.append(chunk_out)

        success = _concat_demuxer(chunk_files, out_path)
        if success and target_duration > 0:
            tmp = out_path + '_trim.mp4'
            if _run(['ffmpeg', '-y', '-i', out_path, '-t', str(target_duration),
                     '-c', 'copy', tmp], f'Trim to {target_duration:.1f}s'):
                if os.path.exists(tmp):
                    os.replace(tmp, out_path)
        return success
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def build_freeze_frame_segment(video_path: str, out_path: str, duration: float = 2.0) -> bool:
    """Hold last frame from video for continuous duration (silent)."""
    try:
        frame_path = tempfile.mktemp(suffix='.png')
        duration_actual = _video_duration(video_path)
        frame_time = max(0, duration_actual - 0.1)
        
        _run([
            'ffmpeg', '-y', '-ss', str(frame_time), '-i', video_path,
            '-vframes', '1', frame_path
        ], f'Extract last frame')
        
        if os.path.exists(frame_path):
            result = _run([
                'ffmpeg', '-y',
                '-loop', '1', '-i', frame_path,
                '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo',
                '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
                '-c:a', 'aac', '-ar', '44100', '-ac', '2',
                '-vf', f'scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p',
                '-t', str(duration),
                out_path
            ], f'Freeze frame {duration}s')
            return result
        return False
    except Exception as e:
        print(f"  ❌ Freeze frame error: {e}")
        return False
    finally:
        if os.path.exists(frame_path):
            try:
                os.unlink(frame_path)
            except:
                pass


def build_bulletin_video(bulletin_dir: str, logo_path: str,
                         intro_path: str) -> Optional[str]:
    print("\n" + "=" * 60)
    print("🎬 BUILDING BULLETIN VIDEO")
    print("=" * 60)

    manifest_path = os.path.join(bulletin_dir, 'bulletin_manifest.json')
    if not os.path.exists(manifest_path):
        print(f"❌ manifest not found")
        return None

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    items = manifest.get('items', [])
    duration_min = manifest.get('duration_minutes', 0)
    bulletin_name = manifest.get('bulletin_name', 'bulletin')

    if not items:
        return None

    print(f"📋 {bulletin_name} | ⏱️  {duration_min}min | Items: {len(items)}")

    from config import INPUT_IMAGE_DIR, INPUT_VIDEO_DIR, PREFIX_IMAGE, PREFIX_VIDEO, BREAK_DURATION

    headlines_dir = os.path.join(bulletin_dir, 'headlines')
    scripts_dir = os.path.join(bulletin_dir, 'scripts')
    segments_dir = tempfile.mkdtemp(prefix=f"segments_{bulletin_name}_")

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
        return None

    valid_items = []
    for item in items:
        ha_p = os.path.join(headlines_dir, item.get('headline_audio', ''))
        sa_p = os.path.join(scripts_dir, item.get('script_audio', ''))
        if os.path.exists(ha_p) and os.path.exists(sa_p):
            valid_items.append((item, ha_p, sa_p))

    if not valid_items:
        return None

    target_seconds = duration_min * 60
    per_script_cap = None
    all_segments: List[str] = []
    seg_idx = 0

    print("\n[1/4] Intro...")
    intro_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_intro.mp4')
    seg_idx += 1
    if not build_intro_segment(intro_path, intro_seg):
        return None
    all_segments.append(intro_seg)

    filler_png = os.path.join(BASE_DIR, 'filler.jpeg')
    break_video = os.path.join(BASE_DIR, 'break.mp4')
    break_media = break_video if os.path.exists(break_video) else filler_png

    intro_break_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_break_after_intro.mp4')
    seg_idx += 1
    if build_filler_segment(break_media, BREAK_DURATION, intro_break_seg):
        all_segments.append(intro_break_seg)

    from config import BASE_DIR as _BASE_DIR
    template_path = os.path.join(_BASE_DIR, 'template.mp4')
    if not os.path.exists(template_path):
        template_path = None

    print(f"\n[2/4] Headlines ({len(valid_items)})...")
    for idx, (item, ha_p, _) in enumerate(valid_items):
        rank = item['rank']
        headline_text = item.get('headline', '')

        if idx > 0:
            hl_break_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_hl_break_{rank:02d}.mp4')
            seg_idx += 1
            if build_filler_segment(break_media, BREAK_DURATION, hl_break_seg):
                all_segments.append(hl_break_seg)

        card_path = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_headline_{rank:02d}.mp4')
        seg_idx += 1
        if build_headline_card(headline_text, ha_p, card_path, template_path):
            all_segments.append(card_path)

    headlines_end_time = sum(_video_duration(seg) for seg in all_segments)
    print(f"  📊 Headlines end: {headlines_end_time:.2f}s")

    print(f"\n[3/4] News ({len(valid_items)})...")
    for idx, (item, _, sa_p) in enumerate(valid_items):
        rank = item['rank']
        counter = item.get('counter')
        media_type = item.get('media_type', 'image')

        media_file = find_input_media(counter, media_type)
        news_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_news_{rank:02d}.mp4')
        seg_idx += 1

        if media_file:
            allocated_dur = float(item.get('script_duration', 0.0)) or None
            build_news_segment(media_file, sa_p, logo_path, news_seg, allocated_dur)
        else:
            raw_dur = _audio_duration(sa_p)
            duration = min(raw_dur, per_script_cap) if per_script_cap else raw_dur
            _run([
                'ffmpeg', '-y',
                '-f', 'lavfi', '-i', f'color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}',
                '-i', sa_p,
                '-vf', f'fps={FPS},format=yuv420p,setpts=PTS-STARTPTS',
                '-af', 'asetpts=PTS-STARTPTS',
                '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
                '-c:a', AUDIO_CODEC, '-ar', '44100', '-ac', '2',
                '-video_track_timescale', '12800',
                '-map', '0:v', '-map', '1:a',
                '-t', str(duration),
                news_seg
            ], f'Black fallback {rank}')

        if os.path.exists(news_seg):
            all_segments.append(news_seg)
            
            # Add 2-sec freeze frame of last frame
            freeze_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_freeze_{rank:02d}.mp4')
            seg_idx += 1
            if build_freeze_frame_segment(news_seg, freeze_seg, duration=2.0):
                all_segments.append(freeze_seg)

    actual_so_far = sum(_video_duration(seg) for seg in all_segments)
    filler_start_time = actual_so_far
    filler_duration = target_seconds - actual_so_far - 2
    print(f"\n[4/4] Filler ({filler_duration:.1f}s)...")

    if filler_duration > 0.1:
        filler_seg = os.path.join(segments_dir, f'{str(seg_idx).zfill(3)}_filler.mp4')
        if build_filler_segment(filler_png, filler_duration, filler_seg):
            all_segments.append(filler_seg)

    if not all_segments:
        return None

    final_path = os.path.join(bulletin_dir, f'{bulletin_name}.mp4')
    final_path_tmp = final_path + '_tmp.mp4'

    if not concatenate_segments(all_segments, final_path_tmp, target_duration=target_seconds):
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

    actual_dur = _video_duration(final_path)
    size_mb = os.path.getsize(final_path) / (1024 * 1024)

    print(f"\n✅ Ready!")
    print(f"   📁 {final_path}")
    print(f"   ⏱️  {actual_dur:.1f}s ({actual_dur/60:.2f}min)")
    print("=" * 60)

    manifest['final_video'] = final_path
    manifest['actual_duration_s'] = round(actual_dur, 2)
    manifest['target_duration_s'] = target_seconds
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    shutil.rmtree(segments_dir, ignore_errors=True)
    return final_path


def _latest_bulletin_dir():
    from config import BASE_OUTPUT_DIR
    bulletins_root = os.path.join(BASE_OUTPUT_DIR, 'bulletins')
    if not os.path.exists(bulletins_root):
        return None
    folders = [
        os.path.join(bulletins_root, d)
        for d in os.listdir(bulletins_root)
        if os.path.isdir(os.path.join(bulletins_root, d))
        and os.path.exists(os.path.join(bulletins_root, d, 'bulletin_manifest.json'))
    ]
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

    logo = sys.argv[2] if len(sys.argv) >= 3 else os.path.join(BASE_DIR, 'logo.mov')
    intro = sys.argv[3] if len(sys.argv) >= 4 else os.path.join(BASE_DIR, 'intro.mp4')

    result = build_bulletin_video(bulletin_dir, logo, intro)
    if result:
        print(f"Done: {result}")
    else:
        sys.exit(1)