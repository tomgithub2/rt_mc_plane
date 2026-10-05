"""玩家管理：白名单 / OP / 封禁（含 IP），在线列表、踢人、给 OP。"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import audit as audit_mod, serverctl
from ..auth import get_current_user
from ..config import get_config, instance_dir
from .. import permissions as perms
from ..permissions import require_instance
from ..process_manager import manager
from ..rcon import try_command

router = APIRouter(prefix='/api/instances/{iid}/players', tags=['players'])


def _row(iid: int, user: dict = None, perm: str = None) -> dict:
    """取实例行 + 实例级权限校验。

    白名单/OP/封禁是**玩家管理**：写操作按"下发命令"口径要求 `instance.command`
    （这些动作最终都会写 ops.json/banned-players.json，等价于游戏内指令的效力）。
    """
    if user is None:
        raise HTTPException(status_code=401, detail='未登录')
    return require_instance(user, iid, perm)


class PlayerIn(BaseModel):
    which: str
    name: str = ''
    uuid: str = ''
    level: int = 4
    reason: str = 'Banned by an operator.'
    ip: str = ''


class NameIn(BaseModel):
    which: str
    name: str


class ActIn(BaseModel):
    name: str
    reason: str = 'Kicked by an operator.'


def _rcon(row: dict, cmd: str):
    cfg = get_config()
    port = int(row.get('rcon_port') or cfg.get('rcon_port') or 25575)
    pwd = row.get('rcon_password') or cfg.get('rcon_password') or ''
    if not pwd:
        return False, '未配置 RCON 密码（在实例配置 → 启动参数里填写，或在设置页配置默认值）'
    return try_command(cfg.get('rcon_host', '127.0.0.1'), port, pwd, cmd)


@router.get('')
def list_all(iid: int, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    online = None
    online_source = ''
    inst = manager.get(iid)
    st = manager.status(iid)
    if st['running']:
        ok, text = _rcon(row, 'list')
        if ok:
            online = text.strip()
            online_source = 'rcon'
        elif inst.online_names:
            online = ', '.join(sorted(inst.online_names))
            online_source = 'log'
        else:
            online = ''
            online_source = 'unavailable'
    return {'ok': True,
            'whitelist': serverctl.player_list(row, 'whitelist'),
            'ops': serverctl.player_list(row, 'ops'),
            'banned_players': serverctl.player_list(row, 'banned-players'),
            'banned_ips': serverctl.player_list(row, 'banned-ips'),
            'online_text': online,
            'online_source': online_source,
            'online_names': st.get('online_names', []),
            'online_count': st.get('players', 0),
            'running': st['running'],
            'files': {k: os.path.join(instance_dir(row), v) for k, v in serverctl.PLAYER_FILES.items()}}


@router.post('/add')
def add(iid: int, body: PlayerIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    if body.which not in serverctl.PLAYER_FILES:
        raise HTTPException(status_code=400, detail='类型不合法')
    r = serverctl.player_add(row, body.which, body.name, body.uuid, body.level, body.reason, body.ip)
    if not r.get('ok'):
        raise HTTPException(status_code=400, detail=r.get('error'))
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'player.add', iid, f'{body.which} 添加 {body.name or body.ip}')
    return r


@router.post('/remove')
def remove(iid: int, body: NameIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    if body.which not in serverctl.PLAYER_FILES:
        raise HTTPException(status_code=400, detail='类型不合法')
    r = serverctl.player_remove(row, body.which, body.name)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'player.remove', iid, f'{body.which} 移除 {body.name}')
    return r


@router.post('/op')
def give_op(iid: int, body: NameIn, request: Request, user: dict = Depends(get_current_user)):
    """给 OP：写 ops.json（离线可用）+ 运行中的实例同时走 RCON 立即生效。"""
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    r = serverctl.player_add(row, 'ops', body.name)
    note = '仅写入 ops.json，重启后生效'
    if manager.status(iid)['running']:
        ok, text = _rcon(row, f'op {body.name}')
        note = f'已写入 ops.json；RCON 立即生效：{text.strip()[:120]}' if ok else \
               f'已写入 ops.json；RCON 不可用（{text}），重启后生效'
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'player.op', iid, f'给予 OP：{body.name}')
    return {'ok': True, 'note': note}


@router.post('/deop')
def take_op(iid: int, body: NameIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    r = serverctl.player_remove(row, 'ops', body.name)
    note = '仅修改 ops.json，重启后生效'
    if manager.status(iid)['running']:
        ok, text = _rcon(row, f'deop {body.name}')
        note = f'已修改 ops.json；RCON：{text.strip()[:120]}' if ok else \
               f'已修改 ops.json；RCON 不可用（{text}），重启后生效'
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'player.deop', iid, f'取消 OP：{body.name}')
    return {'ok': True, 'note': note}


@router.post('/kick')
def kick(iid: int, body: ActIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    if not manager.status(iid)['running']:
        raise HTTPException(status_code=400, detail='实例未运行，无法踢人')
    ok, text = _rcon(row, f'kick {body.name} {body.reason[:100]}')
    if not ok:
        r = manager.send_command(iid, f'kick {body.name} {body.reason[:100]}')
        if not r.get('ok'):
            raise HTTPException(status_code=502, detail=f'踢人失败：RCON={text}；控制台={r.get("error")}')
        text = '已通过控制台 stdio 下发'
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'player.kick', iid, f'踢出 {body.name}')
    return {'ok': True, 'result': text}


@router.post('/ban')
def ban(iid: int, body: ActIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    r = serverctl.player_add(row, 'banned-players', body.name, reason=body.reason)
    if not r.get('ok'):
        raise HTTPException(status_code=400, detail=r.get('error'))
    note = '已写入 banned-players.json'
    if manager.status(iid)['running']:
        ok, text = _rcon(row, f'ban {body.name} {body.reason[:100]}')
        note += f'；RCON：{text.strip()[:100]}' if ok else f'；RCON 不可用（{text}）'
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'player.ban', iid, f'封禁 {body.name}', level='warn')
    return {'ok': True, 'note': note}


@router.post('/pardon')
def pardon(iid: int, body: NameIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    serverctl.player_remove(row, 'banned-players', body.name)
    note = '已从 banned-players.json 移除'
    if manager.status(iid)['running']:
        ok, text = _rcon(row, f'pardon {body.name}')
        note += f'；RCON：{text.strip()[:100]}' if ok else '；RCON 不可用，重启后完全生效'
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'player.pardon', iid, f'解封 {body.name}')
    return {'ok': True, 'note': note}


@router.get('/rcon')
def rcon_status(iid: int, user: dict = Depends(get_current_user)):
    row = _row(iid, user, perms.P_INSTANCE_COMMAND)
    ok, text = _rcon(row, 'list')
    return {'ok': ok, 'result': text, 'error': '' if ok else text}
