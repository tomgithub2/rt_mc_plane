/* 视图验收：遍历实例列表与仪表盘的所有视图，检查渲染是否成立、是否持久化
   用法：node views-check.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9711;
const PROFILE = path.join(os.tmpdir(), 'mcviews-' + Date.now());
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

  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 2000, height: 1100, deviceScaleFactor: 1, mobile: false });
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(4500);

  const probe = (page) => `(function(){
      var sw=document.querySelector('[data-view-switch="${page}"]');
      var active=sw?sw.querySelector('.btn.active'):null;
      var pb=document.getElementById('page-body');
      return JSON.stringify({
        页面:'${page}',
        切换器按钮:(sw?[].map.call(sw.querySelectorAll('.btn'),function(b){return b.getAttribute('data-v')}):[]),
        当前视图: active?active.getAttribute('data-v'):'(无)',
        卡片: document.querySelectorAll('.dash-card').length,
        实例卡: document.querySelectorAll('.inst-card').length,
        紧凑行: document.querySelectorAll('.dense-row').length,
        表头列: document.querySelectorAll('.dense-head > *').length,
        表格: document.querySelectorAll('#page-body table').length,
        分组块: document.querySelectorAll('.group-block').length,
        分组标题: [].map.call(document.querySelectorAll('.group-head h3'),function(h){return h.textContent}),
        趋势图: document.querySelectorAll('.chart-host svg').length,
        趋势空: document.querySelectorAll('.chart-host .chart-empty').length,
        状态色带: document.querySelectorAll('.status-cell').length,
        文本长度: pb?pb.textContent.trim().length:-1
      });})()`;

  async function pickView(page, key) {
    return ev(`(function(){
      var sw=document.querySelector('[data-view-switch="${page}"]');
      if(!sw) return 'NO_SWITCH';
      var b=sw.querySelector('[data-v="${key}"]');
      if(!b) return 'NO_BTN';
      b.click(); return 'clicked';})()`);
  }

  console.log('========== 实例列表（4 视图） ==========');
  await ev(`location.hash='#/instances'`); await sleep(3000);
  for (const k of ['cards', 'compact', 'table', 'grouped']) {
    console.log('  切换 -> ' + k + ': ' + await pickView('instances', k));
    await sleep(1400);
    console.log('    ' + await ev(probe('instances')));
  }
  console.log('\n  持久化检查（刷新后应保持 grouped）:');
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/instances' }); await sleep(4000);
  console.log('    ' + await ev(probe('instances')));

  console.log('\n========== 仪表盘（3 视图） ==========');
  await ev(`location.hash='#/dashboard'`); await sleep(3000);
  for (const k of ['cards', 'compact', 'trend']) {
    console.log('  切换 -> ' + k + ': ' + await pickView('dashboard', k));
    await sleep(2200);
    console.log('    ' + await ev(probe('dashboard')));
  }
  console.log('\n  趋势视图持续 6 秒（看曲线是否随时间增长）:');
  for (let i = 0; i < 3; i++) {
    await sleep(2000);
    console.log('    ' + await ev(`(function(){
        var svgs=document.querySelectorAll('.chart-host svg');
        var paths=[].map.call(document.querySelectorAll('.chart-host svg path[stroke]'),function(p){return (p.getAttribute('d')||'').length});
        return JSON.stringify({图数:svgs.length, 路径点数:paths, 色带格数:document.querySelectorAll('.status-cell .strip i').length});})()`));
  }

  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\nconsole: ' + (real.length ? real.slice(0, 5).join('\n         ') : '（无异常）'));
  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
