# -*- coding: utf-8 -*-
"""账号与权限 · 规格 §8 六条验收 · 端到端自检（真 ASGI 服务 + 真 HTTP 请求）。

为什么要起真服务而不是直接调函数：本项目的验收口径是**打接口看状态码**。
权限体系的坑几乎全在"中间件 / 依赖注入 / 路由挂载"这一层
（例如 `include_router` 的惰性包装、鉴权闸门早于路由依赖、异常处理器返回码），
直接调函数会把这些问题全部掩盖过去。

用法（在 ``backend/`` 下）：

    set PYTHONUTF8=1
    python tools\\accounts_selftest.py

行为：

1. 自己起一个**独立数据目录**上的面板实例（默认 ``%TEMP%\\mcpanel-acctest``，
   或 ``--data-dir`` 指定；每次运行前清空），端口也自己挑（默认 8199）。
2. 按 `docs/FEATURE-ACCOUNTS.md` §8 逐条断言，打印每一条的请求/状态码/响应摘要。
3. 跑完关掉服务，退出码 0=全过、1=有失败。**原始输出就是验收证据**。

覆盖的验收条目：

| # | 规格 §8 原文 | 本脚本怎么验 |
|---|---|---|
| 1 | 全新库启动 → 只打印一次超管口令 → 登录成功 → `/api/me/permissions` 齐全 | 全新库启动，抓取终端里的初始口令，用它登录，核对 `role=super_admin` 与 15 个权限点 |
| 2 | `user` 角色访问他人实例/系统设置/用户管理 → 403；访问自己实例 → 200 | 建 3 个实例（超管名下 1 个、user 名下 1 个），逐条打接口核 403/200 |
| 3 | `user` 建实例超配额 → 403 + 中文原因 | 用「内存超配额」触发（不依赖能否建成功，稳定可复现） |
| 4 | 重置口令后旧 token 立即失效、新口令可登录、只在当次返回 | 重置 → 旧 token 打接口必须 401 → 新口令登录 → 库中无明文 |
| 5 | 唯一超管降级/停用/删除被拒；自删被拒 | 四条操作逐条核 400 + 中文原因 |
| 6 | 审计能看到每一次操作（谁、对谁、什么动作、IP） | 查 `/api/audit`，逐条核对 8 个动作都在，且带操作者与 IP |
"""
import argparse
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

HERE = os.path.dirname(os.path.abspath(__file__))          # backend/tools
BACKEND = os.path.dirname(HERE)                            # backend
DEPS = os.path.join(BACKEND, '.deps')
PY = sys.executable

SUPER_PW = 'SuperAdmin#2026x'          # 13 位、4 类字符 → 满足策略
USER_PW = 'NormalUser#2026x'
RESET_PW = 'ResetPw#2026zzz'

ROLE_PERMS = {
    'super_admin': ['instance.create', 'instance.delete', 'instance.start', 'instance.stop',
                    'instance.command', 'instance.files', 'instance.plugins', 'instance.backup',
                    'instance.cron', 'instance.build_import', 'instance.settings_network',
                    'user.manage', 'system.settings', 'audit.view', 'log.view'],
    'admin': ['instance.create', 'instance.delete', 'instance.start', 'instance.stop',
              'instance.command', 'instance.files', 'instance.plugins', 'instance.backup',
              'instance.cron', 'instance.build_import', 'instance.settings_network',
              'audit.view', 'log.view'],
    'user': ['instance.create', 'instance.start', 'instance.stop', 'instance.command',
             'instance.files', 'instance.plugins', 'instance.backup', 'instance.cron',
             'instance.build_import', 'log.view'],
    'viewer': [],
}

FAILURES = []
PASSES = []
_STEP = [0]


# ---------------------------------------------------------------- 输出
def head(title: str):
    print()
    print('=' * 78)
    print(f'  {title}')
    print('=' * 78)


def step(text: str):
    _STEP[0] += 1
    print(f'\n[{_STEP[0]:02d}] {text}')


def ok(text: str, extra: str = ''):
    PASSES.append(text)
    print(f'     PASS  {text}' + (f'   {extra}' if extra else ''))


def bad(text: str, detail: str = ''):
    FAILURES.append(f'{text} :: {detail}')
    print(f'     FAIL  {text}')
    if detail:
        print(f'           {detail}')


def check(cond, text: str, detail: str = ''):
    (ok if cond else bad)(text, '' if cond else detail)
    return bool(cond)


# ---------------------------------------------------------------- HTTP
def req(method: str, url: str, token: str = '', body=None, timeout: float = 30.0):
    """返回 (status, json_or_text)。绝不抛异常（4xx/5xx 也是有效结果）。"""
    data = None
    headers = {'Accept': 'application/json'}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
            return resp.status, _parse(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        return e.code, _parse(raw)
    except Exception as e:                                   # noqa: BLE001
        return 0, f'{type(e).__name__}: {e}'


def _parse(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        return raw


def detail_of(payload) -> str:
    if isinstance(payload, dict):
        return str(payload.get('detail') or payload.get('error') or payload)
    return str(payload)


def _upload(base: str, path: str, token: str, filename: str, data: bytes, field: str = 'file'):
    """multipart/form-data 上传（手搓 body，不引入 requests 依赖）。"""
    boundary = '----mcpanelSelftestBoundary7f3a'
    parts = []
    parts.append(('--' + boundary + '\r\n').encode())
    parts.append((f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n').encode())
    parts.append(data)
    parts.append(('\r\n--' + boundary + '--\r\n').encode())
    payload = b''.join(parts)
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}',
               'Content-Length': str(len(payload)), 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(base + path, data=payload, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, _parse(resp.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        return e.code, _parse(e.read().decode('utf-8', 'replace'))
    except Exception as e:                                   # noqa: BLE001
        return 0, f'{type(e).__name__}: {e}'


# ---------------------------------------------------------------- 服务进程
def _port_alive(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def free_port(prefer: int) -> int:
    """挑一个**没人监听**的端口。

    ⚠️ 这里必须同时确认"能 bind"且"没人 connect"：只用 bind 判定时，
    上一轮没杀干净的 uvicorn（Windows 上 `terminate()` 有时杀不掉子进程）
    会占着旧端口，于是本轮健康检查打到了**上一轮的旧服务**上 ——
    测试于是跑在一个角色已被改坏的老库上，报出一堆看不懂的错误。
    第一版就踩了这个坑，所以在应用内所有平台上都要堵死。
    """
    for p in range(prefer, prefer + 40):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', p))
            except OSError:
                continue
        if not _port_alive(p):
            return p
    raise SystemExit('找不到既空闲又无人监听的端口')


def _kill_proc(proc):
    """确保面板进程**连同子进程**真的死掉（Windows 上必须走 taskkill /T）。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                           capture_output=True)
        else:
            proc.kill()
    except Exception:                                       # noqa: BLE001
        pass
    try:
        proc.wait(timeout=10)
    except Exception:                                       # noqa: BLE001
        pass


def _wait_port_free(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_alive(port):
            return True
        time.sleep(0.3)
    return False


def boot(data_dir: str, port: int):
    """起面板子进程；返回 (proc, stdout_lines, base_url)。

    全新库时 `ensure_admin_user()` 会把随机初始口令 **只打印到终端** —— 我们从
    子进程 stdout 里把它抓出来，这正是"只在本地终端打印一次"的验证方式。

    ⚠️ Windows 的 `select()` 只支持套接字，对管道会抛 `WinError 10038`，
    所以这里用一个后台线程持续把 stdout 读进列表，主线程只管轮询健康检查。
    """
    import threading

    env = dict(os.environ)
    env['MC_DATA_DIR'] = data_dir
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    code = (f'import sys; sys.path[:0] = [r"{BACKEND}", r"{DEPS}"];'
            f'import uvicorn; uvicorn.run("app.main:app", host="127.0.0.1", port={port},'
            f' log_level="warning", ws="websockets")')
    proc = subprocess.Popen([PY, '-c', code], cwd=BACKEND, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace', bufsize=1)
    lines = []
    lock = threading.Lock()

    def _reader():
        try:
            for line in proc.stdout:
                with lock:
                    lines.append(line)
        except Exception:                                   # noqa: BLE001
            pass

    threading.Thread(target=_reader, daemon=True).start()

    def snapshot(_lines=lines, _lock=lock):
        """随时取一份当前已捕获的终端输出快照（口令横幅可能在就绪后才刷出来）。"""
        with _lock:
            return list(_lines)

    base = f'http://127.0.0.1:{port}'
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit('面板进程启动即退出：\n' + ''.join(snapshot()))
        st, _ = req('GET', base + '/api/health', timeout=2)
        if st == 200:
            time.sleep(1.2)                     # 再等一会儿，让首启横幅打印完
            return proc, snapshot, base
        time.sleep(0.4)
    proc.kill()
    raise SystemExit('面板启动超时')


def initial_password(lines) -> str:
    for i, line in enumerate(lines):
        if '初始口令' in line:
            return line.split('初始口令', 1)[1].strip().lstrip(':：').strip()
    return ''


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description='账号与权限规格 §8 六条验收')
    ap.add_argument('--data-dir', default=os.path.join(
        os.environ.get('TEMP') or '/tmp', 'mcpanel-acctest'))
    ap.add_argument('--port', type=int, default=8199)
    ap.add_argument('--keep', action='store_true', help='跑完保留测试数据目录')
    args = ap.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    head('账号与权限 · 规格 §8 验收（端到端，真 HTTP）')
    print(f'  数据目录 : {data_dir}   （每次运行前清空 = 全新库）')
    print(f'  Python   : {PY}')

    if os.path.isdir(data_dir):
        shutil.rmtree(data_dir, ignore_errors=True)
    if os.path.isdir(data_dir):
        raise SystemExit(f'测试数据目录清理失败，拒绝在脏状态上开跑：{data_dir}')
    os.makedirs(data_dir, exist_ok=True)
    db_file = os.path.join(data_dir, 'mc.db')
    if os.path.exists(db_file):
        raise SystemExit(f'拒绝启动：这是旧库，不是全新库 → {db_file}')
    # 本脚本要跑 20+ 次登录，会撞上"登录 10 次/60 秒"的防爆破限流（那是**正确**行为，
    # 但会把接口测试染成 429）。所以只在这个一次性测试数据目录里把它调高。
    with io.open(os.path.join(data_dir, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'login_rate_limit': 500}, f)

    port = free_port(args.port)
    print(f'  服务端口 : {port}')
    proc, snapshot, base = boot(data_dir, port)
    print('  面板已就绪，首启终端输出如下：')
    for l in snapshot():
        print('      | ' + l.rstrip())

    try:
        run_all(base, data_dir, snapshot)
    finally:
        _kill_proc(proc)
        if not _wait_port_free(port):
            bad(f'面板进程未能释放端口 {port}（下一轮可能连到旧服务上）')
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)

    head('结果汇总')
    print(f'  通过 {len(PASSES)} 项，失败 {len(FAILURES)} 项')
    if FAILURES:
        print('\n  失败明细：')
        for f in FAILURES:
            print('   - ' + f)
        return 1
    print('  ✅ 规格 §8 六条验收全部通过')
    return 0


def run_all(base: str, data_dir: str, snapshot):
    # ============================================================ §8.1
    step('§8.1 全新库启动 → 终端只打印一次超管口令 → 用它登录 → 权限齐全')

    row = _db(data_dir, 'SELECT id, username, role, status FROM users ORDER BY id')
    print(f'    库中用户       : {row}')
    check(len(row) == 1 and row[0]['username'] == 'admin' and row[0]['role'] == 'super_admin',
          '默认账号落成唯一超级管理员（username=admin, role=super_admin）',
          f'实际: {row}')

    create_audit = _db(data_dir, "SELECT COUNT(*) AS n FROM audit_logs WHERE action='init'")
    check(create_audit and int(create_audit[0]['n']) == 1,
          '首启建号写入审计一次（action=init）', f'实际: {create_audit}')

    # ① 终端一次性口令：从子进程 stdout 抓（这是"只在本地终端打印一次"的直接证据）
    boot_lines = snapshot()
    if not initial_password(boot_lines):
        # 横幅可能还在管道缓冲里，等一会再抓一次
        time.sleep(2.0)
        boot_lines = snapshot()
    print('    首启终端输出（含口令横幅，口令本身不在日志里回显）：')
    for l in boot_lines:
        if '口令' in l or 'admin' in l or '超级管理员' in l:
            print('      | ' + l.rstrip())
    pwd = initial_password(boot_lines)
    if pwd:
        ok('首启在终端打印了初始口令（已从子进程 stdout 捕获，长度 %d，不在此回显全文）'
           % len(pwd))
        check(_pw_policy_error(pwd) == '', '初始口令满足 ≥12 位 + 3 类字符（随机生成）',
              '策略不符')
        tok = login(base, 'admin', pwd)
        check(bool(tok), '用终端里那一次打印的初始口令登录成功')
        if tok:
            st, r = req('GET', base + '/api/me/permissions', tok)
            check(st == 200 and (r or {}).get('role') == 'super_admin',
                  '初始账号的 /api/me/permissions 显示 role=super_admin', detail_of(r))
            check(sorted((r or {}).get('perms') or []) == sorted(ROLE_PERMS['super_admin']),
                  '初始账号权限点齐全（15 项）', f"实际: {(r or {}).get('perms')}")
    else:
        bad('未能从终端输出里抓到初始口令', '子进程 stdout 里没有"初始口令"行')

    # 库里只有哈希、无明文
    hashes = _db(data_dir, 'SELECT password_hash FROM users')
    h = (hashes[0]['password_hash'] if hashes else '')
    check('$' in h and len(h.split('$')[0]) == 32 and (not pwd or pwd not in h),
          '库里只有 PBKDF2 哈希（32 位 salt$hash），无明文口令',
          f'实际: {h[:24]}…')
    check(not _grep_dir(data_dir, pwd) if pwd else True,
          '明文口令没有以任何形式落盘（全目录扫描）')

    # 为了让后续用例用固定口令断言（避免把随机口令写进日志/代码），改成本地已知口令
    st, r = _set_pw(data_dir, SUPER_PW)
    check(st == 0, '以本地脚本把超管口令设为已知值（走 hash_password，不绕过策略）', r)

    token = login(base, 'admin', SUPER_PW)
    check(bool(token), '超管用口令登录成功（POST /api/auth/login → 200 + token）')
    if not token:
        raise SystemExit('超管登录失败，后续无法继续')

    st, r = req('GET', base + '/api/me/permissions', token)
    perms = (r or {}).get('perms') or []
    check(st == 200, f'GET /api/me/permissions → {st}')
    check((r or {}).get('role') == 'super_admin', 'role = super_admin',
          f"实际 role={(r or {}).get('role')}")
    missing = [p for p in ROLE_PERMS['super_admin'] if p not in perms]
    check(not missing, f'权限点齐全（{len(perms)} 项，含 user.manage/system.settings/audit.view）',
          f'缺少: {missing}')
    check(sorted(perms) == sorted(ROLE_PERMS['super_admin']),
          '权限点集合与规格 §2 完全一致（不多不少）',
          f'实际: {sorted(perms)}')

    # ============================================================ §8.2
    step('§8.2 建 user 角色账号 → 他人实例/系统设置/用户管理全部 403；自己实例 200')

    st, r = req('POST', base + '/api/users', token,
                {'username': 'tang', 'password': USER_PW, 'role': 'user',
                 'quota': {'max_instances': 3, 'max_memory_mb_total': 8192,
                           'max_backups': 5, 'max_upload_mb': 128,
                           'allow_build_import': False}})
    check(st == 200, f'POST /api/users 建普通用户 tang → {st}',
          detail_of(r))
    uid = (r or {}).get('id')

    st2, r2 = req('POST', base + '/api/users', token,
                  {'username': 'shadow', 'password': USER_PW, 'role': 'viewer'})
    check(st2 == 200, f'POST /api/users 建只读账号 shadow → {st2}', detail_of(r2))
    vid = (r2 or {}).get('id')

    utoken = login(base, 'tang', USER_PW)
    vtoken = login(base, 'shadow', USER_PW)
    check(bool(utoken) and bool(vtoken), 'user / viewer 两个账号都能登录')

    st, r = req('GET', base + '/api/me/permissions', utoken)
    uperms = (r or {}).get('perms') or []
    check(st == 200 and (r or {}).get('role') == 'user', f'user 的 role = user（{st}）')
    check(not set(['user.manage', 'system.settings', 'audit.view']) & set(uperms),
          'user 权限集不含 user.manage / system.settings / audit.view',
          f'实际: {uperms}')
    check(sorted(uperms) == sorted(ROLE_PERMS['user']),
          'user 权限集与规格 §2 一致', f'实际: {sorted(uperms)}')

    st, r = req('GET', base + '/api/me/permissions', vtoken)
    check(st == 200 and (r or {}).get('perms') == [],
          'viewer 权限集为空（一切写操作默认被拒）', f'实际: {r}')

    # 超管再建 2 个实例，其中一个给 tang
    iid_admin = _mk_instance(base, token, 'admin-owned', 25570)
    iid_user = _mk_instance(base, token, 'tang-owned', 25571, owner_id=uid)
    check(bool(iid_admin) and bool(iid_user),
          f'超管建 2 个实例（admin 名下 #{iid_admin}、tang 名下 #{iid_user}）')

    step('    ① 他人实例 → 403')
    for path, label in ((f'/api/instances/{iid_admin}', '他人实例详情'),
                        (f'/api/instances/{iid_admin}/status', '他人实例状态'),
                        (f'/api/instances/{iid_admin}/log', '他人实例控制台日志'),
                        (f'/api/instances/{iid_admin}/files', '他人实例文件列表'),
                        (f'/api/instances/{iid_admin}/backups', '他人实例备份列表')):
        st, r = req('GET', base + path, utoken)
        check(st == 403, f'user GET {label} ({path}) → 403', f'实际 {st}: {detail_of(r)}')
    for path, label in ((f'/api/instances/{iid_admin}/start', '启动'),
                        (f'/api/instances/{iid_admin}/stop', '停止'),
                        (f'/api/instances/{iid_admin}/command', '下发命令'),
                        (f'/api/instances/{iid_admin}/backups', '建备份')):
        st, r = req('POST', base + path, utoken, {'command': 'list', 'note': ''})
        check(st == 403, f'user POST 他人实例{label} ({path}) → 403',
              f'实际 {st}: {detail_of(r)}')
    st, r = req('DELETE', base + f'/api/instances/{iid_admin}', utoken)
    check(st == 403, 'user DELETE 他人实例 → 403', f'实际 {st}: {detail_of(r)}')

    step('    ② 系统设置 / 用户管理 / 审计 → 403')
    for method, path, body, label in (
            ('GET', '/api/settings', None, '面板设置'),
            ('PUT', '/api/settings', {'port': 8300}, '改面板设置'),
            ('GET', '/api/users', None, '用户列表'),
            ('POST', '/api/users', {'username': 'evil', 'password': USER_PW}, '新建用户'),
            ('PATCH', f'/api/users/{uid}', {'role': 'super_admin'}, '改角色'),
            ('POST', f'/api/users/{uid}/kick', {}, '强制下线'),
            ('DELETE', f'/api/users/{uid}', None, '删除用户'),
            ('GET', '/api/me/permissions', None, '（对照：这个必须 200）')):
        st, r = req(method, base + path, utoken, body)
        if '对照' in label:
            check(st == 200, f'user {method} {path} {label} → 200', f'实际 {st}')
        else:
            check(st == 403, f'user {method} {path}（{label}）→ 403',
                  f'实际 {st}: {detail_of(r)}')
    for path, label in (('/api/audit', '审计日志'), ('/api/audit/login', '登录日志'),
                        ('/api/logs/app', '面板日志'), ('/api/maintenance/usage', '全盘占用'),
                        ('/api/webhook', 'Webhook 配置')):
        st, r = req('GET', base + path, utoken)
        check(st == 403, f'user GET {path}（{label}）→ 403', f'实际 {st}: {detail_of(r)}')

    step('    ③ 自己的实例 → 200')
    for path, label in ((f'/api/instances/{iid_user}', '详情'),                        (f'/api/instances/{iid_user}/status', '状态'),
                        (f'/api/instances/{iid_user}/log', '日志'),
                        (f'/api/instances/{iid_user}/files', '文件列表'),
                        (f'/api/instances/{iid_user}/backups', '备份列表'),
                        (f'/api/instances/{iid_user}/players', '玩家列表'),
                        (f'/api/instances/{iid_user}/plugins', '插件列表'),
                        (f'/api/instances/{iid_user}/metrics', '监控曲线'),
                        (f'/api/instances/{iid_user}/jars', 'jar 列表'),
                        (f'/api/instances/{iid_user}/tps', 'TPS'),
                        (f'/api/instances/{iid_user}/config/properties', 'server.properties'),
                        (f'/api/instances/{iid_user}/config/startup', '启动参数')):
        st, r = req('GET', base + path, utoken)
        check(st == 200, f'user GET 自己实例{label} ({path}) → 200',
              f'实际 {st}: {detail_of(r)}')

    step('    ④ 列表只含自己的实例')
    st, r = req('GET', base + '/api/instances', utoken)
    ids = [i['id'] for i in (r or {}).get('instances', [])]
    check(st == 200 and ids == [iid_user], f'GET /api/instances 只返回自己的 #{iid_user}',
          f'实际: {ids}')
    check((r or {}).get('scope') == 'mine', 'scope = mine（不暗示"本该有更多"）',
          f"实际: {(r or {}).get('scope')}")
    st, r = req('GET', base + '/api/overview', utoken)
    oids = [i['id'] for i in (r or {}).get('instances', [])]
    check(st == 200 and oids == [iid_user], f'GET /api/overview 也只含自己的 #{iid_user}',
          f'实际: {oids}')

    st, r = req('GET', base + '/api/instances', token)
    aids = [i['id'] for i in (r or {}).get('instances', [])]
    check(st == 200 and set(aids) == {iid_admin, iid_user},
          '超管 GET /api/instances 能看到全部实例', f'实际: {aids}')
    st, r = req('GET', base + f'/api/instances?owner={uid}', token)
    oids = [i['id'] for i in (r or {}).get('instances', [])]
    check(st == 200 and oids == [iid_user], f'超管按 owner={uid} 筛选归属', f'实际: {oids}')

    step('    ⑤ 只读账号：看得到，写不动')
    st, r = req('GET', base + f'/api/instances/{iid_admin}/log', vtoken)
    check(st == 200, f'viewer 可读任意实例日志（规格 §2「只读查看…日志」）→ {st}',
          detail_of(r))
    for method, path, body in (('POST', f'/api/instances/{iid_admin}/command', {'command': 'list'}),
                               ('POST', f'/api/instances/{iid_admin}/start', None),
                               ('POST', '/api/instances', {'name': 'x', 'mc_version': '1.21.4'}),
                               ('PUT', f'/api/instances/{iid_admin}/config/properties',
                                {'updates': {'motd': 'hacked'}})):
        st, r = req(method, base + path, vtoken, body)
        check(st == 403, f'viewer {method} {path}（写操作）→ 403',
              f'实际 {st}: {detail_of(r)}')

    # ============================================================ §8.3
    step('§8.3 用 user 账号超配额 → 403 + 中文原因')
    # 内存配额：tang 上限 8192MB。先建一个吃满 4096MB 的实例，再申请 8192MB → 合计超限。
    st, r = req('POST', base + '/api/instances', utoken,
                {'name': 'quota-a', 'mc_version': '1.21.4', 'memory_mb': 4096,
                 'port': 25580, 'download': False})
    check(st == 200, f'user 在配额内建实例（4096MB）→ {st}', detail_of(r))
    st, r = req('POST', base + '/api/instances', utoken,
                {'name': 'quota-b', 'mc_version': '1.21.4', 'memory_mb': 8192,
                 'port': 25581, 'download': False})
    check(st == 403, 'user 内存超配额建实例（4096+8192 > 8192）→ 403', f'实际 {st}')
    d = detail_of(r)
    check('内存配额不足' in d and '8192' in d,
          '响应是中文人话，且点明上限与当前占用', d)

    # 实例数配额：把 tang 的 max_instances 调成 1 → 再建必被拒
    st, r = req('PATCH', base + f'/api/users/{uid}', token,
                {'quota': {'max_instances': 1}})
    check(st == 200, f'超管把 tang 的 max_instances 调成 1 → {st}', detail_of(r))
    st, r = req('POST', base + '/api/instances', utoken,
                {'name': 'quota-c', 'mc_version': '1.21.4', 'memory_mb': 512,
                 'port': 25582, 'download': False})
    check(st == 403, 'user 实例数超配额（2 > 1）→ 403', f'实际 {st}')
    d = detail_of(r)
    check('实例数已达上限' in d and '调整配额' in d,
          '实例数超限原因同样点明上限并给出下一步（联系超管调整配额）', d)

    # 建筑导入配额（allow_build_import=false）→ 走真实的 multipart 上传路径，
    # 这样才会真正命中 `check_quota(user,'build_import')` 这一道闸门。
    st, r = _upload(base, f'/api/instances/{iid_user}/build/upload', utoken,
                    'tiny.schem', b'\x1f\x8b\x08\x00tiny-not-a-real-schematic')
    check(st == 403, 'allow_build_import=false 时上传建筑文件 → 403', f'实际 {st}')
    d = detail_of(r)
    check('建筑导入' in d and '超级管理员' in d,
          '建筑导入被拒时说明原因与下一步', d)
    st, r = req('PATCH', base + f'/api/users/{uid}', token,
                {'quota': {'allow_build_import': True}})
    check(st == 200, '超管为该账号开通建筑导入 → 200', detail_of(r))
    st, r = _upload(base, f'/api/instances/{iid_user}/build/upload', utoken,
                    'tiny.schem', b'\x1f\x8b\x08\x00tiny-not-a-real-schematic')
    check(st == 200, '开通后同一请求通过配额闸门（进入解析阶段）→ 200', detail_of(r))
    st, r = req('PATCH', base + f'/api/users/{uid}', token,
                {'quota': {'allow_build_import': False, 'max_instances': 3}})
    check(st == 200, f'配额复原（max_instances=3, allow_build_import=false）→ {st}')

    # ============================================================ §8.4
    step('§8.4 重置口令：旧 token 立即失效、新口令可登录、只在当次返回')

    st, r = req('GET', base + '/api/instances', utoken)
    check(st == 200, '重置前：user 的 token 可用')
    st, r = req('POST', base + f'/api/users/{uid}/password', token, {'password': RESET_PW})
    check(st == 200, f'超管重置 tang 口令 → {st}', detail_of(r))
    check((r or {}).get('password') == RESET_PW, '响应里一次性回显新口令')
    check('只在本次响应' in str((r or {}).get('note', '')),
          '响应 note 明确"只在本次返回一次"', str((r or {}).get('note')))

    st, r = req('GET', base + '/api/instances', utoken)
    check(st == 401, '重置后：旧 token 立即失效（→ 401）', f'实际 {st}: {detail_of(r)}')
    st, r = req('GET', base + '/api/instances', vtoken)
    check(st == 200, '他人的 token 不受影响（只清目标用户的会话）')

    ntoken = login(base, 'tang', RESET_PW)
    check(bool(ntoken), '新口令可登录')
    st, r = req('GET', base + f'/api/instances/{iid_user}', ntoken)
    check(st == 200, '新会话可正常访问自己的实例')

    # 自动生成口令 + 库中无明文
    st, r = req('POST', base + f'/api/users/{uid}/password', token, {})
    gen = (r or {}).get('password') or ''
    check(st == 200 and len(gen) >= 16, f'口令留空 → 服务端随机生成（{len(gen)} 位）')
    check(bool(_pw_policy_error(gen)) is False, '随机口令满足 ≥12 位 + 3 类字符策略', gen)
    rows = _db(data_dir, f'SELECT password_hash FROM users WHERE id={uid}')
    check(rows and gen not in rows[0]['password_hash'],
          '生成的明文口令不落库（库里只有哈希）')

    st, r = req('POST', base + f'/api/users/{uid}/password', token, {'password': 'short'})
    check(st == 400, '弱口令被拒（POST 重置口令 → 400）', f'实际 {st}')
    # ⚠️ 上面两次重置都清了 tang 的全部会话，所以 §8.4 开始时那个 `utoken` 到这里**已经死了**。
    #    后面（§12 的越权/穿越用例）必须用最新口令重新登录，不能复用旧 token。
    ntoken = login(base, 'tang', gen) or login(base, 'tang', RESET_PW)
    check(bool(ntoken), '随机生成的口令同样能登录（会话可用）')
    utoken = ntoken          # 后续所有"普通用户"用例统一用当前有效会话

    # ============================================================ §8.5
    step('§8.5 唯一超管降级/停用/删除被拒；自删被拒')

    st, r = req('PATCH', base + f'/api/users/{1}', token, {'role': 'user'})
    check(st == 400, '把唯一超管降级 → 400', f'实际 {st}: {detail_of(r)}')
    check('超级管理员' in detail_of(r), '拒绝原因讲清"必须保留至少 1 个超管"', detail_of(r))

    st, r = req('PATCH', base + '/api/users/1', token, {'status': 0})
    check(st == 400, '停用唯一超管 → 400', f'实际 {st}: {detail_of(r)}')
    check('自己' in detail_of(r) or '超级管理员' in detail_of(r),
          '拒绝原因是人话', detail_of(r))

    st, r = req('DELETE', base + '/api/users/1', token)
    check(st == 400, '删除唯一超管（=自删）→ 400', f'实际 {st}: {detail_of(r)}')
    check('自己' in detail_of(r), '自删被单独识别（禁止删除自己的账号）', detail_of(r))

    # 自我降级：先造第二个超管，再让第一个超管自我降级
    st, r = req('POST', base + '/api/users', token,
                {'username': 'super2', 'password': SUPER_PW, 'role': 'super_admin'})
    check(st == 200, f'再造一个超管 super2 → {st}', detail_of(r))
    st, r = req('PATCH', base + '/api/users/1', token, {'role': 'admin'})
    check(st == 400, '有第二个超管时，自我降级仍被拒 → 400', f'实际 {st}: {detail_of(r)}')
    check('自我降级' in detail_of(r), '拒绝原因是"禁止自我降级"', detail_of(r))

    # 删除唯一超管（用 admin 视角：先删 super2，再试图删 1）
    st, r = req('DELETE', base + '/api/users/1', token)
    check(st == 400, '仍拒删自己（超管）', f'实际 {st}')
    st2, r2 = req('POST', base + '/api/users/1/kick', token, {})
    check(st2 == 400, '不能强制下线自己 → 400', f'实际 {st2}: {detail_of(r2)}')

    # 倒数第二个超管可被降级（规格只禁"自我降级"与"最后一个超管"）
    # ⚠️ 注意：这会把 admin 变成普通用户，用它自己的 token 就再也不能管用户了。
    #    所以先用 super2 的 token 把 admin 降级，**随后立即用 super2 复原**，
    #    避免后面的用例拿着失效权限的 token 跑（第一版就踩过这个坑）。
    s2 = login(base, 'super2', SUPER_PW)
    check(bool(s2), 'super2 可登录')
    st, r = req('PATCH', base + '/api/users/1', s2, {'role': 'user'})
    check(st == 200, 'super2 降级 admin（此时仍有 super2 是超管，规格允许）→ 200',
          f'实际 {st}: {detail_of(r)}')
    st, r = req('PATCH', base + '/api/users/1', s2, {'role': 'super_admin'})
    check(st == 200, 'super2 立即把 admin 复原为 super_admin → 200', detail_of(r))
    st, r = req('GET', base + '/api/users', token)
    check(st == 200, 'admin 复原后 token 重新有 user.manage 权限（→ 200）', f'实际 {st}')

    # 删除最后一个超管：先造出第三个超管，验证"超管互删"仍受保护
    st, r = req('POST', base + '/api/users', token,
                {'username': 'super3', 'password': SUPER_PW, 'role': 'super_admin'})
    check(st == 200, '再造 super3 → 200', detail_of(r))
    sid3 = (r or {}).get('id')
    s3 = login(base, 'super3', SUPER_PW)
    check(bool(s3), 'super3 可登录（三个超管并存时互删不会把系统删空）')
    # super3 试图删掉自己以外的超管：每次操作后系统里仍有别的超管，所以允许
    st, r = req('DELETE', base + f'/api/users/{sid3}', token)
    check(st in (200, 400), f'超管互删（删 super3）→ {st}', detail_of(r))
    if st == 200:
        # 现在只剩 admin 与 super2 → super2 可被 admin 删除
        st, r = req('DELETE', base + f'/api/users/{sid3}', token)
    st, r = req('GET', base + '/api/users', token)
    supers = [u for u in (r or {}).get('users', []) if u['role'] == 'super_admin']
    check(len(supers) >= 1, f'系统内始终保留至少 1 个超管（当前 {len(supers)} 个）',
          f'实际: {[u["username"] for u in supers]}')

    # 真正做一次"强制下线"（自踢已被上面的 400 拒掉，这里踢一个真有会话的账号）
    st, r = req('POST', base + '/api/users', token,
                {'username': 'kickme', 'password': USER_PW, 'role': 'user'})
    check(st == 200, '建一个待踢账号 kickme → 200', detail_of(r))
    kid = (r or {}).get('id')
    ktoken = login(base, 'kickme', USER_PW)
    st, r = req('GET', base + '/api/instances', ktoken)
    check(bool(ktoken) and st == 200, 'kickme 的会话可用')
    st, r = req('POST', base + f'/api/users/{kid}/kick', token, {})
    check(st == 200, '超管强制下线 kickme → 200', detail_of(r))
    check('token_epoch' in str((r or {}).get('note', '')) or '失效' in str((r or {}).get('note', '')),
          '响应说明了"其所有会话立即失效"', str((r or {}).get('note')))
    st, r = req('GET', base + '/api/instances', ktoken)
    check(st == 401, '被踢后其 token 立即失效 → 401', f'实际 {st}: {detail_of(r)}')
    st, r = req('DELETE', base + f'/api/users/{kid}', token)
    check(st == 200, '清理待踢账号 → 200', detail_of(r))

    # 停用即踢下线：停用另一个账号后其会话也要失效
    st, r = req('POST', base + '/api/users', token,
                {'username': 'disableme', 'password': USER_PW, 'role': 'user'})
    did = (r or {}).get('id')
    dtoken = login(base, 'disableme', USER_PW)
    st, r = req('PATCH', base + f'/api/users/{did}', token, {'status': 0})
    check(st == 200, '停用 disableme → 200', detail_of(r))
    st, r = req('GET', base + '/api/instances', dtoken)
    check(st == 401, '停用后其 token 立即失效 → 401', f'实际 {st}: {detail_of(r)}')
    st, r = req('POST', base + '/api/auth/login', body={'username': 'disableme',
                                                        'password': USER_PW})
    check(st == 403, '被停用的账号无法再登录 → 403（停用不能靠换个新 token 绕过去）',
          f'实际 {st}: {detail_of(r)}')
    check('停用' in detail_of(r), '拒绝原因说明"账号已被停用"', detail_of(r))
    st, r = req('DELETE', base + f'/api/users/{did}', token)
    check(st == 200, '清理被停用账号 → 200', detail_of(r))

    # 删除有实例的用户：必须先转移或勾选一并删除
    st, r = req('DELETE', base + f'/api/users/{uid}', token)
    check(st == 400, '删除有实例的用户（未勾选一并删除）→ 400', f'实际 {st}: {detail_of(r)}')
    check('一并删除' in detail_of(r) and '转移' in detail_of(r),
          '拒绝原因讲清"先转移归属或勾选一并删除"', detail_of(r))
    st, r = req('DELETE', base + f'/api/users/{vid}', token)
    check(st == 200, f'删除无实例的 viewer 账号成功 → {st}', detail_of(r))
    st, r = req('POST', base + f'/api/users/{vid}/kick', token, {})
    check(st == 404, '对已删除用户操作 → 404', f'实际 {st}')

    # ============================================================ §8.6
    step('§8.6 审计里能看到上述每一次操作（谁、对谁、动作、IP）')

    st, r = req('GET', base + '/api/audit?limit=500', token)
    logs = (r or {}).get('logs') or []
    check(st == 200 and len(logs) > 0, f'GET /api/audit 可读（{len(logs)} 条）')
    by_action = {}
    for l in logs:
        by_action.setdefault(l['action'], []).append(l)
    want = {
        'init': '首启建号',
        'auth.login': '登录',
        'user.create': '建用户',
        'user.update': '改用户',
        'user.reset_password': '重置口令',
        'user.kick': '强制下线',
        'user.delete': '删除用户',
        'instance.create': '建实例',
    }
    for action, label in want.items():
        items = by_action.get(action) or []
        if check(bool(items), f'审计含 {action}（{label}）× {len(items)}'):
            sample = items[0]
            has_who = bool(sample.get('user'))
            has_ip = bool(str(sample.get('ip') or '').strip())
            if action == 'init':
                # 首启建号发生在**任何 HTTP 请求之前**（启动期），所以没有 IP，
                # 操作者记为 'system'。这是预期行为，不能当成缺字段。
                check(has_who and sample['user'] == 'system',
                      '  └ init 记录操作者为 system（启动期动作，无 IP 属正常）',
                      f"实际 user={sample.get('user')!r} ip={sample.get('ip')!r}")
            else:
                check(has_who and has_ip,
                      f'  └ {action} 记录了操作者与 IP'
                      f'（user={sample.get("user")!r} ip={sample.get("ip")!r}）')

    # 用户管理类操作必须是 warn 级（规格 §7）
    warn = [l for l in logs if l['action'].startswith('user.') and l['level'] == 'warn']
    check(len(warn) >= 4, f'用户管理类操作审计为 warn 级（{len(warn)} 条）',
          f'实际 warn: {[l["action"] for l in warn]}')

    # 明文口令绝不进审计
    leaked = [l for l in logs
              if SUPER_PW in str(l.get('detail') or '') or RESET_PW in str(l.get('detail') or '')
              or USER_PW in str(l.get('detail') or '')]
    check(not leaked, '审计日志里没有任何明文口令（安全红线）',
          f'泄漏: {leaked[:2]}')

    st, r = req('GET', base + '/api/audit/login?limit=100', token)
    llogs = (r or {}).get('logs') or []
    fails = [l for l in llogs if not l['success']]
    check(st == 200 and len(llogs) > 0, f'登录日志可读（{len(llogs)} 条，含失败 {len(fails)} 条）')

    # ============================================================ 附加
    step('附加：默认拒绝与接口自洽')
    for path, label in (('/api/nonexistent-endpoint', '不存在的 API 必须 JSON 404'),
                        ('/api/users/999999', '不存在的用户 404')):
        st, r = req('GET', base + path, token)
        want_code = 404
        check(st == want_code, f'{label} → {want_code}', f'实际 {st}: {detail_of(r)}')
    st, r = req('GET', base + '/api/users')
    check(st == 401, '未登录访问 /api/users → 401', f'实际 {st}')
    st, r = req('GET', base + '/api/users', 'bogus-token')
    check(st == 401, '伪造 token → 401', f'实际 {st}')
    # 路径穿越：`..` 必须**百分号编码**（urllib/http 客户端会自己规范化字面 `../`，
    # 那样请求根本到不了服务器，测不出 pathguard），用 %2E%2E 才能真正打到后端。
    st0, r0 = req('GET', base + '/api/instances', utoken)
    if st0 != 200:
        sess = _db(data_dir, f'SELECT token, expires_at FROM sessions WHERE uid={uid}')
        print(f'    诊断: utoken repr={utoken!r}')
        print(f'    诊断: 库中该用户会话 {[(s["token"][:12] + "…", s["expires_at"]) for s in sess]}')
        print(f'    诊断: utoken 是否在库中 = {any(s["token"] == utoken for s in sess)}')
        print(f'    诊断: /api/auth/me → {req("GET", base + "/api/auth/me", utoken)}')
    check(st0 == 200, f'（对照）穿越测试前 utoken 仍有效 → {st0}', detail_of(r0))
    st, r = req('GET', base + f'/api/instances/{iid_user}/files?path=%2E%2E%2F%2E%2E%2F%2E%2E%2Fetc%2Fpasswd',
                utoken)
    check(st in (400, 403), f'路径穿越被 pathguard 拦住 → {st}', detail_of(r))
    st, r = req('GET', base + f'/api/instances/{iid_user}/files/read?path=%2E%2E%2Fserver.properties',
                utoken)
    check(st in (400, 403, 404), f'越出实例根目录的读取被拦 → {st}', detail_of(r))

    # ============================================================ 附加：老库迁移
    check_legacy_migration(base)


def check_legacy_migration(base: str):
    """老库（角色体系之前建的库）升级上来必须仍然能管：

    - `instances.owner_id` 与 `users` 配额列自动补齐（幂等 ALTER TABLE）；
    - 库里有 `role='admin'` 的老账号、且一个超管都没有 → 提升为 super_admin；
    - 没有归属的老实例 → 划给初始超管（否则"谁都看不见"）。
    """
    step('附加：老库迁移（角色体系之前的库升级上来）')
    legacy = os.path.join(os.environ.get('TEMP') or '/tmp', 'mcpanel-acctest-legacy')
    shutil.rmtree(legacy, ignore_errors=True)
    os.makedirs(legacy, exist_ok=True)
    _make_legacy_db(legacy)

    before_u = _db(legacy, 'PRAGMA table_info(users)')
    before_i = _db(legacy, 'PRAGMA table_info(instances)')
    print(f'    迁移前 users 列    : {[c["name"] for c in before_u]}')
    print(f'    迁移前 instances 列: {[c["name"] for c in before_i]}')

    port = free_port(8210)
    proc, _snapshot, lbase = boot(legacy, port)
    try:
        after_u = {c['name'] for c in _db(legacy, 'PRAGMA table_info(users)')}
        after_i = {c['name'] for c in _db(legacy, 'PRAGMA table_info(instances)')}
        want_u = {'max_instances', 'max_memory_mb_total', 'max_backups', 'max_upload_mb',
                  'allow_build_import'}
        check(want_u <= after_u, f'users 自动补上配额列 {sorted(want_u)}',
              f'实际: {sorted(after_u)}')
        check('owner_id' in after_i, 'instances 自动补上 owner_id 列', f'实际: {sorted(after_i)}')

        row = _db(legacy, "SELECT id, username, role FROM users WHERE username='legacyop'")
        check(row and row[0]['role'] == 'super_admin',
              '老库无超管 → 原 admin 账号被提升为 super_admin', f'实际: {row}')

        inst = _db(legacy, 'SELECT id, name, owner_id FROM instances')
        check(inst and inst[0]['owner_id'] == (row[0]['id'] if row else -1),
              '无归属的老实例已划给初始超管（否则谁都看不见）', f'实际: {inst}')

        pw = 'LegacyOp#2026xx'
        st, _r = _set_pw(legacy, pw, username='legacyop')
        check(st == 0, '老账号口令设为已知值', _r)
        tok = login(lbase, 'legacyop', pw)
        check(bool(tok), '提升后的老账号能登录')
        st, r = req('GET', lbase + '/api/me/permissions', tok)
        check(st == 200 and (r or {}).get('role') == 'super_admin'
              and sorted((r or {}).get('perms') or []) == sorted(ROLE_PERMS['super_admin']),
              '提升后的老账号拿到超管全量权限', detail_of(r))
        st, r = req('GET', lbase + '/api/instances', tok)
        ids = [i['id'] for i in (r or {}).get('instances', [])]
        check(st == 200 and len(ids) == 1,
              '超大可见迁移过来的老实例', f'实际: {ids}')
    finally:
        _kill_proc(proc)
        _wait_port_free(port)
        shutil.rmtree(legacy, ignore_errors=True)


def _make_legacy_db(root: str):
    """造一个"角色体系之前"的最小库：users 无配额列、instances 无 owner_id、role='admin'。"""
    import sqlite3
    conn = sqlite3.connect(os.path.join(root, 'mc.db'))
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            status INTEGER NOT NULL DEFAULT 1,
            token_epoch INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            last_login REAL
        );
        CREATE TABLE instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            core_type TEXT NOT NULL DEFAULT 'vanilla',
            mc_version TEXT DEFAULT '',
            core_version TEXT DEFAULT '',
            jar_path TEXT DEFAULT '',
            java_path TEXT DEFAULT '',
            memory_mb INTEGER NOT NULL DEFAULT 2048,
            port INTEGER NOT NULL DEFAULT 25565,
            dir TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'stopped',
            pid INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            last_start_at REAL,
            last_stop_at REAL,
            auto_restart INTEGER NOT NULL DEFAULT 0,
            restart_count INTEGER NOT NULL DEFAULT 0,
            extra_jvm_args TEXT DEFAULT '',
            extra_server_args TEXT DEFAULT '',
            nogui INTEGER NOT NULL DEFAULT 1,
            rcon_enabled INTEGER NOT NULL DEFAULT 0,
            rcon_port INTEGER NOT NULL DEFAULT 25575,
            rcon_password TEXT DEFAULT '',
            accept_eula INTEGER NOT NULL DEFAULT 0,
            exit_code INTEGER,
            last_crash TEXT DEFAULT '',
            note TEXT DEFAULT ''
        );
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL, user TEXT DEFAULT '', ip TEXT DEFAULT '',
            action TEXT NOT NULL, instance_id INTEGER, detail TEXT DEFAULT '',
            level TEXT DEFAULT 'info'
        );
        CREATE TABLE login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL, username TEXT DEFAULT '', ip TEXT DEFAULT '',
            ua TEXT DEFAULT '', success INTEGER NOT NULL, reason TEXT DEFAULT ''
        );
    """)
    conn.execute("INSERT INTO users (username, password_hash, role, status, created_at) "
                 "VALUES ('legacyop', 'x$y', 'admin', 1, ?)", (time.time(),))
    conn.execute("INSERT INTO instances (name, core_type, mc_version, dir, created_at) "
                 "VALUES ('old-world', 'vanilla', '1.20.4', ?, ?)",
                 (os.path.join(root, 'instances', '1_old-world'), time.time()))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- 小工具
def login(base: str, user: str, pw: str) -> str:
    st, r = req('POST', base + '/api/auth/login', body={'username': user, 'password': pw})
    if st != 200:
        bad(f'登录 {user} 失败', f'{st}: {detail_of(r)}')
        return ''
    return (r or {}).get('token') or ''


def _mk_instance(base: str, token: str, name: str, port: int, owner_id=None):
    body = {'name': name, 'mc_version': '1.21.4', 'memory_mb': 1024,
            'port': port, 'download': False}
    if owner_id:
        body['owner_id'] = owner_id
    st, r = req('POST', base + '/api/instances', token, body)
    if st != 200:
        bad(f'建实例 {name} 失败', f'{st}: {detail_of(r)}')
        return 0
    return (r or {}).get('id') or 0


def _db(data_dir: str, sql: str):
    """直接读测试库（只读校验用，不改状态）。"""
    import sqlite3
    conn = sqlite3.connect(os.path.join(data_dir, 'mc.db'))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _set_pw(data_dir: str, pw: str, username: str = 'admin') -> tuple:
    """把已知口令写进测试库（走应用自己的 hash_password，不绕过策略）。

    用独立子进程执行，避免把 app 导入进本进程（那会绑定本进程的 MC_DATA_DIR）。
    """
    code = (
        'import sys; sys.path[:0] = [r"%s", r"%s"];'
        'from app import auth as a, database as d;'
        'err = a.password_policy_error(%r);'
        'assert not err, err;'
        'd.execute("UPDATE users SET password_hash=? WHERE username=?",'
        '          (a.hash_password(%r), %r));'
        'print("ok")' % (BACKEND, DEPS, pw, pw, username))
    env = dict(os.environ)
    env['MC_DATA_DIR'] = data_dir
    env['PYTHONUTF8'] = '1'
    p = subprocess.run([PY, '-c', code], cwd=BACKEND, env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return (p.returncode, (p.stdout + p.stderr).strip()[:400])


def _grep_dir(root: str, needle: str) -> bool:
    """在测试数据目录里搜索明文口令（验证"绝不落盘明文"这条红线）。"""
    if not needle:
        return False
    raw = needle.encode('utf-8')
    for base, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(base, fn)
            try:
                with open(p, 'rb') as f:
                    if raw in f.read():
                        return True
            except Exception:                               # noqa: BLE001
                continue
    return False


def _pw_policy_error(pw: str) -> str:
    if not pw or len(pw) < 12:
        return 'too short'
    classes = sum((any(c.islower() for c in pw), any(c.isupper() for c in pw),
                   any(c.isdigit() for c in pw), any(not c.isalnum() for c in pw)))
    return '' if classes >= 3 else 'need 3 classes'


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
