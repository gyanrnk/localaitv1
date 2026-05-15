

from asyncio.log import logger
from datetime import datetime
import json
from typing import Optional
import os
import shutil
import tempfile
import subprocess
import concurrent.futures
 
from PIL.Image import item
 
from message_queue import MessageQueue
from gupshup_handler import GupshupHandler
from file_manager import FileManager
from media_handler import MediaHandler
from telugu_processor import TeluguProcessor
from tts_handler import detect_channel, get_tts_for_channel
from bulletin_builder import append_news_item
import report_state_manager as _rsm
from config import OUTPUT_AUDIO_DIR, REPORTER_PHOTO_DIR, ADDRESS_GIF_PATH, ensure_assets
ensure_assets()  # download missing static assets from S3 on startup
from openai_handler import OpenAIHandler, GeminiHandler, get_llm_handler
from clip_analyzer import get_structure_decision, should_use_clip_first
 
 
def _smart_split(script: str):
    """
    Intelligently split a script into (intro, analysis) at a sentence boundary.
 
    Strategy:
    - Find all sentence-ending positions (. ! ? ।)
    - Pick the sentence boundary closest to the 45% mark of the script
      (slightly front-weighted so intro sets context, analysis wraps up)
    - Both parts guaranteed to be complete sentences
    """
    import re
    text = script.strip()
    if not text:
        return text, ""
 
    # Find all sentence-end positions
    sentence_ends = [m.end() for m in re.finditer(r'[.!?।]\s+', text)]
 
    if not sentence_ends:
        # No sentence boundaries found — hard split at word level midpoint
        words = text.split()
        mid   = len(words) // 2
        return ' '.join(words[:mid]), ' '.join(words[mid:])
 
    target_pos = int(len(text) * 0.45)   # slightly front-weighted
    best_end   = min(sentence_ends, key=lambda p: abs(p - target_pos))
 
    intro    = text[:best_end].strip()
    analysis = text[best_end:].strip()
 
    # Safety: if either part is empty, return whole script as intro
    if not intro or not analysis:
        return text, ""
 
    return intro, analysis
 
 
class NewsBot:
    """Main News Bot orchestrator"""
 
    def __init__(self):
        self.gupshup       = GupshupHandler()
        self.file_manager  = FileManager()
        self.media_handler = MediaHandler()
        self.groq          = GeminiHandler()
        self.telugu        = TeluguProcessor()
        self.message_queue = MessageQueue(text_wait_timeout=120)
        # NOTE: No shared self.tts — each item creates its own TTSHandler via
        # TTSHandler.for_item() so the male/female alternation is correct.
        self._recover_stuck_items()
 
    def _recover_stuck_items(self):
        """Startup pe 'processing' stuck items ko 'failed' mark karo."""
        # Old JSON version (commented out — STATE_FILE removed after DB migration):
        # from report_state_manager import STATE_FILE, mark_failed
        # if not os.path.exists(STATE_FILE): return
        # with open(STATE_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        # stuck = [k for k, v in data.items() if v.get('status') == 'processing']
        try:
            from report_state_manager import mark_failed
            import db as _db_recover
            stuck_rows = _db_recover.fetchall(
                "SELECT report_id FROM processed_reports WHERE status = 'processing'"
            )
            stuck = [r['report_id'] for r in stuck_rows]
            if stuck:
                print(f"⚠️ [Startup] {len(stuck)} stuck items — marking failed for reprocess")
                for rid in stuck:
                    mark_failed(rid, reason="Stuck on previous run — auto-recovered")
                print(f"✅ [Startup] {len(stuck)} items recovered")
        except Exception as e:
            print(f"⚠️ [Startup] Recovery failed: {e}")
 
    def regenerate_item(self, item: dict) -> bool:
        from config import OUTPUT_AUDIO_DIR, OUTPUT_SCRIPT_DIR, OUTPUT_HEADLINE_DIR
        import shutil
 
        counter    = item.get('counter')
        media_type = item.get('media_type', 'x')
        type_prefix_map = {'image': 'i', 'video': 'v', 'audio': 'a'}
        type_prefix = type_prefix_map.get(media_type, 'x')
 
        script_audio_name    = item.get('script_audio', '')
        headline_audio_name  = item.get('headline_audio', '')
        intro_name           = item.get('intro_audio_filename', '')
        analysis_name        = item.get('analysis_audio_filename', '')
        script_filename      = item.get('script_filename', '')
 
        sa_path = os.path.join(OUTPUT_AUDIO_DIR,    script_audio_name)
        ha_path = os.path.join(OUTPUT_HEADLINE_DIR,  headline_audio_name)
        sc_path = os.path.join(OUTPUT_SCRIPT_DIR,    script_filename)
        intro_path    = os.path.join(OUTPUT_AUDIO_DIR, intro_name)    if intro_name    else None
        analysis_path = os.path.join(OUTPUT_AUDIO_DIR, analysis_name) if analysis_name else None
 
        # ── Step 1: Script text ──────────────────────────────────────────────────
        import s3_storage as _s3_regen
        script = None
        if not os.path.exists(sc_path):
            # Try S3 before regenerating
            _s3_regen.ensure_local(sc_path, _s3_regen.key_for_script(script_filename))

        if os.path.exists(sc_path):
            with open(sc_path, 'r', encoding='utf-8') as f:
                script = f.read().strip()
            print(f"  [REGEN] Script file found for item {counter}")
        elif item.get('original_text'):
            print(f"  [REGEN] Regenerating script for item {counter}")
            script = get_llm_handler(item.get('location_name', '')).generate_news_script(item['original_text'])
            if script:
                script = self.telugu.convert_numbers_in_text(script)
                script = self.telugu.clean_script(script)
                os.makedirs(OUTPUT_SCRIPT_DIR, exist_ok=True)
                with open(sc_path, 'w', encoding='utf-8') as f:
                    f.write(script)
                # Upload regenerated script to S3
                _s3_regen.upload_file_async(sc_path, _s3_regen.key_for_script(script_filename))
        
        if not script:
            print(f"  [REGEN] ❌ No script — cannot regenerate item {counter}")
            return False
 
        # ── Step 2: Headline ─────────────────────────────────────────────────────
        headline = item.get('headline') or get_llm_handler(item.get('location_name', '')).generate_headline(script)
 
        # ── Step 3: TTS — missing audio files regenerate karo ────────────────────
        import tempfile, concurrent.futures
 
        # Sync voice counter to this item's index so same voice is reused
        # from bulletin_builder import load_metadata as _load_meta_regen
        # existing_items = _load_meta_regen()
        # item_index = next(
        #     (i for i, x in enumerate(existing_items) if x.get('counter') == counter),
        #     0
        # )
        # set_voice_counter(item_index)
        import db as _db_regen
        _idx_row = _db_regen.fetchall(
            "SELECT COUNT(*) AS n FROM news_items WHERE counter <= %s", (counter,)
        )
        item_index = max(0, int(_idx_row[0]['n']) - 1) if _idx_row else 0
        _regen_tts = get_tts_for_channel(detect_channel(item.get('location_name', '')), item_index)
        print(f"🎙️  [REGEN] Item {counter} voice: {_regen_tts.speaker.upper()} (index={item_index})")
 
        def _gen_if_missing(text, dest_path, label):
            if dest_path and not os.path.exists(dest_path):
                print(f"  [REGEN] Generating {label}...")
                tmp = dest_path + '_tmp.mp3'
                ok  = _regen_tts.generate_audio(text, tmp)
                if ok and os.path.exists(tmp):
                    shutil.move(tmp, dest_path)
                    return True
                return False
            return True  # already exists
 
        intro_script    = item.get('intro_script', '')
        analysis_script = item.get('analysis_script', '')
 
        # Agar intro/analysis text nahi hai toh smart split karo
        if not intro_script or not analysis_script:
            intro_script, analysis_script = _smart_split(script)
 
        tasks = [
            (script,          sa_path,       'script audio'),
            (headline,        ha_path,       'headline audio'),
            (intro_script,    intro_path,    'intro audio'),
            (analysis_script, analysis_path, 'analysis audio'),
        ]
 
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_gen_if_missing, text, path, label)
                    for text, path, label in tasks if path]
            results = [f.result() for f in futures]
 
        # ── Step 3b: Upload newly generated audio files to S3 ────────────────────
        for _audio_path, _audio_name in [
            (sa_path,       script_audio_name),
            (ha_path,       headline_audio_name),
            (intro_path,    intro_name),
            (analysis_path, analysis_name),
        ]:
            if _audio_path and os.path.exists(_audio_path):
                _s3_regen.upload_file_async(_audio_path, _s3_regen.key_for_audio(_audio_name))

        # ── Step 4: Duration recalculate + status update ──────────────────────────
        # from bulletin_builder import load_metadata, save_metadata, _metadata_lock
        import subprocess

        def _dur(p):
            try:
                r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                    '-of', 'default=noprint_wrappers=1:nokey=1', p],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return float(r.stdout.decode().strip())
            except:
                return 0.0

        # with _metadata_lock:
        #     all_items = load_metadata()
        #     for m in all_items:
        #         if m.get('counter') == counter and m.get('media_type') == media_type:
        #             if os.path.exists(sa_path):
        #                 m['script_duration']   = _dur(sa_path)
        #             if os.path.exists(ha_path):
        #                 m['headline_duration'] = _dur(ha_path)
        #             m['status'] = 'complete'
        #             print(f"  [REGEN] ✅ Item {counter} regenerated successfully")
        #             break
        #     save_metadata(all_items)
        import db as _db_regen2
        _sd = _dur(sa_path) if os.path.exists(sa_path) else None
        _hd = _dur(ha_path) if os.path.exists(ha_path) else None
        _db_regen2.execute("""
            UPDATE news_items SET
                status            = 'complete',
                script_duration   = COALESCE(%s, script_duration),
                headline_duration = COALESCE(%s, headline_duration)
            WHERE counter = %s AND media_type = %s
        """, (_sd, _hd, counter, media_type))
        print(f"  [REGEN] ✅ Item {counter} regenerated successfully")
        return True
 
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
 
        user_audio_info = matched.get('user_audio') or matched.get('extra_media')
        if user_audio_info:
            audio_url = user_audio_info.get('url', '')
            if audio_url and audio_url.startswith('http'):
                tmp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                tmp_audio.close()
                if self.gupshup.download_media(audio_url, tmp_audio.name):
                    extra_audio_path = tmp_audio.name
                    print(f"✅ User audio downloaded for transcription")
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
        print(f"DEBUG: media_type='{message_data['media_type']}', has_text={bool(message_data['text'])}")
 
        if message_data['media_type']:
            msg_type = 'user_audio' if message_data['media_type'] == 'audio' else message_data['media_type']
            print(f"DEBUG: Converting '{message_data['media_type']}' → '{msg_type}'")
            matched = self.message_queue.add_message(
                sender=sender,
                message_type=msg_type,
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
 
 
    def process_gupshup_webhook_queue_only(self, webhook_data: dict) -> dict:
        message_data = self.gupshup.parse_webhook_message(webhook_data)
        sender       = message_data['sender']
        message_id   = message_data['message_id']
        matched      = None
 
        if message_data['media_type']:
            msg_type = 'user_audio' if message_data['media_type'] == 'audio' else message_data['media_type']
            matched = self.message_queue.add_message(
                sender=sender,
                message_type=msg_type,
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
                return {'duplicate': True, 'sender': sender}
            return {'matched': matched, 'sender': sender}
 
        return {'waiting': True, 'sender': sender}
 
    def process_multi_media_report(self, text: str = None,
                                   video_paths: list = None,
                                   image_paths: list = None,
                                   audio_paths: list = None,
                                   sender: str = None,
                                   sender_name=None,
                                   report_id: str = None,
                                   sender_photo='',
                                   location_address: str = '',
                                   location_name: str = '',
                                   location_id: int = None,
                                   user_id: str = '',
                                   category_id: int = 1,
                                   created_at: str = '') -> dict:
        """
        Process a multi-media report (from web app) with multiple videos, images, audios.
 
        Final news item structure in bulletin:
          [TTS Intro + Image slideshow (first half)]
          → [Best video clip - real audio]
          → [TTS Analysis + Image slideshow (second half)]
 
        For cross-video best clip selection (Option B):
          All videos → audio extract → segments merged with time offset →
          clip_analyzer runs once → best clip identified across all videos.
        """
        import shutil as _shutil
 
        result = {
            'success': False, 'script': None, 'headline': None,
            'media_info': None, 'files': {}, 'audio_path': None, 'error': None
        }
 
        print("=" * 60)
        print("📱 PROCESSING MULTI-MEDIA REPORT")
        print(f"   Videos: {len(video_paths or [])} | Images: {len(image_paths or [])} | Audios: {len(audio_paths or [])}")
        print("=" * 60)
 
        video_paths = video_paths or []
        image_paths = image_paths or []
        audio_paths = audio_paths or []
 
        # Derive media_type from what was submitted
        if video_paths:
            media_type = 'video'
        elif image_paths:
            media_type = 'image'
        else:
            media_type = 'audio'
 
        BASE = "https://localaitv.com"
        def full_url(p):
            if p and not p.startswith('http'):
                return f"{BASE}/{p.lstrip('/')}"
            return p
 
        # ── Download all media files ──────────────────────────────────────────
        local_videos = []
        local_images = []
        local_audios = []
 
        for url in video_paths:
            url = full_url(url)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
            tmp.close()
            if self.gupshup.download_media(url, tmp.name):
                local_videos.append(tmp.name)
                print(f"✅ Video downloaded: {tmp.name}")
            else:
                os.unlink(tmp.name)
                print(f"⚠️ Failed to download video: {url}")
 
        for url in image_paths:
            url = full_url(url)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            tmp.close()
            if self.gupshup.download_media(url, tmp.name):
                local_images.append(tmp.name)
                print(f"✅ Image downloaded: {tmp.name}")
            else:
                os.unlink(tmp.name)
                print(f"⚠️ Failed to download image: {url}")
 
        for url in audio_paths:
            url = full_url(url)
            suffix = '.webm' if '.webm' in url else '.mp3'
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.close()
            if self.gupshup.download_media(url, tmp.name):
                local_audios.append(tmp.name)
                print(f"✅ Audio downloaded: {tmp.name}")
            else:
                os.unlink(tmp.name)
                print(f"⚠️ Failed to download audio: {url}")
 
        # ── Determine primary media type for file_manager ────────────────────
        # Priority: video > image > audio
        primary_media_path = local_videos[0] if local_videos else (local_images[0] if local_images else None)
        primary_media_type = 'video' if local_videos else ('image' if local_images else 'audio')
 
        media_info = None
        if primary_media_path:
            media_info = self.file_manager.save_input_media(primary_media_path)
            if media_info:
                result['media_info'] = media_info
                # Override type to reflect multi-media
                media_info['multi_videos'] = []
                media_info['multi_images'] = []
 
                # Save additional videos/images to file_manager
                for vp in local_videos[1:]:
                    vi = self.file_manager.save_input_media(vp)
                    if vi:
                        media_info['multi_videos'].append(vi['input_path'])
 
                # Save all images
                # Save additional images only (primary already saved above)
                # saved_image_paths = []
                # if primary_media_type == 'image' and media_info:
                #     saved_image_paths.append(media_info['input_path'])  # already saved
                # for ip in local_images[1:] if primary_media_type == 'image' else local_images:
                #     ii = self.file_manager.save_input_media(ip)
                #     if ii:
                #         saved_image_paths.append(ii['input_path'])
                # media_info['multi_images'] = saved_image_paths
                saved_image_paths = []
 
                if primary_media_type == 'image' and media_info:
                    # First image already saved as primary — just reference it
                    saved_image_paths.append(media_info['input_path'])
                    # Save remaining images
                    for ip in local_images[1:]:
                        ii = self.file_manager.save_input_media(ip)
                        if ii:
                            saved_image_paths.append(ii['input_path'])
                elif local_images:
                    # Primary is video — save ALL images separately (none saved yet)
                    for ip in local_images:
                        ii = self.file_manager.save_input_media(ip)
                        if ii:
                            saved_image_paths.append(ii['input_path'])
 
                media_info['multi_images'] = saved_image_paths
                # Primary video saved path
                if local_videos:
                    media_info['multi_videos'].insert(0, media_info['input_path'])
                    media_info['type'] = 'video'
 
        # ── Stage 1 checkpoint: downloads done ───────────────────────────────
        if report_id:
            _rsm.update_stage(report_id, 'transcribe', {
                'local_videos': local_videos,
                'local_images': local_images,
                'local_audios': local_audios,
            })
 
        # ── Build combined transcript from all videos + audios ────────────────
        all_segments = []       # merged with time offsets
        all_transcripts = []
        time_offset = 0.0
        best_clip_video_path = None  # which video the best clip belongs to
        best_clip_start = None
        best_clip_end = None
        structure_analysis = None
        intro_script = ''
        analysis_script = ''
 
        # Videos: extract audio → transcribe → collect segments with offset
        video_segment_map = []  # list of (video_path, offset, segments[])
        for vpath in local_videos:
            print(f"🎬 Extracting audio from video: {vpath}")
            extracted = self._extract_audio_from_video(vpath)
            if not extracted:
                print(f"⚠️ Audio extraction failed for {vpath}")
                video_segment_map.append((vpath, time_offset, []))
                continue
 
            tr = get_llm_handler(location_name).transcribe_audio(extracted)
            transcript_text = tr.get('text', '')
            segments = tr.get('segments', [])
            os.unlink(extracted)
 
            if transcript_text:
                all_transcripts.append(transcript_text)
 
            # Offset segments
            offset_segs = []
            for seg in segments:
                offset_segs.append({
                    'start': seg['start'] + time_offset,
                    'end':   seg['end']   + time_offset,
                    'text':  seg['text'],
                    '_video_path': vpath,   # track source video
                    '_local_start': seg['start'],
                    '_local_end':   seg['end'],
                })
 
            video_segment_map.append((vpath, time_offset, offset_segs))
            all_segments.extend(offset_segs)
 
            # Advance offset by video duration
            import subprocess as _sp
            dur_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                       '-of', 'default=noprint_wrappers=1:nokey=1', vpath]
            dur_r = _sp.run(dur_cmd, stdout=_sp.PIPE, stderr=_sp.PIPE)
            try:
                time_offset += float(dur_r.stdout.decode().strip())
            except Exception:
                time_offset += 30.0
 
        # Extra audios (reporter narration) → transcribe
        # [FIX] Video transcripts sirf clip selection ke liye — script mein nahi
        # Reporter ka recorded audio → script ke liye alag rakhो
        audio_transcripts = []   # sirf recorded audio (script ke liye)
        for apath in local_audios:
            print(f"🎙️ Transcribing audio: {apath}")
            tr = get_llm_handler(location_name).transcribe_audio(apath)
            t = tr.get('text', '')
            if t:
                audio_transcripts.append(t)
                all_transcripts.append(t)  # clip selection ke liye bhi
 
        # ── Build combined text for script generation ─────────────────────────
        # Script sirf: user text + reporter recorded audio
        # Video transcript script mein NAHI jaata (gana/irrelevant audio se bachne ke liye)
        combined_parts = []
        if text and text.strip():
            combined_parts.append(text.strip())
        if audio_transcripts:
            combined_parts.append(' '.join(audio_transcripts))
        combined_text = '\n\n'.join(combined_parts) if combined_parts else ''
 
        # ── Stage 2 checkpoint: transcription done ────────────────────────────
        if report_id and combined_text.strip():
            _rsm.update_stage(report_id, 'script', {
                'combined_text':    combined_text,
                'all_transcripts':  all_transcripts,
            })
 
        if not combined_text.strip():
            print("⚠️ No text/audio content — skipping item silently")
            result['success'] = True   # silent skip, not an error
            return result
 
        # ── Target words ──────────────────────────────────────────────────────
        from config import WORDS_PER_SECOND_TELUGU
        if media_type == 'video':
            # 59s total − 20s max clip = 39s for TTS narration
            target_words = round(39 * WORDS_PER_SECOND_TELUGU)   # ~86 words
        else:
            _per_item_sec = (300 - 20) / 5
            target_words  = max(30, int(_per_item_sec * WORDS_PER_SECOND_TELUGU))
        # ── Best clip selection (Option B: cross-video) ───────────────────────
        if local_videos:
            print("🎯 Running cross-video clip selection...")
            try:
                from editorial_planner import EditorialPlanner
                planner = EditorialPlanner(get_llm_handler(location_name))
                plan = planner.build_story_plan(all_segments, user_text=combined_text)
 
                _intro    = plan.get('tts_intro', '')
                _analysis = plan.get('tts_analysis', '')
                _clip     = plan.get('clip')
 
                if _intro and _clip:
                    # Find which video this clip belongs to
                    clip_global_start = _clip['start']
                    clip_global_end   = _clip['end']
 
                    # Reverse map: find the video whose offset range contains this clip
                    for vpath, v_offset, v_segs in video_segment_map:
                        if v_segs:
                            v_dur_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                         '-of', 'default=noprint_wrappers=1:nokey=1', vpath]
                            import subprocess as _sp2
                            v_dur_r = _sp2.run(v_dur_cmd, stdout=_sp2.PIPE, stderr=_sp2.PIPE)
                            try:
                                v_dur = float(v_dur_r.stdout.decode().strip())
                            except Exception:
                                v_dur = 60.0
                            if v_offset <= clip_global_start < v_offset + v_dur:
                                best_clip_video_path = vpath
                                best_clip_start = clip_global_start - v_offset
                                best_clip_end   = clip_global_end   - v_offset
                                break
 
                    if best_clip_video_path is None and local_videos:
                        # Fallback: use first video
                        best_clip_video_path = local_videos[0]
                        best_clip_start = clip_global_start
                        best_clip_end   = clip_global_end
 
                    intro_script    = _intro
                    analysis_script = _analysis
                    script          = (intro_script + '\n\n' + analysis_script).strip()
                    structure_analysis = {
                        'structure':           plan['structure'],
                        'score':               _clip.get('score', 0),
                        'structure_reasoning': plan['structure'],
                        'clip_info': {
                            'start': best_clip_start,
                            'end':   best_clip_end,
                        },
                        'clip_video_path': best_clip_video_path,
                    }
                    print(f"✅ Cross-video clip: {best_clip_video_path} [{best_clip_start:.1f}s→{best_clip_end:.1f}s]")
                else:
                    print("⚠️ Editorial plan no clip — using clip_analyzer fallback")
                    from clip_analyzer import get_structure_decision
                    fallback = get_structure_decision(' '.join(all_transcripts), segments=all_segments)
                    fallback_clip = fallback.get('clip_info')
 
                    if fallback_clip and (fallback_clip['end'] - fallback_clip['start']) >= 5.0:
                        clip_gs = fallback_clip['start']
                        clip_ge = fallback_clip['end']
                        for vpath, v_offset, v_segs in video_segment_map:
                            if v_segs:
                                import subprocess as _sp3
                                v_dur_r = _sp3.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                                    '-of', 'default=noprint_wrappers=1:nokey=1', vpath],
                                                   stdout=_sp3.PIPE, stderr=_sp3.PIPE)
                                try:
                                    v_dur = float(v_dur_r.stdout.decode().strip())
                                except Exception:
                                    v_dur = 60.0
                                if v_offset <= clip_gs < v_offset + v_dur:
                                    best_clip_video_path = vpath
                                    best_clip_start = clip_gs - v_offset
                                    best_clip_end   = clip_ge - v_offset
                                    break
                        if best_clip_video_path is None:
                            best_clip_video_path = local_videos[0]
                            best_clip_start = clip_gs
                            best_clip_end   = clip_ge
 
                        full_script = get_llm_handler(location_name).generate_news_script(combined_text, target_words=target_words)
                        intro_script, analysis_script = _smart_split(full_script)
                        script          = full_script
                        structure_analysis = {
                            'structure':     'intro_clip_analysis',
                            'score':         fallback.get('score', 0),
                            'clip_info':     {'start': best_clip_start, 'end': best_clip_end},
                            'clip_video_path': best_clip_video_path,
                        }
                    else:
                        print("⚠️ No valid clip found — plain script")
                        script = get_llm_handler(location_name).generate_news_script(combined_text, target_words=target_words)
                        structure_analysis = None
 
            except Exception as e:
                print(f"⚠️ Editorial planner error: {e} — falling back")
                script = get_llm_handler(location_name).generate_news_script(combined_text, target_words=target_words)
                structure_analysis = None
        else:
            # No videos — image/audio only
            print("📝 No videos — generating script from text/transcript")
            script = get_llm_handler(location_name).generate_news_script(combined_text, target_words=target_words)
            structure_analysis = None
 
        if not script:
            result['error'] = "Script generation failed"
            return result
 
        # ── Telugu processing ─────────────────────────────────────────────────
        script = self.telugu.convert_numbers_in_text(script)
        script = self.telugu.clean_script(script)
        if intro_script:
            intro_script    = self.telugu.convert_numbers_in_text(intro_script)
            intro_script    = self.telugu.clean_script(intro_script)
            intro_script    = self.telugu.remove_media_references(intro_script)   # ← add
        if analysis_script:
            analysis_script = self.telugu.convert_numbers_in_text(analysis_script)
            analysis_script = self.telugu.clean_script(analysis_script)
            analysis_script = self.telugu.remove_media_references(analysis_script)  # ← add
 
        # ── Headline ──────────────────────────────────────────────────────────
        headline = get_llm_handler(location_name).generate_headline(script) or "వార్త"
 
        # ── Stage 3 checkpoint: script + headline done ────────────────────────
        if report_id:
            _rsm.update_stage(report_id, 'tts', {
                'script':           script,
                'headline':         headline,
                'intro_script':     intro_script,
                'analysis_script':  analysis_script,
                'structure_analysis': structure_analysis,
            })
 
        # ── TTS Generation ────────────────────────────────────────────────────
        if not media_info:
            # No media at all — fallback to text-only processing
            result.update({'success': True, 'script': script, 'headline': headline})
            return result
 
        counter = media_info['counter']
        ts      = datetime.now().timestamp()
 
        audio_temp_path          = os.path.join(tempfile.gettempdir(), f"temp_audio_{counter}_{ts}.mp3")
        headline_audio_temp_path = os.path.join(tempfile.gettempdir(), f"temp_headline_{counter}_{ts}.mp3")
        intro_audio_temp_path    = None
        analysis_audio_temp_path = None
 
        has_clip_structure = bool(
            structure_analysis and
            structure_analysis.get('clip_info') and
            intro_script and analysis_script
        )
 
        if has_clip_structure:
            intro_audio_temp_path    = os.path.join(tempfile.gettempdir(), f"temp_intro_{counter}_{ts}.mp3")
            analysis_audio_temp_path = os.path.join(tempfile.gettempdir(), f"temp_analysis_{counter}_{ts}.mp3")
            print("🎤 Generating headline + intro + analysis TTS in parallel...")
        else:
            print("🎤 Generating script + headline TTS in parallel...")
 
        # ── Per-item voice: sync counter → pick alternating voice ─────────────
        # from bulletin_builder import load_metadata as _load_meta
        # set_voice_counter(len(_load_meta()))
        # _item_tts = TTSHandler.for_item()   # same instance for ALL audio of this item
        # print(f"🎙️  Item voice: {_item_tts.speaker.upper()} (headline + script + intro + analysis)")
 
        # from bulletin_builder import load_metadata as _load_meta, _metadata_lock
        # with _metadata_lock:
        #     set_voice_counter(len(_load_meta()))
        import db as _db_vc1
        _vc1_row = _db_vc1.fetchall("SELECT COUNT(*) AS n FROM news_items")
        _vc1_n   = int(_vc1_row[0]["n"]) if _vc1_row else 0
        _item_tts = get_tts_for_channel(detect_channel(location_name), _vc1_n)
        print(f"🎙️  Item voice: {_item_tts.speaker.upper()} (headline + script + intro + analysis)")
 
        def _gen_script():
            return _item_tts.generate_audio(script, audio_temp_path,
                                            allocated_duration=media_info.get('allocated_duration'))
        def _gen_headline():
            return _item_tts.generate_audio(headline, headline_audio_temp_path)
        def _gen_intro():
            return _item_tts.generate_audio(intro_script, intro_audio_temp_path)
        def _gen_analysis():
            return _item_tts.generate_audio(analysis_script, analysis_audio_temp_path)
 
        if has_clip_structure:
            try:
                audio_generated = _gen_script()
                headline_ok     = _gen_headline()
                intro_ok        = _gen_intro()
                analysis_ok     = _gen_analysis()
            except RuntimeError as e:
                if report_id:
                    _rsm.mark_failed(report_id, reason=f"TTS failed: {e}")
                raise
            if not intro_ok:
                intro_audio_temp_path = None
            if not analysis_ok:
                analysis_audio_temp_path = None
        else:
            try:
                audio_generated = _gen_script()
                headline_ok     = _gen_headline()
            except RuntimeError as e:
                if report_id:
                    _rsm.mark_failed(report_id, reason=f"TTS failed: {e}")
                raise
 
        # ── Save outputs ──────────────────────────────────────────────────────
        type_prefix = 'v' if local_videos else ('i' if local_images else 'a')
 
        output_files = self.file_manager.save_outputs(
            script=script,
            headline=headline,
            media_counter=counter,
            media_type=media_info.get('type', 'video'),
            audio_data_or_path=audio_temp_path if audio_generated else None,
            headline_audio_data_or_path=headline_audio_temp_path if headline_ok else None,
        )
        result['files'] = output_files
        if audio_generated and output_files.get('audio_path'):
            result['audio_path'] = output_files['audio_path']
 
        intro_audio_filename    = None
        analysis_audio_filename = None
 
        if intro_audio_temp_path and os.path.exists(intro_audio_temp_path):
            intro_audio_filename = f"oa{type_prefix}{counter}_intro.mp3"
            dest = os.path.join(OUTPUT_AUDIO_DIR, intro_audio_filename)
            try:
                _shutil.copy2(intro_audio_temp_path, dest)
                print(f"✅ Intro audio saved: {intro_audio_filename}")
            except Exception as e:
                print(f"❌ Intro audio save failed: {e}")
                intro_audio_filename = None
 
        if analysis_audio_temp_path and os.path.exists(analysis_audio_temp_path):
            analysis_audio_filename = f"oa{type_prefix}{counter}_analysis.mp3"
            dest = os.path.join(OUTPUT_AUDIO_DIR, analysis_audio_filename)
            try:
                _shutil.copy2(analysis_audio_temp_path, dest)
                print(f"✅ Analysis audio saved: {analysis_audio_filename}")
            except Exception as e:
                print(f"❌ Analysis audio save failed: {e}")
                analysis_audio_filename = None
 
        # ── Save clip video path for video_builder ────────────────────────────
        clip_video_saved_path = None
        if structure_analysis and structure_analysis.get('clip_video_path'):
            src_vpath = structure_analysis['clip_video_path']
            # Find if already saved in file_manager
            for saved_p in (media_info.get('multi_videos') or []):
                # Match by comparing temp download paths
                if src_vpath == local_videos[0] and saved_p == media_info.get('input_path'):
                    clip_video_saved_path = saved_p
                    break
                elif src_vpath in local_videos:
                    idx_v = local_videos.index(src_vpath)
                    all_saved = [media_info.get('input_path')] + (media_info.get('multi_videos') or [])[1:]
                    if idx_v < len(all_saved):
                        clip_video_saved_path = all_saved[idx_v]
                        break
            if not clip_video_saved_path:
                clip_video_saved_path = media_info.get('input_path')
 
        # ── Sender photo: API se alag 'photo' field aaye tabhi use karo ──────
        # local_images = news ki images hain, reporter profile photo NAHI
        # BAAD MEIN:
        saved_sender_photo = ''
        if sender_photo:
            try:
                import requests as _req
                FRONTEND_BASE_URL = "https://localaitv.com"
                photo_url = sender_photo if sender_photo.startswith('http') else f"{FRONTEND_BASE_URL}/{sender_photo.lstrip('/')}"
                ext = os.path.splitext(sender_photo)[-1] or '.jpg'
                photo_filename = f"reporter_{user_id}{ext}"
                photo_dest = os.path.join(REPORTER_PHOTO_DIR, photo_filename)
                if not os.path.exists(photo_dest):
                    r = _req.get(photo_url, timeout=10)
                    r.raise_for_status()
                    with open(photo_dest, 'wb') as f:
                        f.write(r.content)
                    print(f"✅ Reporter photo saved: {photo_dest}")
                else:
                    print(f"✅ Reporter photo already exists: {photo_dest}")
                saved_sender_photo = photo_dest
            except Exception as e:
                print(f"⚠️ Reporter photo download failed: {e}")
        # Future: agar API reporter_photo field bheje toh yahan handle karo
 
        # ── Stage 4 checkpoint: TTS + audio files saved ───────────────────────
        if report_id:
            _rsm.update_stage(report_id, 'save', {
                'output_files':           output_files,
                'intro_audio_filename':   intro_audio_filename,
                'analysis_audio_filename': analysis_audio_filename,
                'clip_video_saved_path':  clip_video_saved_path,
            })
 
        priority = self._detect_priority(text)
 
        # Location directly from API — no resolver needed
        loc_id   = location_id if (location_id and int(location_id) != 0) else 0
        loc_name = location_name or location_address or 'Unknown'
        print(f"📍 [API] location_id={loc_id} | loc_name='{loc_name}'")
 
        append_news_item({
            'counter':                   counter,
            'media_type':                media_info.get('type', 'video'),
            'priority':                  priority,
            'sender_name':               sender_name or '',
            'sender_photo':              saved_sender_photo,
            'sender_gif':                ADDRESS_GIF_PATH if os.path.exists(ADDRESS_GIF_PATH) else '',
            'timestamp':                 datetime.now().isoformat(),
            'headline':                  headline,
            'script_filename':           output_files.get('script_filename', ''),
            'headline_filename':         output_files.get('headline_filename', ''),
            'headline_audio':            output_files.get('headline_audio_filename', ''),
            'script_audio':              output_files.get('audio_filename', ''),
            'script_duration':           output_files.get('script_duration', 0.0),
            'headline_duration':         output_files.get('headline_duration', 0.0),
            'total_duration':            output_files.get('total_duration', 0.0),
            'clip_structure':            structure_analysis.get('structure') if structure_analysis else None,
            'clip_start':                structure_analysis['clip_info']['start'] if structure_analysis and structure_analysis.get('clip_info') else None,
            'clip_end':                  structure_analysis['clip_info']['end']   if structure_analysis and structure_analysis.get('clip_info') else None,
            'clip_video_path':           clip_video_saved_path,
            'multi_image_paths':         media_info.get('multi_images', []),
            'multi_video_paths':         media_info.get('multi_videos', []),
            'intro_audio_filename':      intro_audio_filename,
            'analysis_audio_filename':   analysis_audio_filename,
            'status': 'complete',
            'original_text': combined_text,
            'location_id':   loc_id,
            'location_name': loc_name,
            'location_address': location_address,
            'created_at': created_at if created_at else datetime.now().isoformat(),
            'category_id': category_id,
            'user_id':   user_id or '',
            's3_key_input':        media_info.get('s3_key_input') if media_info else None,
            's3_key_script_audio': output_files.get('s3_key_script_audio'),
            's3_key_headline_audio': output_files.get('s3_key_headline_audio'),
        })
        logger.info(f"📋 [DEBUG] location_id={location_id} | location_address='{location_address}'")
        print(f"📋 Metadata saved [{priority.upper()}]")
 
        # ── Mark report fully complete in state tracker ───────────────────────
        if report_id:
            _rsm.mark_complete(report_id)
 
        from event_logger import log_event
        log_event(
            event      = 'generated',
            counter    = counter,
            media_type = media_info.get('type', 'video'),
            extra      = json.dumps({
                'multi_videos': media_info.get('multi_videos', []),
                'multi_images': media_info.get('multi_images', []),
            }) if (media_info.get('multi_videos') or media_info.get('multi_images')) else None
        )
 
        # ── Cleanup temps ─────────────────────────────────────────────────────
        for tmp in (local_videos + local_images + local_audios +
                    [audio_temp_path, headline_audio_temp_path,
                     intro_audio_temp_path, analysis_audio_temp_path]):
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
        print("🧹 Temp files cleaned up")
 
        result.update({'success': True, 'script': script, 'headline': headline})
        print("✅ Multi-media processing complete!")
        print("=" * 60)
        return result
 
    def process_message(self, text: str = None, media_path: str = None,
        sender: str = None, extra_audio_path: str = None, sender_name: str = None,
        location_address: str = '', location_id: int = None) -> dict:  # ← ADD
        result = {
            'success': False, 'script': None, 'headline': None,
            'media_info': None, 'files': {}, 'audio_path': None, 'error': None
        }
        structure_analysis  = None
        intro_script        = ''
        analysis_script     = ''
 
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
        combined_text        = text.strip() if text and text.strip() else ''  # ← YAHAN
        # ─── Target words calculation ─────────────────────────────────────────
        from config import WORDS_PER_SECOND_TELUGU
        _per_item_sec = (300 - 20) / 5
        _clip_reserve = 20 if media_type == 'video' else 0
        target_words  = max(30, int((_per_item_sec - _clip_reserve) * WORDS_PER_SECOND_TELUGU))
        print(f"[DEBUG] target_words={target_words} | media_type={media_type}")
        # ──────────────────────────────────────────────────────────────────────
 
        # ─── VIDEO ───────────────────────────────────────────────────────────
        if media_type == 'video':
            print("🎬 Video received — extracting audio...")
            extracted_audio_path = self._extract_audio_from_video(media_info['input_path'])
 
            transcript = ''
            segments   = []
            if extracted_audio_path:
                transcript_result = get_llm_handler(location_address).transcribe_audio(extracted_audio_path)
                transcript = transcript_result.get('text', '')
                segments   = transcript_result.get('segments', [])
            else:
                print("⚠️ Audio extraction failed")
 
            if not transcript.strip() and not (text and text.strip()):
                result['error'] = "Video skipped: no text and no human voice detected"
                return result
 
            if segments:
                try:
                    from editorial_planner import EditorialPlanner
                    planner = EditorialPlanner(get_llm_handler(location_address))
                    plan    = planner.build_story_plan(segments, user_text=combined_text)
 
                    _intro    = plan.get('tts_intro', '')
                    _analysis = plan.get('tts_analysis', '')
                    _clip     = plan.get('clip')
 
                    if _intro and _clip:
                        intro_script    = _intro
                        analysis_script = _analysis
                        script          = (intro_script + '\n\n' + analysis_script).strip()
                        structure_analysis = {
                            'structure':           plan['structure'],
                            'score':               _clip.get('score', 0),
                            'structure_reasoning': plan['structure'],
                            'clip_info':           _clip,
                        }
                        print(f"✅ Editorial plan: {plan['structure']} | clip {_clip['start']:.1f}s→{_clip['end']:.1f}s")
 
                    else:
                        print("⚠️ Editorial plan returned no clip — trying clip_analyzer fallback")
                        from clip_analyzer import get_structure_decision
                        fallback_analysis = get_structure_decision(transcript, segments=segments)
                        fallback_clip     = fallback_analysis.get('clip_info')
 
                        if fallback_clip and (fallback_clip['end'] - fallback_clip['start']) >= 5.0:
                            combined        = self._combine_text_and_transcript(text, transcript)
                            full_script     = get_llm_handler(location_address).generate_news_script(combined, target_words=target_words)
                            intro_script, analysis_script = _smart_split(full_script)
                            script          = full_script
                            structure_analysis = {
                                'structure':           'intro_clip_analysis',
                                'score':               fallback_analysis.get('score', 0),
                                'structure_reasoning': 'clip_analyzer fallback',
                                'clip_info':           fallback_clip,
                            }
                            print(f"✅ clip_analyzer fallback: clip {fallback_clip['start']:.1f}s→{fallback_clip['end']:.1f}s")
                        else:
                            # ── FIX 1: time-based clip when transcript exists but clip_analyzer fails ──
                            print("⚠️ clip_analyzer found no clip — using time-based clip")
                            v_dur_r = subprocess.run(
                                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', media_info['input_path']],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE
                            )
                            try:
                                v_dur = float(v_dur_r.stdout.decode().strip())
                            except Exception:
                                v_dur = 30.0
                            clip_s   = min(5.0, v_dur * 0.2)
                            clip_raw = min(clip_s + 20.0, v_dur * 0.8)   # cap at 20s
                            clip_e   = max(clip_s + 8.0, clip_raw)        # enforce min 8s
                            clip_e   = min(clip_e, v_dur)   
                            combined    = self._combine_text_and_transcript(text, transcript)
                            full_script = get_llm_handler(location_address).generate_news_script(combined, target_words=target_words)
                            intro_script, analysis_script = _smart_split(full_script)
                            script = full_script
                            structure_analysis = {
                                'structure':           'intro_clip_analysis',
                                'score':               0,
                                'structure_reasoning': 'time-based fallback',
                                'clip_info':           {'start': clip_s, 'end': clip_e},
                            }
                            print(f"✅ Time-based clip: {clip_s:.1f}s→{clip_e:.1f}s")
 
                except Exception as e:
                    print(f"⚠️ Editorial planner error: {e} — falling back")
                    combined           = self._combine_text_and_transcript(text, transcript)
                    script             = get_llm_handler(location_address).generate_news_script(combined, target_words=target_words)
                    structure_analysis = None
            else:
                # ── FIX 1: No segments at all — time-based clip, no transcript needed ──
                print("⚠️ No transcript segments — using time-based clip")
                v_dur_r = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', media_info['input_path']],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                try:
                    v_dur = float(v_dur_r.stdout.decode().strip())
                except Exception:
                    v_dur = 30.0
                clip_s   = min(5.0, v_dur * 0.2)
                clip_raw = min(clip_s + 20.0, v_dur * 0.8)   # cap at 20s
                clip_e   = max(clip_s + 8.0, clip_raw)        # enforce min 8s
                clip_e   = min(clip_e, v_dur) 
                combined    = self._combine_text_and_transcript(text, transcript)
                full_script = get_llm_handler(location_address).generate_news_script(combined, target_words=target_words)
                intro_script, analysis_script = _smart_split(full_script)
                script = full_script
                structure_analysis = {
                    'structure':           'intro_clip_analysis',
                    'score':               0,
                    'structure_reasoning': 'time-based fallback (no segments)',
                    'clip_info':           {'start': clip_s, 'end': clip_e},
                }
                print(f"✅ Time-based clip (no segments): {clip_s:.1f}s→{clip_e:.1f}s")
 
        # ─── AUDIO ───────────────────────────────────────────────────────────
        elif media_type == 'audio':
            print("🎙️ Audio received — transcribing...")
            transcript_result = get_llm_handler(location_address).transcribe_audio(media_info['input_path'])
            transcript = transcript_result.get('text', '')
            if transcript:
                combined = self._combine_text_and_transcript(text, transcript)
                print("📝 Generating script from text + audio transcript...")
                script = get_llm_handler(location_address).generate_news_script(combined, target_words=target_words)
            else:
                print("⚠️ Transcription failed — falling back to text only")
                if text and text.strip():
                    script = get_llm_handler(location_address).generate_news_script(text, target_words=target_words)
 
        # ─── IMAGE ───────────────────────────────────────────────────────────
        elif media_type == 'image':
            if extra_audio_path and os.path.exists(extra_audio_path):
                print("🖼️🎙️ Image + Audio received — transcribing audio...")
                transcript_result = get_llm_handler(location_address).transcribe_audio(extra_audio_path)
                transcript = transcript_result.get('text', '')
                if transcript:
                    combined = self._combine_text_and_transcript(text, transcript)
                    print("📝 Generating script from audio transcript...")
                    script = get_llm_handler(location_address).generate_news_script(combined, target_words=target_words)
                else:
                    print("⚠️ Audio transcription failed — falling back to text only")
                    if text and text.strip():
                        script = get_llm_handler(location_address).generate_news_script(text, target_words=target_words)
                    else:
                        result['error'] = "Image+Audio received but transcription failed and no text provided"
                        return result
            elif text and text.strip():
                print("🖼️ Image saved. Generating script from TEXT only...")
                script = get_llm_handler(location_address).generate_news_script(text, target_words=target_words)
            else:
                result['error'] = "Image received but no text or audio provided — skipping"
                print("❌ Image with no text or audio — skipping")
                return result
 
        # ─── TEXT ONLY ───────────────────────────────────────────────────────
        elif text and text.strip():
            print("📝 Generating script from text only...")
            script = get_llm_handler(location_address).generate_news_script(text, target_words=target_words)
 
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
 
        if intro_script:
            intro_script    = self.telugu.convert_numbers_in_text(intro_script)
            intro_script    = self.telugu.clean_script(intro_script)
        if analysis_script:
            analysis_script = self.telugu.convert_numbers_in_text(analysis_script)
            analysis_script = self.telugu.clean_script(analysis_script)
 
        print("📰 Generating headline...")
        headline = get_llm_handler(location_address).generate_headline(script)
        if not headline:
            print("⚠️ Headline generation failed — using default")
            headline = "వార్త"
 
        # ─── TTS Generation ──────────────────────────────────────────────────
        audio_temp_path          = None
        headline_audio_temp_path = None
        intro_audio_temp_path    = None
        analysis_audio_temp_path = None
        audio_generated          = False
 
        if media_info:
            counter = media_info['counter']
            ts      = datetime.now().timestamp()
 
            audio_temp_path = os.path.join(
                tempfile.gettempdir(),
                f"temp_audio_{counter}_{ts}.mp3"
            )
            headline_audio_temp_path = os.path.join(
                tempfile.gettempdir(),
                f"temp_headline_{counter}_{ts}.mp3"
            )
 
            # ── FIX 3: analysis_script optional — intro alone is enough ──────────
            has_clip_structure = bool(
                structure_analysis and
                structure_analysis.get('clip_info') and
                intro_script
            )
 
            if has_clip_structure:
                intro_audio_temp_path    = os.path.join(tempfile.gettempdir(), f"temp_intro_{counter}_{ts}.mp3")
                analysis_audio_temp_path = os.path.join(tempfile.gettempdir(), f"temp_analysis_{counter}_{ts}.mp3") if analysis_script else None
                print("🎤 Generating headline + intro + analysis TTS in parallel...")
            else:
                print("🎤 Generating script + headline audio in parallel...")
 
            print(f"[DEBUG] TTS call | counter={counter} | "
                f"allocated_duration={media_info.get('allocated_duration')} | "
                f"script_duration={media_info.get('script_duration')}")
 
            # ── Per-item voice: sync counter → pick alternating voice ─────────
            # from bulletin_builder import load_metadata as _load_meta
            # set_voice_counter(len(_load_meta()))
            # _item_tts = TTSHandler.for_item()   # same instance for ALL audio of this item
            # print(f"🎙️  Item voice: {_item_tts.speaker.upper()} (headline + script + intro + analysis)")
            # from bulletin_builder import load_metadata as _load_meta, _metadata_lock
            # with _metadata_lock:
            #     set_voice_counter(len(_load_meta()))
            import db as _db_vc2
            _vc2_row = _db_vc2.fetchall("SELECT COUNT(*) AS n FROM news_items")
            _vc2_n   = int(_vc2_row[0]["n"]) if _vc2_row else 0
            _item_tts = get_tts_for_channel(detect_channel(location_address), _vc2_n)
            print(f"🎙️  Item voice: {_item_tts.speaker.upper()} (headline + script + intro + analysis)")
 
            def _gen_script():
                return _item_tts.generate_audio(
                    script, audio_temp_path,
                    allocated_duration=media_info.get('allocated_duration')
                )
 
            def _gen_headline():
                return _item_tts.generate_audio(headline, headline_audio_temp_path)
 
            def _gen_intro():
                return _item_tts.generate_audio(intro_script, intro_audio_temp_path)
 
            def _gen_analysis():
                return _item_tts.generate_audio(analysis_script, analysis_audio_temp_path)
 
            if has_clip_structure:
                futures = {
                    'script':   None,
                    'headline': None,
                    'intro':    None,
                    'analysis': None,
                }
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    futures['script']   = executor.submit(_gen_script)
                    futures['headline'] = executor.submit(_gen_headline)
                    futures['intro']    = executor.submit(_gen_intro)
                    if analysis_script and analysis_audio_temp_path:
                        futures['analysis'] = executor.submit(_gen_analysis)
 
                    audio_generated = futures['script'].result()
                    headline_ok     = futures['headline'].result()
                    intro_ok        = futures['intro'].result()
                    analysis_ok     = futures['analysis'].result() if futures['analysis'] else False
 
                if not intro_ok:
                    print("❌ Intro TTS failed — clip structure will use fallback")
                    intro_audio_temp_path = None
                else:
                    print("✅ Intro TTS generated")
 
                if not analysis_ok:
                    print("⚠️ Analysis TTS failed or skipped")
                    analysis_audio_temp_path = None
                else:
                    print("✅ Analysis TTS generated")
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    f_script   = executor.submit(_gen_script)
                    f_headline = executor.submit(_gen_headline)
                    audio_generated = f_script.result()
                    headline_ok     = f_headline.result()
 
            if audio_generated:
                print("✅ Script audio generated")
            else:
                print("❌ Script audio generation failed")
 
            if not headline_ok:
                print("❌ Headline audio failed")
                headline_audio_temp_path = None
            else:
                print("✅ Headline audio generated")
 
        # ─── Save outputs ─────────────────────────────────────────────────────
        intro_audio_filename    = None
        analysis_audio_filename = None
 
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
 
            type_prefix_map = {'image': 'i', 'video': 'v', 'audio': 'a'}
            type_prefix     = type_prefix_map.get(media_info['type'], 'x')
            counter         = media_info['counter']
 
            if intro_audio_temp_path and os.path.exists(intro_audio_temp_path):
                intro_audio_filename = f"oai{type_prefix}{counter}_intro.mp3"
                dest = os.path.join(OUTPUT_AUDIO_DIR, intro_audio_filename)
                try:
                    shutil.copy2(intro_audio_temp_path, dest)
                    print(f"✅ Intro audio saved:    {intro_audio_filename}")
                except Exception as e:
                    print(f"❌ Intro audio save failed: {e}")
                    intro_audio_filename = None
 
            if analysis_audio_temp_path and os.path.exists(analysis_audio_temp_path):
                analysis_audio_filename = f"oai{type_prefix}{counter}_analysis.mp3"
                dest = os.path.join(OUTPUT_AUDIO_DIR, analysis_audio_filename)
                try:
                    shutil.copy2(analysis_audio_temp_path, dest)
                    print(f"✅ Analysis audio saved: {analysis_audio_filename}")
                except Exception as e:
                    print(f"❌ Analysis audio save failed: {e}")
                    analysis_audio_filename = None
 
            priority = self._detect_priority(text)
 
            # ── FIX 2: clip_video_path add kiya — pehle missing tha ─────────────
            append_news_item({
                'counter':                media_info['counter'],
                'media_type':             media_info['type'],
                'priority':               priority,
                'timestamp':              datetime.now().isoformat(),
                'headline':               headline,
                'script_filename':        output_files.get('script_filename', ''),
                'headline_filename':      output_files.get('headline_filename', ''),
                'headline_audio':         output_files.get('headline_audio_filename', ''),
                'script_audio':           output_files.get('audio_filename', ''),
                'script_duration':        output_files.get('script_duration', 0.0),
                'headline_duration':      output_files.get('headline_duration', 0.0),
                'total_duration':         output_files.get('total_duration', 0.0),
                'clip_structure':         structure_analysis.get('structure') if structure_analysis else None,
                'clip_start':             structure_analysis['clip_info']['start'] if structure_analysis and structure_analysis.get('clip_info') else None,
                'clip_end':               structure_analysis['clip_info']['end']   if structure_analysis and structure_analysis.get('clip_info') else None,
                'clip_video_path':        media_info.get('input_path') if structure_analysis else None,
                'multi_image_paths':      [],
                'sender_name':            sender_name or '',
                'sender_photo':           '',
                'intro_audio_filename':   intro_audio_filename,
                'analysis_audio_filename': analysis_audio_filename,
                'status': 'complete',
                'original_text': combined_text,
                's3_key_input':        media_info.get('s3_key_input') if media_info else None,
                's3_key_script_audio': output_files.get('s3_key_script_audio'),
                's3_key_headline_audio': output_files.get('s3_key_headline_audio'),
            })
            print(f"📋 Metadata saved [{priority.upper()}]")
 
        # ─── Cleanup temps ────────────────────────────────────────────────────
        for tmp in [
            audio_temp_path, headline_audio_temp_path,
            extracted_audio_path, extra_audio_path,
            intro_audio_temp_path, analysis_audio_temp_path
        ]:
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
 
    def _convert_path_to_url(self, file_path: str) -> str:
        from config import API_BASE_URL
        if '/outputs/' in file_path:
            relative_path = file_path.split('/outputs/')[1]
        elif '/inputs/' in file_path:
            relative_path = file_path.split('/inputs/')[1]
        else:
            relative_path = os.path.basename(file_path)
        url = f"{API_BASE_URL}/api/media/{relative_path}"
        if os.path.exists(file_path):
            print(f"✅ File exists: {file_path}")
            print(f"   → URL: {url}")
        else:
            print(f"❌ File NOT found: {file_path}")
            print(f"   → URL: {url}")
        return url
 
 
    def _send_to_incidents_api(self, title: str, description: str,
                               media_info: Optional[dict], output_files: dict,
                               text: Optional[str] = None,
                               location_id: int = 0,       # ← ADD
                               category_id: int = 0):
        import requests as _requests
        from config import LOCALAITV_API_URL, LOCALAITV_API_TOKEN
 
        if not LOCALAITV_API_URL:
            return
 
        headers = {"Content-Type": "application/json"}
        if LOCALAITV_API_TOKEN:
            headers["Authorization"] = f"Bearer {LOCALAITV_API_TOKEN}"
 
        try:
            audio_path       = None
            cover_image_path = None
            video_path       = None
 
            print("\n" + "="*60)
            print("🔍 DEBUG: Path → URL Conversion")
            print("="*60)
 
            if output_files.get('audio_path'):
                print(f"\n📁 Audio file:")
                audio_path = self._convert_path_to_url(output_files.get('audio_path'))
            else:
                print(f"⚠️ No audio_path in output_files")
 
            if media_info:
                if media_info.get('type') == 'image':
                    print(f"\n🖼️  Image file:")
                    cover_image_path = self._convert_path_to_url(media_info.get('input_path'))
                elif media_info.get('type') == 'video':
                    print(f"\n🎬 Video file:")
                    video_path = self._convert_path_to_url(media_info.get('input_path'))
            else:
                print(f"⚠️ No media_info")
 
            print("\n" + "="*60)
 
            payload = {
                "title":       (title or "వార్త")[:255],
                "description": description or "",
            }
 
            if category_id:
                payload["category_id"] = category_id
 
            if location_id:
                payload["location_id"] = location_id
            if audio_path:
                payload["audio_path"] = audio_path
            if cover_image_path:
                payload["cover_image_path"] = cover_image_path
            if video_path:
                payload["video_path"] = video_path
 
            form_headers = {k: v for k, v in headers.items() if k != "Content-Type"}
 
            print(f"📡 Sending to Incidents API: {LOCALAITV_API_URL}")
            print(f"   category_id={category_id} location_id= {location_id}")
 
            response = _requests.post(LOCALAITV_API_URL, json=payload, headers=headers, timeout=15)
 
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