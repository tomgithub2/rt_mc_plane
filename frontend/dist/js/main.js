/* 应用入口：路由注册 + 启动 */
(function () {
  // 登录
  Router.add('#/login', Pages.login);
  // 仪表盘（首屏：多实例卡片网格 + 置顶/拖动排序）
  Router.add('#/dashboard', Pages.dashboard);
  // 实例
  Router.add('#/instances', Pages.instances);
  Router.add('#/instances/:id', Pages.instanceDetail);
  Router.add('#/instances/:id/:tab', Pages.instanceDetail);
  Router.add('#/create', Pages.create);
  Router.add('#/settings', Pages.settings);
  Router.add('#/accounts', Pages.accounts);
  Router.add('#/audit', Pages.audit);

  document.addEventListener('DOMContentLoaded', function () {
    // 未登录时先确认服务在线（健康检查免鉴权）
    API.get('/api/health').then(function (h) {
      window.__MC_VERSION = h.version;
    }).catch(function () {}).then(function () {
      Router.start();
    });
  });
})();
