"""
Configuration file for News Bot
"""
import os
from dotenv import load_dotenv

load_dotenv()


OPENAI_API_KEY       = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL         = os.getenv('OPENAI_MODEL', 'gpt-4o')
OPENAI_HEADLINE_MODEL = os.getenv('OPENAI_HEADLINE_MODEL', 'gpt-4o-mini')  # ADD THIS
OPENAI_WHISPER_MODEL = os.getenv('OPENAI_WHISPER_MODEL', 'gpt-4o-transcribe')
SARVAM_API_KEY       = os.getenv('SARVAM_API_KEY', '')
MAX_TTS_CONCURRENCY  = int(os.getenv('MAX_TTS_CONCURRENCY', '3'))


def get_channel_tts_provider(channel_name: str) -> str:
    """
    Returns 'sarvam' or 'gcp' for the given channel.

    .env examples:
        TTS_PROVIDER_KURNOOL=gcp          ← Kurnool uses GCP TTS
        TTS_PROVIDER_KARIMNAGAR=gcp       ← Karimnagar uses GCP TTS
        TTS_PROVIDER_DEFAULT=sarvam       ← fallback for all others (default: sarvam)
    """
    env_key  = f"TTS_PROVIDER_{channel_name.upper().replace(' ', '_').replace('-', '_')}"
    provider = os.getenv(env_key, os.getenv('TTS_PROVIDER_DEFAULT', 'sarvam')).lower()
    print(f"[TTS-CFG] channel='{channel_name}' | env_key='{env_key}' | value='{os.getenv(env_key)}' | resolved='{provider}'")
    return provider

GUPSHUP_API_KEY       = os.getenv('GUPSHUP_API_KEY', '')
GUPSHUP_APP_NAME      = os.getenv('GUPSHUP_APP_NAME', '')
GUPSHUP_SOURCE_NUMBER = os.getenv('GUPSHUP_SOURCE_NUMBER', '')

PORT = os.getenv('PORT', '8001')

HEYGEN_API_KEY = os.getenv('HEYGEN_API_KEY', '')
DID_API_KEY    = os.getenv('DID_API_KEY', '')


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_INPUT_DIR  = os.path.join(BASE_DIR, 'inputs')
BASE_OUTPUT_DIR = os.path.join(BASE_DIR, 'outputs')

INPUT_IMAGE_DIR = os.path.join(BASE_INPUT_DIR, 'images')
INPUT_VIDEO_DIR = os.path.join(BASE_INPUT_DIR, 'videos')
INPUT_AUDIO_DIR = os.path.join(BASE_INPUT_DIR, 'audios')

OUTPUT_SCRIPT_DIR   = os.path.join(BASE_OUTPUT_DIR, 'scripts')
OUTPUT_HEADLINE_DIR = os.path.join(BASE_OUTPUT_DIR, 'headlines')
OUTPUT_AUDIO_DIR    = os.path.join(BASE_OUTPUT_DIR, 'audios')
PREFIX_IMAGE        = 'i'
PREFIX_VIDEO        = 'v'
PREFIX_AUDIO        = 'a'
PREFIX_SCRIPT       = 's'
PREFIX_HEADLINE     = 'h'
PREFIX_OUTPUT_AUDIO = 'oa'

REPORTER_PHOTO_DIR = os.path.join(BASE_OUTPUT_DIR, "reporters")
os.makedirs(REPORTER_PHOTO_DIR, exist_ok=True)

SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.m4a', '.ogg']

INTRO_VIDEO_DURATION       = 27
HEADLINE_DURATION_PER_ITEM = 4
ADDRESS_GIF_PATH = os.path.join(BASE_DIR, 'assets', 'address.gif')  # path adjust karo
REPORTER_DURATION = 5 
API_BASE_URL = "https://srv1264596.hstgr.cloud"
BGM_PATH         = os.path.join(BASE_DIR, 'news_intro.mpeg')
BGM_VOLUME       = float(os.getenv('BGM_VOLUME', '0.25'))
BGM_ENABLED      = os.getenv('BGM_ENABLED', 'true').lower() != 'false'
BGM_FADE_SECONDS = 2.5

BREAK_DURATION          = 2
WORDS_PER_SECOND_TELUGU = 2.2
MAX_WORDS_PER_SCRIPT    = int(60 * WORDS_PER_SECOND_TELUGU)
MAX_WORDS_PER_HEADLINE  = int(HEADLINE_DURATION_PER_ITEM * WORDS_PER_SECOND_TELUGU)
FIVE_MIN_INJECT_ENABLED = os.getenv('FIVE_MIN_INJECT_ENABLED', 'true').lower() != 'false'




LOCAL_ADS_DIR = os.path.join(BASE_DIR, 'assets', 'ads1')  # local mp4 folder
WHOISWHO_DURATION_RESERVE = 60   # seconds
BULLETIN_DURATIONS = [5, 10] 


TELUGU_NEWS_SCRIPT_PROMPT = f"""You are an expert Telugu news script writer for a professional television news bulletin.

YOUR TASK:
Generate a complete, broadcast-ready Telugu news script from the provided content.

STRICT REQUIREMENTS:
1. CRITICAL WORD LIMIT:
   - Maximum {MAX_WORDS_PER_SCRIPT} words
2. CONTENT PURITY:
   - Write ONLY the news story content
   - NO openings: No "నమస్కారం", "శుభోదయం", "ఈ రోజు వార్తలు"
   - NO closings: No "ధన్యవాదాలు", "మళ్ళీ కలుద్దాం", sign-offs
   - NO time references: No "ఒక గంట క్రితం", "ఈ రోజు", "నిన్న"
   - NO meta commentary: No "ఇప్పుడు వార్త చూద్దాం"
   - Start directly with the news story

3. LANGUAGE QUALITY:
   - Use formal, professional Telugu (వ్యవహారిక తెలుగు)
   - Write in active voice for impact
   - Use proper Telugu journalism terminology
   - Keep sentences clear, concise, and powerful
   - Average sentence length: 15-20 words
   - Use connectors for smooth flow (అయితే, కాగా, మరోవైపు)

4. STRUCTURE:
   - Lead paragraph: Most important facts (who, what, when, where)
   - Body: Supporting details only — NO repetition of lead facts
   - Conclusion: Impact or next steps
   - Each paragraph: 2-3 sentences maximum
   - NEVER repeat the same fact, name, or phrase twice

5. READABILITY:
   - Write for spoken delivery (easy to read aloud)
   - Avoid complex compound sentences
   - Use punctuation that helps with breathing pauses
   - Prefer Telugu words over English transliterations when possible

6. TONE:
   - Maintain journalistic neutrality
   - Be factual and authoritative
   - Show appropriate gravity for serious news

7. FORMATTING:
   - Use proper Telugu script throughout
   - Paragraph breaks for clarity
   - No bullet points or numbering

REMEMBER: You are creating content for a news anchor on live television. Every word matters.

LANGUAGE ENFORCEMENT: Input may arrive in Urdu, Hindi, English, or any other language. You MUST translate and rewrite it entirely into Telugu. Output must contain ONLY Telugu script (తెలుగు లిపి). Zero tolerance for Urdu, Hindi, Arabic, or English words in the output."""

TELUGU_HEADLINE_PROMPT = f"""You are an expert Telugu news headline writer.

REQUIREMENTS:
1. LENGTH: Maximum 4-5 words maximum 2 lines
2. DURATION: Must fit in {HEADLINE_DURATION_PER_ITEM} seconds when spoken
3. STYLE: Past tense, action-first (ఏం జరిగింది format)
4. CONTENT: Most important single fact — person + action or place + event
5. LANGUAGE: Pure Telugu, no English mixing, no verbs ending in -తుంది/-స్తుంది
6. AVOID: Questions, exclamation marks, conjunctions, filler words

GOOD EXAMPLES:
  చెన్నైలో తుఫాను దెబ్బ
  భారత సైన్యం విజయం
  డావోస్‌లో మోదీ ప్రసంగం

OUTPUT: Headline only — nothing else."""


# ================================
# Editorial Planner Prompts
# ================================
WORDS_PER_SECOND_TTS = 2.2
EDITORIAL_PLANNER_PROMPT = f"""
You are a professional Telugu broadcast news editor. 
Produce a news story that fits inside 59 seconds total (TTS narration + video clip combined).

════════════════════════════════════════════
TIMING BUDGET  (must not exceed 59 seconds)
════════════════════════════════════════════
  Hook        :  ~5s   → {round(5  * WORDS_PER_SECOND_TTS)} Telugu words  (tts_intro opening)
  Context     : ~10s   → {round(10 * WORDS_PER_SECOND_TTS)} Telugu words  (tts_intro continuation)
  ── tts_intro total: ~15s / {round(15 * WORDS_PER_SECOND_TTS)} words ──
  Video clip  : 8–20s  (extracted from input video — most relevant segment only)
  Analysis    : ~12s   → {round(12 * WORDS_PER_SECOND_TTS)} Telugu words  (tts_analysis opening)
  Closing     :  ~4s   → {round(4  * WORDS_PER_SECOND_TTS)} Telugu words  (tts_analysis closing line)
  ── tts_analysis total: ~16s / {round(16 * WORDS_PER_SECOND_TTS)} words ──

  MAX clip duration  : 20 seconds
  MIN clip duration  :  8 seconds
  MAX tts_intro      : {round(15 * WORDS_PER_SECOND_TTS)} words
  MAX tts_analysis   : {round(16 * WORDS_PER_SECOND_TTS)} words
  HARD TOTAL CEILING : 59 seconds

════════════════════════════════════════════
CLIP SELECTION
════════════════════════════════════════════
- Pick the single most visually/emotionally relevant 8–20s segment
- Do NOT use the full video
- Prefer segments with: strong speech, key action, or emotional peak
- clip.start and clip.end must be floats from the actual transcript timestamps
- score: 0.0–1.0

════════════════════════════════════════════
STRUCTURE CHOICE  (pick one)
════════════════════════════════════════════
  "intro_clip_analysis"  → DEFAULT. Clip needs setup first.
  "clip_intro_analysis"  → BREAKING. Clip is self-explanatory, leads with impact.
  "intro_analysis_clip"  → INVESTIGATIVE. Clip is proof/evidence shown at end.

════════════════════════════════════════════
WRITING RULES
════════════════════════════════════════════
  tts_intro  must contain:
    • Hook sentence: the single most important fact (who/what/where)
    • Context: brief background so viewer understands the clip
    • End with a smooth lead-in line into what comes next
    • STRICT MAX: {round(15 * WORDS_PER_SECOND_TTS)} Telugu words

  tts_analysis must contain:
    • Why this matters / impact
    • What happens next OR key takeaway
    • Final closing line (e.g. "ఈ విషయంలో మరిన్ని వివరాలు రానున్నాయి.")
    • STRICT MAX: {round(16 * WORDS_PER_SECOND_TTS)} Telugu words
  
  NEVER reference the video or clip in narration.
  ❌ No "ఈ వీడియోలో", "ఈ క్లిప్‌లో", "video lo", "clip lo", or any variant.
  The anchor speaks the story — the clip plays silently behind them.
  
  LANGUAGE: ALL tts_intro and tts_analysis output MUST be in Telugu script (తెలుగు లిపి) only.
  Zero tolerance for English, Urdu, Hindi, or Arabic words in those fields.
  Translate all input content into Telugu before writing.

════════════════════════════════════════════
OUTPUT — strict JSON only, no extra text:
════════════════════════════════════════════
{{
  "structure": "intro_clip_analysis" | "clip_intro_analysis" | "intro_analysis_clip",
  "clip": {{
    "start": float,
    "end":   float,
    "text":  "...",
    "score": float
  }},
  "tts_intro":    "...",
  "tts_analysis": "..."
}}
"""

# ── LocalAI TV Incidents API ──────────────────────────────────────────────
LOCALAITV_API_URL     = os.getenv('LOCALAITV_API_URL', 'https://localaitv.com/api/incidents')
LOCALAITV_API_TOKEN   = os.getenv('LOCALAITV_API_TOKEN', '')
# LOCALAITV_LOCATION_ID = int(os.getenv('LOCALAITV_LOCATION_ID', '1'))
LOCALAITV_CATEGORY_ID = int(os.getenv('LOCALAITV_CATEGORY_ID', '1'))
BULLETIN_API_TOKEN = os.getenv('BULLETIN_API_TOKEN', '')


# ── Location Resolution ───────────────────────────────────────────────────────
DEFAULT_LOCATION_ID   = 0
DEFAULT_LOCATION_NAME = "General"

LOCATION_MAP = {
    # Telangana
    "hyderabad":    1,
    "warangal":     2,
    "nizamabad":    3,
    "khammam":      4,
    "karimnagar":   5,
    "ramagundam":   6,
    "mahbubnagar":  7,
    "nalgonda":     8,
    "adilabad":     9,
    "suryapet":     10,
    "miryalaguda":  11,
    "siddipet":     12,
    "jagtial":      13,
    "mancherial":   14,
    "sangareddy":   15,
    "medak":        16,
    "vikarabad":    17,
    "wanaparthy":   18,
    "jogulamba":    19,
    "bhadradri":    20,
    # Andhra Pradesh
    "kurnool":      21,
    "vizag":        22,
    "visakhapatnam":22,
    "vijayawada":   23,
    "tirupati":     24,
    "guntur":       25,
    "nellore":      26,
    "kadapa":       27,
    "anantapur":    28,
    "kakinada":     29,
    "rajahmundry":  30,
    "eluru":        31,
    "ongole":       32,
    "srikakulam":   33,
    "vizianagaram": 34,
    "chittoor":     35,
    "hindupur":     36,
    "tenali":       37,
    "proddatur":    38,
    "nandyal":      39,
    "machilipatnam":40,
    "Madhapur":      41,
    "madhapur":          41,
    "vittal rao nagar":  41,   # logs mein yahi dikh raha tha loc_id=544282 wala
    "hitech city":       41,
    "jubilee hills":     41,   # nearby areas bhi Madhapur bulletin mein chahiye toh
    "film nagar":        41,
}



# config.py — LOCATION_MAP ke baad

import hashlib as _hashlib


def get_loc_id_from_address(address: str) -> int:
    if not address:
        return 0
    addr_lower = address.lower().strip()

    # ✅ FIX: Sub-area priority check PEHLE karo (Hyderabad se pehle match hona chahiye)
    PRIORITY_MAP = {
        "madhapur":         41,
        "vittal rao nagar": 41,
        "hitech city":      41,
        "jubilee hills":    41,
        "banjara hills":    41,
        "gachibowli":       41,
        "film nagar":       41,
    }
    for key, loc_id in PRIORITY_MAP.items():
        if key in addr_lower:
            return loc_id

    # Existing keyword match
    for key, loc_id in LOCATION_MAP.items():
        if key.lower() in addr_lower:
            return loc_id

    # Fallback: hash-based ID
    hash_id = int(_hashlib.md5(addr_lower.encode()).hexdigest()[:5], 16) + 10000
    return hash_id

# ── Ticker Overlay ────────────────────────────────────────────────────────────
# ── Item Video Cache ─────────────────────────────────────────────────────────
# Pre-built item videos stored here so next bulletin can reuse instantly.
# Never deleted automatically — lives outside bulletin folders.
ITEM_VIDEO_CACHE_DIR = os.path.join(BASE_OUTPUT_DIR, 'item_video_cache')
os.makedirs(ITEM_VIDEO_CACHE_DIR, exist_ok=True)

TICKER_PNG_PATH  = os.path.join(BASE_DIR, 'assets', 'ticker2.png')
ADS_FOLDER_PATH  = os.path.join(BASE_DIR, 'assets', 'ads')   # .txt files, one ad per file
os.makedirs(ADS_FOLDER_PATH, exist_ok=True)

TICKER_HEADLINE_SPEED    = 220   # px/sec — white band scroll speed
TICKER_AD_SPEED          = 180   # px/sec — red band scroll speed
TICKER_HEADLINE_Y        = 722   # white band vertical centre (px from top)
TICKER_AD_Y              = 762   # red band vertical centre (px from top)
TICKER_HEADLINE_FONTSIZE = 32
TICKER_AD_FONTSIZE       = 30
TICKER_ENABLED           = os.getenv('TICKER_ENABLED', 'true').lower() != 'false'



# ── AWS S3 Storage ────────────────────────────────────────────────────────────
# ── S3 Injected Bulletin ──────────────────────────────────────────────────────
S3_INJECT_ENABLED       = os.getenv('S3_INJECT_ENABLED', 'true').lower() != 'false'
S3_BUCKET_NAME          = os.getenv('S3_BUCKET_NAME', '')        # our own bucket (ads, static assets, bulletins)
S3_BUCKET_NAME_M        = os.getenv('S3_BUCKET_NAME_M', '')      # external bucket (whoiswho, vege, trainroutes)
S3_BULLETIN_PREFIX = os.getenv('S3_BULLETIN_PREFIX', 'whoiswho/outputs')
S3_REGION = os.getenv('AWS_REGION_M', 'ap-south-2')   # ← 2
S3_INJECT_LOCAL_DIR     = os.path.join(BASE_OUTPUT_DIR, 's3_inject_cache')
os.makedirs(S3_INJECT_LOCAL_DIR, exist_ok=True)

S3_INJECT_DURATION = int(os.getenv('S3_INJECT_DURATION', '60'))  # seconds

# ── Database ──────────────────────────────────────────────────────────────────
# Default: SQLite file alongside the project.  Override with a full
# postgresql://user:pass@host:5432/dbname URL in production.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/news_bulletin.db")

# ── Static Asset Bootstrap (S3 → local) ───────────────────────────────────────
S3_STATIC_PREFIX = os.getenv('S3_STATIC_PREFIX', 'static-assets')

# All static assets the app needs locally — relative to BASE_DIR
_STATIC_ASSETS = [
    'assets/address.gif',
    'assets/ticker2.png',
    'assets/ticker3.png',
    'assets/ticker4.png',
    'assets/kurnool_and_local.png',
    'assets/filler.mp4',
    'assets/break.mp4',
    'assets/cap1.mp4',
    'assets/template4.mp4',
    'assets/logo3.mov',
    'assets/intro4.mp4',
    'assets/Gidugu Regular.otf',
    'news_intro.mpeg',
    # Fonts — downloaded only if Linux system fonts (fonts-noto) are not installed
    'NotoSansTelugu.ttf',
    'seguiemj.ttf',
]

_SYSTEM_FONT_SUBSTITUTES = {
    # If any system path exists, skip downloading the local fallback
    'NotoSansTelugu.ttf': [
        '/usr/share/fonts/truetype/noto/NotoSansTelugu-Bold.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf',
        '/usr/share/fonts/noto/NotoSansTelugu-Bold.ttf',
    ],
    'seguiemj.ttf': [
        '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
        '/usr/share/fonts/noto/NotoColorEmoji.ttf',
    ],
}

def ensure_assets():
    """Download missing static assets from S3. Skips files that already exist locally
    or whose system-font substitutes are present (avoids redundant font downloads)."""
    import boto3
    from botocore.config import Config as _BotoConfig

    def _needs_download(asset: str) -> bool:
        if os.path.exists(os.path.join(BASE_DIR, asset)):
            return False
        fname = os.path.basename(asset)
        for sys_path in _SYSTEM_FONT_SUBSTITUTES.get(fname, []):
            if os.path.exists(sys_path):
                return False  # system font available — local copy not needed
        return True

    missing = [a for a in _STATIC_ASSETS if _needs_download(a)]
    if not missing:
        return

    _cfg = _BotoConfig(
        request_checksum_calculation='when_required',
        response_checksum_validation='when_required',
    )
    s3 = boto3.client('s3', region_name=S3_REGION,
                      aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                      aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                      config=_cfg)
    for asset in missing:
        local_path = os.path.join(BASE_DIR, asset)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        s3_key = f"{S3_STATIC_PREFIX}/{asset}"
        try:
            s3.download_file(S3_BUCKET_NAME, s3_key, local_path)
            print(f"[assets] ✅ Downloaded: {asset}")
        except Exception as e:
            print(f"[assets] ⚠️ Could not download {asset}: {e}")
# ─────────────────────────────────────────────────────────────────────────────