"""SQLite 数据层：连接、建表、通用查询辅助（与 RT面板 同风格）。"""
import os
import sqlite3
import threading
import time

from .config import DATA_DIR

DB_FILE = os.path.join(DATA_DIR, 'mc.db')

_write_lock = threading.RLock()
_local = threading.local()

#: 账号与权限相关列（`docs/FEATURE-ACCOUNTS.md` §3）。
#: 单位：MB / 个数；`allow_build_import` 用 0/1（SQLite 无布尔）。
USER_QUOTA_COLUMNS = (
    ('max_instances', 'INTEGER NOT NULL DEFAULT 3'),
    ('max_memory_mb_total', 'INTEGER NOT NULL DEFAULT 8192'),
    ('max_backups', 'INTEGER NOT NULL DEFAULT 5'),
    ('max_upload_mb', 'INTEGER NOT NULL DEFAULT 128'),
    ('allow_build_import', 'INTEGER NOT NULL DEFAULT 0'),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    status INTEGER NOT NULL DEFAULT 1,
    token_epoch INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_login REAL,
    max_instances INTEGER NOT NULL DEFAULT 3,
    max_memory_mb_total INTEGER NOT NULL DEFAULT 8192,
    max_backups INTEGER NOT NULL DEFAULT 5,
    max_upload_mb INTEGER NOT NULL DEFAULT 128,
    allow_build_import INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    uid INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    ip TEXT DEFAULT '',
    ua TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner_id INTEGER,
    core_type TEXT NOT NULL DEFAULT 'vanilla',
    mc_version TEXT DEFAULT '',
    core_version TEXT DEFAULT '',
    jar_path TEXT DEFAULT '',
    java_path TEXT DEFAULT '',
    memory_mb INTEGER NOT NULL DEFAULT 2048,
    port INTEGER NOT NULL DEFAULT 25565,
    dir TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'stopped',
    pid INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    last_start_at REAL,
    last_stop_at REAL,
    auto_restart INTEGER NOT NULL DEFAULT 0,
    restart_count INTEGER NOT NULL DEFAULT 0,
    extra_jvm_args TEXT DEFAULT '',
    extra_server_args TEXT DEFAULT '',
    nogui INTEGER NOT NULL DEFAULT 1,
    rcon_enabled INTEGER NOT NULL DEFAULT 0,
    rcon_port INTEGER NOT NULL DEFAULT 25575,
    rcon_password TEXT DEFAULT '',
    accept_eula INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER,
    last_crash TEXT DEFAULT '',
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    user TEXT DEFAULT '',
    ip TEXT DEFAULT '',
    action TEXT NOT NULL,
    instance_id INTEGER,
    detail TEXT DEFAULT '',
    level TEXT DEFAULT 'info'
);

CREATE TABLE IF NOT EXISTS login_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    username TEXT DEFAULT '',
    ip TEXT DEFAULT '',
    ua TEXT DEFAULT '',
    success INTEGER NOT NULL,
    reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    cpu REAL DEFAULT 0,
    mem_mb REAL DEFAULT 0,
    players INTEGER DEFAULT 0,
    tps REAL,
    mspt REAL
);
CREATE INDEX IF NOT EXISTS idx_metrics_inst_ts ON metrics(instance_id, ts);

CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL,
    file TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    kind TEXT DEFAULT 'manual',
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_backups_inst ON backups(instance_id, created_at);

CREATE TABLE IF NOT EXISTS cron_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER,
    name TEXT NOT NULL,
    schedule TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'command',
    payload TEXT DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_run REAL,
    last_status TEXT DEFAULT '',
    next_run REAL
);

CREATE TABLE IF NOT EXISTS cron_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    status TEXT DEFAULT '',
    output TEXT DEFAULT '',
    duration REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cron_runs_job ON cron_runs(job_id, ts);

CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT DEFAULT '',
    url TEXT DEFAULT '',
    dest TEXT DEFAULT '',
    total INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    error TEXT DEFAULT '',
    started_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS crash_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    exit_code INTEGER,
    tail TEXT DEFAULT '',
    action TEXT DEFAULT ''
);
"""


def connect() -> sqlite3.Connection:
    conn = getattr(_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(DB_FILE, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        _local.conn = conn
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> bool:
    """幂等加列（SQLite 没有 `ADD COLUMN IF NOT EXISTS`）。

    老库升级上来时缺列 → 补上；已存在则什么都不做。返回是否真的加了列。
    只接受**字面量**表名/列名/类型（它们全部来自本文件的常量，不接受外部输入）。
    """
    cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if column in cols:
        return False
    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {decl}')
    return True


def migrate(conn: sqlite3.Connection) -> int:
    """账号与权限相关的老库迁移：`instances.owner_id` + `users` 配额列。"""
    added = 0
    if ensure_column(conn, 'instances', 'owner_id', 'INTEGER'):
        added += 1
    for col, decl in USER_QUOTA_COLUMNS:
        if ensure_column(conn, 'users', col, decl):
            added += 1
    conn.execute('CREATE INDEX IF NOT EXISTS idx_instances_owner ON instances(owner_id)')
    return added


def init_db():
    with _write_lock:
        conn = connect()
        conn.executescript(SCHEMA)
        created = migrate(conn)
        conn.commit()
    if created:
        print(f'[mcpanel] 数据表已升级：新增 {created} 个列（账号/权限迁移）', flush=True)
    return created


def query(sql: str, args: tuple = (), one: bool = False):
    cur = connect().execute(sql, args)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, args: tuple = ()):
    with _write_lock:
        conn = connect()
        cur = conn.execute(sql, args)
        conn.commit()
        lastrow = cur.lastrowid
        cur.close()
        return lastrow


def execute_many(sql: str, seq):
    with _write_lock:
        conn = connect()
        conn.executemany(sql, seq)
        conn.commit()


def now() -> float:
    return time.time()
