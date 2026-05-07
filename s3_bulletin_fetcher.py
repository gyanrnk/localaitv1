"""
S3 se pre-built 1-min bulletin video randomly fetch karo.
Sirf boto3 + random logic — video_builder.py ko clean rakhne ke liye alag file.
"""
import json
import os
import random
import subprocess
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from typing import List, Optional

from config import (
    S3_BUCKET_NAME_M,
    S3_BULLETIN_PREFIX,
    S3_REGION,
    S3_INJECT_LOCAL_DIR,
)


def _s3_client():
    return boto3.client(
        's3',
        region_name=S3_REGION,
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    )


def list_s3_bulletins() -> list:
    """S3 prefix ke andar saare .mp4 files list karo."""
    try:
        s3  = _s3_client()
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
        s3 = _s3_client()
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

def fetch_whoiswho_bulletin() -> Optional[str]:
    try:
        s3  = _s3_client()
        res = s3.list_objects_v2(Bucket=S3_BUCKET_NAME_M, Prefix='whoiswho/outputs/')
        mp4_files = [obj for obj in res.get('Contents', [])
                     if obj['Key'].endswith('.mp4') and obj['Size'] > 0]
        if not mp4_files:
            print("  [WHOISWHO] ⚠️ No clip found")
            return None

        # ← CHANGE: random pick instead of latest
        chosen = random.choice(mp4_files)
        local_path = os.path.join(S3_INJECT_LOCAL_DIR, os.path.basename(chosen['Key']))
        if os.path.exists(local_path) and os.path.getsize(local_path) > 100_000:
            print(f"  [WHOISWHO] ✅ Cache hit: {os.path.basename(local_path)}")
            return local_path
        s3.download_file(S3_BUCKET_NAME_M, chosen['Key'], local_path)
        print(f"  [WHOISWHO] ✅ Downloaded: {os.path.basename(local_path)}")
        return local_path
    except (BotoCoreError, ClientError) as e:
        print(f"  [WHOISWHO] ❌ Error: {e}")
        return None


def fetch_ad_clips() -> List[Optional[str]]:
    try:
        s3  = _s3_client()
        res = s3.list_objects_v2(Bucket=S3_BUCKET_NAME_M, Prefix='ads/outputs/')
        mp4_files = [obj for obj in res.get('Contents', [])
                     if obj['Key'].endswith('.mp4') and obj['Size'] > 0]
        if not mp4_files:
            print("  [AD-INJECT] ⚠️ No clips found")
            return []
        local_paths = []
        for obj in mp4_files:
            local_path = os.path.join(S3_INJECT_LOCAL_DIR, os.path.basename(obj['Key']))
            if not (os.path.exists(local_path) and os.path.getsize(local_path) > 100_000):
                s3.download_file(S3_BUCKET_NAME_M, obj['Key'], local_path)
                print(f"  [AD-INJECT] ✅ Downloaded: {os.path.basename(local_path)}")
            else:
                print(f"  [AD-INJECT] ✅ Cache hit: {os.path.basename(local_path)}")
            local_paths.append(local_path)
        return local_paths
    except (BotoCoreError, ClientError) as e:
        print(f"  [AD-INJECT] ❌ Error: {e}")
        return []
    
def fetch_ad_clips() -> List[Optional[str]]:
    try:
        s3  = _s3_client()
        res = s3.list_objects_v2(Bucket=S3_BUCKET_NAME_M, Prefix='ads/outputs/')
        mp4_files = [obj for obj in res.get('Contents', [])
                     if obj['Key'].endswith('.mp4') and obj['Size'] > 0]
        if not mp4_files:
            print("  [AD-INJECT] ⚠️ No clips found")
            return []
        local_paths = []
        for obj in mp4_files:
            local_path = os.path.join(S3_INJECT_LOCAL_DIR, os.path.basename(obj['Key']))
            if not (os.path.exists(local_path) and os.path.getsize(local_path) > 100_000):
                s3.download_file(S3_BUCKET_NAME_M, obj['Key'], local_path)
                print(f"  [AD-INJECT] ✅ Downloaded: {os.path.basename(local_path)}")
            else:
                print(f"  [AD-INJECT] ✅ Cache hit: {os.path.basename(local_path)}")
            local_paths.append(local_path)
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