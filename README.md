# LocalAI TV — Telugu News Bulletin Automation

An end-to-end automated Telugu news production system. Reporters submit news via WhatsApp; the system generates scripts, synthesizes audio, builds broadcast-quality video bulletins, and streams them live to YouTube — fully unattended.

---

## How It Works

```
Reporter (WhatsApp)
        │
        ▼
  Gupshup Webhook  ──► Media download + queue
        │
        ▼
  AI Pipeline
  ├── OpenAI / Groq  →  Telugu news script + headline
  ├── Sarvam AI TTS  →  MP3 audio (male/female alternating)
  └── Clip Analyzer  →  Best video segment selection
        │
        ▼
  Bulletin Builder
  ├── Selects items by priority + duration budget
  ├── Injects WhoisWho clips + ads from S3
  └── Writes bulletin_manifest.json
        │
        ▼
  Video Builder (FFmpeg 1080p/25fps)
  ├── Intro → News items → Injections → Filler
  ├── Ticker overlay (scrolling headlines)
  └── Reporter card + GIF overlay
        │
        ▼
  YouTube Live Stream  +  LocalAI TV API
```

---

## Features

- **WhatsApp ingestion** — Accepts image, video, and audio reports via Gupshup webhook
- **Telugu AI scripts** — GPT-4o generates broadcast-ready Telugu news scripts and headlines
- **TTS narration** — Sarvam AI (Manan / Arya voices) with male/female alternation per item
- **Smart bulletin scheduling** — Priority-based (breaking → urgent → normal), greedy duration fitting, atempo audio speed adjustment
- **Video clip analysis** — Extracts the most relevant 8–20s segment from reporter videos
- **S3-backed storage** — All inputs, outputs, audio, and bulletin videos stored in AWS S3; local disk is only a working buffer
- **CloudSQL state** — PostgreSQL for all metadata, event logs, report state, and app state (ticker cursor, cleanup timestamps)
- **Multi-channel** — Karimnagar, Khammam, Kurnool channels; OpenAI classifies item locations to the right channel
- **Ad + WhoisWho injection** — Pulls ad clips and whoiswho segments from S3, randomly interleaved
- **Ticker overlay** — Scrolling dual-band ticker with headlines + ads, cursor persisted across bulletins
- **YouTube Live streaming** — Direct RTMP push via FFmpeg with CBR encoding
- **CPU Governor** — FFmpeg concurrency throttling to prevent server overload
- **24-hour cleanup** — Auto-deletes old items, files, and bulletins; state tracked in CloudSQL

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web server | Flask |
| AI / LLM | OpenAI GPT-4o, Groq |
| TTS | Sarvam AI (Telugu) |
| Video processing | FFmpeg, Pillow |
| Messaging | Gupshup WhatsApp API |
| Object storage | AWS S3 |
| Database | Google CloudSQL (PostgreSQL) |
| Streaming | YouTube Live (RTMP) |
| Fonts | Noto Sans Telugu, Gidugu |

---

## Project Structure

```
webhook_server.py       # Flask app — main entry point, API endpoints, build orchestration
main.py                 # NewsBot class — item processing pipeline
bulletin_builder.py     # Bulletin planning, item selection, manifest generation
video_builder.py        # FFmpeg video composition
file_manager.py         # Local file I/O + S3 upload/download
s3_storage.py           # Central S3 helper (upload, download, async, key builders)
s3_bulletin_fetcher.py  # Downloads ads and WhoisWho clips from S3
db.py                   # CloudSQL connection pool + app_state helpers
config.py               # All config, prompts, static asset bootstrap
tts_handler.py          # Sarvam AI TTS
openai_handler.py       # OpenAI / Groq API wrapper
clip_analyzer.py        # Video clip structure analysis
editorial_planner.py    # Story structure (intro/clip/analysis)
ticker_overlay.py       # Scrolling ticker rendering
yt_streamer.py          # YouTube Live streaming
event_logger.py         # CloudSQL audit logging
report_state_manager.py # Report processing state (retry/checkpoint)
telugu_processor.py     # Telugu number conversion, text cleanup
media_handler.py        # Image/video validation
message_queue.py        # WhatsApp message batching
gupshup_handler.py      # Gupshup API client
location_resolver.py    # Location ID mapping
governor/               # CPU governor — FFmpeg slot throttling
```

---

## CloudSQL Tables

| Table | Purpose |
|---|---|
| `news_items` | News item metadata, audio paths, durations, S3 keys |
| `processed_reports` | Report processing state (processing / complete / failed) |
| `item_events` | Per-item audit log |
| `bulletin_events` | Per-bulletin audit log |
| `incidents` | Raw incident/report data |
| `app_state` | Key-value store (ticker cursor, cleanup timestamps) |

---

## S3 Key Structure

```
static-assets/          # Fonts, GIFs, intro/filler/break videos (bootstrap)
items/inputs/           # Reporter-uploaded images, videos, audios
items/scripts/          # Generated script .txt files
items/headlines/        # Headline text + audio files
items/audios/           # Script, intro, analysis audio files
item_cache/             # Pre-built item videos (reuse across bulletins)
bulletins/{channel}/    # Final bulletin .mp4 + manifest.json
whoiswho/outputs/       # External WhoisWho clips (read-only)
ads/                    # Ad clips (read-only)
```

---

## Setup

### Prerequisites

- Python 3.11+
- FFmpeg installed and in PATH
- PostgreSQL (Google CloudSQL recommended)
- AWS S3 bucket
- Gupshup WhatsApp Business account
- Sarvam AI API key
- OpenAI API key

### Install dependencies

```bash
pip install -r requirements.txt
```

### Linux font setup (cloud server)

```bash
apt-get install -y fonts-noto fonts-noto-color-emoji
```

If system fonts are not available, `ensure_assets()` will download `NotoSansTelugu.ttf` and `seguiemj.ttf` from S3 automatically on startup.

### Environment variables

Create a `.env` file (see `.env.example` if available):

```env
# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o

# Sarvam TTS
SARVAM_API_KEY=

# Gupshup WhatsApp
GUPSHUP_API_KEY=
GUPSHUP_APP_NAME=
GUPSHUP_SOURCE_NUMBER=

# AWS S3
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-south-2
S3_BUCKET_NAME=

# CloudSQL PostgreSQL
DATABASE_URL=postgresql://user:pass@host:5432/dbname?sslmode=require

# YouTube
YT_STREAM_KEY=

# LocalAI TV API
LOCALAITV_API_TOKEN=
BULLETIN_API_TOKEN=

# Feature flags
TICKER_ENABLED=true
S3_INJECT_ENABLED=true
FIVE_MIN_INJECT_ENABLED=true
BGM_ENABLED=true
```

### Run

```bash
python webhook_server.py
```

The server starts on port `8000` by default (`PORT` env var to override).

---

## API Endpoints

### WhatsApp Webhook (Gupshup)

All four routes accept the same Gupshup payload — use whichever matches your webhook configuration:

| Method | Endpoint | Description |
|---|---|---|
| POST | `/` | Gupshup WhatsApp webhook (root) |
| POST | `/webhook` | Gupshup WhatsApp webhook |
| POST | `/gupshup/webhook` | Gupshup WhatsApp webhook |
| POST | `/whatsapp/webhook` | Gupshup WhatsApp webhook |

### Report / Incident Ingestion

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/webhooks/reports` | Single report submission (LocalAI TV app) |
| POST | `/api/webhooks/batch` | Batch submission — up to 3 items in one request |
| POST | `/api/feed` | Submit a raw incident (stores to CloudSQL `incidents` table) |
| GET | `/api/feed?page=1&limit=20` | List incidents paginated from CloudSQL |

**Batch payload format (`/api/webhooks/batch`):**
```json
{
  "items": [
    { "text": "caption", "media_url": "https://...", "media_type": "image|video|audio" }
  ]
}
```

### Media & Utility

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/media/<path>` | Serve local media files (outputs or inputs dir) |
| GET | `/health` | Health check — returns `{"status": "healthy"}` |

---

## Deployment Notes

- **Ephemeral disk safe** — All generated files are uploaded to S3; local disk is a working buffer only. Server restarts do not lose data.
- **Multi-instance** — State is in CloudSQL; S3 keys stored in `news_items` table. Item video cache syncs to S3.
- **Connection pooling** — `db.py` uses `ThreadedConnectionPool` (min=2, max=10).
- **No Windows paths on Linux** — Font resolution checks Linux system paths first, falls back to S3-downloaded local copies.
