# -*- coding: utf-8 -*-
"""对照实验：服务端监控循环采到的 cpu 与"直接量同一个 PID"是否一致。

因为 psutil 的 cpu_percent 对"跨进程"的对象也能算（Windows 上用的是系统级
cpu_times），所以可以在测试进程里直接量 java 的占用，与服务端写入的值比对。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path[:0] = [BACKEND, os.path.join(BACKEND, '.deps')]

import psutil  # noqa: E402

from app.database import init_db, query  # noqa: E402
from app.process_manager import manager  # noqa: E402

init_db()
rows = query('SELECT id, name, status FROM instances ORDER BY id')
print('实例:')
for r in rows:
    print('  #%s %-18s status=%s' % (r['id'], r['name'], r['status']))

target = None
for r in rows:
    st = manager.status(r['id'])
    if st['running']:
        target = (r['id'], r['name'], st)
        break

if not target:
    print('\n没有正在运行的实例 —— 请先启动一个再跑本脚本')
    sys.exit(0)

iid, name, st = target
pid = st['pid']
print('\n被测: #%s %s  pid=%s' % (iid, name, pid))

p = psutil.Process(pid)
print('  服务端 status() 报的 cpu = %s' % st['cpu'])
print('  服务端 status() 报的 mem = %s MB' % st['mem_mb'])

print('\n直接采样（与监控循环同法，连续 5 次）:')
vals = []
for i in range(5):
    p.cpu_percent(interval=None)
    time.sleep(0.2)
    v = p.cpu_percent(interval=None)
    vals.append(v)
    print('   第%d次 = %.1f%%   (mem=%.1f MB)' % (i + 1, v, p.memory_info().rss / 1048576))
    time.sleep(0.8)

print('\n结论:')
print('  直接采样最大 %.1f%%，服务端上报 %s%%' % (max(vals), st['cpu']))
if max(vals) > 0.5 and float(st['cpu'] or 0) == 0.0:
    print('  ❌ 服务端监控循环没有采到真实值（采样路径有问题）')
elif max(vals) <= 0.5:
    print('  ✅ 该进程占用本来就极低（<0.5%%），显示 0.0% 是**真实值**，不是 bug')
else:
    print('  ✅ 两边都非 0，基本一致')
