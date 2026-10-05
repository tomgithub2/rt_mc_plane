# 功能规格：建筑导入（无需机器人进服）

> 本文由主线（上级 agent）编写，属于**核心设计**。子代理只做 UI / 契约 / 文案 / 图标等次要件，
> 修订本文须经主线同意。

## 1. 目标

用户在面板上传一个建筑文件（或包含多个建筑的 zip），填一个目标坐标，点一次「导入」，
建筑就出现在服务端世界的对应位置。

硬性约束（用户明确要求）：

- **不依赖任何玩家 / 机器人进服**：全程由面板 + 服务端自身完成，不需要开假人、不需要 OP 账号在线。
- **不破坏存档**：写入前必须自动备份受影响的区块文件，且提供一键回滚。
- **绝不半写**：任何前置条件不满足时明确拒绝并给出原因，不允许写一半留个残废存档。

## 2. 支持的格式

| 格式 | 说明 | 处理方式 |
|---|---|---|
| `.schem` | Sponge Schematic（v1 / v2 / v3），WorldEdit / FAWE 通用 | 引擎 A 直接吃；引擎 B 解析 |
| `.schematic` | MCEdit 老格式（gzip 的 NBT） | 同上 |
| `.nbt` | 原版结构方块导出的 structure | 引擎 B 原生（无 palette 版本差异问题） |
| `.litematic` | Litematica（可含多区域、每区域独立坐标） | 多区域时让用户选一个或全部 |
| `.mcstructure` | 基岩版 | **标记为需转换**，MVP 只做识别与提示 |
| `.zip` | 内含以上任一 / 或多建筑 | 批量导入（按清单选择要导入的成员） |

统一先做一次**解析与预检**（见 §5），把「能不能导、会覆盖什么、有多少方块映射不上」讲清楚再动手。

## 3. 两套执行引擎（自动择优）

### 引擎 A：原版 `/place template` + RCON（首选；实例运行中即可用）

> **本节的依据是实测，不是推测。** 原设计的「装 WorldEdit 用 `//paste`」路线**已被实测否掉**：
> Paper 1.21.4 + WorldEdit 7.4.6 / FAWE 2.15.4，0 玩家时经 RCON 下发 `//version` `//schem load` `//paste`
> 一律返回 `Unknown or incomplete command`（控制台未注册这些命令）；网传的
> `commands.allow-commands-in-console` 在 7.4.x 已不存在。机制上是 `//paste` 默认走
> `PlacementType.PLAYER`，要求 actor 是 `Locatable`，控制台必失败。
> 详见 `docs/RESEARCH-schematic-formats.md` §3。

**可行做法（实测通过：0 玩家、零插件、运行中）**：

```
# 1) 把结构放这里（目录名是 structures 复数；文件是 gzip 的 NBT）
<server>/<world>/generated/minecraft/structures/<name>.nbt
# 2) 模板只在服务端启动时扫描 → 需要重启一次实例（或先探活，报 "There is no template" 就提示重启并续做）
# 3) RCON 下发（不要带前导 /）：
forceload add <x1> <z1> <x2> <z2>
place template <name> <x> <y> <z> [rotation] [mirror] [integrity] [seed]
forceload remove <x1> <z1> <x2> <z2>
# 跨维度：execute in minecraft:the_nether run place template <name> <x> <y> <z>
```

实测证据：`list` 显示 0 玩家时执行 `place template test1 100 65 -200` →
`Loaded template "minecraft:test1" at 100, 65, -200`；随后用从零写的 Anvil 解析器直接读 region 文件确认
`(100,65,-200)=minecraft:stone`、`(100,66,-200)=minecraft:gold_block`、`(99,65,-200)=air`。

必须实现的语义（直接决定预检文案与用户预期）：

- `<pos>` 是**最小角**（占据 `[pos, pos+size-1]`）；
- **无条件覆盖**已有方块；想「只填空气」要在 `.nbt` 里把跳过的位置写成 `minecraft:structure_void`（放置时自动跳过）；
- `rotation` ∈ `none|clockwise_90|counterclockwise_90|180`；`mirror` ∈ `none|front_back|left_right`；`integrity` 0–1.0；`seed` Int；**`strict` 仅 1.21.5+，低版本会报错，禁止使用**；
- **只接受原版 `.nbt`** → 面板必须自己把 `.schem` / `.schematic` / `.litematic` 转成 `.nbt`；
- 目标区块**必须先 `forceload`**，否则 `That position is not loaded`；
- **实体不会被放置，方块实体会**（箱子内容、告示牌文字正常）；
- 待验证优化：数据包 `data/<ns>/structure/` + `/reload` 能否**免重启**加载模板（能省一次重启）。

### 引擎 A′：自研小插件（二期，仅当需要精细控制时）

若将来需要 `only_air` 精细放置、包含实体、生物群系、超大建筑性能优化，正解是**自研一个服务端插件**暴露 API，
而不是依赖 WorldEdit 的控制台命令（后者已被实测否掉）。MVP 不做。


### 引擎 B：离线写入 Anvil 区域文件（无插件依赖；**要求实例已停止**）

- 解析 schematic → 目标 MC 版本的**方块状态注册表**（从版本清单里的 reports 数据取，或随实例版本对齐）→ 直接读写 `world/region/r.X.Z.mca`、`DIM-1/region`、`DIM1/region`。
- 写入内容：区块 palette + `block_states`（含 `data` 位压缩）+ **方块实体 NBT**（箱子/告示牌/刷怪笼等）。
- 默认**不写**实体与生物群系（MVP 边界）；跨版本缺失方块 → 列出清单，用户可选「跳过 / 替换为同类 / 中止」。
- 安全：写入前备份被触及的 region 文件（复用备份模块的 tar.gz 与轮转逻辑）；支持 `dry-run` 只出报告不落盘。

### 引擎选择规则（面板自动判定，也允许手动指定）

| 实例状态 | 结构是否已就绪 | 选择 |
|---|---|---|
| 运行中 | `.nbt` 已放入 `structures/` 且已重启加载 | **引擎 A（`/place template`）** |
| 运行中 | 未就绪 | 提示「需重启一次实例以加载模板」，用户确认后由面板重启并续做 |
| 已停止 | 任意 | **引擎 B（离线 Anvil 写入）**，最快且不依赖游戏内命令 |
| 已停止 | 也可先起服走 A | 默认仍选 B；大建筑或需方块实体精细行为时可选 A |


## 4. 坐标与选项

- `origin`: `x, y, z`（整数；y 允许负值以支持地底）
- `dimension`: `overworld` | `nether` | `end`
- `rotate`: `0/90/180/270`；`mirror`: `none/x/z/xy`
- `place_mode`: `only_air`（只填空气，默认，最安全）| `replace_all` | `replace_list`（给出要替换的方块清单）
- `include_entities`: 默认关；`include_biome`: 默认关
- `batch`: 多文件按给定顺序与偏移依次导入
- **边界保护**：目标坐标 + 建筑尺寸算出的 bbox 若超出世界高度限制或跨维度 → 预检直接拒绝

## 5. 预检（导入前必须给用户看的报告）

`POST /api/instances/{iid}/build/preview` 返回：

```json
{
  "ok": true,
  "format": "schem",
  "size": {"x": 32, "y": 18, "z": 24},
  "blocks_total": 13824,
  "blocks_affected": 9216,
  "dimension": "overworld",
  "bbox": {"min": [100, 64, -200], "max": [131, 81, -177]},
  "palette_total": 47,
  "palette_unmapped": [{"name": "create:cogwheel", "count": 12}],
  "chunks_touched": 12,
  "engine_available": ["plugin", "offline"],
  "engine_recommended": "plugin",
  "warnings": ["目标区域内有 3 个玩家已建造的方块将被覆盖"],
  "requires_backup": true
}
```

## 6. 任务化与审计

- 导入是**异步任务**：状态 `parsing → mapping → writing(n/N) → done|failed|cancelled`，带进度与可取消。
- **写入前强制备份**（region 级），并在审计日志记录：谁、哪个实例、哪个文件（原名 + sha256）、坐标、维度、方块数、耗时、结果。
- 失败或用户反悔 → `POST .../build/rollback/{task_id}` 用备份还原；还原前再备份当前状态（可反复横跳）。

## 7. API 形状（草案，最终以 `API-CONTRACT.md` 合并为准）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/instances/{iid}/build/upload` | multipart 上传（`file` + `path`），返回 `upload_id` 与 sha256 |
| POST | `/api/instances/{iid}/build/preview` | `{upload_id, mc_version?, ...}` → §5 的报告 |
| POST | `/api/instances/{iid}/build/import` | `{upload_id, x,y,z, dimension, rotate, mirror, place_mode, replace_list, include_entities, engine, backup}` → `{ok, task_id}` |
| GET | `/api/instances/{iid}/build/tasks/{task_id}` | 进度与结果 |
| POST | `/api/instances/{iid}/build/tasks/{task_id}/cancel` | 取消（写入中允许在区块边界安全停止） |
| POST | `/api/instances/{iid}/build/rollback/{task_id}` | 回滚 |
| GET | `/api/build/formats` | 支持格式、体积上限、注意事项 |

## 8. 安全与健壮性要求

1. 上传与解压都过 `pathguard`（`realpath` + `commonpath`，含 `normcase` 归一）；
2. **zip 炸弹防护**：成员数上限、单成员与总解压体积上限、禁止绝对路径与 `..` 成员（zip-slip）、拒绝符号链接成员；
3. NBT 解析深度与数组长度上限，防恶意文件打爆内存；
4. 解析在**独立进程/线程 + 超时**中执行，面板主线程不被大文件卡死；
5. 单实例同时只允许一个导入任务（排队而不是并发写同一批区块）；
6. 所有涉及世界的写操作在审计日志里为 `level=warn` 以上。

## 9. 验收标准（我会亲自跑）

1. 用 `.schem`（WorldEdit 导出的真实建筑）在**已停止**的实例上走引擎 B：导入 → 启动服务端 → 用日志/区块读取确认目标坐标处方块真的变了；
2. 用同一建筑走引擎 A：实例运行中装 WorldEdit → RCON `//schem load` + `//paste` → 无机器人进服，确认生效；
3. 故意给越界坐标 / 超高建筑 / 未映射方块 → 预检必须给出明确拒绝或清单，不得写入；
4. 回滚：导入后一键恢复，region 文件与导入前**哈希一致**；
5. 恶意样本：zip-slip、超大解压、深层 NBT → 全部被拒且面板进程存活。
