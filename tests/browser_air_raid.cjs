/* Local-only browser integration; no connection to Raspberry Pi or external API. */
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'reports/air-raid');
fs.mkdirSync(out, {recursive: true});
const fixture = name => JSON.parse(fs.readFileSync(path.join(root, `public/preview-data/${name}.json`), 'utf8'));
const fresh = (name = 'shelter') => {
  const s = fixture(name);
  s.now = new Date().toISOString(); s.schedule.date = s.now.slice(0, 10);
  s.sync = {ok:true,at:s.now};
  s.alarm = {active: s.mode === 'AIR_RAID', sound_enabled: true, event_id: 'controlled-alarm', volume: 0.65, status: {http: 200, at: s.now}};
  return s;
};
let state = fresh('groups'), offline = false;
const checks = [], errors = [];
function protectedData() {
  const crypto = require('node:crypto'), result = {};
  const visit = dir => {
    for (const entry of fs.readdirSync(dir, {withFileTypes:true})) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile()) result[path.relative(root,file)] = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    }
  };
  visit(path.join(root,'data')); visit(path.join(root,'public/audio'));
  return result;
}
const initialData = protectedData();
const pass = message => { checks.push(message); console.log('PASS:', message); };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const json = value => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname === '/api/state') { if (offline) { res.writeHead(503); return res.end(); } return json(state); }
  if (url.pathname.startsWith('/api/')) return json({});
  const file = path.resolve(root, 'public', '.' + (url.pathname === '/' ? '/tv4.html' : url.pathname));
  if (!file.startsWith(path.join(root, 'public') + path.sep)) { res.writeHead(403); return res.end(); }
  try {
    res.setHeader('Content-Type', ({'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.json':'application/json'})[path.extname(file)] || 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch { res.writeHead(404); res.end(); }
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({channel:'chrome', headless:true, chromiumSandbox:true});
  try {
    const page = await browser.newPage({viewport:{width:1920,height:1080}});
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.plays = [];
      HTMLMediaElement.prototype.play = function() { window.plays.push({id:this.id,volume:this.volume}); return Promise.resolve(); };
      HTMLMediaElement.prototype.pause = function() {};
    });
    const base = `http://127.0.0.1:${server.address().port}`;
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('АКТУАЛЬНІ'));
    assert.match(await page.locator('#weather').textContent(), /Погода недоступна/);
    state = fresh();
    await page.locator('#air-raid-display').waitFor({state:'visible', timeout:9000});
    assert.equal(await page.locator('#raid-schedule').isVisible(), true);
    assert.equal(await page.locator('#weather').isVisible(), false);
    assert.equal(await page.locator('#air-raid-display').evaluate(n => getComputedStyle(n).backgroundColor), 'rgb(127, 29, 29)');
    assert.deepEqual(await page.locator('#air-raid-display').boundingBox(), {x:0,y:0,width:1920,height:1080});
    assert.equal(await page.locator('#air-raid-display').evaluate(n => n.scrollHeight <= n.clientHeight + 1), true);
    assert.equal((await page.evaluate(() => window.plays.filter(e => e.id === 'tv4-alarm-audio'))).length, 1);
    await page.screenshot({path:path.join(out,'alarm-lesson-full-hd.png')});
    pass('Actual NORMAL → AIR_RAID poll, Full HD red warning, compact shelter rows, weather hidden, alarm once at configured volume');
    state = {...fresh(), schedule:undefined, weather:undefined, alarm:{...fresh().alarm,event_id:'missing-schedule'}};
    await page.waitForFunction(() => document.querySelector('#raid-data-status').textContent.includes('недоступні'), null, {timeout:9000});
    assert.equal(await page.locator('#air-raid-display').isVisible(), true);
    assert.equal((await page.evaluate(() => window.plays.filter(e => e.id === 'tv4-alarm-audio'))).length, 2);
    pass('Alarm rendering and sound work without schedule or weather payload');
    offline = true;
    await page.waitForFunction(() => document.querySelector('#raid-data-status').textContent.includes('застарілі'), null, {timeout:9000});
    assert.equal(await page.locator('#air-raid-display').isVisible(), true);
    assert.equal(await page.locator('#raid-schedule').isVisible(), false);
    await page.reload();
    await page.locator('#air-raid-display').waitFor({state:'visible'});
    assert.equal(await page.locator('#raid-schedule').isVisible(), false);
    pass('Offline cache across reload retains alarm, labels stale data and suppresses stale shelter rows');
    offline = false; state = fresh('groups'); state.mode = 'ALL_CLEAR'; state.alarm = {active:false,status:{http:null}};
    await page.waitForFunction(() => document.querySelector('#special-title').textContent.includes('НЕ ПІДТВЕРДЖЕНО'), null, {timeout:9000});
    assert.equal(await page.locator('#alert-data-notice').isVisible(), true);
    pass('Unknown ALL_CLEAR status is explicitly unconfirmed and never labelled as confirmed all-clear');
    state = fresh('groups'); state.mode = 'ALL_CLEAR'; state.alarm.active = false;
    await page.waitForFunction(() => document.querySelector('#special-title').textContent.includes('ВІДБІЙ'), null, {timeout:9000});
    assert.equal(await page.locator('#air-raid-display').isVisible(), false);
    offline = true;
    await page.waitForFunction(() => document.querySelector('#special-title').textContent.includes('НЕ ПІДТВЕРДЖЕНО'), null, {timeout:9000});
    offline = false;
    state = fresh('groups');
    await page.locator('#tables').waitFor({state:'visible',timeout:9000});
    assert.equal(await page.locator('#air-raid-display').isVisible(), false);
    pass('ALL_CLEAR then NORMAL restores main timetable');
    for (const [name, phase] of [['shelter','LESSON'],['break','BREAK'],['weekend','NO_SCHEDULE'],['holiday','HOLIDAY']]) {
      const s = fixture(name); s.mode = 'AIR_RAID'; s.schedule.shelter = true;
      await page.goto(`${base}/tv-display-preview.html?sample=${name}`);
      await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('2026'));
      assert.equal(await page.locator('audio').count(), 0);
      assert.deepEqual(await page.evaluate(() => window.plays), []);
      await page.evaluate(s => window.SafetyDisplay.render(s, {online:true,sample:true}), s);
      assert.equal(await page.locator('#air-raid-display').isVisible(), true);
      assert.equal(await page.locator('#raid-schedule').isVisible(), ['LESSON','BREAK'].includes(phase));
      await page.screenshot({path:path.join(out,`alarm-${name}-full-hd.png`)});
    }
    pass('Isolated archive preview: lesson, break, weekend and vacation; no invented holiday lessons');
    await page.goto(base + '/index.html'); state = fresh();
    await page.locator('#air-raid-display').waitFor({state:'visible',timeout:9000});
    assert.equal(await page.locator('#weatherCard').isVisible(), false);
    assert.equal(await page.locator('#air-raid-display').evaluate(n => getComputedStyle(n).zIndex), '2147483647');
    await page.screenshot({path:path.join(out,'legacy-alarm-full-hd.png')});
    pass('Legacy blue UI uses same fullscreen safety warning above all ordinary slides');
    const values = await page.evaluate(() => {
      const text = window.SafetyDisplay.weatherText;
      return [text({available:false}), text({available:true,temperature:null}), text({available:true,temperature:0,updated_at:new Date().toISOString()}), text({available:true,temperature:5,updated_at:'2020-01-01'}), text({available:true,temperature:5,stale:true,updated_at:new Date().toISOString()})];
    });
    assert.match(values[0], /Погода недоступна/); assert.match(values[1], /Погода недоступна/);
    assert.match(values[2], /0 °C/); assert.match(values[3], /застарілі/); assert.match(values[4], /застарілі/);
    pass('Weather unavailable/null/zero/old-cache/provider-error presentation');
    for (const change of ['no-sync','old-sync','not-shelter','expired-lesson','old-state','unknown-alert']) {
      const s = fresh();
      if (change === 'no-sync') delete s.sync;
      if (change === 'old-sync') s.sync.at = '2020-01-01';
      if (change === 'not-shelter') s.schedule.shelter = false;
      if (change === 'expired-lesson') s.schedule.seconds_to_lesson_end = 0;
      if (change === 'old-state') s.now = '2020-01-01';
      if (change === 'unknown-alert') { s.mode = 'NORMAL'; s.alarm = {active:false,status:{http:null}}; }
      await page.evaluate(s => window.SafetyDisplay.render(s, {online:true}), s);
      if (change === 'unknown-alert') assert.equal(await page.locator('#alert-data-notice').isVisible(), true);
      else assert.equal(await page.locator('#raid-schedule').isVisible(), false, change);
    }
    pass('Unknown/old timetable source, normal rows, expired lesson and old state cannot qualify as current shelter data; unknown alarm status remains visible');
    assert.deepEqual(errors, []);
    assert.deepEqual(protectedData(), initialData, 'Tests/preview must not mutate production data or audio assets');
    pass('Production data/audio SHA-256 unchanged; archive preview has no audio elements or playback calls');
    fs.writeFileSync(path.join(out,'browser-results.json'), JSON.stringify({checks,errors,noProductionMutation:true},null,2));
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); server.close(); process.exitCode = 1; });
