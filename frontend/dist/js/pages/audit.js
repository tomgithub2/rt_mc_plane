/* 审计日志页：面板操作 / 登录记录 */
window.Pages = window.Pages || {};

Pages.audit = function (app) {
  app.innerHTML = C.shell({
    active: 'audit',
    crumbs: [{ text: '面板', hash: '#/audit' }, { text: '审计日志' }]
  });
  C.bindShell(app);
  var body = document.getElementById('page-body');
  var TAB = 'audit', filter = '', instFilter = '';

  body.innerHTML = '' +
    '<div class="page-head"><div class="titles"><div class="kicker">Audit Trail</div>' +
      '<h1>审计日志</h1><div class="sub">谁在什么时候对哪个实例做了什么 —— 面板自身的操作记录</div></div>' +
      '<div class="acts"><button class="btn sm" id="a-refresh">' + Icon.svg('refresh', 15) + '刷新</button></div></div>' +
    '<div class="tabs">' +
      '<div class="tab active" data-t="audit">操作日志</div>' +
      '<div class="tab" data-t="login">登录记录</div></div>' +
    '<div class="card"><div class="card-head">' +
      '<div class="search-box" style="flex:1 1 240px">' + Icon.svg('search', 15) +
        '<input type="text" id="a-filter" placeholder="按动作过滤，例如 file. / instance. / cron." /></div>' +
      '<div class="right"><span class="badge" id="a-count">—</span></div></div>' +
    '<div id="a-list"><div class="loading"><span class="spinner"></span>读取中…</div></div></div>';

  body.querySelectorAll('[data-t]').forEach(function (el) {
    el.addEventListener('click', function () {
      TAB = el.getAttribute('data-t');
      body.querySelectorAll('[data-t]').forEach(function (x) { x.classList.remove('active'); });
      el.classList.add('active');
      load();
    });
  });
  document.getElementById('a-refresh').addEventListener('click', load);
  document.getElementById('a-filter').addEventListener('input', U.debounce(function (e) {
    filter = e.target.value.trim(); load();
  }, 250));

  function levelBadge(l) {
    if (l === 'error') return '<span class="badge err">错误</span>';
    if (l === 'warn') return '<span class="badge" style="color:var(--warning);border-color:color-mix(in srgb,var(--warning) 45%,transparent)">警告</span>';
    return '<span class="badge">信息</span>';
  }

  function load() {
    if (TAB === 'login') {
      API.get('/api/audit/login?limit=300').then(function (d) {
        var rows = d.logs || [];
        document.getElementById('a-count').textContent = rows.length + ' 条';
        document.getElementById('a-list').innerHTML = rows.length
          ? '<div class="table-wrap"><table><thead><tr><th class="mono">时间</th><th>账号</th>' +
            '<th class="mono">来源 IP</th><th>结果</th><th>原因</th><th>User-Agent</th></tr></thead><tbody>' +
            rows.map(function (r) {
              return '<tr><td class="mono num">' + U.fmtTime(r.ts, true) + '</td>' +
                '<td>' + U.esc(r.username) + '</td><td class="mono">' + U.esc(r.ip) + '</td>' +
                '<td>' + (r.success ? '<span class="badge ok">成功</span>' : '<span class="badge err">失败</span>') + '</td>' +
                '<td class="small">' + U.esc(r.reason || '') + '</td>' +
                '<td class="small faint">' + U.esc((r.ua || '').slice(0, 60)) + '</td></tr>';
            }).join('') + '</tbody></table></div>'
          : C.empty('audit', '还没有登录记录', '登录成功与失败都会记录在这里，包含来源 IP 与原因。', '');
      }).catch(function (e) {
        if (Perm.denyIfForbidden(e, app, { perm: 'audit.view', active: 'audit',
                                           crumbs: [{ text: '面板' }, { text: '审计日志' }] })) return;
        document.getElementById('a-list').innerHTML = '<div class="tip err">' + U.esc(e.message) + '</div>';
      });
      return;
    }
    API.get('/api/audit?limit=400' + (filter ? '&action=' + encodeURIComponent(filter) : '')).then(function (d) {
      var rows = d.logs || [];
      document.getElementById('a-count').textContent = (d.total || rows.length) + ' 条';
      document.getElementById('a-list').innerHTML = rows.length
        ? '<div class="table-wrap"><table><thead><tr><th class="mono">时间</th><th>操作人</th>' +
          '<th class="mono">来源 IP</th><th>动作</th><th class="mono">实例</th><th>级别</th><th>详情</th></tr></thead><tbody>' +
          rows.map(function (r) {
            return '<tr><td class="mono num">' + U.fmtTime(r.ts, true) + '</td>' +
              '<td>' + U.esc(r.user || 'system') + '</td>' +
              '<td class="mono small">' + U.esc(r.ip || '—') + '</td>' +
              '<td><span class="tag">' + U.esc(r.action) + '</span></td>' +
              '<td class="mono">' + (r.instance_id ? '<a href="#/instances/' + r.instance_id + '">#' + r.instance_id + '</a>' : '—') + '</td>' +
              '<td>' + levelBadge(r.level) + '</td>' +
              '<td class="small">' + U.esc(r.detail || '') + '</td></tr>';
          }).join('') + '</tbody></table></div>'
        : C.empty('audit', '没有匹配的审计记录', '换个关键字试试，或先做一次操作（创建实例、改配置、备份等）。', '');
    }).catch(function (e) {
      if (Perm.denyIfForbidden(e, app, { perm: 'audit.view', active: 'audit',
                                         crumbs: [{ text: '面板' }, { text: '审计日志' }] })) return;
      document.getElementById('a-list').innerHTML = '<div class="tip err">' + U.esc(e.message) + '</div>';
    });
  }
  load();
};
