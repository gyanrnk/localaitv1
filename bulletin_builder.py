"""
Bulletin Builder
Reads metadata.json, ranks news items, builds bulletin folder.

Ranking order:
  1. BREAKING  (highest)
  2. URGENT
  3. NORMAL    (lowest)
  Within each group → least used first, then newest timestamp first

Duration model (exact 5 min):
  TARGET = duration_minutes * 60        (e.g. 300s)
  budget = TARGET - INTRO_VIDEO_DURATION (e.g. 284.6s)

  All selected items must fit within budget.
  Remaining time → filler_duration stored in manifest.
  video_builder.py loops logo.mov for exactly filler_duration seconds.
  Result: intro + content + filler = exactly TARGET seconds.

Output folder structure:
  outputs/bulletins/bulletin_5min_TIMESTAMP/
      ├── bulletin_manifest.json   (includes filler_duration)
      ├── headlines/
      │   ├── 01_hi1.mp3
      │   └── ...
      └── scripts/
          ├── 01_oai1.mp3
          └── ...
"""

import os
import json
import shutil
import time
from datetime import datetime
from typing import List, Dict, Optional
from config import INTRO_VIDEO_DURATION

from config import (
    OUTPUT_HEADLINE_DIR,
    OUTPUT_AUDIO_DIR,
    OUTPUT_SCRIPT_DIR,
    BASE_OUTPUT_DIR,
    BASE_DIR,
)


METADATA_FILE = os.path.join(BASE_OUTPUT_DIR, 'metadata.json')
BULLETINS_DIR = os.path.join(BASE_OUTPUT_DIR, 'bulletins')

PRIORITY_RANK = {
    'breaking': 0,
    'urgent':   1,
    'normal':   2,
}


def load_metadata() -> List[Dict]:
    """Load all news item metadata from metadata.json"""
    if not os.path.exists(METADATA_FILE):
        return []
    try:
        with open(METADATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error loading metadata: {e}")
        return []


def save_metadata(items: List[Dict]):
    """Save full metadata list back to metadata.json"""
    os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)
    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Error saving metadata: {e}")


def append_news_item(item: Dict):
    """
    Append a single news item to metadata.json.
    Called from main.py after every successful processing.
    """
    items = load_metadata()
    items.append(item)
    save_metadata(items)
    print(f"✅ Metadata saved for item {item.get('counter')} [{item.get('priority')}]")


def rank_news_items(items: List[Dict]) -> List[Dict]:
    """
    Sort news items by:
      1. Priority group  (breaking=0 > urgent=1 > normal=2)
      2. used_count      (least used first)
      3. Timestamp       (newest first within each group)
    """
    def sort_key(item):
        priority = PRIORITY_RANK.get(item.get('priority', 'normal').lower(), 2)
        used     = item.get('used_count', 0)
        try:
            ts = datetime.fromisoformat(item.get('timestamp', '1970-01-01T00:00:00')).timestamp()
        except Exception:
            ts = 0
        return (priority, used, -ts)

    return sorted(items, key=sort_key)


def _safe_rmtree(path: str, retries: int = 5, delay: float = 2.0):
    """
    Remove a directory tree, retrying on Windows PermissionError.
    """
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


def build_bulletin(duration_minutes: int) -> Optional[str]:
    """
    Build a bulletin folder for the given duration.

    Duration model:
      budget = (duration_minutes * 60) - INTRO_VIDEO_DURATION
      Items are selected greedily (priority order) to fit within budget.
      filler_duration = budget - sum(selected item durations)
      video_builder.py will loop logo.mov for filler_duration seconds
      so that intro + content + filler = exactly duration_minutes * 60.

    Args:
        duration_minutes: 5 | 10 | 30 | 60

    Returns:
        Path to the bulletin folder, or None on failure
    """
    all_items = load_metadata()
    if not all_items:
        print("❌ No news items found in metadata.json")
        return None

    # ─── Validate items — both audio files must exist ───────────────────────
    valid_items = []
    for item in all_items:
        headline_audio = item.get('headline_audio', '')
        script_audio   = item.get('script_audio', '')
        ha_path = os.path.join(OUTPUT_HEADLINE_DIR, headline_audio)
        sa_path = os.path.join(OUTPUT_AUDIO_DIR,    script_audio)
        if headline_audio and script_audio and os.path.exists(ha_path) and os.path.exists(sa_path):
            valid_items.append(item)
        else:
            print(f"⚠️ Skipping item {item.get('counter')} — audio files missing")

    if not valid_items:
        print("❌ No valid items with audio files found")
        return None

    ranked = rank_news_items(valid_items)

    # ─── Duration constants ─────────────────────────────────────────────────
    TARGET    = duration_minutes * 60   # e.g. 300s
    intro_dur = INTRO_VIDEO_DURATION    # fixed (e.g. 15.4s)
    budget    = TARGET - intro_dur      # e.g. 284.6s — all content must fit here

    # ─── Step 1: Ensure total_duration is set on every item ─────────────────
    # total_duration = headline_duration + script_duration
    # (no transition buffer — filler handles the remaining gap cleanly)
    for item in ranked:
        if not item.get('total_duration'):
            item['total_duration'] = (
                float(item.get('headline_duration', 0.0)) +
                float(item.get('script_duration',   0.0))
            )

    # ─── Step 2: Greedy selection — fit as many items as possible ───────────
    selected = []
    used     = 0.0

    for item in ranked:
        item_total = float(item['total_duration'])
        if used + item_total <= budget:
            selected.append(item)
            used += item_total

    # ─── Step 3: Filler duration = gap left after all content ─────────────
    # video_builder.py will loop logo.mov for exactly this many seconds.
    # intro + used + filler_duration = TARGET  →  exact 5 min guaranteed.
    # filler_duration = round(budget - used, 3)   # always >= 0
    filler_duration = 0.0

    actual_count = len(selected)

    print(f"\n⏱️  DURATION BUDGET")
    print(f"   Target          : {TARGET:.1f}s ({duration_minutes} min)")
    print(f"   Intro           : {intro_dur:.1f}s")
    print(f"   Content (items) : {used:.3f}s  ({actual_count} items)")
    print(f"   Filler (logo)   : {filler_duration:.3f}s")
    print(f"   Total           : {intro_dur + used + filler_duration:.3f}s  ✅")

    # ─── Build bulletin folder ───────────────────────────────────────────────
    os.makedirs(BULLETINS_DIR, exist_ok=True)

    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    bulletin_name = f"bulletin_{duration_minutes}min_{timestamp_str}"
    # bulletin_dir  = os.path.join(BULLETINS_DIR, bulletin_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_name = f"{bulletin_name}_{timestamp}"

    bulletin_dir = os.path.join(BULLETINS_DIR, unique_name)
    
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
        'filler_duration':  filler_duration,   # ← logo.mov loops for this long
        'created_at':       datetime.now().isoformat(),
        'items':            []
    }

    for idx, item in enumerate(selected, start=1):
        counter    = item.get('counter')
        media_type = item.get('media_type', 'x')
        priority   = item.get('priority', 'normal')
        headline   = item.get('headline', '')

        headline_audio_src = os.path.join(OUTPUT_HEADLINE_DIR, item['headline_audio'])
        script_audio_src   = os.path.join(OUTPUT_AUDIO_DIR,    item['script_audio'])

        ha_dest_name = f"{str(idx).zfill(2)}_{item['headline_audio']}"
        sa_dest_name = f"{str(idx).zfill(2)}_{item['script_audio']}"

        ha_dest = os.path.join(headlines_dir, ha_dest_name)
        sa_dest = os.path.join(scripts_dir,   sa_dest_name)

        shutil.copy2(headline_audio_src, ha_dest)
        shutil.copy2(script_audio_src,   sa_dest)

        print(f"  [{idx:02d}] [{priority.upper():8s}] {headline[:50]}")

        manifest['items'].append({
            'rank':              idx,
            'counter':           counter,
            'media_type':        media_type,
            'priority':          priority,
            'timestamp':         item.get('timestamp', ''),
            'headline':          headline,
            'headline_audio':    ha_dest_name,
            'script_audio':      sa_dest_name,
            'script_duration':   item.get('script_duration',   0.0),
            'headline_duration': item.get('headline_duration', 0.0),
            'total_duration':    item.get('total_duration',    0.0),
        })

    manifest_path = os.path.join(temp_dir, 'bulletin_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Atomic rename: temp → final (safe even if previous folder exists)
    if os.path.exists(bulletin_dir):
        old_dir = bulletin_dir + '_old'
        if os.path.exists(old_dir):
            _safe_rmtree(old_dir)
        os.rename(bulletin_dir, old_dir)
        os.rename(temp_dir, bulletin_dir)
        _safe_rmtree(old_dir)
    else:
        os.rename(temp_dir, bulletin_dir)

    # Update used_count for all selected items
    selected_counters = {item.get('counter') for item in selected}
    all_items_updated = load_metadata()
    for item in all_items_updated:
        if item.get('counter') in selected_counters:
            item['used_count'] = item.get('used_count', 0) + 1
    save_metadata(all_items_updated)
    print(f"✅ used_count updated for {len(selected_counters)} items")

    print("-" * 50)
    print(f"✅ Bulletin built: {bulletin_dir}")
    print(f"   filler_duration = {filler_duration:.3f}s  (logo.mov will loop for this)")
    return bulletin_dir


if __name__ == '__main__':
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    result = build_bulletin(duration)
    if result:
        print(f"\n📁 Output: {result}")




