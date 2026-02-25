"""
OpenAI Handler - Script & headline generation via OpenAI (gpt-4o)
             - Audio transcription via OpenAI Whisper (whisper-1)

Drop-in replacement for groq_handler.py
"""
import requests
from openai import OpenAI
from typing import Optional

from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_WHISPER_MODEL,
    TELUGU_NEWS_SCRIPT_PROMPT,
    TELUGU_HEADLINE_PROMPT,
)


class OpenAIHandler:
    """
    Handles:
      - Telugu news script generation  → OpenAI (gpt-4o)
      - Telugu headline generation     → OpenAI (gpt-4o)
      - Audio transcription            → OpenAI Whisper (whisper-1)
    """

    def __init__(self):
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set in .env")
        self.client        = OpenAI(api_key=OPENAI_API_KEY)
        self.model         = OPENAI_MODEL
        self.whisper_model = OPENAI_WHISPER_MODEL


    def generate_news_script(self, text_content: str) -> Optional[str]:
        """
        Generate a broadcast-ready Telugu news script from text content
        (user message, transcript, or a combination of both).

        Args:
            text_content: Raw input text to turn into a Telugu news script

        Returns:
            Telugu news script string, or None on failure
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": TELUGU_NEWS_SCRIPT_PROMPT},
                    {"role": "user",   "content": text_content}
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": TELUGU_HEADLINE_PROMPT},
                    {"role": "user",   "content": f"News Script:\n\n{script}"}
                ],
                temperature=0.3,
                max_tokens=250,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ OpenAI headline generation error: {e}")
            return None


    def transcribe_audio(self, audio_path: str) -> Optional[str]:
        """
        Transcribe an audio file using OpenAI Whisper (whisper-1).
        Works for standalone audio messages AND audio extracted from videos.

        Supported formats: MP3, MP4, MPEG, MPGA, M4A, WAV, WEBM
        Max file size: 25 MB (OpenAI limit).

        Args:
            audio_path: Local path to the audio file

        Returns:
            Transcribed text string, or None on failure
        """
        try:
            print(f"🎙️ Transcribing audio via OpenAI Whisper: {audio_path}")

            with open(audio_path, 'rb') as audio_file:
                response = self.client.audio.transcriptions.create(
                    model=self.whisper_model,
                    file=audio_file,
                    language="te",        # Telugu; remove for auto-detect
                    response_format="text"
                )

            transcript = response.strip() if isinstance(response, str) else response

            if not transcript:
                print("⚠️ Whisper returned empty transcript")
                return None

            print(f"✅ Transcription complete ({len(transcript)} chars)")
            return transcript

        except Exception as e:
            print(f"❌ OpenAI Whisper error: {e}")
            return None