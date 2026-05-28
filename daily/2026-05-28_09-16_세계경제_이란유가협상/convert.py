"""
카드 HTML → MP4 변환 (ffmpeg overlay 방식)

핵심: Playwright video 재생에 의존하지 않음.
- Playwright는 HTML을 정적 PNG로 캡처만 함 (video는 숨겨서 캡처)
- ffmpeg가 hero 영역에 videos/*.mp4를 직접 합성
- 클라우드/로컬 어디서나 hero 영상이 확실히 들어감

처리 방식:
- .card--cover: hero가 전체 카드. video 베이스 + 카드 PNG(hero 부분 chroma key 처리) 오버레이
- 그 외: PNG 베이스 + hero 위치 좌표에 video 오버레이
- .card--cta: video 없음. PNG를 6초 정적 영상으로
"""
import asyncio
import sys
import subprocess
import re
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).parent
CARDS_DIR = ROOT / "cards"
OUT_DIR = ROOT / "png"
WIDTH = 1080
HEIGHT = 1350
VIDEO_SECONDS = 6

# cover variant 캡처 시 hero 영역을 칠할 chroma key 색 (마젠타, 디자인에 안 쓰이는 색)
CHROMA = "#00FF00"


def natural_key(p: Path):
    m = re.search(r"(\d+)", p.stem)
    return int(m.group(1)) if m else 0


async def measure_card(page, html_file: Path):
    """카드 variant + hero 좌표/크기 + video 소스 측정."""
    url = html_file.resolve().as_uri()
    await page.goto(url, wait_until="load", timeout=60000)
    await page.evaluate("() => document.fonts.ready")
    await asyncio.sleep(0.3)
    info = await page.evaluate(
        """() => {
          const card = document.querySelector('.card');
          const variant = card ? Array.from(card.classList).find(c => c.startsWith('card--')) || '' : '';
          const hero = document.querySelector('.hero');
          const v = hero ? hero.querySelector('video') : null;
          const rect = hero ? hero.getBoundingClientRect() : null;
          return {
            variant,
            video_src: v ? v.getAttribute('src') : null,
            hero: rect ? {
              x: Math.round(rect.left),
              y: Math.round(rect.top),
              w: Math.round(rect.width),
              h: Math.round(rect.height),
            } : null,
          };
        }"""
    )
    return info


async def screenshot_normal(page, html_file: Path, out_png: Path):
    """일반 카드(.card--content, --dashboard 등): video 태그 숨기고 캡처."""
    url = html_file.resolve().as_uri()
    await page.goto(url, wait_until="load", timeout=60000)
    await page.evaluate("() => document.fonts.ready")
    await page.evaluate(
        """() => {
          document.querySelectorAll('.hero video').forEach(v => v.style.visibility = 'hidden');
        }"""
    )
    await asyncio.sleep(0.4)
    await page.screenshot(path=str(out_png), omit_background=False, full_page=False)


async def screenshot_cover(page, html_file: Path, out_png: Path):
    """cover variant: cover-stack element만 alpha PNG로 캡처.
    body/card/hero 모두 transparent로 강제 → cover-stack(텍스트)만 alpha PNG.
    ffmpeg에서 video 위에 overlay 시 anti-aliasing 자연스럽게 합성됨."""
    url = html_file.resolve().as_uri()
    await page.goto(url, wait_until="load", timeout=60000)
    await page.evaluate("() => document.fonts.ready")
    await page.evaluate(
        """() => {
          const css = document.createElement('style');
          css.textContent = `
            html, body { background: transparent !important; }
            .card { background: transparent !important; }
            .card--cover .hero { display: none !important; }
          `;
          document.head.appendChild(css);
        }"""
    )
    await asyncio.sleep(0.4)
    # omit_background=True → 투명 영역은 alpha 채널로 처리
    await page.screenshot(path=str(out_png), omit_background=True, full_page=False)


def compose_overlay(card_png: Path, video_path: Path, hero: dict, out_mp4: Path) -> bool:
    """일반 카드: PNG base + hero 위치에 video overlay."""
    hw, hh = hero["w"], hero["h"]
    hx, hy = hero["x"], hero["y"]
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(video_path),
        "-loop", "1", "-i", str(card_png),
        "-filter_complex",
        f"[0:v]scale={hw}:{hh}:force_original_aspect_ratio=increase,crop={hw}:{hh}[fg];"
        f"[1:v]scale={WIDTH}:{HEIGHT}[bg];"
        f"[bg][fg]overlay={hx}:{hy}:eof_action=repeat",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-t", str(VIDEO_SECONDS),
        "-movflags", "+faststart", "-an",
        str(out_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    [!] ffmpeg failed: {result.stderr[:400]}")
        return False
    return True


def compose_cover(card_png: Path, video_path: Path, out_mp4: Path) -> bool:
    """cover variant: video를 base로 + alpha PNG(텍스트만) overlay.
    PNG가 진짜 alpha 채널을 가져서 anti-aliasing이 자연스럽게 합성됨 (색 누락 없음)."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(video_path),
        "-loop", "1", "-i", str(card_png),
        "-filter_complex",
        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},eq=brightness=-0.15:contrast=1.05[bg];"
        f"[1:v]scale={WIDTH}:{HEIGHT}[fg];"
        f"[bg][fg]overlay=0:0:eof_action=repeat",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-t", str(VIDEO_SECONDS),
        "-movflags", "+faststart", "-an",
        str(out_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    [!] ffmpeg failed: {result.stderr[:400]}")
        return False
    return True


def compose_static(card_png: Path, out_mp4: Path) -> bool:
    """video 없는 카드(cta 등): PNG를 6초 정적 영상으로."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-t", str(VIDEO_SECONDS), "-i", str(card_png),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-vf", f"scale={WIDTH}:{HEIGHT}",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    [!] ffmpeg failed: {result.stderr[:400]}")
        return False
    return True


def verify_motion(mp4: Path) -> bool:
    """mp4에서 t=1s와 t=5s 프레임을 추출해 md5 비교 → 다르면 motion 있음."""
    import hashlib
    tmp_dir = OUT_DIR / "_verify"
    tmp_dir.mkdir(exist_ok=True)
    a = tmp_dir / f"{mp4.stem}_a.png"
    b = tmp_dir / f"{mp4.stem}_b.png"
    for t, out in [(1, a), (5, b)]:
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(mp4), "-vframes", "1", "-ss", str(t), str(out)],
            capture_output=True,
        )
    if not (a.exists() and b.exists()):
        return False
    ha = hashlib.md5(a.read_bytes()).hexdigest()
    hb = hashlib.md5(b.read_bytes()).hexdigest()
    a.unlink(missing_ok=True)
    b.unlink(missing_ok=True)
    return ha != hb


async def render_card(page, html_file: Path, max_attempts: int = 2):
    info = await measure_card(page, html_file)
    variant = info.get("variant", "")
    video_src = info.get("video_src")
    hero = info.get("hero")
    is_cover = (variant == "card--cover")

    out_mp4 = OUT_DIR / f"{html_file.stem}.mp4"
    card_png = OUT_DIR / f"_{html_file.stem}_card.png"

    print(f"[*] {html_file.name} ({variant})")

    if is_cover:
        await screenshot_cover(page, html_file, card_png)
    else:
        await screenshot_normal(page, html_file, card_png)

    video_path = None
    if video_src:
        video_path = (html_file.parent / video_src).resolve()
        if not video_path.exists():
            video_path = None

    # video 없는 카드 (cta) → 정적 영상으로
    if not video_path:
        ok = compose_static(card_png, out_mp4)
        card_png.unlink(missing_ok=True)
        if ok:
            print(f"    -> {out_mp4.relative_to(ROOT)} (static, no video)")
        return ok

    # 영상 합성 시도 + 검증 + 재시도
    for attempt in range(1, max_attempts + 1):
        if is_cover:
            ok = compose_cover(card_png, video_path, out_mp4)
            kind = "cover+video"
        else:
            ok = compose_overlay(card_png, video_path, hero, out_mp4)
            kind = f"overlay@{hero['x']},{hero['y']} {hero['w']}x{hero['h']}"

        if not ok:
            print(f"    [!] attempt {attempt} ffmpeg fail")
            continue

        if verify_motion(out_mp4):
            print(f"    -> {out_mp4.relative_to(ROOT)} ({kind}) motion OK")
            card_png.unlink(missing_ok=True)
            return True
        print(f"    [!] attempt {attempt} motion verify FAILED (still frame). retrying...")

    # 모든 시도 실패 → static fallback (영상 없이라도 카드는 나가야 함)
    print(f"    [!] all attempts failed, fallback to static PNG video")
    compose_static(card_png, out_mp4)
    card_png.unlink(missing_ok=True)
    return False


async def main():
    OUT_DIR.mkdir(exist_ok=True)
    cards = sorted(CARDS_DIR.glob("card*.html"), key=natural_key)
    if not cards:
        print(f"[!] No card*.html in {CARDS_DIR}")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
        )
        page = await context.new_page()

        for html_file in cards:
            await render_card(page, html_file)

        # _verify 임시 디렉토리 정리
        verify_dir = OUT_DIR / "_verify"
        if verify_dir.exists():
            for f in verify_dir.iterdir():
                f.unlink()
            verify_dir.rmdir()

        await browser.close()

    print(f"\n[OK] outputs in {OUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
