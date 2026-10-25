// Playwright check for /floor: plays a full SIM build at 1440x900 and 390x844, asserts the HUD never overlaps the PiP and the page never scrolls sideways.
// Run: node scripts/floor-check.mjs   (needs `npm start` on :3100; PLAYWRIGHT_DIR points at a folder with playwright installed if it is not a dependency)
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire((process.env.PLAYWRIGHT_DIR ?? process.cwd()) + "/");
const { chromium } = require("playwright");
const BASE = process.env.FLOOR_URL ?? "http://localhost:3100/floor";
const OUT = process.env.FLOOR_SHOTS ?? "../../floor-shots";
mkdirSync(OUT, { recursive: true });

const overlap = (a, b) => !(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y);
let failed = 0;
const check = (ok, msg) => { console.log(`${ok ? "PASS" : "FAIL"} ${msg}`); if (!ok) failed++; };

const browser = await chromium.launch();
for (const [name, w, h] of [["desktop", 1440, 900], ["phone", 390, 844]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="floor-hud"]');
  const seen = new Set();
  const shots = new Set(["Round 1 of", "revealed", "is out at", "WINNER"]);
  let overlaps = 0, samples = 0, sealedPrice = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 60_000) {
    const hud = await page.locator('[data-testid="floor-hud"]').boundingBox();
    const pip = await page.locator('[data-testid="floor-pip"]').boundingBox();
    const text = await page.evaluate(() => document.body.innerText);
    const hudText = await page.locator('[data-testid="floor-round"]').innerText();
    samples++;
    if (hud && pip && overlap(hud, pip)) overlaps++;
    if (/sealed/.test(hudText) && !/revealed/.test(hudText)) {
      const ledger = await page.locator('[data-testid="floor-ledger"]').innerText();
      if (/\$\d/.test(ledger)) sealedPrice = true;
    }
    for (const k of shots) if (!seen.has(k) && text.toLowerCase().includes(k.toLowerCase())) { seen.add(k); if (k === "is out at") { await page.waitForTimeout(600); await page.screenshot({ path: `${OUT}/direction-${w}.png` }); } await page.screenshot({ path: `${OUT}/${name}-${k.replace(/\W+/g, "-")}.png` }); }
    if (await page.locator('[data-testid="floor-deal"]').count()) {
      seen.add("DEAL"); await page.waitForTimeout(600);
      await page.screenshot({ path: `${OUT}/${name}-DEAL.png` });
      break;
    }
    await page.waitForTimeout(250);
  }
  const noScroll = await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth);
  check(seen.has("DEAL"), `${name}: full build played to the end card (${[...seen].join(", ")})`);
  check(seen.has("is out at"), `${name}: referee call and the eaten reason shown`);
  check(overlaps === 0, `${name}: HUD never overlapped the PiP over ${samples} samples`);
  check(!sealedPrice, `${name}: no price in the ledger while sealed`);
  check(noScroll, `${name}: no horizontal scroll`);
  check(await page.locator("text=SIM").first().isVisible(), `${name}: SIM label visible`);
  await page.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
