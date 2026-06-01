"""
regen_headlines.py — re-generate stored headlines for OLD items using the
fixed generate_headline (retries + complete-sentence output), so we can verify
the headline fix on existing content without waiting for fresh reports.

USAGE
  Dry-run (DEFAULT — writes NOTHING, just prints old -> new):
      python regen_headlines.py
      python regen_headlines.py --hours 48 --limit 15
      python regen_headlines.py --all          # consider every item, not just broken
      python regen_headlines.py --counters 12104,12103,12095

  Apply (updates DB headline + regenerates the headline TTS audio so the card
  audio matches the new text + resets the used flag so it rebuilds):
      python regen_headlines.py --apply --limit 10

NOTES
  - Detects "incomplete" headlines = empty, or single-line with <=6 words
    (the old script-prefix fallback signature). Good new headlines are 2-line.
  - Script source per item: intro_script, else original_text (DB columns).
  - Requires DB reachability on port 5432. If you get a connection timeout,
    your public IP is not allowlisted for the Postgres firewall.
"""
import argparse
import os

import db
from openai_handler import get_llm_handler


def looks_incomplete(h: str) -> bool:
    """Old broken headlines are single-line fragments of <=6 words.
    Good (fixed) headlines are 2-line (contain a newline) and end on a verb."""
    if not h or not h.strip():
        return True
    h = h.strip()
    if "\n" in h:          # 2-line format = produced by the good path
        return False
    if len(h) <= 4 or len(h.split()) <= 1:
        return True
    return len(h.split()) <= 6


def get_script_text(row: dict) -> str:
    return (row.get("intro_script") or row.get("original_text") or "").strip()


def regen_audio_and_reset(row: dict, new_headline: str) -> None:
    """Regenerate the headline TTS audio from the new text, re-upload to S3, and
    reset the used flag so the item re-enters a bulletin. Best-effort."""
    from config import OUTPUT_HEADLINE_DIR
    from tts_handler import detect_channel, get_tts_for_channel
    import s3_storage as _s3

    counter   = row.get("counter")
    ha_name   = row.get("headline_audio", "")
    loc_name  = row.get("location_name", "") or ""

    if ha_name:
        try:
            idx_row = db.fetchall(
                "SELECT COUNT(*) AS n FROM news_items WHERE counter <= %s", (counter,)
            )
            item_index = max(0, int(idx_row[0]["n"]) - 1) if idx_row else 0
            tts = get_tts_for_channel(detect_channel(loc_name), item_index)
            os.makedirs(OUTPUT_HEADLINE_DIR, exist_ok=True)
            ha_path = os.path.join(OUTPUT_HEADLINE_DIR, ha_name)
            tmp = ha_path + "_tmp.mp3"
            if tts.generate_audio(new_headline, tmp) and os.path.exists(tmp):
                import shutil
                shutil.move(tmp, ha_path)
                _s3.upload_file_async(ha_path, _s3.key_for_audio(ha_name))
                print(f"      ↳ headline audio regenerated + uploaded ({ha_name})")
            else:
                print(f"      ⚠️ headline audio regen failed — card audio may not match")
        except Exception as e:
            print(f"      ⚠️ headline audio regen error: {e}")

    # Reset so the planner picks it into a fresh bulletin
    db.execute(
        "UPDATE news_items SET used_count = 0, bulletined = 0, next_bulletin = 0 "
        "WHERE counter = %s", (counter,)
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually write DB + regenerate audio + reset flags")
    ap.add_argument("--hours", type=int, default=48,
                    help="only consider items from the last N hours (default 48)")
    ap.add_argument("--limit", type=int, default=15,
                    help="max items to process (default 15)")
    ap.add_argument("--all", action="store_true",
                    help="consider every item, not only incomplete-looking ones")
    ap.add_argument("--counters", type=str, default="",
                    help="comma-separated counters to target (overrides filters)")
    args = ap.parse_args()

    if args.counters.strip():
        ctrs = [int(c) for c in args.counters.split(",") if c.strip()]
        rows = db.fetchall(
            "SELECT * FROM news_items WHERE counter = ANY(%s) ORDER BY counter DESC",
            (ctrs,),
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM news_items "
            "WHERE timestamp::timestamptz >= NOW() - INTERVAL '%s hours' "
            "ORDER BY counter DESC" % int(args.hours)
        )

    candidates = rows if args.all else [r for r in rows if looks_incomplete(r.get("headline", ""))]
    candidates = candidates[: args.limit]

    mode = "APPLY" if args.apply else "DRY-RUN (no writes)"
    print(f"=== regen_headlines [{mode}] ===")
    print(f"window={args.hours}h | scanned={len(rows)} | targeting={len(candidates)} "
          f"(limit={args.limit}, all={args.all})\n")

    llm = get_llm_handler()
    changed = skipped = 0
    for r in candidates:
        counter = r.get("counter")
        old_hl  = (r.get("headline") or "").strip()
        script  = get_script_text(r)
        if not script:
            print(f"[{counter}] SKIP — no intro_script/original_text in DB | old={old_hl!r}")
            skipped += 1
            continue

        new_hl = llm.generate_headline(script)
        if not new_hl or not new_hl.strip():
            print(f"[{counter}] SKIP — regeneration returned nothing | old={old_hl!r}")
            skipped += 1
            continue

        new_disp = new_hl.replace("\n", " / ")
        print(f"[{counter}] OLD {old_hl!r}\n           NEW '{new_disp}'  ({len(new_hl.split())} words)")

        if args.apply:
            db.execute("UPDATE news_items SET headline = %s WHERE counter = %s",
                       (new_hl, counter))
            regen_audio_and_reset(r, new_hl)
        changed += 1

    print(f"\nDone. {'updated' if args.apply else 'would update'} {changed}, skipped {skipped}.")
    if not args.apply and changed:
        print("Re-run with --apply to commit these (and regenerate matching audio).")


if __name__ == "__main__":
    main()
