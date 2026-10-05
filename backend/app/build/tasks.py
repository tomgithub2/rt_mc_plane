"""异步导入任务：状态机、进度、取消、region 级强制备份与回滚。

状态：``parsing → mapping → backup → writing(n/N) → done | failed | cancelled``
  · 单实例同时只允许一个导入任务（在实例粒度排队，绝不并发写同一批区块）
  · 备份是**逐字节复制**被触及的 region 文件 + sha256 记录，因此回滚后
    sha256 与导入前完全一致（自检项 2 的硬要求）
  · 写入在区块边界检查取消标志，取消后已写入的区块由调用方决定是否回滚
"""
import hashlib
import io
import json
import os
import shutil
import tarfile
import threading
import time
import traceback

from . import anvil, formats, mapping, plan
from .nbt import Tag

try:
    from ..config import DATA_DIR
    from ..database import execute, now, query
    from .. import audit as audit_mod
except Exception:                                     # pragma: no cover
    DATA_DIR = os.path.join(os.getcwd(), 'data')
    def execute(*a, **k):
        return None

    def query(*a, **k):
        return []

    def now():
        return time.time()

    class _A:
        @staticmethod
        def audit(*a, **k):
            pass
    audit_mod = _A()

TASKS_DIR = os.path.join(DATA_DIR, 'build', 'tasks')
BACKUP_DIR = os.path.join(DATA_DIR, 'build', 'backups')
MAX_CONCURRENT = 4

ST_PARSING = 'parsing'
ST_MAPPING = 'mapping'
ST_BACKUP = 'backup'
ST_WRITING = 'writing'
ST_DONE = 'done'
ST_FAILED = 'failed'
ST_CANCELLED = 'cancelled'
ST_QUEUED = 'queued'

_lock = threading.RLock()
_tasks = {}
_instance_busy = {}
_sem = threading.Semaphore(MAX_CONCURRENT)


class Cancelled(Exception):
    pass


def sha256_file(path: str, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(buf)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class BuildTask:
    __slots__ = ('id', 'instance_id', 'username', 'ip', 'upload_id', 'filename', 'sha256',
                 'schematic', 'origin', 'dimension', 'rotate', 'mirror', 'place_mode',
                 'replace_list', 'include_entities', 'engine', 'do_backup', 'status',
                 'stage', 'message', 'progress', 'total', 'result', 'error', 'cancel',
                 'created_at', 'started_at', 'finished_at', 'backup_dir', 'manifest',
                 'report', 'member', 'rotated_bbox', 'samples')

    def __init__(self, task_id, instance_id, username='', ip='', filename='', **kw):
        self.id = task_id
        self.instance_id = int(instance_id)
        self.username = username
        self.ip = ip
        self.upload_id = kw.get('upload_id', '')
        self.filename = filename
        self.sha256 = kw.get('sha256', '')
        self.schematic = None
        self.origin = tuple(kw.get('origin') or (0, 64, 0))
        self.dimension = kw.get('dimension') or 'overworld'
        self.rotate = int(kw.get('rotate') or 0)
        self.mirror = kw.get('mirror') or 'none'
        self.place_mode = kw.get('place_mode') or 'only_air'
        self.replace_list = list(kw.get('replace_list') or [])
        self.include_entities = bool(kw.get('include_entities'))
        self.engine = kw.get('engine') or 'auto'
        self.do_backup = bool(kw.get('backup', True))
        self.member = kw.get('member') or ''
        self.status = ST_QUEUED
        self.stage = ST_QUEUED
        self.message = '排队中'
        self.progress = 0
        self.total = 0
        self.result = {}
        self.error = ''
        self.report = kw.get('report') or {}
        self.cancel = threading.Event()
        self.created_at = time.time()
        self.started_at = 0.0
        self.finished_at = 0.0
        self.backup_dir = ''
        self.manifest = []
        self.rotated_bbox = None
        self.samples = []

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            'task_id': self.id,
            'instance_id': self.instance_id,
            'status': self.status,
            'stage': self.stage,
            'message': self.message,
            'progress': self.progress,
            'total': self.total,
            'percent': round(self.progress / self.total * 100, 1) if self.total else (
                100 if self.status == ST_DONE else 0),
            'filename': self.filename,
            'sha256': self.sha256,
            'origin': list(self.origin),
            'dimension': self.dimension,
            'rotate': self.rotate,
            'mirror': self.mirror,
            'place_mode': self.place_mode,
            'engine': self.engine,
            'engine_used': self.result.get('engine', ''),
            'error': self.error,
            'result': self.result,
            'backup_dir': self.backup_dir,
            'backup_files': [m['path'] for m in self.manifest],
            'has_backup': bool(self.manifest),
            'samples': self.samples[:12],
            'created_at': self.created_at,
            'started_at': self.started_at,
            'finished_at': self.finished_at,
            'duration': round((self.finished_at or time.time()) - (self.started_at or time.time()), 2)
            if self.started_at else 0,
            'cancellable': self.status in (ST_QUEUED, ST_PARSING, ST_MAPPING, ST_BACKUP, ST_WRITING),
            'username': self.username,
            'report': {k: v for k, v in (self.report or {}).items()
                       if k in ('format', 'size', 'blocks_total', 'blocks_affected',
                                'palette_total', 'chunks_touched', 'bbox', 'warnings')},
        }


def new_id() -> str:
    return 'b' + hashlib.sha1(f'{time.time()}-{os.urandom(8).hex()}'.encode()).hexdigest()[:15]


# ---------------------------------------------------------------- 生命周期

def instance_busy(instance_id: int):
    """该实例上正在跑的任务（不排队的不算）。"""
    with _lock:
        t = _instance_busy.get(int(instance_id))
        if t and t.status in (ST_PARSING, ST_MAPPING, ST_BACKUP, ST_WRITING):
            return t
    return None


def start(task: BuildTask) -> BuildTask:
    with _lock:
        busy = _instance_busy.get(task.instance_id)
        if busy is not None and busy.status in (ST_PARSING, ST_MAPPING, ST_BACKUP, ST_WRITING):
            task.status = ST_QUEUED
            task.message = f'实例上已有导入任务 {busy.id} 在跑，本任务排队等待'
        _tasks[task.id] = task
    _persist(task)
    threading.Thread(target=_run, args=(task,), daemon=True).start()
    return task


def get(task_id: str):
    with _lock:
        t = _tasks.get(task_id)
    if t:
        return t
    return load(task_id)


def list_tasks(instance_id: int = None, limit: int = 50) -> list:
    with _lock:
        items = list(_tasks.values())
    if instance_id is not None:
        items = [t for t in items if t.instance_id == int(instance_id)]
    items.sort(key=lambda t: t.created_at, reverse=True)
    out = [t.to_dict() for t in items[:limit]]
    if len(out) < limit:
        seen = {o['task_id'] for o in out}
        for row in _load_all_persisted():
            if len(out) >= limit:
                break
            if row['task_id'] in seen:
                continue
            if instance_id is not None and int(row.get('instance_id') or 0) != int(instance_id):
                continue
            out.append(row)
    return out


def cancel(task_id: str) -> dict:
    t = get(task_id)
    if not t:
        return {'ok': False, 'error': '任务不存在'}
    if t.status in (ST_DONE, ST_FAILED, ST_CANCELLED):
        return {'ok': False, 'error': f'任务已结束（{t.status}），无法取消'}
    t.cancel.set()
    t.message = '收到取消请求，将在区块边界安全停止…'
    return {'ok': True, 'task_id': task_id, 'note': '已请求取消；写入中的任务会在当前区块写完后停止'}


def _run(task: BuildTask):
    with _sem:
        with _lock:
            busy = _instance_busy.get(task.instance_id)
            if busy is not None and busy.status in (ST_PARSING, ST_MAPPING, ST_BACKUP, ST_WRITING):
                holding = True
            else:
                holding = False
                _instance_busy[task.instance_id] = task
        if holding:
            # 排队：等前一个结束
            while True:
                time.sleep(1.0)
                with _lock:
                    busy = _instance_busy.get(task.instance_id)
                if busy is None or busy.status not in (ST_PARSING, ST_MAPPING, ST_BACKUP,
                                                       ST_WRITING):
                    break
                if task.cancel.is_set():
                    task.status = ST_CANCELLED
                    task.message = '排队中被取消'
                    task.finished_at = time.time()
                    _persist(task)
                    return
            with _lock:
                _instance_busy[task.instance_id] = task
        task.started_at = time.time()
        task.status = ST_PARSING
        task.stage = ST_PARSING
        task.message = '解析建筑文件'
        _persist(task)
        try:
            from . import engines          # 延迟导入，避免与 engines 循环依赖
            engines.run_import(task, progress, _check_cancel)
            task.status = ST_DONE
            task.stage = ST_DONE
            task.message = task.result.get('note') or '导入完成'
        except Cancelled:
            task.status = ST_CANCELLED
            task.stage = ST_CANCELLED
            task.message = '已取消' + ('（已写入的部分可用 rollback 还原）'
                                       if task.result.get('chunks_written') else '')
        except formats.FormatError as e:
            task.status = ST_FAILED
            task.stage = ST_FAILED
            task.error = str(e)
            task.message = f'解析失败：{e}'
        except plan.PreviewError as e:
            task.status = ST_FAILED
            task.stage = ST_FAILED
            task.error = str(e)
            task.message = str(e)
        except anvil.AnvilError as e:
            task.status = ST_FAILED
            task.stage = ST_FAILED
            task.error = str(e)
            task.message = f'世界文件错误：{e}'
        except Exception as e:
            task.status = ST_FAILED
            task.stage = ST_FAILED
            task.error = f'{type(e).__name__}: {e}'
            task.message = f'导入失败：{task.error}'
            task.result['traceback'] = traceback.format_exc()[-2000:]
        finally:
            task.finished_at = time.time()
            with _lock:
                if _instance_busy.get(task.instance_id) is task:
                    _instance_busy.pop(task.instance_id, None)
            _persist(task)
            _audit(task)


def progress(task: BuildTask, stage: str = None, done: int = None, total: int = None,
             message: str = None, **extra):
    if stage:
        task.stage = stage
        if stage in (ST_MAPPING, ST_BACKUP, ST_WRITING):
            task.status = stage
    if done is not None:
        task.progress = int(done)
    if total is not None:
        task.total = int(total)
    if message:
        task.message = message
    if extra:
        task.result.update(extra)


def _check_cancel(task: BuildTask):
    if task.cancel.is_set():
        raise Cancelled()


def _audit(task: BuildTask):
    """审计：所有涉及世界的写操作 level=warn（规格 §8.6）。"""
    detail = (f'建筑导入 {task.filename}（sha256 {str(task.sha256)[:16]}…）'
              f' 实例 {task.instance_id} 维度 {task.dimension} 坐标 {list(task.origin)}'
              f' 引擎 {task.result.get("engine", task.engine)}'
              f' 写入方块 {task.result.get("blocks_written", 0)}'
              f' 耗时 {round((task.finished_at or time.time()) - (task.started_at or 1), 2)}s'
              f' 结果 {task.status}')
    if task.status == ST_DONE:
        audit_mod.audit(task.username, task.ip, 'build.import', task.instance_id, detail,
                        level='warn')
    elif task.status == ST_CANCELLED:
        audit_mod.audit(task.username, task.ip, 'build.import.cancelled', task.instance_id,
                        detail, level='warn')
    else:
        audit_mod.audit(task.username, task.ip, 'build.import.failed', task.instance_id,
                        detail + f' 错误 {task.error}', level='warn')


# ---------------------------------------------------------------- 持久化

def task_dir(task_id: str) -> str:
    return os.path.join(TASKS_DIR, task_id)


def _persist(task: BuildTask):
    try:
        d = task_dir(task.id)
        os.makedirs(d, exist_ok=True)
        with io.open(os.path.join(d, 'task.json'), 'w', encoding='utf-8') as f:
            json.dump(task.to_dict(), f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def load(task_id: str):
    p = os.path.join(task_dir(task_id), 'task.json')
    if not os.path.isfile(p):
        return None
    try:
        with io.open(p, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return None
    t = BuildTask(d.get('task_id') or task_id, d.get('instance_id') or 0,
                  username=d.get('username', ''), filename=d.get('filename', ''),
                  sha256=d.get('sha256', ''))
    t.status = d.get('status', ST_DONE)
    t.stage = d.get('stage', t.status)
    t.message = d.get('message', '')
    t.progress = d.get('progress', 0)
    t.total = d.get('total', 0)
    t.result = d.get('result') or {}
    t.error = d.get('error', '')
    t.origin = tuple(d.get('origin') or (0, 0, 0))
    t.dimension = d.get('dimension', 'overworld')
    t.backup_dir = d.get('backup_dir', '')
    t.samples = d.get('samples') or []
    t.created_at = d.get('created_at', 0)
    t.started_at = d.get('started_at', 0)
    t.finished_at = d.get('finished_at', 0)
    man = os.path.join(t.backup_dir, 'manifest.json') if t.backup_dir else ''
    if man and os.path.isfile(man):
        try:
            with io.open(man, encoding='utf-8') as f:
                t.manifest = (json.load(f) or {}).get('files') or []
        except Exception:
            pass
    return t


def _load_all_persisted():
    out = []
    if not os.path.isdir(TASKS_DIR):
        return out
    for name in sorted(os.listdir(TASKS_DIR), reverse=True)[:200]:
        p = os.path.join(TASKS_DIR, name, 'task.json')
        if not os.path.isfile(p):
            continue
        try:
            with io.open(p, encoding='utf-8') as f:
                out.append(json.load(f))
        except Exception:
            continue
    out.sort(key=lambda d: d.get('created_at') or 0, reverse=True)
    return out


# ---------------------------------------------------------------- 备份 / 回滚

def backup_regions(task: BuildTask, region_paths, world_root: str = '') -> dict:
    """把将被写入的 region 文件逐字节备份到 ``data/build/backups/<task_id>/``。

    返回 ``{'dir':..., 'files':[{'path','backup','sha256','size'}], 'skipped':[...]}``
    """
    dest = os.path.join(BACKUP_DIR, task.id)
    os.makedirs(dest, exist_ok=True)
    files = []
    skipped = []
    for p in sorted(set(region_paths)):
        if not os.path.isfile(p):
            skipped.append({'path': p, 'reason': '文件不存在（导入会新建）'})
            continue
        rel = os.path.relpath(p, world_root) if world_root else os.path.basename(p)
        safe = rel.replace('\\', '/').replace('..', '_').replace(':', '_')
        target = os.path.join(dest, 'files', safe)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(p, target)
        files.append({
            'path': os.path.abspath(p),
            'rel': rel,
            'backup': os.path.abspath(target),
            'sha256': sha256_file(target),
            'size': os.path.getsize(target),
        })
    manifest = {'task_id': task.id, 'instance_id': task.instance_id, 'created_at': time.time(),
                'world_root': world_root, 'files': files, 'skipped': skipped}
    with io.open(os.path.join(dest, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    # 顺手打一个 tar.gz 方便用户下载（与备份模块形态一致，但不依赖它）
    try:
        tgz = os.path.join(dest, f'build-backup-{task.id}.tar.gz')
        with tarfile.open(tgz, 'w:gz') as tf:
            for entry in files:
                tf.add(entry['backup'], arcname=entry['rel'])
            mf = os.path.join(dest, 'manifest.json')
            tf.add(mf, arcname='manifest.json')
    except Exception:
        pass
    task.backup_dir = dest
    task.manifest = files
    return manifest


def rollback(task: BuildTask, by: str = '', ip: str = '') -> dict:
    """用备份还原被触及的 region 文件，并校验 sha256 与导入前完全一致。"""
    if not task.manifest:
        return {'ok': False, 'error': '该任务没有可用的备份（可能未开启备份或还没开始写入）'}
    restored = []
    mismatch = []
    missing = []
    for entry in task.manifest:
        src = entry.get('backup')
        dst = entry.get('path')
        if not src or not os.path.isfile(src):
            missing.append(entry.get('rel') or dst)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + '.rollback.tmp'
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        got = sha256_file(dst)
        ok = (got == entry.get('sha256'))
        restored.append({'path': dst, 'sha256_before': entry.get('sha256'),
                         'sha256_after': got, 'match': ok,
                         'size': os.path.getsize(dst)})
        if not ok:
            mismatch.append(dst)
    # 备份文件里没有的 region（导入时新建的）应当删除，才能回到「导入前状态」
    removed = []
    for path in task.result.get('created_regions') or []:
        if not any(e.get('path') == path for e in task.manifest):
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed.append(path)
            except Exception:
                pass
    ok = not mismatch and not missing
    detail = (f'回滚任务 {task.id}：还原 {len(restored)} 个 region 文件，'
              f'删除 {len(removed)} 个新建文件，哈希不一致 {len(mismatch)} 个')
    audit_mod.audit(by or task.username, ip or task.ip, 'build.rollback', task.instance_id,
                    detail, level='warn')
    task.result['rolled_back'] = True
    task.result['rollback'] = {'files': restored, 'removed': removed}
    _persist(task)
    return {'ok': ok, 'restored': restored, 'removed': removed, 'missing': missing,
            'sha256_mismatch': mismatch, 'note': detail}


def purge_old_backups(days: int = 14) -> int:
    """清理过期导入备份。"""
    if not os.path.isdir(BACKUP_DIR):
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for name in os.listdir(BACKUP_DIR):
        p = os.path.join(BACKUP_DIR, name)
        try:
            if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        except Exception:
            pass
    return n


def list_backups(instance_id: int = None) -> list:
    out = []
    if not os.path.isdir(BACKUP_DIR):
        return out
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        man = os.path.join(BACKUP_DIR, name, 'manifest.json')
        if not os.path.isfile(man):
            continue
        try:
            with io.open(man, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            continue
        if instance_id is not None and int(d.get('instance_id') or 0) != int(instance_id):
            continue
        out.append({'task_id': d.get('task_id') or name,
                    'instance_id': d.get('instance_id'),
                    'created_at': d.get('created_at'),
                    'files': len(d.get('files') or []),
                    'dir': os.path.join(BACKUP_DIR, name)})
    return out
