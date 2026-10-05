"""插件/模组源：Modrinth（可用）、SpigotMC（尽力）、CurseForge（需 API Key）。

三个源都遵守同一约定：失败返回 {'ok': False, 'error': '...'}，
文案里明确写清是"源不可达"还是"需要 key"，绝不假装成功。
"""
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import get_config
from .sources import UA, http_get, http_json, SourceError

MODRINTH = 'https://api.modrinth.com/v2'
SPIGET = 'https://api.spiget.org/v2'
CURSEFORGE = 'https://api.curseforge.com/v1'


def target_dir(row: dict) -> str:
    """按核心类型决定装到 plugins 还是 mods。"""
    core = str(row.get('core_type') or '').lower()
    return 'plugins' if core in ('paper', 'purpur', 'spigot', 'bukkit') else 'mods'


# ---------------------------------------------------------------- Modrinth
def modrinth_search(query: str, mc_version: str = '', mod_type: str = '', limit: int = 20,
                    offset: int = 0) -> dict:
    facets = []
    if mc_version:
        facets.append([f'versions:{mc_version}'])
    if mod_type:
        facets.append([f'project_type:{mod_type}'])
    params = {'query': query or '', 'limit': str(min(max(limit, 1), 40)),
              'offset': str(max(offset, 0))}
    if facets:
        import json as _json
        params['facets'] = _json.dumps(facets)
    url = f'{MODRINTH}/search?' + urllib.parse.urlencode(params)
    try:
        d = http_json(url, timeout=20)
        hits = [{'id': h.get('project_id'), 'slug': h.get('slug'), 'title': h.get('title'),
                 'description': h.get('description'), 'downloads': h.get('downloads'),
                 'author': h.get('author'), 'icon': h.get('icon_url'),
                 'categories': h.get('categories', []), 'versions': (h.get('versions') or [])[-6:],
                 'project_type': h.get('project_type')} for h in d.get('hits', [])]
        return {'ok': True, 'source': 'modrinth', 'total': d.get('total_hits', len(hits)),
                'hits': hits}
    except SourceError as e:
        return {'ok': False, 'error': f'Modrinth 源不可达：{e}', 'hits': [], 'source': 'modrinth'}


def modrinth_versions(project: str, mc_version: str = '', loader: str = '') -> dict:
    loaders = [loader] if loader else []
    params = {}
    if loaders:
        import json as _json
        params['loaders'] = _json.dumps(loaders)
    if mc_version:
        import json as _json
        params['game_versions'] = _json.dumps([mc_version])
    url = f'{MODRINTH}/project/{urllib.parse.quote(project)}/version'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    try:
        d = http_json(url, timeout=20)
        out = []
        for v in d[:30]:
            files = v.get('files') or []
            primary = next((f for f in files if f.get('primary')), files[0] if files else None)
            if not primary:
                continue
            out.append({'id': v.get('id'), 'name': v.get('name'), 'version_number': v.get('version_number'),
                        'game_versions': v.get('game_versions', []), 'loaders': v.get('loaders', []),
                        'date': (v.get('date_published') or '')[:10],
                        'filename': primary.get('filename'), 'url': primary.get('url'),
                        'size': primary.get('size'),
                        'sha1': ((primary.get('hashes') or {}).get('sha1') or ''),
                        'sha512': ((primary.get('hashes') or {}).get('sha512') or '')})
        return {'ok': True, 'versions': out, 'source': 'modrinth'}
    except SourceError as e:
        return {'ok': False, 'error': f'Modrinth 版本列表获取失败：{e}', 'versions': [],
                'source': 'modrinth'}


# ---------------------------------------------------------------- SpigotMC (Spiget)
def spiget_search(query: str, limit: int = 20, offset: int = 0) -> dict:
    try:
        url = (f'{SPIGET}/search/resources/{urllib.parse.quote(query or "")}'
               f'?size={min(max(limit, 1), 40)}&page={max(1, offset // max(1, limit) + 1)}'
               f'&field=name&sort=-downloads')
        d = http_json(url, timeout=20)
        hits = [{'id': r.get('id'), 'title': (r.get('name') or ''),
                 'tag': r.get('tag'), 'premium': bool((r.get('premium') or {}).get('price')),
                 'downloads': r.get('downloads'), 'rating': (r.get('rating') or {}).get('average'),
                 'tested_versions': (r.get('testedVersions') or [])[:6],
                 'icon': (r.get('icon') or {}).get('url'),
                 'external': bool(r.get('external')),
                 'file_type': (r.get('file') or {}).get('type')}
                for r in (d if isinstance(d, list) else [])]
        return {'ok': True, 'source': 'spigot', 'hits': hits}
    except SourceError as e:
        return {'ok': False, 'error': f'SpigotMC(Spiget) 源不可达：{e}', 'hits': [], 'source': 'spigot'}


def _spigot_cdn_url(rid) -> str:
    """SpigotMC 官方 CDN 直链（部分资源可用，付费/外链资源会失败）。"""
    return f'https://cdn.spigotmc.org/resources/{rid}/download'


def spiget_download(rid: str, dest_dir: str) -> dict:
    """先尝试官方 CDN 直链；失败则明确报"需要人工下载"。"""
    rid = str(rid or '').strip()
    if not rid.isdigit():
        return {'ok': False, 'error': '资源 ID 不合法'}
    # 查元信息拿文件名
    fname = f'spigot-{rid}.jar'
    try:
        info = http_json(f'{SPIGET}/resources/{rid}', timeout=15)
        f = info.get('file') or {}
        if f.get('type') == 'external':
            return {'ok': False, 'source': 'spigot',
                    'error': '该资源是外链资源（external），无法自动下载，请到 SpigotMC 手动下载后上传'}
        if f.get('type') == 'premium':
            return {'ok': False, 'source': 'spigot',
                    'error': '该资源为付费资源，无法自动下载，请购买后上传 jar'}
        name = (info.get('name') or f'spigot-{rid}')
        fname = re.sub(r'[^A-Za-z0-9._\-]', '_', name)[:60] + '.jar'
    except SourceError:
        pass
    url = _spigot_cdn_url(rid)
    from .downloader import download_sync
    dest = os.path.join(dest_dir, fname)
    res = download_sync(url, dest, timeout=180)
    if res.get('ok'):
        return {'ok': True, 'file': dest, 'name': fname, 'source': 'spigot'}
    return {'ok': False, 'source': 'spigot',
            'error': f'SpigotMC 自动下载失败（{res.get("error") or res.get("status")}）'
                     f'——该站有 Cloudflare 与登录限制，请手动下载后上传'}


# ---------------------------------------------------------------- CurseForge
def curseforge_search(query: str, mc_version: str = '', limit: int = 20) -> dict:
    key = (get_config().get('curseforge_api_key') or '').strip()
    if not key:
        return {'ok': False, 'source': 'curseforge', 'hits': [],
                'error': 'CurseForge 需要 API Key（在设置页填写），官方接口不允许匿名访问（实测直连返回 403）'}
    params = {'gameId': '432', 'searchFilter': query or '',
              'pageSize': str(min(max(limit, 1), 40)), 'sortField': '2', 'sortOrder': 'desc'}
    if mc_version:
        params['gameVersion'] = mc_version
    url = f'{CURSEFORGE}/mods/search?' + urllib.parse.urlencode(params)
    try:
        raw = http_get(url, timeout=20, headers={'x-api-key': key, 'Accept': 'application/json'})
        import json as _json
        d = _json.loads(raw.decode('utf-8', 'replace'))
        hits = [{'id': m.get('id'), 'title': m.get('name'), 'description': (m.get('summary') or '')[:200],
                 'downloads': (m.get('downloadCount')), 'author': '',
                 'icon': ((m.get('logo') or {}).get('thumbnailUrl')),
                 'categories': []} for m in d.get('data', [])]
        return {'ok': True, 'source': 'curseforge', 'hits': hits}
    except SourceError as e:
        return {'ok': False, 'source': 'curseforge', 'hits': [],
                'error': f'CurseForge 接口调用失败：{e}'}


def curseforge_files(mod_id: str, mc_version: str = '') -> dict:
    key = (get_config().get('curseforge_api_key') or '').strip()
    if not key:
        return {'ok': False, 'source': 'curseforge', 'error': 'CurseForge 需要 API Key', 'files': []}
    url = f'{CURSEFORGE}/mods/{urllib.parse.quote(str(mod_id))}/files'
    if mc_version:
        url += '?' + urllib.parse.urlencode({'gameVersion': mc_version})
    try:
        raw = http_get(url, timeout=20, headers={'x-api-key': key, 'Accept': 'application/json'})
        import json as _json
        d = _json.loads(raw.decode('utf-8', 'replace'))
        files = []
        for f in d.get('data', [])[:30]:
            files.append({'id': f.get('id'), 'name': f.get('displayName'),
                          'filename': f.get('fileName'), 'size': f.get('fileLength'),
                          'date': (f.get('fileDate') or '')[:10],
                          'downloadUrl': f.get('downloadUrl')})
        return {'ok': True, 'source': 'curseforge', 'files': files}
    except SourceError as e:
        return {'ok': False, 'source': 'curseforge', 'files': [],
                'error': f'CurseForge 文件列表失败：{e}'}


# ---------------------------------------------------------------- 统一搜索
def search(query: str, mc_version: str = '', source: str = 'modrinth',
           mod_type: str = '', limit: int = 20) -> dict:
    if source == 'modrinth':
        return modrinth_search(query, mc_version, mod_type, limit)
    if source == 'spigot':
        return spiget_search(query, limit)
    if source == 'curseforge':
        return curseforge_search(query, mc_version, limit)
    return {'ok': False, 'error': f'未知源：{source}', 'hits': []}


def probe() -> list:
    out = []
    r = modrinth_search('sodium', limit=1)
    out.append({'source': 'modrinth', 'ok': r.get('ok', False), 'error': r.get('error', '')})
    r = spiget_search('EssentialsX', limit=1)
    out.append({'source': 'spigot', 'ok': r.get('ok', False), 'error': r.get('error', '')})
    r = curseforge_search('jei', limit=1)
    out.append({'source': 'curseforge', 'ok': r.get('ok', False),
                'error': r.get('error', '') if not r.get('ok') else ''})
    return out


def loader_for(core_type: str) -> str:
    return {'fabric': 'fabric', 'quilt': 'quilt', 'forge': 'forge',
            'neoforge': 'neoforge', 'paper': 'paper', 'purpur': 'paper',
            'spigot': 'spigot', 'bukkit': 'bukkit'}.get(str(core_type or '').lower(), '')
