"""
Render cards/card*.html → png/card*.png (또는 .mp4 if video card)

- 비디오 태그(<video src=...>)가 포함된 카드는 MP4로 출력 (6초 녹화)
- 그 외는 기존대로 1080×1350 @2x PNG
"""
import asyncio
import sys
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).parent
CARDS_DIR = ROOT / "cards"
OUT_DIR = ROOT / "png"
WIDTH = 1080
HEIGHT = 1350
SCALE = 2
VIDEO_SECONDS = 6
# Playwright 녹화 시작 시점엔 페이지/비디오가 아직 안 그려진 빈 프레임이 잡힘 (~0.1초).
# 살짝 더 녹화한 뒤 ffmpeg로 앞부분만 trim해서 깨끗한 6초 출력.
SKIP_HEAD_SECONDS = 0.3


def has_video_tag(html_file: Path) -> bool:
    return "<video" in html_file.read_text(encoding="utf-8")


async def render_png(page, html_file: Path):
    url = html_file.resolve().as_uri()
    await page.goto(url, wait_until="load", timeout=60000)
    await page.evaluate("() => document.fonts.ready")
    await asyncio.sleep(0.6)
    out_path = OUT_DIR / (html_file.stem + ".png")
    await page.screenshot(path=str(out_path), omit_background=False)
    print(f"    -> {out_path.relative_to(ROOT)}")


async def render_mp4(browser, html_file: Path):
    """비디오 카드: Playwright로 녹화 후 ffmpeg로 MP4 변환."""
    out_mp4 = OUT_DIR / (html_file.stem + ".mp4")
    tmp_dir = OUT_DIR / "_tmp_video"
    tmp_dir.mkdir(exist_ok=True)
    for old in tmp_dir.glob("*.webm"):
        old.unlink()

    context = await browser.new_context(
        viewport={"width": WIDTH, "height": HEIGHT},
        device_scale_factor=1,
        record_video_dir=str(tmp_dir),
        record_video_size={"width": WIDTH, "height": HEIGHT},
    )
    page = await context.new_page()
    url = html_file.resolve().as_uri()
    await page.goto(url, wait_until="load", timeout=60000)
    await page.evaluate("() => document.fonts.ready")
    await page.evaluate(
        "() => document.querySelectorAll('video').forEach(v => { v.muted = true; v.play(); })"
    )
    # SKIP_HEAD_SECONDS만큼 추가로 녹화해 두면 ffmpeg가 앞부분 trim 가능
    await asyncio.sleep(VIDEO_SECONDS + SKIP_HEAD_SECONDS)
    await page.close()
    await context.close()

    webms = list(tmp_dir.glob("*.webm"))
    if not webms:
        print(f"    [!] No webm produced for {html_file.name}")
        return
    webm = max(webms, key=lambda p: p.stat().st_mtime)

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(SKIP_HEAD_SECONDS),  # 빈 프레임 구간 trim
        "-i", str(webm),
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={WIDTH}:{HEIGHT}",
        "-t", str(VIDEO_SECONDS),
        "-an",
        str(out_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    [!] ffmpeg failed: {result.stderr}")
        return
    webm.unlink()
    print(f"    -> {out_mp4.relative_to(ROOT)} (video, {VIDEO_SECONDS}s)")


async def main():
    OUT_DIR.mkdir(exist_ok=True)
    cards = sorted(CARDS_DIR.glob("card*.html"))
    if not cards:
        print(f"[!] No card*.html in {CARDS_DIR}")
        sys.exit(1)

    CHROMIUM_EXEC = (
        "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"
    )
    import os
    launch_kwargs = {"args": ["--autoplay-policy=no-user-gesture-required"]}
    if os.path.exists(CHROMIUM_EXEC):
        launch_kwargs["executable_path"] = CHROMIUM_EXEC

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        png_context = await browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=SCALE,
        )
        png_page = await png_context.new_page()

        for html_file in cards:
            print(f"[*] {html_file.name}")
            if has_video_tag(html_file):
                await render_mp4(browser, html_file)
            else:
                await render_png(png_page, html_file)

        await png_context.close()
        tmp_dir = OUT_DIR / "_tmp_video"
        if tmp_dir.exists():
            for f in tmp_dir.iterdir():
                f.unlink()
            tmp_dir.rmdir()

        await browser.close()

    print(f"\n[OK] outputs in {OUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
