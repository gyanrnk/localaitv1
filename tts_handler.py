
"""
TTS Handler - Sarvam AI Text-to-Speech
"""
import io
import requests
import os
from config import SARVAM_API_KEY
import base64
import wave


class TTSHandler:
    """Handle Sarvam AI TTS"""
    
    def __init__(self):
        self.api_key = SARVAM_API_KEY
        self.base_url = "https://api.sarvam.ai/text-to-speech"
    
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

    def _call_tts_api(self, inputs: list, headers: dict) -> list:
        """Call Sarvam TTS API with a batch of inputs (max 3). Returns list of raw audio bytes."""
        data = {
            "inputs": inputs,
            "target_language_code": "te-IN",
            "speaker": "arya",
            "pitch": 0,
            "pace": 1.0,
            "loudness": 1.5,
            "speech_sample_rate": 22050,
            "enable_preprocessing": False,
            "model": "bulbul:v2"
        }
        response = requests.post(self.base_url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        audios = result.get("audios", [])
        return [base64.b64decode(a) for a in audios]

    def generate_audio(self, text: str, output_path: str) -> bool:
        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json"
        }

        chunks = self._chunk_text(text, max_chars=500)
        print(f"TTS: {len(chunks)} chunks generated from text")

        # Sarvam API allows max 3 inputs per request — batch accordingly
        BATCH_SIZE = 3
        all_raw_chunks = []

        try:
            for i in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[i:i + BATCH_SIZE]
                print(f"TTS: Sending batch {i // BATCH_SIZE + 1} ({len(batch)} chunks)")
                raw = self._call_tts_api(batch, headers)
                if not raw:
                    print(f"TTS Error: no audio returned for batch {i // BATCH_SIZE + 1}")
                    return False
                all_raw_chunks.extend(raw)

            if not all_raw_chunks:
                print("TTS Error: no audio in response")
                return False

            if len(all_raw_chunks) == 1:
                with open(output_path, 'wb') as f:
                    f.write(all_raw_chunks[0])
            else:
                wav_buffers = [wave.open(io.BytesIO(chunk), 'rb') for chunk in all_raw_chunks]
                params = wav_buffers[0].getparams()

                with wave.open(output_path, 'wb') as out_wav:
                    out_wav.setparams(params)
                    for buf in wav_buffers:
                        out_wav.writeframes(buf.readframes(buf.getnframes()))

                for buf in wav_buffers:
                    buf.close()

            print(f"TTS: Audio saved to {output_path}")
            return True

        except Exception as e:
            print(f"TTS Error: {e}")
            return False