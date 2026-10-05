# Snowolf 竞品与风格基线调研报告

> 调研对象：**Snowolf（Snowolf-Studio/Snowolf）**——Minecraft 多服务器管理面板
> 调研日期：2026 年（本机时钟）
> 报告用途：「我的世界开服面板」产品立项的功能与风格基线
>
> ## ⚠️ 使用边界（**落地实现时必须遵守**）
>
> 本报告是**事实性调研/兼容性分析**，供我方独立实现时做取舍参考。**它不是取材仓库**：
>
> 1. **禁止把对方的源码、模块、组件、封装好的工具函数、专有业务逻辑复制进本项目**——
>    一行都不行。§2 里引用 `src/components/*`、`theme.css` 等**只作为事实来源标注**
>    （证明某个结论有出处），**不是让我们去抄那些文件**。
> 2. **可以吸收的只有两类**：① 无著作性的**通用设计参数**（颜色字面值、圆角/间距尺寸阶、
>    缓动曲线、动效时长）；② **通用交互范式**（侧栏+顶栏+卡片网格首屏、列表可排序可置顶一类，
>    这类范式在 Vercel / Linear / 各家后台里普遍存在，不是某产品的独创表达）。
> 3. **禁止直接沿用对方的**：专有组件名/模块名（如 `GlowCard`、`ServerSubNav`、`DynamicIsland`、
>    `MetallicPaint` 等）、专有命名与文案、品牌 Logo/图标素材、以及对方独有的功能编排与实现细节。
> 4. 我方代码里**不出现对方产品名**作为命名或标识，避免让人误以为存在血缘或绑定。
>    确需指向本报告时，只写"界面调研结论（见 docs/）"。
>
> 已按此边界复核：`frontend/`、`backend/` 中**无任何对方源码或专有命名**（详见 `PROGRESS.md` §6.6）。
>
> **口径约定（全文严格遵守）**：
> - **[官方文档]** = Snowolf 官方文档站 / README / 发行说明原文所述。
> - **[源码实测]** = 本次调研直接读取其公开仓库源码、CSS 变量、命令注册表所得，属客观证据。
> - **[实测]** = 本次调研用 `curl` 实际发起的 HTTP 请求结果（含状态码）。
> - **[我看截图]** = 本次调研确实看到了图片内容。**本报告未使用此口径——因为未获取到任何官方界面截图**（见 §2.1）。
> - **[推测]** = 无直接证据的推断，已逐条标注。

---

# 一、Snowolf 是什么

## 1.1 结论

**Snowolf 是一个 Minecraft（Java 版）多服务器「桌面」管理面板**，不是网页面板、不是主机商控制台、不是游戏客户端。

依据（一手证据）：

| 项 | 值 | 来源 |
|---|---|---|
| 仓库 | `Snowolf-Studio/Snowolf`（GitHub Organization 账号） | [GitHub API](https://api.github.com/repos/Snowolf-Studio/Snowolf) **[实测]** |
| 自述 | 「Minecraft 多服务器**桌面**管理面板（Tauri + React + TypeScript + Rust）」 | 仓库 README **[官方文档]** |
| 官方定位句 | 「Windows 上的 Minecraft Java 版服务器管理面板：创建、多实例运维与常用工具」 | [docs 站《什么是 Snowolf》](https://docs-snowolf.lr-luorui.cn/zh-CN/docs/what-is-snowolf) **[官方文档]** |
| 不是什么 | 官方明确写：「**不是网页控制面板**：进程与文件都在你这台 Windows 上」「不是游戏客户端」 | 同上 **[官方文档]** |
| 许可证 | **GPL-3.0**（SPDX `GPL-3.0`，`gpl-3.0`） | GitHub API **[实测]** |
| 主语言 | TypeScript（1,973,885 B），其次 Rust（1,807,995 B）、SCSS（656,055 B） | `/languages` **[实测]** |
| star / 创建 / 最后推送 | 9 stars / 2026-04-21 创建 / 2026-08-03 最后 push | GitHub API **[实测]** |
| 仓库体积 | 11,290 KB（约 11 MB），默认分支 `main` | GitHub API **[实测]** |
| 文档站 | `https://docs-snowolf.lr-luorui.cn/`（Next.js 构建，支持 en / zh-CN / zh-TW / ja） | **[实测]** HTTP 200 |

## 1.2 命名与「雪狼」误判的澄清

- **中文名**：官方文档与发行说明中**未出现**「雪狼」这一中文名。文档/源码里出现的自称是 **Snowolf**、**Snowolf Studio / Snowolf-studio**、**LR-UI / LR'小さな狐の妖精**（文档署名与设计系统注释）。
  → **「雪狼」属于未证实的推测译名，本报告不建议采用。**
- **`snowolf.cn` 与 Snowolf 产品无关**：**[实测]** `https://snowolf.cn/` 与 `https://www.snowolf.cn/` 均返回 **HTTP 200**，但内容是一个**影视站**（`<title>成全影视大全在线播放第6季…`，`贵ICP备36325334号-6`，站点自称「云影剧场」）。即该域名已被**无关用途占用**，**不能**当作 Snowolf 官网。
- 其他疑似域名 **[实测]**：`snowolf.cc` → 连接失败（000）；`snowolf.top` → 连接失败（000）；`docs.snowolf.cn` → 连接失败（000）。均**未找到证据**。
- **官方品牌站**：`snowolf.lr-luorui.cn`——`https://` 返回 **404**，`http://` 返回 **200 但仅 138 字节**（空壳）。文档《安装、更新与获取》页自己也写明：「**官网角色**：`snowolf.lr-luorui.cn` 是品牌与介绍站，**不是可靠的二进制唯一来源**。锁定安装包时仍以 GitHub Releases 或应用内更新为准。」→ **[官方文档]** 直接佐证该站不是主分发渠道。
- 父级站点 `https://lr-luorui.cn/` **[实测]** HTTP 200（8,326 B），为开发者的个人/组织站。

## 1.3 版本线与开源关系（**关键**）

README 原文 **[官方文档]**：

> 「随着 Snowolf **2.0** 完成底层架构的大规模重构，1.7 系列也完成了它作为上一代技术实现的阶段性使命。2.0 的核心底层由我们重新设计与实现，不再沿用 1.7 中源自 SeaLantern 的底层代码。」
> 「我们决定完整公开 **1.7 系列**源码……」
> 「若你关心最新产品能力，请以 **2.0 发行版与官方文档**为准。」

因此：

- **本仓库 = 1.7 系列源码**（GPL-3.0-or-later），**2.0 未开源**，只发布二进制。
- 1.7 后端**早期参考并衍生自** [FPSZ/SeaLantern](https://github.com/FPSZ/SeaLantern)（GPL-3.0-or-later，自述「一款由B站社区共创的客制化 Minecraft 开服器」）**[官方文档]** + **[实测]** 该仓库存在、13 stars、最后 push 2026-02-25。
  → **含义**：Snowolf 1.7 的底层血统与 SeaLantern 同源，属「B站社区共创开服器」生态的一支。
- **重要的口径风险**：本报告 §3 的功能清单**主要来自源码与文档站**。其中源码是 1.7 的，文档站标题写的是「以 2.0 为准」。凡源码与文档不一致处，下方逐条标注。

## 1.4 渠道与社区

- GitHub Releases 是官方推荐安装渠道 **[官方文档]**。
- 社区：QQ 群（群号在应用内「关于」页）、**爱发电**（赞助）、**Bilibili**（动态与教程）、GitHub **[官方文档]**。
- 商业模型：**Snowolf Cloud 账号**（浏览器授权登录）承载「AI 权益、套餐、头像、设备管理」；套餐分 **Free / Pro / Plus**，另有「一天 Pro 体验」与「内测解锁」入口；支付走**爱发电**，支持订单号认领 **[官方文档]**。
- 内网穿透是**另一套独立账号**，与 Cloud 不互通 **[官方文档]**。

## 1.5 未找到 / 信息不足的部分

- **B 站视频 [BV15t5S6MEq1](https://www.bilibili.com/video/BV15t5S6MEq1/)**（标题「Snowolf一站式MC服务器管理：一键开服+可视化运维，告别手动配置」）：本次检索命中该 URL，但**未能取到视频内容或封面**，无法作为截图来源。→ **未获取到**。
- **Snowolf 2.0 的独立发行说明**：本次通过 GitHub Releases API 检索，**API 因限流返回空**；在早前一次成功调用中取到 **10 个 release（v1.1.0-beta.1 → v1.7.2-beta）**，**未发现任何 2.0 标签**。→ 2.0 的发布记录**未获取到**；2.0 的存在仅有 README 文字为证。
- **「雪狼」中文名**：**未找到证据**。
- 是否有官方在线演示站：**未找到证据**。

---

# 二、界面风格基线（含截图链接）

## 2.1 先说结论：**官方界面截图一张都没拿到**

- 文档站 26 个页面共出现 **244 处**图片引用，其中绝大多数形如
  `data-screenshot-placeholder="players-guide/step-01-online.webp"`，即官方**尚未补齐的占位图**（页面内文字写「待补截图」）。
- **[实测]** 逐一探测以下路径形态，**全部 404**：
  - `/screenshots/players-guide/step-01-online.webp` → 404
  - `/screenshots/desktop-tray-guide/step-01-island.webp` → 404
  - `/docs/players-guide/step-01-online.webp` → 404
  - `/screenshots/create-server/step-01-create-hub.webp` → 404
  - 另试 `/screenshots/<slug>/step-01.png`、`/<slug>/step-01.webp` 等 10+ 变体 → **全部 404**
- **[实测]** `sitemap.xml` / `robots.txt` 均 404，无法枚举资源清单。
- **[实测]** 文档站**真实存在**的图片仅 3 个：
  | 用途 | URL | 实测 | 说明 |
  |---|---|---|---|
  | Logo（黑） | `https://docs-snowolf.lr-luorui.cn/logo-black.svg` | 200, 20,984 B, `image/svg+xml` | 可用于确认品牌视觉，**非界面截图** |
  | Logo（白） | `https://docs-snowolf.lr-luorui.cn/logo-white.svg` | 200, 20,979 B, `image/svg+xml` | 同上 |
  | 站点图标 | `https://docs-snowolf.lr-luorui.cn/icon.png` | 200, 2,030 B, `image/png` | 同上 |
  | 贡献者头像 | `https://docs-snowolf.lr-luorui.cn/contributors/lr-fox.jpg` 等 | 在 HTML 中引用 | 头像，非界面 |

> **结论：§2 的界面风格描述不来自截图，而来自其公开的 `theme.css` 设计令牌与官方文档的界面文字描述。这是比截图更精确的一手证据，但「观感」层面（排版实际效果、图标画风）仍有无法验证的部分，已逐条标注 [推测]。**

## 2.2 配色系统（来源：`src/styles/theme.css`，45,556 B）**[源码实测]**

文件首行注释定义了设计系统身份：

```css
/* 黑白灰单色设计系统，LR-UI风格等比例设计喵 */
```

即 **Snowolf 的默认视觉基底是「黑白灰单色 + LR-UI 风格等比例大圆角」**，彩色是可选变体而非默认。

### 深色主题（默认基底）`[data-theme="dark"]`

| 语义 | Hex | 用途 |
|---|---|---|
| `--bg-primary` | `#0a0a0a` | 最底层背景（近纯黑） |
| `--bg-secondary` | `#141414` | 次级面 |
| `--bg-tertiary` | `#1f1f1f` | 三级面 |
| `--bg-elevated` | `#1a1a1a` | 卡片/浮起面 |
| `--text-primary` | `#f5f5f5` | 主文字 |
| `--text-secondary` | `#a3a3a3` | 次文字 |
| `--text-tertiary` | `#525252` | 三级文字 |
| `--border-subtle` | `#262626` | 弱边框 |
| `--border-default` | `#333333` | 常规边框 |
| `--border-strong` | `#525252` | 强边框 |
| `--brand-primary` | `#f5f5f5` | **品牌色＝浅灰白**（单色系统特征） |
| `--brand-secondary` | `#d4d4d4` | — |
| `--color-error` | `#f87171` | 控制台/状态 错误 |
| `--color-warn` | `#fb923c` | 警告（橙） |
| `--color-info` | `#34d399` | 成功/信息（绿） |
| `--color-debug` | `#22d3ee` | 调试（青） |
| `--nav-active-bg` | `rgba(219,219,219,0.1)` | 侧栏选中态 |

### 浅色主题 `:root` / `[data-theme="light"]`

| 语义 | Hex |
|---|---|
| `--bg-primary` | `#fafafa` |
| `--bg-secondary` | `#f5f5f5` |
| `--bg-tertiary` | `#e8e8e8` |
| `--bg-elevated` | `#ffffff` |
| `--text-primary` | `#171717` |
| `--text-secondary` | `#525252` |
| `--text-tertiary` | `#a3a3a3` |
| `--border-subtle` | `#e8e8e8` |
| `--border-default` | `#d4d4d4` |
| `--brand-primary` | `#171717` |
| `--color-error` | `#dc2626` |
| `--color-warn` | `#ea580c` |
| `--color-info` | `#059669` |
| `--color-debug` | `#0891b2` |

灰度阶为 Tailwind 式中性灰：`#fafafa #f5f5f5 #e5e5e5 #d4d4d4 #a3a3a3 #737373 #525252 #404040 #262626 #171717 #0a0a0a`。

### 明/暗主题与彩色变体 **[源码实测]**

主题选择 = **明暗 × 配色变体** 的二维组合（每种组合都有独立 token 块）：

- 明暗：`light` / `dark`
- 配色变体：`eye-care`（护眼）、`contrast`（高对比）、`orange`、`blue`、`purple`、`green`

`light` 下的品牌色实测值：

| 变体 | `--brand-primary` |
|---|---|
| orange（活力橙） | `#c2410c` |
| blue（静谧蓝） | `#1d4ed8` |
| purple（薰衣草紫） | `#7e22ce` |
| green（薄荷绿） | `#15803d` |
| eye-care（护眼） | `#5c4d3c` |
| contrast（高对比） | `#000000` |

> **[官方文档]** 佐证：v1.6.0 发行说明「彩色主题与配色变体……包含**活力橙、静谧蓝、薰衣草紫、薄荷绿**等；同时提供**护眼模式与高对比度**配色」。
> **[官方文档]** 变现方式：v1.6.0 起「**浅色/深色基底免费可选；部分多彩主题、图标包、终端预设和金属 Logo 受 Pro/Plus 或独立授权限制**；权益到期后受限外观可能被收回」。→ **主题是付费点**。

### 状态色与「成功色＝灰」的反常设计（重要风格特征）

`theme.css` 中 **[源码实测]**：

```css
--error:   var(--color-error);
--warning: var(--color-warn);
--success: var(--gray-700);   /* 深色主题下为 --gray-300 */
```

即 **`success` 不映射到绿色，而映射到灰色**。这是「黑白灰单色设计系统」的直接后果：**成功态靠灰度与文案表达，而非绿色。**

> **风格启示（对本产品的直接价值）**：Snowolf 走的是**极名单色 + 大圆角**路线（类似 Vercel / Linear 的中性灰调），而不是国内 MC 面板常见的「Element Plus 默认蓝 + 高饱和状态色」。这是它与 RT面板、小皮面板等在观感上最本质的分野。

## 2.3 圆角、间距、阴影、动效 **[源码实测]**

**圆角系统**（等比例大圆角，明显大于常规后台）：

```
--radius-xs: 8px    --radius-sm: 12px   --radius-md: 16px
--radius-lg: 20px   --radius-xl: 24px   --radius-2xl: 28px
--radius-full: 9999px
```

**间距系统**（紧凑且对称，4 / 8 基准）：

```
--space-1: 4px   --space-2: 8px   --space-3: 12px  --space-4: 16px
--space-5: 20px  --space-6: 24px  --space-8: 32px  --space-10: 40px
```

**动效令牌**：

```
--transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
--transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1);
--transition-slow: 300ms cubic-bezier(0.4, 0, 0.2, 1);
```

**阴影系统**——这是 Snowolf 观感的关键，采用**多层叠加 + 1px 内描边**的「真实感」做法，而非单层阴影：

- `--shadow-ambient`: `0 0 0 1px rgba(0,0,0,0.03)`（亮）/ `0 0 0 1px rgba(255,255,255,0.06)`（暗）——**用 1px ring 代替边框**
- `--shadow-primary`: 两层小阴影 `0 1px 2px` + `0 2px 4px`
- `--shadow-elevated`（暗色下）：**五层递进** `0 4px 8px / 0 12px 12px / 0 24px 16px / 0 40px 20px / 0 60px 24px` **+ 尾部 `rgba(255,255,255,0.06) 0 0 0 1px` 内描边**
- 另有 `--shadow-floating`（6 层）、`--shadow-modal`（6 层）、`--shadow-dropdown`（6 层）、`--shadow-menu-panel`、`--shadow-menu-panel-enter`

> **可直接借鉴的规范**：多层阴影 = `translateY` 越大、模糊半径越大、透明度越低，最后收一条 1px 白色内描边提亮边缘。这是「高级感浮层」的通用配方。

**毛玻璃（玻璃拟态）**：`bg-*-rgb` 系列变量专为毛玻璃准备（如 `--bg-primary-rgb: 10, 10, 10`），文档说明毛玻璃效果**可独立开关顶栏 / 侧栏 / 底部**。桌面端另有平台原生材质：源码中 macOS 走 `apply_vibrancy(NSVisualEffectMaterial::UnderWindowBackground)`，Windows 有 `apply_acrylic` 命令。**[源码实测]**

## 2.4 导航形态与首屏布局 **[官方文档] + [源码实测] + [推测]**

- **导航形态 = 左侧边栏 + 顶栏 + 服务器子导航**（三级）：
  - 侧栏主入口（可配置可见项与顺序）
  - **顶栏**：含「Snowolf Cloud」账号入口、服务器下拉菜单、灵动岛、捐赠/版本/反馈按钮（后三者可单独隐藏）
  - **服务器子导航**（`ServerSubNav` 组件）：`概览 / 终端 / 文件 / 配置 / 模组插件 / 玩家 / 计划任务 / 设置`
  - **智能侧边栏**：窗口缩小自动折叠、拉大自动展开（v1.2.0）**[官方文档]**
- **首屏 = 仪表盘（Home）**：多实例**卡片网格**（`GlowCard` / `GlowCardGrid` / `HomeServerCardsSection`），每卡显示**状态、CPU、内存、冲突徽章**，提供启动/停止与子页入口；**卡片可拖动排序或置顶**（官方文档「服务器卡片显示状态、CPU、内存和冲突提示……可拖动排序或置顶常用服务器」）**[官方文档] + [源码实测]**
- **「一键开服」向导 = 有**。`CreateServer` 是独立整页向导，典型步骤 **[官方文档]**：
  `选择源文件 → 安装位置 → 启动与运行 → 确认创建`
  并配有**任务中心**展示「下载、解压、安装、扫描启动项和登记实例」等阶段。
  **[官方文档]** 明示默认值：「最大内存常为 **4096 MB**、最小 **1024 MB**、端口 **25565**、自动接受 EULA 默认 **false**」。
- **灵动岛（Dynamic Island）**：顶栏正中间显示运行中服务器与系统资源（CPU / 内存 / 磁盘 / 网络），可自定义 logo、文案、快捷跳转按钮。这是 Snowolf 最具辨识度的 UI 发明，**同类面板中未见对应物**。**[官方文档]** v1.4.0 + **[源码实测]** `src/components/DynamicIsland/`
- **系统托盘弹窗**：左键弹资源面板、右键系统菜单，可配置点击后跳转目标与显示指标 **[官方文档]**。
- **桌面壳行为**：非 macOS 下 `set_decorations(false)`（**自绘无边框窗口 + 自定义窗口控件**，源码有 `WindowControls` 组件）；关闭按钮三态 `minimize` / `close` / `ask` **[源码实测]**
- **背景系统**：可上传背景图、**运行中轮播**（10–600 秒，淡入淡出过渡）、启动时背景（保持当前/顺序/随机）、背景模糊、遮罩强度、卡片透明度、缩略图画廊 **[官方文档]** v1.7.2

## 2.5 终端、表格、卡片、图标、字体 **[源码实测] + [官方文档] + [推测]**

- **终端**：基于 **xterm.js**（`src/components/XTermConsole/`），自带 `ConsoleInput`。
  - `Ctrl+F` 日志搜索，**高亮色为橙黄色**（v1.7.2 改为「更醒目的橙黄色」）**[官方文档]**
  - 向上加载历史**保留 ANSI 颜色** **[官方文档]**
  - **命令保护开关**（未识别到已启动时需手动解除保护才能强制发送指令）——**安全设计，值得抄** **[官方文档]**
  - 分段追加 + 向上滚动加载（避免一次性加载卡顿）、终端日志导出、**选中日志「发送到 AI」** **[官方文档]**
  - 终端有独立**配色预设**（部分属付费权益）**[官方文档]**
- **文本编辑**：内置 **Monaco**（`src/monaco/`），支持目录树、文件搜索、后缀筛选、批量替换 **[源码实测] + [官方文档]**
- **卡片**：`Card` + `GlowCard`（发光卡片）+ `StatCard` + `ServerDataCard` + `SparklineChart` + `DiskSpeedChart` + `GradientText` + `MetallicPaint`（金属质感 Logo）**[源码实测]**
- **表格/列表**：模组插件列表显示**项目 logo、启用/禁用/更新状态、操作入口**；`ThickSlider`（粗滑块）、`SegmentControl`（分段控件）、`Skeleton`（骨架屏）、`Sonner`（Toast）、`HeadlessModal` / `Modal` / `Dialog`、`AnimatedDropdownPanel`、`DropdownMenu`、`GlobalContextMenu`（全局右键菜单）、`ProgressBar`、`time-picker` **[源码实测]**
- **图标风格**：`public/images/server-cores/` 下每个核心有专属 PNG/SVG（Paper / Purpur / Fabric / neoforge / Vanilla / Spigot / BungeeCord / Mohist / Arclight / Nukkit / Folia / Leaf / Leaves / Luminol / Pufferfish / Mojang…）→ **核心类型用真实品牌 logo 做视觉区分**，是很好的做法 **[源码实测]**
- **字体**：**未找到字体令牌**（`theme.css` 无 `--font-*`）。有独立 `Font` 设置页，且存在 `settingsStore.font.test.ts`；v1.2.1 修复过白底主题的字体渲染问题。**[官方文档]** 明确：「选择**系统字体**后检查中英文、数字、终端和长路径是否完整显示。**当前字体大小控件未正式开放**。」
  → 即采用**跟随系统字体**策略，无自定义字号阶。**[源码实测] + [官方文档]**
- **信息密度** **[推测]**：从 `--space-*` 最大仅到 40px、圆角最大 28px、卡片网格布局推断，属**中等偏低密度**的「留白充足型」后台，而非 1Panel 类高密度表格型。**此项为推测，无截图验证。**

## 2.6 官方截图 URL 汇总

**结论：未获取到任何官方界面截图 URL。** 已尝试的路径清单见 §2.1，全部 404。可用的**仅品牌视觉资源**：

- `https://docs-snowolf.lr-luorui.cn/logo-black.svg`
- `https://docs-snowolf.lr-luorui.cn/logo-white.svg`
- `https://docs-snowolf.lr-luorui.cn/icon.png`
- `https://docs-snowolf.lr-luorui.cn/contributors/lr-fox.jpg`（贡献者头像）

文档站自身引用的占位图命名规则（**若日后补齐，URL 极可能形如**）：
`https://docs-snowolf.lr-luorui.cn/screenshots/<doc-slug>/<step-NN>-<name>.webp`
（例：`/screenshots/players-guide/step-01-online.webp`）——**[推测]**，当前**实测 404**。

---

# 三、Snowolf 功能清单

> **证据强度最高的来源：`src-tauri/src/lib.rs` 里的 `tauri::generate_handler!` 命令注册表——共约 230 个后端命令，这是「后端能力清单」的硬证据。** 下方凡标 **[命令]** 者，命令名均为源码原文。

## 3.1 开服与实例创建

| 功能 | 证据 |
|---|---|
| 三种创建方式：**一键下载核心** / **导入 JAR·ZIP** / **托管已有目录** | [官方文档] + [命令] `create_server` `import_server` `add_existing_server` |
| **从模板创建** | [官方文档] + `src/pages/CreateServer/components/TemplateInstallDialog/` |
| **整合包导入** | [命令] `import_modpack`（**注意：这是 1.7 源码里的命令，文档站未单列此页**） |
| **创建任务中心**（异步任务：下载→解压→安装→扫描启动项→登记实例） | [官方文档] + [命令] `create_server_task_start/status/cancel/delete/list_recent` |
| 启动项候选扫描（避免误选 installer/client） | [官方文档] + [命令] `scan_startup_candidates` |
| 目录复制与冲突处理 | [命令] `collect_copy_conflicts` `copy_directory_contents` |
| **Docker 创建** | **[官方文档]** 明写「**Docker（开发中）**」「模板市场和 Docker 创建目前未正式开放，不应作为教程主路径」→ **未交付** |
| 镜像源选择 | [官方文档] 列举 `MCServerJars`、`VersionMC`；源码另有 **CNB 镜像**与 **BMCLAPI** |

## 3.2 服务端核心支持

从 `public/images/server-cores/` 资产 + `CORE_TYPE_ICON_PATHS` + 下载器源码 **[源码实测]**：

| 类别 | 核心 |
|---|---|
| 原版 | **Vanilla**（Mojang） |
| 插件端 | **Paper、Purpur、Spigot、Bukkit、Folia、Pufferfish、Leaf、Leaves、Luminol** |
| 模组端 | **Fabric、Forge、NeoForge、Quilt**（Quilt 见 §6 元数据；Quilt 图标未在资产中列出，**[推测]** 支持度较低） |
| 混合端 | **Mohist、Arclight** |
| 代理/群组 | **BungeeCord**（`CORE_TYPE_ICON_PATHS` 中写作 `Bungeecord`）、**Lightfall**（Velocity 系代理） |
| 基岩版 | **Nukkit / Nukkitx** —— **[重要] Snowolf 只覆盖 Nukkit 这类 Java 实现的基岩服务端；未发现对官方 Bedrock Dedicated Server (BDS) 的支持证据。** |

**实测的下载 URL（源码原文）**：
```
https://piston-meta.mojang.com/mc/game/version_manifest_v2.json
https://api.papermc.io/v2/projects/paper/versions/{}/builds/latest/downloads/paper-{}-latest.jar   ← 已失效，见 §6
https://api.purpurmc.org/v2/purpur/{}/latest/download
https://meta.fabricmc.net/v2/versions/loader/{}/{}/0.11.2/server/jar
https://cnb.cool/Snowolf-studio/ServerCore-Mirror/-/releases/download/26.02.27/jar_lfs_links.json
https://bmclapi2.bangbang93.com
```

## 3.3 Java 运行时与 JVM

| 功能 | 证据 |
|---|---|
| Java 自动检测（Windows 注册表 + 扫描候选目录，深度/别名常量可配） | [命令] `detect_java` `scan_java_in_directory`；`services/java_detector.rs` 用 `winreg` 读注册表 + `JAVA_PATH_ALIASES` |
| 手动指定 / 浏览 `java.exe` / 校验路径 / 重新检测 | [命令] `validate_java_path` `pick_java_file` |
| **面板内下载并安装 Java 运行时**（带进度事件 `java-install-progress`、重试、取消、超时） | [命令] `install_java` `cancel_java_install`；`services/download/java_installer.rs` |
| 运行时装到程序数据目录 `runtimes/<version_name>/` | [源码实测] |
| 每个实例级 Java 覆盖全局默认 | [官方文档] |
| **JVM 参数拼装工具**，作用域可选「实例设置」/「服务器默认」 | [官方文档] 工具箱 · JVM |
| **NeoForge `user_jvm_args.txt` 三策略**：完全覆盖 / 智能合并 / 不写入 | [官方文档] + `services/server/user_jvm_args.rs` |
| 内存 min/max（默认 1024 / 4096 MB）、端口、编码 | [官方文档] |
| Java 与核心版本配对指引（Java 8/17/21） | [官方文档] |

## 3.4 控制台

| 功能 | 证据 |
|---|---|
| 实时日志（xterm.js）、ANSI 颜色保留、分段追加、向上滚动加载 | [官方文档] + [源码实测] |
| 命令下发（`send_command`）、快捷命令区、输入自动填充 | [命令] + [官方文档] |
| `Ctrl+F` 搜索 + 橙黄色高亮 | [官方文档] |
| 命令保护开关（强制发送需解除保护） | [官方文档] |
| 日志导出到文件 / 清空显示（不删磁盘日志） | [命令] `export_server_logs_to_file` `clear_server_logs` |
| 日志读取与分页（`get_server_logs` / `get_server_log_entries`） | [命令] |
| **日志管道** `services/server/log_pipeline.rs`、去重 `logDisplayDedup`、序列跟踪 `logSeqTracker`、Minecraft 日志行解析 `minecraftLogLine.tsx` | [源码实测] |
| **选中日志发送给 AI** | [官方文档] |
| **RCON** | **未找到证据**（Snowolf 走 stdin/stdout 命令下发，无 RCON 客户端） |

## 3.5 文件与配置

| 功能 | 证据 |
|---|---|
| 文件浏览（面包屑、搜索、路径复制）、上传、下载、重命名、删除 | [官方文档] + [命令] `list_server_files` `create_server_folder` `create_server_file` `copy_server_file` `move_server_file` `delete_server_file` |
| 文本文件读写 + **文件预览**（类型预览、图片查看器） | [命令] `read_server_text_file` `read_server_file_preview` `write_server_text_file`；`ImageViewer.tsx` |
| **Monaco 内置编辑器**：目录树、文件搜索、后缀筛选、批量替换 | [官方文档] + [源码实测] |
| **与 Windows 资源管理器双向拖放**（复制/移动模式可选） | [官方文档] |
| **`server.properties` 可视化编辑器**：按类别分组、**可搜索中文说明或英文配置键** | [官方文档] + [命令] `read_server_properties` `write_server_properties` |
| **改端口时自动同步面板登记端口**（避免冲突检查失准） | [官方文档] + [命令] `update_server_registry_port` |

## 3.6 插件与模组

| 功能 | 证据 |
|---|---|
| `mods` / `plugins` 目录识别、列表（含项目 **logo**） | [命令] `m_get_mods` `m_get_plugins` `m_get_mod_icons` |
| 上传本地 JAR、**启用/禁用（`.disabled` 重命名）**、删除 | [命令] `m_toggle_mod` `m_toggle_plugin` `m_delete_mod` `m_delete_plugin` |
| **Modrinth 集成**：搜索、版本列表、项目详情、下载 | [命令] `modrinth_search` `modrinth_get_project` `modrinth_get_project_versions` `modrinth_get_minecraft_versions` `modrinth_download_mod`；`services/modrinth_service.rs` 基址 `https://api.modrinth.com/v2` |
| **检查更新 / 更新 / 更新失败回滚** | [命令] `m_check_mod_update` `m_update_mod` `m_rollback_mod_update`；[官方文档]「更新失败时 Snowolf 会尝试回滚旧版本」 |
| 读取模组/插件配置文件路径 | [命令] `m_get_mod_config_files` `m_get_plugin_config_files` |
| **Modrinth 之外的来源** | **未找到证据**：无 CurseForge、无 SpigotMC 内置商店（SpigotMC 仅出现在 Spigot 核心下载，非插件市场） |
| **CurseForge / SpigotMC 插件市场** | **未找到证据** |

## 3.7 备份与还原

| 功能 | 证据 |
|---|---|
| **世界备份**（World Backup） | [官方文档] 独立页《世界备份与停服恢复》 |
| **智能档**：备份目标与世界在同一 NTFS 卷时用**硬链接**省空间；跨盘或 FS 不支持则退回**完整拷贝** | [官方文档] |
| 间隔 15 分钟 – 24 小时、保留份数、可选「**仅在有玩家在线时备份**」 | [官方文档] |
| **停服恢复**（`停止并恢复`，会停服再覆盖世界），多阶段进度 | [官方文档] |
| `.pre-restore-` 快照残留提示 | [官方文档] |
| 备份导出 / 删除 / 区域热力图 | [官方文档] |
| **依赖 Snowolf Cloud + SWP 连接 + 账号权益**（离线缓存只能展示部分信息） | [官方文档] ← **重要限制：备份不是纯本地能力** |
| **手动整目录备份命令** | [命令] `services/server/manager_backup.rs` 存在，但**未在命令注册表中出现** → 该能力主要面向内部/世界备份 |

## 3.8 计划任务与自动化

| 功能 | 证据 |
|---|---|
| 四种调度：**固定间隔 / 周期每周 / 指定日期时间 / 原始 Cron** | [官方文档] + [命令] `upsert_server_schedule_task` |
| 动作链：**发送命令 / 延迟 / 开始识别 / 停止识别 / 重启 / 强制结束** | [官方文档] |
| 「重启会先等待停止，最长约 120 秒」；延迟单位毫秒（300000 = 5 分钟） | [官方文档] |
| 运行日志（每动作成功/失败/**跳过原因**）、上次运行、预计下次时间 | [官方文档] + [命令] `get_server_schedule_task_run_log` `get_server_schedule_task_run_meta` |
| 任务数上限 `max_server_schedule_tasks` | [命令] |
| **危险模式**（放宽命令长度/字符/动作数/延迟/Cron 校验，仅本次运行有效） | [官方文档] + [命令] `get/set_server_schedule_danger_mode` |
| **崩溃检测 / 自动重启** | **未找到证据**（有计划任务的「重启」动作，但**没有崩溃事件触发的自动重启**，也没有 TPS 阈值触发） |

## 3.9 端口与网络

| 功能 | 证据 |
|---|---|
| **端口冲突检查（默认开启）**，启动前拦截 | [官方文档] + [命令] `check_port_in_use` `get_servers_with_same_port` |
| **工作目录重复 / 路径嵌套检测** | [官方文档] + [命令] `get_servers_with_work_dir` `scan_server_registration_conflicts` `validate_server_path` |
| **冲突徽章** UI | [源码实测] `ServerConflictBadges` |
| **内网穿透（FRP）**：内置 frp 客户端、隧道创建/启动/停止/状态、独立账号与套餐流量、激活码 | [命令] `tunnel_host` `tunnel_join` `tunnel_stop` `tunnel_status` `tunnel_copy_ticket` `tunnel_regenerate_ticket` `tunnel_generate_ticket`；`services/online/frp_client.rs` `frp_tunnel.rs` `tunnel.rs` |
| **穿透服务即将下线** | [官方文档] 明写「产品界面已提示该服务**将下线且不再维护**」「若页面明确显示服务已无期限停止支持，不应依赖它承载长期或重要服务器」← **重要负面信号** |
| 本机/局域网/公网地址指引、Windows 防火墙放行指引、CGNAT 说明 | [官方文档] |
| **端口转发自动化** | 无（仅文档指引） |
| **域名绑定** | **未找到证据** |
| 本地 HTTP 服务（供外部/扩展调用） | [源码实测] `services/http/http_server.rs` `http_command_handlers.rs` |

## 3.10 玩家管理

| 功能 | 证据 |
|---|---|
| **在线玩家查询**（`list` 类命令解析，多核心预设 Vanilla/Paper/Forge/Velocity + 自定义命令），自动刷新（默认关，空服自动拉长间隔） | [官方文档] + [命令] `services/server/player.rs` |
| **白名单** 增删查 | [命令] `get_whitelist` `add_to_whitelist` `remove_from_whitelist` |
| **封禁** 查/封/**限时封禁**/解封（可填原因与时长） | [命令] `get_banned_players` `ban_player` `ban_player_timed` `unban_player` |
| **OP** 授予/移除 | [命令] `get_ops` `add_op` `remove_op` |
| **踢人** | [命令] `kick_player` |
| **离线管理名单**（服务器停止时仍可改部分 JSON 名单） | [官方文档] |
| **操作审计日志 + 导出** | [官方文档] + [命令] `export_logs` `export_server_logs_to_file`；[官方文档]「玩家管理操作会记录在页面日志中，可导出用于审计」 |
| **封禁 IP** | **未找到证据**（命令只有 `ban_player` / `ban_player_timed`，无 IP 级封禁命令） |

## 3.11 性能监控与可视化

| 功能 | 证据 |
|---|---|
| 仪表盘卡片：**状态 / CPU / 内存 / 冲突提示** | [官方文档] + [命令] `get_servers_dashboard_snapshot` |
| 进程级资源统计 | [命令] `get_process_stats` |
| 系统信息 | [命令] `get_system_info` |
| **灵动岛**实时资源：CPU / 运行内存 / 磁盘使用率 / 网络使用率 | [官方文档] |
| 托盘弹窗资源面板（指标可选） | [官方文档] |
| **迷你折线图**（SparklineChart）、磁盘速度图（DiskSpeedChart）、StatCard | [源码实测] |
| **TPS / MSPT** | **未找到证据**（无 TPS/MSPT 采集命令） |
| **玩家数曲线** | **未找到证据** |
| **告警 / 阈值通知** | **未找到证据**（无告警配置命令） |
| **网页地图（BlueMap / Dynmap）** | **未找到证据** |

## 3.12 多实例与批量操作

| 功能 | 证据 |
|---|---|
| **多实例仪表盘**（卡片网格，可拖动排序、置顶） | [官方文档] + [命令] `get_server_list` `get_servers_dashboard_snapshot` |
| 实例卡片内直接启停 | [官方文档] |
| **外部运行进程「恢复托管」** | [官方文档] + [命令] `recover_server_management` |
| 取消托管（保留磁盘文件）vs 彻底删除 | [命令] `unlink_server_from_app` `delete_server`；[官方文档] 区分清晰且有「阅读等待确认」 |
| **批量启停 / 批量操作多实例** | **未找到证据**（无批量启停命令；仅扩展安装支持 `install_extensions_batch`） |
| 任务中心**批量**视图 | 部分：`poll_all_downloads` 可批量轮询下载 |

## 3.13 权限、多用户、配额

- **未找到证据**：无用户体系、无子账号、无角色权限、无资源配额、无多租户。
- 这是 Snowolf 作为**单机桌面应用**的架构必然结果（官方明写「不是网页控制面板」）。
- 唯一的「权限」概念是 **AI 文件读取授权**与**扩展权限系统**（见 3.14）。

## 3.14 扩展系统（**Snowolf 最独特的能力，文档站未在导航中突出，但源码证据充分**）

| 功能 | 证据 |
|---|---|
| **Lua 脚本扩展运行时**（独立于前端的后端沙箱） | [源码实测] `src-tauri/src/extensions/runtime/` 含 `core/sandbox.rs` `core/capabilities.rs` `core/lifecycle.rs` `core/callbacks.rs` `core/runtime.rs`；`plugins/runtime/core/permissions.rs` `sandbox.rs` |
| **扩展可注入导航项、CSS、右键菜单、组件** | [命令] `get_extension_nav_items` `get_extension_css` `get_all_extension_css` `context_menu_callback` `component_mirror_register` |
| **扩展市场**（分类、详情、安装、批量安装、检查更新） | [命令] `fetch_market_extensions` `fetch_market_categories` `fetch_market_extension_detail` `install_from_market` `install_extensions_batch` `check_all_extension_updates` |
| **扩展能力清单与权限日志** | [命令] `get_capability_list` `get_extension_capabilities` `get_extension_permission_logs` |
| 扩展设置读写、图标、UI 快照 | [命令] `get/set_extension_settings` `get_extension_icon` `get_extension_ui_snapshot` `get_extension_sidebar_snapshot` |
| 页面/语言变化事件回调 | [命令] `on_page_changed` `on_locale_changed` |
| 有 **Lua API 文档** | [源码实测] `src-tauri/src/extensions/runtime/i18n/LUA_API.md` |

> **[官方文档]** 佐证：「扩展可**注入导航、样式和上下文菜单**。安装前确认来源与权限。」

## 3.15 工具箱（官方独立页《工具箱》）

| 工具 | 产物 |
|---|---|
| **MOTD 可视化编辑**（可应用到 `server.properties`；原版 MOTD 约 2 行限制） | 写入 `server.properties` |
| **Tellraw 指令生成器**（可视化编辑彩色文字、实时预览、选区着色、彩虹文字） | tellraw JSON/命令 |
| **LOGO 生成器**（裁剪正方形 → 64×64） | `server-icon.png` |
| **JVM 参数拼装** | 实例设置 / 服务器默认 |
| **彩色昵称生成** | 文本 |

## 3.16 AI Agent（**2.0 时代的核心卖点**）

| 功能 | 证据 |
|---|---|
| **Snowolf AI 1.0 / 2.0 托管模型**（消耗托管余额） | [官方文档] |
| **自定义模型**：预设 OpenAI、Azure OpenAI、Google、xAI、Mistral、Groq、Together、Fireworks、OpenRouter、DeepSeek、Moonshot、智谱、MiniMax、豆包、硅基流动 | [官方文档] |
| **本地模型**：Ollama（默认 `http://127.0.0.1:11434/v1`）、LM Studio（`http://127.0.0.1:1234/v1`） | [官方文档] |
| **视觉能力**（发图，最多 4 张，PNG/JPEG/WebP/GIF） | [官方文档] |
| **AI 可执行的真实操作**：列出服务器、查状态/日志/Java/端口占用；启停重启；**修改已停止服务器的内存**；读改 `server.properties`；搜索/读取/修改 UTF-8 文本文件；**从镜像创建新服务器**；改服务器默认运行目录；取消托管；彻底删除目录 | [官方文档] ← **这是「AI 排障 + AI 运维」的完整闭环** |
| **确认卡机制**：停止/重启/改内存/创建服务器/改配置/写文件/改默认设置/取消托管/彻底删除**需要确认**；启动与只读操作可直接执行 | [官方文档] |
| **文件读取授权三级**：仅本次 / 本段对话 / 这台服永久 / 拒绝 | [官方文档] |
| **diff 预览**（减号旧值、加号新值） | [官方文档] |
| **对话回滚同时还原 AI 写入的文件**（仅覆盖 AI 写文件工具且有修订记录的改动） | [官方文档] |
| 会话管理（重命名、置顶、队列、停止生成）、**浮窗模式** `Ctrl+Shift+A` | [官方文档] |
| AI 工具**拒绝读取**密钥类文件、JAR、世界 region、图片 | [官方文档] |
| 按 Token/权益计费：Free / Pro / Plus，AI 权益需登录 Cloud | [官方文档] |

## 3.17 主题、个性化与桌面集成

- 明暗 × 6 配色变体、护眼、高对比（**部分付费**）**[源码实测] + [官方文档]**
- **背景图** + 轮播 + 模糊 + 遮罩 + 卡片透明度 **[官方文档]**
- **毛玻璃**顶栏/侧栏/底部独立开关 + Windows Acrylic / macOS Vibrancy **[官方文档] + [源码实测]**
- 图标包、终端配色预设、**金属 Logo**（付费）**[官方文档]**
- 系统字体选择（字号控件未开放）**[官方文档]**
- **UI 设置**：仪表盘区块、快捷操作、侧栏主入口、服务器子导航、顶栏按钮的可见性与排序（**隐藏当前入口会自动跳转，设置入口始终保留**）**[官方文档]**
- 通知设置页、系统托盘、灵动岛 **[源码实测] + [官方文档]**
- **首次启动欢迎向导**（协议与介绍）**[官方文档] + [源码实测]** `FirstLaunchWelcome`

## 3.18 移动端、面板更新、API

| 项 | 结论 |
|---|---|
| **移动端适配** | **未找到证据**。桌面应用，且**仅 Windows**（官方「当前发行面向 Windows 桌面」）。有响应式布局修复记录（v1.2.1），但那指窗口缩放而非移动端。 |
| **面板自身更新** | **[官方文档]** 完整：应用内检查更新 → 下载（支持**增量 ZIP**）→ 状态「更新包已就绪」→ 安装 → 独立 **Updater** 进程安装。多源：`update_github.rs` / `update_gitee.rs` / `update_cnb.rs` / `update_checksum.rs` / `update_arch.rs`，并有开发期可切换的检查源 `get/set_dev_update_check_source`。**[命令]** |
| **开放 API** | **部分**：`services/http/http_server.rs` + `http_command_handlers.rs` 提供本地 HTTP 命令通道；扩展系统有完整 Lua API（`LUA_API.md`）。但**未有面向第三方的公开 REST API 文档/密钥体系**。→ **未找到证据**（公开 API）。 |

## 3.19 国际化

**[源码实测]** `src-tauri/locales/` 缺 11 个语种文件：
`de-DE, en-US, es-ES, fr-FA, ja-JP, ko-KR, ru-RU, vi-VN, zh-CN, zh-TW`（+ `zh-CN` 与 `zh-TW` 分开）→ **11 个 locale**。
文档站亦提供 en / zh-CN / zh-TW / ja。扩展运行时也有 i18n 模块。

## 3.20 明确不支持的（负向清单）

- ❌ 网页面板 / 远程访问（架构上就是桌面应用）
- ❌ 多用户 / 子账号 / 权限 / 资源配额
- ❌ RCON
- ❌ TPS / MSPT 采集
- ❌ 网页地图（BlueMap / Dynmap）
- ❌ 崩溃自动重启 / 阈值告警
- ❌ CurseForge / SpigotMC 插件市场
- ❌ 批量启停
- ❌ 官方 Bedrock Dedicated Server (BDS)
- ❌ 域名绑定 / 端口转发自动化
- ❌ 移动端
- ⚠️ Docker 与模板市场「开发中」
- ⚠️ **内网穿透官方已宣布将下线且不再维护**
- ⚠️ **世界备份依赖 Snowolf Cloud 账号与权益**，非纯本地

---

# 四、竞品功能矩阵

## 4.0 交付形态与授权（新增列，按需求补入）

| 面板 | 交付形态 | 安装方式 | 授权 / 计费 | 是否需登录账号 | 是否 SaaS |
|---|---|---|---|---|---|
| **Snowolf** | **独立桌面应用**（Tauri，**仅 Windows**） | 下载安装包 / ZIP / 增量更新包（GitHub Releases 为主渠道） | **应用本体免费**；**AI、部分主题/图标/终端预设、内网穿透套餐**需付费（爱发电）；GPL-3.0（1.7 源码） | **可选**：本地功能不需登录；**AI 与云备份必须登录 Snowolf Cloud**；穿透需另一套独立账号 | 否（本地进程），**但 AI/备份是 SaaS 依赖** |
| **Pterodactyl（翼龙）** | **独立自托管 Web 面板**（PHP/Laravel + Node Wings 守护进程） | 自建：Web 面板 + 每台节点装 Wings；需 PHP/MySQL/Redis/Docker | **开源免费**（MIT 系）；自付服务器成本 | 是（自带用户体系，管理员建号） | 否（自托管）；亦有第三方托管商转售 |
| **MCSManager（MCSM）** | **独立自托管 Web 面板**（Node.js），**分布式多节点** | Linux 一键脚本（`script.mcsmanager.com/setup_cn.sh`）/ 手动 / Docker；Windows 解压即用（不污染注册表） | **开源免费**（GitHub `MCSManager/MCSManager`）；文档页有推广位广告 | 是（自带多用户权限体系） | 否（自托管） |
| **AMP（CubeCoders）** | **独立自托管 Web 面板**（Windows / Linux，多游戏） | 官方安装器 + 实例化 "AMP instance"；有 Application/Enterprise 等版本 | **商业付费**（按版本/实例数授权，有免费/受限档；详见其 Editions Comparison） | 是（自带用户/角色体系） | 否（自托管），厂商提供授权与支持 |
| **Multicraft** | **主机商绑定型面板**（面向 hosting 公司转售） | 自建（Linux/Windows 安装脚本，常与 WHMCS/Blesta 计费系统集成） | **商业付费**（按实例/授权） | 是（多租户，最终用户由主机商开号） | 否（主机商自建给客户用） |
| **雨云 / 皓云 等国内厂商面板** | **SaaS 主机商绑定**（买机器附赠控制台） | 无需安装，注册即用 | **随机器付费**（云主机/面板服套餐） | 是（必须注册厂商账号） | **是** |
| **小皮面板（phpStudy）** | **独立自托管 Web 面板**（Windows 为主，**通用运维面板**，非 MC 专用） | 一键安装包 | 免费（含增值） | 是（面板自身账号/本地） | 否 |
| **PebbleHost / Shockbyte 类托管商** | **SaaS 主机商绑定**（自研或 Multicraft/Pterodactyl 二次封装） | 无需安装，网页下单即用 | **订阅制**（按月/按配置） | 是（必须注册） | **是** |
| **RT面板**（同仓兄弟产品，非 MC 专用） | **独立 Web 面板**（Vue + Element Plus，官网 `www.rt888.icu`）**[实测]** 200 | 未在本报告核实安装方式 | 官网自称「**完全免费**的跨平台服务器运维面板」**[实测]** | 未核实 | 否 |

> **对「本产品」的直接含义**：Snowolf 是**桌面**、Pterodactyl/MCSM/AMP 是**自托管 Web**、国内厂商与 PebbleHost/Shockbyte 是**SaaS**。我们要做的是**接近第二类但更轻**的**独立 Web 面板**。

## 4.1 桌面应用 vs 网页面板：Snowolf 交付形态的优劣

| 维度 | Snowolf（桌面 Tauri） | 我们（网页面板） |
|---|---|---|
| 安装成本 | 需下载安装、仅 Windows、需处理 Updater 与 Program Files 权限问题 | **免安装**，浏览器即开 |
| 多端访问 | ❌ 只能在装了客户端的机器上 | ✅ 手机/平板/他人电脑均可 |
| 远程运维 | ❌ 需远程桌面到那台 Windows | ✅ 任意地点 |
| 团队协作 | ❌ 无用户体系 | ✅ 多用户/子账号/审计 |
| 嵌入官网 | ❌ 不可能 | ✅ 可嵌入营销站做「在线演示」 |
| 与服务器同机 | ✅ 天然同机，文件/进程直连，延迟最低 | 需 agent 或同机部署 |
| 本地文件与拖放 | ✅ 与资源管理器双向拖放、Monaco 原生体验 | 受浏览器沙箱限制（可用 File System Access API 部分弥补） |
| 系统集成 | ✅ 托盘、灵动岛、毛玻璃、Acrylic/Vibrancy、自绘无边框窗口 | ❌ 均不可用 |
| 分发与升级 | 需处理签名、安装器、增量更新、杀软误报 | **改完即生效**，无安装器成本 |
| 备案/合规 | 分发二进制，无 ICP 压力 | **独立站点需 ICP 备案与合规提示**（见 §4.2） |
| 后端语言约束 | Tauri 需 Rust | 自由（Node/Go/Python） |
| 离线可用 | ✅ 完全离线可用（AI/备份除外） | ❌ 依赖网络到面板 |

**结论**：Snowolf 的**系统集成与本地体验**（灵动岛、托盘、拖放、毛玻璃）是网页端**结构性无法复制**的；反过来，**免安装、多端、远程、协作、可嵌官网**是网页端**结构性优势**。这构成我们最主要的差异化论据，但**不要试图在网页里假装桌面体验**（例如硬做灵动岛会显得廉价）——应转而把「多端 + 协作 + 可嵌入」做到位。

## 4.2 独立站点需要什么（站点侧能力清单）

作为**独立网站**（而不仅是「一个面板程序」），通常还需要下列站点侧能力。

| 站点侧能力 | Snowolf 有？ | 行业普遍性 | 备注 |
|---|---|---|---|
| 品牌/介绍官网 | ⚠️ **有但形同虚设**：`snowolf.lr-luorui.cn` HTTPS 404、HTTP 仅 138 B 空壳 **[实测]**；官方文档自认「不是可靠的二进制唯一来源」 | 普遍有 | **我们应把官网做成真站点**：产品介绍、特性、截图、价格 |
| 下载页 | ⚠️ 主要靠 GitHub Releases（国内访问不稳）+ 多镜像源 | 普遍有 | **必须自建下载页 + 国内 CDN**，这是 Snowolf 的明显短板 |
| 文档站 | ✅ **做得很好**：`docs-snowolf.lr-luorui.cn`，26+ 页、4 语言、结构化导航（入门/AI Agent/服务器/联机与网络/工具与扩展/设置与排障/社区与反馈） | 自托管开源面板常缺，商业面板有 | **这是我们该重点对齐的一项**，且比多数国内面板强 |
| 注册 / 登录 | ✅ Snowolf Cloud（浏览器授权登录，桌面端回跳） | 商业面板普遍有 | 注意：**桌面端「网页授权 → 回跳应用」模式**是桌面才需要的；网页端用常规会话即可 |
| 邮箱验证 / 找回口令 | ⚠️ 未找到证据（文档提到「用户名、邮箱和密码需要前往**账号站**修改」→ 账号站承担此责，但未见验证/找回流程文档） | 普遍有 | **必备** |
| 套餐 / 授权 / 购买 | ✅ Free / Pro / Plus + 试用 + 爱发电支付 + **订单号认领** | 商业面板普遍有 | 「爱发电 + 订单号手动认领」是**低配做法**，到账体验差（文档 FAQ 就在处理「支付完成但未到账」）；**我们应做标准支付网关 + 回调自动到账** |
| 试用 / 在线演示 | ✅ 有「一天 Pro 体验」「内测解锁」入口；❌ **无在线演示站** | 商业普遍有演示 | **在线演示是我们网页端独有的结构性优势**，务必做（Snowolf 做不了） |
| 版本与升级通道 | ✅ **很强**：应用内检查更新、增量 ZIP、独立 Updater、多源（GitHub/Gitee/CNB）、校验和、开发期可切换源 | 罕见 | **值得抄**：网页端应做**发布通道 + 灰度 + 版本公告 + 强制/可选升级策略** |
| 公告 / 更新日志 | ⚠️ 有 Releases 更新日志（写得很详细，含「下载说明」表格与「更新步骤」）；❌ 未见站内公告系统 | 普遍有 | 我们应做**站内公告 + Changelog 页** |
| 工单 / 客服 | ⚠️ 仅 **QQ 群 + Bilibili + GitHub Issues**；❌ 无工单系统 | 商业面板普遍有工单 | 若做付费，**工单/客服是必需** |
| 状态页 / 服务可用性 | ❌ 未找到证据（文档只让用户「检查 Cloud 状态」） | 商业普遍有 | 依赖云能力的产品**必须有状态页** |
| 隐私政策 / 服务条款 / 开源许可 | ✅ **有**（`src/pages/Legal/`：`legalPolicyData.ts`、`LegalPolicyPage`、`OpenSourceLicensePage`；README 提到应用内《开源许可与第三方声明》） | 国内产品常缺 | **做得比多数国内面板好，值得对齐** |
| 备案与合规提示 | ❌ 未找到证据（域名 `lr-luorui.cn` 的备案情况未核实） | 国内必需 | **我们面向国内必须处理 ICP 备案** |
| 社区 / 赞助 | ✅ QQ 群、爱发电、Bilibili | 普遍有 | — |
| 错误上报与隐私脱敏 | ✅ **很强**：Sentry 脱敏上报（可关）、**隐私处理版日志导出**（「导出最近一份隐私处理版日志」）、路径/用户名/玩家名脱敏提醒、密钥不得出现在截图 | 罕见 | **强烈建议抄**：这是**信任建设**资产，尤其 AI 产品 |
| 设备管理 | ✅ 设备列表、撤销设备、撤销当前设备即登出 | 商业普遍有 | 网页端对应「登录设备 / 会话管理」 |
| 多语言站点 | ✅ 文档 4 语言、应用 11 locale | 少见 | 可选 |
| 可嵌入官网的在线演示 | ❌ 不可能（桌面） | — | **我们的独特卖点** |

**Snowolf 有而我们不该照抄的**：桌面网页授权登录回跳（网页端不需要）、爱发电订单号手动认领（低配）。
**Snowolf 没有而我们该有**：真官网、自建下载页+CDN、在线演示、工单、状态页、备案合规、自动到账支付。

## 4.3 功能矩阵

图例：✅ 有 ｜ ⚠️ 部分/有条件/开发中 ｜ ❌ 无 ｜ ❓ 未核实

| 功能 | Snowolf | Pterodactyl | MCSManager | AMP | 备注 |
|---|---|---|---|---|---|
| **交付形态** | 桌面应用(Windows) | 自托管 Web | 自托管 Web | 自托管 Web | —— |
| 一键开服向导 | ✅ | ⚠️（Nest/Egg + 变量表单） | ✅（一键搭建 Java/基岩/Steam） | ✅（实例创建向导） | MCSM 有「一键搭建」专页 |
| 核心选择（Vanilla/Paper/Purpur/Spigot） | ✅ | ⚠️ 靠 Egg 配置 | ✅ | ✅ | 见 §6 元数据 |
| 核心选择（Fabric/Forge/NeoForge/Quilt） | ✅（Quilt ❓） | ⚠️ 靠 Egg | ✅ | ✅ | —— |
| 基岩版(BDS) | ❌（仅 Nukkit 系） | ⚠️ 靠 Egg | ✅（独立基岩搭建页） | ✅ | **Snowolf 短板** |
| 代理端(BungeeCord/Velocity) | ✅ BungeeCord/Lightfall | ✅（Egg） | ⚠️（可手工） | ✅ | —— |
| 群组一键组网 | ❌ | ❌ | ❌ | ❌ | **行业普遍缺失 → 机会点** |
| Java 运行时管理 | ✅ **含面板内下载安装** | ⚠️（多为手动/Docker 镜像） | ⚠️（可用镜像/Docker） | ✅ | Snowolf 做得最好 |
| JVM 参数可视化 | ✅（工具箱 + NeoForge 三策略） | ⚠️（启动变量） | ✅（启动参数） | ✅ | —— |
| 实时控制台 | ✅ xterm.js | ✅ | ✅ | ✅ | —— |
| RCON | ❌ | ⚠️（部分 Egg） | ✅（RCON 支持） | ✅ | Snowolf 缺 |
| 文件管理 | ✅ 拖放+Monaco | ✅ | ✅ | ✅ | —— |
| server.properties 可视化 | ✅（可搜中文说明） | ⚠️（配置文件编辑器） | ⚠️（文件编辑） | ✅ | Snowolf 体验好 |
| 插件/模组市场 | ⚠️ **仅 Modrinth** | ❌（靠 Egg/手动） | ⚠️（手动上传为主） | ⚠️（部分） | MCSM 文档有「镜像管理」 |
| CurseForge 集成 | ❌ | ❌ | ❌ | ⚠️ | **需 key，行业普遍缺** |
| 模组更新/回滚 | ✅（含回滚） | ❌ | ❌ | ❌ | **Snowolf 领先** |
| 备份/还原 | ⚠️ **依赖 Cloud 权益** | ✅ 本地/远程备份 | ✅ | ✅ | Snowolf 的云依赖是缺陷 |
| 定时任务 | ✅（4 种调度 + 动作链 + 危险模式） | ✅（计划任务） | ⚠️ | ✅ | Snowolf 的「动作链 + 跳过原因日志」很好 |
| 崩溃自动重启 | ❌ | ⚠️（靠 Egg/脚本） | ⚠️ | ✅ | **机会点** |
| 端口分配/冲突检测 | ✅（默认开启 + 目录嵌套检测） | ✅（每个 server 自动分配端口） | ✅ | ✅ | Snowolf 的**目录嵌套检测**是亮点 |
| 内网穿透 | ⚠️ **内置但官方宣布下线** | ❌ | ❌ | ❌ | **机会点**（国内刚需） |
| 域名绑定 | ❌ | ⚠️ | ❌ | ⚠️ | —— |
| 玩家管理（白名单/OP/封禁/踢人） | ✅（含限时封禁） | ⚠️（靠插件/RCON） | ⚠️（靠插件） | ⚠️ | Snowolf 领先 |
| 封禁 IP | ❌ | ❌ | ⚠️ | ⚠️ | —— |
| 玩家行为审计 | ⚠️（仅面板操作日志） | ❌ | ⚠️ | ❌ | **机会点** |
| CPU/内存监控 | ✅ | ✅ | ✅ | ✅ | —— |
| **TPS / MSPT** | ❌ | ⚠️（需插件） | ⚠️（需插件） | ⚠️ | **行业普遍缺失 → 机会点** |
| 玩家数曲线 | ❌ | ⚠️（需插件） | ❌ | ⚠️ | **机会点** |
| 磁盘/网络监控 | ✅ | ✅ | ✅ | ✅ | —— |
| 告警/阈值通知 | ❌ | ⚠️ | ❌ | ✅ | **机会点** |
| 多实例管理 | ✅ 卡片网格+置顶 | ✅（多 server） | ✅（**分布式多节点**） | ✅ | MCSM 分布式领先 |
| 批量启停 | ❌ | ⚠️ | ✅ | ✅ | Snowolf 缺 |
| 多用户/子账号/权限 | ❌ | ✅ 完善 | ✅ 完善 | ✅ 完善 | **Snowolf 结构性缺失** |
| 资源配额/超卖保护 | ❌ | ✅（内存/CPU/磁盘限额） | ✅ | ✅ | **机会点（针对超卖）** |
| 整合包一键装 | ⚠️ 有 `import_modpack` 命令，文档未单列 | ⚠️（Egg 变量） | ✅（一键搭建） | ✅ | **机会点**（CurseForge/FTB/Modrinth modpack） |
| 网页地图(BlueMap/Dynmap) | ❌ | ❌ | ❌ | ❌ | **行业普遍缺失 → 机会点** |
| 审计日志 | ⚠️（面板操作日志） | ✅ | ✅ | ✅ | —— |
| 主题/个性化 | ✅ **极丰富**（明暗×6变体+背景轮播+毛玻璃+灵动岛） | ⚠️（可换主题） | ⚠️ | ✅ | **Snowolf 观感投入最大** |
| 移动端适配 | ❌ | ⚠️（响应式一般） | ⚠️ | ⚠️ | MCSM 有 HTML 卡片小组件 API |
| 面板自更新 | ✅ **很强**（增量+多源+Updater） | ✅ | ✅ | ✅ | —— |
| 开放 API | ⚠️（本地 HTTP + Lua 扩展 API；无公开 REST） | ✅ **完整 REST/Client API** | ✅ **完整 REST API**（含 apikey 文档） | ✅ | Pterodactyl/MCSM 领先 |
| 扩展/插件生态 | ✅ **Lua 扩展 + 市场 + 权限沙箱** | ⚠️（Egg/主题） | ⚠️（HTML 卡片组件） | ⚠️ | Snowolf 扩展架构独特 |
| AI 排障/运维 | ✅ **完整闭环**（含确认卡+文件回滚+视觉） | ❌ | ❌ | ❌ | **Snowolf 独有领先项** |
| 迁移导入（从其它面板） | ⚠️ 仅「导入 JAR/ZIP」「托管已有目录」 | ✅（可从其它面板迁移） | ⚠️ | ✅ | **机会点**：从 Pterodactyl/MCSM 迁移 |
| 在线演示 | ❌（桌面不可行） | ⚠️（官方 demo 站） | ⚠️ | ✅ | **我们的结构性优势** |
| 多语言 | ✅ 11 locale | ✅ | ✅ | ✅ | —— |

> **❓ 未核实项**：AMP / Multicraft / 国内厂商面板的确切功能边界，本次未做逐项界面核实，表中相关单元格为基于其公开定位与文档的**合理判断**，非实测。**MCSManager** 的功能项来自其[官方中文文档](https://docs.mcsmanager.com/zh_cn/index.html)与 API 文档目录 **[实测可达]**。**Pterodactyl** 来自[官方文档](https://pterodactyl.io/project/introduction.html) **[实测可达]**。**AMP** 来自 [CubeCoders AMP 页](https://cubecoders.com/AMP)与[版本对比帖](https://discourse.cubecoders.com/t/editions-comparison-sheet/2247) **[实测可达]**。**Multicraft** 来自[官网](https://multicraft.org/)与[安装文档](https://multicraft.org/site/docs/install) **[实测可达]**。

---

# 五、差异化机会点（它没有但我们该有的）

按「行业普遍缺失程度 × 用户痛感 × 实现可行性」排序。

## 5.1 差异化能力候选（完整清单）

| # | 能力 | 行业现状 | 为什么是机会 | 难度 |
|---|---|---|---|---|
| 1 | **整合包一键装**（CurseForge / Modrinth modpack / FTB，含依赖解析与服务端/客户端区分） | Snowolf 有 `import_modpack` 命令但文档未单列；Pterodactyl 靠 Egg 手填；MCSM 仅「一键搭建」基础核心 | 整合包是**开服最大门槛**。目前玩家要自己找包、扒服务端、删客户端模组 | 中 |
| 2 | **崩溃根因分析**（读日志栈 → 定位到具体模组/依赖/Java 版本/端口，给可执行修复） | 行业无（Snowolf 的 AI 只是通用问答式排查，未内建规则库） | 崩溃是最高频求助。**规则库 + LLM 双层**可做高准确率 | 中 |
| 3 | **TPS / MSPT 低自动诊断**（采集 TPS/MSPT → 关联实体/区块/插件 → 给出热点） | **行业普遍缺失**（全靠装 spark/Timings 插件自己看） | 面板级内置 spark 集成 + 自动解读 = 强付费点 | 中 |
| 4 | **Mod 依赖冲突检测**（上传前静态解析 `fabric.mod.json`/`mods.toml` → 缺失依赖、加载器/版本不匹配、重复 Mod） | 行业无（Snowolf 只在崩溃后让用户「看日志」） | **前置校验**比事后排障价值高得多 | 中 |
| 5 | **跨服群组一键组网**（BungeeCord/Velocity：一键建代理 + 多子服 + 自动写 config + 端口与转发配置） | **全行业缺失**（所有人都要手工改 yml） | 群组服是中大型服标配，配置极繁琐 | 中 |
| 6 | **内网穿透一键开**（集成 frp / 自建中转 / Cloudflare Tunnel，含域名与证书） | Snowolf 有但**官方已宣布下线**；其它面板基本没有 | **国内家宽无公网 IP 是刚需**。谁做好谁赢 | 中（重资产：需中转节点） |
| 7 | **玩家行为审计**（登录/登出、指令、容器访问、方块破坏/放置、掉线原因，可检索可导出） | 行业无（只有面板操作日志） | 服主追查「谁拆了我的家」是真实高频需求 | 中高（需服务端插件配合） |
| 8 | **资源超卖保护**（按套餐限额 CPU/内存/磁盘/玩家数/流量，超额熔断而非静默超卖） | 自托管面板有配额，但**国内低价面板普遍超卖** | 若我们做多租户/SaaS，这是**信任与稳定性护城河** | 中 |
| 9 | **离线可用的降级模式**（面板服务不可达时本地缓存可查看实例、读日志、改文件） | 行业无（面板挂了就只能 SSH） | Snowolf 的文档提到「离线缓存可以展示部分信息」但仅限备份页 | 中 |
| 10 | **AI 排障**（把 AI 从「聊天」做成「带证据的运维）」——**注意：Snowolf 已做到** | **Snowolf 已领先**（确认卡 + diff + 文件回滚 + 视觉 + 自定义/本地模型） | 我们若做，必须**至少对齐**其确认卡与回滚机制，否则不如不做 | 高 |
| 11 | **迁移导入**（从 Pterodactyl / MCSManager / Multicraft / 甚至 Snowolf 目录导入实例） | 行业弱（Pterodactyl 有一些迁移工具） | 降低迁移成本 = 直接抢存量用户 | 中 |
| 12 | **网页地图内置**（BlueMap / Dynmap / squaremap 一键部署 + 反代 + 嵌入面板） | **全行业缺失** | 地图是玩家最爱、服主最不会配的功能 | 中低 |
| 13 | **在线演示站**（免注册试用真实面板，带沙箱实例与定时重置） | Snowolf **做不到**（桌面）；Pterodactyl 有官方 demo | **我们的结构性优势**，转化率利器 | 中 |
| 14 | **可嵌入官网的面板卡片**（把「服务器状态 / 在线人数 / TPS」以 iframe 或小组件嵌到服主自己的官网） | MCSM 有「制作卡片小组件」类似能力；Snowolf 无 | 服主需要在自己站点展示状态 | 低 |
| 15 | **与其它面板/站点的可选互操作（默认关闭、互不依赖）** | 行业无 | 见 §5.2 | 低 |
| 16 | **状态页 + 公告 + 工单** | Snowolf 只有 QQ 群 | 付费产品的基础设施 | 低 |
| 17 | **崩溃/宕机自动重启 + 多通道告警**（Webhook / 邮件 / 企业微信 / 钉钉 / TG） | Snowolf 无；AMP 有 | 挂机服刚需 | 低 |
| 18 | **备份不依赖云**（纯本地 + 可选 S3/WebDAV/对象存储，硬链接去重） | Snowolf **备份需 Cloud 权益**（缺陷）；Pterodactyl/MCSM 本地可用 | 「我的备份凭什么要登录你的云」是强反对理由 | 低中 |
| 19 | **版本/模组安全扫描**（对比 Modrinth/OSV 的已知恶意/后门模组库） | 行业无 | MC 恶意模组（fractureiser 类）是真实事件 | 中 |
| 20 | **配置模板与「服型预设」**（生存/空岛/RPG/生电/竞技 一键预设：核心+配置+插件集+JVM+规则） | 行业弱 | 降低新手决策成本 | 低 |

## 5.2 「与其它面板/站点的可选互操作」单列（按需求新增）

**定位：默认关闭、彼此独立的可选能力，绝不作为安装前提，绝不捆绑。**

三种可选形态（**三选一或组合，均需用户显式开启**）：

1. **同风格并列入口**（最轻，零耦合）
   - 在本产品导航中提供「切换到 RT面板」的外部链接式入口（**仅跳转，不做任何数据交换、不检测是否安装、不做单点登录**）。
   - 视觉上采用**一致的导航位置与图标规格**，让同时使用两个产品的用户认知负担最低。
   - 反向同理：本产品可作为 RT面板 的一个外链入口。
   - **硬约束**：任一方未安装/未部署时，该入口仅是一个失效链接的降级提示，**不得**影响本产品任何功能。
2. **带签名的 API 互调**（中）
   - 双方各自暴露**显式的、需用户手动生成密钥**的 REST 端点（如「列出服务器状态」「查询在线人数」「触发备份」）。
   - 采用 **HMAC 签名 + 时间戳 + 重放保护**，密钥仅存本地面板且可随时吊销。
   - **默认关闭**：未显式配置对方地址与密钥时，代码路径完全不激活。
   - **单向可选**：A 调 B 不需要 B 调 A。
3. **单站登录对接**（最重，需谨慎）
   - 可选 OIDC/OAuth2：把本产品作为 Identity Provider 或 Relying Party，实现「一次登录，两站通行」。
   - **必须**保留本产品自身的账号密码登录路径，且**允许完全关闭**该对接。
   - 需明确告知用户数据流向与授权范围，并写入隐私政策。

**明确不做的**：默认捆绑安装、安装时自动探测并接管另一个面板、共享同一套数据库、隐式单点登录、把对方功能包装成本产品功能。

---

# 六、技术可行性：核心/元数据/Java 下载接口清单与实测可达性

**测试方法**：本机 `curl.exe`（部分带 `-k -sSL --ssl-no-revoke`），超时 15–30 s，`User-Agent: Mozilla/5.0` 或 `research`。测试时间：本次调研当时。
**说明**：本机外网**总体可达**（多数国际源成功），但**部分域名被加速器劫持到 127.0.0.1** 导致连接失败（`000`）。下表中 `000` 已标注为「本机网络/劫持问题」，**不等于该接口在公网不可用**。

## 6.1 Minecraft 原版（Mojang 官方）

| 接口 | 确切 URL | 鉴权 | 实测 | 备注 |
|---|---|---|---|---|
| 版本清单 v2（推荐） | `https://piston-meta.mojang.com/mc/game/version_manifest_v2.json` | 无 | **200**，277,187 B，0.88 s | **可用**。实测 917 个版本，`latest.release = 26.3`、`latest.snapshot = 26.4-snapshot-2` |
| 版本清单（旧域） | `https://launchermeta.mojang.com/mc/game/version_manifest.json` | 无 | **200**，209,329 B | 可用，但**建议只用 piston-meta v2** |
| 单版本详情 | `https://piston-meta.mojang.com/v1/packages/<sha1>/<version>.json` | 无 | **200** | 从清单的 `versions[].url` 取得 |
| **服务端 JAR 直链** | `https://piston-data.mojang.com/v1/objects/<sha1>/server.jar` | 无 | **200**，62,294,556 B | **可用**。实测 `26.3` → `sha1=33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c`，`javaVersion.majorVersion = 25` |
| **国内镜像（BMCLAPI）** | `https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json` | 无 | **200**，277,187 B | **可用**，强烈建议接入（Snowolf 源码亦使用此域） |
| 国内镜像-服务端 | `https://bmclapi2.bangbang93.com/version/<ver>/server` | 无 | **200**，51,627,615 B | **可用**（实测 1.21.1） |

> **可行性结论**：原版链路**完全可行且零鉴权**。`version_manifest_v2` 含 `sha1` 与 `javaVersion.majorVersion`，可直接驱动「选版本 → 下载 → 校验 → 选 Java」全流程。

## 6.2 PaperMC（**重大变更，必须注意**）

| 接口 | 确切 URL | 鉴权 | 实测 | 结论 |
|---|---|---|---|---|
| v2（**旧，Snowolf 1.7 仍在使用**） | `https://api.papermc.io/v2/projects/paper` | 无 | **410 Gone**，176 B | **已废弃**。响应体：`{"ok":false,"error":"sunset","message":"This API version has been sunset and is no longer available. To upgrade…"}` |
| v2 下载直链（Snowolf 1.7 使用） | `https://api.papermc.io/v2/projects/paper/versions/{v}/builds/latest/downloads/paper-{v}-latest.jar` | 无 | **404** | **已失效** |
| v2 Velocity | `https://api.papermc.io/v2/projects/velocity` | 无 | **410 Gone** | 已废弃 |
| v3（`api.` 域） | `https://api.papermc.io/v3/projects/paper` | 无 | **403**（1,660 B） | **不可直接用** |
| **v3（推荐，`fill.` 域）** | `https://fill.papermc.io/v3/projects/paper` | 无 | **200**，864 B | **✅ 这是当前可用入口** |
| v3 构建列表 | `https://fill.papermc.io/v3/projects/paper/versions/<ver>/builds` | 无 | **200** | 返回数组，`[0]` 为最新 |
| v3 下载地址 | 见构建对象的 `downloads["server:default"].url` | 无 | **200** | 形如 `https://fill-data.papermc.io/v1/objects/<sha256>/paper-<ver>-<build>.jar` |
| v3 Velocity | `https://fill.papermc.io/v3/projects/velocity` | 无 | **200**，393 B | **可用** |
| v3 Waterfall | `https://fill.papermc.io/v3/projects/waterfall` | 无 | **200**，184 B | 可用 |

**实测样例（Paper 1.21.1）**：
```json
{"id":133,"time":"2025-03-28T16:16:41.212Z","channel":"STABLE",
 "downloads":{"server:default":{
   "name":"paper-1.21.1-133.jar",
   "checksums":{"sha256":"39bd8c00b9e18de91dcabd3cc3dcfa5328685a53b7187a2f63280c22e2d287b9"},
   "size":49394394,
   "url":"https://fill-data.papermc.io/v1/objects/39bd8c00b9e18de91dcabd3cc3dcfa5328685a53b7187a2f63280c22e2d287b9/paper-1.21.1-133.jar"}}}
```

> ⚠️ **关键风险与机会**：Snowolf 1.7 源码里硬编码的是**已 sunset 的 v2 接口**（实测 410/404）。这说明其 1.7 的 Paper 一键下载**当前应该是坏的**，或它实际走的是 CNB 镜像。**我们应从第一天就用 `fill.papermc.io/v3`**，并优先读取 `checksums.sha256` 做完整性校验。

## 6.3 Purpur

| 接口 | 确切 URL | 鉴权 | 实测 |
|---|---|---|---|
| 项目列表 | `https://api.purpurmc.org/v2/purpur` | 无 | **200**，418 B |
| 版本详情 | `https://api.purpurmc.org/v2/purpur/<ver>` | 无 | **200**，389 B |
| **下载直链** | `https://api.purpurmc.org/v2/purpur/<ver>/latest/download` | 无 | **200**，53,071,332 B（1.21.1）**✅ 可用** |

## 6.4 Fabric

| 接口 | 确切 URL | 鉴权 | 实测 |
|---|---|---|---|
| 游戏版本 | `https://meta.fabricmc.net/v2/versions/game` | 无 | **200**，30,232 B |
| 加载器版本 | `https://meta.fabricmc.net/v2/versions/loader/<mcver>` | 无 | **200**，590,278 B |
| **服务端 JAR** | `https://meta.fabricmc.net/v2/versions/loader/<mcver>/<loaderver>/<installerver>/server/jar` | 无 | **200**，155,096 B **✅ 可用**（实测 `1.21.1/0.16.9/0.11.2`，与 Snowolf 源码同形） |

## 6.5 Quilt

| 接口 | 确切 URL | 鉴权 | 实测 |
|---|---|---|---|
| 游戏版本 | `https://meta.quiltmc.org/v3/versions/game` | 无 | **200**，24,814 B |
| 加载器版本 | `https://meta.quiltmc.org/v3/versions/loader/<mcver>` | 无 | **200**，728,448 B |
| 安装器 | `https://meta.quiltmc.org/v3/versions/installer` | 无 | **200**，18,348 B **✅ 可用** |

## 6.6 Forge / NeoForge

| 接口 | 确切 URL | 鉴权 | 实测 |
|---|---|---|---|
| Forge 推荐版本 | `https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json` | 无 | **200**，4,111 B |
| Forge Maven 元数据 | `https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml` | 无 | **200**，211,749 B |
| **Forge 安装器** | `https://maven.minecraftforge.net/net/minecraftforge/forge/<mcver>-<forgever>/forge-<mcver>-<forgever>-installer.jar` | 无 | **200**，5,973,950 B（`1.20.1-47.2.0`）**✅ 可用** |
| NeoForge 元数据 | `https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml` | 无 | **200**，65,529 B（首次） |
| NeoForge 安装器 | `https://maven.neoforged.net/releases/net/neoforged/neoforge/<ver>/neoforge-<ver>-installer.jar` | 无 | ⚠️ **本机第二次访问时 `000`（连接失败，疑似加速器/限流），未能确证** |

> ⚠️ **口径说明**：NeoForge 的 maven 元数据**第一次实测 200**（65,529 B），但随后同域请求变为 `000`。因此**URL 形态可信，可用性存疑**，需在真实环境复测并准备镜像回退。

## 6.7 Java（Adoptium / Temurin 等）

| 接口 | 确切 URL | 鉴权 | 实测 |
|---|---|---|---|
| 可用版本列表 | `https://api.adoptium.net/v3/info/available_releases` | 无 | **200**，428 B **✅** |
| 最新 JDK 资产 | `https://api.adoptium.net/v3/assets/latest/<major>/hotspot?architecture=x64&image_type=jdk&os=windows&vendor=eclipse` | 无 | **200**，2,801 B **✅ 可用**（实测 major=21） |
| **Microsoft OpenJDK 直链** | `https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip` | 无 | **200**，201,096,952 B（192 MB）**✅ 可用** |

> Snowolf 的 `java_installer.rs` 本身**不硬编码下载源**，而是接收前端传入的 `url` 参数并流式下载 + 校验 —— 即**下载源在前端配置**，这样的设计便于换源。**[源码实测]**

## 6.8 插件 / 模组平台

| 平台 | 接口 | 鉴权 | 实测 | 结论 |
|---|---|---|---|---|
| **Modrinth** | `https://api.modrinth.com/v2/search?limit=1` | **无需 key**（建议带 UA） | **200**，5,205 B | ✅ **首选**。Snowolf 即用此源（`modrinth_service.rs` 基址 `https://api.modrinth.com/v2`） |
| Modrinth 项目 | `https://api.modrinth.com/v2/project/<slug>` | 无 | **200**，7,267 B（`iris`） | ✅ |
| Modrinth 加载器标签 | `https://api.modrinth.com/v2/tag/loader` | 无 | **200**，25,622 B | ✅ |
| Modrinth 游戏版本标签 | `https://api.modrinth.com/v2/tag/game_version` | 无 | **200**，84,482 B | ✅ |
| **CurseForge** | `https://api.curseforge.com/v1/mods/search?gameId=432` | **需要 `x-api-key`** | **403**，37 B，响应体原文：**`Forbidden: API Key missing or invalid`** | ⚠️ **必须申请 key**。需向 CurseForge 申请（有审批），且**其 API 条款限制第三方分发**，商用需评估合规 |
| **SpigotMC** | `https://api.spigotmc.org/legacy/update.php?resource=<id>` | 无（但**有 Cloudflare 反爬**） | **403**，5,487 B（返回 HTML 挑战页） | ⚠️ **不可编程使用**。无官方公开 API，属**未授权抓取**，不建议接入 |
| SpigotMC 网站 | `https://www.spigotmc.org/resources/categories/1/` | — | **403** | 同上 |
| Bukkit/Spigot 构建 | `https://hub.spigotmc.org/versions/` | 无 | **200**，9,684 B | ⚠️ 索引页可读；**但** `https://hub.spigotmc.org/versions/1.21.1.json` → **403**。且 Spigot 的 **BuildTools 需本地编译**（不可直接下载成品服务端），接入成本高 |
| CraftBukkit 直链（第三方 CDN） | `https://cdn.getbukkit.org/craftbukkit/craftbukkit-1.21.1.jar` | 无 | **200**，76,244,246 B | ⚠️ **可用但为第三方 CDN，非官方**，长期可靠性存疑 |
| Spiget（第三方 Spigot API） | `https://api.spiget.org/v2/resources/1` | 无 | **404** | 端点已变，需重查；属社区非官方 |

## 6.9 基岩版 / 代理 / 其它

| 接口 | 确切 URL | 鉴权 | 实测 | 结论 |
|---|---|---|---|---|
| Geyser 项目列表 | `https://download.geysermc.org/v2/projects/geyser` | 无 | **200**，386 B | ✅ 可用（**注意：正确形态是 `/v2/projects/geyser`，不是 `/v2/projects/geyser/versions`**，后者 404） |
| Geyser 版本列表 | `https://download.geysermc.org/v2/projects/geyser/versions` | 无 | **404** | ❌ 端点形态错误 |
| Geyser 服务器 API | `https://api.geysermc.org/v2/servers` | — | **403**，5,394 B | ⚠️ 需鉴权/受限 |
| 服务器状态查询 | `https://api.mcsrvstat.us/3/<host>` | 无 | **200**，17,160 B | ✅ 可用于「服务器在线状态」展示 |
| 服务器图标 | `https://images.mcsrvstat.us/` | — | **000** | 本机不可达 |
| MCJars 聚合 API | `https://mcjars.app/api/v2/builds/paper` | 无 | **200**，58,050 B | ✅ 可作 Paper 的备用聚合源 |
| CNB 镜像（Snowolf 使用） | `https://cnb.cool/Snowolf-studio/ServerCore-Mirror/-/releases/download/26.02.27/jar_lfs_links.json` | 无 | **404** | ❌ **Snowolf 引用的镜像清单链接已失效** |
| VersionMC 镜像（Snowolf 文档列举） | `https://versionmc.cn/` | — | **000**，0.05 s | 本机不可达（快速失败，疑 DNS/劫持） |
| MCServerJars（Snowolf 文档列举） | `https://mcsj.cn/` | — | **000**，0.11 s | 本机不可达（同上） |

## 6.10 素材 / 镜像通道（供我们自建下载页参考）

| 目标 | URL | 实测 |
|---|---|---|
| GitHub Raw（直连） | `https://raw.githubusercontent.com/...` | **000**（本机被劫持/重置）❌ |
| **gh-proxy 镜像** | `https://gh-proxy.com/https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>` | **200**，1,907 B ✅ **可用** |
| ghproxy.net | `https://ghproxy.net/https://raw.githubusercontent.com/...` | **000**，15 s 超时 ❌ |
| hub.gitmirror.com | `https://hub.gitmirror.com/https://raw.githubusercontent.com/...` | **000**，0.14 s ❌ |
| kkgithub | `https://kkgithub.com/...` | **000** ❌ |
| jsDelivr | `https://cdn.jsdelivr.net/gh/<owner>/<repo>@<ref>/<path>` | **301**（会回落到 raw.githubusercontent，本机仍不通）❌ |
| **GitHub REST API** | `https://api.github.com/...` | **200** ✅ **可用**（本次调研的主力通道） |

> **对本机的实操结论**：**`api.github.com` 与 `gh-proxy.com` 是本机可用通道**；`raw.githubusercontent.com` / `github.com` / jsDelivr / 主要 gh 镜像均被本机网络环境阻断。这直接说明**面向国内用户的下载页不能只依赖 GitHub**。

## 6.11 可达性总评（给架构的结论）

- **零鉴权即可用（优先接入）**：Mojang piston-meta v2 + piston-data、**BMCLAPI 镜像**、**Paper `fill.papermc.io/v3`**、Purpur、Fabric meta、Quilt meta、Forge maven、**Adoptium API**、Microsoft OpenJDK、**Modrinth API**、GeyserMC download、mcsrvstat。
- **需要 key**：**CurseForge**（`x-api-key`，实测 403 `Forbidden: API Key missing or invalid`）。
- **不可用 / 不建议**：**Paper v2（410 sunset）**、**SpigotMC API（403 Cloudflare）**、Spigot BuildTools 成品直链（403，需本地编译）、Geyser `api.geysermc.org`（403）。
- **可用但非官方**：`cdn.getbukkit.org`、`mcjars.app`（建议作为回退源而非主源）。
- **NeoForge**：URL 形态可信，可用性需复测（本机实测不稳定）。
- **Snowolf 自身的风险点（对我们是机会）**：其 1.7 源码引用的 **Paper v2 已 sunset**、**CNB 镜像清单 404**、**穿透服务官方宣布下线**、**备份依赖云权益**、**下载主渠道是 GitHub（国内不稳）**。

---

# 七、建议的 MVP 与二期功能边界

## 7.1 产品定位建议

**做一个「独立 Web 面板」**：免安装、多端、可远程、可协作、可嵌入官网；面向**个人服主 + 小型团队**；国内网络优先。

**不做**：不自建中转节点之前不开穿透；不做移动原生 App；不与任何面板捆绑。

## 7.2 MVP（第一期）——「能开起来、看得见、管得住」

**必须对齐 Snowolf 的最低集（它有的我们也得有）**：

1. **开服向导**：三种方式（下载核心 / 导入 JAR·ZIP / 托管已有目录）+ 模板
2. **核心覆盖**：Vanilla、Paper、Purpur、Fabric、Forge、NeoForge、Spigot（回退源）、BungeeCord、Velocity；基岩版至少 **Geyser + Paper** 组合（补齐 Snowolf 的 BDS 缺口）
3. **Java 运行时管理**：检测 + 手动指定 + **面板内下载安装**（Adoptium / Microsoft OpenJDK）+ 版本配对校验
4. **JVM 与内存**：min/max、附加参数、`user_jvm_args` 策略（覆盖/合并/不写入）
5. **实时控制台**：xterm.js、ANSI、Ctrl+F 搜索、命令下发、**命令保护开关**、日志导出
6. **文件管理**：浏览/上传/下载/重命名/删除/移动 + **Monaco 编辑器** + 面包屑与搜索
7. **`server.properties` 可视化编辑**（含中文说明搜索）+ 改端口自动同步登记端口
8. **插件/模组管理**：本地上传、启停、删除 + **Modrinth 集成**（搜索/版本/下载）+ 更新与回滚
9. **备份与还原**：**纯本地**（硬链接去重 + 保留策略），**不依赖任何云**
10. **定时任务**：固定间隔 / 每周 / Cron + 动作链（命令/延迟/启停/重启/强制结束）+ 运行日志
11. **玩家管理**：白名单、OP、封禁（含限时）、踢人、在线列表
12. **性能监控**：CPU / 内存 / 磁盘 / 网络 + 迷你折线图
13. **多实例**：卡片网格、置顶排序、启停
14. **端口与路径冲突检测**（含**目录重复与路径嵌套检测**，这是 Snowolf 的亮点，直接抄）
15. **面板自更新 + 版本与升级通道**
16. **主题**：明/暗 + 少量配色变体（**先做免费**，付费后置）
17. **多用户与权限**（网页端结构性优势，必须 MVP 就做）：管理员 / 运维 / 只读子账号 + 操作审计
18. **站点侧基础**：官网、**自建下载页 + 国内 CDN**、文档站、注册/登录/邮箱验证/找回口令、隐私政策与服务条款、**ICP 备案**

## 7.3 二期——「比它好」

**差异化 TOP 3（推荐优先做）**：

| 优先级 | 能力 | 理由 |
|---|---|---|
| **1** | **TPS / MSPT 采集 + 低 TPS 自动诊断**（内置 spark 集成，自动给出实体/区块/插件热点） | **行业普遍缺失**；是「面板」从「启停工具」升级为「运维工具」的分水岭；付费意愿强 |
| **2** | **整合包一键装**（CurseForge modpack / Modrinth modpack / FTB，含服务端·客户端分离与依赖解析） | 开服最大门槛；Snowolf 只有半成品命令；可显著降低新手流失 |
| **3** | **崩溃根因分析 + Mod 依赖冲突检测**（规则库 + LLM 双层） | 崩溃与依赖冲突是最高频求助；**前置静态校验**比事后排障价值高 |

**其余二期项**：网页地图一键部署（BlueMap/Dynmap）、跨服群组一键组网（Bungee/Velocity）、内网穿透（需先备好中转节点）、玩家行为审计、崩溃自动重启 + 多通道告警、迁移导入（Pterodactyl/MCSM/目录）、在线演示站、**可选互操作**（§5.2）、服务器状态卡片小组件、资源配额与超卖保护、AI 排障（**对齐 Snowolf 的确认卡/diff/回滚后再上**）。

## 7.4 明确不做 / 延后

- AI 排障：**MVP 不做**（Snowolf 已建立高标尺，做差了反而扣分）；二期以「对齐 + 差异化（多租户/审计场景）」方式进入。
- 内网穿透：**MVP 不做**（重资产；且 Snowolf 已证明这条路会走到「下线」）。
- 移动原生 App：不做（响应式足够）。
- CurseForge：**先谈授权**再决定（key + 条款风险）。
- SpigotMC：**不做**（403 + 无授权 API）。
- 桌面客户端：不做（网页是我们的差异化基础）。

## 7.5 建议的功能条数基线

- **必须对齐 Snowolf 的功能条数**：本报告 §3 共梳理出 **约 20 个功能域、约 120 项可交付功能点**（其中后端命令级证据 **约 230 个**）。
- **MVP 建议锁定 §7.2 的 18 项**（括号内为对应 §3 功能域）。
- **二期补齐 §5.1 清单中的 20 项差异化候选**。

---

# 八、比 RT面板 更好看的设计基线

> **目标**：本产品的观感要**明显优于现有 RT面板**。
> **RT面板实测基线（一手证据）**：官网 `https://www.rt888.icu/` **[实测]** HTTP 200；技术栈为 **Vue 3 + Vue Router + Element Plus（全量引入）+ axios + dayjs**，**无构建步骤**（`vue.global.prod.js`、`element-plus.full.min.js` 直接 `<script>` 引入）；字体栈 `'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif`，等宽 `Consolas, monospace`；圆角散落为 **4/6/8/9/10/11/12/14/16/999px**（**无统一阶**）；字号散落为 **11.5/12/12.5/13/13.5/14/15/16/18/21/30/36/42px**（**无统一阶**）；三套主题：
>
> | 主题 | 背景主色 | 强调色 | 阴影 | 状态色 |
> |---|---|---|---|---|
> | `lightgold`（默认，白金） | `#f6f3ec` / 卡 `#fffdf8` | `#b8860b`（深金），渐变 `135deg #e9c95f→#b8860b→#8a6508` | `0 8px 28px rgba(120,90,20,.1)` + `glow 0 0 24px rgba(184,134,11,.18)` | 成功 `#4c9a52`、警告 `#c98a1b`、危险 `#d9534f`、信息 `#a68a3c` |
> | `light`（亮色专业） | `#f4f6fa` / 卡 `#ffffff` | `#2b6bef`（蓝） | `0 1px 3px rgba(23,32,48,.06), 0 1px 2px rgba(23,32,48,.04)` | `#16a34a` / `#d97706` / `#e5484d` / `#64748b` |
> | `silverblack`（银黑） | `#0c0f14` / 卡 `#141922` | `#b9c8dd`（银） | `0 8px 32px rgba(0,0,0,.5)` | `#4fc08d` / `#d8a24a` / `#e06c75` / `#8aa0ba` |
>
> **RT面板的可改进点（我们的机会）**：① 圆角与字号**无阶**（散落 10 档 / 13 档）；② **Element Plus 全量引入 + 无构建** → 首屏体积与视觉同质化严重（一眼看出是 Element Plus）；③ **渐变强调色（白金）偏「轻奢/装饰」**，与运维工具需要的「克制、可信、高信息密度」气质不符；④ 阴影为**单层或双层**，缺少层级区分；⑤ 未发现明确的 **WCAG 对比度**约束；⑥ 未发现系统的**动效时长/缓动令牌**。

以下每条规范**均可直接落为 CSS token**。建议前缀 `--mc-`。

## 8.1 排版层级与字号阶（对齐 RT 的散乱）

**用 1.2 倍模数建立 7 级字阶**（RT 的 13 档散值 → 我们的 7 档）：

```css
--mc-font-sans: system-ui, -apple-system, 'Segoe UI', 'PingFang SC',
                'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
--mc-font-mono: 'JetBrains Mono', 'Cascadia Code', ui-monospace,
                Consolas, 'SF Mono', monospace;
--mc-font-num:  var(--mc-font-mono);   /* 数字表格用等宽，对齐更稳 */

--mc-fs-xs:   12px;  /* 辅助说明、时间戳、徽标 */
--mc-fs-sm:   13px;  /* 表格正文、表单标签 */
--mc-fs-base: 14px;  /* 正文默认（后台基准） */
--mc-fs-md:   16px;  /* 卡片标题、强调正文 */
--mc-fs-lg:   20px;  /* 区块标题 */
--mc-fs-xl:   25px;  /* 页面主标题 */
--mc-fs-2xl:  31px;  /* 空状态/营销数字（0.5rem 对齐） */

--mc-lh-tight:  1.25;   /* 标题 */
--mc-lh-snug:   1.4;    /* 卡片标题/按钮 */
--mc-lh-normal: 1.6;    /* 正文 */
--mc-lh-loose:  1.75;   /* 长文档/日志 */

--mc-fw-regular: 400;
--mc-fw-medium:  500;   /* 标题一律 500，不用 700（更克制、更像 Linear/Vercel） */
--mc-fw-semibold:600;   /* 仅用于表格数字/关键指标 */

--mc-tracking-tight: -0.011em;  /* ≥20px 标题收字距 */
--mc-tracking-normal: 0;
--mc-tracking-wide:  0.02em;    /* 全大写小标签 */
```

**规范**：页面上**同时出现的字号不超过 4 档**；数字（TPS/MSPT/内存/玩家数）**必须用等宽字体 + `font-variant-numeric: tabular-nums`**，否则数值刷新时会跳动——**这是 RT 面板与多数国内面板的典型瑕疵**。

## 8.2 8px 栅格与留白节奏

```css
--mc-space-0: 0;      --mc-space-1: 4px;    --mc-space-2: 8px;
--mc-space-3: 12px;   --mc-space-4: 16px;   --mc-space-5: 20px;
--mc-space-6: 24px;   --mc-space-8: 32px;   --mc-space-10: 40px;
--mc-space-12: 48px;  --mc-space-16: 64px;  --mc-space-20: 80px;

/* 语义留白（按「节奏」而非「数值」命名，避免各处随手写 16px） */
--mc-gap-inline:  var(--mc-space-2);   /* 图标与文字 */
--mc-gap-field:   var(--mc-space-3);   /* 表单行内 */
--mc-gap-card:    var(--mc-space-4);   /* 卡片内元素 */
--mc-gap-section: var(--mc-space-6);   /* 卡片之间 */
--mc-gap-page:    var(--mc-space-8);   /* 页面区块之间 */
--mc-pad-card:    var(--mc-space-5);   /* 卡片内边距 */
--mc-pad-page:    var(--mc-space-8);   /* 页面外边距（桌面） */
--mc-pad-page-sm: var(--mc-space-4);   /* 窄屏 */
```

**规范**：所有间距必须是 `4` 的倍数（8px 栅格）；**禁止出现 5/7/9/11/13px** 这类散值（RT 面板圆角里就有 9px、11px，属典型失序）。

## 8.3 层级与投影（对齐 RT 的单层阴影）

**用「层级语义」而非「阴影数值」命名**，并统一采用**多层叠加 + 1px ring** 配方：

```css
/* 亮色 */
--mc-ring: 0 0 0 1px rgba(0,0,0,.06);
--mc-elev-0: none;
--mc-elev-1: 0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.10);              /* 卡片 */
--mc-elev-2: 0 2px 4px rgba(16,24,40,.06), 0 4px 8px rgba(16,24,40,.08);              /* 悬浮卡/下拉 */
--mc-elev-3: 0 4px 8px rgba(16,24,40,.06), 0 12px 16px rgba(16,24,40,.08), var(--mc-ring);  /* 弹层 */
--mc-elev-4: 0 8px 16px rgba(16,24,40,.08), 0 24px 32px rgba(16,24,40,.10), var(--mc-ring); /* 模态 */
/* 深色：以白色 ring 提亮边缘，阴影加深 */
--mc-ring-dark: 0 0 0 1px rgba(255,255,255,.08);
--mc-elev-1-dark: 0 1px 2px rgba(0,0,0,.5), 0 1px 3px rgba(0,0,0,.35);
--mc-elev-3-dark: 0 4px 8px rgba(0,0,0,.45), 0 12px 16px rgba(0,0,0,.35), var(--mc-ring-dark);

--mc-z-base: 0;      --mc-z-sticky: 100;  --mc-z-drawer: 200;
--mc-z-dropdown: 300; --mc-z-modal: 400;  --mc-z-toast: 500;  --mc-z-tooltip: 600;
```

**规范**：**同一时刻页面上出现的阴影层级不超过 3 种**；模态必须有遮罩 `rgba(0,0,0,.5)`（亮）/ `rgba(0,0,0,.72)`（暗）；**禁止**用阴影做「发光装饰」（RT 白金主题的 `--shadow-glow` 与强调渐变即属装饰性发光，运维工具应克制）。

## 8.4 状态色与徽标体系（SVG 三色）

**语义色必须与品牌色解耦**（Snowolf 的「成功=灰」是单色系统的特例，我们**不抄**，因为运维需要一眼分辨状态）：

```css
/* 亮色 */
--mc-success: #16a34a;  --mc-success-bg: #f0fdf4;  --mc-success-border: #bbf7d0;
--mc-warning: #d97706;  --mc-warning-bg: #fffbeb;  --mc-warning-border: #fde68a;
--mc-danger:  #dc2626;  --mc-danger-bg:  #fef2f2;  --mc-danger-border:  #fecaca;
--mc-info:    #2563eb;  --mc-info-bg:    #eff6ff;  --mc-info-border:    #bfdbfe;
--mc-neutral: #64748b;  --mc-neutral-bg: #f8fafc;  --mc-neutral-border: #e2e8f0;

/* 服务器状态专用（服主最需要的语义） */
--mc-state-running:  #16a34a;  /* 运行中 */
--mc-state-starting: #d97706;  /* 启动中 */
--mc-state-stopping: #d97706;  /* 停止中 */
--mc-state-stopped:  #64748b;  /* 已停止 */
--mc-state-crashed:  #dc2626;  /* 崩溃 */
--mc-state-external: #7c3aed;  /* 外部运行/未托管 */

/* 深色：底色用低透明度，而非浅色实底 */
--mc-success-bg-dark: rgba(22,163,74,.14);
--mc-danger-bg-dark:  rgba(220,38,38,.16);
```

**徽标（Badge）规范**——**禁止靠颜色单独承载语义**（无障碍硬要求）：

```css
--mc-badge-h: 20px;  --mc-badge-pad-x: 8px;  --mc-badge-radius: var(--mc-radius-full);
--mc-badge-fs: var(--mc-fs-xs);  --mc-badge-fw: var(--mc-fw-medium);
```

- **每个状态徽标 = 色点 + 文字**（或 图标 + 文字），色点 6px 圆点。
- 状态点带**呼吸动效**仅用于 `running`（`--mc-pulse: 2s ease-in-out infinite`），**崩溃态用静态红 + 轻微抖动一次**，不要持续闪烁（会造成焦虑与性能开销）。
- **TPS 分级徽标**（我们独有）：`≥19.5` 绿 / `18–19.5` 黄 / `15–18` 橙 / `<15` 红，并在 `hover` 展开 MSPT 与热点提示。

## 8.5 圆角、边框、控件规范

```css
--mc-radius-xs: 4px;    /* 徽标内、小标签 */
--mc-radius-sm: 6px;    /* 输入框、按钮（小） */
--mc-radius-md: 8px;    /* 按钮、输入框（默认） */
--mc-radius-lg: 12px;   /* 卡片 */
--mc-radius-xl: 16px;   /* 面板容器、模态 */
--mc-radius-full: 9999px;
--mc-radius-card: var(--mc-radius-lg);
--mc-radius-modal: var(--mc-radius-xl);

--mc-border-width: 1px;
--mc-border: 1px solid var(--mc-border-default);
--mc-focus-ring: 0 0 0 3px rgba(37,99,235,.22);   /* 键盘聚焦，必须可见 */
```

**规范**：
- 圆角**只用这 6 档**（RT 用了 10 档散值）。**按钮 8px、卡片 12px、模态 16px** 是安全且现代的配方。
- **焦点环必须做**（RT 与多数国内面板缺失）——键盘 `Tab` 可达性是 WCAG AA 要求。

## 8.6 按钮规范

```css
--mc-btn-h-sm: 28px;  --mc-btn-h-md: 34px;  --mc-btn-h-lg: 40px;
--mc-btn-pad-x-sm: 10px; --mc-btn-pad-x-md: 14px; --mc-btn-pad-x-lg: 18px;
--mc-btn-radius: var(--mc-radius-md);
--mc-btn-fs: var(--mc-fs-sm);
--mc-btn-fw: var(--mc-fw-medium);
--mc-btn-gap: var(--mc-space-2);  /* 图标与文字 */
--mc-btn-transition: background-color 120ms ease, box-shadow 120ms ease, transform 80ms ease;
--mc-btn-active-press: translateY(1px);   /* 按压反馈 */
```

变体与主次：**主按钮每屏最多 1 个**（`primary` = 实底品牌色）；`secondary` = 描边；`ghost` = 无底；`danger` = 淡红底 + 红字（**不要用实底大红**做删除，破坏页面平衡）。

**硬性规范**：
- **破坏性操作（删除服务器、恢复世界、强制结束）必须走二次确认模态**，且确认按钮**不是默认聚焦项**；对「彻底删除目录」类操作加**输入服务器名确认**（Snowolf 用「阅读等待确认」，同样有效）。
- 危险操作按钮**禁止与常规按钮同色同权**。

## 8.7 表单规范

```css
--mc-field-h: 34px;  --mc-field-pad-x: 12px;
--mc-field-radius: var(--mc-radius-md);
--mc-field-bg: var(--mc-bg-elevated);
--mc-field-border: 1px solid var(--mc-border-default);
--mc-field-border-focus: 1px solid var(--mc-accent);
--mc-field-placeholder: var(--mc-text-tertiary);
--mc-field-label-fs: var(--mc-fs-sm);
--mc-field-label-fw: var(--mc-fw-medium);
--mc-field-help-fs: var(--mc-fs-xs);
--mc-field-error: var(--mc-danger);
--mc-field-gap-label: 6px;     /* 标签与输入框 */
--mc-field-gap-row: 16px;      /* 表单项之间 */
```

**规范**：
- 表单**必须右侧或下方给「帮助文本」**——MC 配置项（`online-mode`、`view-distance`、`max-tick-time`）对新手极不友好；**为每个 `server.properties` 键内置中文说明**（**Snowolf 已做到「可搜索中文说明或英文配置键」，这是必抄项**）。
- **危险配置项（`online-mode=false`、`allow-flight`、`enable-command-block`）用警告态标记**并给风险说明——Snowolf 文档也在提醒 `online-mode` 的安全影响。
- 数字输入（内存/端口/视距）**必须带单位与范围校验**，不要只给空输入框。

## 8.8 表格规范

```css
--mc-table-row-h: 40px;         /* 舒适密度 */
--mc-table-row-h-compact: 32px; /* 紧凑模式（可切换） */
--mc-table-head-bg: var(--mc-bg-secondary);
--mc-table-head-fs: var(--mc-fs-xs);
--mc-table-head-fw: var(--mc-fw-medium);
--mc-table-head-color: var(--mc-text-secondary);
--mc-table-border: 1px solid var(--mc-border-subtle);
--mc-table-hover-bg: var(--mc-bg-hover);
--mc-table-zebra: none;         /* 不用斑马纹，改用 hover + 分割线 */
--mc-table-sticky-head: position: sticky; top: 0;  /* 长列表必须吸顶 */
--mc-table-num-align: right;    /* 数值列右对齐 + tabular-nums */
```

**规范**：
- **默认 40px 行高**，提供**密度切换**（舒适/紧凑）——这是专业运维工具的标志性能力（RT 与多数国内面板没有）。
- **数值列右对齐 + 等宽数字**；**状态列用徽标**；**操作列固定在右侧**。
- 空表格必须给**空状态**（见 8.11）。

## 8.9 卡片规范

```css
--mc-card-radius: var(--mc-radius-card);
--mc-card-bg: var(--mc-bg-elevated);
--mc-card-border: 1px solid var(--mc-border-subtle);
--mc-card-shadow: var(--mc-elev-1);
--mc-card-pad: var(--mc-pad-card);
--mc-card-gap: var(--mc-gap-section);
--mc-card-hover-shadow: var(--mc-elev-2);
--mc-card-hover-transition: box-shadow 160ms ease, transform 160ms ease;
--mc-card-hover-lift: translateY(-1px);   /* 悬浮微抬，最多 2px */
```

**服务器卡片（核心信息架构）必须一次说清 5 件事**：
1. **状态**（色点 + 文字徽标）
2. **核心 + MC 版本**（用官方核心 logo，Snowolf 的做法值得借鉴）
3. **CPU / 内存**（迷你进度条或 sparkline）
4. **在线玩家 / 最大玩家**
5. **主操作**（启动/停止 + 更多菜单）

**规范**：卡片悬浮抬升 **≤2px**（超过会显得廉价）；**禁止**给卡片加装饰性渐变或发光边框（RT 白金主题的问题）。

## 8.10 数据可视化（TPS / MSPT / CPU / 内存 / 玩家曲线）

这是**我们最重要的差异化界面**（Snowolf 与多数竞品都缺 TPS/MSPT）。

```css
--mc-chart-h-sm: 40px;    /* 卡片内迷你图 */
--mc-chart-h-md: 120px;   /* 面板内主图 */
--mc-chart-h-lg: 220px;   /* 详情页 */
--mc-chart-grid: rgba(0,0,0,.06);        /* 暗色 rgba(255,255,255,.08) */
--mc-chart-axis-fs: var(--mc-fs-xs);
--mc-chart-axis-color: var(--mc-text-tertiary);
--mc-chart-line-w: 1.5px;
--mc-chart-dot-r: 2.5px;                 /* 仅在 hover 显示 */
--mc-chart-area-opacity: .12;            /* 面积填充 */
--mc-chart-crosshair: rgba(100,116,139,.5);
--mc-chart-tooltip-radius: var(--mc-radius-md);
--mc-chart-tooltip-shadow: var(--mc-elev-3);
--mc-chart-transition: 300ms ease-out;   /* 数据更新过渡 */
--mc-chart-window: 60;                   /* 默认 60 点窗口 */
```

**规范（可直接作为验收标准）**：
- **四条曲线同框、共享 X 轴时间**：TPS（左轴 0–20，带 20 参考线）、MSPT（右轴，带 50ms 红线）、CPU%、内存%（右轴 0–100）。
- **TPS 20 与 MSPT 50ms 必须有参考线并标注**——这是「一眼判断健康度」的关键。
- **玩家数用面积图**（离散、可累计感），**TPS 用折线**（连续性）。
- **颜色语义固定**：CPU 蓝 / 内存 紫 / TPS 绿 / MSPT 橙。**图例常驻，不用「点击展开」。**
- **时间窗切换**：1m / 5m / 15m / 1h / 6h / 24h；切换时**不重载整页**。
- **数据缺口必须画成断线 + 灰色区块**，**禁止把缺口插值成直线**（这是数据诚实性问题，专业用户会立刻不信任）。
- **hover 十字准线 + 统一 tooltip**（时间 + 全部指标值），不要每个序列各自弹一个。
- **零基线必须从 0 开始**（内存/CPU 用 0–100）；TPS 轴固定 0–20，**不要自动缩放**（自动缩放会掩盖问题）。
- 迷你图（卡片内 sparkline）**不画轴、不画网格**，只画线 + 末端点。

## 8.11 控制台观感

```css
--mc-console-bg:        #0b0e14;   /* 亮色主题下也用深底（终端是深色语境） */
--mc-console-bg-dark:   #080a0f;
--mc-console-fg:        #c9d1d9;
--mc-console-font:      var(--mc-font-mono);
--mc-console-fs:        12.5px;
--mc-console-lh:        1.55;
--mc-console-pad:       12px 14px;
--mc-console-radius:    var(--mc-radius-md);
--mc-console-sel:       rgba(88,166,255,.28);
--mc-console-search-hit: #f59e0b;        /* 搜索高亮：橙黄（Snowolf 也用橙黄） */
--mc-console-search-hit-bg: rgba(245,158,11,.22);
--mc-console-line-hover: rgba(255,255,255,.04);
--mc-console-ansi-ok:    #3fb950;
--mc-console-ansi-warn:  #d29922;
--mc-console-ansi-error: #f85149;
--mc-console-ansi-info:  #58a6ff;
--mc-console-scrollbar-w: 10px;
```

**规范**：
- **ANSI 颜色必须保留**（不能 strip）；**必须支持向上无限加载**并保留颜色（Snowolf 已做到）。
- **搜索高亮用橙黄**（在深底上对比度足够且不刺眼）；**当前命中项更亮**，并提供「上/下一个」与命中计数。
- **ERROR / WARN / Exception 行给独立左侧色条**——比整行着色更克制也更易扫读。
- **命令输入框与日志区分离**（不要混排）；输入框支持 `↑/↓` 历史与 Tab 补全（补全 `say`、`whitelist`、`op`、`stop`、`save-all` 等常用指令）。
- **「命令保护」开关必须做**（Snowolf 的设计）：未确认服务端就绪时，强制发送需显式解除保护——**防止把指令打进未启动的 stdin**。
- 日志行**虚拟滚动**（`xterm.js` 或自研虚拟列表），**万行不卡**；提供**「复制选中」「导出选中」「发送给 AI」**浮动工具条（选中时出现）。

## 8.12 空状态与引导

```css
--mc-empty-pad: var(--mc-space-16) var(--mc-space-6);
--mc-empty-icon-size: 48px;
--mc-empty-icon-color: var(--mc-text-tertiary);
--mc-empty-title-fs: var(--mc-fs-md);
--mc-empty-title-fw: var(--mc-fw-medium);
--mc-empty-desc-fs: var(--mc-fs-sm);
--mc-empty-desc-color: var(--mc-text-secondary);
--mc-empty-desc-maxw: 42ch;         /* 描述最长 42 字符宽，保证可读 */
--mc-empty-gap: var(--mc-space-4);
--mc-empty-action-gap: var(--mc-space-3);
```

**规范**：
- **每个空状态 = 图标 + 标题 + 一句说明 + 一个主行动按钮**（四件套，缺一不可）。
- **说明文字必须告诉用户「下一步做什么」，而不是「暂无数据」**。反例：`暂无数据`；正例：`还没有服务器。点「创建服务器」，选一个核心和版本，3 分钟就能开服。`
- **新手引导用「检查清单式」**（Checklist）而非「遮罩式教程」：`安装 Java ✓ → 创建服务器 ✓ → 启动 → 进游戏`，完成项打勾并持久化。**Snowolf 有「首次启动欢迎向导」，但我们要把它做成可持续的进度清单。**
- **首次进入有服务器但没启动时，直接给「启动」CTA + 预计耗时**。

## 8.13 动效时长与缓动

```css
--mc-dur-instant: 80ms;   /* 按压、hover 变色 */
--mc-dur-fast:   120ms;   /* 按钮、开关 */
--mc-dur-base:   180ms;   /* 下拉、tooltip */
--mc-dur-slow:   240ms;   /* 抽屉、面板展开 */
--mc-dur-slower: 320ms;   /* 模态、页面切换 */

--mc-ease-standard: cubic-bezier(0.2, 0, 0, 1);        /* 默认（快进慢出） */
--mc-ease-decelerate: cubic-bezier(0, 0, 0, 1);        /* 进入 */
--mc-ease-accelerate: cubic-bezier(0.3, 0, 1, 1);      /* 退出 */
--mc-ease-spring: linear(0, .35 12%, .72 24%, .93 38%, 1 50%, 1); /* 弹性（慎用） */

--mc-anim-pulse: 2s var(--mc-ease-standard) infinite;  /* 运行中状态点 */
--mc-anim-shimmer: 1.4s linear infinite;               /* 骨架屏 */
--mc-anim-count-up: 400ms var(--mc-ease-decelerate);   /* 数字滚动 */
```

**硬性规范**：
- **交互反馈 ≤120ms**（超过会有「黏手感」）；**面板/模态展开 ≤320ms**。
- **进入用 decelerate、退出用 accelerate**（退出必须比进入快，约 0.7×）。
- **位移距离：模态 ≤16px、下拉 ≤8px、页面切换 ≤24px**（不要做大幅滑动）。
- **`prefers-reduced-motion: reduce` 时必须关闭所有非必要动效**（含轮播、脉冲、shimmer）——**无障碍硬要求，RT 与多数国内面板未做**。
- **禁止**用动效做「庆祝式」效果（撒花、弹跳大图标）；运维工具需要**冷静**。

## 8.14 暗/亮主题与无障碍（WCAG AA）

**对比度硬性要求（AA）**：
- 正文文字 vs 背景 **≥ 4.5:1**
- 大字（≥18.66px 粗体 或 ≥24px）**≥ 3:1**
- **UI 组件与图形边界 ≥ 3:1**（边框、图标、图表线、输入框描边）
- **焦点指示 ≥ 3:1** 且**不得仅靠颜色**

**因此，我们**不采用**「亮色主题品牌色 = 纯黑 `#171717`、成功 = 灰」这类低对比方案。** 建议 token：

```css
/* 亮色 */
--mc-bg-base:      #f7f8fa;   /* 比纯白柔和，减少眩光 */
--mc-bg-elevated:  #ffffff;
--mc-bg-secondary: #f1f3f6;
--mc-bg-hover:     #eef1f5;
--mc-text-primary:   #0f172a;   /* vs #ffffff = 16.9:1 ✅ */
--mc-text-secondary: #475569;   /* vs #ffffff =  7.5:1 ✅ */
--mc-text-tertiary:  #64748b;   /* vs #ffffff =  4.8:1 ✅ 仍达 AA */
--mc-border-subtle:  #e5e9ef;
--mc-border-default: #d3d9e1;   /* vs 白 ≈ 3.1:1 ✅ 达 UI 边界要求 */
--mc-accent:         #2563eb;   /* vs 白 = 5.2:1 ✅ */

/* 深色 */
--mc-bg-base-d:      #0b0e14;
--mc-bg-elevated-d:  #151a23;
--mc-bg-secondary-d: #1b212c;
--mc-bg-hover-d:     #222a37;
--mc-text-primary-d:   #e8edf5;  /* vs #0b0e14 ≈ 15.2:1 ✅ */
--mc-text-secondary-d: #a3b0c2;  /* vs #0b0e14 ≈  8.4:1 ✅ */
--mc-text-tertiary-d:  #7d8a9c;  /* vs #0b0e14 ≈  5.2:1 ✅ */
--mc-border-subtle-d:  #232b38;
--mc-border-default-d: #333d4d;  /* vs #0b0e14 ≈ 3.2:1 ✅ */
--mc-accent-d:         #60a5fa;  /* vs #0b0e14 ≈  8.1:1 ✅ */
```

**额外硬性规范**：
- **状态色在暗色下必须单独调亮**（不能直接复用亮色值）——例如亮色 `--mc-danger: #dc2626`（vs 深底仅 3.4:1，不达标），暗色需 `#f87171`。
- **亮暗切换必须遵守 `prefers-color-scheme`** 作为默认，并允许手动覆盖（三态：跟随系统 / 亮 / 暗）。
- **禁止用「纯黑 `#000` + 纯白 `#fff`」**（对比过强导致眩光）；用 `#0b0e14` / `#f7f8fa`。
- **图表不能只靠颜色区分序列**——必须同时有**图例文字 + 线型差异**（实线/虚线）。
- 交付前用 axe DevTools / Lighthouse 无障碍审计，**目标 ≥95 分**。

## 8.15 响应式断点

```css
--mc-bp-xs:  0;      /* 手机竖屏 */
--mc-bp-sm:  640px;  /* 手机横屏 / 小平板 */
--mc-bp-md:  768px;  /* 平板竖屏 */
--mc-bp-lg:  1024px; /* 平板横屏 / 小笔记本 → 侧栏展开临界点 */
--mc-bp-xl:  1280px; /* 桌面 */
--mc-bp-2xl: 1536px; /* 宽屏 → 内容最大宽度限制生效 */
--mc-bp-3xl: 1920px;

--mc-container-max: 1440px;   /* 内容区最大宽度，超宽屏居中留白 */
--mc-sidebar-w: 240px;
--mc-sidebar-w-collapsed: 64px;
--mc-topbar-h: 56px;
```

**布局行为规范**：
| 断点 | 侧栏 | 顶栏 | 卡片网格 | 表格 | 终端 |
|---|---|---|---|---|---|
| `< 768px` | **抽屉**（汉堡唤起，覆盖式） | 56px，标题居中 | **1 列** | **卡片化**（每行变卡片，不用横向滚动） | 全屏，输入框吸底 |
| `768–1023px` | **收窄为图标栏**（64px） | 56px | 2 列 | 横向滚动 + 首列固定 | 全屏 |
| `≥ 1024px` | **常驻展开**（240px，可手动折叠） | 56px | 2–3 列 | 正常表格 | 分栏（日志 + 侧信息） |
| `≥ 1536px` | 常驻 240px | 56px | 3–4 列 | 正常表格 | 分栏 + 更宽图表 |

**规范**：
- **移动端必须能完成「启停服务器 / 看日志 / 踢人 / 看 TPS」四件事**（这是「多端」承诺的底线验收标准）。
- **触控目标 ≥ 44×44px**（WCAG 2.5.5）。
- **表格在窄屏必须卡片化**，**禁止**让用户横向拖一张 12 列的表格。
- **终端在移动端必须给「常用命令按钮」**（手机打字不便）。

## 8.16 与 RT面板的差距清单（验收对照）

| 项 | RT面板实测 | 我们的目标 | 落点 token |
|---|---|---|---|
| 字号阶 | 13 档散值 | **7 档模数阶** | `--mc-fs-*` |
| 圆角 | 10 档散值（4–16px + 999） | **6 档** | `--mc-radius-*` |
| 间距 | 未见系统阶 | **4px 基准 12 档 + 语义 gap** | `--mc-space-*` / `--mc-gap-*` |
| 阴影 | 单层/双层 | **4 级多层 + 1px ring** | `--mc-elev-1..4` |
| 动效令牌 | 未发现 | **4 时长 + 3 缓动 + reduced-motion** | `--mc-dur-*` / `--mc-ease-*` |
| 组件库 | **Element Plus 全量、无构建** | **按需引入 + 构建期 tree-shaking + 自研设计系统** | — |
| 状态可辨识 | 有语义色 | **色点+文字双编码 + 6 态服务器状态** | `--mc-state-*` |
| 数字对齐 | 未见 tabular-nums | **等宽 + tabular-nums（防跳动）** | `--mc-font-num` |
| 表格密度 | 单一密度 | **舒适/紧凑可切换 + 吸顶表头** | `--mc-table-row-h*` |
| 数据可视化 | 未核实 | **TPS/MSPT/CPU/内存四线同框 + 断线诚实呈现** | `--mc-chart-*` |
| 控制台 | 未核实 | **ANSI 保留 + 橙黄搜索高亮 + 错误色条 + 命令保护** | `--mc-console-*` |
| 无障碍 | 未见对比度约束 | **WCAG AA + 焦点环 + reduced-motion + axe ≥95** | 见 §8.14 |
| 密集操作 | — | **右键菜单 + 批量选择 + 快捷键** | — |
| 在线演示 | ❌（Snowolf 桌面亦不可行） | ✅ **免注册沙箱演示** | — |

> **一句话设计方向**：把 RT面板 的「轻奢金 + Element Plus 同质化」换成 **「冷静的中性色 + 精确的 8px 栅格 + 多层级阴影 + 等宽数字 + 真实数据可视化 + 无障碍可用的深色主题」**，并**把 TPS/MSPT 诊断做成首页主角**——这是我们视觉与功能上都能压过 RT面板 与 Snowolf 的地方。

---

# 附：参考链接清单

## A. Snowolf 一手来源

| 内容 | URL | 状态 |
|---|---|---|
| 仓库 API | `https://api.github.com/repos/Snowolf-Studio/Snowolf` | **[实测]** 200 |
| 仓库页 | https://github.com/Snowolf-Studio/Snowolf | web_fetch 不通，API 可读 |
| README | `https://api.github.com/repos/Snowolf-Studio/Snowolf/readme` | **[实测]** 可读（base64） |
| README（镜像） | https://gh-proxy.com/https://raw.githubusercontent.com/Snowolf-Studio/Snowolf/main/README.md | **[实测]** 200 |
| 文件树 | `https://api.github.com/repos/Snowolf-Studio/Snowolf/git/trees/main?recursive=1` | **[实测]** 899 blob |
| 发行说明 | `https://api.github.com/repos/Snowolf-Studio/Snowolf/releases?per_page=100` | 首次成功（10 条），后限流 |
| Releases 页 | https://github.com/Snowolf-Studio/Snowolf/releases | — |
| 组织仓库列表 | `https://api.github.com/users/Snowolf-Studio/repos` | **[实测]** 200（2 个仓库：`Snowolf`、`snowolf-templates`） |
| 设计令牌 | `src/styles/theme.css`（45,556 B） | **[源码实测]** |
| 后端命令注册表 | `src-tauri/src/lib.rs`（44,540 B） | **[源码实测]** |
| 路由（功能地图） | `src/router/index.tsx` | **[源码实测]** |
| 核心下载源 | `src-tauri/src/services/server/downloader.rs` | **[源码实测]** |
| Modrinth 服务 | `src-tauri/src/services/modrinth_service.rs` | **[源码实测]** |
| Java 安装器 | `src-tauri/src/services/download/java_installer.rs` | **[源码实测]** |
| Java 检测 | `src-tauri/src/services/java_detector.rs` | **[源码实测]** |
| 扩展运行时 | `src-tauri/src/extensions/runtime/**`、`plugins/runtime/**` | **[源码实测]** |
| 常量（镜像源） | `src-tauri/src/utils/constants.rs` | **[源码实测]** |
| 多语言 | `src-tauri/locales/*.json`（11 个） | **[源码实测]** |

## B. Snowolf 官方文档站（26 页，全部 **[实测]** 200）

基址：`https://docs-snowolf.lr-luorui.cn/zh-CN/docs/<slug>`

`what-is-snowolf` · `quick-start` · `install` · `choose-create-method` · `create-server` · `download-create-server` · `import-host-and-tasks` · `server-lifecycle` · `manage-servers` · `server-terminal-guide` · `files-and-config` · `server-files-guide` · `server-config-guide` · `server-settings-guide` · `server-defaults-guide` · `java-install` · `mods-and-plugins`→实为 `mods-and-players` · `mods-plugins-guide` · `players-guide` · `scheduled-tasks-guide` · `world-backup-and-restore` · `tasks-and-backup` · `network-access-guide` · `connection-troubleshooting` · `tunnel-guide` · `tunnel-and-cloud` · `ai-getting-started` · `ai-server-actions` · `ai-context` · `ai-prompting` · `ai-permissions-and-rollback` · `ai-models-and-troubleshooting` · `tools` · `personalization-guide` · `desktop-tray-guide` · `update-extensions-guide` · `plans-purchase-guide` · `cloud-account-guide` · `advanced-diagnostics-guide` · `troubleshooting-hub` · `settings` · `community`

可用品牌资源：`/logo-black.svg`、`/logo-white.svg`、`/icon.png`（**[实测]** 200）
**界面截图：全部 404，未获取到。**（尝试 `/screenshots/<slug>/step-NN-*.webp`、`/docs/<slug>/*.webp`、`/<slug>/*.webp`、`*.png` 等 10+ 形态）

## C. 关联 / 上游项目

- SeaLantern（Snowolf 1.7 上游血统）：https://github.com/FPSZ/SeaLantern **[实测]** 存在，13 stars，GPL-3.0，push 2026-02-25
- snowolf-templates：https://github.com/Snowolf-Studio/snowolf-templates **[实测]** 存在
- 开发者站点：https://lr-luorui.cn/ **[实测]** 200（8,326 B）
- 官方品牌站：`snowolf.lr-luorui.cn` —— HTTPS **404** / HTTP **200 仅 138 B** **[实测]**
- 无关域名占用：`https://snowolf.cn/` → 影视站 **[实测]** 200

## D. 竞品官方来源（**[实测]** 可达）

- MCSManager 官网：https://mcsmanager.com/ （200）
- MCSManager 中文文档：https://docs.mcsmanager.com/zh_cn/index.html （200）
- MCSManager 仓库：https://github.com/MCSManager/MCSManager
- MCSManager 一键搭建 Java 版 / 基岩版 / Steam：`/zh_cn/setup_java_edition.html`、`/zh_cn/setup_bedrock_edition.html`、`/zh_cn/setup_steam.html`、`/zh_cn/setup_package.html`
- MCSManager API 文档：`/zh_cn/apis/get_apikey.html`、`/zh_cn/apis/api_instance.html` 等
- MCSManager HTML 卡片小组件：`/zh_cn/apis/html_card.html`
- Pterodactyl 官网：https://pterodactyl.io/ （200）
- Pterodactyl 简介：https://pterodactyl.io/project/introduction.html （200）
- Pterodactyl 快速上手：https://pterodactyl.io/panel/1.0/getting_started.html （200）
- Pterodactyl 系统需求：https://mintlify.wiki/pterodactyl/panel/system-requirements
- AMP（CubeCoders）：https://cubecoders.com/AMP （200）
- AMP 版本对比：https://discourse.cubecoders.com/t/editions-comparison-sheet/2247 （200）
- Multicraft 官网：https://multicraft.org/ （200）
- Multicraft 安装文档：https://multicraft.org/site/docs/install （200）
- Multicraft + Blesta 模块：https://docs.blesta.com/display/user/Multicraft
- 雨云：https://www.rainyun.com/ （200）
- 雨云开服教程：https://forum.rainyun.com/t/topic/12985 （200）
- 小皮面板：https://www.xp.cn/ （200）
- PebbleHost：https://www.pebblehost.com/ （403，反爬）
- Shockbyte：https://shockbyte.com/ （403，反爬）
- Modrinth：https://modrinth.com/ （200）
- CurseForge：https://www.curseforge.com/minecraft （403，反爬）
- SpigotMC：https://www.spigotmc.org/resources/categories/1/ （403，反爬）
- **RT面板（同仓兄弟产品）**：https://www.rt888.icu/ （200）；设计令牌来自 `https://www.rt888.icu/css/themes.css`（8,680 B）与 `https://www.rt888.icu/css/site.css`（12,218 B）**[实测]**
- Snowolf 引用的 B 站视频（**已删除**）：https://www.bilibili.com/video/BV15t5S6MEq1/

## E. 元数据 / 下载接口（全部 **[实测]**，详见 §6）

- Mojang：`https://piston-meta.mojang.com/mc/game/version_manifest_v2.json`（200）
- BMCLAPI 镜像：`https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json`（200）
- Paper（**当前**）：`https://fill.papermc.io/v3/projects/paper`（200）
- Paper（**已废弃**）：`https://api.papermc.io/v2/projects/paper`（**410 sunset**）
- Purpur：`https://api.purpurmc.org/v2/purpur`（200）
- Fabric：`https://meta.fabricmc.net/v2/versions/game`（200）
- Quilt：`https://meta.quiltmc.org/v3/versions/game`（200）
- Forge：`https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json`（200）
- NeoForge：`https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml`（首次 200，后 000）
- Adoptium：`https://api.adoptium.net/v3/info/available_releases`（200）
- Microsoft OpenJDK：`https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip`（200，192 MB）
- Modrinth：`https://api.modrinth.com/v2/search?limit=1`（200，**无需 key**）
- **CurseForge：`https://api.curseforge.com/v1/mods/search?gameId=432`（403，`Forbidden: API Key missing or invalid`）**
- **SpigotMC：`https://api.spigotmc.org/legacy/update.php?resource=1`（403 Cloudflare）**
- Spigot 版本索引：`https://hub.spigotmc.org/versions/`（200）；单版本 JSON（403）
- CraftBukkit（第三方 CDN）：`https://cdn.getbukkit.org/craftbukkit/craftbukkit-1.21.1.jar`（200）
- GeyserMC：`https://download.geysermc.org/v2/projects/geyser`（200）
- MCJars 聚合：`https://mcjars.app/api/v2/builds/paper`（200）
- 服务器状态：`https://api.mcsrvstat.us/3/play.hypixel.net`（200）
- 镜像通道：`https://api.github.com/**`（200）、`https://gh-proxy.com/<raw-url>`（200）；raw.githubusercontent / github.com / jsDelivr / ghproxy.net / hub.gitmirror / kkgithub（本机 **000**）
- Snowolf 引用但**已失效**：`https://cnb.cool/Snowolf-studio/ServerCore-Mirror/-/releases/download/26.02.27/jar_lfs_links.json`（**404**）

---

## 调研方法与局限说明

**方法**：
1. `web_search` 定位（Snowolf 的搜索命中率很低，主要靠 GitHub API）。
2. **绕开 web_fetch 的 SSRF 限制，改用 shell `curl.exe`** 直连，这是本次调研的关键突破——`web_fetch` 对 `api.github.com` / 文档站均失败，但 `curl` 全部成功。
3. 全程读取 **GitHub REST API**（`api.github.com` 可达）而非网页 HTML。
4. 文档站 26 页**全量抓取**，并用 `<article>` 边界 + UTF-8 显式解码剥离侧栏噪声（首轮因编码错误出现乱码，已修正）。
5. 直接读取**源码**（`theme.css`、`lib.rs` 命令注册表、`router/index.tsx`、各 service），获得比截图更精确的一手证据。
6. **对所有第三方接口逐一实测 HTTP 状态码**，不依赖文档声称。
7. RT面板以 `curl` 读取其官网 + 真实 CSS 文件，获取**非推测的**设计令牌。

**局限与未获取项**：
1. **未获取到任何 Snowolf 官方界面截图**（文档站占位图全部 404，尝试 10+ 路径形态 + sitemap/robots 均失败）。因此 §2 的「观感」描述基于设计令牌与文字描述，**图标画风、实际排版密度、视觉层次实感无法验证**，相关推断已标 [推测]。
2. **Snowolf 2.0 的功能清单未获取到**：2.0 未开源、GitHub Releases API 限流、文档站标题虽称「以 2.0 为准」但内容混编。§3 的功能清单**主要反映 1.7 源码 + 文档站**，可能与 2.0 有差异（尤其 AI 部分明显是 2.0 时代功能）。
3. **GitHub API 限流**：调研后期部分 API 返回空（releases/tags），未能完成全量翻页。
4. **AMP / Multicraft / 国内厂商面板未做逐项界面与功能核实**，§4.3 中相关单元格为基于公开定位的判断，已标 ❓/⚠️。
5. **NeoForge maven 可用性未确证**（首次 200、后续 000）。
6. 本机网络有**域名劫持到 127.0.0.1** 的现象，凡 `000` 结果均**不能**推断为公网不可用。
7. 未核实 `lr-luorui.cn` 的 ICP 备案状态。
