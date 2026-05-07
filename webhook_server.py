from datetime import datetime
import shutil
from flask import Flask, json, request, jsonify
import pytz
from event_logger import init_db, save_incident
from main import NewsBot
from bulletin_builder import build_bulletin, load_metadata
from video_builder import build_bulletin_video
from governor.build_queue import queue_bulletin_build  # [BUILD QUEUE HOOK]
try:
    from governor.cpu_governor import governor as _governor
except ImportError:
    class _DummyGovernor:
        def wait_for_slot(self, desc=""): pass
    _governor = _DummyGovernor()
import logging
import threading
from time import sleep, time
import tempfile
import os
from flask import send_from_directory
from werkzeug.utils import secure_filename
import mimetypes
from datetime import datetime, timedelta  # timedelta add karo agar missing hai
from openai_handler import OpenAIHandler  # ya jo bhi instance hai

init_db()


import requests as _req
from config import API_BASE_URL, BULLETIN_API_TOKEN, LOCALAITV_API_URL, BASE_DIR, OUTPUT_AUDIO_DIR, OUTPUT_HEADLINE_DIR, OUTPUT_SCRIPT_DIR  # ya alag variable

REPORTS_API_URL = "https://localaitv.com/api/webhooks/reports"
PROCESSED_IDS_FILE = os.path.join(BASE_DIR, 'processed_report_ids.json')

try:
    from config import BASE_DIR, PORT
except ImportError:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PORT     = 8000

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"📁 BASE_DIR = {BASE_DIR}")

import subprocess
import json
import tempfile

def has_human_voice(video_path: str, min_duration: float = 2.0) -> bool:
    """
    Detect if video contains human voice/speech.
    ffprobe se original video pe audio duration pehle check karo —
    sirf tab ffmpeg extract karo jab duration pass ho.
    """
    audio_temp_path = None
    try:
        # Step 1: ffprobe original video pe — koi temp file nahi, koi ffmpeg nahi
        duration_cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        duration_result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=15)
        duration = float(duration_result.stdout.strip() or 0)

        if duration < min_duration:
            print(f"⚠️ Audio too short: {duration:.2f}s < {min_duration}s")
            return False

        # Step 2: Governor hook — tab hi ffmpeg chalao jab zaroorat ho
        _governor.wait_for_slot('has_human_voice extract')

        audio_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        audio_temp.close()
        audio_temp_path = audio_temp.name

        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vn', '-acodec', 'libmp3lame', '-ab', '128k', '-ar', '16000',
            audio_temp_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            print(f"❌ Audio extraction failed (code={result.returncode}): {result.stderr.decode()[-300:]}")
            return False

        # Step 3: Transcribe using Whisper/Groq
        from openai_handler import OpenAIHandler
        groq = OpenAIHandler()
        transcript_result = groq.transcribe_audio(audio_temp_path)

        transcript = transcript_result.get('text', '')
        if not transcript or len(transcript.strip()) < 10:
            print(f"❌ No speech detected in video")
            return False

        print(f"✅ Human voice detected: {transcript[:50]}...")
        return True

    except Exception as e:
        print(f"❌ Voice detection error: {e}")
        return False
    finally:
        # Temp file hamesha clean hoga — chahe koi bhi path ho
        if audio_temp_path and os.path.exists(audio_temp_path):
            try:
                os.unlink(audio_temp_path)
            except Exception:
                pass

app = Flask(__name__)

# @app.after_request
# def after_request(response):
#     if response.content_type.startswith('application/json'):
#         response.headers['Content-Type'] = 'application/json; charset=utf-8'
#     return response


@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Range, Content-Type'
    response.headers['Access-Control-Expose-Headers'] = 'Content-Range, Accept-Ranges, Content-Length'
    response.headers['Accept-Ranges'] = 'bytes'
    if response.content_type.startswith('application/json'):
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

bot = NewsBot()

def process_expired_queue():
    """
    Background worker — runs every 5 seconds
    
    Processing rules:
    - Video + Text/Audio → ✅ Process
    - Video only → Check for human voice
      - Has human voice → ✅ Process
      - No human voice → ❌ Skip
    - Image + Text/Audio → ✅ Process
    - Image only → ❌ Skip (already handled in message_queue)
    - Text only → ✅ Process (after timeout)
    """
    while True:
        try:
            sleep(5)

            # Process expired media (image/video)
            for item in bot.message_queue.get_expired_media():
                sender     = item['sender']
                media_data = item['media']
                media_type = media_data.get('type', 'image')
                has_content = media_data.get('text') or item.get('user_audio')
                
                logger.info(f"⏰ Processing expired {media_type} for {sender}")
                
                # NEW LOGIC: For video-only (no text/audio), check human voice
                if media_type == 'video' and not has_content:
                    logger.info(f"🔍 Video-only detected, checking for human voice...")
                    
                    # Download video first
                    ext_map   = {'image': '.jpg', 'video': '.mp4', 'audio': '.mp3'}
                    ext       = ext_map.get(media_type, '.bin')
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                    temp_file.close()
                    
                    if not bot.gupshup.download_media(media_data['url'], temp_file.name):
                        logger.error(f"❌ Failed to download video for voice detection")
                        os.unlink(temp_file.name)
                        continue
                    
                    # Check for human voice
                    if not has_human_voice(temp_file.name):
                        logger.info(f"⏭️ SKIPPING: Video has no human voice - {sender}")
                        os.unlink(temp_file.name)
                        continue  # Skip this video
                    
                    logger.info(f"✅ Human voice detected in video, processing...")
                    
                    # Process video with detected voice
                    sender_name = item.get('sender_name', '')
                    print(f"  [WORKER] sender={sender} | sender_name='{sender_name}'")
                    result = bot.process_message(
                        text=None,
                        media_path=temp_file.name,
                        sender=sender,
                        sender_name=sender_name   # [FIX]
                    )
                    if result['success'] and result.get('headline'):
                        bot.gupshup.send_message(
                            sender,
                            f"✅ వార్త ప్రాసెస్ అయింది!\n\n📰 {result['headline']}"
                        )
                    os.unlink(temp_file.name)
                
                else:
                    # Standard processing for media with text/audio
                    ext_map   = {'image': '.jpg', 'video': '.mp4', 'audio': '.mp3'}
                    ext       = ext_map.get(media_type, '.bin')
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                    temp_file.close()

                    if bot.gupshup.download_media(media_data['url'], temp_file.name):
                        sender_name = item.get('sender_name', '')
                        print(f"  [WORKER] sender={sender} | sender_name='{sender_name}'")
                        result = bot.process_message(
                            text=media_data.get('text'),
                            media_path=temp_file.name,
                            sender=sender,
                            sender_name=sender_name   # [FIX]
                        )
                        if result['success'] and result.get('headline'):
                            bot.gupshup.send_message(
                                sender,
                                f"✅ వార్త ప్రాసెస్ అయింది!\n\n📰 {result['headline']}"
                            )
                    os.unlink(temp_file.name)

            # Process expired text-only messages
            for item in bot.message_queue.get_expired_text():
                sender    = item['sender']
                text_data = item['text_data']
                logger.info(f"⏰ Processing expired text-only for {sender}")

                sender_name = item.get('sender_name', '')
                print(f"  [WORKER] text-only | sender={sender} | sender_name='{sender_name}'")
                result = bot.process_message(
                    text=text_data.get('text'),
                    media_path=None,
                    sender=sender,
                    sender_name=sender_name   # [FIX]
                )
                if result['success'] and result.get('headline'):
                    bot.gupshup.send_message(
                        sender,
                        f"✅ వార్త ప్రాసెస్ అయింది!\n\n📰 {result['headline']}"
                    )

        except Exception as e:
            logger.error(f"Background worker error: {e}")
            sleep(5)


_building_lock = threading.Lock()
_TTS_SEMAPHORE = threading.Semaphore(1)  # ek waqt mein sirf ek report TTS karega

_last_count    = 0


def _get_metadata_count() -> int:
    try:
        return len(load_metadata())
    except Exception:
        return 0

def _delete_incident(incident_id: str):
    try:
        import requests as _req  # ← add karo
        from config import LOCALAITV_API_TOKEN
        resp = _req.delete(
            f"https://localaitv.com/api/incidents/{incident_id}",
            headers={"Authorization": f"Bearer {LOCALAITV_API_TOKEN}"},
            timeout=10
        )
        print
        if resp.status_code in (200, 204):
            logger.info(f"🗑️ Incident deleted: {incident_id}")
        else:
            logger.warning(f"⚠️ Delete failed {incident_id}: {resp.status_code}")
    except Exception as e:
        logger.error(f"❌ Delete incident error: {e}")

def _send_bulletin_items_to_api(items: list, segments_url: str, bulletin_dir: str):
    import requests as _req
    import concurrent.futures
    from config import (
        LOCALAITV_API_URL, LOCALAITV_API_TOKEN,
        API_BASE_URL, BASE_OUTPUT_DIR, BASE_INPUT_DIR,
        INPUT_IMAGE_DIR, INPUT_VIDEO_DIR,
        PREFIX_IMAGE, PREFIX_VIDEO,
        LOCALAITV_CATEGORY_ID,
    )

    if not LOCALAITV_API_URL or not items:
        return

    headers = {"Content-Type": "application/json"}
    if BULLETIN_API_TOKEN:
        headers["Authorization"] = f"Bearer {BULLETIN_API_TOKEN}"

    def to_url(local_path):
        norm = local_path.replace("\\", "/")
        out  = BASE_OUTPUT_DIR.replace("\\", "/").rstrip("/")
        inp  = BASE_INPUT_DIR.replace("\\", "/").rstrip("/")
        if norm.startswith(out):
            rel = norm[len(out):].lstrip("/")
        elif norm.startswith(inp):
            rel = norm[len(inp):].lstrip("/")
        else:
            rel = os.path.basename(local_path)
        return f"{API_BASE_URL}/api/media/{rel}"

    def find_media(counter, media_type):
        exts_map = {
            "image": (["jpg","jpeg","png","webp","gif"], INPUT_IMAGE_DIR, PREFIX_IMAGE),
            "video": (["mp4","mov","avi","mkv","webm"], INPUT_VIDEO_DIR, PREFIX_VIDEO),
        }
        if media_type not in exts_map:
            return None
        exts, directory, prefix = exts_map[media_type]
        for ext in exts:
            p = os.path.join(directory, f"{prefix}{counter}.{ext}")
            if os.path.exists(p):
                return p
        return None

    # Metadata fallback for location_id — ek baar load karo
    from bulletin_builder import load_metadata as _load_meta
    _meta_map = {str(m.get('counter')): m for m in _load_meta()}

    from config import OUTPUT_SCRIPT_DIR

    def _post_one(item):
        try:
            item_loc_id = item.get("location_id")
            if not item_loc_id or int(item_loc_id) == 0:
                meta_entry  = _meta_map.get(str(item.get('counter')), {})
                item_loc_id = meta_entry.get('location_id')
                if item_loc_id:
                    item['location_id']   = item_loc_id
                    item['location_name'] = meta_entry.get('location_name', '')
            # if not item_loc_id or int(item_loc_id) == 0:
            #     logger.info(f"  Skipping item {item.get('counter')} - no valid location_id")
            #     return None



            counter         = item.get("counter")
            media_type      = item.get("media_type", "")
            headline        = item.get("headline", "వార్త")
            script_audio    = item.get("script_audio", "")
            script_filename = item.get("script_filename", "")

            scripts_dir = os.path.join(bulletin_dir, "scripts")
            audio_local = os.path.join(scripts_dir, script_audio)
            audio_url   = to_url(audio_local) if os.path.exists(audio_local) else None

            script_text     = ""
            script_txt_path = os.path.join(OUTPUT_SCRIPT_DIR, script_filename) if script_filename else None
            if script_txt_path and os.path.exists(script_txt_path):
                try:
                    with open(script_txt_path, "r", encoding="utf-8") as _sf:
                        script_text = _sf.read().strip()
                except Exception as _e:
                    logger.warning(f"  ⚠️ Could not read script for item {counter}: {_e}")
            if not script_text:
                script_text = headline

            # media_local      = find_media(counter, media_type)
            # image_url        = to_url(media_local) if (media_local and media_type == "image") else None

            media_local = find_media(counter, media_type)
            image_url   = None

            if media_local and media_type == "image":
                image_url = to_url(media_local)
            elif media_local and media_type == "video":
                # Video ke pehle frame se thumbnail extract karo
                thumb_path = media_local.rsplit(".", 1)[0] + "_thumb.jpg"
                if not os.path.exists(thumb_path):
                    import subprocess
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", media_local, "-ss", "00:00:01",
                        "-vframes", "1", "-q:v", "2", thumb_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                if os.path.exists(thumb_path):
                    image_url = to_url(thumb_path)
            rank             = item.get("rank", counter)
            news_segment_url = None
            item_video_local = item.get('item_video_local')
            if item_video_local and os.path.exists(item_video_local):
                news_segment_url = to_url(item_video_local)
            else:
                logger.warning(f"  ⚠️ No concat item video for rank={rank} — video_path skipped")
            payload = {
                "title":       headline[:255],
                "description": script_text[:1000],   # ← trim — heavy payload fix
                "category_id": str(LOCALAITV_CATEGORY_ID),
            }
            # loc_id = item.get('location_id')
            # if loc_id is not None and str(loc_id) != '0':
            #     payload["location_id"] = str(loc_id)

            loc_id = item.get('location_id', 0)
            if not loc_id or int(loc_id) == 0:
                loc_id = 1  # sirf tab jab API ne nahi bheja
            payload["location_id"] = str(loc_id)

            # loc_id = item.get('location_id', 0) or 1  # fallback to 1 (Hyderabad) if 0
            # payload["location_id"] = int(loc_id)

            post_location = (
                item.get('location_name') or
                item.get('location_address') or
                'Telangana'
            )
            payload["post_location"] = post_location
            created_at = item.get('created_at', '') or item.get('timestamp', '')
            print(1143, "created_at:", created_at)
            payload["timestamp"] = created_at if created_at else datetime.now().isoformat()

            # _post_one ke andar — already existing code ke saath:
            user_id = item.get('user_id', '')
            if not user_id:
                meta_entry = _meta_map.get(str(item.get('counter')), {})
                user_id    = meta_entry.get('user_id', '')
            if user_id:
                payload["user_id"] = user_id
            else:
                logger.warning(f"  ⏭️  Item {counter} — user_id missing, skipping")
                return  # ya continue, depending on structure
            # if audio_url:
            #     payload["audio_path"] = audio_url
            if image_url:
                payload["cover_image_path"] = image_url
            if news_segment_url:
                payload["video_path"] = news_segment_url
            if segments_url:
                payload["segments_path"] = segments_url

            _log_payload(f'incident_item_{counter}', payload)
            logger.info(f"  📦 Incident payload [item {counter}]: {json.dumps(payload, ensure_ascii=False)}")

            resp = _req.post(f"{LOCALAITV_API_URL}/api/incidents", json=payload, headers=headers, timeout=15)
            logger.info(f"  📤 Item {counter} → {resp.status_code}")

            if resp.status_code in (200, 201):
                resp_data   = resp.json()
                incident_id = (
                    resp_data.get("data", {}).get("incident_id")
                    or resp_data.get("data", {}).get("id")
                    or resp_data.get("id", "?")
                )
                logger.info(f"  ✅ Item {counter} → incident {incident_id}")

                try:
                    # _req.post(f"{API_BASE_URL}/api/incidents/local", json=payload, timeout=5)

                    from event_logger import save_incident
                    save_incident(payload, incident_id=str(incident_id))

                    logger.info(f"  📥 Local mirror done: {payload.get('title','?')}")
                except Exception as _e:
                    logger.warning(f"  ⚠️ Local mirror failed: {_e}")

                from event_logger import log_event
                log_event(
                    event        = 'api_posted',
                    counter      = counter,
                    media_type   = media_type,
                    incident_id  = str(incident_id),
                    api_item_id  = str(incident_id),
                    api_status   = 'success',
                    api_response = str(resp.status_code),
                )
                return (counter, media_type, str(incident_id))
            else:
                logger.warning(f"  ⚠️ Item {counter} → {resp.status_code}: {resp.text[:200]}")
                from event_logger import log_event
                log_event(
                    event        = 'api_posted',
                    counter      = counter,
                    media_type   = media_type,
                    api_status   = 'failed',
                    api_response = f"{resp.status_code}: {resp.text[:200]}",
                )
                return None

        except Exception as e:
            logger.error(f"  ❌ Item {item.get('counter')} API error: {e}")
            return None

    logger.info(f"📡 Sending {len(items)} items to Incidents API (parallel)...")

    # ── Parallel POST ─────────────────────────────────────────────────────────
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_post_one, item) for item in items]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                counter, media_type, incident_id = res
                results[(counter, media_type)] = incident_id

    # ── Metadata EK BAAR update karo — loop ke bahar ─────────────────────────

    if results:
        from bulletin_builder import load_metadata, save_metadata, _metadata_lock
        with _metadata_lock:
            all_meta = load_metadata()
            for m in all_meta:
                key = (m.get('counter'), m.get('media_type'))
                if key in results:
                    m['incident_id'] = results[key]
            save_metadata(all_meta)
        # ADD:
        from event_logger import update_incident_id
        # for (counter, media_type), incident_id in results.items():
        #     update_incident_id(counter, media_type, incident_id)
        for (counter, media_type), incident_id in results.items():
            threading.Thread(
                target=update_incident_id,
                args=(counter, media_type, incident_id),
                daemon=True
            ).start()
        logger.info(f"✅ Metadata updated for {len(results)} items")

##### ── 08-04-15-43 ────────────────────────────────────────────────────
def _get_bulletin_thumbnail(items: list, manifest: dict) -> str | None:
    """First item ka thumbnail return karta hai bulletin ke liye."""
    from config import BASE_OUTPUT_DIR, BASE_INPUT_DIR, INPUT_IMAGE_DIR, INPUT_VIDEO_DIR, PREFIX_IMAGE, PREFIX_VIDEO, API_BASE_URL

    def to_url(local_path):
        norm = local_path.replace("\\", "/")
        out  = BASE_OUTPUT_DIR.replace("\\", "/").rstrip("/")
        inp  = BASE_INPUT_DIR.replace("\\", "/").rstrip("/")
        if norm.startswith(out):
            rel = norm[len(out):].lstrip("/")
        elif norm.startswith(inp):
            rel = norm[len(inp):].lstrip("/")
        else:
            rel = os.path.basename(local_path)
        return f"{API_BASE_URL}/api/media/{rel}"

    sorted_items = sorted(items, key=lambda x: x.get("rank", x.get("counter", 999)))
    for item in sorted_items:
        counter    = item.get("counter")
        media_type = item.get("media_type", "")

        if media_type == "image":
            for ext in ["jpg","jpeg","png","webp"]:
                p = os.path.join(INPUT_IMAGE_DIR, f"{PREFIX_IMAGE}{counter}.{ext}")
                if os.path.exists(p):
                    return to_url(p)

        elif media_type == "video":
            for ext in ["mp4","mov","avi","mkv","webm"]:
                p = os.path.join(INPUT_VIDEO_DIR, f"{PREFIX_VIDEO}{counter}.{ext}")
                if os.path.exists(p):
                    thumb_path = p.rsplit(".", 1)[0] + "_thumb.jpg"
                    if not os.path.exists(thumb_path):
                        import subprocess
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", p, "-ss", "00:00:01",
                             "-vframes", "1", "-q:v", "2", thumb_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                    if os.path.exists(thumb_path):
                        return to_url(thumb_path)
    return None

##### ── 08-04-15-43 ────────────────────────────────────────────────────

##### ── 08-04-15-43 ────────────────────────────────────────────────────

import json, os
from datetime import datetime

PAYLOAD_LOG = os.path.join(BASE_DIR, 'payloads.json')

def _log_payload(label: str, payload: dict):
    """Debug: append payload to payloads.json"""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'label': label,
        'payload': payload
    }
    try:
        if os.path.exists(PAYLOAD_LOG):
            with open(PAYLOAD_LOG, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
        data.append(entry)
        with open(PAYLOAD_LOG, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️ Payload log failed: {e}")

##### ── 08-04-15-43 ────────────────────────────────────────────────────

##------------ added 10-04-12-43 ------------    

def _trim_timestamp(ts: str) -> str:
    """Convert 2026-04-09T10:42:23.416044 -> 2026-04-09T10:42:23"""
    if not ts:
        return datetime.now().isoformat(timespec="seconds")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return ts.split(".")[0] if "." in ts else ts
##------------ added 10-04-12-43 ------------    

def _send_bulletin_to_api(bulletin_dir: str, video_path: str, manifest: dict):
    import requests as _req
    from config import LOCALAITV_API_TOKEN, API_BASE_URL, BASE_OUTPUT_DIR

    url = "https://localaitv.com/api/bulletins"
    headers = {"Authorization": f"Bearer {BULLETIN_API_TOKEN}",
               "Content-Type": "application/json"}

    # Video URL banana
    if '/outputs/' in video_path:
        rel = video_path.replace('\\', '/').split('/outputs/')[1]
    else:
        rel = os.path.basename(video_path)
    video_url = f"{API_BASE_URL}/api/media/{rel}"

    items     = manifest.get('items', [])
    loc_name  = items[0].get('location_name', '') if items else ''
    # created   = manifest.get('created_at', '')[:10]
    # title     = f"{loc_name} News Bulletin {created}".strip() if loc_name else 'News Bulletin'
    IST = pytz.timezone("Asia/Kolkata")
    created_at = manifest.get('created_at', datetime.now().isoformat())
    start_dt   = datetime.fromisoformat(created_at).replace(tzinfo=pytz.utc).astimezone(IST)

    rounded_min = (start_dt.minute // 5) * 5
    start_dt   = start_dt.replace(minute=rounded_min, second=0, microsecond=0)

    # ✅ Only starting time
    start_time = start_dt.strftime('%I:%M %p').lstrip('0')
    # location_en = manifest.get('location', '') or (items[0].get('location_name', '') if items else '')
    # # "Kurnool, Kurnool" jaise strings se sirf pehla part lo
    # location_en = location_en.split(',')[0].strip()
    location_en = "Kurnool"
    _oai = OpenAIHandler()
    location_te = _oai.translate_to_telugu(location_en) if location_en else 'వార్త'

    title = f"{location_te} వార్త బులెటిన్స్ | 🕒 {start_time}"


    payload = {
        "title":          title,
        "content":        f"{manifest.get('item_count', 0)} news items",
        "timestamp": _trim_timestamp(manifest.get("created_at", "")),
        "priority_level": "low",
        "expiry_time":    None,
        "image_url":      _get_bulletin_thumbnail(items, manifest),  ## changed-08-04-15-43
        "audio_url":      None,
        "video_url":      video_url,  # ← bulletin final video
    }

    try:
        _log_payload('bulletin', payload)

        resp = _req.post(url, json=payload, headers=headers, timeout=15)
        logger.info(f"  📤 Payload: {json.dumps(payload, ensure_ascii=False)}")
        if resp.status_code in (200, 201):
            logger.info(f"✅ Bulletin sent to API: {resp.json()}")
            # ADD:
            from event_logger import log_event
            bulletin_id = resp.json().get('id')
            log_event(
                event         = 'bulletin_uploaded',
                bulletin_name = os.path.basename(bulletin_dir),
                api_item_id   = bulletin_id,
                api_status    = 'success',
                api_response  = str(resp.status_code),
            )
        else:
            logger.warning(f"⚠️ Bulletin API: {resp.status_code}: {resp.text[:200]}")
            # ADD:
            from event_logger import log_event
            log_event(
                event         = 'bulletin_uploaded',
                bulletin_name = os.path.basename(bulletin_dir),
                api_status    = 'failed',
                api_response  = f"{resp.status_code}: {resp.text[:200]}",
            )
    except Exception as e:
        logger.error(f"❌ Bulletin API error: {e}")


def _concat_item_segments(rank: int, segments_dir: str, out_path: str) -> bool:
    """Collect all segments for a given item rank and concat into one video."""
    import glob, shutil

    rank_str = str(rank).zfill(2)

    # Collect in filename-sorted order (NNN_ prefix ensures correct sequence)
    patterns = [
        f"*_intro_{rank_str}.mp4",
        f"*_clip_{rank_str}.mp4",
        f"*_analysis_{rank_str}.mp4",
        f"*_news_{rank_str}.mp4",        # image / audio items (single segment)
    ]

    matched = []
    for pat in patterns:
        found = sorted(glob.glob(os.path.join(segments_dir, pat)))
        matched.extend(found)

    # Re-sort by the numeric NNN prefix so order is always correct
    matched = sorted(set(matched), key=lambda p: os.path.basename(p))

    if not matched:
        logger.warning(f"  ⚠️ No segments found for rank={rank}")
        return False

    if len(matched) == 1:
        shutil.copy2(matched[0], out_path)
        return True

    list_file = out_path + '_list.txt'
    try:
        with open(list_file, 'w', encoding='utf-8') as f:
            for seg in matched:
                f.write(f"file '{os.path.abspath(seg)}'\n")
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', list_file,
            '-c', 'copy',
            out_path
        ]
        _governor.wait_for_slot(f'concat rank={rank if "rank" in dir() else "?"}')
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            logger.error(f"  ❌ ffmpeg concat error: {result.stderr.decode()[-300:]}")
            return False
        return True
    finally:
        if os.path.exists(list_file):
            os.unlink(list_file)

def _run_planner():
    global _last_count

    if not _building_lock.acquire(blocking=False):
        logger.info("🔒 Bulletin build already in progress — skipping this cycle")
        return

    try:
        logger.info("🔨 Building bulletins (all locations)...")
        from bulletin_builder import build_all_location_bulletins
        results = build_all_location_bulletins(10)

        if not results:
            logger.warning("⚠️ No items — bulletin not built")
            return

        # ── Ticker text: saare metadata items ki headlines join karo ──────────
        from bulletin_builder import load_metadata
        from datetime import datetime, timedelta, timezone

        _all_meta = load_metadata()
        _cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        seen = set()
        _headlines = []
        for item in _all_meta:
            h = item.get('headline', '').strip()
            if not h or h in seen:
                continue
            ts_str = item.get('created_at') or item.get('timestamp', '')
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= _cutoff:
                    seen.add(h)
                    _headlines.append(h)
            except Exception:
                _headlines.append(h)
        ticker_text = '   ★   '.join(_headlines) if _headlines else "తాజా వార్తల కోసం చూస్తూ ఉండండి"
        # ─────────────────────────────────────────────────────────────────────


        if not results:
            logger.warning("⚠️ No items — bulletin not built")
            return

        _base      = BASE_DIR or os.path.dirname(os.path.abspath(__file__))
        logo_path  = os.path.join(_base, 'logo3.mov')
        intro_path = os.path.join(_base, 'intro4.mp4')

        if not os.path.exists(logo_path):
            logger.error(f"❌ logo3.mov not found at: {logo_path}")
        if not os.path.exists(intro_path):
            logger.error(f"❌ intro3.mp4 not found at: {intro_path}")

        import json as _json

        for loc_id, info in results.items():
            bulletin_dir = info.get('path')
            if not bulletin_dir:
                logger.warning(f"⚠️ No bulletin for location [{loc_id}] {info.get('location_name')}")
                continue

            logger.info(f"🏗️  Processing bulletin: [{loc_id}] {info.get('location_name')}")

            # ── Read manifest BEFORE build — already written by build_all_location_bulletins ──
            manifest_path  = os.path.join(bulletin_dir, 'bulletin_manifest.json')
            segments_dir   = os.path.join(bulletin_dir, 'segments')
            item_video_dir = os.path.join(bulletin_dir, 'item_videos')
            os.makedirs(item_video_dir, exist_ok=True)

            _manifest = {}
            items     = []
            try:
                with open(manifest_path, 'r', encoding='utf-8') as _mf:
                    _manifest = _json.load(_mf)
                items = _manifest.get('items', [])
                logger.info(f"📋 Pre-build manifest loaded: {len(items)} items")
            except Exception as _e:
                logger.warning(f"⚠️ Could not read pre-build manifest: {_e}")

            # expected_ranks = {item.get('rank') for item in items}
            # item_by_rank   = {item.get('rank'): item for item in items}
            expected_ranks = {item.get('rank') for item in items if item.get('type') == 'news'}
            item_by_rank   = {item.get('rank'): item for item in items if item.get('type') == 'news'}

            # ── Start bulletin video build in BACKGROUND thread ───────────────
            # Isse watcher saath mein chal sakta hai — bulletin complete hone
            # ka wait kiye bina incidents fire ho sakti hain.
            # _build_result = {'video_path': None, 'error': None}

            # Yahan add karo:
            _build_done = threading.Event()
            _build_result = {'video_path': None, 'error': None}

            def _build_video_bg():
                logger.info(f"🔨 [BUILD-THREAD] Starting: {os.path.basename(bulletin_dir)}")
                try:
                    # ── Stale markers ko BUILD THREAD ke andar clean karo ──
                    import glob as _glob
                    for _stale in _glob.glob(os.path.join(segments_dir, 'item_*_ready.json')):
                        try:
                            os.remove(_stale)
                            logger.info(f"🧹 Stale marker removed: {os.path.basename(_stale)}")
                        except Exception:
                            pass
                    # ─────────────────────────────────────────────────────
                    vp = queue_bulletin_build(bulletin_dir, logo_path, intro_path, ticker_text=ticker_text)

                    _build_result['video_path'] = vp
                    logger.info(f"🔨 [BUILD-THREAD] Done → {vp}")
                except Exception as _be:
                    _build_result['error'] = str(_be)
                    logger.error(f"❌ [BUILD-THREAD] Exception: {_be}", exc_info=True)
                finally:
                    _build_done.set()  # ← Signal: thread complete (success ya error dono mein)

            build_thread = threading.Thread(
                target=_build_video_bg,
                daemon=True,
                name=f"bulletin-build-{loc_id}"
            )
            import glob as _glob
            for _stale in _glob.glob(os.path.join(segments_dir, 'item_*_ready.json')):
                try:
                    os.remove(_stale)
                    logger.info(f"🧹 Stale marker removed: {os.path.basename(_stale)}")
                except Exception:
                    pass
            build_thread.start()
            logger.info(f"🚀 [WATCHER] Build thread started — now watching for item-ready markers in segments/")

            # ── Watcher: poll segments_dir for item_XX_ready.json markers ─────
            # video_builder.py har item ke segments done hone ke baad marker
            # likhta hai. Watcher use pick up karke turant concat + incident fire
            # karta hai — bulletin complete hone ka wait NAHI karta.
            processed_ranks = set()
            segments_url    = None

            POLL_INTERVAL = 0.5   # seconds — kitni baar scan karna hai
            MAX_WAIT_SEC = 1800
            
            t_watch_start = time()
            logger.info(f"⏱️  [WATCHER] Polling every {POLL_INTERVAL}s | timeout={MAX_WAIT_SEC}s | expecting {len(expected_ranks)} items")

            while len(processed_ranks) < len(expected_ranks):

                # Build thread crash check
                # if not build_thread.is_alive() and not _build_result['video_path']:
                #     logger.error("❌ [WATCHER] Build thread died without producing video — stopping watcher")
                #     break

                # if _build_done.is_set() and not _build_result['video_path']:
                #     logger.error("❌ [WATCHER] Build thread finished without producing video — stopping watcher")
                #     break

                if _build_done.is_set():
                    if _build_result['video_path']:
                        logger.info("✅ [WATCHER] Build thread completed successfully")
                        break
                    elif _build_result.get('error'):
                        logger.error(f"❌ [WATCHER] Build thread errored: {_build_result['error']}")
                        break

                # Timeout check
                elapsed_watch = time() - t_watch_start
                if elapsed_watch > MAX_WAIT_SEC:
                    logger.error(f"❌ [WATCHER] Timeout after {MAX_WAIT_SEC}s — processed {len(processed_ranks)}/{len(expected_ranks)}")
                    break

                # Scan for new item-ready markers
                if os.path.exists(segments_dir):
                    for rank in sorted(expected_ranks - processed_ranks):
                        marker_path = os.path.join(segments_dir, f'item_{rank:02d}_ready.json')
                        if not os.path.exists(marker_path):
                            continue

                        # ── Marker mila — read karo ───────────────────────────
                        try:
                            with open(marker_path, 'r', encoding='utf-8') as _mf:
                                marker = _json.load(_mf)
                        except Exception as _me:
                            logger.warning(f"  ⚠️ [rank={rank}] Marker read error (retry next cycle): {_me}")
                            continue  # next poll cycle mein try karenge

                        is_reused = marker.get('reused', False)
                        item_dict = item_by_rank.get(rank, marker.get('item', {}))
                        counter   = item_dict.get('counter')
                        mtype     = item_dict.get('media_type', '')
                        item_out  = os.path.join(item_video_dir, f"item_{rank:02d}.mp4")

                        logger.info(
                            f"  📌 [rank={rank}] Marker detected "
                            f"(counter={counter}, type={mtype}, reused={is_reused}) "
                            f"at t+{round(time()-t_watch_start, 1)}s into watch"
                        )

                        # ── Build segments_url once (after segments_dir exists) ──
                        if not segments_url:
                            from config import BASE_OUTPUT_DIR
                            norm_seg = segments_dir.replace('\\', '/')
                            norm_out = BASE_OUTPUT_DIR.replace('\\', '/').rstrip('/')
                            if norm_seg.startswith(norm_out):
                                rel = norm_seg[len(norm_out):].lstrip('/')
                            else:
                                rel = os.path.relpath(segments_dir, BASE_DIR).replace('\\', '/')
                            segments_url = f"{LOCALAITV_API_URL}/api/media/{rel}"
                            logger.info(f"📂 Segments URL: {segments_url}")

                        # ── Reused item: sirf copy + metadata, incident skip ───
                        if is_reused:
                            # existing = item_dict.get('item_video_local', '')
                            # if existing and os.path.exists(existing):
                            #     if os.path.abspath(existing) != os.path.abspath(item_out):
                            #         shutil.copy2(existing, item_out)
                            #         item_dict['item_video_local'] = item_out
                            logger.info(f"  ♻️  [rank={rank}] Reused video copied → {os.path.basename(item_out)}")
                            from bulletin_builder import load_metadata, save_metadata, _metadata_lock
                            with _metadata_lock:
                                all_meta = load_metadata()
                                for m in all_meta:
                                    if m.get('counter') == counter and m.get('media_type') == mtype:
                                        m['item_video_local'] = item_out
                                        break
                                save_metadata(all_meta)
                                # else:
                                #     logger.info(f"  ♻️  [rank={rank}] Already at correct path — skip copy")
                            logger.info(f"  ⏭️  [rank={rank}] Reused item — incident re-post skip")
                            processed_ranks.add(rank)
                            continue

                        # ── Fresh item: concat segments → incident fire ────────
                        t_concat = time()
                        logger.info(f"  🔧 [rank={rank}] concat starting...")
                        ok = _concat_item_segments(rank, segments_dir, item_out)
                        concat_elapsed = round(time() - t_concat, 2)

                        if ok:
                            item_dict['item_video_local'] = item_out
                            logger.info(f"  ✅ [rank={rank}] concat done in {concat_elapsed}s → {os.path.basename(item_out)}")

                            # # ── Save to global item video cache ───────────────
                            # # Next bulletin can reuse this immediately, even
                            # # before current bulletin finishes building.
                            # try:
                            #     from config import ITEM_VIDEO_CACHE_DIR
                            #     import shutil as _shc
                            #     os.makedirs(ITEM_VIDEO_CACHE_DIR, exist_ok=True)
                            #     cache_dst = os.path.join(
                            #         ITEM_VIDEO_CACHE_DIR,
                            #         f'item_{counter}_video.mp4'
                            #     )
                            #     _shc.copy2(item_out, cache_dst)
                            #     logger.info(f"  💾 [CACHE] item_{counter}_video.mp4 → cache")
                            # except Exception as _ce:
                            #     logger.warning(f"  ⚠️  [CACHE] copy failed counter={counter}: {_ce}")

                            # ── Metadata update ───────────────────────────────
                            from bulletin_builder import load_metadata, save_metadata, _metadata_lock
                            with _metadata_lock:
                                all_meta = load_metadata()
                                for m in all_meta:
                                    if m.get('counter') == counter and m.get('media_type') == mtype:
                                        m['item_video_local'] = item_out
                                        # m['item_video_cached'] = cache_dst if 'cache_dst' in dir() else ''
                                        break
                                save_metadata(all_meta)
                            logger.info(f"  💾 [rank={rank}] metadata saved")

                            # ── TURANT incident fire — bulletin ka wait nahi ───
                            logger.info(
                                f"  🚀 [rank={rank}] Firing incident thread at "
                                f"t+{round(time()-t_watch_start, 1)}s "
                                f"(bulletin build still in progress)"
                            )
                            threading.Thread(
                                # target=_send_bulletin_items_to_api,
                                args=([item_dict], segments_url, bulletin_dir),
                                daemon=True,
                                name=f"incident-rank-{rank}"
                            ).start()

                        else:
                            item_dict['item_video_local'] = None
                            logger.warning(f"  ⚠️ [rank={rank}] concat FAILED after {concat_elapsed}s")

                        processed_ranks.add(rank)

                from time import sleep as _sleep
                _sleep(POLL_INTERVAL)

            total_watch = round(time() - t_watch_start, 1)
            logger.info(
                f"✅ [WATCHER] Done — {len(processed_ranks)}/{len(expected_ranks)} items processed "
                f"in {total_watch}s total watch time"
            )

            # ── Wait for bulletin build thread to finish ───────────────────────
            logger.info(f"⏳ Waiting for bulletin build thread to complete...")
            build_thread.join(timeout=1800)

            video_path = _build_result.get('video_path')
            print(1044, video_path)
            if not video_path:
                logger.error(f"❌ Bulletin video build failed for [{loc_id}] {info.get('location_name')}")
                continue

            # ── Re-read manifest (video_builder updates it during build) ──────
            try:
                with open(manifest_path, 'r', encoding='utf-8') as _mf:
                    _manifest = _json.load(_mf)
                logger.info(f"📋 Post-build manifest re-read OK")
            except Exception as _e:
                logger.warning(f"⚠️ Could not re-read manifest after build: {_e}")

            # # ── Write item_video_local paths into manifest ────────────────────
            # for idx, mitem in enumerate(_manifest.get('items', [])):
            #     r = mitem.get('rank')
            #     if r in item_by_rank and item_by_rank[r].get('item_video_local'):
            #         _manifest['items'][idx]['item_video_local'] = item_by_rank[r]['item_video_local']

            try:
                with open(manifest_path, 'w', encoding='utf-8') as _mf:
                    _json.dump(_manifest, _mf, ensure_ascii=False, indent=2)
                logger.info("💾 Manifest saved with updated item_video_local paths")
            except Exception as _e:
                logger.warning(f"⚠️ Could not save manifest: {_e}")

            _last_count = _get_metadata_count()
            logger.info(f"✅ Bulletin ready → {video_path}")

            # ── POST full bulletin video to Bulletins API (uncomment when needed) ──
            # _send_bulletin_to_api(bulletin_dir, video_path, _manifest)
            print(f"📤 Payload preview (would send to API): {json.dumps(_manifest, ensure_ascii=False)[:1000]}...")

    except Exception as e:
        logger.error(f"❌ Planner build error: {e}", exc_info=True)

    finally:
        _building_lock.release()
        # ── Auto-trigger: agar build ke dauran naye items aaye toh ──
        from bulletin_builder import load_metadata, BULLETINS_DIR
        try:
            all_meta = load_metadata()
            pending = sum(1 for v in all_meta.values() if not v.get('used_count',0) == 0)
            if pending > 0:
                logger.info(f"🔄 Post-build: {pending} items pending — auto-triggering next build")
                threading.Thread(target=_run_planner, daemon=True).start()
        except Exception:
            pass



def _load_processed_ids():
    try:
        with open(PROCESSED_IDS_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()

def _save_processed_id(report_id: str):
    _processed_report_ids.add(report_id)
    try:
        with open(PROCESSED_IDS_FILE, 'w') as f:
            json.dump(list(_processed_report_ids), f)
    except Exception as e:
        logger.warning(f"⚠️ Could not save processed IDs: {e}")

_processed_report_ids = _load_processed_ids()  # ← set() replace kiya

def poll_reports_loop():
    """Poll reports API every 10 seconds for new submissions"""
    from config import LOCALAITV_API_TOKEN
    logger.info("📡 Reports poller started")
    while True:
        try:
            resp = _req.get(
                REPORTS_API_URL,
                headers={
                    "Host": "localaitv.com",
                    "Authorization": f"Bearer {LOCALAITV_API_TOKEN}"
                },
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                try:
                    debug_path = os.path.join(BASE_DIR, "debug_report.json")
                    with open(debug_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4, ensure_ascii=False)
                    # logger.info(f"📝 Saved polled report JSON to {debug_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Debug write failed: {e}")
                reports = data.get('items', data.get('data', []))
                
                for report in reports:
                    report_id = report.get('id')
                    if not report_id or report_id in _processed_report_ids:
                        continue
                    
                    _processed_report_ids.add(report_id)
                    _save_processed_id(report_id)
                    logger.info(f"🆕 New report: {report_id}")
                    
                    # Queue mein daalo
                    _enqueue_report(report)
                    
        except Exception as e:
            logger.error(f"❌ Poll error: {e}")
        
        sleep(10)

def planner_loop():
    global _last_count

    _last_count = _get_metadata_count()
    logger.info(f"⏰ Planner started (current item count: {_last_count})")

    while True:
        sleep(60)

        try:
            current_count = _get_metadata_count()

            # Lines 642-657 ko yeh kar do:
            if current_count == _last_count:
                continue

            # ← YEH UNCOMMENT + FIX KARO
            from bulletin_builder import load_metadata, BULLETINS_DIR
            existing_bulletins = [
                d for d in os.listdir(BULLETINS_DIR)
                if os.path.isdir(os.path.join(BULLETINS_DIR, d))
            ] if os.path.exists(BULLETINS_DIR) else []

            unbulletined = sum(1 for m in load_metadata() if not m.get('bulletined'))

            if not existing_bulletins and current_count < 5:
                logger.info(f"⏳ First bulletin needs 5 items — only {current_count} ready")
                continue

            if current_count < 6 and unbulletined < 1:
                logger.info(f"⏳ Only {current_count} items — waiting for at least 6")
                continue

            # logger.info(f"🆕 {unbulletined} new item(s) pending — triggering build")
            # threading.Thread(target=_run_planner, daemon=True).start()
            # FIX:
            logger.info(f"🆕 {unbulletined} new item(s) pending — triggering build")
            if not _building_lock.locked():
                threading.Thread(target=_run_planner, daemon=True).start()
            else:
                logger.info("🔒 Build in progress — next build will auto-trigger after current finishes")
            
            _last_count = current_count
            # ─────────────────────────────────────────────────────────────

            # logger.info(
            #     f"🆕 Planner: {current_count - _last_count} new item(s) detected "
            #     f"({_last_count} → {current_count}) — triggering build"
            # )
            # threading.Thread(target=_run_planner, daemon=True).start()

        except Exception as e:
            logger.error(f"❌ Planner loop error: {e}")

threading.Thread(target=planner_loop,          daemon=True).start()
logger.info("⏰ Planner loop started")

threading.Thread(target=process_expired_queue, daemon=True).start()
logger.info("🚀 Background worker started")
threading.Thread(target=poll_reports_loop,     daemon=True).start()
# logger.info("📡 Reports poller started")

def retry_failed_reports_loop():
    """
    Every 2 minutes: check report_state.json for failed or stuck reports and retry them.
    Stuck = status 'processing' with last_attempt older than STUCK_THRESHOLD_MINUTES.
    """
    import report_state_manager as _rsm
    logger.info("🔁 Retry loop started")
    sleep(120)  # wait 2 min on startup before first check
    while True:
        try:
            retryable = _rsm.get_retryable_reports()
            if retryable:
                logger.info(f"🔁 Found {len(retryable)} report(s) to retry")
            for report in retryable:
                report_id = report.get('id')
                if not report_id:
                    continue
                logger.info(f"🔁 Retrying report: {report_id}")
                # Re-enqueue — _enqueue_report will call mark_processing again
                # which increments attempt count
                try:
                    _enqueue_report(report)
                except Exception as e:
                    logger.error(f"❌ Retry enqueue failed for {report_id}: {e}")
        except Exception as e:
            logger.error(f"❌ Retry loop error: {e}")
        sleep(120)

threading.Thread(target=retry_failed_reports_loop, daemon=True).start()

def cleanup_old_data_loop():
    """
    Har 1hr check karta hai:
      - 24hr se purane items metadata se remove karta hai
      - Unki saari files delete karta hai:
          inputs/ (images, videos, audios)
          outputs/scripts/, outputs/headlines/, outputs/audios/
          outputs/bulletins/<bulletin_dir>/
          outputs/item_video_cache/
          outputs/reporters/
      - metadata.json  — 24hr+ entries remove
      - report_state.json — 24hr+ entries remove
      - processed_report_ids.json — sync with report_state
      - debug_report.json — 24hr+ old hone par delete
      - ticker_state.json — daily auto-reset (khud hoti hai)
      - outputs/bulletins/*_tmp, *_old — 1hr+ stale folders delete
    Restart-safe: .last_cleanup file se last run time track karta hai.
    """
    import shutil as _shutil
    from time import time, sleep
    from datetime import datetime, timezone, timedelta

    MAX_AGE_SEC      = 24 * 60 * 60   # 24 hours
    CHECK_INTERVAL   = 3600           # har 1hr mein check
    LAST_RUN_FILE    = os.path.join(BASE_DIR, ".last_cleanup")

    logger.info("🧹 Cleanup loop started (24hr mode, checks every 1hr)")

    def _del_file(path: str):
        """Safe file delete with logging."""
        try:
            if path and os.path.isfile(path):
                os.remove(path)
                logger.info(f"🗑️ Deleted: {path}")
        except Exception as e:
            logger.warning(f"⚠️ Could not delete {path}: {e}")

    def _is_older_than_24hr(ts_str: str, now: float) -> bool:
        """ISO timestamp string 24hr se purana hai?"""
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (now - ts.timestamp()) >= MAX_AGE_SEC
        except Exception:
            return False  # parse na ho toh safe side — delete mat karo

    while True:
        now = time()

        # ── Restart-safe: last run check ──────────────────────────────────────
        last_run = 0.0
        try:
            if os.path.exists(LAST_RUN_FILE):
                last_run = float(open(LAST_RUN_FILE).read().strip())
        except Exception:
            last_run = 0.0

        if now - last_run < MAX_AGE_SEC:
            next_in = (last_run + MAX_AGE_SEC - now) / 3600
            logger.info(f"🧹 Cleanup skip — next run in {next_in:.1f} hrs")
            sleep(CHECK_INTERVAL)
            continue

        now = time()
        logger.info("🧹 Running 24-hour cleanup...")

        try:
            from config import BASE_INPUT_DIR, BASE_OUTPUT_DIR
        except ImportError:
            logger.warning("⚠️ Cleanup: could not import config dirs")
            sleep(CHECK_INTERVAL)
            continue

        # ── Config dirs ───────────────────────────────────────────────────────
        try:
            from config import (
                REPORTER_PHOTO_DIR,
                ITEM_VIDEO_CACHE_DIR,
            )
        except ImportError:
            REPORTER_PHOTO_DIR   = None
            ITEM_VIDEO_CACHE_DIR = None

        try:
            from bulletin_builder import (
                BULLETINS_DIR,
                load_metadata,
                save_metadata,
                _metadata_lock,
            )
        except ImportError as e:
            logger.warning(f"⚠️ Cleanup: could not import bulletin_builder: {e}")
            sleep(CHECK_INTERVAL)
            continue

        # ══════════════════════════════════════════════════════════════════════
        # STEP 1 — metadata.json se 24hr+ purane items identify karo
        # ══════════════════════════════════════════════════════════════════════
        old_items  = []   # delete honge
        keep_items = []   # rahenge

        try:
            with _metadata_lock:
                all_items = load_metadata()

            for item in all_items:
                ts_str = item.get('created_at') or item.get('timestamp', '')
                if _is_older_than_24hr(ts_str, now):
                    old_items.append(item)
                else:
                    keep_items.append(item)

            logger.info(
                f"🧹 Metadata: total={len(all_items)} | "
                f"old(delete)={len(old_items)} | keep={len(keep_items)}"
            )
        except Exception as e:
            logger.warning(f"⚠️ Metadata load failed: {e}")
            sleep(CHECK_INTERVAL)
            continue

        # ══════════════════════════════════════════════════════════════════════
        # STEP 2 — purane items ki saari files delete karo
        # ══════════════════════════════════════════════════════════════════════
        for item in old_items:
            counter = item.get('counter')
            logger.info(f"🗑️ Cleaning item counter={counter}")

            # — Output audio files —
            _del_file(os.path.join(OUTPUT_AUDIO_DIR,   item.get('script_audio',   '')))
            _del_file(os.path.join(OUTPUT_HEADLINE_DIR, item.get('headline_audio', '')))
            _del_file(os.path.join(OUTPUT_SCRIPT_DIR,   item.get('script_filename','') if item.get('script_filename') else ''))

            # — Intro / analysis audio (clip items) —
            if item.get('intro_audio_filename'):
                _del_file(os.path.join(OUTPUT_AUDIO_DIR, item['intro_audio_filename']))
            if item.get('analysis_audio_filename'):
                _del_file(os.path.join(OUTPUT_AUDIO_DIR, item['analysis_audio_filename']))

            # — Clip video —
            _del_file(item.get('clip_video_path', ''))

            # — Item video local —
            _del_file(item.get('item_video_local', ''))

            # — Multi-image paths —
            for img_path in item.get('multi_image_paths', []):
                _del_file(img_path)

            # — Input files (counter se match karke) —
            if counter and os.path.exists(BASE_INPUT_DIR):
                for root, _, files in os.walk(BASE_INPUT_DIR):
                    for fname in files:
                        stem   = os.path.splitext(fname)[0]
                        digits = ''.join(filter(str.isdigit, stem))
                        try:
                            if digits and int(digits) == int(counter):
                                _del_file(os.path.join(root, fname))
                        except Exception:
                            pass

        # ══════════════════════════════════════════════════════════════════════
        # STEP 3 — metadata.json save karo (sirf keep_items)
        # ══════════════════════════════════════════════════════════════════════
        if old_items:
            try:
                with _metadata_lock:
                    save_metadata(keep_items)
                logger.info(f"✅ metadata.json updated — {len(old_items)} entries removed")
            except Exception as e:
                logger.warning(f"⚠️ metadata.json save failed: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 4 — outputs/scripts/, headlines/, audios/ leftover files
        #          (jo metadata mein nahi hain but disk par pade hain)
        # ══════════════════════════════════════════════════════════════════════
        for sub in ['scripts', 'headlines', 'audios']:
            folder = os.path.join(BASE_OUTPUT_DIR, sub)
            if not os.path.exists(folder):
                continue
            for fname in os.listdir(folder):
                fpath = os.path.join(folder, fname)
                try:
                    if (os.path.isfile(fpath) and
                            now - os.path.getmtime(fpath) > MAX_AGE_SEC):
                        _del_file(fpath)
                except Exception as e:
                    logger.warning(f"⚠️ Could not check {fpath}: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 5 — inputs/ leftover files (mtime se)
        # ══════════════════════════════════════════════════════════════════════
        if os.path.exists(BASE_INPUT_DIR):
            for root, _, files in os.walk(BASE_INPUT_DIR):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        if now - os.path.getmtime(fpath) > MAX_AGE_SEC:
                            _del_file(fpath)
                    except Exception as e:
                        logger.warning(f"⚠️ Could not check {fpath}: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 6 — Bulletin directories (24hr+ purane)
        # ══════════════════════════════════════════════════════════════════════
        if os.path.exists(BULLETINS_DIR):
            for bname in os.listdir(BULLETINS_DIR):
                bpath = os.path.join(BULLETINS_DIR, bname)
                if not os.path.isdir(bpath):
                    continue

                # Folder name se age nikalo (format: bul_gen_20260317_042409)
                age_sec = None
                parts = bname.replace('_tmp', '').replace('_old', '').split('_')
                if len(parts) >= 4:
                    try:
                        dt_str    = parts[-2] + parts[-1]   # '20260317042409'
                        folder_dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                        age_sec   = now - folder_dt.timestamp()
                    except Exception:
                        pass

                if age_sec is None:
                    age_sec = now - os.path.getmtime(bpath)

                if age_sec > MAX_AGE_SEC:
                    try:
                        _shutil.rmtree(bpath)
                        logger.info(f"🗑️ Deleted bulletin dir: {bname}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not delete bulletin {bpath}: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 7 — Stale _tmp / _old bulletin folders (1hr+)
        # ══════════════════════════════════════════════════════════════════════
        if os.path.exists(BULLETINS_DIR):
            for bname in os.listdir(BULLETINS_DIR):
                bpath = os.path.join(BULLETINS_DIR, bname)
                if not os.path.isdir(bpath):
                    continue
                if bname.endswith('_tmp') or bname.endswith('_old'):
                    try:
                        if now - os.path.getmtime(bpath) > 3600:
                            _shutil.rmtree(bpath)
                            logger.info(f"🗑️ Deleted stale temp folder: {bname}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not delete stale folder {bname}: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 8 — Reporter photos (24hr+)
        # ══════════════════════════════════════════════════════════════════════
        if REPORTER_PHOTO_DIR and os.path.exists(REPORTER_PHOTO_DIR):
            for fname in os.listdir(REPORTER_PHOTO_DIR):
                fpath = os.path.join(REPORTER_PHOTO_DIR, fname)
                try:
                    if (os.path.isfile(fpath) and
                            now - os.path.getmtime(fpath) > MAX_AGE_SEC):
                        _del_file(fpath)
                except Exception as e:
                    logger.warning(f"⚠️ Reporter photo check failed {fname}: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 9 — Item video cache (24hr+)
        # ══════════════════════════════════════════════════════════════════════
        if ITEM_VIDEO_CACHE_DIR and os.path.exists(ITEM_VIDEO_CACHE_DIR):
            for fname in os.listdir(ITEM_VIDEO_CACHE_DIR):
                fpath = os.path.join(ITEM_VIDEO_CACHE_DIR, fname)
                try:
                    if (os.path.isfile(fpath) and
                            now - os.path.getmtime(fpath) > MAX_AGE_SEC):
                        _del_file(fpath)
                except Exception as e:
                    logger.warning(f"⚠️ Item video cache check failed {fname}: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 10 — report_state.json (24hr+ entries remove)
        # ══════════════════════════════════════════════════════════════════════
        try:
            import report_state_manager as _rsm
            cutoff_dt = datetime.fromtimestamp(now - MAX_AGE_SEC)
            with _rsm._lock:
                data   = _rsm._load()
                before = len(data)
                pruned = {}
                for rid, entry in data.items():
                    try:
                        last = datetime.fromisoformat(
                            entry.get('last_attempt', '1970-01-01')
                        )
                        if last >= cutoff_dt:
                            pruned[rid] = entry
                    except Exception:
                        pruned[rid] = entry
                if len(pruned) < before:
                    _rsm._save(pruned)
                    logger.info(
                        f"🗑️ report_state.json: {before - len(pruned)} old entries removed"
                    )
        except Exception as e:
            logger.warning(f"⚠️ report_state.json cleanup failed: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 11 — processed_report_ids.json (live IDs se sync)
        # ══════════════════════════════════════════════════════════════════════
        try:
            global _processed_report_ids
            import report_state_manager as _rsm2
            with _rsm2._lock:
                live_data = _rsm2._load()
            live_ids = set(live_data.keys())
            _processed_report_ids = _processed_report_ids & live_ids
            with open(PROCESSED_IDS_FILE, 'w') as f:
                json.dump(list(_processed_report_ids), f)
            logger.info(
                f"🗑️ processed_report_ids.json → {len(_processed_report_ids)} active IDs"
            )
        except Exception as e:
            logger.warning(f"⚠️ processed_report_ids.json cleanup failed: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # STEP 12 — debug_report.json (24hr+ old hone par delete)
        # ══════════════════════════════════════════════════════════════════════
        debug_path = os.path.join(BASE_DIR, "debug_report.json")
        try:
            if (os.path.exists(debug_path) and
                    now - os.path.getmtime(debug_path) > MAX_AGE_SEC):
                _del_file(debug_path)
        except Exception as e:
            logger.warning(f"⚠️ debug_report.json cleanup failed: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # DONE
        # ══════════════════════════════════════════════════════════════════════
        logger.info("✅ 24-hour cleanup complete")

        try:
            open(LAST_RUN_FILE, 'w').write(str(now))
        except Exception as e:
            logger.warning(f"⚠️ Could not save .last_cleanup timestamp: {e}")

        sleep(CHECK_INTERVAL)


threading.Thread(target=cleanup_old_data_loop, daemon=True).start()


def _process_matched_background(matched: dict, sender: str):
    """
    Run heavy processing (download, Whisper, OpenAI, TTS) in a background thread
    so the webhook handler returns immediately and avoids gunicorn timeout.
    """
    try:
        result = bot._process_matched_message(matched)
        result['sender'] = sender
        if result.get('success') and result.get('headline'):
            bot.gupshup.send_message(
                sender,
                f"✅ వార్త ప్రాసెస్ అయింది!\n\n📰 {result['headline']}"
            )
            logger.info(f"✅ Background processing complete for {sender}: {result['headline'][:50]}")
        else:
            logger.error(f"❌ Background processing failed for {sender}: {result.get('error')}")
    except Exception as e:
        logger.error(f"❌ Background processing exception for {sender}: {e}", exc_info=True)


def _enqueue_report(report: dict):
    logger.info(f"📋 Report data: subject='{report.get('subject')}' message='{report.get('message')}' "
                f"videos={report.get('video_paths')} images={report.get('image_paths')} audios={report.get('audio_paths')}")
    # [DEBUG] Poora payload print karo — isse pata chalega kaunsi fields aa rahi hain

    report_id   = report.get('id')
    user_id   = report.get('userId')   # ← ADD: alag variable, clearly named
    email       = report.get('email', '')
    name        = report.get('name') or report.get('sender_name') or report.get('reporter_name') or ''
    profile_picture = report.get('profilePicture', '')
    subject     = report.get('subject', '')
    description = report.get('message', '')
    created_at = report.get('created_at', '')
    # YEH ADD KARO — locationId extract karo
    def _safe_int(val):
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    location_id      = _safe_int(report.get('location_id') or report.get('locationId') or 0)
    location_address = report.get('locationAddress') or report.get('location_address', '')
    location_name    = report.get('locationName') or report.get('location_name', '')

    logger.info(f"📋 [DEBUG] Full report payload keys: {list(report.keys())}")
    logger.info(f"📋 [DEBUG] name='{report.get('name')}' | email='{report.get('email')}' | sender_name='{name}'")
    logger.info(f"📋 [DEBUG] report_id='{report_id}' | user_id='{user_id}'")

    def _to_list(val):
        if isinstance(val, list): return val
        if val: return [val]
        return []

    def _make_full_url(path: str) -> str:
        """Relative path (uploads/images/...) ko full URL mein convert karo"""
        if path.startswith('http://') or path.startswith('https://'):
            return path  # already full URL
        return f"{API_BASE_URL}/{path.lstrip('/')}"
    
    video_paths = _to_list(report.get('video_paths') or report.get('video_path'))
    image_paths = _to_list(report.get('image_paths') or report.get('image_path'))
    audio_paths = _to_list(report.get('audio_paths') or report.get('audio_path'))

    sender = email or f"report_{report_id}"
    text   = f"{subject}\n\n{description}".strip()

    # ── Multi-media report (multiple videos/images/audios) ────────────────────
    # Bypass the single-media queue and process directly as a multi-media item
    has_multi = (len(video_paths) + len(image_paths) + len(audio_paths)) > 1
    has_any   = video_paths or image_paths or audio_paths

    if has_multi or has_any:
        logger.info(f"🗂️ Multi-media report: {len(video_paths)} videos, {len(image_paths)} images, {len(audio_paths)} audios")
        import report_state_manager as _rsm
        _rsm.mark_processing(report_id, original_report=report)
        threading.Thread(
            target=_process_multi_media_report_background,
            args=(text, video_paths, image_paths, audio_paths, sender, report_id, email, name, profile_picture, location_id, location_address, location_name, user_id, created_at),
            daemon=True
        ).start()
        return

    # ── Fallback: text-only report ────────────────────────────────────────────
    if text:
        matched = bot.message_queue.add_message(
            sender=sender,
            message_type='text',
            data={'text': text},
            message_id=report_id
        )
        if matched and not matched.get('duplicate'):
            threading.Thread(
                target=_process_report_background,
                args=(matched, sender, report_id, email),
                daemon=True
            ).start()

@app.route('/api/media/<path:filepath>')
def serve_media(filepath):
    from config import BASE_OUTPUT_DIR, BASE_INPUT_DIR
    
    outputs_path = os.path.join(BASE_OUTPUT_DIR, filepath)
    inputs_path = os.path.join(BASE_INPUT_DIR, filepath)
    
    # If it's a directory (e.g. segments folder), return JSON listing of files with URLs
    for base, base_dir in [(BASE_OUTPUT_DIR, outputs_path), (BASE_INPUT_DIR, inputs_path)]:
        if os.path.isdir(base_dir):
            from config import API_BASE_URL
            files = []
            for fname in sorted(os.listdir(base_dir)):
                fpath = os.path.join(base_dir, fname)
                if os.path.isfile(fpath):
                    files.append({
                        'name': fname,
                        'url': f"{API_BASE_URL}/api/media/{filepath}/{fname}",
                        'size': os.path.getsize(fpath)
                    })
            return jsonify({'segments': files, 'path': filepath}), 200

    if os.path.exists(outputs_path):
        return send_from_directory(BASE_OUTPUT_DIR, filepath)
    elif os.path.exists(inputs_path):
        return send_from_directory(BASE_INPUT_DIR, filepath)
    else:
        return {'error': 'File not found'}, 404

##### ── 08-04-15-43 ────────────────────────────────────────────────────

_local_incidents: list = []

@app.route('/api/feed', methods=['POST'])
def local_incident_post():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'status': 'error', 'message': 'Empty payload'}), 400
    from event_logger import save_incident
    save_incident(data)
    logger.info(f"📥 Local incident stored: {data.get('title','?')}")
    return jsonify({'status': 'ok'}), 201

@app.route('/api/feed', methods=['GET'])
def local_incident_get():
    import sqlite3
    import os
    
    try:
        # Database path
        db_path = os.path.join(os.path.dirname(__file__), 'item_events.db')
        
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        offset = (page - 1) * limit
        
        # Connect to database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get total count
        cursor.execute("SELECT COUNT(*) as total FROM incidents")
        total_row = cursor.fetchone()
        total = total_row['total'] if total_row else 0
        
        # Get paginated data
        cursor.execute("""
            SELECT * FROM incidents 
            ORDER BY received_at DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        rows = cursor.fetchall()
        data = []
        for row in rows:
            data.append({
                'id': row['id'],
                'incident_id': row['incident_id'],
                'title': row['title'],
                'description': row['description'],
                'category_id': row['category_id'],
                'location_id': row['location_id'],
                'post_location': row['post_location'],
                'user_id': row['user_id'],
                'timestamp': row['timestamp'],
                'cover_image_path': row['cover_image_path'],
                'video_path': row['video_path'],
                'segments_path': row['segments_path'],
                'counter': row['counter'],
                'received_at': row['received_at']
            })
        
        conn.close()
        
        return jsonify({
            'status': 'ok',
            'total': total,
            'page': page,
            'limit': limit,
            'data': data
        }), 200
        
    except Exception as e:
        logger.error(f"GET API Error: {e}")
        import traceback
        traceback.print_exc()  # This will print full error in console
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

##### ── 08-04-15-43 ────────────────────────────────────────────────────

def _process_multi_media_report_background(text: str, video_paths: list, image_paths: list,
                                            audio_paths: list, sender: str, report_id: str, email: str, name, profile_picture='', location_id=0, location_address='', location_name='', user_id='', created_at=''):
    import report_state_manager as _rsm
    _TTS_SEMAPHORE.acquire()
    try:
        logger.info(f"🔄 Processing multi-media report {report_id}")
        result = bot.process_multi_media_report(
            text=text,
            video_paths=video_paths,
            image_paths=image_paths,
            audio_paths=audio_paths,
            sender=sender,
            sender_name=name,
            report_id=report_id,
            sender_photo=profile_picture,
            location_id=location_id,
            location_address=location_address,
            location_name=location_name,
            user_id=user_id,
            created_at=created_at,
        )
        if result.get('success') and result.get('headline'):
            logger.info(f"✅ Multi-media report {report_id}: {result['headline'][:50]}")
        else:
            err = result.get('error', 'unknown error')
            logger.error(f"❌ Multi-media report {report_id} failed: {err}")
            _rsm.mark_failed(report_id, reason=err)
    except Exception as e:
        logger.error(f"❌ Multi-media report background error: {e}", exc_info=True)
        try:
            import report_state_manager as _rsm2
            _rsm2.mark_failed(report_id, reason=str(e))
        except Exception:
            pass
    finally:
        _TTS_SEMAPHORE.release()


def _process_report_background(matched: dict, sender: str, report_id: str, email: str):
    try:
        logger.info(f"🔄 Processing report {report_id}")
        result = bot._process_matched_message(matched)
        
        if result.get('success') and result.get('headline'):
            logger.info(f"✅ Report {report_id}: {result['headline'][:50]}")
            # Optional email notification here
        else:
            logger.error(f"❌ Report {report_id} failed: {result.get('error')}")
    except Exception as e:
        logger.error(f"❌ Report background error: {e}", exc_info=True)

    

def _process_batch_background(batch_items: list, batch_id: str):
    """
    Process multiple media items in parallel, then trigger bulletin build.
    batch_items: list of dicts with keys: text, media_type, media_url
    """
    import concurrent.futures

    logger.info(f"🗂️ Batch {batch_id}: processing {len(batch_items)} items...")
    results = []

    def _process_one(item_data):
        idx        = item_data['idx']
        text       = item_data.get('text')
        media_url  = item_data.get('media_url')
        media_type = item_data.get('media_type')  # 'image' | 'video' | 'audio'

        media_path = None
        try:
            if media_url:
                ext_map = {'image': '.jpg', 'video': '.mp4', 'audio': '.mp3'}
                ext     = ext_map.get(media_type, '.bin')
                tmp     = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                tmp.close()
                if bot.gupshup.download_media(media_url, tmp.name):
                    media_path = tmp.name
                else:
                    os.unlink(tmp.name)
                    logger.warning(f"  ⚠️ Batch item {idx}: download failed")

            result = bot.process_message(
                text=text,
                media_path=media_path,
                sender=f"batch_{batch_id}_{idx}",
            )
            if result.get('success'):
                logger.info(f"  ✅ Batch item {idx} done: {result.get('headline','')[:50]}")
            else:
                logger.warning(f"  ⚠️ Batch item {idx} failed: {result.get('error')}")
            return result
        except Exception as e:
            logger.error(f"  ❌ Batch item {idx} exception: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            if media_path and os.path.exists(media_path):
                try:
                    os.unlink(media_path)
                except Exception:
                    pass

    # Process all items in parallel (up to 3 at once)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_process_one, item): item for item in batch_items}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    success_count = sum(1 for r in results if r.get('success'))
    logger.info(f"🗂️ Batch {batch_id}: {success_count}/{len(batch_items)} items processed — triggering bulletin build")

    # Trigger bulletin build immediately after batch is done
    threading.Thread(target=_run_planner, daemon=True).start()


@app.route('/api/webhooks/batch', methods=['POST'])
def receive_batch_webhook():
    """
    Accept a batch of up to 3 news items in one request and process them
    together into a single bulletin.

    Expected JSON body:
    {
        "items": [
            {
                "text":       "Optional caption / context",
                "media_url":  "https://...",        // optional
                "media_type": "image"|"video"|"audio"  // required if media_url present
            },
            ...  (max 3)
        ]
    }
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'status': 'error', 'message': 'Empty payload'}), 400

        raw_items = data.get('items', [])
        if not raw_items:
            return jsonify({'status': 'error', 'message': 'No items provided'}), 400

        # Enforce max 3
        raw_items = raw_items[:3]

        # Validate each item has at least text or media_url
        batch_items = []
        for i, item in enumerate(raw_items):
            text      = (item.get('text') or '').strip()
            media_url = (item.get('media_url') or '').strip()
            media_type = (item.get('media_type') or '').strip().lower()

            if not text and not media_url:
                return jsonify({
                    'status': 'error',
                    'message': f'Item {i+1} has neither text nor media_url'
                }), 400

            if media_url and media_type not in ('image', 'video', 'audio'):
                return jsonify({
                    'status': 'error',
                    'message': f'Item {i+1}: media_type must be image, video, or audio'
                }), 400

            batch_items.append({
                'idx':        i + 1,
                'text':       text or None,
                'media_url':  media_url or None,
                'media_type': media_type or None,
            })

        batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        logger.info(f"📦 Batch {batch_id}: {len(batch_items)} item(s) received")

        threading.Thread(
            target=_process_batch_background,
            args=(batch_items, batch_id),
            daemon=True
        ).start()

        return jsonify({
            'status':    'processing',
            'batch_id':  batch_id,
            'item_count': len(batch_items),
            'message':   f'{len(batch_items)} items queued for processing'
        }), 200

    except Exception as e:
        logger.error(f"❌ Batch webhook error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500



@app.route('/api/webhooks/reports', methods=['POST'])
def receive_report_webhook():
    try:
        logger.info("📨 Report webhook received")
        report_data = request.get_json(silent=True)

        if not report_data:
            return jsonify({'status': 'error', 'message': 'Empty payload'}), 400

        # Delegate directly to _enqueue_report — same logic as batch webhook
        _enqueue_report(report_data)

        report_id = report_data.get('userId') or str(time.time())
        return jsonify({'status': 'processing', 'report_id': report_id}), 200

    except Exception as e:
        logger.error(f"❌ Report webhook error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/', methods=['GET', 'POST'])
@app.route('/webhook', methods=['GET', 'POST'])
@app.route('/gupshup/webhook', methods=['GET', 'POST'])
@app.route('/whatsapp/webhook', methods=['GET', 'POST'])
def webhook():
    try:
        logger.info(f"📨 Webhook received: {request.method}")
        logger.info(f"📨 Content-Type: {request.content_type}")
        
        webhook_data = request.get_json(silent=True)
        
        if not webhook_data:
            logger.warning(f"⚠️ Empty/invalid JSON body")
            return jsonify({'status': 'acknowledged'}), 200

        logger.info(f"📨 Parsed successfully, processing...")

        if webhook_data.get('type') == 'user-event':
            payload = webhook_data.get('payload', {})
            if payload.get('type') == 'sandbox-start':
                logger.info("✅ Gupshup sandbox webhook acknowledged")
                return jsonify({'status': 'success'}), 200

        if 'entry' not in webhook_data and webhook_data.get('type') not in ['message-event', 'user-event', 'message']:
            return jsonify({'status': 'acknowledged'}), 200

        # Parse message and check queue — this is fast (no API calls)
        result = bot.process_gupshup_webhook_queue_only(webhook_data)

        if result.get('waiting'):
            logger.info("⏳ Waiting for matching message...")
            return jsonify({'status': 'waiting'}), 200

        if result.get('duplicate'):
            logger.info("⭕ Duplicate, skipping")
            return jsonify({'status': 'duplicate'}), 200

        if result.get('matched'):
            # Heavy processing (download, transcribe, TTS) — run in background thread
            matched = result['matched']
            sender  = result.get('sender', '')
            logger.info(f"✅ Matched — processing in background for {sender}")
            threading.Thread(
                target=_process_matched_background,
                args=(matched, sender),
                daemon=True
            ).start()
            return jsonify({'status': 'processing'}), 200

        if webhook_data.get('type') == 'user-event':
            return jsonify({'status': 'success'}), 200

        logger.error(f"❌ Failed: {result.get('error')}")
        return jsonify({'status': 'error', 'error': result.get('error')}), 400

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        logger.exception("Full traceback:")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)




