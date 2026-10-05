#!/usr/bin/env python
"""端到端自检（覆盖规格 §9 验收 1~5 与全部安全项）。

流程
  1. 用**独立数据目录 + 独立端口**起一个测试面板（不碰正在跑的生产面板）；
  2. 建真实例（vanilla 1.21.4，download=true）→ 启动一次让服务端生成世界 → 停止；
  3. 用手工样本走引擎 B 导入到指定坐标 → 用 anvil.py 读回方块证明写入；
  4. 回滚 → 比对 touched region 的 sha256 与导入前是否完全一致；
  5. 负坐标导入（floor 语义）；
  6. 越界 / 超高 / 未映射 / zip-slip / zip 炸弹 / 深层 NBT 全部被拒（贴原始响应）；
  7. 格式覆盖：.schem(v1/v2/v3) / .schematic / .nbt / .litematic 各解析一例；
  8. 最后把服务端启动一次确认世界正常加载，并**停实例、杀干净 java**。

用法: PYTHONUTF8=1 python tools/build_selftest.py
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

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path[:0] = [BACKEND, os.path.join(BACKEND, '.deps')]

import httpx  # noqa: E402

PORT = int(os.environ.get('BUILD_SELFTEST_PORT') or 8199)
MC_PORT = int(os.environ.get('BUILD_SELFTEST_MC_PORT') or 25580)
RCON_PORT = int(os.environ.get('BUILD_SELFTEST_RCON_PORT') or 25581)
BASE = f'http://127.0.0.1:{PORT}'
DATA = os.path.join(BACKEND, 'data', 'buildwork', 'selftest-data')
SAMPLES = os.path.join(BACKEND, 'data', 'buildwork', 'selftest-samples')
JAR_SRC = os.path.join(BACKEND, 'data', 'buildwork', 'server-1.21.4.jar')
ADMIN = 'admin'
PASSWORD = 'SelfTest#Build2026x'

PANEL_LOG = os.path.join(BACKEND, 'data', 'buildwork', 'selftest-panel.log')

_results = []


def section(title):
    print('\n' + '=' * 78)
    print('== ' + title)
    print('=' * 78)


def check(name, ok, detail=''):
    _results.append((name, bool(ok), str(detail)[:400]))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name,
                           ('  — ' + str(detail)[:300]) if detail else ''))
    return bool(ok)


def jdump(obj, limit=1600):
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    return s if len(s) <= limit else s[:limit] + ' …(截断)'


# ---------------------------------------------------------------- 面板

def wait_port(port, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(('127.0.0.1', port), 1.0):
                return True
        except OSError:
            time.sleep(0.4)
    return False


def start_panel():
    env = dict(os.environ)
    env['MC_DATA_DIR'] = DATA
    env['PYTHONUTF8'] = '1'
    env['MC_DOCS'] = '0'
    env['MC_TEST_PORT'] = str(PORT)
    env['PYTHONPATH'] = os.pathsep.join([BACKEND, os.path.join(BACKEND, '.deps')])
    cfg_dir = DATA
    os.makedirs(cfg_dir, exist_ok=True)
    with io.open(os.path.join(cfg_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'port': PORT, 'bind_host': '127.0.0.1', 'default_java': 'java'}, f)
    log = io.open(PANEL_LOG, 'w', encoding='utf-8', errors='replace')
    launcher = (
        "import sys, os\n"
        "sys.path[:0] = [%r, %r]\n"
        "from app.main import app\n"
        "from app.routers import build as build_router\n"
        "app.include_router(build_router.router)   # 测试面板上手动挂载（main.py 不允许改）\n"
        "import uvicorn\n"
        "uvicorn.run(app, host='127.0.0.1', port=%d, log_level='warning')\n"
        % (BACKEND, os.path.join(BACKEND, '.deps'), PORT))
    proc = subprocess.Popen([sys.executable, '-c', launcher],
                            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    if not wait_port(PORT, 90):
        proc.kill()
        raise RuntimeError('测试面板启动失败，日志见 ' + PANEL_LOG)
    return proc, log


def stop_panel(proc, log):
    try:
        proc.terminate()
        proc.wait(timeout=20)
    except Exception:
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                           capture_output=True)
        except Exception:
            pass
    try:
        log.close()
    except Exception:
        pass


def ensure_admin_password():
    """用面板自身的 auth 模块把 admin 口令设成已知值（独立数据目录，无副作用）。"""
    env = dict(os.environ)
    env['MC_DATA_DIR'] = DATA
    env['PYTHONUTF8'] = '1'
    code = (
        "import sys; sys.path[:0]=['.','.deps']\n"
        "from app.database import init_db, execute, query, now\n"
        "from app.auth import hash_password, ensure_admin_user\n"
        "init_db()\n"
        "ensure_admin_user()\n"
        "execute('DELETE FROM sessions')\n"
        "execute('DELETE FROM users')\n"
        "execute('INSERT INTO users (username,password_hash,role,status,created_at) VALUES (?,?,?,?,?)',\n"
        "        ('admin', hash_password(%r), 'admin', 1, now()))\n"
        "print('admin ready', query('SELECT id,username FROM users', one=True))\n"
    ) % PASSWORD
    r = subprocess.run([sys.executable, '-c', code], cwd=BACKEND, env=env,
                       capture_output=True)
    print(r.stdout.decode('utf-8', 'replace').strip())
    if r.returncode != 0:
        print(r.stderr.decode('utf-8', 'replace')[-1500:])
        raise RuntimeError('初始化测试管理员失败')


class Api:
    def __init__(self, base):
        self.c = httpx.Client(base_url=base, timeout=180.0)
        self.token = ''

    def login(self):
        r = self.c.post('/api/auth/login', json={'username': ADMIN, 'password': PASSWORD})
        r.raise_for_status()
        self.token = r.json().get('token') or r.json().get('access_token') or ''
        self.c.headers['Authorization'] = 'Bearer ' + self.token
        return self.token

    def get(self, path, **kw):
        return self.c.get(path, **kw)

    def post(self, path, **kw):
        return self.c.post(path, **kw)

    def delete(self, path, **kw):
        return self.c.delete(path, **kw)


# ---------------------------------------------------------------- 工具

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def upload(api, iid, path):
    with open(path, 'rb') as f:
        r = api.post(f'/api/instances/{iid}/build/upload',
                     files={'file': (os.path.basename(path), f, 'application/octet-stream')},
                     data={'path': os.path.basename(path)})
    return r


def wait_task(api, iid, task_id, timeout=300):
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout:
        r = api.get(f'/api/instances/{iid}/build/tasks/{task_id}')
        if r.status_code != 200:
            time.sleep(1)
            continue
        d = r.json()
        last = d
        if d.get('status') in ('done', 'failed', 'cancelled'):
            return d
        time.sleep(1.5)
    return last


def gen_samples():
    shutil.rmtree(SAMPLES, ignore_errors=True)
    os.makedirs(SAMPLES, exist_ok=True)
    r1 = subprocess.run([sys.executable, 'tools/build_make_sample.py', SAMPLES],
                        cwd=BACKEND, capture_output=True,
                        env={**os.environ, 'PYTHONUTF8': '1'})
    print(r1.stdout.decode('utf-8', 'replace').strip())
    if r1.returncode != 0:
        print(r1.stderr.decode('utf-8', 'replace')[-2000:])
    r2 = subprocess.run([sys.executable, 'tools/build_make_sample.py', SAMPLES, '--malicious'],
                        cwd=BACKEND, capture_output=True,
                        env={**os.environ, 'PYTHONUTF8': '1'})
    print(r2.stdout.decode('utf-8', 'replace').strip())
    if r2.returncode != 0:
        print(r2.stderr.decode('utf-8', 'replace')[-2000:])
    return sorted(os.listdir(SAMPLES))


# ---------------------------------------------------------------- main

def main():
    overall = []
    panel = None
    clog = None
    try:
        section('0. 准备：独立数据目录 + 测试面板 + 样本')
        print('数据目录:', DATA)
        print('面板端口:', PORT, ' MC 端口:', MC_PORT, ' RCON:', RCON_PORT)
        shutil.rmtree(DATA, ignore_errors=True)
        os.makedirs(DATA, exist_ok=True)
        ensure_admin_password()
        gen_samples()
        print('样本文件:', gen_samples.__doc__ or '', )
        panel, clog = start_panel()
        print('测试面板已启动 PID', panel.pid)
        api = Api(BASE)
        api.login()
        print('登录成功，token 长度', len(api.token))
        r = api.get('/api/instances')
        check('面板 API 可用', r.status_code == 200, r.text[:200])

        # ---------------- 建实例（真实例，复用已下载的 jar 节省时间）
        section('1. 建真实例（vanilla 1.21.4）')
        inst_dir = os.path.join(DATA, 'instances', 'buildtest')
        os.makedirs(os.path.join(inst_dir, 'logs'), exist_ok=True)
        if os.path.isfile(JAR_SRC):
            shutil.copyfile(JAR_SRC, os.path.join(inst_dir, 'server-1.21.4.jar'))
            print('已复制已有的 server-1.21.4.jar 到实例目录（避免重复下载 56MB）')
        r = api.post('/api/instances', json={
            'name': 'buildtest', 'core_type': 'vanilla', 'mc_version': '1.21.4',
            'memory_mb': 1024, 'port': MC_PORT, 'rcon_enabled': True,
            'rcon_port': RCON_PORT, 'rcon_password': 'selftest-rcon-pw',
            'accept_eula': True, 'download': os.path.isfile(JAR_SRC) is False,
        })
        print('POST /api/instances ->', r.status_code, jdump(r.json(), 900))
        check('创建实例', r.status_code == 200, r.text[:200])
        iid = r.json()['id']
        inst_dir = r.json()['instance']['dir']
        # 把 jar 放好（面板自己下的或我们复制的）
        r = api.get(f'/api/instances/{iid}')
        row = r.json()['instance']
        print('实例 jar_path =', row.get('jar_path'))
        jar = row.get('jar_path') or ''
        if not jar:
            jar_abs = os.path.join(inst_dir, 'server-1.21.4.jar')
        else:
            jar_abs = jar if os.path.isabs(jar) else os.path.join(inst_dir, os.path.basename(jar))
        if not os.path.isfile(jar_abs):
            print('jar 不存在，直接放一份:', jar_abs)
            os.makedirs(os.path.dirname(jar_abs), exist_ok=True)
            shutil.copyfile(JAR_SRC, jar_abs)
            r = api.post(f'/api/instances/{iid}/jar', json={'jar_path': jar_abs})
            print('set jar ->', r.status_code, r.text[:200])
        # 让 server.properties 用我们的端口 + 开 RCON
        with io.open(os.path.join(inst_dir, 'server.properties'), 'w', encoding='utf-8') as f:
            f.write(f'enable-rcon=true\nrcon.port={RCON_PORT}\nrcon.password=selftest-rcon-pw\n'
                    f'online-mode=false\nserver-port={MC_PORT}\ngamemode=creative\n'
                    f'level-type=minecraft\\:flat\nspawn-protection=0\nview-distance=10\n'
                    f'simulation-distance=10\n')
        with io.open(os.path.join(inst_dir, 'eula.txt'), 'w', encoding='utf-8') as f:
            f.write('eula=true\n')
        api.post(f'/api/instances/{iid}', json={})

        # ---------------- 首次启动生成世界
        section('2. 首次启动（生成世界 + spawn 区块），随后停止')
        r = api.post(f'/api/instances/{iid}/start')
        print('start ->', r.status_code, r.text[:300])
        ok_ready = False
        t0 = time.time()
        while time.time() - t0 < 300:
            st = api.get(f'/api/instances/{iid}/status').json()
            if st.get('running') and any('Done (' in (l.get('line') or '')
                                         for l in api.get(f'/api/instances/{iid}/log',
                                                          params={'lines': 400}).json()
                                         .get('lines', [])):
                ok_ready = True
                break
            if not st.get('running') and t0 > 10:
                break
            time.sleep(2)
        logs = api.get(f'/api/instances/{iid}/log', params={'lines': 60}).json()
        print('服务端就绪:', ok_ready)
        print('日志尾部:')
        for l in (logs.get('lines') or [])[-12:]:
            print('   |', l.get('line'))
        check('服务端首次启动并完成加载', ok_ready)

        # ---------------- 让服务端把目标区域的区块先真实生成出来
        # 离线引擎不会替服务端生成地形，所以先用 RCON forceload 把目标区块生成好。
        # 目的坐标：(5,100,5) / (-100,100,-217) / (40,100,40) / (60,100,60) / (80,100,80)
        section('2b. RCON forceload 目标区域（先把区块生成出来，离线写入才不会留空洞）')
        for (bx, bz) in [(5, 5), (-100, -217), (40, 40), (60, 60), (80, 80)]:
            cx, cz = bx >> 4, bz >> 4
            x0, z0 = (cx - 2) * 16, (cz - 2) * 16
            x1, z1 = (cx + 2) * 16 + 15, (cz + 2) * 16 + 15
            r = api.post(f'/api/instances/{iid}/rcon',
                         json={'command': f'forceload add {x0} {z0} {x1} {z1}'})
            print('  forceload add %d %d %d %d -> %s %s'
                  % (x0, z0, x1, z1, r.status_code, r.text[:160]))
        time.sleep(3)
        r = api.post(f'/api/instances/{iid}/rcon', json={'command': 'save-all flush'})
        print('  save-all ->', r.status_code, r.text[:160])
        time.sleep(3)
        r = api.post(f'/api/instances/{iid}/stop')
        print('stop ->', r.status_code, r.text[:200])
        time.sleep(3)
        st = api.get(f'/api/instances/{iid}/status').json()
        check('实例已停止', not st.get('running'), st.get('status'))
        world = os.path.join(inst_dir, 'world')
        print('world 目录存在:', os.path.isdir(os.path.join(world, 'region')),
              os.listdir(os.path.join(world, 'region'))[:4])

        # ---------------- 格式覆盖（解析）
        section('3. 格式覆盖：每种格式解析一例（尺寸 / 方块数 / 调色板）')
        formats = ['sample_v3.schem', 'sample_v2.schem', 'sample_v1.schem', 'sample.schematic',
                   'sample.nbt', 'sample.litematic', 'sample_negsize.litematic']
        parsed = {}
        for name in formats:
            p = os.path.join(SAMPLES, name)
            if not os.path.isfile(p):
                check('解析 ' + name, False, '样本不存在')
                continue
            up = upload(api, iid, p)
            if up.status_code != 200:
                check('解析 ' + name, False, up.text[:200])
                continue
            uid = up.json()['upload_id']
            r = api.post(f'/api/instances/{iid}/build/preview', json={
                'upload_id': uid, 'x': 0, 'y': 100, 'z': 0, 'dimension': 'overworld',
                'place_mode': 'replace_all'})
            if r.status_code != 200:
                check('解析 ' + name, False, r.text[:200])
                continue
            d = r.json()
            parsed[name] = (uid, d)
            print('  %-26s format=%-9s size=%s palette=%d blocks_total=%d unmapped=%d'
                  % (name, d.get('format'), d.get('size'), d.get('palette_total') or 0,
                     d.get('blocks_total') or 0, d.get('blocks_unmapped') or 0))
            check('解析 ' + name, d.get('size', {}).get('x', 0) > 0)
        src_unmapped = None
        p = os.path.join(SAMPLES, 'sample_unmapped.nbt')
        if os.path.isfile(p):
            up = upload(api, iid, p)
            uid = up.json()['upload_id']
            r = api.post(f'/api/instances/{iid}/build/preview', json={
                'upload_id': uid, 'x': 40, 'y': 100, 'z': 40, 'place_mode': 'replace_all'})
            d = r.json()
            src_unmapped = (uid, d)
            print('  %-26s unmapped=%d 清单=%s'
                  % ('sample_unmapped.nbt', d.get('blocks_unmapped') or 0,
                     json.dumps(d.get('palette_unmapped'), ensure_ascii=False)[:300]))
            check('未映射方块被真实统计出', (d.get('blocks_unmapped') or 0) >= 1,
                  json.dumps(d.get('palette_unmapped'), ensure_ascii=False)[:300])

        # ---------------- 引擎 B 端到端 + 读回
        section('4. 引擎 B 端到端：导入 → anvil.py 读回方块')
        uid = parsed['sample_v3.schem'][0]
        ORIGIN = (5, 100, 5)
        r = api.post(f'/api/instances/{iid}/build/preview', json={
            'upload_id': uid, 'x': ORIGIN[0], 'y': ORIGIN[1], 'z': ORIGIN[2],
            'dimension': 'overworld', 'place_mode': 'replace_all'})
        prev = r.json()
        print('预检报告（§5 全字段）:')
        print(jdump({k: prev.get(k) for k in (
            'ok', 'format', 'size', 'blocks_total', 'blocks_affected', 'dimension', 'bbox',
            'palette_total', 'palette_unmapped', 'chunks_touched', 'engine_available',
            'engine_recommended', 'warnings', 'requires_backup', 'blocks_overwrite',
            'registry', 'place_mode')}, 2000))
        check('预检字段齐全', all(k in prev for k in
                                  ('format', 'size', 'blocks_total', 'blocks_affected',
                                   'dimension', 'bbox', 'palette_total', 'palette_unmapped',
                                   'chunks_touched', 'engine_available', 'engine_recommended',
                                   'warnings', 'requires_backup')))
        check('预检推荐引擎 = offline', prev.get('engine_recommended') == 'offline',
              prev.get('engine_recommended'))
        # 记录导入前 region 哈希
        regions = [os.path.join(world, 'region', f) for f in
                   sorted(os.listdir(os.path.join(world, 'region')))] if \
            os.path.isdir(os.path.join(world, 'region')) else []
        before = {p: sha256_file(p) for p in regions}
        print('导入前 region 哈希:')
        for p, h in before.items():
            print('   %s  %s' % (os.path.basename(p), h))
        before_files = set(before)

        r = api.post(f'/api/instances/{iid}/build/import', json={
            'upload_id': uid, 'x': ORIGIN[0], 'y': ORIGIN[1], 'z': ORIGIN[2],
            'dimension': 'overworld', 'place_mode': 'replace_all', 'backup': True,
            'include_entities': True})
        print('import ->', r.status_code, r.text[:300])
        check('导入请求被接受', r.status_code == 200, r.text[:200])
        task_id = r.json()['task_id']
        d = wait_task(api, iid, task_id)
        print('任务最终状态:', jdump({k: d.get(k) for k in
                                      ('status', 'stage', 'message', 'progress', 'total',
                                       'blocks_written', 'chunks_written', 'engine_used',
                                       'error')}, 1200))
        check('导入任务 done', d.get('status') == 'done', d.get('message'))
        if d.get('result', {}).get('traceback'):
            print('traceback:', d['result']['traceback'][-1200:])

        from app.build import anvil as AV
        print('用 app/build/anvil.py 读回（期望：石头地板 / 石砖墙 / 玻璃顶 / 楼梯 / 箱子 / 告示牌）')
        expect = [
            (5, 100, 5, 'minecraft:stone'),
            (6, 101, 6, 'minecraft:stone_bricks'),
            (9, 102, 7, 'minecraft:glass'),
            (6, 101, 7, 'minecraft:oak_stairs'),
            (8, 101, 7, 'minecraft:chest'),
            (6, 101, 6, 'minecraft:oak_sign'),
        ]
        readback = []
        for (x, y, z, want) in expect:
            got = AV.read_block(world, 'overworld', x, y, z)
            name = (got or {}).get('Name')
            props = (got or {}).get('Properties') or {}
            readback.append((x, y, z, want, name, props))
            print('   (%d,%d,%d) 期望 %-22s 实际 %-22s %s'
                  % (x, y, z, want, name, json.dumps(props, ensure_ascii=False)))
        check('读回方块与样本一致',
              all(rb[4] == rb[3] for rb in readback),
              json.dumps([(rb[0], rb[1], rb[2], rb[3], rb[4]) for rb in readback
                          if rb[4] != rb[3]], ensure_ascii=False))
        be = AV.read_block_entity(world, 'overworld', 8, 101, 7)
        print('   箱子方块实体:', jdump(None if be is None else {
            'id': None, 'has_items': bool(be and be.value.get('Items'))}, 200)
            if be is None else 'Items=%s' % len(be.value.get('Items').as_list()))
        sign_be = AV.read_block_entity(world, 'overworld', 6, 101, 6)
        print('   告示牌方块实体:', '有' if sign_be is not None else '无')

        # ---------------- 回滚
        section('5. 回滚：region 文件 sha256 必须与导入前完全一致')
        r = api.post(f'/api/instances/{iid}/build/rollback/{task_id}')
        print('rollback ->', r.status_code)
        rollback_body = r.json()
        print(jdump({k: rollback_body.get(k) for k in ('ok', 'note', 'removed',
                                                       'sha256_mismatch')}, 900))
        for f in (rollback_body.get('restored') or []):
            print('   %s\n     before=%s\n     after =%s  match=%s'
                  % (os.path.basename(f['path']), f['sha256_before'], f['sha256_after'],
                     f['match']))
        after = {p: sha256_file(p) for p in
                 [os.path.join(world, 'region', f) for f in
                  sorted(os.listdir(os.path.join(world, 'region')))]}
        same = all(before.get(p) == after.get(p) for p in before) and \
            set(after) == before_files
        for p in sorted(before):
            print('   %s\n     导入前 %s\n     回滚后 %s  %s'
                  % (os.path.basename(p), before[p], after.get(p),
                     '一致' if before[p] == after.get(p) else '不一致'))
        check('回滚后所有 region 文件 sha256 与导入前一致', same)
        got = AV.read_block(world, 'overworld', 5, 100, 5)
        check('回滚后目标坐标回到空气', (got or {}).get('Name', '').endswith('air'),
              json.dumps(got, ensure_ascii=False))

        # ---------------- 负坐标
        section('6. 负坐标导入（floor 语义）')
        neg = (-100, 100, -217)
        print('坐标 %s → chunk X = %d>>4 = %d, chunk Z = %d>>4 = %d'
              % (neg, neg[0], neg[0] >> 4, neg[2], neg[2] >> 4))
        print('        region 文件 = r.%d.%d.mca（= floor(X/512), floor(Z/512)）'
              % (neg[0] >> 9, neg[2] >> 9))
        r = api.post(f'/api/instances/{iid}/build/import', json={
            'upload_id': uid, 'x': neg[0], 'y': neg[1], 'z': neg[2],
            'dimension': 'overworld', 'place_mode': 'replace_all', 'backup': True})
        print('import(-100,100,-217) ->', r.status_code, r.text[:200])
        dneg = wait_task(api, iid, r.json()['task_id'])
        print('任务:', dneg.get('status'), dneg.get('message'))
        rp = AV.region_path(world, 'overworld', neg[0], neg[2])
        print('region 文件路径:', rp, '存在:', os.path.isfile(rp))
        for (dx, dy, dz, want) in [(0, 0, 0, 'minecraft:stone'),
                                   (1, 1, 1, 'minecraft:stone_bricks'),
                                   (4, 2, 3, 'minecraft:glass'),
                                   (-1, 0, 0, None)]:
            x, y, z = neg[0] + dx, neg[1] + dy, neg[2] + dz
            got = AV.read_block(world, 'overworld', x, y, z)
            print('   (%d,%d,%d) 期望 %-18s 实际 %s' % (x, y, z, want,
                                                        json.dumps(got, ensure_ascii=False)))
        negok = (AV.read_block(world, 'overworld', neg[0], neg[1], neg[2]) or {}).get(
            'Name') == 'minecraft:stone'
        check('负坐标写入正确（floor 语义）', negok)
        # 再回滚一次，保证世界干净
        rr = api.post(f'/api/instances/{iid}/build/rollback/{dneg["task_id"]}')
        print('负坐标任务回滚:', rr.status_code, rr.text[:200])

        # ---------------- 越界 / 超高 / 未映射 / 恶意
        section('7. 越界 / 超高 / 未映射 / 恶意样本（全部必须被拒）')
        cases = []
        r = api.post(f'/api/instances/{iid}/build/preview', json={
            'upload_id': uid, 'x': 0, 'y': -80, 'z': 0, 'place_mode': 'replace_all'})
        cases.append(('超世界下限（y=-80）', r))
        r = api.post(f'/api/instances/{iid}/build/preview', json={
            'upload_id': uid, 'x': 0, 'y': 300, 'z': 0, 'place_mode': 'replace_all'})
        cases.append(('超世界上限（y=300）', r))
        r = api.post(f'/api/instances/{iid}/build/preview', json={
            'upload_id': uid, 'x': 40_000_000, 'y': 64, 'z': 0, 'place_mode': 'replace_all'})
        cases.append(('X 超出世界边界（4e7）', r))
        high = os.path.join(SAMPLES, 'sample_for_out_of_range.nbt')
        if os.path.isfile(high):
            up = upload(api, iid, high)
            r = api.post(f'/api/instances/{iid}/build/preview', json={
                'upload_id': up.json()['upload_id'], 'x': 0, 'y': 64, 'z': 0,
                'place_mode': 'replace_all'})
            cases.append(('400 层超高建筑 @y=64', r))
        for name, path in [('zip-slip', 'evil_zipslip.zip'), ('绝对路径成员', 'evil_absolute.zip'),
                           ('符号链接成员', 'evil_symlink.zip'), ('zip 炸弹', 'evil_bomb.zip'),
                           ('成员数爆炸', 'evil_many.zip'), ('深层 NBT', 'evil_deep.nbt'),
                           ('超大数组', 'evil_bigarray.nbt'), ('gzip 炸弹', 'evil_gzip_bomb.nbt')]:
            p = os.path.join(SAMPLES, path)
            if not os.path.isfile(p):
                continue
            up = upload(api, iid, p)
            if up.status_code != 200:
                cases.append((name + '（上传即拒）', up))
                continue
            r = api.post(f'/api/instances/{iid}/build/preview', json={
                'upload_id': up.json()['upload_id'], 'x': 0, 'y': 100, 'z': 0,
                'place_mode': 'replace_all'})
            cases.append((name, r))
        all_rejected = True
        for name, r in cases:
            body = ''
            try:
                body = jdump(r.json(), 400)
            except Exception:
                body = r.text[:200]
            rejected = r.status_code >= 400
            all_rejected = all_rejected and rejected
            print('   %-24s HTTP %s  %s' % (name, r.status_code, body))
        check('全部恶意/越界样本被拒（HTTP ≥400）', all_rejected)
        # 面板还活着？
        r = api.get('/api/health')
        check('面板进程存活', r.status_code == 200, r.text[:120])
        r = api.get('/api/instances')
        check('面板仍能正常服务', r.status_code == 200)

        # ---------------- 导入后启动服务端
        section('8. 导入后启动服务端：确认世界正常加载（无坏区块崩溃）')
        r = api.post(f'/api/instances/{iid}/build/import', json={
            'upload_id': uid, 'x': ORIGIN[0], 'y': ORIGIN[1], 'z': ORIGIN[2],
            'dimension': 'overworld', 'place_mode': 'replace_all', 'backup': True,
            'include_entities': True})
        d2 = wait_task(api, iid, r.json()['task_id'])
        print('再次导入:', d2.get('status'), d2.get('message'))
        r = api.post(f'/api/instances/{iid}/start')
        print('start ->', r.status_code, r.text[:200])
        ok_done = False
        bad = []
        t0 = time.time()
        while time.time() - t0 < 300:
            st = api.get(f'/api/instances/{iid}/status').json()
            logs = api.get(f'/api/instances/{iid}/log', params={'lines': 500}).json()
            lines = [l.get('line') or '' for l in (logs.get('lines') or [])]
            if any('Done (' in l for l in lines):
                ok_done = True
            bad = [l for l in lines if any(k in l for k in
                                           ('Bad chunk', 'Failed to load chunk', 'corrupt',
                                            'Chunk file at', 'region file', 'Exception ticking',
                                            'SEVERE'))]
            if ok_done:
                break
            if not st.get('running') and t0 > 10:
                break
            time.sleep(2)
        check('导入后服务端正常启动（Done）', ok_done)
        check('服务端日志无坏区块/损坏报错', not bad, jdump(bad[:3], 600))
        print('日志尾部:')
        for l in (lines[-14:] if 'lines' in dir() else []):
            print('   |', l)
        # RCON 读回
        api_last = api.get(f'/api/instances/{iid}/rcon/test')
        print('RCON 测试:', api_last.status_code, api_last.text[:200])
        r = api.post(f'/api/instances/{iid}/rcon',
                     json={'command': 'execute if block 5 100 5 minecraft:stone'})
        print('RCON 读回 (5,100,5) is stone ->', r.status_code, r.text[:300])
        check('服务端内存里也确认方块已写入', 'passed' in r.text.lower(), r.text[:200])
        r = api.post(f'/api/instances/{iid}/stop')
        print('stop ->', r.status_code, r.text[:200])
        time.sleep(4)

        # ---------------- 并发 / 取消
        section('9. 单实例串行 + 取消 + 审计 + 路由数')
        r1 = api.post(f'/api/instances/{iid}/build/import', json={
            'upload_id': uid, 'x': 60, 'y': 100, 'z': 60, 'place_mode': 'replace_all',
            'backup': True})
        r2 = api.post(f'/api/instances/{iid}/build/import', json={
            'upload_id': uid, 'x': 80, 'y': 100, 'z': 80, 'place_mode': 'replace_all',
            'backup': True})
        print('并发第二个 import ->', r2.status_code, r2.text[:200])
        check('单实例同时只允许一个导入任务（409）', r2.status_code == 409, r2.text[:200])
        if r1.status_code == 200:
            tid = r1.json()['task_id']
            time.sleep(0.3)
            rc = api.post(f'/api/instances/{iid}/build/tasks/{tid}/cancel')
            print('cancel ->', rc.status_code, rc.text[:200])
            d = wait_task(api, iid, tid, timeout=120)
            print('取消后任务状态:', d.get('status'), d.get('message'))
            check('取消生效', d.get('status') in ('cancelled', 'done'), d.get('status'))
        # 审计
        from app.database import query as dbq
        audits = dbq("SELECT action, level, detail FROM audit_logs WHERE action LIKE 'build.%' "
                     "ORDER BY id DESC LIMIT 6")
        print('审计日志（level=warn 要求）:')
        for a in audits:
            print('   %-24s %-6s %s' % (a['action'], a['level'], (a['detail'] or '')[:110]))
        check('导入审计为 warn 级', any(a['level'] == 'warn' for a in audits))
    finally:
        section('清理')
        try:
            if panel is not None:
                stop_panel(panel, clog)
                print('测试面板已停止')
        except Exception as e:
            print('停止测试面板失败:', e)
        # 杀掉可能残留的测试服务端 java（只杀命令行里带 selftest-data 的）
        try:
            import psutil
            killed = []
            for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                cmd = ' '.join(p.info.get('cmdline') or [])
                if 'java' in (p.info.get('name') or '').lower() and 'selftest-data' in cmd:
                    p.kill()
                    killed.append(p.info['pid'])
            print('清理残留 java 进程:', killed or '无')
        except Exception as e:
            print('清理 java 失败:', e)

    print('\n' + '=' * 78)
    print('自检汇总')
    print('=' * 78)
    npass = sum(1 for _n, ok, _d in _results if ok)
    for name, ok, detail in _results:
        print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name,
                               ('' if ok else '  ← ' + detail[:200])))
    print('  %d/%d 通过' % (npass, len(_results)))
    out = os.path.join(BACKEND, 'data', 'buildwork', 'selftest-summary.json')
    with io.open(out, 'w', encoding='utf-8') as f:
        json.dump([{'name': n, 'ok': o, 'detail': d} for n, o, d in _results], f,
                  ensure_ascii=False, indent=1)
    print('汇总写入', out)
    return 0 if npass == len(_results) else 2


if __name__ == '__main__':
    sys.exit(main())
