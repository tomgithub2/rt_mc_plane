# API 契约 · 前端需求部分（由前端侧起草）

> 本文件是**前后端对齐的唯一依据**。第 1 节由前端（次要件负责人）维护：
> 写清"每个页面需要什么接口、什么字段、什么语义"。
> 第 2 节由核心负责人填写/确认最终形状；若与第 1 节不一致，以第 2 节为准并回改第 1 节的消费代码。
>
> 状态说明：`[需确认]` = 前端已按此实现，等待核心确认；`[已确认]` = 双方对齐；`[变更]` = 核心已改，前端需适配。

---

## 0. 通用约定（前端假定）

| 项 | 约定 |
|---|---|
| 基址 | 同源 `/api/**`，无版本前缀 |
| 鉴权 | `Authorization: Bearer <token>`；WebSocket 与下载直链额外支持 `?token=<token>` |
| 未登录 | **任何** `/api/**` 未带有效令牌必须返回 `401`，响应体 `{"detail": "..."}` |
| 越权/路径越界 | `403`，响应体 `{"detail": "..."}` |
| 参数校验失败 | `422`，前端只展示 `detail` 的字符串形式 |
| 其它错误 | 4xx/5xx，前端把 `detail` 原样显示给用户（要求是**中文人话**，不要堆栈） |
| 时间 | 所有时间戳为 **Unix 秒（float）**；前端自己格式化为 `HH:MM:SS` / `YYYY-MM-DD HH:MM:SS` |
| 大小 | 字节数（int） |
| 分页 | 列表接口用 `limit` / `offset`（query），返回体里带 `total`（可选） |
| 列表包装 | 一律 `{"ok": true, "<名字>": [...]}`，前端只读该字段 |
| 布尔 | 实例上的布尔字段（`auto_restart`/`nogui`/`rcon_enabled`）后端可能返回 `0/1`，前端按真值判断 |

**前端已有的错误处理**：`api.js` 里 401 → 清 token 并跳 `#/login`；其它非 2xx → `throw new Error(detail)` 并弹 toast。

---

## 1. 页面 → 接口与字段（前端需求）

### 1.1 登录页 `#/login`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/health` | 免鉴权。`{ok, version, service}` —— 登录页只展示 `version` 文案 |
| POST | `/api/auth/login` | body `{username, password}` → `{ok, token, expires_at, user:{id,username,role}}`。失败 401（提示文案里前端原样显示 `detail`）；失败次数过多 429 |

### 1.2 应用外壳（每个已登录页面都会调）

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/auth/me` | `{ok, user:{id,username,role,last_login}}`。刷新页面后前端靠它恢复用户名 |
| POST | `/api/auth/logout` | `{ok:true}`；令牌立即失效 |
| POST | `/api/auth/password` | body `{old_password,new_password}` → `{ok, note}`；成功后前端跳登录页 |

### 1.3 实例列表 `#/instances`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/instances` | `{ok, instances:[Instance]}` |

**`Instance` 对象——前端读取的字段（缺一不可）：**

```
id:int, name:str, core_type:str, core_label:str(可读中文名), mc_version:str, port:int,
memory_mb:int, dir:str, dir_size:int,
status:'running'|'stopped'|'starting'|'stopping'|'crashed',
running:bool, pid:int, uptime:int(秒), uptime_text:str,
cpu:float(%), mem_mb:float, players:int, max_players:int,
tps:float|null, tps_available:bool,          # tps_available=false 时前端显示"不可用"，不显示 0
auto_restart:bool, jar_path:str, exit_code:int|null, note:str
```

生命周期（列表页与详情页共用）：

| 方法 | 路径 | 需要返回 |
|---|---|---|
| POST | `/api/instances/{iid}/start` | `{ok, pid}`；失败 400 + 中文原因（如"服务端 jar 不存在"） |
| POST | `/api/instances/{iid}/stop` | `{ok, graceful:bool, note?}`；`graceful:false` 表示走了强制结束 |
| POST | `/api/instances/{iid}/restart` | `{ok}` |
| POST | `/api/instances/{iid}/kill` | `{ok}` |
| GET | `/api/instances/{iid}/status` | `{ok, status, running, pid, uptime, uptime_text, cpu, mem_mb, players, max_players, tps, tps_available, mspt, online_names:[str]}` |

**批量操作（多服务器管理）**：`POST /api/instances-batch` body `{action:'start'|'stop'|'restart'|'kill', ids:[int], confirm:bool}` → `{ok, success:int, total:int, results:[{id,name,ok,error}]}`

### 1.4 新建实例向导 `#/create`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/cores` | `{ok, sources:[{id,label}]}`，`id ∈ {vanilla,paper,purpur,fabric,quilt,forge,neoforge}` |
| GET | `/api/cores/{source}/versions` | `{ok, versions:[{id,type:'release'|'snapshot'|'rc'|'other',released:str}], count, error?}`。**源不可达时 `ok:false` + `error`（中文），前端会显示"源不可达"并引导改用其它核心或本地上传** |
| GET | `/api/cores/{source}/builds?mc=<ver>` | `{ok, builds:[{id,channel?,time?}]}`（仅 paper/forge/neoforge 有意义，其它源返回空数组即可） |
| GET | `/api/java` | `{ok, detected:[{ok,major,version_line,path,source:'system'|'panel'}], installed:[...], java_dir}` |
| POST | `/api/java/test` | body `{path}` → `{ok, major?, version_line?, error?}` |
| POST | `/api/java/install` | body `{major:int, image:'jre'|'jdk'}` → `{ok, path, major, dir, version_line}`；**失败 502 + `detail`=中文原因（如"Adoptium 不可达"）** |
| POST | `/api/instances` | body `{name, core_type, mc_version, core_version, memory_mb, port, java_path, auto_restart, accept_eula, download, rcon_enabled, rcon_port}` → `{ok, id, instance:Instance, download?:{ok, task_id?, filename?, kind?:'server'|'installer', note?, error?, dest?}}` |
| GET | `/api/downloads/{tid}` | `{ok, id, label, url, total, done, percent, speed, status:'pending'|'downloading'|'done'|'failed', error, dest}` —— 向导用它轮询进度条 |

> `download.ok=false` 时前端显示 `error` 并提示"可改用本地上传 jar"，**不视为创建失败**。

### 1.5 实例详情 · 控制台 `#/instances/{id}/console`

| 类型 | 路径 | 约定 |
|---|---|---|
| WS | `/api/instances/{id}/console/ws?token=<t>` | 未认证直接关闭（前端按"未登录"处理）。**下行消息**：`{type:'hello', instance, id, status:Status, history:[LogLine]}`、`{type:'log', ts, line, level:'info'|'warn'|'error'|'input'|'panel', stream}`、`{type:'status', status:Status}`、`{type:'ack', ok, error, cmd}`、`{type:'pong', ts}`。**上行消息**：`{type:'cmd', data:'<命令>'}`、`{type:'ping'}`、`{type:'status'}` |
| GET | `/api/instances/{id}/log?lines=N` | `{ok, lines:[LogLine], status:Status}` |
| GET | `/api/instances/{id}/log/download` | 纯文本附件（`latest.log`） |
| GET | `/api/instances/{id}/metrics?hours=1` | `{ok, hours, points:[{ts,cpu,mem_mb,players,tps,mspt}], tps_available:bool, tps_note:str, summary:{...}}` |
| POST | `/api/instances/{id}/command` | body `{command}` → `{ok}`；实例未运行 400 |
| GET | `/api/instances/{id}/rcon/test` | `{ok, result, error}` —— 前端据此显示 RCON 可用/不可用 |
| POST | `/api/instances/{id}/rcon` | body `{command}` → `{ok, result}`；不可用 502 + 原因 |

**`LogLine`**：`{ts:float, line:str, level:'info'|'warn'|'error'|'input'|'panel', stream:'stdout'|'stderr'|'tail'}`

> 前端对 `level` 分色：`info` 常规、`warn` 黄、`error` 红、`input` 绿（命令回显）、`panel` 金（面板自身消息）。**ANSI 转义前端自己剥**，但**历史日志（latest.log）要求保留原始 ANSI 字节**，前端可按需开关。

### 1.6 详情 · 文件 `#/instances/{id}/files`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/instances/{iid}/files?path=<rel>` | `{ok, path:str(相对), abs:str, parent:str\|null, items:[{name,dir,size,mtime,symlink,editable}]}` |
| GET | `/api/instances/{iid}/files/read?path=` | `{ok, path, size, content, encoding:'utf-8'}`；>4MB 用 413 |
| PUT | `/api/instances/{iid}/files/write` | body `{path, content}` → `{ok, size}` |
| POST | `/api/instances/{iid}/files/mkdir` | body `{path}` → `{ok, path}` |
| POST | `/api/instances/{iid}/files/rename` | body `{path, new_name}` → `{ok, path}` |
| POST | `/api/instances/{iid}/files/delete` | body `{path}` → `{ok}` |
| POST | `/api/instances/{iid}/files/unzip` | body `{path, target?}` → `{ok, extracted:int, dest}` |
| POST | `/api/instances/{iid}/files/upload` | multipart：字段 `file` + 表单字段 `path`(目标相对目录) → `{ok, path, size}` |
| GET | `/api/instances/{iid}/files/download?path=` | 附件流 |

**安全红线（前端已按此写测试断言）**：`../../../windows/win.ini`、`/etc/passwd`、`C:\Windows\win.ini`、
`....//....//`、URL 编码的 `..%2f`、以及**指向实例目录外的符号链接**，都必须 `403`（不能 404、不能 200）。

### 1.7 详情 · 配置 `#/instances/{id}/config`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/instances/{iid}/config/properties` | `{ok, exists:bool, path, rows:[PropRow], props:obj, missing:[{key,label,type,desc}], schema:[...]}` |
| PUT | `/api/instances/{iid}/config/properties` | body `{updates:{key:value}}` → `{ok, written, path}`；校验失败 400 + 中文原因。**必须保留注释/空行/未知键/键顺序** |
| GET/POST | `/api/instances/{iid}/config/eula` | GET `{ok, exists, accepted, raw?}`；POST 一键写入 `eula=true` |
| GET | `/api/instances/{iid}/config/startup` | `{ok, memory_mb, extra_jvm_args, extra_server_args, nogui, java_path, auto_restart, rcon_enabled, rcon_port, has_rcon_password, jar_path, command_preview}` |
| PUT | `/api/instances/{iid}/config/startup` | 同名 body 子集 → `{ok, changed:[...], command_preview}` |
| GET | `/api/instances/{iid}/jars` | `{ok, jars:[{path,rel,size,mtime}], current}` |
| POST | `/api/instances/{iid}/jar` | body `{jar_path}` → `{ok, jar_path}`；目录外路径 403 |
| POST | `/api/instances/{iid}/run-installer` | Forge/NeoForge 安装器 → `{ok, exit_code, scripts:[str], args:[str], error, output:[str]}` |
| POST | `/api/instances/{iid}/install-core` | body `{source, mc_version, build}` → `{ok, task_id, filename, dest, kind, note, installer:bool}` |

**`PropRow`**：`{i:int, kind:'pair'|'comment'|'blank', key?, value?, label?, type?, desc?, known?, raw?}`
`type` 取值：`text` / `int` / `bool` / `enum:a,b,c`（前端据此渲染输入控件）。

### 1.8 详情 · 玩家 `#/instances/{id}/players`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/instances/{iid}/players` | `{ok, whitelist:[], ops:[], banned_players:[], banned_ips:[], online_text:str, online_source:'rcon'|'log'|'unavailable', online_names:[], online_count:int, running:bool, files:{whitelist:path,...}}` |
| POST | `/api/instances/{iid}/players/add` | body `{which:'whitelist'|'ops'|'banned-players'|'banned-ips', name, uuid?, level?, reason?, ip?}` → `{ok, entry}` |
| POST | `/api/instances/{iid}/players/remove` | body `{which, name}` → `{ok, removed:int}` |
| POST | `/api/instances/{iid}/players/op` \| `/deop` \| `/kick` \| `/ban` \| `/pardon` | body `{name, reason?}` → `{ok, note?, result?}`；**`note` 用中文说明"仅写文件，重启生效"或"RCON 已生效"/"RCON 不可用"** |
| GET | `/api/instances/{iid}/players/rcon` | `{ok, result, error}` |

### 1.9 详情 · 插件/模组（前端 Tab 待接）

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/instances/{iid}/plugins` | `{ok, items:[{dir,name,size,mtime,enabled,kind}], target_dir, loader}` |
| POST | `/api/instances/{iid}/plugins/toggle` | body `{dir,name,enable}` → `{ok}` |
| POST | `/api/instances/{iid}/plugins/delete` | body `{dir,name}` → `{ok}` |
| POST | `/api/instances/{iid}/plugins/upload` | multipart `file` + `dir` |
| GET | `/api/instances/{iid}/plugins/search?source=&query=&mc_version=&mod_type=` | `{ok, source, hits:[...], total?, error?}` |
| GET | `/api/instances/{iid}/plugins/versions?project=&source=` | `{ok, versions:[{id,name,version_number,filename,url,size,sha1,game_versions,loaders}]}` |
| POST | `/api/instances/{iid}/plugins/install` | body `{source, project?, version_id?, url?, filename?, sha1?}` → `{ok, task_id?, file, dir?, note?, dest?}` |
| GET | `/api/plugins-probe` | `{ok, results:[{source,ok,error}]}` —— 设置页实测三源可达性 |

### 1.10 详情 · 备份 `#/instances/{id}/backups`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/instances/{iid}/backups` | `{ok, backups:[{id,instance_id,file,name,size,created_at,kind:'manual'|'cron'|'pre-restore',note,exists:bool}]}` |
| POST | `/api/instances/{iid}/backups` | body `{note}` → `{ok, id, file, name, size, removed:[...]}` |
| POST | `/api/instances/{iid}/backups/{bid}/restore` | `{ok, restored, pre_backup}`；实例运行中 400 |
| DELETE | `/api/instances/{iid}/backups/{bid}` | `{ok}` |
| GET | `/api/instances/{iid}/backups/{bid}/download` | 附件流 |

### 1.11 详情 · 计划任务 `#/instances/{id}/cron`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/cron` | `{ok, jobs:[{id,instance_id,instance_name,name,schedule,action,payload,enabled,last_run,last_status,next_run,next_run_ts}], actions:[str]}` |
| POST | `/api/cron` | body `{name, schedule, action, instance_id, payload, enabled}` → `{ok, id}`；cron 非法 400 |
| PATCH | `/api/cron/{jid}` | 子集 → `{ok, changed}` |
| DELETE | `/api/cron/{jid}` | `{ok}` |
| POST | `/api/cron/{jid}/run` | `{ok, status, output, duration}`（立即执行一次） |
| GET | `/api/cron/{jid}/runs?limit=` | `{ok, runs:[{id,job_id,ts,status,output,duration}]}` |
| POST | `/api/cron/validate` | body `{schedule}` → `{ok, error, next_run}` |

`action ∈ {restart,stop,start,backup,command,broadcast}`。

### 1.12 详情 · 设置 `#/instances/{id}/settings`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/instances/{iid}` | `{ok, instance:Instance}`（含 `dir_size`、`eula:{exists,accepted}`、`note`、`exit_code`） |
| PATCH | `/api/instances/{iid}` | body 子集 `{name,port,note,auto_restart,memory_mb,java_path,rcon_*}` → `{ok, changed, instance}` |
| GET | `/api/instances/{iid}/crashes?limit=` | `{ok, crashes:[{id,ts,exit_code,tail,action}]}` —— `tail` 是最后 50 行日志原文 |
| GET | `/api/instances/{iid}/metrics?hours=24` | 同 1.5 |
| DELETE | `/api/instances/{iid}?purge=true\|false` | `{ok, note}`；运行中 409 |

### 1.13 设置页 `#/settings`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/settings` | `{ok, config:{...}, rcon_password_set:bool, curseforge_api_key_set:bool, version, paths:{data,instances,logs,backups,java,downloads}, note}`。**`rcon_password` / `curseforge_api_key` 必须回空串，绝不回明文** |
| PUT | `/api/settings` | 子集白名单：`port,bind_host,site_name,session_hours,max_login_fails,lock_minutes,sample_interval,log_ring_lines,download_workers,default_java,default_jvm_args,default_memory_mb,backup_keep,mirror_prefix,rcon_enabled,rcon_host,rcon_port,rcon_password,curseforge_api_key,auto_restart_limit,theme` → `{ok, config, note}`；超范围 400 |
| GET | `/api/cores-probe` | `{ok, results:[{source,label,ok,count,error}]}` —— 7 个源逐个实测可达性 |
| GET | `/api/java/adoptium` | `{ok, lts:[int], releases:[int], error?}` |
| DELETE | `/api/java/{major}` | `{ok}`；仍被实例引用 → 409 + 中文原因 |
| GET | `/api/maintenance/usage` | `{ok, usage:{'名字':bytes}, metrics_rows, audit_rows, crash_rows, download_rows, db_size, paths}` |
| POST | `/api/maintenance/clean-tmp` | `{ok, removed, freed}` |
| POST | `/api/maintenance/clean-metrics` | `{ok, deleted, remain}` |
| POST | `/api/maintenance/clean-logs` | `{ok, removed, freed}` |
| POST | `/api/maintenance/open-dir` | body `{which:'data'|'logs'|'instances'|'backups'|'java'}` → `{ok, path}` 或 `{ok:false,error}`（无桌面环境时） |
| GET | `/api/logs/app?limit=&level=` | `{ok, lines:[{ts,level,text}], files:[{name,size,mtime}], total}` |
| GET | `/api/logs/app/download` | 纯文本附件 |
| GET | `/api/webhook` / PUT `/api/webhook` | `{ok, webhook:{url,events:[],enabled}, events:[...]}`；可用事件：`instance.start/stop/crash`、`backup.create`、`cron.run`、`auth.login` |

### 1.14 审计日志页 `#/audit`

| 方法 | 路径 | 需要返回 |
|---|---|---|
| GET | `/api/audit?limit=&offset=&action=&instance_id=` | `{ok, logs:[{id,ts,user,ip,action,instance_id,detail,level:'info'|'warn'|'error'}], total}` |
| GET | `/api/audit/login?limit=` | `{ok, logs:[{id,ts,username,ip,ua,success:0\|1,reason}]}` |
| GET | `/api/overview` | `{ok, instances:[...], host:{cpu_percent,mem_percent,mem_used_mb,mem_total_mb,disk_percent,disk_free_gb,cpu_count}, counts:{total,running,players}, version, java:[...]}`（首页概览用，**尚未接入 UI**） |

---

### 1.15 详情 · 建筑导入（无需机器人进服）

> 形状**完全依据** `docs/FEATURE-BUILDING-IMPORT.md` §7 与 §5 登记，前端不改名、不改字段。
> 该规格归核心所有；此处只写消费侧形状与前端约束。

| 方法 | 路径 | 请求 | 需要返回 |
|---|---|---|---|
| POST | `/api/instances/{iid}/build/upload` | multipart：`file`（建筑文件）+ `path`（目标相对目录） | `{ok, upload_id, sha256, size, format}`，`format ∈ {schem, schematic, nbt, litematic, mcstructure, zip}` |
| POST | `/api/instances/{iid}/build/preview` | `{upload_id, mc_version?, x?, y?, z?, dimension?, rotate?, mirror?, place_mode?, replace_list?, include_entities?, include_biome?, member?}` | §5 报告，**必须含** `format`、`size{x,y,z}`、`blocks_total`、`blocks_affected`、`dimension`、`bbox{min[3],max[3]}`、`palette_total`、**`palette_unmapped:[{name,count}]`**、`chunks_touched`、**`engine_available:[]`**、**`engine_recommended`**、**`warnings:[]`**、**`requires_backup`**；越界/跨维度/超高度时 `ok:false` + `error`（中文原因） |
| POST | `/api/instances/{iid}/build/import` | `{upload_id, x, y, z, dimension, rotate, mirror, place_mode, replace_list, include_entities, engine, backup}` | `{ok, task_id}`；前置不满足（实例运行中且未装插件等）→ 400/409 + 中文原因 |
| GET | `/api/instances/{iid}/build/tasks/{task_id}` | — | `{state, progress, written_chunks, total_chunks, error}`，`state ∈ {parsing, mapping, writing(n/N), done, failed, cancelled}`，`progress` 0–100 |
| POST | `/api/instances/{iid}/build/tasks/{task_id}/cancel` | — | `{ok}`（写入中允许在区块边界安全停止） |
| POST | `/api/instances/{iid}/build/rollback/{task_id}` | — | `{ok, note?}`；回滚前需再备份当前状态 |
| GET | `/api/build/formats` | — | `{ok, formats:[{ext, name, note, needs_convert?}], max_size}` |

**前端约束（硬性，代码即如此执行）：**

1. **前端不得自己编造 `palette_unmapped` 与 `warnings`。** 未映射方块清单、警告列表、
   受影响方块数、涉及区块数、推荐引擎，**一律只渲染后端返回值**；后端未提供就显示「后端未提供」，
   绝不用估算值填充 —— 这是防止用假数据骗用户的关键约束。
2. **未预检不得直接导入。** 在拿到该 `upload_id` 的成功预检（`ok:true`）之前，「导入」按钮保持禁用；
   预检 `ok:false` 时只显示拒绝原因，不出现导入入口。
3. **预检失败不清空用户已填的坐标与选项**，便于改坐标后重试。
4. **回滚必须二次确认**，确认文案讲清「会覆盖导入之后这段时间的改动」。
5. **引擎选择不由前端臆测**：用后端 `engine_recommended` 预选，允许用户手动改；
   若用户选的引擎不在 `engine_available` 内，则禁用该选项并显示原因。
6. 卖点文案固定为**「无需机器人进服」**；同时如实标注前置条件：
   引擎 A 需装 WorldEdit + 开启 RCON；引擎 B 需先停止实例。
7. `mcstructure`（基岩版）只做识别与「需转换」提示，**前端不给导入按钮**。

**本轮 UI 使用 mock 数据**（`frontend/dist/js/mock-build.js`），字段与上表逐字对齐；
后端就绪后只需把 mock 的取数函数换成 `API.post/get`，其余渲染逻辑不用改。

---

### 1.16 账号与权限（默认超级管理员）

> 形状**完全依据** `docs/FEATURE-ACCOUNTS.md` §5 登记，前端不改名、不改字段。
> 认证（PBKDF2-SHA256 600k / ≥12 位 3 类 / 失败锁定 / 会话 epoch / 审计）由核心实现。

| 方法 | 路径 | 权限 | 请求 | 需要返回 |
|---|---|---|---|---|
| GET | `/api/users` | `user.manage` | `?limit=&offset=` | `{ok, users:[User], total}`；`User = {id, username, role:'super_admin'\|'admin'\|'user'\|'viewer', status:0\|1, quota:{max_instances,max_memory_mb_total,max_backups,max_upload_mb,allow_build_import}, last_login, instance_count, created_at}` |
| POST | `/api/users` | `user.manage` | `{username, password, role, quota:{...}}` | `{ok, id, user:User}`；用户名重复 409；口令不合策略 400 + 中文原因 |
| PATCH | `/api/users/{id}` | `user.manage` | `{role?, status?, quota?}` | `{ok, changed:[...], user:User}`；**自我降级 / 停用最后一个超管 → 400 + 中文原因** |
| POST | `/api/users/{id}/password` | `user.manage` | `{password?}`（留空由服务端随机生成） | `{ok, password, note}` —— **`password` 只在本次响应里出现一次**，页面显示一次后可复制，关闭即不再可见；旧 token 立即失效（bump `token_epoch`） |
| POST | `/api/users/{id}/kick` | `user.manage` | — | `{ok}`（bump `token_epoch`，该用户所有会话失效） |
| DELETE | `/api/users/{id}` | `user.manage` | `?purge_instances=true\|false` | `{ok, note}`；**禁止自删、禁止删除最后一个超管**（400）；名下实例需先转移或一并删除，`note` 要说明实际做了什么 |
| GET | `/api/me/permissions` | 登录即可 | — | `{ok, role, perms:[...], quota:{...}}`。`perms` 取值见下 |

**权限点（与 `FEATURE-ACCOUNTS.md` §2 一致）：**
`instance.create` `instance.delete` `instance.start` `instance.stop` `instance.command`
`instance.files` `instance.plugins` `instance.backup` `instance.cron` `instance.build_import`
`instance.settings_network` `user.manage` `system.settings` `audit.view` `log.view`

**前端约束（硬性）：**

1. **菜单与按钮按 `/api/me/permissions` 隐藏/禁用；但后端必须逐个路由兜底 403。**
   前端隐藏**不算安全**——任何被隐藏的入口，直接构造请求也必须被后端拒绝。
   前端拿到 403 时统一 toast「权限不足」并保持当前页面不崩。
2. **直接访问越权页面**要给设计过的「权限不足」空状态（说明缺少哪个权限点、当前角色是什么、
   可以找谁申请），**不允许白屏，也不允许把裸 403 抛给用户**。
3. **任何页面、日志、审计里都不出现明文口令。** 重置口令的响应**只在当次**渲染，
   弹窗关闭后 DOM 中不再保留该字符串（前端不写入 localStorage / 不写控制台）。
4. **登录页**：失败要有明确提示；触发锁定时显示**剩余锁定倒计时**（按 429 响应 + 本地计时）；
   首次运行引导写明「**默认账号是超级管理员**」；**绝不出现任何"默认密码"字样**（口令只在服务器终端打印一次）。
5. **顶栏角色徽标**四色区分（超级管理员 / 管理员 / 普通用户 / 只读），全部走 token 体系并过 WCAG AA。
6. **实例卡片**：`super_admin` / `admin` 视角显示「归属用户」；`user` 视角只看到自己的实例
   （列表本身由后端过滤，前端文案保持一致，不暗示"这里本该有更多"）。
7. 用户管理类操作后端审计为 `warn` 级；前端在危险操作（删除用户、强制下线、重置口令）
   一律二次确认，删除用户的确认文案要讲清「其名下实例需先转移或一并删除」。

**本轮 UI 使用 mock 数据**（`frontend/dist/js/mock-accounts.js`），字段与上表逐字对齐；
后端就绪后把 mock 取数函数换成 `API.get/post/patch/del` 即可，渲染逻辑不用改。

---

## 2. 前端不依赖、但核心可能新增的接口（预留）

前端按需接入，接口形状请在此登记后再实现：

| 计划能力 | 建议路径 | 前端用途 | 状态 |
|---|---|---|---|
| **建筑导入（无需机器人进服）** | 见 §1.15（7 个接口） | 详情新增「建筑」Tab | **规格已定**（`FEATURE-BUILDING-IMPORT.md`），UI 已用 mock 完成，待后端接口 |
| 崩溃根因分析（退出码 + 日志特征 → 人话结论 + 建议） | `GET /api/instances/{id}/crash-analysis` | 设置 Tab 崩溃记录卡片里展示"结论 + 建议" | 规划中 |
| TPS 低自动诊断（耗资源插件/实体/区块） | `GET /api/instances/{id}/diagnose` | 控制台侧栏一键诊断 |
| Mod 依赖冲突检测 | `GET /api/instances/{id}/mods/conflicts` | 插件 Tab 顶部告警条 |
| BungeeCord/Velocity 群组一键组网 | `POST /api/groups`、`GET /api/groups` | 顶部新增"群组"导航 |
| 从旧实例/其它面板导入 | `POST /api/import/scan`、`POST /api/import/apply` | 新建向导增加"导入"入口 |
| 玩家行为审计 | `GET /api/instances/{id}/player-audit` | 玩家 Tab 新增"行为"分栏 |
| 多用户 + 实例级配额 | `GET/POST /api/users`、`PATCH /api/users/{uid}` | 设置页新增"用户"分栏 |
| 网页地图接入（BlueMap/Dynmap） | `GET/PUT /api/instances/{id}/maps` | 详情新增"地图"Tab |
| 内网穿透 FRP | `GET/POST /api/frp/config`、`POST /api/frp/{start,stop}`、`GET /api/frp/logs` | 设置页新增"内网穿透"分栏 |
| 整合包一键安装 | `GET /api/modpacks/search`、`POST /api/modpacks/install` | 新建向导增加"整合包"核心类型 |

---

## 3. 前端假设与硬性要求（按现状写明；核心可裁定后回改本节）

> 以下每一条前端**已按此实现**。若核心要改，请在此节标注 `[变更]` 并说明，前端再适配。

**A. 数据语义**

1. **`Instance.tps_available === false` 时，`tps` 必须是 `null`，不得回 `0`。**
   前端用 `tps_available` 决定是否显示「不可用」；回 `0` 会把"没有数据"伪装成"TPS 为 0"，属于编造数据。
   同理 `mspt` 无数据时回 `null`。并请在 `tps_note` 里给中文原因（例如"该服务端未在日志输出 TPS 且未启用 RCON"）。
2. **`stop` 必须回 `graceful: bool`**，如实反映"是否走了 stdin `stop` + 在超时内优雅退出"。
   `graceful:false` 时前端提示"已强制结束进程树"。
3. **日志 `level` 由后端判定**并随每行下发（`info|warn|error|input|panel`），前端**不再二次判断**，保证全站配色一致。
4. **所有"不可用"场景都要带中文原因**（`error` / `tps_note` / `note` / `warnings`），前端直接原样展示，不做二次解释、不做兜底猜测。
5. **控制台 WS 的 `history` 只回最近 N 行**（建议 200，最多 500），否则首屏会卡。
6. **列表类响应统一 `{ok:true, 复数名词:[...]}`**，前端只读那个字段；分页统一 `limit`/`offset` + `total`。

**B. 传输约定**

7. **上传接口 multipart 字段名固定为 `file`**，其余为普通表单字段：
   `files/upload` 用 `path`（目标相对目录，空串=根）、`plugins/upload` 用 `dir`、
   `build/upload` 用 `path`。**不要改名。**
8. **下载直链必须支持 `?token=`**（浏览器 `<a download>` 带不了 Header）：
   `files/download`、`log/download`、`backups/{bid}/download`、`logs/app/download`。
9. **WebSocket 未认证时**用 `close(code=4401)`（或先 `accept()` 再关）；前端按"未登录 → 跳登录页"处理。
   会话失效也用 4401，不要用 1008 之外的自定义码。

**C. 安全与权限**

10. **`/api/health` 必须免鉴权**，且**不得包含任何配置/路径/版本之外的信息**（登录页用它判断服务是否在线）。
11. **菜单与按钮按 `/api/me/permissions` 隐藏/禁用，但后端必须逐路由 `require_perm` 兜底 403。**
    前端隐藏**不算安全边界**：任何被隐藏的入口，直接构造请求也必须被拒绝。
    前端收到 403 → toast「权限不足」，越权页面 → 设计过的「权限不足」空状态（不白屏、不裸抛 403）。
12. **兜底鉴权若从中件层移除**，请确保**每个路由都显式声明依赖**——前端的未登录断言会全量遍历 `/api/**` 断言 401，
    漏一个就会在自检里暴露（这也是我们希望保留的护栏）。
13. **任何响应、日志、审计里都不得出现明文口令**；`POST /api/users/{id}/password` 的 `password` 字段只在当次响应出现。

**D. 一致性**

14. **`instance.status` 取值固定为** `running|stopped|starting|stopping|crashed`；前端据此选徽标配色与呼吸动画。
15. **`badge`/状态文案的"人话"由前端负责**，后端只给机器可读值（枚举、错误码），不要下发中文状态词。
16. **布尔字段（`auto_restart`/`nogui`/`rcon_enabled` 等）允许 `0/1`**，前端按真值判断；新增字段请沿用该惯例或在契约中注明。


---

## 4. 变更记录

| 日期 | 变更 | 影响 |
|---|---|---|
| 初始 | 前端侧起草（第 1 节为已实现消费形状） | 待核心确认第 2、3 节 |
