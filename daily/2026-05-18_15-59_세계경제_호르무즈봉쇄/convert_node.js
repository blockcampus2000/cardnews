const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const ROOT = __dirname;
const CARDS_DIR = path.join(ROOT, 'cards');
const OUT_DIR = path.join(ROOT, 'png');
const WIDTH = 1080;
const HEIGHT = 1350;
const SCALE = 2;

async function main() {
  if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

  const cards = fs.readdirSync(CARDS_DIR)
    .filter(f => f.match(/^card\d+\.html$/))
    .sort()
    .map(f => path.join(CARDS_DIR, f));

  if (!cards.length) { console.error('No card*.html found'); process.exit(1); }

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: SCALE,
  });
  const page = await context.newPage();

  for (const html of cards) {
    const url = 'file://' + html;
    const name = path.basename(html, '.html');
    console.log('[*]', path.basename(html));
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await new Promise(r => setTimeout(r, 400));
    const out = path.join(OUT_DIR, name + '.png');
    await page.screenshot({ path: out, omitBackground: false });
    console.log('    ->', path.relative(ROOT, out));
  }

  await browser.close();
  console.log(`\n[OK] ${cards.length} PNG(s) written to png/`);
}

main().catch(e => { console.error(e); process.exit(1); });
