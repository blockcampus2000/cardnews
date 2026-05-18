const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const ROOT = __dirname;
const CARDS_DIR = path.join(ROOT, 'cards');
const OUT_DIR = path.join(ROOT, 'png');
const WIDTH = 1080;
const HEIGHT = 1350;
const SCALE = 2;
const CHROMIUM_PATH = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

(async () => {
  if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR);

  const cards = fs.readdirSync(CARDS_DIR)
    .filter(f => f.match(/^card\d+\.html$/))
    .sort()
    .map(f => path.join(CARDS_DIR, f));

  if (!cards.length) { console.error('No card*.html found'); process.exit(1); }

  const browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: SCALE,
  });
  const page = await context.newPage();

  for (const htmlFile of cards) {
    const url = 'file://' + htmlFile;
    const name = path.basename(htmlFile, '.html');
    console.log(`[*] ${path.basename(htmlFile)}`);
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    const outPath = path.join(OUT_DIR, name + '.png');
    await page.screenshot({ path: outPath, omitBackground: false });
    console.log(`    -> png/${name}.png`);
  }

  await browser.close();
  console.log(`\n[OK] ${cards.length} PNG(s) written to png/`);
})().catch(e => { console.error(e); process.exit(1); });
