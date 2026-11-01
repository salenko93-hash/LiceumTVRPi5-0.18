/* Local Chromium QA. Read-only HTTP host and controlled API responses only. */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const ROOT = path.resolve(__dirname, '..');
const reportDir = path.join(ROOT, 'reports/tv-display-preview');
fs.mkdirSync(reportDir, {recursive: true});
const fixture = name => JSON.parse(fs.readFileSync(path.join(ROOT, 'public/preview-data', name + '.json'), 'utf8'));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function main() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const server = spawn(process.env.PYTHON || 'python', ['-B', 'tools/serve_tv_preview.py', '--port', String(port)], {cwd: ROOT, stdio: 'ignore'});
  let browser;
  const checks = [];
  const pass = value => { checks.push(value); console.log('PASS:', value); };
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let n = 0; ; n++) {
      try { if ((await fetch(base)).ok) break; } catch {}
      if (n > 50) throw Error('Local preview server did not start');
      await delay(100);
    }
    browser = await chromium.launch({channel: 'chrome', headless: true, chromiumSandbox: true});
    const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const open = async sample => {
      await page.goto(`${base}/tv-display-preview.html?sample=${sample}`);
      await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('2026'));
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    };
    const overflow = () => page.evaluate(() => [...document.querySelectorAll('.fit-text')].flatMap(node => {
      if (!node.getClientRects().length) return [];
      const cell = node.parentElement, css = getComputedStyle(cell), label = cell.querySelector('.group-label');
      const height = cell.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom) - (label ? label.offsetHeight + 2 : 0);
      return node.scrollHeight > height + 1 || node.scrollWidth > node.clientWidth + 1
        ? [{text: node.textContent, font: getComputedStyle(node).fontSize, height, scroll: node.scrollHeight}] : [];
    }));
    await open('groups');
    assert.equal(await page.locator('.class-row').count(), 8);
    const bounds = await page.evaluate(() => ['.header', '#table-left', '#table-right', '.footer'].map(selector => {
      const r = document.querySelector(selector).getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
    }));
    assert.deepEqual(bounds, [[40, 40, 1840, 120], [40, 184, 904, 780], [976, 184, 904, 780], [40, 980, 1840, 60]]);
    assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('.class-row')].map(n => n.offsetHeight)), Array(8).fill(160));
    assert.deepEqual(await overflow(), []);
    assert.ok(await page.locator('.group-label').count() >= 2);
    await page.screenshot({path: path.join(reportDir, 'groups-1920x1080.png')});
    pass('Exact Full HD geometry, 8 simultaneous classes, 160px rows, aligned subgroup cells');

    await open('break');
    assert.match(await page.locator('#phase').textContent(), /Наступний урок/);
    assert.equal((await page.locator('.class-row').allTextContents()).length, 8);
    await page.screenshot({path: path.join(reportDir, 'break-1920x1080.png')});
    pass('Break explicitly shows next lesson from engine rows, with all 8 classes');
    await open('substitution');
    assert.equal(await page.locator('[data-class="10-А"] .badge').textContent(), 'ЗАМІНА');
    assert.equal(await page.locator('[data-class="10-А"] .room').textContent(), 'К2');
    pass('Synthetic substitution result and changed room displayed inside row');
    await open('long');
    assert.deepEqual(await overflow(), []);
    assert.match(await page.locator('[data-class="10-А"]').textContent(), /Демонстраційний викладач довгого тестового предмета/);
    await page.screenshot({path: path.join(reportDir, 'long-1920x1080.png')});
    pass('Long subject/full teacher names and 2 groups fit without truncation');

    for (const [sample, title] of [['holiday', 'КАНІКУЛИ'], ['weekend', 'НЕМАЄ ЗАНЯТЬ'], ['after-school', 'УРОКИ ЗАВЕРШЕНО']]) {
      await open(sample);
      assert.equal(await page.locator('#special-title').textContent(), title);
      assert.equal(await page.locator('#tables').isVisible(), false);
      if (sample === 'holiday') await page.screenshot({path: path.join(reportDir, 'holiday-1920x1080.png')});
    }
    pass('Holiday/weekend/end-of-day retain calendar state; no fabricated live lessons');
    await open('shelter');
    assert.match(await page.locator('#phase').textContent(), /УКРИТТІ/);
    assert.equal(await page.locator('#air-raid-display').isVisible(), true);
    assert.equal(await page.locator('#raid-schedule').isVisible(), true);
    await open('denominator');
    assert.match(await page.locator('#week').textContent(), /ЗНАМЕННИК/);
    await open('lesson');
    assert.match(await page.locator('#week').textContent(), /ЧИСЕЛЬНИК/);
    pass('Shelter timetable and denominator supported');

    let priority = fixture('holiday');
    await page.route('**/preview-data/holiday.json', route => route.fulfill({json: priority}));
    for (const [mode, title] of [['AIR_RAID', 'ПОВІТРЯНА ТРИВОГА'], ['SILENCE', 'ХВИЛИНА МОВЧАННЯ'], ['ALL_CLEAR', 'ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ']]) {
      priority.mode = mode;
      priority.alarm = {active: false, status: {http: 200, at: priority.now}};
      await open('holiday');
      assert.equal(await page.locator('#special-title').textContent(), title);
    }
    await page.unroute('**/preview-data/holiday.json');
    assert.equal(await page.locator('audio').count(), 0);
    assert.equal(await page.locator('html').getAttribute('translate'), 'no');
    pass('Priority modes override holidays; isolated preview stays silent and marks page notranslate');

    let current;
    await page.route('**/preview-data/long.json', route => route.fulfill({json: current}));
    const corpus = fixture('corpus');
    let smallest = 100;
    for (const item of corpus) {
      current = item;
      await open('long');
      assert.deepEqual(await overflow(), [], `${item.now} shelter=${item.schedule.shelter}`);
      const sizes = await page.locator('.fit-text').evaluateAll(nodes => nodes.map(n => parseFloat(getComputedStyle(n).fontSize)));
      smallest = Math.min(smallest, ...sizes);
    }
    pass(`All ${corpus.length} synthetic schema states: no cell overflow; smallest font ${smallest}px`);
    await page.unroute('**/preview-data/long.json');
    await page.setViewportSize({width: 3840, height: 2160});
    await open('groups');
    assert.deepEqual(await page.locator('#table-right').boundingBox(), {x: 1952, y: 368, width: 1808, height: 1560});
    assert.deepEqual(await overflow(), []);
    await page.screenshot({path: path.join(reportDir, 'groups-3840x2160.png')});
    await page.setViewportSize({width: 1280, height: 720});
    await open('groups');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight), true);
    pass('4K exact 2x scaling and 720p fit; no document scrolling');

    const live = await browser.newPage({viewport: {width: 1920, height: 1080}});
    await live.addInitScript(() => {
      const timeouts = new Set(), intervals = new Set();
      const later = window.setTimeout.bind(window), cancel = window.clearTimeout.bind(window);
      const every = window.setInterval.bind(window), end = window.clearInterval.bind(window);
      window.setTimeout = (fn, ms, ...args) => { const id = later(() => { timeouts.delete(id); fn(...args); }, ms); timeouts.add(id); return id; };
      window.clearTimeout = id => { timeouts.delete(id); cancel(id); };
      window.setInterval = (fn, ms, ...args) => { const id = every(fn, ms, ...args); intervals.add(id); return id; };
      window.clearInterval = id => { intervals.delete(id); end(id); };
      window.previewTimers = () => ({timeouts: timeouts.size, intervals: intervals.size});
    });
    let apiCalls = 0, unavailable = false, pending = 0, maximum = 0;
    await live.route('**/api/state', async route => {
      apiCalls++; pending++; maximum = Math.max(maximum, pending);
      await delay(20); pending--;
      if (unavailable) return route.fulfill({status: 503, body: 'offline'});
      await route.fulfill({json: fixture('groups')});
    });
    await live.goto(`${base}/tv-display-preview.html`);
    await live.waitForFunction(() => document.querySelector('#connection').textContent.includes('АКТУАЛЬНІ'));
    const oldClock = await live.locator('#clock').textContent();
    await live.waitForFunction(previous => document.querySelector('#clock').textContent !== previous, oldClock, {timeout: 3000});
    assert.notEqual(await live.locator('#clock').textContent(), oldClock);
    unavailable = true;
    await live.waitForFunction(() => document.querySelector('#connection').textContent.includes('КЕШ'), {timeout: 9000});
    assert.equal(await live.locator('.class-row').count(), 8);
    await live.reload();
    await live.waitForFunction(() => document.querySelector('#connection').textContent.includes('КЕШ'));
    unavailable = false;
    await live.waitForFunction(() => document.querySelector('#connection').textContent.includes('АКТУАЛЬНІ'), {timeout: 9000});
    assert.equal(maximum, 1);
    pass(`Real /api/state adapter: ticking clock, offline cache across reload, recovery, no concurrent polling (${apiCalls} requests)`);
    assert.deepEqual(await live.evaluate(() => window.previewTimers()), {timeouts: 1, intervals: 1});
    await live.evaluate(() => window.dispatchEvent(new Event('pagehide')));
    assert.deepEqual(await live.evaluate(() => window.previewTimers()), {timeouts: 0, intervals: 0});
    pass('Only one clock interval and one scheduled poll; pagehide clears both');
    await live.close();

    const fresh = await browser.newPage();
    await fresh.route('**/api/state', route => route.fulfill({status: 503, body: 'offline'}));
    await fresh.goto(`${base}/tv-display-preview.html`);
    await fresh.waitForFunction(() => document.querySelector('#connection').textContent.includes('ДАНІ НЕДОСТУПНІ'));
    assert.equal(await fresh.locator('.class-row').count(), 8);
    assert.match(await fresh.locator('#left-rows').textContent(), /Очікування даних/);
    await fresh.close();
    pass('Cold offline start displays unavailable placeholders, never fixtures');
    const malicious = fixture('lesson');
    malicious.schedule.rows[0].entries[0].subject = '<img src=x onerror=alert(1)>';
    await page.route('**/preview-data/lesson.json', route => route.fulfill({json: malicious}));
    await open('lesson');
    assert.equal(await page.locator('.class-row img').count(), 0);
    assert.match(await page.locator('[data-class="10-А"]').textContent(), /<img/);
    assert.deepEqual(errors, []);
    pass('API text escaped; no script injection or page errors');
    fs.writeFileSync(path.join(reportDir, 'browser-results.json'), JSON.stringify({checks, corpusStates: corpus.length, minimumRealDataFontPx: smallest, errors}, null, 2));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
