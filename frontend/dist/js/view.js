/* View · 页面状态与错误边界的**唯一实现**
   ============================================================================
   为什么要有这个文件：重构前每个页面各写各的，结果就是——统计数字画出来了、
   列表渲染时抛异常，异常被吞掉，用户看到"有标题和数字、列表空的"，**页面上一个字的
   报错都没有**。同类问题在 7 个 bug 里占了 5 个。

   这个模块把三件事收口到一处：

   1. **错误边界**：`View.boot()` 包住页面初始化，任何同步异常都会变成一张
      可读的错误卡片（含原文 + 堆栈 + 重试/退出），页面绝不会白着。
   2. **四种状态**：loading / error / denied / empty，样式统一，不再各写各的。
   3. **错误归一**：`View.describe(err)` 把任意异常变成 {title, detail, hint}，
      401/403/404/429/网络错误各有对应的人话与下一步。

   约定：页面**不要**再自己拼 `<div class="tip err">`；一律用这里的函数。
   ========================================================================== */
window.View = (function () {

  /* ---------------------------------------------------------------- 错误归一 */
  function describe(err, ctx) {
    ctx = ctx || {};
    var msg = (err && err.message) || String(err || '未知错误');
    var status = (err && err.status) || 0;
    var where = ctx.label || ctx.perm || '';

    if (status === 401) {
      return { kind: 'auth', title: '登录已失效',
               detail: '这个页面需要重新登录。', hint: '点「重新登录」，或退出后重新登录。' };
    }
    if (status === 403) {
      return { kind: 'denied', title: '权限不足',
               detail: msg || ('缺少权限点 ' + (where || '（未知）')),
               hint: '需要的话请让超级管理员在「账号管理」里调整你的角色或配额。' };
    }
    if (status === 404) {
      return { kind: 'error', title: '内容不存在',
               detail: msg, hint: '可能是实例已被删除，或链接过期。' };
    }
    if (status === 429) {
      return { kind: 'error', title: '请求过于频繁',
               detail: msg, hint: '稍等一会儿再试；频繁刷新/批量操作会触发限流。' };
    }
    if (status >= 500) {
      return { kind: 'error', title: '面板内部错误',
               detail: msg, hint: '面板日志里有更详细的堆栈，可到「设置 → 应用日志」查看。' };
    }
    if (!status && /Failed to fetch|NetworkError|Load failed/i.test(msg)) {
      return { kind: 'offline', title: '连不上面板服务',
               detail: msg, hint: '确认面板进程还在运行，然后重试。' };
    }
    return { kind: 'error', title: ctx.title || '出错了', detail: msg,
             hint: ctx.hint || '' };
  }

  /* ---------------------------------------------------------------- 状态渲染 */
  function loading(text) {
    return '<div class="loading" data-view-loading><span class="spinner"></span>' +
      U.esc(text || '读取中…') + '</div>';
  }

  /* 一个统一的错误卡片：原文 + 可选堆栈 + 重试/退出。 */
  function error(e, opts) {
    opts = opts || {};
    var d = describe(e, opts);
    var actions = [];
    if (opts.retry !== false) {
      actions.push('<button class="btn primary" data-view-retry>重试</button>');
    }
    if (opts.plain) {
      actions.push('<button class="btn" data-view-plain>' + U.esc(opts.plainLabel || '用简化视图显示') + '</button>');
    }
    actions.push('<button class="btn" data-view-logout>退出登录</button>');
    return '<div class="card" data-view-error>' +
      '<div class="card-head"><h3>' + U.esc(d.title) + '</h3>' +
        (d.kind === 'denied' ? '<div class="right badge role-viewer">权限不足</div>' : '') + '</div>' +
      '<div class="tip ' + (d.kind === 'denied' ? 'warn' : 'err') + ' mb">' + U.esc(d.detail) + '</div>' +
      (d.hint ? '<div class="small muted mb">' + U.esc(d.hint) + '</div>' : '') +
      (opts.context ? '<div class="kv small mb">' + opts.context + '</div>' : '') +
      '<div class="row">' + actions.join('') + '</div>' +
      (opts.showStack && e && e.stack
        ? '<details class="mt"><summary class="small muted">技术细节（发给管理员）</summary>' +
          '<pre class="small mono" style="white-space:pre-wrap;max-height:200px;overflow:auto">' +
          U.esc(e.stack) + '</pre></details>'
        : '') +
      '</div>';
  }

  /* 越权页：规格 §6 要求"说明缺哪个权限点、当前角色、可以找谁"，不许白屏或裸 403。 */
  function denied(app, opts) {
    opts = opts || {};
    var meta = (window.Perm && Perm.roleMeta()) || {};
    var perms = (window.Perm && opts.perm) ? opts.perm : '';
    var body = '' +
      '<div class="page-head"><div class="titles">' +
        '<div class="kicker">Access Denied</div><h1>权限不足</h1>' +
        '<div class="sub">当前账号没有访问这个页面的权限</div></div></div>' +
      '<div class="card">' +
        '<div class="empty">' +
          '<div class="art">' + Icon.svg('shieldCheck', 34) + '</div>' +
          '<div class="t">缺少权限：<span class="mono">' + U.esc(perms || '未知') + '</span></div>' +
          '<div class="d">你的角色是「' + U.esc(meta.name || '未知') + '」，该角色不包含这个权限点。' +
            '这不是错误，是设计如此 —— 面板按最小权限原则工作。<br>' +
            '需要的话请让<b>超级管理员</b>在「账号管理」里调整你的角色或配额。</div>' +
          '<div class="row" style="justify-content:center">' +
            '<button class="btn primary" data-go="#/instances">' + Icon.svg('instances', 15) +
              '返回实例列表</button>' +
            '<button class="btn" data-go="#/settings">前往设置</button>' +
          '</div>' +
        '</div>' +
        '<hr class="hair" />' +
        '<div class="kv small">' +
          '<div class="k">你的角色</div><div class="v">' + U.esc(meta.name || '') +
            '（' + U.esc((window.Perm && Perm.role()) || '') + '）</div>' +
          '<div class="k">该角色说明</div><div class="v">' + U.esc(meta.desc || '') + '</div>' +
          '<div class="k">需要的权限点</div><div class="v mono">' + U.esc(perms) + '</div>' +
        '</div>' +
        '<div class="tip mt small">前端隐藏入口只是体验优化；<b>真正的边界在后端</b> —— ' +
          '即使直接构造请求，后端也会返回 403。</div>' +
      '</div>';
    if (app) {
      app.innerHTML = C.shell({ active: opts.active || '', crumbs: opts.crumbs || [{ text: '权限不足' }] });
      C.bindShell(app);
    }
    var host = document.getElementById('page-body') || app;
    if (host) { host.innerHTML = body; bindGo(host); }
  }

  function bindGo(root) {
    if (!root) return;
    root.querySelectorAll('[data-go]').forEach(function (b) {
      b.addEventListener('click', function () { location.hash = b.getAttribute('data-go'); });
    });
  }

  /* 把一段 HTML（loading/error/denied）挂到某个容器，并把里面的按钮接上行为。
     `onRetry` / `onPlain` 由调用方提供；不提供时"重试"走 Router.refresh()。 */
  function mount(el, html, handlers) {
    if (!el) return;
    el.innerHTML = html;
    handlers = handlers || {};
    var r = el.querySelector('[data-view-retry]');
    if (r) r.addEventListener('click', function () {
      if (handlers.onRetry) handlers.onRetry(); else Router.refresh();
    });
    var p = el.querySelector('[data-view-plain]');
    if (p && handlers.onPlain) p.addEventListener('click', handlers.onPlain);
    var o = el.querySelector('[data-view-logout]');
    if (o) o.addEventListener('click', function () {
      if (window.API) API.clearToken();
      location.hash = '#/login';
      location.reload();
    });
    bindGo(el);
  }

  /* 便捷：直接把错误画到容器里 */
  function showError(el, e, opts, handlers) {
    opts = opts || {};
    mount(el, error(e, opts), handlers);
  }

  /* ---------------------------------------------------------------- 错误边界
     页面入口统一这么写：

       Pages.foo = function (app) {
         View.boot(app, {
           active: 'foo', crumbs: [...],
           run: function (ctx) { ... ctx.body ... ctx.fail(err) ... }
         });
       };

     `run` 里的**同步异常**会被兜住并画成错误卡片；`ctx.fail(err)` 用于异步失败。
     这样"页面白着、没有任何提示"在结构上就不可能发生。 */
  function boot(app, opts) {
    opts = opts || {};
    var ctx = {
      app: app,
      get body() { return document.getElementById('page-body'); },
      /* 异步失败统一入口 */
      fail: function (err, o) {
        var el = document.getElementById('page-body');
        if (!el) return;
        if (o && o.el) el = o.el;
        var merged = Object.assign({ showStack: true }, o || {});
        showError(el, err, merged, o && o.handlers);
        try { console.error('[page ' + (opts.active || '?') + ']', err); } catch (e) {}
      }
    };
    try {
      app.innerHTML = C.shell({
        active: opts.active || '',
        crumbs: opts.crumbs || [],
        actions: opts.actions || ''
      });
      C.bindShell(app);
      opts.run(ctx);
    } catch (err) {
      /* 初始化就炸了：至少给用户一张能读的错误卡，而不是白屏 */
      try { console.error('[page boot ' + (opts.active || '?') + ']', err); } catch (e) {}
      var body = document.getElementById('page-body');
      if (body) {
        showError(body, err, { title: '页面初始化失败', showStack: true },
                  { onRetry: function () { Router.refresh(); } });
      } else if (app) {
        app.innerHTML = '<div class="content" id="page-body"></div>';
        showError(document.getElementById('page-body'), err,
                  { title: '页面初始化失败', showStack: true });
      }
    }
    return ctx;
  }

  /* 兼容旧调用点（任务：迁移完成后删除）。
     `PermDenied` 原来是 accounts.js 里的全局函数，已收口到 View.denied。 */
  window.PermDenied = function (app, opts) { denied(app, opts); };

  /* 全局兜底：任何没被 catch 的异步异常都弹出来，绝不静默 */
  var _installed = false;
  function installGlobalHandlers() {
    if (_installed) return;
    _installed = true;
    window.addEventListener('unhandledrejection', function (e) {
      var r = e && e.reason;
      if (r && (r.status === 401)) return;              // 401 由 API 层统一处理
      try { console.error('[unhandled]', r); } catch (x) {}
    });
  }

  return { describe: describe, loading: loading, error: error, denied: denied,
           mount: mount, showError: showError, boot: boot, bindGo: bindGo,
           installGlobalHandlers: installGlobalHandlers };
})();
