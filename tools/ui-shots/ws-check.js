/* 单独验控制台 WebSocket：登录 → 进实例控制台 → 看 WS 是否真的连上并收到 hello
   用法：node ws-check.js <base> <password>
   ========================================================================== */
const { spawn } = require('child_process');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const PORT = 9377;
const PROFILE = path.join(os.tmpdir(), 'mcws-' + Date.now());
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
  await cdp(ws, 'Page.enable'); await cdp(ws, 'Runtime.enable'); await cdp(ws, 'Log.enable');

  const wsEvents = [];
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === 'Network.webSocketFrameReceived' || m.method === 'Network.webSocketCreated' ||
        m.method === 'Network.webSocketClosed' || m.method === 'Network.webSocketFrameError') {
      wsEvents.push(m.method.replace('Network.', '') + ' ' +
        (m.params.response ? JSON.stringify(m.params.response).slice(0, 120) : '') +
        (m.params.url || ''));
    }
    if (m.method === 'Log.entryAdded' && /websocket/i.test(m.params.entry.text || '')) {
      wsEvents.push('LOG ' + m.params.entry.text.slice(0, 160));
    }
  });
  await cdp(ws, 'Network.enable');

  async function ev(expr) {
    const r = await cdp(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result && r.result.value;
  }

  await cdp(ws, 'Page.navigate', { url: BASE + '/#/login' });
  await sleep(1800);
  await ev(`(function(){var u=document.getElementById('u'),p=document.getElementById('p');
      u.value='admin'; p.value=${JSON.stringify(PW)};
      document.getElementById('login-form').dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}));})()`);
  await sleep(3000);

  const iid = await ev(`fetch('/api/instances',{headers:{Authorization:'Bearer '+localStorage.getItem('mc_token')}})
      .then(r=>r.json()).then(d=>(d.instances&&d.instances[0])?d.instances[0].id:0)`);
  console.log('实例 id=' + iid + '，进入控制台…');
  wsEvents.length = 0;
  await ev(`location.hash='#/instances/${iid}/console'`);
  await sleep(6000);

  const st = await ev(`JSON.stringify({
      hasConsole: !!document.querySelector('.console-box, #c-log, [class*=console]'),
      wsReady: (window.__mcWsState !== undefined) ? window.__mcWsState : null,
      wsOpen: !!(window.__ws && window.__ws.readyState === 1),
      logLines: document.querySelectorAll('.console-box .line, #c-log .line, .log-line').length,
      bodyLen: (document.getElementById('page-body')||document.body).textContent.length
    })`);
  console.log('页面状态: ' + st);

  /* 直接由页面发起一次 WS，抓 close code —— 4401/4403/4404 是后端的鉴权码，
     1006 是握手被拒（服务端异常），能区分"权限拒绝"和"服务端崩了"。 */
  const probe = await ev(`new Promise(function(res){
      var tok = localStorage.getItem('mc_token');
      var url = (location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/api/instances/${iid}/console/ws?token='+encodeURIComponent(tok);
      var w = new WebSocket(url);
      var got = [];
      var done = false;
      function fin(tag, extra){ if(done) return; done=true; res(JSON.stringify({tag:tag, extra:extra||'', frames:got.slice(0,3)})); }
      w.onopen = function(){ got.push('open'); };
      w.onmessage = function(e){ got.push('msg:'+String(e.data).slice(0,80)); if(got.length>2) fin('opened-and-messaged'); };
      w.onerror = function(){ got.push('error'); };
      w.onclose = function(e){ got.push('close:'+e.code); fin('closed', 'code='+e.code+' reason='+(e.reason||'')); };
      setTimeout(function(){ fin('timeout', 'readyState='+w.readyState); }, 5000);
    })`);
  console.log('直连 WS 探测: ' + probe);

  console.log('\nWebSocket 事件:');
  if (wsEvents.length) wsEvents.slice(0, 12).forEach((e) => console.log('  ' + e));
  else console.log('  （没捕到 WS 事件）');

  const failed = wsEvents.some((e) => /500|error|closed/i.test(e));
  console.log('\n结论: ' + (failed ? '❌ WS 仍失败' : '✅ 没有 WS 失败痕迹'));
  ws.close(); edge.kill();
  await sleep(400);
  try { require('fs').rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
