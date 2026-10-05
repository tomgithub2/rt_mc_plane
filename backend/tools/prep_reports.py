"""开发辅助：下载 1.21.4 服务端 jar 并生成 reports（方块状态注册表）。

不属于交付物，仅供本地研究/自检使用。
用法: PYTHONUTF8=1 python tools/prep_reports.py [mc_version]
"""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
WORK = os.path.join(BACKEND, 'data', 'buildwork')
UA = {'User-Agent': 'mc-server-panel/0.1 (+local)'}


def main():
    mc = sys.argv[1] if len(sys.argv) > 1 else '1.21.4'
    os.makedirs(WORK, exist_ok=True)
    jar = os.path.join(WORK, f'server-{mc}.jar')
    if not os.path.isfile(jar):
        req = urllib.request.Request(
            'https://launchermeta.mojang.com/mc/game/version_manifest_v2.json', headers=UA)
        man = json.load(urllib.request.urlopen(req, timeout=30))
        url = [v for v in man['versions'] if v['id'] == mc][0]['url']
        meta = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
        dl = meta['downloads']['server']['url']
        print('downloading', dl, flush=True)
        with urllib.request.urlopen(urllib.request.Request(dl, headers=UA), timeout=300) as r, \
                open(jar + '.part', 'wb') as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        os.replace(jar + '.part', jar)
    print('jar:', jar, os.path.getsize(jar), flush=True)
    gen = os.path.join(WORK, 'gen')
    os.makedirs(gen, exist_ok=True)
    cmd = ['java', '-DbundlerMainClass=net.minecraft.data.Main', '-jar', jar, '--reports']
    print('running', cmd, 'cwd', gen, flush=True)
    p = subprocess.run(cmd, cwd=gen, capture_output=True)
    print('exit', p.returncode, flush=True)
    print(p.stdout.decode('utf-8', 'replace')[-4000:], flush=True)
    print(p.stderr.decode('utf-8', 'replace')[-4000:], flush=True)
    rep = os.path.join(gen, 'generated', 'reports')
    if os.path.isdir(rep):
        print('REPORTS:', os.listdir(rep), flush=True)


if __name__ == '__main__':
    main()
