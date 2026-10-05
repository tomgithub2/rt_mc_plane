# -*- coding: utf-8 -*-
"""下载 vanilla 服务端 jar 到自检期望的位置（`data/buildwork/server-1.21.4.jar`）。

为什么需要它：`tools/build_selftest.py` 的引擎 B 验收要**先把世界生成出来**
（离线写 Anvil 只对已存在的区块有效），所以必须先真启动一次服务端。
缺 jar 时自检会在前置步骤直接崩（`shutil.copyfile` FileNotFoundError）。

用法：PYTHONUTF8=1 python tools/fetch_server_jar.py [版本]
"""
import hashlib
import io
import json
import os
import sys
import time
import urllib.request

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_DIR = os.path.join(BACKEND, 'data', 'buildwork')

SOURCES = [
    ('official', 'https://launchermeta.mojang.com/mc/game/version_manifest_v2.json'),
    ('bmclapi', 'https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json'),
]


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'mc-panel-selftest/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else '1.21.4'
    os.makedirs(DEST_DIR, exist_ok=True)
    dest = os.path.join(DEST_DIR, f'server-{want}.jar')
    if os.path.isfile(dest) and os.path.getsize(dest) > 10 * 1024 * 1024:
        print(f'已存在，跳过下载: {dest}  ({os.path.getsize(dest) / 1048576:.1f} MB)')
        return 0

    manifest = None
    for name, url in SOURCES:
        try:
            manifest = get_json(url)
            print(f'[manifest] {name} 可用（{len(manifest.get("versions", []))} 个版本）')
            break
        except Exception as e:                                # noqa: BLE001
            print(f'[manifest] {name} 失败: {e}')
    if not manifest:
        print('两个元数据源都不可达，放弃', file=sys.stderr)
        return 2

    entry = None
    for v in manifest.get('versions', []):
        if v.get('id') == want:
            entry = v
            break
    if not entry:
        print(f'版本清单里没有 {want}', file=sys.stderr)
        return 3
    print(f'[version] {want}  url={entry["url"]}')

    detail = None
    for name, base in (('official', ''), ('bmclapi', 'https://bmclapi2.bangbang93.com')):
        u = entry['url'] if not base else base + entry['url'].split('launchermeta.mojang.com')[-1]
        try:
            detail = get_json(u)
            print(f'[detail] 取到（{name}）')
            break
        except Exception as e:                                # noqa: BLE001
            print(f'[detail] {name} 失败: {e}')
    if not detail:
        return 4

    dl = (detail.get('downloads') or {}).get('server')
    if not dl or not dl.get('url'):
        print('该版本没有 server 下载项', file=sys.stderr)
        return 5
    url, size, sha1 = dl['url'], dl.get('size', 0), dl.get('sha1', '')
    print(f'[download] {url}\n           期望大小 {size / 1048576:.1f} MB  sha1={sha1[:16]}…')

    tmp = dest + '.part'
    h = hashlib.sha1()
    got = 0
    t0 = time.time()
    req = urllib.request.Request(url, headers={'User-Agent': 'mc-panel-selftest/1.0'})
    with urllib.request.urlopen(req, timeout=120) as r, io.open(tmp, 'wb') as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if size:
                pct = got * 100 // size
                sys.stdout.write(f'\r            {pct:3d}%  {got / 1048576:6.1f} MB  '
                                 f'{got / max(0.001, time.time() - t0) / 1048576:.1f} MB/s')
                sys.stdout.flush()
    print()
    actual = h.hexdigest()
    if sha1 and actual != sha1:
        print(f'sha1 不匹配！期望 {sha1} 实际 {actual}', file=sys.stderr)
        os.remove(tmp)
        return 6
    os.replace(tmp, dest)
    print(f'[ok] {dest}  ({os.path.getsize(dest) / 1048576:.1f} MB, sha1 校验通过)')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
