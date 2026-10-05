"""统一应用日志、维护（缓存清理 / 占用统计）、插件源探测、开放 API 与 Webhook。

设计要点：面板自身的操作日志由 logging 写入 data/logs/panel.log，
同时提供内存环形缓冲方便前端直接读最近若干行。
"""
import collections
import io
import json
import logging
import os
import shutil
import threading
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import audit as audit_mod
from ..auth import get_current_user
from ..config import (BACKUP_DIR, DATA_DIR, DOWNLOADS_DIR, INSTANCE_DIR, JAVA_DIR, LOG_DIR,
                      TMP_DIR, get_config, save_config)
from ..database import execute, now, query
from .. import permissions as perms
from ..permissions import require_instance, require_perm
from ..process_manager import manager
from ..sources import SOURCE_LABELS

router = APIRouter(prefix='/api', tags=['maintenance'])

# ---------------------------------------------------------------- 应用日志
_RING = collections.deque(maxlen=3000)
_panel_log = os.path.join(LOG_DIR, 'panel.log')


class _RingHandler(logging.Handler):
    def emit(self, record):
        try:
            _RING.append({'ts': record.created, 'level': record.levelname.lower(),
                          'text': self.format(record)})
        except Exception:
            pass


def install_log_handler():
    """把面板自身的日志接进环形缓冲 + 落盘（main.py 启动时调用一次）。"""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, _RingHandler):
            return
    h = _RingHandler()
    h.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(name)s: %(message)s', '%H:%M:%S'))
    root.addHandler(h)
    try:
        fh = logging.FileHandler(_panel_log, encoding='utf-8')
        fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(name)s: %(message)s'))
        root.addHandler(fh)
    except Exception:
        pass


def app_log(line: str, level: str = 'info'):
    logging.getLogger('mcpanel.app').log(
        {'info': logging.INFO, 'warn': logging.WARNING, 'error': logging.ERROR}.get(level, logging.INFO),
        line)


@router.get('/logs/app')
def read_app_log(limit: int = Query(default=200, ge=1, le=3000),
                 level: str = '', user: dict = Depends(get_current_user)):
    # 面板自身日志是**全局**的：只给能看审计的角色（超管/管理员），普通用户与只读看不到
    require_perm(user, perms.P_AUDIT_VIEW)
    lines = list(_RING)
    if level:
        lines = [l for l in lines if l['level'] == level]
    files = []
    if os.path.isdir(LOG_DIR):
        for fn in sorted(os.listdir(LOG_DIR)):
            p = os.path.join(LOG_DIR, fn)
            if os.path.isfile(p):
                files.append({'name': fn, 'size': os.path.getsize(p),
                              'mtime': os.path.getmtime(p)})
    return {'ok': True, 'lines': lines[-limit:], 'files': files, 'total': len(lines)}


@router.get('/logs/app/download')
def download_app_log(user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_AUDIT_VIEW)
    if not os.path.isfile(_panel_log):
        # 退化：把环形缓冲导出
        tmp = os.path.join(TMP_DIR, 'panel-log-%d.txt' % int(time.time()))
        with io.open(tmp, 'w', encoding='utf-8') as f:
            for l in _RING:
                f.write(l['text'] + '\n')
        return FileResponse(tmp, media_type='text/plain; charset=utf-8', filename='panel.log')
    return FileResponse(_panel_log, media_type='text/plain; charset=utf-8', filename='panel.log')


@router.get('/logs/files')
def instance_log_files(iid: int, user: dict = Depends(get_current_user)):
    # 实例日志：属主/管理员/只读都能看（只读档含"控制台/状态/日志"，见规格 §2）
    row = require_instance(user, iid)
    from ..config import instance_dir
    d = os.path.join(instance_dir(row), 'logs')
    out = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d), reverse=True):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                out.append({'name': fn, 'size': os.path.getsize(p), 'mtime': os.path.getmtime(p)})
    return {'ok': True, 'files': out}


# ---------------------------------------------------------------- 占用与清理
def _dir_size(path: str, cap: int = 100 * 1024 ** 3) -> int:
    total = 0
    if not os.path.isdir(path):
        return 0
    for base, dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(base, fn))
            except Exception:
                pass
        if total > cap:
            break
    return total


@router.get('/maintenance/usage')
def usage(user: dict = Depends(get_current_user)):
    # 全盘占用/库大小/路径属于面板系统信息 → 只有超管能看
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    return {'ok': True,
            'usage': {
                '数据目录 backend/data': _dir_size(DATA_DIR),
                '实例目录 instances': _dir_size(INSTANCE_DIR),
                '备份 backups': _dir_size(BACKUP_DIR),
                'Java 运行时 java': _dir_size(JAVA_DIR),
                '下载缓存 downloads': _dir_size(DOWNLOADS_DIR),
                '临时文件 tmp': _dir_size(TMP_DIR),
                '面板日志 logs': _dir_size(LOG_DIR),
            },
            'metrics_rows': (query('SELECT COUNT(*) AS c FROM metrics', one=True) or {}).get('c', 0),
            'audit_rows': (query('SELECT COUNT(*) AS c FROM audit_logs', one=True) or {}).get('c', 0),
            'crash_rows': (query('SELECT COUNT(*) AS c FROM crash_logs', one=True) or {}).get('c', 0),
            'download_rows': (query('SELECT COUNT(*) AS c FROM downloads', one=True) or {}).get('c', 0),
            'db_size': os.path.getsize(os.path.join(DATA_DIR, 'mc.db')) if
                       os.path.isfile(os.path.join(DATA_DIR, 'mc.db')) else 0,
            'paths': {'data': DATA_DIR, 'logs': LOG_DIR, 'instances': INSTANCE_DIR}}


@router.post('/maintenance/clean-tmp')
def clean_tmp(request: Request, hours: int = 24, user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    removed, freed = 0, 0
    cutoff = time.time() - hours * 3600
    for d in (TMP_DIR, DOWNLOADS_DIR):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    freed += os.path.getsize(p)
                    os.remove(p)
                    removed += 1
            except Exception:
                pass
    execute('DELETE FROM downloads WHERE status IN (?,?) AND started_at < ?',
            ('done', 'failed', cutoff))
    audit_mod.audit(user['username'], get_client_ip(request), 'maintenance.clean_tmp',
                    detail=f'清理临时文件 {removed} 个，释放 {freed} 字节')
    return {'ok': True, 'removed': removed, 'freed': freed}


@router.post('/maintenance/clean-metrics')
def clean_metrics(request: Request, days: int = 7, user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    before = (query('SELECT COUNT(*) AS c FROM metrics', one=True) or {}).get('c', 0)
    execute('DELETE FROM metrics WHERE ts < ?', (now() - days * 86400,))
    after = (query('SELECT COUNT(*) AS c FROM metrics', one=True) or {}).get('c', 0)
    audit_mod.audit(user['username'], get_client_ip(request), 'maintenance.clean_metrics',
                    detail=f'清理 {days} 天前监控数据：{before - after} 行')
    return {'ok': True, 'deleted': before - after, 'remain': after}


@router.post('/maintenance/clean-logs')
def clean_logs(request: Request, keep_latest: bool = True, user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    removed, freed = 0, 0
    for row in query('SELECT * FROM instances'):
        from ..config import instance_dir
        d = os.path.join(instance_dir(row), 'logs')
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if keep_latest and fn == 'latest.log':
                continue
            p = os.path.join(d, fn)
            try:
                if os.path.isfile(p):
                    freed += os.path.getsize(p)
                    os.remove(p)
                    removed += 1
            except Exception:
                pass
    audit_mod.audit(user['username'], get_client_ip(request), 'maintenance.clean_logs',
                    detail=f'清除历史日志 {removed} 个，释放 {freed} 字节')
    return {'ok': True, 'removed': removed, 'freed': freed}


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else ''


# ---------------------------------------------------------------- 插件源探测
@router.get('/plugins-probe')
def plugins_probe(user: dict = Depends(get_current_user)):
    from .. import pluginsources
    return {'ok': True, 'results': pluginsources.probe()}


# ---------------------------------------------------------------- 批量操作
class BatchIn(BaseModel):
    action: str
    ids: list = []
    confirm: bool = False


@router.post('/instances-batch')
def batch(body: BatchIn, request: Request, user: dict = Depends(get_current_user)):
    """批量启停/重启（多服务器管理）。

    ⚠️ 逐个实例过权限：普通用户只能批量操作**自己的**实例，
    别人的实例在该次响应里单独返回 403 原因（不影响其余项）。
    """
    if body.action not in ('start', 'stop', 'restart', 'kill'):
        raise HTTPException(status_code=400, detail='不支持的批量动作')
    need = perms.P_INSTANCE_COMMAND
    if body.action == 'start':
        need = perms.P_INSTANCE_START
    elif body.action in ('stop', 'kill'):
        need = perms.P_INSTANCE_STOP
    results = []
    for iid in body.ids:
        row = query('SELECT id,name FROM instances WHERE id=?', (iid,), one=True)
        if not row:
            results.append({'id': iid, 'ok': False, 'error': '实例不存在'})
            continue
        try:
            require_instance(user, iid, need)
        except HTTPException as exc:
            results.append({'id': iid, 'name': row['name'], 'ok': False,
                            'error': str(exc.detail), 'denied': True})
            continue
        try:
            r = getattr(manager, body.action)(iid, by=user['username'])
            results.append({'id': iid, 'name': row['name'], 'ok': bool(r.get('ok', True)),
                            'error': r.get('error', '')})
        except Exception as e:
            results.append({'id': iid, 'name': row['name'], 'ok': False, 'error': str(e)})
    okn = len([r for r in results if r.get('ok')])
    denied = len([r for r in results if r.get('denied')])
    audit_mod.audit(user['username'], get_client_ip(request), 'instance.batch', None,
                    f'批量 {body.action}：{okn}/{len(results)} 成功'
                    + (f'，{denied} 个因权限不足被拒' if denied else ''))
    return {'ok': True, 'results': results, 'success': okn, 'total': len(results),
            'denied': denied}


# ---------------------------------------------------------------- 打开目录（本机）
@router.post('/maintenance/open-dir')
def open_dir(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """在本机文件管理器中打开目录（仅本机可用，服务器环境会失败）。"""
    import subprocess
    import sys
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    what = str(body.get('which') or 'data')
    paths = {'data': DATA_DIR, 'logs': LOG_DIR, 'instances': INSTANCE_DIR,
             'backups': BACKUP_DIR, 'java': JAVA_DIR}
    p = paths.get(what)
    if not p or not os.path.isdir(p):
        raise HTTPException(status_code=404, detail='目录不存在')
    try:
        if sys.platform == 'win32':
            os.startfile(p)  # noqa: S606
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', p])
        else:
            subprocess.Popen(['xdg-open', p])
    except Exception as e:
        return {'ok': False, 'error': f'无法打开（当前为无桌面环境？）：{e}', 'path': p}
    return {'ok': True, 'path': p}


# ---------------------------------------------------------------- 开放 API / Webhook
class WebhookIn(BaseModel):
    url: str = ''
    events: list = []
    enabled: bool = False


@router.get('/webhook')
def get_webhook(user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    cfg = get_config()
    return {'ok': True, 'webhook': cfg.get('webhook') or {'url': '', 'events': [], 'enabled': False},
            'events': ['instance.start', 'instance.stop', 'instance.crash', 'backup.create',
                       'cron.run', 'auth.login']}


@router.put('/webhook')
def put_webhook(body: WebhookIn, user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    cfg = get_config()
    cfg['webhook'] = {'url': body.url.strip(), 'events': body.events, 'enabled': bool(body.enabled)}
    # webhook 不在 DEFAULTS 白名单里，直接写文件
    import json as _json
    from ..config import CONFIG_FILE
    with io.open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)
    return {'ok': True, 'webhook': cfg['webhook']}


def fire_webhook(event: str, payload: dict):
    """事件触发时异步 POST（失败静默，绝不影响主流程）。"""
    cfg = get_config()
    wh = cfg.get('webhook') or {}
    if not wh.get('enabled') or not wh.get('url'):
        return
    if wh.get('events') and event not in wh['events']:
        return

    def _post():
        try:
            import urllib.request
            data = json.dumps({'event': event, 'ts': time.time(), 'payload': payload},
                              ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(wh['url'], data=data,
                                         headers={'Content-Type': 'application/json',
                                                  'User-Agent': 'mc-server-panel/0.1'})
            urllib.request.urlopen(req, timeout=8).read(64)
        except Exception:
            pass
    threading.Thread(target=_post, daemon=True).start()
