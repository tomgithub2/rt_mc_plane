/* 无头浏览器逐页截图（Edge headless + CDP，无第三方依赖）
   用法： node shot.js <初始口令> [输出目录]
   产出： docs/ui-review/*.png  +  shots.json（含每页 console 错误）
*/
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
/* 面板地址可用 MC_SHOT_BASE 覆盖（默认 8100）。
   用独立实例截图的原因：共享的 8100 实例带 600 req/min 限流，连轴截 30+ 个页面会撞 429，
   而且该限流桶在服务端长时间不释放（核心侧问题），会一直卡住整个截图流程。 */
const BASE = process.env.MC_SHOT_BASE || 'http://127.0.0.1:8100';
const PORT = 9333;
const OUT = process.argv[3] || path.resolve(__dirname, '..', '..', 'docs', 'ui-review');
const PWD = process.argv[2] || '';
const PROFILE = path.join(os.tmpdir(), 'mcshot-' + Date.now());

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
    setTimeout(() => reject(new Error('timeout ' + method)), 45000);
  });
}

async function main() {
  const edge = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--hide-scrollbars', '--force-device-scale-factor=1', '--mute-audio',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + PROFILE, 'about:blank'
  ], { stdio: 'ignore', detached: false });

  let targets = null;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      targets = await r.json();
      if (targets && targets.length) break;
    } catch (e) { /* 还没起来 */ }
  }
  if (!targets || !targets.length) throw new Error('无法连接 Edge 调试端口');
  const page = targets.find((t) => t.type === 'page') || targets[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  await cdp(ws, 'Page.enable');
  await cdp(ws, 'Runtime.enable');
  await cdp(ws, 'Log.enable');
  await cdp(ws, 'Network.enable');

  const consoleErrors = [];
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === 'Runtime.exceptionThrown') {
      consoleErrors.push('EXC ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push('ERR ' + m.params.args.map((a) => a.value || a.description || '').join(' '));
    }
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
      consoleErrors.push('LOG ' + m.params.entry.text + ' @ ' + (m.params.entry.url || ''));
    }
  });

  async function goto(url) {
    await cdp(ws, 'Page.navigate', { url });
    await sleep(1400);
  }
  async function evalJs(expr) {
    const r = await cdp(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    return r.result && r.result.value;
  }
  /* 先按目标视口渲染并等待稳定，再截整页。
     注意：不能在渲染前就把 viewport 高度设成整页高度 —— 那会让响应式断点按畸形尺寸命中，
     侧栏被隐藏、卡片塌成单列（第一轮截图就是这么坏掉的）。 */
  let VIEW = { w: 1920, h: 1080 };
  async function setView(w, h) {
    VIEW = { w: w, h: h };
    await cdp(ws, 'Emulation.setDeviceMetricsOverride',
      { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  }
  /* ---------------------------------------------------------------- 截图实现（含已知限制）
     本机 Edge（--headless=new）有一个渲染/合成怪癖，已实测确认：
       · 正常文档流里的静态内容在某些尺寸下完全不参与合成，截图只剩背景；
       · 把内容改为绝对定位后即可正常合成（实测非背景像素 0.35% → 91%）；
       · 裁切高度**恰好等于**视口高度的页面（如 1920×1080 的短页面）会输出纯背景空图，
         而更高的页面（如 1920×1616）正常。
     SHOT_CSS 把壳层三块提升为绝对定位，并先放大视口再裁切，可让**大多数**页面正常出图。
     ⚠️ 已知未解决：视口高度与页面高度同为 1080 量级的短页面（实例列表、控制台、
        设置-常规、向导步骤、亮色/彩色变体的实例列表）仍会截成空图。
         这是无头合成问题，不是页面自身问题 —— 可用真实浏览器打开
         http://127.0.0.1:8100/ 复核这些页面。已出图的页面见 docs/DESIGN.md 截图索引。 */
  const SHOT_CSS = `#app{position:relative !important;}` +
    `.shell{position:static !important;display:block !important;min-height:0 !important}` +
    `.sidebar{position:absolute !important;left:0 !important;top:0 !important;
              height:var(--shot-h,1080px) !important;overflow:hidden !important}` +
    `.main{position:absolute !important;left:0 !important;top:0 !important;
           width:100% !important;padding-left:var(--sidebar-w) !important;
           display:block !important}` +
    `.topbar{position:static !important}` +
    `.console-box{height:620px !important}` +
    `body{height:auto !important}`;

  async function shot(name) {
    await sleep(800);
    await evalJs(`(function(){
        var old=document.getElementById('__mcshot'); if(old) old.remove();
        var st=document.createElement('style'); st.id='__mcshot';
        st.textContent=${JSON.stringify(SHOT_CSS)};
        document.head.appendChild(st);
        window.scrollTo(0,0);
        return true; })()`);
    await sleep(420);
    /* 先量出内容真实高度，再据此设定侧栏高度与裁切高度 */
    const met = await evalJs(`(function(){
        var sh=document.querySelector('.shell'), mn=document.querySelector('.main');
        var h=Math.ceil(Math.max(sh?sh.scrollHeight:0, mn?mn.scrollHeight:0,
                                 document.documentElement.scrollHeight));
        h=Math.max(h, 400); h=Math.min(h, 4200);
        document.documentElement.style.setProperty('--shot-h', h+'px');
        var sb=document.querySelector('.sidebar');
        if(sb) sb.style.height=h+'px';
        return JSON.stringify({w: Math.min(Math.ceil(window.innerWidth), 2560), h: h});
      })()`);
    const M = JSON.parse(met || '{"w":1920,"h":1080}');
    /* 关键：裁切高度等于视口高度时，这台 Edge 会输出"纯背景"空图（内容不参与合成）。
       因此先把视口高度放大到明显超过裁切高度，再做裁切截图；截完恢复视口。 */
    const bigH = Math.min(Math.max(M.h + 420, 1500), 4600);
    await cdp(ws, 'Emulation.setDeviceMetricsOverride',
      { width: VIEW.w, height: bigH, deviceScaleFactor: 1, mobile: false });
    await sleep(620);
    const r = await cdp(ws, 'Page.captureScreenshot',
      { format: 'png', clip: { x: 0, y: 0, width: M.w, height: M.h, scale: 1 },
        captureBeyondViewport: true, fromSurface: true });
    fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(r.data, 'base64'));
    await cdp(ws, 'Emulation.setDeviceMetricsOverride',
      { width: VIEW.w, height: VIEW.h, deviceScaleFactor: 1, mobile: false });
    await evalJs("(function(){var s=document.getElementById('__mcshot'); if(s) s.remove();" +
                 "document.documentElement.style.removeProperty('--shot-h');})()");
    console.log('  shot ' + name + '.png   [' + M.w + '×' + M.h + '，视口临时 ' + bigH + ']');
  }

  fs.mkdirSync(OUT, { recursive: true });

  // 拿一个令牌（登录接口）
  const lr = await fetch(BASE + '/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: PWD })
  });
  const login = await lr.json();
  if (!login.token) throw new Error('登录失败：' + JSON.stringify(login).slice(0, 200));
  console.log('登录 OK，开始截图');

  const token = login.token;
  const results = [];

  /* 角色视角截图需要**真实账号的 token**。
     早期版本用 MockAccounts.setMe('viewer') 在浏览器里假装切角色 —— 那层 mock 已删除
     （账号页改成对接真实 /api/users 了），所以这里改成真的在后端建账号、真的登录拿 token，
     再把该 token 注入 localStorage。这样截到的权限态就是后端真实算出来的，
     而不是前端演出来的。 */
  async function tokenFor(username, password, role) {
    try {
      let r = await fetch(BASE + '/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      if (r.status === 401) {
        await fetch(BASE + '/api/users', {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
          body: JSON.stringify({ username, password, role })
        });
        r = await fetch(BASE + '/api/auth/login', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
      }
      const d = await r.json();
      if (d && d.token) { console.log('  角色账号 ' + username + ' (' + role + ') 已就绪'); return d.token; }
    } catch (e) { /* 失败则该组截图退回超管视角，并在汇总里可见 */ }
    console.log('  [!] 角色账号 ' + username + ' 不可用，该组截图将使用超管视角');
    return token;
  }
  const PW_ROLE = 'ShotRole#2026xx';
  const tokViewer = await tokenFor('shot-viewer', PW_ROLE, 'viewer');
  const tokUser = await tokenFor('shot-user', PW_ROLE, 'user');

  /* 面板对 /api/** 有 600 req/min 限流；连轴截 30+ 个页面时偶发 429。
     这里做指数退避重试，而不是去改服务端限流参数。
     另：演示实例可以预建好并用 --iid 传入，避免截图过程里还要走一次写接口。 */
  async function fetchRetry(url, opts, label) {
    opts = opts || {};
    let wait = 2500;
    for (let i = 0; i < 6; i++) {
      const r = await fetch(url, opts);
      if (r.status !== 429) return r;
      console.log('    [429] ' + (label || url) + ' 限流，等待 ' + Math.round(wait / 1000) + 's 后重试…');
      await sleep(wait);
      wait = Math.min(wait * 2, 60000);
    }
    return fetch(url, opts);
  }

  async function capturePage(name, hash, opts) {
    opts = opts || {};
    const useTok = opts.token || token;
    consoleErrors.length = 0;
    await goto(BASE + '/' + hash);
    await evalJs(`localStorage.setItem('mc_token', ${JSON.stringify(useTok)});`);
    if (opts.setup) await evalJs(opts.setup);
    await goto(BASE + '/' + hash);
    /* 换 token 后必须重新解析路由，否则页面还用着上一个账号的权限快照 */
    if (opts.token) await evalJs('Router.refresh();');
    await sleep(opts.wait || 1600);
    if (opts.after) await evalJs(opts.after);
    await sleep(700);
    await shot(name);
    results.push({ name: name, hash: hash, errors: consoleErrors.slice(0, 10) });
  }

  // 登录页（清掉令牌）
  await goto(BASE + '/#/login');
  await evalJs("localStorage.removeItem('mc_token'); sessionStorage.clear();");
  await goto(BASE + '/#/login');
  await sleep(1200);
  consoleErrors.length = 0;
  await setView(1920, 1080);
  await shot('01-login');
  results.push({ name: '01-login', hash: '#/login', errors: consoleErrors.slice(0, 10) });

  await capturePage('02-instances', '#/instances');
  await capturePage('03-create-step1', '#/create');
  await capturePage('04-create-step5', '#/create', {
    wait: 2600,
    after: "document.querySelectorAll('#w-next').forEach(function(b){for(var i=0;i<4;i++)b.click();});"
  });
  await capturePage('05-settings-general', '#/settings');
  await capturePage('06-settings-theme', '#/settings', { after: "document.querySelector('[data-t=theme]')&&document.querySelector('[data-t=theme]').click();" });
  await capturePage('07-audit', '#/audit');

  // 实例详情各 Tab：先建（或复用）一个演示实例
  const auth = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token };
  const wantIid = process.env.MC_SHOT_IID || '';
  const rawList = await fetchRetry(BASE + '/api/instances', { headers: auth }, 'list instances');
  const listText = await rawList.text();
  console.log('    [diag] GET /api/instances -> HTTP ' + rawList.status + ' body=' + listText.slice(0, 160));
  let listRes = {};
  try { listRes = JSON.parse(listText); } catch (e) { listRes = {}; }
  let demo = wantIid
    ? (listRes.instances || []).find((i) => String(i.id) === String(wantIid))
    : (listRes.instances || []).find((i) => i.name === 'ui-review-demo');
  if (!demo && (listRes.instances || []).length) {
    // 指定 id 未命中时退化为复用任意一个已存在实例 —— 截图只需要"有一个实例"，
    // 不值得为了建实例去撞限流，更不该因此让整轮截图失败。
    demo = (listRes.instances || [])[0];
    console.log('    未命中指定实例，复用已有实例 #' + demo.id + '（' + demo.name + '）');
  }
  if (!demo) {
    const cr = await fetchRetry(BASE + '/api/instances', {
      method: 'POST', headers: auth,
      body: JSON.stringify({ name: 'ui-review-demo', core_type: 'paper', mc_version: '1.21.4',
                             memory_mb: 4096, port: 25871, download: false, accept_eula: true })
    });
    const created = await cr.json();
    if (!created.id) throw new Error('创建演示实例失败：' + JSON.stringify(created).slice(0, 300));
    demo = created.instance || { id: created.id };
  }
  const iid = demo.id;
  console.log('演示实例 id=' + iid + ' status=' + demo.status);

  const tabs = ['console', 'files', 'config', 'players', 'build', 'backups', 'cron', 'settings'];
  for (let i = 0; i < tabs.length; i++) {
    const t = tabs[i];
    await capturePage(String(10 + i).padStart(2, '0') + '-detail-' + t, '#/instances/' + iid + '/' + t,
      { wait: 2400 });
  }

  /* 建筑 Tab 专项：空状态 → 上传+预检后 → 任务进行中。
     用 mock 数据直接驱动 PagesBuild 所依赖的 MockBuild，保证截到的是"有内容"的状态。 */
  const BUILD = '#/instances/' + iid + '/build';
  await capturePage('17-build-empty', BUILD, { wait: 2000 });

  await capturePage('18-build-preview', BUILD, {
    wait: 2400,
    after: `(function(){
        var up = MockBuild.upload('castle_1.21.schem', 2482176, '9f2c1d4e7a3b50816c9d0e4f2a7b3c5d8e6f1a2b3c4d5e6f708192a3b4c5d6e7');
        window.__mcBuildUp = up;
        var pv = document.getElementById('b-preview');
        if (pv) pv.click();
      })()`
  });

  await capturePage('19-build-task', BUILD, {
    wait: 2600,
    after: `(function(){
        var up = MockBuild.upload('castle_1.21.schem', 2482176, '9f2c1d4e7a3b50816c9d0e4f2a7b3c5d8e6f1a2b3c4d5e6f708192a3b4c5d6e7');
        var pv = document.getElementById('b-preview'); if (pv) pv.click();
        setTimeout(function(){
          var im = document.getElementById('b-import'); if (im) im.click();
        }, 700);
      })()`
  });

  // 建筑 Tab 的亮色与窄屏
  await capturePage('26-build-light', BUILD, {
    setup: "document.documentElement.setAttribute('data-theme','lightgold');",
    after: "(function(){document.documentElement.setAttribute('data-theme','lightgold');" +
           "var up=MockBuild.upload('tower.schem',812544,'aa11bb22cc33dd44ee55ff6600112233445566778899aabbccddeeff0011223344');" +
           "var pv=document.getElementById('b-preview'); if(pv) pv.click();})()"
  });

  /* ============================ 账号与权限 ============================ */
  // 登录页（含首次运行引导「默认账号是超级管理员」与锁定倒计时占位）
  await capturePage('40-login-firstrun', '#/login', { wait: 1600 });
  // 账号管理页：暗色
  await capturePage('41-accounts-dark', '#/accounts', { wait: 2200 });
  // 账号管理页：亮色纸面
  await capturePage('42-accounts-light', '#/accounts', {
    setup: "document.documentElement.setAttribute('data-theme','lightgold');",
    after: "document.documentElement.setAttribute('data-theme','lightgold');"
  });
  // 重置口令一次性回显弹窗（含复制按钮）
  await capturePage('43-accounts-reset-once', '#/accounts', {
    wait: 2200,
    after: "(function(){var b=document.querySelector('[data-pw]'); if(b) b.click();" +
           "setTimeout(function(){var ok=document.querySelector('#mc-modal [data-ok]'); if(ok) ok.click();},200);})()"
  });
  // 新建用户弹窗（角色 + 配额）
  await capturePage('44-accounts-new-user', '#/accounts', {
    wait: 2200,
    after: "(function(){var b=document.getElementById('u-new'); if(b) b.click();})()"
  });
  // 四种角色徽标：只读视角（顶栏徽标 + 菜单按权限收窄）
  await capturePage('45-role-viewer', '#/instances', { token: tokViewer });
  // 普通用户视角
  await capturePage('46-role-user', '#/instances', { token: tokUser });
  // 权限不足空状态（只读角色直接访问账号管理）
  await capturePage('47-perm-denied', '#/accounts', {
    token: tokViewer,
    wait: 2000,
    after: "(function(){Router.refresh();})()"
  });
  // 恢复超管视角，供后续变体截图使用
  await capturePage('48-role-super-admin', '#/instances', { token: token });

  // 亮色纸面主题各一张
  await capturePage('20-light-instances', '#/instances', {
    setup: "document.documentElement.setAttribute('data-theme','lightgold');",
    after: "document.documentElement.setAttribute('data-theme','lightgold');"
  });
  await capturePage('21-light-detail', '#/instances/' + iid + '/settings', {
    setup: "document.documentElement.setAttribute('data-theme','lightgold');",
    after: "document.documentElement.setAttribute('data-theme','lightgold');"
  });
  // 紧凑密度 + 活力橙变体
  await capturePage('22-variant-orange-compact', '#/instances', {
    setup: "document.documentElement.setAttribute('data-theme','orange');document.documentElement.setAttribute('data-density','compact');",
    after: "document.documentElement.setAttribute('data-theme','orange');document.documentElement.setAttribute('data-density','compact');"
  });
  await capturePage('23-variant-blue', '#/instances', {
    setup: "document.documentElement.setAttribute('data-theme','blue');",
    after: "document.documentElement.setAttribute('data-theme','blue');"
  });
  await capturePage('24-variant-violet', '#/instances', {
    setup: "document.documentElement.setAttribute('data-theme','violet');",
    after: "document.documentElement.setAttribute('data-theme','violet');"
  });
  await capturePage('25-variant-mint', '#/instances', {
    setup: "document.documentElement.setAttribute('data-theme','mint');",
    after: "document.documentElement.setAttribute('data-theme','mint');"
  });
  // 窄屏（响应式）
  await setView(900, 1000);
  await capturePage('30-narrow-1024', '#/instances');
  await capturePage('31-build-narrow', BUILD, {
    after: "(function(){var up=MockBuild.upload('hut.schem',204800,'bb11cc22dd33ee44ff5500112233445566778899aabbccddeeff00112233aabb');" +
           "var pv=document.getElementById('b-preview'); if(pv) pv.click();})()"
  });
  await capturePage('32-accounts-narrow', '#/accounts', { wait: 1800 });
  await capturePage('33-perm-denied-narrow', '#/accounts', {
    token: tokViewer, wait: 1800, after: "(function(){Router.refresh();})()"
  });
  await setView(1920, 1080);

  // 清理演示实例（保留）—— 不删，方便人工复核；如需清理请手动删
  fs.writeFileSync(path.join(OUT, 'shots.json'),
    JSON.stringify({ generated_at: new Date().toISOString(), demo_instance_id: iid, shots: results }, null, 2));

  console.log('\n=== 每页 console 错误汇总 ===');
  let bad = 0;
  results.forEach((r) => {
    if (r.errors.length) { bad++; console.log('  ' + r.name + ': ' + r.errors.join(' | ')); }
  });
  if (!bad) console.log('  全部页面无 console 错误 ✓');

  ws.close();
  edge.kill();
  await sleep(600);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
  process.exit(0);
}

main().catch(async (e) => {
  console.error('FAILED: ' + e.message);
  process.exit(1);
});
