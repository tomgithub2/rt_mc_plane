"""实例配置：server.properties 可视化、eula、启动参数、jar 选择。"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import audit as audit_mod, javaruntime, mcprops, serverctl
from ..auth import get_current_user
from ..config import instance_dir
from ..database import execute, query
from .. import permissions as perms
from ..permissions import require_instance
from ..process_manager import manager

router = APIRouter(prefix='/api/instances/{iid}/config', tags=['config'])

#: 改这些键等于改端口/绑定 → 需要 `instance.settings_network`（规格 §2：普通用户不可改）
_NETWORK_PROPS = {'server-port', 'rcon.port', 'query.port', 'server-ip',
                  'enable-rcon', 'network-compression-threshold'}


def _row(iid: int, user: dict = None, write: bool = False) -> dict:
    """取实例行 + 实例级权限校验（读=能看即可；写=须为属主/管理员且可改配置）。"""
    if user is None:
        raise HTTPException(status_code=401, detail='未登录')
    if write:
        return require_instance(user, iid, perms.P_SETTINGS)
    return require_instance(user, iid)


def _command(row: dict) -> dict:
    """最终启动命令行（渲染给用户看；与 process_manager.build_command 保持一致）。"""
    detail = javaruntime.render_command(row)
    detail['command_preview'] = ' '.join(manager.build_command(row))
    detail['actual_command'] = detail['command_preview']
    detail['workdir'] = instance_dir(row)
    return detail


class PropsIn(BaseModel):
    updates: dict


class StartupIn(BaseModel):
    memory_mb: int = None
    extra_jvm_args: str = None
    extra_server_args: str = None
    nogui: bool = None
    java_path: str = None
    auto_restart: bool = None
    rcon_enabled: bool = None
    rcon_port: int = None
    rcon_password: str = None


@router.get('/properties')
def get_properties(iid: int, user: dict = Depends(get_current_user)):
    row = _row(iid, user)
    path = os.path.join(instance_dir(row), 'server.properties')
    model = mcprops.read_props(path)
    rows = mcprops.annotate(model)
    # 未出现的常用键也提供给前端（方便一键补全）
    known = {r['key'] for r in rows if r.get('kind') == 'pair'}
    missing = [{'key': k, 'label': lbl, 'type': typ, 'desc': desc}
               for k, lbl, typ, desc in mcprops.SCHEMA if k not in known]
    return {'ok': True, 'exists': model['exists'], 'path': path, 'rows': rows,
            'props': model['props'], 'missing': missing,
            'schema': [{'key': k, 'label': l, 'type': t, 'desc': d} for k, l, t, d in mcprops.SCHEMA]}


@router.put('/properties')
def put_properties(iid: int, body: PropsIn, request: Request,
                   user: dict = Depends(get_current_user)):
    # server.properties 里既有普通玩法项、也有**端口/绑定**项：
    # 命中网络键就必须额外具备 `instance.settings_network`（规格 §2）。
    touched = set((body.updates or {}).keys())
    if touched & _NETWORK_PROPS:
        require_instance(user, iid, perms.P_SETTINGS)
    row = _row(iid, user, write=True)
    path = os.path.join(instance_dir(row), 'server.properties')
    r = mcprops.write_props(path, body.updates)
    if not r.get('ok'):
        raise HTTPException(status_code=400, detail=r.get('error', '写入失败'))
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'config.properties', iid,
                    f'修改 server.properties：{", ".join(list(body.updates)[:20])}')
    return r


@router.get('/eula')
def get_eula(iid: int, user: dict = Depends(get_current_user)):
    return {'ok': True, **serverctl.eula_status(_row(iid, user))}


@router.post('/eula')
def accept_eula(iid: int, request: Request, user: dict = Depends(get_current_user)):
    # 接受 EULA 是"让服务端能启动"的必要动作 → 归到启停权限
    row = require_instance(user, iid, perms.P_INSTANCE_START)
    r = serverctl.accept_eula(row)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'config.eula', iid, '接受 Minecraft EULA')
    return r


@router.get('/startup')
def get_startup(iid: int, user: dict = Depends(get_current_user)):
    row = _row(iid, user)
    return {'ok': True, 'memory_mb': row['memory_mb'], 'extra_jvm_args': row['extra_jvm_args'],
            'extra_server_args': row['extra_server_args'], 'nogui': bool(row['nogui']),
            'java_path': row['java_path'], 'auto_restart': bool(row['auto_restart']),
            'rcon_enabled': bool(row['rcon_enabled']), 'rcon_port': row['rcon_port'],
            'has_rcon_password': bool(row.get('rcon_password')),
            'jar_path': row['jar_path'],
            'command_preview': ' '.join(manager.build_command(row)),
            'command_detail': _command(row)}


@router.get('/startup/preview')
def startup_preview(iid: int, user: dict = Depends(get_current_user)):
    """启动参数预览：把最终命令行逐段渲染出来（java 路径 / 内存 / JVM 参数 / nogui）。"""
    return _command(_row(iid, user))


@router.put('/startup')
def put_startup(iid: int, body: StartupIn, request: Request,
                user: dict = Depends(get_current_user)):
    cur = require_instance(user, iid, perms.P_SETTINGS)
    fields, args, changed = [], [], []
    for key, val in body.dict(exclude_unset=True).items():
        if val is None:
            continue
        if key == 'memory_mb':
            if not 1 <= int(val) <= 65536:
                raise HTTPException(status_code=400, detail='内存需在 1~65536 MB 之间')
            # 内存是配额项：按"差额"校验（同口径见 permissions.check_quota 注释）
            owner = query('SELECT * FROM users WHERE id=?',
                          (int(cur.get('owner_id') or 0),), one=True) or user
            delta = max(0, int(val) - int(cur.get('memory_mb') or 0))
            if delta:
                perms.check_quota(owner, 'memory', amount=delta)
        if key == 'rcon_port':
            if not 1 <= int(val) <= 65535:
                raise HTTPException(status_code=400, detail='RCON 端口不合法')
            # 改 RCON 端口 = 改网络设置（规格 §2：普通用户不可）
            require_instance(user, iid, perms.P_SETTINGS)
        if key in ('nogui', 'auto_restart', 'rcon_enabled'):
            val = 1 if val else 0
        fields.append(f'{key}=?')
        args.append(val)
        changed.append(key)
    if not fields:
        return {'ok': True, 'changed': []}
    args.append(iid)
    execute(f'UPDATE instances SET {", ".join(fields)} WHERE id=?', tuple(args))
    row = _row(iid, user)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'config.startup', iid, f'修改启动参数：{", ".join(changed)}')
    return {'ok': True, 'changed': changed,
            'command_preview': ' '.join(manager.build_command(row)),
            'command_detail': _command(row)}
