# """
# Main News Bot - Entry Point

# Processing logic:
#   Text + Video  → extract audio from video → Sarvam STT → combine text+video_transcript → Groq → script
#   Text + Audio  → Sarvam STT → combine text+transcript → Groq → script
#   Text + Image  → image is saved/stored only, script generated from TEXT alone via Groq
#   Text only     → Groq → script  (after 30s timeout waiting for media)
#   Media + User-Audio → extract if video + user-audio transcript → combine both → script
#   Media + Text + User-Audio → extract video audio (if video) + combine text + user-audio → script
#   Media only    → SKIP (discarded in message queue — no text/caption/audio)
# """

# from asyncio.log import logger
# from datetime import datetime
# from typing import Optional
# import os
# import tempfile
# import subprocess

# from message_queue import MessageQueue
# from gupshup_handler import GupshupHandler
# from file_manager import FileManager
# from media_handler import MediaHandler
# from telugu_processor import TeluguProcessor
# from tts_handler import TTSHandler
# from bulletin_builder import append_news_item
# from config import OUTPUT_AUDIO_DIR
# from openai_handler import OpenAIHandler


# class NewsBot:
#     """Main News Bot orchestrator"""

#     def __init__(self):
#         self.gupshup       = GupshupHandler()
#         self.file_manager  = FileManager()
#         self.media_handler = MediaHandler()
#         self.groq = OpenAIHandler()
#         self.telugu        = TeluguProcessor()
#         self.message_queue = MessageQueue(text_wait_timeout=30)
#         self.tts           = TTSHandler()


#     def _extract_audio_from_video(self, video_path: str) -> Optional[str]:
#         """
#         Extract audio track from video using ffmpeg.
#         Returns path to a temp .mp3 file, or None on failure.
#         Install ffmpeg: apt-get install ffmpeg
#         """
#         try:
#             audio_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
#             audio_temp.close()

#             cmd = [
#                 'ffmpeg', '-y',
#                 '-i', video_path,
#                 '-vn',
#                 '-acodec', 'libmp3lame',
#                 '-ab', '128k',
#                 '-ar', '44100',
#                 audio_temp.name
#             ]
#             result = subprocess.run(
#                 cmd,
#                 stdout=subprocess.PIPE,
#                 stderr=subprocess.PIPE,
#                 timeout=120
#             )

#             if result.returncode != 0:
#                 print(f"❌ ffmpeg error: {result.stderr.decode()[:300]}")
#                 os.unlink(audio_temp.name)
#                 return None

#             print(f"✅ Audio extracted from video → {audio_temp.name}")
#             return audio_temp.name

#         except FileNotFoundError:
#             print("❌ ffmpeg not found. Run: apt-get install ffmpeg")
#             return None
#         except subprocess.TimeoutExpired:
#             print("❌ ffmpeg timed out")
#             return None
#         except Exception as e:
#             print(f"❌ Audio extraction error: {e}")
#             return None


#     def _process_matched_message(self, matched: dict) -> dict:
#         """Download media (if any) and call process_message()"""
#         sender = matched.get('sender') or ''
#         if not sender:
#             logger.warning("⚠️ No sender in matched message")
#             return {'success': False, 'error': 'No sender'}

#         text       = matched.get('text')
#         media_info = matched.get('media')
#         user_audio_info = matched.get('user_audio')

#         media_path = None
#         if media_info:
#             ext_map   = {'image': '.jpg', 'video': '.mp4', 'audio': '.mp3'}
#             ext       = ext_map.get(media_info.get('type', ''), '.bin')
#             media_url = media_info.get('url', '')

#             if not media_url or not media_url.startswith('http'):
#                 print(f"⚠️ Skipping media download: invalid URL '{media_url}'")
#             else:
#                 tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
#                 tmp.close()
#                 if self.gupshup.download_media(media_url, tmp.name):
#                     media_path = tmp.name
#                 else:
#                     os.unlink(tmp.name)

#         user_audio_path = None
#         if user_audio_info:
#             audio_url = user_audio_info.get('url', '')
#             if audio_url and audio_url.startswith('http'):
#                 tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
#                 tmp.close()
#                 if self.gupshup.download_media(audio_url, tmp.name):
#                     user_audio_path = tmp.name
#                 else:
#                     os.unlink(tmp.name)

#         result = self.process_message(text=text, media_path=media_path, user_audio_path=user_audio_path, sender=sender)
#         result['sender'] = sender
#         return result

#     def process_gupshup_webhook(self, webhook_data: dict) -> dict:
#         """Parse Gupshup webhook and route to message queue"""
#         message_data = self.gupshup.parse_webhook_message(webhook_data)
#         sender       = message_data['sender']
#         message_id   = message_data['message_id']
#         matched      = None

#         if message_data['media_type']:
#             # Treat incoming audio as user_audio for matching
#             msg_type = 'user_audio' if message_data['media_type'] == 'audio' else message_data['media_type']
#             matched = self.message_queue.add_message(
#                 sender=sender,
#                 message_type=msg_type,
#                 data={
#                     'url':  message_data['media_url'],
#                     'type': message_data['media_type'],
#                     'text': message_data['text'],
#                 },
#                 message_id=message_id
#             )
#         elif message_data['text']:
#             matched = self.message_queue.add_message(
#                 sender=sender,
#                 message_type='text',
#                 data={'text': message_data['text']},
#                 message_id=message_id
#             )

#         if matched:
#             if matched.get('duplicate'):
#                 return {'success': True, 'duplicate': True, 'sender': sender}
#             return self._process_matched_message(matched)

#         return {'success': True, 'waiting': True, 'sender': sender}


#     def process_message(self, text: str = None, media_path: str = None, 
#                         user_audio_path: str = None, sender: str = None) -> dict:
#         """
#         Full pipeline:
#           1. Save input media
#           2. Build content for script (see module docstring for priority)
#           3. Convert numbers + clean Telugu text
#           4. Generate headline via Groq
#           5. TTS audio (script + headline) via Sarvam AI
#           6. Save all outputs
#           7. Cleanup temp files
#         """
#         result = {
#             'success':    False,
#             'script':     None,
#             'headline':   None,
#             'media_info': None,
#             'files':      {},
#             'audio_path': None,
#             'error':      None
#         }

#         print("=" * 60)
#         print("📱 PROCESSING NEW MESSAGE")
#         print("=" * 60)

#         media_info = None
#         if media_path and os.path.exists(media_path):
#             print("💾 Saving input media...")
#             media_info = self.file_manager.save_input_media(media_path)
#             if media_info:
#                 result['media_info']           = media_info
#                 self.media_handler.media_path  = media_info['input_path']
#                 self.media_handler.media_type  = media_info['type']

#         media_type = media_info['type'] if media_info else None

#         script               = None
#         extracted_audio_path = None
#         user_audio_transcript = None

#         # Transcribe user-provided audio if available
#         if user_audio_path and os.path.exists(user_audio_path):
#             print("🎙️ Transcribing user-provided audio...")
#             user_audio_transcript = self.groq.transcribe_audio(user_audio_path)
#             if user_audio_transcript:
#                 print("✅ User-audio transcribed")

#         if media_type == 'video':
#             print("🎬 Video received — extracting audio...")
#             extracted_audio_path = self._extract_audio_from_video(media_info['input_path'])

#             if extracted_audio_path:
#                 extracted_transcript = self.groq.transcribe_audio(extracted_audio_path)
                
#                 if extracted_transcript and user_audio_transcript:
#                     # Video + User-Audio + (optional) Text
#                     combined = self._combine_text_and_transcripts(
#                         text, extracted_transcript, user_audio_transcript
#                     )
#                     print("📝 Generating script from text + video audio + user audio (Groq)...")
#                     script = self.groq.generate_news_script(combined)
#                 elif user_audio_transcript:
#                     # Video + User-Audio (no text from message)
#                     combined = self._combine_text_and_transcripts(
#                         text, None, user_audio_transcript
#                     )
#                     print("📝 Generating script from user audio + video (Groq)...")
#                     script = self.groq.generate_news_script(combined)
#                 elif extracted_transcript:
#                     # Video + Text (existing flow)
#                     combined = self._combine_text_and_transcript(text, extracted_transcript)
#                     print("📝 Generating script from text + video transcript (Groq)...")
#                     script = self.groq.generate_news_script(combined)
#                 else:
#                     print("⚠️ Transcription failed — falling back to text only")
#                     if text and text.strip():
#                         script = self.groq.generate_news_script(text)
#             else:
#                 print("⚠️ Audio extraction failed — falling back to text/user-audio")
#                 if user_audio_transcript:
#                     combined = self._combine_text_and_transcripts(text, None, user_audio_transcript)
#                     script = self.groq.generate_news_script(combined)
#                 elif text and text.strip():
#                     script = self.groq.generate_news_script(text)

#         elif media_type == 'audio':
#             print("🎙️ Audio media received — transcribing via Sarvam AI STT...")
#             media_transcript = self.groq.transcribe_audio(media_info['input_path'])

#             if media_transcript and user_audio_transcript:
#                 # Both media audio + user audio
#                 combined = self._combine_text_and_transcripts(text, media_transcript, user_audio_transcript)
#                 print("📝 Generating script from text + media audio + user audio (Groq)...")
#                 script = self.groq.generate_news_script(combined)
#             elif user_audio_transcript:
#                 # User audio only
#                 combined = self._combine_text_and_transcripts(text, None, user_audio_transcript)
#                 print("📝 Generating script from text + user audio (Groq)...")
#                 script = self.groq.generate_news_script(combined)
#             elif media_transcript:
#                 # Media audio only
#                 combined = self._combine_text_and_transcript(text, media_transcript)
#                 print("📝 Generating script from text + media audio (Groq)...")
#                 script = self.groq.generate_news_script(combined)
#             else:
#                 print("⚠️ Transcription failed — falling back to text only")
#                 if text and text.strip():
#                     script = self.groq.generate_news_script(text)

#         elif media_type == 'image':
#             if user_audio_transcript:
#                 combined = self._combine_text_and_transcripts(text, None, user_audio_transcript)
#                 print("🖼️ Image saved. Generating script from text + user-audio (Groq)...")
#                 script = self.groq.generate_news_script(combined)
#             elif text and text.strip():
#                 print("🖼️ Image saved. Generating script from TEXT only (Groq)...")
#                 script = self.groq.generate_news_script(text)
#             else:
#                 result['error'] = "Image received but no text/audio provided — skipping"
#                 print("❌ Image with no text/audio — skipping")
#                 return result

#         elif user_audio_transcript:
#             # No media, just user-audio + text
#             combined = self._combine_text_and_transcripts(text, None, user_audio_transcript)
#             print("📝 Generating script from text + user-audio (Groq)...")
#             script = self.groq.generate_news_script(combined)
#         elif text and text.strip():
#             print("📝 Generating script from text only (Groq)...")
#             script = self.groq.generate_news_script(text)

#         else:
#             result['error'] = "No valid content to process"
#             print("❌ No valid content")
#             return result

#         if not script:
#             result['error'] = "Script generation failed"
#             print("❌ Script generation failed")
#             return result

#         print("🔄 Processing Telugu text...")
#         script = self.telugu.convert_numbers_in_text(script)
#         script = self.telugu.clean_script(script)

#         print("📰 Generating headline (Groq)...")
#         headline = self.groq.generate_headline(script)
#         if not headline:
#             print("⚠️ Headline generation failed — using default")
#             headline = "వార్త"

#         audio_temp_path = None
#         audio_generated = False

#         if media_info:
#             print("🎤 Generating script audio (Sarvam TTS)...")
#             audio_temp_path = os.path.join(
#                 tempfile.gettempdir(),
#                 f"temp_audio_{media_info['counter']}_{datetime.now().timestamp()}.mp3"
#             )
#             if self.tts.generate_audio(script, audio_temp_path):
#                 audio_generated = True
#                 print("✅ Script audio generated")
#             else:
#                 print("❌ Script audio generation failed")

#         headline_audio_temp_path = None

#         if media_info and headline:
#             print("🎤 Generating headline audio (Sarvam TTS)...")
#             headline_audio_temp_path = os.path.join(
#                 tempfile.gettempdir(),
#                 f"temp_headline_{media_info['counter']}_{datetime.now().timestamp()}.mp3"
#             )
#             if not self.tts.generate_audio(headline, headline_audio_temp_path):
#                 print("❌ Headline audio failed")
#                 headline_audio_temp_path = None

#         if media_info:
#             print("💾 Saving outputs...")
#             output_files = self.file_manager.save_outputs(
#                 script=script,
#                 headline=headline,
#                 media_counter=media_info['counter'],
#                 media_type=media_info['type'],
#                 audio_data_or_path=audio_temp_path if audio_generated else None,
#                 headline_audio_data_or_path=headline_audio_temp_path
#             )
#             result['files'] = output_files
#             if audio_generated and output_files.get('audio_path'):
#                 result['audio_path'] = output_files['audio_path']
#                 print(f"✅ Script audio saved:   {output_files.get('audio_filename')}")
#             if output_files.get('headline_audio_path'):
#                 print(f"✅ Headline audio saved: {output_files.get('headline_audio_filename')}")

#             priority = self._detect_priority(text)
#             append_news_item({
#                 'counter':           media_info['counter'],
#                 'media_type':        media_info['type'],
#                 'priority':          priority,
#                 'timestamp':         datetime.now().isoformat(),
#                 'headline':          headline,
#                 'script_filename':   output_files.get('script_filename', ''),
#                 'headline_filename': output_files.get('headline_filename', ''),
#                 'headline_audio':    output_files.get('headline_audio_filename', ''),
#                 'script_audio':      output_files.get('audio_filename', ''),
#                 'script_duration':   output_files.get('script_duration', 0.0),
#                 'headline_duration': output_files.get('headline_duration', 0.0),
#                 'total_duration':    output_files.get('total_duration', 0.0),
#             })
#             print(f"📋 Metadata saved [{priority.upper()}]")

#         for tmp in [audio_temp_path, headline_audio_temp_path, extracted_audio_path, user_audio_path]:
#             if tmp and os.path.exists(tmp):
#                 try:
#                     os.remove(tmp)
#                 except Exception:
#                     pass
#         print("🧹 Temp files cleaned up")

#         result.update({'success': True, 'script': script, 'headline': headline})
#         print("✅ Processing complete!")
#         print("=" * 60)
#         return result


#     @staticmethod
#     def _detect_priority(text: Optional[str]) -> str:
#         """
#         Detect priority tag from reporter's WhatsApp message text.
#         Looks for #breaking or #urgent (case-insensitive).
#         Returns: 'breaking' | 'urgent' | 'normal'
#         """
#         if not text:
#             return 'normal'
#         text_lower = text.lower()
#         if '#breaking' in text_lower:
#             return 'breaking'
#         if '#urgent' in text_lower:
#             return 'urgent'
#         return 'normal'

#     @staticmethod
#     def _combine_text_and_transcript(text: Optional[str], transcript: str) -> str:
#         """
#         Merge user-provided context text with the audio/video transcript.
#         Clear labels help Groq understand which part is which.
#         """
#         if text and text.strip():
#             return (
#                 f"[Reporter Context]: {text.strip()}\n\n"
#                 f"[Audio Transcript]: {transcript.strip()}"
#             )
#         return transcript.strip()

#     @staticmethod
#     def _combine_text_and_transcripts(text: Optional[str], extracted_transcript: Optional[str], 
#                                      user_audio_transcript: Optional[str]) -> str:
#         """
#         Combine up to 3 sources: text, extracted video audio, user-provided audio.
#         """
#         parts = []
        
#         if text and text.strip():
#             parts.append(f"[Reporter Context]: {text.strip()}")
        
#         if extracted_transcript and extracted_transcript.strip():
#             parts.append(f"[Video Audio Transcript]: {extracted_transcript.strip()}")
        
#         if user_audio_transcript and user_audio_transcript.strip():
#             parts.append(f"[User Audio Transcript]: {user_audio_transcript.strip()}")
        
#         return "\n\n".join(parts) if parts else ""


#     def display_results(self, result: dict):
#         print("\n" + "=" * 60)
#         print("📰 GENERATED CONTENT")
#         print("=" * 60)
#         if result.get('headline'):
#             print(f"\n🏷️  HEADLINE:\n{result['headline']}\n")
#         if result.get('script'):
#             print(f"📄 SCRIPT:\n{result['script']}\n")
#         if result.get('files'):
#             files = result['files']
#             print("📁 OUTPUT FILES:")
#             if files.get('headline_filename'):
#                 print(f"   • {files['headline_filename']}")
#             if files.get('script_filename'):
#                 print(f"   • {files['script_filename']}")
#         if result.get('media_info'):
#             print(f"\n🎬 MEDIA: {result['media_info']['filename']}")
#         print("=" * 60 + "\n")

# import requests

# def fetch_pending_incidents(api_url: str, token: str):
#     """Fetch pending incidents from fullstack dev's endpoint"""
#     try:
#         headers = {
#             'Authorization': f'Bearer {token}',
#             'Content-Type': 'application/json'
#         }
#         response = requests.get(f"{api_url}?status=pending", headers=headers)
#         if response.status_code == 200:
#             return response.json().get('items', [])
#         else:
#             print(f"❌ Failed to fetch incidents: {response.status_code}")
#             return []
#     except Exception as e:
#         print(f"❌ Error fetching incidents: {e}")
#         return []

# def post_bulletin(api_url: str, token: str, bulletin_data: dict):
#     """Send processed bulletin back to fullstack endpoint"""
#     try:
#         headers = {
#             'Authorization': f'Bearer {token}',
#             'Content-Type': 'application/json'
#         }
#         response = requests.post(api_url, json=bulletin_data, headers=headers)
#         if response.status_code in [200, 201]:
#             print(f"✅ Bulletin posted: {bulletin_data.get('incident_id')}")
#             return True
#         else:
#             print(f"❌ Failed to post bulletin: {response.status_code}")
#             return False
#     except Exception as e:
#         print(f"❌ Error posting bulletin: {e}")
#         return False

        
# def main():
#     bot = NewsBot()
#     print("\n🚀 Test: text-only message")
#     result = bot.process_message(
#         text="Breaking: Indian cricket team won by 50 runs. Rohit Sharma scored 125 in 90 balls."
#     )
#     if result['success']:
#         bot.display_results(result)


# if __name__ == "__main__":
#     main()



"""
Main News Bot - Entry Point

Processing logic:
  Text + Video        → extract audio from video → Groq STT → combine text+transcript → Groq → script
  Text + Audio        → Groq STT → combine text+transcript → Groq → script
  Text + Image        → image is saved/stored only, script generated from TEXT alone via Groq
  Image + Audio       → image saved, audio transcribed via Groq STT → script from transcript
  Text + Image+Audio  → image saved, audio transcribed → combine text+transcript → Groq → script
  Text only           → Groq → script  (after 30s timeout waiting for media)
  Media only          → SKIP (discarded in message queue — no text/caption)
"""

from asyncio.log import logger
from datetime import datetime
from typing import Optional
import os
import tempfile
import subprocess

from message_queue import MessageQueue
from gupshup_handler import GupshupHandler
from file_manager import FileManager
from media_handler import MediaHandler
from telugu_processor import TeluguProcessor
from tts_handler import TTSHandler
from bulletin_builder import append_news_item
from config import OUTPUT_AUDIO_DIR
from openai_handler import OpenAIHandler


class NewsBot:
    """Main News Bot orchestrator"""

    def __init__(self):
        self.gupshup       = GupshupHandler()
        self.file_manager  = FileManager()
        self.media_handler = MediaHandler()
        self.groq          = OpenAIHandler()
        self.telugu        = TeluguProcessor()
        self.message_queue = MessageQueue(text_wait_timeout=30)
        self.tts           = TTSHandler()


    def _extract_audio_from_video(self, video_path: str) -> Optional[str]:
        try:
            audio_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            audio_temp.close()
            cmd = [
                'ffmpeg', '-y', '-i', video_path,
                '-vn', '-acodec', 'libmp3lame', '-ab', '128k', '-ar', '44100',
                audio_temp.name
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            if result.returncode != 0:
                print(f"❌ ffmpeg error: {result.stderr.decode()[:300]}")
                os.unlink(audio_temp.name)
                return None
            print(f"✅ Audio extracted from video → {audio_temp.name}")
            return audio_temp.name
        except FileNotFoundError:
            print("❌ ffmpeg not found.")
            return None
        except subprocess.TimeoutExpired:
            print("❌ ffmpeg timed out")
            return None
        except Exception as e:
            print(f"❌ Audio extraction error: {e}")
            return None


    def _process_matched_message(self, matched: dict) -> dict:
        sender = matched.get('sender') or ''
        if not sender:
            logger.warning("⚠️ No sender in matched message")
            return {'success': False, 'error': 'No sender'}

        text             = matched.get('text')
        media_info       = matched.get('media')
        media_path       = None
        extra_audio_path = None

        if media_info:
            ext_map   = {'image': '.jpg', 'video': '.mp4', 'audio': '.mp3'}
            ext       = ext_map.get(media_info.get('type', ''), '.bin')
            media_url = media_info.get('url', '')
            if not media_url or not media_url.startswith('http'):
                print(f"⚠️ Skipping media download: invalid URL '{media_url}'")
            else:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                tmp.close()
                if self.gupshup.download_media(media_url, tmp.name):
                    media_path = tmp.name
                else:
                    os.unlink(tmp.name)

        extra_media_info = matched.get('extra_media')
        if extra_media_info and extra_media_info.get('type') == 'audio':
            audio_url = extra_media_info.get('url', '')
            if audio_url and audio_url.startswith('http'):
                tmp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                tmp_audio.close()
                if self.gupshup.download_media(audio_url, tmp_audio.name):
                    extra_audio_path = tmp_audio.name
                else:
                    os.unlink(tmp_audio.name)

        result           = self.process_message(
            text=text, media_path=media_path, sender=sender,
            extra_audio_path=extra_audio_path
        )
        result['sender'] = sender
        return result


    def process_gupshup_webhook(self, webhook_data: dict) -> dict:
        message_data = self.gupshup.parse_webhook_message(webhook_data)
        sender       = message_data['sender']
        message_id   = message_data['message_id']
        matched      = None

        if message_data['media_type']:
            matched = self.message_queue.add_message(
                sender=sender,
                message_type=message_data['media_type'],
                data={
                    'url':  message_data['media_url'],
                    'type': message_data['media_type'],
                    'text': message_data['text'],
                },
                message_id=message_id
            )
        elif message_data['text']:
            matched = self.message_queue.add_message(
                sender=sender,
                message_type='text',
                data={'text': message_data['text']},
                message_id=message_id
            )

        if matched:
            if matched.get('duplicate'):
                return {'success': True, 'duplicate': True, 'sender': sender}
            return self._process_matched_message(matched)

        return {'success': True, 'waiting': True, 'sender': sender}


    def process_message(self, text: str = None, media_path: str = None,
                        sender: str = None, extra_audio_path: str = None) -> dict:
        result = {
            'success': False, 'script': None, 'headline': None,
            'media_info': None, 'files': {}, 'audio_path': None, 'error': None
        }

        print("=" * 60)
        print("📱 PROCESSING NEW MESSAGE")
        print("=" * 60)

        media_info = None
        if media_path and os.path.exists(media_path):
            print("💾 Saving input media...")
            media_info = self.file_manager.save_input_media(media_path)
            if media_info:
                result['media_info']          = media_info
                self.media_handler.media_path = media_info['input_path']
                self.media_handler.media_type = media_info['type']

        media_type           = media_info['type'] if media_info else None
        script               = None
        extracted_audio_path = None

        if media_type == 'video':
            print("🎬 Video received — extracting audio...")
            extracted_audio_path = self._extract_audio_from_video(media_info['input_path'])
            if extracted_audio_path:
                transcript = self.groq.transcribe_audio(extracted_audio_path)
                if transcript:
                    combined = self._combine_text_and_transcript(text, transcript)
                    print("📝 Generating script from text + video transcript...")
                    script = self.groq.generate_news_script(combined)
                else:
                    print("⚠️ Transcription failed — falling back to text only")
                    if text and text.strip():
                        script = self.groq.generate_news_script(text)
            else:
                print("⚠️ Audio extraction failed — falling back to text only")
                if text and text.strip():
                    script = self.groq.generate_news_script(text)

        elif media_type == 'audio':
            print("🎙️ Audio received — transcribing...")
            transcript = self.groq.transcribe_audio(media_info['input_path'])
            if transcript:
                combined = self._combine_text_and_transcript(text, transcript)
                print("📝 Generating script from text + audio transcript...")
                script = self.groq.generate_news_script(combined)
            else:
                print("⚠️ Transcription failed — falling back to text only")
                if text and text.strip():
                    script = self.groq.generate_news_script(text)

        elif media_type == 'image':
            if extra_audio_path and os.path.exists(extra_audio_path):
                print("🖼️🎙️ Image + Audio received — transcribing audio...")
                transcript = self.groq.transcribe_audio(extra_audio_path)
                if transcript:
                    combined = self._combine_text_and_transcript(text, transcript)
                    print("📝 Generating script from audio transcript...")
                    script = self.groq.generate_news_script(combined)
                else:
                    print("⚠️ Audio transcription failed — falling back to text only")
                    if text and text.strip():
                        script = self.groq.generate_news_script(text)
                    else:
                        result['error'] = "Image+Audio received but transcription failed and no text provided"
                        return result
            elif text and text.strip():
                print("🖼️ Image saved. Generating script from TEXT only...")
                script = self.groq.generate_news_script(text)
            else:
                result['error'] = "Image received but no text or audio provided — skipping"
                print("❌ Image with no text or audio — skipping")
                return result

        elif text and text.strip():
            print("📝 Generating script from text only...")
            script = self.groq.generate_news_script(text)

        else:
            result['error'] = "No valid content to process"
            print("❌ No valid content")
            return result

        if not script:
            result['error'] = "Script generation failed"
            print("❌ Script generation failed")
            return result

        print("🔄 Processing Telugu text...")
        script = self.telugu.convert_numbers_in_text(script)
        script = self.telugu.clean_script(script)

        print("📰 Generating headline...")
        headline = self.groq.generate_headline(script)
        if not headline:
            print("⚠️ Headline generation failed — using default")
            headline = "వార్త"

        audio_temp_path  = None
        audio_generated  = False

        if media_info:
            print("🎤 Generating script audio (Sarvam TTS)...")
            audio_temp_path = os.path.join(
                tempfile.gettempdir(),
                f"temp_audio_{media_info['counter']}_{datetime.now().timestamp()}.mp3"
            )
            if self.tts.generate_audio(script, audio_temp_path):
                audio_generated = True
                print("✅ Script audio generated")
            else:
                print("❌ Script audio generation failed")

        headline_audio_temp_path = None
        if media_info and headline:
            print("🎤 Generating headline audio (Sarvam TTS)...")
            headline_audio_temp_path = os.path.join(
                tempfile.gettempdir(),
                f"temp_headline_{media_info['counter']}_{datetime.now().timestamp()}.mp3"
            )
            if not self.tts.generate_audio(headline, headline_audio_temp_path):
                print("❌ Headline audio failed")
                headline_audio_temp_path = None

        if media_info:
            print("💾 Saving outputs...")
            output_files = self.file_manager.save_outputs(
                script=script,
                headline=headline,
                media_counter=media_info['counter'],
                media_type=media_info['type'],
                audio_data_or_path=audio_temp_path if audio_generated else None,
                headline_audio_data_or_path=headline_audio_temp_path
            )
            result['files'] = output_files
            if audio_generated and output_files.get('audio_path'):
                result['audio_path'] = output_files['audio_path']
                print(f"✅ Script audio saved:   {output_files.get('audio_filename')}")
            if output_files.get('headline_audio_path'):
                print(f"✅ Headline audio saved: {output_files.get('headline_audio_filename')}")

            priority = self._detect_priority(text)
            append_news_item({
                'counter':           media_info['counter'],
                'media_type':        media_info['type'],
                'priority':          priority,
                'timestamp':         datetime.now().isoformat(),
                'headline':          headline,
                'script_filename':   output_files.get('script_filename', ''),
                'headline_filename': output_files.get('headline_filename', ''),
                'headline_audio':    output_files.get('headline_audio_filename', ''),
                'script_audio':      output_files.get('audio_filename', ''),
                'script_duration':   output_files.get('script_duration', 0.0),
                'headline_duration': output_files.get('headline_duration', 0.0),
                'total_duration':    output_files.get('total_duration', 0.0),
            })
            print(f"📋 Metadata saved [{priority.upper()}]")

            # ── Send to LocalAI TV Incidents API ────────────────────────────
            self._send_to_incidents_api(
                title=headline,
                description=script,
                media_info=media_info,
                output_files=output_files,
                text=text,
            )

        for tmp in [audio_temp_path, headline_audio_temp_path, extracted_audio_path, extra_audio_path]:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        print("🧹 Temp files cleaned up")

        result.update({'success': True, 'script': script, 'headline': headline})
        print("✅ Processing complete!")
        print("=" * 60)
        return result


    def _send_to_incidents_api(self, title: str, description: str,
                               media_info: Optional[dict], output_files: dict,
                               text: Optional[str] = None):
        """
        POST processed news to LocalAI TV Incidents API.
        category_id=1 (politics), location_id=1 (Hyderabad) — confirmed valid from GET /incidents.
        Non-blocking — errors never crash the pipeline.
        """
        import requests as _requests
        from config import LOCALAITV_API_URL, LOCALAITV_API_TOKEN, LOCALAITV_LOCATION_ID, LOCALAITV_CATEGORY_ID

        if not LOCALAITV_API_URL:
            return

        headers = {"Content-Type": "application/json"}
        if LOCALAITV_API_TOKEN:
            headers["Authorization"] = f"Bearer {LOCALAITV_API_TOKEN}"

        try:
            audio_path       = output_files.get('audio_path') or None
            cover_image_path = None
            video_path       = None

            if media_info and media_info.get('type') == 'image':
                cover_image_path = media_info.get('input_path')
            elif media_info and media_info.get('type') == 'video':
                video_path = media_info.get('input_path')

            # API expects form-encoded data (not JSON)
            payload = {
                "title":            (title or "వార్త")[:255],
                "description":      description or "",
                "category_id":      LOCALAITV_CATEGORY_ID,
                "location_id":      LOCALAITV_LOCATION_ID,
            }
            # Only add optional fields if they have values (None causes validation errors)
            if audio_path:
                payload["audio_path"] = audio_path
            if cover_image_path:
                payload["cover_image_path"] = cover_image_path
            if video_path:
                payload["video_path"] = video_path

            # Remove Content-Type so requests sets it correctly for form data
            form_headers = {k: v for k, v in headers.items() if k != "Content-Type"}

            print(f"📡 Sending to Incidents API: {LOCALAITV_API_URL}")
            print(f"   category_id={LOCALAITV_CATEGORY_ID}  location_id={LOCALAITV_LOCATION_ID}")

            response = _requests.post(LOCALAITV_API_URL, data=payload, headers=form_headers, timeout=15)

            if response.status_code in (200, 201):
                data        = response.json()
                incident_id = data.get("data", {}).get("incident_id", "?")
                print(f"✅ Incident created → ID: {incident_id}")
            else:
                print(f"⚠️ Incidents API returned {response.status_code}: {response.text[:300]}")

        except Exception as e:
            print(f"⚠️ Incidents API error (non-fatal): {e}")


    @staticmethod
    def _detect_priority(text: Optional[str]) -> str:
        if not text:
            return 'normal'
        text_lower = text.lower()
        if '#breaking' in text_lower:
            return 'breaking'
        if '#urgent' in text_lower:
            return 'urgent'
        return 'normal'

    @staticmethod
    def _combine_text_and_transcript(text: Optional[str], transcript: str) -> str:
        if text and text.strip():
            return (
                f"[Reporter Context]: {text.strip()}\n\n"
                f"[Audio Transcript]: {transcript.strip()}"
            )
        return transcript.strip()

    def display_results(self, result: dict):
        print("\n" + "=" * 60)
        print("📰 GENERATED CONTENT")
        print("=" * 60)
        if result.get('headline'):
            print(f"\n🏷️  HEADLINE:\n{result['headline']}\n")
        if result.get('script'):
            print(f"📄 SCRIPT:\n{result['script']}\n")
        if result.get('files'):
            files = result['files']
            print("📁 OUTPUT FILES:")
            if files.get('headline_filename'):
                print(f"   • {files['headline_filename']}")
            if files.get('script_filename'):
                print(f"   • {files['script_filename']}")
        if result.get('media_info'):
            print(f"\n🎬 MEDIA: {result['media_info']['filename']}")
        print("=" * 60 + "\n")


def main():
    bot = NewsBot()
    print("\n🚀 Test: text-only message")
    result = bot.process_message(
        text="Breaking: Indian cricket team won by 50 runs. Rohit Sharma scored 125 in 90 balls."
    )
    if result['success']:
        bot.display_results(result)


if __name__ == "__main__":
    main()