/* 角色元信息 · 前端唯一出处
   ============================================================================
   角色名/徽标配色/说明本来散在 mock-accounts.js（已删）、View.denied、
   components.js 里（原来引用的是 MockAccounts.ROLE_META）。后端仍是权威
   （`/api/me/permissions` 会带 `roles`/`role_meta`），这里只是**接口没拿到时
   也能正确渲染**的兜底副本，两者字段保持一致。
   ========================================================================== */
window.Roles = (function () {
  var META = {
    super_admin: { key: 'super_admin', name: '超级管理员', short: '超管', cls: 'role-super',
                   desc: '全部权限：用户与角色管理、系统设置、所有实例的任意操作、审计' },
    admin: { key: 'admin', name: '管理员', short: '管理', cls: 'role-admin',
             desc: '管理所有实例与查看审计；不可管理用户与系统设置' },
    user: { key: 'user', name: '普通用户', short: '用户', cls: 'role-user',
            desc: '只能操作自己拥有的实例，受配额限制' },
    viewer: { key: 'viewer', name: '只读', short: '只读', cls: 'role-viewer',
              desc: '只读查看被授权的实例（控制台/状态/日志）' }
  };
  var ORDER = ['super_admin', 'admin', 'user', 'viewer'];

  /* 合并后端返回的角色表（后端是权威，字段更全） */
  function merge(list) {
    (list || []).forEach(function (r) {
      if (!r || !r.key) return;
      META[r.key] = Object.assign({}, META[r.key] || {}, r);
      if (ORDER.indexOf(r.key) < 0) ORDER.push(r.key);
    });
    return META;
  }

  function get(key) { return META[key] || {}; }
  function name(key) { return (META[key] || {}).name || key || ''; }
  function all() { return META; }
  function keys() { return ORDER.slice(); }

  return { get: get, name: name, all: all, keys: keys, merge: merge, META: META };
})();
