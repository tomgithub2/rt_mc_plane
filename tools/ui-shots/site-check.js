/* 官网验收：结构、内容、可点性、响应式、主题、控制台异常
   用法：node site-check.js <base> [outDir]
   ========================================================================== */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const OUT = process.argv[3] || os.tmpdir();
const PORT = 9799;
const PROFILE = path.join(os.tmpdir(), 'mcsite-' + Date.now());
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

  const failed = []; const errs = []; const loaded = [];
  ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
    if (m.method === 'Network.responseReceived') {
      const u = m.params.response.url.replace(BASE, '');
      if (/\.(js|css|html)$|\/$/.test(u)) loaded.push(m.params.response.status + ' ' + u);
      if (m.params.response.status >= 400) failed.push(m.params.response.status + ' ' + u);
    }
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 180));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 160)); });

  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR ' + (r.exceptionDetails.exception?.description || '').slice(0, 200); return r.result && r.result.value; });

  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 1500, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp(ws, 'Page.navigate', { url: BASE + '/site/' }); await sleep(3000);

  console.log('==== 标题与结构 ====');
  console.log(await ev(`(function(){
    return JSON.stringify({
      标题: document.title,
      描述: (document.querySelector('meta[name=description]')||{}).content||'',
      h1: (document.querySelector('h1')||{}).textContent.replace(/\\s+/g,' ').trim(),
      章节: [].map.call(document.querySelectorAll('section[id]'),function(s){return s.id}),
      功能卡: document.querySelectorAll('.fcard').length,
      核心表行: document.querySelectorAll('.tbl tbody tr').length,
      步骤: document.querySelectorAll('.step').length,
      FAQ: document.querySelectorAll('.faq details').length,
      设计块: document.querySelectorAll('.dbox').length,
      色板: document.querySelectorAll('.sw').length,
      正文长度: document.body.textContent.replace(/\\s+/g,' ').trim().length
    }, null, 1);})()`));

  console.log('\n==== 导航锚点是否都有对应节点 ====');
  console.log(await ev(`(function(){
    var out=[];
    [].slice.call(document.querySelectorAll('.nav-links a')).forEach(function(a){
      var id=a.getAttribute('href'); if(!id||id[0]!=='#') return;
      out.push(id+' -> '+(document.querySelector(id)?'OK':'缺失'));
    });
    return out.join('\\n');})()`));

  console.log('\n==== 主题切换与动画 ====');
  console.log('  初始主题: ' + await ev(`document.documentElement.getAttribute('data-theme')`));
  await ev(`document.getElementById('theme-btn').click()`); await sleep(400);
  console.log('  点一次后: ' + await ev(`document.documentElement.getAttribute('data-theme')`));
  await ev(`document.getElementById('theme-btn').click()`); await sleep(400);
  console.log('  再点一次: ' + await ev(`document.documentElement.getAttribute('data-theme')`));
  await sleep(2500);
  console.log('  界面示意: ' + await ev(`(function(){
    var f=document.querySelector('.bar-fill');
    var n=document.querySelector('.mock .num');
    return JSON.stringify({进度条宽:f?f.style.width:'-', 首个数字:n?n.textContent:'-',
      入场动画已触发: document.querySelectorAll('.reveal.in').length+'/'+document.querySelectorAll('.reveal').length});})()`));

  console.log('\n==== 响应式（780 / 1024 / 1500） ====');
  for (const w of [1500, 1024, 780, 420]) {
    await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(700);
    console.log('  ' + await ev(`(function(){
      var nav=document.querySelector('.nav-links'); var mb=document.getElementById('menu-btn');
      var ns=getComputedStyle(nav); var ms=getComputedStyle(mb);
      return JSON.stringify({宽:${w}, 导航display:ns.display, 汉堡display:ms.display,
        横向溢出: document.documentElement.scrollWidth>window.innerWidth+1});})()`));
  }

  // 截图
  for (const [w, h, tag] of [[1500, 1000, 'wide'], [420, 900, 'mobile']]) {
    await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await sleep(900);
    const png = await cdp(ws, 'Page.captureScreenshot', { format: 'png', fromSurface: true,
      clip: { x: 0, y: 0, width: w, height: h, scale: 1 } });
    const f = path.join(OUT, 'site-' + tag + '.png');
    fs.writeFileSync(f, Buffer.from(png.data, 'base64'));
    console.log('\n  截图 ' + f + '  ' + fs.statSync(f).size + ' 字节');
  }

  console.log('\n==== 资源加载 ====');
  loaded.forEach((x) => console.log('  ' + x));
  if (failed.length) { console.log('  ❌ 失败请求:'); failed.forEach((x) => console.log('    ' + x)); }
  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\nconsole: ' + (real.length ? real.slice(0, 5).join('\n         ') : '（无异常）'));
  ws.close(); edge.kill(); await sleep(400);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
