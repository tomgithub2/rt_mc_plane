"""计划任务：5 字段 cron 解析 + 后台调度线程 + 执行历史。

动作：
  restart  重启实例（优雅停 → 起）
  stop     停止实例
  start    启动实例
  backup   备份实例
  command  向实例控制台下发一条命令
  broadcast 下发 say <payload>
"""
import re
import threading
import time
import traceback

from .config import get_config
from .database import execute, now, query
from . import audit as audit_mod

_FIELDS = ('minute', 'hour', 'day', 'month', 'weekday')

_RANGES = {'minute': (0, 59), 'hour': (0, 23), 'day': (1, 31),
           'month': (1, 12), 'weekday': (0, 7)}


def _parse_field(field: str, lo: int, hi: int) -> set:
    out = set()
    for part in str(field).split(','):
        part = part.strip()
        if not part:
            continue
        step = 1
        if '/' in part:
            part, s = part.split('/', 1)
            step = int(s)
            if step <= 0:
                raise ValueError('步长必须为正整数')
        if part in ('*', ''):
            start, end = lo, hi
        elif '-' in part:
            a, b = part.split('-', 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if part == '*' and step == 1:
            start, end = lo, hi
        if start < lo or end > hi or start > end:
            raise ValueError(f'超出取值范围 {lo}-{hi}')
        for v in range(start, end + 1, step):
            out.add(v)
    if not out:
        raise ValueError('空字段')
    return out


def validate_cron(expr: str) -> str:
    """返回错误文案；空字符串表示合法。支持 5 段标准 cron。"""
    parts = str(expr or '').split()
    if len(parts) != 5:
        return 'cron 表达式需要 5 段：分 时 日 月 周（例：0 4 * * *）'
    try:
        for i, f in enumerate(parts):
            lo, hi = _RANGES[_FIELDS[i]]
            _parse_field(f, lo, hi)
    except ValueError as e:
        return f'cron 第 {i + 1} 段不合法：{e}'
    return ''


def _parse_expr(expr: str):
    """一次解析 5 段表达式，返回 (minute, hour, day, month, weekday, dom_restricted, dow_restricted)。"""
    parts = str(expr or '').split()
    if len(parts) != 5:
        raise ValueError('cron 表达式需要 5 段')
    minute = _parse_field(parts[0], 0, 59)
    hour = _parse_field(parts[1], 0, 23)
    day = _parse_field(parts[2], 1, 31)
    month = _parse_field(parts[3], 1, 12)
    wd = _parse_field(parts[4], 0, 7)
    dom_r = parts[2].strip() not in ('*', '')
    dow_r = parts[4].strip() not in ('*', '')
    return minute, hour, day, month, wd, dom_r, dow_r


def _match_parsed(p, ts: float) -> bool:
    minute, hour, day, month, wd, dom_r, dow_r = p
    tm = time.localtime(ts)
    if tm.tm_min not in minute or tm.tm_hour not in hour or tm.tm_mon not in month:
        return False
    wd_now = tm.tm_wday + 1                      # cron: 0/7=周日
    wd_ok = (wd_now in wd) or (wd_now == 7 and 0 in wd) or (wd_now == 0 and 7 in wd)
    dom_ok = tm.tm_mday in day
    # 标准 cron：日与周都被限定时取 OR；只有一个被限定就只看那一个
    if dom_r and dow_r:
        return dom_ok or wd_ok
    if dom_r:
        return dom_ok
    if dow_r:
        return wd_ok
    return True


def matches(expr: str, ts: float = None) -> bool:
    ts = ts if ts is not None else time.time()
    try:
        p = _parse_expr(expr)
    except (ValueError, TypeError):
        return False
    return _match_parsed(p, ts)


def next_run(expr: str, after: float = None) -> float:
    """粗算下次触发时间（最多向前找 366 天；解析一次后逐分钟比对，避免重复解析）。"""
    try:
        p = _parse_expr(expr)
    except (ValueError, TypeError):
        return 0.0
    t = int((after if after is not None else time.time()) // 60 * 60) + 60
    end = t + 366 * 24 * 60 * 60
    while t <= end:
        if _match_parsed(p, t):
            return float(t)
        t += 60
    return 0.0


_run_guards = {}
_guard_lock = threading.Lock()


def run_job(job: dict, trigger: str = 'schedule') -> dict:
    """执行一个计划任务，落库历史。"""
    from .process_manager import manager
    jid = job.get('id')
    with _guard_lock:
        if _run_guards.get(jid):
            return {'ok': False, 'status': 'skipped', 'output': '上一次执行尚未结束，本次跳过',
                    'duration': 0.0}
        _run_guards[jid] = True
    t0 = time.time()
    status, output = 'ok', ''
    try:
        action = job.get('action')
        iid = job.get('instance_id')
        payload = job.get('payload') or ''
        if action == 'restart':
            r = manager.restart(iid, by=f'cron:{job.get("name")}')
        elif action == 'start':
            r = manager.start(iid, by=f'cron:{job.get("name")}')
        elif action == 'stop':
            r = manager.stop(iid, by=f'cron:{job.get("name")}')
        elif action == 'backup':
            from . import serverctl
            if not iid:
                status, r = 'error', {'ok': False, 'error': 'backup 动作需要指定实例'}
            else:
                row = query('SELECT * FROM instances WHERE id=?', (iid,), one=True)
                r = (serverctl.create_backup(row, kind='cron',
                                             note=f'计划任务 {job.get("name")}')
                     if row else {'ok': False, 'error': f'实例 {iid} 不存在'})
        elif action == 'command':
            r = manager.send_command(iid, payload)
        elif action == 'broadcast':
            r = manager.send_command(iid, f'say {payload}')
        else:
            status, r = 'error', {'ok': False, 'error': f'未知动作：{action}'}
        output = str(r)
        if status == 'ok' and isinstance(r, dict) and r.get('ok') is False:
            status = 'error'
    except Exception as e:
        status = 'error'
        output = f'{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}'
    finally:
        with _guard_lock:
            _run_guards.pop(jid, None)
    dur = time.time() - t0
    execute('INSERT INTO cron_runs (job_id, ts, status, output, duration) VALUES (?,?,?,?,?)',
            (job['id'], now(), status, output[:4000], dur))
    execute('UPDATE cron_jobs SET last_run=?, last_status=?, next_run=? WHERE id=?',
            (now(), status, next_run(job['schedule']), job['id']))
    audit_mod.audit('system', '', 'cron.run', job.get('instance_id'),
                    f'计划任务「{job.get("name")}」[{trigger}] {status}: {output[:200]}',
                    level='info' if status == 'ok' else 'error')
    return {'ok': status == 'ok', 'status': status, 'output': output, 'duration': dur}


class Scheduler:
    def __init__(self, interval: int = 20):
        self.interval = interval
        self._stop = False
        self._thread = None
        self._last_minute = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True, name='mc-cron')
        self._thread.start()

    def stop(self):
        self._stop = True

    def _loop(self):
        # 启动时补齐 next_run 展示值
        try:
            for j in query('SELECT * FROM cron_jobs WHERE enabled=1'):
                execute('UPDATE cron_jobs SET next_run=? WHERE id=?',
                        (next_run(j['schedule']), j['id']))
        except Exception:
            pass
        while not self._stop:
            try:
                tm = time.localtime()
                key = (tm.tm_year, tm.tm_mon, tm.tm_mday, tm.tm_hour, tm.tm_min)
                jobs = query('SELECT * FROM cron_jobs WHERE enabled=1')
                for j in jobs:
                    try:
                        if not matches(j['schedule']):
                            continue
                        if self._last_minute.get(j['id']) == key:
                            continue        # 同一分钟只跑一次
                        self._last_minute[j['id']] = key
                        threading.Thread(target=run_job, args=(j, 'schedule'),
                                         daemon=True).start()
                    except Exception:
                        continue
                execute('DELETE FROM cron_runs WHERE ts < ?', (now() - 30 * 86400,))
            except Exception:
                pass
            time.sleep(self.interval)


scheduler = Scheduler()
