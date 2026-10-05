/* 创建向导布局诊断：核心网格、版本列表、导航按钮的几何与可点击性
   用法：node create-diag.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9733;
const PROFILE = path.join(os.tmpdir(), 'mcwizdiag-' + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = cdp._id = (cdp._id || 0) + 1;
    const onMsg = (ev) => { const m = JSON.parse(ev.data);
      if (m.id === id) { ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method + ' ' + JSON.stringify(m.error))) : resolve(m.result); } };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
    setTimeout(() => reject(new Error('timeout ' + method)), 60000);
  });
}

async function main() {
  const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + PROFILE, 'about:blank'], { stdio: 'ignore' });
  let targets = null;
  for (let i = 0; i < 40; i++) { await sleep(500);
    try { const r = await fetch('http://127.0.0.1:' + PORT + '/json/list'); targets = await r.json();
      if (targets && targets.length) break; } catch (e) {} }
  const page = targets.find((t) => t.type === 'page') || targets[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable'); await cdp(ws, 'Log.enable');
  const errs = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 200));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 180)); });

  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR ' + (r.exceptionDetails.exception?.description || '').slice(0, 240); return r.result && r.result.value; });

  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(4000);
  await ev(`location.hash='#/create'`); await sleep(3000);

  const geom = () => ev(`(function(){
      function box(sel, parent){ var els=[].slice.call((parent||document).querySelectorAll(sel));
        return els.slice(0, 30).map(function(e){ var r=e.getBoundingClientRect(); var s=getComputedStyle(e);
          return {t:(e.textContent||'').trim().slice(0,20), x:Math.round(r.x), y:Math.round(r.y),
                  w:Math.round(r.width), h:Math.round(r.height), disp:s.display, vis:s.visibility,
                  pe:s.pointerEvents, z:s.zIndex, pos:s.position}; }); }
      var card=document.querySelector('.core-card');
      var body=document.getElementById('page-body');
      return JSON.stringify({
        核心卡: box('.core-card'),
        导航按钮: box('.nav, .row button, #w-next, #w-back, button'),
        版本项: box('.version-item'),
        手填框: box('#v-manual'),
        页面文本: body?body.textContent.replace(/\\s+/g,' ').slice(0,300):''
      });})()`);

  console.log('==== 第 1 步（选核心）几何 ====');
  console.log(await geom());

  // 切到第 2 步看版本列表
  await ev(`(function(){var b=document.getElementById('w-next'); if(b) b.click(); return 1;})()`);
  await sleep(3500);
  console.log('\n==== 第 2 步（选版本）几何 ====');
  console.log(await geom());

  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\nconsole: ' + (real.length ? real.slice(0, 5).join('\n         ') : '（无异常）'));
  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
