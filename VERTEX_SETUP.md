# Vertex AI migration — setup & remaining steps

The code is migrated. `GeminiHandler` now has a Vertex AI mode behind the
`GEMINI_USE_VERTEX` env toggle. AI Studio mode still works when the toggle is off.

## What changed in code
- `config.py` — added `GEMINI_USE_VERTEX`, `VERTEX_PROJECT` (default `localaitv`), `VERTEX_LOCATION` (default `us-central1`).
- `openai_handler.py` — added a token-refreshing Vertex client; `GeminiHandler.__init__`
  branches on `GEMINI_USE_VERTEX`; model names auto-prefixed with `google/`;
  `get_llm_handler()` no longer needs `GEMINI_API_KEY` when Vertex is on.
- `requirements.txt` — added `google-auth`.
- `.gitignore` — explicitly ignores `vertex-key.json` / `*-key.json` / ADC file.
- `test_vertex.py` — smoke test (auth + Telugu script + headline).

The token used as the OpenAI `api_key` is refreshed before every call, so the
~1h token expiry is handled automatically.

## .env additions
```dotenv
GEMINI_USE_VERTEX=true
VERTEX_PROJECT=localaitv
VERTEX_LOCATION=us-central1
# Pick ONE auth method below.
# (A) Service-account key file:
GOOGLE_APPLICATION_CREDENTIALS=C:\Users\Gyanaranjan kabi\Desktop\temp_copy\vertex-key.json
# (B) ADC (gcloud auth application-default login) — leave GOOGLE_APPLICATION_CREDENTIALS unset.
```
You can keep `GEMINI_API_KEY` as-is; it's ignored while `GEMINI_USE_VERTEX=true`
and is the instant fallback if you set the toggle back to false.

## Steps that still need YOU (account/permission-gated — I can't do these from here)
These touch the `localaitv` GCP account, which isn't the account my browser is
signed into, and some need org-admin rights.

1. **Enable the API** (once):
   ```
   gcloud config set project localaitv
   gcloud services enable aiplatform.googleapis.com
   ```

2. **Get credentials — pick the simplest that works:**

   - **Option B first (recommended, no org policy fight):** user ADC.
     ```
     gcloud auth application-default login
     ```
     Log in with the account that owns `localaitv`. Leave
     `GOOGLE_APPLICATION_CREDENTIALS` unset. Done — no SA key, the
     `iam.disableServiceAccountKeyCreation` org policy is irrelevant.

   - **Option A (SA key):** needs the org policy disabled first (requires
     `roles/orgpolicy.policyAdmin` — your admin). Then:
     ```
     gcloud iam service-accounts keys create vertex-key.json \
       --iam-account vertex-pipeline@localaitv.iam.gserviceaccount.com
     ```
     Save it as `vertex-key.json` in this folder and point
     `GOOGLE_APPLICATION_CREDENTIALS` at it.

3. **Grant the role** to the service account (Option A) or to your user (Option B
   uses your own permissions, so grant your user `roles/aiplatform.user` if needed):
   ```
   gcloud projects add-iam-policy-binding localaitv \
     --member serviceAccount:vertex-pipeline@localaitv.iam.gserviceaccount.com \
     --role roles/aiplatform.user
   ```

## Test (after credentials are set)
```
python test_vertex.py
```
Expect a Telugu script + headline and "✅ Vertex AI path works end-to-end."

## Deploy
Set the same `.env` values on the Hostinger VPS, place the key file there (Option A)
or run `gcloud auth application-default login` on the VPS (Option B), then push to
main. **Do not push until local test passes — push to main = LIVE.**

## Note (out of scope, flag for later)
Two other spots still call AI Studio directly and will keep 429-ing until migrated:
`openai_handler.py` `transcribe_audio()` (uses google-genai) and
`bulletin_builder.py` `classify_location_to_channel()` (~line 1589). Script and
headline generation — the thing that was blocking bulletins — are fully on Vertex.
