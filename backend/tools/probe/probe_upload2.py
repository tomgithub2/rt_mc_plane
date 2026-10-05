"""把上传 422 的完整响应体打出来（服务端 detail 可能带字段级原因）。"""
import io
import json
import os
import sys
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:8100'


def req(method, path, body=None, token=None, ctype='application/json'):
    h = {'User-Agent': 'probe2'}
    if token:
        h['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        if ctype == 'application/json':
            data = json.dumps(body).encode('utf-8')
            h['Content-Type'] = 'application/json'
        else:
            data = body
            h['Content-Type'] = ctype
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def mp(fields, fname, content):
    """与 selftest.py 完全一致的构造方式"""
    b = b'----probe2' + os.urandom(6).hex().encode()
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(b'--' + b + b'\r\n')
        out.write(('Content-Disposition: form-data; name="%s"\r\n\r\n' % k).encode())
        out.write(str(v).encode() + b'\r\n')
    out.write(b'--' + b + b'\r\n')
    out.write(('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % fname).encode())
    out.write(b'Content-Type: application/java-archive\r\n\r\n')
    out.write(content + b'\r\n')
    out.write(b'--' + b + b'--\r\n')
    return out.getvalue(), 'multipart/form-data; boundary=' + b.decode()


def main():
    st, b = req('POST', '/api/auth/login', {'username': 'admin', 'password': sys.argv[1]})
    tok = json.loads(b)['token']
    port = 26600
    while True:
        st, b = req('POST', '/api/instances', {
            'name': 'detail-probe', 'core_type': 'vanilla', 'mc_version': '', 'memory_mb': 512,
            'port': port, 'download': False}, token=tok)
        if st == 200:
            iid = json.loads(b)['id']
            break
        port += 1
    print('iid =', iid)

    # A：小体积 ASCII
    d, ct = mp({'path': ''}, 'a.jar', b'PK\x03\x04hello' * 10)
    st, b = req('POST', '/api/instances/%d/files/upload' % iid, d, tok, ct)
    print('A 小体积 ASCII  -> %s %s' % (st, b[:400]))

    # B：大体积二进制（接近真实 jar）
    d, ct = mp({'path': ''}, 'b.jar', os.urandom(200000))
    st, b = req('POST', '/api/instances/%d/files/upload' % iid, d, tok, ct)
    print('B 200KB 随机二进制 -> %s %s' % (st, b[:400]))

    # C：真实 mock jar（含 \r\n 与二进制混合）
    jar = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp', 'mock-server.jar')
    if os.path.isfile(jar):
        with open(jar, 'rb') as f:
            content = f.read()
        d, ct = mp({'path': ''}, 'server.jar', content)
        st, b = req('POST', '/api/instances/%d/files/upload' % iid, d, tok, ct)
        print('C 真实 jar (%d 字节) -> %s %s' % (len(content), st, b[:400]))
    else:
        print('C 跳过：未找到', jar)

    req('DELETE', '/api/instances/%d?purge=true' % iid, token=tok)
    print('已清理', iid)
    return 0


if __name__ == '__main__':
    sys.exit(main())
