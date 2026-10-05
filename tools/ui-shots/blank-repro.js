/* 用户报障复现：内容区空 + 亮色
   量清楚：资源加载状态、主题解析后的真实变量、侧栏/内容区几何、内容区到底有没有节点
   用法：node blank-repro.js <base> <password> [width] [height]
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const W = parseInt(process.argv[4] || '2555', 10);
const H = parseInt(process.argv[5] || '1323', 10);
const PORT = 9601;
const PROFILE = path.join(os.tmpdir(), 'mcblank-' + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = cdp._id = (cdp._id || 0) + 1;
    const onMsg = (ev) => { const m = JSON.parse(ev.data);
      if (m.id === id) { ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method + ' ' + JSON.stringify(m.error))) : resolve(m.result); } };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
    setTimeout(() => reject(new Error('timeout ' + method)), 30000);
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
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable'); await cdp(ws, 'Log.enable'); await cdp(ws, 'Network.enable');
  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });

  const res = []; const errs = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Network.responseReceived') {
      const u = m.params.response.url.replace(BASE, '');
      if (/\.(js|css)$/.test(u) || u === '/') res.push(m.params.response.status + ' ' + u);
    }
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 260));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 200));
  });

  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR: ' + (r.exceptionDetails.exception?.description || '').slice(0, 200); return r.result && r.result.value; });

  await cdp(ws, 'Page.navigate', { url: BASE + '/' }); await sleep(3000);
  console.log('==== 资源加载 ====');
  res.forEach((x) => console.log('   ' + x));
  console.log('\n==== 首屏异常 ====');
  console.log(errs.length ? errs.map((e) => '   ' + e).join('\n') : '   （无）');

  console.log('\n==== 登录 ====');
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      if(!u||!p) return 'NO_FORM'; u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true})); return 'ok';})()`)
    .then((r) => console.log('   submit=' + r));
  await sleep(4000);
  res.length = 0; errs.length = 0;
  await ev(`location.hash='#/instances'`);
  await sleep(3500);

  console.log('\n==== 该页资源（若新页面有新脚本） ====');
  console.log(res.length ? res.map((x) => '   ' + x).join('\n') : '   （无新请求）');

  const info = await ev(`(function(){
      var cs=getComputedStyle(document.documentElement);
      function box(sel){ var e=document.querySelector(sel); if(!e) return null;
        var r=e.getBoundingClientRect(); var s=getComputedStyle(e);
        return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
                disp:s.display,vis:s.visibility,op:s.opacity,bg:s.backgroundColor,col:s.color}; }
      var pb=document.getElementById('page-body');
      return JSON.stringify({
        hash: location.hash,
        theme: document.documentElement.getAttribute('data-theme'),
        density: document.documentElement.getAttribute('data-density'),
        prefersLight: window.matchMedia('(prefers-color-scheme: light)').matches,
        vars: { bgBase: cs.getPropertyValue('--bg-base').trim(),
                surface1: cs.getPropertyValue('--surface-1').trim(),
                textPrimary: cs.getPropertyValue('--text-primary').trim(),
                line2: cs.getPropertyValue('--line-2').trim() },
        bodyBg: getComputedStyle(document.body).backgroundColor,
        shell: box('.shell'), sidebar: box('.sidebar'), main: box('.main'),
        content: box('.content'), pageBody: box('#page-body'),
        pbChildren: pb ? pb.children.length : -1,
        pbText: pb ? pb.textContent.trim().slice(0,160) : '(无 #page-body)',
        pbHtmlHead: pb ? pb.innerHTML.trim().slice(0,200) : '',
        statCards: document.querySelectorAll('#page-body .stat').length,
        instCards: document.querySelectorAll('#page-body .inst-card, #page-body .inst-grid > *').length,
        topbarChildren: document.querySelectorAll('.topbar > *').length,
        navItems: document.querySelectorAll('.nav-item').length
      });})()`);
  console.log('\n==== 实测状态 ====');
  try { console.log(JSON.stringify(JSON.parse(info), null, 1)); } catch (e) { console.log(info); }

  console.log('\n==== 该页异常 ====');
  console.log(errs.length ? errs.map((e) => '   ' + e).join('\n') : '   （无）');

  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
