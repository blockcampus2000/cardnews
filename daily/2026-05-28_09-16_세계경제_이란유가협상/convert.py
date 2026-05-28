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
    # 모든 video가 readyState>=3 될 때까지 대기 (5초 타임아웃) — video.readyState 기반 대기
    # 클라우드 라우틴 환경에서 영상이 hero에 안 들어가던 문제 해결.
    try:
        await page.wait_for_function(
            "() => { const vs = document.querySelectorAll('video'); return vs.length === 0 || Array.from(vs).every(v => v.readyState >= 3); }",
            timeout=5000,
        )
    except Exception:
        pass  # 타임아웃이어도 일단 진행
    await page.evaluate(
        "() => document.querySelectorAll('video').forEach(v => { v.muted = true; v.playsInline = true; v.play().catch(()=>{}); })"
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


def natural_key(p: Path):
    """card1.html, card2.html, ..., card10.html 자연 정렬용 키"""
    import re
    m = re.search(r"(\d+)", p.stem)
    return int(m.group(1)) if m else 0


async def main():
    OUT_DIR.mkdir(exist_ok=True)
    # 자연 정렬: card1 → card2 → ... → card10 (알파벳 정렬은 card10이 card2 앞으로 옴)
    cards = sorted(CARDS_DIR.glob("card*.html"), key=natural_key)
    if not cards:
        print(f"[!] No card*.html in {CARDS_DIR}")
        sys.exit(1)

    async with async_playwright() as p:
        import os as _os
        _chrome = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        _launch_kwargs = {"args": ["--autoplay-policy=no-user-gesture-required"]}
        if _os.path.exists(_chrome):
            _launch_kwargs["executable_path"] = _chrome
        browser = await p.chromium.launch(**_launch_kwargs)

        # 모든 카드를 MP4로 출력 — 텔레그램 album type 통일 + 순서 보장
        # video 태그 없는 카드도 6초 정적 영상으로
        for html_file in cards:
            print(f"[*] {html_file.name}")
            await render_mp4(browser, html_file)

        tmp_dir = OUT_DIR / "_tmp_video"
        if tmp_dir.exists():
            for f in tmp_dir.iterdir():
                f.unlink()
            tmp_dir.rmdir()

        await browser.close()

    print(f"\n[OK] outputs in {OUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
