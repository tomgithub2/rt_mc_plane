#!/usr/bin/env python
"""生成自检用的建筑样本（**手工构造**，不下载任何真实建筑）。

样本：5(X) × 3(Y) × 4(Z) 的小屋
  y=0  石头地板 5×4
  y=1  石砖围一圈（空心），内部 2 格放：
        · 朝向楼梯 oak_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]
        · 装物品的箱子 chest[facing=north,type=single,waterlogged=false]（含 2 组物品）
        · 告示牌 oak_sign[rotation=8]（front_text 一行文字）
  y=2  玻璃屋顶 5×4 中的 3×2

支持写出：``.schem``（Sponge v3 / v2 / v1）、``.schematic``（MCEdit）、``.nbt``（原版结构）、
``.litematic``（含负 Size 区域）、``.zip``（把若干样本打包），以及若干**恶意样本**。

用法::

    PYTHONUTF8=1 python tools/build_make_sample.py <out_dir> [--all]
    PYTHONUTF8=1 python tools/build_make_sample.py <out_dir> --malicious
"""
import argparse
import io
import json
import os
import struct
import sys
import zipfile

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]

from app.build import nbt as N  # noqa: E402
from app.build.formats import PaletteEntry, bits_for_palette, unpack_tight  # noqa: E402
from app.build.nbt import Tag, compress  # noqa: E402

W, H, L = 5, 3, 4                       # X, Y, Z
SIZE = (W, H, L)


# ---------------------------------------------------------------- 样本内容

def sample_blocks():
    """返回 ``[(x,y,z, PaletteEntry, be_nbt|None)]``。"""
    blocks = []
    stone = PaletteEntry('minecraft:stone')
    brick = PaletteEntry('minecraft:stone_bricks')
    glass = PaletteEntry('minecraft:glass')
    stair = PaletteEntry('minecraft:oak_stairs',
                         {'facing': 'east', 'half': 'bottom', 'shape': 'straight',
                          'waterlogged': 'false'})
    chest = PaletteEntry('minecraft:chest',
                         {'facing': 'north', 'type': 'single', 'waterlogged': 'false'})
    sign = PaletteEntry('minecraft:oak_sign', {'rotation': '8', 'waterlogged': 'false'})

    # y=0 地板
    for x in range(W):
        for z in range(L):
            blocks.append((x, 0, z, stone, None))
    # y=1 围墙（空心）
    for x in range(W):
        for z in range(L):
            if x in (0, W - 1) or z in (0, L - 1):
                blocks.append((x, 1, z, brick, None))
    # 内部：楼梯 / 箱子 / 告示牌
    blocks.append((1, 1, 2, stair, None))
    chest_nbt = Tag.compound({
        'id': Tag.string('minecraft:chest'),
        'x': Tag.int(3), 'y': Tag.int(1), 'z': Tag.int(2),
        'Items': Tag.list_([
            Tag.compound({'Slot': Tag.byte(0), 'id': Tag.string('minecraft:diamond'),
                          'count': Tag.int(12)}),
            Tag.compound({'Slot': Tag.byte(1), 'id': Tag.string('minecraft:golden_apple'),
                          'count': Tag.int(3)}),
        ], 'compound'),
    })
    blocks.append((3, 1, 2, chest, chest_nbt))
    sign_nbt = Tag.compound({
        'id': Tag.string('minecraft:sign'),
        'x': Tag.int(1), 'y': Tag.int(1), 'z': Tag.int(1),
        'is_waxed': Tag.byte(0),
        'front_text': Tag.compound({
            'has_glowing_text': Tag.byte(0),
            'color': Tag.string('black'),
            'messages': Tag.list_([Tag.string('{"text":"mcpanel 测试告示牌"}'),
                                   Tag.string('{"text":""}'),
                                   Tag.string('{"text":""}'),
                                   Tag.string('{"text":""}')], 'string'),
        }),
        'back_text': Tag.compound({
            'has_glowing_text': Tag.byte(0),
            'color': Tag.string('black'),
            'messages': Tag.list_([Tag.string('{"text":""}')] * 4, 'string'),
        }),
    })
    blocks.append((1, 1, 1, sign, sign_nbt))
    # y=2 玻璃屋顶（3×2）
    for x in range(1, 4):
        for z in range(1, 3):
            blocks.append((x, 2, z, glass, None))
    return blocks


def palette_of(blocks):
    pal = []
    idx = {}
    for (_x, _y, _z, entry, _nbt) in blocks:
        key = entry.state_string()
        if key not in idx:
            idx[key] = len(pal)
            pal.append(entry)
    return pal, idx


# ---------------------------------------------------------------- 写出器

def write_vanilla_nbt(path, blocks=None, size=SIZE):
    """原版结构文件。

    注意：``size`` / ``pos`` 必须是 **TAG_List of TAG_Int** —— 实测写成 TAG_Int_Array 时
    1.21.4 服务端的 ``/place template`` 会把模板解析成空并返回 ``Failed to place template``。
    """
    blocks = blocks if blocks is not None else sample_blocks()
    pal, idx = palette_of(blocks)
    out = []
    for (x, y, z, entry, nbt_) in blocks:
        d = {'pos': Tag.list_([Tag.int(x), Tag.int(y), Tag.int(z)], 'int'),
             'state': Tag.int(idx[entry.state_string()])}
        if nbt_ is not None:
            d['nbt'] = Tag.compound(dict(nbt_.value))
        out.append(Tag.compound(d))
    root = Tag.compound({
        'DataVersion': Tag.int(4189),
        'size': Tag.list_([Tag.int(v) for v in size], 'int'),
        'palette': Tag.list_([e.to_nbt() for e in pal], 'compound'),
        'blocks': Tag.list_(out, 'compound'),
        'entities': Tag.list_([], 'compound'),
    })
    with open(path, 'wb') as f:
        f.write(compress(N.write(root), 'gzip'))
    return {'format': 'nbt', 'path': path, 'size': list(size), 'palette': len(pal),
            'blocks': len(blocks)}


def _varint_bytes(values):
    out = bytearray()
    for v in values:
        v = int(v)
        while True:
            b = v & 0x7F
            v >>= 7
            if v:
                out.append(b | 0x80)
            else:
                out.append(b)
                break
    return bytes(out)


def write_sponge(path, version=3, blocks=None, size=SIZE):
    """Sponge v3（Schematic 包裹 + BlockPalette）或 v1/v2（扁平 + Palette）。"""
    blocks = blocks if blocks is not None else sample_blocks()
    pal, idx = palette_of(blocks)
    w, h, l = size
    data = [0] * (w * h * l)
    for (x, y, z, entry, _nbt) in blocks:
        data[x + z * w + y * w * l] = idx[entry.state_string()]
    varints = _varint_bytes(data)
    if version == 3:
        pal_nbt = {}
        for entry in pal:
            pal_nbt[entry.state_string()] = Tag.int(idx[entry.state_string()])
        bes = []
        for (x, y, z, entry, nbt_) in blocks:
            if nbt_ is None:
                continue
            d = Tag.compound(dict(nbt_.value))
            d.value['Pos'] = Tag.int_array([x, y, z])
            d.value['Id'] = Tag.string(str(N.cget_str(d, 'id', 'minecraft:chest')))
            bes.append(d)
        container = Tag.compound({
            'Palette': Tag.compound(pal_nbt),
            'Data': Tag.byte_array(varints),
            'BlockEntities': Tag.list_(bes, 'compound'),
        })
        root = Tag.compound({
            'Schematic': Tag.compound({
                'Version': Tag.int(3),
                'DataVersion': Tag.int(4189),
                'Width': Tag.short(w), 'Height': Tag.short(h), 'Length': Tag.short(l),
                'Offset': Tag.int_array([0, 0, 0]),
                'Blocks': container,
                'Metadata': Tag.compound({'Name': Tag.string('mcpanel sample'),
                                          'Author': Tag.string('mc-server-panel')}),
            }),
            'Version': Tag.int(3),
            'DataVersion': Tag.int(4189),
        })
    else:
        pal_nbt = {}
        for entry in pal:
            pal_nbt[entry.state_string()] = Tag.int(idx[entry.state_string()])
        bes = []
        for (x, y, z, entry, nbt_) in blocks:
            if nbt_ is None:
                continue
            d = Tag.compound(dict(nbt_.value))
            d.value['Pos'] = Tag.int_array([x, y, z])
            d.value['Id'] = Tag.string(str(N.cget_str(d, 'id', 'minecraft:chest')))
            bes.append(d)
        root = Tag.compound({
            'Version': Tag.int(version),
            'DataVersion': Tag.int(version == 2 and 2586 or 1343),
            'Width': Tag.short(w), 'Height': Tag.short(h), 'Length': Tag.short(l),
            'Offset': Tag.int_array([0, 0, 0]),
            'Palette': Tag.compound(pal_nbt),
            'PaletteMax': Tag.int(len(pal)),
            'BlockData': Tag.byte_array(varints),
            'BlockEntities': Tag.list_(bes, 'compound'),
            'Entities': Tag.list_([], 'compound'),
        })
    with open(path, 'wb') as f:
        f.write(compress(N.write(root), 'gzip'))
    return {'format': f'schem-v{version}', 'path': path, 'size': list(size),
            'palette': len(pal), 'blocks': len(blocks)}


def write_mcedit(path, blocks=None, size=SIZE):
    """MCEdit .schematic：YZX 索引，Blocks/Metadata/AddBlocks（数字 id）。

    这里故意用**旧版数字 id**：石头=1、玻璃=20、石砖=98、箱子=54、木楼梯=53(meta 决定朝向)。
    """
    w, h, l = size
    total = w * h * l
    ids = bytearray(total)
    metas = bytearray(total)
    world = [None] * total
    legacy = {
        'minecraft:stone': (1, 0),
        'minecraft:glass': (20, 0),
        'minecraft:stone_bricks': (98, 0),
        'minecraft:chest': (54, 2),          # meta&3=2 → facing north（旧版语义）
        'minecraft:oak_sign': (63, 8),       # 8*22 = 176° → rotation=8（旧版 16 档制）
        'minecraft:oak_stairs': (53, 0),     # meta&3=0 → facing east（旧版语义）
    }
    if blocks is None:
        blocks = sample_blocks()
    for (x, y, z, entry, _nbt) in blocks:
        i = (y * l + z) * w + x
        bid, meta = legacy.get(entry.name, (1, 0))
        ids[i] = bid & 0xFF
        metas[i] = meta & 0x0F
        world[i] = (x, y, z)
    te = []
    for (x, y, z, entry, nbt_) in blocks:
        if entry.name == 'minecraft:chest':
            te.append(Tag.compound({
                'id': Tag.string('Chest'),
                'Pos': Tag.int_array([x, y, z]),
                'Items': Tag.list_([
                    Tag.compound({'Slot': Tag.byte(0), 'id': Tag.string('minecraft:diamond'),
                                  'Count': Tag.byte(12), 'Damage': Tag.short(0)}),
                ], 'compound'),
            }))
        elif entry.name == 'minecraft:oak_sign':
            te.append(Tag.compound({
                'id': Tag.string('Sign'),
                'Pos': Tag.int_array([x, y, z]),
                'Text1': Tag.string('{"text":"mcpanel"}'),
                'Text2': Tag.string('{"text":"legacy"}'),
                'Text3': Tag.string(''), 'Text4': Tag.string(''),
            }))
    root = Tag.compound({
        'Width': Tag.short(w), 'Height': Tag.short(h), 'Length': Tag.short(l),
        'Materials': Tag.string('Alpha'),
        'Blocks': Tag.byte_array(bytes(ids)),
        'Data': Tag.byte_array(bytes(metas)),
        'AddBlocks': Tag.byte_array(bytes(total // 2)),
        'Entities': Tag.list_([], 'compound'),
        'TileEntities': Tag.list_(te, 'compound'),
    })
    with open(path, 'wb') as f:
        f.write(compress(N.write(root), 'gzip'))
    return {'format': 'schematic', 'path': path, 'size': list(size), 'palette': 6,
            'blocks': len(blocks)}


def write_litematic(path, blocks=None, size=SIZE, negative_size=False):
    """Litematica：tight 位打包（条目可跨 long 边界），可选负 Size。"""
    blocks = blocks if blocks is not None else sample_blocks()
    pal, idx = palette_of(blocks)
    w, h, l = size
    volume = w * h * l
    values = [0] * volume
    for (x, y, z, entry, _nbt) in blocks:
        values[(y * l + z) * w + x] = idx[entry.state_string()]
    bits = bits_for_palette(len(pal))
    need = (volume * bits + 63) // 64
    longs = [0] * need
    for i, v in enumerate(values):
        start = i * bits
        li = start >> 6
        off = start & 0x3F
        longs[li] |= (v & ((1 << bits) - 1)) << off
        if off + bits > 64:
            longs[li + 1] |= (v & ((1 << bits) - 1)) >> (64 - off)
    signed = [x - (1 << 64) if x >= (1 << 63) else x for x in longs]
    te = []
    for (x, y, z, entry, nbt_) in blocks:
        if nbt_ is None:
            continue
        d = Tag.compound({k: v for k, v in nbt_.value.items() if k not in ('x', 'y', 'z')})
        d.value['Pos'] = Tag.int_array([x, y, z])
        te.append(d)
    sz = [w, h, l]
    if negative_size:
        sz[0] = -w
    region = Tag.compound({
        'Position': Tag.int_array([0, 0, 0]),
        'Size': Tag.int_array(sz),
        'BlockStatePalette': Tag.list_([e.to_nbt() for e in pal], 'compound'),
        'BlockStates': Tag.long_array(signed),
        'TileEntities': Tag.list_(te, 'compound'),
        'Entities': Tag.list_([], 'compound'),
        'PendingBlockTicks': Tag.list_([], 'compound'),
        'PendingFluidTicks': Tag.list_([], 'compound'),
    })
    root = Tag.compound({
        'Version': Tag.int(6),
        'MinecraftDataVersion': Tag.int(4189),
        'Metadata': Tag.compound({
            'Name': Tag.string('mcpanel-sample'),
            'Author': Tag.string('mc-server-panel'),
            'Description': Tag.string('自检样本'),
            'EnclosingSize': Tag.compound({'x': Tag.int(w), 'y': Tag.int(h), 'z': Tag.int(l)}),
            'RegionCount': Tag.int(1),
            'TotalBlocks': Tag.int(len(blocks)),
            'TotalVolume': Tag.int(volume),
            'TimeCreated': Tag.long(0), 'TimeModified': Tag.long(0),
            'Software': Tag.string('mc-server-panel'),
        }),
        'Regions': Tag.compound({'main': region}),
    })
    with open(path, 'wb') as f:
        f.write(compress(N.write(root), 'gzip'))
    return {'format': 'litematic', 'path': path, 'size': list(size), 'palette': len(pal),
            'blocks': len(blocks), 'bits': bits, 'longs': need}


# ---------------------------------------------------------------- 恶意样本

def write_malicious(out_dir):
    """生成安全自检用的恶意样本（zip-slip / zip 炸弹 / 深层 NBT / 超大数组）。"""
    os.makedirs(out_dir, exist_ok=True)
    out = []

    # 1) zip-slip：成员名含 ../
    p = os.path.join(out_dir, 'evil_zipslip.zip')
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('../../evil.schem', b'x' * 32)
        z.writestr('ok.schem', b'y' * 32)
    out.append(('zip-slip（成员 ../../evil.schem）', p))

    # 2) 绝对路径成员
    p = os.path.join(out_dir, 'evil_absolute.zip')
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('/etc/evil.schem', b'x' * 32)
    out.append(('绝对路径成员（/etc/evil.schem）', p))

    # 3) 符号链接成员
    p = os.path.join(out_dir, 'evil_symlink.zip')
    zi = zipfile.ZipInfo('link.schem')
    zi.external_attr = (0xA1FF << 16)          # S_IFLNK | 0777
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr(zi, '/etc/passwd')
    out.append(('符号链接成员（link.schem → /etc/passwd）', p))

    # 4) zip 炸弹：高压缩比的大成员
    p = os.path.join(out_dir, 'evil_bomb.zip')
    with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('bomb.schem', b'\x00' * (300 * 1024 * 1024))
    out.append(('zip 炸弹（单成员解压 300MB）', p))

    # 5) 成员数爆炸
    p = os.path.join(out_dir, 'evil_many.zip')
    with zipfile.ZipFile(p, 'w') as z:
        for i in range(600):
            z.writestr(f'm{i}.schem', b'x')
    out.append(('成员数 600（上限 512）', p))

    # 6) 深层 NBT（嵌套 200 层 compound）—— 手工拼字节，否则被我们自己的写入器挡住
    p = os.path.join(out_dir, 'evil_deep.nbt')
    raw = bytearray(b'\x0a\x00\x00')
    for _ in range(200):
        raw += b'\x0a' + struct.pack('>H', 1) + b'a'
    raw += b'\x00' * 201
    with open(p, 'wb') as f:
        f.write(compress(bytes(raw), 'gzip'))
    out.append(('深层 NBT（200 层 compound）', p))

    # 7) 超大数组（long 数组声明 2^26 个元素但没有数据）
    p = os.path.join(out_dir, 'evil_bigarray.nbt')
    raw = bytearray()
    raw += b'\x0a\x00\x00'                     # compound, name ''
    raw += b'\x0c' + struct.pack('>H', 3) + b'arr' + struct.pack('>i', 1 << 26)
    raw += b'\x00'
    with open(p, 'wb') as f:
        f.write(compress(bytes(raw), 'gzip'))
    out.append(('超大 long 数组（声明 2^26 元素）', p))

    # 8) 声明超大解压体积的 gzip 炸弹
    p = os.path.join(out_dir, 'evil_gzip_bomb.nbt')
    with open(p, 'wb') as f:
        f.write(compress(b'\x00' * (600 * 1024 * 1024), 'gzip'))
    out.append(('gzip 炸弹（解压 600MB）', p))

    # 9) 越界坐标 / 超高建筑的合法文件（用预检拒绝，不是解析拒绝）
    p = os.path.join(out_dir, 'sample_for_out_of_range.nbt')
    write_vanilla_nbt(p, size=(5, 400, 4),
                      blocks=[(x, y, z, PaletteEntry('minecraft:stone'), None)
                              for x in range(5) for z in range(4) for y in range(400)])
    out.append(('超高建筑（Y 400 层）', p))

    # 10) 含未映射方块（跨版本不存在的 mod 方块）
    p = os.path.join(out_dir, 'sample_unmapped.nbt')
    blocks = sample_blocks() + [(4, 1, 3, PaletteEntry('create:cogwheel'), None),
                                (0, 1, 3, PaletteEntry('minecraft:not_a_real_block'), None)]
    write_vanilla_nbt(p, blocks=blocks)
    out.append(('含未映射方块（create:cogwheel / not_a_real_block）', p))
    return out


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description='生成建筑导入自检样本')
    ap.add_argument('out_dir', help='输出目录')
    ap.add_argument('--all', action='store_true', help='生成全部格式')
    ap.add_argument('--malicious', action='store_true', help='生成恶意样本')
    ap.add_argument('--zip', action='store_true', help='额外打包一个 zip')
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    results = []
    if args.malicious:
        for label, p in write_malicious(args.out_dir):
            print(f'[恶意样本] {label} → {p}')
        return 0
    blocks = sample_blocks()
    results.append(write_sponge(os.path.join(args.out_dir, 'sample_v3.schem'), 3, blocks))
    results.append(write_sponge(os.path.join(args.out_dir, 'sample_v2.schem'), 2, blocks))
    results.append(write_sponge(os.path.join(args.out_dir, 'sample_v1.schem'), 1, blocks))
    results.append(write_mcedit(os.path.join(args.out_dir, 'sample.schematic'), blocks))
    results.append(write_vanilla_nbt(os.path.join(args.out_dir, 'sample.nbt'), blocks))
    results.append(write_litematic(os.path.join(args.out_dir, 'sample.litematic'), blocks))
    results.append(write_litematic(os.path.join(args.out_dir, 'sample_negsize.litematic'),
                                   blocks, negative_size=True))
    if args.zip or args.all:
        zp = os.path.join(args.out_dir, 'samples.zip')
        with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
            for r in results:
                z.write(r['path'], os.path.basename(r['path']))
        results.append({'format': 'zip', 'path': zp, 'size': list(SIZE),
                        'palette': '-', 'blocks': '-'})
    for r in results:
        print('[样本] %-14s %s  size=%s palette=%s blocks=%s'
              % (r['format'], r['path'], r.get('size'), r.get('palette'), r.get('blocks')))
    with io.open(os.path.join(args.out_dir, 'samples.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print('共 %d 个样本 → %s' % (len(results), args.out_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
