"""备份与还原：tar.gz 打包、保留份数轮转、下载/还原/删除。"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import audit as audit_mod, serverctl
from ..auth import get_current_user
from ..database import query
from .. import permissions as perms
from ..permissions import require_instance

router = APIRouter(prefix='/api/instances/{iid}/backups', tags=['backups'])


def _row(iid: int, user: dict = None, write: bool = False) -> dict:
    """取实例行 + 实例级权限校验（读=能看即可；写=须为属主/管理员且有备份权限）。"""
    if user is None:
        raise HTTPException(status_code=401, detail='未登录')
    if write:
        return require_instance(user, iid, perms.P_INSTANCE_BACKUP)
    return require_instance(user, iid)


class BackupIn(BaseModel):
    note: str = ''


@router.get('')
def list_backups(iid: int, user: dict = Depends(get_current_user)):
    _row(iid, user)
    rows = query('SELECT * FROM backups WHERE instance_id=? ORDER BY created_at DESC', (iid,))
    for r in rows:
        r['exists'] = os.path.isfile(r['file'])
        r['name'] = os.path.basename(r['file'])
    return {'ok': True, 'backups': rows}


@router.post('')
def create(iid: int, body: BackupIn, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, write=True)
    # 备份份数配额（规格 §3）；超管不受限
    owner = query('SELECT * FROM users WHERE id=?',
                  (int(row.get('owner_id') or 0),), one=True) or user
    perms.check_quota(owner, 'backup')
    r = serverctl.create_backup(row, kind='manual', note=body.note)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'backup.create', iid,
                    f'创建备份 {os.path.basename(r.get("file", ""))}（{r.get("size", 0)} 字节）')
    return r


@router.post('/{bid}/restore')
def restore(iid: int, bid: int, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, write=True)
    r = serverctl.restore_backup(row, bid)
    if not r.get('ok'):
        raise HTTPException(status_code=400, detail=r.get('error', '还原失败'))
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'backup.restore', iid, f'还原备份 #{bid}', level='warn')
    return r


@router.delete('/{bid}')
def delete(iid: int, bid: int, request: Request, user: dict = Depends(get_current_user)):
    row = _row(iid, user, write=True)
    r = serverctl.delete_backup(row, bid)
    if not r.get('ok'):
        raise HTTPException(status_code=400, detail=r.get('error', '删除失败'))
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'backup.delete', iid, f'删除备份 #{bid}')
    return r


@router.get('/{bid}/download')
def download(iid: int, bid: int, user: dict = Depends(get_current_user)):
    _row(iid, user)
    b = query('SELECT * FROM backups WHERE id=? AND instance_id=?', (bid, iid), one=True)
    if not b or not os.path.isfile(b['file']):
        raise HTTPException(status_code=404, detail='备份文件不存在')
    return FileResponse(b['file'], media_type='application/gzip',
                        filename=os.path.basename(b['file']))
