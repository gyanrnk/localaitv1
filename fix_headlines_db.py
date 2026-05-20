"""
fix_headlines_db.py
Run on VPS inside container:
    docker exec localaitv_app python fix_headlines_db.py

Finds news_items where headline is short/bad (<= 4 chars or <= 1 word),
regenerates from intro_script column in DB, updates headline.
"""
import db
from openai_handler import get_llm_handler

def is_bad_headline(h):
    if not h:
        return True
    h = h.strip()
    if len(h) <= 4:
        return True
    if len(h.split()) <= 1:
        return True
    return False

rows = db.fetchall("""
    SELECT counter, headline, intro_script, original_text
    FROM news_items
    WHERE timestamp::timestamptz >= NOW() - INTERVAL '48 hours'
    ORDER BY counter DESC
""")

bad = [r for r in rows if is_bad_headline(r.get('headline', ''))]
print(f"Total items (48h): {len(rows)} | Bad headlines: {len(bad)}")

fixed = 0
llm = get_llm_handler()
for r in bad:
    counter = r['counter']
    old_hl  = r.get('headline', '')

    script_text = (r.get('intro_script') or r.get('original_text') or '').strip()

    if not script_text:
        print(f"  [{counter}] No script in DB — skipping (headline='{old_hl}')")
        continue

    new_hl = llm.generate_headline(script_text)
    if not new_hl or is_bad_headline(new_hl):
        print(f"  [{counter}] Regeneration failed — skipping")
        continue

    db.execute(
        "UPDATE news_items SET headline = %s WHERE counter = %s",
        (new_hl, counter)
    )
    print(f"  [{counter}] '{old_hl}' → '{new_hl}'")
    fixed += 1

print(f"\nDone. Fixed {fixed}/{len(bad)} bad headlines.")