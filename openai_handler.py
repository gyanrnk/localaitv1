"""
OpenAI Handler - Script & headline generation via OpenAI (gpt-4o)
             - Audio transcription via OpenAI Whisper (whisper-1)

Drop-in replacement for groq_handler.py
"""
import requests
import threading
import time
from openai import OpenAI
from typing import Optional
import re
from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_HEADLINE_MODEL,
    OPENAI_WHISPER_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    TELUGU_NEWS_SCRIPT_PROMPT,
    TELUGU_HEADLINE_PROMPT,
)


class OpenAIHandler:
    """
    Handles:
      - Telugu news script generation  → OpenAI (gpt-4o)
      - Telugu headline generation     → OpenAI (gpt-4o-mini)
      - Audio transcription            → OpenAI Whisper
    """

    def __init__(self):
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set in .env")
        self.client         = OpenAI(api_key=OPENAI_API_KEY)
        self.model          = OPENAI_MODEL
        self.headline_model = OPENAI_HEADLINE_MODEL
        self.whisper_model  = OPENAI_WHISPER_MODEL
        self._semaphore     = threading.Semaphore(1)  # max 1 concurrent OpenAI call


    def generate_news_script(self, input_text: str, structure_hint: dict = None, target_words: int = None) -> dict:
        """
        Generate news script with optional structure guidance.

        Args:
            input_text: Combined text/transcript
            structure_hint: Optional dict from clip_analyzer with structure recommendation
        """

        # Build structure instruction
        structure_instruction = ""
        if structure_hint and structure_hint.get('clip_info'):
            structure = structure_hint['structure']
            clip_text = structure_hint['clip_info']['text']

            if structure == 'clip_first':
                structure_instruction = f"""
    STRUCTURE DIRECTIVE: CLIP-FIRST (High-impact opening)
    The identified clip is strong and self-contained. Use this structure:
    1. Start with the clip directly (no intro)
    2. Then provide context and analysis in Telugu TTS

    Key clip: "{clip_text}"
    This clip should be the OPENING of your video.
    """
            elif structure == 'narrative':
                structure_instruction = f"""
    STRUCTURE DIRECTIVE: NARRATIVE BUILD
    The clip needs context. Use this structure:
    1. Telugu TTS intro (set the scene)
    2. Telugu TTS analysis (build understanding)
    3. End with the clip as confirmation/payoff

    Key clip: "{clip_text}"
    """
            else:  # standard
                structure_instruction = f"""
    STRUCTURE DIRECTIVE: STANDARD (Intro → Clip → Analysis)
    Use traditional news flow:
    1. Telugu TTS intro (brief context)
    2. The clip
    3. Telugu TTS analysis

    Key clip: "{clip_text}"
    """

        try:
            system_prompt = TELUGU_NEWS_SCRIPT_PROMPT
            system_prompt += (
                "\n\nCRITICAL: The input content may be in ANY language (Urdu, Hindi, English, etc.). "
                "You MUST translate and rewrite everything into professional Telugu script only. "
                "NEVER output any Urdu, Hindi, Arabic, or English words in the script. "
                "Every single word of output must be in Telugu script (తెలుగు)."
            )
            if target_words:
                system_prompt += (
                    f"\n\nTARGET LENGTH: Approximately {target_words} words. "
                    f"Complete the story naturally within this length — proper ending mandatory, no abrupt cuts."
                )

            with self._semaphore:
                time.sleep(1.5)  # breathing room between calls
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": input_text}
                    ],
                    temperature=0.3,
                    max_tokens=2000,
                )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ OpenAI script generation error: {e}")
            return None


    def generate_headline(self, script: str) -> Optional[str]:
        """
        Generate a short Telugu headline from a news script.

        Args:
            script: The Telugu news script

        Returns:
            Telugu headline string, or None on failure
        """
        try:
            with self._semaphore:
                time.sleep(1.5)  # breathing room between calls
                response = self.client.chat.completions.create(
                    model=self.headline_model,  # gpt-4o-mini
                    messages=[
                        {"role": "system", "content": TELUGU_HEADLINE_PROMPT +
                         "\n\nCRITICAL: Headline must be maximum 5-7 words only. Short and punchy. No long sentences."},
                        {"role": "user",   "content": f"News Script:\n\n{script}"}
                    ],
                    temperature=0.3,
                    max_tokens=50,
                )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ OpenAI headline generation error: {e}")
            return None


    def transcribe_audio(self, audio_path: str) -> dict:
        import io, os, subprocess, tempfile

        # Convert webm/ogg/m4a to mp3 before sending — OpenAI rejects raw webm bytes
        _send_path = audio_path
        _tmp_mp3   = None
        ext = os.path.splitext(audio_path)[1].lower()
        if ext in ('.webm', '.ogg', '.m4a', '.opus'):
            try:
                _tmp_mp3 = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
                _tmp_mp3.close()
                r = subprocess.run(
                    ['ffmpeg', '-y', '-i', audio_path, '-ar', '16000', '-ac', '1',
                     '-b:a', '64k', _tmp_mp3.name],
                    capture_output=True, timeout=60
                )
                if r.returncode == 0:
                    _send_path = _tmp_mp3.name
            except Exception as _ce:
                print(f"⚠️ webm→mp3 convert failed: {_ce}, sending original")

        try:
            send_name = os.path.basename(_send_path)
            with open(_send_path, 'rb') as f:
                audio_bytes = f.read()

            # Try verbose_json first (timestamps); fall back to json if model rejects it
            try:
                response = self.client.audio.transcriptions.create(
                    model=self.whisper_model,
                    file=(send_name, io.BytesIO(audio_bytes)),
                    response_format='verbose_json',
                    timestamp_granularities=['segment'],
                )
                segments = [
                    {'start': s.start, 'end': s.end, 'text': s.text}
                    for s in (getattr(response, 'segments', None) or [])
                ]
            except Exception:
                response = self.client.audio.transcriptions.create(
                    model=self.whisper_model,
                    file=(send_name, io.BytesIO(audio_bytes)),
                    response_format='json',
                )
                segments = []

            text = getattr(response, 'text', '') or ''

            # fallback: if model returns no segments, estimate from words
            if text.strip() and not segments:
                words, WPS, t = text.strip().split(), 2.2, 0.0
                for i in range(0, len(words), 8):
                    chunk = words[i:i+8]
                    dur = len(chunk) / WPS
                    segments.append({'start': round(t, 2), 'end': round(t + dur, 2), 'text': ' '.join(chunk)})
                    t += dur

            return {'text': text or '', 'segments': segments}
        except Exception as e:
            print(f"❌ Transcription error: {e}")
            return {'text': '', 'segments': []}
        finally:
            if _tmp_mp3:
                try: os.unlink(_tmp_mp3.name)
                except: pass


    def generate_editorial_plan(self, transcript_text: str) -> str:
        """
        Generates structured editorial plan JSON for a single news story.
        Returns raw JSON string (validated later in editorial_planner.py).
        """
        from config import EDITORIAL_PLANNER_PROMPT

        TELUGU_EDITORIAL_SYSTEM = (
            EDITORIAL_PLANNER_PROMPT +
            "\n\nCRITICAL LANGUAGE RULE: tts_intro and tts_analysis fields in your JSON "
            "MUST be written entirely in Telugu script (తెలుగు లిపి). "
            "Zero tolerance for English, Urdu, Hindi, or Arabic in those fields."
        )

        with self._semaphore:
            time.sleep(1.5)  # breathing room between calls
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": TELUGU_EDITORIAL_SYSTEM},
                    {"role": "user",   "content": f"Transcript:\n{transcript_text}"}
                ],
                temperature=0.3,
            )

        return response.choices[0].message.content.strip()
    
    def translate_to_telugu(self, text: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": f"Translate this place name to Telugu script only. Reply with ONLY the Telugu text, nothing else: {text}"
                }],
                max_tokens=20,
                temperature=0,
            )
            return resp.choices[0].message.content.strip()
        except:
            return text


class GeminiHandler:
    """Gemini API handler — same interface as OpenAIHandler for script/headline generation."""

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set in .env")
        self.client = OpenAI(
            api_key=GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.model          = GEMINI_MODEL
        self.headline_model = GEMINI_MODEL
        self._semaphore     = threading.Semaphore(1)

    def generate_news_script(self, input_text: str, structure_hint: dict = None, target_words: int = None) -> Optional[str]:
        system_prompt = TELUGU_NEWS_SCRIPT_PROMPT + (
            "\n\nCRITICAL: The input content may be in ANY language (Urdu, Hindi, English, etc.). "
            "You MUST translate and rewrite everything into professional Telugu script only. "
            "NEVER output any Urdu, Hindi, Arabic, or English words in the script. "
            "Every single word of output must be in Telugu script (తెలుగు)."
        )
        if target_words:
            system_prompt += (
                f"\n\nTARGET LENGTH: Approximately {target_words} words. "
                f"Complete the story naturally within this length — proper ending mandatory, no abrupt cuts."
            )
        try:
            with self._semaphore:
                time.sleep(1.0)
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": input_text},
                    ],
                    temperature=0.3,
                    max_tokens=2000,
                )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ Gemini script generation error: {e}")
            return None

    def generate_headline(self, script: str) -> Optional[str]:
        try:
            with self._semaphore:
                time.sleep(1.0)
                response = self.client.chat.completions.create(
                    model=self.headline_model,
                    messages=[
                        {"role": "system", "content": TELUGU_HEADLINE_PROMPT +
                         "\n\nCRITICAL: Headline must be maximum 5-7 words only. Short and punchy. No long sentences."},
                        {"role": "user",   "content": f"News Script:\n\n{script}"},
                    ],
                    temperature=0.3,
                    max_tokens=50,
                )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ Gemini headline generation error: {e}")
            return None

    def generate_editorial_plan(self, transcript_text: str) -> str:
        from config import EDITORIAL_PLANNER_PROMPT
        system_prompt = (
            EDITORIAL_PLANNER_PROMPT +
            "\n\nCRITICAL LANGUAGE RULE: tts_intro and tts_analysis fields in your JSON "
            "MUST be written entirely in Telugu script (తెలుగు లిపి). "
            "Zero tolerance for English, Urdu, Hindi, or Arabic in those fields."
        )
        with self._semaphore:
            time.sleep(1.0)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": f"Transcript:\n{transcript_text}"},
                ],
                temperature=0.3,
            )
        return response.choices[0].message.content.strip()

    def translate_to_telugu(self, text: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": f"Translate this place name to Telugu script only. Reply with ONLY the Telugu text, nothing else: {text}"
                }],
                max_tokens=20,
                temperature=0,
            )
            return resp.choices[0].message.content.strip()
        except:
            return text

    def transcribe_audio(self, audio_path: str) -> dict:
        import os, subprocess, tempfile
        from google import genai as google_genai

        # Convert to mp3 if needed
        _send_path = audio_path
        _tmp_mp3   = None
        ext = os.path.splitext(audio_path)[1].lower()
        if ext in ('.webm', '.ogg', '.m4a', '.opus'):
            try:
                _tmp_mp3 = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
                _tmp_mp3.close()
                r = subprocess.run(
                    ['ffmpeg', '-y', '-i', audio_path, '-ar', '16000', '-ac', '1',
                     '-b:a', '64k', _tmp_mp3.name],
                    capture_output=True, timeout=60
                )
                if r.returncode == 0:
                    _send_path = _tmp_mp3.name
            except Exception as _ce:
                print(f"⚠️ webm→mp3 convert failed: {_ce}, sending original")

        try:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            audio_file = client.files.upload(file=_send_path)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    'Transcribe this audio verbatim in the original language. Return only the transcription text, nothing else.',
                    audio_file,
                ],
            )
            text = (response.text or '').strip()

            try:
                client.files.delete(name=audio_file.name)
            except Exception:
                pass

            # Estimate segments from words (Gemini doesn't provide timestamps)
            segments = []
            if text:
                words, WPS, t = text.split(), 2.2, 0.0
                for i in range(0, len(words), 8):
                    chunk = words[i:i+8]
                    dur = len(chunk) / WPS
                    segments.append({'start': round(t, 2), 'end': round(t + dur, 2), 'text': ' '.join(chunk)})
                    t += dur

            return {'text': text, 'segments': segments}
        except Exception as e:
            print(f"❌ Gemini transcription error: {e}")
            return {'text': '', 'segments': []}
        finally:
            if _tmp_mp3:
                try: os.unlink(_tmp_mp3.name)
                except: pass


def get_llm_handler(location_name: str = ''):
    """Returns GeminiHandler for all locations."""
    if GEMINI_API_KEY:
        return GeminiHandler()
    print("⚠️  GEMINI_API_KEY not set — falling back to OpenAI")
    return OpenAIHandler()

