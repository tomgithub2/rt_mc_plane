"""计划任务路由：cron 校验、增删改查、执行历史、手动执行。"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import audit as audit_mod
from ..auth import get_current_user
from ..database import execute, now, query
from .. import permissions as perms
from ..permissions import require_instance, require_perm
from ..scheduler import next_run, run_job, validate_cron

router = APIRouter(prefix='/api/cron', tags=['cron'])

ACTIONS = ['restart', 'stop', 'start', 'backup', 'command', 'broadcast']


def _job_or_404(jid: int, user: dict, perm: str = None) -> dict:
    """取任务并做权限校验。

    任务绑定实例时走实例级校验（普通用户只能动自己实例的任务）；
    系统级任务（`instance_id` 为空，例如"全局面板备份"）则要求 `system.settings`。
    """
    job = query('SELECT * FROM cron_jobs WHERE id=?', (jid,), one=True)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在')
    iid = job.get('instance_id')
    if not iid:
        require_perm(user, perms.P_SYSTEM_SETTINGS)
        return job
    require_instance(user, int(iid), perm or perms.P_INSTANCE_CRON)
    return job


def _visible_job_ids(user: dict) -> list:
    """该用户能看到/能操作的任务 id 列表（管理员=全部）。"""
    if perms.is_admin(user):
        rows = query('SELECT id FROM cron_jobs')
    else:
        rows = query('SELECT j.id FROM cron_jobs j JOIN instances i ON i.id=j.instance_id '
                     'WHERE i.owner_id=?', (int(user['id']),))
    return [int(r['id']) for r in rows]


class JobIn(BaseModel):
    name: str
    schedule: str
    action: str
    instance_id: int = None
    payload: str = ''
    enabled: bool = True


class JobPatch(BaseModel):
    name: str = None
    schedule: str = None
    action: str = None
    instance_id: int = None
    payload: str = None
    enabled: bool = None


@router.get('')
def list_jobs(user: dict = Depends(get_current_user)):
    if perms.is_admin(user):
        rows = query('SELECT j.*, i.name AS instance_name FROM cron_jobs j '
                     'LEFT JOIN instances i ON i.id=j.instance_id ORDER BY j.id ASC')
    else:
        rows = query('SELECT j.*, i.name AS instance_name FROM cron_jobs j '
                     'JOIN instances i ON i.id=j.instance_id '
                     'WHERE i.owner_id=? ORDER BY j.id ASC', (int(user['id']),))
    for r in rows:
        r['next_run_ts'] = next_run(r['schedule']) if r['enabled'] else 0
    return {'ok': True, 'jobs': rows, 'actions': ACTIONS}


@router.post('')
def create_job(body: JobIn, request: Request, user: dict = Depends(get_current_user)):
    err = validate_cron(body.schedule)
    if err:
        raise HTTPException(status_code=400, detail=err)
    if body.action not in ACTIONS:
        raise HTTPException(status_code=400, detail=f'动作必须是：{"、".join(ACTIONS)}')
    if body.action != 'backup' and not body.instance_id:
        raise HTTPException(status_code=400, detail='该动作需要指定实例')
    # 绑实例 → 必须是自己的实例且有 cron 权限；不绑实例（全局任务）→ 只有超管能建
    if body.instance_id:
        require_instance(user, int(body.instance_id), perms.P_INSTANCE_CRON)
    else:
        require_perm(user, perms.P_SYSTEM_SETTINGS)
    if body.action == 'command' and not body.payload.strip():
        raise HTTPException(status_code=400, detail='command 动作需要填写命令内容')
    jid = execute('INSERT INTO cron_jobs (instance_id, name, schedule, action, payload, enabled, '
                  'created_at, next_run) VALUES (?,?,?,?,?,?,?,?)',
                  (body.instance_id, body.name.strip()[:60], body.schedule.strip(), body.action,
                   body.payload, 1 if body.enabled else 0, now(),
                   next_run(body.schedule) if body.enabled else 0))
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'cron.create', body.instance_id,
                    f'新建计划任务「{body.name}」{body.schedule} → {body.action}')
    return {'ok': True, 'id': jid}


@router.patch('/{jid}')
def patch_job(jid: int, body: JobPatch, request: Request, user: dict = Depends(get_current_user)):
    job = _job_or_404(jid, user)
    if body.instance_id is not None and int(body.instance_id or 0) != int(job.get('instance_id') or 0):
        # 改归属 = 换一个实例，两边都要有权限；改成"全局任务"只有超管可以
        if body.instance_id:
            require_instance(user, int(body.instance_id), perms.P_INSTANCE_CRON)
        else:
            require_perm(user, perms.P_SYSTEM_SETTINGS)
    fields, args, changed = [], [], []
    for key, val in body.dict(exclude_unset=True).items():
        if val is None:
            continue
        if key == 'schedule':
            err = validate_cron(val)
            if err:
                raise HTTPException(status_code=400, detail=err)
        if key == 'action' and val not in ACTIONS:
            raise HTTPException(status_code=400, detail='动作不合法')
        if key == 'enabled':
            val = 1 if val else 0
        fields.append(f'{key}=?')
        args.append(val)
        changed.append(key)
    if not fields:
        return {'ok': True, 'changed': []}
    args.append(jid)
    execute(f'UPDATE cron_jobs SET {", ".join(fields)} WHERE id=?', tuple(args))
    job = query('SELECT * FROM cron_jobs WHERE id=?', (jid,), one=True)
    execute('UPDATE cron_jobs SET next_run=? WHERE id=?',
            (next_run(job['schedule']) if job['enabled'] else 0, jid))
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'cron.update', job['instance_id'], f'修改计划任务「{job["name"]}」：{", ".join(changed)}')
    return {'ok': True, 'changed': changed}


@router.delete('/{jid}')
def delete_job(jid: int, request: Request, user: dict = Depends(get_current_user)):
    job = _job_or_404(jid, user)
    execute('DELETE FROM cron_jobs WHERE id=?', (jid,))
    execute('DELETE FROM cron_runs WHERE job_id=?', (jid,))
    audit_mod.audit(user['username'], request.client.host if request.client else '',
                    'cron.delete', job['instance_id'], f'删除计划任务「{job["name"]}」')
    return {'ok': True}


@router.post('/{jid}/run')
def run_now(jid: int, request: Request, user: dict = Depends(get_current_user)):
    job = _job_or_404(jid, user)
    r = run_job(job, trigger=f'manual:{user["username"]}')
    return r


@router.get('/{jid}/runs')
def runs(jid: int, limit: int = 50, user: dict = Depends(get_current_user)):
    _job_or_404(jid, user)
    rows = query('SELECT * FROM cron_runs WHERE job_id=? ORDER BY ts DESC LIMIT ?', (jid, limit))
    return {'ok': True, 'runs': rows}


@router.post('/validate')
def validate(body: dict = Body(...), user: dict = Depends(get_current_user)):
    expr = str(body.get('schedule') or '')
    err = validate_cron(expr)
    return {'ok': not err, 'error': err, 'next_run': next_run(expr) if not err else 0}


@router.get('/all-runs')
def all_runs(limit: int = 100, user: dict = Depends(get_current_user)):
    ids = _visible_job_ids(user)
    if not ids:
        return {'ok': True, 'runs': []}
    marks = ','.join('?' * len(ids))
    rows = query(f'SELECT r.*, j.name AS job_name FROM cron_runs r '
                 f'LEFT JOIN cron_jobs j ON j.id=r.job_id '
                 f'WHERE r.job_id IN ({marks}) ORDER BY r.ts DESC LIMIT ?',
                 tuple(ids) + (limit,))
    return {'ok': True, 'runs': rows}
