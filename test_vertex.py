"""
Vertex AI smoke test — verifies GeminiHandler works in Vertex mode.

Run AFTER credentials are set up (SA key via GOOGLE_APPLICATION_CREDENTIALS,
or `gcloud auth application-default login`) and GEMINI_USE_VERTEX=true in .env.

    python test_vertex.py

It does three things:
  1. confirms a GCP access token can be minted (auth works),
  2. runs a short Telugu generate_news_script call,
  3. runs generate_headline on the result.
Exit code 0 = all good.
"""
import sys
from config import GEMINI_USE_VERTEX, VERTEX_PROJECT, VERTEX_LOCATION, GEMINI_MODEL


def main() -> int:
    print(f"GEMINI_USE_VERTEX={GEMINI_USE_VERTEX} | project={VERTEX_PROJECT} | "
          f"location={VERTEX_LOCATION} | model={GEMINI_MODEL}")
    if not GEMINI_USE_VERTEX:
        print("❌ GEMINI_USE_VERTEX is not enabled. Set GEMINI_USE_VERTEX=true in .env first.")
        return 1

    # 1) Auth check
    try:
        from openai_handler import _VertexTokenSource
        tok = _VertexTokenSource().token()
        print(f"✅ Got GCP access token (len={len(tok)}).")
    except Exception as e:
        print(f"❌ Could not obtain GCP credentials/token: {e}")
        print("   Fix: set GOOGLE_APPLICATION_CREDENTIALS to the SA key path, OR run")
        print("   `gcloud auth application-default login`.")
        return 1

    # 2) + 3) Real generation calls
    from openai_handler import GeminiHandler
    h = GeminiHandler()

    sample = "Hyderabad city saw heavy rainfall today, causing waterlogging in several low-lying areas."
    print("\n--- generate_news_script ---")
    script = h.generate_news_script(sample, target_words=60)
    if not script:
        print("❌ generate_news_script returned nothing.")
        return 1
    print(script)

    print("\n--- generate_headline ---")
    headline = h.generate_headline(script)
    if not headline:
        print("❌ generate_headline returned nothing.")
        return 1
    print(headline)

    print("\n✅ Vertex AI path works end-to-end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
