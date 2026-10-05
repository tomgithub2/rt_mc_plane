/* 仪表盘（首页）
   ============================================================================
   布局要点（本项目的界面调研结论，详见 docs/）：
     · **首屏 = 仪表盘**：多实例**卡片网格**，每卡显示**状态 / CPU / 内存**，
       并提供启动·停止与子页入口
     · **卡片可拖动排序、可置顶**常用实例（顺序与置顶持久化在 localStorage）
     · 顶栏提供**实例快速切换**（跳到该实例控制台）
     · 侧栏 + 顶栏 + 实例子导航三级结构（子导航在实例详情页内）

   与「实例列表」的分工：
     · 仪表盘（本页）= 扫一眼全局 + 常用实例置顶 + 快捷启停
     · 实例列表 = 完整字段、搜索、表格视图、批量操作
   ========================================================================== */
window.Pages = window.Pages || {};

Pages.dashboard = function (app) {
  View.boot(app, {
    active: 'dashboard',
    crumbs: [{ text: '面板', hash: '#/dashboard' }, { text: '仪表盘' }],
    actions: '<button class="btn sm" id="dash-refresh">' + Icon.svg('refresh', 15) + '刷新</button>' +
             '<button class="btn sm primary" data-go="#/create">' + Icon.svg('plus', 15) + '新建实例</button>',
    run: function (ctx) {
      var body = ctx.body;
      View.bindGo(body);

      var insts = [];            // 实例（含实时状态）
      var host = {};             // 主机资源
      var hist = {};             // id -> {cpu:[], mem:[]} 采样历史（给 sparkline）
      var view = ViewMode.get('dashboard');   // cards / compact / trend
      /* 趋势视图用的历史：主机资源 + 每个实例的状态色带。
         每次推送累积一格，上限 HOST_HIST_MAX（1 秒一帧 → 约 2 分钟）。 */
      var HOST_HIST_MAX = 120;
      var hostHist = { cpu: [], mem: [] };
      var statusHist = {};       // id -> ['running','stopped',…]
      var seqDrawn = false;

      var PIN_KEY = 'mc_dash_pins';       // 置顶
      var ORDER_KEY = 'mc_dash_order';    // 拖动排序
      function readJson(k, dflt) {
        try { return JSON.parse(localStorage.getItem(k)) || dflt; } catch (e) { return dflt; }
      }
      function writeJson(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
      var pins = readJson(PIN_KEY, []);
      var order = readJson(ORDER_KEY, []);

      /* ---------------------------------------------------------------- 排序 */
      function ordered() {
        var list = insts.slice();
        var idx = {};
        order.forEach(function (id, i) { idx[id] = i; });
        list.sort(function (a, b) {
          var pa = pins.indexOf(a.id) >= 0 ? 0 : 1;
          var pb = pins.indexOf(b.id) >= 0 ? 0 : 1;
          if (pa !== pb) return pa - pb;                       // 置顶优先
          var oa = idx[a.id] === undefined ? 999 : idx[a.id];
          var ob = idx[b.id] === undefined ? 999 : idx[b.id];
          if (oa !== ob) return oa - ob;                       // 再按自定义顺序
          return (a.id || 0) - (b.id || 0);
        });
        return list;
      }

      /* ---------------------------------------------------------------- 采样 */
      function sample() {
        insts.forEach(function (it) {
          var h = hist[it.id] || (hist[it.id] = { cpu: [], mem: [] });
          h.cpu.push(Number(it.cpu) || 0);
          h.mem.push(Number(it.mem_mb) || 0);
          if (h.cpu.length > 60) h.cpu.shift();
          if (h.mem.length > 60) h.mem.shift();
          /* 状态色带：记"这一刻是什么状态"，用于趋势视图 */
          var s = statusHist[it.id] || (statusHist[it.id] = []);
          s.push(it.running ? 'running' : (it.status || 'stopped'));
          if (s.length > HOST_HIST_MAX) s.shift();
        });
      }

      /* 主机资源历史（趋势视图的主机 CPU/内存曲线） */
      function sampleHost() {
        if (host.cpu_percent === undefined || host.cpu_percent === null) return;
        hostHist.cpu.push(Number(host.cpu_percent) || 0);
        hostHist.mem.push(Number(host.mem_percent) || 0);
        if (hostHist.cpu.length > HOST_HIST_MAX) hostHist.cpu.shift();
        if (hostHist.mem.length > HOST_HIST_MAX) hostHist.mem.shift();
      }

      /* ---------------------------------------------------------------- 取数 */
      function load(showToast) {
        return Promise.all([
          API.get('/api/instances'),
          API.get('/api/overview').catch(function () { return {}; })   // 主机资源拿不到不算错
        ]).then(function (r) {
          insts = (r[0] && r[0].instances) || [];
          host = (r[1] && r[1].host) || {};
          /* 顶栏的"服务器快速切换"读的是 Store.state.instances；仪表盘也写一份，
             这样进面板第一眼就能用切换器（实例列表页同样会写）。 */
          Store.set({ instances: insts });
          sample();
          sampleHost();
          draw();
          C.fillServerSwitch(app);            // 顶栏"快速切换实例"（数据到了才能填）
          if (showToast) Toast.ok('已刷新（' + insts.length + ' 个实例）');
        }).catch(function (e) {
          if (Perm.denyIfForbidden(e, app, { perm: 'log.view', active: 'dashboard',
                                             crumbs: [{ text: '面板' }, { text: '仪表盘' }] })) return;
          View.showError(body, e, { title: '仪表盘读取失败', showStack: true },
                         { onRetry: function () { load(); } });
        });
      }

      /* ---------------------------------------------------------------- 渲染 */
      function draw() {
        try { drawInner(); } catch (err) {
          View.showError(body, err, { title: '仪表盘渲染失败', showStack: true },
                         { onRetry: function () { load(); } });
        }
      }

      function drawInner() {
        var running = insts.filter(function (i) { return i.running; }).length;
        var players = insts.reduce(function (a, i) { return a + (i.running ? (i.players || 0) : 0); }, 0);
        var pinned = ordered().filter(function (i) { return pins.indexOf(i.id) >= 0; });
        var rest = ordered().filter(function (i) { return pins.indexOf(i.id) < 0; });
        body.innerHTML = '' +
          '<div class="page-head"><div class="titles">' +
            '<div class="kicker">Home</div><h1>仪表盘 <span class="badge" id="dash-live">' +
              U.esc(liveState) + '</span></h1>' +
            '<div class="sub" id="dash-sub">' + headSub() + '</div>' +
          '</div>' +
          '<div class="acts">' + ViewMode.switchHtml('dashboard', view) + '</div>' +
          '</div>' +

          /* 主机资源条：CPU / 内存 / 磁盘 / 实例数做成一行紧凑指标（所有视图都保留） */
          '<div class="grid cols-4 mb" id="dash-host"></div>' +

          (view === 'trend' ? trendHtml()
            : view === 'compact' ? compactSection()
            : (insts.length
                ? (pinned.length ? section('置顶', pinned, true) : '') +
                  section(pinned.length ? '全部实例' : '实例', rest, false)
                : '<div class="card">' + C.empty('server', '还没有任何服务器实例',
                    '点右上角「新建实例」走一遍向导：选核心 → 选版本 → 内存与端口 → 确认下载。' +
                    '也可以到「实例列表」先看已有的或从本地上传 jar。',
                    '<button class="btn primary" data-go="#/create">新建第一个实例</button>') + '</div>'));

        drawHost();
        if (view === 'trend') drawTrend();
        bind();
        ViewMode.bind(body, 'dashboard', function (key) { view = key; draw(); });
        View.bindGo(body);
        seqDrawn = true;
      }

      /* ---------------------------------------------------------- 紧凑视图
         一行一个实例，冲着一屏扫完去（几十个实例时卡片视图翻页太累）。 */
      function compactSection() {
        if (!insts.length) {
          return '<div class="card">' + C.empty('server', '还没有任何服务器实例',
            '点右上角「新建实例」开始。', '') + '</div>';
        }
        return '<div class="card flush dense-list">' +
          '<div class="dense-head"><span>实例</span><span>状态</span><span class="num">CPU</span>' +
            '<span class="num">内存</span><span class="num">玩家</span><span>运行时长</span>' +
            '<span class="num">端口</span><span></span></div>' +
          ordered().map(function (it) {
            var isPin = pins.indexOf(it.id) >= 0;
            return '<div class="dense-row" data-id="' + it.id + '">' +
              '<span class="dense-name" data-open="' + it.id + '">' +
                '<i class="dot ' + U.esc(it.status) + '"></i>' +
                (isPin ? '<b class="pin-mark">★</b>' : '') + U.esc(it.name) +
                '<em>' + U.esc(it.core_label || it.core_type) + '</em></span>' +
              '<span data-slot="badge">' + C.statusBadge(it.status) + '</span>' +
              '<span class="num mono" data-slot="cpu">' + (it.running ? (Number(it.cpu) || 0).toFixed(2) + '%' : '—') + '</span>' +
              '<span class="num mono" data-slot="mem">' + (it.running ? Math.round(it.mem_mb || 0) + 'MB' : '—') + '</span>' +
              '<span class="num mono" data-slot="players">' + (it.running ? (it.players || 0) : '—') + '</span>' +
              '<span class="mono small" data-slot="uptime">' + (it.running ? U.esc(it.uptime_text) : '—') + '</span>' +
              '<span class="num mono small">:' + it.port + '</span>' +
              '<span class="dense-acts">' +
                (it.running
                  ? '<button class="btn xs" data-act="stop" data-id="' + it.id + '">停止</button>'
                  : '<button class="btn xs" data-act="start" data-id="' + it.id + '">启动</button>') +
                '<button class="btn xs ghost" data-pin="' + it.id + '">' + (isPin ? '★' : '☆') + '</button>' +
              '</span>' +
            '</div>';
          }).join('') + '</div>';
      }

      /* ---------------------------------------------------------- 趋势视图
         关注"变化"而不是"此刻"：主机 CPU/内存取推送累积的历史；
         实例内存 TOP 叠加显示，方便一眼看出谁在吃内存；
         再加一条状态色带，把最近若干次采样的状态变化铺开。 */
      function trendHtml() {
        var top = insts.slice().sort(function (a, b) {
          return (Number(b.mem_mb) || 0) - (Number(a.mem_mb) || 0);
        }).slice(0, 6);
        return '<div class="grid cols-2 mb">' +
            '<div class="card"><div class="card-head"><h3>主机 CPU</h3>' +
              '<div class="right small muted" id="trend-host-cpu-now">—</div></div>' +
              '<div id="trend-host-cpu" class="chart-host"></div></div>' +
            '<div class="card"><div class="card-head"><h3>主机内存</h3>' +
              '<div class="right small muted" id="trend-host-mem-now">—</div></div>' +
              '<div id="trend-host-mem" class="chart-host"></div></div>' +
          '</div>' +
          '<div class="card mb"><div class="card-head"><h3>各实例内存占用</h3>' +
            '<div class="right small muted">按当前占用取前 ' + top.length + ' 个 · 单位 MB</div></div>' +
            '<div id="trend-inst-mem" class="chart-host tall"></div>' +
            (insts.length ? '' : '<div class="small muted mt">还没有实例</div>') +
          '</div>' +
          '<div class="card"><div class="card-head"><h3>实例状态一览</h3>' +
            '<div class="right small muted">每格 = 一次采样（最近 ' + HOST_HIST_MAX + ' 次）</div></div>' +
            '<div class="status-strip">' + ordered().map(function (it) {
              var h = statusHist[it.id] || [];
              return '<div class="status-cell" title="' + U.esc(it.name) + '">' +
                '<div class="strip">' + (h.length ? h.map(function (s) {
                  return '<i class="' + U.esc(s) + '"></i>';
                }).join('') : '<i></i>') + '</div>' +
                '<div class="small ellip">' + U.esc(it.name) + '</div></div>';
            }).join('') + '</div></div>';
      }

      function drawTrend() {
        var c1 = document.getElementById('trend-host-cpu');
        var c2 = document.getElementById('trend-host-mem');
        var c3 = document.getElementById('trend-inst-mem');
        if (c1 && Chart.area) {
          Chart.area(c1, [{ name: 'CPU %', values: hostHist.cpu || [] }],
                     { height: 150, max: 100, emptyText: '正在累积采样…' });
        }
        if (c2 && Chart.area) {
          Chart.area(c2, [{ name: '内存 %', values: hostHist.mem || [] }],
                     { height: 150, max: 100, emptyText: '正在累积采样…' });
        }
        if (c3 && Chart.area) {
          var top = insts.slice().sort(function (a, b) {
            return (Number(b.mem_mb) || 0) - (Number(a.mem_mb) || 0);
          }).slice(0, 6);
          Chart.area(c3, top.map(function (it) {
            return { name: it.name, values: ((hist[it.id] || {}).mem) || [] };
          }), { height: 200, emptyText: '实例都在停止状态，没有内存采样' });
        }
        var n1 = document.getElementById('trend-host-cpu-now');
        if (n1) n1.textContent = (host.cpu_percent === undefined || host.cpu_percent === null)
          ? '—' : host.cpu_percent + '%';
        var n2 = document.getElementById('trend-host-mem-now');
        if (n2) n2.textContent = (host.mem_percent === undefined || host.mem_percent === null)
          ? '—' : host.mem_percent + '%';
      }

      function section(title, list, isPinned) {
        if (!list.length && isPinned) return '';
        return '<div class="dash-section">' +
          '<div class="dash-section-head"><h2>' + U.esc(title) + '</h2>' +
            '<span class="badge">' + list.length + '</span></div>' +
          '<div class="inst-grid" data-list="' + (isPinned ? 'pin' : 'all') + '">' +
            list.map(card).join('') +
          '</div></div>';
      }

      function card(it) {
        var h = hist[it.id] || { cpu: [] };
        var isPin = pins.indexOf(it.id) >= 0;
        return '<div class="inst-card dash-card ' + U.esc(it.status) + '" data-id="' + it.id +
                 '" draggable="true">' +
          '<span data-slot="ring">' + C.ring(it.status, ringPercent(it), it.core_type) + '</span>' +
          '<div class="inst-top">' +
            '<div style="min-width:0">' +
              '<div class="inst-name" data-open="' + it.id + '">' + U.esc(it.name) + '</div>' +
              '<div class="inst-meta">' + U.esc(it.core_label || it.core_type) +
                (it.mc_version ? ' · ' + U.esc(it.mc_version) : '') +
                ' · :' + it.port + ' · ' + it.memory_mb + 'MB</div>' +
            '</div>' +
            '<div class="spacer"></div>' +
            '<span data-slot="badge">' + C.statusBadge(it.status) + '</span>' +
            '<button class="btn xs ghost dash-pin" data-pin="' + it.id + '" title="' +
              (isPin ? '取消置顶' : '置顶这张卡片') + '">' + (isPin ? '★' : '☆') + '</button>' +
          '</div>' +
          '<div class="metrics">' +
            C.metric('CPU', (it.running ? (Number(it.cpu) || 0).toFixed(2) + '%' : '—')) +
            C.metric('内存', (it.running ? Math.round(it.mem_mb || 0) + 'MB' : '—')) +
            C.metric('玩家', (it.running ? String(it.players || 0) : '—')) +
            C.metric('TPS', (it.tps_available ? Number(it.tps).toFixed(1) : '不可用')) +
          '</div>' +
          '<div class="spark-wrap" data-slot="spark" data-n="' + ((h && h.cpu) ? h.cpu.length : 0) +
            '" data-run="' + !!it.running + '">' + sparkSvg(it, h) + '</div>' +
          '<div class="row between small muted">' +
            '<span data-slot="uptime">' + uptimeText(it) + '</span>' +
            (it.auto_restart ? '<span class="badge">自动重启</span>' : '') +
          '</div>' +
          '<div class="inst-actions">' +
            (it.running
              ? '<button class="btn sm" data-act="restart" data-id="' + it.id + '">' + Icon.svg('restart', 14) + '重启</button>' +
                '<button class="btn sm danger" data-act="stop" data-id="' + it.id + '">' + Icon.svg('stop', 14) + '停止</button>'
              : '<button class="btn sm" data-act="start" data-id="' + it.id + '">' + Icon.svg('play', 14) + '启动</button>') +
            '<button class="btn sm" data-open="' + it.id + '">' + Icon.svg('terminal', 14) + '控制台</button>' +
            '<button class="btn sm ghost" data-go="#/instances/' + it.id + '/files">文件</button>' +
          '</div>' +
        '</div>';
      }

      function uptimeText(it) {
        return it.running ? ('运行 ' + U.esc(it.uptime_text || '0分0秒') + ' · PID ' + it.pid)
                          : '未运行';
      }

      function sparkSvg(it, h) {
        return Chart.sparkline((h && h.cpu) || [], { height: 34,
          color: it.status === 'running' ? 'var(--text-secondary)' : 'var(--neutral)' });
      }

      /* ---------------------------------------------------------------- 原地更新
         实时推送每 2 秒一帧。**不整页重绘**：只改卡片上会变的那几个字段，
         这样拖动排序、搜索框焦点、sparkline 历史都不会被打断。
         只有"实例集合变了"（新增/删除）才整体重画。 */
      /* 只有**值真的变了**才写 DOM，并给一个轻微上浮淡入。
         每秒一帧都无条件写 textContent 会让浏览器反复重排/重绘，看着像闪。 */
      function setVal(el, text, animate) {
        if (!el) return;
        text = (text === undefined || text === null) ? '—' : String(text);
        if (el.textContent === text) return;          // 值没变 → 完全不动 DOM
        el.textContent = text;
        if (animate === false) return;
        el.classList.remove('mc-val-updated');
        void el.offsetWidth;                          // 强制重排一次，让动画能重放
        el.classList.add('mc-val-updated');
      }

      function setHtml(el, html) {
        if (!el) return;
        if (el.innerHTML === html) return;
        el.innerHTML = html;
      }

      function patchCard(el, it, h) {
        if (!el) return;
        var cls = 'inst-card dash-card ' + (it.status || '');
        if (el.className !== cls) el.className = cls;

        var ring = el.querySelector('[data-slot="ring"]');
        if (ring) setHtml(ring, C.ring(it.status, ringPercent(it), it.core_type));

        var badge = el.querySelector('[data-slot="badge"]');
        if (badge) setHtml(badge, C.statusBadge(it.status));

        var m = el.querySelectorAll('.metrics .metric .v');
        if (m.length >= 4) {
          setVal(m[0], it.running ? (Number(it.cpu) || 0).toFixed(2) + '%' : '—');
          setVal(m[1], it.running ? Math.round(Number(it.mem_mb) || 0) + 'MB' : '—');
          setVal(m[2], it.running ? String(it.players || 0) : '—');
          setVal(m[3], it.tps_available ? Number(it.tps).toFixed(1) : '不可用');
        }
        var up = el.querySelector('[data-slot="uptime"]');
        if (up) setVal(up, uptimeText(it), false);     // 运行时长每秒都在变，不做动画（否则一直闪）

        /* sparkline：点数变了才重画，并整块淡入（SVG 几何属性不能做 transition） */
        var sp = el.querySelector('[data-slot="spark"]');
        if (sp) {
          var n = (h && h.cpu) ? h.cpu.length : 0;
          if (String(sp.getAttribute('data-n')) !== String(n) ||
              sp.getAttribute('data-run') !== String(!!it.running)) {
            sp.setAttribute('data-n', n);
            sp.setAttribute('data-run', String(!!it.running));
            sp.innerHTML = sparkSvg(it, h);
            sp.classList.remove('mc-spark-updated');
            void sp.offsetWidth;
            sp.classList.add('mc-spark-updated');
          }
        }
      }

      function patchHost() {
        var el = document.getElementById('dash-host');
        if (!el) return;
        function pct(v) { return (v === undefined || v === null) ? '—' : Math.round(v) + '%'; }
        var vals = el.querySelectorAll('.stat .v');
        if (vals.length < 4) { drawHost(); return; }
        setVal(vals[0], pct(host.cpu_percent));
        setVal(vals[1], pct(host.mem_percent));
        setVal(vals[2], (host.disk_free_gb === undefined ? '—' : host.disk_free_gb + ' GB'));
        setVal(vals[3], String(insts.length));
        var subs = el.querySelectorAll('.stat .s');
        if (subs.length >= 4) {
          setVal(subs[0], (host.cpu_count || '?') + ' 核', false);
          setVal(subs[1], host.mem_used_mb
            ? (Math.round(host.mem_used_mb / 1024) + ' / ' + Math.round((host.mem_total_mb || 0) / 1024) + ' GB')
            : '—', false);
          setVal(subs[2], '数据目录所在盘（已用 ' + pct(host.disk_percent) + '）', false);
          setVal(subs[3], insts.filter(function (i) { return i.running; }).length + ' 个运行中', false);
        }
      }

      /* 实时帧到达：合并进 insts 后原地更新 */
      function applyLive(snap) {
        var incoming = snap.instances || [];
        var sameSet = incoming.length === insts.length &&
          incoming.every(function (x, i) { return insts[i] && String(insts[i].id) === String(x.id); });
        /* 合并：保留 HTTP 才有的字段（core_label / port / memory_mb / auto_restart …） */
        var byId = {};
        insts.forEach(function (x) { byId[String(x.id)] = x; });
        insts = incoming.map(function (x) {
          return Object.assign({}, byId[String(x.id)] || {}, x);
        });
        host = (snap.host && Object.keys(snap.host).length) ? snap.host : host;
        sample();                       // 累积实例 sparkline / 状态色带历史
        sampleHost();                   // 累积主机资源历史
        Store.set({ instances: insts });
        var sub = document.getElementById('dash-sub');
        if (sub) sub.innerHTML = headSub();
        if (!sameSet) { draw(); return; }        // 集合变了才重画
        /* 趋势视图：曲线要跟着帧走，但**不重建整页**（否则图表会闪） */
        if (view === 'trend') { drawTrend(); patchHost(); return; }
        patchHost();
        if (view === 'compact') { patchCompact(); return; }
        insts.forEach(function (it) {
          patchCard(body.querySelector('.dash-card[data-id="' + it.id + '"]'),
                    it, hist[it.id]);
        });
      }

      /* 紧凑视图的原地更新（同样是"值变了才写"） */
      function patchCompact() {
        insts.forEach(function (it) {
          var row = body.querySelector('.dense-row[data-id="' + it.id + '"]');
          if (!row) return;
          var b = row.querySelector('[data-slot="badge"]');
          if (b) setHtml(b, C.statusBadge(it.status));
          setVal(row.querySelector('[data-slot="cpu"]'),
                 it.running ? (Number(it.cpu) || 0).toFixed(2) + '%' : '—');
          setVal(row.querySelector('[data-slot="mem"]'),
                 it.running ? Math.round(it.mem_mb || 0) + 'MB' : '—');
          setVal(row.querySelector('[data-slot="players"]'), it.running ? String(it.players || 0) : '—');
          setVal(row.querySelector('[data-slot="uptime"]'), it.running ? (it.uptime_text || '') : '—', false);
        });
      }

      function headSub() {
        var running = insts.filter(function (i) { return i.running; }).length;
        var players = insts.reduce(function (a, i) { return a + (i.running ? (i.players || 0) : 0); }, 0);
        return insts.length + ' 个实例 · ' + running + ' 个运行中 · ' + players + ' 名在线玩家。' +
          '卡片可<b>拖动排序</b>、点图钉<b>置顶</b>常用服务器。';
      }

      var liveState = '离线';
      function setLive(state) {
        liveState = state;
        var el = document.getElementById('dash-live');
        if (!el) return;
        el.className = 'badge ' + (state === '实时' ? 'ok' : (state === '重连中' ? 'gold' : ''));
        el.textContent = state === '实时' ? '实时' : (state === '轮询' ? '轮询' : state);
      }

      function drawHost() {
        var el = document.getElementById('dash-host');
        if (!el) return;
        function pct(v) { return (v === undefined || v === null) ? '—' : Math.round(v) + '%'; }
        el.innerHTML =
          stat('CPU 占用', pct(host.cpu_percent), (host.cpu_count || '?') + ' 核') +
          stat('内存', pct(host.mem_percent),
               (host.mem_used_mb ? Math.round(host.mem_used_mb / 1024) + ' / ' +
                Math.round((host.mem_total_mb || 0) / 1024) + ' GB' : '—')) +
          stat('磁盘剩余', (host.disk_free_gb === undefined ? '—' : host.disk_free_gb + ' GB'),
               '数据目录所在盘（已用 ' + pct(host.disk_percent) + '）') +
          stat('实例', String(insts.length),
               insts.filter(function (i) { return i.running; }).length + ' 个运行中');
      }

      function stat(k, v, s) {
        return '<div class="stat"><div class="k">' + U.esc(k) + '</div>' +
          '<div class="v">' + U.esc(v) + '</div><div class="s">' + U.esc(s) + '</div></div>';
      }

      function ringPercent(it) {
        if (it.status === 'starting' || it.status === 'stopping') return 60;
        if (it.running) {
          var p = Number(it.cpu) || 0;
          return p > 90 ? 100 : (p > 5 ? Math.round(p) : 25);
        }
        return it.status === 'crashed' ? 100 : 0;
      }

      function find(id) { return insts.filter(function (x) { return String(x.id) === String(id); })[0]; }

      /* ---------------------------------------------------------------- 交互 */
      function bind() {
        var rf = document.getElementById('dash-refresh');
        if (rf) rf.addEventListener('click', function () { C.withLoading(rf, load(true)); });

        body.querySelectorAll('[data-open]').forEach(function (el) {
          el.addEventListener('click', function () {
            location.hash = '#/instances/' + el.getAttribute('data-open') + '/console';
          });
        });
        body.querySelectorAll('[data-go]').forEach(function (el) {
          el.addEventListener('click', function () { location.hash = el.getAttribute('data-go'); });
        });

        /* 置顶 */
        body.querySelectorAll('[data-pin]').forEach(function (b) {
          b.addEventListener('click', function (e) {
            e.stopPropagation();
            var id = Number(b.getAttribute('data-pin'));
            var i = pins.indexOf(id);
            if (i >= 0) { pins.splice(i, 1); Toast.info('已取消置顶'); }
            else { pins.unshift(id); Toast.ok('已置顶：' + ((find(id) || {}).name || id)); }
            writeJson(PIN_KEY, pins);
            draw();
          });
        });

        /* 启停 */
        body.querySelectorAll('[data-act]').forEach(function (b) {
          b.addEventListener('click', function (e) {
            e.stopPropagation();
            var id = b.getAttribute('data-id');
            var act = b.getAttribute('data-act');
            var it = find(id) || {};
            var map = { start: '启动', stop: '停止', restart: '重启' };
            var run = function () {
              C.withLoading(b, API.post('/api/instances/' + id + '/' + act, {}).then(function (r) {
                Toast.ok('已请求' + map[act] + '：' + (it.name || id) + (r.note ? '（' + r.note + '）' : ''));
                setTimeout(function () { load(); }, 700);
              }).catch(function (err) { Toast.err(map[act] + '失败：' + err.message); }));
            };
            if (act === 'stop') {
              C.Modal.confirm('停止实例', '先发送 stop 优雅停止，30 秒未退出则强制结束进程树。确定继续？', run);
            } else run();
          });
        });

        /* 拖动排序（HTML5 DnD；置顶组与普通组各自可排） */
        var dragId = null;
        body.querySelectorAll('.dash-card').forEach(function (c) {
          c.addEventListener('dragstart', function (e) {
            dragId = Number(c.getAttribute('data-id'));
            try { e.dataTransfer.setData('text/plain', String(dragId)); } catch (x) {}
            c.classList.add('dragging');
          });
          c.addEventListener('dragend', function () { c.classList.remove('dragging'); });
          c.addEventListener('dragover', function (e) { e.preventDefault(); c.classList.add('drag-over'); });
          c.addEventListener('dragleave', function () { c.classList.remove('drag-over'); });
          c.addEventListener('drop', function (e) {
            e.preventDefault();
            c.classList.remove('drag-over');
            var target = Number(c.getAttribute('data-id'));
            if (!dragId || dragId === target) return;
            /* 把被拖的卡片插到目标位置 */
            var list = ordered().map(function (x) { return x.id; });
            var from = list.indexOf(dragId);
            var to = list.indexOf(target);
            if (from < 0 || to < 0) return;
            list.splice(from, 1);
            list.splice(to, 0, dragId);
            order = list;
            writeJson(ORDER_KEY, order);
            draw();
            Toast.info('已保存排序');
          });
        });
      }

      /* ---------------------------------------------------------------- 实时通道
         一条 WebSocket 推送**全部实例**的轻量状态（服务端每 2 秒一帧，纯内存读取）。
         断线按 1s→2s→5s→10s 退避重连；连续失败则退到 10 秒轮询兜底，并如实显示状态。*/
      var ws = null, wsRetry = 0, wsTimer = null, pollTimer = null, alive = true;

      function wsConnect() {
        if (!alive || !document.getElementById('dash-host')) return;
        try { ws = new WebSocket(API.wsUrl('/api/dashboard/ws')); } catch (e) { scheduleReconnect(); return; }
        ws.onopen = function () {
          wsRetry = 0;
          if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
          setLive('实时');
        };
        ws.onmessage = function (ev) {
          var m;
          try { m = JSON.parse(ev.data); } catch (e) { return; }
          if (m.type === 'live') applyLive(m);
        };
        ws.onclose = function () {
          ws = null;
          if (!alive) return;
          setLive(pollTimer ? '轮询' : '重连中');
          scheduleReconnect();
        };
        ws.onerror = function () { try { ws.close(); } catch (e) {} };
      }

      function scheduleReconnect() {
        if (wsTimer) clearTimeout(wsTimer);
        wsRetry += 1;
        if (wsRetry >= 4 && !pollTimer) startFallbackPoll();
        var delay = Math.min(10000, [0, 1000, 2000, 5000, 10000][Math.min(wsRetry, 4)]);
        wsTimer = setTimeout(wsConnect, delay);
      }

      /* 兜底轮询：WS 连续失败时保证页面仍然会更新（同时把状态标成"轮询"） */
      function startFallbackPoll() {
        if (pollTimer) return;
        setLive('轮询');
        pollTimer = setInterval(function () {
          if (!alive || !document.getElementById('dash-host')) { clearInterval(pollTimer); pollTimer = null; return; }
          load();
        }, 10000);
        Store.state.pollers.push(pollTimer);
      }

      function stopLive() {
        alive = false;
        if (wsTimer) { clearTimeout(wsTimer); wsTimer = null; }
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        if (ws) { try { ws.close(); } catch (e) {} ws = null; }
      }

      /* 首帧走 HTTP（含 core_label / port / memory_mb 等 HTTP 独有字段），随后交给 WS */
      load().then(function () { wsConnect(); });
      return { destroy: stopLive };
    }
  });
};
