# -*- coding: utf-8 -*-
"""前后端 URL 交叉核对：把前端的 API.get/post 路径与后端真实路由表比对。

用途：这一类 bug（前端请求了后端不存在的路径 → 静默 404 → 界面"没反应"）
靠肉眼看代码很难发现，必须机器比对。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
sys.path[:0] = [BACKEND, os.path.join(BACKEND, '.deps')]

from app import main as app_main  # noqa: E402

real = set(app_main._ROUTE_PATHS)


def norm(p: str) -> str:
    """把前端拼接出来的路径与后端路由统一成同一种"形状"用于比对：
    :id / {iid} / 数字 / 模板占位 全部替换为 {}。"""
    p = p.split('?')[0].rstrip('/')
    p = re.sub(r'\$\{[^}]*\}', '{}', p)          # 模板占位（JS 里可能被截断）
    p = re.sub(r"'[^']*'", '{}', p)              # 字符串拼接
    p = re.sub(r'"[^"]*"', '{}', p)
    p = re.sub(r'\{[^}]*\}', '{}', p)
    p = re.sub(r':[A-Za-z_]\w*', '{}', p)
    p = re.sub(r'/\d+', '/{}', p)
    return p


real_shapes = {}
for r in real:
    real_shapes.setdefault(norm(r), r)

# 抓前端所有 API.get / API.post / API.put / API.patch / API.del / API.upload 的第一个参数
JS_DIRS = [os.path.join(ROOT, 'frontend', 'dist', 'js')]
pat = re.compile(
    r"""API\.(get|post|put|patch|del|delete|upload)\s*\(\s*(['"`])(.+?)\2""",
    re.S)
# 也抓拼接形式：API.get('/api/x/' + id + '/y')
pat2 = re.compile(
    r"""API\.(get|post|put|patch|del|delete|upload)\s*\(\s*([^,\n)]+)""")

found = []
for d in JS_DIRS:
    for dp, _dn, fns in os.walk(d):
        for fn in fns:
            if not fn.endswith('.js'):
                continue
            fp = os.path.join(dp, fn)
            src = io.open(fp, encoding='utf-8').read()
            for m in pat.finditer(src):
                found.append((os.path.relpath(fp, ROOT), m.group(3)))
            for m in pat2.finditer(src):
                expr = m.group(2).strip()
                if expr.startswith(("'", '"', '`')):
                    continue                      # 上面已处理
                if '/api/' not in expr:
                    continue
                # 取整段表达式里的路径骨架
                found.append((os.path.relpath(fp, ROOT), expr))

print('后端真实 API 路由 %d 条；前端引用 %d 处\n' % (len(real), len(found)))

bad = []
ok = 0
for f, rawpath in found:
    shape = norm(rawpath)
    if not shape.startswith('/api'):
        continue
    if shape in real_shapes:
        ok += 1
        continue
    # 允许前缀匹配（例如 '/api/instances/' + id + '/build/tasks' 会被截断成 '/api/instances/{}'）
    pref = [k for k in real_shapes if k.startswith(shape) or shape.startswith(k)]
    if pref:
        ok += 1
        continue
    bad.append((f, rawpath.strip(), shape))

if bad:
    print('❌ 疑似前端调了后端不存在的路径：')
    seen = set()
    for f, raw, shape in bad:
        key = (f, shape)
        if key in seen:
            continue
        seen.add(key)
        print('   %-42s %s' % (f, raw.strip()[:80]))
        print('   %-42s   → 归一化 %s' % ('', shape))
else:
    print('✅ 前端所有 /api 路径都能在后端路由表里找到')

print('\n匹配成功 %d 处' % ok)
