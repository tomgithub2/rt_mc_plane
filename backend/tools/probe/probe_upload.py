"""定位上传接口 422 的测试端/服务端边界（只读诊断，不改后端）。

依次尝试几种 multipart 构造方式，看哪种能被服务端接受：
  1. 标准：file 带 Content-Type + path 空值
  2. file 不带 Content-Type
  3. path 字段放在 file 之后
  4. 不做任何 form 字段，只有 file
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:8100'


def req(method, path, body=None, token=None, ctype='application/json'):
    h = {'User-Agent': 'up-test'}
    if token:
        h['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        if ctype == 'application/json':
            data = json.dumps(body).encode('utf-8')
            h['Content-Type'] = 'application/json'
        else:
            data = body
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return -1, str(e)


def build(boundary, file_ct=True, path_first=True, include_path=True, include_file=True):
    b = boundary.encode()
    out = io.BytesIO()
    def part(name, value):
        out.write(b'--' + b + b'\r\n')
        out.write(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
        out.write(value + b'\r\n')
    def filepart():
        out.write(b'--' + b + b'\r\n')
        out.write(b'Content-Disposition: form-data; name="file"; filename="server.jar"\r\n')
        if file_ct:
            out.write(b'Content-Type: application/java-archive\r\n')
        out.write(b'\r\n')
        out.write(b'PK\x03\x04fakejarcontent' * 20 + b'\r\n')
    if path_first:
        if include_path:
            part('path', b'')
        if include_file:
            filepart()
    else:
        if include_file:
            filepart()
        if include_path:
            part('path', b'')
    out.write(b'--' + b + b'--\r\n')
    return out.getvalue(), 'multipart/form-data; boundary=' + boundary


def main():
    st, b = req('POST', '/api/auth/login', {'username': 'admin', 'password': sys.argv[1]})
    if st != 200:
        print('登录失败', st, b[:200])
        return 1
    tok = json.loads(b)['token']
    print('登录 OK')

    # 找一个可用实例，没有就建一个
    st, b = req('GET', '/api/instances', token=tok)
    insts = json.loads(b).get('instances', [])
    mine = [i for i in insts if i['name'] == 'up-probe']
    if mine:
        iid = mine[0]['id']
    else:
        port = 26000
        while True:
            st, b = req('POST', '/api/instances', {
                'name': 'up-probe', 'core_type': 'vanilla', 'mc_version': '', 'memory_mb': 512,
                'port': port, 'download': False, 'accept_eula': True}, token=tok)
            if st == 200:
                iid = json.loads(b)['id']
                break
            port += 1
            if port > 26100:
                print('无法创建实例', st, b[:200]); return 1
    print('实例 id =', iid)

    cases = [
        ('1 标准：path 在前 + file 带 CT', dict(file_ct=True, path_first=True, include_path=True)),
        ('2 file 不带 Content-Type', dict(file_ct=False, path_first=True, include_path=True)),
        ('3 path 在 file 之后', dict(file_ct=True, path_first=False, include_path=True)),
        ('4 只有 file，没有 path', dict(file_ct=True, path_first=True, include_path=False)),
    ]
    for label, kw in cases:
        data, ct = build('----probe' + os.urandom(4).hex(), **kw)
        st, b = req('POST', '/api/instances/%d/files/upload' % iid, data, token=tok, ctype=ct)
        print('  %-34s -> HTTP %s  %s' % (label, st, b[:150]))

    # 清理
    req('DELETE', '/api/instances/%d?purge=true' % iid, token=tok)
    print('已清理实例', iid)
    return 0


if __name__ == '__main__':
    sys.exit(main())
