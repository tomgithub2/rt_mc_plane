"""插件/模组：本地列表 + 启用禁用 + 删除 + Modrinth/Spigot/CurseForge 搜索安装。"""
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .. import audit as audit_mod, pluginsources, serverctl
from ..auth import get_current_user
from ..config import instance_dir
from ..downloader import start_download
from .. import permissions as perms
from ..permissions import require_instance

router = APIRouter(prefix='/api/instances/{iid}/plugins', tags=['plugins'])


def _row(iid: int, user: dict = None, write: bool = False) -> dict:
    """取实例行 + 实例级权限校验（读=能看即可；写=属主/管理员且有插件权限）。"""
    if user is None:
        raise HTTPException(status_code=401, detail='未登录')
    if write:
        return require_instance(user, iid, perms.P_INSTANCE_PLUGINS)
    return require_instance(user, iid)


class ToggleIn(BaseModel):
    dir: str
    name: str
    enable: bool


class DeleteIn(BaseModel):
    dir: str
    name: str


class SearchIn(BaseModel):
    source: str = 'modrinth'
    query: str = ''
    mc_version: str = ''
    mod_type: str = ''


class InstallIn(BaseModel):
    source: str
    project: str = ''
    version_id: str = ''
    url: str = ''
    filename: str = ''
    sha1: str = ''


@router.get('')
def list_plugins(iid: int, user: dict = Depends(get_current_user)):
    row = _row(iid, user)
    return {'ok': True, 'items': serverctl.plugins(row),
            'target_dir': pluginsources.target_dir(row),
            'loader': pluginsources.loader_for(row['core_type'])}


@router.post('/toggle')
def toggle(iid: int, body: ToggleIn, request: Request, user: dict = Depends(get_current_user)):
    r = serverctl.plugin_toggle(_row(iid, user, write=True), body.dir, body.name, body.enable)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'plugin.toggle', iid,
                    f'{"启用" if body.enable else "禁用"} {body.dir}/{body.name}')
    return r


@router.post('/delete')
def delete(iid: int, body: DeleteIn, request: Request, user: dict = Depends(get_current_user)):
    r = serverctl.plugin_delete(_row(iid, user, write=True), body.dir, body.name)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'plugin.delete', iid, f'删除 {body.dir}/{body.name}', level='warn')
    return r


@router.post('/upload')
async def upload(iid: int, request: Request, dir: str = Form(default=''),
                 file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    row = _row(iid, user, write=True)
    dir = dir or pluginsources.target_dir(row)
    if dir not in serverctl.PLUGIN_DIRS:
        raise HTTPException(status_code=400, detail='目录只能是 plugins 或 mods')
    data = await file.read()
    if len(data) > 512 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='文件超过 512MB 上限')
    perms.check_quota(user, 'upload', amount=len(data))     # 上传配额（规格 §3）
    name = os.path.basename(file.filename or 'plugin.jar')
    if not name.lower().endswith(('.jar', '.jar.disabled', '.litemod', '.zip')):
        raise HTTPException(status_code=400, detail='只允许上传 .jar / .zip 文件')
    r = serverctl.save_upload(row, dir, name, data)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'plugin.upload', iid, f'上传 {dir}/{name}（{len(data)} 字节）')
    return r


# ---------------------------------------------------------------- 在线源
@router.get('/search')
def search(iid: int, source: str = 'modrinth', query: str = '', mc_version: str = '',
           mod_type: str = '', limit: int = 20, user: dict = Depends(get_current_user)):
    row = _row(iid, user)
    mc = mc_version or row.get('mc_version') or ''
    mt = mod_type or ('mod' if pluginsources.target_dir(row) == 'mods' else 'plugin')
    return pluginsources.search(query, mc, source, mt, limit)


@router.get('/versions')
def versions(iid: int, project: str, source: str = 'modrinth', mc_version: str = '',
             user: dict = Depends(get_current_user)):
    row = _row(iid, user)
    mc = mc_version or row.get('mc_version') or ''
    if source == 'modrinth':
        r = pluginsources.modrinth_versions(project, mc, pluginsources.loader_for(row['core_type']))
        if not r.get('ok'):
            raise HTTPException(status_code=502, detail=r.get('error'))
        return r
    if source == 'curseforge':
        r = pluginsources.curseforge_files(project, mc)
        if not r.get('ok'):
            raise HTTPException(status_code=502, detail=r.get('error'))
        return r
    raise HTTPException(status_code=400, detail='该源不支持版本列表，请直接使用搜索下载')


@router.post('/install')
def install(iid: int, body: InstallIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, write=True)
    root = instance_dir(row)
    target = pluginsources.target_dir(row)
    dest_dir = os.path.join(root, target)
    os.makedirs(dest_dir, exist_ok=True)

    if body.source == 'spigot':
        r = pluginsources.spiget_download(body.project, dest_dir)
        if not r.get('ok'):
            raise HTTPException(status_code=502, detail=r.get('error'))
        audit_mod.audit(user['username'], request.client.host if request.client else '',
                        'plugin.install', iid, f'从 SpigotMC 安装 {r.get("name")}')
        return {'ok': True, 'file': r.get('name'), 'note': '已从 SpigotMC 下载'}

    if not body.url:
        raise HTTPException(status_code=400, detail='缺少下载地址')
    fname = os.path.basename(body.filename or body.url.split('?')[0]) or 'plugin.jar'
    dest = os.path.join(dest_dir, fname)
    tid = start_download(body.url, dest, label=fname, sha1=body.sha1, kind=target)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'plugin.install', iid, f'安装 {target}/{fname}（源 {body.source}）')
    return {'ok': True, 'task_id': tid, 'file': fname, 'dir': target, 'dest': dest}


@router.get('/sources')
def sources(user: dict = Depends(get_current_user)):
    return {'ok': True, 'results': pluginsources.probe(),
            'note': 'CurseForge 官方接口不允许匿名访问，需要 API Key（设置页填写）'}
