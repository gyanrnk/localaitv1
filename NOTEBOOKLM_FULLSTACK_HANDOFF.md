# NotebookLM ↔ UI — Complete Fullstack Integration Guide

Everything you need to integrate **NotebookLM bulletins** into the UI: where they're
stored, how to fetch them, how the upload + render APIs work, and how the
national / state / district / local geography maps to channels.

> **One-line model:** an admin uploads a raw NotebookLM video → our backend wraps it
> (intro + anchor) into a **processed bulletin** and stores it in S3 → the UI fetches the
> processed bulletins from **one GET endpoint** and renders them per location.
> The frontend only **calls** these APIs (it never builds them). The **raw** video is
> never shown — only the **processed** bulletin.

---

## 0. The 2 endpoints you integrate

| # | API | Method | Auth | Purpose |
|---|-----|--------|------|---------|
| 1 | `/v2/api/notebooklm/presign` | POST | Bearer token | Admin upload — get a signed S3 URL to PUT the raw file |
| 2 | `/v2/api/notebooklm/bulletins` | GET | none | Render — list the **processed** bulletins (+ playable URLs) |

- **Base URL:** `https://srv1264596.hstgr.cloud/v2`
  ⚠️ The `/v2` prefix is **mandatory**. The bare root (`…hstgr.cloud/api/…`) returns **502**.
  In the frontend env: `VITE_NOTEBOOKLM_API_URL=https://srv1264596.hstgr.cloud/v2`
- **Auth:** only the **upload** API needs a Bearer token (ask Gyana; keep it in an env var,
  not in committed code). The **render** API is open (no auth).

---

## 1. Big-picture flow

```
  ┌── ADMIN UPLOAD ──────────────────────────────────────────────┐
  │ Admin form ──POST /v2/api/notebooklm/presign (Bearer)──► signed S3 URL │
  │ Admin form ──PUT file──────────────────────────────────► S3 (raw)      │
  └───────────────────────────────────────────────────────┬──────┘
                                                           │  raw stored in geo/…/notebooklm/
                                                           ▼
                         BACKEND STREAMER (automatic, no frontend work)
                         builds the PROCESSED bulletin:
                           intro + welcome anchor + notebooklm + closing anchor
                                                           │
                                                           ▼  stored in geo/…/notebooklm_processed/
  ┌── UI RENDER ─────────────────────────────────────────────────┐
  │ UI ──GET /v2/api/notebooklm/bulletins (poll)──► list + playable URLs    │
  │ UI renders <video src={url}> in the right location (by location_id)     │
  └──────────────────────────────────────────────────────────────┘
```

**The UI gets NotebookLM only from endpoint #2** (poll it). NotebookLM bulletins do **not**
appear in the citizen `/api/bulletins` feed — they live in their **own dedicated endpoint**.

---

## 2. Geography model — national / state / district / local  ⭐ (read this carefully)

This decides **where** a NotebookLM uploaded by the admin shows up in the UI.

### 2.1 Upload levels (what the admin picks)

| scope (+ kind) | meaning |
|---|---|
| **national** | the whole country |
| **state** | one state (`andhra_pradesh` / `telangana`) |
| **district** + `kind=local` | one district's **hyperlocal** news |
| **district** + `kind=district` | one district's **district-level** news |

> `local` and `district` are both under **scope `district`** — one is hyperlocal, the other
> is the whole district.

### 2.2 Fan-out — where each upload appears in the UI

| Admin uploads | Shows on (UI channels) |
|---|---|
| **national** | every channel (all districts) |
| **state** (e.g. AP) | **every district of that state** (Kurnool, Guntur, Kakinada, Nalore, Tirupati) — each with that channel's own intro+anchor |
| **district + local** (e.g. Kurnool) | only **Kurnool** (local) |
| **district + district** (e.g. Kurnool) | only **Kurnool** (district-level) |

### 2.3 What you get back on render — the `kind`

Each channel/location can have up to **four** NotebookLM bulletins:

| `kind` (in the render response) | source | meaning |
|---|---|---|
| `local` | that district's local upload | hyperlocal |
| `district` | that district's district upload | district-level |
| `state` | the state-wide upload, **fanned out to this district** | state news (with the state intro) |
| `national` | the national upload, **fanned out to every channel** | nation-wide news (one bulletin shown on all channels, with the national intro) |

Each render item carries a **`location_id`** so you place it under the correct channel.

---

## 3. API #1 — Upload (admin) : `POST /v2/api/notebooklm/presign`

Two steps: (1) ask the backend for a signed URL, (2) PUT the file straight to S3.

### Step 1 — get the signed URL
```
POST  https://srv1264596.hstgr.cloud/v2/api/notebooklm/presign
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{ "scope": "district", "state": "andhra_pradesh",
  "district": "kurnool", "kind": "local",
  "filename": "notebooklm_2026-06-08.mp4" }
```
Field rules:
| field | rule |
|---|---|
| `scope` | `national` \| `state` \| `district` |
| `state` | required for `state`/`district` → `andhra_pradesh` \| `telangana` |
| `district` | required for `district` (lowercase, see list) |
| `kind` | required for `district` → `local` \| `district` |
| `filename` | **must end in `.mp4`**; use a unique date-based name (don't overwrite) |

Response `200`:
```json
{ "status": "ok",
  "uploadUrl": "https://news-689186650531-ap-south-2-an.s3.ap-south-2.amazonaws.com/…&X-Amz-Signature=…",
  "key": "geo/states/andhra_pradesh/districts/kurnool/local/notebooklm/notebooklm_2026-06-08.mp4",
  "contentType": "video/mp4", "expiresIn": 3600 }
```
Errors: `401` (bad/missing token), `400` (filename not `.mp4`, or invalid scope/state/district/kind combo).

### Step 2 — PUT the file straight to S3
```
PUT  <uploadUrl>
Content-Type: video/mp4
<binary .mp4 body>
```
That's it — the backend streamer turns it into a processed bulletin automatically.

### React example
```js
const BASE  = import.meta.env.VITE_NOTEBOOKLM_API_URL;   // https://srv1264596.hstgr.cloud/v2
const TOKEN = import.meta.env.VITE_NOTEBOOKLM_TOKEN;

// 1) get the signed URL
const r = await fetch(`${BASE}/api/notebooklm/presign`, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ scope:'district', state:'andhra_pradesh',
    district:'kurnool', kind:'local', filename:`notebooklm_${date}.mp4` }),
});
const { uploadUrl } = await r.json();

// 2) PUT the file straight to S3
await fetch(uploadUrl, { method:'PUT', headers:{ 'Content-Type':'video/mp4' }, body: file });
```

> **CORS / origins (already handled server-side — for your awareness):** the S3 bucket
> whitelists specific origins. `http://localhost:5173` (your dev) and `https://localaitv.com`
> are allowed. If you deploy the admin page to a **different** origin, ask Gyana to add it to
> the bucket CORS — the frontend cannot fix CORS itself.

---

## 4. API #2 — Render (UI) : `GET /v2/api/notebooklm/bulletins`

Lists the **processed** bulletins (intro + anchor), each with a **ready-to-play presigned
`.mp4` URL (valid 1 hour)**, newest-first. **No auth.**

```
GET  https://srv1264596.hstgr.cloud/v2/api/notebooklm/bulletins
GET  …/bulletins?location_id=305&kind=local
```
Optional filters (omit for everything):
| param | values |
|---|---|
| `channel` | `Kurnool, Guntur, Kakinada, Nalore, Tirupati, Khammam, Karimnagar, Warangal, Nalgonda` |
| `location_id` | backend location id (`305`=Kurnool, `161`=Khammam, `335`=Tirupati, …) |
| `kind` | `local` \| `district` \| `state` \| `national` |

Response `200`:
```json
{
  "status": "ok",
  "count": 1,
  "items": [
    {
      "channel": "Kurnool",
      "location_id": 305,
      "kind": "local",
      "title": "స్థానిక వార్తలు",
      "date": "08-06-2026",
      "filename": "sthanika_vaartalu_20260608.mp4",
      "key": "geo/states/andhra_pradesh/districts/kurnool/notebooklm_processed/sthanika_vaartalu_20260608.mp4",
      "url": "https://…s3.ap-south-2…&X-Amz-Signature=…",
      "size": 73010548,
      "lastModified": "2026-06-08T10:15:30+00:00"
    }
  ]
}
```
Field meaning:
- **`url`** — playable `.mp4`, drop into a `<video>` tag. **Expires in 1 hour** → re-fetch the
  list for a fresh URL (don't cache `url` long-term).
- **`location_id`** — which channel/location this belongs to (matches citizen bulletins/reports).
- **`title`** — clean **Telugu display name** (e.g. `రాష్ట్ర వార్తలు`). **Show THIS in the UI, not `filename`** — `filename` is an internal ASCII S3 key (underscores/.mp4). `date` is a ready `DD-MM-YYYY` string.
- **`kind`** — `local` / `district` / `state` / `national` (see §2.3) → place it in the right section.
- **`lastModified`** — items are **newest-first**; the first matching item = the latest.

### React example
```js
const res = await fetch(`${BASE}/api/notebooklm/bulletins?location_id=305&kind=local`);
const { items } = await res.json();
const latest = items[0];                          // newest
if (latest) return <video src={latest.url} controls />;
```

### Polling
There is no server push — **poll** this endpoint (on page load + every few minutes) and
re-render. A new bulletin appears in the next poll after it's built. No websocket needed.

---

## 5. Where things are stored in S3 (for your understanding — you don't access S3 directly)

| what | S3 key pattern |
|---|---|
| **RAW** (admin upload, national) | `geo/national/notebooklm/<file>.mp4` |
| **RAW** (state) | `geo/states/<state>/_state/notebooklm/<file>.mp4` |
| **RAW** (district) | `geo/states/<state>/districts/<district>/<local\|district>/notebooklm/<file>.mp4` |
| **PROCESSED — local/district** | `geo/states/<state>/districts/<district>/notebooklm_processed/<sthanika\|jilla>_vaartalu_<date>.mp4` (per-district — content differs per district) |
| **PROCESSED — state** | `geo/states/<state>/_state/notebooklm_processed/rashtra_vaartalu_<date>.mp4` (ONE per state, fanned out to its districts at render) |
| **PROCESSED — national** | `geo/national/notebooklm_processed/jatiya_vaartalu_<date>.mp4` (ONE, fanned out to all channels at render) |

You never touch S3 directly — the APIs give you presigned URLs. The `key` field is shown
only for reference/debugging.

**Lifecycle (automatic):** raw uploads are cleaned up shortly after processing; processed
bulletins are kept for a few days (newest per location+kind always retained). Because old
ones are pruned, **always poll for the latest** rather than caching a fixed item.

---

## 6. Reference data

### Dropdowns (for the upload form)
```js
states = ["andhra_pradesh", "telangana"]
districts = {
  andhra_pradesh: ["kurnool", "guntur", "kakinada", "nalore", "tirupati"],
  telangana:      ["khammam", "karimnagar", "warangal", "nalgonda"]
}
kinds = ["local", "district"]   // only for scope = district
```

### Location IDs (channel ↔ backend id)
```
Karimnagar 75 · Nalgonda 141 · Warangal 154 · Khammam 161 · Kakinada 209
Nalore 285 · Kurnool 305 · Tirupati 335 · Guntur 344
```

---

## 7. Caveats / notes
- **`national` is now LIVE** — a national upload is processed into ONE bulletin and **fanned
  out to every channel** (`kind=national`, with the national intro). state / district / local
  all work too. (Render: make sure the UI handles the `national` kind.)
- **`url` (both endpoints) expires in 1 hour** — re-fetch; don't persist it.
- **NotebookLM is NOT in the citizen `/api/bulletins` feed** — it has its own dedicated
  endpoint (#2). Don't look for it in the citizen feed.
- **CORS is server-side** — the frontend can't fix it. Dev (`localhost:5173`) + `localaitv.com`
  are whitelisted; other origins must be added by Gyana.

---

## 8. Fullstack checklist
- [ ] Set `VITE_NOTEBOOKLM_API_URL=https://srv1264596.hstgr.cloud/v2` and `VITE_NOTEBOOKLM_TOKEN=<token from Gyana>`.
- [ ] **Admin upload page:** form (scope/state/district/kind/filename) → `POST …/presign` (Bearer) → `PUT` file to `uploadUrl`.
- [ ] **Render:** poll `GET …/bulletins`, group by `location_id` + `kind`, play `item.url` in `<video>`, re-fetch every few minutes for fresh URLs.
- [ ] If you deploy to a new origin, tell Gyana to whitelist it in S3 CORS.

## TL;DR
- **Upload:** `POST /v2/api/notebooklm/presign` (Bearer) → `PUT` to the returned S3 URL.
- **Render:** poll `GET /v2/api/notebooklm/bulletins` → play each `item.url`, place by `location_id`+`kind`.
- **Geography:** national → all; state → all districts of the state; district+local/district → that district. (§2)
- **Only the processed bulletin is shown**, only via endpoint #2, URLs expire in 1h.
