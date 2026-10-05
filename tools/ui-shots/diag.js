/* 在无头 Edge 里直接检查路由与页面处理器注册状态（诊断用） */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = 'http://127.0.0.1:8100';
const PORT = 9336;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let _id = 0;
function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = ++_id;
    const on = (ev) => { const m = JSON.parse(ev.data); if (m.id === id) { ws.removeEventListener('message', on); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); } };
    ws.addEventListener('message', on);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
    setTimeout(() => reject(new Error('timeout ' + method)), 20000);
  });
}
(async () => {
  const prof = path.join(os.tmpdir(), 'mcdiag-' + Date.now());
  const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--remote-debugging-port=' + PORT, '--user-data-dir=' + prof, 'about:blank'], { stdio: 'ignore' });
  let t = null;
  for (let i = 0; i < 40; i++) { await sleep(500); try { t = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json(); if (t.length) break; } catch (e) {} }
  const ws = new WebSocket(t.find(x => x.type === 'page').webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable');
  // 关键：先固定视口，否则默认 756px 会命中 ≤1024 断点、侧栏变抽屉并被移出视口
  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  const lr = await fetch(BASE + '/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'admin', password: process.argv[2] }) });
  const tok = (await lr.json()).token;
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/instances' });
  await sleep(1500);
  await cdp(ws, 'Runtime.evaluate', { expression: `localStorage.setItem('mc_token','${tok}')` });
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/instances/1/console' });
  await sleep(2500);
  const expr = `JSON.stringify({
     pages: Object.keys(window.Pages||{}),
     hasDetail: typeof (window.Pages||{}).instanceDetail,
     hasInstances: typeof (window.Pages||{}).instances,
     /* 注意：建筑 Tab 不是 Pages.build，而是 instance_detail.js 内的 RENDER.build
        调用 PagesBuild.render(...)，所以这里检查 PagesBuild。 */
     hasPagesBuild: typeof window.PagesBuild,
     hasMockBuild: typeof window.MockBuild,
     hasPagesBuild: typeof window.PagesBuild,
     current: (window.Router && Router.current && Router.current()),
     hash: location.hash,
     iconsCount: Object.keys((window.Icon||{}).paths||{}).length,
     hasBg: typeof window.Bg,
     hasChart: typeof window.Chart,
     innerW: window.innerWidth,
     mediaHideSidebar: window.matchMedia('(max-width: 1024px)').matches,
     shellExists: !!document.querySelector('.shell'),
     sidebarExists: !!document.querySelector('.sidebar'),
     sidebarRect: (function(){var e=document.querySelector('.sidebar');if(!e)return null;var r=e.getBoundingClientRect();
        return {x:r.x,w:r.width,h:r.height,display:getComputedStyle(e).display,transform:getComputedStyle(e).transform,position:getComputedStyle(e).position};})(),
     stylesheets: Array.prototype.map.call(document.styleSheets, function(s){return s.href;}),
     sidebarW: getComputedStyle(document.documentElement).getPropertyValue('--sidebar-w').trim(),
     cardCount: document.querySelectorAll('.inst-card').length,
     contentLen: ((document.getElementById('page-body')||{innerHTML:''}).innerHTML||'').length,
     contentStart: ((document.getElementById('page-body')||{innerHTML:''}).innerHTML||'').slice(0,180)
   })`;
  const r = await cdp(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true });
  console.log(r.result.value);
  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  process.exit(0);
})().catch(e => { console.error('FAIL ' + e.message); process.exit(1); });
