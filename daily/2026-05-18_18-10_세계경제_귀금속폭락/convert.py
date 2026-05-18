"""
Render cards/card*.html to png/card*.png at 1080x1350 (Instagram portrait).

Setup (one-time):
    pip install playwright
    playwright install chromium

Run:
    python convert.py
"""
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).parent
CARDS_DIR = ROOT / "cards"
OUT_DIR = ROOT / "png"
WIDTH = 1080
HEIGHT = 1350
SCALE = 2  # 2x render for crisp output


async def main():
    OUT_DIR.mkdir(exist_ok=True)
    cards = sorted(CARDS_DIR.glob("card*.html"))
    if not cards:
        print(f"[!] No card*.html files found in {CARDS_DIR}")
        sys.exit(1)

    CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROMIUM)
        context = await browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=SCALE,
        )
        page = await context.new_page()

        for html_file in cards:
            url = html_file.resolve().as_uri()
            print(f"[*] {html_file.name}")
            await page.goto(url, wait_until="networkidle")
            await page.evaluate("() => document.fonts.ready")
            await asyncio.sleep(0.4)  # small settle
            out_path = OUT_DIR / (html_file.stem + ".png")
            await page.screenshot(path=str(out_path), omit_background=False)
            print(f"    -> {out_path.relative_to(ROOT)}")

        await browser.close()

    print(f"\n[OK] {len(cards)} PNG(s) written to {OUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
