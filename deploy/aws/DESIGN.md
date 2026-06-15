# LocalAI TV — AWS Migration Design (Phase 0)

> **Status:** DRAFT for approval. No infrastructure has been created. This document is the
> Phase 0 deliverable: confirmed architecture, decisions/recommendations (§6), target
> architecture, component→service map, live-AWS verification (§9), and a cost envelope.
> **Nothing in §7 Phase 1+ starts until this is approved and the open decisions below are confirmed.**

- **Source repo:** `localaitv1` — `https://github.com/gyanrnk/localaitv1.git` (branch `main`),
  local path `C:\Users\Gyanaranjan kabi\Desktop\localaitv2019_clone\localaitv1`.
- **Migration workspace (this folder):** `C:\Users\Gyanaranjan kabi\AI news AWS`.
- **AWS account:** `689186650531` (verified via `localaitv-phase0` IAM user).
- **Date:** 2026-06-14.

---

## 0. Decision log & reconciliation with existing Mumbai resources (2026-06-14)

**Decisions confirmed by owner:**
- **Streamer topology → Scenario A (hybrid).** GPU builds on AWS; streamers stay on Hostinger;
  S3-native handoff. (~$50–110/mo AWS; avoids ~$1,400/mo YouTube egress.)
- **Approach → rebuild clean via Terraform** from the `localaitv1` repo (source of truth =
  `github.com/gyanrnk/localaitv1.git`, matches live Hostinger prod). The prior Mumbai scaffold is
  treated as a **throwaway experiment**, not reused as the basis.
- **Secrets → SSM Parameter Store (SecureString).**
- **O1 (TTS) resolved → API-key path** (`GOOGLE_TTS_API_KEY`); `adc.json` not required (the code uses
  ADC only when the key is unset, per `tts_handler_gcp.py` `_get_client`).
- **Isolation → all work on an `aws-migration` branch; `main`→Hostinger deploy untouched until cutover.**

**Prior Mumbai experiment (ap-south-1, acct 689186650531) — to be superseded, NOT reused:**

| Resource | Identity | State |
|---|---|---|
| EC2 `localaitv-pipeline` / `localaitv-streamer` / `localaitv-gpu-test` | c6i.large / c6i.2xlarge / **g4dn.xlarge** (bare Ubuntu) | **stopped** |
| RDS `localaitv-pipeline-db` | Postgres 16.14, db.t4g.small, public | **available (running, ~$25–30/mo)** |
| ECR `localaitv-builder` | `:latest` ~668 MB (**CPU image, no CUDA**) | present |
| SQS `localaitv-build-queue.fifo` + DLQ | FIFO, vis 1800s, maxReceive 3 | idle |
| ECS `localaitv-builders` | 4 task defs, **GPU=null / Fargate-shaped (CPU libx264)** | 0 capacity, 0 services |
| S3 `localaitv-content-mumbai` | in-region content + `_deploy/pipeline/*.box-current.py` snapshots | active |

- The prior effort completed **SQS dispatch + containerized CPU builds + RDS + secrets**, but **never
  did GPU/NVENC or autoscaling** — which is exactly this brief's core. It also evolved the pipeline
  code (sqs_dispatcher, claim model, `CDN_BASE_URL`); per the "rebuild clean" decision we do **not**
  carry that code forward — we extend the `localaitv1` repo with flag-gated changes instead.
- **Collision avoidance:** Terraform creates **new, distinctly-named** resources. Proposed prefix
  **`laitv-<env>-*`** (e.g. `laitv-stg-builder`, `laitv-stg-build-queue.fifo`, cluster
  `laitv-stg-builders`) so nothing clashes with the experiment.

**D-DB (resolved):** RDS `localaitv-pipeline-db` had **0 connections for 7 days** and no local config
referenced it (prod DB host is Hostinger/`srv1002.hstgr.io`; pipeline uses CloudSQL). Confirmed NOT
production → **keep CloudSQL (per brief §6.6)**; RDS was experiment.

**D-CLEANUP (EXECUTED 2026-06-14):** Idle experiment decommissioned (owner-approved "full cleanup +
snapshots"). Recovery artifacts retained:
- RDS final snapshot **`localaitv-pipeline-db-final-20260614`** (restore to recover the DB).
- AMIs **`ami-078ff571ed87693cb`** (pipeline), **`ami-061b343c16ff39d57`** (gpu-test),
  **`ami-0e8bceb86f1590fd1`** (streamer) — restore to recover instance contents.
- Deleted: RDS instance, 3 EC2 (terminated, ~280 GB EBS freed), ECR `localaitv-builder` + images,
  SQS `localaitv-build-queue.fifo` + DLQ, ECS cluster `localaitv-builders` + task defs, key pair
  `localaitv-pipeline-key`, security groups `localaitv-pipeline-sg` / `localaitv-rds-sg`.
- **Untouched:** all S3 buckets (ap-south-2 prod + `localaitv-content-mumbai`), default VPC, IAM role
  `EC2-SSM-Role_app`. Idle cost stopped ≈ ~$58/mo.

---

## 0.1 Real-time "shorts" path — owner's PRIMARY focus (added 2026-06-14)

Owner emphasis: the top priority is the **real-time per-item path**, not just the YouTube bulletins:
**report input → process → Incidents API → short renders on the PWA main page, in real time.**

How it works in code (`main.py._send_to_incidents_api` + `_convert_path_to_url`):
- A report input is processed — AI headline/description (OpenAI/Gemini) + TTS audio (Google) — and its
  **raw uploaded media** (image/video) is referenced (`media_info['input_path']`).
- `_send_to_incidents_api` POSTs `{title, description, category_id, location_id, audio_path,
  cover_image_path, video_path}` to **`LOCALAITV_API_URL = https://localaitv.com/api/incidents`**
  (Bearer `LOCALAITV_API_TOKEN`) → returns `incident_id` → the PWA renders it as a "short".
- **This path does NOT need GPU/FFmpeg** — the short = raw media + AI text + TTS audio. GPU is only for
  the heavy 10-min **bulletin/stream** path. The two paths are separate, both fed by report inputs:
  - **Real-time shorts (PRIORITY):** light — LLM + TTS + media upload + incident POST (seconds).
  - **Bulletins (brief's GPU target):** heavy — NVENC composition → YouTube (the scaling bottleneck).

Migration implication (critical; flag-gated "storage handoff" — allowed by brief §0.4):
- `_convert_path_to_url` emits **`{API_BASE_URL}/api/media/{rel}`** — the pipeline host's own media
  server. On Hostinger that host is long-lived so it resolves. **On AWS, item media must be uploaded to
  S3 and the incident payload must carry S3/CDN URLs** (`s3_storage.upload_file` + `public_url` exist),
  else shorts would point at an ephemeral/host-bound URL and 404.
- Item-processing + incident fire should run on the **long-lived app/web service (desired=1)** — which
  is already required to be a singleton (planner/poller/cleanup). The GPU fleet only handles bulletins.
- **Acceptance (validate FIRST):** a report input appears as a short on the PWA main page in real time,
  with media served from S3/CDN.

Open: confirm (a) this understanding, and (b) whether to stand up / validate the real-time shorts path
on AWS **ahead of** the GPU bulletin fleet.

---

## 0.2 Real-time scaling design — two autoscaling pools (added 2026-06-14)

**Confirmed: horizontal auto-scaling DOES parallelize report processing.** The LLM `Semaphore(1)`
(+1s sleep, [openai_handler.py:900](../../openai_handler.py)) and TTS `Semaphore(MAX_TTS_CONCURRENCY=3)`
are **per-process** — the handler is created inside each process (`NewsBot()` / `get_llm_handler()`), so
**N worker processes → N× aggregate concurrency**. The current single-app caps (batch
`ThreadPoolExecutor(max_workers=3)`, LLM 1-at-a-time, TTS 3) are intentional **provider-429 guards**, so
the true ceiling is the **LLM/TTS provider quota**, not instance count.

Architecture = **1 orchestrator + 2 independent autoscaling worker pools**:

| Component | Role | Hardware | Scale signal | Count |
|---|---|---|---|---|
| **Orchestrator** | singleton loops (planner, report-poller, retry, cleanup) — *enqueue jobs only* | small CPU | n/a | **desired=1** |
| **Report workers** | real-time shorts: `process_message` (LLM+TTS+media) → post to Incidents API (S3/CDN URLs) | CPU (cheap; Fargate-ok, **no GPU**) | report-queue depth | 0…N |
| **Builder workers** | heavy bulletin composition (NVENC) → S3 → YouTube | GPU g4dn | build-queue depth | 0…N |

Why not "just auto-scale the current app": planner/poller/cleanup are **singletons** — running them on
every replica would double-build. They stay on the orchestrator (desired=1); only **stateless** workers scale.

**Provider-quota sizing:** aggregate concurrency = (report workers) × (per-worker permits). Size
worker-max + OpenAI/Gemini RPM/TPM + Google TTS quota *together*; keep a per-worker semaphore ≈
(quota ÷ max workers) so scaling never exceeds the provider limit. Request quota raises early (lead time).

**The report worker is a thin NEW file that REUSES existing logic unchanged** — it calls the existing
`NewsBot.process_message(...)` (returns `{success, script, headline, audio_path, media_info, files}`)
and the existing Incidents-API post path. The only existing-file hooks are the already-listed flag-gated
ones (`_convert_path_to_url` → S3/CDN; producer enqueues to the report queue behind a flag). Built as new
files, tested local→staging, pushed only when proven.

Sketch (pseudocode — design only, NOT committed/runnable):

```python
# report_worker.py  (NEW file, sketch) — reuses existing NewsBot; zero edits to existing logic
from main import NewsBot               # existing, unchanged
import sqs_helper, s3_storage          # sqs_helper = new thin wrapper; s3_storage exists
bot = NewsBot()                        # per-process → its own LLM/TTS semaphores

while True:
    msg = sqs_helper.receive(REPORT_QUEUE_URL, wait=20)            # long-poll SQS
    if not msg:
        continue
    try:
        job = msg.body  # {sender, text, media_s3_key, location_id, location_address, category_id}
        media_path = s3_storage.download_to_tmp(job["media_s3_key"]) if job.get("media_s3_key") else None
        # ── EXISTING processing, untouched: media + LLM headline/script + TTS audio ──
        result = bot.process_message(
            text=job.get("text"), media_path=media_path, sender=job["sender"],
            location_id=job.get("location_id"), location_address=job.get("location_address", ""))
        if result.get("success"):
            post_to_incidents(result)   # existing post path; media URLs S3/CDN (flag-gated change)
            sqs_helper.delete(msg)      # ack
        else:
            sqs_helper.release(msg)     # retry; DLQ after maxReceiveCount
    except Exception:
        sqs_helper.release(msg)         # visibility timeout → retry
```

One worker = one in-flight LLM call per location handler; **M workers = M concurrent**. Auto-scale M on
report-queue `ApproximateNumberOfMessagesVisible`, floor 0. Idempotency via the existing MessageQueue
dedup + an SQS dedup id. Producer (orchestrator) enqueues a report job instead of in-process processing
when `REPORT_BACKEND=sqs` (flag; default `local` = today's behavior).

---

## 0.3 Processing guarantees — HARD requirements (owner, 2026-06-14)

Non-negotiable for the report path:
1. **Exactly-once processing** — one report is handled by exactly ONE worker; never duplicated across instances.
2. **No drops** — every report received MUST be processed (none lost under burst or crash).
3. **Scale on NEW distinct work only** — a new instance spawns only for new *unclaimed* input; it never
   re-processes input another worker already claimed.

How the SQS design enforces each:
- **One-worker-per-message:** on `receive`, the message is hidden by the **visibility timeout** (claimed)
  so no other worker sees it; on success the worker **deletes** it. Two workers never process the same report.
- **Scale = capacity for unclaimed work:** autoscale on **`ApproximateNumberOfMessagesVisible`** (backlog of
  *visible/unclaimed* messages), target backlog-per-worker. In-flight messages are invisible/claimed, so a new
  instance picks up only NEW messages — never a duplicate of a claimed one.
- **Nothing dropped:** SQS is durable; a worker crash → visibility timeout lapses → message reappears → retried.
  Poison messages go to the **DLQ** after `maxReceiveCount` (parked for inspection, never silently lost).
- **Idempotency (rare-redelivery safety):** FIFO `MessageDeduplicationId` (report_id/content hash) + existing
  `MessageQueue` dedup (msg-id/content, 1h) + DB claim columns (`bulletined`/`claimed_at`).
- **Safe scale-in:** worker finishes + acks the current message before terminating (ECS task drain / ASG
  scale-in protection during processing) → scale-down never interrupts or duplicates work.
- **Enqueue reliability:** intake enqueues the report to SQS durably (after the MessageQueue assembles a
  complete report = matched media+text+audio) **before** acking the webhook → no report lost at intake.

**Acceptance test:** force a burst of 50 distinct reports → exactly **50 processed, 0 duplicates, 0 drops**;
workers scale up on visible backlog and back to **0** when drained; a deliberately killed worker's in-flight
report is **retried**, not lost. Same guarantees apply to the builder (bulletin) queue.

---

## 1. Confirmed architecture (§2 verified against code, with corrections)

One Python 3.11 image (`Dockerfile`), two runtime roles in `docker-compose.prod.yml`:

| Role | Entry | Port | Nature | Notes |
|---|---|---|---|---|
| `app` | `webhook_server.py` (Flask, `python webhook_server.py`) | 8001 | Web + background worker **threads** | Health at `/health`; module-level daemon threads: planner, report-poller, retry, cleanup |
| `streamer` | `yt_streamer.py` | — | Long-lived FFmpeg → YouTube **RTMPS** | `STREAM_MODE=copy`; one pipe per channel; watches `WATCH_DIR_BASE=/app/outputs/bulletins` |

**Heavy compute (build path):**
- `video_builder.py` — FFmpeg composition. `VIDEO_CODEC='libx264'`, `PRESET='veryfast'`, CBR
  `VIDEO_BITRATE/MAXRATE=4000k`, `BUFSIZE=8000k`, `GOP_SIZE=50` (`FPS=25`), `-keyint_min 50`,
  `-sc_threshold 0`, `-pix_fmt yuv420p`, audio `aac 128k 44100 stereo`, `1920×1080`.
- `ticker_overlay.py` — Playwright/Chromium render + FFmpeg re-encode. Separate profile:
  `libx264`, `PRESET='ultrafast'`, `CRF=23`.
- `governor/build_queue.py` — singleton `BuildQueue` with **one worker thread**; runs **one build
  at a time** as a subprocess (`process_wrapper.py builder …` → `video_builder.py`), `block=True`.
  `MAX_QUEUE_SIZE=10`, `BUILD_TIMEOUT=3600s`. **This single-host serialization is the bottleneck.**
- `governor/cpu_governor.py` — throttles builds (sleep between FFmpeg calls) based on live stream
  count + CPU%; `governor/stream_registry.py` is a **local JSON file** of active streams.
- `governor/process_wrapper.py` — launches builder with `nice 15` + `taskset -c 4,5,6,7`.

**State & integrations:**
- **S3 already in use** (`s3_storage.py`, `s3_bulletin_fetcher.py`), region `ap-south-2`. Two
  buckets: own (`S3_BUCKET_NAME`, creds `AWS_ACCESS_KEY_ID`) and `_M` (`S3_BUCKET_NAME_M`, creds
  `AWS_ACCESS_KEY_ID_M`). `s3_storage.py` already defines bulletin keys:
  `bulletins/{channel}/{name}.mp4` and `…_manifest.json`.
- **DB:** external CloudSQL Postgres via `DATABASE_URL` (`sslmode=require`).
- **LLM:** OpenAI (`gpt-4o`) + Gemini.
- **TTS:** Google Cloud TTS / Sarvam. **WhatsApp:** Gupshup.
- **CI/CD:** `.github/workflows/deploy.yml` → security/smoke tests → build → push to **GHCR** →
  SSH deploy to Hostinger `/root/localaitv1` (`docker compose -f docker-compose.prod.yml up -d`).

### Corrections to the brief (these change the migration)

1. **No separate "builder" service exists today.** Builds run as **subprocesses inside the `app`
   container** (webhook → `_build_video_bg` thread → `queue_bulletin_build`). The SQS/worker split
   is new wiring, not a re-host.
2. **The streamer does NOT transcode.** `STREAM_MODE=copy` → it stream-copies pre-built bulletins
   to RTMPS. **GPU/NVENC only helps the build path; it does nothing for the streamer.** Streamers
   are cheap CPU + heavy bandwidth.
3. **Gemini uses an API key, not Vertex/`adc.json`** — `google_genai.Client(api_key=GEMINI_API_KEY)`.
   No `vertexai`/`GEMINI_USE_VERTEX` anywhere. `adc.json`/`GOOGLE_APPLICATION_CREDENTIALS` appears
   only in `tts_handler_gcp.py` comments; prod compose passes `GOOGLE_TTS_API_KEY`. **So `adc.json`
   is likely not mounted in prod today.** → *Open question O1.*
4. **`CDN_BASE_URL` is not in this repo** (likely the PWA's; out of scope).
5. **10 channel slots are defined** (Khammam, Kurnool, Karimnagar, Anatpur, Kakinada, Nalore,
   Tirupati, Guntur, Warangal, Nalgonda), not 9; active count = `STREAM_COUNT` (default 3,
   `.env.example`=7).
6. **`_M` bucket is a separate AWS account** (distinct access keys) → an IAM task role covers the
   own bucket, but `_M` needs a cross-account bucket policy or keeps using keys.
7. **`process_wrapper.py` pins `taskset -c 4,5,6,7`** (assumes ≥8 cores) → would fail on a 4-vCPU
   g4dn.xlarge; the SQS builder path must bypass it.
8. **`stream_registry.py` is local-JSON** → not shared across hosts (irrelevant once builders leave
   the streamer host).
9. **`app` starts singleton loops at import** (planner/report-poller/retry/cleanup) → the web/app
   service must run at **desired count = 1** (or get leader election); it can't naively autoscale.
10. **No `gunicorn`** — Flask is served by `python webhook_server.py` (dev server). Out of scope to
    change, noted for awareness.

---

## 2. Live AWS verification (§9) — measured, not assumed

Queried from `localaitv-phase0` (acct `689186650531`):

| Check | ap-south-2 (Hyderabad) | ap-south-1 (Mumbai) |
|---|---|---|
| g4dn / g5 / g6 offered (by AZ) | **none — zero GPU offered** | g4dn.xlarge in **1a/1b/1c**; g5.xlarge in 1a/1b; g6.xlarge in 1a/1b; g4dn.2xlarge in all 3 |
| On-Demand **G/VT vCPU quota** (`L-DB2E81BA`) | **0** | **8** (= 2× g4dn.xlarge @ 4 vCPU) |
| g4dn.xlarge On-Demand price | — | **$0.579 / hr** (verified via Pricing API) |

**Hard conclusions:**
- **GPU compute must run in ap-south-1.** ap-south-2 (where S3 lives) offers no GPU at all.
- **Fargate has no GPU** → builders must be ECS-on-EC2 / EKS / Batch (confirmed).
- **The 8-vCPU quota caps you at 2 concurrent g4dn.xlarge builders today.** Running ~10 parallel
  builds needs a quota increase (e.g. **40 vCPU**) — **this has lead time; request it now** (see
  Action A1). Until then, autoscaling tops out at 2 builders.
- ECS GPU-optimized AMI: resolve dynamically at apply time via the SSM public parameter
  (`/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended`); the scoped phase-0 user
  couldn't read it, so the exact path is confirmed in Phase 2 from the Terraform/CI role.

---

## 3. ⚠️ Cost finding that shapes the architecture

**YouTube egress dominates everything.** At 4 Mbps video + 128 kbps audio per stream × 10 channels
× 24/7 ≈ **~13 TB/month of data-transfer-out**. At ap-south-1 internet egress (~$0.1093/GB) that is
**≈ $1,400/month** — vs. a g4dn.xlarge builder at ~$0.58/hr. Hostinger VPS bandwidth is typically
bundled/cheap, so **moving the *streamers* to AWS is both the most expensive change and the one that
does *not* address the stated bottleneck.**

The objective — *parallel, GPU-accelerated builds that autoscale to zero when idle* — is fully met by
moving **only the build fleet** to AWS and leaving streaming where bandwidth is cheap. This is the
basis for the recommended topology below (Scenario A).

---

## 4. Decisions & recommendations (§6)

> Each is a recommendation **awaiting your confirmation**. O-items are open questions.

**6.1 Compute platform → ECS-on-EC2 (GPU builders) + SQS.** Closest to the current Compose model,
supports GPU (Fargate doesn't), least new ops vs EKS. AWS Batch is a clean fit for bursty GPU jobs
but adds a job-definition layer over the existing subprocess model; SQS+ECS keeps `video_builder.py`
unchanged. **Streamers: recommend keeping off AWS** (see §3) rather than CPU ECS.

**6.2 Region → ap-south-1 (Mumbai) for all compute** (forced by GPU availability). S3 stays in
ap-south-2; cross-region transfer for ~10–20 MB bulletins is a few dollars/month.

**6.3 GPU type → g4dn.xlarge** (1× T4, unlimited NVENC sessions, cheapest GPU, $0.579/hr On-Demand;
Spot typically far cheaper — verify at apply). Move to g5/A10G only if a single build is too slow on
T4 or filters are GPU-bound.

**6.4 Handoff → S3-native** *if* streamers stay off-AWS (recommended): the builder uploads to
`bulletins/{channel}/{name}.mp4` (keys already exist in `s3_storage.py`) and streamers pull via the
existing `s3_bulletin_fetcher.py` path. **EFS only works if streamers also move to AWS** — EFS cannot
span AWS↔Hostinger. *This choice is coupled to O2 (streamer location).*

**6.5 Build orchestration → SQS**, workers autoscale on `ApproximateNumberOfMessagesVisible`, floor
**0**. Replaces the in-process single-slot `build_queue.py`. (Batch viable; SQS chosen for minimal
code change.)

**6.6 Database → keep CloudSQL.** Allow-list the ap-south-1 NAT egress IP; `sslmode=require` already
set. RDS is an optional later phase.

**6.7 NVENC rollout → `VIDEO_ENCODER` flag (`nvenc` | `libx264` | `auto`).** Auto-detect a usable
`h264_nvenc` encoder, else fall back to `libx264`, instantly reversible per-deployment. **Scope to
get right (Phase 3):** there are **two encode profiles** (builder CBR + ticker CRF) **and hardcoded
`libx264` call sites** (`video_builder.py` ~lines 2173/2764/2800/2829 + the CBR-injection helper
~line 280) that must *all* honor the flag. Proposed param mapping, preserving the YouTube spec:

| libx264 (current) | h264_nvenc (target) | Note |
|---|---|---|
| `-preset veryfast` | `-preset p4 -tune ll` | speed/quality knob differs; tune for latency-low |
| `-b:v 4000k -maxrate 4000k -bufsize 8000k` | same + `-rc cbr` | force CBR on NVENC |
| `-g 50 -keyint_min 50 -sc_threshold 0` | `-g 50 -no-scenecut 1` | keyframe cadence preserved |
| `-pix_fmt yuv420p` | `-pix_fmt yuv420p` | identical |
| ticker `-crf 23` | `-rc vbr -cq 23` (or keep libx264 for ticker) | CRF has no exact NVENC twin |

Any setting that can't match 1:1 (e.g. x264 `-tune`, exact B-frame behavior, profile/level) will be
**flagged for your decision**, not silently changed. Output is validated by `ffprobe` diff in Phase 4.

---

## 5. Target architecture (recommended: Scenario A — hybrid)

```
                         ┌──────────────────────── AWS ap-south-1 (Mumbai) ────────────────────────┐
                         │                                                                          │
  WhatsApp/Gupshup ─►  app/web (ECS-on-EC2, desired=1)        SQS build queue                       │
  reports/webhooks      webhook_server.py (Flask :8001)   ┌─► localaitv-builds ──┐                  │
                         │  planner/poller/retry/cleanup    │   (visible msgs)    │                  │
                         │  ENQUEUE build msg ──────────────┘                     ▼                  │
                         │                                          GPU builder ASG (ECS capacity)   │
                         │                                          g4dn.xlarge, Spot, floor=0       │
                         │                                          video_builder.py + ticker        │
                         │                                          h264_nvenc (VIDEO_ENCODER flag)   │
                         │                                                     │ upload bulletin      │
                         │   CloudWatch logs/metrics/alarms                    ▼                      │
                         │   (queue depth, GPU util, build ok/fail) ───►  scale builders on depth     │
                         └─────────────────────────────────────────────────────┼────────────────────┘
                                                                                │ S3 PutObject
   ┌──────────────── GCP ────────────────┐        ┌──────── AWS S3 ap-south-2 (existing) ───────────┐
   │ CloudSQL Postgres (DATABASE_URL)     │◄──────►│ S3_BUCKET_NAME  bulletins/{channel}/{name}.mp4  │
   │ (allow-list ap-south-1 NAT IP)       │        │ S3_BUCKET_NAME_M (cross-account)                │
   └──────────────────────────────────────┘        └──────────────────────┬─────────────────────────┘
                                                                            │ s3_bulletin_fetcher pull
   ┌──────── Hostinger VPS (unchanged bandwidth-cheap host) ────────────────▼────────────┐
   │ streamer: yt_streamer.py  STREAM_MODE=copy  ──►  YouTube RTMPS (10 channels)         │
   │ (the ~13 TB/mo egress stays here, where it's bundled/cheap)                          │
   └─────────────────────────────────────────────────────────────────────────────────────┘
```

*Scenario B (all-in AWS):* streamers also run on CPU ECS in ap-south-1 with an **EFS** handoff
(`WATCH_DIR_BASE` → EFS mount). Functionally clean, but adds streamer instances **and ~$1,400/mo
egress**. Offered only if you want zero Hostinger footprint.

---

## 6. Component → AWS service map

| Current | Recommended AWS target |
|---|---|
| `app` container (Flask + singleton loops) | ECS-on-EC2 service, **desired=1**, small CPU instance (e.g. t3.medium) |
| `governor/build_queue.py` (single-slot) | **Amazon SQS** queue (`BUILD_BACKEND=sqs`) |
| Build subprocess (`video_builder.py`) | **ECS-on-EC2 GPU builder** (g4dn.xlarge, Spot, ASG floor 0) consuming SQS |
| `cpu_governor.py` throttle | **No-op on dedicated GPU workers** (no stream contention on-host) |
| Shared `./outputs/bulletins` handoff | **S3-native** (`bulletins/{channel}/…`, keys already exist) [Scenario A] / **EFS** [Scenario B] |
| `streamer` container | **Stays on Hostinger** [A] / CPU ECS service [B] |
| GHCR image | **Amazon ECR** (new push job; GHCR/Hostinger job left intact) |
| `.env` (~40 vars) + `adc.json` | **SSM Parameter Store (SecureString)** via task-def `secrets`/`valueFrom` |
| Local logs (`json-file`) | **CloudWatch Logs** + dashboards/alarms |
| CloudSQL Postgres | **Unchanged** (allow-list NAT IP) |
| S3 (ap-south-2, 2 buckets) | **Unchanged**; IAM task role for own bucket, keys/bucket-policy for `_M` |

---

## 7. Secrets plan (§5)

- **Default: AWS SSM Parameter Store (SecureString)** under `/localaitv/<env>/<KEY>`. Cheaper than
  Secrets Manager (standard params free; SecureString uses a free KMS default) and sufficient — you
  don't currently rotate these. **Recommend SSM**; choose Secrets Manager only if you want managed
  rotation (it adds ~$0.40/secret/mo + API costs).
- ECS task definitions pull each value via `secrets: [{ valueFrom: <SSM ARN> }]` — **not baked env**.
- **IAM task role** for S3 (own bucket); keep `AWS_ACCESS_KEY_ID*` env as a working fallback so code
  needs no change on day one. `_M` (cross-account) keeps keys or gets a cross-account bucket policy.
- `adc.json`: **only if O1 confirms TTS uses the ADC path** — store as one SecureString, write to the
  `GOOGLE_APPLICATION_CREDENTIALS` path at container start. Otherwise skip (prod uses `GOOGLE_TTS_API_KEY`).
- **Zero secrets in git** — examples use placeholders only; the existing CI secret-scan stays.

---

## 8. Cost envelope (ap-south-1, monthly, indicative)

| Item | Scenario A (hybrid, recommended) | Scenario B (all-in AWS) |
|---|---|---|
| GPU builders (g4dn.xlarge) | Spot, scale-to-zero, ~3 builder-hrs/day ≈ **$15–55** | same |
| app/web (t3.medium, 24/7) | **~$30–40** | ~$30–40 |
| Streamers | **$0 (stay on Hostinger)** | CPU instance(s) ~$120–250 |
| **YouTube egress (~13 TB)** | **$0 on AWS (stays on Hostinger)** | **~$1,400** |
| EFS handoff | not used | ~$5–20 |
| S3 cross-region (bulletins) | ~$2–10 | ~$2–10 |
| SQS / ECR / CloudWatch | ~$1–5 | ~$1–5 |
| **Approx. AWS total** | **~$50–110 / mo** | **~$1,560–1,700 / mo** |

The contrast is the whole argument for Scenario A. On-Demand builders (if Spot interruptions hurt
build SLAs) raise A's builder line to ~$50–150/mo — still far below B.

---

## 9. Open decisions awaiting your confirmation

- **O1 — TTS credentials:** Does prod actually use `GOOGLE_APPLICATION_CREDENTIALS`/`adc.json` for
  Google TTS, or only `GOOGLE_TTS_API_KEY`? (Decides whether we inject `adc.json` at all.)
- **O2 — Streamer location:** Scenario A (keep streamers on Hostinger, S3 handoff — recommended) vs
  Scenario B (streamers on AWS, EFS handoff, +~$1,400/mo). **This drives §6.4.**
- **O3 — Confirm §6.1/6.3/6.5/6.6/6.7** as recommended above.
- **O4 — Secrets store:** SSM (recommended) vs Secrets Manager (rotation).
- **O5 — Workspace/git model for Phase 1+:** keep AWS files standalone in `AI news AWS`, or clone
  `localaitv1` here so the flag-gated code changes (Phase 3) live as branches/PRs against the repo.

## 10. Actions with lead time (start now)

- **A1 — Request a GPU quota increase** in ap-south-1: `Running On-Demand G and VT instances`
  (`L-DB2E81BA`) from **8 → e.g. 40 vCPU** (10× g4dn.xlarge). Until granted, parallelism caps at 2.
- **A2 — (If Spot)** also confirm Spot G/VT quota; plan On-Demand fallback for build SLAs.

---

## 11. Phased plan (recap, refined by findings)

- **Phase 0 (this doc)** — approve decisions above. *No infra.*
- **Phase 1** — add a **GPU builder image** (CUDA base + NVENC FFmpeg + fonts-noto + Playwright;
  verify `ffmpeg -encoders | grep nvenc`), push to **ECR**, extend CI with an ECR job (GHCR/Hostinger
  job untouched), migrate secrets to SSM.
- **Phase 2** — Terraform in `deploy/aws/terraform/`: VPC/networking, ECR, ECS cluster + GPU ASG
  capacity provider, SQS, IAM roles, SSM params, security groups, CloudWatch, autoscaling (queue
  depth → desired count, floor 0). (+EFS only under Scenario B.) Stand up **staging**.
- **Phase 3** — flag-gated code: `VIDEO_ENCODER` (NVENC + libx264 fallback, output spec preserved),
  `BUILD_BACKEND=sqs|local` (keep VPS path working). Builder consumes SQS; handoff per O2.
- **Phase 4** — validate (ffprobe spec diff vs VPS build; audio-exclusivity/ticker/BGM/intro
  unchanged), load-test all channels, confirm scale up + back to floor; CloudWatch dashboards/alarms.
- **Phase 5** — runbook + **rollback to Hostinger**; per-channel canary cutover; Hostinger kept warm.

## 12. Rollback posture

The Hostinger path (`docker-compose.prod.yml`, `setup-vps.sh`, GHCR job, SSH deploy) is **never
modified or removed** through Phase 4. Every AWS change is additive (new files/dirs, new CI job, new
infra). Cutover is reversible per-channel by repointing the streamer source back to the VPS-built
bulletins and setting `BUILD_BACKEND=local`. Full rollback = stop using the AWS build fleet; Hostinger
continues unaffected.
