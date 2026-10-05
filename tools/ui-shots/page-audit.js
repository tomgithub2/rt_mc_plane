/* 逐页走查：把每个页面都打开，记录 h1 / 内容长度 / console 异常 / 失败请求
   用法：node page-audit.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9366;
const PROFILE = path.join(os.tmpdir(), 'mcaudit-' + Date.now());
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
  await cdp(ws, 'Network.enable');

  const errs = [];
  const httpFails = [];
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === 'Runtime.exceptionThrown') {
      errs.push('EXC ' + (m.params.exceptionDetails.exception?.description ||
                          m.params.exceptionDetails.text));
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      errs.push('ERR ' + m.params.args.map((a) => a.value || a.description || '').join(' '));
    }
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
      errs.push('LOG ' + m.params.entry.text + ' @ ' + (m.params.entry.url || ''));
    }
    if (m.method === 'Network.responseReceived') {
      const r = m.params.response;
      if (r.status >= 400) httpFails.push(r.status + ' ' + r.url.replace(BASE, ''));
    }
  });

  async function ev(expr) {
    const r = await cdp(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result && r.result.value;
  }

  /* 先登录（走真实表单） */
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' });
  await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(3000);
  console.log('登录后 hash=' + await ev('location.hash'));

  // 找一个实例 id
  const iid = await ev(`fetch('/api/instances',{headers:{Authorization:'Bearer '+localStorage.getItem('mc_token')}})
      .then(r=>r.json()).then(d=>(d.instances&&d.instances[0])?d.instances[0].id:0)`);
  console.log('用实例 id=' + iid);

  const pages = [
    ['#/instances', '实例列表'],
    ['#/create', '新建实例向导'],
    ['#/settings', '设置页'],
    ['#/audit', '审计日志'],
    ['#/accounts', '账号管理'],
    ['#/instances/' + iid, '实例详情-控制台'],
    ['#/instances/' + iid + '/files', '详情-文件'],
    ['#/instances/' + iid + '/config', '详情-配置'],
    ['#/instances/' + iid + '/players', '详情-玩家'],
    ['#/instances/' + iid + '/plugins', '详情-插件'],
    ['#/instances/' + iid + '/backups', '详情-备份'],
    ['#/instances/' + iid + '/cron', '详情-任务'],
    ['#/instances/' + iid + '/build', '详情-建筑'],
    ['#/instances/' + iid + '/settings', '详情-设置']
  ];

  let bad = 0;
  for (const [hash, label] of pages) {
    errs.length = 0; httpFails.length = 0;
    await ev(`location.hash=${JSON.stringify(hash)}`);
    await sleep(2600);
    const st = JSON.parse(await ev(`JSON.stringify({
        h1: (document.querySelector('#page-body h1')||document.querySelector('#app h1')||{}).textContent || '',
        bodyLen: (document.getElementById('page-body')||document.body).textContent.trim().length,
        empty: !!document.querySelector('#page-body .empty'),
        rows: document.querySelectorAll('#page-body table tbody tr').length,
        cards: document.querySelectorAll('#page-body .card, #page-body .stat').length,
        boot: !!document.querySelector('.boot-splash')
      })`));
    const realErrs = errs.filter((e) => !/favicon/.test(e));
    const badHttp = httpFails.filter((u) => !/favicon/.test(u));
    const ok = st.h1 && st.bodyLen > 40 && !st.boot && realErrs.length === 0 && badHttp.length === 0;
    if (!ok) bad++;
    console.log(`${ok ? ' OK ' : 'BAD '} ${label.padEnd(14)} h1="${st.h1}" 文本=${st.bodyLen} 行=${st.rows} 卡片=${st.cards}` +
                (st.boot ? ' [卡在启动画面]' : '') +
                (realErrs.length ? '\n      异常: ' + realErrs.slice(0, 3).join(' | ') : '') +
                (badHttp.length ? '\n      失败请求: ' + badHttp.slice(0, 6).join(' | ') : ''));
  }

  console.log('\n==== 汇总：' + bad + ' / ' + pages.length + ' 个页面有问题 ====');
  ws.close(); edge.kill();
  await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
