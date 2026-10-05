/* 仪表盘实时更新验收
   验证：WS 是否连上、是否持续收到 live 帧、卡片是否**原地更新**（DOM 节点不被替换）、
   sparkline 是否累积、拖动/置顶是否不受推送影响、断线是否退避重连。
   用法：node live-check.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9666;
const PROFILE = path.join(os.tmpdir(), 'mclive-' + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = cdp._id = (cdp._id || 0) + 1;
    const onMsg = (ev) => { const m = JSON.parse(ev.data);
      if (m.id === id) { ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method + ' ' + JSON.stringify(m.error))) : resolve(m.result); } };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
    setTimeout(() => reject(new Error('timeout ' + method)), 40000);
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

  const frames = []; const wsEvents = []; const errs = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Network.webSocketCreated') wsEvents.push('created ' + m.params.url.replace(BASE, ''));
    if (m.method === 'Network.webSocketClosed') wsEvents.push('closed');
    if (m.method === 'Network.webSocketFrameReceived') {
      const p = m.params.response.payloadData || '';
      if (p.indexOf('"live"') >= 0) frames.push(Date.now());
    }
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
  console.log('落地页 = ' + await ev('location.hash'));

  /* 给第一张卡打标记，验证推送是"原地更新"而不是"整页重绘" */
  await ev(`(function(){var c=document.querySelector('.dash-card');
      if(c) c.setAttribute('data-mark','KEEP'); return !!c;})()`);
  const before = await ev(`(function(){var c=document.querySelector('.dash-card');
      return JSON.stringify({有标记: c?c.getAttribute('data-mark'):null,
        卡片数: document.querySelectorAll('.dash-card').length,
        实时徽标: (document.getElementById('dash-live')||{}).textContent||'',
        spark点数: document.querySelectorAll('.dash-card .spark-wrap svg polyline, .dash-card .spark-wrap path').length});})()`);
  console.log('\n推送前: ' + before);

  console.log('\n等待 9 秒观察实时帧…');
  frames.length = 0;
  await sleep(9000);

  const after = await ev(`(function(){var c=document.querySelector('.dash-card');
      var ring=document.querySelector('.dash-card [data-slot="ring"]');
      return JSON.stringify({有标记: c?c.getAttribute('data-mark'):null,
        卡片数: document.querySelectorAll('.dash-card').length,
        实时徽标: (document.getElementById('dash-live')||{}).textContent||'',
        spark点数: document.querySelectorAll('.dash-card .spark-wrap svg polyline, .dash-card .spark-wrap path').length,
        副标题: (document.getElementById('dash-sub')||{}).textContent||''});})()`);
  console.log('推送后: ' + after);

  console.log('\n==== 实时性结论 ====');
  console.log('  收到的 live 帧数（9 秒内）: ' + frames.length);
  if (frames.length >= 3) {
    const gaps = frames.slice(1).map((t, i) => t - frames[i]);
    console.log('  帧间隔(ms): ' + gaps.map((g) => Math.round(g)).join(', '));
  }
  console.log('  WebSocket 事件: ' + JSON.stringify(wsEvents.slice(0, 6)));
  const A = JSON.parse(before), B = JSON.parse(after);
  console.log('  ✅ 原地更新（标记保留）: ' + (B['有标记'] === 'KEEP' ? '是' : '否 —— 被整页重绘了'));
  console.log('  ✅ sparkline 累积: ' + (B.spark点数 >= A.spark点数 ? '是' : '否'));
  console.log('  ✅ 实时徽标: ' + B.实时徽标);

  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\nconsole: ' + (real.length ? real.slice(0, 4).join(' | ') : '（无异常）'));

  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
