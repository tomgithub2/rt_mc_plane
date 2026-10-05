# -*- coding: utf-8 -*-
"""验证 CPU 采样修法：证明"每次新建 Process 直接读 cpu_percent()"恒为 0，
而"同一对象先采样一次再读"能得到真实百分比。

用一个真实在燃烧 CPU 的子进程做被测对象，两种写法都指向它。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path[:0] = [BACKEND, os.path.join(BACKEND, '.deps')]

import psutil  # noqa: E402

# 起一个真的在烧 CPU 的子进程
burn = subprocess.Popen([sys.executable, '-c',
                         'while True: pass'], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
time.sleep(1.5)
pid = burn.pid
print('被测进程 PID = %d（正在满核燃烧）' % pid)

try:
    # 旧写法：每次新建对象、直接读
    old = []
    for _ in range(3):
        p = psutil.Process(pid)
        old.append(p.cpu_percent(interval=None))
        time.sleep(0.5)

    # 新写法：同一对象先采样一次，隔 0.2s 再读
    new = []
    for _ in range(3):
        p = psutil.Process(pid)
        p.cpu_percent(interval=None)        # 建立基线
        time.sleep(0.2)
        new.append(p.cpu_percent(interval=None))
        time.sleep(0.3)

    print('  旧写法（直接读）        = %s' % ['%.1f' % v for v in old])
    print('  新写法（先采样再读）    = %s' % ['%.1f' % v for v in new])
    print()
    if max(new) > 50 and max(old) < 5:
        print('  ✅ 确认：旧写法恒为 0，新写法拿到真实占用')
    elif max(new) > 50:
        print('  ✅ 新写法拿到真实占用（旧写法本次也非 0，取快照时机不同）')
    else:
        print('  ⚠️ 新写法也没拿到高占用，需要再查')
finally:
    burn.kill()
    burn.wait()
    print('已清理测试进程')
