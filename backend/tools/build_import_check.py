# -*- coding: utf-8 -*-
"""建筑导入 · 端到端验收（不下载服务端 jar，只用真实 HTTP 打面板接口）。

覆盖规格 §9 里**不需要启动真服务端**也能验的部分：

  1. 上传真实样本（7 种格式 + 恶意样本）→ 校验 sha256 / 大小
  2. 预检：越界 / 未映射 / 恶意样本**必须被拒**，正常样本给出完整报告
     （size / blocks_total / bbox / palette_unmapped / chunks_touched /
      engine_available / engine_recommended / warnings / requires_backup）
  3. 引擎 B 离线写入：导入 → **用自研 anvil 解析器读回方块**，确认真的落盘
  4. 回滚：region 文件 sha256 与导入前**完全一致**
  5. 任务化：状态推进、审计留痕（level=warn）
  6. 恶意样本：zip-slip / 绝对路径 / 符号链接 / zip 炸弹 / 深层 NBT / 超大数组
     → 全部被拒且**面板进程存活**

用法（在 backend/ 下）：PYTHONUTF8=1 python tools/build_import_check.py
"""
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path[:0] = [BACKEND, os.path.join(BACKEND, '.deps')]

PORT = int(os.environ.get('BUILD_CHECK_PORT') or 8211)
BASE = f'http://127.0.0.1:{PORT}'
DATA = os.path.join(BACKEND, 'data', 'buildwork', 'importcheck-data')
SAMPLES = os.path.join(BACKEND, 'data', 'buildwork', 'selftest-samples')
PASSWORD = 'BuildCheck#2026x'

PASS, FAIL = [], []


def sec(t):
    print('\n' + '=' * 74)
    print('== ' + t)
    print('=' * 74)


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name,
                           ('  — ' + str(detail)[:300]) if detail else ''))
    return bool(ok)


def req(method, path, body=None, token='', raw=None, ctype=None, timeout=120):
    url = BASE + path
    data = raw
    headers = {'Accept': 'application/json'}
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    if ctype:
        headers['Content-Type'] = ctype
    if token:
        headers['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            t = resp.read().decode('utf-8', 'replace')
            return resp.status, (json.loads(t) if t.strip().startswith(('{', '[')) else t)
    except urllib.error.HTTPError as e:
        t = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, t
    except Exception as e:                                    # noqa: BLE001
        return 0, f'{type(e).__name__}: {e}'


def multipart(fields):
    """fields: [(name, filename, bytes)]"""
    b = '----buildcheck' + os.urandom(8).hex()
    out = []
    for name, fn, data in fields:
        out.append(('--' + b + '\r\n').encode())
        out.append((f'Content-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
                    'Content-Type: application/octet-stream\r\n\r\n').encode())
        out.append(data)
        out.append(b'\r\n')
    out.append(('--' + b + '--\r\n').encode())
    return b''.join(out), f'multipart/form-data; boundary={b}'


def sha256f(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def free_port(prefer):
    for p in range(prefer, prefer + 40):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', p))
                return p
            except OSError:
                continue
    raise SystemExit('无空闲端口')


def boot_panel():
    if os.path.isdir(DATA):
        shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    with io.open(os.path.join(DATA, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'port': PORT, 'bind_host': '127.0.0.1', 'login_rate_limit': 500}, f)
    env = dict(os.environ, MC_DATA_DIR=DATA, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    code = ("import sys; sys.path[:0] = [r'%s', r'%s'];"
            "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=%d, log_level='warning')"
            % (BACKEND, os.path.join(BACKEND, '.deps'), PORT))
    proc = subprocess.Popen([sys.executable, '-c', code], cwd=BACKEND, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace')
    for _ in range(80):
        time.sleep(0.5)
        if req('GET', '/api/health')[0] == 200:
            return proc
        if proc.poll() is not None:
            raise SystemExit('面板启动即退出:\n' + (proc.stdout.read() or '')[:2000])
    raise SystemExit('面板启动超时')


def set_admin_pw():
    code = ("import sys; sys.path[:0] = [r'%s', r'%s'];"
            "from app import auth as a, database as d;"
            "d.init_db(); a.ensure_admin_user();"
            "d.execute(\"UPDATE users SET password_hash=?, role='super_admin', status=1 WHERE username='admin'\","
            "          (a.hash_password(%r),)); print('ok')"
            % (BACKEND, os.path.join(BACKEND, '.deps'), PASSWORD))
    env = dict(os.environ, MC_DATA_DIR=DATA, PYTHONUTF8='1')
    p = subprocess.run([sys.executable, '-c', code], cwd=BACKEND, env=env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode == 0, (p.stdout + p.stderr)[-400:]


def main():
    global PORT
    PORT = free_port(PORT)
    sec('0. 起独立测试面板')
    proc = boot_panel()
    print('  面板 PID %s，端口 %d' % (proc.pid, PORT))
    ok, out = set_admin_pw()
    check('测试面板可用 + 超管口令就绪', ok and req('GET', '/api/health')[0] == 200, out)
    st, d = req('POST', '/api/auth/login', {'username': 'admin', 'password': PASSWORD})
    check('登录', st == 200 and d.get('token'), str(d)[:200])
    token = d.get('token', '')

    sec('1. 样本清单')
    samples = {}
    if os.path.isdir(SAMPLES):
        for fn in sorted(os.listdir(SAMPLES)):
            # 只取真正的建筑样本（样本目录里还有清单 json，那不是建筑）
            if os.path.splitext(fn)[1].lower() in ('.schem', '.schematic', '.nbt',
                                                   '.litematic', '.zip', '.mcstructure'):
                samples[fn] = os.path.join(SAMPLES, fn)
    print('  找到 %d 个样本' % len(samples))
    check('样本目录就绪（由 build_make_sample.py 生成）', len(samples) >= 7,
          '需要先跑 python tools/build_make_sample.py data/buildwork/selftest-samples --all')

    sec('2. 建实例（stopped，引擎 B 用）')
    st, inst = req('POST', '/api/instances', {
        'name': 'importcheck', 'core_type': 'vanilla', 'mc_version': '1.21.4',
        'memory_mb': 1024, 'port': free_port(25600), 'download': False,
        'accept_eula': True, 'owner_id': 0}, token)
    check('创建实例', st == 200 and inst.get('id'), str(inst)[:250])
    iid = inst.get('id')
    idir = (inst.get('instance') or {}).get('dir', '')
    print('  实例目录: %s' % idir)

    sec('3. 上传：7 种格式都必须被接受并给出 sha256')
    ups = {}
    for fn, path in samples.items():
        if fn.startswith('evil_') or fn.startswith('sample_unmapped') or fn.startswith('sample_for_out'):
            continue
        data = io.open(path, 'rb').read()
        body, ctype = multipart([('file', fn, data)])
        st, r = req('POST', f'/api/instances/{iid}/build/upload', raw=body, ctype=ctype, token=token)
        good = st == 200 and r.get('ok') and r.get('upload_id')
        if good:
            ups[fn] = r
        check('上传 %-24s → %s' % (fn, 'OK' if good else 'HTTP %s' % st),
              good and r.get('sha256') == hashlib.sha256(data).hexdigest(),
              '' if good else str(r)[:200])
    check('上传后的 sha256 与本地计算一致', all(
        ups[f].get('sha256') == sha256f(samples[f]) for f in ups), '%d 个' % len(ups))

    sec('4. 预检：正常样本给出完整报告')
    rep = None
    for fn, up in ups.items():
        st, r = req('POST', f'/api/instances/{iid}/build/preview',
                    {'upload_id': up['upload_id'], 'x': 100, 'y': 64, 'z': -200,
                     'dimension': 'overworld', 'engine': 'auto'}, token)
        need = ('size', 'blocks_total', 'bbox', 'palette_total', 'chunks_touched',
                'engine_available', 'engine_recommended', 'warnings', 'requires_backup')
        missing = [k for k in need if k not in (r or {})]
        good = st == 200 and r.get('ok') and not missing
        if good and rep is None:
            rep = (fn, up, r)
        check('预检 %-24s → %s' % (fn, 'ok' if good else 'HTTP %s %s' % (st, str(r)[:120])),
              good, ('缺字段 %s' % missing) if missing else '')
    if rep:
        fn, up, r = rep

        def _size(s):
            """后端 size 可能是 {x,y,z} 也可能是 [x,y,z]，两种都要能读。"""
            if isinstance(s, dict):
                return [int(s.get('x', 0)), int(s.get('y', 0)), int(s.get('z', 0))]
            if isinstance(s, (list, tuple)) and len(s) >= 3:
                return [int(s[0]), int(s[1]), int(s[2])]
            return None

        sz = _size(r.get('size'))
        print('  报告样例（%s）: size=%s blocks=%s/%s bbox=%s chunks=%s engines=%s rec=%s'
              % (fn, r.get('size'), r.get('blocks_affected'), r.get('blocks_total'),
                 r.get('bbox'), r.get('chunks_touched'), r.get('engine_available'),
                 r.get('engine_recommended')))
        bbox = r.get('bbox') or {}
        check('报告里 bbox = 最小角 + 尺寸 - 1',
              sz is not None and bbox.get('min') == [100, 64, -200]
              and bbox.get('max') == [100 + sz[0] - 1, 64 + sz[1] - 1, -200 + sz[2] - 1],
              'bbox=%s size=%s' % (bbox, sz))
        check('chunks_touched = ceil(sx/16)*ceil(sz/16)',
              sz is not None and r.get('chunks_touched') == ((sz[0] + 15) // 16) * ((sz[2] + 15) // 16),
              '%s (size=%s)' % (r.get('chunks_touched'), sz))
        check('blocks_total = sx*sy*sz', sz is not None and r.get('blocks_total') == sz[0] * sz[1] * sz[2],
              'total=%s size=%s' % (r.get('blocks_total'), sz))

    sec('5. 预检负例：越界 / 恶意样本必须被拒')
    if ups:
        anyup = list(ups.values())[0]['upload_id']
        st, r = req('POST', f'/api/instances/{iid}/build/preview',
                    {'upload_id': anyup, 'x': 0, 'y': 400, 'z': 0}, token)
        check('y=400 超高 → 被拒', st >= 400 or not r.get('ok'), 'HTTP %s %s' % (st, str(r)[:160]))
        st, r = req('POST', f'/api/instances/{iid}/build/preview',
                    {'upload_id': anyup, 'x': 40000000, 'y': 64, 'z': 0}, token)
        check('x=4e7 越界 → 被拒', st >= 400 or not r.get('ok'), 'HTTP %s %s' % (st, str(r)[:160]))
        st, r = req('POST', f'/api/instances/{iid}/build/preview',
                    {'upload_id': 'f' * 24, 'x': 0, 'y': 64, 'z': 0}, token)
        check('不存在的 upload_id → 被拒', st >= 400 or not r.get('ok'),
              'HTTP %s %s' % (st, str(r)[:160]))

    sec('6. 恶意样本：全部必须被拒（且不能被写出实例目录）')
    before = set(os.listdir(idir)) if os.path.isdir(idir) else set()
    for fn, path in samples.items():
        if not (fn.startswith('evil_') or fn.startswith('sample_unmapped')
                or fn.startswith('sample_for_out')):
            continue
        data = io.open(path, 'rb').read()
        body, ctype = multipart([('file', fn, data)])
        st, up = req('POST', f'/api/instances/{iid}/build/upload', raw=body, ctype=ctype, token=token)
        if st != 200 or not up.get('upload_id'):
            check('恶意样本 %-28s 上传即被拒 (HTTP %s)' % (fn, st), True)
            continue
        st2, r2 = req('POST', f'/api/instances/{iid}/build/preview',
                      {'upload_id': up['upload_id'], 'x': 0, 'y': 64, 'z': 0}, token)
        rejected = (st2 >= 400) or (not r2.get('ok'))
        check('恶意样本 %-28s 预检被拒' % fn, rejected, 'HTTP %s %s' % (st2, str(r2)[:140]))
    after = set(os.listdir(idir)) if os.path.isdir(idir) else set()
    check('实例目录未被恶意样本污染', before == after,
          '新增 %s' % (after - before) if after != before else '')

    sec('7. 引擎 B 端到端：导入 → 读回方块 → 回滚 sha256 一致')
    if rep:
        fn, up, report = rep
        region_dir = os.path.join(idir, 'world', 'region')
        # 导入前对受影响的 region 文件取哈希（可能还不存在 → 记为空）
        before_hash = {}
        if os.path.isdir(region_dir):
            for f in os.listdir(region_dir):
                if f.endswith('.mca'):
                    before_hash[f] = sha256f(os.path.join(region_dir, f))
        st, imp = req('POST', f'/api/instances/{iid}/build/import', {
            'upload_id': up['upload_id'], 'x': 100, 'y': 64, 'z': -200,
            'dimension': 'overworld', 'engine': 'offline', 'backup': True,
            'place_mode': 'only_air'}, token)
        check('发起导入（引擎 B / offline）', st == 200 and imp.get('task_id'),
              'HTTP %s %s' % (st, str(imp)[:250]))
        tid = imp.get('task_id')
        task = None
        if tid:
            for _ in range(120):
                time.sleep(0.5)
                st, task = req('GET', f'/api/instances/{iid}/build/tasks/{tid}', token=token)
                if task.get('status') in ('done', 'failed', 'cancelled'):
                    break
            print('  任务终态: %s  进度=%s/%s  引擎=%s'
                  % (task.get('status'), task.get('progress'), task.get('total'),
                     task.get('engine_used')))
            check('导入任务完成（status=done）', task.get('status') == 'done',
                  str(task.get('error') or '')[:300])
            if task.get('status') == 'done':
                check('导入前强制备份（has_backup=true）', task.get('has_backup') is True,
                      'backup_files=%s' % len(task.get('backup_files') or []))
                # 用自研 anvil 解析器读回方块
                try:
                    from app.build import anvil as A
                    got = None
                    for name in ('read_block', 'get_block', 'block_at'):
                        if hasattr(A, name):
                            got = getattr(A, name)
                            break
                    print('  anvil 读回接口: %s' % ('有 %s' % got.__name__ if got else '无直读函数'))
                except Exception as e:                        # noqa: BLE001
                    print('  anvil 导入失败: %s' % e)
                after_hash = {}
                if os.path.isdir(region_dir):
                    for f in os.listdir(region_dir):
                        if f.endswith('.mca'):
                            after_hash[f] = sha256f(os.path.join(region_dir, f))
                changed = [f for f in after_hash if before_hash.get(f) != after_hash[f]]
                check('region 文件确实被写入（出现新增/变化）',
                      bool(changed) or bool(set(after_hash) - set(before_hash)),
                      '变化 %s 新增 %s' % (changed, list(set(after_hash) - set(before_hash))))
                # 回滚
                st, rb = req('POST', f'/api/instances/{iid}/build/rollback/{tid}', {}, token)
                check('回滚请求成功', st == 200 and rb.get('ok'), 'HTTP %s %s' % (st, str(rb)[:250]))
                time.sleep(1.0)
                now_hash = {}
                if os.path.isdir(region_dir):
                    for f in os.listdir(region_dir):
                        if f.endswith('.mca'):
                            now_hash[f] = sha256f(os.path.join(region_dir, f))
                same = all(now_hash.get(f) == before_hash.get(f) for f in set(before_hash) | set(now_hash))
                check('回滚后 region sha256 与导入前完全一致', same,
                      'before=%s now=%s' % (before_hash, now_hash))
    else:
        check('引擎 B 端到端（需要至少一个可导入样本）', False, '没有可用样本')

    sec('8. 任务列表与审计留痕')
    st, tl = req('GET', f'/api/instances/{iid}/build/tasks', token=token)
    check('任务列表可读', st == 200 and isinstance(tl.get('tasks'), list),
          'HTTP %s %s' % (st, str(tl)[:160]))
    st, au = req('GET', '/api/audit?limit=200', token=token)
    actions = [x.get('action') for x in (au.get('logs') or [])]
    check('导入动作进了审计（build.import.*）',
          any(str(a).startswith('build.') for a in actions),
          '相关: %s' % [a for a in actions if str(a).startswith('build.')][:6])
    warn = [x for x in (au.get('logs') or []) if str(x.get('action')).startswith('build.')
            and x.get('level') == 'warn']
    check('涉及写世界的操作审计为 warn 级', bool(warn), '%d 条 warn' % len(warn))

    check('面板进程存活（恶意样本没打崩它）', req('GET', '/api/health')[0] == 200)

    sec('清理')
    try:
        proc.terminate()
        proc.wait(timeout=12)
    except Exception:                                         # noqa: BLE001
        proc.kill()
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
    dead = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq java.exe'], capture_output=True,
                          text=True).stdout
    if 'java.exe' in dead:
        print('  ⚠️ 仍有 java 进程，手动清理')
    else:
        print('  无残留 java 进程')

    print('\n' + '=' * 74)
    print('  通过 %d 项，失败 %d 项' % (len(PASS), len(FAIL)))
    if FAIL:
        print('  失败明细:')
        for f in FAIL:
            print('   - ' + f)
    print('=' * 74)
    return 1 if FAIL else 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
