/* 首屏前应用主题与信息密度，避免闪白/闪跳 */
(function () {
  var t = 'auto', d = 'comfy';
  try {
    t = localStorage.getItem('mc_theme') || 'auto';
    d = localStorage.getItem('mc_density') || 'comfy';
  } catch (e) {}
  document.documentElement.setAttribute('data-theme', t);
  document.documentElement.setAttribute('data-density', d);
})();
