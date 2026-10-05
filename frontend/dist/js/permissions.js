/* 权限工具 · 对接真实后端
   ============================================================================
   数据来源：`GET /api/me/permissions`（契约 §1.16）
     → {ok, role, role_name, role_meta, roles:[…], perms:[…], all_perms:[…],
        quota:{…}, quota_usage:{…}, flags:{…}}

   铁律（契约 §1.16 / 规格 §7）：**前端隐藏菜单与按钮只是体验优化，不是安全边界**。
   后端逐个路由 `require_perm` 兜底 403 —— 直接构造请求同样进不去。

   约定：
   - `has()` 在**权限表还没拿到**时一律返回 false（默认拒绝）。
   - 页面拿不到权限表 → 用 `View.showError()` 画出来，不要靠本模块画 UI。
   - `denyIfForbidden(err, app, opts)`：403 的统一出口，转交 `View.denied()`。
   ========================================================================== */
window.Perm = (function () {
  var snap = null;          // 权限快照（未加载 = null）
  var inflight = null;      // 正在飞的请求，供并发调用共用
  var lastError = '';       // 最近一次失败原因（诊断用）

  function apply(p) {
    snap = p || {};
    lastError = '';
    return snap;
  }

  /* 拉一次权限快照并缓存；`force=true` 强制重新拉（换账号/角色变更后必须强制）。 */
  function load(force) {
    if (snap && !force) return Promise.resolve(snap);
    if (inflight && !force) return inflight;
    inflight = API.get('/api/me/permissions').then(function (p) {
      inflight = null;
      return apply(p);
    }).catch(function (e) {
      inflight = null;
      snap = null;                                  // 失败 = 没有权限表 = 默认拒绝
      lastError = (e && e.message) || String(e);
      throw e;                                      // 交给页面/路由去显示
    });
    return inflight;
  }

  function has(perm) {
    if (!snap) return false;
    if (snap.role === 'super_admin') return true;
    return (snap.perms || []).indexOf(perm) >= 0;
  }

  function role() { return snap ? snap.role : null; }
  function roleMeta() {
    if (!snap) return {};
    return snap.role_meta || allRoles()[snap.role] || {};
  }
  function allRoles() {
    var out = {};
    ((snap && snap.roles) || []).forEach(function (r) { out[r.key] = r; });
    return out;
  }
  function quota() { return (snap && snap.quota) || {}; }
  function quotaUsage() { return (snap && snap.quota_usage) || {}; }
  function flags() { return (snap && snap.flags) || {}; }
  function perms() { return (snap && snap.perms) || []; }
  function realRole() { return (snap && snap.role) || null; }
  function canViewAll() { return ['super_admin', 'admin'].indexOf(role()) >= 0; }
  function loaded() { return !!snap; }
  function reset() { snap = null; inflight = null; }
  function pending() { return inflight; }
  function error() { return lastError; }

  /* 403 统一出口：画「权限不足」页并返回 true 表示"已处理，调用方 return 即可"。
     若本地权限表显示该权限**本来就有**，那 403 就不是角色问题（可能是实例归属），
     返回 false 让调用方走普通错误分支，避免把"不属于你"说成"角色无权限"。 */
  function denyIfForbidden(err, app, opts) {
    opts = opts || {};
    if (!err || err.status !== 403) return false;
    if (opts.perm && has(opts.perm)) return false;
    View.denied(app, opts);
    return true;
  }

  return { load: load, has: has, role: role, realRole: realRole, roleMeta: roleMeta,
           allRoles: allRoles, quota: quota, quotaUsage: quotaUsage, flags: flags,
           perms: perms, canViewAll: canViewAll, loaded: loaded, reset: reset,
           pending: pending, error: error, denyIfForbidden: denyIfForbidden,
           denied: function (err) { View.showError(document.getElementById('page-body'), err); } };
})();
