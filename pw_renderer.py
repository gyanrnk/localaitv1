"""
pw_renderer.py
──────────────
Single point of truth for HTML → PNG rendering via Playwright Chromium.

Design goals:
    1. Thread-safe singleton browser    — no race on lazy init.
    2. Page pool                         — reuse pages, avoid new_context() / new_page() per call.
    3. set_content() instead of goto()   — no temp HTML file, no networkidle wait.
    4. Disk-backed PNG cache             — survives worker restart.
    5. Pre-warm hook                     — pay cold-start once at worker boot, not on first render.

Usage:
    from src.news_bulletin_builder.builders.pw_renderer import renderer

    out_png = renderer.render(
        html=html_string,
        viewport={"width": 1920, "height": 1080},
        cache_key="reporter:v5:Anjali:abc123",   # optional; if given, cache hit returns instantly
    )

    # Optional pre-warm at worker start (called from celery worker_ready signal):
    renderer.prewarm()

    # Optional explicit shutdown (called at end of build, or atexit):
    renderer.shutdown()
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Cache directory (disk-backed) ────────────────────────────────────────────
# Falls back to /tmp if BASE_OUTPUT_DIR not configured. Caller can override.
def _default_cache_dir() -> str:
    try:
        from config import BASE_OUTPUT_DIR
        return os.path.join(BASE_OUTPUT_DIR, "cache", "pw_renders")
    except Exception:
        return os.path.join(os.path.dirname(__file__), ".pw_cache")


# ── Chromium launch flags — tuned for headless rendering, low memory ─────────
_CHROMIUM_FLAGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu-compositing",
    # extra memory + startup wins for offscreen rendering:
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-default-apps",
    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
    "--password-store=basic",
    "--use-mock-keychain",
]


class PWRenderer:
    """
    Thread-safe Playwright renderer with one browser, one context, one reusable page.

    Why a single page is enough:
        page.set_content(html) replaces the full document each call. Viewport
        is set per-call. Concurrent renders within one process are serialized
        on _render_lock — Playwright sync API is not safe for true concurrency
        on a shared page anyway. For parallelism, scale Celery workers (each
        worker has its own renderer).
    """

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        self._lock          = threading.Lock()       # guards browser/context/page lifecycle
        self._render_lock   = threading.Lock()       # guards single-page reuse
        self._pw            = None                   # sync_playwright instance
        self._browser       = None
        self._context       = None
        self._page          = None
        self._cache_dir     = cache_dir or _default_cache_dir()
        os.makedirs(self._cache_dir, exist_ok=True)
        atexit.register(self.shutdown)

    # ── Browser / context lifecycle ──────────────────────────────────────────

    def _ensure_browser(self) -> None:
        """Lazy + thread-safe browser/context/page init."""
        if self._page is not None and self._browser and self._browser.is_connected():
            return
        with self._lock:
            # double-checked
            if self._page is not None and self._browser and self._browser.is_connected():
                return
            from playwright.sync_api import sync_playwright
            self._pw       = sync_playwright().start()
            self._browser  = self._pw.chromium.launch(args=_CHROMIUM_FLAGS)
            # One persistent context with a default 1920x1080 viewport.
            # Per-call viewports are applied with page.set_viewport_size().
            self._context  = self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                bypass_csp=True,
                java_script_enabled=True,
                offline=True,                # file:// renders need no network
            )
            self._page     = self._context.new_page()
            logger.info("[PWRenderer] Chromium launched + context + page ready")

    def prewarm(self) -> None:
        """Call from worker_ready signal so first render doesn't pay cold-start."""
        try:
            self._ensure_browser()
            # Touch the page once so the renderer is fully warm.
            self._page.set_content("<html><body></body></html>", wait_until="load")
            logger.info("[PWRenderer] prewarm complete")
        except Exception as e:
            logger.warning(f"[PWRenderer] prewarm failed: {e}")

    def shutdown(self) -> None:
        with self._lock:
            try:
                if self._page is not None:
                    self._page.close()
            except Exception:
                pass
            try:
                if self._context is not None:
                    self._context.close()
            except Exception:
                pass
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                pass
            self._page = self._context = self._browser = self._pw = None

    # ── Cache helpers ────────────────────────────────────────────────────────

    def _cache_path(self, key: str) -> str:
        # md5 of key keeps filename safe regardless of caller content.
        h = hashlib.md5(key.encode("utf-8")).hexdigest()
        return os.path.join(self._cache_dir, f"{h}.png")

    # ── Public render API ────────────────────────────────────────────────────

    def render(
        self,
        html: str,
        viewport: dict,
        out_png: Optional[str] = None,
        cache_key: Optional[str] = None,
        omit_background: bool = True,
        clip: Optional[dict] = None,
    ) -> Optional[str]:
        """
        Render HTML → PNG.

        Args:
            html:        full HTML document (caller builds the string).
            viewport:    {"width": int, "height": int}
            out_png:     destination path. If None, a path under cache_dir is used.
            cache_key:   if given AND cache file exists, returns it without rendering.
                         Versioning is the caller's job — bump the key when HTML changes.
            omit_background: transparent PNG (default True).
            clip:        optional {"x":, "y":, "width":, "height":} to clip the screenshot.

        Returns:
            Path to the rendered PNG, or None on failure.
        """
        # ── Cache hit ────────────────────────────────────────────────────────
        if cache_key:
            cached = self._cache_path(cache_key)
            if os.path.exists(cached) and os.path.getsize(cached) > 0:
                if out_png and out_png != cached:
                    # Hardlink instead of copy — instant, no extra disk.
                    try:
                        if os.path.exists(out_png):
                            os.unlink(out_png)
                        os.link(cached, out_png)
                        return out_png
                    except OSError:
                        # Fallback: caller can use the cached path directly.
                        pass
                return cached
            # Decide where the screenshot lands so we also populate the cache.
            if out_png is None:
                out_png = cached
        else:
            if out_png is None:
                # Anonymous render — drop into cache_dir with a random name.
                import tempfile
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".png", dir=self._cache_dir
                )
                tmp.close()
                out_png = tmp.name

        # ── Render ───────────────────────────────────────────────────────────
        for _attempt in range(2):
            try:
                self._ensure_browser()
                with self._render_lock:
                    self._page.set_viewport_size(viewport)
                    self._page.set_content(html, wait_until="load")
                    shot_args = {"path": out_png, "omit_background": omit_background}
                    if clip:
                        shot_args["clip"] = clip
                    self._page.screenshot(**shot_args)
                return out_png
            except Exception as e:
                logger.exception(f"[PWRenderer] render failed (attempt {_attempt+1}): {e}")
                self.shutdown()
                if _attempt == 0:
                    logger.info("[PWRenderer] Retrying with fresh browser...")
        return None


# ── Singleton ────────────────────────────────────────────────────────────────
renderer = PWRenderer()