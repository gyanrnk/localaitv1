"""
S3 se pre-built 1-min bulletin video randomly fetch karo.
Sirf boto3 + random logic — video_builder.py ko clean rakhne ke liye alag file.
"""
import json
import os
import random
import re
import subprocess
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from typing import List, Optional

from config import (
    S3_BUCKET_NAME,
    S3_BUCKET_NAME_M,
    S3_BULLETIN_PREFIX,
    S3_REGION,
    S3_INJECT_LOCAL_DIR,
    LOCATION_ID_TO_CHANNEL,
    CHANNEL_STATE,
)


import threading as _threading
from botocore.config import Config as _BotoConfig

_s3_lock   = _threading.Lock()
_s3_lock_m = _threading.Lock()
_s3_singleton   = None
_s3_singleton_m = None

def _s3_client():
    """Own bucket — singleton client (thread-safe, pool size 25)."""
    global _s3_singleton
    if _s3_singleton is None:
        with _s3_lock:
            if _s3_singleton is None:
                _s3_singleton = boto3.client(
                    's3',
                    region_name=os.getenv('AWS_REGION', S3_REGION),
                    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                    config=_BotoConfig(max_pool_connections=25),
                )
    return _s3_singleton

def _s3_client_m():
    """Meghna's bucket — singleton client (thread-safe, pool size 25)."""
    global _s3_singleton_m
    if _s3_singleton_m is None:
        with _s3_lock_m:
            if _s3_singleton_m is None:
                _s3_singleton_m = boto3.client(
                    's3',
                    region_name=S3_REGION,
                    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID_M'),
                    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY_M'),
                    config=_BotoConfig(max_pool_connections=25),
                )
    return _s3_singleton_m


# ── Location-aware tiered fetch helpers ─────────────────────────────────────
# channel(lower) -> [backend ids]; LOCATION_ID_TO_CHANNEL se bana (COMPLETE 9-id map,
# 209 Kakinada / 335 Tirupati included) — jaan-bujhke channel_backend_ids NAHI use kiya:
# wo CLASSIFIED_LOCATION_MAP par hai jisme 209/335 missing hain, aur wo
# webhook_server/yt_streamer ke saath shared hai (unka behavior nahi chhedna).
_CHANNEL_TO_BACKEND_IDS = {}
for _bid, _ch in LOCATION_ID_TO_CHANNEL.items():
    _CHANNEL_TO_BACKEND_IDS.setdefault(_ch.strip().lower(), []).append(_bid)


def _ids_for_channel(channel_name):
    if not channel_name:
        return []
    return _CHANNEL_TO_BACKEND_IDS.get(str(channel_name).strip().lower(), [])


def _sibling_ids(channel_name):
    """Same-state backend ids EXCLUDING the channel's own id(s)."""
    st = CHANNEL_STATE.get(str(channel_name or '').strip().lower())
    if not st:
        return []
    own = set(_ids_for_channel(channel_name))
    return [bid for bid, ch in LOCATION_ID_TO_CHANNEL.items()
            if bid not in own and CHANNEL_STATE.get(ch.strip().lower()) == st]


def _list_mp4_keys(prefix):
    """Paginated (key, LastModified) list under prefix. [] on ANY error.
    Paginator (bare list_objects_v2 nahi) — whoiswho/outputs/ ~351 keys pe hai
    aur ~35-40/day badh raha; 1000-key page cap jaldi silently truncate karta."""
    try:
        s3 = _s3_client_m()
        out = []
        for page in s3.get_paginator('list_objects_v2').paginate(
                Bucket=S3_BUCKET_NAME_M, Prefix=prefix):
            out += [(o['Key'], o.get('LastModified'))
                    for o in page.get('Contents', [])
                    if o['Key'].endswith('.mp4') and o['Size'] > 0]
        return out
    except Exception as e:
        print(f"  [S3-INJECT] ❌ list error ({prefix}): {e}")
        return []


def _latest_date_subset(keys, base_prefix):
    """Ek id ke keys ko uske NEWEST date folder tak filter karo. Key shape:
    <base_prefix><id>/<YYYY-MM-DD>/<file>.mp4 — ISO dates lexicographic sort hote.
    Max us id ke APNE folders par (Guntur/344 ek din peeche chalta hai — aaj ka
    folder assume kabhi nahi). Undated keys unchanged pass-through."""
    dated = {}
    for k, lm in keys:
        parts = k[len(base_prefix):].split('/')      # [id, date, file]
        if len(parts) >= 3:
            dated.setdefault(parts[1], []).append((k, lm))
    if not dated:
        return keys
    return dated[max(dated)]


def _cached_download(key, base_prefix, family):
    """COLLISION-PROOF flat cache naam ke saath download:
    <family>_<relative-key '/'->'_' > e.g. whoiswho/outputs/75/2026-06-10/bulletin_1.mp4
    -> whoiswho_75_2026-06-10_bulletin_1.mp4. Basename collision fix (har id ke clips
    bulletin_<n>.mp4 naam ke hain — Karimnagar ka bulletin_1 Kakinada ke liye false
    cache-hit ho jaata). Unique naam _effective_dur/_reencode ke reenc-cache me bhi
    sahi flow hota (wo basename se key karte). Returns local path | None; never raises."""
    rel = key[len(base_prefix):] if key.startswith(base_prefix) else key
    local_path = os.path.join(S3_INJECT_LOCAL_DIR,
                              f"{family}_{rel.replace('/', '_')}")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 100_000:
        print(f"  [{family.upper()}] ✅ Cache hit: {os.path.basename(local_path)}")
        return local_path
    try:
        _s3_client_m().download_file(S3_BUCKET_NAME_M, key, local_path)
        print(f"  [{family.upper()}] ✅ Downloaded: {os.path.basename(local_path)}")
        return local_path
    except Exception as e:
        print(f"  [{family.upper()}] ❌ Download failed ({key}): {e}")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        return None


def _fetch_location_clip(base_prefix, channel_name, family, quiet=False):
    """3-tier location-aware pick. NEVER raises — koi bhi failure -> agla tier -> None.
    TIER1: apne backend id(s), latest date folder, random within.
    TIER2: same-state sibling ids, har id ka latest folder, union par random.
    TIER3: global per-id pool — legacy flat keys SHAPE se excluded
           (key <base_prefix><digits>/... match kare tabhi).
    quiet=True 'no clip'/tier-pick prints suppress karta (public_voice me abhi
    outputs/ content nahi — har build pe log spam nahi hona chahiye)."""
    try:
        per_id_re = re.compile(re.escape(base_prefix) + r'\d+/')
        for tier, ids in (('TIER1', _ids_for_channel(channel_name)),
                          ('TIER2', _sibling_ids(channel_name))):
            pool = []
            for bid in ids:
                pool += _latest_date_subset(
                    _list_mp4_keys(f"{base_prefix}{bid}/"), base_prefix)
            if pool:
                key, _lm = random.choice(pool)
                if not quiet:
                    print(f"  [{family.upper()}] {tier} pick ({channel_name}): {key}")
                p = _cached_download(key, base_prefix, family)
                if p:
                    return p          # download fail -> agla tier try hoga
        # TIER3 — global pool, legacy flat keys excluded
        pool = [(k, lm) for k, lm in _list_mp4_keys(base_prefix)
                if per_id_re.match(k)]
        if pool:
            key, _lm = random.choice(pool)
            if not quiet:
                print(f"  [{family.upper()}] TIER3 pick: {key}")
            return _cached_download(key, base_prefix, family)
        if not quiet:
            print(f"  [{family.upper()}] ⚠️ No clip found")
        return None
    except Exception as e:
        print(f"  [{family.upper()}] ❌ Error: {e}")
        return None


def list_s3_bulletins() -> list:
    """S3 prefix ke andar saare .mp4 files list karo."""
    try:
        s3  = _s3_client_m()
        res = s3.list_objects_v2(Bucket=S3_BUCKET_NAME_M, Prefix=S3_BULLETIN_PREFIX)
        keys = [
            obj['Key']
            for obj in res.get('Contents', [])
            if obj['Key'].endswith('.mp4') and obj['Size'] > 0
        ]
        print(f"  [S3-INJECT] Found {len(keys)} bulletins in s3://{S3_BUCKET_NAME_M}/{S3_BULLETIN_PREFIX}")
        return keys
    except (BotoCoreError, ClientError) as e:
        print(f"  [S3-INJECT] ❌ list_objects error: {e}")
        return []


def _reencode_for_bulletin(src_path: str, out_path: str = None) -> str:
    out_path = out_path or src_path.replace('.mp4', '_reenc.mp4')
    """
    S3 clip ko main bulletin ke saath compatible format mein re-encode karo.
    1920x1080, yuv420p, 25fps, aac audio — same as bulletin segments.
    Re-encoded file _reenc.mp4 suffix ke saath cache hoti hai.
    """
    out_path = src_path.replace('.mp4', '_reenc.mp4')

    # Cache hit — dobara encode mat karo
    if os.path.exists(out_path) and os.path.getsize(out_path) > 100_000:
        print(f"  [S3-INJECT] Re-encode cache hit → {os.path.basename(out_path)}")
        return out_path

    print(f"  [S3-INJECT] 🔄 Re-encoding for bulletin compatibility...")
    cmd = [
        'ffmpeg', '-y', '-i', src_path,
        '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,'
               'pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
        '-r', '25',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-ar', '44100', '-ac', '2',
        '-movflags', '+faststart',
        out_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode == 0:
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        print(f"  [S3-INJECT] ✅ Re-encoded → {os.path.basename(out_path)} ({size_mb:.1f} MB)")
        return out_path
    else:
        print(f"  [S3-INJECT] ⚠️ Re-encode failed — using original (may cause concat issues)")
        print(f"  [S3-INJECT] FFmpeg error: {result.stderr.decode()[-300:]}")
        return src_path


def fetch_random_s3_bulletin() -> Optional[str]:
    """
    S3 se random 1-min bulletin download + re-encode karo.
    Returns: local re-encoded file path (str) ya None agar failed.
    """
    keys = list_s3_bulletins()
    if not keys:
        print("  [S3-INJECT] ⚠️ No bulletins available on S3 — skipping injection")
        return None

    chosen_key = random.choice(keys)
    filename   = os.path.basename(chosen_key)
    local_path = os.path.join(S3_INJECT_LOCAL_DIR, filename)
    reenc_path = local_path.replace('.mp4', '_reenc.mp4')

    # Re-encoded cache hit — download bhi skip karo
    if os.path.exists(reenc_path) and os.path.getsize(reenc_path) > 100_000:
        print(f"  [S3-INJECT] ✅ Full cache hit (re-encoded) → {os.path.basename(reenc_path)}")
        return reenc_path

    # Download karo
    print(f"  [S3-INJECT] ⬇️  Downloading s3://{S3_BUCKET_NAME_M}/{chosen_key} ...")
    try:
        s3 = _s3_client_m()
        s3.download_file(S3_BUCKET_NAME_M, chosen_key, local_path)
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        print(f"  [S3-INJECT] ✅ Downloaded → {filename} ({size_mb:.1f} MB)")
    except (BotoCoreError, ClientError) as e:
        print(f"  [S3-INJECT] ❌ Download failed: {e}")
        if os.path.exists(local_path):
            os.remove(local_path)
        return None

    # Re-encode karo bulletin format mein
    # return _reencode_for_bulletin(local_path)
    return local_path

def fetch_whoiswho_bulletin(channel_name: str = None) -> Optional[str]:
    """Location-wise whoiswho clip.
    channel_name (e.g. 'Kakinada') ke saath: TIER1 apna district -> TIER2 same-state
    siblings -> TIER3 global per-id pool. Bina arg: TIER1/2 skip (no ids) -> seedha
    TIER3 — yaani SAARE per-id clips par random, legacy flat whoiswho_*.mp4 excluded.
    Never raises; total failure pe None (build segment skip karta, bulletin banta)."""
    return _fetch_location_clip('whoiswho/outputs/', channel_name, 'whoiswho')


def fetch_publicvoice_bulletin(channel_name: str = None) -> Optional[str]:
    """Public-voice clip: public_voice/outputs/<backend_id>/<date>/*.mp4 se.
    Wo prefix S3 par ABHI exist nahi karta — jab tak upstream render karke outputs/
    nahi bharta, ye silently None deta hai (quiet=True: empty prefix par zero log
    lines; empty list S3 error nahi to _list_mp4_keys bhi kuch print nahi karta).
    Jaan-bujhke public_voice/videos/ KABHI nahi padhta — wo raw user uploads hain,
    broadcast-ready nahi."""
    return _fetch_location_clip('public_voice/outputs/', channel_name,
                                'publicvoice', quiet=True)


# def fetch_ad_clips() -> List[Optional[str]]:  # duplicate — commented out
#     try:
#         s3  = _s3_client()
#         res = s3.list_objects_v2(Bucket=S3_BUCKET_NAME_M, Prefix='ads/outputs/')
#         mp4_files = [obj for obj in res.get('Contents', [])
#                      if obj['Key'].endswith('.mp4') and obj['Size'] > 0]
#         if not mp4_files:
#             print("  [AD-INJECT] ⚠️ No clips found")
#             return []
#         local_paths = []
#         for obj in mp4_files:
#             local_path = os.path.join(S3_INJECT_LOCAL_DIR, os.path.basename(obj['Key']))
#             if not (os.path.exists(local_path) and os.path.getsize(local_path) > 100_000):
#                 s3.download_file(S3_BUCKET_NAME_M, obj['Key'], local_path)
#                 print(f"  [AD-INJECT] ✅ Downloaded: {os.path.basename(local_path)}")
#             else:
#                 print(f"  [AD-INJECT] ✅ Cache hit: {os.path.basename(local_path)}")
#             local_paths.append(local_path)
#         return local_paths
#     except (BotoCoreError, ClientError) as e:
#         print(f"  [AD-INJECT] ❌ Error: {e}")
#         return []

def fetch_ad_clips() -> List[Optional[str]]:
    try:
        s3  = _s3_client()
        res = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix='ads/outputs/')
        mp4_files = [obj for obj in res.get('Contents', [])
                     if obj['Key'].endswith('.mp4') and obj['Size'] > 0]
        if not mp4_files:
            print("  [AD-INJECT] ⚠️ No clips found")
            return []
        local_paths = []
        for obj in mp4_files:
            local_path = os.path.join(S3_INJECT_LOCAL_DIR, os.path.basename(obj['Key']))
            s3_mtime   = obj.get('LastModified')

            local_exists = os.path.exists(local_path) and os.path.getsize(local_path) > 100_000
            s3_is_newer  = (
                local_exists and s3_mtime is not None and
                s3_mtime.timestamp() > os.path.getmtime(local_path)
            )
            if not local_exists or s3_is_newer:
                s3.download_file(S3_BUCKET_NAME, obj['Key'], local_path)
                reason = "updated on S3" if s3_is_newer else "not cached"
                print(f"  [AD-INJECT] ✅ Downloaded ({reason}): {os.path.basename(local_path)}")
            else:
                print(f"  [AD-INJECT] ✅ Cache hit: {os.path.basename(local_path)}")
            local_paths.append(local_path)
        random.shuffle(local_paths)
        return local_paths
    except (BotoCoreError, ClientError) as e:
        print(f"  [AD-INJECT] ❌ Error: {e}")
        return []


def fetch_local_ad_clips() -> List[str]:
    from config import BASE_DIR
    ads_dir = os.path.join(BASE_DIR, 'assets', 'ads1')
    if not os.path.exists(ads_dir):
        return []

    all_clips = [
        os.path.join(ads_dir, f)
        for f in os.listdir(ads_dir)
        if f.lower().endswith('.mp4')
        and '_reenc' not in f.lower()   # reenc files skip
        and os.path.getsize(os.path.join(ads_dir, f)) > 0
    ]

    # ← CHANGE: shuffle then pick 4
    random.shuffle(all_clips)
    chosen = all_clips[:4]

    print(f"  [AD-LOCAL] {len(all_clips)} ads available → picked {len(chosen)} randomly")
    for c in chosen:
        print(f"    → {os.path.basename(c)}")
    return chosen