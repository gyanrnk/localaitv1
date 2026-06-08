# NotebookLM ↔ UI — Fullstack Handoff

**Goal:** admin uploads a NotebookLM file → backend auto-builds a **processed bulletin**
(intro + anchor) → **UI renders the processed bulletin**.

> Frontend does **not** build any API. The backend (already built & running) provides
> them. Frontend only **calls** them. The **raw** video is never shown in the UI — only
> the **processed** bulletin.

---

## The flow

```
  Admin form ──POST /api/notebooklm/presign──► gets a signed PUT URL   (backend gives slip)
  Admin form ──PUT file──────────────────────► S3 (direct; file never touches the server)
                                                   │
                          backend streamer auto-builds the PROCESSED bulletin
                          (intro + welcome anchor + notebooklm + closing anchor)
                                                   │
                                                   ▼
  UI page ──GET /api/notebooklm/bulletins──► processed list + playable URL
          └─ render <video src=url> ✅  (RAW is never listed here)
```

Only **2 APIs** matter for this use-case:

| API | Side | UI shows it? |
|---|---|---|
| `POST /api/notebooklm/presign` | Admin upload (input) | ❌ input only |
| `GET /api/notebooklm/bulletins` | UI render (output) | ✅ **only this** |

**Base URL:** `https://srv1264596.hstgr.cloud/v2`  ⚠️ **note the `/v2`** — the API is served under `/v2`. The bare root (`https://srv1264596.hstgr.cloud/api/...`) returns **502** (proxies to a dead port). Always prefix `/v2`.
So in the frontend env: `VITE_NOTEBOOKLM_API_URL=https://srv1264596.hstgr.cloud/v2`.
**Auth:** Bearer token needed **only** for the upload API. Ask Gyana for the value (never hard-code it in committed frontend code — use an env var).

> **Note on file upload (PUT to S3):** after presign, the browser PUTs the file directly to S3. The S3 bucket must allow **CORS** for `PUT` from the frontend origin (e.g. `http://localhost:5173` and the prod origin). If the PUT fails with a CORS error, ask Gyana to add the bucket CORS rule (backend-side, one-time).

---

## 1) Upload a NotebookLM file — `POST /api/notebooklm/presign`

Two steps: (1) ask the backend for a signed URL, (2) PUT the file straight to S3.

### Step 1 — get the signed URL
```
POST <APP_BASE>/api/notebooklm/presign
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{ "scope": "district", "state": "andhra_pradesh",
  "district": "kurnool", "kind": "local",
  "filename": "notebooklm_2026-06-08.mp4" }
```
Field rules:
| field | values / rule |
|---|---|
| `scope` | `national` \| `state` \| `district` |
| `state` | required for `state`/`district` → `andhra_pradesh` \| `telangana` |
| `district` | required for `district` (lowercase) — see dropdown list |
| `kind` | required for `district` → `local` \| `district` |
| `filename` | **must end in `.mp4`**; use a unique date-based name (don't overwrite) |

Response `200`:
```json
{ "status": "ok",
  "uploadUrl": "https://...s3...&X-Amz-Signature=...",
  "key": "geo/states/andhra_pradesh/districts/kurnool/local/notebooklm/notebooklm_2026-06-08.mp4",
  "contentType": "video/mp4", "expiresIn": 3600 }
```
Errors: `401` (bad/missing token), `400` (filename not `.mp4`, or invalid scope/state/district/kind combo).

### Step 2 — upload the file directly to S3
```
PUT <uploadUrl>
Content-Type: video/mp4
<binary .mp4 body>
```
Done. The backend streamer then automatically turns it into a processed bulletin.

### Example (React)
```js
// 1) get the slip
const r = await fetch(`${BASE}/api/notebooklm/presign`, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ scope:'district', state:'andhra_pradesh',
    district:'kurnool', kind:'local', filename:`notebooklm_${date}.mp4` }),
});
const { uploadUrl } = await r.json();
// 2) push file straight to S3
await fetch(uploadUrl, { method:'PUT', headers:{ 'Content-Type':'video/mp4' }, body: file });
```

---

## 2) Render processed bulletins — `GET /api/notebooklm/bulletins`

Lists the **processed** bulletins (intro + anchor) the streamer built, each with a
**ready-to-play presigned `.mp4` URL (valid 1 hour)**, newest first. **No auth.**

```
GET <APP_BASE>/api/notebooklm/bulletins
GET <APP_BASE>/api/notebooklm/bulletins?location_id=305&kind=local
```
Optional filters (omit for everything):
| param | values |
|---|---|
| `channel` | `Kurnool, Guntur, Kakinada, Nalore, Tirupati, Khammam, Karimnagar, Warangal, Nalgonda` |
| `location_id` | backend location id (e.g. `305`=Kurnool, `161`=Khammam, `335`=Tirupati) |
| `kind` | `local` \| `district` \| `state` |

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
      "filename": "nlm_local_20260608_101530.mp4",
      "key": "geo/states/andhra_pradesh/districts/kurnool/notebooklm_processed/nlm_local_20260608_101530.mp4",
      "url": "https://...s3...&X-Amz-Signature=...",
      "size": 73010548,
      "lastModified": "2026-06-08T10:15:30+00:00"
    }
  ]
}
```
- `url` = playable `.mp4` → drop into a `<video>` tag. **Expires in 1h** → re-fetch the list for a fresh URL (don't cache `url` long-term).
- `location_id` matches citizen bulletins/reports → place each bulletin under the correct location/channel in the UI.
- Items are **newest-first** → first matching item = the latest for that location.

### Render (React)
```js
const res = await fetch(`${BASE}/api/notebooklm/bulletins?location_id=305&kind=local`);
const { items } = await res.json();
const latest = items[0];                       // newest
if (latest) return <video src={latest.url} controls />;
```

### Polling
The list updates whenever the streamer builds a new bulletin. Poll
`GET /api/notebooklm/bulletins` periodically (e.g. on page load + every few minutes) and
re-render — no websocket needed.

---

## Dropdown data (for the upload form)
```js
states = ["andhra_pradesh", "telangana"]
districts = {
  andhra_pradesh: ["kurnool","guntur","kakinada","nalore","tirupati"],
  telangana:      ["khammam","karimnagar","warangal","nalgonda"]
}
kinds = ["local","district"]   // district scope only
```

## Location IDs (channel ↔ backend id)
```
Karimnagar 75 · Nalgonda 141 · Warangal 154 · Khammam 161 · Kakinada 209
Nalore 285 · Kurnool 305 · Tirupati 335 · Guntur 344
```

---

## TL;DR for fullstack
- **2 APIs only:** `POST /api/notebooklm/presign` (admin upload) + `GET /api/notebooklm/bulletins` (UI render).
- **Upload** = call presign → PUT file to the returned S3 URL. File goes straight to S3, never through the server.
- **Render** = GET the processed list → play each `item.url` in a `<video>`. **URLs expire in 1h**, re-fetch.
- **Raw video is never shown** — only processed bulletins.
- **Need from Gyana:** app base URL + admin Bearer token (upload only). Put them in frontend env vars, not in code.
