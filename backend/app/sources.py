"""服务端核心源适配器：Vanilla / Paper / Purpur / Fabric / Quilt / Forge / NeoForge。

约定
  · list_versions(source) -> {'ok', 'versions', 'latest', 'count', 'error', 'via', 'mirror_used'}
  · list_builds(source, mc) -> {'ok', 'builds', 'error'}
  · resolve(source, mc, build) -> {'ok','url','urls','filename','sha1','sha256','md5',
                                   'note','kind','via','mirror_used','verified'}
  · kind: 'server'   → 下载后可直接 -jar 运行
          'installer'→ 下载后需要执行安装器生成启动脚本（Forge / NeoForge）

镜像与降级
  · 每个源的"版本列表 / 构建列表 / 下载直链"三处都先打官方源，失败自动降级 BMCLAPI
    （https://bmclapi2.bangbang93.com），成功时在返回值里用 via='bmclapi' + mirror_used=True
    明确回报"用的是哪个源"，绝不静默换源。
  · BMCLAPI 实测覆盖：Mojang（清单 / version json / server jar / piston 对象）、
    Fabric、Quilt、Forge（/forge/minecraft/<mc>、/forge/download/<build>、/maven/…）、
    NeoForge（/neoforge/list/<mc>、/maven/…）。**Paper / Purpur 无 BMCLAPI 镜像**
    （/paper/** 实测 404），仍会尝试一次并在结果里如实标注。
  · resolve() 返回的 urls 是"下载候选直链列表"，download 引擎按序尝试，任一成功即落盘校验。
  · 任何异常都返回 ok=False + 可读原因，绝不抛到上层。
"""
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request

UA = 'guanwang/mc/0.1 (+local)'
TIMEOUT = 15
PROBE_TIMEOUT = 10

SOURCES = ['vanilla', 'paper', 'purpur', 'fabric', 'quilt', 'forge', 'neoforge']
SOURCE_LABELS = {
    'vanilla': '原版 Vanilla（Mojang）',
    'paper': 'Paper（高性能，插件服）',
    'purpur': 'Purpur（Paper 分支，可调项多）',
    'fabric': 'Fabric（轻量模组）',
    'quilt': 'Quilt（Fabric 分支）',
    'forge': 'Forge（模组，需安装器）',
    'neoforge': 'NeoForge（模组，需安装器）',
}

# ---------------------------------------------------------------- 镜像
BMCLAPI = 'https://bmclapi2.bangbang93.com'
MIRROR_LABEL = {'bmclapi': 'BMCLAPI（国内镜像）', 'official': '官方源'}
# Mojang 各下载域名 → BMCLAPI 同路径
_MOJANG_MIRRORS = ('https://launchermeta.mojang.com/', 'https://piston-meta.mojang.com/',
                   'https://launcher.mojang.com/', 'https://piston-data.mojang.com/')
# maven 仓库 → BMCLAPI /maven/
_MAVEN_MIRRORS = ('https://maven.minecraftforge.net/', 'https://maven.neoforged.net/releases/',
                  'https://maven.neoforged.net/')


class SourceError(Exception):
    pass


def http_get(url: str, timeout: int = TIMEOUT, headers: dict = None) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SourceError(f'HTTP {e.code} {e.reason}')
    except urllib.error.URLError as e:
        raise SourceError(f'网络不可达：{getattr(e, "reason", e)}')
    except socket.timeout:
        raise SourceError('请求超时')
    except Exception as e:
        raise SourceError(f'{type(e).__name__}: {e}')


def http_json(url: str, timeout: int = TIMEOUT, headers: dict = None):
    raw = http_get(url, timeout, headers)
    try:
        return json.loads(raw.decode('utf-8', 'replace'))
    except Exception as e:
        raise SourceError(f'返回内容不是合法 JSON：{e}')


def mirror_of(url: str) -> str:
    """把官方直链换算成 BMCLAPI 镜像直链；无对应镜像返回空串。"""
    if not url:
        return ''
    for host in _MOJANG_MIRRORS:
        if url.startswith(host):
            return BMCLAPI + '/' + url[len(host):]
    for host in _MAVEN_MIRRORS:
        if url.startswith(host):
            return BMCLAPI + '/maven/' + url[len(host):]
    return ''


def http_probe(url: str, timeout: int = PROBE_TIMEOUT) -> dict:
    """用 Range 请求探测直链是否真的可下载（跟随重定向）。

    返回 {ok, status, total, final, error}。NeoForge 的 maven 不支持 HEAD，
    因此统一用 'Range: bytes=0-0'，200/206 都算可达。
    """
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Range': 'bytes=0-0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = getattr(r, 'status', 200) or 200
            cr = r.headers.get('Content-Range') or ''
            total = 0
            m = re.search(r'/(\d+)\s*$', cr)
            if m:
                total = int(m.group(1))
            else:
                try:
                    total = int(r.headers.get('Content-Length') or 0)
                except Exception:
                    total = 0
            return {'ok': status in (200, 206), 'status': status, 'total': total,
                    'final': r.geturl(), 'error': ''}
    except urllib.error.HTTPError as e:
        return {'ok': False, 'status': e.code, 'total': 0, 'final': url,
                'error': f'HTTP {e.code} {e.reason}'}
    except urllib.error.URLError as e:
        return {'ok': False, 'status': 0, 'total': 0, 'final': url,
                'error': f'网络不可达：{getattr(e, "reason", e)}'}
    except Exception as e:
        return {'ok': False, 'status': 0, 'total': 0, 'final': url,
                'error': f'{type(e).__name__}: {e}'}


def _fail(msg: str, **kw) -> dict:
    return {'ok': False, 'error': msg, 'versions': [], 'builds': [], 'via': '', 'tried': [], **kw}


def _cands(pairs) -> list:
    """(url, tag) 列表 → 去重去空的候选列表。"""
    out, seen = [], set()
    for url, tag in pairs:
        if not url or url in seen:
            continue
        seen.add(url)
        out.append((url, tag))
    return out


def _fetch_any(cands, timeout: int = TIMEOUT, headers: dict = None) -> dict:
    """按序尝试候选 URL，返回 {ok, raw, url, via, tried, error}。"""
    tried = []
    for url, tag in _cands(cands):
        try:
            raw = http_get(url, timeout, headers)
            return {'ok': True, 'raw': raw, 'url': url, 'via': tag, 'tried': tried, 'error': ''}
        except SourceError as e:
            tried.append(f'{MIRROR_LABEL.get(tag, tag)} {url} → {e}')
    return {'ok': False, 'raw': b'', 'url': '', 'via': '', 'tried': tried,
            'error': tried[-1] if tried else '没有可用地址'}


def _fetch_json_any(cands, timeout: int = TIMEOUT, headers: dict = None) -> dict:
    r = _fetch_any(cands, timeout, headers)
    if not r.get('ok'):
        return r
    try:
        r['data'] = json.loads(r['raw'].decode('utf-8', 'replace'))
    except Exception as e:
        r['ok'] = False
        r['error'] = f'{MIRROR_LABEL.get(r["via"], r["via"])} 返回内容不是合法 JSON：{e}'
        r['tried'] = list(r.get('tried') or []) + [r['error']]
    return r


def _ok(out: dict, via: str, tried=None) -> dict:
    out['via'] = via
    out['mirror_used'] = via == 'bmclapi'
    out['source_used'] = MIRROR_LABEL.get(via, via)
    if tried:
        out['tried'] = tried
    return out


def _verkey(v: str) -> list:
    return [int(x) if str(x).isdigit() else 0 for x in re.split(r'[.\-+]', str(v))]


def _newest_installer(official_url: str, mirror_url: str) -> tuple:
    """取**两源合并后**最新的 installer 版本，返回 (版本, tried)。

    为什么合并而不是"先成功先返回"：BMCLAPI 的 quilt-meta 严重陈旧
    （实测官方 34 个版本到 0.15.1，镜像只有 18 个、停在 0.9.1），
    而旧版本的 jar 在 maven 上可能已经下不动 —— 一旦镜像先应答，
    就会选中一个**注定下载失败**的版本（这正是 quilt 装不上的原因）。
    拿不到任何数据时返回 ('', tried)，由调用方给默认值。
    """
    tried = []
    versions = []
    for url, via in ((official_url, 'official'), (mirror_url, 'bmclapi')):
        if not url:
            continue
        try:
            raw = http_json(url, timeout=25)
        except Exception as e:                                # noqa: BLE001
            tried.append({'url': url, 'via': via, 'error': f'{type(e).__name__}: {e}'})
            continue
        tried.append({'url': url, 'via': via, 'ok': True})
        for e in (raw or []):
            v = str(((e or {}).get('version') if isinstance(e, dict) else e) or '')
            if v and v not in versions:
                versions.append(v)
    if not versions:
        return '', tried
    return max(versions, key=_verkey), tried


def _xml_versions(xml: str) -> list:
    return re.findall(r'<version>([^<]+)</version>', xml)


def _maven_sha1(url: str) -> str:
    """maven 仓库的 <artifact>.sha1 旁文件（Forge / NeoForge 都提供）→ 用于下载后校验。"""
    if not url:
        return ''
    for cand in (url + '.sha1', (mirror_of(url) + '.sha1') if mirror_of(url) else ''):
        if not cand:
            continue
        try:
            raw = http_get(cand, timeout=12).decode('utf-8', 'replace').strip()
        except SourceError:
            continue
        m = re.search(r'\b([0-9a-fA-F]{40})\b', raw)
        if m:
            return m.group(1).lower()
    return ''


# 元数据缓存（Quilt 官方 meta 单次拉取可达 1~3 分钟，必须缓存，否则会拖垮面板）
_meta_cache = {}
_meta_lock = threading.RLock()


def _cached_json(key, fetch, ttl: int = 900) -> dict:
    with _meta_lock:
        hit = _meta_cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            out = dict(hit[1])
            out['cached'] = True
            return out
    val = fetch()
    if val.get('ok'):
        with _meta_lock:
            _meta_cache[key] = (time.time(), dict(val))
    return val


def clear_meta_cache():
    with _meta_lock:
        _meta_cache.clear()


# ---------------------------------------------------------------- Vanilla
def vanilla_versions():
    r = _fetch_json_any(_cands([
        ('https://launchermeta.mojang.com/mc/game/version_manifest_v2.json', 'official'),
        (BMCLAPI + '/mc/game/version_manifest_v2.json', 'bmclapi')]), timeout=25)
    if not r.get('ok'):
        return _fail('Vanilla 版本清单获取失败：' + r['error'], source='vanilla',
                     tried=r.get('tried'), hint='Mojang 清单与 BMCLAPI 镜像都不可达时可改用本地上传 jar')
    d = r['data']
    out = []
    for v in d.get('versions', []):
        out.append({'id': v['id'], 'type': v.get('type', 'release'),
                    'released': (v.get('releaseTime') or '')[:10]})
    rel = [v for v in out if v['type'] == 'release']
    snap = [v for v in out if v['type'] != 'release']
    return _ok({'ok': True, 'versions': rel + snap, 'latest': d.get('latest', {}),
                'source': 'vanilla', 'count': len(out)}, r['via'], r.get('tried'))


def vanilla_resolve(mc: str, build: str = '', verify: bool = True):
    man = _fetch_json_any(_cands([
        ('https://launchermeta.mojang.com/mc/game/version_manifest_v2.json', 'official'),
        (BMCLAPI + '/mc/game/version_manifest_v2.json', 'bmclapi')]), timeout=25)
    if not man.get('ok'):
        return _fail(f'Vanilla {mc} 版本清单获取失败：{man["error"]}', source='vanilla',
                     tried=man.get('tried'))
    target = None
    for v in man['data'].get('versions', []):
        if v['id'] == mc:
            target = v
            break
    if not target:
        return _fail(f'未找到版本 {mc}', source='vanilla', tried=man.get('tried'))
    meta = _fetch_json_any(_cands([
        (target['url'], 'official'),
        (BMCLAPI + f'/version/{mc}/json', 'bmclapi'),
        (mirror_of(target['url']), 'bmclapi')]), timeout=25)
    if not meta.get('ok'):
        return _fail(f'Vanilla {mc} 元数据获取失败：{meta["error"]}', source='vanilla',
                     tried=meta.get('tried'))
    dl = (meta['data'].get('downloads') or {}).get('server')
    if not dl:
        return _fail(f'版本 {mc} 未提供服务端下载（可能是旧版或快照）', source='vanilla',
                     tried=meta.get('tried'))
    url = dl['url']
    urls = [(url, 'official'), (BMCLAPI + f'/version/{mc}/server', 'bmclapi'),
            (mirror_of(url), 'bmclapi')]
    return _ok({'ok': True, 'url': url, 'urls': [{'url': u, 'via': t} for u, t in _cands(urls)],
                'filename': f'server-{mc}.jar', 'sha1': dl.get('sha1', ''),
                'sha256': dl.get('sha256', ''), 'size': dl.get('size', 0),
                'kind': 'server', 'source': 'vanilla',
                'note': 'Mojang 官方服务端（镜像候选用 BMCLAPI）'},
               meta['via'], man.get('tried'))


# ---------------------------------------------------------------- Paper (fill v3)
def _paper_versions_v3(data) -> list:
    """fill.papermc.io/v3 的 versions 是 {major: [ver, ...]}。"""
    out = []
    groups = (data or {}).get('versions') or {}
    if isinstance(groups, dict):
        for _major, minor_list in groups.items():
            for v in (minor_list or []):
                out.append(v)
    elif isinstance(groups, list):
        out = [str(v) for v in groups]
    return out


def _paper_versions_v2(data) -> list:
    """老 papermc v2 / BMCLAPI 的 versions 是 [ver, ...]。"""
    vs = (data or {}).get('versions')
    return [str(v) for v in vs] if isinstance(vs, list) else []


def paper_versions():
    r = _fetch_json_any(_cands([
        ('https://fill.papermc.io/v3/projects/paper', 'official'),
        (BMCLAPI + '/paper/versions', 'bmclapi')]), timeout=25)
    if not r.get('ok'):
        return _fail('Paper 版本列表获取失败：' + r['error'], source='paper', tried=r.get('tried'),
                     hint='api.papermc.io v2 已 sunset（410），本面板使用 fill.papermc.io v3；'
                          'BMCLAPI 已无 /paper 镜像')
    raw = _paper_versions_v3(r['data']) or _paper_versions_v2(r['data'])
    out = []
    for v in raw:
        out.append({'id': v, 'type': 'release' if '-' not in v else 'rc', 'released': ''})
    rel = [v for v in out if v['type'] == 'release']
    other = [v for v in out if v['type'] != 'release']
    return _ok({'ok': True, 'versions': rel + other,
                'latest': {'release': rel[0]['id'] if rel else ''},
                'source': 'paper', 'count': len(out)}, r['via'], r.get('tried'))


def _paper_builds_raw(mc: str) -> dict:
    """返回 {ok, builds:[{id,channel,time,url,sha256,sha1,name,size}], via, tried, error}"""
    r = _fetch_json_any(_cands([
        (f'https://fill.papermc.io/v3/projects/paper/versions/{mc}/builds', 'official'),
        (BMCLAPI + f'/paper/versions/{mc}/builds', 'bmclapi')]), timeout=25)
    if not r.get('ok'):
        return {'ok': False, 'builds': [], 'via': '', 'tried': r.get('tried'),
                'error': r['error']}
    d = r['data']
    items = d if isinstance(d, list) else (d.get('builds') or [])
    out = []
    for b in items:
        if not isinstance(b, dict):
            continue
        # v3: {'id':110,'channel':'STABLE','time':..,'downloads':{'server:default':{...}}}
        dl = (b.get('downloads') or {}).get('server:default') or {}
        if not dl:
            app = (b.get('downloads') or {}).get('application') or {}
            dl = {'name': app.get('name'), 'url': (app.get('url') or ''),
                  'checksums': {'sha256': app.get('sha256', ''), 'sha1': app.get('sha1', '')},
                  'size': app.get('size', 0)}
        ch = dl.get('checksums') or {}
        bid = b.get('id', b.get('build'))
        out.append({'id': bid, 'channel': b.get('channel', ''), 'time': b.get('time', ''),
                    'url': dl.get('url') or '', 'name': dl.get('name') or f'paper-{mc}-{bid}.jar',
                    'sha256': ch.get('sha256', ''), 'sha1': ch.get('sha1', ''),
                    'size': dl.get('size', 0)})
    return {'ok': True, 'builds': out, 'via': r['via'], 'tried': r.get('tried'), 'error': ''}


def paper_resolve(mc: str, build: str = '', verify: bool = True):
    r = _paper_builds_raw(mc)
    if not r.get('ok'):
        return _fail(f'Paper {mc} 下载信息获取失败：{r["error"]}', source='paper',
                     tried=r.get('tried'))
    builds = r['builds']
    if not builds:
        return _fail(f'Paper {mc} 没有可用构建', source='paper', tried=r.get('tried'))
    stable = [b for b in builds if str(b.get('channel', '')).upper() == 'STABLE']
    chosen = stable[0] if stable else builds[0]
    if build:
        for b in builds:
            if str(b.get('id')) == str(build):
                chosen = b
                break
    if not chosen.get('url'):
        return _fail(f'Paper {mc} build {chosen.get("id")} 无服务端下载', source='paper',
                     tried=r.get('tried'))
    urls = [(chosen['url'], 'official'),
            (BMCLAPI + f'/paper/versions/{mc}/builds/{chosen["id"]}/download', 'bmclapi'),
            (mirror_of(chosen['url']), 'bmclapi')]
    return _ok({'ok': True, 'url': chosen['url'],
                'urls': [{'url': u, 'via': t} for u, t in _cands(urls)],
                'filename': chosen['name'], 'sha256': chosen['sha256'], 'sha1': chosen['sha1'],
                'size': chosen['size'], 'kind': 'server', 'source': 'paper',
                'build': chosen['id'], 'channel': chosen['channel'],
                'note': f'Paper build {chosen["id"]}（{chosen["channel"] or "?"}）'},
               r['via'], r.get('tried'))


def paper_builds(mc: str):
    r = _paper_builds_raw(mc)
    if not r.get('ok'):
        return _fail(f'Paper {mc} 构建列表获取失败：{r["error"]}', source='paper',
                     tried=r.get('tried'))
    return _ok({'ok': True, 'builds': [{'id': b['id'], 'channel': b['channel'],
                                        'time': b['time']} for b in r['builds'][:60]]},
               r['via'], r.get('tried'))


# ---------------------------------------------------------------- Purpur
def purpur_versions():
    r = _fetch_json_any(_cands([
        ('https://api.purpurmc.org/v2/purpur', 'official')]), timeout=25)
    if not r.get('ok'):
        return _fail('Purpur 版本列表获取失败：' + r['error'], source='purpur',
                     tried=r.get('tried'), hint='Purpur 官方 API 不可达；该源无 BMCLAPI 镜像')
    vs = r['data'].get('versions') or []
    out = [{'id': v, 'type': 'release' if re.match(r'^\d+\.\d+(\.\d+)?$', v) else 'other',
            'released': ''} for v in vs]
    rel = [v for v in out if v['type'] == 'release']
    other = [v for v in out if v['type'] != 'release']
    return _ok({'ok': True, 'versions': rel + other, 'latest': {'release': rel[0] if rel else ''},
                'source': 'purpur', 'count': len(out)}, r['via'], r.get('tried'))


def purpur_resolve(mc: str, build: str = '', verify: bool = True):
    r = _fetch_json_any(_cands([
        (f'https://api.purpurmc.org/v2/purpur/{mc}', 'official')]), timeout=25)
    if not r.get('ok'):
        return _fail(f'Purpur {mc} 下载信息获取失败：{r["error"]}', source='purpur',
                     tried=r.get('tried'))
    d = r['data']
    builds = d.get('builds') or {}
    allb = builds.get('all') or []
    if build and build not in ('latest',):
        if allb and str(build) not in [str(x) for x in allb]:
            return _fail(f'Purpur {mc} 不存在构建 {build}', source='purpur')
        chosen = str(build)
    else:
        chosen = str(builds.get('latest') or (allb[-1] if allb else ''))
    if not chosen or chosen == 'None':
        return _fail(f'Purpur {mc} 没有可用构建', source='purpur')
    # 单个构建接口带 md5（官方提供 → 必须校验）
    md5 = ''
    bd = _fetch_json_any(_cands([
        (f'https://api.purpurmc.org/v2/purpur/{mc}/{chosen}', 'official')]), timeout=20)
    if bd.get('ok') and isinstance(bd.get('data'), dict):
        md5 = (bd['data'].get('md5') or '').lower()
    url = f'https://api.purpurmc.org/v2/purpur/{mc}/{chosen}/download'
    note = f'Purpur {mc} build {chosen}'
    note += '（已获取 md5，下载后校验）' if md5 else '（官方未提供哈希，跳过校验）'
    return _ok({'ok': True, 'url': url, 'urls': [{'url': url, 'via': 'official'}],
                'filename': f'purpur-{mc}-{chosen}.jar', 'sha1': '', 'sha256': '', 'md5': md5,
                'size': 0, 'kind': 'server', 'source': 'purpur', 'build': chosen,
                'note': note}, r['via'], r.get('tried'))


# ---------------------------------------------------------------- Fabric / Quilt
def _meta_versions(host: str, mirror: str, source: str):
    r = _fetch_json_any(_cands([
        (host, 'official'), (mirror, 'bmclapi')]), timeout=25)
    if not r.get('ok'):
        return None, _fail(f'{source} 版本列表获取失败：{r["error"]}', source=source,
                           tried=r.get('tried'))
    out = [{'id': v['version'], 'type': 'release' if v.get('stable') else 'snapshot',
            'released': ''} for v in r['data']]
    rel = [v for v in out if v['type'] == 'release']
    other = [v for v in out if v['type'] != 'release']
    return _ok({'ok': True, 'versions': rel + other,
                'latest': {'release': rel[0]['id'] if rel else ''},
                'source': source, 'count': len(out)}, r['via'], r.get('tried')), None


def fabric_versions():
    ok, bad = _meta_versions('https://meta.fabricmc.net/v2/versions/game',
                             BMCLAPI + '/fabric-meta/v2/versions/game', 'fabric')
    return ok or bad


def _fabric_like_resolve(source: str, meta_base: str, mirror_base: str, mc: str, build: str = '',
                         verify: bool = True):
    r = _fetch_json_any(_cands([
        (f'{meta_base}/versions/loader/{mc}', 'official'),
        (f'{mirror_base}/versions/loader/{mc}', 'bmclapi')]), timeout=25)
    if not r.get('ok'):
        return _fail(f'{source} {mc} 加载器列表获取失败：{r["error"]}', source=source,
                     tried=r.get('tried'))
    loaders = r['data'] or []
    if not loaders:
        return _fail(f'{source} 不支持 Minecraft {mc}', source=source, tried=r.get('tried'))
    if build and str(build) != 'latest':
        picked = None
        for l in loaders:
            if str((l.get('loader') or {}).get('version')) == str(build):
                picked = l
                break
        if picked is None:
            return _fail(f'{source} {mc} 不存在加载器版本 {build}', source=source)
        loader = str(picked['loader']['version'])
    else:
        stable = [l for l in loaders if (l.get('loader') or {}).get('stable')]
        loader = str(((stable or loaders)[0].get('loader') or {}).get('version'))
    # installer 版本：**两个源都问、合并后取真正最新的**。
    # 为什么不能"先成功先返回"：BMCLAPI 的 quilt-meta 严重陈旧（实测只到 0.9.1，
    # 官方已是 0.15.1，落后 6 个大版本），而 0.9.1 的 jar 在 maven.quiltmc.org 上
    # 已经下不动（超时）→ 一旦镜像先应答就选中一个**注定下载失败**的版本。
    inst, inst_tried = _newest_installer(f'{meta_base}/versions/installer',
                                        f'{mirror_base}/versions/installer')
    inst = inst or '1.0.1'
    url = f'{meta_base}/versions/loader/{mc}/{loader}/{inst}/server/jar'
    urls = [(url, 'official'), (f'{mirror_base}/versions/loader/{mc}/{loader}/{inst}/server/jar',
                                'bmclapi')]
    via = r['via']
    return _ok({'ok': True, 'url': url, 'urls': [{'url': u, 'via': t} for u, t in _cands(urls)],
                'filename': f'{source}-server-{mc}-{loader}.jar', 'sha1': '', 'sha256': '',
                'size': 0, 'kind': 'server', 'source': source, 'loader': loader,
                'installer': inst,
                'note': f'{source.title()} loader {loader}（该 jar 为启动器，首次启动会自行拉取依赖）'},
               via, r.get('tried') + inst_tried)


def fabric_resolve(mc: str, build: str = '', verify: bool = True):
    return _fabric_like_resolve('fabric', 'https://meta.fabricmc.net/v2',
                                BMCLAPI + '/fabric-meta/v2', mc, build, verify)


def quilt_versions():
    def fetch():
        return _fetch_json_any(_cands([
            ('https://meta.quiltmc.org/v3/versions/game', 'official'),
            (BMCLAPI + '/quilt-meta/v3/versions/game', 'bmclapi')]), timeout=45)
    r = _cached_json('quilt_game', fetch)
    if not r.get('ok'):
        return _fail('Quilt 版本列表获取失败：' + r['error'], source='quilt',
                     tried=r.get('tried'), hint='Quilt 官方 meta 本机经常握手超时，可改用 Fabric')
    out = [{'id': v['version'], 'type': 'release' if v.get('stable') else 'snapshot',
            'released': ''} for v in r['data']]
    rel = [v for v in out if v['type'] == 'release']
    other = [v for v in out if v['type'] != 'release']
    return _ok({'ok': True, 'versions': rel + other,
                'latest': {'release': rel[0]['id'] if rel else ''},
                'source': 'quilt', 'count': len(out)}, r['via'], r.get('tried'))


_QUILT_META = 'https://meta.quiltmc.org/v3'
_QUILT_META_MIRROR = BMCLAPI + '/quilt-meta/v3'


def _quilt_loaders(mc: str) -> dict:
    """Quilt 的**版本化** loader 接口。实测官方稳定要 **89 秒**，所以：
      · 超时压到 12 秒 —— 它几乎必然超时，早失败早走全量清单退路，
        否则"创建实例"这个请求要干等一分半；
      · 先问 BMCLAPI（秒回，但版本化路径是 404），再问官方。
    真正可用的是 `_quilt_loaders_from_full`，这里只是"能精确匹配就精确匹配"的尝试。"""
    def fetch():
        return _fetch_json_any(_cands([
            (f'{_QUILT_META_MIRROR}/versions/loader/{mc}', 'bmclapi'),
            (f'{_QUILT_META}/versions/loader/{mc}', 'official')]), timeout=12)
    return _cached_json(('quilt_loaders', mc), fetch, ttl=300)


def _quilt_installers() -> dict:
    """Quilt installer 清单：**以 maven 自己的元数据为准**。

    为什么不问 meta.quiltmc.org：那个站在本机实测极慢（版本化接口 89 秒、
    installer 清单也常几十秒甚至超时），而**下载源自己的** maven-metadata.xml
    只要 2 秒、34 个版本、最新 0.15.1 —— 元数据与 jar 同源，不可能对不上。
    镜像（BMCLAPI）的 quilt-meta 只到 0.9.1 且落后 6 个大版本，
    而 0.9.1 的 jar 在 maven 上已经下不动，所以只当兜底。
    """
    MAVEN_META = ('https://maven.quiltmc.org/repository/release/'
                  'org/quiltmc/quilt-installer/maven-metadata.xml')
    BASE = ('https://maven.quiltmc.org/repository/release/'
            'org/quiltmc/quilt-installer')

    def entry_of(v, want_sha1=False):
        url = f'{BASE}/{v}/quilt-installer-{v}.jar'
        # maven 仓库有 <artifact>.jar.sha1 边车文件，但每个要 ~8 秒 —— 只为
        # **选中的那个版本**拉一次（34 个版本全拉要 4 分多钟）。
        return {'version': v, 'url': url,
                'maven': 'org.quiltmc:quilt-installer', 'file_size': 0,
                'hashes': {'sha1': _maven_sha1(url) if want_sha1 else ''}}

    def fetch():
        tried = []
        # 1) maven 元数据（首选：快且与 jar 同源）
        try:
            xml = http_get(MAVEN_META, timeout=20).decode('utf-8', 'replace')
            vs = [v for v in re.findall(r'<version>([^<]+)</version>', xml) if v.strip()]
            tried.append({'url': MAVEN_META, 'via': 'maven', 'ok': True, 'count': len(vs)})
            if vs:
                rows = [entry_of(v) for v in sorted(vs, key=_verkey, reverse=True)]
                # 只给最新版本补 sha1（边车文件慢，一个 ~8 秒，34 个全拉会拖垮）
                if rows:
                    newest = rows[0]
                    rows[0] = entry_of(newest['version'], want_sha1=True)
                return _ok({'ok': True, 'data': rows, 'count': len(rows)}, 'maven', tried)
        except Exception as e:                                # noqa: BLE001
            tried.append({'url': MAVEN_META, 'via': 'maven',
                          'error': f'{type(e).__name__}: {e}'})
        # 2) 兜底：两个 quilt-meta（可能陈旧，但至少能给出一个版本）
        merged, seen = [], set()
        for url, via in ((f'{_QUILT_META}/versions/installer', 'official'),
                         (f'{_QUILT_META_MIRROR}/versions/installer', 'bmclapi')):
            try:
                raw = http_json(url, timeout=25)
            except Exception as e:                            # noqa: BLE001
                tried.append({'url': url, 'via': via, 'error': f'{type(e).__name__}: {e}'})
                continue
            tried.append({'url': url, 'via': via, 'ok': True})
            for e in (raw or []):
                if not isinstance(e, dict):
                    continue
                v = str(e.get('version') or '')
                if v and v not in seen:
                    seen.add(v)
                    merged.append(e)
        if not merged:
            return _fail('Quilt installer 清单获取失败', source='quilt', tried=tried)
        merged.sort(key=lambda e: _verkey(e.get('version') or ''), reverse=True)
        return _ok({'ok': True, 'data': merged, 'count': len(merged)}, 'official', tried)
    return _cached_json('quilt_installers', fetch, ttl=1800)


def _quilt_loaders_from_full(mc: str) -> dict:
    """退路：从**全量** loader 清单里取最新 loader。

    Quilt 的版本化接口 `/versions/loader/<mc>` 实测**稳定要 89 秒**
    （超时设 45 秒时必然失败），而**全量清单** `/versions/loader` 在 BMCLAPI 上
    秒回（22KB / 221 条）。全量清单每项只有
    `{separator, build, maven, version}` —— **没有 game 字段**，
    所以无法按游戏版本筛选，只能取版本号最大的 loader。

    因此返回值里带 `unverified_mc=True`，让调用方在 note 里如实说明
    "loader 来自镜像全量清单、未按游戏版本校验"。Quilt loader 对同代游戏版本
    兼容性通常没问题，但这一点必须让用户知道，不能假装是精确匹配。
    """
    def fetch():
        tried = []
        rows = []
        for url, tag in ((f'{_QUILT_META_MIRROR}/versions/loader', 'bmclapi'),
                         (f'{_QUILT_META}/versions/loader', 'official')):
            try:
                raw = http_json(url, timeout=45)
            except Exception as e:                            # noqa: BLE001
                tried.append({'url': url, 'via': tag, 'error': f'{type(e).__name__}: {e}'})
                continue
            tried.append({'url': url, 'via': tag, 'ok': True})
            if isinstance(raw, list) and raw:
                rows = raw
                break
        if not rows:
            return _fail('Quilt loader 全量清单获取失败', source='quilt', tried=tried)
        rows = [r for r in rows if isinstance(r, dict) and r.get('version')]
        if not rows:
            return _fail('Quilt 全量清单为空', source='quilt', tried=tried)
        newest = max(rows, key=lambda r: _verkey(str(r.get('version') or '')))
        # 包装成与版本化接口一致的形状：调用方读 data[].loader.version
        data = [{'loader': {'version': str(newest.get('version'))}, 'game': {'version': mc},
                 'unverified_mc': True}]
        return _ok({'ok': True, 'data': data, 'count': 1, 'unverified_mc': True},
                   'bmclapi' if any(t.get('via') == 'bmclapi' and t.get('ok') for t in tried)
                   else 'official', tried)
    return _cached_json(f'quilt_loaders_full_{mc}', fetch, ttl=1800)


def quilt_resolve(mc: str, build: str = '', verify: bool = True):
    """Quilt：**直接走全量清单取最新 loader**，不再碰那个 89 秒的版本化接口。

    官方 `meta.quiltmc.org/v3/versions/loader/<mc>` 实测稳定要 89 秒（且只给
    871KB 的版本对应关系）；BMCLAPI 版本化路径 404。而**全量清单**
    `/versions/loader` 秒回、里面有最新 loader 版本号。反正 Quilt 的预构建
    server jar 端点现在基本全 404，最终都要落到 quilt-installer，
    所以不值得为精确的 loader 版本对应关系等一分半。
    """
    tried, via = [], 'official'
    lr = _quilt_loaders_from_full(mc)
    loader = ''
    # 全量清单返回的 loader 没有 game 版本对应关系（unverified_mc=True），
    # 但它是"能拿到的最新 loader"，对同代游戏版本通常可用 —— 如实标注即可。
    if lr.get('ok'):
        tried = list(lr.get('tried') or [])
        via = lr.get('via') or 'official'
        vers = []
        for e in (lr.get('data') or []):
            v = str(((e or {}).get('loader') or {}).get('version') or '')
            if v:
                vers.append(v)
        if build and build not in ('latest',) and build in vers:
            loader = build
        elif vers:
            nonbeta = [v for v in vers if not re.search(r'(beta|rc|pre|snapshot)', v, re.I)]
            loader = max(nonbeta or vers, key=_verkey)
    # ⚠️ loader 解析不出来时**必须明确失败**，不能继续拼一个 `--loader-version=` 为空的
    # 安装命令 —— 那样用户拿到的是一个"下得下来但装不上"的 jar，比直接报错更糟，
    # 而且提示文案会自相矛盾（历史上就出现过"探测 0 个候选均 404"配空 loader）。
    if not loader:
        return _fail(f'Quilt 没能解析出 {mc} 可用的 loader 版本：'
                     '官方 meta 响应极慢（实测 >70 秒）且镜像无该版本的 loader 列表。',
                     source='quilt', tried=tried,
                     hint='可以先用 Fabric（同样轻量、中文文档多）；'
                          '或稍后重试 Quilt，或在实例详情里手动上传 quilt-installer 安装。')
    ir = _quilt_installers()
    inst = {'version': '', 'url': '', 'sha1': '', 'sha256': '', 'size': 0}
    if ir.get('ok') and ir.get('data'):
        entries = sorted([e for e in ir['data'] if isinstance(e, dict)],
                         key=lambda e: _verkey(e.get('version') or ''), reverse=True)
        if entries:
            top = entries[0]
            hs = top.get('hashes') or {}
            inst = {'version': str(top.get('version') or ''), 'url': str(top.get('url') or ''),
                    'sha1': hs.get('sha1', ''), 'sha256': hs.get('sha256', ''),
                    'size': int(top.get('file_size') or 0)}
    if ir.get('via') == 'bmclapi' and via == 'official':
        via = 'bmclapi'

    # 预构建 jar 探测**只在 loader 是精确解析出来的时候做**。
    # 走全量清单退路时不做：那个 loader 版本没有游戏版本对应关系，
    # 用它去探测预构建 jar 只会平白多花几十秒（该 endpoint 现在基本全 404），
    # 而实测整条链路光探测就要 ~4 分钟 —— 创建实例的请求会直接卡死。
    ladder = []
    if loader and inst['version'] and not lr.get('unverified_mc'):
        for base, tag in ((_QUILT_META, 'official'), (_QUILT_META_MIRROR, 'bmclapi')):
            ladder.append((f'{base}/versions/loader/{mc}/{loader}/{inst["version"]}/server/jar',
                           tag))
            ladder.append((f'{base}/versions/loader/{mc}/{loader}/server/jar', tag))
    probes = []
    for u, tag in _cands(ladder):
        p = http_probe(u, timeout=20)
        probes.append({'url': u, 'via': tag, 'status': p.get('status'), 'ok': p.get('ok')})
        if p.get('ok'):
            return _ok({'ok': True, 'url': u, 'urls': [{'url': u, 'via': tag}],
                        'filename': f'quilt-server-{mc}-{loader}.jar', 'sha1': '', 'sha256': '',
                        'size': p.get('total') or 0, 'kind': 'server', 'source': 'quilt',
                        'loader': loader, 'installer': inst['version'], 'probes': probes,
                        'note': f'Quilt loader {loader}（该 jar 为启动器，首次启动会自行拉取依赖）'},
                       tag, tried)
    # 预构建 jar 全 404 → 退到 quilt-installer（官方提供 sha1/sha256，下载后校验）
    if inst['url']:
        alt = mirror_of(inst['url'])
        unverified = bool(lr.get('unverified_mc'))
        note = ('Quilt 官方预构建 server jar 不可用'
                + (f'（探测 {len(probes)} 个候选均 404）' if probes
                   else '（loader 取自镜像全量清单，已跳过昂贵的预构建探测）')
                + f'，已改为下载官方 quilt-installer {inst["version"]}：'
                f'在实例目录执行 `java -jar {os.path.basename(inst["url"])} install server {mc} '
                f'--loader-version={loader} --download-server` 即可生成服务端')
        if unverified:
            note += ('。注意：该 loader 版本取自镜像的**全量清单**，'
                     '未按游戏版本逐个校验（Quilt 的版本化接口实测稳定要 89 秒，已跳过）')
        return _ok({'ok': True, 'url': inst['url'],
                    'urls': [{'url': u, 'via': t} for u, t in
                             _cands([(inst['url'], 'official'), (alt, 'bmclapi')])],
                    'filename': os.path.basename(inst['url']), 'sha1': inst['sha1'],
                    'sha256': inst['sha256'], 'size': inst['size'], 'kind': 'installer',
                    'source': 'quilt', 'loader': loader, 'build': inst['version'],
                    'full': inst['version'], 'probes': probes, 'fallback': 'installer',
                    'verified': bool(verify), 'install_cmd':
                        f'java -jar {os.path.basename(inst["url"])} install server {mc} '
                        f'--loader-version={loader or "latest"} --download-server',
                    'note': note}, via, tried)
    return _fail(f'Quilt {mc} 既没有预构建 server jar（{len(probes)} 个候选 404），'
                 f'也拿不到 quilt-installer（{ir.get("error", "官方 meta 不可达")}）'
                 '；建议改用 Fabric 或本地上传 jar',
                 source='quilt', tried=tried, probes=probes)


# ---------------------------------------------------------------- Forge
_FORGE_META = 'https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml'
_FORGE_META_MIRROR = BMCLAPI + '/maven/net/minecraftforge/forge/maven-metadata.xml'
_NEOFORGE_META = 'https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml'
_NEOFORGE_META_MIRROR = BMCLAPI + '/maven/net/neoforged/neoforge/maven-metadata.xml'


def _forge_versions_raw() -> dict:
    r = _fetch_any(_cands([(_FORGE_META, 'official'), (_FORGE_META_MIRROR, 'bmclapi')]), timeout=25)
    if not r.get('ok'):
        return {'ok': False, 'error': r['error'], 'tried': r.get('tried'), 'versions': []}
    xml = r['raw'].decode('utf-8', 'replace')
    mcs = {}
    for v in _xml_versions(xml):
        if '-' not in v:
            continue
        mc, fv = v.split('-', 1)
        if not re.match(r'^\d+\.\d+', mc):
            continue
        mcs.setdefault(mc, []).append(fv)
    out = [{'id': mc, 'type': 'release', 'released': '', 'builds': len(fvs)}
           for mc, fvs in mcs.items()]
    out.sort(key=lambda item: _verkey(item['id']), reverse=True)
    return {'ok': True, 'versions': out, 'via': r['via'], 'tried': r.get('tried'), 'xml': xml}


def forge_versions():
    r = _forge_versions_raw()
    if not r.get('ok'):
        return _fail('Forge 版本列表获取失败：' + r['error'], source='forge', tried=r.get('tried'),
                     hint='Forge 官方 maven 与 BMCLAPI 镜像都不可达时可改用本地上传 jar')
    out = r['versions']
    return _ok({'ok': True, 'versions': out,
                'latest': {'release': out[0]['id'] if out else ''},
                'source': 'forge', 'count': len(out)}, r['via'], r.get('tried'))


def _bmcl_forge_builds(mc: str) -> list:
    """BMCLAPI /forge/minecraft/<mc> → [{full, build, installer_sha1}]；失败返回 []。"""
    r = _fetch_json_any(_cands([(BMCLAPI + f'/forge/minecraft/{mc}', 'bmclapi')]), timeout=25)
    if not r.get('ok') or not isinstance(r.get('data'), list):
        return []
    out = []
    for it in r['data']:
        if not isinstance(it, dict):
            continue
        full = str(it.get('version') or '')
        if not full:
            continue
        sha1 = ''
        for f in (it.get('files') or []):
            if f.get('category') == 'installer':
                sha1 = f.get('hash', '')
                break
        out.append({'full': full, 'id': full.split('-', 1)[-1], 'numeric': it.get('build'),
                    'sha1': sha1})
    return out


def forge_builds(mc: str):
    r = _forge_versions_raw()
    out = []
    if r.get('ok'):
        xml = r.get('xml') or ''
        for v in _xml_versions(xml):
            if v.startswith(mc + '-'):
                out.append({'id': v.split('-', 1)[1], 'full': v})
        out.reverse()
        via, tried = r.get('via', ''), r.get('tried')
    else:
        via, tried = 'bmclapi', r.get('tried')
    if not out:
        bm = _bmcl_forge_builds(mc)
        if bm:
            out = [{'id': b['id'], 'full': b['full'], 'numeric': b.get('numeric'),
                    'sha1': b.get('sha1', '')} for b in reversed(bm)]
            via = 'bmclapi'
    if not out:
        return _fail(f'Forge 未找到 Minecraft {mc} 的构建（{r.get("error", "官方与镜像均无数据")}）',
                     source='forge', tried=tried)
    return _ok({'ok': True, 'builds': out[:80]}, via, tried)


def forge_resolve(mc: str, build: str = '', verify: bool = True, probe_limit: int = 4):
    x = forge_builds(mc)
    if not x.get('ok') or not x['builds']:
        return _fail(f'Forge 未找到 Minecraft {mc} 的构建', source='forge', tried=x.get('tried'))
    builds = x['builds']
    ordered = []
    if build:
        for b in builds:
            if str(b['id']) == str(build):
                ordered.append(b)
                break
        if not ordered:
            return _fail(f'Forge {mc}-{build} 不存在', source='forge')
    else:
        ordered = builds
    numeric_map = {}
    bm = _bmcl_forge_builds(mc)
    for b in bm:
        numeric_map[b['full']] = b
    chosen, checked = None, []
    for b in ordered[:max(1, probe_limit)]:
        full = b['full']
        fn = f'forge-{full}-installer.jar'
        official = f'https://maven.minecraftforge.net/net/minecraftforge/forge/{full}/{fn}'
        cands = [(official, 'official'), (mirror_of(official), 'bmclapi')]
        nb = numeric_map.get(full)
        if nb and nb.get('numeric'):
            cands.append((BMCLAPI + f'/forge/download/{nb["numeric"]}', 'bmclapi'))
        if not verify:
            chosen = (b, cands, '')
            break
        hit = None
        for u, tag in _cands(cands):
            p = http_probe(u)
            checked.append({'url': u, 'via': tag, 'status': p.get('status'), 'ok': p.get('ok')})
            if p.get('ok'):
                hit = (u, tag)
                break
        if hit:
            chosen = (b, cands, hit)
            break
    if not chosen:
        return _fail(f'Forge {mc} 的安装器直链全部探测失败（{len(checked)} 个候选）',
                     source='forge', source_used='official+bmclapi', probes=checked[-6:])
    b, cands, hit = chosen
    full = b['full']
    fn = f'forge-{full}-installer.jar'
    url = cands[0][0]
    via = hit[1] if hit else 'official'
    sha1 = b.get('sha1') or _maven_sha1(url) or (
        (numeric_map.get(full) or {}).get('sha1', ''))
    return _ok({'ok': True, 'url': url, 'urls': [{'url': u, 'via': t} for u, t in _cands(cands)],
                'filename': fn, 'sha1': sha1, 'sha256': '', 'size': 0,
                'kind': 'installer', 'source': 'forge', 'build': full.split('-', 1)[1],
                'full': full, 'verified': bool(hit),
                'probes': checked[-6:],
                'note': 'Forge 需要先运行安装器生成启动脚本（面板会自动执行 --installServer）'
                        + ('（已取到 sha1，下载后校验）' if sha1 else '')},
               via, x.get('tried'))


# ---------------------------------------------------------------- NeoForge
def _neo_mc_from_version(v: str) -> str:
    """NeoForge 版本号 → Minecraft 版本。

    老命名：21.1.72 → 1.21.1；21.0.167 → 1.21；20.4.237 → 1.20.4
    新年份命名：26.3.0.40 → 26.3
    """
    parts = str(v).split('.')
    if len(parts) < 2 or not parts[0].isdigit():
        return ''
    major = int(parts[0])
    if major >= 26:
        return f'{parts[0]}.{parts[1]}'
    mc = '1.' + parts[0]
    if parts[1] != '0':
        mc += '.' + parts[1]
    return mc


def _neo_prefix(mc: str) -> str:
    """NeoForge 版本前缀：1.21.4 → '21.4.'；1.21 → '21.0.'；26.3 → '26.3.'"""
    mc = str(mc or '').strip()
    if mc.startswith('1.'):
        parts = mc[2:].split('.')
        if len(parts) == 1:
            return parts[0] + '.0.'
        return parts[0] + '.' + parts[1] + '.'
    return mc + '.'


def _neoforge_versions_raw() -> dict:
    r = _fetch_any(_cands([(_NEOFORGE_META, 'official'), (_NEOFORGE_META_MIRROR, 'bmclapi')]),
                   timeout=25)
    if not r.get('ok'):
        return {'ok': False, 'error': r['error'], 'tried': r.get('tried'), 'versions': []}
    xml = r['raw'].decode('utf-8', 'replace')
    vers = [v for v in _xml_versions(xml) if '-' not in v]
    mcset = set()
    for v in vers:
        mc = _neo_mc_from_version(v)
        if mc:
            mcset.add(mc)
    out = [{'id': mc, 'type': 'release', 'released': ''}
           for mc in sorted(mcset, key=_verkey, reverse=True)]
    return {'ok': True, 'versions': out, 'via': r['via'], 'tried': r.get('tried'), 'xml': xml}


def neoforge_versions():
    r = _neoforge_versions_raw()
    if not r.get('ok'):
        return _fail('NeoForge 版本列表获取失败：' + r['error'], source='neoforge',
                     tried=r.get('tried'))
    out = r['versions']
    return _ok({'ok': True, 'versions': out, 'latest': {'release': out[0]['id'] if out else ''},
                'source': 'neoforge', 'count': len(out)}, r['via'], r.get('tried'))


def _bmcl_neo_builds(mc: str) -> dict:
    """BMCLAPI /neoforge/list/<mc> → {version: installerPath}；失败返回 {}。"""
    r = _fetch_json_any(_cands([(BMCLAPI + f'/neoforge/list/{mc}', 'bmclapi')]), timeout=25)
    if not r.get('ok') or not isinstance(r.get('data'), list):
        return {}
    out = {}
    for it in r['data']:
        if not isinstance(it, dict):
            continue
        v = str(it.get('version') or '')
        p = str(it.get('installerPath') or '')
        if v and p:
            out[v] = p
    return out


def neoforge_builds(mc: str):
    r = _neoforge_versions_raw()
    vers, tried = [], r.get('tried')
    via = r.get('via') or 'official'
    if r.get('ok'):
        xml = r.get('xml') or ''
        vers = [v for v in _xml_versions(xml) if '-' not in v]
    prefix = _neo_prefix(mc)
    bm = _bmcl_neo_builds(mc)
    out, seen = [], set()
    for v in vers:
        if not v.startswith(prefix) or v in seen:
            continue
        seen.add(v)
        out.append({'id': v, 'full': v, 'installer': 'official',
                    'bmclapi_path': bm.get(v, '')})
    for v, path in bm.items():
        if v in seen or not v.startswith(prefix):
            continue
        seen.add(v)
        out.append({'id': v, 'full': v, 'installer': 'bmclapi', 'bmclapi_path': path})
    out.sort(key=lambda b: _verkey(b['id']), reverse=True)
    if not out:
        return _fail(f'NeoForge 未找到 Minecraft {mc} 的构建', source='neoforge', tried=tried)
    return _ok({'ok': True, 'builds': out[:80]}, via, tried)


def neoforge_resolve(mc: str, build: str = '', verify: bool = True, probe_limit: int = 5):
    x = neoforge_builds(mc)
    if not x.get('ok') or not x['builds']:
        return _fail(f'NeoForge 未找到 Minecraft {mc} 的构建', source='neoforge',
                     tried=x.get('tried'))
    builds = x['builds']
    if build:
        ordered = [b for b in builds if str(b['id']) == str(build)]
        if not ordered:
            return _fail(f'NeoForge {mc}-{build} 不存在', source='neoforge')
    else:
        stable = [b for b in builds if 'beta' not in b['id']]
        ordered = stable or builds
    chosen, checked = None, []
    for b in ordered[:max(1, probe_limit)]:
        full = b['full']
        fn = f'neoforge-{full}-installer.jar'
        official = (f'https://maven.neoforged.net/releases/net/neoforged/neoforge/{full}/{fn}')
        cands = [(official, 'official'), (mirror_of(official), 'bmclapi')]
        if b.get('bmclapi_path'):
            cands.append((BMCLAPI + b['bmclapi_path'], 'bmclapi'))
        if not verify:
            chosen = (b, cands, '')
            break
        hit = None
        for u, tag in _cands(cands):
            p = http_probe(u)
            checked.append({'url': u, 'via': tag, 'status': p.get('status'), 'ok': p.get('ok')})
            if p.get('ok'):
                hit = (u, tag)
                break
        if hit:
            chosen = (b, cands, hit)
            break
    if not chosen:
        # 探测都失败时仍返回最新一个候选（下载引擎会再按序重试），但如实标注 verified=false
        b = ordered[0]
        fn = f'neoforge-{b["full"]}-installer.jar'
        official = f'https://maven.neoforged.net/releases/net/neoforged/neoforge/{b["full"]}/{fn}'
        cands = [(official, 'official'), (mirror_of(official), 'bmclapi')]
        if b.get('bmclapi_path'):
            cands.append((BMCLAPI + b['bmclapi_path'], 'bmclapi'))
        return _ok({'ok': True, 'url': official,
                    'urls': [{'url': u, 'via': t} for u, t in _cands(cands)],
                    'filename': fn, 'sha1': '', 'sha256': '', 'size': 0, 'kind': 'installer',
                    'source': 'neoforge', 'build': b['full'], 'full': b['full'],
                    'verified': False, 'probes': checked[-6:],
                    'warning': f'NeoForge {b["full"]} 安装器直链探测未通过（{len(checked)} 个候选），'
                               '已返回最新候选，下载时仍会逐候选重试',
                    'note': 'NeoForge 需要先运行安装器生成启动脚本（面板会自动执行 --installServer）'},
                   'official', x.get('tried'))
    b, cands, hit = chosen
    fn = f'neoforge-{b["full"]}-installer.jar'
    via = hit[1] if hit else 'official'
    sha1 = _maven_sha1(cands[0][0])
    return _ok({'ok': True, 'url': cands[0][0],
                'urls': [{'url': u, 'via': t} for u, t in _cands(cands)],
                'filename': fn, 'sha1': sha1, 'sha256': '', 'size': 0, 'kind': 'installer',
                'source': 'neoforge', 'build': b['full'], 'full': b['full'],
                'verified': bool(hit), 'probes': checked[-6:],
                'note': (f'NeoForge {b["full"]}（安装器直链已实测可达）' if hit
                         else 'NeoForge 需要先运行安装器生成启动脚本')
                        + ('（已取到 sha1，下载后校验）' if sha1 else '')},
               via, x.get('tried'))


# ---------------------------------------------------------------- 统一入口
_LISTERS = {'vanilla': vanilla_versions, 'paper': paper_versions, 'purpur': purpur_versions,
            'fabric': fabric_versions, 'quilt': quilt_versions, 'forge': forge_versions,
            'neoforge': neoforge_versions}
_RESOLVERS = {'vanilla': vanilla_resolve, 'paper': paper_resolve, 'purpur': purpur_resolve,
              'fabric': fabric_resolve, 'quilt': quilt_resolve, 'forge': forge_resolve,
              'neoforge': neoforge_resolve}
_BUILDERS = {'paper': paper_builds, 'forge': forge_builds, 'neoforge': neoforge_builds}


def list_versions(source: str) -> dict:
    fn = _LISTERS.get(source)
    if not fn:
        return _fail(f'未知下载源：{source}', source=source)
    try:
        out = fn()
        out.setdefault('source', source)
        out.setdefault('label', SOURCE_LABELS.get(source, source))
        return out
    except Exception as e:      # 兜底：适配器自身 bug 也不能打断面板
        return _fail(f'{source} 适配器异常：{type(e).__name__}: {e}', source=source)


def list_builds(source: str, mc: str) -> dict:
    fn = _BUILDERS.get(source)
    if not fn:
        return {'ok': True, 'builds': [], 'via': '', 'note': f'{source} 无构建列表（直接选版本即可）'}
    try:
        return fn(mc)
    except Exception as e:
        return _fail(f'{source} {mc} 构建列表异常：{type(e).__name__}: {e}', source=source)


def resolve(source: str, mc: str, build: str = '', verify: bool = True) -> dict:
    fn = _RESOLVERS.get(source)
    if not fn:
        return _fail(f'未知下载源：{source}', source=source)
    try:
        out = fn(mc, build, verify=verify)
        out.setdefault('source', source)
        return out
    except Exception as e:
        return _fail(f'{source} {mc} 解析异常：{type(e).__name__}: {e}', source=source)


def verify_download(info: dict, timeout: int = PROBE_TIMEOUT) -> dict:
    """对 resolve() 结果逐候选直链实测（Range 200/206）。"""
    urls = info.get('urls') or ([{'url': info.get('url'), 'via': info.get('via') or 'official'}]
                                if info.get('url') else [])
    probes = []
    for item in urls:
        u = item.get('url') if isinstance(item, dict) else item
        tag = item.get('via', '') if isinstance(item, dict) else ''
        if not u:
            continue
        p = http_probe(u, timeout)
        probes.append({'url': u, 'via': tag, 'status': p.get('status'), 'ok': p.get('ok'),
                       'total': p.get('total'), 'final': p.get('final'), 'error': p.get('error')})
    best = next((p for p in probes if p['ok']), None)
    return {'ok': bool(best), 'reachable': bool(best), 'chosen': best, 'probes': probes,
            'status': (best or {}).get('status'), 'via': (best or {}).get('via', '')}


def probe_all(timeout: int = 8) -> list:
    """逐个源实测可达性（设置页用）：列版本 → 拿一个版本 → 解析直链 → 探测直链。"""
    results = []
    for s in SOURCES:
        t0 = time.time()
        item = {'source': s, 'label': SOURCE_LABELS.get(s, s), 'ok': False, 'count': 0,
                'error': '', 'via': '', 'mirror_used': False, 'version': '', 'url_status': 0,
                'download_ok': False, 'download_via': ''}
        try:
            lv = list_versions(s)
            item['ok'] = bool(lv.get('ok'))
            item['count'] = lv.get('count', 0)
            item['error'] = lv.get('error', '')
            item['via'] = lv.get('via', '')
            item['mirror_used'] = bool(lv.get('mirror_used'))
            rel = [v for v in (lv.get('versions') or [])
                   if v.get('type') in ('release', 'snapshot')] or (lv.get('versions') or [])
            pick = ''
            for prefer in ('1.21.4', '1.21.1', '1.21', '1.20.6'):
                if any(v.get('id') == prefer for v in rel):
                    pick = prefer
                    break
            if not pick and rel:
                pick = rel[0].get('id', '')
            item['version'] = pick
            if item['ok'] and pick:
                rv = resolve(s, pick, '', verify=False)
                if rv.get('ok'):
                    v = verify_download(rv, timeout=timeout)
                    item['download_ok'] = bool(v.get('ok'))
                    item['url_status'] = v.get('status') or 0
                    item['download_via'] = v.get('via', '')
                else:
                    item['error'] = item['error'] or rv.get('error', '解析直链失败')
        except Exception as e:
            item['error'] = f'{type(e).__name__}: {e}'
        item['ms'] = int((time.time() - t0) * 1000)
        results.append(item)
    return results
