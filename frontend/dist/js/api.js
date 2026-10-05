/* API 客户端：Bearer 令牌 + **统一的错误形状**
   ============================================================================
   重构要点：以前 reject 出去的是 `new Error(detail)`，只有一句话 ——
   页面没法区分"权限不足 / 登录过期 / 参数错 / 服务挂了"，所以只能一律
   `Toast.err(e.message)` 了事，异常一多就静默了。

   现在所有失败都是同一个形状：

     { message: '人话原因', status: 403, url: '/api/users', method: 'GET',
       data: {...后端原始响应}, isAuth: false, isDenied: true, isNetwork: false }

   于是 `View.describe(err)` 能给出准确的标题/提示，页面也不用再猜。

   401 仍然自动清令牌并回登录页（这是路由层的职责，不适合塞给每个页面）。
   ========================================================================== */
window.API = (function () {
  var TOKEN_KEY = 'mc_token';

  function getToken() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } }
  function setToken(t) { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch (e) {} }
  function clear() { setToken(''); }

  function authHeaders(extra) {
    var h = extra || {};
    var t = getToken();
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  /* 401：清令牌 + 回登录页（同一个页面里连打多个 401 只跳一次） */
  var _bounced = false;
  function handle401() {
    clear();
    if (location.hash.indexOf('#/login') === 0) return;
    if (_bounced) return;
    _bounced = true;
    setTimeout(function () { _bounced = false; }, 1500);
    location.hash = '#/login';
  }

  /* 把任意失败归一成上面那个形状 */
  function apiError(message, status, url, method, data) {
    var e = new Error(message || ('HTTP ' + status));
    e.status = status || 0;
    e.url = url || '';
    e.method = (method || 'GET').toUpperCase();
    e.data = data;
    e.isAuth = e.status === 401;
    e.isDenied = e.status === 403;
    e.isNetwork = !e.status;
    return e;
  }

  function detailOf(d, status) {
    if (d && typeof d === 'object') {
      var m = d.detail || d.error || d.message;
      if (Array.isArray(m)) {
        return m.map(function (x) { return x.msg || JSON.stringify(x); }).join('; ');
      }
      if (m) return String(m);
    }
    if (typeof d === 'string' && d.trim() && d.length < 300) return d.trim();
    return 'HTTP ' + status;
  }

  function req(method, path, body, opts) {
    opts = opts || {};
    var init = { method: method, headers: authHeaders(opts.headers || {}) };
    if (body !== undefined && body !== null) {
      if (body instanceof FormData) {
        init.body = body;
      } else {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(body);
      }
    }
    return fetch(path, init).then(function (r) {
      if (r.status === 401) handle401();
      var ct = r.headers.get('content-type') || '';
      if (ct.indexOf('application/json') < 0) {
        return r.text().then(function (t) {
          if (!r.ok) throw apiError('HTTP ' + r.status + ' ' + (t || '').slice(0, 200),
                                    r.status, path, method, t);
          return t;
        });
      }
      return r.json().then(function (d) {
        if (!r.ok) throw apiError(detailOf(d, r.status), r.status, path, method, d);
        return d;
      }, function () {
        /* 响应不是合法 JSON（例如后端挂了返回空）*/
        throw apiError('响应不是合法 JSON（HTTP ' + r.status + '）', r.status, path, method);
      });
    }, function (netErr) {
      /* fetch 本身失败：网络断了 / 服务没起来 / 被扩展拦了 */
      throw apiError('连不上面板服务：' + ((netErr && netErr.message) || '网络错误'),
                     0, path, method);
    });
  }

  var api = {
    get: function (p, o) { return req('GET', p, null, o); },
    post: function (p, b, o) { return req('POST', p, b, o); },
    put: function (p, b, o) { return req('PUT', p, b, o); },
    patch: function (p, b, o) { return req('PATCH', p, b, o); },
    del: function (p, b, o) { return req('DELETE', p, b, o); },
    token: getToken, setToken: setToken, clearToken: clear,
    wsUrl: function (path) {
      var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      var t = getToken();
      return proto + '//' + location.host + path +
        (path.indexOf('?') < 0 ? '?' : '&') + 'token=' + encodeURIComponent(t);
    },
    fileUrl: function (path) {
      var t = getToken();
      return path + (path.indexOf('?') < 0 ? '?' : '&') + 'token=' + encodeURIComponent(t);
    },
    /* 上传（带进度）。失败同样归一成上面那个形状。 */
    upload: function (path, file, fields, onProgress) {
      return new Promise(function (resolve, reject) {
        var fd = new FormData();
        Object.keys(fields || {}).forEach(function (k) { fd.append(k, fields[k]); });
        fd.append('file', file);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', path);
        var t = getToken();
        if (t) xhr.setRequestHeader('Authorization', 'Bearer ' + t);
        xhr.upload.onprogress = function (e) {
          if (onProgress && e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100));
        };
        xhr.onload = function () {
          if (xhr.status === 401) handle401();
          var d = null;
          try { d = JSON.parse(xhr.responseText); } catch (e) { d = xhr.responseText; }
          if (xhr.status >= 200 && xhr.status < 300) { resolve(d || {}); return; }
          reject(apiError(detailOf(d, xhr.status), xhr.status, path, 'POST', d));
        };
        xhr.onerror = function () {
          reject(apiError('上传失败：连不上面板服务', 0, path, 'POST'));
        };
        xhr.send(fd);
      });
    }
  };
  return api;
})();
