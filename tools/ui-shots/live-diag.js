/* 诊断：仪表盘实时通道在"用户真实加载路径"下是否生效
   报告：加载到的 dashboard.js 是不是新代码、WS 是否建立、收到多少帧、徽标状态、数值是否在变
   用法：node live-diag.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9699;
const PROFILE = path.join(os.tmpdir(), 'mcdiag-' + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = cdp._id = (cdp._id || 0) + 1;
    const onMsg = (ev) => { const m = JSON.parse(ev.data);
      if (m.id === id) { ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method)) : resolve(m.result); } };
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
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable'); await cdp(ws, 'Log.enable'); await cdp(ws, 'Network.enable');

  const jsHash = {}; const wsUrls = []; let frames = 0; const errs = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Network.responseReceived') {
      const u = m.params.response.url;
      if (/dashboard\.js/.test(u)) jsHash.dashboard = m.params.response.headers['content-length'] || '?';
      if (/\.js$|\.css$/.test(u)) jsHash[u.split('/').pop()] = m.params.response.status;
    }
    if (m.method === 'Network.webSocketCreated') wsUrls.push(m.params.url.replace(BASE, ''));
    if (m.method === 'Network.webSocketFrameReceived' &&
        (m.params.response.payloadData || '').indexOf('"live"') >= 0) frames++;
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 180));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 160));
  });

  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR ' + (r.exceptionDetails.exception?.description || '').slice(0, 200); return r.result && r.result.value; });

  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(4500);

  console.log('==== 前端代码版本 ====');
  console.log('  dashboard.js content-length = ' + (jsHash.dashboard || '(未记录)'));
  console.log('  判断依据：新版含 "patchCard" / "dash-live" / 无 setInterval(…,5000) 轮询');

  console.log('\n==== 页面内代码特征 ====');
  const feat = await ev(`(function(){
      var src = [].slice.call(document.scripts).map(function(s){return s.src}).filter(function(s){return /dashboard/.test(s)});
      return JSON.stringify({
        有实时徽标元素: !!document.getElementById('dash-live'),
        徽标文本: (document.getElementById('dash-live')||{}).textContent||'(无)',
        卡片总数: document.querySelectorAll('.dash-card').length,
        有data-slot: document.querySelectorAll('[data-slot]').length,
        脚本: src
      });})()`);
  console.log('  ' + feat);

  console.log('\n==== WebSocket ====');
  console.log('  建立的连接: ' + JSON.stringify(wsUrls));

  console.log('\n==== 观察 8 秒（数据是否在变） ====');
  frames = 0;
  const samples = [];
  for (let i = 0; i < 8; i++) {
    await sleep(1000);
    samples.push(await ev(`(function(){var c=document.querySelector('.dash-card');
      var m=c?c.querySelectorAll('.metrics .metric .v'):[];
      var up=c?c.querySelector('[data-slot="uptime"]'):null;
      return JSON.stringify({t:${i + 1}, 徽标:(document.getElementById('dash-live')||{}).textContent||'',
        CPU:m[0]?m[0].textContent:'', 内存:m[1]?m[1].textContent:'', 运行:up?up.textContent:''});})()`));
  }
  samples.forEach((s) => console.log('  ' + s));
  const uniq = new Set(samples.map((s) => s.replace(/"t":\d+,/, '')));
  console.log('\n  收到 live 帧: ' + frames);
  console.log('  8 秒内出现过 ' + uniq.size + ' 种不同状态' + (uniq.size <= 1 ? '  ← 数据确实没变（实例都没在跑）' : ''));

  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\nconsole: ' + (real.length ? real.slice(0, 4).join(' | ') : '（无异常）'));
  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
