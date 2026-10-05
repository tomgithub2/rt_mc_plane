"""登录 / 登出 / 会话 / 改密。"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from .. import audit as audit_mod
from ..auth import (change_password, create_session, destroy_session, get_client_ip,
                    get_current_user, is_locked, password_policy_error, record_fail,
                    reset_fail, verify_password)
from ..database import execute, now, query

router = APIRouter(prefix='/api/auth', tags=['auth'])


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePwIn(BaseModel):
    old_password: str
    new_password: str


@router.post('/login')
def login(body: LoginIn, request: Request):
    ip = get_client_ip(request)
    ua = request.headers.get('user-agent', '')
    key = f'{body.username}|{ip}'
    if is_locked(key):
        audit_mod.login_log(body.username, ip, ua, False, '账号已锁定')
        raise HTTPException(status_code=429, detail='失败次数过多，账号已临时锁定，请稍后再试')
    user = query('SELECT * FROM users WHERE username=?', (body.username,), one=True)
    # ⚠️ 停用（status=0）的账号必须拒绝登录。`resolve_token` 已经用 `u.status=1` 兜住了
    # "已建会话"，但**登录这一道**如果只看口令哈希，被停用的账号就能当场换一个新 token
    # 重新进来，等于停用形同虚设。（端到端验收脚本实测到过这个洞。）
    if user and not int(user.get('status') or 0):
        audit_mod.login_log(body.username, ip, ua, False, '账号已停用')
        raise HTTPException(status_code=403, detail='该账号已被停用，请联系超级管理员')
    if not user or not verify_password(body.password, user['password_hash']):
        n = record_fail(key)
        audit_mod.login_log(body.username, ip, ua, False, '用户名或密码错误')
        raise HTTPException(status_code=401, detail=f'用户名或密码错误（已失败 {n} 次）')
    reset_fail(key)
    token, exp = create_session(user['id'], ip, ua)
    execute('UPDATE users SET last_login=? WHERE id=?', (now(), user['id']))
    audit_mod.login_log(body.username, ip, ua, True, '')
    audit_mod.audit(user['username'], ip, 'auth.login', detail='登录面板')
    return {'ok': True, 'token': token, 'expires_at': exp,
            'user': {'id': user['id'], 'username': user['username'], 'role': user['role']}}


@router.post('/logout')
def logout(authorization: str = Header(default=''), user: dict = Depends(get_current_user)):
    token = authorization[7:].strip() if authorization.startswith('Bearer ') else ''
    destroy_session(token)
    audit_mod.audit(user['username'], '', 'auth.logout', detail='退出登录')
    return {'ok': True}


@router.get('/me')
def me(user: dict = Depends(get_current_user)):
    return {'ok': True, 'user': {'id': user['id'], 'username': user['username'],
                                 'role': user['role'], 'last_login': user.get('last_login')}}


@router.post('/password')
def change_pw(body: ChangePwIn, request: Request, user: dict = Depends(get_current_user)):
    err = password_policy_error(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    change_password(user['id'], body.old_password, body.new_password)
    audit_mod.audit(user['username'], get_client_ip(request), 'auth.password',
                    detail='修改面板口令（所有会话已失效）')
    return {'ok': True, 'note': '口令已修改，请重新登录'}
