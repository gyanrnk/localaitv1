# """
# Configuration file for News Bot
# """
# import os
# from dotenv import load_dotenv

# load_dotenv()


# OPENAI_API_KEY     = os.getenv('OPENAI_API_KEY', '')
# OPENAI_MODEL       = os.getenv('OPENAI_MODEL', 'gpt-4o')          # ← YEH ADD KARO
# OPENAI_WHISPER_MODEL = os.getenv('OPENAI_WHISPER_MODEL', 'gpt-4o-transcribe')
# SARVAM_API_KEY = os.getenv('SARVAM_API_KEY', '')

# GUPSHUP_API_KEY       = os.getenv('GUPSHUP_API_KEY', '')
# GUPSHUP_APP_NAME      = os.getenv('GUPSHUP_APP_NAME', '')
# GUPSHUP_SOURCE_NUMBER = os.getenv('GUPSHUP_SOURCE_NUMBER', '')

# PORT = os.getenv('PORT', '8000')

# HEYGEN_API_KEY = os.getenv('HEYGEN_API_KEY', '')
# DID_API_KEY    = os.getenv('DID_API_KEY', '')


# BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# BASE_INPUT_DIR  = os.path.join(BASE_DIR, 'inputs')
# BASE_OUTPUT_DIR = os.path.join(BASE_DIR, 'outputs')

# INPUT_IMAGE_DIR = os.path.join(BASE_INPUT_DIR, 'images')
# INPUT_VIDEO_DIR = os.path.join(BASE_INPUT_DIR, 'videos')
# INPUT_AUDIO_DIR = os.path.join(BASE_INPUT_DIR, 'audios')

# OUTPUT_SCRIPT_DIR   = os.path.join(BASE_OUTPUT_DIR, 'scripts')
# OUTPUT_HEADLINE_DIR = os.path.join(BASE_OUTPUT_DIR, 'headlines')
# OUTPUT_AUDIO_DIR    = os.path.join(BASE_OUTPUT_DIR, 'audios')

# PREFIX_IMAGE        = 'i'
# PREFIX_VIDEO        = 'v'
# PREFIX_AUDIO        = 'a'
# PREFIX_SCRIPT       = 's'
# PREFIX_HEADLINE     = 'h'
# PREFIX_OUTPUT_AUDIO = 'oa'

# SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
# SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
# SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.m4a', '.ogg']

# INTRO_VIDEO_DURATION       = 15.4
# HEADLINE_DURATION_PER_ITEM = 4


# # ── Background Music ────────────────────────────────────────────────────────
# # Place your background music file at: <BASE_DIR>/bgm.mp3  (or .wav / .m4a)
# # Set BGM_VOLUME between 0.0 (silent) and 1.0 (full volume).
# # Recommended: 0.06–0.12 for a subtle professional underscore.
# # Set BGM_ENABLED = False to skip BGM entirely.
# BGM_PATH    = os.path.join(BASE_DIR, 'news_intro.mpeg')   # path to your music file
# BGM_VOLUME  = float(os.getenv('BGM_VOLUME', '0.25'))  # 8% volume by default
# BGM_ENABLED = os.getenv('BGM_ENABLED', 'true').lower() != 'false'
# BGM_FADE_SECONDS = 2.5   # fade-in at start, fade-out at end

# BREAK_DURATION = 2   # seconds — logo card between news segments
# WORDS_PER_SECOND_TELUGU = 2.2
# MAX_WORDS_PER_SCRIPT    = int(60 * WORDS_PER_SECOND_TELUGU)   
# MAX_WORDS_PER_HEADLINE  = int(HEADLINE_DURATION_PER_ITEM * WORDS_PER_SECOND_TELUGU)  
# TELUGU_NEWS_SCRIPT_PROMPT = f"""You are an expert Telugu news script writer for a professional television news bulletin.

# YOUR TASK:
# Generate a complete, broadcast-ready Telugu news script from the provided content.

# STRICT REQUIREMENTS:
# 1. CRITICAL WORD LIMIT:
#    - Maximum {MAX_WORDS_PER_SCRIPT} words
# 2. CONTENT PURITY:
#    - Write ONLY the news story content
#    - NO openings: No "నమస్కారం", "శుభోదయం", "ఈ రోజు వార్తలు"
#    - NO closings: No "ధన్యవాదాలు", "మళ్ళీ కలుద్దాం", sign-offs
#    - NO time references: No "ఒక గంట క్రితం", "ఈ రోజు", "నిన్న"
#    - NO meta commentary: No "ఇప్పుడు వార్త చూద్దాం"
#    - Start directly with the news story

# 3. LANGUAGE QUALITY:
#    - Use formal, professional Telugu (వ్యవహారిక తెలుగు)
#    - Write in active voice for impact
#    - Use proper Telugu journalism terminology
#    - Keep sentences clear, concise, and powerful
#    - Average sentence length: 15-20 words
#    - Use connectors for smooth flow (అయితే, కాగా, మరోవైపు)

# 4. STRUCTURE:
#    - Lead paragraph: Most important facts (who, what, when, where)
#    - Body: Supporting details only — NO repetition of lead facts
#    - Conclusion: Impact or next steps
#    - Each paragraph: 2-3 sentences maximum
#    - NEVER repeat the same fact, name, or phrase twice

# 5. READABILITY:
#    - Write for spoken delivery (easy to read aloud)
#    - Avoid complex compound sentences
#    - Use punctuation that helps with breathing pauses
#    - Prefer Telugu words over English transliterations when possible

# 6. TONE:
#    - Maintain journalistic neutrality
#    - Be factual and authoritative
#    - Show appropriate gravity for serious news

# 7. FORMATTING:
#    - Use proper Telugu script throughout
#    - Paragraph breaks for clarity
#    - No bullet points or numbering

# REMEMBER: You are creating content for a news anchor on live television. Every word matters."""

# # TELUGU_HEADLINE_PROMPT = f"""You are an expert Telugu news headline writer.

# # REQUIREMENTS:
# # 1. LENGTH: Maximum 2 lines. Each line maximum 3-4 Telugu words only.
# #    Total headline: maximum 7-8 words combined.
# # 2. DURATION: Must fit in {HEADLINE_DURATION_PER_ITEM} seconds when spoken
# # 3. STYLE: Past tense, action-first (ఏం జరిగింది format)
# # 4. CONTENT: Most important single fact — person + action or place + event
# # 5. LANGUAGE: Pure Telugu, no English mixing, no verbs ending in -తుంది/-స్తుంది
# # 6. AVOID: Questions, exclamation marks, conjunctions, filler words

# # GOOD EXAMPLES (2 lines, 3-4 words each):
# #   చెన్నైలో తుఫాను దెబ్బ
# #   వేల మంది నిరాశ్రయులు

# #   భారత సైన్యం విజయం
# #   సరిహద్దు ఘర్షణ ముగిసింది

# # BAD EXAMPLES (too long per line):
# #   తెలంగాణలో భారీ వర్షాల వల్ల పలు జిల్లాలు ప్రభావితం  ← too long!

# # OUTPUT: Headline only — nothing else, no quotes, no labels."""

# TELUGU_HEADLINE_PROMPT = f"""You are an expert Telugu news headline writer.

# REQUIREMENTS:
# 1. LENGTH: Maximum 20 characters per line, maximum 2 lines
# 2. DURATION: Must fit in {HEADLINE_DURATION_PER_ITEM} seconds when spoken
# 3. STYLE: Past tense, action-first (ఏం జరిగింది format)
# 4. CONTENT: Most important single fact — person + action or place + event
# 5. LANGUAGE: Pure Telugu, no English mixing, no verbs ending in -తుంది/-స్తుంది
# 6. AVOID: Questions, exclamation marks, conjunctions, filler words

# GOOD EXAMPLES:
#   చెన్నైలో తుఫాను దెబ్బ
#   భారత సైన్యం విజయం
#   డావోస్‌లో మోదీ ప్రసంగం

# OUTPUT: Headline only — nothing else."""





"""
Configuration file for News Bot
"""
import os
from dotenv import load_dotenv

load_dotenv()


OPENAI_API_KEY       = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL         = os.getenv('OPENAI_MODEL', 'gpt-4o')
OPENAI_WHISPER_MODEL = os.getenv('OPENAI_WHISPER_MODEL', 'gpt-4o-transcribe')
SARVAM_API_KEY       = os.getenv('SARVAM_API_KEY', '')

GUPSHUP_API_KEY       = os.getenv('GUPSHUP_API_KEY', '')
GUPSHUP_APP_NAME      = os.getenv('GUPSHUP_APP_NAME', '')
GUPSHUP_SOURCE_NUMBER = os.getenv('GUPSHUP_SOURCE_NUMBER', '')

PORT = os.getenv('PORT', '8000')

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

SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.m4a', '.ogg']

INTRO_VIDEO_DURATION       = 15.4
HEADLINE_DURATION_PER_ITEM = 4

BGM_PATH         = os.path.join(BASE_DIR, 'news_intro.mpeg')
BGM_VOLUME       = float(os.getenv('BGM_VOLUME', '0.25'))
BGM_ENABLED      = os.getenv('BGM_ENABLED', 'true').lower() != 'false'
BGM_FADE_SECONDS = 2.5

BREAK_DURATION          = 2
WORDS_PER_SECOND_TELUGU = 2.2
MAX_WORDS_PER_SCRIPT    = int(60 * WORDS_PER_SECOND_TELUGU)
MAX_WORDS_PER_HEADLINE  = int(HEADLINE_DURATION_PER_ITEM * WORDS_PER_SECOND_TELUGU)

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

REMEMBER: You are creating content for a news anchor on live television. Every word matters."""

TELUGU_HEADLINE_PROMPT = f"""You are an expert Telugu news headline writer.

REQUIREMENTS:
1. LENGTH: Maximum 20 characters per line, maximum 2 lines
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

# ── LocalAI TV Incidents API ──────────────────────────────────────────────
LOCALAITV_API_URL     = os.getenv('LOCALAITV_API_URL', 'https://localaitv.com/api/incidents')
LOCALAITV_API_TOKEN   = os.getenv('LOCALAITV_API_TOKEN', '')
LOCALAITV_LOCATION_ID = int(os.getenv('LOCALAITV_LOCATION_ID', '1'))
LOCALAITV_CATEGORY_ID = int(os.getenv('LOCALAITV_CATEGORY_ID', '2'))