/* 在放大视口后测量真实几何：确认各元素是否可见、在视口内（诊断截图空白问题） */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = 'http://127.0.0.1:8100';
const PORT = 9337;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let _id = 0;
function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = ++_id;
    const on = (ev) => { const m = JSON.parse(ev.data); if (m.id === id) { ws.removeEventListener('message', on); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); } };
    ws.addEventListener('message', on);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
    setTimeout(() => reject(new Error('timeout ' + method)), 25000);
  });
}
(async () => {
  const prof = path.join(os.tmpdir(), 'mcgeo-' + Date.now());
  const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--remote-debugging-port=' + PORT, '--user-data-dir=' + prof, 'about:blank'], { stdio: 'ignore' });
  let t = null;
  for (let i = 0; i < 40; i++) { await sleep(500); try { t = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json(); if (t.length) break; } catch (e) {} }
  const ws = new WebSocket(t.find(x => x.type === 'page').webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable');
  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  const lr = await fetch(BASE + '/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'admin', password: process.argv[2] }) });
  const tok = (await lr.json()).token;
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/instances' });
  await sleep(1200);
  await cdp(ws, 'Runtime.evaluate', { expression: `localStorage.setItem('mc_token','${tok}')` });
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/instances' });
  await sleep(3000);
  const expr = `(function(){
    function info(sel){
      var e = document.querySelector(sel);
      if(!e) return {sel:sel, exists:false};
      var r = e.getBoundingClientRect(), cs = getComputedStyle(e);
      return {sel:sel, exists:true, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height),
              display:cs.display, visibility:cs.visibility, opacity:cs.opacity, bg:cs.backgroundColor, color:cs.color,
              zIndex:cs.zIndex, position:cs.position};
    }
    return JSON.stringify({
      vw: window.innerWidth, vh: window.innerHeight,
      els: [info('.shell'), info('.sidebar'), info('.main'), info('.topbar'), info('.content'),
            info('#page-body'), info('.page-head'), info('#stats'), info('#inst-list'), info('.empty'), info('.stat')],
      emptyText: (document.querySelector('.empty .t')||{}).textContent || null,
      statsText: (document.getElementById('stats')||{}).textContent ? document.getElementById('stats').textContent.slice(0,80) : null,
      bodyBg: getComputedStyle(document.body).backgroundColor,
      theme: document.documentElement.getAttribute('data-theme')
    });
  })()`;
  const r = await cdp(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true });
  const d = JSON.parse(r.result.value);
  console.log('viewport', d.vw + 'x' + d.vh, 'theme=' + d.theme, 'bodyBg=' + d.bodyBg);
  d.els.forEach(e => console.log('  ' + JSON.stringify(e)));
  console.log('emptyText=', d.emptyText);
  console.log('statsText=', d.statsText);
  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  process.exit(0);
})().catch(e => { console.error('FAIL ' + e.message); process.exit(1); });
