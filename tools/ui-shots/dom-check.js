/* 无头浏览器 DOM 断言（Edge headless + CDP，零第三方依赖）
   ----------------------------------------------------------------------------
   为什么需要它：本机 Edge（--headless=new）在 1080 量级高度的页面上**合成不出内容**
   （shot.js 头部已记录该已知限制：截图只剩背景）。截图证明不了页面是否正确，
   所以前端验收改为**读 DOM**：
     · 页面是否真的渲染出内容（不是白屏、不是 boot 占位）
     · 菜单/按钮是否按权限隐藏（对比超管 / 普通用户 / 只读三种 token）
     · 越权页是否给出设计过的「权限不足」空状态（而不是裸 403 或白屏）
     · 账号管理页是否真的从 /api/users 拿到了 3 个用户并画出角色徽标
     · 全程 console 是否有异常

   用法：node dom-check.js <base_url> <admin_password> [输出json]
   ========================================================================== */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = (process.argv[2] || 'http://127.0.0.1:8123').replace(/\/$/, '');
const ADMIN_PW = process.argv[3] || '';
const OUT = process.argv[4] || '';
const PORT = 9344;
const PROFILE = path.join(os.tmpdir(), 'mcdoms-' + Date.now());
const ROLE_PW = 'ShotRole#2026xx';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
let failures = 0;

function check(cond, label, detail) {
  if (cond) { results.push({ ok: true, label }); console.log('   PASS  ' + label); }
  else {
    failures++;
    results.push({ ok: false, label, detail: detail || '' });
    console.log('   FAIL  ' + label + (detail ? '\n         ' + detail : ''));
  }
  return !!cond;
}

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
  ], { stdio: 'ignore' });

  let targets = null;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/list');
      targets = await r.json();
      if (targets && targets.length) break;
    } catch (e) { /* not up yet */ }
  }
  if (!targets || !targets.length) throw new Error('无法连接 Edge 调试端口');
  const page = targets.find((t) => t.type === 'page') || targets[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  await cdp(ws, 'Page.enable');
  await cdp(ws, 'Runtime.enable');
  await cdp(ws, 'Log.enable');

  const consoleErrors = [];
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === 'Runtime.exceptionThrown') {
      consoleErrors.push('EXC ' + (m.params.exceptionDetails.exception?.description ||
                                   m.params.exceptionDetails.text));
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push('ERR ' + m.params.args.map((a) => a.value || a.description || '').join(' '));
    }
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
      consoleErrors.push('LOG ' + m.params.entry.text);
    }
  });

  async function ev(expr) {
    const r = await cdp(ws, 'Runtime.evaluate',
      { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) {
      throw new Error('eval: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    }
    return r.result && r.result.value;
  }
  async function goto(hash) {
    await cdp(ws, 'Page.navigate', { url: BASE + '/' + hash });
    await sleep(1300);
  }

  /* ---------------------------------------------------------------- 登录拿 token */
  async function login(username, password) {
    const r = await fetch(BASE + '/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const d = await r.json().catch(() => ({}));
    return d.token || '';
  }
  const admin = await login('admin', ADMIN_PW);
  if (!admin) throw new Error('超管登录失败（口令不对？）');

  async function ensureUser(username, role) {
    let t = await login(username, ROLE_PW);
    if (t) return t;
    await fetch(BASE + '/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + admin },
      body: JSON.stringify({ username, password: ROLE_PW, role })
    });
    return await login(username, ROLE_PW);
  }
  const viewer = await ensureUser('shot-viewer', 'viewer');
  const norm = await ensureUser('shot-user', 'user');
  check(!!viewer && !!norm, '三种角色账号的 token 都拿到了（超管/普通用户/只读）');

  /* 设定 token 后必须**丢掉权限缓存**再重新解析路由：
     否则页面会沿用上一个账号的权限快照（这正是本次验收一开始抓到的假阳性来源）。 */
  /* 切换身份用**真实刷新**（等价于用户重新登录/换账号），而不是同页 Router.refresh()：
     后者要依赖路由器内部状态机在"异步权限装载 + hash 变化"之间正确收尾，
     拿它当验收手段会把路由器的一个竞态放大成整组用例失败。
     用户真正的操作路径就是"重新打开页面"，所以按那个路径验。 */
  async function asUser(token, hash, wait) {
    await goto('#/login');          // 先到同源页面，localStorage 才可用
    await ev(`localStorage.setItem('mc_token', ${JSON.stringify(token)});`);
    await cdp(ws, 'Page.navigate', { url: BASE + '/' + hash });
    await sleep(700);
    await cdp(ws, 'Page.reload', { ignoreCache: false });
    await sleep(wait || 2200);
    const st = await ev(`JSON.stringify({hash: location.hash,
        tok: (localStorage.getItem('mc_token')||'').length,
        role: (window.Perm && Perm.role && Perm.role()) || null,
        h1: (document.querySelector('#app h1')||{}).textContent || ''})`);
    console.log('    [state] ' + st);
  }

  /* ============================================================ 1. 真实数据渲染 */
  console.log('\n[1] 账号管理页：真的从 /api/users 拿数据并渲染');
  consoleErrors.length = 0;
  await asUser(admin, '#/accounts', 2200);

  const info = await ev(`(function(){
      var g=function(s){var e=document.querySelector(s);return e?e.textContent.trim():'';};
      var nav=[].map.call(document.querySelectorAll('.nav-item span'),function(e){return e.textContent.trim();});
      return JSON.stringify({
        boot: !!document.querySelector('.boot-splash'),
        h1: g('h1'),
        rows: document.querySelectorAll('#u-list tbody tr').length,
        users: [].map.call(document.querySelectorAll('#u-list tbody tr td:first-child b'),
                          function(e){return e.textContent.trim();}),
        roleBadges: [].map.call(document.querySelectorAll('#u-list tbody tr .badge'),
                            function(e){return e.className.replace('badge','').trim()+'|'+e.textContent.trim();}),
        stats: [].map.call(document.querySelectorAll('#u-stats .stat'),function(e){return e.textContent.trim();}),
        nav: nav,
        roleTop: g('.topbar-right .badge'),
        denied: /权限不足/.test(document.body.textContent)
      });
    })()`);
  const I = JSON.parse(info);
  const probe = await ev(`(function(){
      var app=document.getElementById('app');
      var pr=(window.Router&&Router.current)?Router.current():null;
      return JSON.stringify({
        hasShell: !!app.querySelector('.shell'),
        hasLogin: !!app.querySelector('.login-wrap'),
        pageBody: !!(document.getElementById('page-body')),
        hash: location.hash,
        routePath: pr ? pr.path : null,
        hasAccountsPage: typeof (window.Pages && Pages.accounts),
        hasAccountsNav: !!document.querySelector('[data-nav="#/accounts"]'),
        permRole: (window.Perm && Perm.role && Perm.role()) || null,
        permHasManage: !!(window.Perm && Perm.has && Perm.has('user.manage')),
        appHead: app.innerHTML.slice(0, 120)
      });
    })()`);
  console.log('    [probe] ' + probe);
  if (I.h1 !== '账号管理') {
    const dump = await ev(`JSON.stringify({hash: location.hash,
        body: (document.getElementById('page-body')||{}).textContent,
        appHtml: (document.getElementById('app')||{}).innerHTML.slice(0,400)})`);
    console.log('    诊断: ' + dump);
  }
  check(!I.boot, '页面已脱离 boot 占位（真的渲染了）');
  check(I.h1 === '账号管理', '标题是「账号管理」', '实际: ' + I.h1);
  check(I.rows >= 3, '用户表格画出了 ≥3 行（数据来自后端）', '实际 ' + I.rows + ' 行');
  check(I.users.indexOf('admin') >= 0, '列表里有 admin（后端返回的真实用户）', I.users.join(','));
  check(/role-super/.test(I.roleBadges.join(' ')), '超管行显示 role-super 金色徽标',
        I.roleBadges.join(' | '));
  check(/role-(admin|user|viewer)/.test(I.roleBadges.join(' ')),
        '其它角色徽标也按四色体系渲染', I.roleBadges.join(' | '));
  check(/超级管理员|管理员/.test(I.roleTop), '顶栏角色徽标显示角色中文名', I.roleTop);
  check(I.nav.indexOf('账号管理') >= 0, '超管能看到「账号管理」菜单项', I.nav.join(','));
  check(!I.denied, '超管访问账号管理不会被判越权');

  /* ============================================================ 2. 只读视角 */
  console.log('\n[2] 只读账号：菜单收窄 + 越权页给「权限不足」空状态');
  consoleErrors.length = 0;
  await asUser(viewer, '#/instances', 1800);
  const vInst = await ev(`(function(){
      var nav=[].map.call(document.querySelectorAll('.nav-item span'),function(e){return e.textContent.trim();});
      return JSON.stringify({nav:nav, badge:(document.querySelector('.topbar-right .badge')||{}).textContent||'',
        boot: !!document.querySelector('.boot-splash')});
    })()`);
  const V = JSON.parse(vInst);
  check(!V.boot, '只读视角页面正常渲染');
  check(V.nav.indexOf('账号管理') < 0, '只读看不到「账号管理」菜单（按权限隐藏）', V.nav.join(','));
  check(/只读/.test(V.badge), '顶栏徽标显示「只读」', V.badge);

  await asUser(viewer, '#/accounts', 2000);
  const vDeny = await ev(`(function(){
      var t=document.body.textContent;
      return JSON.stringify({denied:/权限不足/.test(t), hasPerm:/缺少权限/.test(t),
        userManage:/user\\.manage/.test(t),
        hasBack:/返回实例列表/.test(t),
        rows: document.querySelectorAll('#u-list tbody tr').length,
        boot: !!document.querySelector('.boot-splash')});
    })()`);
  const D = JSON.parse(vDeny);
  check(!D.boot, '越权页不是白屏 / 不是 boot 占位');
  check(D.denied && D.hasPerm, '越权页给出「权限不足」空状态');
  check(D.userManage, '空状态里写明缺少哪个权限点（user.manage）');
  check(D.hasBack, '空状态里有「返回实例列表」的行动按钮');
  check(D.rows === 0, '越权时不渲染用户表格（没有把数据漏给只读）', '行数 ' + D.rows);

  /* ============================================================ 3. 普通用户视角 */
  console.log('\n[3] 普通用户：看不到审计/账号管理，但能进实例页');
  await asUser(norm, '#/instances', 1800);
  const nInst = await ev(`(function(){
      var nav=[].map.call(document.querySelectorAll('.nav-item span'),function(e){return e.textContent.trim();});
      return JSON.stringify({nav:nav, badge:(document.querySelector('.topbar-right .badge')||{}).textContent||'',
        boot: !!document.querySelector('.boot-splash'), h1:(document.querySelector('h1')||{}).textContent||''});
    })()`);
  const N = JSON.parse(nInst);
  check(!N.boot, '普通用户视角页面正常渲染');
  check(N.nav.indexOf('账号管理') < 0, '普通用户看不到「账号管理」', N.nav.join(','));
  check(/普通用户/.test(N.badge), '顶栏徽标显示「普通用户」', N.badge);

  /* ============================================================ 4. 前端没有假数据 */
  console.log('\n[4] 假数据层已彻底移除（改了假数据以为生效是最危险的）');
  const globals = await ev(`JSON.stringify({
      MockAccounts: typeof window.MockAccounts,
      Perm: typeof window.Perm,
      hasPermLoad: !!(window.Perm && typeof Perm.load === 'function'),
      hasRoleMeta: !!(window.Perm && typeof Perm.roleMeta === 'function')
    })`);
  const G = JSON.parse(globals);
  check(G.MockAccounts === 'undefined', 'window.MockAccounts 已不存在（假用户列表已删除）',
        '实际: ' + G.MockAccounts);
  check(G.Perm === 'object' && G.hasPermLoad && G.hasRoleMeta,
        'window.Perm 存在且是真实实现（load/roleMeta）');

  /* ============================================================ 5. console 干净 */
  console.log('\n[5] 全程 console 无异常');
  const real = consoleErrors.filter((e) => !/favicon/.test(e));
  check(real.length === 0, '本轮所有页面 console 无 JS 异常 / 无 4xx 资源错误',
        real.slice(0, 6).join('\n         '));

  console.log('\n============================================================');
  const passed = results.filter((r) => r.ok).length;
  console.log(`  DOM 断言：通过 ${passed} 项，失败 ${failures} 项`);
  if (failures) {
    console.log('  失败明细：');
    results.filter((r) => !r.ok).forEach((r) => console.log('   - ' + r.label + ' :: ' + r.detail));
  } else {
    console.log('  ✅ 前端权限体系与真实接口联通全部通过');
  }

  if (OUT) {
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    fs.writeFileSync(OUT, JSON.stringify({ base: BASE, results: results,
                                           console_errors: real }, null, 2));
  }

  ws.close();
  edge.kill();
  await sleep(500);
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
  process.exit(failures ? 1 : 0);
}

main().catch(async (e) => {
  console.error('FAILED: ' + e.message);
  process.exit(2);
});
