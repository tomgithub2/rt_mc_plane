/* 自动下载 · 全核心回归
   对每个核心：解析直链 → 真下载 → 校验落盘（大小 + jar 结构 + 声明哈希）
   用法：node download-all.js <base> <password> [mcver]
   ========================================================================== */
const fs = require('fs');
const crypto = require('crypto');
const BASE = (process.argv[2] || 'http://127.0.0.1:8100').replace(/\/$/, '');
const PW = process.argv[3] || '';
const MC = process.argv[4] || '1.21.4';
const CORES = ['vanilla', 'paper', 'purpur', 'fabric', 'forge', 'neoforge', 'quilt'];

(async () => {
  const l = await (await fetch(BASE + '/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: PW })
  })).json();
  const H = { Authorization: 'Bearer ' + l.token, 'Content-Type': 'application/json' };
  const cur = await (await fetch(BASE + '/api/instances', { headers: H })).json();
  const used = new Set((cur.instances || []).map((x) => Number(x.port)));
  let port = 25800;

  const results = [];
  for (const core of CORES) {
    port++; while (used.has(port)) port++;
    console.log('\n==== ' + core + ' (' + MC + ') ====');
    const t0 = Date.now();
    const r = await fetch(BASE + '/api/cores/' + core + '/resolve?mc=' + MC, { headers: H });
    const info = await r.json().catch(() => null);
    const rt = ((Date.now() - t0) / 1000).toFixed(1);
    if (r.status !== 200 || !info || !info.ok) {
      console.log('  ❌ 解析失败 HTTP ' + r.status + ' ' + rt + 's  ' + JSON.stringify(info).slice(0, 260));
      results.push({ core, ok: false, why: '解析失败', detail: JSON.stringify(info).slice(0, 200) });
      continue;
    }
    console.log('  ✅ 解析 ' + rt + 's  kind=' + info.kind + '  file=' + info.filename);
    console.log('     sha1=' + (info.sha1 || '').slice(0, 16) + '  url=' + (info.url || '').slice(0, 90));

    const cr = await fetch(BASE + '/api/instances', {
      method: 'POST', headers: H,
      body: JSON.stringify({ name: 'dl-' + core + '-' + Date.now() % 100000, core_type: core,
        mc_version: MC, memory_mb: 1024, port, download: true, accept_eula: true })
    });
    const inst = await cr.json();
    if (!inst.id) {
      console.log('  ❌ 建实例失败 HTTP ' + cr.status + ' ' + JSON.stringify(inst).slice(0, 200));
      results.push({ core, ok: false, why: '建实例失败', detail: JSON.stringify(inst).slice(0, 200) });
      continue;
    }
    const id = inst.id;
    const dl = inst.download || {};
    const started = !!dl.task_id;
    console.log('  实例 #' + id + '  下载启动=' + started + '  file=' + (dl.filename || '(无)'));

    let done = false, state = '';
    if (started) {
      for (let i = 0; i < 60; i++) {
        await new Promise((x) => setTimeout(x, 4000));
        const d = await (await fetch(BASE + '/api/downloads', { headers: H })).json();
        const t = (d.downloads || []).find((x) => x.dest && x.dest.indexOf(id + '_') >= 0);
        if (!t) continue;
        state = t.status;
        if (i % 4 === 0) console.log('     ' + ((i + 1) * 4) + 's ' + t.status + ' ' + t.percent + '% ' +
          Math.round((t.done || 0) / 1048576) + '/' + Math.round((t.total || 0) / 1048576) + 'MB');
        if (t.status === 'done' || t.status === 'failed') {
          done = t.status === 'done';
          if (t.status === 'failed') console.log('     ❌ ' + String(t.error).slice(0, 220));
          break;
        }
      }
    }

    const one = await (await fetch(BASE + '/api/instances/' + id, { headers: H })).json();
    const row = one.instance || {};
    let verdict = { core, ok: false, why: '' };
    if (row.jar_path && fs.existsSync(row.jar_path)) {
      const st = fs.statSync(row.jar_path);
      const buf = fs.readFileSync(row.jar_path);
      const isZip = buf[0] === 0x50 && buf[1] === 0x4b;
      let hashOk = 'n/a';
      if (info.sha1) hashOk = crypto.createHash('sha1').update(buf).digest('hex') === info.sha1 ? 'OK' : 'MISMATCH';
      else if (info.sha256) hashOk = crypto.createHash('sha256').update(buf).digest('hex') === info.sha256 ? 'OK' : 'MISMATCH';
      verdict.ok = done && isZip && hashOk !== 'MISMATCH';
      verdict.why = Math.round(st.size / 1048576) + 'MB zip=' + isZip + ' sha=' + hashOk;
      console.log('  ' + (verdict.ok ? '✅' : '❌') + ' 落盘 ' + verdict.why);
    } else {
      verdict.why = 'jar 未落盘 (state=' + state + ')';
      console.log('  ❌ ' + verdict.why);
    }
    results.push(verdict);

    await fetch(BASE + '/api/instances/' + id + '/kill', { method: 'POST', headers: H, body: '{}' }).catch(() => {});
    await new Promise((x) => setTimeout(x, 1200));
    await fetch(BASE + '/api/instances/' + id, { method: 'DELETE', headers: H });
    await new Promise((x) => setTimeout(x, 800));
    const base = 'D:/DeepSeekHarness/guanwang/mc/backend/data/instances/';
    try { fs.readdirSync(base).filter((f) => f.startsWith(id + '_'))
      .forEach((f) => { try { fs.rmSync(base + f, { recursive: true, force: true }); } catch (e) {} }); } catch (e) {}
  }

  console.log('\n========== 汇总 ==========');
  results.forEach((r) => console.log('  ' + (r.ok ? '✅' : '❌') + ' ' + r.core.padEnd(10) + ' ' + r.why));
  const bad = results.filter((r) => !r.ok);
  console.log('\n  ' + (results.length - bad.length) + '/' + results.length + ' 个核心可正常自动下载');
})().catch((e) => { console.error('FAILED: ' + e.message); process.exit(2); });
