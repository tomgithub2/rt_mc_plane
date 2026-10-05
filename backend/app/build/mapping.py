"""方块状态注册表与版本映射。

映射目标：把「方块状态串」映射为目标 MC 版本的**全局方块状态数字 id**（Anvil 用的那个 id）。

注册表来源（按优先级，全部实测过）：
  1. 缓存         ``data/build/cache/blocks-<version>.json``（本模块生成）
  2. 实例内 reports ``<实例目录>/**/generated/reports/blocks.json``（官方数据生成器产物）
  3. 实例服务端 jar ``java -DbundlerMainClass=net.minecraft.data.Main -jar server.jar --reports``
     （1.21.4 实测 ~1.2 秒生成，会解包 40+ 个 library jar，只做一次并缓存）
  4. 实例世界存档里已有的区块调色板（**稀疏回退**：只能识别世界里出现过的方块状态）
  5. 内置的旧版兼容表（只用于 .schematic 的 id+meta → 现代方块名）

映射不上的方块会进入「未映射清单」，由预检 / 用户决定跳过还是中止。
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading

try:
    from ..config import DATA_DIR, get_config
except Exception:                                     # pragma: no cover
    DATA_DIR = os.path.join(os.getcwd(), 'data')
    def get_config():
        return {}

CACHE_DIR = os.path.join(DATA_DIR, 'build', 'cache')

_STATE_RE = re.compile(r'^\s*([A-Za-z0-9_.\-]+:[A-Za-z0-9_./\-]+|\*)\s*(?:\[(.*)\])?\s*$')

# 常见方块改名（旧名 → 新名）。覆盖建筑里最常见的几种。
ALIASES = {
    'minecraft:grass': 'minecraft:short_grass',
    'minecraft:grass_path': 'minecraft:dirt_path',
    'minecraft:lit_furnace': 'minecraft:furnace',
    'minecraft:flowing_water': 'minecraft:water',
    'minecraft:flowing_lava': 'minecraft:lava',
    'minecraft:water': 'minecraft:water',
    'minecraft:lava': 'minecraft:lava',
    'minecraft:cauldron': 'minecraft:cauldron',
    'minecraft:sign': 'minecraft:oak_sign',
    'minecraft:wall_sign': 'minecraft:oak_wall_sign',
    'minecraft:wooden_door': 'minecraft:oak_door',
    'minecraft:wooden_slab': 'minecraft:oak_slab',
    'minecraft:wooden_stairs': 'minecraft:oak_stairs',
    'minecraft:double_wooden_slab': 'minecraft:oak_slab',
    'minecraft:standing_banner': 'minecraft:white_banner',
    'minecraft:wall_banner': 'minecraft:white_wall_banner',
    'minecraft:bed': 'minecraft:red_bed',
    'minecraft:skull': 'minecraft:skeleton_skull',
    'minecraft:stone_slab': 'minecraft:smooth_stone_slab',
    'minecraft:stone_stairs': 'minecraft:cobblestone_stairs',
    'minecraft:fence': 'minecraft:oak_fence',
    'minecraft:fence_gate': 'minecraft:oak_fence_gate',
    'minecraft:nether_brick_fence': 'minecraft:nether_brick_fence',
    'minecraft:nether_brick_stairs': 'minecraft:nether_brick_stairs',
    'minecraft:brick_stairs': 'minecraft:brick_stairs',
    'minecraft:stone_brick_stairs': 'minecraft:stone_brick_stairs',
    'minecraft:sandstone_stairs': 'minecraft:sandstone_stairs',
    'minecraft:spruce_stairs': 'minecraft:spruce_stairs',
    'minecraft:birch_stairs': 'minecraft:birch_stairs',
    'minecraft:jungle_stairs': 'minecraft:jungle_stairs',
    'minecraft:acacia_stairs': 'minecraft:acacia_stairs',
    'minecraft:dark_oak_stairs': 'minecraft:dark_oak_stairs',
    'minecraft:quartz_stairs': 'minecraft:quartz_stairs',
    'minecraft:red_sandstone_stairs': 'minecraft:red_sandstone_stairs',
    'minecraft:purpur_stairs': 'minecraft:purpur_stairs',
    'minecraft:hardened_clay': 'minecraft:terracotta',
    'minecraft:stained_hardened_clay': 'minecraft:white_terracotta',
    'minecraft:stained_glass': 'minecraft:white_stained_glass',
    'minecraft:stained_glass_pane': 'minecraft:white_stained_glass_pane',
    'minecraft:concrete': 'minecraft:white_concrete',
    'minecraft:concrete_powder': 'minecraft:white_concrete_powder',
    'minecraft:wool': 'minecraft:white_wool',
    'minecraft:carpet': 'minecraft:white_carpet',
    'minecraft:prismarine_bricks': 'minecraft:prismarine_bricks',
    'minecraft:noteblock': 'minecraft:note_block',
    'minecraft:golden_rail': 'minecraft:powered_rail',
    'minecraft:lit_redstone_torch': 'minecraft:redstone_torch',
    'minecraft:unlit_redstone_torch': 'minecraft:redstone_torch',
    'minecraft:redstone_wire': 'minecraft:redstone_wire',
    'minecraft:end_bricks': 'minecraft:end_stone_bricks',
    'minecraft:magma': 'minecraft:magma_block',
    'minecraft:slime': 'minecraft:slime_block',
    'minecraft:snow_layer': 'minecraft:snow',
    'minecraft:heavy_weighted_pressure_plate': 'minecraft:heavy_weighted_pressure_plate',
    'minecraft:light_weighted_pressure_plate': 'minecraft:light_weighted_pressure_plate',
    'minecraft:daylight_detector_inverted': 'minecraft:daylight_detector',
    'minecraft:trapdoor': 'minecraft:oak_trapdoor',
    'minecraft:iron_trapdoor': 'minecraft:iron_trapdoor',
    'minecraft:wooden_button': 'minecraft:oak_button',
    'minecraft:stone_button': 'minecraft:stone_button',
    'minecraft:wooden_pressure_plate': 'minecraft:oak_pressure_plate',
    'minecraft:piston_head': 'minecraft:piston_head',
    'minecraft:piston_extension': 'minecraft:moving_piston',
    'minecraft:end_gateway': 'minecraft:end_gateway',
    'minecraft:purpur_pillar': 'minecraft:purpur_pillar',
    'minecraft:quartz_ore': 'minecraft:nether_quartz_ore',
    'minecraft:sea_lantern': 'minecraft:sea_lantern',
    'minecraft:structure_block': 'minecraft:structure_block',
    'minecraft:standing_sign': 'minecraft:oak_sign',
    'minecraft:wall_banner': 'minecraft:white_wall_banner',
    '.': 'minecraft:air',
    'minecraft:air': 'minecraft:air',
    'minecraft:cave_air': 'minecraft:cave_air',
    'minecraft:void_air': 'minecraft:void_air',
}


def normalize_name(name: str) -> str:
    name = str(name or '').strip()
    if not name:
        return 'minecraft:air'
    if ':' not in name:
        name = 'minecraft:' + name
    return ALIASES.get(name, name)


def split_state(state: str):
    """把一个方块状态串拆成 (name, properties)。"""
    s = str(state or '').strip()
    if not s:
        return 'minecraft:air', {}
    props = {}
    if '[' in s:
        name, rest = s.split('[', 1)
        if rest.endswith(']'):
            rest = rest[:-1]
        for part in rest.split(','):
            part = part.strip()
            if not part or '=' not in part:
                continue
            k, v = part.split('=', 1)
            props[k.strip()] = v.strip()
    else:
        name = s
    return normalize_name(name), props


# ---------------------------------------------------------------- 注册表

class Registry:
    """某个 MC 版本的方块状态表。"""

    def __init__(self, version: str, source: str = '', sparse: bool = False):
        self.version = str(version or '')
        self.source = source
        self.sparse = bool(sparse)
        self.by_state = {}        # 'minecraft:stone[facing=north]' 规范化串 → id
        self.blocks = {}          # name → {'states': {props_tuple: id}, 'props': {k: [v..]},
        #                                       'default': id}
        self.unmapped_report = []

    # ------------------------------------------------------------ 查询
    @staticmethod
    def props_key(props: dict):
        return tuple(sorted((str(k), str(v)) for k, v in (props or {}).items()))

    def has_block(self, name: str) -> bool:
        return name in self.blocks

    def state_id(self, name: str, props: dict):
        """精确查询；不存在返回 None。"""
        blk = self.blocks.get(name)
        if not blk:
            return None
        return blk['states'].get(self.props_key(props))

    def canonical(self, name: str, props: dict):
        """把属性补齐/裁剪成目标版本认可的集合。

        返回 ``(props, notes)``；notes 记录被丢弃的未知属性 / 补上的默认值。
        """
        notes = []
        blk = self.blocks.get(name)
        if not blk:
            return dict(props or {}), notes
        allowed = blk.get('props') or {}
        out = {}
        for k, v in (props or {}).items():
            vals = allowed.get(k)
            if vals is None:
                notes.append(f'属性 {k} 在 {self.version} 不存在，已忽略')
                continue
            if str(v) not in vals:
                notes.append(f'属性 {k}={v} 在 {self.version} 不合法，已忽略')
                continue
            out[k] = str(v)
        for k, vals in allowed.items():
            if k not in out and vals:
                out[k] = str(vals[0])
        if set(out) != set(props or {}) or any(str((props or {}).get(k)) != out[k] for k in out):
            pass
        return out, notes

    def resolve(self, name: str, props: dict):
        """尽力解析：精确 → 规范化 → 忽略属性 → 默认状态。返回 (id|None, notes)。"""
        notes = []
        name = normalize_name(name)
        blk = self.blocks.get(name)
        if not blk:
            return None, [f'方块 {name} 在 {self.version} 不存在']
        sid = self.state_id(name, props)
        if sid is not None:
            return sid, notes
        cand, n2 = self.canonical(name, props)
        notes += n2
        sid = self.state_id(name, cand)
        if sid is not None:
            return sid, notes
        d = blk.get('default')
        if d is not None:
            notes.append(f'方块 {name} 的该状态组合不存在，已改用默认状态')
            return d, notes
        return None, notes + [f'方块 {name} 无可用状态']

    # ------------------------------------------------------------ 构建
    def add(self, name: str, props: dict, sid: int, default: bool = False):
        name = normalize_name(name)
        blk = self.blocks.setdefault(name, {'states': {}, 'props': {}, 'default': None})
        k = self.props_key(props)
        blk['states'][k] = int(sid)
        if default or blk['default'] is None:
            if default:
                blk['default'] = int(sid)
        for pk, pv in (props or {}).items():
            vals = blk['props'].setdefault(str(pk), [])
            if str(pv) not in vals:
                vals.append(str(pv))
        self.by_state[self.state_string(name, props)] = int(sid)

    @staticmethod
    def state_string(name: str, props: dict) -> str:
        if not props:
            return name
        return name + '[' + ','.join(f'{k}={v}' for k, v in sorted(props.items())) + ']'

    def finalize(self):
        for blk in self.blocks.values():
            if blk['default'] is None and blk['states']:
                blk['default'] = min(blk['states'].values())
        return self

    def to_json(self) -> dict:
        return {
            'version': self.version,
            'source': self.source,
            'sparse': self.sparse,
            'blocks': {n: {'props': b['props'], 'default': b['default'],
                           'states': [['|'.join(f'{k}={v}' for k, v in kk), sid]
                                      for kk, sid in b['states'].items()]}
                       for n, b in self.blocks.items()},
        }

    @staticmethod
    def from_json(d: dict) -> 'Registry':
        reg = Registry(d.get('version', ''), d.get('source', ''), d.get('sparse', False))
        for name, b in (d.get('blocks') or {}).items():
            blk = reg.blocks.setdefault(name, {'states': {}, 'props': {}, 'default': None})
            blk['props'] = {k: list(v) for k, v in (b.get('props') or {}).items()}
            blk['default'] = b.get('default')
            for pair in (b.get('states') or []):
                key, sid = pair[0], int(pair[1])
                props = {}
                if key:
                    for kv in key.split('|'):
                        if '=' in kv:
                            k, v = kv.split('=', 1)
                            props[k] = v
                blk['states'][Registry.props_key(props)] = sid
                reg.by_state[Registry.state_string(name, props)] = sid
        return reg


# ---------------------------------------------------------------- reports 解析

def registry_from_mojang_report(data: dict, version: str, source: str = 'reports') -> Registry:
    """Mojang 数据生成器的 ``generated/reports/blocks.json`` → Registry。"""
    reg = Registry(version, source=source)
    for name, blk in (data or {}).items():
        if not isinstance(blk, dict):
            continue
        states = blk.get('states') or []
        for st in states:
            if not isinstance(st, dict):
                continue
            props = st.get('properties') or {}
            reg.add(name, {str(k): str(v) for k, v in props.items()},
                    int(st.get('id', 0)), default=bool(st.get('default')))
    return reg.finalize()


def registry_from_world_regions(world_dir: str, version: str) -> Registry:
    """稀疏回退：扫世界 region 文件里出现过的 palette（只能识别出现过的状态）。"""
    from . import anvil
    reg = Registry(version, source='world-palette(稀疏回退)', sparse=True)
    count = 0
    for path in anvil.iter_region_files(world_dir):
        try:
            with anvil.RegionFile(path) as rf:
                for cx, cz in rf.present_chunks():
                    nbt = rf.read_chunk(cx, cz)
                    if not nbt:
                        continue
                    tag = nbt
                    for sect in anvil.sections_of(tag):
                        pal = anvil.section_palette(sect)
                        for entry in pal:
                            name = entry.get('Name') or ''
                            if not name:
                                continue
                            props = {str(k): str(v) for k, v in (entry.get('Properties') or {}).items()}
                            if reg.has_block(name) and reg.state_id(name, props) is not None:
                                continue
                            # 无法知道全局 id，用「未定」占位；解析时按默认状态处理
                            reg.add(name, props, -1)
                        count += 1
                    if count > 4000:
                        break
        except Exception:
            continue
    if not reg.blocks:
        raise RuntimeError('世界存档里没有可用的区块调色板')
    for blk in reg.blocks.values():
        if blk['default'] is None or blk['default'] < 0:
            blk['default'] = None
    return reg.finalize_sparse()


class _SparseRegistry(Registry):
    pass


def _finalize_sparse(self: Registry):
    """稀疏表：默认状态标记为 -1，表示“不知道该状态的全局 id”。"""
    for blk in self.blocks.values():
        if blk['default'] is None or blk['default'] < 0:
            blk['default'] = -1
        blk['states'] = {k: (-1 if v is None or v < 0 else v) for k, v in blk['states'].items()}
    return self


Registry.finalize_sparse = _finalize_sparse


# ---------------------------------------------------------------- 注册表获取

_lock = threading.RLock()
_cache = {}
_mem_cache = {}


def cache_path(version: str) -> str:
    safe = re.sub(r'[^A-Za-z0-9._\-]', '_', str(version or 'unknown'))[:64]
    return os.path.join(CACHE_DIR, f'blocks-{safe}.json')


def _load_cached(version: str):
    p = cache_path(version)
    if not os.path.isfile(p):
        return None
    try:
        with io.open(p, encoding='utf-8') as f:
            return Registry.from_json(json.load(f))
    except Exception:
        return None


def _save_cached(reg: Registry):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = cache_path(reg.version) + '.tmp'
        with io.open(tmp, 'w', encoding='utf-8') as f:
            json.dump(reg.to_json(), f, ensure_ascii=False)
        os.replace(tmp, cache_path(reg.version))
    except Exception:
        pass


def _find_reports_json(instance_dir_path: str):
    """在实例目录里找数据生成器产物 blocks.json（reports 目录）。"""
    if not instance_dir_path or not os.path.isdir(instance_dir_path):
        return None
    best = None
    for root, dirs, files in os.walk(instance_dir_path):
        dirs[:] = [d for d in dirs if d not in ('libraries', 'versions', '.git')]
        for fn in files:
            if fn == 'blocks.json':
                p = os.path.join(root, fn)
                if os.path.basename(root) == 'reports' or 'reports' in p.replace('\\', '/'):
                    if best is None or os.path.getsize(p) > os.path.getsize(best):
                        best = p
    return best


def generate_reports(jar_path: str, timeout: int = 300, workdir: str = None) -> str:
    """用实例服务端 jar 生成 reports，返回 blocks.json 路径。

    命令：``java -DbundlerMainClass=net.minecraft.data.Main -jar server.jar --reports``
    """
    java = (get_config().get('default_java') or '').strip() or 'java'
    jar_path = os.path.abspath(jar_path)
    if not os.path.isfile(jar_path):
        raise RuntimeError(f'服务端 jar 不存在：{jar_path}')
    gen = workdir or tempfile.mkdtemp(prefix='mcpanel-reports-')
    os.makedirs(gen, exist_ok=True)
    cmd = [java, '-DbundlerMainClass=net.minecraft.data.Main', '-jar', jar_path, '--reports']
    proc = subprocess.run(cmd, cwd=gen, capture_output=True, timeout=timeout)
    out = (proc.stdout or b'').decode('utf-8', 'replace')
    err = (proc.stderr or b'').decode('utf-8', 'replace')
    target = None
    for root, _dirs, files in os.walk(gen):
        for fn in files:
            if fn == 'blocks.json' and os.path.basename(root) == 'reports':
                target = os.path.join(root, fn)
    if not target:
        raise RuntimeError(f'数据生成器未产出 reports（退出码 {proc.returncode}）：'
                           f'{(err or out)[-400:]}')
    return target


def registry_for(mc_version: str, instance: dict = None, allow_generate: bool = True,
                 allow_world_fallback: bool = True) -> Registry:
    """拿到某版本的方块状态注册表（带多层回退，永不抛异常给路由层）。"""
    version = str(mc_version or '').strip() or 'unknown'
    with _lock:
        if version in _mem_cache:
            return _mem_cache[version]
    reg = None
    source = ''
    # 1) 缓存
    reg = _load_cached(version)
    if reg is not None:
        source = 'cache'
    inst_dir = ''
    if instance:
        try:
            from ..config import instance_dir
            inst_dir = instance_dir(instance)
        except Exception:
            inst_dir = instance.get('dir') or ''
    # 2) 实例里的 reports
    if reg is None and inst_dir:
        rp = _find_reports_json(inst_dir)
        if rp:
            try:
                with io.open(rp, encoding='utf-8') as f:
                    reg = registry_from_mojang_report(json.load(f), version, source=f'reports:{rp}')
                source = 'instance-reports'
            except Exception:
                reg = None
    # 3) 用实例 jar 现场生成
    if reg is None and allow_generate and instance:
        jar = instance.get('jar_path') or ''
        jar_abs = jar if os.path.isabs(jar) else os.path.join(inst_dir, os.path.basename(jar or ''))
        if inst_dir and os.path.isfile(jar_abs):
            try:
                rp = generate_reports(jar_abs, workdir=os.path.join(inst_dir, '.mcpanel-reports'))
                with io.open(rp, encoding='utf-8') as f:
                    reg = registry_from_mojang_report(json.load(f), version,
                                                      source=f'jar-reports:{os.path.basename(jar_abs)}')
                source = 'jar-reports'
            except Exception:
                reg = None
    # 4) 稀疏回退：世界存档 palette
    if reg is None and allow_world_fallback and inst_dir:
        for cand in _world_dirs(inst_dir, instance):
            try:
                reg = registry_from_world_regions(cand, version)
                source = 'world-palette'
                break
            except Exception:
                reg = None
    if reg is None:
        reg = Registry(version, source='unavailable')
        reg.finalize()
        with _lock:
            _mem_cache[version] = reg
        return reg
    if source in ('cache', 'instance-reports', 'jar-reports') and not reg.sparse:
        _save_cached(reg)
    with _lock:
        _mem_cache[version] = reg
    return reg


def _world_dirs(inst_dir: str, instance: dict = None):
    out = []
    if not inst_dir:
        return out
    for name in ('world', 'world_nether', 'world_the_end'):
        p = os.path.join(inst_dir, name)
        if os.path.isdir(p):
            out.append(p)
    return out


def registry_available(mc_version: str, instance: dict = None) -> dict:
    """给预检用：注册表是否可用 + 来源 + 方块种类数。"""
    reg = registry_for(mc_version, instance,
                       allow_generate=bool(instance), allow_world_fallback=bool(instance))
    return {
        'available': bool(reg.blocks) and not reg.sparse,
        'partial': bool(reg.sparse),
        'source': reg.source,
        'blocks': len(reg.blocks),
        'version': reg.version,
    }


# ---------------------------------------------------------------- 旧版 id+meta → 现代状态

WOOD = ['oak', 'spruce', 'birch', 'jungle', 'acacia', 'dark_oak']
COLORS = ['white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink', 'gray',
          'light_gray', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black']
_STAIR_BASES = {
    53: 'oak', 134: 'spruce', 135: 'birch', 136: 'jungle', 163: 'acacia', 164: 'dark_oak',
    67: 'cobblestone', 108: 'brick', 109: 'stone_brick', 114: 'nether_brick',
    128: 'sandstone', 156: 'quartz', 180: 'red_sandstone', 203: 'purpur',
}
_SLAB_BASES = {
    44: [(0, 'smooth_stone'), (1, 'sandstone'), (2, 'petrified_oak'), (3, 'cobblestone'),
         (4, 'brick'), (5, 'stone_brick'), (6, 'nether_brick'), (7, 'quartz')],
    182: [(0, 'red_sandstone')],
    126: [(i, w) for i, w in enumerate(WOOD)],
    181: [(i, c) for i, c in enumerate(WOOD)],
    205: [(0, 'purpur')],
}
_SLAB_TOP_BIT = {'stone': 8, 'wood': 8}
_LEGACY_SIMPLE = {
    0: 'air', 1: 'stone', 2: 'grass_block', 3: 'dirt', 4: 'cobblestone', 5: 'planks',
    7: 'bedrock', 12: 'sand', 13: 'gravel', 14: 'gold_ore', 15: 'iron_ore', 16: 'coal_ore',
    17: 'oak_log', 18: 'oak_leaves', 19: 'sponge', 20: 'glass', 21: 'lapis_ore',
    22: 'lapis_block', 23: 'dispenser', 24: 'sandstone', 25: 'note_block', 35: 'white_wool',
    41: 'gold_block', 42: 'iron_block', 45: 'bricks', 46: 'tnt', 47: 'bookshelf',
    48: 'mossy_cobblestone', 49: 'obsidian', 52: 'spawner', 54: 'chest', 56: 'diamond_ore',
    57: 'diamond_block', 58: 'crafting_table', 60: 'farmland', 61: 'furnace', 62: 'furnace',
    65: 'ladder', 73: 'redstone_ore', 74: 'redstone_ore', 79: 'ice', 80: 'snow_block',
    81: 'cactus', 82: 'clay', 83: 'sugar_cane', 84: 'jukebox', 85: 'oak_fence',
    86: 'pumpkin', 87: 'netherrack', 88: 'soul_sand', 89: 'glowstone', 91: 'jack_o_lantern',
    95: 'white_stained_glass', 97: 'infested_stone', 98: 'stone_bricks', 99: 'brown_mushroom_block',
    100: 'red_mushroom_block', 101: 'iron_bars', 102: 'glass_pane', 103: 'melon',
    106: 'vine', 110: 'mycelium', 111: 'lily_pad', 112: 'nether_bricks', 113: 'nether_brick_fence',
    116: 'enchanting_table', 117: 'brewing_stand', 118: 'cauldron', 120: 'end_portal_frame',
    121: 'end_stone', 122: 'dragon_egg', 123: 'redstone_lamp', 124: 'redstone_lamp',
    125: 'oak_planks', 129: 'emerald_ore', 133: 'emerald_block', 137: 'command_block',
    138: 'beacon', 139: 'cobblestone_wall', 140: 'flower_pot', 141: 'carrots',
    142: 'potatoes', 145: 'anvil', 146: 'trapped_chest', 147: 'light_weighted_pressure_plate',
    148: 'heavy_weighted_pressure_plate', 149: 'comparator', 150: 'comparator',
    151: 'daylight_detector', 152: 'redstone_block', 153: 'nether_quartz_ore',
    154: 'hopper', 155: 'quartz_block', 158: 'dropper', 159: 'white_terracotta',
    160: 'white_stained_glass_pane', 161: 'acacia_leaves', 162: 'acacia_log',
    165: 'slime_block', 166: 'barrier', 167: 'iron_trapdoor', 168: 'prismarine',
    169: 'sea_lantern', 170: 'hay_block', 171: 'white_carpet', 172: 'terracotta',
    173: 'coal_block', 174: 'packed_ice', 175: 'sunflower', 176: 'white_banner',
    177: 'white_wall_banner', 178: 'daylight_detector', 179: 'red_sandstone',
    180: 'red_sandstone_stairs', 181: 'red_sandstone_slab', 182: 'red_sandstone_slab',
    183: 'spruce_fence_gate', 184: 'birch_fence_gate', 185: 'jungle_fence_gate',
    186: 'dark_oak_fence_gate', 187: 'acacia_fence_gate', 188: 'spruce_fence',
    189: 'birch_fence', 190: 'jungle_fence', 191: 'dark_oak_fence', 192: 'acacia_fence',
    198: 'end_rod', 199: 'chorus_plant', 200: 'chorus_flower', 201: 'purpur_block',
    202: 'purpur_pillar', 204: 'purpur_double_slab', 206: 'end_stone_bricks',
    207: 'beetroots', 208: 'dirt_path', 209: 'end_gateway', 210: 'repeating_command_block',
    211: 'chain_command_block', 212: 'frosted_ice', 213: 'magma_block', 214: 'nether_wart_block',
    215: 'red_nether_bricks', 216: 'bone_block', 217: 'structure_void', 218: 'observer',
    219: 'white_shulker_box', 220: 'orange_shulker_box', 221: 'magenta_shulker_box',
    222: 'light_blue_shulker_box', 223: 'yellow_shulker_box', 224: 'lime_shulker_box',
    225: 'pink_shulker_box', 226: 'gray_shulker_box', 227: 'light_gray_shulker_box',
    228: 'cyan_shulker_box', 229: 'purple_shulker_box', 230: 'blue_shulker_box',
    231: 'brown_shulker_box', 232: 'green_shulker_box', 233: 'red_shulker_box',
    234: 'black_shulker_box', 235: 'white_glazed_terracotta', 236: 'orange_glazed_terracotta',
    237: 'magenta_glazed_terracotta', 238: 'light_blue_glazed_terracotta',
    239: 'yellow_glazed_terracotta', 240: 'lime_glazed_terracotta', 241: 'pink_glazed_terracotta',
    242: 'gray_glazed_terracotta', 243: 'light_gray_glazed_terracotta',
    244: 'cyan_glazed_terracotta', 245: 'purple_glazed_terracotta', 246: 'blue_glazed_terracotta',
    247: 'brown_glazed_terracotta', 248: 'green_glazed_terracotta', 249: 'red_glazed_terracotta',
    250: 'black_glazed_terracotta', 251: 'white_concrete', 252: 'white_concrete_powder',
    255: 'structure_block',
}
# 需要按 meta 细分的 id
_LEGACY_META = {
    44: 'stone_slab', 43: 'double_stone_slab', 126: 'wooden_slab', 125: 'double_wooden_slab',
    181: 'red_sandstone_slab', 182: 'red_sandstone_slab', 205: 'purpur_slab',
    204: 'purpur_double_slab',
    35: 'wool', 95: 'stained_glass', 159: 'stained_hardened_clay', 160: 'stained_glass_pane',
    171: 'carpet', 251: 'concrete', 252: 'concrete_powder',
    5: 'planks', 17: 'log', 18: 'leaves', 162: 'log2', 161: 'leaves2',
    24: 'sandstone', 98: 'stone_bricks', 155: 'quartz_block', 179: 'red_sandstone',
    168: 'prismarine', 175: 'double_plant', 31: 'tallgrass', 37: 'yellow_flower',
    38: 'red_flower', 6: 'sapling', 50: 'torch', 75: 'redstone_torch', 76: 'redstone_torch',
    54: 'chest', 63: 'standing_sign', 68: 'wall_sign', 144: 'skull',
    149: 'comparator', 150: 'comparator', 151: 'daylight_detector', 178: 'daylight_detector',
    26: 'bed', 176: 'banner', 177: 'banner',
    **{k: 'stairs' for k in _STAIR_BASES},
}

_FACING4 = ['south', 'west', 'north', 'east']      # meta & 3 的旧语义
_TORCH_FACING = ['east', 'west', 'south', 'north', 'up']
_LEAVES_TYPE = ['oak', 'spruce', 'birch', 'jungle']
_PLANT = ['sunflower', 'lilac', 'tall_grass', 'large_fern', 'rose_bush', 'peony']
_FLOWER_YELLOW = ['dandelion']
_FLOWER_RED = ['poppy', 'blue_orchid', 'allium', 'azure_bluet', 'red_tulip', 'orange_tulip',
               'white_tulip', 'pink_tulip', 'oxeye_daisy']
_SAPLING = ['oak', 'spruce', 'birch', 'jungle', 'acacia', 'dark_oak']
_SKULL = {'skeleton': 'skeleton_skull', 'wither': 'wither_skeleton_skull',
          'zombie': 'zombie_head', 'player': 'player_head', 'creeper': 'creeper_head',
          'dragon': 'dragon_head'}


def _stairs_entry(bid: int, meta: int):
    base = _STAIR_BASES.get(bid)
    if not base:
        return None
    facing = _FACING4[meta & 3]
    half = 'top' if (meta & 4) else 'bottom'
    shape = 'straight'
    if bid in (53, 134, 135, 136, 163, 164):
        shape = 'straight'
    name = f'{base}_stairs' if base not in ('stone',) else 'stone_stairs'
    if base == 'cobblestone':
        name = 'cobblestone_stairs'
    elif base in ('brick',):
        name = 'brick_stairs'
    elif base in ('stone_brick',):
        name = 'stone_brick_stairs'
    elif base in ('nether_brick',):
        name = 'nether_brick_stairs'
    elif base in ('sandstone',):
        name = 'sandstone_stairs'
    elif base in ('quartz',):
        name = 'quartz_stairs'
    elif base in ('red_sandstone',):
        name = 'red_sandstone_stairs'
    elif base in ('purpur',):
        name = 'purpur_stairs'
    else:
        name = base + '_stairs'
    from .formats import PaletteEntry
    return PaletteEntry('minecraft:' + name,
                        {'facing': facing, 'half': half, 'shape': shape,
                         'waterlogged': 'false'})


def legacy_block_entry(bid: int, meta: int):
    """旧版 (block id, data) → :class:`~app.build.formats.PaletteEntry`。

    覆盖建筑里最常见的方块；无法精确还原的走近似（例如楼梯的 shape 一律 straight）。
    """
    from .formats import PaletteEntry
    meta = int(meta) & 0x0F
    if bid == 0:
        return PaletteEntry('minecraft:air')
    if bid in _STAIR_BASES:
        e = _stairs_entry(bid, meta)
        if e is not None:
            return e
    if bid in (43, 44, 125, 126, 181, 182, 204, 205):
        top = bool(meta & 8)
        kinds = _SLAB_BASES.get(bid)
        base = None
        if kinds:
            base = dict(kinds).get(meta & 7)
        if not base:
            base = 'smooth_stone' if bid in (43, 44) else 'red_sandstone'
        name = base + '_slab'
        if bid in (43, 125, 204):
            name = base + '_slab'          # 双台阶在 1.13+ 就是同一种半砖
        return PaletteEntry('minecraft:' + name, {'type': 'top' if top else 'bottom',
                                                  'waterlogged': 'false'})
    if bid in (35, 95, 159, 160, 171, 251, 252):
        color = COLORS[meta & 15]
        tail = {35: 'wool', 95: 'stained_glass', 159: 'terracotta',
                160: 'stained_glass_pane', 171: 'carpet', 251: 'concrete',
                252: 'concrete_powder'}[bid]
        return PaletteEntry(f'minecraft:{color}_{tail}')
    if bid in (5, 17, 18, 161, 162):
        idx = meta & 3 if bid in (17, 18) else meta & 7
        if bid in (17, 18):
            idx = meta & 3
        wood = WOOD[idx] if idx < len(WOOD) else 'oak'
        if bid == 5:
            return PaletteEntry(f'minecraft:{wood}_planks')
        if bid == 17:
            if meta & 12 == 0:
                return PaletteEntry(f'minecraft:{wood}_log', {'axis': 'y'})
            if meta & 12 == 4:
                return PaletteEntry(f'minecraft:{wood}_log', {'axis': 'x'})
            if meta & 12 == 8:
                return PaletteEntry(f'minecraft:{wood}_log', {'axis': 'z'})
            return PaletteEntry(f'minecraft:{wood}_wood', {'axis': 'y'})
        if bid == 18:
            return PaletteEntry(f'minecraft:{wood}_leaves',
                                {'distance': '7', 'persistent': 'false', 'waterlogged': 'false'})
        if bid == 162:
            wood2 = WOOD[4 + (meta & 1)] if (meta & 1) < 2 else 'acacia'
            if meta & 12 == 4:
                return PaletteEntry(f'minecraft:{wood2}_log', {'axis': 'x'})
            if meta & 12 == 8:
                return PaletteEntry(f'minecraft:{wood2}_log', {'axis': 'z'})
            return PaletteEntry(f'minecraft:{wood2}_log', {'axis': 'y'})
        if bid == 161:
            wood2 = 'dark_oak' if (meta & 1) else 'acacia'
            return PaletteEntry(f'minecraft:{wood2}_leaves',
                                {'distance': '7', 'persistent': 'false', 'waterlogged': 'false'})
    if bid == 24:
        if meta == 1:
            return PaletteEntry('minecraft:chiseled_sandstone')
        if meta == 2:
            return PaletteEntry('minecraft:cut_sandstone')
        return PaletteEntry('minecraft:sandstone')
    if bid == 179:
        if meta == 1:
            return PaletteEntry('minecraft:chiseled_red_sandstone')
        if meta == 2:
            return PaletteEntry('minecraft:cut_red_sandstone')
        return PaletteEntry('minecraft:red_sandstone')
    if bid == 98:
        name = {0: 'stone_bricks', 1: 'mossy_stone_bricks', 2: 'cracked_stone_bricks',
                3: 'chiseled_stone_bricks'}.get(meta, 'stone_bricks')
        return PaletteEntry('minecraft:' + name)
    if bid == 155:
        if meta in (1,):
            return PaletteEntry('minecraft:chiseled_quartz_block')
        if meta in (2, 3, 4):
            return PaletteEntry('minecraft:quartz_pillar', {'axis': 'y'})
        return PaletteEntry('minecraft:quartz_block')
    if bid == 168:
        return PaletteEntry({0: 'minecraft:prismarine', 1: 'minecraft:prismarine_bricks',
                             2: 'minecraft:dark_prismarine'}.get(meta, 'minecraft:prismarine'))
    if bid == 6:
        return PaletteEntry(f'minecraft:{_SAPLING[meta & 7] if (meta & 7) < 6 else "oak"}_sapling',
                            {'stage': '0'})
    if bid == 31:
        return PaletteEntry({0: 'minecraft:dead_bush', 1: 'minecraft:short_grass',
                             2: 'minecraft:fern'}.get(meta, 'minecraft:short_grass'))
    if bid == 37:
        return PaletteEntry('minecraft:dandelion')
    if bid == 38:
        name = _FLOWER_RED[meta] if meta < len(_FLOWER_RED) else 'poppy'
        return PaletteEntry('minecraft:' + name)
    if bid == 175:
        name = _PLANT[meta & 7] if (meta & 7) < len(_PLANT) else 'sunflower'
        return PaletteEntry('minecraft:' + name, {'half': 'upper' if (meta & 8) else 'lower'})
    if bid in (50, 75, 76):
        facing = _TORCH_FACING[meta] if meta < len(_TORCH_FACING) else 'up'
        name = 'wall_torch' if facing != 'up' else 'torch'
        if bid in (75, 76):
            name = 'redstone_wall_torch' if facing != 'up' else 'redstone_torch'
            if bid == 75:
                return PaletteEntry('minecraft:redstone_torch', {'lit': 'true'})
        return PaletteEntry('minecraft:' + name, {'facing': facing} if facing != 'up' else {})
    if bid == 54:
        return PaletteEntry('minecraft:chest', {'facing': _FACING4[meta & 3], 'type': 'single',
                                                'waterlogged': 'false'})
    if bid == 146:
        return PaletteEntry('minecraft:trapped_chest', {'facing': _FACING4[meta & 3],
                                                        'type': 'single', 'waterlogged': 'false'})
    if bid in (61, 62):
        return PaletteEntry('minecraft:furnace', {'facing': _FACING4[meta & 3],
                                                  'lit': 'true' if bid == 62 else 'false'})
    if bid == 23:
        return PaletteEntry('minecraft:dispenser', {'facing': _FACING4[meta & 7]
                                                    if (meta & 7) < 4 else 'north',
                                                    'triggered': 'false'})
    if bid == 158:
        return PaletteEntry('minecraft:dropper', {'facing': _FACING4[meta & 7]
                                                  if (meta & 7) < 4 else 'north',
                                                  'triggered': 'false'})
    if bid == 63:
        return PaletteEntry('minecraft:oak_sign', {'rotation': str((meta & 15) * 22)})
    if bid == 68:
        return PaletteEntry('minecraft:oak_wall_sign', {'facing': _FACING4[meta & 7]
                                                        if (meta & 7) < 4 else 'north',
                                                        'waterlogged': 'false'})
    if bid == 144:
        return PaletteEntry('minecraft:' + _SKULL.get(str(meta & 7), 'skeleton_skull'),
                            {'rotation': str((meta >> 3 & 1) * 8)})
    if bid == 26:
        return PaletteEntry('minecraft:red_bed', {'facing': _FACING4[meta & 3],
                                                 'part': 'head' if (meta & 8) else 'foot',
                                                 'occupied': 'false'})
    if bid == 149:
        return PaletteEntry('minecraft:comparator',
                            {'facing': _FACING4[meta & 3], 'mode': 'compare',
                             'powered': 'false'})
    if bid == 150:
        return PaletteEntry('minecraft:comparator',
                            {'facing': _FACING4[meta & 3], 'mode': 'subtract',
                             'powered': 'false'})
    if bid in (151, 178):
        return PaletteEntry('minecraft:daylight_detector', {'inverted': 'true' if bid == 178
                                                            else 'false', 'power': '0'})
    if bid == 176:
        return PaletteEntry('minecraft:white_banner', {'rotation': str((meta & 15) * 22)})
    if bid == 177:
        return PaletteEntry('minecraft:white_wall_banner', {'facing': _FACING4[meta & 3]})
    if bid == 139:
        return PaletteEntry('minecraft:cobblestone_wall', {'up': 'true',
                                                           'waterlogged': 'false'})
    if bid == 145:
        return PaletteEntry('minecraft:anvil', {'facing': _FACING4[meta & 3]})
    if bid == 120:
        return PaletteEntry('minecraft:end_portal_frame',
                            {'facing': _FACING4[meta & 3], 'eye': 'true' if (meta & 4) else 'false'})
    if bid == 154:
        return PaletteEntry('minecraft:hopper', {'facing': 'down' if (meta & 8) else
                                                 _FACING4[meta & 7] if (meta & 7) < 4 else 'down',
                                                 'enabled': 'true'})
    if bid == 218:
        return PaletteEntry('minecraft:observer', {'facing': _FACING4[meta & 7]
                                                   if (meta & 7) < 6 else 'north',
                                                   'powered': 'false'})
    if bid == 216:
        return PaletteEntry('minecraft:bone_block', {'axis': ['y', 'x', 'z', 'y'][meta & 3]})
    if bid == 173:
        return PaletteEntry('minecraft:coal_block')
    if bid == 206:
        return PaletteEntry('minecraft:end_stone_bricks')
    if bid == 215:
        return PaletteEntry('minecraft:red_nether_bricks')
    if bid == 213:
        return PaletteEntry('minecraft:magma_block')
    if bid == 198:
        return PaletteEntry('minecraft:end_rod', {'facing': 'up'})
    if bid in _LEGACY_SIMPLE and bid not in _LEGACY_META:
        return PaletteEntry('minecraft:' + _LEGACY_SIMPLE[bid])
    if bid in _LEGACY_SIMPLE:
        return PaletteEntry('minecraft:' + _LEGACY_SIMPLE[bid])
    # 未知 id：退化成石头，让它进入未映射清单更安全 —— 这里返回 air 会静默丢方块，
    # 所以用一个显式的伪名字，预检会把它列出来。
    return PaletteEntry(f'minecraft:legacy_unknown_{bid}_{meta}')
