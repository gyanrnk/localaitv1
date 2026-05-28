# Ticker Strip Fix — Local vs VPS Comparison

## Root Cause (Final)

| | Local (Windows) | VPS (Linux Docker) |
|--|--|--|
| `ticker4.png` size | **1920×163** (correct) | **1920×150** (wrong/old file) |
| Headline band color | **#810f05 crimson** | **#ffffff white** |
| Result | Crimson band, text visible ✅ | White band, text invisible ❌ |

**Real fix:** Upload correct `ticker4.png` from local to VPS:
```
scp "assets/ticker4.png" root@72.62.241.21:/root/localaitv1/assets/ticker4.png
```

Assets folder is a **volume mount** from VPS (`./assets:/app/assets`) — Docker image updates do NOT update asset files.

---

## Why the Headline Was Invisible (Root Cause Explained)

1. `ticker4.png` on VPS had **white** in the headline scrolling area
2. `_prepare_labels_overlay()` only makes **crimson + black** pixels transparent
3. White pixels stayed **opaque** in labels PNG
4. Labels PNG overlaid on top → **white covered everything** in headline band
5. White text on white = invisible, regardless of any code fix

---

## Failed Approaches (What We Tried Before Finding Root Cause)

### Attempt 1: `omit_background=True` (Playwright)
- **Idea:** Make screenshot transparent so crimson from ticker4.png shows through
- **Why failed:** Docker headless Chromium ignores `omit_background=True` → always renders white background
- **Works on:** Windows Chrome ✅ | Linux Docker headless ❌

### Attempt 2: Green Screen + FFmpeg Chromakey
- **Idea:** Set HTML background `#00ff00`, FFmpeg `chromakey=0x00ff00:0.05:0.1` to remove green
- **Why failed:** Playwright DID render green correctly on VPS (tested — pixel was `(0,255,0)`)
  BUT ticker4.png on VPS was white in headline area → labels PNG covered strip with white regardless
- **Status:** Technically correct approach but masked by the real root cause

### Attempt 3: `HEADLINE_BG` Direct Color in HTML
- **Idea:** Set HTML background to exact crimson `rgb(129,15,5)` matching ticker4.png
- **Why failed:** Same reason — VPS ticker4.png was white, labels PNG still covered with white

---

## Actual Code Changes Made (ticker_overlay.py)

### Current state after all fixes:

**HTML backgrounds** (both `_build_headline_html` and `_build_ad_html`):
```python
# Headline: uses HEADLINE_BG = (129, 15, 5) — exact crimson from ticker4.png
bg_r, bg_g, bg_b = HEADLINE_BG[:3]
html,body { background: rgb({bg_r},{bg_g},{bg_b}); }

# Ad: uses AD_BG = (0, 0, 0) — black
bg_r, bg_g, bg_b = AD_BG[:3]
html,body { background: rgb({bg_r},{bg_g},{bg_b}); }
```

**Screenshot** (`_render_strip`):
```python
page.screenshot(path=tmp_png_path)   # no omit_background
```

**FFmpeg filter** (both filter chains):
```python
# No chromakey — direct overlay
f"[2:v]crop=...mod(...):0[hl_scroll];"
f"[ticker_base][hl_scroll]overlay=...;"
```

---

## Key Architecture Notes

- `assets/` folder → **volume mounted** from VPS, not baked in Docker image
- `outputs/` folder → **volume mounted** from VPS (bulletin files persist)
- `inputs/` folder → **volume mounted** from VPS
- Python code (`.py` files) → **baked in Docker image** — updated via CI/CD push
- If asset file changes locally → must `scp` to VPS manually OR commit + git pull on VPS

---

## `_prepare_labels_overlay` Logic

Creates `ticker4_labels.png` where:
- **Crimson pixels** (`r≥100, g≤35, b≤25`) → transparent (alpha=0)
- **Black pixels** → transparent (alpha=0)  
- **Everything else** (navy labels, diagonal edges) → opaque

This allows strip text to show through the transparent band areas while labels/decorations stay visible on top.

---

## TTS Fix (Separate)

| File | Before | After |
|--|--|--|
| `tts_handler_gcp.py` | `speaking_rate=1.5` | `speaking_rate=1.0` |

`item_video_cache/` stores old TTS audio — clear cache after rate change:
```bash
rm -rf /root/localaitv1/outputs/item_video_cache/*
```