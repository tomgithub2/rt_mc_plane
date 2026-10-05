/* 实时数据变化的活体验证：启动一个实例，看仪表盘卡片是否**不刷新页面**就自己变
   用法：node live-change.js <base> <password> <iid>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const IID = process.argv[4] || '3';
const PORT = 9677;
const PROFILE = path.join(os.tmpdir(), 'mclc-' + Date.now());
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
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable');
  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => r.result && r.result.value);

  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(4500);

  const snap = () => ev(`(function(){
      var c=document.querySelector('.dash-card[data-id="${IID}"]');
      if(!c) return '(找不到该卡片)';
      var m=c.querySelectorAll('.metrics .metric .v');
      return JSON.stringify({卡状态类: c.className.replace('inst-card dash-card ',''),
        徽标: (c.querySelector('[data-slot="badge"]')||{}).textContent||'',
        运行行: (c.querySelector('[data-slot="uptime"]')||{}).textContent||'',
        CPU: m[0]?m[0].textContent:null, 内存: m[1]?m[1].textContent:null, 玩家: m[2]?m[2].textContent:null,
        副标题: (document.getElementById('dash-sub')||{}).textContent||''});})()`);

  console.log('启动前: ' + await snap());
  // 页面自身不刷新：整个观察期间只记录 DOM，不做任何导航
  const mark = await ev(`(function(){var c=document.querySelector('.dash-card[data-id="${IID}"]');
      if(c) c.setAttribute('data-mark','LIVE'); return !!c;})()`);
  console.log('已打标记: ' + mark);

  console.log('\n通过 API 启动实例 ' + IID + '（页面不做任何刷新）…');
  const tok = await ev(`localStorage.getItem('mc_token')`);
  const r = await fetch(BASE + '/api/instances/' + IID + '/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tok },
    body: '{}' });
  console.log('  启动响应: HTTP ' + r.status + ' ' + (await r.text()).slice(0, 160));

  for (const t of [3, 8, 15, 25, 40]) {
    await sleep(t * 1000 - (t === 3 ? 0 : 0));
    console.log(`\n+${t}s: ` + await snap());
    console.log(`      标记仍在: ` + await ev(`(function(){var c=document.querySelector('.dash-card[data-id="${IID}"]');return c?c.getAttribute('data-mark'):null;})()`));
  }

  console.log('\n停回实例…');
  await fetch(BASE + '/api/instances/' + IID + '/stop', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tok }, body: '{}' });
  await sleep(8000);
  console.log('停止后: ' + await snap());

  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
