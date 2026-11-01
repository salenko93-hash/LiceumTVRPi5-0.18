/* Full HD equivalence and isolation; only a local fixture server is started. */
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'reports/demo-tv-display');
fs.mkdirSync(out, {recursive:true});
const scenes = {lesson:'lesson', break:'break', numerator:'lesson', denominator:'denominator',
  substitution:'substitution', groups:'groups', duty:'lesson', holiday:'holiday', shelter:'shelter'};
const fixture = name => JSON.parse(fs.readFileSync(path.join(root, `public/preview-data/${name}.json`), 'utf8'));
function hashes(dir) {
  const result = {};
  const visit = folder => fs.readdirSync(folder, {withFileTypes:true}).forEach(item => {
    const file = path.join(folder, item.name);
    if (item.isDirectory()) visit(file);
    else if (item.isFile()) result[path.relative(dir,file)] = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  });
  visit(dir); return result;
}
const before = {data:hashes(path.join(root,'data')), audio:hashes(path.join(root,'public/audio')), server:hashes(path.join(root,'server'))};
const checks = [], comparisons = [], errors = [];
const pass = message => { checks.push(message); console.log('PASS:',message); };
let current;
const server = http.createServer((req,res) => {
  // Same framing/script restrictions as the application; DEMO needs no iframe/eval.
  res.setHeader('X-Frame-Options','DENY');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
  const url = new URL(req.url,'http://localhost');
  const json = body => {res.setHeader('Content-Type','application/json');res.end(JSON.stringify(body));};
  if (url.pathname === '/api/state') return json(current);
  if (url.pathname.startsWith('/api/')) return json({});
  if (url.pathname.startsWith('/preview-data/')) {
    const name = path.basename(url.pathname,'.json');
    if (!Object.values(scenes).includes(name)) {res.writeHead(404);return res.end();}
    const snapshot = fixture(name);
    snapshot.sync = {ok:true,at:snapshot.now};
    snapshot.alarm = {active:snapshot.mode === 'AIR_RAID',sound_enabled:false,status:{http:200,at:snapshot.now}};
    return json(snapshot);
  }
  const file = path.resolve(root,'public','.'+url.pathname);
  if (!file.startsWith(path.join(root,'public')+path.sep)) {res.writeHead(403);return res.end();}
  try {
    res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css'})[path.extname(file)] || 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch {res.writeHead(404);res.end();}
});
const sleep = ms => new Promise(resolve => setTimeout(resolve,ms));
async function until(page, condition) {
  for (let n=0;n<150;n++) { if (await page.evaluate(condition)) return; await sleep(50); }
  throw Error('UI condition timed out');
}
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({channel:'chrome',headless:true,chromiumSandbox:true});
  try {
    const base = `http://127.0.0.1:${server.address().port}`;
    const context = await browser.newContext({viewport:{width:1920,height:1080}});
    await context.addInitScript(() => {
      const at = Number(new URLSearchParams(location.search).get('qaNow'));
      if (at) Date.now = () => at; // identical frozen test time on both pages
      window.mediaCalls = []; window.storageWrites = [];
      HTMLMediaElement.prototype.play = function() {window.mediaCalls.push(this.src);return Promise.resolve();};
      HTMLMediaElement.prototype.pause = function() {};
      const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key,value) {window.storageWrites.push(key);return set.call(this,key,value);};
    });
    const demo = await context.newPage(), production = await context.newPage();
    const requests = [];
    demo.on('request', request => requests.push({method:request.method(),url:request.url()}));
    for (const page of [demo,production]) page.on('pageerror', error => errors.push(error.message));
    for (const [scene,sample] of Object.entries(scenes)) {
      current = fixture(sample);
      current.sync = {ok:true,at:current.now};
      current.alarm = {active:current.mode === 'AIR_RAID',sound_enabled:false,status:{http:200,at:current.now}};
      const query = `qaNow=${Date.parse(current.now)}`;
      await demo.goto(`${base}/demo.html?scenario=${scene}&controls=hidden&${query}`);
      await until(demo, () => document.documentElement.dataset.demoReady === 'true');
      // DEMO applies the explicit duty-only test override in memory.
      if (scene === 'duty') current.duty = {enabled:true,paused:false,class:'10-В'};
      await production.goto(`${base}/tv4.html?${query}`);
      await until(production, () => document.querySelector('#connection').textContent.includes('АКТУАЛЬНІ'));
      for (const page of [demo,production]) {
        await page.evaluate(() => document.fonts.ready);
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      }
      assert.equal(await demo.locator('#demoBadge').isVisible(),true);
      assert.equal(await demo.locator('audio').count(),0);
      assert.deepEqual(await demo.evaluate(() => window.mediaCalls),[]);
      assert.deepEqual(await demo.evaluate(() => window.storageWrites),[]);
      assert.equal(await demo.evaluate(() => typeof window.TVDisplayDemo.render),'function');
      assert.equal(await production.evaluate(() => typeof window.TVDisplayDemo),'undefined');
      const signature = page => page.evaluate(() => [...document.querySelectorAll('.table,.class-row,.columns,.cell,.fit-text')].map(n => {
        const r=n.getBoundingClientRect(), c=getComputedStyle(n);
        return {text:n.textContent,rect:[r.x,r.y,r.width,r.height],font:c.font,fontSize:c.fontSize,color:c.color,background:c.backgroundColor,columns:c.gridTemplateColumns};
      }));
      assert.deepEqual(await signature(demo),await signature(production),`${scene}: table typography/geometry/data`);
      await demo.screenshot({path:path.join(out,`${scene}-demo-1920x1080.png`)});
      await production.screenshot({path:path.join(out,`${scene}-production-1920x1080.png`)});
      // Only metadata and DEMO controls differ by design. Hide them in both
      // comparison copies; keep the original, labelled screenshots above.
      const normalize = '#demoControls,#demoOpen,#demoBadge{display:none!important}.edition b,.footer,#special>span{visibility:hidden!important}#raid-data-status{display:none!important}';
      const a = await demo.addStyleTag({content:normalize});
      const b = await production.addStyleTag({content:normalize});
      const demoImage = await demo.screenshot({path:path.join(out,`${scene}-demo-layout.png`)});
      const prodImage = await production.screenshot({path:path.join(out,`${scene}-production-layout.png`)});
      const pixelDifference = await demo.evaluate(async images => {
        const decoded = await Promise.all(images.map(async base64 => {
          const img = new Image(); img.src = `data:image/png;base64,${base64}`; await img.decode();
          const canvas = document.createElement('canvas'); canvas.width=img.width; canvas.height=img.height;
          const ctx=canvas.getContext('2d'); ctx.drawImage(img,0,0); return ctx.getImageData(0,0,img.width,img.height).data;
        }));
        let changed=0, maxChannelDelta=0, onlyRoundedTableCorners=true, minX=1920,minY=1080,maxX=-1,maxY=-1;
        for (let i=0;i<decoded[0].length;i+=4) if ([0,1,2,3].some(c=>decoded[0][i+c]!==decoded[1][i+c])) {
          changed++; for (let c=0;c<4;c++) maxChannelDelta=Math.max(maxChannelDelta,Math.abs(decoded[0][i+c]-decoded[1][i+c]));
          const p=i/4,x=p%1920,y=Math.floor(p/1920);
          const nearCorner = [40,976].some(left =>
            Math.min(Math.abs(x-left),Math.abs(x-(left+904)))<=2 && Math.min(Math.abs(y-184),Math.abs(y-964))<=24
            || Math.min(Math.abs(y-184),Math.abs(y-964))<=2 && Math.min(Math.abs(x-left),Math.abs(x-(left+904)))<=24);
          onlyRoundedTableCorners = onlyRoundedTableCorners && nearCorner;
          minX=Math.min(minX,x);minY=Math.min(minY,y);maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);
        }
        return {changed,maxChannelDelta,onlyRoundedTableCorners,bounds:[minX,minY,maxX,maxY]};
      }, [demoImage.toString('base64'),prodImage.toString('base64')]);
      // Permit only tiny antialiasing differences at rounded table corners:
      // <=10 of 2,073,600 pixels, <=4/255 per channel. Text has no tolerance.
      assert.ok(pixelDifference.changed<=10 && pixelDifference.maxChannelDelta<=4 && pixelDifference.onlyRoundedTableCorners,`${scene}: normalized Full HD pixels: ${JSON.stringify(pixelDifference)}`);
      await a.evaluate(n=>n.remove()); await b.evaluate(n=>n.remove());
      comparisons.push({scene,sample,fullHDLayoutEquivalent:true,pixelIdentical:pixelDifference.changed===0,pixelDifference,sha256:crypto.createHash('sha256').update(demoImage).digest('hex')});
      if (scene === 'substitution') assert.equal(await demo.locator('.badge').count()>0,true);
      if (scene === 'groups') assert.equal(await demo.locator('.is-split').count()>0,true);
      if (scene === 'duty') assert.match(await demo.locator('[data-class="10-В"] .duty-mark').textContent(),/ЧЕРГОВИЙ/);
      if (scene === 'holiday') assert.equal(await demo.locator('#tables').isVisible(),false);
      if (scene === 'shelter') {
        assert.equal(await demo.locator('#air-raid-display').isVisible(),true);
        assert.equal(await demo.locator('#demoBadge').isVisible(),true);
        await demo.locator('#demoOpen').click();
        assert.equal(await demo.locator('#demoControls').isVisible(),true);
      }
      pass(`${scene}: shared geometry/type/data match; Full HD pixel difference ${pixelDifference.changed}, max channel delta ${pixelDifference.maxChannelDelta}`);
    }
    await demo.locator('#demoHide').click();
    assert.equal(await demo.locator('#demoBadge').isVisible(),true);
    await demo.keyboard.press('Escape');
    await Promise.all([demo.waitForEvent('load'), demo.locator('#demoScenario').selectOption('groups')]);
    await until(demo, () => document.documentElement.dataset.demoReady === 'true');
    assert.equal(await demo.locator('#demoScenario').inputValue(),'groups');
    assert.equal(await demo.locator('.is-split').count()>0,true);
    await demo.bringToFront();
    await demo.locator('#demoFullscreen').click();
    await until(demo, () => !!document.fullscreenElement);
    await demo.locator('#demoFullscreen').click();
    await until(demo, () => !document.fullscreenElement);
    pass('Controls: scenario navigation, hide/open/Escape and fullscreen work; DEMO label survives alarm and hidden controls');
    await demo.goto(`${base}/demo.html?scenario=invalid&sample=shelter`);
    await until(demo, () => document.documentElement.dataset.demoReady === 'true');
    assert.equal(await demo.locator('#demoScenario').inputValue(),'lesson');
    assert.match(await demo.locator('#phase').textContent(),/Поточний урок/);
    assert.equal(await demo.locator('#air-raid-display').isVisible(),false);
    await demo.route('**/preview-data/lesson.json', route => route.fulfill({status:503,body:'fixture unavailable'}));
    await demo.reload();
    await until(demo, () => !document.querySelector('#demoError').hidden);
    assert.equal(await demo.locator('#demoBadge').isVisible(),true);
    assert.deepEqual(await demo.evaluate(() => window.mediaCalls),[]);
    pass('Invalid scene falls back to a bounded test fixture; unavailable fixture shows an error without API fallback or sound');
    assert.deepEqual(requests.filter(r=>r.method !== 'GET' || new URL(r.url).pathname.startsWith('/api/') || r.url.includes('/audio/')),[]);
    assert.deepEqual(hashes(path.join(root,'data')),before.data);
    assert.deepEqual(hashes(path.join(root,'public/audio')),before.audio);
    assert.deepEqual(hashes(path.join(root,'server')),before.server);
    pass('DEMO has no API/audio requests, no writes, no storage changes; production data/audio/server hashes unchanged');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({checks,comparisons,errors,viewport:{width:1920,height:1080},normalization:'Only DEMO chrome and mode/source metadata hidden for pixel comparison; originals saved with labels'},null,2));
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
