/* 自绘数据可视化：sparkline + 面积图（纯 SVG，无 CDN、无 chartjunk）
   · 有坐标轴刻度、hover 读数、空状态
   · 数据一律 tabular-nums 显示，避免跳动 */
window.Chart = (function () {
  var NS = 'http://www.w3.org/2000/svg';

  function niceMax(v) {
    v = Number(v) || 0;
    if (v <= 0) return 1;
    var exp = Math.floor(Math.log10(v));
    var base = Math.pow(10, exp);
    var n = v / base;
    var step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
    return step * base;
  }

  function path(points, w, h, max, pad) {
    pad = pad || 0;
    var n = points.length;
    if (n === 0) return { line: '', area: '' };
    var inner = h - pad * 2;
    var stepX = n > 1 ? w / (n - 1) : w;
    var d = '', a = '';
    points.forEach(function (v, i) {
      var x = n > 1 ? i * stepX : w / 2;
      var y = pad + inner - (Math.max(0, Math.min(max, Number(v) || 0)) / max) * inner;
      d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1) + ' ';
      a += (i === 0 ? 'M' + x.toFixed(1) + ' ' + (h - pad) : 'L' + x.toFixed(1) + ' ' + y.toFixed(1)) + ' ';
    });
    a += 'L' + w + ' ' + (h - pad) + ' L0 ' + (h - pad) + ' Z';
    return { line: d.trim(), area: a.trim() };
  }

  /* 迷你曲线：实例卡/统计块用 */
  function sparkline(values, opts) {
    opts = opts || {};
    var w = opts.width || 260, h = opts.height || 36, color = opts.color || 'var(--accent-bright)';
    var vals = (values || []).filter(function (v) { return v !== null && v !== undefined; });
    if (!vals.length) {
      return '<div class="chart-empty" style="height:' + h + 'px">暂无数据</div>';
    }
    var max = niceMax(Math.max.apply(null, vals) * 1.15);
    var p = path(vals, w, h, max, 3);
    var uid = 'sp' + Math.random().toString(36).slice(2, 8);
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" height="' + h + '" role="img" aria-label="趋势">' +
      '<defs><linearGradient id="' + uid + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + color + '" stop-opacity=".38"/>' +
      '<stop offset="100%" stop-color="' + color + '" stop-opacity="0"/></linearGradient></defs>' +
      '<path d="' + p.area + '" fill="url(#' + uid + ')"/>' +
      '<path d="' + p.line + '" fill="none" stroke="' + color + '" stroke-width="1.5" ' +
      'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>';
  }

  /* 面积图：带坐标轴刻度与 hover 读数 */
  function area(container, series, opts) {
    opts = opts || {};
    if (typeof container === 'string') container = document.querySelector(container);
    if (!container) return;
    /* 多系列时逐条给颜色：调用方没传 color 就按单色系统的灰阶循环分配，
       否则图例与线会全是同一个颜色、分不清哪条是哪条。 */
    var PALETTE = ['var(--text-primary)', 'var(--text-secondary)', 'var(--text-muted)',
                   'var(--info)', 'var(--warning)', 'var(--danger)'];
    (series || []).forEach(function (s, i) {
      if (!s.color) s.color = PALETTE[i % PALETTE.length];
    });
    var all = [];
    (series || []).forEach(function (s) {
      (s.values || []).forEach(function (v) { if (v !== null && v !== undefined) all.push(Number(v)); });
    });
    if (!all.length) {
      container.innerHTML = '<div class="chart-empty" style="height:' + (opts.height || 180) + 'px">' +
        (opts.emptyText || '该时间范围内没有采样数据') + '</div>';
      return;
    }
    var W = opts.width || 720, H = opts.height || 180;
    var padL = 44, padR = 12, padT = 12, padB = 22;
    var iw = W - padL - padR, ih = H - padT - padB;
    var max = niceMax(Math.max.apply(null, all) * 1.1);
    var ticks = [0, max / 2, max];
    var ts = (series[0] && series[0].labels) || [];
    var uid = 'ar' + Math.random().toString(36).slice(2, 8);

    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" height="' + H + '">';
    svg += '<defs>';
    (series || []).forEach(function (s, i) {
      svg += '<linearGradient id="' + uid + i + '" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0%" stop-color="' + s.color + '" stop-opacity=".30"/>' +
        '<stop offset="100%" stop-color="' + s.color + '" stop-opacity="0"/></linearGradient>';
    });
    svg += '</defs>';
    // 网格与 Y 轴刻度
    ticks.forEach(function (t) {
      var y = padT + ih - (t / max) * ih;
      svg += '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) +
        '" stroke="var(--line-1)" stroke-width="1"/>';
      svg += '<text x="' + (padL - 7) + '" y="' + (y + 3.5).toFixed(1) + '" text-anchor="end" ' +
        'fill="var(--text-faint)" font-size="10" font-family="var(--font-mono)">' +
        (max > 100 ? Math.round(t) : Math.round(t * 10) / 10) + '</text>';
    });
    (series || []).forEach(function (s, i) {
      var vals = s.values || [];
      var n = vals.length;
      var stepX = n > 1 ? iw / (n - 1) : iw;
      var line = '', ar = '';
      vals.forEach(function (v, k) {
        var x = padL + (n > 1 ? k * stepX : iw / 2);
        var y = padT + ih - (Math.max(0, Math.min(max, Number(v) || 0)) / max) * ih;
        line += (k === 0 ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1) + ' ';
        ar += (k === 0 ? 'M' + x.toFixed(1) + ' ' + (padT + ih) : 'L' + x.toFixed(1) + ' ' + y.toFixed(1)) + ' ';
      });
      ar += 'L' + (padL + iw) + ' ' + (padT + ih) + ' L' + padL + ' ' + (padT + ih) + ' Z';
      svg += '<path d="' + ar + '" fill="url(#' + uid + i + ')"/>';
      svg += '<path d="' + line + '" fill="none" stroke="' + s.color + '" stroke-width="1.6" ' +
        'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>';
    });
    // 时间刻度：首/中/尾
    if (ts.length) {
      [0, Math.floor(ts.length / 2), ts.length - 1].forEach(function (idx, j) {
        var n = ts.length;
        var x = padL + (n > 1 ? idx * (iw / (n - 1)) : iw / 2);
        var anchor = j === 0 ? 'start' : (j === 2 ? 'end' : 'middle');
        svg += '<text x="' + x.toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + anchor + '" ' +
          'fill="var(--text-faint)" font-size="10" font-family="var(--font-mono)">' + ts[idx] + '</text>';
      });
    }
    svg += '<line class="hover-line" x1="0" y1="' + padT + '" x2="0" y2="' + (padT + ih) +
      '" stroke="var(--accent)" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>';
    svg += '</svg><div class="chart-tip"></div>';
    container.innerHTML = svg;
    container.classList.add('chart-wrap');

    // hover 交互
    var svgEl = container.querySelector('svg');
    var tip = container.querySelector('.chart-tip');
    var hline = container.querySelector('.hover-line');
    var labels = (series[0] && series[0].labelsFull) || ts;
    svgEl.addEventListener('mousemove', function (e) {
      var rect = svgEl.getBoundingClientRect();
      var ratio = W / rect.width;
      var x = (e.clientX - rect.left) * ratio;
      var n = (series[0] && series[0].values.length) || 0;
      if (!n) return;
      var idx = Math.round((x - padL) / (iw / Math.max(1, n - 1)));
      idx = Math.max(0, Math.min(n - 1, idx));
      var px = padL + (n > 1 ? idx * (iw / (n - 1)) : iw / 2);
      hline.setAttribute('x1', px); hline.setAttribute('x2', px); hline.setAttribute('opacity', '.8');
      var rows = '<div style="color:var(--text-faint)">' + (labels[idx] || '') + '</div>';
      (series || []).forEach(function (s) {
        var v = s.values[idx];
        rows += '<div><i style="display:inline-block;width:7px;height:7px;border-radius:2px;background:' +
          s.color + ';margin-right:5px"></i>' + s.name + ' <b>' +
          (v === null || v === undefined ? '-' : (Math.round(Number(v) * 10) / 10)) + (s.unit || '') + '</b></div>';
      });
      tip.innerHTML = rows;
      tip.style.display = 'block';
      var left = (px / ratio) + 10;
      if (left > rect.width - 130) left = (px / ratio) - 140;
      tip.style.left = Math.max(2, left) + 'px';
      tip.style.top = Math.max(2, e.clientY - rect.top - 40) + 'px';
    });
    svgEl.addEventListener('mouseleave', function () {
      tip.style.display = 'none';
      hline.setAttribute('opacity', '0');
    });
  }

  return { sparkline: sparkline, area: area, niceMax: niceMax };
})();
