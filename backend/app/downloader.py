"""下载引擎：多候选直链降级、带进度、哈希校验、并发限制、可失败降级。

进度落在 downloads 表 + 内存字典，前端轮询 /api/downloads/{id} 或看列表。

语义（P0-1 收口）
  · `status`: pending → downloading → done | failed（兼容旧前端）
  · `state` : running | done | failed（新前端用；pending/downloading 都算 running）
  · `progress`: 0~100（= 旧字段 percent）
  · `ok`     : **只有真正落盘且校验通过（含哈希 / 长度 / zip 结构）后才为 True**
  · `verified` / `verified_hashes`: 是否做过校验、校验了哪些摘要
  · `urls`   : 候选直链列表（官方 + BMCLAPI 镜像），按序重试，`used_url`/`used_via` 记录实际用的那个
"""
import hashlib
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile

from .config import DOWNLOADS_DIR, get_config
from .database import execute, now, query

UA = 'guanwang/mc/0.1 (+local)'
_tasks = {}
_lock = threading.RLock()
_sem = None
_inflight = ('pending', 'downloading')


def _semaphore():
    global _sem
    with _lock:
        if _sem is None:
            _sem = threading.Semaphore(max(1, int(get_config().get('download_workers', 2))))
        return _sem


def _safe_name(name: str) -> str:
    name = os.path.basename(str(name or 'download.bin'))
    return re.sub(r'[^A-Za-z0-9._\-+]', '_', name)[:120] or 'download.bin'


def _mirror(url: str) -> str:
    """可选镜像前缀（如 BMCLAPI），配置留空则直连。"""
    prefix = (get_config().get('mirror_prefix') or '').strip().rstrip('/')
    if not prefix:
        return url
    for host in ('launchermeta.mojang.com', 'piston-meta.mojang.com',
                 'launcher.mojang.com', 'piston-data.mojang.com'):
        if host in url:
            path = url.split(host, 1)[1]
            return prefix + path
    return url


def hasher(name: str):
    if name == 'sha256':
        return hashlib.sha256()
    if name == 'sha1':
        return hashlib.sha1()
    if name == 'md5':
        return hashlib.md5()
    return None


def _norm_candidates(url, urls, mirrors) -> list:
    """统一成 [{'url','via'}]，官方在前、镜像在后，去重。"""
    out, seen = [], set()
    seq = []
    if urls:
        for item in urls:
            if isinstance(item, dict):
                seq.append((item.get('url'), item.get('via') or 'official'))
            else:
                seq.append((item, 'official'))
    if url:
        seq.insert(0, (url, 'official'))
    for item in (mirrors or []):
        if isinstance(item, dict):
            seq.append((item.get('url'), item.get('via') or 'mirror'))
        else:
            seq.append((item, 'mirror'))
    for u, tag in seq:
        if not u:
            continue
        m = _mirror(u)
        cand = m or u
        if cand in seen:
            continue
        seen.add(cand)
        out.append({'url': cand, 'via': tag if cand == u else (tag or 'mirror')})
    return out


def start_download(url: str, dest: str, label: str = '', sha1: str = '', sha256: str = '',
                   kind: str = 'jar', urls=None, md5: str = '', size: int = 0,
                   mirrors=None) -> str:
    """提交下载任务，返回 task_id。

    urls: 候选直链列表（[{'url','via'}] 或 [str]），按序尝试，任一成功即完成。
    size: 预期字节数（源提供时用于完整性校验）。
    """
    tid = uuid.uuid4().hex[:16]
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cands = _norm_candidates(url, urls, mirrors)
    if not cands and url:
        cands = [{'url': url, 'via': 'official'}]
    rec = {'id': tid, 'kind': kind, 'label': label or os.path.basename(dest),
           'url': (cands[0]['url'] if cands else url), 'urls': cands,
           'dest': dest, 'total': int(size or 0), 'done': 0, 'status': 'pending', 'error': '',
           'sha1': sha1, 'sha256': sha256, 'md5': md5, 'expect_size': int(size or 0),
           'started_at': now(), 'finished_at': None, 'speed': 0.0,
           'used_url': '', 'used_via': '', 'verified': False, 'verified_hashes': []}
    with _lock:
        _tasks[tid] = rec
    execute('INSERT OR REPLACE INTO downloads (id, kind, label, url, dest, total, done, status, '
            'error, started_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (tid, kind, rec['label'], rec['url'], dest, 0, 0, 'pending', '', rec['started_at']))
    threading.Thread(target=_run, args=(tid,), daemon=True).start()
    return tid


def _update(tid: str, **fields):
    with _lock:
        rec = _tasks.get(tid)
        if rec:
            rec.update(fields)
    keys = [k for k in fields if k in ('total', 'done', 'status', 'error', 'finished_at')]
    if keys:
        sql = 'UPDATE downloads SET ' + ','.join(f'{k}=?' for k in keys) + ' WHERE id=?'
        execute(sql, tuple(fields[k] for k in keys) + (tid,))


def _cleanup(part: str):
    try:
        if os.path.isfile(part):
            os.remove(part)
    except Exception:
        pass


def _download_one(tid: str, rec: dict, cand: dict, resume: dict = None,
                  attempts: int = 3) -> dict:
    """下载单个候选直链；成功返回 {'ok':True,'bytes':n}，失败抛异常。

    **慢源/停滞源支持断点续传**：有些源（实测 Quilt 的 maven）会长时间零数据，
    一次 `read()` 一旦超过 socket 超时就整段失败 —— 而它其实**能下，只是极慢**
    （8.5 MB 要几分钟）。所以这里对同一个候选重试若干次，每次带
    `Range: bytes=<已有字节>-` 接着写 `.part`，并把增量哈希状态一并延续，
    这样最终校验仍然覆盖完整文件。
    """
    dest = rec['dest']
    part = dest + '.part'
    url = cand['url']
    state = resume if resume is not None else {}
    last_err = None
    # 总时长上限：45 秒只是"单次 read 无数据"的超时，**慢速滴数据可以无限拖**
    # （实测某源 8.5MB 拖了几分钟）。这里给同一个候选加一个总预算，
    # 超了就交给下一个候选/报错，别让一个慢源把整个任务占死。
    budget = float(os.environ.get('MC_DL_CAND_BUDGET') or 600)
    deadline = time.time() + budget

    for attempt in range(1, max(1, attempts) + 1):
        if time.time() > deadline:
            raise last_err or TimeoutError(f'候选源超时预算 {int(budget)}s 用尽：{url}')
        # 已有多少字节可以接着下
        have = 0
        if state.get('done'):
            have = int(state['done'])
        elif os.path.exists(part):
            try:
                have = os.path.getsize(part)
            except OSError:
                have = 0
        if state.get('restart'):
            have = 0
            state['restart'] = False

        h1 = state.get('h1') if have else (hasher('sha1') if rec.get('sha1') else None)
        h2 = state.get('h2') if have else (hasher('sha256') if rec.get('sha256') else None)
        h3 = state.get('h3') if have else (hasher('md5') if rec.get('md5') else None)
        if have and not (h1 or h2 or h3 or not (rec.get('sha1') or rec.get('sha256') or rec.get('md5'))):
            have = 0                      # 哈希状态丢了就不能续，只能重来
            h1 = hasher('sha1') if rec.get('sha1') else None
            h2 = hasher('sha256') if rec.get('sha256') else None
            h3 = hasher('md5') if rec.get('md5') else None

        headers = {'User-Agent': UA}
        if have:
            headers['Range'] = 'bytes=%d-' % have
        req = urllib.request.Request(url, headers=headers)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                ranged = (getattr(r, 'status', None) == 206)
                if have and not ranged:
                    # 服务器不支持 Range：从头来（哈希也要重置）
                    have = 0
                    h1 = hasher('sha1') if rec.get('sha1') else None
                    h2 = hasher('sha256') if rec.get('sha256') else None
                    h3 = hasher('md5') if rec.get('md5') else None
                clen = int(r.headers.get('Content-Length') or 0)
                total = (have + clen) if ranged else clen
                _update(tid, total=total, used_url=url, used_via=cand.get('via', ''),
                        done=have)
                done = have
                last_ui = 0.0
                with open(part, 'ab' if have else 'wb') as f:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        if h1:
                            h1.update(chunk)
                        if h2:
                            h2.update(chunk)
                        if h3:
                            h3.update(chunk)
                        done += len(chunk)
                        if time.time() - last_ui > 0.3:
                            last_ui = time.time()
                            _update(tid, done=done,
                                    speed=round((done - have) /
                                                max(0.001, time.time() - t0) / 1048576, 2))
                _update(tid, done=done,
                        speed=round((done - have) / max(0.001, time.time() - t0) / 1048576, 2))
        except Exception as e:                                # noqa: BLE001
            last_err = e
            # 把"已经下到哪、哈希算到哪"留给下一次尝试
            state.update({'done': 0 if state.get('restart') else _part_size(part),
                          'h1': h1, 'h2': h2, 'h3': h3})
            if attempt < attempts:
                continue
            raise

        if total and done != total:
            last_err = ValueError(f'下载不完整：收到 {done} 字节，Content-Length 为 {total}')
            state.update({'done': done, 'h1': h1, 'h2': h2, 'h3': h3})
            if attempt < attempts and done < total:
                continue                                      # 续传补齐
            raise last_err
        state.update({'done': done, 'h1': h1, 'h2': h2, 'h3': h3})
        break

    # ---- 校验（只有全部通过才落盘）
    verified = []
    if h2:
        got = h2.hexdigest()
        if got.lower() != str(rec['sha256']).lower():
            raise ValueError(f'sha256 校验失败：期望 {rec["sha256"][:16]}…，实际 {got[:16]}…')
        verified.append('sha256')
    if h1:
        got = h1.hexdigest()
        if got.lower() != str(rec['sha1']).lower():
            raise ValueError(f'sha1 校验失败：期望 {rec["sha1"][:16]}…，实际 {got[:16]}…')
        verified.append('sha1')
    if h3:
        got = h3.hexdigest()
        if got.lower() != str(rec['md5']).lower():
            raise ValueError(f'md5 校验失败：期望 {rec["md5"][:16]}…，实际 {got[:16]}…')
        verified.append('md5')
    if rec.get('expect_size') and done != int(rec['expect_size']):
        raise ValueError(f'文件大小与源声明不符：期望 {rec["expect_size"]}，实际 {done}')
    if rec['dest'].lower().endswith('.jar'):
        try:
            if not zipfile.is_zipfile(part):
                raise ValueError('下载内容不是合法 jar（zip 结构校验失败）')
            verified.append('zip')
        except zipfile.BadZipFile as e:
            raise ValueError(f'jar 结构校验失败：{e}')
    os.replace(part, dest)
    return {'ok': True, 'bytes': done, 'verified': verified}


def _part_size(path: str) -> int:
    try:
        return os.path.getsize(path) if os.path.exists(path) else 0
    except OSError:
        return 0


def _run(tid: str):
    rec = _tasks.get(tid)
    if not rec:
        return
    sem = _semaphore()
    with sem:
        part = rec['dest'] + '.part'
        _update(tid, status='downloading')
        cands = list(rec.get('urls') or [])
        if not cands and rec.get('url'):
            cands = [{'url': rec['url'], 'via': 'official'}]
        errors = []
        for idx, cand in enumerate(cands):
            try:
                res = _download_one(tid, rec, cand)
                _update(tid, status='done', finished_at=now(), error='',
                        verified=True, verified_hashes=res.get('verified') or [],
                        urls_tried=errors)
                return
            except urllib.error.HTTPError as e:
                _cleanup(part)
                errors.append(f'{cand.get("via", "")} {cand["url"]} → HTTP {e.code} {e.reason}')
            except urllib.error.URLError as e:
                _cleanup(part)
                errors.append(f'{cand.get("via", "")} {cand["url"]} → 网络不可达：'
                              f'{getattr(e, "reason", e)}')
            except Exception as e:
                _cleanup(part)
                errors.append(f'{cand.get("via", "")} {cand["url"]} → {type(e).__name__}: {e}')
            if idx + 1 < len(cands):
                _update(tid, done=0, error='候选源失败，正在换源重试…',
                        note=f'{errors[-1]}')
        _update(tid, status='failed', finished_at=now(), verified=False,
                error=('全部候选源失败：' + '；'.join(errors))[:1000] if errors else '没有可用直链',
                urls_tried=errors)


def _reconcile():
    """面板重启后，DB 里还挂在 pending/downloading 的任务其实已经中断 → 如实标记失败。"""
    try:
        rows = query('SELECT id, dest FROM downloads WHERE status IN (?,?)', _inflight)
    except Exception:
        return
    for r in rows:
        with _lock:
            alive = r['id'] in _tasks
        if alive:
            continue
        try:
            execute('UPDATE downloads SET status=?, error=?, finished_at=? WHERE id=?',
                    ('failed', '面板重启，任务已中断（请重新下载）', now(), r['id']))
        except Exception:
            pass
        _cleanup(str(r.get('dest') or '') + '.part')


def state_of(status: str) -> str:
    if status == 'done':
        return 'done'
    if status == 'failed':
        return 'failed'
    return 'running'


def get(tid: str) -> dict:
    _reconcile()
    with _lock:
        rec = _tasks.get(tid)
        if rec:
            out = dict(rec)
        else:
            out = query('SELECT * FROM downloads WHERE id=?', (tid,), one=True)
    if not out:
        return {'ok': False, 'error': '任务不存在'}
    total = out.get('total') or 0
    done = out.get('done') or 0
    out['percent'] = round(done / total * 100, 1) if total else (100.0 if out.get('status') == 'done' else 0.0)
    out['progress'] = out['percent']
    out['state'] = state_of(out.get('status') or '')
    # ok 只在"落盘 + 校验通过"后为真
    out['ok'] = out.get('status') == 'done'
    out['done'] = done
    out.pop('sha1', None)
    out.pop('sha256', None)
    out.pop('md5', None)
    return out


def list_tasks(limit: int = 50) -> list:
    _reconcile()
    rows = query('SELECT * FROM downloads ORDER BY started_at DESC LIMIT ?', (limit,))
    for r in rows:
        total = r.get('total') or 0
        done = r.get('done') or 0
        r['percent'] = round(done / total * 100, 1) if total else (
            100.0 if r.get('status') == 'done' else 0.0)
        r['progress'] = r['percent']
        r['state'] = state_of(r.get('status') or '')
        with _lock:
            rec = _tasks.get(r['id'])
        if rec:
            r['speed'] = rec.get('speed', 0)
            r['used_url'] = rec.get('used_url', '')
            r['used_via'] = rec.get('used_via', '')
            r['verified'] = rec.get('verified', False)
    return rows


def active_tasks() -> list:
    """当前进程里真正在跑（pending/downloading）的任务。"""
    with _lock:
        return [dict(r) for r in _tasks.values() if r.get('status') in _inflight]


def active_for(paths) -> dict:
    """找出正在写入给定路径之一的下载任务（用于 start 前置校验）。

    paths: 一组绝对路径（实例 jar_path / 实例目录）。
    返回最靠前的一个任务 dict；没有则 None。
    """
    want = set()
    for p in (paths or []):
        if not p:
            continue
        try:
            want.add(os.path.normcase(os.path.abspath(p)))
        except Exception:
            continue
    for rec in active_tasks():
        dest = rec.get('dest') or ''
        if not dest:
            continue
        key = os.path.normcase(os.path.abspath(dest))
        if key in want:
            return rec
        for w in want:
            if key.startswith(w.rstrip('\\/') + os.sep):
                return rec
    return None


def wait(tid: str, timeout: float = 300.0, poll: float = 0.3) -> dict:
    """同步等待一个任务结束（安装器等小文件用）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = get(tid)
        if rec.get('status') in ('done', 'failed'):
            return rec
        time.sleep(poll)
    rec = get(tid)
    rec['ok'] = False
    rec['error'] = rec.get('error') or '下载超时'
    return rec


def download_sync(url: str, dest: str, sha1: str = '', sha256: str = '', timeout: int = 300,
                  md5: str = '', urls=None, size: int = 0) -> dict:
    """同步下载（小文件用，如安装器二次拉取）。"""
    tid = start_download(url, dest, label=os.path.basename(dest), sha1=sha1, sha256=sha256,
                         kind='sync', md5=md5, urls=urls, size=size)
    return wait(tid, timeout)
