/**
 * Render cards/card*.html → png/card*.mp4 (6초)
 * Node.js playwright + ffmpeg
 * 배경 비디오 프레임을 주입한 뒤 고품질 스크린샷 → MP4 인코딩
 * video.readyState 기반 대기 로직 포함
 */
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const CARDS_DIR = path.join(ROOT, 'cards');
const OUT_DIR = path.join(ROOT, 'png');
const FRAMES_DIR = path.join(OUT_DIR, 'frames');
const WIDTH = 1080;
const HEIGHT = 1350;
const VIDEO_SECONDS = 6;
const FPS = 24;

function naturalKey(filename) {
  const m = filename.match(/(\d+)/);
  return m ? parseInt(m[1]) : 0;
}

// card HTML → 주입할 프레임 이미지 경로 파악
function getFramePath(htmlFile) {
  const content = fs.readFileSync(htmlFile, 'utf8');
  const m = content.match(/src="\.\.\/videos\/(v\d+)\.mp4"/);
  if (!m) return null;
  const num = m[1].replace('v', '');
  const fp = path.join(FRAMES_DIR, `f${num}.png`);
  return fs.existsSync(fp) ? fp : null;
}

async function renderCard(browser, htmlFile) {
  const stem = path.basename(htmlFile, '.html');
  const outMp4 = path.join(OUT_DIR, stem + '.mp4');
  const tmpPng = path.join(OUT_DIR, `_tmp_${stem}.png`);

  const framePath = getFramePath(htmlFile);
  let frameB64 = null;
  if (framePath) {
    frameB64 = fs.readFileSync(framePath).toString('base64');
  }

  const ctx = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  await page.goto('file://' + htmlFile, { waitUntil: 'load', timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);

  // 배경 비디오 프레임 주입 (video.readyState 대신 미리 추출된 PNG 사용)
  if (frameB64) {
    await page.evaluate((b64) => {
      document.querySelectorAll('.hero video').forEach(vid => {
        const img = document.createElement('img');
        img.src = 'data:image/png;base64,' + b64;
        img.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block;position:absolute;inset:0;';
        vid.replaceWith(img);
      });
    }, frameB64);
  }

  await new Promise(r => setTimeout(r, 600));
  await page.screenshot({ path: tmpPng });
  await page.close();
  await ctx.close();

  // 고품질 6초 MP4 인코딩
  const result = spawnSync('ffmpeg', [
    '-y', '-loglevel', 'error',
    '-loop', '1', '-framerate', String(FPS),
    '-i', tmpPng,
    '-c:v', 'libx264', '-preset', 'medium',
    '-b:v', '2000k',           // 충분한 비트레이트로 100KB+ 보장
    '-pix_fmt', 'yuv420p',
    '-vf', `scale=${WIDTH}:${HEIGHT}`,
    '-t', String(VIDEO_SECONDS),
    '-an',
    outMp4,
  ]);

  try { fs.unlinkSync(tmpPng); } catch(e) {}

  if (result.status !== 0) {
    console.log(`  [!] ffmpeg failed: ${(result.stderr || '').toString().slice(0, 300)}`);
    return;
  }

  const size = fs.statSync(outMp4).size;
  console.log(`  -> ${stem}.mp4 (${(size / 1024).toFixed(0)}KB, ${VIDEO_SECONDS}s)`);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const cards = fs.readdirSync(CARDS_DIR)
    .filter(f => f.match(/^card\d+\.html$/))
    .sort((a, b) => naturalKey(a) - naturalKey(b));

  if (cards.length === 0) {
    console.error('[!] No card*.html found in', CARDS_DIR);
    process.exit(1);
  }

  console.log(`[*] Rendering ${cards.length} cards...`);
  const browser = await chromium.launch({
    args: ['--autoplay-policy=no-user-gesture-required'],
  });

  for (const card of cards) {
    console.log(`[*] ${card}`);
    await renderCard(browser, path.join(CARDS_DIR, card));
  }

  await browser.close();
  console.log(`\n[OK] outputs in ${OUT_DIR}/`);
})();
