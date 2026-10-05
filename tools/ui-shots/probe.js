/* 对照实验：在同一页面分别注入几种 CSS，找出手栏/内容不参与合成的真正原因。
   每种变体各截一张，随后用 inspect_shots.py 看非背景像素占比。 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = 'http://127.0.0.1:8100';
const PORT = 9338;
const OUT = path.resolve(__dirname, '..', '..', 'docs', 'ui-review', '_probe');
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
const VARIANTS = [
  ['A-baseline', ''],
  ['B-no-sidebar', '.sidebar{display:none !important}'],
  ['C-nosticky', '.sidebar,.topbar{position:static !important}'],
  ['D-nosticky-nosidebar', '.sidebar{display:none !important}.topbar{position:static !important}'],
  ['E-shell-block', '.shell{display:block !important}'],
  ['F-opaque-bg', '.shell,.main,.content{background:#ffffff !important}'],
  ['G-no-modal-filter', '*{backdrop-filter:none !important;-webkit-backdrop-filter:none !important}'],
];
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const prof = path.join(os.tmpdir(), 'mcprobe-' + Date.now());
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

  for (const [name, css] of VARIANTS) {
    await cdp(ws, 'Page.navigate', { url: BASE + '/#/instances' });
    await sleep(2600);
    await cdp(ws, 'Runtime.evaluate', { expression: `(function(){
        var old=document.getElementById('__probe'); if(old) old.remove();
        var st=document.createElement('style'); st.id='__probe'; st.textContent=${JSON.stringify(css)};
        document.head.appendChild(st);
        return true; })()` });
    await sleep(600);
    const r = await cdp(ws, 'Page.captureScreenshot', { format: 'png', fromSurface: true });
    fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(r.data, 'base64'));
    console.log('  probe ' + name);
  }
  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  process.exit(0);
})().catch(e => { console.error('FAIL ' + e.message); process.exit(1); });
