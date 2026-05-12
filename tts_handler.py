"""
TTS Handler - Sarvam AI Text-to-Speech
Dual-model setup:
  - manan (bulbul:v3) — Male anchor voice
  - arya  (bulbul:v2) — Female presenter voice

Voice alternation rule:
  Even items (0, 2, 4...) → manan (male)
  Odd items  (1, 3, 5...) → arya  (female)

  SAME voice is used for ALL audio of that item:
    headline + script + intro + analysis → all same voice
"""
import io
import requests
import os
import threading
import time
from config import SARVAM_API_KEY
import base64
import wave

# Global lock — ek waqt mein sirf ek TTS request Sarvam pe jaayegi
_TTS_LOCK = threading.Lock()

# ── Voice Alternation System ──────────────────────────────────────────────────
_voice_counter_lock = threading.Lock()
_voice_counter       = 0


def set_voice_counter(n: int):
    """
    Force-set the voice counter to n.
    Call this BEFORE TTSHandler.for_item() with the current count of
    already-saved metadata items so the alternation stays consistent
    across server restarts.

    Usage (in main.py, before processing a new item):
        from tts_handler import set_voice_counter
        from bulletin_builder import load_metadata
        set_voice_counter(len(load_metadata()))
        item_tts = TTSHandler.for_item()
    """
    global _voice_counter
    with _voice_counter_lock:
        _voice_counter = n
    print(f"🔁  Voice counter set to {n} → next voice = {'manan' if n % 2 == 0 else 'arya'}")


def _get_alternate_voice() -> str:
    """
    Returns 'manan' or 'arya' alternating with each call.
    Thread-safe. Call ONCE per news item.
    """
    global _voice_counter
    with _voice_counter_lock:
        voice = "manan" if (_voice_counter % 2 == 0) else "arya"
        _voice_counter += 1
    gender = "♂ MALE" if voice == "manan" else "♀ FEMALE"
    print(f"🔄  Voice Alternation #{_voice_counter - 1}: {voice.upper()} ({gender})")
    return voice


class TTSHandler:
    """
    Handle Sarvam AI TTS with dual-model support.

    Per-item usage (recommended):
        item_tts = TTSHandler.for_item()
        # Use item_tts for ALL audio: headline + script + intro + analysis
        item_tts.generate_audio(headline_text,  headline_path)
        item_tts.generate_audio(script_text,    script_path)
        item_tts.generate_audio(intro_text,     intro_path)
        item_tts.generate_audio(analysis_text,  analysis_path)

    Direct usage:
        TTSHandler(speaker="manan")   ← male
        TTSHandler(speaker="arya")    ← female
    """

    _SPEAKER_MODEL = {
        "manan": "bulbul:v3",   # Male anchor
        "arya":  "bulbul:v2",   # Female presenter
    }

    def __init__(self, speaker: str = None):
        self.api_key  = SARVAM_API_KEY
        self.base_url = "https://api.sarvam.ai/text-to-speech"
        spk           = (speaker or "manan").lower()
        self.speaker  = spk
        self.model    = self._SPEAKER_MODEL.get(spk, "bulbul:v3")
        print(f"🎙️  TTSHandler ready: speaker={self.speaker.upper()} | model={self.model}")

    @classmethod
    def for_item(cls) -> "TTSHandler":
        """
        Pick an alternating voice for a complete news item.
        Call ONCE per item — use the same instance for ALL audio
        (headline, script, intro, analysis).

        Always call set_voice_counter(len(load_metadata())) before this
        so the sequence survives server restarts.
        """
        voice = _get_alternate_voice()
        return cls(speaker=voice)

    # ── kept for backward compat — both map to same voice now ────────────────
    @classmethod
    def for_script(cls) -> "TTSHandler":
        """Deprecated: use for_item() instead."""
        return cls(speaker="manan")

    @classmethod
    def for_headline(cls) -> "TTSHandler":
        """Deprecated: use for_item() instead."""
        return cls(speaker="arya")

    # ── Text chunking ─────────────────────────────────────────────────────────
    def _chunk_text(self, text: str, max_chars: int = 500) -> list:
        words = text.split()
        chunks, current = [], []
        current_len = 0
        for word in words:
            if current_len + len(word) + 1 > max_chars:
                chunks.append(' '.join(current))
                current, current_len = [word], len(word)
            else:
                current.append(word)
                current_len += len(word) + 1
        if current:
            chunks.append(' '.join(current))
        return chunks

    # ── Sarvam API call ───────────────────────────────────────────────────────
    def _call_tts_api(self, inputs: list, headers: dict, pace: float = 1.2) -> list:
        MAX_RETRIES = 3
        with _TTS_LOCK:
            for attempt in range(MAX_RETRIES):
                try:
                    payload = {
                        "inputs":               inputs,
                        "target_language_code": "te-IN",
                        "speaker":              self.speaker,
                        "model":                self.model,
                        "pace":                 pace,
                        "speech_sample_rate":   22050,
                        "enable_preprocessing": True,
                    }
                    response = requests.post(self.base_url, headers=headers, json=payload)
                    response.raise_for_status()
                    audios = response.json().get("audios", [])
                    return [base64.b64decode(a) for a in audios]

                except requests.exceptions.HTTPError as e:
                    try:
                        err_body = e.response.json()
                    except Exception:
                        err_body = e.response.text if e.response else str(e)
                    print(f"❌ TTS attempt {attempt+1} HTTP {e.response.status_code}: {err_body}")
                    if e.response is not None and e.response.status_code == 400:
                        print(f"   ⚠️ 400 Bad Request — skipping retries")
                        return None
                    wait = 5 * (2 ** attempt)
                    if attempt < MAX_RETRIES - 1:
                        print(f"   Retrying in {wait}s...")
                        time.sleep(wait)
                    else:
                        print(f"   All {MAX_RETRIES} attempts failed")
                        return None

                except Exception as e:
                    wait = 5 * (2 ** attempt)
                    print(f"❌ TTS attempt {attempt+1} failed: {e}")
                    if attempt < MAX_RETRIES - 1:
                        print(f"   Retrying in {wait}s...")
                        time.sleep(wait)
                    else:
                        print(f"   All {MAX_RETRIES} attempts failed")
                        return None

    # ── Main generate function ────────────────────────────────────────────────
    def generate_audio(self, text: str, output_path: str,
                       allocated_duration: float = None) -> bool:

        if not text or not text.strip():
            print(f"⚠️ TTS skipped — empty text received")
            return False

        text = text.strip()
        print(f"🔤 TTS [{self.speaker}/{self.model}] ({len(text)} chars): {text[:100]!r}")

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type":         "application/json"
        }

        chunks     = self._chunk_text(text, max_chars=500)
        pace       = 1.2
        BATCH_SIZE = 3
        all_raw    = []

        try:
            for i in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[i : i + BATCH_SIZE]
                print(f"TTS: Sending batch {i // BATCH_SIZE + 1} ({len(batch)} chunks)")
                raw = self._call_tts_api(batch, headers, pace)

                if raw is None:
                    print(f"❌ TTS batch {i // BATCH_SIZE + 1} failed — skipping")
                    return False
                if not raw:
                    print(f"TTS Error: no audio in batch {i // BATCH_SIZE + 1}")
                    return False
                all_raw.extend(raw)

            if not all_raw:
                print("TTS Error: no audio in response")
                return False

            if len(all_raw) == 1:
                with open(output_path, 'wb') as f:
                    f.write(all_raw[0])
            else:
                wav_buffers = [wave.open(io.BytesIO(chunk), 'rb') for chunk in all_raw]
                params = wav_buffers[0].getparams()
                with wave.open(output_path, 'wb') as out_wav:
                    out_wav.setparams(params)
                    for buf in wav_buffers:
                        out_wav.writeframes(buf.readframes(buf.getnframes()))
                for buf in wav_buffers:
                    buf.close()

            print(f"✅ TTS saved → {output_path}  [{self.speaker} / {self.model}]")
            return True

        except Exception as e:
            print(f"TTS Error: {e}")
            return False


# ── Channel → TTS provider factory ───────────────────────────────────────────

_CHANNEL_KEYWORDS = {
    "Karimnagar": ["karimnagar", "jagtial", "mancherial", "ramagundam"],
    "Khammam":    ["khammam", "kothagudem", "bhadrachalam"],
    "Kurnool":    ["kurnool", "nandyal", "proddatur"],
    "Anatpur":    ["anantapur", "anatpur", "hindupur", "dharmavaram"],
    "Kakinada":   ["kakinada", "rajahmundry", "eluru"],
    "Nalore":     ["nellore", "nalore", "ongole"],
    "Tirupati":   ["tirupati", "chittoor", "kadapa"],
    "Guntur":     ["guntur", "tenali", "narasaraopet", "palnadu"],
    "Warangal":   ["warangal", "hanamkonda", "kazipet", "jangaon"],
    "Nalgonda":   ["nalgonda", "miryalaguda", "suryapet", "kodad"],
}


def detect_channel(location_name: str) -> str:
    """
    Fast channel detection from a location string.
    Reads the bulletin_builder location-cache first, then keyword matching.
    Returns a channel name; defaults to 'Kurnool' if unknown.
    """
    import json
    import os as _os

    loc_lower = (location_name or "").lower()

    cache_file = _os.path.join(_os.path.dirname(__file__), '.location_channel_cache.json')
    if _os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cache = json.load(f)
            if location_name in cache:
                return cache[location_name]
        except Exception:
            pass

    for channel, keywords in _CHANNEL_KEYWORDS.items():
        if any(k in loc_lower for k in keywords):
            print(f"[TTS-CH] location='{location_name}' → channel='{channel}' (keyword match)")
            return channel
    print(f"[TTS-CH] location='{location_name}' → channel='Kurnool' (default fallback)")
    return "Kurnool"


def get_tts_for_channel(channel_name: str, voice_counter_n: int) -> TTSHandler:
    """
    Factory: picks Sarvam or GCP TTS based on per-channel .env config.
    Sets the voice counter and returns a ready TTSHandler instance.

    .env config:
        TTS_PROVIDER_KURNOOL=gcp          ← Kurnool channel uses GCP TTS
        TTS_PROVIDER_DEFAULT=sarvam       ← all others default to Sarvam

    Usage in main.py:
        from tts_handler import detect_channel, get_tts_for_channel
        _item_tts = get_tts_for_channel(detect_channel(location_name), voice_counter_n)
    """
    from config import get_channel_tts_provider
    provider = get_channel_tts_provider(channel_name)
    print(f"🎛️  Channel '{channel_name}' → TTS provider: {provider.upper()}")

    if provider == "gcp":
        import tts_handler_gcp as _gcp
        _gcp.set_voice_counter(voice_counter_n)
        return _gcp.TTSHandler.for_item()
    else:
        set_voice_counter(voice_counter_n)
        return TTSHandler.for_item()