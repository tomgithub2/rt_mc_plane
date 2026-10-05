/* 创建向导：逐步检查元素重叠 + 可点性
   重叠判定：任意两个"应该互不覆盖"的按钮/列表项，矩形重叠面积 > 30% 视为重合
   用法：node create-overlap.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9744;
const PROFILE = path.join(os.tmpdir(), 'mcover-' + Date.now());
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
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 180));
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errs.push('LOG ' + m.params.entry.text.slice(0, 160)); });
  const ev = (e) => cdp(ws, 'Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })
    .then((r) => { if (r.exceptionDetails) return 'EVALERR ' + (r.exceptionDetails.exception?.description || '').slice(0, 200); return r.result && r.result.value; });

  const OVERLAP = `(function(){
    var pb=document.getElementById('page-body');
    if(!pb) return '[]';
    // 找最近的"裁剪祖先"（overflow 为 auto/scroll/hidden 且内容溢出）
    function clipper(el){
      var p=el.parentElement;
      while(p && p!==document.body){
        var s=getComputedStyle(p);
        if(/auto|scroll|hidden/.test(s.overflowY) && p.scrollHeight>p.clientHeight+1) return p;
        if(/auto|scroll|hidden/.test(s.overflowX) && p.scrollWidth>p.clientWidth+1) return p;
        p=p.parentElement;
      }
      return null;
    }
    // a 的裁剪祖先是否会切掉 b 的矩形 → 说明 b 在可视区外，不算重叠
    function clippedAway(a,b){
      var c=clipper(a); if(!c) return false;
      var cr=c.getBoundingClientRect(), br=b.getBoundingClientRect();
      return br.top >= cr.bottom-1 || br.bottom <= cr.top+1 ||
             br.left >= cr.right-1 || br.right <= cr.left+1;
    }
    var sel='button, .btn, .version-item, .core-card, input, select, .field, .step, .badge, .tip, .version-list, .build-list, .ver-picked';
    var els=[].slice.call(pb.querySelectorAll(sel)).filter(function(e){
      var s=getComputedStyle(e); if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity)===0) return false;
      var r=e.getBoundingClientRect(); return r.width>4&&r.height>4;});
    var bad=[];
    for(var i=0;i<els.length;i++) for(var j=i+1;j<els.length;j++){
      var a=els[i],b=els[j];
      if(a.contains(b)||b.contains(a)) continue;
      if(clippedAway(a,b)||clippedAway(b,a)) continue;   // 被滚动容器裁掉的不算
      var ra=a.getBoundingClientRect(), rb=b.getBoundingClientRect();
      var ox=Math.max(0,Math.min(ra.right,rb.right)-Math.max(ra.left,rb.left));
      var oy=Math.max(0,Math.min(ra.bottom,rb.bottom)-Math.max(ra.top,rb.top));
      var inter=ox*oy; if(inter<=0) continue;
      var smaller=Math.min(ra.width*ra.height, rb.width*rb.height);
      if(smaller>0 && inter/smaller>0.3){
        bad.push({a:(a.textContent||a.tagName).trim().slice(0,26), b:(b.textContent||b.tagName).trim().slice(0,26),
                  ratio:Math.round(inter/smaller*100),
                  aBox:[Math.round(ra.x),Math.round(ra.y),Math.round(ra.width),Math.round(ra.height)],
                  bBox:[Math.round(rb.x),Math.round(rb.y),Math.round(rb.width),Math.round(rb.height)]});
      }
    }
    return JSON.stringify(bad.slice(0,10), null, 1);})()`;

  const clickNext = () => ev(`(function(){
      var bs=[].slice.call(document.querySelectorAll('#w-next,#w-create,button'));
      for(var i=0;i<bs.length;i++){
        var t=(bs[i].textContent||'').trim();
        if(/^下一步|^创建并开始下载/.test(t)&&!bs[i].disabled){bs[i].click();return t;}
      } return 'NONE';})()`);

  await cdp(ws, 'Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' }); await sleep(2000);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(4000);
  await ev(`location.hash='#/create'`); await sleep(3000);

  const names = ['1 选核心', '2 选版本', '3 内存/端口', '4 Java', '5 确认'];
  for (let s = 0; s < 5; s++) {
    await sleep(1600);
    const o = await ev(OVERLAP);
    console.log('\n===== 第 ' + names[s] + ' 步的重叠检测 =====');
    console.log(o === '[]' ? '  ✅ 无重叠' : '  ⚠️ ' + o);
    if (s < 4) { const r = await clickNext(); console.log('  下一步 -> ' + r); }
  }

  console.log('\n===== 点"创建并开始下载"后的结果区 =====');
  const r = await ev(`(function(){var b=document.getElementById('w-create'); if(!b) return 'NO_BTN'; b.click(); return 'clicked';})()`);
  console.log('  ' + r);
  await sleep(9000);
  console.log(await ev(OVERLAP));
  console.log('  结果区文本: ' + await ev(`(function(){var e=document.getElementById('create-result');
      return e?e.textContent.replace(/\\s+/g,' ').slice(0,200):'(无)';})()`));
  const real = errs.filter((e) => !/favicon/.test(e));
  console.log('\nconsole: ' + (real.length ? real.slice(0, 4).join('\n         ') : '（无异常）'));
  ws.close(); edge.kill(); await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
