/* 创建向导的"自动下载"实际体验验收
   走真实 UI：选核心 → 选版本 → 内存/端口 → 确认创建，全程记录网络请求与页面文案，
   重点看：进度条是否动、失败是否说清原因、下载中能否启动、成功后 jar 是否正确。
   用法：node wizard-download.js <base> <password> [core]
   ========================================================================== */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const CORE = process.argv[4] || 'paper';
const PORT = 9722;
const PROFILE = path.join(os.tmpdir(), 'mcwiz-' + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(ws, method, params) {
  return new Promise((resolve, reject) => {
    const id = cdp._id = (cdp._id || 0) + 1;
    const onMsg = (ev) => { const m = JSON.parse(ev.data);
      if (m.id === id) { ws.removeEventListener('message', onMsg);
        m.error ? reject(new Error(method + ' ' + JSON.stringify(m.error))) : resolve(m.result); } };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
    setTimeout(() => reject(new Error('timeout ' + method)), 90000);
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

  const reqs = []; const errs = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Network.responseReceived') {
      const u = (m.params.response.url || '').replace(BASE, '');
      if (/\/api\//.test(u)) reqs.push(m.params.response.status + ' ' + u.split('?')[0]);
    }
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 200));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 180));
  });

  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR ' + (r.exceptionDetails.exception?.description || '').slice(0, 240); return r.result && r.result.value; });
  const txt = () => ev(`(function(){var pb=document.getElementById('page-body');
      return pb?pb.textContent.replace(/\\s+/g,' ').trim().slice(0,700):'(无)';})()`);
  const clickText = (t) => ev(`(function(){
      var els=[].slice.call(document.querySelectorAll('button, .core-card, .opt, [data-core], [data-pick], label'));
      var hit=els.filter(function(e){return (e.textContent||'').replace(/\\s+/g,' ').indexOf(${JSON.stringify(t)})>=0});
      if(!hit.length) return 'NOT_FOUND';
      hit[0].click(); return 'clicked:'+hit[0].textContent.replace(/\\s+/g,' ').trim().slice(0,40);})()`);

  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(4000);

  console.log('==== 进入创建向导 ====');
  await ev(`location.hash='#/create'`); await sleep(3000);
  console.log('  步骤1: ' + (await txt()).slice(0, 260));

  console.log('\n==== 选核心: ' + CORE + ' ====');
  console.log('  ' + await ev(`(function(){
      var els=[].slice.call(document.querySelectorAll('[data-core], .core-card, [data-src], .opt-card'));
      if(!els.length) return 'NO_CORE_ELEMENTS';
      var hit=els.filter(function(e){return e.getAttribute('data-core')==='${CORE}'||e.getAttribute('data-src')==='${CORE}'
        ||(e.textContent||'').toLowerCase().indexOf('${CORE}')>=0});
      if(!hit.length) return 'NO_MATCH; 可选=' + els.map(function(e){return e.getAttribute('data-core')||e.getAttribute('data-src')||e.textContent.trim().slice(0,14)}).join('|');
      hit[0].click(); return 'clicked ' + (hit[0].getAttribute('data-core')||hit[0].getAttribute('data-src')||'?');})()`));
  await sleep(2500);

  console.log('\n==== 选版本 ====');
  console.log('  ' + await ev(`(function(){
      var sel=document.querySelector('select');
      var opts=[].slice.call(document.querySelectorAll('[data-ver], .ver-item, .opt'));
      if(sel && sel.options.length>1){ sel.value=sel.options[sel.options.length-1].value||sel.options[1].value;
        sel.dispatchEvent(new Event('change',{bubbles:true}));
        return 'select -> ' + sel.value + ' (共'+sel.options.length+'项)'; }
      if(opts.length){ opts[opts.length-1].click(); return 'clicked opt ' + opts[opts.length-1].textContent.trim(); }
      return 'NO_VERSION_UI';})()`));
  await sleep(2500);
  console.log('  当前: ' + (await txt()).slice(0, 300));

  console.log('\n==== 一路点"下一步"，直到出现"创建/确认" ====');
  for (let i = 0; i < 6; i++) {
    const r = await ev(`(function(){
        var bs=[].slice.call(document.querySelectorAll('button'));
        var nx=bs.filter(function(b){return /下一步|继续|确认创建|创建|开始下载|确定/.test(b.textContent)&&!b.disabled});
        if(!nx.length) return 'NO_NEXT';
        nx[0].click(); return 'clicked: '+nx[0].textContent.replace(/\\s+/g,' ').trim();})()`);
    console.log('   ' + r);
    await sleep(2200);
    if (/确认|创建/.test(r) && !/下一步/.test(r)) break;
  }

  console.log('\n==== 页面文案（看是否出现下载进度） ====');
  console.log('  ' + (await txt()).slice(0, 600));

  console.log('\n==== 观察下载（最多 90 秒，记录进度文案变化） ====');
  reqs.length = 0;
  let prev = '';
  for (let i = 1; i <= 30; i++) {
    await sleep(3000);
    const t = await ev(`(function(){var pb=document.getElementById('page-body');
        var prog=document.querySelector('.progress i');
        var pm=document.querySelector('.progress');
        return JSON.stringify({pct: prog?prog.style.width:null,
          进度块: !!pm, 文案:(pm&&pm.parentNode?pm.parentNode.textContent.replace(/\\s+/g,' ').trim():'').slice(0,120),
          页尾: pb?pb.textContent.replace(/\\s+/g,' ').trim().slice(-200):''});})()`);
    if (t !== prev) { console.log(`   ${i * 3}s: ${t}`); prev = t; }
    const o = JSON.parse(t);
    if (/100%/.test(o.进度块 ? o.文案 : '') || /创建成功|已完成|下载完成|进入实例/.test(o.页尾)) {
      console.log('   -> 看起来已完成'); break;
    }
  }

  console.log('\n==== 下载期间/之后的接口调用 ====');
  [...new Set(reqs)].forEach((r) => console.log('   ' + r));

  console.log('\n==== 最终页面文案 ====');
  console.log('  ' + (await txt()).slice(0, 600));

  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\nconsole: ' + (real.length ? real.slice(0, 5).join('\n         ') : '（无异常）'));

  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
