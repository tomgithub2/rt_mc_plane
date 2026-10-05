"""审计日志（面板自身操作）与登录日志。"""
from .database import execute, now


def audit(user, ip: str, action: str, instance_id=None, detail: str = '', level: str = 'info'):
    try:
        execute('INSERT INTO audit_logs (ts, user, ip, action, instance_id, detail, level) '
                'VALUES (?,?,?,?,?,?,?)',
                (now(), str(user or ''), str(ip or ''), str(action),
                 instance_id, str(detail)[:2000], level))
    except Exception:
        pass


def login_log(username: str, ip: str, ua: str, success: bool, reason: str = ''):
    try:
        execute('INSERT INTO login_logs (ts, username, ip, ua, success, reason) '
                'VALUES (?,?,?,?,?,?)',
                (now(), str(username or ''), str(ip or ''), str(ua or '')[:200],
                 1 if success else 0, str(reason or '')[:300]))
    except Exception:
        pass


def audit_ctx(request, user, action: str, instance_id=None, detail: str = '', level: str = 'info'):
    ip = request.client.host if request.client else ''
    uname = (user or {}).get('username', '') if isinstance(user, dict) else str(user or '')
    audit(uname, ip, action, instance_id, detail, level)
