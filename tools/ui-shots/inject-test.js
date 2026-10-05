/* 决定性测试：注入已知颜色的元素，看截图里到底出现什么。
   · 固定定位红块（高层级）  → 若出现，说明合成正常，问题在内容自身
   · 内容区内联绿块          → 若出现，说明内容区在渲染
   · 侧栏内蓝块              → 若出现，说明侧栏在渲染 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = 'http://127.0.0.1:8100';
const PORT = 9339;
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
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const prof = path.join(os.tmpdir(), 'mcinj-' + Date.now());
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
  const inj = `(function(){
     function box(id, color, style){
       var d=document.createElement('div'); d.id=id;
       d.style.cssText='background:'+color+';'+style;
       d.textContent=id;
       return d;
     }
     document.body.appendChild(box('FIXED_RED','#ff0000','position:fixed;left:10px;top:10px;width:200px;height:80px;z-index:2147483647;color:#fff;font-size:20px'));
     var c=document.querySelector('.content')||document.body;
     c.appendChild(box('INLINE_GREEN','#00ff00','position:relative;width:300px;height:60px;color:#000;font-size:18px'));
     var s=document.querySelector('.sidebar')||document.body;
     s.appendChild(box('SIDE_BLUE','#0000ff','position:relative;width:150px;height:50px;color:#fff;font-size:18px'));
     var pb=document.getElementById('page-body');
     if(pb) pb.appendChild(box('PAGEBODY_YELLOW','#ffff00','position:relative;width:400px;height:60px;color:#000;font-size:18px'));
     return JSON.stringify({content:!!document.querySelector('.content'), pb:!!pb, sidebar:!!document.querySelector('.sidebar')});
  })()`;
  const injRes = await cdp(ws, 'Runtime.evaluate', { expression: inj, returnByValue: true });
  console.log('injected:', injRes.result.value);
  await sleep(600);
  let r = await cdp(ws, 'Page.captureScreenshot', { format: 'png', fromSurface: true });
  fs.writeFileSync(path.join(OUT, 'INJ-viewport.png'), Buffer.from(r.data, 'base64'));
  r = await cdp(ws, 'Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, fromSurface: true });
  fs.writeFileSync(path.join(OUT, 'INJ-beyond.png'), Buffer.from(r.data, 'base64'));
  r = await cdp(ws, 'Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1920, height: 1080, scale: 1 }, captureBeyondViewport: true });
  fs.writeFileSync(path.join(OUT, 'INJ-clip.png'), Buffer.from(r.data, 'base64'));
  console.log('captured 3 variants');
  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  process.exit(0);
})().catch(e => { console.error('FAIL ' + e.message); process.exit(1); });
