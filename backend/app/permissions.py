"""角色 / 权限 / 实例归属 / 配额 —— 账号与权限体系的唯一裁定处。

依据：`docs/FEATURE-ACCOUNTS.md`（§2 角色矩阵、§3 归属与配额、§5 API、§7 安全红线）
与 `docs/API-CONTRACT.md` §1.16。

设计原则（照规格 §7 安全红线）：

1. **后端兜底**：前端隐藏菜单/按钮**不算安全**。所有写接口都必须显式过一次
   `require_perm()` / `require_instance()`，漏写就是漏洞。
2. **默认拒绝**：`viewer` 的权限集**故意留空** —— 只读档位的读操作走各项
   `can_view` / `can_view_logs` 判定，任何写操作都会因为查不到权限点而被 403，
   不需要（也不允许）靠"记得给每个写接口加检查"来兜底。
3. **中文人话**：所有拒绝都返回 403/400 + 中文原因（含当前角色、缺哪个权限点、
   配额上限是多少），前端把 `detail` 原样显示给用户。
4. 本模块**不 import 任何 router**（避免循环导入）；只有 `default_quota_for_user()`
   在函数内部 import `routers.users`（那是默认配额的唯一出处）。

权限点取自规格 §2（**不得擅自增删名字**）：

    instance.create  instance.delete  instance.start   instance.stop   instance.command
    instance.files   instance.plugins instance.backup  instance.cron   instance.build_import
    instance.settings_network
    user.manage      system.settings  audit.view       log.view
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from .database import execute, query

# ---------------------------------------------------------------- 角色
SUPER_ADMIN = 'super_admin'
ADMIN = 'admin'
USER = 'user'
VIEWER = 'viewer'

#: 角色元信息。`key` 顺序 = 从高到低；`cls` 供前端角色徽标配色（与 mock 逐字一致）。
ROLE_META = {
    SUPER_ADMIN: {'name': '超级管理员', 'short': '超管', 'cls': 'role-super',
                  'desc': '全部权限：用户与角色管理、系统设置、所有实例的任意操作、审计'},
    ADMIN: {'name': '管理员', 'short': '管理', 'cls': 'role-admin',
            'desc': '管理所有实例与查看审计；不可管理用户与系统设置'},
    USER: {'name': '普通用户', 'short': '用户', 'cls': 'role-user',
           'desc': '只能操作自己拥有的实例，受配额限制'},
    VIEWER: {'name': '只读', 'short': '只读', 'cls': 'role-viewer',
             'desc': '只读查看被授权的实例（控制台/状态/日志）'},
}
ROLES = tuple(ROLE_META)            # ('super_admin','admin','user','viewer')
ROLE_KEYS = ROLES
ROLE_NAMES = {k: v['name'] for k, v in ROLE_META.items()}


def role_name(role: str) -> str:
    """角色中文名（未知角色原样返回，便于排查脏数据）。"""
    meta = ROLE_META.get(str(role or ''))
    return meta['name'] if meta else str(role or '未知角色')


# ---------------------------------------------------------------- 权限点
P_INSTANCE_CREATE = 'instance.create'
P_INSTANCE_DELETE = 'instance.delete'
P_INSTANCE_START = 'instance.start'
P_INSTANCE_STOP = 'instance.stop'
P_INSTANCE_COMMAND = 'instance.command'
P_INSTANCE_FILES = 'instance.files'
P_INSTANCE_PLUGINS = 'instance.plugins'
P_INSTANCE_BACKUP = 'instance.backup'
P_INSTANCE_CRON = 'instance.cron'
P_INSTANCE_BUILD = 'instance.build_import'
P_INSTANCE_NETWORK = 'instance.settings_network'
P_USER_MANAGE = 'user.manage'
P_SYSTEM_SETTINGS = 'system.settings'
P_AUDIT_VIEW = 'audit.view'
P_LOG_VIEW = 'log.view'

#: 语义别名：规格 §2「普通用户不可改实例设置」。命名权限点只有
#: `instance.settings_network` 一个（见 `ALL_PERMS`），实例设置类路由统一用它，
#: 既不发明新的权限点名字，又能让"改端口/绑定"这条规则只在一处生效。
P_SETTINGS = P_INSTANCE_NETWORK

ALL_PERMS = (
    P_INSTANCE_CREATE, P_INSTANCE_DELETE, P_INSTANCE_START, P_INSTANCE_STOP,
    P_INSTANCE_COMMAND, P_INSTANCE_FILES, P_INSTANCE_PLUGINS, P_INSTANCE_BACKUP,
    P_INSTANCE_CRON, P_INSTANCE_BUILD, P_INSTANCE_NETWORK,
    P_USER_MANAGE, P_SYSTEM_SETTINGS, P_AUDIT_VIEW, P_LOG_VIEW,
)

#: 对**单个实例**生效的权限点（超管/管理员天然对全部实例生效；
#: 普通用户必须是自己拥有的实例才生效；只读一律不生效）。
_INSTANCE_SCOPED = frozenset((
    P_INSTANCE_DELETE, P_INSTANCE_START, P_INSTANCE_STOP, P_INSTANCE_COMMAND,
    P_INSTANCE_FILES, P_INSTANCE_PLUGINS, P_INSTANCE_BACKUP, P_INSTANCE_CRON,
    P_INSTANCE_BUILD, P_INSTANCE_NETWORK,
))

#: 普通用户权限集。规格 §2 写「只能操作自己拥有的实例（owner_id），受配额限制」，
#: 所以 `instance.files` / `instance.plugins` **必须**在列 —— 文件 Tab 就是实例目录浏览器
#: （读写 server.properties、memory 相关配置、上传/删除 jar、plugins/mods 目录），
#: 实例所有者对**自己实例**的这两项操作正是规格 §2「管理自己的实例」的核心内容，
#: 且仍受 `require_instance` 归属校验 + `max_upload_mb` 配额约束。
#: 规格 §6.4 的「菜单与按钮按权限隐藏」依赖这份集合的**成员判定**
#: （例如 `allow_build_import=false` 时前端把建筑 Tab 显示为禁用态），
#: 因此它与 `allow_build_import`（配额）是**两层**开关，不互相替代。
_USER_PERMS = frozenset((
    P_INSTANCE_CREATE, P_INSTANCE_START, P_INSTANCE_STOP, P_INSTANCE_COMMAND,
    P_INSTANCE_FILES, P_INSTANCE_PLUGINS, P_INSTANCE_BACKUP, P_INSTANCE_CRON,
    P_INSTANCE_BUILD, P_LOG_VIEW,
))

_ADMIN_PERMS = frozenset(p for p in ALL_PERMS if p not in (P_USER_MANAGE, P_SYSTEM_SETTINGS))

#: ⚠️ `viewer` **故意留空**：一切写操作默认被拒（见模块 docstring 第 2 条）。
#: 只读档位的"读"由 `can_view_instance()` 按角色放行，不依赖权限点。
_VIEWER_PERMS = frozenset()

_ROLE_PERMS = {
    SUPER_ADMIN: frozenset(ALL_PERMS),
    ADMIN: _ADMIN_PERMS,
    USER: _USER_PERMS,
    VIEWER: _VIEWER_PERMS,
}

# ---------------------------------------------------------------- 配额
QUOTA_FIELDS = ('max_instances', 'max_memory_mb_total', 'max_backups',
                'max_upload_mb', 'allow_build_import')
QUOTA_LIMITS = {'max_instances': 10000, 'max_memory_mb_total': 1048576,
                'max_backups': 10000, 'max_upload_mb': 10485760}

#: 角色默认配额（前端 mock 的取值口径；建号时未显式给配额就用这份）。
#: 超管不受配额约束（这里给一个"很大"的值只是为了 API 字段齐全）。
DEFAULT_QUOTA = {
    SUPER_ADMIN: {'max_instances': 20, 'max_memory_mb_total': 65536,
                  'max_backups': 50, 'max_upload_mb': 1024, 'allow_build_import': True},
    ADMIN: {'max_instances': 10, 'max_memory_mb_total': 32768,
            'max_backups': 20, 'max_upload_mb': 512, 'allow_build_import': True},
    USER: {'max_instances': 3, 'max_memory_mb_total': 8192,
           'max_backups': 5, 'max_upload_mb': 128, 'allow_build_import': False},
    VIEWER: {'max_instances': 0, 'max_memory_mb_total': 0,
             'max_backups': 0, 'max_upload_mb': 0, 'allow_build_import': False},
}


# ---------------------------------------------------------------- 错误与判定
class PermError(HTTPException):
    """权限不足 → 403（只有"最后一个超管"这类业务约束用 400，见 routers/users.py）。

    `main.py` 注册了统一异常处理器，所以直接在普通函数里 `raise` 即可，
    不依赖 FastAPI 的依赖注入链。
    """

    def __init__(self, detail: str, status_code: int = 403, code: str = ''):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code or f'perm_{status_code}'


def _uid(user) -> int:
    return int((user or {}).get('id') or 0)


def _role(user) -> str:
    return str((user or {}).get('role') or '')


def user_perms(user) -> list:
    """该用户实际拥有的权限点（按 `ALL_PERMS` 声明顺序，便于前端稳定展示）。"""
    if not user:
        return []
    granted = _ROLE_PERMS.get(_role(user), frozenset())
    return [p for p in ALL_PERMS if p in granted]


def has_perm(user, perm: str) -> bool:
    if not user:
        return False
    return perm in _ROLE_PERMS.get(_role(user), frozenset())


def is_admin(user) -> bool:
    """超管或管理员（可见全部实例）。"""
    return _role(user) in (SUPER_ADMIN, ADMIN)


def is_super(user) -> bool:
    return _role(user) == SUPER_ADMIN


def require_perm(user, perm: str):
    """校验权限点；不足则 403 + 中文原因（说明当前角色缺哪个权限点）。带上 user 便于复用。"""
    if not user:
        raise PermError('未登录', status_code=401, code='perm_401')
    if not has_perm(user, perm):
        raise PermError(
            f'权限不足：当前角色「{role_name(_role(user))}」没有 `{perm}` 权限，'
            f'请联系超级管理员')
    return user


def can_view_instance(user, row) -> bool:
    """实例**读**权限。

    ⚠️ 这里**不能**用 `has_perm(user, P_LOG_VIEW)` 来放行 —— 那是个真实的越权漏洞：
    `log.view` 的本意是"**被授权的**实例上看日志"（规格 §2 只读档），
    而"哪些实例算被授权"由归属决定。若把它当成"能看全部实例"的通行证，
    普通用户（权限集里也有 log.view）就能读到别人的实例详情/文件/备份。

    所以判定顺序固定为：超管/管理员看全部 → 属主看自己的 → `viewer` 角色可读
    （只读档位的语义），其余一律拒绝。
    """
    if not user or not row:
        return False
    if is_admin(user):
        return True
    if int(row.get('owner_id') or 0) == _uid(user):
        return True
    return _role(user) == VIEWER


def can_view_logs(user, row) -> bool:
    """控制台/日志：超管、管理员、属主、只读（`viewer` 只有 `log.view`）。

    规格 §2 只读档原文「只读查看被授权的实例（控制台/状态/日志）」—— 控制台赫然在列，
    所以这里不能要求 `instance.command`（否则 viewer 看不到任何东西）。
    """
    return can_view_instance(user, row)


def require_instance(user, iid, perm: Optional[str] = None, alive: bool = True) -> dict:
    """实例级权限校验：**校验 + 取行** 一次完成，供各路由直接调用。

    - `perm=None` → 只要求"能看这个实例"（读接口）；
    - `perm='instance.start'` 等 → 除归属外还要求该权限点；**超管/管理员对全部实例放行**，
      普通用户必须是自己拥有的实例，只读一律被拒；
    - `alive=True` → 不存在时 404；`False` → 返回 `None`（供"归属可选"的调用方兜底）。
    """
    row = query('SELECT * FROM instances WHERE id=?', (int(iid),), one=True)
    if not row:
        if not alive:
            return None
        raise HTTPException(status_code=404, detail='实例不存在')

    owner_id = int(row.get('owner_id') or 0)
    mine = owner_id == _uid(user)

    if perm:
        # 超管/管理员：权限点齐全即对任意实例生效。
        if is_admin(user) and has_perm(user, perm):
            return row
        if not mine:
            raise PermError(f'权限不足：该实例不属于你（归属用户 id={owner_id or "未分配"}），'
                            f'无法执行 `{perm}`')
        if not has_perm(user, perm):
            raise PermError(f'权限不足：当前角色「{role_name(_role(user))}」没有 `{perm}` 权限')
        return row

    if is_admin(user) or mine or _role(user) == VIEWER:
        return row
    raise PermError('权限不足：该实例不属于你，且当前角色没有查看权限')


# ---------------------------------------------------------------- 查询辅助
def instance_count(owner_id: int) -> int:
    row = query('SELECT COUNT(*) AS n FROM instances WHERE owner_id=?', (owner_id,), one=True)
    return int(row['n']) if row else 0


def instance_counts() -> dict:
    """一次查全部用户的实例数（列表页 N+1 的替代）。"""
    rows = query('SELECT owner_id, COUNT(*) AS n FROM instances GROUP BY owner_id')
    return {int(r['owner_id'] or 0): int(r['n']) for r in rows}


def ensure_columns(conn):
    """建表/迁移：`instances.owner_id`（归属）。在 `database.init_db()` 事务里调用。"""
    from .database import ensure_column
    ensure_column(conn, 'instances', 'owner_id', 'INTEGER')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_instances_owner ON instances(owner_id)')


def resolve_init_admin() -> Optional[int]:
    """孤儿实例（`owner_id` 为空）的接管者：第一个超管，其次任意超管，最后第一个账号。"""
    row = query('SELECT id FROM users WHERE role=? ORDER BY id ASC LIMIT 1',
                (SUPER_ADMIN,), one=True)
    if not row:
        row = query('SELECT id FROM users ORDER BY id ASC LIMIT 1', one=True)
    return int(row['id']) if row else None


def assign_orphans() -> int:
    """把没有归属的实例交给初始超管（旧的单账号库升级上来的必然情形）。

    幂等：没有 `owner_id IS NULL` 的行时什么也不做，返回 0。
    """
    row = query('SELECT COUNT(*) AS n FROM instances WHERE owner_id IS NULL', one=True)
    if not row or not int(row['n']):
        return 0
    aid = resolve_init_admin()
    if not aid:
        return 0
    n = int(row['n'])
    execute('UPDATE instances SET owner_id=? WHERE owner_id IS NULL', (aid,))
    return n


# ---------------------------------------------------------------- 配额
def default_quota_for_user(role: str) -> dict:
    """按角色给默认配额。客户端可覆盖；这里只负责给一份合法初值。"""
    base = dict(DEFAULT_QUOTA.get(str(role or ''), DEFAULT_QUOTA[USER]))
    try:
        from .routers.users import DEFAULT_QUOTA as ROUTER_QUOTA     # 唯一出处
        base.update(dict(ROUTER_QUOTA.get(str(role or ''), {})))
    except Exception:
        pass
    return base


def quota_of(user) -> dict:
    """从用户行取配额（列缺失/为空时回落到角色默认值）。"""
    role = _role(user)
    out = dict(DEFAULT_QUOTA.get(role, DEFAULT_QUOTA[USER]))
    for f in QUOTA_FIELDS:
        if f in (user or {}) and user[f] is not None:
            out[f] = user[f]
    out['allow_build_import'] = bool(out.get('allow_build_import'))
    for f in ('max_instances', 'max_memory_mb_total', 'max_backups', 'max_upload_mb'):
        out[f] = int(out.get(f) or 0)
    return out


def quota_usage(uid: int) -> dict:
    """某用户的配额占用：实例数 / 已申请内存合计 / 备份数。"""
    uid = int(uid or 0)
    irow = query('SELECT COUNT(*) AS n, COALESCE(SUM(memory_mb),0) AS mem '
                 'FROM instances WHERE owner_id=?', (uid,), one=True)
    brow = query('SELECT COUNT(*) AS n FROM backups b JOIN instances i ON i.id=b.instance_id '
                 'WHERE i.owner_id=?', (uid,), one=True)
    return {'instances': int(irow['n']) if irow else 0,
            'memory_mb': int(irow['mem']) if irow else 0,
            'backups': int(brow['n']) if brow else 0}


def check_quota(user, what: str, amount: int = 0, limit: Optional[int] = None) -> None:
    """配额逐项校验；超限 **403 + 中文原因**（规格 §3）。

    `what` ∈ `instance` / `memory` / `upload` / `backup` / `build_import`。
    超管不受配额约束（规格 §2：超级管理员=全部权限）。
    允许"超额后不变更"（例如实例数已超限时不再放行新建，但仍可删除）。
    """
    if not user or is_super(user):
        return
    quo = quota_of(user)
    uid = _uid(user)
    use = quota_usage(uid)

    if what == 'instance':
        cap = quo['max_instances'] if limit is None else int(limit)
        if use['instances'] + 1 > cap:
            raise PermError(
                f'实例数已达上限 {cap} 个（当前 {use["instances"]} 个），'
                f'无法再创建，请联系超级管理员调整配额')
        return

    if what == 'memory':
        cap = quo['max_memory_mb_total'] if limit is None else int(limit)
        now_mb = use['memory_mb']
        want = int(amount or 0)
        if now_mb + want > cap:
            raise PermError(
                f'内存配额不足：已申请 {now_mb} MB，本次再加 {want} MB 将超过上限 {cap} MB，'
                f'请联系超级管理员调整配额')
        return

    if what == 'upload':
        cap = quo['max_upload_mb'] if limit is None else int(limit)
        mb = (int(amount or 0) + 1024 * 1024 - 1) // (1024 * 1024)
        if mb > cap:
            raise PermError(f'上传配额不足：该文件约 {mb} MB，超过上限 {cap} MB，'
                            f'请联系超级管理员调整配额')
        return

    if what == 'backup':
        cap = quo['max_backups'] if limit is None else int(limit)
        if use['backups'] + 1 > cap:
            raise PermError(f'备份数已达上限 {cap} 个（当前 {use["backups"]} 个），'
                            f'请先删除旧备份或联系超级管理员调整配额')
        return

    if what == 'build_import':
        if not quo.get('allow_build_import'):
            raise PermError('该账号未开通「建筑导入」权限，请联系超级管理员开通')
        if limit is not None:
            cap = int(limit)
            if int(amount or 0) > cap:
                raise PermError(f'该接口体积上限 {cap} MB，本次 {int(amount or 0)} MB 超出限制')
        return

    raise ValueError(f'未知的配额类型: {what}')


# ---------------------------------------------------------------- 前端用的权限快照
def permission_flags(user) -> dict:
    """给前端渲染按钮用的**派生布尔**（不是权限点本身，供 UI 少写判断）。

    取值全部来自 `has_perm` / 配额，前端只读不算安全 —— 后端仍逐个路由兜底。
    """
    quo = quota_of(user)
    return {
        'view_all_instances': is_admin(user),
        'manage_users': has_perm(user, P_USER_MANAGE),
        'system_settings': has_perm(user, P_SYSTEM_SETTINGS),
        'view_audit': has_perm(user, P_AUDIT_VIEW),
        'view_logs': has_perm(user, P_LOG_VIEW),
        'create_instance': has_perm(user, P_INSTANCE_CREATE),
        'build_import': has_perm(user, P_INSTANCE_BUILD) and bool(quo.get('allow_build_import')),
        'upload_mb': quo['max_upload_mb'],
    }


def permissions_payload(user) -> dict:
    """`GET /api/me/permissions` 的响应体（契约 §1.16：`{ok, role, perms, quota}`）。"""
    role = _role(user)
    uid = _uid(user)
    return {
        'ok': True,
        'role': role,
        'role_name': role_name(role),
        'role_meta': ROLE_META.get(role, {}),
        'roles': [dict(ROLE_META[k], key=k) for k in ROLES],
        'perms': user_perms(user),
        'all_perms': list(ALL_PERMS),
        'quota': quota_of(user),
        'quota_usage': quota_usage(uid),
        'flags': permission_flags(user),
    }
