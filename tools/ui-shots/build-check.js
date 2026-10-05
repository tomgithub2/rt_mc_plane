/* 建筑导入 Tab · 真实接口联通验收
   记录该 Tab 实际打了哪些接口、页面里有没有真实数据（格式表/导入记录），
   并在浏览器里真的走一次 上传 → 预检 全链路。
   用法：node build-check.js <base> <password> [samplePath]
   ========================================================================== */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const SAMPLE = process.argv[4] || '';
const PORT = 9533;
const PROFILE = path.join(os.tmpdir(), 'mcbuild-' + Date.now());
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

  const seen = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Network.requestWillBeSent') {
      const u = m.params.request.url.replace(BASE, '');
      if (/\/api\//.test(u)) seen.push(m.params.request.method + ' ' + u.split('?')[0]);
    } });
  const errs = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 200));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 160)); });
  await cdp(ws, 'Network.enable');

  const ev = (e, awaitP) => cdp(ws, 'Runtime.evaluate',
    { expression: e, returnByValue: true, awaitPromise: awaitP !== false })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR ' + (r.exceptionDetails.exception?.description || '').slice(0, 200); return r.result && r.result.value; });

  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(3500);

  const iid = await ev(`fetch('/api/instances',{headers:{Authorization:'Bearer '+localStorage.getItem('mc_token')}})
    .then(r=>r.json()).then(d=>(d.instances&&d.instances[0])?d.instances[0].id:0)`);
  console.log('实例 id=' + iid);

  seen.length = 0; errs.length = 0;
  await ev(`location.hash='#/instances/${iid}/build'`);
  await sleep(4000);

  console.log('\n== 建筑 Tab 发出的接口 ==');
  (seen.length ? seen : ['(无)']).forEach((s) => console.log('   ' + s));
  const need = ['/api/build/formats', '/api/instances/' + iid + '/build/tasks'];
  need.forEach((n) => {
    const hit = seen.some((s) => s.indexOf(n) >= 0);
    console.log('   ' + (hit ? '✅' : '❌') + ' 调用了 ' + n);
  });

  const dom = JSON.parse(await ev(`(function(){
      var pb=document.getElementById('page-body');
      var txt=pb?pb.textContent:'';
      var cards=document.querySelectorAll('#tab-body .card, #page-body .card').length;
      return JSON.stringify({
        h1:(document.querySelector('.main h1')||{}).textContent||'',
        len: txt.length,
        hasDrop: !!document.getElementById('b-drop'),
        hasFormats: /\\.schem/.test(txt) && /\\.litematic/.test(txt),
        hasHistory: /导入记录|还没有导入过建筑/.test(txt),
        hasEngine: /offline|Anvil/.test(txt),
        cards: cards,
        head: txt.replace(/\\s+/g,' ').slice(0, 320)
      });})()`));
  console.log('\n== 页面内容 ==');
  console.log('   h1=' + dom.h1 + '  文本=' + dom.len + ' 卡片=' + dom.cards);
  console.log('   拖放区=' + dom.hasDrop + '  真实格式表=' + dom.hasFormats +
              '  导入记录区=' + dom.hasHistory + '  引擎信息=' + dom.hasEngine);
  console.log('   摘要: ' + dom.head);

  if (SAMPLE && fs.existsSync(SAMPLE)) {
    console.log('\n== 浏览器内真实上传样本 ==');
    const b64 = fs.readFileSync(SAMPLE).toString('base64');
    const name = path.basename(SAMPLE);
    seen.length = 0;
    const up = await ev(`(async function(){
        var bin = atob(${JSON.stringify(b64)});
        var arr = new Uint8Array(bin.length);
        for (var i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
        var f = new File([arr], ${JSON.stringify(name)}, {type:'application/octet-stream'});
        var dt = new DataTransfer(); dt.items.add(f);
        var drop = document.getElementById('b-drop');
        if (!drop) return 'NO_DROP';
        var ev2 = new Event('drop', {bubbles:true, cancelable:true});
        ev2.dataTransfer = dt;
        drop.dispatchEvent(ev2);
        await new Promise(function(r){ setTimeout(r, 6000); });
        var pb = document.getElementById('page-body');
        return JSON.stringify({ txt: pb.textContent.replace(/\\s+/g,' ').slice(0,400),
          hasPreview: /区块|调色板|未映射|引擎/.test(pb.textContent) });
      })()`);
    console.log('   上传后: ' + up);
    console.log('   上传期间接口: ' + JSON.stringify(seen));
  } else {
    console.log('\n（未提供样本路径，跳过真实上传）');
  }

  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\n== console ==');
  console.log(real.length ? real.slice(0, 5).join('\n') : '   （无异常）');

  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
