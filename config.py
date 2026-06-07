"""
Configuration file for News Bot
"""
import os
from dotenv import load_dotenv

load_dotenv()


OPENAI_API_KEY        = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL          = os.getenv('OPENAI_MODEL', 'gpt-4o')
OPENAI_HEADLINE_MODEL = os.getenv('OPENAI_HEADLINE_MODEL', 'gpt-4o-mini')
OPENAI_WHISPER_MODEL  = os.getenv('OPENAI_WHISPER_MODEL', 'gpt-4o-transcribe')
GEMINI_API_KEY        = os.getenv('GEMINI_API_KEY', '')
# NOTE: gemini-2.5-PRO is a heavy "thinking" model — on the OpenAI-compat
# endpoint its reasoning tokens are counted inside max_tokens, so script/headline
# calls (max_tokens 80-2000) return EMPTY with finish_reason=length. Use a flash
# model (minimal thinking) for fast text gen. Overridable via .env GEMINI_MODEL.
GEMINI_MODEL          = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

# --- Vertex AI (GCP postpay) mode -------------------------------------------
# When GEMINI_USE_VERTEX=true, GeminiHandler talks to Vertex AI's
# OpenAI-compatible endpoint instead of AI Studio. Auth is a short-lived GCP
# access token (refreshed automatically) derived from either:
#   - a service-account key file (GOOGLE_APPLICATION_CREDENTIALS=...vertex-key.json), or
#   - Application Default Credentials (`gcloud auth application-default login`).
# No GEMINI_API_KEY is needed in Vertex mode. Leave unset to keep AI Studio.
GEMINI_USE_VERTEX     = os.getenv('GEMINI_USE_VERTEX', '').lower() in ('1', 'true', 'yes')
VERTEX_PROJECT        = os.getenv('VERTEX_PROJECT', 'localaitv')
VERTEX_LOCATION       = os.getenv('VERTEX_LOCATION', 'us-central1')

SARVAM_API_KEY        = os.getenv('SARVAM_API_KEY', '')
MAX_TTS_CONCURRENCY  = int(os.getenv('MAX_TTS_CONCURRENCY', '3'))


def get_channel_intro_path(channel_name: str, base_dir: str = None) -> str:
    """
    Returns channel-specific intro video path.
    Looks for assets/intro_{channel_lower}.mp4 first, falls back to assets/intro4.mp4.

    File naming convention on VPS:
        assets/intro_kurnool.mp4
        assets/intro_guntur.mp4
        assets/intro_warangal.mp4
        assets/intro_nalgonda.mp4
        assets/intro4.mp4          <- default fallback
    """
    _base = base_dir or BASE_DIR
    channel_key = channel_name.lower().replace(' ', '_').replace('-', '_')
    specific = os.path.join(_base, 'assets', f'intro_{channel_key}.mp4')
    if os.path.exists(specific):
        return specific
    return os.path.join(_base, 'assets', 'intro4.mp4')


def get_channel_logo_path(channel_name: str, base_dir: str = None) -> str:
    """
    Returns channel-specific logo path.
    Checks .gif, .mov, .mp4 in that order, falls back to assets/logo3.mov.

    File naming convention on VPS:
        assets/logo_kurnool.gif   (or .mov / .mp4)
        assets/logo_guntur.gif
        assets/logo3.mov          <- default fallback
    """
    _base = base_dir or BASE_DIR
    channel_key = channel_name.lower().replace(' ', '_').replace('-', '_')
    for ext in ('.gif', '.mov', '.mp4'):
        specific = os.path.join(_base, 'assets', f'logo_{channel_key}{ext}')
        if os.path.exists(specific):
            return specific
    return os.path.join(_base, 'assets', 'logo3.mov')


def get_channel_cap1_path(channel_name: str, base_dir: str = None) -> str:
    """
    Returns channel-specific cap1 (break-news) video path.
    Looks for assets/cap1_{channel_lower}.mp4 first, falls back to assets/cap1.mp4.

    File naming convention on VPS:
        assets/cap1_kurnool.mp4
        assets/cap1_karimnagar.mp4
        assets/cap1_tirupati.mp4
        assets/cap1.mp4          <- default fallback
    """
    _base = base_dir or BASE_DIR
    channel_key = channel_name.lower().replace(' ', '_').replace('-', '_')
    specific = os.path.join(_base, 'assets', f'cap1_{channel_key}.mp4')
    if os.path.exists(specific):
        return specific
    return os.path.join(_base, 'assets', 'cap1.mp4')


def get_anchor_clip(base_dir: str = None) -> str:
    """Pick a RANDOM 'welcome anchor' clip from assets/anchors/ (shared pool).

    Played right after the channel intro per the Production Manual §8
    (Channel Intro → Welcome Anchor → Headlines). Returns '' if the folder is
    empty/missing — the caller then skips the anchor segment gracefully.

    File convention: assets/anchors/anchor1.mp4, anchor2.mp4, ...
    """
    import glob, random
    _base = base_dir or BASE_DIR
    clips = sorted(glob.glob(os.path.join(_base, 'assets', 'anchors', '*.mp4')))
    if not clips:
        return ''
    return random.choice(clips)


def get_ending_anchor_clip(base_dir: str = None) -> str:
    """Pick a RANDOM 'ending anchor' clip from assets/anchors_end/ (shared pool).

    Played at the END of the bulletin — after the last news/injection, just
    before the short tail filler (… News → Injections → Ending Anchor → Filler).
    Returns '' if the folder is empty/missing — the caller then skips the ending
    anchor segment gracefully (and reserves no budget for it).

    File convention: assets/anchors_end/anchor_end1.mp4, anchor_end2.mp4, ...
    """
    import glob, random
    _base = base_dir or BASE_DIR
    clips = sorted(glob.glob(os.path.join(_base, 'assets', 'anchors_end', '*.mp4')))
    if not clips:
        return ''
    return random.choice(clips)


def get_anchor_pair(base_dir: str = None):
    """Return a (welcome, ending) anchor clip PAIR for the SAME person.

    Manual v2 §13: "Opening anchor and closing anchor must be the same person."
    Pairing is by the index in the filename — assets/anchors/anchor{N}.mp4 is the
    SAME person as assets/anchors_end/anchor_end{N}.mp4. We pick a random N for
    which BOTH a welcome clip and a matching ending clip exist, so opening and
    closing are always the same anchor.

    Graceful fallbacks (so a bulletin never crashes over anchors):
      - No matching ending for any welcome → (welcome, '')  [ending skipped;
        we never pair mismatched people, that would violate §13]
      - No welcome clips at all            → ('', '')

    Returns (welcome_path, ending_path); '' for a missing side.

    File convention (operator MUST keep indices aligned per person):
      assets/anchors/anchor1.mp4      ↔ assets/anchors_end/anchor_end1.mp4
      assets/anchors/anchor2.mp4      ↔ assets/anchors_end/anchor_end2.mp4
    """
    import glob, random, re
    _base = base_dir or BASE_DIR
    welcome_clips = sorted(glob.glob(os.path.join(_base, 'assets', 'anchors',     '*.mp4')))
    ending_clips  = sorted(glob.glob(os.path.join(_base, 'assets', 'anchors_end', '*.mp4')))

    def _idx(path: str):
        m = re.search(r'(\d+)', os.path.basename(path))
        return m.group(1) if m else None

    if not welcome_clips:
        return ('', '')

    ending_by_idx = {}
    for e in ending_clips:
        k = _idx(e)
        if k is not None and k not in ending_by_idx:
            ending_by_idx[k] = e

    # Indices jinke liye dono (welcome + matching ending) maujood hain
    paired = [w for w in welcome_clips if _idx(w) in ending_by_idx]
    if paired:
        w = random.choice(paired)
        return (w, ending_by_idx[_idx(w)])

    # Koi matching ending nahi mila → §13 violate na ho, isliye sirf welcome
    # (closing anchor skip — mismatched person kabhi pair nahi karenge)
    return (random.choice(welcome_clips), '')


def get_ending_anchor_clip(base_dir: str = None) -> str:
    """Pick a RANDOM 'ending anchor' clip from assets/anchors_end/ (shared pool).

    Played at the END of the bulletin, right before the outro filler
    (… News → Injections → Ending Anchor → Filler). Returns '' if the folder
    is empty/missing — the caller then skips the ending anchor gracefully.

    File convention: assets/anchors_end/anchor_end1.mp4, anchor_end2.mp4, ...
    """
    import glob, random
    _base = base_dir or BASE_DIR
    clips = sorted(glob.glob(os.path.join(_base, 'assets', 'anchors_end', '*.mp4')))
    if not clips:
        return ''
    return random.choice(clips)


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
HEADLINE_DURATION_PER_ITEM = 8
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
ADS_ENABLED             = os.getenv('ADS_ENABLED', 'true').lower() != 'false'




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

HEADLINE_REVIEWER_PROMPT = """You are a professional TV news headline editor for LocalAI TV.

YOUR JOB:
Rewrite the given headline into the most powerful broadcast TV headline possible.

HOW TO REWRITE:
- Target: 6 to 8 words
- Strategy: combine words smartly, use strong verbs, drop filler words
- NEVER drop WHO, WHAT, WHERE — these are the core of any headline
- Use hyphens to combine related words
- If the original is already sharp and ≤8 words, return it unchanged

WHAT NOT TO DO:
- Do NOT cut the headline in the middle
- Do NOT drop location, action, or impact
- Do NOT add information not in the original
- Do NOT output more than 8 words

OUTPUT: Only the final headline. Nothing else."""

TELUGU_HEADLINE_PROMPT = """Write one Telugu TV news headline using this exact 4-slot formula:

  [సందర్భం] + [కర్త] + [కర్మ] + [క్రియ]

SLOT DEFINITIONS:
  [సందర్భం]  — 1-2 words  — WHERE or WHEN or CONTEXT  (e.g. హైదరాబాద్‌లో, ఏపీలో, నేడు)
  [కర్త]      — 1-2 words  — WHO did it               (e.g. పోలీసులు, ప్రభుత్వం, రైతులు)
  [కర్మ]      — 2-3 words  — WHAT — the object/action  (e.g. నిరసన కార్యక్రమం, భూసేకరణ నిర్ణయాన్ని)
  [క్రియ]     — 1 word     — VERB — past tense Telugu   (e.g. చేశారు, ప్రకటించింది, అరెస్టు చేశారు)

TOTAL: 6 to 8 words (never fewer than 6). Every slot must be filled. Sentence must end on the verb.

LANGUAGE: Telugu script only. Zero English, Hindi, Urdu words.

FORMAT: Output on 2 lines. Break naturally between [కర్త] and [కర్మ].

EXAMPLES:

  హైదరాబాద్‌లో పోలీసులు             ← సందర్భం + కర్త
  మాదక ద్రవ్యాల వ్యాపారిని అరెస్టు చేశారు  ← కర్మ + క్రియ
  (7 words — complete sentence)

  తెలంగాణ ప్రభుత్వం                  ← సందర్భం+కర్త merged
  కొత్త రైతు పథకాన్ని ప్రకటించింది   ← కర్మ + క్రియ
  (6 words — complete sentence)

  ఏపీలో భారీ వర్షాలకు               ← సందర్భం + కర్మ
  రైతుల పంటలు దెబ్బతిన్నాయి         ← కర్త+కర్మ+క్రియ
  (7 words — complete sentence)

WRONG (incomplete — ends on noun, no verb):
  ఏపీ రైతు సంఘం ఎరువుల పంపిణీ కార్యక్రమం

RIGHT (complete — verb at end):
  ఏపీ రైతు సంఘం ఎరువుల
  పంపిణీ కార్యక్రమం నిర్వహించింది

OUTPUT: Only the 2-line Telugu headline. Nothing else."""


# ================================
# Editorial Planner Prompts
# ================================
WORDS_PER_SECOND_TTS = 2.2
EDITORIAL_PLANNER_PROMPT = f"""
You are a professional Telugu broadcast news editor.
Produce a news story that fits inside 45 seconds total (TTS narration + video clip combined).
50/50 RULE: narration (tts_intro + tts_analysis) ≈ 22s = half the item; video clip ≈ 22s = other half.
Keep narration tight, complete and meaningful — full sentences only, never cut mid-thought.

════════════════════════════════════════════
TIMING BUDGET  (must not exceed 45 seconds)
════════════════════════════════════════════
  Hook        :  ~4s   → {round(4  * WORDS_PER_SECOND_TTS)} Telugu words  (tts_intro opening)
  Context     :  ~6s   → {round(6  * WORDS_PER_SECOND_TTS)} Telugu words  (tts_intro continuation)
  ── tts_intro total: ~10s / {round(10 * WORDS_PER_SECOND_TTS)} words ──
  Video clip  : 8–23s  (extracted from input video — most relevant segment only; ~22s = 50% half)
  Analysis    :  ~8s   → {round(8  * WORDS_PER_SECOND_TTS)} Telugu words  (tts_analysis opening)
  Closing     :  ~4s   → {round(4  * WORDS_PER_SECOND_TTS)} Telugu words  (tts_analysis closing line)
  ── tts_analysis total: ~12s / {round(12 * WORDS_PER_SECOND_TTS)} words ──

  MAX clip duration  : 23 seconds
  MIN clip duration  :  8 seconds
  MAX tts_intro      : {round(10 * WORDS_PER_SECOND_TTS)} words
  MAX tts_analysis   : {round(12 * WORDS_PER_SECOND_TTS)} words
  HARD TOTAL CEILING : 45 seconds

════════════════════════════════════════════
CLIP SELECTION
════════════════════════════════════════════
- Pick the single most visually/emotionally relevant 8–23s segment
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
    • STRICT MAX: {round(10 * WORDS_PER_SECOND_TTS)} Telugu words

  tts_analysis must contain:
    • Why this matters / impact
    • What happens next OR key takeaway
    • Final closing line (e.g. "ఈ విషయంలో మరిన్ని వివరాలు రానున్నాయి.")
    • STRICT MAX: {round(12 * WORDS_PER_SECOND_TTS)} Telugu words
  
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

# Static English → Telugu name map for bulletin titles (avoids LLM call for known cities)
LOCATION_TELUGU_MAP = {
    "hyderabad":     "హైదరాబాద్",
    "warangal":      "వరంగల్",
    "nizamabad":     "నిజామాబాద్",
    "khammam":       "ఖమ్మం",
    "karimnagar":    "కరీంనగర్",
    "ramagundam":    "రామగుండం",
    "mahbubnagar":   "మహబూబ్‌నగర్",
    "nalgonda":      "నల్గొండ",
    "adilabad":      "ఆదిలాబాద్",
    "suryapet":      "సూర్యాపేట",
    "miryalaguda":   "మిర్యాలగూడ",
    "siddipet":      "సిద్దిపేట",
    "jagtial":       "జగిత్యాల",
    "mancherial":    "మంచిర్యాల",
    "sangareddy":    "సంగారెడ్డి",
    "medak":         "మేడక్",
    "vikarabad":     "వికారాబాద్",
    "wanaparthy":    "వనపర్తి",
    "jogulamba":     "జోగులాంబ",
    "bhadradri":     "భద్రాద్రి",
    "kurnool":       "కర్నూల్",
    "vizag":         "విశాఖపట్నం",
    "visakhapatnam": "విశాఖపట్నం",
    "vijayawada":    "విజయవాడ",
    "tirupati":      "తిరుపతి",
    "guntur":        "గుంటూర్",
    "nellore":       "నెల్లూరు",
    "kadapa":        "కడప",
    "anantapur":     "అనంతపురం",
    "kakinada":      "కాకినాడ",
    "rajahmundry":   "రాజమహేంద్రవరం",
    "eluru":         "ఏలూరు",
    "ongole":        "ఒంగోలు",
    "srikakulam":    "శ్రీకాకుళం",
    "vizianagaram":  "విజయనగరం",
    "chittoor":      "చిత్తూరు",
    "hindupur":      "హిందూపురం",
    "tenali":        "తెనాలి",
    "proddatur":     "ప్రొద్దుటూరు",
    "nandyal":       "నంద్యాల",
    "machilipatnam": "మచిలీపట్నం",
    "madhapur":      "మాధాపూర్",
    "hyderabad madhapur": "మాధాపూర్",
    "news":          "వార్త",
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


# ── Classified-form location bulletins (EXT bucket) ─────────────────────────
# EXT bucket stores classified videos as {form}/outputs/{backend_id}/...
# These BACKEND ids are a SEPARATE id-space from LOCATION_MAP (1..41) — resolved
# ONCE via GET /api/locations/{id}, baked here. Runtime NEVER calls the API.
# NOTE: backend 75/141/... are unrelated to LOCATION_MAP's 1..41 — keep separate.
CLASSIFIED_LOCATION_MAP = {
    # "<backend_id>": {"channel": "<stream channel key>", "telugu": "<name>"}
    "75":  {"channel": "karimnagar", "telugu": "కరీంనగర్"},
    "141": {"channel": "nalgonda",   "telugu": "నల్గొండ"},
    "154": {"channel": "warangal",   "telugu": "వరంగల్"},
    "161": {"channel": "khammam",    "telugu": "ఖమ్మం"},     # content hai, par stream channel nahi (abhi skip)
    "285": {"channel": "nellore",    "telugu": "నెల్లూరు"},
    "305": {"channel": "kurnool",    "telugu": "కర్నూలు"},
    "344": {"channel": "guntur",     "telugu": "గుంటూరు"},
}

# Reverse: stream channel (lowercased) -> [backend location ids] feeding it.
CHANNEL_LOCATION_IDS = {}
for _bid, _v in CLASSIFIED_LOCATION_MAP.items():
    CHANNEL_LOCATION_IDS.setdefault(_v["channel"], []).append(_bid)
# CHANNEL_DEFS me Nellore(285) ka stream channel naam "Nalore" hai → alias.
if "nellore" in CHANNEL_LOCATION_IDS:
    CHANNEL_LOCATION_IDS.setdefault("nalore", CHANNEL_LOCATION_IDS["nellore"])

_CLASSIFIED_FALLBACK = ("unknown", "స్థానిక వార్తలు")

def get_classified_location(loc_id):
    """backend location_id (int|str) -> (channel_key, telugu_name). Safe fallback,
    never raises (unknown / 'all' / 'None' / '' -> generic)."""
    key = str(loc_id).strip()
    if not key or key.lower() in ("all", "none"):
        return _CLASSIFIED_FALLBACK
    e = CLASSIFIED_LOCATION_MAP.get(key)
    if not e:
        return _CLASSIFIED_FALLBACK
    return (e.get("channel") or _CLASSIFIED_FALLBACK[0],
            e.get("telugu")  or _CLASSIFIED_FALLBACK[1])

def channel_backend_ids(channel_name):
    """stream channel name -> [backend location ids] (empty list if none)."""
    return CHANNEL_LOCATION_IDS.get(str(channel_name).strip().lower(), [])


# ── Channel → State (for geo/ S3 structure) ─────────────────────────────────
CHANNEL_STATE = {
    "kurnool": "andhra_pradesh", "guntur": "andhra_pradesh", "kakinada": "andhra_pradesh",
    "nalore": "andhra_pradesh", "nellore": "andhra_pradesh", "tirupati": "andhra_pradesh",
    "anatpur": "andhra_pradesh", "anantapur": "andhra_pradesh",
    "khammam": "telangana", "karimnagar": "telangana", "warangal": "telangana",
    "nalgonda": "telangana",
}

def channel_state(channel_name):
    """stream channel -> state key (for geo/ paths), or None."""
    return CHANNEL_STATE.get(str(channel_name).strip().lower())

def geo_district_prefix(channel_name):
    """geo/ prefix for a channel's district folder (MAIN bucket), or None if
    the channel's state is unknown. e.g. Kurnool ->
    'geo/states/andhra_pradesh/districts/kurnool'."""
    st = channel_state(channel_name)
    if not st:
        return None
    dist = str(channel_name).strip().lower().replace(' ', '_').replace('-', '_')
    return f"geo/states/{st}/districts/{dist}"


# ── News-bulletin routing: DETERMINISTIC location -> channel ────────────────
# Backend location_id is authoritative; location_name is a fallback. UNKNOWN -> None
# (skip — NEVER default to Kurnool; the old LLM classify_location_to_channel defaulted
# everything to Kurnool on Gemini failure, starving all other channels). Anatpur is
# intentionally NOT mapped (skip — no content).
LOCATION_ID_TO_CHANNEL = {
    "75":  "Karimnagar", "141": "Nalgonda", "154": "Warangal", "161": "Khammam",
    "209": "Kakinada",   "285": "Nalore",   "305": "Kurnool",  "335": "Tirupati",
    "344": "Guntur",
}
_NEWS_CHANNELS = ["Khammam", "Kurnool", "Karimnagar", "Anatpur", "Kakinada",
                  "Nalore", "Tirupati", "Guntur", "Warangal", "Nalgonda"]

def resolve_news_channel(location_id, location_name=''):
    """Deterministic location -> channel for news bulletins.
    1) backend location_id (authoritative), 2) location_name substring match,
    3) None (unknown -> SKIP, never Kurnool-default)."""
    ch = LOCATION_ID_TO_CHANNEL.get(str(location_id).strip())
    if ch:
        return ch
    nl = str(location_name or '').strip().lower()
    if nl:
        for c in _NEWS_CHANNELS:
            if c.lower() in nl:
                return c
    return None


# ── NotebookLM upload: geo/ S3 key by scope (admin upload API) ──────────────
_GEO_STATES    = ("andhra_pradesh", "telangana")
_GEO_DISTRICTS = {
    "andhra_pradesh": {"kurnool", "guntur", "kakinada", "nalore", "tirupati", "anatpur"},
    "telangana":      {"khammam", "karimnagar", "warangal", "nalgonda"},
}

def notebooklm_geo_key(scope, state='', district='', kind='', filename='notebooklm.mp4'):
    """Compute the geo/ S3 key for a notebooklm upload by scope.
      national : geo/national/notebooklm/<file>
      state    : geo/states/<state>/_state/notebooklm/<file>
      district : geo/states/<state>/districts/<district>/<local|district>/notebooklm/<file>
    Returns None if the scope's required fields are missing/invalid."""
    scope = (scope or '').strip().lower()
    fn    = (filename or '').strip() or 'notebooklm.mp4'
    st    = (state or '').strip().lower()
    d     = (district or '').strip().lower().replace(' ', '_').replace('-', '_')
    k     = (kind or '').strip().lower()
    if scope == 'national':
        return f"geo/national/notebooklm/{fn}"
    if scope == 'state':
        if st not in _GEO_STATES:
            return None
        return f"geo/states/{st}/_state/notebooklm/{fn}"
    if scope == 'district':
        if st not in _GEO_STATES or d not in _GEO_DISTRICTS.get(st, set()) or k not in ('local', 'district'):
            return None
        return f"geo/states/{st}/districts/{d}/{k}/notebooklm/{fn}"
    return None

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
    # Location-specific intro videos
    'assets/intro_karimnagar.mp4',
    'assets/intro_tirupati.mp4',
    'assets/intro_khammam.mp4',
    'assets/intro_nalgonda.mp4',
    'assets/intro_guntur.mp4',
    'assets/intro_warangal.mp4',
    'assets/intro_kakinada.mp4',
    'assets/intro_nalore.mp4',
    # Location-specific cap1 (break-news) videos
    'assets/cap1_karimnagar.mp4',
    'assets/cap1_tirupati.mp4',
    'assets/cap1_kakinada.mp4',
    'assets/cap1_nalore.mp4',
    # NotebookLM filler videos
    'assets/notebooklm_guntur.mp4',
    'assets/notebooklm_nalgonda.mp4',
    'assets/notebooklm_tirupati.mp4',
    'assets/notebooklm_warangal.mp4',
    'assets/notebooklm_kakinada.mp4',
    'assets/notebooklm_nalore.mp4',
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

# Whole folders mirrored from S3 (variable-count pools — operator just drops
# files in the S3 prefix, no code change needed). Every object under
# {S3_STATIC_PREFIX}/{folder}/ is synced into local {folder}/.
#   S3:    static-assets/assets/anchors/anchor1.mp4, anchor2.mp4, ...
#   Local: assets/anchors/anchor1.mp4, anchor2.mp4, ...
_S3_SYNC_FOLDERS = [
    'assets/anchors',       # welcome anchor pool (intro ke baad)
    'assets/anchors_end',   # ending anchor pool (news ke baad, filler se pehle)
    'assets/ads',           # per-channel ad-ticker text: assets/ads/<channel>/*.txt
]


def ensure_assets():
    """Sync static assets from S3 (S3 = source of truth).

    Downloads MISSING assets, AND re-downloads any local file whose size differs
    from S3 — this self-heals a wrong/stale asset that the old 'download only if
    missing' logic never fixed (e.g. a wrong intro4.mp4 left in the VPS volume
    that made Kurnool show Nalgonda's intro). System-font substitutes are still
    honoured; fonts themselves are not size-checked (stable + large)."""
    import boto3
    from botocore.config import Config as _BotoConfig

    if not S3_BUCKET_NAME:
        return  # S3 not configured — nothing to sync

    _cfg = _BotoConfig(
        request_checksum_calculation='when_required',
        response_checksum_validation='when_required',
    )
    s3 = boto3.client('s3', region_name=S3_REGION,
                      aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                      aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                      config=_cfg)

    def _s3_size(s3_key: str):
        try:
            return int(s3.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)['ContentLength'])
        except Exception:
            return None  # not in S3 / error — leave the local copy untouched

    def _needs_download(asset: str) -> bool:
        # Download if MISSING, or if the S3 object is NEWER than the local copy
        # (i.e. an operator just uploaded an updated asset to S3). A stale/older
        # S3 copy NEVER overwrites a newer local file — this is what protects a
        # correct, scp'd VPS asset from being clobbered by an old S3 version
        # (the white ticker4.png disaster), while still letting fresh S3 uploads
        # propagate to the VPS automatically.
        local_path = os.path.join(BASE_DIR, asset)
        if not os.path.exists(local_path):
            fname = os.path.basename(asset)
            for sys_path in _SYSTEM_FONT_SUBSTITUTES.get(fname, []):
                if os.path.exists(sys_path):
                    return False  # system font available — local copy not needed
            return True  # genuinely missing
        if asset.lower().endswith(('.ttf', '.otf')):
            return False  # fonts are stable — never refresh
        # Refresh only when S3 is newer than local (operator pushed an update).
        try:
            head = s3.head_object(Bucket=S3_BUCKET_NAME, Key=f"{S3_STATIC_PREFIX}/{asset}")
            s3_mtime = head['LastModified'].timestamp()
            if s3_mtime > os.path.getmtime(local_path) + 2:  # 2s tolerance
                print(f"[assets] 🔄 S3 newer → refreshing: {asset}")
                return True
        except Exception:
            pass  # S3 missing/unreachable → keep the local copy
        return False

    for asset in [a for a in _STATIC_ASSETS if _needs_download(a)]:
        local_path = os.path.join(BASE_DIR, asset)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        s3_key = f"{S3_STATIC_PREFIX}/{asset}"
        try:
            s3.download_file(S3_BUCKET_NAME, s3_key, local_path)
            print(f"[assets] ✅ Downloaded: {asset}")
        except Exception as e:
            print(f"[assets] ⚠️ Could not download {asset}: {e}")

    # ── Folder mirrors: download EVERY object under each S3 folder prefix ──────
    # (variable-count pools like anchors — add files in S3, no code change)
    for folder in _S3_SYNC_FOLDERS:
        try:
            prefix = f"{S3_STATIC_PREFIX}/{folder}/"
            local_dir = os.path.join(BASE_DIR, folder)
            os.makedirs(local_dir, exist_ok=True)   # read-only FS → caught below, no crash
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if key.endswith('/'):
                        continue  # skip the folder placeholder
                    # Preserve subfolder structure (rel path under the prefix) so
                    # per-channel dirs like ads/kurnool/kurnool_ads.txt land as
                    # assets/ads/kurnool/kurnool_ads.txt (NOT flattened).
                    rel = key[len(prefix):]
                    if not rel:
                        continue
                    dst = os.path.join(local_dir, *rel.split('/'))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    # download if missing or size differs (self-heal)
                    if os.path.exists(dst) and os.path.getsize(dst) == int(obj.get('Size', -1)):
                        continue
                    try:
                        s3.download_file(S3_BUCKET_NAME, key, dst)
                        print(f"[assets] ✅ Synced {folder}/{rel}")
                    except Exception as e:
                        print(f"[assets] ⚠️ Could not sync {folder}/{rel}: {e}")
        except Exception as e:
            print(f"[assets] ⚠️ Folder sync failed for {folder}: {e}")
# ─────────────────────────────────────────────────────────────────────────────