# testing

# LocalAI TV - Telugu News Bulletin Automation

Automated Telugu news production for LocalAI TV. The system ingests reporter submissions from WhatsApp/Gupshup and the LocalAI TV reports API, generates Telugu scripts and headlines, creates Sarvam TTS audio, builds FFmpeg video bulletins, uploads artifacts to S3, and rotates channel-specific bulletins into YouTube Live streams.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Features](#features)
3. [Prerequisites](#prerequisites)
4. [Quick Start (Local Development)](#quick-start-local-development)
5. [Docker Setup](#docker-setup)
6. [Environment Variables](#environment-variables)
7. [Running the Project](#running-the-project)
8. [API Endpoints](#api-endpoints)
9. [CI/CD Setup](#cicd-setup)
10. [Project Structure](#project-structure)
11. [Database Schema](#database-schema)
12. [Detailed API Usage](#detailed-api-usage)
13. [Security Best Practices](#security-best-practices)
14. [Backup and Restore](#backup-and-restore)
15. [Performance Optimization](#performance-optimization)
16. [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ARCHITECTURE                                    │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │   Reporter   │     │ LocalAI TV   │     │  Gupshup     │
  │   (WhatsApp) │     │    App       │     │  WhatsApp    │
  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │  Flask Web Server  │
                 │  (webhook_server)  │
                 └──────────┬──────────┘
                            │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │   Reports    │    │   Planner    │    │   Cleanup    │
  │   Poller     │    │    Loop      │    │    Loop      │
  └──────────────┘    └──────────────┘    └──────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │     NewsBot        │
                 │    (main.py)       │
                 └──────────┬──────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
    ▼                       ▼                       ▼
┌─────────┐          ┌─────────────┐         ┌─────────────┐
│ OpenAI  │          │   Sarvam    │         │    S3       │
│ Whisper │          │     TTS     │         │   Storage   │
└─────────┘          └─────────────┘         └─────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │  Bulletin Builder │
                 │ (bulletin_builder) │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   Video Builder    │
                 │ (video_builder.py) │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   YouTube Streamer │
                 │   (yt_streamer.py) │
                 └─────────────────────┘
```

---

## Features

- **WhatsApp Ingestion**: Receive news reports via Gupshup WhatsApp webhooks
- **API Reports**: Receive reports from LocalAI TV web application
- **Multi-Media Support**: Process text, images, videos, and audio
- **AI Transcription**: OpenAI Whisper for video/audio transcription
- **AI Script Generation**: OpenAI GPT-4 powered Telugu script and headline generation
- **Telugu TTS**: Sarvam AI Text-to-Speech with alternating voices (manan/arya)
- **Smart Clip Selection**: EditorialPlanner for best clip selection from videos
- **Video Bulletin Building**: FFmpeg-powered video compilation with ticker, overlays, BGM
- **YouTube Live Streaming**: RTMPS streaming to multiple YouTube channels
- **PostgreSQL Database**: Full state management for items, reports, events
- **AWS S3 Storage**: Cloud storage for media, scripts, bulletins
- **7 Channels**: Karimnagar, Khammam, Kurnool, Anatpur, Kakinada, Nalore, Tirupati
- **Background Processing**: Automatic polling, retry, and cleanup loops

---

## Prerequisites

### System Requirements
- **OS**: Linux (Ubuntu 20.04+) or macOS
- **Python**: 3.11+
- **FFmpeg**: Must be installed and in PATH
- **RAM**: Minimum 4GB (recommended 8GB+)
- **Disk**: Minimum 20GB for logs and cache

### External Services
- **PostgreSQL**: CloudSQL or local PostgreSQL 15+
- **AWS S3**: Main bucket + external bucket for ads/whoiswho
- **OpenAI**: API key for GPT-4 and Whisper
- **Sarvam AI**: API key for Telugu TTS
- **Gupshup**: WhatsApp Business API account
- **YouTube**: Live stream keys for each channel

---

## Quick Start (Local Development)

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-repo/localaitv.git
cd localaitv
```

### Step 2: Create Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt

# Optional: Install Playwright for HTML-to-PNG rendering
pip install playwright
python -m playwright install chromium

# Install FFmpeg (if not installed)
# Ubuntu:
sudo apt-get install -y ffmpeg
# macOS:
brew install ffmpeg
```

### Step 4: Configure Environment Variables

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your actual API keys and credentials
# See Environment Variables section below for details
```

### Step 5: Set Up Database

```bash
# Option A: Use local PostgreSQL
# Create a PostgreSQL database and user
sudo -u postgres psql
CREATE DATABASE localaitv_db;
CREATE USER localaitv WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE localaitv_db TO localaitv;

# Update DATABASE_URL in .env
DATABASE_URL="postgresql://localaitv:your_password@localhost:5432/localaitv_db?sslmode=disable"

# Option B: Use CloudSQL (recommended for production)
# Update DATABASE_URL in .env with your CloudSQL connection string
```

### Step 6: Run the Application

```bash
# Start the webhook server
python webhook_server.py

# Server will run on http://localhost:8000
```

### Step 7: Verify Installation

```bash
# Check health endpoint
curl http://localhost:8000/health

# Check database connection
curl http://localhost:8000/api/feed?limit=1
```

---

## Docker Setup

### Option 1: Development

```bash
# Build and start all services
docker-compose up --build

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Option 2: Production (on VPS)

```bash
# Copy production compose file (already in repo)
# docker-compose.prod.yml is the production config

# Edit .env with production values
nano .env

# Start services
docker-compose -f docker-compose.prod.yml up -d

# View logs
docker-compose -f docker-compose.prod.yml logs -f

# Restart
docker-compose -f docker-compose.prod.yml restart
```

### Makefile Commands

```bash
# Build Docker image
make build

# Start development
make up

# Stop services
make down

# Restart services
make restart

# View logs
make logs

# Show running containers
make ps

# Clean up everything
make clean
```

---

## Environment Variables

Create a `.env` file with the following variables:

### Server Configuration
```env
PORT=8000
API_BASE_URL=https://srv1264596.hstgr.cloud
```

### OpenAI
```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4o
OPENAI_HEADLINE_MODEL=gpt-4o-mini
OPENAI_WHISPER_MODEL=whisper-1
```

### Sarvam TTS
```env
SARVAM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

### Gupshup WhatsApp
```env
GUPSHUP_API_KEY=your_gupshup_api_key
GUPSHUP_APP_NAME=your_app_name
GUPSHUP_SOURCE_NUMBER=918523847888
```

### Database (PostgreSQL)
```env
DB_TYPE=postgres
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname?sslmode=require&connect_timeout=5
```

### AWS S3 (Main Bucket)
```env
USE_S3=true
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxx
AWS_REGION=ap-south-2
S3_BUCKET_NAME=your-bucket-name
S3_STATIC_PREFIX=static-assets
```

### AWS S3 (External Bucket)
```env
AWS_ACCESS_KEY_ID_M=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY_M=xxxxxxxxxxxxxxxxxxxx
AWS_REGION_M=ap-south-2
S3_BUCKET_NAME_M=your-external-bucket
S3_BULLETIN_PREFIX=whoiswho/outputs
```

### LocalAI TV APIs
```env
LOCALAITV_API_URL=https://localaitv.com
LOCALAITV_API_TOKEN=your_token
LOCALAITV_CATEGORY_ID=1
BULLETIN_API_TOKEN=your_bulletin_token
```

### YouTube Streaming
```env
YOUTUBE_STREAMING_ENABLED=true
YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
YT_STREAM_KEY=your_stream_key
YT_STREAM_KEY_KURNOOL=your_kurnool_key
YT_STREAM_KEY_KARIMNAGAR=your_karimnagar_key
STREAM_COUNT=7
```

### Feature Flags
```env
ENABLE_PLANNER=true
ENABLE_REPORT_POLLER=true
ENABLE_RETRY=true
ENABLE_CLEANUP=true
TICKER_ENABLED=true
BGM_ENABLED=true
BGM_VOLUME=0.25
```

---

## Running the Project

### 1. Start the Webhook Server (Main Application)

```bash
# Development
python webhook_server.py

# Production (with gunicorn)
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 webhook_server:app --timeout 120
```

### 2. Start YouTube Streamer (Optional)

```bash
python yt_streamer.py
```

### 3. Build Bulletins Manually

```bash
# Build bulletins for all channels
python bulletin_builder.py 10

# Build video from bulletin
python video_builder.py outputs/bulletins/Kurnool/bul_20260509_120000
```

### 4. Background Threads

The webhook server automatically starts these background threads:
- **Planner Loop**: Checks for new items and builds bulletins
- **Reports Poller**: Polls LocalAI TV API for new reports
- **Retry Loop**: Retries failed report processing
- **Cleanup Loop**: Deletes old items and files every 24 hours

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Home page |
| `GET` | `/health` | Health check with DB/S3/FFmpeg checks |
| `POST` | `/webhook` | Gupshup WhatsApp webhook |
| `POST` | `/gupshup/webhook` | Alternative webhook |
| `POST` | `/whatsapp/webhook` | WhatsApp webhook |
| `POST` | `/api/webhooks/reports` | LocalAI TV report webhook |
| `POST` | `/api/webhooks/batch` | Batch report webhook (up to 3 items) |
| `GET` | `/api/feed` | List incidents |
| `GET` | `/api/media/<path>` | Serve media files |

### Example: Send a Report

```bash
curl -X POST http://localhost:8000/api/webhooks/reports \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Test news report",
    "media_url": "https://example.com/video.mp4",
    "media_type": "video",
    "location_id": 5,
    "location_name": "Karimnagar"
  }'
```

---

## CI/CD Setup

### GitHub Actions

The project includes automatic deployment to your Hostinger VPS via GitHub Actions.

1. **Push code to main branch** → Triggers CI/CD

2. **GitHub Secrets to configure**:

```bash
# Get SSH known hosts
ssh-keyscan 72.62.241.21 >> ~/.ssh/known_hosts

# Add to GitHub Secrets:
VPS_HOST: 72.62.241.21
VPS_PORT: 22
VPS_USER: root
SSH_PRIVATE_KEY: <your-private-key>
SSH_KNOWN_HOSTS: <content-of-known-hosts>
DATABASE_URL: <your-database-url>
AWS_ACCESS_KEY_ID: <your-aws-key>
AWS_SECRET_ACCESS_KEY: <your-aws-secret>
S3_BUCKET_NAME: <your-bucket>
OPENAI_API_KEY: <your-openai-key>
SARVAM_API_KEY: <your-sarvam-key>
# ... other secrets
```

### Manual VPS Setup

```bash
# SSH to VPS
ssh root@72.62.241.21

# Run setup script
chmod +x setup-vps.sh
./setup-vps.sh

# Edit .env with your values
nano .env

# Start with Docker
docker-compose -f docker-compose.prod.yml up -d
```

---

## Project Structure

```
localaitv/
├── webhook_server.py          # Main Flask app + background threads
├── main.py                    # NewsBot processing pipeline
├── bulletin_builder.py       # Select items & create bulletins
├── video_builder.py          # Build final video MP4
├── yt_streamer.py            # YouTube Live streaming
├── config.py                 # Configuration & paths
├── db.py                     # PostgreSQL connection pool
├── openai_handler.py         # OpenAI GPT-4 & Whisper API calls
├── tts_handler.py            # Sarvam AI TTS
├── gupshup_handler.py        # WhatsApp webhook handler
├── file_manager.py           # File storage + S3 upload
├── media_handler.py          # Media file processing
├── telugu_processor.py       # Telugu text processing (numbers, cleaning)
├── clip_analyzer.py          # Video clip analysis for best segment
├── editorial_planner.py      # AI-powered story planning & clip selection
├── ticker_overlay.py         # Video ticker rendering
├── s3_storage.py             # AWS S3 operations
├── s3_bulletin_fetcher.py    # Download bulletins from S3
├── event_logger.py           # Audit logging to database
├── message_queue.py          # WhatsApp message matching
├── report_state_manager.py   # Report retry state tracking
├── runner.py                 # Standalone runner
├── fixed.py                  # Utility functions
├── governor/                 # Build queue & CPU management
│   ├── build_queue.py        # Bulletin build queue
│   ├── cpu_governor.py       # CPU throttling for streaming
│   ├── process_wrapper.py    # Process wrapper utilities
│   └── stream_registry.py    # Stream state registry
├── inputs/                   # Input media (images, videos, audios)
│   ├── images/
│   ├── videos/
│   └── audios/
├── outputs/                  # Generated content
│   ├── scripts/              # Generated Telugu scripts
│   ├── headlines/            # Headline text & audio
│   ├── audios/               # TTS audio files
│   ├── reporters/            # Reporter profile photos
│   ├── item_video_cache/     # Cached processed videos
│   ├── bulletins/            # Generated bulletins
│   └── s3_inject_cache/      # S3 injection cache
├── assets/                   # Static assets (logos, tickers)
├── Dockerfile                # Docker image build
├── docker-compose.yml        # Development compose
├── docker-compose.prod.yml   # Production compose
├── Makefile                  # Make commands
├── requirements.txt          # Python dependencies
├── .env.example              # Environment template
└── setup-vps.sh              # VPS setup script
```

---

## Database Schema

### Tables

```sql
-- Main news items table
CREATE TABLE news_items (
    id BIGSERIAL PRIMARY KEY,
    counter INTEGER UNIQUE,
    media_type TEXT,
    priority TEXT DEFAULT 'normal',
    timestamp TEXT,
    headline TEXT,
    script_filename TEXT,
    headline_audio TEXT,
    script_audio TEXT,
    headline_duration REAL,
    script_duration REAL,
    total_duration REAL,
    clip_structure TEXT,
    clip_start REAL,
    clip_end REAL,
    clip_video_path TEXT,
    location_id INTEGER,
    location_name TEXT,
    sender TEXT,
    sender_name TEXT,
    sender_photo TEXT,
    user_id TEXT,
    used_count INTEGER DEFAULT 0,
    bulletined INTEGER DEFAULT 0,
    next_bulletin INTEGER DEFAULT 0,
    incident_id TEXT,
    original_text TEXT,
    intro_script TEXT,
    analysis_script TEXT,
    intro_audio_filename TEXT,
    analysis_audio_filename TEXT,
    multi_image_paths TEXT,
    item_video_local TEXT,
    storage_key TEXT,
    item_manifest JSONB,
    s3_key_input TEXT,
    s3_key_script_audio TEXT,
    s3_key_headline_audio TEXT,
    allocated_duration REAL
);

-- Processed reports tracking
CREATE TABLE processed_reports (
    id BIGSERIAL PRIMARY KEY,
    report_id TEXT UNIQUE,
    status TEXT,
    payload JSONB,
    stage TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Event logging
CREATE TABLE item_events (
    id BIGSERIAL PRIMARY KEY,
    event TEXT,
    counter INTEGER,
    media_type TEXT,
    at TIMESTAMP DEFAULT NOW(),
    extra TEXT
);

-- Generated bulletins
CREATE TABLE bulletins (
    id BIGSERIAL PRIMARY KEY,
    bulletin_name TEXT UNIQUE,
    location_id INTEGER,
    location_name TEXT,
    video_url TEXT,
    thumbnail_url TEXT,
    item_count INTEGER,
    total_duration REAL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Application state
CREATE TABLE app_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Media assets tracking
CREATE TABLE media_assets (
    id BIGSERIAL PRIMARY KEY,
    media_type TEXT,
    s3_key TEXT,
    local_path TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Media counters
CREATE TABLE media_counters (
    id SERIAL PRIMARY KEY,
    media_type TEXT UNIQUE,
    counter INTEGER DEFAULT 0
);
```

---

## Detailed API Usage

### Send a News Report via Webhook

```bash
curl -X POST http://localhost:8000/api/webhooks/reports \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -d '{
    "text": "Today at 3 PM, the Chief Minister inaugurated the new highway in Karimnagar.",
    "media_url": "https://example.com/video.mp4",
    "media_type": "video",
    "location_id": 5,
    "location_name": "Karimnagar",
    "category_id": 1,
    "sender_name": "Reporter John",
    "user_id": "user_123"
  }'
```

### Batch Upload (Multiple Items)

```bash
curl -X POST http://localhost:8000/api/webhooks/batch \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {
        "text": "First news item",
        "media_url": "https://example.com/img1.jpg",
        "media_type": "image",
        "location_name": "Kurnool"
      },
      {
        "text": "Second news item",
        "media_url": "https://example.com/img2.jpg",
        "media_type": "image",
        "location_name": "Khammam"
      }
    ]
  }'
```

### Query Incidents/Feed

```bash
# Get all incidents
curl "http://localhost:8000/api/feed"

# Get with pagination
curl "http://localhost:8000/api/feed?page=1&limit=20"

# Get specific location
curl "http://localhost:8000/api/feed?location_id=5"
```

### Health Check with Details

```bash
curl http://localhost:8000/health | jq
```

Response:
```json
{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "s3": "ok",
    "ffmpeg": "ok"
  },
  "response_time_ms": 45.2
}
```

---

## Security Best Practices

### 1. Environment Variables
- Never commit `.env` files to GitHub (already in `.gitignore`)
- Use GitHub Secrets for CI/CD
- Rotate API keys periodically

### 2. Database
- Use SSL/TLS for database connections (`sslmode=require`)
- Use strong passwords
- Restrict database access to your VPS IP only

### 3. AWS S3
- Use IAM users with limited permissions
- Don't use root AWS credentials
- Enable S3 bucket versioning

### 4. API Security
- Implement rate limiting
- Add API key validation
- Use HTTPS in production

---

## Backup and Restore

### Database Backup (PostgreSQL)

```bash
# Backup
pg_dump -h your-host -U your-user -d your-db > backup_$(date +%Y%m%d).sql

# Restore
psql -h your-host -U your-user -d your-db < backup_20260509.sql
```

### S3 Backup

```bash
# Sync entire bucket to local
aws s3 sync s3://your-bucket-name ./backup/

# Restore specific folder
aws s3 sync ./backup/items s3://your-bucket-name/items
```

### Volume Backup (Docker)

```bash
# Backup inputs/outputs directories
tar -czvf localaitv-backup.tar.gz ./inputs ./outputs

# Restore
tar -xzvf localaitv-backup.tar.gz -C ./
```

---

## Performance Optimization

### 1. Database
- Add indexes on frequently queried columns:
  ```sql
  CREATE INDEX idx_news_items_location ON news_items(location_id);
  CREATE INDEX idx_news_items_counter ON news_items(counter);
  CREATE INDEX idx_item_events_at ON item_events(at);
  ```

### 2. Video Processing
- Use hardware acceleration if available
- Limit concurrent FFmpeg processes (handled by governor)

### 3. Memory Management
- Monitor container memory usage
- Set container memory limits in docker-compose

### 4. Caching
- S3 caching is automatic
- Video cache reuses processed items

---

## Scaling Considerations

### Current Limitations
- Single Flask instance (can be scaled with gunicorn)
- Single PostgreSQL connection pool (10 connections)
- Video processing is CPU-intensive

### Future Scaling Options
- Use gunicorn with multiple workers: `gunicorn -w 4`
- Add read replicas for PostgreSQL
- Use GPU instances for video processing
- Implement message queue (Redis/RabbitMQ) for async processing

---

## Troubleshooting

### FFmpeg Not Found
```bash
# Ubuntu
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

### Database Connection Failed
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test connection
psql -h localhost -U localaitv -d localaitv_db
```

### S3 Upload Failed
```bash
# Verify AWS credentials
aws s3 ls s3://your-bucket-name

# Check bucket policy and permissions
```

### High Memory Usage
```bash
# Check container memory
docker stats

# Clean up old images
docker system prune -a
```

### Reset Application
```bash
# Stop services
docker-compose -f docker-compose.prod.yml down

# Remove volumes (will lose all data)
docker-compose -f docker-compose.prod.yml down -v

# Rebuild and start
docker-compose -f docker-compose.prod.yml up --build
```

### Common Issues

1. **TTS Generation Fails**
   - Check Sarvam API key is valid
   - Check API quota limits

2. **Video Processing Slow**
   - Increase CPU resources
   - Check FFmpeg is properly installed
   - Monitor disk I/O

3. **YouTube Stream Drops**
   - Check stream key validity
   - Verify network stability
   - Monitor bitrate settings

4. **Report Processing Stuck**
   - Check database connection
   - Review retry queue in processed_reports table
   - Check for stuck items with `status = 'processing'`

---

## License

MIT License - See LICENSE file for details.

---

## Support

For issues and questions, please open a GitHub issue or contact the maintainers.