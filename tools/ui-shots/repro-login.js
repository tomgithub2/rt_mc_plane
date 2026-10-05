/* 真实用户路径复现：打开页面 → 填登录表单 → 提交 → 看落地页与报错
   用法：node repro-login.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9355;
const PROFILE = path.join(os.tmpdir(), 'mcrepro-' + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = cdp._id = (cdp._id || 0) + 1;
    const onMsg = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === id) {
        ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method + ': ' + JSON.stringify(m.error))) : resolve(m.result);
      }
    };
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
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      targets = await r.json();
      if (targets && targets.length) break;
    } catch (e) {}
  }
  const page = targets.find((t) => t.type === 'page') || targets[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  await cdp(ws, 'Page.enable');
  await cdp(ws, 'Runtime.enable');
  await cdp(ws, 'Log.enable');

  const errs = [];
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === 'Runtime.exceptionThrown') {
      errs.push('EXC ' + (m.params.exceptionDetails.exception?.description ||
                          m.params.exceptionDetails.text));
    }
    if (m.method === 'Runtime.consoleAPICalled') {
      const txt = m.params.args.map((a) => a.value || a.description || '').join(' ');
      if (m.params.type === 'error' || m.params.type === 'warning') errs.push(m.params.type.toUpperCase() + ' ' + txt);
    }
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
      errs.push('LOG ' + m.params.entry.text + ' @ ' + (m.params.entry.url || ''));
    }
  });

  async function ev(expr) {
    const r = await cdp(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result && r.result.value;
  }
  async function snap(tag) {
    const s = await ev(`JSON.stringify({
        hash: location.hash,
        appKids: document.getElementById('app') ? document.getElementById('app').children.length : -1,
        firstCls: (document.querySelector('#app > *')||{}).className || '',
        h1: (document.querySelector('#app h1')||{}).textContent || '',
        hasForm: !!document.getElementById('login-form'),
        hasLoginWrap: !!document.querySelector('.login-wrap'),
        hasShell: !!document.querySelector('.shell'),
        token: (localStorage.getItem('mc_token')||'').length,
        bodyLen: document.body.textContent.trim().length,
        bodyHead: document.body.textContent.trim().slice(0,80)
      })`);
    console.log(`  [${tag}] ${s}`);
    return JSON.parse(s);
  }

  console.log('== 1) 打开首页（新访客） ==');
  await cdp(ws, 'Page.navigate', { url: BASE + '/' });
  await sleep(2500);
  await snap('首页');

  console.log('\n== 2) 打开 #/login ==');
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' });
  await sleep(2000);
  await snap('登录页');

  console.log('\n== 3) 填表并提交 ==');
  await ev(`(function(){
      var u=document.getElementById('u'), p=document.getElementById('p');
      if(!u||!p) return 'NO_FORM';
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit', {cancelable:true, bubbles:true}));
      return 'submitted';
    })()`).then((r) => console.log('  submit ->', r));
  await sleep(4000);
  await snap('提交后');

  console.log('\n== 4) 手动跳实例页 ==');
  await ev("location.hash='#/instances'");
  await sleep(3000);
  await snap('实例页');

  console.log('\n== 5) 账号管理页 ==');
  await ev("location.hash='#/accounts'");
  await sleep(3000);
  await snap('账号页');

  console.log('\n== 6) 直接刷新账号页（冷启动） ==');
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/accounts' });
  await sleep(3500);
  await snap('刷新后账号页');

  console.log('\n== console 异常/告警 ==');
  if (errs.length) errs.slice(0, 25).forEach((e) => console.log('  ' + e));
  else console.log('  （无）');

  ws.close(); edge.kill();
  await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
