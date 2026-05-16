# import math
# import os
# import json
# import shutil
# import subprocess
# import time
# from datetime import datetime
# from typing import List, Dict, Optional
# from config import (
#     OUTPUT_HEADLINE_DIR,
#     OUTPUT_AUDIO_DIR,
#     OUTPUT_SCRIPT_DIR,
#     BASE_OUTPUT_DIR,
#     BASE_DIR,
#     INTRO_VIDEO_DURATION, BREAK_DURATION,
#     ADDRESS_GIF_PATH,
#     ITEM_VIDEO_CACHE_DIR,
# )

# import threading
# _metadata_lock = threading.Lock()

# METADATA_FILE = os.path.join(BASE_OUTPUT_DIR, 'metadata.json')
# BULLETINS_DIR = os.path.join(BASE_OUTPUT_DIR, 'bulletins')

# PRIORITY_RANK = {
#     'breaking': 0,
#     'urgent':   1,
#     'normal':   2,
# }

# def _load_ticker_cursor() -> float:
#     """Global ticker cursor load karo CloudSQL se — midnight pe auto-reset."""
#     try:
#         import db as _db
#         raw = _db.get_state('ticker_cursor')
#         if not raw:
#             return 0.0
#         state = json.loads(raw)
#         saved_date = state.get('date', '')
#         today = datetime.now().strftime('%Y-%m-%d')
#         if saved_date != today:
#             print(f"🔄 Ticker cursor reset — new day ({saved_date} → {today})")
#             return 0.0
#         return float(state.get('cursor', 0.0))
#     except Exception as e:
#         print(f"⚠️ ticker_cursor load error: {e}")
#         return 0.0


# def _save_ticker_cursor(val: float):
#     """Global ticker cursor CloudSQL mein persist karo."""
#     try:
#         import db as _db
#         _db.set_state('ticker_cursor', json.dumps({
#             'cursor':     round(val, 3),
#             'date':       datetime.now().strftime('%Y-%m-%d'),
#             'updated_at': datetime.now().isoformat(),
#         }))
#     except Exception as e:
#         print(f"❌ ticker_state save error: {e}")

# CLIP_MAX = 20  # max clip duration to consider for allocation (in seconds)

# # def load_metadata() -> List[Dict]:
# #     if not os.path.exists(METADATA_FILE):
# #         return []
# #     try:
# #         with open(METADATA_FILE, 'r', encoding='utf-8') as f:
# #             return json.load(f)
# #     except Exception as e:
# #         print(f"❌ Error loading metadata: {e}")
# #         return []

# def load_metadata() -> List[Dict]:
#     try:
#         import db as _db
#         rows = _db.fetchall("SELECT * FROM news_items ORDER BY counter ASC")
#         for r in rows:
#             for k in ('multi_image_paths', 'multi_video_paths'):
#                 v = r.get(k)
#                 if isinstance(v, str):
#                     try:
#                         r[k] = json.loads(v)
#                     except Exception:
#                         r[k] = []
#         return rows
#     except Exception as e:
#         print(f"❌ Error loading news_items from DB: {e}")
#         return []


# # def save_metadata(items: List[Dict]):
# #     os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)
# #     try:
# #         with open(METADATA_FILE, 'w', encoding='utf-8') as f:
# #             json.dump(items, f, ensure_ascii=False, indent=2)
# #     except Exception as e:
# #         print(f"❌ Error saving metadata: {e}")

# def save_metadata(items: List[Dict]):
#     """Update mutable fields of existing news_items rows in DB."""
#     import db as _db
#     for item in items:
#         counter = item.get('counter')
#         if counter is None:
#             continue
#         _db.execute("""
#             UPDATE news_items SET
#                 used_count        = %s,
#                 next_bulletin     = %s,
#                 bulletined        = %s,
#                 priority          = COALESCE(%s, priority),
#                 item_video_local  = %s,
#                 incident_id       = %s,
#                 script_duration   = %s,
#                 headline_duration = %s,
#                 total_duration    = %s
#             WHERE counter = %s
#         """, (
#             item.get('used_count', 0),
#             1 if item.get('next_bulletin') else 0,
#             1 if item.get('bulletined') else 0,
#             item.get('priority'),
#             item.get('item_video_local'),
#             item.get('incident_id'),
#             item.get('script_duration', 0.0),
#             item.get('headline_duration', 0.0),
#             item.get('total_duration', 0.0),
#             counter,
#         ))


# def delete_news_items(counters: list):
#     """Delete news_items rows by counter list (used by cleanup loop)."""
#     import db as _db
#     if not counters:
#         return
#     _db.execute("DELETE FROM news_items WHERE counter = ANY(%s)", (list(counters),))


# # def append_news_item(item: Dict):
# #     with _metadata_lock:
# #         items = load_metadata()
# #         items.append(item)
# #         save_metadata(items)
# #     print(f"✅ Metadata saved for item {item.get('counter')} [{item.get('priority')}]")
# #
# #     from event_logger import log_event
# #     log_event(
# #         event      = 'bulletin_added',
# #         counter    = item.get('counter'),
# #         media_type = item.get('media_type'),
# #     )

# def append_news_item(item: Dict):
#     import db as _db
#     multi_images = item.get('multi_image_paths', [])
#     if isinstance(multi_images, list):
#         multi_images = json.dumps(multi_images, ensure_ascii=False)

#     _db.execute("""
#         INSERT INTO news_items (
#             counter, media_type, priority,
#             sender, sender_name, sender_photo,
#             timestamp, headline, script_filename,
#             headline_audio, script_audio,
#             intro_audio_filename, analysis_audio_filename,
#             headline_duration, script_duration, total_duration, allocated_duration,
#             clip_structure, clip_start, clip_end, clip_video_path,
#             location_id, location_name,
#             user_id, original_text,
#             intro_script, analysis_script,
#             multi_image_paths,
#             used_count, bulletined, next_bulletin,
#             s3_key_input, s3_key_script_audio, s3_key_headline_audio,
#             storage_key, item_manifest
#         ) VALUES (
#             %s, %s, %s,
#             %s, %s, %s,
#             %s, %s, %s,
#             %s, %s,
#             %s, %s,
#             %s, %s, %s, %s,
#             %s, %s, %s, %s,
#             %s, %s,
#             %s, %s,
#             %s, %s,
#             %s,
#             %s, %s, %s,
#             %s, %s, %s,
#             %s, %s
#         ) ON CONFLICT (counter, media_type) DO UPDATE SET
#             priority                = EXCLUDED.priority,
#             headline                = EXCLUDED.headline,
#             script_audio            = EXCLUDED.script_audio,
#             script_duration         = EXCLUDED.script_duration,
#             headline_duration       = EXCLUDED.headline_duration,
#             total_duration          = EXCLUDED.total_duration,
#             clip_structure          = EXCLUDED.clip_structure,
#             clip_start              = EXCLUDED.clip_start,
#             clip_end                = EXCLUDED.clip_end,
#             clip_video_path         = EXCLUDED.clip_video_path,
#             intro_audio_filename    = EXCLUDED.intro_audio_filename,
#             analysis_audio_filename = EXCLUDED.analysis_audio_filename,
#             intro_script            = EXCLUDED.intro_script,
#             analysis_script         = EXCLUDED.analysis_script,
#             multi_image_paths       = EXCLUDED.multi_image_paths,
#             original_text           = EXCLUDED.original_text,
#             location_id             = EXCLUDED.location_id,
#             location_name           = EXCLUDED.location_name,
#             sender_photo            = EXCLUDED.sender_photo
#     """, (
#         item.get('counter'),
#         item.get('media_type', 'video'),
#         item.get('priority', 'normal'),
#         item.get('sender', item.get('sender_name', '')),
#         item.get('sender_name', ''),
#         item.get('sender_photo', ''),
#         item.get('timestamp', item.get('created_at', datetime.now().isoformat())),
#         item.get('headline', ''),
#         item.get('script_filename', ''),
#         item.get('headline_audio', ''),
#         item.get('script_audio', ''),
#         item.get('intro_audio_filename'),
#         item.get('analysis_audio_filename'),
#         float(item.get('headline_duration', 0.0)),
#         float(item.get('script_duration', 0.0)),
#         float(item.get('total_duration', 0.0)),
#         float(item.get('allocated_duration', 0.0)),
#         item.get('clip_structure'),
#         item.get('clip_start'),
#         item.get('clip_end'),
#         item.get('clip_video_path'),
#         item.get('location_id', 0),
#         item.get('location_name', ''),
#         item.get('user_id', ''),
#         item.get('original_text', ''),
#         item.get('intro_script', ''),
#         item.get('analysis_script', ''),
#         multi_images,
#         0,
#         0,
#         0,
#         item.get('s3_key_input'),
#         item.get('s3_key_script_audio'),
#         item.get('s3_key_headline_audio'),
#         item.get('storage_key'),
#         item.get('item_manifest'),
#     ))
#     print(f"✅ DB: news_item inserted counter={item.get('counter')} [{item.get('priority')}]")

#     from event_logger import log_event
#     log_event(
#         event      = 'bulletin_added',
#         counter    = item.get('counter'),
#         media_type = item.get('media_type'),
#     )


# # def rank_news_items(items: List[Dict]) -> List[Dict]:
# #     def sort_key(item):
# #         priority = PRIORITY_RANK.get(item.get('priority', 'normal').lower(), 2)
# #         used     = item.get('used_count', 0)
# #         dur      = float(item.get('total_duration', 999))
# #         try:
# #             ts = datetime.fromisoformat(item.get('timestamp', '1970-01-01T00:00:00')).timestamp()
# #         except Exception:
# #             ts = 0
# #         return (priority, used, dur, -ts)

# #     return sorted(items, key=sort_key)

# def rank_news_items(items: List[Dict]) -> List[Dict]:
#     """
#     Priority order:
#     1. breaking/urgent pehle
#     2. Unused items pehle (used_count == 0)
#     3. Nayi items pehle (timestamp descending) — yahi main fix hai
#     4. Choti duration pehle (budget fit hone ke liye)
#     """
#     def sort_key(item):
#         priority = PRIORITY_RANK.get(item.get('priority', 'normal').lower(), 2)
#         used     = item.get('used_count', 0)
#         try:
#             ts = datetime.fromisoformat(item.get('timestamp', '1970-01-01T00:00:00')).timestamp()
#         except Exception:
#             ts = 0
#         dur = float(item.get('total_duration', 999))
#         return (priority, used, -ts, dur)  # -ts = newest first

#     return sorted(items, key=sort_key)


# def _safe_rmtree(path: str, retries: int = 5, delay: float = 2.0):
#     for attempt in range(retries):
#         try:
#             shutil.rmtree(path)
#             return True
#         except PermissionError:
#             if attempt < retries - 1:
#                 print(f"⏳ Folder in use, retrying ({attempt + 1}/{retries})...")
#                 time.sleep(delay)
#             else:
#                 print("⚠️ Could not fully delete old folder — proceeding anyway")
#                 shutil.rmtree(path, ignore_errors=True)
#                 return True
#     return True


# _LOCATION_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.location_channel_cache.json')
# _CHANNELS = ["Karimnagar", "Khammam", "Kurnool", "Anatpur", "Kakinada", "Nalore", "Tirupati",
#              "Guntur", "Warangal", "Nalgonda"]

# def classify_location_to_channel(location_names: list) -> dict:
#     """Use OpenAI to map raw location_name strings to one of 7 channels. Kurnool is default."""
#     import json
#     from openai import OpenAI
#     from config import OPENAI_API_KEY

#     cache = {}
#     if os.path.exists(_LOCATION_CACHE_FILE):
#         with open(_LOCATION_CACHE_FILE, 'r') as f:
#             cache = json.load(f)

#     uncached = [n for n in location_names if n not in cache]
#     if uncached:
#         client = OpenAI(api_key=OPENAI_API_KEY)
#         prompt = (
#             f"Map each location name to exactly one of these channels: {_CHANNELS}. "
#             f"If unsure or no match, assign 'Kurnool'. "
#             f"Return ONLY a JSON object like {{\"loc_name\": \"Channel\"}}.\n\n"
#             f"Locations: {uncached}"
#         )
#         resp = client.chat.completions.create(
#             model="gpt-4o-mini",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0,
#         )
#         try:
#             raw = resp.choices[0].message.content.strip()
#             # strip markdown code fences if present
#             if raw.startswith('```'):
#                 raw = raw.split('```')[1]
#                 if raw.startswith('json'):
#                     raw = raw[4:]
#                 raw = raw.strip()
#             mapping = json.loads(raw)
#             cache.update(mapping)
#             with open(_LOCATION_CACHE_FILE, 'w') as f:
#                 json.dump(cache, f, indent=2)
#         except Exception as e:
#             print(f"⚠️ Location classify failed: {e} — defaulting all to Kurnool")
#             for n in uncached:
#                 cache[n] = "Kurnool"

#     return {n: cache.get(n, "Kurnool") for n in location_names}


# # def build_all_location_bulletins(duration_minutes: int) -> dict:
# #     """Metadata se sabhi unique locations detect karke har ek ka bulletin banao."""
# #     from datetime import datetime, timedelta, timezone
# #     all_items = load_metadata()

# #     _cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
# #     def _in_24hr(item):
# #         ts_str = item.get('created_at') or item.get('timestamp', '')
# #         try:
# #             ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
# #             if ts.tzinfo is None:
# #                 ts = ts.replace(tzinfo=timezone.utc)
# #             return ts >= _cutoff
# #         except Exception:
# #             return True
# #     all_items = [i for i in all_items if _in_24hr(i)]

# #     if not all_items:
# #         print("❌ No items in metadata")
# #         return {}

# #     results = {}
# #     path = build_bulletin(duration_minutes)
# #     results['all'] = {'location_name': 'All', 'path': path}
# #     return results

# def build_all_location_bulletins(duration_minutes: int) -> dict:
#     """Metadata se sabhi unique locations detect karke har ek ka bulletin banao."""
#     from datetime import datetime, timedelta, timezone
#     all_items = load_metadata()

#     _cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
#     def _in_24hr(item):
#         ts_str = item.get('created_at') or item.get('timestamp', '')
#         try:
#             ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
#             if ts.tzinfo is None:
#                 ts = ts.replace(tzinfo=timezone.utc)
#             return ts >= _cutoff
#         except Exception:
#             return True
#     all_items = [i for i in all_items if _in_24hr(i)]

#     if not all_items:
#         print("❌ No items in metadata")
#         return {}

#     # # Unique locations collect karo
#     # unique_locs = {}
#     # for item in all_items:
#     #     lid = item.get('location_id')
#     #     lname = item.get('location_name', '')
#     #     if lid and lname:
#     #         unique_locs[str(lid)] = lname

#     # print(f"🌍 Found {len(unique_locs)} unique locations: {list(unique_locs.values())}")

#     # results = {}
#     # for loc_id, loc_name in unique_locs.items():
#     #     print(f"\n{'='*60}\n🏗️  Building bulletin for [{loc_id}] {loc_name}\n{'='*60}")
#     #     path = build_bulletin(duration_minutes, location_id=loc_id, location_name=loc_name)
#     #     if path:
#     #         results[loc_id] = {'location_name': loc_name, 'path': path}

#     # return results

#     # Collect unique raw location names
#     raw_location_names = list({
#         item.get('location_name', '')
#         for item in all_items
#         if item.get('location_name', '')
#     })

#     # OpenAI classify → one of 3 canonical channels
#     loc_to_channel = classify_location_to_channel(raw_location_names)
#     print(f"🗺️  Location mapping: {loc_to_channel}")

#     # Bucket items by channel
#     KNOWN_CHANNELS = {"Karimnagar", "Khammam", "Kurnool",
#                       "Anatpur", "Kakinada", "Nalore", "Tirupati",
#                       "Guntur", "Warangal", "Nalgonda"}
#     channel_items  = {ch: [] for ch in KNOWN_CHANNELS}
#     general_items  = []  # items that don't match any of the 7 channels

#     for item in all_items:
#         raw     = item.get('location_name', '')
#         channel = loc_to_channel.get(raw)
#         if channel and channel in KNOWN_CHANNELS:
#             channel_items[channel].append(item)
#         else:
#             general_items.append(item)

#     if general_items:
#         print(f"🌐 {len(general_items)} general items (no location match)")

#     results = {}
#     for channel_name, items in channel_items.items():
#         if items:
#             # Channel ke apne items hain — sirf wahi use karo
#             use_items = items
#             print(f"\n{'='*60}\n🏗️  Building bulletin for {channel_name} ({len(items)} own items)\n{'='*60}")
#         elif general_items:
#             # Apne items nahi hain — general items fallback ke roop me use karo
#             use_items = general_items
#             print(f"\n{'='*60}\n🏗️  Building bulletin for {channel_name} (no own items — using {len(general_items)} general items)\n{'='*60}")
#         else:
#             print(f"⚠️ No items for {channel_name}, skipping")
#             continue
#         path = build_bulletin(duration_minutes, location_name=channel_name, _items_override=use_items)
#         if path:
#             results[channel_name] = {'location_name': channel_name, 'path': path}

#     return results


# # def build_bulletin(duration_minutes: int, location_id: int = None, location_name: str = None) -> Optional[str]:
# def build_bulletin(duration_minutes: int, location_id: int = None, location_name: str = None, _items_override: list = None) -> Optional[str]:
#     all_items = load_metadata()

#     if _items_override is not None:
#         all_items = _items_override

#     if not all_items:
#         print("❌ No news items found in metadata.json")
#         return None

#     # Validate items — both audio files must exist
#     # EXCLUDE items marked for next bulletin (they were skipped before)
#     import s3_storage as _s3
#     valid_items = []
#     for item in all_items:
#         if item.get('next_bulletin'):
#             continue  # Skip items reserved for next bulletin
#         headline_audio = item.get('headline_audio', '')
#         script_audio   = item.get('script_audio', '')
#         ha_path = os.path.join(OUTPUT_HEADLINE_DIR, headline_audio)
#         sa_path = os.path.join(OUTPUT_AUDIO_DIR,    script_audio)

#         # S3 fallback — download missing audio files before validation
#         if headline_audio and not os.path.exists(ha_path):
#             _s3.ensure_local(ha_path, _s3.key_for_audio(headline_audio))
#         if script_audio and not os.path.exists(sa_path):
#             _s3.ensure_local(sa_path, _s3.key_for_audio(script_audio))

#         if headline_audio and script_audio and os.path.exists(ha_path) and os.path.exists(sa_path):
#             valid_items.append(item)
#         else:
#             print(f"⚠️ Skipping item {item.get('counter')} — audio files missing: headline_audio='{headline_audio}' exists={os.path.exists(ha_path)} | script_audio='{script_audio}' exists={os.path.exists(sa_path)}")

#     # ── Location filter ───────────────────────────────────────────────────────
#     if location_id is not None:
#         valid_items = [
#             i for i in valid_items
#             if str(i.get('location_id', '')) == str(location_id)
#         ]
#         if not valid_items:
#             print(f"❌ No items for location_id={location_id} ({location_name})")
#             return None
#         print(f"📍 Filtered {len(valid_items)} items for [{location_id}] {location_name}")


#     if not valid_items:
#         print("❌ No valid items with audio files found")
#         return None

#     # ranked    = rank_news_items(valid_items)
#     # Pending-first: agar enough unused items hain to old skip
#     unused_items = [x for x in valid_items if x.get('used_count', 0) == 0]
#     MIN_ITEMS_THRESHOLD = 8

#     if len(unused_items) >= MIN_ITEMS_THRESHOLD:
#         ranked = rank_news_items(unused_items)
#         print(f"  [RANK] {len(unused_items)} unused items — old items skipped")
#     else:
#         ranked = rank_news_items(valid_items)
#         print(f"  [RANK] Only {len(unused_items)} unused — mixing with old items")

#     intro_dur = INTRO_VIDEO_DURATION

#     # ── Pre-fetch WhoisWho (S3) + Ad clips (S3) ──────────────────────────────
#     from s3_bulletin_fetcher import fetch_whoiswho_bulletin, fetch_ad_clips

#     _whoiswho_clip = fetch_whoiswho_bulletin()           # S3 se 1-min clip
#     _ad_clips_pool = fetch_ad_clips()                    # S3 se ads pool
#     _ad_clips = _ad_clips_pool[:4]                       # initial 4
#     _ad_reserve = _ad_clips_pool[4:10]

#     def _quick_dur(path: str) -> float:
#         try:
#             r = subprocess.run(
#                 ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
#                  '-of', 'default=noprint_wrappers=1:nokey=1', path],
#                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#             return float(r.stdout.decode().strip())
#         except Exception:
#             return 0.0

#     # _whoiswho_dur  = _quick_dur(_whoiswho_clip) if (_whoiswho_clip and os.path.exists(_whoiswho_clip)) else 0.0
#     # _ad_durations  = [_quick_dur(ac) for ac in _ad_clips if ac and os.path.exists(ac)]
#     # _ad_total_dur  = sum(_ad_durations)
#     from config import S3_INJECT_LOCAL_DIR

#     def _effective_dur(original_path: str) -> float:
#         reenc_filename = os.path.basename(original_path).replace('.mp4', '_reenc.mp4')
#         reenc_path     = os.path.join(S3_INJECT_LOCAL_DIR, reenc_filename)
#         if (os.path.exists(reenc_path) and
#                 os.path.getsize(reenc_path) > 100_000 and
#                 os.path.getmtime(original_path) <= os.path.getmtime(reenc_path)):
#             return _quick_dur(reenc_path)
#         return _quick_dur(original_path)

#     _whoiswho_dur  = _effective_dur(_whoiswho_clip) if (_whoiswho_clip and os.path.exists(_whoiswho_clip)) else 0.0
#     _ad_durations  = [_effective_dur(ac) for ac in _ad_clips if ac and os.path.exists(ac)]
#     _ad_total_dur  = sum(_ad_durations)

#     # ── Injections list: whoiswho pehle, phir ads ────────────────────────────
#     _injections = []
#     if _whoiswho_clip and _whoiswho_dur > 0:
#         _injections.append({'path': _whoiswho_clip, 'duration': _whoiswho_dur, 'label': 'whoiswho'})
#     for _i, (ac, ad_dur) in enumerate(zip(_ad_clips, _ad_durations)):
#         if ac and ad_dur > 0:
#             _injections.append({'path': ac, 'duration': ad_dur, 'label': f'ad_{_i+1}'})

#     # 🆕 Shuffle taaki whoiswho aur ads ka order bulletin-to-bulletin different ho
#     import random as _random
#     _random.shuffle(_injections)
#     # ── NEWS budget = TOTAL - injections (injections ka break NAHI hoga) ─────
#     TARGET = duration_minutes * 60 - _whoiswho_dur - _ad_total_dur - 5
#     print(f"  [BUDGET] total={duration_minutes*60}s | whoiswho={_whoiswho_dur:.1f}s | "
#           f"ads={_ad_total_dur:.1f}s ({len(_ad_clips)} clips) | "
#           f"{len(_injections)} injections → news TARGET={TARGET:.1f}s")

#     # ─── Step 1: Ensure total_duration is set on every item ──────────────────
#     def _audio_dur(path: str) -> float:
#         try:
#             r = subprocess.run(
#                 ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
#                  '-of', 'default=noprint_wrappers=1:nokey=1', path],
#                 stdout=subprocess.PIPE, stderr=subprocess.PIPE
#             )
#             return float(r.stdout.decode().strip())
#         except Exception:
#             return 0.0

#     for item in ranked:
#         intro_name    = item.get('intro_audio_filename', '')
#         analysis_name = item.get('analysis_audio_filename', '')
#         has_clip_item = bool(
#             item.get('clip_structure') and
#             item.get('clip_start') is not None and
#             item.get('clip_end') is not None and
#             intro_name
#         )

#         if has_clip_item:
#             clip_dur = min(
#                 float(item['clip_end']) - float(item['clip_start']),
#                 CLIP_MAX
#             )
#             intro_path_f    = os.path.join(OUTPUT_AUDIO_DIR, intro_name)
#             analysis_path_f = os.path.join(OUTPUT_AUDIO_DIR, analysis_name) if analysis_name else None

#             intro_dur_actual    = _audio_dur(intro_path_f)    if os.path.exists(intro_path_f)    else float(item.get('script_duration', 0.0)) * 0.5
#             analysis_dur_actual = _audio_dur(analysis_path_f) if (analysis_path_f and os.path.exists(analysis_path_f)) else 0.0

#             item['total_duration'] = (
#                 float(item.get('headline_duration', 0.0)) +
#                 intro_dur_actual +
#                 clip_dur +
#                 analysis_dur_actual
#             )
#         elif not item.get('total_duration'):
#             item['total_duration'] = (
#                 float(item.get('headline_duration', 0.0)) +
#                 float(item.get('script_duration',   0.0))
#             )

#     # ── Smart greedy selection ─────────────────────────────────────────────────
#     selected   = []
#     skipped    = []
#     used       = 0.0
#     cur_budget = TARGET - intro_dur

#     # Break overhead — sirf news items ke liye (injections ka break nahi)
#     def _break_overhead(n: int) -> float:
#         if n == 0:
#             return 0.0
#         intro_break = 1
#         hl_breaks   = max(0, n - 1)
#         news_breaks = max(0, n - 1)
#         return (intro_break + hl_breaks + news_breaks) * BREAK_DURATION

#     for item in ranked:
#         candidate_break_overhead = _break_overhead(len(selected) + 1)
#         effective_budget         = TARGET - intro_dur - candidate_break_overhead
#         item_total               = float(item['total_duration'])

#         if used + item_total <= effective_budget:
#             gap_after    = effective_budget - (used + item_total)
#             future_items = [x for x in ranked if x not in selected and x is not item]
#             min_future_dur = min((float(x['total_duration']) for x in future_items), default=0)

#             if gap_after > 20.0 and future_items and min_future_dur > gap_after:
#                 smaller = [x for x in future_items if float(x['total_duration']) <= effective_budget - used]
#                 if smaller:
#                     skipped.append(item)
#                     continue

#             selected.append(item)
#             used       += item_total
#             cur_budget  = effective_budget
#         else:
#             skipped.append(item)

#     # ── Gap-fit pass ──────────────────────────────────────────────────────────
#     actual_break_overhead = _break_overhead(len(selected))
#     budget                = TARGET - intro_dur - actual_break_overhead
#     gap                   = budget - used
#     filler_gap            = 0.0

#     if gap > 1.0 and skipped:
#         skipped_sorted = sorted(skipped, key=lambda x: float(x.get('total_duration', 0)))
#         still_skipped  = []
#         for item in skipped_sorted:
#             candidate_break_overhead = _break_overhead(len(selected) + 1)
#             effective_budget         = TARGET - intro_dur - candidate_break_overhead
#             item_total               = float(item['total_duration'])
#             gap_now                  = effective_budget - used
#             if item_total <= gap_now:
#                 selected.append(item)
#                 used   += item_total
#                 budget  = effective_budget
#                 gap     = budget - used
#             else:
#                 still_skipped.append(item)
#         skipped = still_skipped
#         actual_break_overhead = _break_overhead(len(selected))
#         final_budget = TARGET - intro_dur - actual_break_overhead
#         filler_gap = max(0.0, final_budget - used)

#     # ── Flag skipped items → next bulletin ───────────────────────────────────
#     if skipped:
#         # with _metadata_lock:
#         #     all_meta = load_metadata()
#         #     meta_map = {str(m.get('counter')): m for m in all_meta}
#         #     for item in skipped:
#         #         ctr = str(item.get('counter'))
#         #         print(f"  ↪  Item {ctr} | dur={item.get('total_duration', 0):.2f}s")
#         #         if ctr in meta_map:
#         #             meta_map[ctr]['next_bulletin'] = True
#         #     save_metadata(list(meta_map.values()))
#         import db as _db
#         skipped_counters = []
#         for item in skipped:
#             ctr = item.get('counter')
#             print(f"  ↪  Item {ctr} | dur={item.get('total_duration', 0):.2f}s")
#             if ctr is not None:
#                 skipped_counters.append(ctr)
#         if skipped_counters:
#             _db.execute(
#                 "UPDATE news_items SET next_bulletin = 1 WHERE counter = ANY(%s)",
#                 (skipped_counters,)
#             )

#     actual_break_overhead = _break_overhead(len(selected))
#     budget                = TARGET - intro_dur - actual_break_overhead

#     # ── Proportional allocation ───────────────────────────────────────────────
#     total_fixed = 0.0
#     for item in selected:
#         total_fixed += float(item.get('headline_duration', 0.0))
#         if item.get('clip_structure') and item.get('clip_start') is not None:
#             clip_dur = min(
#                 float(item['clip_end']) - float(item['clip_start']),
#                 CLIP_MAX
#             )
#             total_fixed += clip_dur

#     script_budget    = budget - total_fixed
#     total_script_dur = sum(float(i.get('script_duration', 0.0)) for i in selected)

#     ATEMPO_MIN = 0.95
#     ATEMPO_MAX = 1.05

#     if script_budget > 0 and total_script_dur > 0:
#         ideal_atempo   = total_script_dur / script_budget
#         uniform_atempo = max(ATEMPO_MIN, min(ATEMPO_MAX, ideal_atempo))
#     else:
#         ideal_atempo   = 1.0
#         uniform_atempo = 1.0

#     actual_total_script = total_script_dur / uniform_atempo if uniform_atempo > 0 else total_script_dur
#     used_after_atempo   = total_fixed + actual_total_script
#     filler_duration     = max(0.0, budget - used_after_atempo)
#     print(f"  ideal_atempo={ideal_atempo:.4f}x → clamped={uniform_atempo:.4f}x")
#     print(f"  actual_script_time={actual_total_script:.2f}s | filler_gap={filler_duration:.2f}s")

#     # ── Filler cap: 3-10s, baaki extra ads se fill ────────────────────────
#     FILLER_MAX = 10.0
#     FILLER_MIN = 3.0

#     while filler_duration > FILLER_MAX and _ad_reserve:
#         next_ad = _ad_reserve.pop(0)
#         next_ad_dur = _effective_dur(next_ad)
#         if next_ad_dur <= 0:
#             continue
#         # Agar yeh ad daalne se filler negative nahi ho raha
#         if filler_duration - next_ad_dur >= FILLER_MIN:
#             _injections.append({
#                 'path': next_ad,
#                 'duration': next_ad_dur,
#                 'label': f'ad_extra_{len(_injections)+1}'
#             })
#             filler_duration -= next_ad_dur
#             print(f"  [FILLER-FIX] Extra ad injected ({next_ad_dur:.1f}s) → filler={filler_duration:.1f}s")
#         else:
#             # Bada ad — list ke end mein wapas daalo, baaki try karo
#             _ad_reserve.append(next_ad)
#             # Agar saare reserve ads bade hain, infinite loop se bachao:
#             if all(_effective_dur(a) > (filler_duration - FILLER_MIN) for a in _ad_reserve):
#                 break

#     # _ad_reserve khatam — agar filler bahut lamba hai to locally downloaded ads reuse karo
#     FILLER_REUSE_THRESHOLD = 30.0
#     if filler_duration > FILLER_REUSE_THRESHOLD and _ad_clips_pool:
#         import random as _rand
#         _reuse_pool = _ad_clips_pool[:]
#         _rand.shuffle(_reuse_pool)
#         for _reuse_ad in _reuse_pool:
#             if filler_duration <= FILLER_MAX:
#                 break
#             _reuse_dur = _effective_dur(_reuse_ad)
#             if _reuse_dur <= 0:
#                 continue
#             if filler_duration - _reuse_dur >= FILLER_MIN:
#                 _injections.append({
#                     'path': _reuse_ad,
#                     'duration': _reuse_dur,
#                     'label': f'ad_reuse_{len(_injections)+1}'
#                 })
#                 filler_duration -= _reuse_dur
#                 print(f"  [FILLER-REUSE] Ad reused ({_reuse_dur:.1f}s) → filler={filler_duration:.1f}s")

#     print(f"  [FILLER-FINAL] {filler_duration:.2f}s (target: {FILLER_MIN}-{FILLER_MAX}s)")
#     for item in selected:
#         headline_dur = float(item.get('headline_duration', 0.0))
#         script_dur   = float(item.get('script_duration', 0.0))
#         has_clip     = bool(item.get('clip_structure') and item.get('clip_start') is not None)
#         clip_dur     = min(float(item["clip_end"]) - float(item["clip_start"]), CLIP_MAX) if has_clip else 0.0

#         actual_script_slot = script_dur / uniform_atempo if uniform_atempo > 0 else script_dur

#         item['allocated_duration'] = headline_dur + clip_dur + actual_script_slot
#         item['_script_slot']       = actual_script_slot
#         item['_atempo']            = uniform_atempo

#         print(f"  Item {item.get('counter')} | script={script_dur:.2f}s → slot={actual_script_slot:.2f}s "
#               f"| atempo={uniform_atempo:.4f}x | allocated={item['allocated_duration']:.2f}s")
#     # ── [DEBUG] Budget vs allocated sanity check ─────────────────────────────
#         _sum_total_duration    = sum(float(i.get('total_duration', 0)) for i in selected)
#         _sum_allocated         = sum(float(i.get('allocated_duration', 0)) for i in selected)
#         _injections_sum        = sum(inj['duration'] for inj in _injections)
#         _expected_final        = (INTRO_VIDEO_DURATION + _sum_allocated
#                                 + actual_break_overhead + _injections_sum + filler_duration)
#         _target_total          = duration_minutes * 60

#         print(f"\n  [DEBUG-BUDGET] ═══════════════════════════════════════════")
#         print(f"  [DEBUG-BUDGET] duration_minutes        = {duration_minutes} ({_target_total}s)")
#         print(f"  [DEBUG-BUDGET] news TARGET             = {TARGET:.2f}s")
#         print(f"  [DEBUG-BUDGET] intro_dur               = {intro_dur}s")
#         print(f"  [DEBUG-BUDGET] break_overhead          = {actual_break_overhead:.2f}s")
#         print(f"  [DEBUG-BUDGET] news budget (effective) = {budget:.2f}s")
#         print(f"  [DEBUG-BUDGET] Σ total_duration (sel)  = {_sum_total_duration:.2f}s")
#         print(f"  [DEBUG-BUDGET] Σ allocated_duration    = {_sum_allocated:.2f}s")
#         print(f"  [DEBUG-BUDGET] atempo (ideal→clamped)  = {ideal_atempo:.4f} → {uniform_atempo:.4f}")
#         print(f"  [DEBUG-BUDGET] ATEMPO CLAMPED?         = {'YES ⚠️' if abs(ideal_atempo - uniform_atempo) > 0.001 else 'no'}")
#         print(f"  [DEBUG-BUDGET] injections sum          = {_injections_sum:.2f}s")
#         print(f"  [DEBUG-BUDGET] filler_duration         = {filler_duration:.2f}s")
#         print(f"  [DEBUG-BUDGET] EXPECTED FINAL          = {_expected_final:.2f}s")
#         print(f"  [DEBUG-BUDGET] TARGET FINAL            = {_target_total}s")
#         print(f"  [DEBUG-BUDGET] DRIFT                   = {_expected_final - _target_total:+.2f}s "
#             f"({((_expected_final - _target_total) / _target_total * 100):+.1f}%)")
#         print(f"  [DEBUG-BUDGET] ═══════════════════════════════════════════\n")

#         # Per-item breakdown
#         for _it in selected:
#             _ctr = _it.get('counter')
#             _hl  = float(_it.get('headline_duration', 0))
#             _sc  = float(_it.get('script_duration', 0))
#             _td  = float(_it.get('total_duration', 0))
#             _ad  = float(_it.get('allocated_duration', 0))
#             _has_clip = bool(_it.get('clip_structure') and _it.get('clip_start') is not None)
#             _cd  = min(float(_it['clip_end']) - float(_it['clip_start']), CLIP_MAX) if _has_clip else 0.0
#             print(f"  [DEBUG-ITEM] ctr={_ctr} | hl={_hl:.1f} script={_sc:.1f} clip={_cd:.1f} "
#                 f"| total={_td:.1f} allocated={_ad:.1f} | diff={_ad - _td:+.2f}s | clip_item={_has_clip}")
#     actual_count = len(selected)

#     # ── Build final_slots: news + injections interleave ───────────────────────
#     # _n_news   = len(selected)
#     # _n_inject = len(_injections)

#     # if _n_inject > 0 and _n_news > 0:
#     #     _insert_every = math.ceil(_n_news / _n_inject)
#     # else:
#     #     _insert_every = _n_news + 1   # koi injection nahi

#     # final_slots = []
#     # _inject_idx = 0
#     # for _si, _news_item in enumerate(selected):
#     #     final_slots.append({'type': 'news', 'item': _news_item})
#     #     if (_si + 1) % _insert_every == 0 and _inject_idx < _n_inject:
#     #         final_slots.append({
#     #             'type':     'injection',
#     #             'path':     _injections[_inject_idx]['path'],
#     #             'duration': _injections[_inject_idx]['duration'],
#     #             'label':    _injections[_inject_idx]['label'],
#     #         })
#     #         _inject_idx += 1

#     # # Bacha hua injection end mein add karo
#     # while _inject_idx < _n_inject:
#     #     final_slots.append({
#     #         'type':     'injection',
#     #         'path':     _injections[_inject_idx]['path'],
#     #         'duration': _injections[_inject_idx]['duration'],
#     #         'label':    _injections[_inject_idx]['label'],
#     #     })
#     #     _inject_idx += 1

#     # print(f"\n  [SLOTS] {_n_news} news + {_n_inject} injections | insert_every={_insert_every}")
#     # for _fs in final_slots:
#     #     if _fs['type'] == 'news':
#     #         ctr = _fs['item'].get('counter')
#     #         dur = _fs['item'].get('allocated_duration', 0)
#     #         print(f"    [NEWS]      counter={ctr} | {dur:.2f}s + {BREAK_DURATION}s break")
#     #     else:
#     #         print(f"    [INJECTION] {_fs['label']} | {_fs['duration']:.2f}s  (no break)")

#     # ── Build final_slots: news + injections interleave ───────────────────────
#     _n_news   = len(selected)
#     _n_inject = len(_injections)

#     import math as _math
#     import random as _random
#     # Random positions — pehle 1 news skip karo (intro ke baad seedha ad nahi)
#     # aur last news ke baad inject mat karo
#     if _n_news >= 3 and _n_inject > 0:
#         _available_pos = list(range(2, _n_news + 1))  # position 2 se _n_news tak
#         _inject_positions = sorted(
#             _random.sample(_available_pos, min(_n_inject, len(_available_pos)))
#         )
#     else:
#         _inject_positions = [max(1, _math.floor(_n_news * (_i + 1) / (_n_inject + 1)))
#                             for _i in range(_n_inject)]

#     final_slots = []
#     _placed     = set()

#     for _si, _news_item in enumerate(selected):
#         final_slots.append({'type': 'news', 'item': _news_item})
#         for _qi, _pos in enumerate(_inject_positions):
#             if _pos == _si + 1 and _qi not in _placed:
#                 final_slots.append({
#                     'type':     'injection',
#                     'path':     _injections[_qi]['path'],
#                     'duration': _injections[_qi]['duration'],
#                     'label':    _injections[_qi]['label'],
#                 })
#                 _placed.add(_qi)

#     # Remaining unplaced injections — end mein
#     for _qi, _inj in enumerate(_injections):
#         if _qi not in _placed:
#             final_slots.append({
#                 'type':     'injection',
#                 'path':     _inj['path'],
#                 'duration': _inj['duration'],
#                 'label':    _inj['label'],
#             })
#             _placed.add(_qi)

#     print(f"\n  [SLOTS] {_n_news} news + {_n_inject} injections")
#     print(f"  [SLOTS] Inject positions: {_inject_positions}")
#     for _fs in final_slots:
#         if _fs['type'] == 'news':
#             ctr = _fs['item'].get('counter')
#             dur = _fs['item'].get('allocated_duration', 0)
#             print(f"    [NEWS]      counter={ctr} | {dur:.2f}s + {BREAK_DURATION}s break")
#         else:
#             print(f"    [INJECTION] {_fs['label']} | {_fs['duration']:.2f}s  (no break)")

#     # ── Build bulletin folder ─────────────────────────────────────────────────
#     # os.makedirs(BULLETINS_DIR, exist_ok=True)

#     # timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
#     # loc_label     = f"loc{location_id}" if location_id is not None else "gen"
#     # bulletin_name = f"bul_{loc_label}_{timestamp_str}"
#     # bulletin_dir  = os.path.join(BULLETINS_DIR, bulletin_name)
#     # ── Build bulletin folder (location-wise) ────────────────────────────────
#     import re
#     os.makedirs(BULLETINS_DIR, exist_ok=True)

#     timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')

#     if location_name:
#         safe_loc = re.sub(r'[^\w\-]', '_', location_name.strip()).title()
#         loc_folder = os.path.join(BULLETINS_DIR, safe_loc)
#     else:
#         loc_folder = os.path.join(BULLETINS_DIR, 'General')
#     os.makedirs(loc_folder, exist_ok=True)

#     bulletin_name = f"bul_{timestamp_str}"
#     bulletin_dir  = os.path.join(loc_folder, bulletin_name)
#     temp_dir      = bulletin_dir + '_tmp'
#     headlines_dir = os.path.join(temp_dir, 'headlines')
#     scripts_dir   = os.path.join(temp_dir, 'scripts')

#     if os.path.exists(temp_dir):
#         _safe_rmtree(temp_dir)

#     os.makedirs(headlines_dir, exist_ok=True)
#     os.makedirs(scripts_dir,   exist_ok=True)

#     print(f"\n📦 Building {duration_minutes}-min bulletin: {bulletin_name}")
#     print(f"   Items selected: {actual_count}")
#     print("-" * 50)

#     manifest = {
#         'bulletin_name':    bulletin_name,
#         'duration_minutes': duration_minutes,
#         'item_count':       actual_count,
#         'filler_duration':  filler_duration,
#         'created_at':       datetime.now().isoformat(),
#         'items':            []
#     }

#     # ── Ticker cumulative start ───────────────────────────────────────────────
#     # segment_start = video time at which this news item starts
#     # Used by ticker_overlay for text scroll continuity
#     _cumulative_start = _load_ticker_cursor()

#     # ── Main manifest loop — iterate final_slots ──────────────────────────────
#     _news_idx = 0   # 1-based counter for news items only

#     for _slot in final_slots:

#         # ── INJECTION SLOT ────────────────────────────────────────────────────
#         if _slot['type'] == 'injection':
#             manifest['items'].append({
#                 'type':     'injection',
#                 'label':    _slot['label'],
#                 'path':     _slot['path'],
#                 'duration': _slot['duration'],
#             })
#             # Ticker OFF during injection — but video time still advances
#             # segment_start of next news item must account for injection duration
#             _cumulative_start += _slot['duration']  # no break
#             continue

#         # ── NEWS SLOT ─────────────────────────────────────────────────────────
#         _news_idx += 1
#         idx  = _news_idx
#         item = _slot['item']

#         counter    = item.get('counter')
#         media_type = item.get('media_type', 'x')
#         priority   = item.get('priority', 'normal')
#         headline   = item.get('headline', '')

#         from event_logger import log_event
#         log_event(
#             event         = 'bulletin_assigned',
#             counter       = counter,
#             media_type    = media_type,
#             bulletin_name = bulletin_name,
#         )

#         headline_audio_src = os.path.join(OUTPUT_HEADLINE_DIR, item['headline_audio'])
#         script_audio_src   = os.path.join(OUTPUT_AUDIO_DIR,    item['script_audio'])

#         ha_dest_name = f"{str(idx).zfill(2)}_{item['headline_audio']}"
#         sa_dest_name = f"{str(idx).zfill(2)}_{item['script_audio']}"

#         ha_dest = os.path.join(headlines_dir, ha_dest_name)
#         sa_dest = os.path.join(scripts_dir,   sa_dest_name)

#         shutil.copy2(headline_audio_src, ha_dest)
#         shutil.copy2(script_audio_src,   sa_dest)

#         # ── Copy intro/analysis audio (video clip items) ──────────────────────
#         intro_dest_name    = None
#         analysis_dest_name = None

#         intro_src_name    = item.get('intro_audio_filename', '')
#         analysis_src_name = item.get('analysis_audio_filename', '')

#         if intro_src_name:
#             intro_src = os.path.join(OUTPUT_AUDIO_DIR, intro_src_name)
#             if not os.path.exists(intro_src):
#                 _s3.ensure_local(intro_src, _s3.key_for_audio(intro_src_name))
#             if os.path.exists(intro_src):
#                 intro_dest_name = f"{str(idx).zfill(2)}_{intro_src_name}"
#                 shutil.copy2(intro_src, os.path.join(scripts_dir, intro_dest_name))
#                 print(f"  [CLIP] Copied intro audio:    {intro_dest_name}")
#             else:
#                 print(f"  [CLIP] ⚠️ Intro audio not found: {intro_src_name}")

#         if analysis_src_name:
#             analysis_src = os.path.join(OUTPUT_AUDIO_DIR, analysis_src_name)
#             if not os.path.exists(analysis_src):
#                 _s3.ensure_local(analysis_src, _s3.key_for_audio(analysis_src_name))
#             if os.path.exists(analysis_src):
#                 analysis_dest_name = f"{str(idx).zfill(2)}_{analysis_src_name}"
#                 shutil.copy2(analysis_src, os.path.join(scripts_dir, analysis_dest_name))
#                 print(f"  [CLIP] Copied analysis audio: {analysis_dest_name}")
#             else:
#                 print(f"  [CLIP] ⚠️ Analysis audio not found: {analysis_src_name}")

#         # ── Apply uniform atempo ──────────────────────────────────────────────
#         script_dur  = float(item.get('script_duration', 0.0))
#         script_slot = float(item.get('_script_slot', 0.0))
#         atempo      = float(item.get('_atempo', 1.0))

#         def _apply_atempo(audio_path: str, label: str):
#             if not os.path.exists(audio_path):
#                 return
#             if abs(atempo - 1.0) <= 0.01:
#                 print(f"  [ATEMPO] {label} | pace ~1.0x — no adjustment")
#                 return
#             ext      = os.path.splitext(audio_path)[1] or '.mp3'
#             tmp_path = audio_path + '_atmp' + ext
#             cmd = ['ffmpeg', '-y', '-i', audio_path, '-filter:a', f'atempo={atempo:.4f}', tmp_path]
#             result = subprocess.run(cmd, capture_output=True)
#             if result.returncode == 0:
#                 os.replace(tmp_path, audio_path)
#                 print(f"  [ATEMPO] {label} | atempo={atempo:.4f}x ✅")
#             else:
#                 print(f"  [ATEMPO] {label} | ❌ ffmpeg failed, using original")
#                 if os.path.exists(tmp_path):
#                     os.remove(tmp_path)

#         if script_dur > 0 and script_slot > 0:
#             _apply_atempo(sa_dest, f"Item {counter} script")
#         if intro_dest_name:
#             _apply_atempo(os.path.join(scripts_dir, intro_dest_name), f"Item {counter} intro")
#         if analysis_dest_name:
#             _apply_atempo(os.path.join(scripts_dir, analysis_dest_name), f"Item {counter} analysis")

#         # ── Recalculate allocated_duration post-atempo ────────────────────────
#         has_clip = bool(item.get('clip_structure') and item.get('clip_start') is not None)

#         if has_clip:
#             actual_intro    = _audio_dur(os.path.join(scripts_dir, intro_dest_name))    if intro_dest_name    else 0.0
#             actual_analysis = _audio_dur(os.path.join(scripts_dir, analysis_dest_name)) if analysis_dest_name else 0.0
#             clip_dur_actual = min(float(item['clip_end']) - float(item['clip_start']), CLIP_MAX)
#             item['allocated_duration'] = (
#                 float(item.get('headline_duration', 0.0)) +
#                 actual_intro + clip_dur_actual + actual_analysis
#             )
#             print(f"  [ALLOC] Item {counter} clip | "
#                   f"hl={item.get('headline_duration',0):.2f}s + "
#                   f"intro={actual_intro:.2f}s + clip={clip_dur_actual:.2f}s + "
#                   f"analysis={actual_analysis:.2f}s = {item['allocated_duration']:.2f}s")
#         else:
#             actual_script = _audio_dur(sa_dest) if (script_dur > 0 and script_slot > 0) else float(item.get('script_duration', 0.0))
#             item['allocated_duration'] = float(item.get('headline_duration', 0.0)) + actual_script
#             print(f"  [ALLOC] Item {counter} script | "
#                   f"hl={item.get('headline_duration',0):.2f}s + "
#                   f"script={actual_script:.2f}s = {item['allocated_duration']:.2f}s")

#         print(f"  [{idx:02d}] [{priority.upper():8s}] {headline[:50]}")

#         manifest['items'].append({
#             'type':                    'news',
#             'rank':                    idx,
#             'counter':                 counter,
#             'media_type':              media_type,
#             'priority':                priority,
#             'timestamp':               item.get('timestamp', ''),
#             'sender_name':             item.get('sender_name', ''),
#             'photo_path':              item.get('sender_photo', ''),
#             'gif_path':                item.get('sender_gif', ADDRESS_GIF_PATH if os.path.exists(ADDRESS_GIF_PATH) else ''),
#             'location_id':             item.get('location_id', 0),
#             'location_name':           item.get('location_name', ''),
#             'headline':                headline,
#             'headline_audio':          ha_dest_name,
#             'script_audio':            sa_dest_name,
#             'script_filename':         item.get('script_filename', ''),
#             'script_duration':         item.get('script_duration',   0.0),
#             'headline_duration':       item.get('headline_duration', 0.0),
#             'total_duration':          item.get('total_duration',    0.0),
#             'allocated_duration':      item['allocated_duration'],
#             'segment_start':           round(_cumulative_start, 3),  # ticker scroll offset
#             'clip_structure':          item.get('clip_structure'),
#             'clip_start':              item.get('clip_start'),
#             'clip_end':                item.get('clip_end'),
#             'intro_audio_filename':    intro_dest_name,
#             'analysis_audio_filename': analysis_dest_name,
#             'clip_video_path':         item.get('clip_video_path'),
#             'item_video_local':        None,
#             'multi_image_paths':       item.get('multi_image_paths', []),
#             'user_id':                 item.get('user_id', ''),
#             'created_at':              item.get('created_at', ''),
#         })

#         # Ticker: news item ke baad BREAK hota hai (break pe ticker OFF)
#         # segment_start ko news content + break se advance karo
#         _cumulative_start += item['allocated_duration'] + BREAK_DURATION

#     _save_ticker_cursor(_cumulative_start)

#     # ── Fix: item_video_local files ko temp_dir mein copy karo rename se pehle ──
#     item_videos_dir = os.path.join(temp_dir, 'item_videos')
#     for entry in manifest.get('items', []):
#         if entry.get('type') == 'injection':
#             continue
#         src = entry.get('item_video_local')
#         if src and os.path.exists(src):
#             os.makedirs(item_videos_dir, exist_ok=True)
#             dst = os.path.join(item_videos_dir, os.path.basename(src))
#             if os.path.abspath(src) != os.path.abspath(dst):
#                 try:
#                     shutil.copy2(src, dst)
#                     entry['item_video_local'] = dst
#                 except Exception as _e:
#                     print(f"⚠️ item_video copy failed for {os.path.basename(src)}: {_e}")
#                     entry['item_video_local'] = None

#     manifest_path = os.path.join(temp_dir, 'bulletin_manifest.json')
#     with open(manifest_path, 'w', encoding='utf-8') as f:
#         json.dump(manifest, f, ensure_ascii=False, indent=2)

#     # Atomic rename
#     safe_loc = re.sub(r'[^\w\-]', '_', (location_name or 'General').strip()).title()
#     if os.path.exists(bulletin_dir):
#         old_dir = bulletin_dir + '_old'
#         if os.path.exists(old_dir):
#             _safe_rmtree(old_dir)
#         os.rename(bulletin_dir, old_dir)
#         os.rename(temp_dir, bulletin_dir)
#         _safe_rmtree(old_dir)
#     else:
#         shutil.move(temp_dir, bulletin_dir)

#     # Upload manifest after rename (file is now in final location)
#     final_manifest = os.path.join(bulletin_dir, 'bulletin_manifest.json')
#     _s3.upload_file_async(
#         final_manifest,
#         _s3.key_for_bulletin_manifest(safe_loc, bulletin_name),
#     )

#     # Update used_count
#     selected_counters = {item.get('counter') for item in selected}
#     # with _metadata_lock:
#     #     all_items_updated = load_metadata()
#     #     for item in all_items_updated:
#     #         if item.get('counter') in selected_counters:
#     #             item['used_count'] = item.get('used_count', 0) + 1
#     #     save_metadata(all_items_updated)
#     import db as _db
#     _db.execute(
#         "UPDATE news_items SET used_count = used_count + 1, bulletined = 1 WHERE counter = ANY(%s)",
#         (list(selected_counters),)
#     )
#     print(f"✅ used_count updated for {len(selected_counters)} items")

#     print("-" * 50)
#     print(f"✅ Bulletin built: {bulletin_dir}")
#     print(f"   filler_duration = {filler_duration:.3f}s  (logo.mov will loop for this)")
#     return bulletin_dir

# if __name__ == '__main__':
#     import sys
#     duration = int(sys.argv[1]) if len(sys.argv) > 1 else 5
#     mode     = sys.argv[2] if len(sys.argv) > 2 else 'dynamic'

#     if mode == 'test':
#         result = build_bulletin(duration, location_id=21, location_name="Kurnool")
#         print(f"Test bulletin: {result}")
#     else:
#         results = build_all_location_bulletins(duration)
#         for loc_id, info in results.items():
#             print(f"[{loc_id}] {info['location_name']} → {info['path']}")







import math
import os
import json
import shutil
import subprocess
import time
from datetime import datetime
from typing import List, Dict, Optional
from config import (
    OUTPUT_HEADLINE_DIR,
    OUTPUT_AUDIO_DIR,
    OUTPUT_SCRIPT_DIR,
    BASE_OUTPUT_DIR,
    BASE_DIR,
    INTRO_VIDEO_DURATION, BREAK_DURATION,
    ADDRESS_GIF_PATH,
    ITEM_VIDEO_CACHE_DIR,
)

import threading
_metadata_lock = threading.Lock()

METADATA_FILE = os.path.join(BASE_OUTPUT_DIR, 'metadata.json')
BULLETINS_DIR = os.path.join(BASE_OUTPUT_DIR, 'bulletins')

PRIORITY_RANK = {
    'breaking': 0,
    'urgent':   1,
    'normal':   2,
}

def _load_ticker_cursor() -> float:
    """Global ticker cursor load karo CloudSQL se — midnight pe auto-reset."""
    try:
        import db as _db
        raw = _db.get_state('ticker_cursor')
        if not raw:
            return 0.0
        state = json.loads(raw)
        saved_date = state.get('date', '')
        today = datetime.now().strftime('%Y-%m-%d')
        if saved_date != today:
            print(f"🔄 Ticker cursor reset — new day ({saved_date} → {today})")
            return 0.0
        return float(state.get('cursor', 0.0))
    except Exception as e:
        print(f"⚠️ ticker_cursor load error: {e}")
        return 0.0


def _save_ticker_cursor(val: float):
    """Global ticker cursor CloudSQL mein persist karo."""
    try:
        import db as _db
        _db.set_state('ticker_cursor', json.dumps({
            'cursor':     round(val, 3),
            'date':       datetime.now().strftime('%Y-%m-%d'),
            'updated_at': datetime.now().isoformat(),
        }))
    except Exception as e:
        print(f"❌ ticker_state save error: {e}")

CLIP_MAX = 20  # max clip duration to consider for allocation (in seconds)

# def load_metadata() -> List[Dict]:
#     if not os.path.exists(METADATA_FILE):
#         return []
#     try:
#         with open(METADATA_FILE, 'r', encoding='utf-8') as f:
#             return json.load(f)
#     except Exception as e:
#         print(f"❌ Error loading metadata: {e}")
#         return []

def load_metadata() -> List[Dict]:
    try:
        import db as _db
        rows = _db.fetchall("SELECT * FROM news_items ORDER BY counter ASC")
        for r in rows:
            for k in ('multi_image_paths', 'multi_video_paths'):
                v = r.get(k)
                if isinstance(v, str):
                    try:
                        r[k] = json.loads(v)
                    except Exception:
                        r[k] = []
        return rows
    except Exception as e:
        print(f"❌ Error loading news_items from DB: {e}")
        return []


# def save_metadata(items: List[Dict]):
#     os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)
#     try:
#         with open(METADATA_FILE, 'w', encoding='utf-8') as f:
#             json.dump(items, f, ensure_ascii=False, indent=2)
#     except Exception as e:
#         print(f"❌ Error saving metadata: {e}")

def save_metadata(items: List[Dict]):
    """Update mutable fields of existing news_items rows in DB."""
    import db as _db
    for item in items:
        counter = item.get('counter')
        if counter is None:
            continue
        _db.execute("""
            UPDATE news_items SET
                used_count        = %s,
                next_bulletin     = %s,
                bulletined        = %s,
                priority          = COALESCE(%s, priority),
                item_video_local  = %s,
                incident_id       = %s,
                script_duration   = %s,
                headline_duration = %s,
                total_duration    = %s
            WHERE counter = %s
        """, (
            item.get('used_count', 0),
            1 if item.get('next_bulletin') else 0,
            1 if item.get('bulletined') else 0,
            item.get('priority'),
            item.get('item_video_local'),
            item.get('incident_id'),
            item.get('script_duration', 0.0),
            item.get('headline_duration', 0.0),
            item.get('total_duration', 0.0),
            counter,
        ))


def delete_news_items(counters: list):
    """Delete news_items rows by counter list (used by cleanup loop)."""
    import db as _db
    if not counters:
        return
    _db.execute("DELETE FROM news_items WHERE counter = ANY(%s)", (list(counters),))


# def append_news_item(item: Dict):
#     with _metadata_lock:
#         items = load_metadata()
#         items.append(item)
#         save_metadata(items)
#     print(f"✅ Metadata saved for item {item.get('counter')} [{item.get('priority')}]")
#
#     from event_logger import log_event
#     log_event(
#         event      = 'bulletin_added',
#         counter    = item.get('counter'),
#         media_type = item.get('media_type'),
#     )

def append_news_item(item: Dict):
    import db as _db
    multi_images = item.get('multi_image_paths', [])
    if isinstance(multi_images, list):
        multi_images = json.dumps(multi_images, ensure_ascii=False)

    _db.execute("""
        INSERT INTO news_items (
            counter, media_type, priority,
            sender, sender_name, sender_photo,
            timestamp, headline, script_filename,
            headline_audio, script_audio,
            intro_audio_filename, analysis_audio_filename,
            headline_duration, script_duration, total_duration, allocated_duration,
            clip_structure, clip_start, clip_end, clip_video_path,
            location_id, location_name,
            user_id, original_text,
            intro_script, analysis_script,
            multi_image_paths,
            used_count, bulletined, next_bulletin,
            s3_key_input, s3_key_script_audio, s3_key_headline_audio,
            storage_key, item_manifest
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s
        ) ON CONFLICT (counter, media_type) DO UPDATE SET
            priority                = EXCLUDED.priority,
            headline                = EXCLUDED.headline,
            script_audio            = EXCLUDED.script_audio,
            script_duration         = EXCLUDED.script_duration,
            headline_duration       = EXCLUDED.headline_duration,
            total_duration          = EXCLUDED.total_duration,
            clip_structure          = EXCLUDED.clip_structure,
            clip_start              = EXCLUDED.clip_start,
            clip_end                = EXCLUDED.clip_end,
            clip_video_path         = EXCLUDED.clip_video_path,
            intro_audio_filename    = EXCLUDED.intro_audio_filename,
            analysis_audio_filename = EXCLUDED.analysis_audio_filename,
            intro_script            = EXCLUDED.intro_script,
            analysis_script         = EXCLUDED.analysis_script,
            multi_image_paths       = EXCLUDED.multi_image_paths,
            original_text           = EXCLUDED.original_text,
            location_id             = EXCLUDED.location_id,
            location_name           = EXCLUDED.location_name,
            sender_photo            = EXCLUDED.sender_photo
    """, (
        item.get('counter'),
        item.get('media_type', 'video'),
        item.get('priority', 'normal'),
        item.get('sender', item.get('sender_name', '')),
        item.get('sender_name', ''),
        item.get('sender_photo', ''),
        item.get('timestamp', item.get('created_at', datetime.now().isoformat())),
        item.get('headline', ''),
        item.get('script_filename', ''),
        item.get('headline_audio', ''),
        item.get('script_audio', ''),
        item.get('intro_audio_filename'),
        item.get('analysis_audio_filename'),
        float(item.get('headline_duration', 0.0)),
        float(item.get('script_duration', 0.0)),
        float(item.get('total_duration', 0.0)),
        float(item.get('allocated_duration', 0.0)),
        item.get('clip_structure'),
        item.get('clip_start'),
        item.get('clip_end'),
        item.get('clip_video_path'),
        item.get('location_id', 0),
        item.get('location_name', ''),
        item.get('user_id', ''),
        item.get('original_text', ''),
        item.get('intro_script', ''),
        item.get('analysis_script', ''),
        multi_images,
        0,
        0,
        0,
        item.get('s3_key_input'),
        item.get('s3_key_script_audio'),
        item.get('s3_key_headline_audio'),
        item.get('storage_key'),
        item.get('item_manifest'),
    ))
    print(f"✅ DB: news_item inserted counter={item.get('counter')} [{item.get('priority')}]")

    from event_logger import log_event
    log_event(
        event      = 'bulletin_added',
        counter    = item.get('counter'),
        media_type = item.get('media_type'),
    )


# def rank_news_items(items: List[Dict]) -> List[Dict]:
#     def sort_key(item):
#         priority = PRIORITY_RANK.get(item.get('priority', 'normal').lower(), 2)
#         used     = item.get('used_count', 0)
#         dur      = float(item.get('total_duration', 999))
#         try:
#             ts = datetime.fromisoformat(item.get('timestamp', '1970-01-01T00:00:00')).timestamp()
#         except Exception:
#             ts = 0
#         return (priority, used, dur, -ts)

#     return sorted(items, key=sort_key)

def rank_news_items(items: List[Dict]) -> List[Dict]:
    """
    Priority order:
    1. breaking/urgent pehle
    2. Unused items pehle (used_count == 0)
    3. Nayi items pehle (timestamp descending) — yahi main fix hai
    4. Choti duration pehle (budget fit hone ke liye)
    """
    def sort_key(item):
        priority = PRIORITY_RANK.get(item.get('priority', 'normal').lower(), 2)
        used     = item.get('used_count', 0)
        try:
            ts = datetime.fromisoformat(item.get('timestamp', '1970-01-01T00:00:00')).timestamp()
        except Exception:
            ts = 0
        dur = float(item.get('total_duration', 999))
        return (priority, used, -ts, dur)  # -ts = newest first

    return sorted(items, key=sort_key)


def _safe_rmtree(path: str, retries: int = 5, delay: float = 2.0):
    for attempt in range(retries):
        try:
            shutil.rmtree(path)
            return True
        except PermissionError:
            if attempt < retries - 1:
                print(f"⏳ Folder in use, retrying ({attempt + 1}/{retries})...")
                time.sleep(delay)
            else:
                print("⚠️ Could not fully delete old folder — proceeding anyway")
                shutil.rmtree(path, ignore_errors=True)
                return True
    return True


_LOCATION_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.location_channel_cache.json')
_CHANNELS = ["Karimnagar", "Khammam", "Kurnool", "Anatpur", "Kakinada", "Nalore", "Tirupati",
             "Guntur", "Warangal", "Nalgonda"]

def classify_location_to_channel(location_names: list) -> dict:
    """Use Gemini (OpenAI-compat client) to map location names to channels. Kurnool is default."""
    import json
    from openai import OpenAI
    from config import GEMINI_API_KEY, GEMINI_MODEL

    cache = {}
    if os.path.exists(_LOCATION_CACHE_FILE):
        with open(_LOCATION_CACHE_FILE, 'r') as f:
            cache = json.load(f)

    uncached = [n for n in location_names if n not in cache]
    if uncached:
        print(f"[GEMINI] 📍 classify_location_to_channel | model={GEMINI_MODEL} | uncached={uncached}")
        client = OpenAI(
            api_key=GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        prompt = (
            f"Map each location name to exactly one of these channels: {_CHANNELS}. "
            f"If unsure or no match, assign 'Kurnool'. "
            f"Return ONLY a JSON object like {{\"loc_name\": \"Channel\"}}. No markdown, no explanation.\n\n"
            f"Locations: {uncached}"
        )
        try:
            resp = client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            raw = resp.choices[0].message.content
            if not raw:
                raise ValueError("Empty response from Gemini")
            raw = raw.strip()
            if raw.startswith('```'):
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
                raw = raw.strip()
            mapping = json.loads(raw)
            cache.update(mapping)
            with open(_LOCATION_CACHE_FILE, 'w') as f:
                json.dump(cache, f, indent=2)
        except Exception as e:
            print(f"⚠️ Location classify failed: {e} — defaulting all to Kurnool")
            for n in uncached:
                cache[n] = "Kurnool"

    return {n: cache.get(n, "Kurnool") for n in location_names}


# def build_all_location_bulletins(duration_minutes: int) -> dict:
#     """Metadata se sabhi unique locations detect karke har ek ka bulletin banao."""
#     from datetime import datetime, timedelta, timezone
#     all_items = load_metadata()

#     _cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
#     def _in_24hr(item):
#         ts_str = item.get('created_at') or item.get('timestamp', '')
#         try:
#             ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
#             if ts.tzinfo is None:
#                 ts = ts.replace(tzinfo=timezone.utc)
#             return ts >= _cutoff
#         except Exception:
#             return True
#     all_items = [i for i in all_items if _in_24hr(i)]

#     if not all_items:
#         print("❌ No items in metadata")
#         return {}

#     results = {}
#     path = build_bulletin(duration_minutes)
#     results['all'] = {'location_name': 'All', 'path': path}
#     return results

def build_all_location_bulletins(duration_minutes: int) -> dict:
    """Metadata se sabhi unique locations detect karke har ek ka bulletin banao."""
    from datetime import datetime, timedelta, timezone
    all_items = load_metadata()

    _cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    def _in_24hr(item):
        ts_str = item.get('created_at') or item.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts >= _cutoff
        except Exception:
            return True
    all_items = [i for i in all_items if _in_24hr(i)]

    if not all_items:
        print("❌ No items in metadata")
        return {}

    # # Unique locations collect karo
    # unique_locs = {}
    # for item in all_items:
    #     lid = item.get('location_id')
    #     lname = item.get('location_name', '')
    #     if lid and lname:
    #         unique_locs[str(lid)] = lname

    # print(f"🌍 Found {len(unique_locs)} unique locations: {list(unique_locs.values())}")

    # results = {}
    # for loc_id, loc_name in unique_locs.items():
    #     print(f"\n{'='*60}\n🏗️  Building bulletin for [{loc_id}] {loc_name}\n{'='*60}")
    #     path = build_bulletin(duration_minutes, location_id=loc_id, location_name=loc_name)
    #     if path:
    #         results[loc_id] = {'location_name': loc_name, 'path': path}

    # return results

    # Collect unique raw location names
    raw_location_names = list({
        item.get('location_name', '')
        for item in all_items
        if item.get('location_name', '')
    })

    # OpenAI classify → one of 3 canonical channels
    loc_to_channel = classify_location_to_channel(raw_location_names)
    print(f"🗺️  Location mapping: {loc_to_channel}")

    # Bucket items by channel
    KNOWN_CHANNELS = {"Karimnagar", "Khammam", "Kurnool",
                      "Anatpur", "Kakinada", "Nalore", "Tirupati",
                      "Guntur", "Warangal", "Nalgonda"}
    channel_items  = {ch: [] for ch in KNOWN_CHANNELS}
    general_items  = []  # items that don't match any of the 7 channels

    for item in all_items:
        raw     = item.get('location_name', '')
        channel = loc_to_channel.get(raw)
        if channel and channel in KNOWN_CHANNELS:
            channel_items[channel].append(item)
        else:
            general_items.append(item)

    if general_items:
        print(f"🌐 {len(general_items)} general items (no location match)")

    results = {}
    for channel_name, items in channel_items.items():
        if items:
            # Channel ke apne items hain — sirf wahi use karo
            use_items = items
            print(f"\n{'='*60}\n🏗️  Building bulletin for {channel_name} ({len(items)} own items)\n{'='*60}")
        elif general_items:
            # Apne items nahi hain — general items fallback ke roop me use karo
            use_items = general_items
            print(f"\n{'='*60}\n🏗️  Building bulletin for {channel_name} (no own items — using {len(general_items)} general items)\n{'='*60}")
        else:
            print(f"⚠️ No items for {channel_name}, skipping")
            continue
        path = build_bulletin(duration_minutes, location_name=channel_name, _items_override=use_items)
        if path:
            results[channel_name] = {'location_name': channel_name, 'path': path}

    return results


# def build_bulletin(duration_minutes: int, location_id: int = None, location_name: str = None) -> Optional[str]:
def build_bulletin(duration_minutes: int, location_id: int = None, location_name: str = None, _items_override: list = None) -> Optional[str]:
    all_items = load_metadata()

    if _items_override is not None:
        all_items = _items_override

    if not all_items:
        print("❌ No news items found in metadata.json")
        return None

    # Validate items — both audio files must exist
    # EXCLUDE items marked for next bulletin (they were skipped before)
    import s3_storage as _s3
    valid_items = []
    for item in all_items:
        if item.get('next_bulletin'):
            continue  # Skip items reserved for next bulletin
        headline_audio = item.get('headline_audio', '')
        script_audio   = item.get('script_audio', '')
        ha_path = os.path.join(OUTPUT_HEADLINE_DIR, headline_audio)
        sa_path = os.path.join(OUTPUT_AUDIO_DIR,    script_audio)

        # S3 fallback — download missing audio files before validation
        if headline_audio and not os.path.exists(ha_path):
            _s3.ensure_local(ha_path, _s3.key_for_audio(headline_audio))
        if script_audio and not os.path.exists(sa_path):
            _s3.ensure_local(sa_path, _s3.key_for_audio(script_audio))

        if headline_audio and script_audio and os.path.exists(ha_path) and os.path.exists(sa_path):
            valid_items.append(item)
        else:
            print(f"⚠️ Skipping item {item.get('counter')} — audio files missing: headline_audio='{headline_audio}' exists={os.path.exists(ha_path)} | script_audio='{script_audio}' exists={os.path.exists(sa_path)}")

    # ── Location filter ───────────────────────────────────────────────────────
    if location_id is not None:
        valid_items = [
            i for i in valid_items
            if str(i.get('location_id', '')) == str(location_id)
        ]
        if not valid_items:
            print(f"❌ No items for location_id={location_id} ({location_name})")
            return None
        print(f"📍 Filtered {len(valid_items)} items for [{location_id}] {location_name}")


    if not valid_items:
        print("❌ No valid items with audio files found")
        return None

    # ranked    = rank_news_items(valid_items)
    # Pending-first: agar enough unused items hain to old skip
    unused_items = [x for x in valid_items if x.get('used_count', 0) == 0]
    MIN_ITEMS_THRESHOLD = 8

    if len(unused_items) >= MIN_ITEMS_THRESHOLD:
        ranked = rank_news_items(unused_items)
        print(f"  [RANK] {len(unused_items)} unused items — old items skipped")
    else:
        ranked = rank_news_items(valid_items)
        print(f"  [RANK] Only {len(unused_items)} unused — mixing with old items")

    intro_dur = INTRO_VIDEO_DURATION

    # ── Pre-fetch WhoisWho (S3) + Ad clips (S3) ──────────────────────────────
    from s3_bulletin_fetcher import fetch_whoiswho_bulletin, fetch_ad_clips

    _whoiswho_clip = fetch_whoiswho_bulletin()           # S3 se 1-min clip
    _ad_clips_pool = fetch_ad_clips()                    # S3 se ads pool
    _ad_clips = _ad_clips_pool[:4]                       # initial 4
    _ad_reserve = _ad_clips_pool[4:10]

    def _quick_dur(path: str) -> float:
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return float(r.stdout.decode().strip())
        except Exception:
            return 0.0

    # _whoiswho_dur  = _quick_dur(_whoiswho_clip) if (_whoiswho_clip and os.path.exists(_whoiswho_clip)) else 0.0
    # _ad_durations  = [_quick_dur(ac) for ac in _ad_clips if ac and os.path.exists(ac)]
    # _ad_total_dur  = sum(_ad_durations)
    from config import S3_INJECT_LOCAL_DIR

    def _effective_dur(original_path: str) -> float:
        reenc_filename = os.path.basename(original_path).replace('.mp4', '_reenc.mp4')
        reenc_path     = os.path.join(S3_INJECT_LOCAL_DIR, reenc_filename)
        if (os.path.exists(reenc_path) and
                os.path.getsize(reenc_path) > 100_000 and
                os.path.getmtime(original_path) <= os.path.getmtime(reenc_path)):
            return _quick_dur(reenc_path)
        return _quick_dur(original_path)

    _whoiswho_dur  = _effective_dur(_whoiswho_clip) if (_whoiswho_clip and os.path.exists(_whoiswho_clip)) else 0.0
    _ad_durations  = [_effective_dur(ac) for ac in _ad_clips if ac and os.path.exists(ac)]
    _ad_total_dur  = sum(_ad_durations)

    # ── Injections list: whoiswho pehle, phir ads ────────────────────────────
    _injections = []
    if _whoiswho_clip and _whoiswho_dur > 0:
        _injections.append({'path': _whoiswho_clip, 'duration': _whoiswho_dur, 'label': 'whoiswho'})
    for _i, (ac, ad_dur) in enumerate(zip(_ad_clips, _ad_durations)):
        if ac and ad_dur > 0:
            _injections.append({'path': ac, 'duration': ad_dur, 'label': f'ad_{_i+1}'})

    # 🆕 Shuffle taaki whoiswho aur ads ka order bulletin-to-bulletin different ho
    import random as _random
    _random.shuffle(_injections)
    # ── NEWS budget = TOTAL - injections (injections ka break NAHI hoga) ─────
    TARGET = duration_minutes * 60 - _whoiswho_dur - _ad_total_dur - 5
    print(f"  [BUDGET] total={duration_minutes*60}s | whoiswho={_whoiswho_dur:.1f}s | "
          f"ads={_ad_total_dur:.1f}s ({len(_ad_clips)} clips) | "
          f"{len(_injections)} injections → news TARGET={TARGET:.1f}s")

    # ─── Step 1: Ensure total_duration is set on every item ──────────────────
    def _audio_dur(path: str) -> float:
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            return float(r.stdout.decode().strip())
        except Exception:
            return 0.0

    for item in ranked:
        intro_name    = item.get('intro_audio_filename', '')
        analysis_name = item.get('analysis_audio_filename', '')
        has_clip_item = bool(
            item.get('clip_structure') and
            item.get('clip_start') is not None and
            item.get('clip_end') is not None and
            intro_name
        )

        if has_clip_item:
            clip_dur = min(
                float(item['clip_end']) - float(item['clip_start']),
                CLIP_MAX
            )
            intro_path_f    = os.path.join(OUTPUT_AUDIO_DIR, intro_name)
            analysis_path_f = os.path.join(OUTPUT_AUDIO_DIR, analysis_name) if analysis_name else None

            intro_dur_actual    = _audio_dur(intro_path_f)    if os.path.exists(intro_path_f)    else float(item.get('script_duration', 0.0)) * 0.5
            analysis_dur_actual = _audio_dur(analysis_path_f) if (analysis_path_f and os.path.exists(analysis_path_f)) else 0.0

            item['total_duration'] = (
                float(item.get('headline_duration', 0.0)) +
                intro_dur_actual +
                clip_dur +
                analysis_dur_actual
            )
        elif not item.get('total_duration'):
            item['total_duration'] = (
                float(item.get('headline_duration', 0.0)) +
                float(item.get('script_duration',   0.0))
            )

    # ── Smart greedy selection ─────────────────────────────────────────────────
    selected   = []
    skipped    = []
    used       = 0.0
    cur_budget = TARGET - intro_dur

    # Break overhead — sirf news items ke liye (injections ka break nahi)
    def _break_overhead(n: int) -> float:
        if n == 0:
            return 0.0
        intro_break = 1
        hl_breaks   = max(0, n - 1)
        news_breaks = max(0, n - 1)
        return (intro_break + hl_breaks + news_breaks) * BREAK_DURATION

    for item in ranked:
        candidate_break_overhead = _break_overhead(len(selected) + 1)
        effective_budget         = TARGET - intro_dur - candidate_break_overhead
        item_total               = float(item['total_duration'])

        if used + item_total <= effective_budget:
            gap_after    = effective_budget - (used + item_total)
            future_items = [x for x in ranked if x not in selected and x is not item]
            min_future_dur = min((float(x['total_duration']) for x in future_items), default=0)

            if gap_after > 20.0 and future_items and min_future_dur > gap_after:
                smaller = [x for x in future_items if float(x['total_duration']) <= effective_budget - used]
                if smaller:
                    skipped.append(item)
                    continue

            selected.append(item)
            used       += item_total
            cur_budget  = effective_budget
        else:
            skipped.append(item)

    # ── Gap-fit pass ──────────────────────────────────────────────────────────
    actual_break_overhead = _break_overhead(len(selected))
    budget                = TARGET - intro_dur - actual_break_overhead
    gap                   = budget - used
    filler_gap            = 0.0

    if gap > 1.0 and skipped:
        skipped_sorted = sorted(skipped, key=lambda x: float(x.get('total_duration', 0)))
        still_skipped  = []
        for item in skipped_sorted:
            candidate_break_overhead = _break_overhead(len(selected) + 1)
            effective_budget         = TARGET - intro_dur - candidate_break_overhead
            item_total               = float(item['total_duration'])
            gap_now                  = effective_budget - used
            if item_total <= gap_now:
                selected.append(item)
                used   += item_total
                budget  = effective_budget
                gap     = budget - used
            else:
                still_skipped.append(item)
        skipped = still_skipped
        actual_break_overhead = _break_overhead(len(selected))
        final_budget = TARGET - intro_dur - actual_break_overhead
        filler_gap = max(0.0, final_budget - used)

    # ── Flag skipped items → next bulletin ───────────────────────────────────
    if skipped:
        # with _metadata_lock:
        #     all_meta = load_metadata()
        #     meta_map = {str(m.get('counter')): m for m in all_meta}
        #     for item in skipped:
        #         ctr = str(item.get('counter'))
        #         print(f"  ↪  Item {ctr} | dur={item.get('total_duration', 0):.2f}s")
        #         if ctr in meta_map:
        #             meta_map[ctr]['next_bulletin'] = True
        #     save_metadata(list(meta_map.values()))
        import db as _db
        skipped_counters = []
        for item in skipped:
            ctr = item.get('counter')
            print(f"  ↪  Item {ctr} | dur={item.get('total_duration', 0):.2f}s")
            if ctr is not None:
                skipped_counters.append(ctr)
        if skipped_counters:
            _db.execute(
                "UPDATE news_items SET next_bulletin = 1 WHERE counter = ANY(%s)",
                (skipped_counters,)
            )

    actual_break_overhead = _break_overhead(len(selected))
    budget                = TARGET - intro_dur - actual_break_overhead

    # ── Proportional allocation ───────────────────────────────────────────────
    total_fixed = 0.0
    for item in selected:
        total_fixed += float(item.get('headline_duration', 0.0))
        if item.get('clip_structure') and item.get('clip_start') is not None:
            clip_dur = min(
                float(item['clip_end']) - float(item['clip_start']),
                CLIP_MAX
            )
            total_fixed += clip_dur

    script_budget    = budget - total_fixed
    total_script_dur = sum(float(i.get('script_duration', 0.0)) for i in selected)

    ATEMPO_MIN = 0.95
    ATEMPO_MAX = 1.05

    if script_budget > 0 and total_script_dur > 0:
        ideal_atempo   = total_script_dur / script_budget
        uniform_atempo = max(ATEMPO_MIN, min(ATEMPO_MAX, ideal_atempo))
    else:
        ideal_atempo   = 1.0
        uniform_atempo = 1.0

    actual_total_script = total_script_dur / uniform_atempo if uniform_atempo > 0 else total_script_dur
    used_after_atempo   = total_fixed + actual_total_script
    filler_duration     = max(0.0, budget - used_after_atempo)
    print(f"  ideal_atempo={ideal_atempo:.4f}x → clamped={uniform_atempo:.4f}x")
    print(f"  actual_script_time={actual_total_script:.2f}s | filler_gap={filler_duration:.2f}s")

    # ── Filler cap: 3-10s, baaki extra ads se fill ────────────────────────
    FILLER_MAX = 10.0
    FILLER_MIN = 3.0

    while filler_duration > FILLER_MAX and _ad_reserve:
        next_ad = _ad_reserve.pop(0)
        next_ad_dur = _effective_dur(next_ad)
        if next_ad_dur <= 0:
            continue
        # Agar yeh ad daalne se filler negative nahi ho raha
        if filler_duration - next_ad_dur >= FILLER_MIN:
            _injections.append({
                'path': next_ad,
                'duration': next_ad_dur,
                'label': f'ad_extra_{len(_injections)+1}'
            })
            filler_duration -= next_ad_dur
            print(f"  [FILLER-FIX] Extra ad injected ({next_ad_dur:.1f}s) → filler={filler_duration:.1f}s")
        else:
            # Bada ad — list ke end mein wapas daalo, baaki try karo
            _ad_reserve.append(next_ad)
            # Agar saare reserve ads bade hain, infinite loop se bachao:
            if all(_effective_dur(a) > (filler_duration - FILLER_MIN) for a in _ad_reserve):
                break

    # _ad_reserve khatam — agar filler bahut lamba hai to locally downloaded ads reuse karo
    FILLER_REUSE_THRESHOLD = 30.0
    if filler_duration > FILLER_REUSE_THRESHOLD and _ad_clips_pool:
        import random as _rand
        _reuse_pool = _ad_clips_pool[:]
        _rand.shuffle(_reuse_pool)
        for _reuse_ad in _reuse_pool:
            if filler_duration <= FILLER_MAX:
                break
            _reuse_dur = _effective_dur(_reuse_ad)
            if _reuse_dur <= 0:
                continue
            if filler_duration - _reuse_dur >= FILLER_MIN:
                _injections.append({
                    'path': _reuse_ad,
                    'duration': _reuse_dur,
                    'label': f'ad_reuse_{len(_injections)+1}'
                })
                filler_duration -= _reuse_dur
                print(f"  [FILLER-REUSE] Ad reused ({_reuse_dur:.1f}s) → filler={filler_duration:.1f}s")

    print(f"  [FILLER-FINAL] {filler_duration:.2f}s (target: {FILLER_MIN}-{FILLER_MAX}s)")
    for item in selected:
        headline_dur = float(item.get('headline_duration', 0.0))
        script_dur   = float(item.get('script_duration', 0.0))
        has_clip     = bool(item.get('clip_structure') and item.get('clip_start') is not None)
        clip_dur     = min(float(item["clip_end"]) - float(item["clip_start"]), CLIP_MAX) if has_clip else 0.0

        actual_script_slot = script_dur / uniform_atempo if uniform_atempo > 0 else script_dur

        item['allocated_duration'] = headline_dur + clip_dur + actual_script_slot
        item['_script_slot']       = actual_script_slot
        item['_atempo']            = uniform_atempo

        print(f"  Item {item.get('counter')} | script={script_dur:.2f}s → slot={actual_script_slot:.2f}s "
              f"| atempo={uniform_atempo:.4f}x | allocated={item['allocated_duration']:.2f}s")
    # ── [DEBUG] Budget vs allocated sanity check ─────────────────────────────
        _sum_total_duration    = sum(float(i.get('total_duration', 0)) for i in selected)
        _sum_allocated         = sum(float(i.get('allocated_duration', 0)) for i in selected)
        _injections_sum        = sum(inj['duration'] for inj in _injections)
        _expected_final        = (INTRO_VIDEO_DURATION + _sum_allocated
                                + actual_break_overhead + _injections_sum + filler_duration)
        _target_total          = duration_minutes * 60

        print(f"\n  [DEBUG-BUDGET] ═══════════════════════════════════════════")
        print(f"  [DEBUG-BUDGET] duration_minutes        = {duration_minutes} ({_target_total}s)")
        print(f"  [DEBUG-BUDGET] news TARGET             = {TARGET:.2f}s")
        print(f"  [DEBUG-BUDGET] intro_dur               = {intro_dur}s")
        print(f"  [DEBUG-BUDGET] break_overhead          = {actual_break_overhead:.2f}s")
        print(f"  [DEBUG-BUDGET] news budget (effective) = {budget:.2f}s")
        print(f"  [DEBUG-BUDGET] Σ total_duration (sel)  = {_sum_total_duration:.2f}s")
        print(f"  [DEBUG-BUDGET] Σ allocated_duration    = {_sum_allocated:.2f}s")
        print(f"  [DEBUG-BUDGET] atempo (ideal→clamped)  = {ideal_atempo:.4f} → {uniform_atempo:.4f}")
        print(f"  [DEBUG-BUDGET] ATEMPO CLAMPED?         = {'YES ⚠️' if abs(ideal_atempo - uniform_atempo) > 0.001 else 'no'}")
        print(f"  [DEBUG-BUDGET] injections sum          = {_injections_sum:.2f}s")
        print(f"  [DEBUG-BUDGET] filler_duration         = {filler_duration:.2f}s")
        print(f"  [DEBUG-BUDGET] EXPECTED FINAL          = {_expected_final:.2f}s")
        print(f"  [DEBUG-BUDGET] TARGET FINAL            = {_target_total}s")
        print(f"  [DEBUG-BUDGET] DRIFT                   = {_expected_final - _target_total:+.2f}s "
            f"({((_expected_final - _target_total) / _target_total * 100):+.1f}%)")
        print(f"  [DEBUG-BUDGET] ═══════════════════════════════════════════\n")

        # Per-item breakdown
        for _it in selected:
            _ctr = _it.get('counter')
            _hl  = float(_it.get('headline_duration', 0))
            _sc  = float(_it.get('script_duration', 0))
            _td  = float(_it.get('total_duration', 0))
            _ad  = float(_it.get('allocated_duration', 0))
            _has_clip = bool(_it.get('clip_structure') and _it.get('clip_start') is not None)
            _cd  = min(float(_it['clip_end']) - float(_it['clip_start']), CLIP_MAX) if _has_clip else 0.0
            print(f"  [DEBUG-ITEM] ctr={_ctr} | hl={_hl:.1f} script={_sc:.1f} clip={_cd:.1f} "
                f"| total={_td:.1f} allocated={_ad:.1f} | diff={_ad - _td:+.2f}s | clip_item={_has_clip}")
    actual_count = len(selected)

    # ── Build final_slots: news + injections interleave ───────────────────────
    # _n_news   = len(selected)
    # _n_inject = len(_injections)

    # if _n_inject > 0 and _n_news > 0:
    #     _insert_every = math.ceil(_n_news / _n_inject)
    # else:
    #     _insert_every = _n_news + 1   # koi injection nahi

    # final_slots = []
    # _inject_idx = 0
    # for _si, _news_item in enumerate(selected):
    #     final_slots.append({'type': 'news', 'item': _news_item})
    #     if (_si + 1) % _insert_every == 0 and _inject_idx < _n_inject:
    #         final_slots.append({
    #             'type':     'injection',
    #             'path':     _injections[_inject_idx]['path'],
    #             'duration': _injections[_inject_idx]['duration'],
    #             'label':    _injections[_inject_idx]['label'],
    #         })
    #         _inject_idx += 1

    # # Bacha hua injection end mein add karo
    # while _inject_idx < _n_inject:
    #     final_slots.append({
    #         'type':     'injection',
    #         'path':     _injections[_inject_idx]['path'],
    #         'duration': _injections[_inject_idx]['duration'],
    #         'label':    _injections[_inject_idx]['label'],
    #     })
    #     _inject_idx += 1

    # print(f"\n  [SLOTS] {_n_news} news + {_n_inject} injections | insert_every={_insert_every}")
    # for _fs in final_slots:
    #     if _fs['type'] == 'news':
    #         ctr = _fs['item'].get('counter')
    #         dur = _fs['item'].get('allocated_duration', 0)
    #         print(f"    [NEWS]      counter={ctr} | {dur:.2f}s + {BREAK_DURATION}s break")
    #     else:
    #         print(f"    [INJECTION] {_fs['label']} | {_fs['duration']:.2f}s  (no break)")

    # ── Build final_slots: news + injections interleave ───────────────────────
    _n_news   = len(selected)
    _n_inject = len(_injections)

    import math as _math
    import random as _random
    # Random positions — pehle 1 news skip karo (intro ke baad seedha ad nahi)
    # aur last news ke baad inject mat karo
    if _n_news >= 3 and _n_inject > 0:
        _available_pos = list(range(2, _n_news + 1))  # position 2 se _n_news tak
        _inject_positions = sorted(
            _random.sample(_available_pos, min(_n_inject, len(_available_pos)))
        )
    else:
        _inject_positions = [max(1, _math.floor(_n_news * (_i + 1) / (_n_inject + 1)))
                            for _i in range(_n_inject)]

    final_slots = []
    _placed     = set()

    for _si, _news_item in enumerate(selected):
        final_slots.append({'type': 'news', 'item': _news_item})
        for _qi, _pos in enumerate(_inject_positions):
            if _pos == _si + 1 and _qi not in _placed:
                final_slots.append({
                    'type':     'injection',
                    'path':     _injections[_qi]['path'],
                    'duration': _injections[_qi]['duration'],
                    'label':    _injections[_qi]['label'],
                })
                _placed.add(_qi)

    # Remaining unplaced injections — end mein
    for _qi, _inj in enumerate(_injections):
        if _qi not in _placed:
            final_slots.append({
                'type':     'injection',
                'path':     _inj['path'],
                'duration': _inj['duration'],
                'label':    _inj['label'],
            })
            _placed.add(_qi)

    print(f"\n  [SLOTS] {_n_news} news + {_n_inject} injections")
    print(f"  [SLOTS] Inject positions: {_inject_positions}")
    for _fs in final_slots:
        if _fs['type'] == 'news':
            ctr = _fs['item'].get('counter')
            dur = _fs['item'].get('allocated_duration', 0)
            print(f"    [NEWS]      counter={ctr} | {dur:.2f}s + {BREAK_DURATION}s break")
        else:
            print(f"    [INJECTION] {_fs['label']} | {_fs['duration']:.2f}s  (no break)")

    # ── Build bulletin folder ─────────────────────────────────────────────────
    # os.makedirs(BULLETINS_DIR, exist_ok=True)

    # timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    # loc_label     = f"loc{location_id}" if location_id is not None else "gen"
    # bulletin_name = f"bul_{loc_label}_{timestamp_str}"
    # bulletin_dir  = os.path.join(BULLETINS_DIR, bulletin_name)
    # ── Build bulletin folder (location-wise) ────────────────────────────────
    import re
    os.makedirs(BULLETINS_DIR, exist_ok=True)

    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    if location_name:
        safe_loc = re.sub(r'[^\w\-]', '_', location_name.strip()).title()
        loc_folder = os.path.join(BULLETINS_DIR, safe_loc)
    else:
        loc_folder = os.path.join(BULLETINS_DIR, 'General')
    os.makedirs(loc_folder, exist_ok=True)

    bulletin_name = f"bul_{timestamp_str}"
    bulletin_dir  = os.path.join(loc_folder, bulletin_name)
    temp_dir      = bulletin_dir + '_tmp'
    headlines_dir = os.path.join(temp_dir, 'headlines')
    scripts_dir   = os.path.join(temp_dir, 'scripts')

    if os.path.exists(temp_dir):
        _safe_rmtree(temp_dir)

    os.makedirs(headlines_dir, exist_ok=True)
    os.makedirs(scripts_dir,   exist_ok=True)

    print(f"\n📦 Building {duration_minutes}-min bulletin: {bulletin_name}")
    print(f"   Items selected: {actual_count}")
    print("-" * 50)

    manifest = {
        'bulletin_name':    bulletin_name,
        'duration_minutes': duration_minutes,
        'item_count':       actual_count,
        'filler_duration':  filler_duration,
        'created_at':       datetime.now().isoformat(),
        'items':            []
    }

    # ── Ticker cumulative start ───────────────────────────────────────────────
    # segment_start = video time at which this news item starts
    # Used by ticker_overlay for text scroll continuity
    _cumulative_start = _load_ticker_cursor()

    # ── Main manifest loop — iterate final_slots ──────────────────────────────
    _news_idx = 0   # 1-based counter for news items only

    for _slot in final_slots:

        # ── INJECTION SLOT ────────────────────────────────────────────────────
        if _slot['type'] == 'injection':
            manifest['items'].append({
                'type':     'injection',
                'label':    _slot['label'],
                'path':     _slot['path'],
                'duration': _slot['duration'],
            })
            # Ticker OFF during injection — but video time still advances
            # segment_start of next news item must account for injection duration
            _cumulative_start += _slot['duration']  # no break
            continue

        # ── NEWS SLOT ─────────────────────────────────────────────────────────
        _news_idx += 1
        idx  = _news_idx
        item = _slot['item']

        counter    = item.get('counter')
        media_type = item.get('media_type', 'x')
        priority   = item.get('priority', 'normal')
        headline   = item.get('headline', '')

        from event_logger import log_event
        log_event(
            event         = 'bulletin_assigned',
            counter       = counter,
            media_type    = media_type,
            bulletin_name = bulletin_name,
        )

        headline_audio_src = os.path.join(OUTPUT_HEADLINE_DIR, item['headline_audio'])
        script_audio_src   = os.path.join(OUTPUT_AUDIO_DIR,    item['script_audio'])

        ha_dest_name = f"{str(idx).zfill(2)}_{item['headline_audio']}"
        sa_dest_name = f"{str(idx).zfill(2)}_{item['script_audio']}"

        ha_dest = os.path.join(headlines_dir, ha_dest_name)
        sa_dest = os.path.join(scripts_dir,   sa_dest_name)

        shutil.copy2(headline_audio_src, ha_dest)
        shutil.copy2(script_audio_src,   sa_dest)

        # ── Copy intro/analysis audio (video clip items) ──────────────────────
        intro_dest_name    = None
        analysis_dest_name = None

        intro_src_name    = item.get('intro_audio_filename', '')
        analysis_src_name = item.get('analysis_audio_filename', '')

        if intro_src_name:
            intro_src = os.path.join(OUTPUT_AUDIO_DIR, intro_src_name)
            if not os.path.exists(intro_src):
                _s3.ensure_local(intro_src, _s3.key_for_audio(intro_src_name))
            if os.path.exists(intro_src):
                intro_dest_name = f"{str(idx).zfill(2)}_{intro_src_name}"
                shutil.copy2(intro_src, os.path.join(scripts_dir, intro_dest_name))
                print(f"  [CLIP] Copied intro audio:    {intro_dest_name}")
            else:
                print(f"  [CLIP] ⚠️ Intro audio not found: {intro_src_name}")

        if analysis_src_name:
            analysis_src = os.path.join(OUTPUT_AUDIO_DIR, analysis_src_name)
            if not os.path.exists(analysis_src):
                _s3.ensure_local(analysis_src, _s3.key_for_audio(analysis_src_name))
            if os.path.exists(analysis_src):
                analysis_dest_name = f"{str(idx).zfill(2)}_{analysis_src_name}"
                shutil.copy2(analysis_src, os.path.join(scripts_dir, analysis_dest_name))
                print(f"  [CLIP] Copied analysis audio: {analysis_dest_name}")
            else:
                print(f"  [CLIP] ⚠️ Analysis audio not found: {analysis_src_name}")

        # ── Apply uniform atempo ──────────────────────────────────────────────
        script_dur  = float(item.get('script_duration', 0.0))
        script_slot = float(item.get('_script_slot', 0.0))
        atempo      = float(item.get('_atempo', 1.0))

        def _apply_atempo(audio_path: str, label: str):
            if not os.path.exists(audio_path):
                return
            if abs(atempo - 1.0) <= 0.01:
                print(f"  [ATEMPO] {label} | pace ~1.0x — no adjustment")
                return
            ext      = os.path.splitext(audio_path)[1] or '.mp3'
            tmp_path = audio_path + '_atmp' + ext
            cmd = ['ffmpeg', '-y', '-i', audio_path, '-filter:a', f'atempo={atempo:.4f}', tmp_path]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode == 0:
                os.replace(tmp_path, audio_path)
                print(f"  [ATEMPO] {label} | atempo={atempo:.4f}x ✅")
            else:
                print(f"  [ATEMPO] {label} | ❌ ffmpeg failed, using original")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        if script_dur > 0 and script_slot > 0:
            _apply_atempo(sa_dest, f"Item {counter} script")
        if intro_dest_name:
            _apply_atempo(os.path.join(scripts_dir, intro_dest_name), f"Item {counter} intro")
        if analysis_dest_name:
            _apply_atempo(os.path.join(scripts_dir, analysis_dest_name), f"Item {counter} analysis")

        # ── Recalculate allocated_duration post-atempo ────────────────────────
        has_clip = bool(item.get('clip_structure') and item.get('clip_start') is not None)

        if has_clip:
            actual_intro    = _audio_dur(os.path.join(scripts_dir, intro_dest_name))    if intro_dest_name    else 0.0
            actual_analysis = _audio_dur(os.path.join(scripts_dir, analysis_dest_name)) if analysis_dest_name else 0.0
            clip_dur_actual = min(float(item['clip_end']) - float(item['clip_start']), CLIP_MAX)
            item['allocated_duration'] = (
                float(item.get('headline_duration', 0.0)) +
                actual_intro + clip_dur_actual + actual_analysis
            )
            print(f"  [ALLOC] Item {counter} clip | "
                  f"hl={item.get('headline_duration',0):.2f}s + "
                  f"intro={actual_intro:.2f}s + clip={clip_dur_actual:.2f}s + "
                  f"analysis={actual_analysis:.2f}s = {item['allocated_duration']:.2f}s")
        else:
            actual_script = _audio_dur(sa_dest) if (script_dur > 0 and script_slot > 0) else float(item.get('script_duration', 0.0))
            item['allocated_duration'] = float(item.get('headline_duration', 0.0)) + actual_script
            print(f"  [ALLOC] Item {counter} script | "
                  f"hl={item.get('headline_duration',0):.2f}s + "
                  f"script={actual_script:.2f}s = {item['allocated_duration']:.2f}s")

        print(f"  [{idx:02d}] [{priority.upper():8s}] {headline[:50]}")

        manifest['items'].append({
            'type':                    'news',
            'rank':                    idx,
            'counter':                 counter,
            'media_type':              media_type,
            'priority':                priority,
            'timestamp':               item.get('timestamp', ''),
            'sender_name':             item.get('sender_name', ''),
            'photo_path':              item.get('sender_photo', ''),
            'gif_path':                item.get('sender_gif', ADDRESS_GIF_PATH if os.path.exists(ADDRESS_GIF_PATH) else ''),
            'location_id':             item.get('location_id', 0),
            'location_name':           item.get('location_name', ''),
            'headline':                headline,
            'headline_audio':          ha_dest_name,
            'script_audio':            sa_dest_name,
            'script_filename':         item.get('script_filename', ''),
            'script_duration':         item.get('script_duration',   0.0),
            'headline_duration':       item.get('headline_duration', 0.0),
            'total_duration':          item.get('total_duration',    0.0),
            'allocated_duration':      item['allocated_duration'],
            'segment_start':           round(_cumulative_start, 3),  # ticker scroll offset
            'clip_structure':          item.get('clip_structure'),
            'clip_start':              item.get('clip_start'),
            'clip_end':                item.get('clip_end'),
            'intro_audio_filename':    intro_dest_name,
            'analysis_audio_filename': analysis_dest_name,
            'clip_video_path':         item.get('clip_video_path'),
            'item_video_local':        None,
            'multi_image_paths':       item.get('multi_image_paths', []),
            'user_id':                 item.get('user_id', ''),
            'created_at':              item.get('created_at', ''),
        })

        # Ticker: news item ke baad BREAK hota hai (break pe ticker OFF)
        # segment_start ko news content + break se advance karo
        _cumulative_start += item['allocated_duration'] + BREAK_DURATION

    _save_ticker_cursor(_cumulative_start)

    # ── Fix: item_video_local files ko temp_dir mein copy karo rename se pehle ──
    item_videos_dir = os.path.join(temp_dir, 'item_videos')
    for entry in manifest.get('items', []):
        if entry.get('type') == 'injection':
            continue
        src = entry.get('item_video_local')
        if src and os.path.exists(src):
            os.makedirs(item_videos_dir, exist_ok=True)
            dst = os.path.join(item_videos_dir, os.path.basename(src))
            if os.path.abspath(src) != os.path.abspath(dst):
                try:
                    shutil.copy2(src, dst)
                    entry['item_video_local'] = dst
                except Exception as _e:
                    print(f"⚠️ item_video copy failed for {os.path.basename(src)}: {_e}")
                    entry['item_video_local'] = None

    manifest_path = os.path.join(temp_dir, 'bulletin_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Atomic rename
    safe_loc = re.sub(r'[^\w\-]', '_', (location_name or 'General').strip()).title()
    if os.path.exists(bulletin_dir):
        old_dir = bulletin_dir + '_old'
        if os.path.exists(old_dir):
            _safe_rmtree(old_dir)
        os.rename(bulletin_dir, old_dir)
        os.rename(temp_dir, bulletin_dir)
        _safe_rmtree(old_dir)
    else:
        shutil.move(temp_dir, bulletin_dir)

    # Upload manifest after rename (file is now in final location)
    final_manifest = os.path.join(bulletin_dir, 'bulletin_manifest.json')
    _s3.upload_file_async(
        final_manifest,
        _s3.key_for_bulletin_manifest(safe_loc, bulletin_name),
    )

    # Update used_count
    selected_counters = {item.get('counter') for item in selected}
    # with _metadata_lock:
    #     all_items_updated = load_metadata()
    #     for item in all_items_updated:
    #         if item.get('counter') in selected_counters:
    #             item['used_count'] = item.get('used_count', 0) + 1
    #     save_metadata(all_items_updated)
    import db as _db
    _db.execute(
        "UPDATE news_items SET used_count = used_count + 1, bulletined = 1 WHERE counter = ANY(%s)",
        (list(selected_counters),)
    )
    print(f"✅ used_count updated for {len(selected_counters)} items")

    print("-" * 50)
    print(f"✅ Bulletin built: {bulletin_dir}")
    print(f"   filler_duration = {filler_duration:.3f}s  (logo.mov will loop for this)")
    return bulletin_dir

if __name__ == '__main__':
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    mode     = sys.argv[2] if len(sys.argv) > 2 else 'dynamic'

    if mode == 'test':
        result = build_bulletin(duration, location_id=21, location_name="Kurnool")
        print(f"Test bulletin: {result}")
    else:
        results = build_all_location_bulletins(duration)
        for loc_id, info in results.items():
            print(f"[{loc_id}] {info['location_name']} → {info['path']}")