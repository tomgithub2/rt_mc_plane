/* 账号管理页（#/accounts）：仅 user.manage 可见
   ----------------------------------------------------------------------------
   数据：**真实后端** `/api/users`（契约 §1.16）——
   原实现走 MockAccounts（本地假数据），已全部换成 API.get/post/patch/del。

   契约约束已内建：
     · 重置口令一次性回显 + 复制，弹窗关闭后从 DOM 移除（不写 localStorage / 不写 console）
     · 删除 / 强制下线 / 重置口令 一律二次确认
     · 无 user.manage 权限 → 设计过的「权限不足」空状态（不白屏、不裸 403）
     · 后端 400/403/409 的中文 detail 原样 toast 给用户（不吞、不改写）
   ========================================================================== */
window.Pages = window.Pages || {};

/* 设计过的「权限不足」空状态（越权页面统一使用，避免白屏或裸 403） */
window.PermDenied = function (app, opts) {
  opts = opts || {};
  var meta = Perm.roleMeta();
  var body = '' +
    '<div class="page-head"><div class="titles">' +
      '<div class="kicker">Access Denied</div><h1>权限不足</h1>' +
      '<div class="sub">当前账号没有访问这个页面的权限</div></div></div>' +
    '<div class="card">' +
      '<div class="empty">' +
        '<div class="art">' + Icon.svg('shieldCheck', 34) + '</div>' +
        '<div class="t">缺少权限：<span class="mono">' + U.esc(opts.perm || '未知') + '</span></div>' +
        '<div class="d">你的角色是「' + U.esc(meta.name || '未知') + '」，该角色不包含这个权限点。' +
          '这不是错误，是设计如此 —— 面板按最小权限原则工作。<br>' +
          '需要的话请让<b>超级管理员</b>在「账号管理」里调整你的角色或配额。</div>' +
        '<div class="row" style="justify-content:center">' +
          '<button class="btn primary" onclick="location.hash=\'#/instances\'">' +
            Icon.svg('instances', 15) + '返回实例列表</button>' +
          '<button class="btn" onclick="location.hash=\'#/settings\'">前往设置</button>' +
        '</div>' +
      '</div>' +
      '<hr class="hair" />' +
      '<div class="kv small">' +
        '<div class="k">你的角色</div><div class="v">' + U.esc(meta.name || '') + '（' + U.esc(Perm.role() || '') + '）</div>' +
        '<div class="k">该角色说明</div><div class="v">' + U.esc(meta.desc || '') + '</div>' +
        '<div class="k">需要的权限点</div><div class="v">' + U.esc(opts.perm || '') + '</div>' +
      '</div>' +
      '<div class="tip mt small">前端隐藏入口只是体验优化；<b>真正的边界在后端</b> —— ' +
        '即使直接构造请求，后端也会返回 403。</div>' +
    '</div>';
  app.innerHTML = C.shell({ active: opts.active || '', crumbs: opts.crumbs || [{ text: '权限不足' }] });
  C.bindShell(app);
  document.getElementById('page-body').innerHTML = body;
};

Pages.accounts = function (app) {
  app.innerHTML = C.shell({
    active: 'accounts',
    crumbs: [{ text: '面板', hash: '#/accounts' }, { text: '账号管理' }]
  });
  C.bindShell(app);

  Perm.load().then(function () {
    if (!Perm.has('user.manage')) {
      return PermDenied(app, { perm: 'user.manage', active: 'accounts',
                              crumbs: [{ text: '面板' }, { text: '账号管理' }] });
    }
    var body = document.getElementById('page-body');
    var filter = '';
    var data = { users: [], total: 0, roles: [] };   // 最近一次 /api/users 的响应
    var me = (Store.state.user || {});

    body.innerHTML = '' +
      '<div class="page-head"><div class="titles">' +
        '<div class="kicker">Accounts &amp; Roles</div><h1>账号管理</h1>' +
        '<div class="sub">默认账号是<b>超级管理员</b>；可创建管理员 / 普通用户 / 只读，并逐项设置配额。' +
        '口令只在服务器终端或重置响应里出现一次，面板永不显示明文。</div></div>' +
        '<div class="acts">' +
          '<button class="btn sm" id="u-reload" title="重新拉取">' + Icon.svg('refresh', 14) + '刷新</button>' +
          '<button class="btn sm primary" id="u-new">' + Icon.svg('userPlus', 15) + '新建用户</button>' +
        '</div></div>' +
      '<div class="grid cols-4 mb" id="u-stats"></div>' +
      '<div class="card"><div class="card-head">' +
        '<div class="search-box" style="flex:1 1 240px">' + Icon.svg('search', 15) +
          '<input type="text" id="u-filter" placeholder="搜索用户名" /></div>' +
        '<div class="right"><span class="badge" id="u-count">—</span></div></div>' +
        '<div id="u-list"></div></div>';

    function roles() {
      var out = {};
      (data.roles || []).forEach(function (r) { out[r.key] = r; });
      return out;
    }

    function reload() {
      return API.get('/api/users?limit=500').then(function (d) {
        data = d || { users: [], total: 0, roles: [] };
        draw();
      }).catch(function (e) {
        if (e.status === 403) return PermDenied(app, { perm: 'user.manage', active: 'accounts',
                                                       crumbs: [{ text: '面板' }, { text: '账号管理' }] });
        document.getElementById('u-list').innerHTML = C.empty('users', '加载失败',
          e.message || '无法获取用户列表', '<button class="btn primary" id="u-retry">重试</button>');
        var rb = document.getElementById('u-retry');
        if (rb) rb.addEventListener('click', reload);
      });
    }

    function draw() {
      var users = data.users || [];
      var rows = users.filter(function (u) {
        return !filter || u.username.toLowerCase().indexOf(filter) >= 0;
      });
      var byRole = {};
      users.forEach(function (u) { byRole[u.role] = (byRole[u.role] || 0) + 1; });
      document.getElementById('u-stats').innerHTML =
        stat('用户总数', String(users.length), users.filter(function (u) { return u.status; }).length + ' 个启用') +
        stat('超级管理员', String(byRole.super_admin || 0), '至少保留 1 个') +
        stat('管理员', String(byRole.admin || 0), '可管所有实例') +
        stat('普通用户 / 只读', (byRole.user || 0) + ' / ' + (byRole.viewer || 0), '受配额与只读限制');
      document.getElementById('u-count').textContent = rows.length + ' / ' + users.length;

      document.getElementById('u-list').innerHTML = rows.length
        ? '<div class="table-wrap"><table><thead><tr>' +
          '<th>用户名</th><th>角色</th><th>状态</th><th>配额</th>' +
          '<th class="mono">实例数</th><th class="mono">最近登录</th><th style="text-align:right">操作</th>' +
          '</tr></thead><tbody>' + rows.map(row).join('') + '</tbody></table></div>'
        : C.empty('users', '没有匹配的用户', '换个关键字，或点右上角「新建用户」创建一个。', '');
      bind();
    }

    function stat(k, v, s) {
      return '<div class="stat"><div class="k">' + U.esc(k) + '</div>' +
        '<div class="v">' + U.esc(v) + '</div><div class="s">' + U.esc(s) + '</div></div>';
    }

    function row(u) {
      var meta = roles()[u.role] || {};
      var q = u.quota || {};
      var self = (u.id === me.id);
      return '<tr>' +
        '<td><b>' + U.esc(u.username) + '</b>' + (self ? ' <span class="badge gold">当前账号</span>' : '') + '</td>' +
        '<td><span class="badge ' + U.esc(meta.cls || '') + '">' + U.esc(meta.name || u.role) + '</span></td>' +
        '<td>' + (u.status
          ? '<span class="badge running"><span class="dot"></span>启用</span>'
          : '<span class="badge">已停用</span>') + '</td>' +
        '<td class="small mono">实例 ' + (q.max_instances || 0) +
          ' · 内存 ' + (q.max_memory_mb_total || 0) + 'MB' +
          ' · 备份 ' + (q.max_backups || 0) +
          ' · 上传 ' + (q.max_upload_mb || 0) + 'MB' +
          (q.allow_build_import ? ' · 建筑导入✔' : ' · 建筑导入✘') + '</td>' +
        '<td class="mono num">' + (u.instance_count || 0) + '</td>' +
        '<td class="mono num">' + (u.last_login ? U.fmtTime(u.last_login, true) : '从未') + '</td>' +
        '<td style="text-align:right" class="nowrap">' +
          '<button class="btn xs" data-edit="' + u.id + '">改角色/配额</button> ' +
          '<button class="btn xs" data-pw="' + u.id + '">重置口令</button> ' +
          '<button class="btn xs" data-toggle="' + u.id + '">' + (u.status ? '停用' : '启用') + '</button> ' +
          '<button class="btn xs" data-kick="' + u.id + '">强制下线</button> ' +
          '<button class="btn xs danger" data-del="' + u.id + '">删除</button>' +
        '</td></tr>';
    }

    function find(id) {
      return (data.users || []).filter(function (x) { return x.id === id; })[0];
    }

    function bind() {
      var nw = document.getElementById('u-new');
      if (nw) nw.addEventListener('click', createUser);
      var rl = document.getElementById('u-reload');
      if (rl) rl.addEventListener('click', function () { C.withLoading(rl, reload()).catch(function () {}); });
      var fi = document.getElementById('u-filter');
      if (fi) fi.addEventListener('input', U.debounce(function (e) {
        filter = e.target.value.trim().toLowerCase(); draw();
      }, 200));

      document.querySelectorAll('[data-edit]').forEach(function (b) {
        b.addEventListener('click', function () { editUser(Number(b.getAttribute('data-edit'))); });
      });
      document.querySelectorAll('[data-pw]').forEach(function (b) {
        b.addEventListener('click', function () { resetPw(Number(b.getAttribute('data-pw'))); });
      });
      document.querySelectorAll('[data-toggle]').forEach(function (b) {
        b.addEventListener('click', function () { toggleUser(Number(b.getAttribute('data-toggle'))); });
      });
      document.querySelectorAll('[data-kick]').forEach(function (b) {
        b.addEventListener('click', function () { kickUser(Number(b.getAttribute('data-kick'))); });
      });
      document.querySelectorAll('[data-del]').forEach(function (b) {
        b.addEventListener('click', function () { delUser(Number(b.getAttribute('data-del'))); });
      });
    }

    function roleSelect(id, val) {
      var rs = roles();
      return '<select id="' + id + '">' + Object.keys(rs).map(function (r) {
        var m = rs[r];
        return '<option value="' + U.esc(r) + '"' + (val === r ? ' selected' : '') + '>' +
          U.esc(m.name) + ' —— ' + U.esc(m.desc) + '</option>';
      }).join('') + '</select>';
    }

    function quotaForm(p, id) {
      p = p || {};
      return '<div class="grid cols-2 tight">' +
        '<div class="field"><label>最大实例数</label><input type="number" class="num" id="' + id + '-mi" value="' + (p.max_instances || 0) + '" min="0" /></div>' +
        '<div class="field"><label>内存总配额（MB）</label><input type="number" class="num" id="' + id + '-mm" value="' + (p.max_memory_mb_total || 0) + '" min="0" step="512" /></div>' +
        '<div class="field"><label>最大备份数</label><input type="number" class="num" id="' + id + '-mb" value="' + (p.max_backups || 0) + '" min="0" /></div>' +
        '<div class="field"><label>单文件上传上限（MB）</label><input type="number" class="num" id="' + id + '-mu" value="' + (p.max_upload_mb || 0) + '" min="0" /></div>' +
        '</div>' +
        '<label class="check"><input type="checkbox" id="' + id + '-bi"' + (p.allow_build_import ? ' checked' : '') + ' />允许建筑导入</label>';
    }

    function readQuota(id) {
      function num(suffix) {
        var el = document.getElementById(id + suffix);
        return el ? (parseInt(el.value, 10) || 0) : 0;
      }
      var bi = document.getElementById(id + '-bi');
      return {
        max_instances: num('-mi'),
        max_memory_mb_total: num('-mm'),
        max_backups: num('-mb'),
        max_upload_mb: num('-mu'),
        allow_build_import: !!(bi && bi.checked)
      };
    }

    /* 统一的失败处理：把后端的中文 detail 原样给用户（403 单独提示"权限不足"） */
    function fail(e) {
      if (e && e.status === 403) Perm.denied(e);
      else Toast.err((e && e.message) || '操作失败');
    }

    function createUser() {
      C.Modal.open({
        title: '新建用户', okText: '创建', wide: true,
        body: '<div class="tip mb">口令遵循面板统一策略：<b>至少 12 位且含大小写/数字/符号中至少三类</b>。' +
              '留空则由面板随机生成，生成结果会在创建后<b>一次性</b>显示，请当场复制给用户。</div>' +
          '<div class="grid cols-2 tight">' +
            '<div class="field"><label>用户名</label><input type="text" id="nu-name" placeholder="3–32 位字母/数字/_.-" /></div>' +
            '<div class="field"><label>初始口令（可留空自动生成）</label><input type="text" id="nu-pw" class="mono" /></div>' +
          '</div>' +
          '<div class="field"><label>角色</label>' + roleSelect('nu-role', 'user') + '</div>' +
          '<div class="kicker mb mt">配额</div>' +
          quotaForm({ max_instances: 3, max_memory_mb_total: 8192, max_backups: 5, max_upload_mb: 128 }, 'nu'),
        onOk: function (m) {
          var payload = {
            username: (m.querySelector('#nu-name').value || '').trim(),
            password: (m.querySelector('#nu-pw').value || '').trim(),
            role: m.querySelector('#nu-role').value,
            quota: readQuota('nu')
          };
          return API.post('/api/users', payload).then(function (r) {
            var plain = payload.password || (r && r.password) || '';
            if (plain) showOnce('用户已创建', payload.username, plain, r && r.note);
            else Toast.ok('用户已创建');
            return reload().then(function () { return false; });   // 保持弹窗在"一次性口令"里
          }).catch(function (e) { fail(e); return false; });
        }
      });
    }

    function editUser(id) {
      var u = find(id);
      if (!u) return;
      C.Modal.open({
        title: '编辑「' + u.username + '」', okText: '保存', wide: true,
        body: '<div class="tip mb">超级管理员不可被降级、停用或删除；系统内至少保留 1 个；也不允许自我降级/自我停用。</div>' +
          '<div class="field"><label>角色</label>' + roleSelect('eu-role', u.role) + '</div>' +
          '<label class="check mb"><input type="checkbox" id="eu-status"' + (u.status ? ' checked' : '') + ' />账号启用</label>' +
          '<div class="kicker mb">配额</div>' + quotaForm(u.quota || {}, 'eu'),
        onOk: function (m) {
          return API.patch('/api/users/' + id, {
            role: m.querySelector('#eu-role').value,
            status: m.querySelector('#eu-status').checked ? 1 : 0,
            quota: readQuota('eu')
          }).then(function (r) {
            Toast.ok('已保存：' + ((r && r.changed) || []).join('、') || '无变化');
            return reload();
          }).catch(function (e) { fail(e); return false; });
        }
      });
    }

    function toggleUser(id) {
      var u = find(id);
      if (!u) return;
      var next = u.status ? 0 : 1;
      C.Modal.confirm(next ? '启用账号' : '停用账号',
        (next ? '将启用「' : '将停用「') + u.username + '」。停用后该账号所有会话立即失效、无法登录。确定？',
        function () {
          return API.patch('/api/users/' + id, { status: next }).then(function () {
            Toast.ok('已' + (next ? '启用' : '停用'));
            return reload();
          }).catch(function (e) { fail(e); return false; });
        }, !next);
    }

    function kickUser(id) {
      var u = find(id);
      if (!u) return;
      C.Modal.confirm('强制下线', '将立即作废「' + u.username + '」的全部会话（token_epoch +1），' +
        '对方下次请求会跳回登录页。确定？', function () {
        return API.post('/api/users/' + id + '/kick', {}).then(function (r) {
          Toast.ok((r && r.note) || '已强制下线');
          return reload();
        }).catch(function (e) { fail(e); return false; });
      }, true);
    }

    function delUser(id) {
      var u = find(id);
      if (!u) return;
      C.Modal.open({
        title: '删除用户「' + u.username + '」', danger: true, okText: '确认删除',
        body: '<div class="tip err mb">删除不可恢复。该用户名下有 <b>' + (u.instance_count || 0) +
          '</b> 个实例：需要先<b>转移归属</b>，或者勾选下面「一并删除」把实例也删掉。</div>' +
          '<label class="check"><input type="checkbox" id="du-purge" />一并删除其名下实例（不可恢复）</label>' +
          (u.role === 'super_admin' ? '<div class="tip warn mt">该账号是超级管理员：删除前请确认系统里还有另一位超管。</div>' : ''),
        onOk: function (m) {
          var purge = m.querySelector('#du-purge').checked;
          return API.del('/api/users/' + id + '?purge_instances=' + (purge ? 'true' : 'false'))
            .then(function (r) {
              Toast.ok((r && r.note) || '已删除');
              return reload();
            }).catch(function (e) { fail(e); return false; });
        }
      });
    }

    /* 重置口令：一次性回显 + 复制；弹窗关闭后从 DOM 移除，不留痕 */
    function resetPw(id) {
      var u = find(id);
      if (!u) return;
      C.Modal.confirm('重置「' + u.username + '」的口令',
        '将生成一个新的随机口令。该用户所有会话会立即失效，必须用新口令重新登录。' +
        '新口令只显示一次，关闭弹窗后无法再查看。确定？', function () {
        return API.post('/api/users/' + id + '/password', {}).then(function (r) {
          showOnce('口令已重置', u.username, (r && r.password) || '', r && r.note);
          return reload();
        }).catch(function (e) { fail(e); return false; });
      }, true);
    }

    /* 一次性口令弹窗：关闭时把明文从 DOM 摘掉（不写 localStorage、不写 console） */
    function showOnce(title, username, plain, note) {
      var m = C.Modal.open({
        title: title, footer: false,
        body: '<div class="tip warn mb">' + U.esc(note ||
            '该口令只在这里显示一次。关闭本窗口后将无法再次查看（服务端只存 PBKDF2 哈希）。') + '</div>' +
          '<div class="field"><label>用户名</label><input type="text" value="' + U.esc(username) + '" readonly /></div>' +
          '<div class="field"><label>口令（一次性）</label>' +
            '<div class="row tight"><input type="text" id="once-pw" class="mono" value="' + U.esc(plain) + '" readonly />' +
            '<button class="btn" id="once-copy">' + Icon.svg('copy', 14) + '复制</button></div></div>' +
          '<div class="row" style="justify-content:flex-end"><button class="btn primary" id="once-close">我已保存，关闭</button></div>',
        onMount: function (mask) {
          var btn = mask.querySelector('#once-copy');
          btn.addEventListener('click', function () {
            var inp = mask.querySelector('#once-pw');
            inp.select();
            var ok = false;
            try { ok = document.execCommand('copy'); } catch (e) {}
            if (navigator.clipboard) {
              navigator.clipboard.writeText(inp.value).then(function () { Toast.ok('已复制到剪贴板'); },
                function () { Toast.warn(ok ? '已复制' : '复制失败，请手动选中复制'); });
            } else {
              Toast.ok(ok ? '已复制到剪贴板' : '请手动选中复制');
            }
          });
          mask.querySelector('#once-close').addEventListener('click', function () {
            var inp = mask.querySelector('#once-pw');
            if (inp) inp.value = '';          // 关闭前清空明文
            C.Modal.close();
          });
        }
      });
      return m;
    }

    reload();
  }).catch(function (e) {
    /* 顶层权限接口失败（401 已在 api.js 里跳登录；其它情况给可读的失败态） */
    if (e && e.status !== 401) {
      document.getElementById('page-body').innerHTML = C.empty('shieldCheck', '无法获取权限信息',
        (e && e.message) || '请稍后重试', '<button class="btn primary" onclick="Router.refresh()">重试</button>');
    }
  });
};
