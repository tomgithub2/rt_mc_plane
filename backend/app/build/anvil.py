"""Anvil 区域文件（region/r.X.Z.mca）读写。

要点
  · **floor 语义**：区块坐标 = ``X >> 4``（Python 的 ``>>`` 对负数就是 floor），
    区域坐标 = ``X >> 9``；区域内偏移 = ``(X & 511) >> 4``。绝不能用 ``int(X/16)``。
  · 同时维护 ``DIM-1`` / ``DIM1`` 老布局与 1.16+ 的 ``dimensions/<ns>/<name>/region`` 新布局。
  · ``block_states`` 位打包：``bits = max(4, ceil(log2(palette_len)))``，
    **条目不允许跨 long 边界**（与 1.16+ 客户端一致；这点和 Litematica 的 tight 打包不同）。
  · 写回时保留原有 chunk 的其它 tag（只替换 sections / block_entities / Heightmaps）。
  · 能从零创建区块：给出实测验证过的最小字段集（见 :func:`new_chunk`）。
"""
import io
import os
import struct
import time
import zlib

from . import nbt as nbtlib
from .nbt import NbtError, NbtLimits, Tag, cget, cget_compound, cget_int, cget_list, cget_str

SECTOR = 4096
MAX_CHUNK_BYTES = SECTOR * 255
REGION_MAGIC = b''

# 世界高度（vanilla 固定值）
DIMENSIONS = {
    'overworld': {'min_y': -64, 'height': 384, 'dirs': ['world', 'region']},
    'nether': {'min_y': 0, 'height': 256, 'dirs': ['world_nether', 'DIM-1']},
    'end': {'min_y': 0, 'height': 256, 'dirs': ['world_the_end', 'DIM1']},
}
BIOME_NAMES = {'overworld': 'minecraft:plains', 'nether': 'minecraft:nether_wastes',
               'end': 'minecraft:the_end'}


class AnvilError(Exception):
    pass


# ---------------------------------------------------------------- 坐标

def chunk_of(v: int) -> int:
    """**floor** 除法：-1 → -1，-16 → -1，-17 → -2。"""
    return int(v) >> 4


def region_of(v: int) -> int:
    return int(v) >> 9


def local_chunk(v: int) -> int:
    return (int(v) >> 4) & 31


def local_in_chunk(v: int) -> int:
    return int(v) & 15


def region_index(cx: int, cz: int) -> int:
    return (int(cx) & 31) + (int(cz) & 31) * 32


# ---------------------------------------------------------------- 位打包

def bits_for(length: int) -> int:
    """Anvil 方块状态每条的位数：max(4, ceil(log2(n)))。"""
    n = int(length)
    if n <= 1:
        return 4
    return max(4, (n - 1).bit_length())


def align_pack(values, bits: int):
    """aligned 打包：条目不跨 long 边界。返回 [int64]。"""
    if bits <= 0:
        bits = 4
    per = 64 // bits
    longs = [0] * ((len(values) + per - 1) // per)
    mask = (1 << bits) - 1
    for i, v in enumerate(values):
        li = i // per
        off = (i % per) * bits
        longs[li] |= (int(v) & mask) << off
    # 转成有符号 64 位
    return [x - (1 << 64) if x >= (1 << 63) else x for x in longs]


def align_unpack(longs, count: int, bits: int):
    """aligned 解包（与 :func:`align_pack` 对称）。"""
    if bits <= 0:
        bits = 4
    per = 64 // bits
    mask = (1 << bits) - 1
    out = [0] * count
    for i in range(count):
        li = i // per
        if li >= len(longs):
            break
        v = int(longs[li]) & 0xFFFFFFFFFFFFFFFF
        out[i] = (v >> ((i % per) * bits)) & mask
    return out


def section_index(x: int, y: int, z: int) -> int:
    """区块内索引：(y*16 + z)*16 + x，x/y/z 为 0..15。"""
    return (int(y) * 16 + int(z)) * 16 + int(x)


# ---------------------------------------------------------------- 区域文件

class RegionFile:
    """一个 r.X.Z.mca 的读写封装（整体载入内存，小文件足够快且在 Windows 上更稳）。"""

    def __init__(self, path: str):
        self.path = path
        self.locations = [0] * 1024      # 每条：offset(24bit) << 8 | length(1byte)
        self.timestamps = [0] * 1024
        self.data = b''                  # 完整原始内容（header 之后是 payload）
        self.dirty = False
        self.new_file = not os.path.isfile(path)
        if not self.new_file:
            with open(path, 'rb') as f:
                raw = f.read()
            if len(raw) == 0:
                self.new_file = True
            elif len(raw) < 2 * SECTOR:
                raise AnvilError(f'区域文件过小，疑似损坏：{path}（{len(raw)} 字节）')
            else:
                for i in range(1024):
                    (loc,) = struct.unpack_from('>i', raw, i * 4)
                    self.locations[i] = loc & 0xFFFFFFFF
                    (ts,) = struct.unpack_from('>i', raw, 4 * 1024 + i * 4)
                    self.timestamps[i] = ts
                self.data = raw

    # ------------------------------------------------------------ 生命周期
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        if self.dirty:
            self.flush()

    # ------------------------------------------------------------ 读取
    def present_chunks(self):
        out = []
        for i, loc in enumerate(self.locations):
            if (loc >> 8) > 0:
                out.append((i % 32, i // 32))
        return out

    def has_chunk(self, cx: int, cz: int) -> bool:
        return (self.locations[region_index(cx, cz)] >> 8) > 0

    def chunk_payload(self, cx: int, cz: int):
        """返回 ``(compression_id, raw_bytes)`` 或 None。

        压缩类型字节高位是 ``0x80`` 时，真正的数据在外部 ``c.X.Z.mcc`` 文件里
        （仅当载荷 >255 扇区 = 1020KiB 才会出现）。
        """
        loc = self.locations[region_index(cx, cz)]
        offset = loc >> 8
        length = loc & 0xFF
        if offset == 0 or length == 0:
            return None
        start = offset * SECTOR
        if start + 5 > len(self.data):
            return None
        (size,) = struct.unpack_from('>i', self.data, start)
        if size <= 0 or size > MAX_CHUNK_BYTES:
            return None
        comp = self.data[start + 4]
        if comp & 0x80:
            # 外部 .mcc
            base = os.path.dirname(self.path)
            mcc = os.path.join(base, f'c.{cx}.{cz}.mcc')
            if not os.path.isfile(mcc):
                raise AnvilError(f'区块 ({cx},{cz}) 使用外部 .mcc 文件但文件不存在：{mcc}')
            with open(mcc, 'rb') as f:
                blob = f.read()
            if len(blob) < 5:
                raise AnvilError(f'外部区块文件过小：{mcc}')
            (size2,) = struct.unpack_from('>i', blob, 0)
            return blob[4], blob[5:4 + size2]
        end = start + 4 + size
        if end > len(self.data):
            return None
        return comp, self.data[start + 5:end]

    def read_chunk(self, cx: int, cz: int, limits: NbtLimits = None):
        """读并解压一个区块，返回 NBT 根 Tag；没有/损坏返回 None。"""
        limits = limits or NbtLimits()
        payload = self.chunk_payload(cx, cz)
        if not payload:
            return None
        comp, raw = payload
        try:
            if comp == 1:
                import gzip
                data = gzip.decompress(raw)
            elif comp == 2:
                data = zlib.decompress(raw)
            elif comp == 3:
                data = raw
            else:
                # 4 = LZ4 / 127 = 自定义压缩 / 128+ = 外部 .mcc：本实现不支持
                raise AnvilError(f'不支持的区块压缩方式 {comp}（LZ4/自定义/外部文件）')
        except AnvilError:
            raise
        except Exception as e:
            raise AnvilError(f'区块 ({cx},{cz}) 解压失败：{type(e).__name__}: {e}')
        if len(data) > limits.raw_bytes:
            raise AnvilError(f'区块 ({cx},{cz}) 解压后过大')
        root = nbtlib.parse(data, limits)
        return root

    # ------------------------------------------------------------ 写入
    def write_chunk(self, cx: int, cz: int, root: Tag, compression: int = 2,
                    limits: NbtLimits = None):
        limits = limits or NbtLimits()
        body = nbtlib.write(root)
        if compression == 2:
            payload = zlib.compress(body, 6)
        elif compression == 1:
            import gzip as _gz
            buf = io.BytesIO()
            with _gz.GzipFile(fileobj=buf, mode='wb', mtime=0) as gz:
                gz.write(body)
            payload = buf.getvalue()
        else:
            compression = 3
            payload = body
        total = len(payload) + 5
        if total > MAX_CHUNK_BYTES:
            raise AnvilError(f'区块 ({cx},{cz}) 压缩后仍有 {total} 字节，超过 255 扇区上限')
        need_sectors = (total + SECTOR - 1) // SECTOR
        idx = region_index(cx, cz)
        old = self.locations[idx]
        old_off = old >> 8
        old_len = old & 0xFF
        if old_off and old_len >= need_sectors:
            start_sector = old_off                      # 原地覆盖，省空间
        else:
            start_sector = self._alloc(need_sectors, idx)
        self._ensure(start_sector * SECTOR + need_sectors * SECTOR)
        buf = bytearray(self.data)
        struct.pack_into('>i', buf, start_sector * SECTOR, len(payload) + 1)
        buf[start_sector * SECTOR + 4] = compression
        buf[start_sector * SECTOR + 5:start_sector * SECTOR + 5 + len(payload)] = payload
        # 尾部 padding 清零（保证整文件 4KiB 对齐且不残留旧数据）
        end = start_sector * SECTOR + total
        limit = (start_sector + need_sectors) * SECTOR
        if limit > len(buf):
            buf.extend(b'\x00' * (limit - len(buf)))
        buf[end:limit] = b'\x00' * (limit - end)
        self.data = bytes(buf)
        self.locations[idx] = ((start_sector << 8) | min(need_sectors, 255)) & 0xFFFFFFFF
        self.timestamps[idx] = int(time.time())
        self.dirty = True
        # 旧位置如果不在原地，释放它
        if old_off and old_off != start_sector:
            self._free(old_off, old_len)
        return start_sector

    def delete_chunk(self, cx: int, cz: int):
        idx = region_index(cx, cz)
        loc = self.locations[idx]
        if not (loc >> 8):
            return
        self._free(loc >> 8, loc & 0xFF)
        self.locations[idx] = 0
        self.timestamps[idx] = 0
        self.dirty = True

    # ------------------------------------------------------------ 扇区管理
    def _sector_bytes(self) -> int:
        return max(2, len(self.data) // SECTOR)

    def _used(self):
        used = set()
        for i, loc in enumerate(self.locations):
            off, ln = loc >> 8, loc & 0xFF
            if off:
                for s in range(off, off + max(1, ln)):
                    used.add(s)
        return used

    def _alloc(self, need: int, skip_idx: int = -1):
        used = self._used()
        total = self._sector_bytes()
        run = 0
        for s in range(2, total + 1):
            if s in used:
                run = 0
                continue
            run += 1
            if run >= need:
                return s - need + 1
        return total           # 追加到文件尾

    def _free(self, off: int, ln: int):
        start = off * SECTOR
        end = (off + max(1, ln)) * SECTOR
        if start >= len(self.data):
            return
        end = min(end, len(self.data))
        buf = bytearray(self.data)
        buf[start:end] = b'\x00' * (end - start)
        self.data = bytes(buf)

    def _ensure(self, size: int):
        if len(self.data) >= size:
            return
        pad = (-len(self.data)) % SECTOR
        self.data = self.data + b'\x00' * pad
        if len(self.data) < size:
            grow = size - len(self.data)
            grow = ((grow + SECTOR - 1) // SECTOR) * SECTOR
            self.data = self.data + b'\x00' * grow

    # ------------------------------------------------------------ 落盘
    def flush(self):
        """写回磁盘：整文件 4KiB 对齐（Minecraft 要求），**先写临时文件再原子替换**。

        这样即使面板在写一半时崩溃，磁盘上的 region 文件也不会变成半截垃圾。
        """
        if not self.dirty and not self.new_file:
            return
        self._ensure(2 * SECTOR)
        buf = bytearray(self.data)
        for i in range(1024):
            struct.pack_into('>i', buf, i * 4, self.locations[i] & 0xFFFFFFFF)
            struct.pack_into('>i', buf, 4 * 1024 + i * 4, self.timestamps[i] & 0xFFFFFFFF)
        if len(buf) % SECTOR:
            buf.extend(b'\x00' * (SECTOR - len(buf) % SECTOR))
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        tmp = self.path + '.mcpanel.tmp'
        with open(tmp, 'wb') as f:
            f.write(buf)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, self.path)
        self.data = bytes(buf)
        self.dirty = False
        self.new_file = False


def iter_region_files(world_dir: str):
    """遍历一个世界目录下所有 region/*.mca。"""
    for sub in ('region', os.path.join('DIM-1', 'region'), os.path.join('DIM1', 'region')):
        d = os.path.join(world_dir, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.startswith('r.') and fn.endswith('.mca'):
                yield os.path.join(d, fn)
    dim_root = os.path.join(world_dir, 'dimensions')
    if os.path.isdir(dim_root):
        for root, dirs, files in os.walk(dim_root):
            if os.path.basename(root) != 'region':
                continue
            for fn in sorted(files):
                if fn.startswith('r.') and fn.endswith('.mca'):
                    yield os.path.join(root, fn)


# ---------------------------------------------------------------- 区块 / section 操作

def sections_of(chunk: Tag):
    """区块里的 sections 列表（Tag list）。"""
    t = cget(chunk, 'sections')
    if isinstance(t, Tag) and t.type == 'list':
        return [s for s in t.value['items'] if isinstance(s, Tag) and s.type == 'compound']
    return []


def section_y(section: Tag) -> int:
    return cget_int(section, 'Y', 0)


def section_palette(section: Tag):
    """返回 [{'Name':.., 'Properties':{..}}]（缺失返回 []）。"""
    bs = cget(section, 'block_states')
    if not isinstance(bs, Tag) or bs.type != 'compound':
        return []
    pal = cget_list(bs, 'palette', 'compound')
    out = []
    for e in pal:
        d = {'Name': cget_str(e, 'Name', ''), 'Properties': {}}
        pt = cget(e, 'Properties')
        if isinstance(pt, Tag) and pt.type == 'compound':
            d['Properties'] = {k: str(v.value) for k, v in pt.value.items()}
        out.append(d)
    return out


def section_blocks(section: Tag):
    """解包一个 section 的方块状态索引数组（长度 4096）。"""
    bs = cget(section, 'block_states')
    pal = section_palette(section)
    if not pal:
        return [], [0] * 4096
    if len(pal) == 1:
        return pal, [0] * 4096
    dt = cget(bs, 'data')
    longs = dt.value if isinstance(dt, Tag) and dt.type == 'longs' else []
    bits = bits_for(len(pal))
    return pal, align_unpack(longs, 4096, bits)


def section_set_blocks(section: Tag, palette: list, values: list):
    """把 (调色板, 4096 个索引) 写回 section（自动选择单值/位打包）。"""
    from .formats import PaletteEntry
    pal_nbt = []
    props_map = []
    for entry in palette:
        if isinstance(entry, PaletteEntry):
            name, props = entry.name, entry.properties
        else:
            name, props = entry.get('Name', ''), entry.get('Properties', {}) or {}
        d = {'Name': Tag.string(name)}
        if props:
            d['Properties'] = Tag.compound({k: Tag.string(str(v)) for k, v in props.items()})
        pal_nbt.append(Tag.compound(d))
        props_map.append((name, tuple(sorted((str(k), str(v)) for k, v in (props or {}).items()))))
    del props_map
    bs = Tag.compound({'palette': Tag.list_(pal_nbt, 'compound')})
    if len(pal_nbt) > 1:
        bits = bits_for(len(pal_nbt))
        bs.value['data'] = Tag.long_array(align_pack(values, bits))
    section.value['block_states'] = bs
    return section


def new_section(y: int, biome: str = 'minecraft:plains', fill_air_index: int = 0):
    return Tag.compound({
        'Y': Tag.byte(y),
        'block_states': Tag.compound({
            'palette': Tag.list_([Tag.compound({'Name': Tag.string('minecraft:air')})], 'compound'),
        }),
        'biomes': Tag.compound({
            'palette': Tag.list_([Tag.string(biome)], 'string'),
        }),
    })


def new_heightmaps(pack_bits: int, height: int, values: dict = None):
    """构造 Heightmaps。values: {'WORLD_SURFACE': [...256], 'MOTION_BLOCKING': [...]} 等。"""
    out = {}
    for key in ('MOTION_BLOCKING', 'MOTION_BLOCKING_NO_LEAVES', 'OCEAN_FLOOR', 'WORLD_SURFACE'):
        arr = (values or {}).get(key) or [0] * 256
        out[key] = Tag.long_array(align_pack(arr, pack_bits))
    return Tag.compound(out)


def new_chunk(cx: int, cz: int, data_version: int, dimension: str = 'overworld',
              sections=None, biome: str = None, heightmaps=None):
    """从零创建一个区块 NBT。

    实测验证过的最小字段集（1.21.4 原版服务端可正常加载、不会重生成、不报坏区块）：
      DataVersion / xPos / zPos / yPos / Status=minecraft:full / LastUpdate
      sections[]（覆盖整个世界的每一节：Y + block_states{palette[,data]} + biomes{palette}）
      Heightmaps（4 个高度图，(height+1) bit × 256 打包）
      structures{starts:{},References:{}} / block_entities[] / block_ticks[] / fluid_ticks[]
      PostProcessing / InhabitedTime
    未写 Light 数据（服务端加载时会自行补全光照），也未写 isLightOn。
    """
    dim = DIMENSIONS.get(dimension) or DIMENSIONS['overworld']
    min_y = dim['min_y']
    height = dim['height']
    biome = biome or BIOME_NAMES.get(dimension, 'minecraft:plains')
    pack_bits = max(1, (height + 1).bit_length())
    if sections is None:
        sections = [new_section(sy, biome)
                    for sy in range(min_y >> 4, ((min_y + height - 1) >> 4) + 1)]
    return Tag.compound({
        'DataVersion': Tag.int(int(data_version or 0)),
        'xPos': Tag.int(cx),
        'zPos': Tag.int(cz),
        'yPos': Tag.int(min_y // 16),
        'Status': Tag.string('minecraft:full'),
        'LastUpdate': Tag.long(int(time.time() * 1000)),
        'InhabitedTime': Tag.long(0),
        'sections': Tag.list_(secs_or(sections), 'compound'),
        'Heightmaps': heightmaps if heightmaps is not None
                      else new_heightmaps(pack_bits, height),
        'structures': Tag.compound({
            'starts': Tag.compound({}),
            'References': Tag.compound({}),
        }),
        'block_entities': Tag.list_([], 'compound'),
        'block_ticks': Tag.list_([], 'compound'),
        'fluid_ticks': Tag.list_([], 'compound'),
        'PostProcessing': Tag.list_(
            [Tag.list_([Tag.short(0)] * 16, 'short') for _ in range(24)], 'list'),
    })


def secs_or(sections):
    return list(sections or [])


def get_or_create_section(chunk: Tag, y: int, biome: str, pack_bits: int):
    """拿到 Y=y 的 section；没有就创建一个并保持 sections 按 Y 升序。"""
    for s in sections_of(chunk):
        if section_y(s) == y:
            return s
    sec = new_section(y, biome)
    lst = cget(chunk, 'sections')
    if not isinstance(lst, Tag) or lst.type != 'list':
        lst = Tag.list_([], 'compound')
        chunk.value['sections'] = lst
    items = lst.value['items']
    items.append(sec)
    items.sort(key=lambda s: section_y(s))
    return sec


def heightmap_values(chunk: Tag, dimension: str, is_solid):
    """按区块当前方块重算 4 个高度图（y 为世界坐标的最大非空 y，无方块记 min_y-1）。"""
    dim = DIMENSIONS.get(dimension) or DIMENSIONS['overworld']
    min_y = dim['min_y']
    height = dim['height']
    out = {}
    for key in ('MOTION_BLOCKING', 'MOTION_BLOCKING_NO_LEAVES', 'OCEAN_FLOOR', 'WORLD_SURFACE'):
        arr = [0] * 256
        for x in range(16):
            for z in range(16):
                top = min_y - 1
                for y in range(min_y + height - 1, min_y - 1, -1):
                    if is_solid(chunk, x, y, z, key):
                        top = y
                        break
                arr[z * 16 + x] = top - min_y + 1
        out[key] = arr
    return out


# ---------------------------------------------------------------- 高层写入器

class ChunkEditor:
    """对一个区块做「读改回写」：解包 → 改少量方块 → 重新打包并保留其它 tag。"""

    def __init__(self, chunk: Tag, dimension: str = 'overworld'):
        self.chunk = chunk
        self.dimension = dimension
        dim = DIMENSIONS.get(dimension) or DIMENSIONS['overworld']
        self.min_y = dim['min_y']
        self.height = dim['height']
        self.biome = BIOME_NAMES.get(dimension, 'minecraft:plains')
        self._palette_cache = {}      # y → (palette, values)
        self._dirty_sections = set()

    # -------------------------------------------------- section 缓存
    def _load(self, sy: int):
        if sy in self._palette_cache:
            return self._palette_cache[sy]
        sec = None
        for s in sections_of(self.chunk):
            if section_y(s) == sy:
                sec = s
                break
        if sec is None:
            sec = get_or_create_section(self.chunk, sy, self.biome,
                                        max(1, (self.height + 1).bit_length()))
        pal, vals = section_blocks(sec)
        if not pal:
            pal = [{'Name': 'minecraft:air', 'Properties': {}}]
            vals = [0] * 4096
        self._palette_cache[sy] = [pal, vals, sec]
        return self._palette_cache[sy]

    def get_block(self, x: int, y: int, z: int):
        """x/z 是区块内 0..15，y 是世界坐标。返回 palette entry dict 或 None。"""
        if y < self.min_y or y >= self.min_y + self.height:
            return None
        sy = y >> 4
        pal, vals, _sec = self._load(sy)
        idx = section_index(x, y & 15, z)
        si = vals[idx]
        if 0 <= si < len(pal):
            return pal[si]
        return None

    def is_air(self, x: int, y: int, z: int) -> bool:
        e = self.get_block(x, y, z)
        if e is None:
            return True
        return str(e.get('Name', '')).endswith(':air') or e.get('Name') in ('minecraft:air',
                                                                           'minecraft:cave_air',
                                                                           'minecraft:void_air')

    def set_block(self, x: int, y: int, z: int, entry) -> bool:
        """设置方块。``entry`` 可以是 PaletteEntry，或 (name, props) 或 dict。

        返回 True 表示写入成功（y 越界返回 False）。
        """
        from .formats import PaletteEntry
        if isinstance(entry, PaletteEntry):
            name, props = entry.name, entry.properties
        elif isinstance(entry, (tuple, list)):
            name, props = entry[0], entry[1]
        elif isinstance(entry, dict):
            name, props = entry.get('Name', ''), entry.get('Properties', {}) or {}
        else:
            name, props = str(entry), {}
        if y < self.min_y or y >= self.min_y + self.height:
            return False
        sy = y >> 4
        pal, vals, sec = self._load(sy)
        key = (name, tuple(sorted((str(k), str(v)) for k, v in (props or {}).items())))
        idx = None
        for i, e in enumerate(pal):
            ek = (e.get('Name', ''), tuple(sorted((str(k), str(v))
                                                  for k, v in (e.get('Properties') or {}).items())))
            if ek == key:
                idx = i
                break
        if idx is None:
            pal.append({'Name': name, 'Properties': dict(props or {})})
            idx = len(pal) - 1
        vals[section_index(x, y & 15, z)] = idx
        self._dirty_sections.add(sy)
        return True

    def fill_all_air(self):
        """把整块区块设为空气（用于 from-scratch 写满一个区块）。"""
        for sy in range(self.min_y >> 4, ((self.min_y + self.height - 1) >> 4) + 1):
            _pal, vals, _sec = self._load(sy)
            for i in range(4096):
                vals[i] = 0
            self._dirty_sections.add(sy)

    # -------------------------------------------------- 方块的「实心」判定（高度图用）
    def _is_solid_for(self, x, y, z, key) -> bool:
        e = self.get_block(x, y, z)
        if e is None:
            return False
        name = str(e.get('Name', ''))
        if name.endswith(':air') or name in ('minecraft:air', 'minecraft:cave_air',
                                             'minecraft:void_air'):
            return False
        if key == 'WORLD_SURFACE':
            return True
        if key in ('MOTION_BLOCKING', 'MOTION_BLOCKING_NO_LEAVES'):
            fluid = name in ('minecraft:water', 'minecraft:lava')
            if key == 'MOTION_BLOCKING_NO_LEAVES' and ('leaves' in name):
                return False
            if fluid:
                return True
            return True
        if key == 'OCEAN_FLOOR':
            return name not in ('minecraft:water', 'minecraft:lava')
        return True

    # -------------------------------------------------- 落地
    def flush(self):
        for sy in self._dirty_sections:
            pal, vals, sec = self._palette_cache[sy]
            section_set_blocks(sec, pal, vals)
        dim = DIMENSIONS.get(self.dimension) or DIMENSIONS['overworld']
        pack_bits = max(1, (dim['height'] + 1).bit_length())
        vals = heightmap_values(self.chunk, self.dimension, self._is_solid_for)
        self.chunk.value['Heightmaps'] = new_heightmaps(pack_bits, dim['height'], vals)
        return self.chunk

    # -------------------------------------------------- 方块实体
    def set_block_entity(self, x: int, y: int, z: int, be: Tag):
        lst = cget(self.chunk, 'block_entities')
        if not isinstance(lst, Tag) or lst.type != 'list':
            lst = Tag.list_([], 'compound')
            self.chunk.value['block_entities'] = lst
        items = lst.value['items']
        if isinstance(be, Tag) and be.type == 'compound':
            be.value['x'] = Tag.int(x)
            be.value['y'] = Tag.int(y)
            be.value['z'] = Tag.int(z)
        for i, old in enumerate(items):
            if cget_int(old, 'x', -999999) == x and cget_int(old, 'y', -999999) == y \
                    and cget_int(old, 'z', -999999) == z:
                items[i] = be
                return
        items.append(be)

    def renumber(self, cx: int, cz: int, data_version: int = None):
        """修正区块自身的坐标字段，避免区块「放错格子」。"""
        self.chunk.value['xPos'] = Tag.int(cx)
        self.chunk.value['zPos'] = Tag.int(cz)
        if data_version:
            self.chunk.value['DataVersion'] = Tag.int(int(data_version))
        if cget(self.chunk, 'Status') is None:
            self.chunk.value['Status'] = Tag.string('minecraft:full')
        return self.chunk


# ---------------------------------------------------------------- 世界目录

def world_dir(instance_dir_path: str, dimension: str = 'overworld') -> str:
    dim = DIMENSIONS.get(dimension) or DIMENSIONS['overworld']
    primary = dim['dirs'][0]
    # 1.16+ 新布局：<world>/dimensions/minecraft/<name>
    if dimension != 'overworld':
        newp = os.path.join(instance_dir_path, 'world', 'dimensions', 'minecraft',
                            {'nether': 'the_nether', 'end': 'the_end'}.get(dimension, dimension))
        if os.path.isdir(os.path.join(newp, 'region')):
            return newp
    p = os.path.join(instance_dir_path, primary)
    if os.path.isdir(p):
        return p
    legacy = dim['dirs'][1] if len(dim['dirs']) > 1 else primary
    lp = os.path.join(instance_dir_path, 'world', legacy)
    if os.path.isdir(lp):
        return lp
    return os.path.join(instance_dir_path, primary)


def region_path(world_dir_path: str, dimension: str, block_x: int, block_z: int) -> str:
    rx, rz = region_of(block_x), region_of(block_z)
    if dimension == 'overworld':
        base = os.path.join(world_dir_path, 'region')
    else:
        dim = DIMENSIONS.get(dimension) or DIMENSIONS['overworld']
        newp = os.path.join(world_dir_path, 'dimensions', 'minecraft',
                            {'nether': 'the_nether', 'end': 'the_end'}.get(dimension, dimension),
                            'region')
        if os.path.isdir(os.path.dirname(newp)):
            base = newp
        else:
            base = os.path.join(world_dir_path, dim['dirs'][1], 'region')
    return os.path.join(base, f'r.{rx}.{rz}.mca')


def level_dat_data_version(world_root: str) -> int:
    """从 level.dat 读 DataVersion（取不到返回 0）。"""
    p = os.path.join(world_root, 'level.dat')
    if not os.path.isfile(p):
        return 0
    try:
        root, _ = nbtlib.parse_file(p)
        data = cget(root, 'Data')
        return cget_int(data, 'DataVersion', 0)
    except Exception:
        return 0


def read_block(world_dir_path: str, dimension: str, x: int, y: int, z: int):
    """读回世界坐标 (x,y,z) 的方块状态（自检用）。返回 dict 或 None。"""
    path = region_path(world_dir_path, dimension, x, z)
    if not os.path.isfile(path):
        return None
    cx, cz = chunk_of(x), chunk_of(z)
    lx, lz = local_in_chunk(x), local_in_chunk(z)
    with RegionFile(path) as rf:
        chunk = rf.read_chunk(cx, cz)
    if chunk is None:
        return None
    ed = ChunkEditor(chunk, dimension)
    return ed.get_block(lx, y, lz)


def read_block_entity(world_dir_path: str, dimension: str, x: int, y: int, z: int):
    path = region_path(world_dir_path, dimension, x, z)
    if not os.path.isfile(path):
        return None
    cx, cz = chunk_of(x), chunk_of(z)
    with RegionFile(path) as rf:
        chunk = rf.read_chunk(cx, cz)
    if chunk is None:
        return None
    for be in cget_list(chunk, 'block_entities', 'compound'):
        if cget_int(be, 'x', -1 << 30) == x and cget_int(be, 'y', -1 << 30) == y \
                and cget_int(be, 'z', -1 << 30) == z:
            return be
    return None
