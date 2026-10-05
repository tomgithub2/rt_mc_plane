"""表征 /api/instances 的 429：在**全新库**的独立实例上做最小复现。

对照：
  A. 连续请求 /api/instances 10 次 → 记录每次状态码
  B. 连续请求 /api/health 10 次（同一中间件路径，但不在限流分支）→ 对照
  C. 连续请求 /api/settings 10 次 → 另一个受同一限流的路径
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[2] if len(sys.argv) > 2 else 'http://127.0.0.1:8110'


def call(method, path, body=None, tok=None, full=False):
    h = {'User-Agent': 'ratelimit-probe'}
    if tok:
        h['Authorization'] = 'Bearer ' + tok
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as f:
            raw = f.read().decode('utf-8', 'replace')
            return f.status, raw if full else raw[:80]
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        return e.code, raw if full else raw[:80]
    except Exception as e:
        return -1, str(e)[:80]


def seq(label, path, n=10, tok=None):
    codes = []
    for _ in range(n):
        st, b = call('GET', path, tok=tok)
        codes.append(st)
    print('  %-22s -> %s' % (label, codes))
    return codes


def main():
    st, b = call('POST', '/api/auth/login', {'username': 'admin', 'password': sys.argv[1]})
    if st != 200:
        print('登录失败', st, b)
        return 1
    st2, b2 = call('POST', '/api/auth/login', {'username': 'admin', 'password': sys.argv[1]}, full=True)
    tok = json.loads(b2)['token'] if st2 == 200 else ''
    if not tok:
        print('拿不到令牌', st2, b2[:120])
        return 1
    print('登录 OK ; 目标 =', BASE)
    print()
    print('--- A. /api/instances 连续 10 次 ---')
    seq('/api/instances', '/api/instances', 10, tok)
    print('--- B. /api/health 连续 10 次（免鉴权，不在限流分支）---')
    seq('/api/health', '/api/health', 10)
    print('--- C. /api/settings 连续 10 次 ---')
    seq('/api/settings', '/api/settings', 10, tok)
    print('--- D. 隔 3 秒后再打一次 /api/instances ---')
    import time
    time.sleep(3)
    print('  /api/instances ->', call('GET', '/api/instances', tok=tok)[0])
    time.sleep(3)
    print('  /api/instances ->', call('GET', '/api/instances', tok=tok)[0])
    return 0


if __name__ == '__main__':
    sys.exit(main())
