"""
TTS Handler - Google Cloud Text-to-Speech (Chirp 3: HD)
Telugu News Broadcast — Dual-voice setup

Voice selection (best for Telugu news anchoring):
  MALE   → Fenrir  (te-IN-Chirp3-HD-Fenrir)  — Deep, authoritative anchor tone
  FEMALE → Aoede   (te-IN-Chirp3-HD-Aoede)   — Natural, warm presenter voice

Voice alternation rule:
  Even items (0, 2, 4...) → Fenrir (male)
  Odd items  (1, 3, 5...) → Aoede  (female)

  SAME voice is used for ALL audio of that item:
    headline + script + intro + analysis → all same voice

Requirements:
  pip install google-cloud-texttospeech
  Set GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json in .env
  OR set GOOGLE_TTS_API_KEY in .env (API key auth)
"""

import os
import re
import threading
import time
from typing import Optional

# ── Google Cloud TTS import (safe guard) ─────────────────────────────────────
try:
    from google.cloud import texttospeech
    from google.api_core.client_options import ClientOptions
    _GOOGLE_TTS_AVAILABLE = True
except ImportError:
    texttospeech = None          # type: ignore
    ClientOptions = None         # type: ignore
    _GOOGLE_TTS_AVAILABLE = False
    print("⚠️  google-cloud-texttospeech not installed. Run: pip install google-cloud-texttospeech")

from config import MAX_TTS_CONCURRENCY

# ── TTS concurrency gate ──────────────────────────────────────────────────────
_TTS_LOCK = threading.Semaphore(max(1, int(MAX_TTS_CONCURRENCY)))

# ── Language ──────────────────────────────────────────────────────────────────
LANGUAGE_CODE = "te-IN"

# ── Voice config ──────────────────────────────────────────────────────────────
VOICE_CONFIG = {
    "orus": {
        "name":   "te-IN-Chirp3-HD-Fenrir",
        "gender": "MALE",
        "label":  "♂ MALE   — Fenrir (best Telugu news anchor)",
    },
    "aoede": {
        "name":   "te-IN-Chirp3-HD-Aoede",
        "gender": "FEMALE",
        "label":  "♀ FEMALE — Aoede (best Telugu female presenter)",
    },
}

# ── Voice alternation system ──────────────────────────────────────────────────
_voice_counter_lock = threading.Lock()
_voice_counter       = 0


def set_voice_counter(n: int):
    """
    Force-set the voice counter to n.
    Call BEFORE TTSHandler.for_item() with the current saved-item count
    so alternation stays consistent across server restarts.
    """
    global _voice_counter
    with _voice_counter_lock:
        _voice_counter = n
    print(f"🔁  [GCP] Voice counter set to {n} → next voice = {'orus (male)' if n % 2 == 0 else 'aoede (female)'}")


def _get_alternate_voice() -> str:
    """Returns 'orus' or 'aoede' alternating with each call. Thread-safe."""
    global _voice_counter
    with _voice_counter_lock:
        voice = "orus" if (_voice_counter % 2 == 0) else "aoede"
        _voice_counter += 1
    cfg = VOICE_CONFIG[voice]
    print(f"🔄  [GCP] Voice Alternation #{_voice_counter - 1}: {voice.upper()} ({cfg['label']})")
    return voice


# ── Google Cloud TTS client (singleton, thread-safe lazy init) ────────────────
_client_lock = threading.Lock()
_tts_client  = None


def _get_client():
    """
    Lazy-init Google Cloud TTS client.
    Supports two auth modes:
      1. API key  → set GOOGLE_TTS_API_KEY or GOOGLE_API_KEY in .env
      2. ADC/JSON → set GOOGLE_APPLICATION_CREDENTIALS in .env
    """
    global _tts_client
    if _tts_client is not None:
        return _tts_client

    with _client_lock:
        if _tts_client is not None:
            return _tts_client

        if not _GOOGLE_TTS_AVAILABLE:
            raise RuntimeError(
                "google-cloud-texttospeech is not installed.\n"
                "Fix: pip install google-cloud-texttospeech"
            )

        api_key = os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            _tts_client = texttospeech.TextToSpeechClient(
                client_options=ClientOptions(api_key=api_key)
            )
            print("🔑  Google TTS: using API key auth")
        else:
            _tts_client = texttospeech.TextToSpeechClient()
            print("🔑  Google TTS: using Application Default Credentials (ADC)")

        return _tts_client


# ── Main handler class ────────────────────────────────────────────────────────

class TTSHandler:
    """
    Handle Google Cloud TTS (Chirp 3: HD) for Telugu news.

    Per-item usage (via factory — do not instantiate directly):
        item_tts = TTSHandler.for_item()
        item_tts.generate_audio(headline_text,  headline_path)
        item_tts.generate_audio(script_text,    script_path)
        item_tts.generate_audio(intro_text,     intro_path)
        item_tts.generate_audio(analysis_text,  analysis_path)
    """

    def __init__(self, speaker: str = None):
        spk = (speaker or "orus").lower()
        if spk not in VOICE_CONFIG:
            print(f"⚠️  Unknown speaker '{spk}', defaulting to 'orus'")
            spk = "orus"

        self.speaker    = spk
        self.voice_cfg  = VOICE_CONFIG[spk]
        self.voice_name = self.voice_cfg["name"]
        self.language   = LANGUAGE_CODE
        print(f"🎙️  [GCP] TTSHandler ready: {self.voice_name} | {self.voice_cfg['label']}")

    @classmethod
    def for_item(cls) -> "TTSHandler":
        """
        Pick an alternating voice for a complete news item.
        Call ONCE per item — reuse same instance for all audio of that item.
        Always call set_voice_counter(n) before this.
        """
        voice = _get_alternate_voice()
        return cls(speaker=voice)

    @classmethod
    def for_script(cls) -> "TTSHandler":
        """Deprecated: use for_item() instead."""
        return cls(speaker="orus")

    @classmethod
    def for_headline(cls) -> "TTSHandler":
        """Deprecated: use for_item() instead."""
        return cls(speaker="aoede")

    def _chunk_text(self, text: str, max_bytes: int = 4500) -> list:
        """Split text into chunks whose UTF-8 size ≤ max_bytes."""
        if len(text.encode("utf-8")) <= max_bytes:
            return [text]

        sentences     = re.split(r'(?<=[.!?।])\s+', text)
        chunks        = []
        current       = []
        current_bytes = 0

        for sent in sentences:
            sent_bytes = len(sent.encode("utf-8"))
            if current_bytes + sent_bytes + 1 > max_bytes:
                if current:
                    chunks.append(" ".join(current))
                current       = [sent]
                current_bytes = sent_bytes
            else:
                current.append(sent)
                current_bytes += sent_bytes + 1

        if current:
            chunks.append(" ".join(current))

        return chunks if chunks else [text]

    def _call_tts_api(self, text_chunk: str, speaking_rate: float = 1.5) -> Optional[bytes]:
        """Call Google Cloud TTS for one text chunk. Returns raw MP3 bytes or None."""
        MAX_RETRIES = 3
        client      = _get_client()

        synthesis_input = texttospeech.SynthesisInput(text=text_chunk)
        voice_params    = texttospeech.VoiceSelectionParams(
            language_code=self.language,
            name=self.voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
            sample_rate_hertz=24000,
            effects_profile_id=["large-home-entertainment-class-device"],
        )

        with _TTS_LOCK:
            for attempt in range(MAX_RETRIES):
                try:
                    response = client.synthesize_speech(
                        input=synthesis_input,
                        voice=voice_params,
                        audio_config=audio_config,
                    )
                    return response.audio_content

                except Exception as e:
                    err_str = str(e)
                    print(f"❌ [GCP] TTS attempt {attempt + 1} failed: {err_str[:200]}")

                    if any(x in err_str.lower() for x in ["invalid", "bad request", "400"]):
                        print("   ⚠️  Non-retryable error — skipping retries")
                        return None

                    if attempt < MAX_RETRIES - 1:
                        wait = 5 * (2 ** attempt)
                        print(f"   Retrying in {wait}s...")
                        time.sleep(wait)
                    else:
                        print(f"   All {MAX_RETRIES} attempts failed")
                        return None

        return None

    @staticmethod
    def _merge_mp3_chunks(chunks: list, output_path: str) -> bool:
        """Concatenate raw MP3 byte chunks into a single file."""
        try:
            with open(output_path, "wb") as f:
                for chunk in chunks:
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"❌ [GCP] MP3 merge error: {e}")
            return False

    def generate_audio(self, text: str, output_path: str,
                       allocated_duration: float = None) -> bool:
        """
        Generate Telugu TTS audio and save to output_path (.mp3).
        allocated_duration is unused — kept for API compatibility with Sarvam handler.
        """
        if not text or not text.strip():
            print("⚠️  [GCP] TTS skipped — empty text received")
            return False

        if not _GOOGLE_TTS_AVAILABLE:
            print("❌ [GCP] google-cloud-texttospeech not installed — TTS aborted")
            return False

        text = text.strip()
        print(f"🔤 [GCP] TTS [{self.voice_name}] ({len(text)} chars): {text[:100]!r}")

        chunks    = self._chunk_text(text, max_bytes=4500)
        all_audio = []

        for idx, chunk in enumerate(chunks):
            print(f"   [GCP] TTS chunk {idx + 1}/{len(chunks)} ({len(chunk.encode('utf-8'))} bytes)")
            audio = self._call_tts_api(chunk)
            if audio is None:
                print(f"❌ [GCP] TTS chunk {idx + 1} failed — aborting")
                return False
            all_audio.append(audio)

        if not all_audio:
            print("❌ [GCP] TTS returned no audio")
            return False

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        success = self._merge_mp3_chunks(all_audio, output_path)
        if success:
            size_kb = os.path.getsize(output_path) / 1024
            print(f"✅ [GCP] TTS saved → {output_path}  [{self.voice_name}]  ({size_kb:.1f} KB)")
        return success
