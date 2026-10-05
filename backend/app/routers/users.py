"""用户管理 API（`docs/FEATURE-ACCOUNTS.md` §5 / `docs/API-CONTRACT.md` §1.16）。

| 方法 | 路径 | 权限 |
|---|---|---|
| GET    | `/api/users`              | `user.manage` |
| POST   | `/api/users`              | `user.manage` |
| PATCH  | `/api/users/{uid}`        | `user.manage` |
| POST   | `/api/users/{uid}/password` | `user.manage` |
| POST   | `/api/users/{uid}/kick`   | `user.manage` |
| DELETE | `/api/users/{uid}`        | `user.manage` |
| GET    | `/api/me/permissions`     | 登录即可 |

安全红线（规格 §7）：口令永不进日志/审计/页面；重置口令只在**当次响应**里回显一次；
禁止自我降级 / 自我停用 / 自删；禁止降级、停用、删除**最后一个超级管理员**。
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .. import audit as audit_mod
from ..auth import (get_client_ip, get_current_user, kick_user, password_policy_error,
                    random_password, reset_password)
from ..database import execute, now, query
from .. import permissions as perms

router = APIRouter(prefix='/api', tags=['users'])

_USERNAME_RE = re.compile(r'^[A-Za-z0-9_.\-]{3,32}$')

#: 建号时的默认配额（前端 mock 的取值口径；字段与 `API-CONTRACT.md` §1.16 逐字一致）。
#: `permissions.default_quota_for_user()` 会读这份，保证"默认配额"只有一处定义。
DEFAULT_QUOTA = {
    perms.SUPER_ADMIN: {'max_instances': 20, 'max_memory_mb_total': 65536,
                       'max_backups': 50, 'max_upload_mb': 1024, 'allow_build_import': True},
    perms.ADMIN: {'max_instances': 10, 'max_memory_mb_total': 32768,
                  'max_backups': 20, 'max_upload_mb': 512, 'allow_build_import': True},
    perms.USER: {'max_instances': 3, 'max_memory_mb_total': 8192,
                 'max_backups': 5, 'max_upload_mb': 128, 'allow_build_import': False},
    perms.VIEWER: {'max_instances': 0, 'max_memory_mb_total': 0,
                   'max_backups': 0, 'max_upload_mb': 0, 'allow_build_import': False},
}


# ---------------------------------------------------------------- 请求体
class QuotaIn(BaseModel):
    max_instances: int = None
    max_memory_mb_total: int = None
    max_backups: int = None
    max_upload_mb: int = None
    allow_build_import: bool = None


class UserCreateIn(BaseModel):
    username: str
    password: str = ''
    role: str = perms.USER
    quota: QuotaIn = None


class UserPatchIn(BaseModel):
    role: str = None
    status: int = None
    quota: QuotaIn = None


class PasswordResetIn(BaseModel):
    password: str = ''


# ---------------------------------------------------------------- 辅助
def _quota_dict(row: dict) -> dict:
    return {
        'max_instances': int(row.get('max_instances') or 0),
        'max_memory_mb_total': int(row.get('max_memory_mb_total') or 0),
        'max_backups': int(row.get('max_backups') or 0),
        'max_upload_mb': int(row.get('max_upload_mb') or 0),
        'allow_build_import': bool(row.get('allow_build_import')),
    }


def user_view(row: dict, counts: dict = None) -> dict:
    """`User` 对象（契约 §1.16 字段逐一对应）。**绝不包含 `password_hash`。**"""
    uid = int(row['id'])
    if counts is None:
        cnt = perms.instance_count(uid)
    else:
        cnt = int(counts.get(uid, 0))
    return {
        'id': uid,
        'username': row['username'],
        'role': row.get('role') or perms.USER,
        'role_name': perms.role_name(row.get('role')),
        'status': int(row.get('status') if row.get('status') is not None else 1),
        'quota': _quota_dict(row),
        'last_login': row.get('last_login'),
        'instance_count': cnt,
        'created_at': row.get('created_at'),
        'token_epoch': int(row.get('token_epoch') or 0),
    }


def _target_or_404(uid: int) -> dict:
    row = query('SELECT * FROM users WHERE id=?', (int(uid),), one=True)
    if not row:
        raise HTTPException(status_code=404, detail='用户不存在')
    return row


def _super_count(exclude_id: int = 0) -> int:
    """启用状态的超级管理员数量（`exclude_id` 用来模拟"如果把这个停用/删掉"）。"""
    if exclude_id:
        row = query('SELECT COUNT(*) AS n FROM users WHERE role=? AND status=1 AND id<>?',
                    (perms.SUPER_ADMIN, int(exclude_id)), one=True)
    else:
        row = query('SELECT COUNT(*) AS n FROM users WHERE role=? AND status=1',
                    (perms.SUPER_ADMIN,), one=True)
    return int(row['n']) if row else 0


def _clean_quota(raw, need_username: bool = False):
    """校验并归一配额；返回 (dict|None, error)。"""
    if raw is None:
        return None, ''
    if hasattr(raw, 'model_dump'):
        data = raw.model_dump(exclude_unset=True)
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        return None, '配额字段格式不正确'
    out = {}
    for f in perms.QUOTA_FIELDS:
        if f not in data or data[f] is None:
            continue
        v = data[f]
        if f == 'allow_build_import':
            out[f] = 1 if v else 0
            continue
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None, f'配额 {f} 必须是整数'
        if iv < 0:
            return None, f'配额 {f} 不能为负数'
        cap = perms.QUOTA_LIMITS.get(f)
        if cap and iv > cap:
            return None, f'配额 {f} 过大（上限 {cap}）'
        out[f] = iv
    return out, ''


def _defaults(role: str) -> dict:
    return dict(DEFAULT_QUOTA.get(role, DEFAULT_QUOTA[perms.USER]))


def _effective_quota(role: str, raw) -> dict:
    """角色默认值 + 用户指定项（缺项按角色默认补齐）。"""
    eff = _defaults(role)
    if raw:
        eff.update({k: v for k, v in raw.items()})
    eff['allow_build_import'] = bool(eff.get('allow_build_import'))
    return eff


# ---------------------------------------------------------------- 当前登录者的权限
@router.get('/me/permissions')
def my_permissions(user: dict = Depends(get_current_user)):
    """登录即可读。前端据此隐藏菜单与按钮 —— **后端仍逐个路由兜底 403**。"""
    return perms.permissions_payload(user)


# ---------------------------------------------------------------- 用户列表 / 新建
@router.get('/users')
def list_users(request: Request, limit: int = Query(default=200, ge=1, le=1000),
               offset: int = Query(default=0, ge=0),
               user: dict = Depends(get_current_user)):
    perms.require_perm(user, perms.P_USER_MANAGE)
    total = query('SELECT COUNT(*) AS n FROM users', one=True)
    rows = query('SELECT * FROM users ORDER BY id ASC LIMIT ? OFFSET ?', (limit, offset))
    counts = perms.instance_counts()
    return {'ok': True, 'users': [user_view(r, counts) for r in rows],
            'total': int(total['n']) if total else len(rows),
            'roles': [dict(perms.ROLE_META[k], key=k) for k in perms.ROLES],
            'all_perms': list(perms.ALL_PERMS),
            'default_quota': {k: dict(v) for k, v in DEFAULT_QUOTA.items()}}


@router.post('/users')
def create_user(body: UserCreateIn, request: Request,
                user: dict = Depends(get_current_user)):
    perms.require_perm(user, perms.P_USER_MANAGE)
    ip = get_client_ip(request)

    username = (body.username or '').strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400,
                            detail='用户名只能是 3–32 位的字母/数字/下划线/点/短横线')
    role = (body.role or perms.USER).strip()
    if role not in perms.ROLES:
        raise HTTPException(status_code=400,
                            detail=f'角色不合法（可选：{"、".join(perms.ROLES)}）')
    if query('SELECT id FROM users WHERE username=?', (username,), one=True):
        raise HTTPException(status_code=409, detail='用户名已存在')

    pwd = body.password or ''
    generated = False
    if not pwd:
        pwd = random_password(20)
        generated = True
    err = password_policy_error(pwd)
    if err:
        raise HTTPException(status_code=400, detail=err)

    raw, qerr = _clean_quota(body.quota)
    if qerr:
        raise HTTPException(status_code=400, detail=qerr)
    eff = _effective_quota(role, raw)

    from ..auth import hash_password
    uid = execute(
        'INSERT INTO users (username, password_hash, role, status, created_at, '
        'max_instances, max_memory_mb_total, max_backups, max_upload_mb, '
        'allow_build_import) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (username, hash_password(pwd), role, 1, now(), eff['max_instances'],
         eff['max_memory_mb_total'], eff['max_backups'], eff['max_upload_mb'],
         1 if eff['allow_build_import'] else 0))

    audit_mod.audit(user['username'], ip, 'user.create',
                    detail=(f'新建用户「{username}」(id={uid})，角色={perms.role_name(role)}，'
                            f'配额={eff}'),
                    level='warn')
    out = {'ok': True, 'id': uid, 'user': user_view(_target_or_404(uid))}
    if generated:
        # 口令只在本次响应里出现一次（规格 §7）
        out['password'] = pwd
        out['note'] = '未指定口令，已由服务端随机生成；该口令只在此处显示一次，请立即交给该用户。'
    return out


# ---------------------------------------------------------------- 改角色 / 状态 / 配额
@router.patch('/users/{uid}')
def patch_user(uid: int, body: UserPatchIn, request: Request,
               user: dict = Depends(get_current_user)):
    perms.require_perm(user, perms.P_USER_MANAGE)
    ip = get_client_ip(request)
    target = _target_or_404(uid)
    tid = int(target['id'])
    changed, details = [], []

    raw, qerr = _clean_quota(body.quota)
    if qerr:
        raise HTTPException(status_code=400, detail=qerr)

    new_role = (body.role or '').strip() or None
    if new_role and new_role != target['role']:
        if new_role not in perms.ROLES:
            raise HTTPException(status_code=400,
                                detail=f'角色不合法（可选：{"、".join(perms.ROLES)}）')
        # 规格 §2/§7：禁止自我降级；禁止把最后一个超管降级
        if tid == int(user['id']) and target['role'] == perms.SUPER_ADMIN \
                and new_role != perms.SUPER_ADMIN:
            raise HTTPException(status_code=400,
                                detail='禁止自我降级：请让另一位超级管理员操作')
        if target['role'] == perms.SUPER_ADMIN and new_role != perms.SUPER_ADMIN:
            if _super_count(exclude_id=tid) < 1:
                raise HTTPException(status_code=400,
                                    detail='系统内必须保留至少 1 个超级管理员，'
                                           '请先新增另一位超管再降级')
        execute('UPDATE users SET role=? WHERE id=?', (new_role, tid))
        changed.append('role')
        details.append(f'角色 {perms.role_name(target["role"])}→{perms.role_name(new_role)}')

    if body.status is not None:
        new_status = 1 if int(body.status) else 0
        cur = int(target.get('status') or 0)
        if new_status != cur:
            if tid == int(user['id']):
                raise HTTPException(status_code=400, detail='禁止停用自己的账号')
            if not new_status and target['role'] == perms.SUPER_ADMIN \
                    and _super_count(exclude_id=tid) < 1:
                raise HTTPException(status_code=400,
                                    detail='禁止停用最后一个超级管理员')
            execute('UPDATE users SET status=? WHERE id=?', (new_status, tid))
            if not new_status:
                kick_user(tid)          # 停用即踢下线，避免已建会话继续用
            changed.append('status')
            details.append('启用' if new_status else '停用（并强制下线）')

    if raw:
        # 角色变了且这次没显式给配额 → 一并套用新角色的默认配额，避免"user 角色带着超管配额"
        eff = _effective_quota(new_role or target['role'], raw)
        execute('UPDATE users SET max_instances=?, max_memory_mb_total=?, max_backups=?, '
                'max_upload_mb=?, allow_build_import=? WHERE id=?',
                (eff['max_instances'], eff['max_memory_mb_total'], eff['max_backups'],
                 eff['max_upload_mb'], 1 if eff['allow_build_import'] else 0, tid))
        changed.append('quota')
        details.append(f'配额更新为 {eff}')

    if not changed:
        return {'ok': True, 'changed': [], 'user': user_view(_target_or_404(tid)),
                'note': '没有需要修改的内容'}

    audit_mod.audit(user['username'], ip, 'user.update',
                    detail=f'修改用户「{target["username"]}」(id={tid})：' + '；'.join(details),
                    level='warn')
    return {'ok': True, 'changed': changed, 'user': user_view(_target_or_404(tid)),
            'note': '已保存：' + '；'.join(details)}


# ---------------------------------------------------------------- 重置口令 / 强制下线
@router.post('/users/{uid}/password')
def reset_user_password(uid: int, body: PasswordResetIn, request: Request,
                        user: dict = Depends(get_current_user)):
    perms.require_perm(user, perms.P_USER_MANAGE)
    ip = get_client_ip(request)
    target = _target_or_404(uid)
    pwd = reset_password(int(target['id']), (body.password or '').strip())
    # ⚠️ 审计里只记"重置了谁"，绝不记口令本身
    audit_mod.audit(user['username'], ip, 'user.reset_password',
                    detail=(f'重置用户「{target["username"]}」(id={target["id"]}) 的口令，'
                            f'其全部会话已失效'),
                    level='warn')
    return {'ok': True, 'password': pwd,
            'note': '该口令只在本次响应返回一次；该用户所有会话已立即失效，需用新口令重新登录。'}


@router.post('/users/{uid}/kick')
def kick(uid: int, request: Request, user: dict = Depends(get_current_user)):
    perms.require_perm(user, perms.P_USER_MANAGE)
    ip = get_client_ip(request)
    target = _target_or_404(uid)
    tid = int(target['id'])
    if tid == int(user['id']):
        raise HTTPException(status_code=400,
                            detail='不能强制下线自己（如需登出请点右上角退出）')
    kick_user(tid)
    audit_mod.audit(user['username'], ip, 'user.kick',
                    detail=f'强制下线用户「{target["username"]}」(id={tid})，其所有会话已失效',
                    level='warn')
    return {'ok': True,
            'note': f'已强制下线「{target["username"]}」，其所有会话立即失效（token_epoch +1）'}


# ---------------------------------------------------------------- 删除
@router.delete('/users/{uid}')
def delete_user(uid: int, request: Request,
                purge_instances: bool = Query(default=False),
                user: dict = Depends(get_current_user)):
    perms.require_perm(user, perms.P_USER_MANAGE)
    ip = get_client_ip(request)
    target = _target_or_404(uid)
    tid = int(target['id'])

    if tid == int(user['id']):
        raise HTTPException(status_code=400, detail='禁止删除自己的账号')
    if target['role'] == perms.SUPER_ADMIN and _super_count(exclude_id=tid) < 1:
        raise HTTPException(status_code=400, detail='禁止删除最后一个超级管理员')

    owned = query('SELECT id, name FROM instances WHERE owner_id=?', (tid,))
    n_inst = len(owned)
    if n_inst and not purge_instances:
        raise HTTPException(
            status_code=400,
            detail=f'该用户名下有 {n_inst} 个实例，请先转移归属，或勾选「一并删除」'
                   f'（将连同实例目录一起删除，不可恢复）')

    deleted = []
    if n_inst and purge_instances:
        import os
        import shutil

        from ..config import INSTANCE_DIR, instance_dir
        from ..process_manager import manager
        rows = query('SELECT * FROM instances WHERE owner_id=?', (tid,))
        for row in rows:
            iid = int(row['id'])
            d = instance_dir(row)
            try:
                manager.forget(iid)
            except Exception:
                pass
            # 目录删除必须过路径闸门（与 instances 路由同一口径），否则宁可不删
            if d and os.path.isdir(d) and \
                    os.path.realpath(d).startswith(os.path.realpath(INSTANCE_DIR)):
                shutil.rmtree(d, ignore_errors=True)
            for sql in ('DELETE FROM backups WHERE instance_id=?',
                        'DELETE FROM cron_runs WHERE job_id IN '
                        '(SELECT id FROM cron_jobs WHERE instance_id=?)',
                        'DELETE FROM cron_jobs WHERE instance_id=?',
                        'DELETE FROM metrics WHERE instance_id=?',
                        'DELETE FROM crash_logs WHERE instance_id=?',
                        'DELETE FROM instances WHERE id=?'):
                execute(sql, (iid,))
            deleted.append({'id': iid, 'name': row.get('name')})

    execute('DELETE FROM sessions WHERE uid=?', (tid,))
    execute('DELETE FROM users WHERE id=?', (tid,))
    audit_mod.audit(user['username'], ip, 'user.delete',
                    detail=(f'删除用户「{target["username"]}」(id={tid})，'
                            f'角色={perms.role_name(target["role"])}；'
                            f'名下实例 {n_inst} 个：'
                            + ('一并删除 ' + '、'.join(f'#{d["id"]} {d["name"]}' for d in deleted)
                               if deleted else '无（或已转移）')),
                    level='warn')

    if deleted:
        note = (f'已删除用户「{target["username"]}」，并一并删除其名下 '
                f'{len(deleted)} 个实例（含实例目录，不可恢复）')
    elif n_inst:
        note = f'已删除用户「{target["username"]}」（其名下 {n_inst} 个实例未受影响）'
    else:
        note = f'已删除用户「{target["username"]}」'
    return {'ok': True, 'note': note, 'deleted_instances': deleted}
