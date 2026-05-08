"""
Central S3 storage helper — all upload/download operations go through here.
Uses our main S3 bucket (S3_BUCKET_NAME) by default.
"""
import io
import os
import threading
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

# ── S3 key prefixes ────────────────────────────────────────────────────────────
S3_PFX_INPUTS    = "items/inputs"     # items/inputs/{image|video|audio}/{filename}
S3_PFX_SCRIPTS   = "items/scripts"    # items/scripts/{filename}
S3_PFX_HEADLINES = "items/headlines"  # items/headlines/{filename}
S3_PFX_AUDIOS    = "items/audios"     # items/audios/{filename}
S3_PFX_CACHE     = "item_cache"       # item_cache/item_{counter}_video.mp4
S3_PFX_BULLETINS = "bulletins"        # bulletins/{channel}/{bul_name}.mp4

# Disable automatic checksum injection — prevents AwsChunkedWrapper (non-seekable)
# from wrapping the upload stream, which breaks botocore retry logic.
_BOTO_CONFIG = Config(
    request_checksum_calculation='when_required',
    response_checksum_validation='when_required',
)

# ── Singleton boto3 client ─────────────────────────────────────────────────────
_lock   = threading.Lock()
_client = None

def _get_client():
    global _client
    with _lock:
        if _client is None:
            _client = boto3.client(
                's3',
                region_name=os.getenv('AWS_REGION', 'ap-south-2'),
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                config=_BOTO_CONFIG,
            )
    return _client

def _bucket() -> str:
    return os.getenv('S3_BUCKET_NAME', '')


# ── Core operations ────────────────────────────────────────────────────────────

def _log(msg: str):
    """Print with UTF-8 fallback for Windows terminals that use cp1252."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode())


def upload_file(local_path: str, s3_key: str, bucket: str = None) -> Optional[str]:
    """Upload a local file to S3. Returns s3_key on success, None on failure."""
    if not local_path or not os.path.exists(local_path):
        _log(f"[S3] WARN upload_file: local file missing: {local_path}")
        return None
    bkt = bucket or _bucket()
    try:
        _get_client().upload_file(local_path, bkt, s3_key)
        _log(f"[S3] OK Uploaded: {s3_key}")
        return s3_key
    except Exception as e:
        _log(f"[S3] ERR Upload failed {s3_key}: {e}")
        return None


def download_file(s3_key: str, local_path: str, bucket: str = None) -> bool:
    """Download an S3 object to a local path. Creates parent dirs. Returns True on success."""
    bkt = bucket or _bucket()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        _get_client().download_file(bkt, s3_key, local_path)
        _log(f"[S3] OK Downloaded: {s3_key}")
        return True
    except ClientError as e:
        code = e.response.get('Error', {}).get('Code', '')
        if code in ('404', 'NoSuchKey'):
            _log(f"[S3] WARN Not found: {s3_key}")
        else:
            _log(f"[S3] ERR Download failed {s3_key}: {e}")
        return False
    except Exception as e:
        _log(f"[S3] ERR Download failed {s3_key}: {e}")
        return False


def file_exists(s3_key: str, bucket: str = None) -> bool:
    """Check if an S3 key exists without downloading."""
    bkt = bucket or _bucket()
    try:
        _get_client().head_object(Bucket=bkt, Key=s3_key)
        return True
    except ClientError:
        return False
    except Exception:
        return False


def upload_bytes(data: bytes, s3_key: str, bucket: str = None) -> Optional[str]:
    """Upload raw bytes to S3. Returns s3_key on success, None on failure."""
    bkt = bucket or _bucket()
    try:
        _get_client().upload_fileobj(io.BytesIO(data), bkt, s3_key)
        _log(f"[S3] OK Uploaded bytes: {s3_key}")
        return s3_key
    except Exception as e:
        _log(f"[S3] ERR Upload bytes failed {s3_key}: {e}")
        return None


def download_bytes(s3_key: str, bucket: str = None) -> Optional[bytes]:
    """Download an S3 object as raw bytes. Returns None on failure."""
    bkt = bucket or _bucket()
    try:
        buf = io.BytesIO()
        _get_client().download_fileobj(bkt, s3_key, buf)
        return buf.getvalue()
    except ClientError as e:
        code = e.response.get('Error', {}).get('Code', '')
        if code not in ('404', 'NoSuchKey'):
            _log(f"[S3] ERR Download bytes failed {s3_key}: {e}")
        return None
    except Exception as e:
        _log(f"[S3] ERR Download bytes failed {s3_key}: {e}")
        return None


def delete_file(s3_key: str, bucket: str = None) -> bool:
    """Delete an S3 object. Returns True on success."""
    bkt = bucket or _bucket()
    try:
        _get_client().delete_object(Bucket=bkt, Key=s3_key)
        return True
    except Exception as e:
        _log(f"[S3] ERR Delete failed {s3_key}: {e}")
        return False


# ── Async upload (fire-and-forget background thread) ─────────────────────────

def upload_file_async(local_path: str, s3_key: str, bucket: str = None):
    """Upload in a daemon thread — does not block caller."""
    threading.Thread(
        target=upload_file,
        args=(local_path, s3_key, bucket),
        daemon=True,
    ).start()


# ── S3 key builders ────────────────────────────────────────────────────────────

def key_for_input(media_type: str, filename: str) -> str:
    """items/inputs/{image|video|audio}/{filename}"""
    return f"{S3_PFX_INPUTS}/{media_type}/{filename}"


def key_for_script(filename: str) -> str:
    return f"{S3_PFX_SCRIPTS}/{filename}"


def key_for_headline(filename: str) -> str:
    return f"{S3_PFX_HEADLINES}/{filename}"


def key_for_audio(filename: str) -> str:
    return f"{S3_PFX_AUDIOS}/{filename}"


def key_for_item_cache(counter) -> str:
    return f"{S3_PFX_CACHE}/item_{counter}_video.mp4"


def key_for_bulletin_video(channel: str, bul_name: str) -> str:
    return f"{S3_PFX_BULLETINS}/{channel}/{bul_name}.mp4"


def key_for_bulletin_manifest(channel: str, bul_name: str) -> str:
    return f"{S3_PFX_BULLETINS}/{channel}/{bul_name}_manifest.json"


# ── Ensure local file exists (download from S3 if missing) ───────────────────

def ensure_local(local_path: str, s3_key: str, bucket: str = None) -> bool:
    """
    If local_path already exists, return True immediately.
    Otherwise try to download from S3.
    """
    if os.path.exists(local_path):
        return True
    return download_file(s3_key, local_path, bucket)
