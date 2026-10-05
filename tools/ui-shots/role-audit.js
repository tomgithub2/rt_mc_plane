/* 用真实角色账号走一遍：看侧栏/内容区在不同角色下是什么样
   用法：node role-audit.js <base> <adminPw>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9455;
const PROFILE = path.join(os.tmpdir(), 'mcrole-' + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = cdp._id = (cdp._id || 0) + 1;
    const onMsg = (ev) => { const m = JSON.parse(ev.data);
      if (m.id === id) { ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method)) : resolve(m.result); } };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
    setTimeout(() => reject(new Error('timeout ' + method)), 30000);
  });
}

async function main() {
  async function login(u, p) {
    const r = await fetch(BASE + '/api/auth/login', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: u, password: p }) });
    const d = await r.json().catch(() => ({}));
    return d.token || '';
  }
  const admin = await login('admin', PW);
  const viewer = await login('shot-viewer', PW);
  const norm = await login('shot-user', PW);
  console.log('token: admin=' + !!admin + ' viewer=' + !!viewer + ' user=' + !!norm);

  const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--no-default-browser-check', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, 'about:blank'], { stdio: 'ignore' });
  let targets = null;
  for (let i = 0; i < 40; i++) { await sleep(500);
    try { const r = await fetch('http://127.0.0.1:' + PORT + '/json/list'); targets = await r.json();
      if (targets && targets.length) break; } catch (e) {} }
  const page = targets.find((t) => t.type === 'page') || targets[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable'); await cdp(ws, 'Log.enable');
  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 1600, height: 900, deviceScaleFactor: 1, mobile: false });
  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => r.result && r.result.value);
  const errs = [];
  ws.addEventListener('message', (e) => { const m = JSON.parse(e.data);
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 120));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 120)); });

  async function visit(token, hash, label) {
    errs.length = 0;
    await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(1200);
    await ev(`localStorage.setItem('mc_token', ${JSON.stringify(token)})`);
    await cdp(ws, 'Page.navigate', { url: BASE + hash }); await sleep(3000);
    const st = await ev(`(function(){var pb=document.getElementById('page-body');
        return JSON.stringify({ hash:location.hash, role:(window.Perm&&Perm.role&&Perm.role())||null,
          navCount: document.querySelectorAll('.nav-item').length,
          navText: [].map.call(document.querySelectorAll('.nav-item span'),function(e){return e.textContent.trim();}),
          h1:(document.querySelector('.main h1')||{}).textContent||'',
          pbLen: pb?pb.textContent.trim().length:-1,
          denied: /权限不足/.test(document.body.textContent),
          loginPage: !!document.querySelector('.login-wrap') });})()`);
    console.log(`  [${label}] ${st}`);
    if (errs.length) console.log('        异常: ' + errs.slice(0, 3).join(' | '));
    return JSON.parse(st);
  }

  console.log('\n== viewer 角色 ==');
  await visit(viewer, '#/instances', 'viewer/实例列表');
  await visit(viewer, '#/instances/1/console', 'viewer/控制台');
  await visit(viewer, '#/settings', 'viewer/设置');
  await visit(viewer, '#/accounts', 'viewer/账号管理');

  console.log('\n== user 角色 ==');
  await visit(norm, '#/instances', 'user/实例列表');
  await visit(norm, '#/settings', 'user/设置');

  console.log('\n== admin 角色（对照） ==');
  await visit(admin, '#/instances', 'admin/实例列表');
  await visit(admin, '#/settings', 'admin/设置');
  await visit(admin, '#/accounts', 'admin/账号管理');
  await visit(admin, '#/audit', 'admin/审计日志');

  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
