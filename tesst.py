
"""
Telugu rendering via Playwright + HTML → screenshot
Requirements: pip install playwright && playwright install chromium
"""

import os

TEST_TEXT = "మార్కెట్లో మూడో పారంభం"
W, H = 900, 300


def test_playwright():
    print("\n── Playwright render ──")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Install: pip install playwright && playwright install chromium")
        return False

    lines = TEST_TEXT.strip().split('\n') if '\n' in TEST_TEXT else [
        "ఖర్గే జెండా ఆవిష్కరణ"
    ]
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
* {{ margin:0; padding:0; }}
body {{
  width:{W}px; height:{H}px;
  background:#780000;
  display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:8px;
}}
.t {{
  font-family:'Noto Sans Telugu','Nirmala UI','Gautami',sans-serif;
  font-size:80px; font-weight:bold; color:white;
  text-shadow:-3px -3px 0 #000,3px -3px 0 #000,
              -3px 3px 0 #000,3px 3px 0 #000;
}}
</style></head><body>
{"".join(f'<div class="t">{l}</div>' for l in lines)}
</body></html>"""

    html_file = os.path.abspath("_test_telugu.html")
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": W, "height": H})
            page.goto(f"file:///{html_file}")
            page.screenshot(path="test_playwright.png", clip={"x": 0, "y": 0, "width": W, "height": H})
            browser.close()
        print("  ✓ Saved: test_playwright.png")
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False
    finally:
        if os.path.exists(html_file):
            os.unlink(html_file)


if __name__ == "__main__":
    print("Testing Telugu rendering with Playwright...\n")
    result = test_playwright()
    print(f"\nResult: {'✓ Success' if result else '✗ Failed'}")