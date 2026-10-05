/* 通用工具 */
window.U = (function () {
  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtSize(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
    return (n / 1073741824).toFixed(2) + ' GB';
  }

  function fmtTime(ts, withDate) {
    if (!ts) return '-';
    var d = new Date(Number(ts) * 1000);
    function p(x) { return x < 10 ? '0' + x : '' + x; }
    var t = p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    if (!withDate) return t;
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + t;
  }

  function fmtDur(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600),
        m = Math.floor(sec % 3600 / 60), s = sec % 60;
    if (d) return d + '天' + h + '小时';
    if (h) return h + '小时' + m + '分';
    if (m) return m + '分' + s + '秒';
    return s + '秒';
  }

  function statusText(s) {
    return { running: '运行中', stopped: '已停止', starting: '启动中', stopping: '停止中', crashed: '已崩溃' }[s] || s || '-';
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      var a = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, a); }, ms || 250);
    };
  }

  function qs(path) {
    var o = {};
    (path || '').replace(/^\?/, '').split('&').forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf('=');
      var k = i < 0 ? kv : kv.slice(0, i);
      var v = i < 0 ? '' : kv.slice(i + 1);
      try { o[decodeURIComponent(k)] = decodeURIComponent(v); } catch (e) { o[k] = v; }
    });
    return o;
  }

  function download(url, filename) {
    var a = document.createElement('a');
    a.href = url;
    if (filename) a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function confirmBox(text) { return window.confirm(text); }

  return {
    esc: esc, fmtSize: fmtSize, fmtTime: fmtTime, fmtDur: fmtDur, statusText: statusText,
    debounce: debounce, qs: qs, download: download, confirm: confirmBox
  };
})();
