"""
ticker_overlay.py
─────────────────
PIL se ticker strip images render karo (emoji + Telugu support),
phir FFmpeg mein scroll karo — drawtext use nahi hota.

Flow (concat approach):
  1. Headlines + Ad texts load karo
  2. Playwright se do PNG strips banao (headline_strip.png, ad_strip.png)
  3. Video ko 3 parts mein split karo:
       intro_clip  = video[0 → TICKER_START_T]            full screen, no ticker
       news_clip   = video[TICKER_START_T → filler_start]  ticker applied
       filler_clip = video[filler_start → end]             full screen, no ticker
  4. Sirf news_clip pe ticker apply karo
  5. Concat: intro + tickered_news + filler → final output
"""

import os
import json
import glob
import shutil
import tempfile
import subprocess
import base64
from datetime import datetime, timezone, timedelta

from config import BASE_DIR, BASE_OUTPUT_DIR, INTRO_VIDEO_DURATION

# ── Font resolution ───────────────────────────────────────────────────────────
_TELUGU_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansTelugu-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifTelugu-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansTelugu-Bold.ttf",
    os.path.join(BASE_DIR, 'NotoSansTelugu.ttf'),
    r'C:\Windows\Fonts\NirmalaB.ttf',
    r'C:\Windows\Fonts\gautamib.ttf',
]

_EMOJI_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    os.path.join(BASE_DIR, 'seguiemj.ttf'),
    r'C:\Windows\Fonts\seguisym.ttf',
]

def _find_font(candidates: list) -> str:
    for f in candidates:
        if f and os.path.exists(f):
            return f
    return ''

TELUGU_FONT = os.environ.get('TELUGU_FONT', '') or _find_font(_TELUGU_CANDIDATES)
EMOJI_FONT  = _find_font(_EMOJI_CANDIDATES)

if TELUGU_FONT:
    print(f"✓ [TICKER] Telugu font: {TELUGU_FONT}")
if EMOJI_FONT:
    print(f"✓ [TICKER] Emoji font:  {EMOJI_FONT}")
else:
    print("⚠️  [TICKER] Emoji font not found — emojis will render via Telugu font fallback")

# ── Ticker config ─────────────────────────────────────────────────────────────
TICKER_PNG_PATH = os.path.join(BASE_DIR, 'assets', 'ticker4.png')
ADS_FOLDER_PATH = os.path.join(BASE_DIR, 'assets', 'ads')
METADATA_FILE   = os.path.join(BASE_OUTPUT_DIR, 'metadata.json')

# ── Mic icon ──────────────────────────────────────────────────────────────────
mic_path = os.path.join(BASE_DIR, 'assets', 'kurnool_and_local.png')
try:
    with open(mic_path, 'rb') as f:
        mic_b64 = base64.b64encode(f.read()).decode()
    print(f"✓ [TICKER] Mic icon loaded: {mic_path}")
except Exception as e:
    mic_b64 = None
    print(f"⚠️  [TICKER] Mic icon not found ({e}) — fallback to ❙")

# Scroll speeds (px/sec)
HEADLINE_SPEED = 120
AD_SPEED       = 100

# ── Layout geometry ───────────────────────────────────────────────────────────
CONTENT_W = 1920
CONTENT_H = 930
TICKER_H  = 148
OUTPUT_H  = CONTENT_H + TICKER_H   # 1078

TICKER_OVERLAY_X = 0
TICKER_OVERLAY_Y = CONTENT_H       # 930

HEADLINE_BAND_Y   = TICKER_OVERLAY_Y
HEADLINE_BAND_H   = 66
HEADLINE_BAND_X   = 215
HEADLINE_SCROLL_W = CONTENT_W - HEADLINE_BAND_X   # 1705

AD_BAND_Y         = TICKER_OVERLAY_Y + 67   # 997
AD_BAND_H         = 81
AD_BAND_X         = 271
AD_SCROLL_W       = CONTENT_W - AD_BAND_X   # 1649

TICKER_START_T = float(INTRO_VIDEO_DURATION)

# Strip render settings
HEADLINE_FONTSIZE = 40
AD_FONTSIZE       = 40
HEADLINE_COLOR    = (255, 255, 255, 255)   # white
AD_COLOR          = (255, 215, 0,   255)   # yellow

AD_SEP = '      '

# FFmpeg codec
VIDEO_CODEC = 'libx264'
PRESET      = 'ultrafast'
CRF         = 23
# VIDEO_CODEC = "h264_nvenc"
# PRESET      = "p4"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _video_duration(path: str) -> float:
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return float(r.stdout.decode().strip())


# ── Data loaders ──────────────────────────────────────────────────────────────

def _load_24hr_headlines() -> list:
    """Returns list of headline strings."""
    # if not os.path.exists(METADATA_FILE):
    #     print("  ⚠️  [TICKER] metadata.json not found")
    #     return ['వార్తలు అందుబాటులో లేవు']
    # try:
    #     with open(METADATA_FILE, 'r', encoding='utf-8') as f:
    #         items = json.load(f)
    # except Exception as e:
    #     print(f"  ⚠️  [TICKER] metadata load error: {e}")
    #     return ['వార్తలు అందుబాటులో లేవు']
    try:
        import db as _db
        items = _db.fetchall(
            "SELECT headline, timestamp FROM news_items "
            "WHERE timestamp::timestamptz >= NOW() - INTERVAL '24 hours' "
            "ORDER BY counter ASC"
        )
    except Exception as e:
        print(f"  ⚠️  [TICKER] DB load error: {e}")
        return ['వార్తలు అందుబాటులో లేవు']

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    texts  = []
    for item in items:
        ts_str = item.get('timestamp', '')
        try:
            ts_str = str(ts_str)
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except Exception:
            pass
        hl = (item.get('headline') or '').strip()
        if hl:
            texts.append(hl)

    if not texts:
        # Fallback — last 24hrs mein nahi mila, all-time latest lo
        print("  ⚠️  [TICKER] No headlines in last 24hrs — using latest available")
        for item in items:
            hl = (item.get('headline') or '').strip()
            if hl:
                texts.append(hl)

    if not texts:
        return ['వార్తలు అందుబాటులో లేవు']

    print(f"  ✅ [TICKER] {len(texts)} headlines loaded")
    return texts


def _load_ad_texts() -> str:
    os.makedirs(ADS_FOLDER_PATH, exist_ok=True)
    files = sorted(glob.glob(os.path.join(ADS_FOLDER_PATH, '*.txt')))
    if not files:
        print("  ⚠️  [TICKER] No ad files found")
        return ' '

    lines = []
    for fp in files:
        try:
            txt = open(fp, 'r', encoding='utf-8').read().strip()
            for line in txt.splitlines():
                line = line.strip()
                if line:
                    lines.append(line)
        except Exception as e:
            print(f"  ⚠️  [TICKER] Ad read error {os.path.basename(fp)}: {e}")

    if not lines:
        return ' '

    print(f"  ✅ [TICKER] {len(lines)} ad lines loaded")
    return f'  {AD_SEP}  '.join(lines)


# ── HTML builders ─────────────────────────────────────────────────────────────

def _build_headline_html(headlines: list, font_size: int,
                          color: tuple, band_h: int,
                          est_w: int, repeats: int) -> str:
    r, g, b, _ = color

    if mic_b64:
        sep = (
            f'<img src="data:image/png;base64,{mic_b64}" '
            f'style="height:{int(font_size * 1.6)}px;vertical-align:middle;margin:0 25px;">'
            # f'style="height:100px;vertical-align:middle;margin:0 25px;">'
        )
    else:
        sep = '   ❙   '

    single_run   = sep.join(headlines)
    full_content = (single_run + f'  {sep}  ') * repeats

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
* {{margin:0;padding:0;}}
html,body {{width:{est_w}px;height:{band_h}px;background:rgba(0,0,0,0);}}
.t {{
    font-family:'Noto Sans Telugu','Nirmala UI',sans-serif;
    font-size:{font_size}px; font-weight:600;
    color:rgb({r},{g},{b});
    white-space:nowrap; line-height:{band_h}px;
    padding-left:10px;
    display:flex; align-items:center;
}}
</style>
</head><body><div class="t">{full_content}</div></body></html>"""


def _build_ad_html(ad_text: str, font_size: int,
                   color: tuple, band_h: int,
                   est_w: int, repeats: int) -> str:
    r, g, b, _ = color
    full_content = (ad_text + f'  {AD_SEP}  ') * repeats

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
* {{margin:0;padding:0;}}
html,body {{width:{est_w}px;height:{band_h}px;background:rgba(0,0,0,0);}}
.t {{
    font-family:'Noto Sans Telugu','Nirmala UI',sans-serif;
    font-size:{font_size}px; font-weight:600;
    color:rgb({r},{g},{b});
    white-space:nowrap; line-height:{band_h}px;
    padding-left:10px;
}}
</style>
</head><body><div class="t">{full_content}</div></body></html>"""


# ── Strip renderer ────────────────────────────────────────────────────────────

def _render_strips_both(headlines: list, ad_text: str,
                         hl_path: str, ad_path: str) -> bool:
    """Dono strips ek hi Playwright browser session mein render karo."""
    import threading
    import queue as _queue
    result_q = _queue.Queue()

    def _run():
        try:
            from playwright.sync_api import sync_playwright
            from PIL import Image

            with sync_playwright() as p:
                browser = p.chromium.launch(args=['--no-sandbox', '--disable-gpu'])

                # ── Headline strip ────────────────────────────────────────
                hl_single_w = max(
                    sum(len(h) for h in headlines) * HEADLINE_FONTSIZE + 200,
                    3000
                )
                hl_repeats = max(3, 30000 // hl_single_w)
                hl_est_w   = min(hl_single_w * hl_repeats, 30000)

                hl_html = _build_headline_html(
                    headlines, HEADLINE_FONTSIZE, HEADLINE_COLOR,
                    HEADLINE_BAND_H, hl_est_w, hl_repeats
                )
                tmp_hl_html = tempfile.mktemp(suffix='_hl.html')
                tmp_hl_png  = tempfile.mktemp(suffix='_hl.png')
                with open(tmp_hl_html, 'w', encoding='utf-8') as f:
                    f.write(hl_html)

                page = browser.new_page(viewport={"width": hl_est_w, "height": HEADLINE_BAND_H})
                page.goto(f"file:///{tmp_hl_html}", wait_until="networkidle")
                page.screenshot(path=tmp_hl_png, omit_background=True)
                page.close()
                os.unlink(tmp_hl_html)

                img = Image.open(tmp_hl_png).convert('RGBA')
                doubled = Image.new('RGBA', (img.width * 2, HEADLINE_BAND_H), (0, 0, 0, 0))
                doubled.paste(img, (0, 0))
                doubled.paste(img, (img.width, 0))
                doubled.save(hl_path, 'PNG')
                print(f"  🖼️  [TICKER] Headline strip: {img.width * 2}×{HEADLINE_BAND_H}px")
                img.close()
                doubled.close()
                os.unlink(tmp_hl_png)

                # ── Ad strip ─────────────────────────────────────────────
                ad_single_w = max(len(ad_text) * AD_FONTSIZE, 3000)
                ad_repeats  = max(3, 30000 // ad_single_w)
                ad_est_w    = min(ad_single_w * ad_repeats, 30000)

                ad_html = _build_ad_html(
                    ad_text, AD_FONTSIZE, AD_COLOR,
                    AD_BAND_H, ad_est_w, ad_repeats
                )
                tmp_ad_html = tempfile.mktemp(suffix='_ad.html')
                tmp_ad_png  = tempfile.mktemp(suffix='_ad.png')
                with open(tmp_ad_html, 'w', encoding='utf-8') as f:
                    f.write(ad_html)

                page = browser.new_page(viewport={"width": ad_est_w, "height": AD_BAND_H})
                page.goto(f"file:///{tmp_ad_html}", wait_until="networkidle")
                page.screenshot(path=tmp_ad_png, omit_background=True)
                page.close()
                os.unlink(tmp_ad_html)

                img = Image.open(tmp_ad_png).convert('RGBA')
                doubled = Image.new('RGBA', (img.width * 2, AD_BAND_H), (0, 0, 0, 0))
                doubled.paste(img, (0, 0))
                doubled.paste(img, (img.width, 0))
                doubled.save(ad_path, 'PNG')
                print(f"  🖼️  [TICKER] Ad strip: {img.width * 2}×{AD_BAND_H}px")
                img.close()
                doubled.close()
                os.unlink(tmp_ad_png)

                browser.close()

            result_q.put(True)

        except Exception as e:
            import traceback
            print(f"  ❌ [TICKER] Strip error: {e}")
            traceback.print_exc()
            result_q.put(False)

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=120)
    return result_q.get() if not result_q.empty() else False

# def _render_strips_both(headlines: list, ad_text: str,
#                          hl_path: str, ad_path: str) -> bool:
#     """
#     Both ticker strips via the shared renderer.

#     Strategy: render ONE tile (single pass, ~3-5000px max), then PIL doubles
#     it. FFmpeg's mod(t*speed, tile_width) gives infinite seamless scroll —
#     requirement is just tile_width >= SCROLL_WINDOW_WIDTH (1705 / 1649).

#     No more 30000px viewports → Chromium never OOMs on this call.
#     """
#     try:
#         from PIL import Image
#         from pw_renderer import renderer

#         # ── Headline strip ──────────────────────────────────────────────────
#         # Tile must be >= scroll window (1705) for seamless wrap. Add a margin.
#         # Cap at 6000 — even very long headlines look fine wrapped/scrolled.
#         hl_natural = sum(len(h) for h in headlines) * HEADLINE_FONTSIZE + 200
#         hl_tile_w  = max(min(hl_natural, 6000), HEADLINE_SCROLL_W + 500)

#         hl_html = _build_headline_html(
#             headlines, HEADLINE_FONTSIZE, HEADLINE_COLOR,
#             HEADLINE_BAND_H, hl_tile_w, 1,        # repeats = 1
#         )

#         tmp_hl_png = renderer.render(
#             html=hl_html,
#             viewport={"width": hl_tile_w, "height": HEADLINE_BAND_H},
#         )
#         if tmp_hl_png is None:
#             print(f"  ❌ [TICKER] Headline render returned None")
#             return False

#         img = Image.open(tmp_hl_png).convert("RGBA")
#         # Double horizontally so FFmpeg's mod-scroll wraps seamlessly.
#         doubled = Image.new("RGBA", (img.width * 2, HEADLINE_BAND_H), (0, 0, 0, 0))
#         doubled.paste(img, (0, 0))
#         doubled.paste(img, (img.width, 0))
#         doubled.save(hl_path, "PNG")
#         print(f"  🖼️  [TICKER] Headline strip: tile={img.width}px → doubled={img.width*2}×{HEADLINE_BAND_H}")
#         img.close()
#         doubled.close()

#         # ── Ad strip ────────────────────────────────────────────────────────
#         ad_natural = len(ad_text) * AD_FONTSIZE + 200
#         ad_tile_w  = max(min(ad_natural, 6000), AD_SCROLL_W + 500)

#         ad_html = _build_ad_html(
#             ad_text, AD_FONTSIZE, AD_COLOR,
#             AD_BAND_H, ad_tile_w, 1,
#         )

#         tmp_ad_png = renderer.render(
#             html=ad_html,
#             viewport={"width": ad_tile_w, "height": AD_BAND_H},
#         )
#         if tmp_ad_png is None:
#             print(f"  ❌ [TICKER] Ad render returned None")
#             return False

#         img = Image.open(tmp_ad_png).convert("RGBA")
#         doubled = Image.new("RGBA", (img.width * 2, AD_BAND_H), (0, 0, 0, 0))
#         doubled.paste(img, (0, 0))
#         doubled.paste(img, (img.width, 0))
#         doubled.save(ad_path, "PNG")
#         print(f"  🖼️  [TICKER] Ad strip: tile={img.width}px → doubled={img.width*2}×{AD_BAND_H}")
#         img.close()
#         doubled.close()

#         return True

#     except Exception as e:
#         import traceback
#         print(f"  ❌ [TICKER] Strip error: {e}")
#         traceback.print_exc()
#         return False


# ── Segment trimmers ──────────────────────────────────────────────────────────

def _trim_clip(src: str, out: str, start: float, end: float):
    """src se [start, end] clip nikalo — scale to OUTPUT_H (full screen)."""
    subprocess.run([
        'ffmpeg', '-y',
        '-ss', str(start), '-t', str(end - start),
        '-i', src,
        '-vf', f'scale={CONTENT_W}:{OUTPUT_H}',
        '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
        '-c:a', 'aac', '-b:a', '192k',
        '-video_track_timescale', '12800',
        out
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def _apply_ticker_to_clip(src: str, out: str,
                           hl_strip: str, ad_strip: str,
                           hl_w: int, ad_w: int):
    """
    Sirf news_clip pe ticker bands + scrolling text apply karo.
    Output: 1920×1078 with ticker3.png bands at bottom.
    """
    fc = (
        f"[0:v]scale={CONTENT_W}:{CONTENT_H}[news_v];"
        f"[news_v]pad={CONTENT_W}:{OUTPUT_H}:0:0:black[padded];"
        f"[padded][1:v]overlay={TICKER_OVERLAY_X}:{TICKER_OVERLAY_Y}[ticker_base];"

        f"[2:v]crop={HEADLINE_SCROLL_W}:{HEADLINE_BAND_H}:"
        f"mod(t*{HEADLINE_SPEED}\\,{hl_w}):0[hl_scroll];"
        f"[ticker_base][hl_scroll]overlay={HEADLINE_BAND_X}:{HEADLINE_BAND_Y}[after_hl];"

        f"[3:v]crop={AD_SCROLL_W}:{AD_BAND_H}:"
        f"mod(t*{AD_SPEED}\\,{ad_w}):0[ad_scroll];"
        f"[after_hl][ad_scroll]overlay={AD_BAND_X}:{AD_BAND_Y}[outv]"
    )

    try:
        dur = _video_duration(src)
    except Exception:
        dur = None

    cmd = [
        'ffmpeg', '-y',
        '-threads', '0', '-filter_threads', '0',
        '-i', src,
        '-loop', '1', '-i', TICKER_PNG_PATH,
        '-loop', '1', '-i', hl_strip,
        '-loop', '1', '-i', ad_strip,
        '-filter_complex', fc,
        '-map', '[outv]', '-map', '0:a',
        '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
        '-c:a', 'copy',
        '-video_track_timescale', '12800',
    ]
    if dur:
        cmd += ['-t', str(dur)]
    cmd.append(out)

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg ticker failed:\n{result.stderr.decode()[-3000:]}")


def _concat_clips(clips: list, out: str):
    """Fast concat — no re-encode."""
    list_file = tempfile.mktemp(suffix='_concat.txt')
    with open(list_file, 'w', encoding='utf-8') as f:
        for c in clips:
            f.write(f"file '{c}'\n")

    result = subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', list_file, '-c', 'copy', out
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    os.unlink(list_file)
    if result.returncode != 0:
        raise RuntimeError(f"Concat failed:\n{result.stderr.decode()[-2000:]}")


# ── Main function ─────────────────────────────────────────────────────────────

def add_ticker_overlay(video_path: str, out_path: str,
                       filler_start: float = None,
                       skip_ranges: list = None) -> bool:
    import time as _time

    print("\n" + "─" * 50)
    print("📺 Adding ticker overlay (single-pass approach)...")

    if not os.path.exists(video_path):
        print(f"  ❌ Input video not found: {video_path}"); return False
    if not os.path.exists(TICKER_PNG_PATH):
        print(f"  ❌ ticker3.png not found: {TICKER_PNG_PATH}"); return False

    headlines = _load_24hr_headlines()
    ad_text   = _load_ad_texts()

    try:
        duration = _video_duration(video_path)
    except Exception as e:
        print(f"  ❌ ffprobe error: {e}"); return False

    print(f"  ℹ️  total={duration:.2f}s | ticker_start={TICKER_START_T}s | filler_start={filler_start}s")

    tmp_dir       = tempfile.mkdtemp(prefix='ticker_work_')
    hl_strip_path = os.path.join(tmp_dir, 'headline_strip.png')
    ad_strip_path = os.path.join(tmp_dir, 'ad_strip.png')

    try:
        # Step 1: Render strips
        t0 = _time.time()
        if not _render_strips_both(headlines, ad_text, hl_strip_path, ad_strip_path):
            print("  ❌ Strip render failed"); return False
        print(f"  ⏱️  Strips in {_time.time()-t0:.1f}s")

        from PIL import Image as _Img
        with _Img.open(hl_strip_path) as im:
            hl_w = im.width // 2
        with _Img.open(ad_strip_path) as im:
            ad_w = im.width // 2
        print(f"  ℹ️  strip widths → hl={hl_w}px  ad={ad_w}px")

        # Step 2: Calculate ticker-ON ranges (inverse of skip_ranges)
        news_end = filler_start if filler_start else duration

        ticker_on_ranges = []
        cursor = TICKER_START_T
        for (skip_s, skip_e) in sorted(skip_ranges or [], key=lambda x: x[0]):
            skip_s = max(skip_s, TICKER_START_T)
            skip_e = min(skip_e, news_end)
            if skip_s >= skip_e:
                continue
            if cursor < skip_s:
                ticker_on_ranges.append((cursor, skip_s))
            cursor = skip_e
        if cursor < news_end:
            ticker_on_ranges.append((cursor, news_end))

        print(f"  ℹ️  Ticker ON ranges: {[(round(s,1), round(e,1)) for s,e in ticker_on_ranges]}")

        # FFmpeg enable expression
        if ticker_on_ranges:
            enable_expr = '+'.join([f'between(t,{s:.3f},{e:.3f})' for s, e in ticker_on_ranges])
        else:
            enable_expr = '0'

        # Step 3: Single-pass FFmpeg — no splitting, no concat, no drift
        t0 = _time.time()

        fc = (
            # Full screen version (1920x1078, no black bar) — always
            f"[0:v]scale={CONTENT_W}:{OUTPUT_H}[full];"

            # Ticker composite (930 + 148 black + ticker bands) — only ON ranges
            f"[0:v]scale={CONTENT_W}:{CONTENT_H}[cnews];"
            f"[cnews]pad={CONTENT_W}:{OUTPUT_H}:0:0:black[padded];"
            f"[padded][1:v]overlay={TICKER_OVERLAY_X}:{TICKER_OVERLAY_Y}[ticker_base];"

            f"[2:v]crop={HEADLINE_SCROLL_W}:{HEADLINE_BAND_H}:mod(t*{HEADLINE_SPEED}\\,{hl_w}):0[hl_scroll];"
            f"[ticker_base][hl_scroll]overlay={HEADLINE_BAND_X}:{HEADLINE_BAND_Y}[after_hl];"
            f"[3:v]crop={AD_SCROLL_W}:{AD_BAND_H}:mod(t*{AD_SPEED}\\,{ad_w}):0[ad_scroll];"
            f"[after_hl][ad_scroll]overlay={AD_BAND_X}:{AD_BAND_Y}[tickered];"

            # Final: ticker ON → tickered version, ticker OFF → full screen version
            f"[full][tickered]overlay=0:0:enable='{enable_expr}'[outv]"
        )

        cmd = [
            'ffmpeg', '-y',
            '-threads', '0', '-filter_threads', '0',
            '-i', video_path,
            '-loop', '1', '-i', TICKER_PNG_PATH,
            '-loop', '1', '-i', hl_strip_path,
            '-loop', '1', '-i', ad_strip_path,
            '-filter_complex', fc,
            '-map', '[outv]', '-map', '0:a',
            '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
            '-c:a', 'copy',
            '-video_track_timescale', '12800',
            '-t', str(duration),
            out_path
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"  ⏱️  Single-pass ticker in {_time.time()-t0:.1f}s")

        if result.returncode != 0:
            print(f"  ❌ FFmpeg failed:\n{result.stderr.decode()[-2000:]}")
            return False

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 10_000:
            print("  ❌ Output missing or too small"); return False

        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        print(f"  ✅ Done → {os.path.basename(out_path)} ({size_mb:.1f} MB)")
        print("─" * 50)
        return True

 

    #     # Step 3: Segment-wise processing
    #     t0 = _time.time()

    #     all_ranges = []
    #     cursor = 0.0
    #     for (seg_s, seg_e) in sorted(ticker_on_ranges):
    #         if cursor < seg_s:
    #             all_ranges.append((cursor, seg_s, 'off'))
    #         all_ranges.append((seg_s, seg_e, 'on'))
    #         cursor = seg_e
    #     if cursor < duration:
    #         all_ranges.append((cursor, duration, 'off'))

    #     tmp_clips = []
    #     for idx, (seg_s, seg_e, mode) in enumerate(all_ranges):
    #         seg_dur = seg_e - seg_s
    #         if seg_dur <= 0:
    #             continue
    #         seg_out = os.path.join(tmp_dir, f'seg_{idx:03d}.mp4')

    #         if mode == 'off':
    #             subprocess.run([
    #                 'ffmpeg', '-y',
    #                 '-ss', str(seg_s), '-t', str(seg_dur),
    #                 '-i', video_path,
    #                 '-vf', f'scale={CONTENT_W}:{OUTPUT_H}',
    #                 '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
    #                 '-c:a', 'aac', '-b:a', '192k',
    #                 '-video_track_timescale', '12800',
    #                 seg_out
    #             ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    #         else:
    #             fc = (
    #                 f"[0:v]scale={CONTENT_W}:{CONTENT_H}[scaled];"
    #                 f"[scaled]pad={CONTENT_W}:{OUTPUT_H}:0:0:black[padded];"
    #                 f"[padded][1:v]overlay={TICKER_OVERLAY_X}:{TICKER_OVERLAY_Y}[ticker_base];"
    #                 f"[2:v]crop={HEADLINE_SCROLL_W}:{HEADLINE_BAND_H}:mod((t+{seg_s:.3f})*{HEADLINE_SPEED}\\,{hl_w}):0[hl_scroll];"
    #                 f"[ticker_base][hl_scroll]overlay={HEADLINE_BAND_X}:{HEADLINE_BAND_Y}[after_hl];"
    #                 f"[3:v]crop={AD_SCROLL_W}:{AD_BAND_H}:mod((t+{seg_s:.3f})*{AD_SPEED}\\,{ad_w}):0[ad_scroll];"
    #                 f"[after_hl][ad_scroll]overlay={AD_BAND_X}:{AD_BAND_Y}[outv]"
    #             )
    #             subprocess.run([
    #                 'ffmpeg', '-y',
    #                 '-ss', str(seg_s), '-t', str(seg_dur),
    #                 '-i', video_path,
    #                 '-loop', '1', '-i', TICKER_PNG_PATH,
    #                 '-loop', '1', '-i', hl_strip_path,
    #                 '-loop', '1', '-i', ad_strip_path,
    #                 '-filter_complex', fc,
    #                 '-map', '[outv]', '-map', '0:a',
    #                 '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
    #                 '-c:a', 'aac', '-b:a', '192k',
    #                 '-video_track_timescale', '12800',
    #                 seg_out
    #             ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    #         tmp_clips.append(seg_out)
    #         print(f"  ✅ Seg {idx+1}/{len(all_ranges)} [{mode}] {seg_s:.1f}→{seg_e:.1f}s")

    #     _concat_clips(tmp_clips, out_path)
    #     print(f"  ⏱️  Segment-wise ticker in {_time.time()-t0:.1f}s")

    except Exception as e:
        import traceback
        print(f"  ❌ Error: {e}")
        traceback.print_exc()
        return False

    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass






# """
# ticker_overlay.py
# ─────────────────
# PIL se ticker strip images render karo (emoji + Telugu support),
# phir FFmpeg mein scroll karo — drawtext use nahi hota.

# Flow (concat approach):
#   1. Headlines + Ad texts load karo
#   2. Pango/Cairo se do PNG strips banao (headline_strip.png, ad_strip.png)
#   3. Video ko 3 parts mein split karo:
#        intro_clip  = video[0 → TICKER_START_T]            full screen, no ticker
#        news_clip   = video[TICKER_START_T → filler_start]  ticker applied
#        filler_clip = video[filler_start → end]             full screen, no ticker
#   4. Sirf news_clip pe ticker apply karo
#   5. Concat: intro + tickered_news + filler → final output
# """

# import os
# import json
# import glob
# import shutil
# import tempfile
# import subprocess
# import base64
# from datetime import datetime, timezone, timedelta

# from config import BASE_DIR, BASE_OUTPUT_DIR, INTRO_VIDEO_DURATION

# # ── Font resolution ───────────────────────────────────────────────────────────
# _TELUGU_CANDIDATES = [
#     "/usr/share/fonts/truetype/noto/NotoSansTelugu-Bold.ttf",
#     "/usr/share/fonts/truetype/noto/NotoSerifTelugu-Bold.ttf",
#     "/usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf",
#     "/usr/share/fonts/noto/NotoSansTelugu-Bold.ttf",
#     os.path.join(BASE_DIR, 'NotoSansTelugu.ttf'),
#     r'C:\Windows\Fonts\NirmalaB.ttf',
#     r'C:\Windows\Fonts\gautamib.ttf',
# ]

# _EMOJI_CANDIDATES = [
#     "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
#     "/usr/share/fonts/noto/NotoColorEmoji.ttf",
#     os.path.join(BASE_DIR, 'seguiemj.ttf'),
#     r'C:\Windows\Fonts\seguisym.ttf',
# ]

# def _find_font(candidates: list) -> str:
#     for f in candidates:
#         if f and os.path.exists(f):
#             return f
#     return ''

# TELUGU_FONT = os.environ.get('TELUGU_FONT', '') or _find_font(_TELUGU_CANDIDATES)
# EMOJI_FONT  = _find_font(_EMOJI_CANDIDATES)

# if TELUGU_FONT:
#     print(f"✓ [TICKER] Telugu font: {TELUGU_FONT}")
# if EMOJI_FONT:
#     print(f"✓ [TICKER] Emoji font:  {EMOJI_FONT}")
# else:
#     print("⚠️  [TICKER] Emoji font not found — emojis will render via Telugu font fallback")

# # ── Ticker config ─────────────────────────────────────────────────────────────
# TICKER_PNG_PATH = os.path.join(BASE_DIR, 'assets', 'ticker4.png')
# ADS_FOLDER_PATH = os.path.join(BASE_DIR, 'assets', 'ads')
# METADATA_FILE   = os.path.join(BASE_OUTPUT_DIR, 'metadata.json')

# # ── Mic icon ──────────────────────────────────────────────────────────────────
# mic_path = os.path.join(BASE_DIR, 'assets', 'kurnool_and_local.png')
# try:
#     with open(mic_path, 'rb') as f:
#         mic_b64 = base64.b64encode(f.read()).decode()
#     print(f"✓ [TICKER] Mic icon loaded: {mic_path}")
# except Exception as e:
#     mic_b64 = None
#     print(f"⚠️  [TICKER] Mic icon not found ({e}) — fallback to ❙")

# # Scroll speeds (px/sec)
# HEADLINE_SPEED = 120
# AD_SPEED       = 100

# # ── Layout geometry ───────────────────────────────────────────────────────────
# CONTENT_W = 1920
# CONTENT_H = 930
# TICKER_H  = 148
# OUTPUT_H  = CONTENT_H + TICKER_H   # 1078

# TICKER_OVERLAY_X = 0
# TICKER_OVERLAY_Y = CONTENT_H       # 930

# HEADLINE_BAND_Y   = TICKER_OVERLAY_Y
# HEADLINE_BAND_H   = 66
# HEADLINE_BAND_X   = 215
# HEADLINE_SCROLL_W = CONTENT_W - HEADLINE_BAND_X   # 1705

# AD_BAND_Y         = TICKER_OVERLAY_Y + 67   # 997
# AD_BAND_H         = 81
# AD_BAND_X         = 271
# AD_SCROLL_W       = CONTENT_W - AD_BAND_X   # 1649

# TICKER_START_T = float(INTRO_VIDEO_DURATION)

# # Strip render settings
# HEADLINE_FONTSIZE = 40
# AD_FONTSIZE       = 40
# HEADLINE_COLOR    = (255, 255, 255, 255)   # white
# AD_COLOR          = (255, 215, 0,   255)   # yellow

# AD_SEP = '      '

# # FFmpeg codec
# VIDEO_CODEC = 'libx264'
# PRESET      = 'ultrafast'
# CRF         = 23
# # VIDEO_CODEC = "h264_nvenc"
# # PRESET      = "p4"

# # ── Helpers ───────────────────────────────────────────────────────────────────

# def _video_duration(path: str) -> float:
#     r = subprocess.run(
#         ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
#          '-of', 'default=noprint_wrappers=1:nokey=1', path],
#         stdout=subprocess.PIPE, stderr=subprocess.PIPE
#     )
#     return float(r.stdout.decode().strip())


# # ── Data loaders ──────────────────────────────────────────────────────────────

# def _load_24hr_headlines() -> list:
#     """Returns list of headline strings."""
#     # if not os.path.exists(METADATA_FILE):
#     #     print("  ⚠️  [TICKER] metadata.json not found")
#     #     return ['వార్తలు అందుబాటులో లేవు']
#     # try:
#     #     with open(METADATA_FILE, 'r', encoding='utf-8') as f:
#     #         items = json.load(f)
#     # except Exception as e:
#     #     print(f"  ⚠️  [TICKER] metadata load error: {e}")
#     #     return ['వార్తలు అందుబాటులో లేవు']
#     try:
#         import db as _db
#         items = _db.fetchall(
#             "SELECT headline, timestamp FROM news_items "
#             "WHERE timestamp::timestamptz >= NOW() - INTERVAL '24 hours' "
#             "ORDER BY counter ASC"
#         )
#     except Exception as e:
#         print(f"  ⚠️  [TICKER] DB load error: {e}")
#         return ['వార్తలు అందుబాటులో లేవు']

#     cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
#     texts  = []
#     for item in items:
#         ts_str = item.get('timestamp', '')
#         try:
#             ts_str = str(ts_str)
#             ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
#             if ts.tzinfo is None:
#                 ts = ts.replace(tzinfo=timezone.utc)
#             if ts < cutoff:
#                 continue
#         except Exception:
#             pass
#         hl = (item.get('headline') or '').strip()
#         if hl:
#             texts.append(hl)

#     if not texts:
#         # Fallback — last 24hrs mein nahi mila, all-time latest lo
#         print("  ⚠️  [TICKER] No headlines in last 24hrs — using latest available")
#         for item in items:
#             hl = (item.get('headline') or '').strip()
#             if hl:
#                 texts.append(hl)

#     if not texts:
#         return ['వార్తలు అందుబాటులో లేవు']

#     print(f"  ✅ [TICKER] {len(texts)} headlines loaded")
#     return texts


# def _load_ad_texts() -> str:
#     os.makedirs(ADS_FOLDER_PATH, exist_ok=True)
#     files = sorted(glob.glob(os.path.join(ADS_FOLDER_PATH, '*.txt')))
#     if not files:
#         print("  ⚠️  [TICKER] No ad files found")
#         return ' '

#     lines = []
#     for fp in files:
#         try:
#             txt = open(fp, 'r', encoding='utf-8').read().strip()
#             for line in txt.splitlines():
#                 line = line.strip()
#                 if line:
#                     lines.append(line)
#         except Exception as e:
#             print(f"  ⚠️  [TICKER] Ad read error {os.path.basename(fp)}: {e}")

#     if not lines:
#         return ' '

#     print(f"  ✅ [TICKER] {len(lines)} ad lines loaded")
#     return f'  {AD_SEP}  '.join(lines)


# # ── HTML builders ─────────────────────────────────────────────────────────────

# def _build_headline_html(headlines: list, font_size: int,
#                           color: tuple, band_h: int,
#                           est_w: int, repeats: int) -> str:
#     r, g, b, _ = color

#     if mic_b64:
#         sep = (
#             f'<img src="data:image/png;base64,{mic_b64}" '
#             f'style="height:{int(font_size * 1.6)}px;vertical-align:middle;margin:0 25px;">'
#             # f'style="height:100px;vertical-align:middle;margin:0 25px;">'
#         )
#     else:
#         sep = '   ❙   '

#     single_run   = sep.join(headlines)
#     full_content = (single_run + f'  {sep}  ') * repeats

#     return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
# <style>
# * {{margin:0;padding:0;}}
# html,body {{width:{est_w}px;height:{band_h}px;background:rgba(0,0,0,0);}}
# .t {{
#     font-family:'Noto Sans Telugu','Nirmala UI',sans-serif;
#     font-size:{font_size}px; font-weight:600;
#     color:rgb({r},{g},{b});
#     white-space:nowrap; line-height:{band_h}px;
#     padding-left:10px;
#     display:flex; align-items:center;
# }}
# </style>
# </head><body><div class="t">{full_content}</div></body></html>"""


# def _build_ad_html(ad_text: str, font_size: int,
#                    color: tuple, band_h: int,
#                    est_w: int, repeats: int) -> str:
#     r, g, b, _ = color
#     full_content = (ad_text + f'  {AD_SEP}  ') * repeats

#     return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
# <style>
# * {{margin:0;padding:0;}}
# html,body {{width:{est_w}px;height:{band_h}px;background:rgba(0,0,0,0);}}
# .t {{
#     font-family:'Noto Sans Telugu','Nirmala UI',sans-serif;
#     font-size:{font_size}px; font-weight:600;
#     color:rgb({r},{g},{b});
#     white-space:nowrap; line-height:{band_h}px;
#     padding-left:10px;
# }}
# </style>
# </head><body><div class="t">{full_content}</div></body></html>"""


# # ── Strip renderer ────────────────────────────────────────────────────────────

# def _render_strips_both(headlines: list, ad_text: str,
#                          hl_path: str, ad_path: str) -> bool:
#     """Render ticker strips with Pango/Cairo, no browser."""
#     try:
#         from PIL import Image
#         from graphics_renderer import pango_available, render_ticker_strip_png

#         # ?? Headline strip ????????????????????????????????????????
#         hl_single_w = max(
#             sum(len(h) for h in headlines) * HEADLINE_FONTSIZE + 200,
#             3000
#         )
#         hl_repeats = max(3, 30000 // hl_single_w)
#         hl_est_w   = min(hl_single_w * hl_repeats, 30000)
#         tmp_hl_png = tempfile.mktemp(suffix='_hl.png')

#         if not render_ticker_strip_png(
#             parts=headlines,
#             out_path=tmp_hl_png,
#             width=hl_est_w,
#             height=HEADLINE_BAND_H,
#             font_size=HEADLINE_FONTSIZE,
#             color=HEADLINE_COLOR,
#             repeats=hl_repeats,
#             separator_image=mic_path if mic_b64 else None,
#             separator_text='   ?   ',
#             icon_height=int(HEADLINE_FONTSIZE * 1.6),
#             icon_margin=25,
#         ):
#             return False

#         img = Image.open(tmp_hl_png).convert('RGBA')
#         doubled = Image.new('RGBA', (img.width * 2, HEADLINE_BAND_H), (0, 0, 0, 0))
#         doubled.paste(img, (0, 0))
#         doubled.paste(img, (img.width, 0))
#         doubled.save(hl_path, 'PNG')
#         renderer_name = 'Pango/Cairo' if pango_available() else 'PIL fallback'
#         print(f"  ???  [TICKER] Headline strip ({renderer_name}): {img.width * 2}?{HEADLINE_BAND_H}px")
#         img.close()
#         doubled.close()
#         os.unlink(tmp_hl_png)

#         # ?? Ad strip ?????????????????????????????????????????????
#         ad_single_w = max(len(ad_text) * AD_FONTSIZE, 3000)
#         ad_repeats  = max(3, 30000 // ad_single_w)
#         ad_est_w    = min(ad_single_w * ad_repeats, 30000)
#         tmp_ad_png  = tempfile.mktemp(suffix='_ad.png')

#         if not render_ticker_strip_png(
#             parts=[ad_text],
#             out_path=tmp_ad_png,
#             width=ad_est_w,
#             height=AD_BAND_H,
#             font_size=AD_FONTSIZE,
#             color=AD_COLOR,
#             repeats=ad_repeats,
#             separator_image=None,
#             separator_text=f'  {AD_SEP}  ',
#             icon_height=int(AD_FONTSIZE * 1.6),
#             icon_margin=25,
#         ):
#             return False

#         img = Image.open(tmp_ad_png).convert('RGBA')
#         doubled = Image.new('RGBA', (img.width * 2, AD_BAND_H), (0, 0, 0, 0))
#         doubled.paste(img, (0, 0))
#         doubled.paste(img, (img.width, 0))
#         doubled.save(ad_path, 'PNG')
#         print(f"  ???  [TICKER] Ad strip ({renderer_name}): {img.width * 2}?{AD_BAND_H}px")
#         img.close()
#         doubled.close()
#         os.unlink(tmp_ad_png)

#         return True

#     except Exception as e:
#         import traceback
#         print(f"  ? [TICKER] Strip error: {e}")
#         traceback.print_exc()
#         return False

# # def _render_strips_both(headlines: list, ad_text: str,
# #                          hl_path: str, ad_path: str) -> bool:
# #     """
# #     Both ticker strips via the shared renderer.

# #     Strategy: render ONE tile (single pass, ~3-5000px max), then PIL doubles
# #     it. FFmpeg's mod(t*speed, tile_width) gives infinite seamless scroll —
# #     requirement is just tile_width >= SCROLL_WINDOW_WIDTH (1705 / 1649).

# #     No more browser screenshots; strips are rendered natively.
# #     """
# #     try:
# #         from PIL import Image
# #         from pw_renderer import renderer

# #         # ── Headline strip ──────────────────────────────────────────────────
# #         # Tile must be >= scroll window (1705) for seamless wrap. Add a margin.
# #         # Cap at 6000 — even very long headlines look fine wrapped/scrolled.
# #         hl_natural = sum(len(h) for h in headlines) * HEADLINE_FONTSIZE + 200
# #         hl_tile_w  = max(min(hl_natural, 6000), HEADLINE_SCROLL_W + 500)

# #         hl_html = _build_headline_html(
# #             headlines, HEADLINE_FONTSIZE, HEADLINE_COLOR,
# #             HEADLINE_BAND_H, hl_tile_w, 1,        # repeats = 1
# #         )

# #         tmp_hl_png = renderer.render(
# #             html=hl_html,
# #             viewport={"width": hl_tile_w, "height": HEADLINE_BAND_H},
# #         )
# #         if tmp_hl_png is None:
# #             print(f"  ❌ [TICKER] Headline render returned None")
# #             return False

# #         img = Image.open(tmp_hl_png).convert("RGBA")
# #         # Double horizontally so FFmpeg's mod-scroll wraps seamlessly.
# #         doubled = Image.new("RGBA", (img.width * 2, HEADLINE_BAND_H), (0, 0, 0, 0))
# #         doubled.paste(img, (0, 0))
# #         doubled.paste(img, (img.width, 0))
# #         doubled.save(hl_path, "PNG")
# #         print(f"  🖼️  [TICKER] Headline strip: tile={img.width}px → doubled={img.width*2}×{HEADLINE_BAND_H}")
# #         img.close()
# #         doubled.close()

# #         # ── Ad strip ────────────────────────────────────────────────────────
# #         ad_natural = len(ad_text) * AD_FONTSIZE + 200
# #         ad_tile_w  = max(min(ad_natural, 6000), AD_SCROLL_W + 500)

# #         ad_html = _build_ad_html(
# #             ad_text, AD_FONTSIZE, AD_COLOR,
# #             AD_BAND_H, ad_tile_w, 1,
# #         )

# #         tmp_ad_png = renderer.render(
# #             html=ad_html,
# #             viewport={"width": ad_tile_w, "height": AD_BAND_H},
# #         )
# #         if tmp_ad_png is None:
# #             print(f"  ❌ [TICKER] Ad render returned None")
# #             return False

# #         img = Image.open(tmp_ad_png).convert("RGBA")
# #         doubled = Image.new("RGBA", (img.width * 2, AD_BAND_H), (0, 0, 0, 0))
# #         doubled.paste(img, (0, 0))
# #         doubled.paste(img, (img.width, 0))
# #         doubled.save(ad_path, "PNG")
# #         print(f"  🖼️  [TICKER] Ad strip: tile={img.width}px → doubled={img.width*2}×{AD_BAND_H}")
# #         img.close()
# #         doubled.close()

# #         return True

# #     except Exception as e:
# #         import traceback
# #         print(f"  ❌ [TICKER] Strip error: {e}")
# #         traceback.print_exc()
# #         return False


# # ── Segment trimmers ──────────────────────────────────────────────────────────

# def _trim_clip(src: str, out: str, start: float, end: float):
#     """src se [start, end] clip nikalo — scale to OUTPUT_H (full screen)."""
#     subprocess.run([
#         'ffmpeg', '-y',
#         '-ss', str(start), '-t', str(end - start),
#         '-i', src,
#         '-vf', f'scale={CONTENT_W}:{OUTPUT_H}',
#         '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
#         '-c:a', 'aac', '-b:a', '192k',
#         '-video_track_timescale', '12800',
#         out
#     ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


# def _apply_ticker_to_clip(src: str, out: str,
#                            hl_strip: str, ad_strip: str,
#                            hl_w: int, ad_w: int):
#     """
#     Sirf news_clip pe ticker bands + scrolling text apply karo.
#     Output: 1920×1078 with ticker3.png bands at bottom.
#     """
#     fc = (
#         f"[0:v]scale={CONTENT_W}:{CONTENT_H}[news_v];"
#         f"[news_v]pad={CONTENT_W}:{OUTPUT_H}:0:0:black[padded];"
#         f"[padded][1:v]overlay={TICKER_OVERLAY_X}:{TICKER_OVERLAY_Y}[ticker_base];"

#         f"[2:v]crop={HEADLINE_SCROLL_W}:{HEADLINE_BAND_H}:"
#         f"mod(t*{HEADLINE_SPEED}\\,{hl_w}):0[hl_scroll];"
#         f"[ticker_base][hl_scroll]overlay={HEADLINE_BAND_X}:{HEADLINE_BAND_Y}[after_hl];"

#         f"[3:v]crop={AD_SCROLL_W}:{AD_BAND_H}:"
#         f"mod(t*{AD_SPEED}\\,{ad_w}):0[ad_scroll];"
#         f"[after_hl][ad_scroll]overlay={AD_BAND_X}:{AD_BAND_Y}[outv]"
#     )

#     try:
#         dur = _video_duration(src)
#     except Exception:
#         dur = None

#     cmd = [
#         'ffmpeg', '-y',
#         '-threads', '0', '-filter_threads', '0',
#         '-i', src,
#         '-loop', '1', '-i', TICKER_PNG_PATH,
#         '-loop', '1', '-i', hl_strip,
#         '-loop', '1', '-i', ad_strip,
#         '-filter_complex', fc,
#         '-map', '[outv]', '-map', '0:a',
#         '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
#         '-c:a', 'copy',
#         '-video_track_timescale', '12800',
#     ]
#     if dur:
#         cmd += ['-t', str(dur)]
#     cmd.append(out)

#     result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#     if result.returncode != 0:
#         raise RuntimeError(f"FFmpeg ticker failed:\n{result.stderr.decode()[-3000:]}")


# def _concat_clips(clips: list, out: str):
#     """Fast concat — no re-encode."""
#     list_file = tempfile.mktemp(suffix='_concat.txt')
#     with open(list_file, 'w', encoding='utf-8') as f:
#         for c in clips:
#             f.write(f"file '{c}'\n")

#     result = subprocess.run([
#         'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
#         '-i', list_file, '-c', 'copy', out
#     ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

#     os.unlink(list_file)
#     if result.returncode != 0:
#         raise RuntimeError(f"Concat failed:\n{result.stderr.decode()[-2000:]}")


# # ── Main function ─────────────────────────────────────────────────────────────

# def add_ticker_overlay(video_path: str, out_path: str,
#                        filler_start: float = None,
#                        skip_ranges: list = None) -> bool:
#     import time as _time

#     print("\n" + "─" * 50)
#     print("📺 Adding ticker overlay (single-pass approach)...")

#     if not os.path.exists(video_path):
#         print(f"  ❌ Input video not found: {video_path}"); return False
#     if not os.path.exists(TICKER_PNG_PATH):
#         print(f"  ❌ ticker3.png not found: {TICKER_PNG_PATH}"); return False

#     headlines = _load_24hr_headlines()
#     ad_text   = _load_ad_texts()

#     try:
#         duration = _video_duration(video_path)
#     except Exception as e:
#         print(f"  ❌ ffprobe error: {e}"); return False

#     print(f"  ℹ️  total={duration:.2f}s | ticker_start={TICKER_START_T}s | filler_start={filler_start}s")

#     tmp_dir       = tempfile.mkdtemp(prefix='ticker_work_')
#     hl_strip_path = os.path.join(tmp_dir, 'headline_strip.png')
#     ad_strip_path = os.path.join(tmp_dir, 'ad_strip.png')

#     try:
#         # Step 1: Render strips
#         t0 = _time.time()
#         if not _render_strips_both(headlines, ad_text, hl_strip_path, ad_strip_path):
#             print("  ❌ Strip render failed"); return False
#         print(f"  ⏱️  Strips in {_time.time()-t0:.1f}s")

#         from PIL import Image as _Img
#         with _Img.open(hl_strip_path) as im:
#             hl_w = im.width // 2
#         with _Img.open(ad_strip_path) as im:
#             ad_w = im.width // 2
#         print(f"  ℹ️  strip widths → hl={hl_w}px  ad={ad_w}px")

#         # Step 2: Calculate ticker-ON ranges (inverse of skip_ranges)
#         news_end = filler_start if filler_start else duration

#         ticker_on_ranges = []
#         cursor = TICKER_START_T
#         for (skip_s, skip_e) in sorted(skip_ranges or [], key=lambda x: x[0]):
#             skip_s = max(skip_s, TICKER_START_T)
#             skip_e = min(skip_e, news_end)
#             if skip_s >= skip_e:
#                 continue
#             if cursor < skip_s:
#                 ticker_on_ranges.append((cursor, skip_s))
#             cursor = skip_e
#         if cursor < news_end:
#             ticker_on_ranges.append((cursor, news_end))

#         print(f"  ℹ️  Ticker ON ranges: {[(round(s,1), round(e,1)) for s,e in ticker_on_ranges]}")

#         # FFmpeg enable expression
#         if ticker_on_ranges:
#             enable_expr = '+'.join([f'between(t,{s:.3f},{e:.3f})' for s, e in ticker_on_ranges])
#         else:
#             enable_expr = '0'

#         # Step 3: Single-pass FFmpeg — no splitting, no concat, no drift
#         t0 = _time.time()

#         fc = (
#             # Full screen version (1920x1078, no black bar) — always
#             f"[0:v]scale={CONTENT_W}:{OUTPUT_H}[full];"

#             # Ticker composite (930 + 148 black + ticker bands) — only ON ranges
#             f"[0:v]scale={CONTENT_W}:{CONTENT_H}[cnews];"
#             f"[cnews]pad={CONTENT_W}:{OUTPUT_H}:0:0:black[padded];"
#             f"[padded][1:v]overlay={TICKER_OVERLAY_X}:{TICKER_OVERLAY_Y}[ticker_base];"

#             f"[2:v]crop={HEADLINE_SCROLL_W}:{HEADLINE_BAND_H}:mod(t*{HEADLINE_SPEED}\\,{hl_w}):0[hl_scroll];"
#             f"[ticker_base][hl_scroll]overlay={HEADLINE_BAND_X}:{HEADLINE_BAND_Y}[after_hl];"
#             f"[3:v]crop={AD_SCROLL_W}:{AD_BAND_H}:mod(t*{AD_SPEED}\\,{ad_w}):0[ad_scroll];"
#             f"[after_hl][ad_scroll]overlay={AD_BAND_X}:{AD_BAND_Y}[tickered];"

#             # Final: ticker ON → tickered version, ticker OFF → full screen version
#             f"[full][tickered]overlay=0:0:enable='{enable_expr}'[outv]"
#         )

#         cmd = [
#             'ffmpeg', '-y',
#             '-threads', '0', '-filter_threads', '0',
#             '-i', video_path,
#             '-loop', '1', '-i', TICKER_PNG_PATH,
#             '-loop', '1', '-i', hl_strip_path,
#             '-loop', '1', '-i', ad_strip_path,
#             '-filter_complex', fc,
#             '-map', '[outv]', '-map', '0:a',
#             '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
#             '-c:a', 'copy',
#             '-video_track_timescale', '12800',
#             '-t', str(duration),
#             out_path
#         ]

#         result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#         print(f"  ⏱️  Single-pass ticker in {_time.time()-t0:.1f}s")

#         if result.returncode != 0:
#             print(f"  ❌ FFmpeg failed:\n{result.stderr.decode()[-2000:]}")
#             return False

#         if not os.path.exists(out_path) or os.path.getsize(out_path) < 10_000:
#             print("  ❌ Output missing or too small"); return False

#         size_mb = os.path.getsize(out_path) / (1024 * 1024)
#         print(f"  ✅ Done → {os.path.basename(out_path)} ({size_mb:.1f} MB)")
#         print("─" * 50)
#         return True

 

#     #     # Step 3: Segment-wise processing
#     #     t0 = _time.time()

#     #     all_ranges = []
#     #     cursor = 0.0
#     #     for (seg_s, seg_e) in sorted(ticker_on_ranges):
#     #         if cursor < seg_s:
#     #             all_ranges.append((cursor, seg_s, 'off'))
#     #         all_ranges.append((seg_s, seg_e, 'on'))
#     #         cursor = seg_e
#     #     if cursor < duration:
#     #         all_ranges.append((cursor, duration, 'off'))

#     #     tmp_clips = []
#     #     for idx, (seg_s, seg_e, mode) in enumerate(all_ranges):
#     #         seg_dur = seg_e - seg_s
#     #         if seg_dur <= 0:
#     #             continue
#     #         seg_out = os.path.join(tmp_dir, f'seg_{idx:03d}.mp4')

#     #         if mode == 'off':
#     #             subprocess.run([
#     #                 'ffmpeg', '-y',
#     #                 '-ss', str(seg_s), '-t', str(seg_dur),
#     #                 '-i', video_path,
#     #                 '-vf', f'scale={CONTENT_W}:{OUTPUT_H}',
#     #                 '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
#     #                 '-c:a', 'aac', '-b:a', '192k',
#     #                 '-video_track_timescale', '12800',
#     #                 seg_out
#     #             ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
#     #         else:
#     #             fc = (
#     #                 f"[0:v]scale={CONTENT_W}:{CONTENT_H}[scaled];"
#     #                 f"[scaled]pad={CONTENT_W}:{OUTPUT_H}:0:0:black[padded];"
#     #                 f"[padded][1:v]overlay={TICKER_OVERLAY_X}:{TICKER_OVERLAY_Y}[ticker_base];"
#     #                 f"[2:v]crop={HEADLINE_SCROLL_W}:{HEADLINE_BAND_H}:mod((t+{seg_s:.3f})*{HEADLINE_SPEED}\\,{hl_w}):0[hl_scroll];"
#     #                 f"[ticker_base][hl_scroll]overlay={HEADLINE_BAND_X}:{HEADLINE_BAND_Y}[after_hl];"
#     #                 f"[3:v]crop={AD_SCROLL_W}:{AD_BAND_H}:mod((t+{seg_s:.3f})*{AD_SPEED}\\,{ad_w}):0[ad_scroll];"
#     #                 f"[after_hl][ad_scroll]overlay={AD_BAND_X}:{AD_BAND_Y}[outv]"
#     #             )
#     #             subprocess.run([
#     #                 'ffmpeg', '-y',
#     #                 '-ss', str(seg_s), '-t', str(seg_dur),
#     #                 '-i', video_path,
#     #                 '-loop', '1', '-i', TICKER_PNG_PATH,
#     #                 '-loop', '1', '-i', hl_strip_path,
#     #                 '-loop', '1', '-i', ad_strip_path,
#     #                 '-filter_complex', fc,
#     #                 '-map', '[outv]', '-map', '0:a',
#     #                 '-c:v', VIDEO_CODEC, '-preset', PRESET, '-crf', str(CRF),
#     #                 '-c:a', 'aac', '-b:a', '192k',
#     #                 '-video_track_timescale', '12800',
#     #                 seg_out
#     #             ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

#     #         tmp_clips.append(seg_out)
#     #         print(f"  ✅ Seg {idx+1}/{len(all_ranges)} [{mode}] {seg_s:.1f}→{seg_e:.1f}s")

#     #     _concat_clips(tmp_clips, out_path)
#     #     print(f"  ⏱️  Segment-wise ticker in {_time.time()-t0:.1f}s")

#     except Exception as e:
#         import traceback
#         print(f"  ❌ Error: {e}")
#         traceback.print_exc()
#         return False

#     finally:
#         try:
#             shutil.rmtree(tmp_dir)
#         except Exception:
#             pass
