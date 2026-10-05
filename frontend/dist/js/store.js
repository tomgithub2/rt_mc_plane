/* 极简全局状态 + 提示 */
window.Store = (function () {
  var state = {
    user: null,
    overview: null,
    instances: [],
    settings: null,
    pollers: []
  };
  var subs = [];

  function set(patch) {
    Object.keys(patch).forEach(function (k) { state[k] = patch[k]; });
    subs.forEach(function (fn) { try { fn(state); } catch (e) {} });
  }

  function subscribe(fn) { subs.push(fn); }

  // 统一轮询管理：切换页面时全部清掉，避免残留定时器
  function every(ms, fn, immediate) {
    if (immediate !== false) { try { fn(); } catch (e) {} }
    var id = setInterval(fn, ms);
    state.pollers.push(id);
    return id;
  }

  function clearPollers() {
    state.pollers.forEach(function (id) { clearInterval(id); });
    state.pollers = [];
  }

  return { state: state, set: set, subscribe: subscribe, every: every, clearPollers: clearPollers };
})();

/* 提示条 */
window.Toast = (function () {
  var box = null;
  function ensure() {
    if (!box) {
      box = document.createElement('div');
      box.className = 'toasts';
      document.body.appendChild(box);
    }
    return box;
  }
  function show(msg, kind, ms) {
    var el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    el.textContent = msg;
    ensure().appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .2s';
      el.style.opacity = '0';
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 220);
    }, ms || (kind === 'err' ? 5200 : 2800));
  }
  return {
    ok: function (m) { show(m, 'ok'); },
    err: function (m) { show(m, 'err'); },
    warn: function (m) { show(m, 'warn'); },
    info: function (m) { show(m, ''); }
  };
})();
