/* 最后一项定位实验：把同样的内容分别放进 (a) 现有 .shell 内、(b) 直接放 body，
   看哪一种能被截图捕捉。用于判断是 .shell 布局的问题还是内容自身的问题。 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = 'http://127.0.0.1:8100';
const PORT = 9340;
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
  const prof = path.join(os.tmpdir(), 'mcshell-' + Date.now());
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

  // (a) 复制 .page-body 的 HTML 直接插入 body（脱离 .shell）
  await cdp(ws, 'Runtime.evaluate', { expression: `(function(){
      var src=document.getElementById('page-body');
      var host=document.createElement('div');
      host.id='DETACHED_COPY';
      host.style.cssText='position:absolute;left:0;top:0;width:1400px;background:#00ff00;color:#000;z-index:5;padding:20px';
      host.innerHTML = src ? src.innerHTML : '<b>no page-body</b>';
      document.body.appendChild(host);
      return host.getBoundingClientRect().height; })()`, returnByValue: true });
  await sleep(700);
  let r = await cdp(ws, 'Page.captureScreenshot', { format: 'png', fromSurface: true });
  fs.writeFileSync(path.join(OUT, 'DETACHED-copy.png'), Buffer.from(r.data, 'base64'));

  // (b) 保留 .shell，但把 .shell 的 CSS 全部取消
  await cdp(ws, 'Runtime.evaluate', { expression: `(function(){
      var c=document.getElementById('DETACHED_COPY'); if(c) c.remove();
      var st=document.createElement('style'); st.id='__unshell';
      st.textContent='.shell{display:block !important;min-height:0 !important}' +
                     '.sidebar{display:none !important}' +
                     '.main{display:block !important}' +
                     '.content{padding:20px !important}' +
                     'body{height:auto !important}';
      document.head.appendChild(st); return true; })()` });
  await sleep(700);
  r = await cdp(ws, 'Page.captureScreenshot', { format: 'png', fromSurface: true });
  fs.writeFileSync(path.join(OUT, 'UNSHELL.png'), Buffer.from(r.data, 'base64'));
  console.log('captured DETACHED-copy.png / UNSHELL.png');
  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  process.exit(0);
})().catch(e => { console.error('FAIL ' + e.message); process.exit(1); });
