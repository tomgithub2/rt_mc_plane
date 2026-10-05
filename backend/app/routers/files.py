"""文件管理：浏览/上传/下载/重命名/删除/解压/新建目录/在线编辑。

所有操作都经过 pathguard（realpath + commonpath），越界与符号链接逃逸一律 403。
"""
import os
import urllib.parse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import audit as audit_mod, serverctl
from ..auth import get_current_user
from .. import permissions as perms
from ..permissions import require_instance

router = APIRouter(prefix='/api/instances/{iid}/files', tags=['files'])

MAX_UPLOAD = 1024 * 1024 * 1024        # 单文件 1GB


def _row(iid: int, user: dict = None, write: bool = False) -> dict:
    """取实例行并做实例级权限校验。

    - `write=False`：能看这个实例即可（超管/管理员/属主/只读）；
    - `write=True` ：必须是属主或管理员，且拥有 `instance.files` 权限点。

    ⚠️ 本文件是**实例目录浏览器**（含 `server.properties`、插件 jar、模组），
    所以**每一项读写都必须过这里**，不允许绕开它自己取实例行。
    """
    if user is None:
        raise HTTPException(status_code=401, detail='未登录')
    if write:
        return require_instance(user, iid, perms.P_INSTANCE_FILES)
    return require_instance(user, iid)


class PathIn(BaseModel):
    path: str


class RenameIn(BaseModel):
    path: str
    new_name: str


class WriteIn(BaseModel):
    path: str
    content: str


class UnzipIn(BaseModel):
    path: str
    target: str = ''


@router.get('')
def list_files(iid: int, path: str = '', user: dict = Depends(get_current_user)):
    return {'ok': True, **serverctl.list_dir(_row(iid, user), path)}


@router.get('/read')
def read_file(iid: int, path: str, user: dict = Depends(get_current_user)):
    return {'ok': True, **serverctl.read_text(_row(iid, user), path)}


@router.put('/write')
def write_file(iid: int, body: WriteIn, request: Request,
               user: dict = Depends(get_current_user)):
    row = _row(iid, user, write=True)
    r = serverctl.write_text(row, body.path, body.content)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'file.write', iid, f'在线编辑保存：{body.path}')
    return r


@router.post('/mkdir')
def mkdir(iid: int, body: PathIn, request: Request, user: dict = Depends(get_current_user)):
    r = serverctl.mkdir(_row(iid, user, write=True), body.path)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'file.mkdir', iid, f'新建目录：{body.path}')
    return r


@router.post('/rename')
def rename(iid: int, body: RenameIn, request: Request, user: dict = Depends(get_current_user)):
    r = serverctl.rename(_row(iid, user, write=True), body.path, body.new_name)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'file.rename', iid, f'重命名：{body.path} → {body.new_name}')
    return r


@router.post('/delete')
def delete(iid: int, body: PathIn, request: Request, user: dict = Depends(get_current_user)):
    r = serverctl.delete(_row(iid, user, write=True), body.path)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'file.delete', iid, f'删除：{body.path}', level='warn')
    return r


@router.post('/unzip')
def unzip(iid: int, body: UnzipIn, request: Request, user: dict = Depends(get_current_user)):
    r = serverctl.unzip(_row(iid, user, write=True), body.path, body.target)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'file.unzip', iid, f'解压：{body.path}（{r.get("extracted")} 个文件）')
    return r


@router.post('/upload')
async def upload(iid: int, request: Request, path: str = Form(default=''),
                 file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    row = _row(iid, user, write=True)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail='文件超过 1GB 上限')
    # 上传配额（规格 §3：上传逐项校验；超管不受限）
    perms.check_quota(user, 'upload', amount=len(data))
    r = serverctl.save_upload(row, path, file.filename or 'upload.bin', data)
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'file.upload', iid, f'上传文件：{r.get("path")}（{len(data)} 字节）')
    return r


@router.get('/download')
def download(iid: int, path: str, user: dict = Depends(get_current_user)):
    row = _row(iid, user)
    target = serverctl.resolve(row, path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail='文件不存在')
    name = os.path.basename(target)
    quoted = urllib.parse.quote(name)
    return FileResponse(target, media_type='application/octet-stream',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quoted}"})
