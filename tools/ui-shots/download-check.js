/* 自动下载专项验收：版本列表 → 建实例(带下载) → 看任务进度 → 校验落盘 jar
   用法：node download-check.js <base> <password> [core] [mcver]
   ========================================================================== */
const fs = require('fs');
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const CORE = process.argv[4] || 'paper';
const MC = process.argv[5] || '1.21.4';

async function main() {
  const login = await (await fetch(BASE + '/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: PW })
  })).json();
  const H = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + login.token };
  const get = async (p) => { const r = await fetch(BASE + p, { headers: H }); return { s: r.status, d: await r.json().catch(() => null) }; };

  console.log('==== 1) 源列表（面板支持哪些核心） ====');
  const src = await get('/api/sources');
  if (src.s === 200) {
    const list = src.d.sources || src.d || [];
    (Array.isArray(list) ? list : Object.keys(list)).slice(0, 12).forEach((x) => {
      const o = typeof x === 'string' ? { key: x } : x;
      console.log('   ' + (o.key || o.id || '?') + '  ' + (o.label || '') + (o.ok === false ? '  ⚠️ 不可用' : ''));
    });
  } else console.log('   /api/sources -> HTTP ' + src.s + ' ' + JSON.stringify(src.d).slice(0, 200));

  console.log('\n==== 2) 版本列表（' + CORE + '） ====');
  const vs = await get('/api/sources/' + CORE + '/versions');
  if (vs.s === 200) {
    const arr = vs.d.versions || [];
    console.log('   共 ' + arr.length + ' 个版本，最新几个: ' + arr.slice(-6).join(', '));
    console.log('   via=' + (vs.d.via || '') + '  mirror_used=' + vs.d.mirror_used);
  } else {
    console.log('   ❌ HTTP ' + vs.s);
    console.log('   ' + JSON.stringify(vs.d).slice(0, 600));
  }

  console.log('\n==== 3) 该版本的构建/下载直链（' + CORE + ' ' + MC + '） ====');
  const dl = await get(`/api/sources/${CORE}/resolve?mc_version=${MC}`);
  console.log('   HTTP ' + dl.s);
  console.log('   ' + JSON.stringify(dl.d).slice(0, 700));

  console.log('\n==== 4) 建实例并触发自动下载 ====');
  const port = 25640 + Math.floor(Math.random() * 20);
  const cr = await fetch(BASE + '/api/instances', {
    method: 'POST', headers: H,
    body: JSON.stringify({ name: 'dl-test-' + Date.now() % 100000, core_type: CORE, mc_version: MC,
                           memory_mb: 1024, port, download: true, accept_eula: true })
  });
  const inst = await cr.json();
  console.log('   HTTP ' + cr.status + '  ' + JSON.stringify(inst).slice(0, 500));
  const iid = inst.id;
  if (!iid) { console.log('   ❌ 没建出实例，后续跳过'); return; }

  if (inst.download) {
    console.log('\n   create 返回的 download 字段: ' + JSON.stringify(inst.download).slice(0, 400));
  }

  console.log('\n==== 5) 轮询下载进度（60 秒） ====');
  let last = '';
  for (let i = 1; i <= 30; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const d = await get('/api/instances/' + iid + '/download');
    const t = JSON.stringify(d.d).slice(0, 260);
    if (t !== last) { console.log(`   ${i * 2}s: HTTP ${d.s}  ${t}`); last = t; }
    else if (i % 5 === 0) console.log(`   ${i * 2}s: (无变化) ${t}`);
    const st = d.d && d.d.state;
    if (st === 'done' || st === 'failed') break;
  }

  console.log('\n==== 6) 落盘校验 ====');
  const one = await get('/api/instances/' + iid);
  const row = one.d.instance || {};
  console.log('   jar_path = ' + row.jar_path);
  console.log('   目录存在? ' + (row.dir ? fs.existsSync(row.dir) : false));
  if (row.dir && fs.existsSync(row.dir)) {
    const files = fs.readdirSync(row.dir).map((f) => {
      const s = fs.statSync(row.dir + '/' + f);
      return f + ' (' + (s.isDirectory() ? 'dir' : Math.round(s.size / 1024) + 'KB') + ')';
    });
    console.log('   目录内容: ' + (files.join(', ') || '(空)'));
  }
  if (row.jar_path) {
    const ok = fs.existsSync(row.jar_path);
    console.log('   jar 存在? ' + ok + (ok ? '  ' + Math.round(fs.statSync(row.jar_path).size / 1048576) + ' MB' : ''));
    if (ok) {
      const b = fs.readFileSync(row.jar_path).slice(0, 4);
      console.log('   文件头: ' + b.toString('hex') + (b[0] === 0x50 && b[1] === 0x4b ? '  (PK = 合法 zip/jar)' : '  ⚠️ 不是 zip 头'));
    }
  }

  console.log('\n==== 7) 下载中启动实例（竞态检查：应给明确错误而不是"jar 不存在"） ====');
  const st2 = await fetch(BASE + '/api/instances/' + iid + '/start', { method: 'POST', headers: H, body: '{}' });
  console.log('   start -> HTTP ' + st2.status + '  ' + (await st2.text()).slice(0, 300));

  console.log('\n==== 8) 清理 ====');
  const del = await fetch(BASE + '/api/instances/' + iid, { method: 'DELETE', headers: H });
  console.log('   DELETE -> HTTP ' + del.status);
  if (row.dir && fs.existsSync(row.dir)) { try { fs.rmSync(row.dir, { recursive: true, force: true }); console.log('   目录已清理'); } catch (e) {} }
}
main().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
