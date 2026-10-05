/* 忠实复现用户路径：**热缓存**（不 reload、不强制刷新）+ 点菜单导航，
   记录每步的请求、console 异常与内容区状态。
   用法：node user-path.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9466;
const PROFILE = path.join(os.tmpdir(), 'mcpath-' + Date.now());
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
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable'); await cdp(ws, 'Log.enable'); await cdp(ws, 'Network.enable');
  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 1600, height: 900, deviceScaleFactor: 1, mobile: false });

  let reqs = [], errs = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Network.responseReceived') { const r = m.params.response;
      reqs.push(r.status + ' ' + r.url.replace(BASE, '').split('?')[0]); }
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text || '').slice(0, 200));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 160));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.types === 'error') errs.push('ERR');
  });
  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR: ' + (r.exceptionDetails.exception?.description || '').slice(0, 150); return r.result && r.result.value; });

  async function state(tag) {
    const s = await ev(`(function(){var pb=document.getElementById('page-body');
      return JSON.stringify({hash:location.hash, shell:!!document.querySelector('.shell'),
        nav: document.querySelectorAll('.nav-item').length,
        h1:(document.querySelector('.main h1')||{}).textContent||'',
        pbLen: pb?pb.textContent.trim().length:-1,
        pbHead: pb?pb.textContent.trim().slice(0,70):'',
        hasProb: !!document.getElementById('prob-retry'),
        login: !!document.querySelector('.login-wrap'),
        tok: (localStorage.getItem('mc_token')||'').length });})()`);
    const real = errs.filter((e) => !/favicon/.test(e));
    console.log(`  [${tag}] ${s}`);
    if (real.length) console.log('        异常: ' + real.slice(0, 3).join(' | '));
    errs = [];
    return s;
  }

  console.log('== 1) 首次打开（无令牌） ==');
  reqs = []; await cdp(ws, 'Page.navigate', { url: BASE + '/' }); await sleep(2500);
  await state('首屏');

  console.log('\n== 2) 提交登录表单（模拟用户输入） ==');
  reqs = [];
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      if(!u||!p) return 'NOFORM'; u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));
      return 'ok';})()`).then((r) => console.log('    submit=' + r));
  await sleep(4000);
  await state('登录后');

  console.log('\n== 3) 用点菜单的方式导航（不刷新页面） ==');
  for (const [label, hash] of [['设置', '#/settings'], ['账号管理', '#/accounts'], ['审计日志', '#/audit'], ['新建实例', '#/create'], ['实例列表', '#/instances']]) {
    reqs = [];
    const clicked = await ev(`(function(){
        var el=document.querySelector('[data-nav="${hash}"]');
        if(!el) return 'NO_MENU_ITEM';
        el.click(); return 'clicked';})()`);
    await sleep(2800);
    const s = JSON.parse(await state('点' + label + ' (' + clicked + ')'));
    const bad = reqs.filter((x) => /^(4|5)\d\d /.test(x) && !/mock-accounts/.test(x));
    if (bad.length) console.log('        失败请求: ' + bad.slice(0, 5).join(' | '));
  }

  console.log('\n== 4) 直接刷新当前页（热缓存，模拟 F5） ==');
  reqs = []; errs = [];
  await cdp(ws, 'Page.reload', {}); await sleep(3500);
  await state('F5 之后');
  const bad2 = reqs.filter((x) => /^(4|5)\d\d /.test(x));
  if (bad2.length) console.log('        失败请求: ' + bad2.slice(0, 5).join(' | '));

  console.log('\n== 5) 进实例详情控制台 ==');
  reqs = []; errs = [];
  await ev(`location.hash='#/instances/1/console'`); await sleep(3500);
  await state('控制台');
  const bad3 = reqs.filter((x) => /^(4|5)\d\d /.test(x));
  if (bad3.length) console.log('        失败请求: ' + bad3.slice(0, 5).join(' | '));

  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
