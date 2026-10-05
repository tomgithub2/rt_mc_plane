"""面板设置、审计日志、登录日志、总览。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .. import audit as audit_mod, javaruntime
from ..auth import get_current_user
from ..config import (BACKUP_DIR, DATA_DIR, DOWNLOADS_DIR, INSTANCE_DIR, JAVA_DIR, LOG_DIR,
                      PANEL_VERSION, get_config, save_config)
from ..database import query
from .. import permissions as perms
from ..permissions import require_perm
from ..process_manager import manager, parse_uptime
from ..sources import SOURCE_LABELS

router = APIRouter(prefix='/api', tags=['settings'])

EDITABLE = ['port', 'bind_host', 'site_name', 'session_hours', 'max_login_fails', 'lock_minutes',
            'login_rate_limit', 'api_rate_limit',
            'sample_interval', 'log_ring_lines', 'download_workers', 'default_java',
            'default_jvm_args', 'default_memory_mb', 'backup_keep', 'mirror_prefix',
            'rcon_enabled', 'rcon_host', 'rcon_port', 'rcon_password',
            'curseforge_api_key', 'auto_restart_limit', 'theme']


class SettingsIn(BaseModel):
    port: int = None
    bind_host: str = None
    site_name: str = None
    session_hours: int = None
    max_login_fails: int = None
    lock_minutes: int = None
    login_rate_limit: int = None
    api_rate_limit: int = None
    sample_interval: int = None
    log_ring_lines: int = None
    download_workers: int = None
    default_java: str = None
    default_jvm_args: str = None
    default_memory_mb: int = None
    backup_keep: int = None
    mirror_prefix: str = None
    rcon_enabled: bool = None
    rcon_host: str = None
    rcon_port: int = None
    rcon_password: str = None
    curseforge_api_key: str = None
    auto_restart_limit: int = None
    theme: str = None


@router.get('/settings')
def get_settings(user: dict = Depends(get_current_user)):
    # 面板系统设置（端口/绑定/存储路径/下载源/密钥）→ 只有超级管理员能看能改（规格 §2）
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    cfg = get_config()
    safe = dict(cfg)
    # 敏感值不回传明文，只回传"是否已设置"
    safe['rcon_password_set'] = bool(cfg.get('rcon_password'))
    safe['curseforge_api_key_set'] = bool(cfg.get('curseforge_api_key'))
    safe['rcon_password'] = ''
    safe['curseforge_api_key'] = ''
    return {'ok': True, 'config': safe, 'version': PANEL_VERSION,
            'paths': {'data': DATA_DIR, 'instances': INSTANCE_DIR, 'logs': LOG_DIR,
                      'backups': BACKUP_DIR, 'java': JAVA_DIR, 'downloads': DOWNLOADS_DIR},
            'note': '端口与绑定地址修改后需要重启面板才生效'}


@router.put('/settings')
def put_settings(body: SettingsIn, request: Request, user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_SYSTEM_SETTINGS)
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()
               if v is not None and k in EDITABLE}
    if 'port' in updates and not 1 <= int(updates['port']) <= 65535:
        raise HTTPException(status_code=400, detail='端口不合法')
    if 'sample_interval' in updates and not 1 <= int(updates['sample_interval']) <= 3600:
        raise HTTPException(status_code=400, detail='采样间隔需在 1~3600 秒之间')
    if 'download_workers' in updates and not 1 <= int(updates['download_workers']) <= 8:
        raise HTTPException(status_code=400, detail='并发下载数需在 1~8 之间（避免吃满全机带宽）')
    if 'backup_keep' in updates and not 1 <= int(updates['backup_keep']) <= 100:
        raise HTTPException(status_code=400, detail='备份保留份数需在 1~100 之间')
    if 'auto_restart_limit' in updates and not 0 <= int(updates['auto_restart_limit']) <= 20:
        raise HTTPException(status_code=400, detail='自动重启上限需在 0~20 之间')
    if 'login_rate_limit' in updates and not 1 <= int(updates['login_rate_limit']) <= 10000:
        raise HTTPException(status_code=400, detail='登录限流需在 1~10000 次/60秒 之间')
    if 'api_rate_limit' in updates and not 60 <= int(updates['api_rate_limit']) <= 1000000:
        raise HTTPException(status_code=400, detail='API 限流需在 60~1000000 次/60秒 之间')
    if updates.get('rcon_enabled') is not None:
        updates['rcon_enabled'] = bool(updates['rcon_enabled'])
    cfg = save_config(updates)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'settings.update', detail=f'修改面板设置：{", ".join(updates.keys())}')
    safe = dict(cfg)
    safe['rcon_password'] = ''
    safe['curseforge_api_key'] = ''
    return {'ok': True, 'config': safe, 'note': '端口与绑定地址修改后需要重启面板才生效'}


# ---------------------------------------------------------------- 总览 / 环境
@router.get('/overview')
def overview(user: dict = Depends(get_current_user)):
    import psutil
    # 总览也要按归属过滤：普通用户/只读看不到别人的实例数量与状态（规格 §3）
    if perms.is_admin(user):
        rows = query('SELECT * FROM instances ORDER BY id ASC')
    else:
        rows = query('SELECT * FROM instances WHERE owner_id=? ORDER BY id ASC',
                     (int(user['id']),))
    insts = []
    running = 0
    players = 0
    for r in rows:
        st = manager.status(r['id'])
        if st['running']:
            running += 1
            players += st['players']
        insts.append({'id': r['id'], 'name': r['name'], 'core_type': r['core_type'],
                      'core_label': SOURCE_LABELS.get(r['core_type'], r['core_type']),
                      'mc_version': r['mc_version'], 'port': r['port'],
                      'memory_mb': r['memory_mb'], 'status': st['status'],
                      'running': st['running'], 'pid': st['pid'],
                      'cpu': st['cpu'], 'mem_mb': st['mem_mb'],
                      'players': st['players'], 'tps': st['tps'],
                      'tps_available': st['tps_available'],
                      'uptime': st['uptime'], 'uptime_text': parse_uptime(st['uptime']),
                      'auto_restart': bool(r['auto_restart'])})
    try:
        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        disk = psutil.disk_usage(DATA_DIR)
        host = {'cpu_percent': cpu, 'mem_percent': vm.percent,
                'mem_used_mb': round(vm.used / 1048576), 'mem_total_mb': round(vm.total / 1048576),
                'disk_percent': disk.percent, 'disk_free_gb': round(disk.free / 1073741824, 1),
                'cpu_count': psutil.cpu_count()}
    except Exception:
        host = {}
    return {'ok': True, 'instances': insts, 'host': host, 'version': PANEL_VERSION,
            'counts': {'total': len(rows), 'running': running, 'players': players},
            'scope': 'all' if perms.is_admin(user) else 'mine',
            'is_admin': perms.is_admin(user),
            'java': javaruntime.detect_all()[:5]}


@router.get('/audit')
def audit_logs(limit: int = Query(default=200, ge=1, le=2000), offset: int = 0,
               instance_id: int = None, action: str = '', user: dict = Depends(get_current_user)):
    # 审计日志：规格 §2 —— 超管与管理员可看，普通用户与只读不可
    require_perm(user, perms.P_AUDIT_VIEW)
    sql = 'SELECT * FROM audit_logs WHERE 1=1'
    args = []
    if instance_id:
        sql += ' AND instance_id=?'
        args.append(instance_id)
    if action:
        sql += ' AND action LIKE ?'
        args.append(f'%{action}%')
    sql += ' ORDER BY id DESC LIMIT ? OFFSET ?'
    args += [limit, offset]
    return {'ok': True, 'logs': query(sql, tuple(args)),
            'total': (query('SELECT COUNT(*) AS c FROM audit_logs', one=True) or {}).get('c', 0)}


@router.get('/audit/login')
def login_logs(limit: int = Query(default=100, ge=1, le=1000),
               user: dict = Depends(get_current_user)):
    require_perm(user, perms.P_AUDIT_VIEW)
    return {'ok': True, 'logs': query('SELECT * FROM login_logs ORDER BY id DESC LIMIT ?',
                                      (limit,))}


@router.get('/health')
def health():
    """免鉴权健康检查（仅返回存活与版本，不泄漏任何配置）。"""
    return {'ok': True, 'version': PANEL_VERSION, 'service': 'mc-server-panel'}
