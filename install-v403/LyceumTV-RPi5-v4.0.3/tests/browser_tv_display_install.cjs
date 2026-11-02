const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ROOT = path.resolve(__dirname, '..');
const report = path.join(ROOT, 'reports/tv-display-install');
fs.mkdirSync(report, {recursive: true});
const fixture = name => JSON.parse(fs.readFileSync(path.join(ROOT, 'public/preview-data', name + '.json'), 'utf8'));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function main() {
  let state = fixture('groups'), event = null, delayedAudio = false;
  const requests = [];
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    requests.push({path: url.pathname, method: req.method, token: req.headers['x-device-token']});
    const json = data => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); };
    if (url.pathname === '/api/state') return json(state);
    if (url.pathname === '/api/audio/current') { if (delayedAudio) await pause(500); return json(event || {}); }
    if (url.pathname === '/api/screen/local-token') return json({token: 'controlled-test-device-token'});
    if (url.pathname === '/api/screen/heartbeat') return json({screen: {}});
    let name = url.pathname === '/' ? '/tv4.html' : url.pathname === '/legacy-tv' ? '/index.html' : url.pathname;
    const file = path.resolve(ROOT, 'public', '.' + name);
    if (!file.startsWith(path.join(ROOT, 'public') + path.sep)) { res.writeHead(403); return res.end(); }
    try {
      const content = fs.readFileSync(file);
      res.setHeader('Content-Type', ({'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json'})[path.extname(file)] || 'application/octet-stream');
      res.end(content);
    } catch { res.writeHead(404); res.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  const checks = [];
  const pass = text => { checks.push(text); console.log('PASS:', text); };
  try {
    browser = await chromium.launch({channel: 'chrome', headless: true, chromiumSandbox: true});
    const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.mediaEvents = [];
      HTMLMediaElement.prototype.play = function() { window.mediaEvents.push({action: 'play', id: this.id || 'scheduled', url: this.src, volume: this.volume}); return Promise.resolve(); };
      HTMLMediaElement.prototype.pause = function() { window.mediaEvents.push({action: 'pause', id: this.id || 'scheduled'}); };
    });
    const base = `http://127.0.0.1:${server.address().port}`;
    await page.goto(base + '/?sample=holiday');
    await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('АКТУАЛЬНІ'));
    assert.equal(await page.locator('.class-row').count(), 8);
    assert.equal(await page.locator('#tables').isVisible(), true);
    assert.equal(await page.locator('html').getAttribute('data-tv-production'), 'true');
    assert.equal(requests.some(r => r.path.startsWith('/preview-data/')), false);
    assert.equal(await page.locator('#source').textContent(), 'LYCEUMTV 4.0 · TV DISPLAY');
    await page.screenshot({path: path.join(report, 'production-full-hd.png')});
    pass('Main route uses new design, all 8 classes; sample query cannot replace production API data');
    const deliver = async (value, online = true) => {
      state = value;
      await page.evaluate(detail => dispatchEvent(new CustomEvent('lyceumtv:state', {detail})), {state: value, online});
      await pause(100);
    };
    const plays = id => page.evaluate(key => window.mediaEvents.filter(e => e.action === 'play' && e.id === key), id);
    const alarmState = fixture('groups');
    alarmState.mode = 'AIR_RAID'; alarmState.alarm = {sound_enabled: true, event_id: 'alarm-one', volume: 0.65};
    await deliver(alarmState); await deliver(alarmState);
    assert.equal((await plays('tv4-alarm-audio')).length, 1);
    assert.equal((await plays('tv4-alarm-audio'))[0].volume, 0.65);
    pass('Alarm plays once per event ID, preserving configured volume');
    const silentState = fixture('groups');
    silentState.mode = 'SILENCE'; silentState.silence = {event_id: 'silence-one', volume: 0.25};
    await deliver(silentState); await deliver(silentState);
    assert.equal((await plays('tv4-silence-audio')).length, 1);
    await deliver({...silentState, silence: {event_id: 'cached-must-not-play', volume: 1}}, false);
    assert.equal((await plays('tv4-silence-audio')).length, 1);
    pass('Minute-of-silence audio deduplicated; cached/offline state never triggers sound');
    event = {event_key: 'scheduled-one', event: {url: '/audio/test-bell.mp3', volume: 0.4}};
    await deliver(fixture('groups')); await deliver(fixture('groups'));
    assert.equal((await plays('scheduled')).length, 1);
    assert.equal((await plays('scheduled'))[0].volume, 0.4);
    pass('Scheduled bells/audio events use existing API and play once');
    delayedAudio = true;
    event = {event_key: 'late-bell', event: {url: '/audio/late.mp3', volume: 0.8}};
    await deliver(fixture('groups'));
    await deliver({...silentState, silence: {event_id: 'silence-priority', volume: 0.25}});
    await pause(700);
    assert.equal((await plays('scheduled')).length, 1);
    assert.equal((await plays('tv4-silence-audio')).length, 2);
    pass('Late scheduled-audio response cannot override a newer priority mode');
    delayedAudio = false; event = null;
    await deliver(fixture('groups'));
    assert.ok(requests.some(r => r.path === '/api/screen/heartbeat' && r.method === 'POST' && r.token === 'controlled-test-device-token'));
    pass('Existing local device-token and authenticated heartbeat protocol retained');
    const holiday = fixture('holiday');
    state = holiday;
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#special-title').textContent === 'КАНІКУЛИ');
    assert.equal(await page.locator('#tables').isVisible(), false);
    pass('Production holiday state still shows КАНІКУЛИ, never an invented timetable');
    state = fixture('break');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#phase').textContent.includes('Наступний урок'));
    await page.setViewportSize({width: 3840, height: 2160});
    await pause(100);
    assert.deepEqual(await page.locator('#table-left').boundingBox(), {x: 80, y: 368, width: 1808, height: 1560});
    assert.equal(await page.locator('.class-row').count(), 8);
    await page.screenshot({path: path.join(report, 'production-break-4k.png')});
    pass('Production break layout and exact 4K scaling');
    const preview = await browser.newPage();
    await preview.goto(base + '/tv-display-preview.html?sample=groups');
    await preview.waitForFunction(() => document.querySelector('#connection').textContent.includes('АРХІВНИЙ'));
    assert.equal(await preview.locator('audio').count(), 0);
    assert.equal(await preview.locator('html').getAttribute('data-tv-production'), null);
    pass('Separate preview remains silent and isolated');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(report, 'browser-results.json'), JSON.stringify({checks, browser: browser.version(), media: 'instrumented HTMLMediaElement; physical sound not tested', errors}, null, 2));
  } finally { if (browser) await browser.close(); server.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
