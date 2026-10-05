/* 视图模式：集中定义 + 集中持久化
   ============================================================================
   为什么单独抽出来：原来视图逻辑是**撒在页面里的** —— `localStorage.getItem('mc_inst_view')`
   读一次、`data-v` 属性写一次、按钮 active 类手工切一次。每加一个视图就要在三处各改一遍，
   很容易漏（漏了就是"按钮点了没反应"或"刷新后回到旧视图"）。
   这里把"有哪些视图 / 默认哪个 / 怎么记住"收在一处，页面只负责渲染。
   ========================================================================== */
window.ViewMode = (function () {
  /* 每个视图：key → { label, icon, title } */
  var SETS = {
    /* 实例列表：按信息密度递增排列 */
    instances: {
      store: 'mc_inst_view',
      default: 'cards',
      modes: [
        { key: 'cards', label: '卡片', icon: 'grid', title: '大卡片：状态环 + sparkline + 启停按钮，适合少数实例' },
        { key: 'compact', label: '紧凑', icon: 'list', title: '单行列表：一屏看更多实例，适合实例较多时' },
        { key: 'table', label: '表格', icon: 'layers', title: '完整字段表格：磁盘占用 / 归属 / 端口等' },
        { key: 'grouped', label: '分组', icon: 'folder', title: '按运行状态分组：运行中 / 已停止 / 异常，一眼看出谁该管' }
      ]
    },
    /* 仪表盘：按关注对象区分 */
    dashboard: {
      store: 'mc_dash_view',
      default: 'cards',
      modes: [
        { key: 'cards', label: '卡片', icon: 'grid', title: '大卡片：每台机器一张，含 CPU sparkline 与快捷启停' },
        { key: 'compact', label: '紧凑', icon: 'list', title: '单行列表：很多实例时一屏扫完' },
        { key: 'trend', label: '趋势', icon: 'chart', title: '近几分钟的主机与各实例资源走势' }
      ]
    }
  };

  function set(name) { return SETS[name] || SETS.instances; }

  function get(name) {
    var s = set(name);
    var v = null;
    try { v = localStorage.getItem(s.store); } catch (e) {}
    var ok = s.modes.some(function (m) { return m.key === v; });
    return ok ? v : s.default;
  }

  function put(name, key) {
    var s = set(name);
    if (!s.modes.some(function (m) { return m.key === key; })) return;
    try { localStorage.setItem(s.store, key); } catch (e) {}
  }

  /* 切换按钮组（统一 class 与 data 属性，页面不用再手写） */
  function switchHtml(name, current) {
    var s = set(name);
    return '<div class="btn-group" data-view-switch="' + name + '">' +
      s.modes.map(function (m) {
        return '<button class="btn sm' + (m.key === current ? ' active' : '') + '" data-v="' + m.key +
          '" title="' + U.esc(m.title) + '">' +
          (Icon.svg ? Icon.svg(m.icon, 14) : '') + '<span>' + U.esc(m.label) + '</span></button>';
      }).join('') + '</div>';
  }

  /* 绑定：回调拿到新的视图 key（已持久化、已切 active 类） */
  function bind(root, name, onPick) {
    var box = (root || document).querySelector('[data-view-switch="' + name + '"]');
    if (!box) return;
    box.addEventListener('click', function (e) {
      var b = e.target.closest('[data-v]');
      if (!b) return;
      var key = b.getAttribute('data-v');
      put(name, key);
      box.querySelectorAll('.btn').forEach(function (x) { x.classList.remove('active'); });
      b.classList.add('active');
      if (onPick) onPick(key);
    });
  }

  return { get: get, put: put, switchHtml: switchHtml, bind: bind, modes: function (n) { return set(n).modes; } };
})();
