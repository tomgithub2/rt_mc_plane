"""路径守卫：所有文件类操作必须限制在实例目录内（realpath + commonpath）。

拒绝三类逃逸：
  1. `../` 相对穿越
  2. 绝对路径越界
  3. 符号链接/junction 指向目录外（用 realpath 解析后再比对）
"""
import os

from fastapi import HTTPException


def _rp(path) -> str:
    return os.path.realpath(os.path.abspath(str(path or '').strip()))


def _key(path) -> str:
    """比较用的归一化键：realpath + normcase。

    Windows 文件系统大小写不敏感，若只用字符串比较，
    `C:\\Servers\\A` 与 `c:\\servers\\a\\..\\..` 这类输入可能绕过包含性判断。
    normcase 在 Windows 上统一小写并把 `/` 归一为 `\\`，在 POSIX 上是恒等操作。
    """
    return os.path.normcase(_rp(path))


def inside(child, parent) -> bool:
    """child 是否在 parent 之内（含 parent 自身）。

    比较走 `_key()`（realpath + normcase），且用 commonpath 而非字符串前缀，
    因此 `..\\` 穿越、绝对路径越界、符号链接逃逸、大小写变形都会被判定为“不在内”。
    """
    c, p = _key(child), _key(parent)
    if not c or not p:
        return False
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:          # 不同盘符 / 非法路径
        return False


def safe_join(root: str, rel: str) -> str:
    """把用户给的相对路径拼到 root 下并校验；越界抛 403。"""
    root_rp = _rp(root)
    rel = str(rel or '').replace('\\', '/').strip()
    if rel.startswith('/') or (len(rel) > 1 and rel[1] == ':'):
        raise HTTPException(status_code=403, detail='不允许使用绝对路径')
    target = _rp(os.path.join(root_rp, rel)) if rel else root_rp
    if target != root_rp and not inside(target, root_rp):
        raise HTTPException(status_code=403, detail='路径越界：仅允许访问实例目录内的文件')
    # 逐段检查，避免中间段落是符号链接却最终拼回目录内（防御性，realpath 已覆盖）
    return target


def assert_inside(path: str, root: str) -> str:
    """校验绝对/相对路径位于 root 内，返回 realpath；否则 403。"""
    rp = _rp(path)
    root_rp = _rp(root)
    if rp != root_rp and not inside(rp, root_rp):
        raise HTTPException(status_code=403, detail='路径越界：仅允许访问实例目录内的文件')
    return rp


def rel_to(path: str, root: str) -> str:
    """返回相对 root 的 POSIX 风格相对路径。"""
    rp, root_rp = _rp(path), _rp(root)
    try:
        rel = os.path.relpath(rp, root_rp)
    except ValueError:
        return ''
    return '' if rel == '.' else rel.replace('\\', '/')


#: ⛔ 绝不允许把实例目录放在这些位置（系统目录 / 面板自身程序目录）。
#   「自选存放目录」这个功能让用户可以指定任意绝对路径，所以必须有一道黑名单兜底：
#   否则一个手滑就能把世界文件写进 /usr 或覆盖掉面板自己的代码。
_FORBIDDEN_EXACT = {
    '/', '/bin', '/boot', '/dev', '/etc', '/home', '/lib', '/lib32', '/lib64',
    '/media', '/mnt', '/opt', '/proc', '/root', '/run', '/sbin', '/srv', '/sys',
    '/tmp', '/usr', '/var',
    'C:\\', 'C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)', 'C:\\Users',
    os.environ.get('SystemRoot', 'C:\\Windows'),
}

#: ⛔ 前缀黑名单：落在这些前缀**之下**的路径也不允许（面板程序目录、系统目录、家目录）。
#: ⚠️ `/root` 与 `/home` 必须在这里 —— 只把它们放精确黑名单是**不够**的：
#:    精确名单只挡 `/root` 本身，`/root/mc` 这种子路径会漏过去（实测踩过）。
_FORBIDDEN_PREFIX = (
    '/etc', '/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64', '/libx32',
    '/boot', '/dev', '/proc', '/sys', '/run',
    '/var/log', '/var/lib/dpkg', '/var/lib/apt', '/var/spool',
    '/root', '/home',
)


def assert_safe_instance_dir(path: str, data_dir: str = '', extra_reserved=()) -> str:
    """校验「实例存放目录」是否安全，返回 realpath；不安全则 403。

    与 `assert_inside()` **用途相反**：那个是"必须待在某个目录里"，
    这个是"用户自选的任意目录，但必须避开系统与面板自身"。安全检查项：

      1. 必须是**绝对路径**（不能是相对路径，否则含义随工作目录漂移）
      2. 不能是文件系统根、家目录、以及常见系统目录（见 `_FORBIDDEN_EXACT`）
      3. 不能落在系统目录前缀之下（见 `_FORBIDDEN_PREFIX`）
      4. 不能在**面板自己的程序目录 / 数据目录之内**
         （否则删除实例时可能连带把面板的库或代码删掉 —— 这是最危险的一种）
      5. 已存在时必须是**空目录或尚无内容**，且可写；父目录必须存在且可写
    """
    raw = str(path or '').strip()
    if not raw:
        raise HTTPException(status_code=400, detail='存放目录不能为空')
    if not os.path.isabs(raw):
        raise HTTPException(status_code=400, detail='存放目录必须是绝对路径（如 /opt/mc-servers/生存服）')
    rp = _rp(raw)
    key = os.path.normcase(rp)

    # 2) 精确黑名单（含根、家目录、系统目录）
    home = os.path.normcase(_rp(os.path.expanduser('~')))
    if key in {os.path.normcase(_rp(p)) for p in _FORBIDDEN_EXACT if p} or key == home:
        raise HTTPException(status_code=403, detail=f'不允许把实例放在系统目录：{rp}')

    # 3) 前缀黑名单
    for bad in _FORBIDDEN_PREFIX:
        bk = os.path.normcase(_rp(bad))
        if key == bk or inside(rp, bk):
            raise HTTPException(status_code=403, detail=f'不允许把实例放在系统目录：{rp}')

    # 4) 面板自身的地盘（程序目录 / 数据目录）—— 最危险的一类，必须挡住
    reserved = []
    if data_dir:
        reserved.append(data_dir)
    reserved.extend(extra_reserved)
    for r in reserved:
        if not r:
            continue
        rk = _rp(r)
        if key == os.path.normcase(rk) or inside(rp, rk):
            raise HTTPException(
                status_code=403,
                detail=f'不能在面板自己的数据/程序目录内建实例：{rp}\n'
                       f'（若这不是你要的，请换一个独立目录）')

    # 5) 目录状态检查
    parent = os.path.dirname(rp) or os.sep
    if os.path.exists(rp):
        if not os.path.isdir(rp):
            raise HTTPException(status_code=400, detail=f'该路径已存在且不是目录：{rp}')
        if os.listdir(rp):
            raise HTTPException(
                status_code=409,
                detail=f'该目录不是空的：{rp}\n'
                       f'为避免覆盖已有数据，请改用一个空目录或新建一个子目录')
        if not os.access(rp, os.W_OK):
            raise HTTPException(status_code=403, detail=f'该目录不可写：{rp}')
    else:
        if not os.path.isdir(parent):
            raise HTTPException(status_code=400, detail=f'上级目录不存在：{parent}')
        if not os.access(parent, os.W_OK):
            raise HTTPException(status_code=403, detail=f'上级目录不可写：{parent}')
    return rp

