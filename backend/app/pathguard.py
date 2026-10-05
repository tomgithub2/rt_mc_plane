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
