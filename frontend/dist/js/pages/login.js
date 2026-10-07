/* 登录页：左侧品牌区（记忆点）+ 右侧表单卡 */
window.Pages = window.Pages || {};

Pages.login = function (app) {
  app.innerHTML = '' +
    '<div class="login-wrap">' +
      '<section class="login-hero">' +
        '<div class="hero-grid-lines"></div>' +
        '<div class="kicker">Minecraft Server Panel</div>' +
        '<h1>把开服这件事<br><em>做扎实</em></h1>' +
        '<p>原版 / Paper / Purpur / Fabric / Quilt / Forge / NeoForge 一键获取，实时控制台、' +
          '可视化配置、玩家与备份管理，进程组管控与崩溃自动重启。</p>' +
        '<div class="hero-feats">' +
          '<div class="hero-feat">' + Icon.svg('terminal', 18) + '<div>WebSocket 实时控制台：分级着色、搜索高亮、命令历史</div></div>' +
          '<div class="hero-feat">' + Icon.svg('chart', 18) + '<div>CPU / 内存 / 玩家 / TPS 采样曲线，拿不到 TPS 就如实标注不可用</div></div>' +
          '<div class="hero-feat">' + Icon.svg('backup', 18) + '<div>tar.gz 备份 + 份数轮转 + 还原前自动备份</div></div>' +
          '<div class="hero-feat">' + Icon.svg('shield', 18) + '<div>路径穿越防护、PBKDF2-600k 口令、全接口鉴权闸门</div></div>' +
        '</div>' +
      '</section>' +
      '<section class="login-panel">' +
        '<form class="login-card" id="login-form" autocomplete="on">' +
          '<div class="login-logo">芮拓</div>' +
          '<div class="login-title">登录面板</div>' +
          '<div class="login-sub">首次运行的初始口令在服务端本地终端打印一次</div>' +
          '<div class="firstrun">首次运行提示：系统已自动创建默认账号 <b>admin</b>，其角色是' +
            '<b>超级管理员</b>（拥有全部权限，可创建管理员 / 普通用户 / 只读账号）。' +
            '初始口令<b>只在服务器终端打印一次</b> —— 面板不显示、不下发，也不写进日志与审计。</div>' +
          '<div id="login-err"></div>' +
          '<div id="login-lock"></div>' +
          '<div class="field"><label for="u">管理员账号</label>' +
            '<input type="text" id="u" name="username" value="admin" autocomplete="username" required /></div>' +
          '<div class="field"><label for="p">口令</label>' +
            '<input type="password" id="p" name="password" autocomplete="current-password" required />' +
            '<div class="desc">至少 12 位，含大小写 / 数字 / 符号中的任意三类</div></div>' +
          '<button class="btn primary block" type="submit" id="login-btn">' + Icon.svg('login', 16) + '登录</button>' +
          '<div class="small faint mt" id="ver"></div>' +
        '</form>' +
      '</section>' +
    '</div>';

  API.get('/api/health').then(function (h) {
    var v = document.getElementById('ver');
    if (v) v.textContent = '服务版本 ' + h.version + ' · 独立运行，不依赖其它面板';
  }).catch(function () {});

  var form = document.getElementById('login-form');
  var errBox = document.getElementById('login-err');
  var lockBox = document.getElementById('login-lock');
  var btn = document.getElementById('login-btn');

  /* 锁定倒计时：后端触发锁定时返回 429，前端按本地计时显示剩余时间并禁用提交 */
  var lockTimer = null;
  function startLock(seconds) {
    var left = seconds;
    if (lockTimer) clearInterval(lockTimer);
    btn.disabled = true;
    function tick() {
      if (left <= 0) {
        clearInterval(lockTimer); lockTimer = null;
        lockBox.innerHTML = '';
        btn.disabled = false;
        return;
      }
      var m = Math.floor(left / 60), s = left % 60;
      lockBox.innerHTML = '<div class="lock-bar">' + Icon.svg('warn', 14) +
        '<span>账号已临时锁定，请在 <span class="mono">' + m + ':' + (s < 10 ? '0' : '') + s +
        '</span> 后重试（面板按「用户名 + IP」计数，防止暴力尝试）</span></div>';
      left -= 1;
    }
    tick();
    lockTimer = setInterval(tick, 1000);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    errBox.innerHTML = '';
    var u = document.getElementById('u').value.trim();
    var p = document.getElementById('p').value;
    if (!u || !p) {
      errBox.innerHTML = '<div class="login-err">请填写账号与口令</div>';
      return;
    }
    C.withLoading(btn, API.post('/api/auth/login', { username: u, password: p }).then(function (d) {
      API.setToken(d.token);
      Store.set({ user: d.user });
      if (window.Perm) {
        Perm.reset();
        return Perm.load().then(function () {
          Toast.ok('登录成功：' + (Perm.roleMeta().name || d.user.role || '') + '，欢迎回来');
          location.hash = '#/dashboard';
        });
      }
      Toast.ok('登录成功，欢迎回来');
      location.hash = '#/dashboard';
    }).catch(function (err) {
      if (err.status === 429) {
        startLock(600);           // 后端默认锁定 10 分钟，前端按 600s 倒计时
        errBox.innerHTML = '<div class="login-err">' + U.esc(err.message) + '</div>';
      } else {
        errBox.innerHTML = '<div class="login-err">' + U.esc(err.message) + '</div>';
      }
      document.getElementById('p').value = '';
      document.getElementById('p').focus();
    }));
  });

  setTimeout(function () { var el = document.getElementById('p'); if (el) el.focus(); }, 60);
};
