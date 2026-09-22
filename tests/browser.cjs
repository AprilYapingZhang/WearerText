// npm install --no-save playwright (or set PLAYWRIGHT_MODULE); then node tests/browser.cjs
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {pathToFileURL} = require('node:url');
const path = require('node:path');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({viewport:{width,height:1000}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      if (process.env.HF_PREVIEW_ROOT) {
        await page.route('https://huggingface.co/datasets/**/resolve/**/preview/*.mp4', async route => {
          const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop());
          const body = fs.readFileSync(path.join(process.env.HF_PREVIEW_ROOT, name));
          await route.fulfill({status:200, contentType:'video/mp4', body, headers:{'access-control-allow-origin':'*'}});
        });
      }
      await page.goto(pathToFileURL(path.resolve(__dirname, '../index.html')).href);
      await page.waitForSelector('#results-body tr');
      assert.equal(await page.locator('.author').count(), 14);
      assert.equal(await page.locator('#results-body tr').count(), 20);
      assert.equal(await page.locator('#task-grid details').count(), 13);
      assert.match(await page.locator('#results-body tr').first().innerText(), /GPT-5.2[\s\S]*73.1/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Page overflows viewport');
      if (process.env.HF_PREVIEW_ROOT) {
        await page.locator('#example-video').evaluate(v => v.play());
        await page.waitForFunction(() => document.querySelector('#example-video').currentTime > 0);
        await page.locator('#example-video').evaluate(v => v.pause());
      }
      await page.selectOption('#task-filter', 'L3.3');
      assert.match(await page.locator('#qa-count').innerText(), /107/);
      assert.match(await page.locator('#example-name').innerText(), /Structured Text Synthesis/);
      const before = await page.locator('#example-id').innerText();
      await page.click('#next-example');
      assert.notEqual(await page.locator('#example-id').innerText(), before);
      await page.fill('#qa-search', 'zzzz-no-match');
      assert.equal(await page.locator('#next-example').isDisabled(), true);
      await page.fill('#qa-search', '');
      await page.selectOption('#task-filter', 'all');
      await page.selectOption('#model-family', 'Open-source Video Models');
      assert.equal(await page.locator('#results-body tr').count(), 4);
      await page.selectOption('#model-family', 'all');
      await page.locator('.figure-details summary').first().click();
      // Local assets must decode; no external model/dataset call is made by this test.
      for (const img of await page.locator('img').all()) {
        await img.scrollIntoViewIfNeeded().catch(() => {});
        if (await img.isVisible()) await img.evaluate(el => el.decode());
      }
      await page.locator('.figure-details summary').first().click();
      await page.evaluate(() => window.scrollTo({top:0,behavior:'instant'}));
      await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR || '/tmp', `wearertext-${width}-top.png`)});
      await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR || '/tmp', `wearertext-${width}.png`), fullPage:true});
      assert.deepEqual(errors, []);
      console.log(`PASS ${width}px: authors, all results, tasks, filtering, pagination, images, no overflow/JS errors`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
