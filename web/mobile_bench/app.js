(function () {
  'use strict';

  var ENVELOPE_FORMAT = 'niuniu-mobile-envelope-v1';
  var SNAPSHOT_FORMAT = 'niuniu-mobile-snapshot-v1';
  var LS_PASS = 'niuniu_mobile_pass';
  var LS_PREF = 'niuniu_mobile_pref';
  var app = document.getElementById('app');

  var state = {
    phase: 'loading', snap: null, env: null, error: '', tab: 'overview', loadedAt: 0,
    loading: false,                    // 下载/解密进行中
    offline: false,                    // 是否来自 Service Worker 离线缓存
    passVisible: false,                // 口令明文显示开关
    search: { signal: '', forward: '', holdings: '' }, // 各页搜索关键词
    forwardFilter: 'all',              // 前向记录状态筛选：all/waiting/open/closed
    chartTip: null,                    // 图表提示 {x, y, text}
    stock: null                        // 正在看走势的股票代码
  };

  var pick = { signal: 'fusion', forward: 'fusion', holdings: 'D' };

  // ------------------------------------------------------------------ 小工具
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function ls(get, key, val) {
    try { if (get) return window.localStorage.getItem(key); if (val === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, val); } catch (e) { /* 无痕模式等 */ }
    return null;
  }
  function isNum(x) { return typeof x === 'number' && isFinite(x); }
  function num(x, d) { return isNum(x) ? x.toFixed(d == null ? 2 : d) : '—'; }
  function pct(x, d, sign) {
    if (!isNum(x)) return '—';
    var s = (x * 100).toFixed(d == null ? 1 : d) + '%';
    return sign && x > 0 ? '+' + s : s;
  }
  function pctc(x, d) { return '<span class="num ' + (isNum(x) ? (x > 0 ? 'up' : x < 0 ? 'down' : '') : 'muted') + '">' + pct(x, d, true) + '</span>'; }
  function money(x) { return isNum(x) ? Math.round(x).toLocaleString('zh-CN') : '—'; }
  function short(code) { return String(code || '').replace(/^[a-z]+\./i, ''); }
  function md(d) { return d ? String(d).slice(5) : '—'; }
  var WEEK = ['日', '一', '二', '三', '四', '五', '六'];
  function wd(d) { var t = new Date(String(d) + 'T00:00:00+08:00'); return isNaN(t) ? '' : '周' + WEEK[new Date(t.getTime() + 8 * 3600000).getUTCDay()]; }
  function dt(iso) { return iso ? String(iso).slice(5, 16).replace('T', ' ') : '—'; }

  // base64 解码：比 atob 更健壮，兼容非 ASCII 字节
  function b64(s) {
    var bin = atob(s.replace(/-/g, '+').replace(/_/g, '/').replace(/,/g, ''));
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // 简单 toast 提示
  var toastTimer;
  function toast(msg, ms) {
    clearTimeout(toastTimer);
    var el = document.getElementById('nn-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'nn-toast';
      el.style.cssText = 'position:fixed;left:50%;bottom:100px;transform:translateX(-50%);background:rgba(0,0,0,.75);color:#fff;padding:8px 14px;border-radius:8px;font-size:13px;z-index:50;pointer-events:none;white-space:nowrap;';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = 1;
    toastTimer = setTimeout(function () { el.style.opacity = 0; }, ms == null ? 2000 : ms);
  }

  // ------------------------------------------------------------------ 加载中遮罩
  function setLoading(on) {
    state.loading = !!on;
    var el = document.getElementById('nn-loading');
    if (on) {
      if (!el) {
        el = document.createElement('div');
        el.id = 'nn-loading';
        el.innerHTML = '<div class="spin"></div><div>正在下载并解密…</div>';      // 样式在 style.css（CSP 不放行行内样式）
      }
      document.body.appendChild(el);
    } else if (el) {
      el.remove();
    }
  }

  // ------------------------------------------------------------------ 可取消的 fetch（15s 超时）
  function abortableFetch(url, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var ctrl = new AbortController();
      var timer = setTimeout(function () { ctrl.abort(); reject(new Error('timeout')); }, timeoutMs == null ? 15000 : timeoutMs);
      fetch(url, { signal: ctrl.signal, cache: 'no-store' })
        .then(function (r) { clearTimeout(timer); resolve(r); })
        .catch(function (e) { clearTimeout(timer); if (e.name === 'AbortError') reject(new Error('timeout')); else reject(e); });
    });
  }

  // ------------------------------------------------------------------ 解密
  function decrypt(env, pass) {
    if (!env || env.format !== ENVELOPE_FORMAT) return Promise.reject(new Error('数据格式不认识'));
    if (!window.crypto || !crypto.subtle) return Promise.reject(new Error('浏览器不支持加密接口（需要 https 打开）'));
    var enc = new TextEncoder();
    return crypto.subtle.importKey('raw', enc.encode(pass), 'PBKDF2', false, ['deriveKey'])
      .then(function (km) {
        return crypto.subtle.deriveKey({ name: 'PBKDF2', salt: b64(env.salt), iterations: env.iterations, hash: 'SHA-256' },
          km, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
      })
      .then(function (key) {
        return crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(env.iv), additionalData: enc.encode(ENVELOPE_FORMAT) }, key, b64(env.ct));
      })
      .then(function (plain) {
        var snap = JSON.parse(new TextDecoder().decode(plain));
        if (snap.format !== SNAPSHOT_FORMAT) throw new Error('快照版本不认识，请刷新页面');
        return snap;
      });
  }

  function classifyError(e) {
    var msg = String(e && e.message || e || '');
    if (msg === 'timeout') return { kind: 'timeout', text: '下载超时，请检查网络后重试' };
    if (/failed to fetch|net::|NetworkError|Failed to execute 'fetch'/.test(msg)) return { kind: 'network', text: '网络不可用，请检查网络后重试' };
    if (/OperationError|口令不对/.test(msg)) return { kind: 'pass', text: '口令不对' };
    if (/数据格式不认识|快照版本不认识/.test(msg)) return { kind: 'format', text: msg };
    return { kind: 'other', text: msg || String(e) };
  }

  function load(passFromUser) {
    if (state.loading) return Promise.resolve();
    setLoading(true);
    state.phase = 'loading';
    render();
    return abortableFetch('data.json?ts=' + Date.now(), 15000)
      .then(function (r) {
        if (!r.ok) throw new Error('下载失败（' + r.status + '）');
        if (r.headers.get('x-sw-cache') === 'true') state.offline = true;
        return r.json();
      })
      .then(function (env) {
        state.env = env;
        var pass = passFromUser || ls(true, LS_PASS);
        if (!pass) { state.phase = 'locked'; state.error = ''; setLoading(false); render(); return null; }
        return decrypt(env, pass).then(function (snap) {
          if (passFromUser) ls(false, LS_PASS, passFromUser);
          state.snap = snap; state.phase = 'ready'; state.loadedAt = Date.now(); setLoading(false); render();
        }, function (e) {
          var c = classifyError(e);
          if (c.kind === 'pass') { ls(false, LS_PASS, null); state.error = c.text; } else { state.error = c.text; }
          state.phase = 'locked'; setLoading(false); render();
        });
      })
      .catch(function (e) {
        var c = classifyError(e);
        state.phase = 'error'; state.error = c.text; setLoading(false); render();
      });
  }

  // ------------------------------------------------------------------ 状态提示
  function freshness(s) {
    var now = Date.now();
    var open = Date.parse(s.plan_day + 'T09:30:00+08:00');
    var gen = Date.parse(s.generated_at);
    var ageDays = isNaN(gen) ? 0 : (now - gen) / 86400000;
    var out = [];
    if (!isNaN(open) && now >= open) {
      out.push({ k: 'warn', t: '数据只到 <b>' + md(s.data_date) + '（' + wd(s.data_date) + '）</b>，已经过了 ' + md(s.plan_day) + ' 开盘。下面的信号和买入清单已是旧的，不要照着下单；等今晚收盘后数据更新。' });
    } else {
      out.push({ k: 'ok', t: '数据截至 <b>' + md(s.data_date) + '（' + wd(s.data_date) + '）</b>收盘，下面是 <b>' + md(s.plan_day) + '（' + wd(s.plan_day) + '）</b>的计划。' });
    }
    if (ageDays > 3) out.push({ k: 'bad', t: '快照已经 ' + Math.floor(ageDays) + ' 天没更新了，电脑上的牛牛可能没开。' });
    return out;
  }

  // ------------------------------------------------------------------ 点一只股票看最近走势
  function rowCode(code) { return code ? ' class="tap" data-code="' + esc(code) + '"' : ''; }
  function stockSheet(s) {
    var code = state.stock; if (!code) return '';
    var st = s.stocks || {}, ser = (st.series || {})[code], dates = st.dates || [];
    var name = (ser && ser.name) || findName(s, code) || '';
    var body;
    if (!ser) {
      body = '<p class="empty">这只股票没有附带走势数据' + (st.error ? '（' + esc(st.error) + '）' : '') + '。电脑上的牛牛更新后再推送一次就有了。</p>';
    } else {
      var c = ser.c || [], last = null, li = -1;
      for (var i = c.length - 1; i >= 0; i--) if (isNum(c[i])) { last = c[i]; li = i; break; }
      function back(k) { var j = li - k; return j >= 0 && isNum(c[j]) && isNum(last) ? last / c[j] - 1 : null; }
      body = (ser.o ? kchart(ser, dates, name) : chart(c, [md(dates[0]), md(dates[dates.length - 1])], { label: name + ' 近 ' + dates.length + ' 个交易日收盘', h: 170 })) +
        '<div class="tiles">' +
        '<div class="tile"><span>最新收盘</span><b class="num">' + num(last, 2) + '</b><span>' + esc(md(dates[li])) + '</span></div>' +
        '<div class="tile"><span>近 5 日</span><b>' + pctc(back(5), 1) + '</b></div>' +
        '<div class="tile"><span>近 20 日</span><b>' + pctc(back(20), 1) + '</b></div>' +
        '<div class="tile"><span>近 ' + (c.length - 1) + ' 日</span><b>' + pctc(back(c.length - 1), 1) + '</b></div></div>' +
        '<div class="scroll"><table class="tbl"><thead><tr><th>日期</th><th class="n">收盘</th><th class="n">当日</th></tr></thead><tbody>' +
        c.map(function (v, i) { return [i, v]; }).slice(-10).reverse().map(function (x) {
          var i = x[0], v = x[1], prev = i > 0 ? c[i - 1] : null;
          return '<tr><td class="num">' + esc(md(dates[i])) + '</td><td class="n num">' + num(v, 2) + '</td><td class="n">' + pctc(isNum(v) && isNum(prev) ? v / prev - 1 : null, 1) + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="small muted">日 K（前复权），红涨绿跌，黄线 5 日均线、蓝线 20 日均线，下方是成交量；点一根 K 线看当天开高低收。数据截至 ' + esc(s.data_date) + '。</p>';
    }
    return '<div class="sheet-back" id="sheet-back"></div><section class="sheet" role="dialog" aria-label="个股走势">' +
      '<header><div><b>' + esc(name) + '</b> <span class="muted num">' + esc(short(code)) + '</span></div><button class="btn" id="sheet-close">关闭</button></header>' + body + '</section>';
  }
  function ma(c, k) {
    return c.map(function (_, i) {
      if (i < k - 1) return null; var sum = 0;
      for (var j = i - k + 1; j <= i; j++) { if (!isNum(c[j])) return null; sum += c[j]; }
      return sum / k;
    });
  }
  function kchart(ser, dates, name) {
    var o = ser.o, h = ser.h, l = ser.l, c = ser.c, v = ser.v || [], n = c.length;
    var lo = Infinity, hi = -Infinity, vmax = 0;
    for (var i = 0; i < n; i++) {
      if (isNum(l[i]) && l[i] < lo) lo = l[i]; if (isNum(h[i]) && h[i] > hi) hi = h[i];
      if (isNum(v[i]) && v[i] > vmax) vmax = v[i];
    }
    if (!isFinite(lo) || !isFinite(hi)) return '<p class="empty">没有 K 线数据。</p>';
    var span = (hi - lo) || hi * 0.02 || 1; lo -= span * 0.04; hi += span * 0.04; span = hi - lo;
    var W = 320, L = 2, R = 40, T = 6, PH = 150, GAP = 8, VH = 38, B = 14, H = T + PH + GAP + VH + B;
    var step = (W - L - R) / n, bw = Math.max(1, step * 0.62);
    function X(i) { return L + step * (i + 0.5); }
    function Y(p) { return T + PH * (1 - (p - lo) / span); }
    var vy0 = T + PH + GAP + VH;
    var svg = '<svg class="chart kline" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(name) + ' 日K">';
    [0, 0.5, 1].forEach(function (f) { var y = T + PH * f; svg += '<line class="grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '"/>'; });
    for (i = 0; i < n; i++) {
      if (!isNum(o[i]) || !isNum(c[i]) || !isNum(h[i]) || !isNum(l[i])) continue;
      var up = c[i] >= o[i], cls = up ? 'ku' : 'kd', x = X(i);
      var top = Y(Math.max(o[i], c[i])), bot = Y(Math.min(o[i], c[i]));
      svg += '<line class="' + cls + '" x1="' + x.toFixed(1) + '" x2="' + x.toFixed(1) + '" y1="' + Y(h[i]).toFixed(1) + '" y2="' + Y(l[i]).toFixed(1) + '"/>';
      svg += '<rect class="' + cls + '" x="' + (x - bw / 2).toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(0.8, bot - top).toFixed(1) + '"/>';
      if (vmax > 0 && isNum(v[i])) {
        var vh = VH * v[i] / vmax;
        svg += '<rect class="' + cls + ' vol" x="' + (x - bw / 2).toFixed(1) + '" y="' + (vy0 - vh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(0.5, vh).toFixed(1) + '"/>';
      }
    }
    [[ma(c, 5), 'ma5'], [ma(c, 20), 'ma20']].forEach(function (m) {
      var d = '', gap = true;
      m[0].forEach(function (y, i) { if (!isNum(y)) { gap = true; return; } d += (gap ? 'M' : 'L') + X(i).toFixed(1) + ' ' + Y(y).toFixed(1); gap = false; });
      if (d) svg += '<path class="' + m[1] + '" d="' + d + '"/>';
    });
    // 点击区：每根 K 线一条竖条，点了显示当天数值
    for (i = 0; i < n; i++) {
      if (!isNum(c[i])) continue;
      var prev = i > 0 && isNum(c[i - 1]) ? c[i - 1] : null;
      var t = md(dates[i]) + ' 开' + num(o[i], 2) + ' 高' + num(h[i], 2) + ' 低' + num(l[i], 2) + ' 收' + num(c[i], 2) + (prev ? ' ' + pct(c[i] / prev - 1, 1, true) : '');
      svg += '<rect class="kc" data-t="' + esc(t) + '" x="' + (L + step * i).toFixed(1) + '" y="' + T + '" width="' + step.toFixed(1) + '" height="' + (PH + GAP + VH) + '"/>';
    }
    svg += '<text x="' + (W - R + 4) + '" y="' + (T + 8) + '">' + num(hi - span * 0.04 / 1.08, 2) + '</text>';
    svg += '<text x="' + (W - R + 4) + '" y="' + (T + PH) + '">' + num(lo + span * 0.04 / 1.08, 2) + '</text>';
    svg += '<text x="' + L + '" y="' + (H - 2) + '">' + esc(md(dates[0])) + '</text>';
    svg += '<text x="' + (W - R) + '" y="' + (H - 2) + '" text-anchor="end">' + esc(md(dates[n - 1])) + '</text>';
    return svg + '</svg>';
  }
  function findName(s, code) {
    var hit = null;
    (function walk(x) {
      if (hit || !x || typeof x !== 'object') return;
      if (Array.isArray(x)) { x.forEach(walk); return; }
      if (x.code === code && x.name) { hit = x.name; return; }
      Object.keys(x).forEach(function (k) { walk(x[k]); });
    })(s.signals); return hit;
  }

  // ------------------------------------------------------------------ 图（支持点击查看数值）
  function chart(vals, labels, opt) {
    opt = opt || {};
    var pts = [];
    for (var i = 0; i < vals.length; i++) if (isNum(vals[i])) pts.push([i, vals[i]]);
    if (pts.length < 2) return '<p class="empty">曲线要至少两个点。</p>';
    var W = 320, H = opt.h || 120, L = 4, R = 38, T = 8, B = 16;
    var min = pts[0][1], max = pts[0][1];
    for (var k = 1; k < pts.length; k++) { var v = pts[k][1]; if (v < min) min = v; if (v > max) max = v; }
    if (opt.base != null) { min = Math.min(min, opt.base); max = Math.max(max, opt.base); }
    var span = max - min || 1; min -= span * 0.06; max += span * 0.06; span = max - min;
    var n = vals.length - 1 || 1;
    function X(i) { return L + (W - L - R) * i / n; }
    function Y(v) { return T + (H - T - B) * (1 - (v - min) / span); }
    var d = '', gap = true;
    for (var j = 0; j < vals.length; j++) {
      if (!isNum(vals[j])) { gap = true; continue; }
      d += (gap ? 'M' : 'L') + X(j).toFixed(1) + ' ' + Y(vals[j]).toFixed(1); gap = false;
    }
    var fmt = opt.fmt || function (v) { return v.toFixed(2); };
    var svg = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(opt.label || '曲线') + '">';
    if (opt.base != null) svg += '<line class="base" x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(opt.base).toFixed(1) + '" y2="' + Y(opt.base).toFixed(1) + '"/>';
    svg += '<line class="grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + (H - B) + '" y2="' + (H - B) + '"/>';
    svg += '<path class="ln" d="' + d + '"/>';
    // 交互点：点击后在页面上方显示数值
    for (var m = 0; m < pts.length; m++) {
      var p = pts[m];
      svg += '<circle class="pt" data-i="' + p[0] + '" data-v="' + p[1] + '"' + (opt.tips && opt.tips[p[0]] != null ? ' data-t="' + esc(opt.tips[p[0]]) + '"' : '') + ' cx="' + X(p[0]).toFixed(1) + '" cy="' + Y(p[1]).toFixed(1) + '" r="3" fill="' + (opt.color || '#f6b72f') + '" opacity="0"/>';
    }
    svg += '<text x="' + (W - R + 4) + '" y="' + (T + 8) + '">' + esc(fmt(max - span * 0.06 / 1.12)) + '</text>';
    svg += '<text x="' + (W - R + 4) + '" y="' + (H - B) + '">' + esc(fmt(min + span * 0.06 / 1.12)) + '</text>';
    if (labels && labels.length) {
      svg += '<text x="' + L + '" y="' + (H - 3) + '">' + esc(labels[0]) + '</text>';
      svg += '<text x="' + (W - R) + '" y="' + (H - 3) + '" text-anchor="end">' + esc(labels[labels.length - 1]) + '</text>';
    }
    return svg + '</svg>';
  }

  function chartTipShow(x, y, text) {
    state.chartTip = { x: x, y: y, text: text };
    render();
  }
  function chartTipHide() { if (!state.chartTip) return; state.chartTip = null; render(); }   // 没有提示就不重画（滚动时会频繁调用）

  function maxDrawdown(eq) {
    var peak = -Infinity, dd = 0;
    eq.forEach(function (v) { if (!isNum(v)) return; if (v > peak) peak = v; if (peak > 0) dd = Math.min(dd, v / peak - 1); });
    return dd;
  }

  // ------------------------------------------------------------------ 选择条
  function chips(group, kinds, labelOf, current, flagOf) {
    return '<div class="chips" role="group" aria-label="选择策略">' + kinds.map(function (k) {
      return '<button class="chip" data-group="' + group + '" data-pick="' + esc(k) + '" aria-pressed="' + (k === current) + '">' +
        esc(labelOf(k)) + (flagOf && flagOf(k) ? '<i class="dot" title="今天有信号"></i>' : '') + '</button>';
    }).join('') + '</div>';
  }
  function shortLabel(snap, kind) {
    var l = (snap.labels && snap.labels[kind]) || kind;
    return l.replace('策略 ', '').replace('（大盘恐慌）', ' 大盘').replace('（行业恐慌）', ' 行业');
  }

  // 搜索过滤数组
  function filterRows(rows, keyword, keys) {
    if (!keyword) return rows;
    var kw = String(keyword).toLowerCase();
    return rows.filter(function (r) {
      return keys.some(function (k) { return String(r[k] || '').toLowerCase().indexOf(kw) >= 0; });
    });
  }

  // ------------------------------------------------------------------ 市场概览（首页）
  var BANDS = [['panic', '恐慌'], ['tense', '紧张'], ['weak', '偏弱'], ['calm', '平稳'], ['strong', '偏强'], ['hot', '过热']];

  function gauge(level) {
    var W = 320, L = 6, R = 6, Y = 14, H = 14, lo = -3, hi = 3;
    var edges = [lo].concat(level.edges || [-1.5, -1, -0.4, 0.6, 1.5], [hi]);
    function X(z) { z = Math.max(lo, Math.min(hi, z)); return L + (W - L - R) * (z - lo) / (hi - lo); }
    var svg = '<svg class="gauge" viewBox="0 0 ' + W + ' 56" role="img" aria-label="情绪档位：' + esc(level.label) + '">';
    for (var i = 0; i < BANDS.length; i++) {
      svg += '<rect class="band b-' + BANDS[i][0] + (BANDS[i][0] === level.key ? ' on' : '') + '" x="' + X(edges[i]).toFixed(1) + '" y="' + Y + '" width="' +
        (X(edges[i + 1]) - X(edges[i])).toFixed(1) + '" height="' + H + '"/>';
      svg += '<text x="' + ((X(edges[i]) + X(edges[i + 1])) / 2).toFixed(1) + '" y="' + (Y + H + 13) + '" text-anchor="middle">' + BANDS[i][1] + '</text>';
    }
    if (isNum(level.z)) {
      var x = X(level.z).toFixed(1);
      svg += '<path class="mark" d="M' + x + ' ' + (Y - 2) + 'l-5 -9h10z"/><line class="mark" x1="' + x + '" x2="' + x + '" y1="' + (Y - 2) + '" y2="' + (Y + H) + '"/>';
    }
    return svg + '</svg>';
  }

  function proxBar(z, thr) {
    var W = 300, prox = isNum(z) && isNum(thr) && thr < 0 ? Math.max(0, Math.min(1, z / thr)) : 0;
    var gap = isNum(z) && isNum(thr) ? (z - thr).toFixed(2) : '—';
    return '<svg class="prox" viewBox="0 0 ' + W + ' 12" role="img" aria-label="离触发线 ' + Math.round(prox * 100) + '%">' +
      '<rect class="track" x="0" y="3" width="' + W + '" height="6" rx="3"/><rect class="fill' + (prox >= 1 ? ' full' : '') + '" x="0" y="3" width="' + (W * prox).toFixed(1) + '" height="6" rx="3"/>' +
      '<line class="tick" x1="' + (W - 1) + '" x2="' + (W - 1) + '" y1="0" y2="12"/></svg>' +
      '<div class="prox-tip">离触发线还差 <span class="num">' + esc(gap) + '</span></div>';
  }

  function trendWord(ch) {
    if (!isNum(ch)) return '';
    if (ch <= -0.3) return '<span class="tag sell">走近</span>';
    if (ch >= 0.3) return '<span class="tag">走远</span>';
    return '<span class="tag off">持平</span>';
  }

  function viewOverview(s) {
    var o = s.overview;
    if (!o || o.error) {
      return '<section class="card"><h2>市场概览</h2><p class="empty">概览还没有数据' + (o && o.error ? '：' + esc(o.error) : '') +
        '。电脑上的牛牛更新到最新版并推送一次后，这里就有了；其他页面不受影响。</p></section>';
    }
    var lv = o.level || {}, mk = o.market || {}, br = mk.breadth || {}, hist = o.history || {}, sg = o.signal || {};
    var html = '';
    if (state.offline) {
      html += '<div class="banner warn">当前显示的是上次缓存的快照（网络不可用，已使用离线缓存），数据可能不是最新，恢复网络后请点刷新重新下载。</div>';
    }

    // 1. 现在情绪
    html += '<section class="card"><h2>现在市场情绪<small>' + md(o.as_of) + ' 收盘</small></h2>' +
      '<div class="mood"><b class="mood-' + esc(lv.tone) + '">' + esc(lv.label || '—') + '</b><span class="muted small">大盘恐慌 z = ' + num(lv.z, 2) +
      (isNum(lv.pct) ? ' · 历史上 ' + pct(lv.pct, 0) + ' 的交易日比现在更悲观' : '') + '</span></div>' +
      gauge(lv) + '<p>' + esc(lv.text || '') + '</p>' +
      '<div class="tiles">' +
      '<div class="tile"><span>今天大盘（等权）</span><b>' + pctc(mk.today, 2) + '</b></div>' +
      '<div class="tile"><span>近 20 日</span><b>' + pctc(mk.mk20, 1) + '</b></div>' +
      '<div class="tile"><span>上涨家数占比</span><b>' + pct(br.up_share, 0) + '</b></div>' +
      '<div class="tile"><span>20 日跌超 10% 的占比</span><b>' + pct(br.r20_below_10_share, 0) + '</b></div></div>' +
      '<p class="small muted">“情绪”指策略看的下跌恐慌程度：全市场等权指数近 20 日涨跌 ÷ 它自己的波动。绿 = 恐慌那一头，红 = 过热那一头。不是涨停板情绪。</p></section>';

    // 1b. 涨停板情绪（另一把尺子：打板资金的冷热；库没更新到今天就只提示，不当现在）
    var lb = o.limit_board;
    if (lb && !lb.stale) {
      var m = lb.metrics || {};
      html += '<section class="card"><h2>涨停板情绪<small>' + md(lb.date) + ' 收盘</small></h2>' +
        '<div class="mood"><b class="mood-calm">' + esc(lb.phase_zh || '—') + '</b><span class="muted small">温度 ' + num(lb.temperature, 0) + ' / 100 · 近 3 日 ' +
        (isNum(lb.change3) ? (lb.change3 > 0 ? '+' : '') + num(lb.change3, 0) : '—') + '</span></div>' +
        '<div class="tiles">' +
        '<div class="tile"><span>涨停 / 跌停（非 ST）</span><b><em class="up">' + num(m.limit_up_count_non_st, 0) + '</em> / <em class="down">' + num(m.limit_down_count_non_st, 0) + '</em></b></div>' +
        '<div class="tile"><span>最高连板</span><b>' + num(m.max_streak, 0) + ' 板</b></div>' +
        '<div class="tile"><span>炸板率</span><b>' + pct(m.broken_rate, 0) + '</b></div>' +
        '<div class="tile"><span>昨日涨停今天均涨</span><b>' + pctc(m.prev_limit_up_avg_return, 1) + '</b></div></div>';
      var lt = (lb.trend || []).filter(function (r) { return isNum(r.temperature); });
      if (lt.length > 1) html += '<h3 class="sub">最近 ' + lt.length + ' 个交易日的温度</h3>' + chart(lt.map(function (r) { return r.temperature; }), lt.map(function (r) { return md(r.date); }), { base: 50, label: '涨停板情绪温度', h: 100, fmt: function (v) { return v.toFixed(0); } });
      html += '<p class="small muted">' + esc(lb.note || '') + ' 它和上面的下跌恐慌是两回事：这里看的是打板资金的冷热，抄底策略不用它做买卖决定。</p></section>';
    } else if (lb && lb.stale) {
      html += '<div class="banner warn">涨停板情绪库只更新到 <b>' + md(lb.date) + '</b>，不是最新，这里先不显示。电脑上的每日自动更新恢复后会自动出现。</div>';
    }

    // 2. 有没有信号
    var open = (sg.books || []).filter(function (b) { return b.gate_open; });
    html += '<section class="card"><h2>有没有信号</h2>';
    if (open.length) {
      html += '<p><span class="tag open">有信号</span> ' + open.map(function (b) { return esc(b.label); }).join('、') + '</p>' +
        '<p class="small">按规则：下一个开盘日（' + md(o.plan_day) + '）开盘买、持有 20 个交易日。候选和计划金额在「信号」页。</p>';
    } else {
      html += '<p><span class="tag off">没有</span> ' + sg.n_books + ' 本账都没触发开仓。空仓等待是正常状态，不用做任何事。</p>';
    }
    if (sg.n_hold) html += '<p class="small">你录入的持仓 ' + sg.n_hold + ' 只' + (sg.sells_due ? '，其中 <b>' + sg.sells_due + ' 只</b>按规则到了卖出的日子（「持仓」页）' : '，暂时没有到期要卖的') + '。</p>';
    html += '<details><summary>' + sg.n_books + ' 本账逐个看</summary><div class="scroll"><table class="tbl"><thead><tr><th>账</th><th>状态</th><th class="n">候选</th></tr></thead><tbody>' +
      (sg.books || []).map(function (b) {
        return '<tr><td>' + esc(b.label) + '</td><td>' + (b.gate_open ? '<span class="tag open">触发</span>' : '<span class="tag off">未触发</span>') + '</td><td class="n num">' + (b.gate_open ? b.n_picks : '—') + '</td></tr>';
      }).join('') + '</tbody></table></div></details></section>';

    // 3. 离触发还差多少
    html += '<section class="card"><h2>离触发还差多少<small>z ≤ ' + num(o.threshold, 1) + ' 才触发</small></h2>';
    (o.layers || []).forEach(function (l) {
      html += '<div class="layer"><div class="lh"><b>' + esc(l.key) + ' ' + esc(l.name) + '</b><span class="muted small">' + esc(l.detail || '') + '</span>' +
        (l.state === 'open' ? '<span class="tag open">已触发</span>' : trendWord(l.change3)) + '</div>' + proxBar(l.z, l.threshold) +
        '<div class="small muted">z = <span class="num">' + num(l.z, 2) + '</span> · 还差 <span class="num">' + num(l.gap, 2) + '</span>（近 3 个交易日 ' +
        (isNum(l.change3) ? (l.change3 > 0 ? '+' : '') + num(l.change3, 2) : '—') + '）</div></div>';
    });
    var tr = (o.trend || []).filter(function (r) { return isNum(r.a); });
    if (tr.length > 1) {
      html += '<h3 class="sub">最近 ' + tr.length + ' 个交易日的大盘 z</h3>' + chart(tr.map(function (r) { return r.a; }), tr.map(function (r) { return md(r.date); }), { base: o.threshold, label: '大盘 z', h: 100 });
    }
    html += '</section>';

    // 4. 后面会怎样
    var scn = o.scenarios || [];
    html += '<section class="card"><h2>后面可能怎样<small>规则推演，不是预测</small></h2>' +
      '<p class="small">要让「大盘恐慌」层触发，大盘（全市场等权）接下来得<b>连续每天这样跌</b>：</p>' +
      '<div class="scroll"><table class="tbl"><thead><tr><th>连跌</th><th class="n">每天约</th><th class="n">累计约</th></tr></thead><tbody>' +
      scn.map(function (c) {
        return '<tr><td>' + c.days + ' 天</td><td class="n">' + (c.daily == null ? '<span class="muted">一天跌不到</span>' : '<span class="num down">' + pct(c.daily, 2) + '</span>') + '</td><td class="n">' + (c.cum == null ? '—' : '<span class="num down">' + pct(c.cum, 1) + '</span>') + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<p class="small muted">用的是和策略同一套公式（滚动 20 日涨跌 ÷ 波动），已把老的一天滚出窗口、波动变大算进去。</p>';
    if (hist.days != null) {
      html += '<h3 class="sub">这一层过去的表现（历史类比）</h3><ul class="plain small">' +
        '<li>2007 年以来，大盘恐慌层触发过 <b>' + hist.days + '</b> 天（占 ' + pct(hist.share, 1) + '），连成 <b>' + hist.episodes + '</b> 段，平均每年约 ' + num(hist.per_year, 1) + ' 段。</li>' +
        (hist.last_date ? '<li>最近一次在 ' + esc(hist.last_date) + '，到现在 ' + hist.since_last + ' 个交易日。</li>' : '') +
        (hist.fwd_median != null ? '<li>每一段触发的第一天之后 ' + hist.horizon + ' 个交易日，大盘（等权）涨跌：中位数 ' + pctc(hist.fwd_median, 1) + '，上涨的占 ' + pct(hist.fwd_win, 0) + '，最差 ' + pctc(hist.fwd_worst, 0) +
          '；任选一天同样往后看：中位数 ' + pctc(hist.base_median, 1) + '，上涨占 ' + pct(hist.base_win, 0) + '。</li>' : '') + '</ul>' +
        '<p class="small muted">历史上触发后大盘平均更容易反弹一些，但也有接着大跌的（最差那一段）。样本是 ' + hist.fwd_n + ' 段，且互相重叠，只当参考。</p>';
    }
    html += '</section>';

    // 5. 需要关注
    html += '<section class="card"><h2>需要关注什么</h2>';
    (o.watch || []).forEach(function (w) {
      html += '<div class="watch w-' + esc(w.tone) + '"><b>' + esc(w.title) + '</b><p>' + esc(w.text) + '</p></div>';
    });
    html += '<p class="small muted">' + esc(o.caveat || '') + '</p></section>';
    return html;
  }

  // ------------------------------------------------------------------ 今日信号
  function viewSignal(s) {
    var kind = state.pick.signal;
    if (s.kinds.indexOf(kind) < 0) kind = state.pick.signal = s.kinds[0];
    var sig = s.signals[kind] || {};
    var open = s.kinds.filter(function (k) { return s.signals[k] && s.signals[k].gate_open; });
    var when = '<b>' + md(s.data_date) + ' 收盘时</b>';
    var html = '<div class="banner ' + (open.length ? 'warn' : 'ok') + '">' +
      (open.length ? when + '有开仓信号：' + open.map(function (k) { return esc(s.labels[k]); }).join('、') : when + '没有任何一本触发开仓信号。空仓等待是正常状态。') + '</div>';
    html += chips('signal', s.kinds, function (k) { return shortLabel(s, k); }, kind, function (k) { return s.signals[k] && s.signals[k].gate_open; });
    if (sig.error) return html + '<section class="card"><h2>' + esc(s.labels[kind]) + '</h2><p class="empty">这一本没算出来：' + esc(sig.error) + '</p></section>';

    var isFusion = !!sig.sleeves;
    html += '<section class="card"><h2>' + esc(s.labels[kind]) + '<small>' + md(sig.date) + ' 收盘后</small></h2>';
    html += '<p>' + (sig.gate_open ? '<span class="tag open">闸门已开</span> 触发的层：' + esc((sig.fired || []).join(' / ') || '—') : '<span class="tag off">闸门未开</span> 今天不开新仓') + '</p>';
    html += '<div class="tiles">' +
      '<div class="tile"><span>大盘恐慌 z（≤ ' + num(sig.z_threshold, 1) + ' 触发）</span><b class="' + (isNum(sig.z) && sig.z <= (sig.z_threshold || -1.5) ? 'up' : '') + '">' + num(sig.z, 2) + '</b></div>' +
      '<div class="tile"><span>大盘近 20 日涨跌</span><b>' + pctc(sig.mk20, 1) + '</b></div></div>';
    if (isFusion) {
      html += '<div class="scroll"><table class="tbl"><thead><tr><th>层</th><th>最弱的一组</th><th class="n">z</th><th class="n">候选</th><th>状态</th></tr></thead><tbody>';
      ['A', 'C', 'B'].forEach(function (k) {
        var sl = sig.sleeves[k]; if (!sl) return;
        html += '<tr><td>' + k + ' ' + esc(sl.name) + '</td><td>' + esc(sl.detail || '—') + (sl.blacklisted ? ' <span class="tag blacklist" title="该行业在 D4 黑名单里，不进入买入池">黑名单</span>' : '') + '</td><td class="n num">' + num(sl.z, 2) +
          '</td><td class="n num">' + (sl.n_pool || 0) + '</td><td>' + (sl.gate ? '<span class="tag open">触发</span>' : '<span class="tag off">未触发</span>') + '</td></tr>';
      });
      html += '</tbody></table></div>';
      var mp = sig.market_position;
      if (mp && mp.on) {
        html += '<p class="small ' + (mp.blocked ? '' : 'muted') + '">近高点过滤：大盘离近 ' + mp.window + ' 日高点 ' + (isNum(mp.gap) ? pct(Math.abs(mp.gap), 1) : '—') +
          (mp.blocked ? '，<b>今天的信号被它挡掉了</b>（不足 ' + pct(mp.pct, 0) + '）。' : '（低于 ' + pct(mp.pct, 0) + ' 才会挡）。') + '</p>';
      }
      if (sig.blacklist && sig.blacklist.length) html += '<p class="small muted">B 层黑名单行业：' + esc(sig.blacklist.join('、')) + '</p>';
    } else if (sig.market_z != null) {
      html += '<p class="small muted">行业最弱 z：' + num(sig.z, 2) + '（大盘 ' + num(sig.market_z, 2) + '）</p>';
    }
    html += '</section>';

    // 候选股：带搜索框
    var picks = sig.picks || [];
    var allPicks = picks;
    var kw = state.search.signal || '';
    var disp = kw ? filterRows(allPicks, kw, ['code', 'name', 'group', 'sleeve']) : allPicks;
    var plan = disp.filter(function (p) { return p.in_plan !== false; });

    var searchBar = '';
    if (allPicks.length) {
      searchBar = '<div class="search-bar"><input type="search" id="sig-search" placeholder="搜索代码/名称/行业/层…" value="' + esc(kw) + '"></div>';
    }

    html += '<section class="card"><h2>候选股<small>' + (picks.length ? '计划买 ' + plan.length + ' 只，其余备选' : '') + '</small></h2>' + searchBar;
    if (!disp.length) {
      html += '<p class="empty">' + (kw ? '没有匹配的候选股。' : (sig.gate_open ? '闸门开了，但今天没有可买的股票。' : '闸门没开，没有候选。')) + '</p>';
    } else {
      html += '<div class="scroll"><table class="tbl"><thead><tr><th>#</th><th>股票</th>' + (isFusion ? '<th>层</th>' : '') + '<th class="n">收盘</th><th class="n">20 日</th>' +
        (isFusion && picks.some(function (p) { return p.plan_shares != null; }) ? '<th class="n">股数</th>' : '') + '</tr></thead><tbody>';
      disp.forEach(function (p) {
        html += '<tr' + rowCode(p.code) + (p.in_plan === false ? ' class="muted"' : '') + '><td class="num">' + esc(p.rank) + '</td><td>' + esc(short(p.code)) + '<span class="nm">' + esc(p.name || '') + (p.group ? ' · ' + esc(p.group) : '') + '</span></td>' +
          (isFusion ? '<td>' + esc(p.sleeve) + '</td>' : '') + '<td class="n num">' + num(p.close, 2) + '</td><td class="n">' + pctc(p.ret20, 1) + '</td>' +
          (isFusion && picks.some(function (q) { return q.plan_shares != null; }) ? '<td class="n num">' + (p.plan_shares != null ? money(p.plan_shares) : '—') + '</td>' : '') + '</tr>';
      });
      html += '</tbody></table></div>';
      if (sig.picks_total && sig.picks_total > picks.length) html += '<p class="small muted">只显示前 ' + picks.length + ' 只，共 ' + sig.picks_total + ' 只。</p>';
    }
    html += '</section>';

    var rec = (sig.recent || []).filter(function (r) { return isNum(r.a != null ? r.a : r.z); });
    if (rec.length > 1) {
      var key = rec[0].a != null ? 'a' : 'z';
      html += '<section class="card"><h2>最近 ' + rec.length + ' 个交易日的大盘 z<small>低于 ' + num(sig.z_threshold, 1) + ' 才触发</small></h2>' +
        chart(rec.map(function (r) { return r[key]; }), rec.map(function (r) { return md(r.date); }), { base: sig.z_threshold, label: '大盘 z', h: 100, color: '#f6b72f' }) + '</section>';
    }
    var inds = (sig.industries || []).filter(function (r) { return isNum(r.z); }).slice(0, 5);
    if (inds.length) {
      html += '<section class="card"><h2>最接近触发的行业<small>z 越低越恐慌</small></h2><div class="scroll"><table class="tbl"><thead><tr><th>行业</th><th class="n">z</th><th class="n">20 日</th><th></th></tr></thead><tbody>' +
        inds.map(function (r) { return '<tr><td>' + esc(r.name) + '</td><td class="n num">' + num(r.z, 2) + '</td><td class="n">' + pctc(r.ret20, 1) + '</td><td>' + (r.triggered ? '<span class="tag open">触发</span>' : '') + '</td></tr>'; }).join('') +
        '</tbody></table></div></section>';
    }
    return html;
  }

  // ------------------------------------------------------------------ 前向跟踪
  var STATUS = { waiting: '等待买入', open: '持有中', closed: '已结算', not_filled: '没买进' };

  function viewForward(s) {
    var kind = state.pick.forward;
    if (s.kinds.indexOf(kind) < 0) kind = state.pick.forward = s.kinds[0];
    var f = s.forward[kind] || {};
    var html = '<div class="banner ok">前向跟踪 = 参数冻结后，每天把当天的信号记下来，之后用真实后续行情结算。只有这个数字才能说明策略在样本外是否有效；样本内回测不算。</div>';
    html += chips('forward', s.kinds, function (k) { return shortLabel(s, k); }, kind);
    if (f.error) return html + '<section class="card"><h2>' + esc(s.labels[kind]) + '</h2><p class="empty">这一本没算出来：' + esc(f.error) + '</p></section>';
    var sm = f.summary || {};
    html += '<section class="card"><h2>' + esc(s.labels[kind]) + '<small>' + (f.start_date ? '从 ' + f.start_date + ' 开始记录' : '') + '</small></h2>';
    if (!sm.n_records) {
      html += '<p class="empty">还没有记录。这一本只在“闸门打开、有候选、数据还新鲜”的交易日记录，没触发就没有记录。</p></section>';
      return html;
    }
    html += '<div class="tiles">' +
      '<div class="tile"><span>信号条数</span><b>' + sm.n_records + '<small class="muted"> · 已结算 ' + sm.n_closed + '</small></b></div>' +
      '<div class="tile"><span>每条信号平均收益</span><b>' + pctc(sm.mean_signal_ret, 2) + '</b></div>' +
      '<div class="tile"><span>信号胜率</span><b>' + pct(sm.signal_win_rate, 0) + '</b></div>' +
      '<div class="tile"><span>单只胜率（' + (sm.n_picks || 0) + ' 只）</span><b>' + pct(sm.pick_win_rate, 0) + '</b></div></div>';
    if (sm.note) html += '<p class="small muted">' + esc(sm.note) + '</p>';
    html += '</section>';

    // 状态筛选
    var filterHtml = '<div class="filter-row">' +
      ['all', 'waiting', 'open', 'closed'].map(function (k) {
        var labelMap = { all: '全部', waiting: '等待买入', open: '持有中', closed: '已结算' };
        return '<button class="chip" data-ff="' + k + '" aria-pressed="' + (state.forwardFilter === k) + '">' + labelMap[k] + '</button>';
      }).join('') + '</div>';

    if (f.portfolio && f.portfolio.curve) {
      var c = f.portfolio.curve, eq = c.equity, last = eq.filter(isNum).slice(-1)[0];
      html += '<section class="card"><h2>前向净值<small>本金 = 1，含成本</small></h2><div class="tiles">' +
        '<div class="tile"><span>累计</span><b>' + pctc(isNum(last) ? last - 1 : null, 1) + '</b></div>' +
        '<div class="tile"><span>最大回撤</span><b>' + pctc(maxDrawdown(eq), 1) + '</b></div></div>' +
        chart(eq, c.dates.map(md), { base: 1, label: '前向净值', color: '#f6b72f' }) +
        ((f.portfolio.mismatched || []).length ? '<p class="small muted">有 ' + f.portfolio.mismatched.length + ' 天的记录和现在重算的候选不完全一致（数据修订等），以记录为准。</p>' : '') + '</section>';
      var op = f.portfolio.open_positions || [];
      if (op.length) {
        html += '<section class="card"><h2>模拟持仓<small>' + op.length + ' 只</small></h2><div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th>信号日</th><th class="n">浮盈</th></tr></thead><tbody>' +
          op.map(function (p) { return '<tr' + rowCode(p.code) + '><td>' + esc(short(p.code)) + '<span class="nm">' + esc(p.name || p.sleeve || '') + '</span></td><td class="num">' + md(p.signal) + '</td><td class="n">' + pctc(p.ret != null ? p.ret : p.mtm, 1) + '</td></tr>'; }).join('') +
          '</tbody></table></div></section>';
      }
    }
    var recs = (f.records || []).filter(function (r) {
      if (state.forwardFilter === 'all') return true;
      return r.status === state.forwardFilter;
    });
    html += '<section class="card"><h2>信号记录<small>最近 ' + recs.length + ' 条（筛选：' + { all: '全部', waiting: '等待买入', open: '持有中', closed: '已结算' }[state.forwardFilter] + '）</small></h2>' + filterHtml;
    recs.forEach(function (r) {
      var ret = r.status === 'closed' ? r.mean_ret : r.mean_mtm;
      html += '<details><summary><b class="num">' + md(r.signal_date) + '</b> <span class="tag">' + esc(STATUS[r.status] || r.status) + '</span> ' +
        (r.fired && r.fired.length ? '<span class="muted small">' + esc(r.fired.join('/')) + '</span> ' : '') + pctc(ret, 2) + '</summary>' +
        '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th>层</th><th class="n">收益</th></tr></thead><tbody>' +
        (r.rows || []).map(function (p) { return '<tr' + rowCode(p.code) + '><td>' + esc(short(p.code)) + '<span class="nm">' + esc(p.name || '') + '</span></td><td>' + esc(p.sleeve || '') + '</td><td class="n">' + (p.status === 'not_filled' ? '<span class="muted">没买进</span>' : pctc(p.ret != null ? p.ret : p.mtm, 1)) + '</td></tr>'; }).join('') +
        '</tbody></table></div></details>';
    });
    return html + '</section>';
  }

  // ------------------------------------------------------------------ 我的持仓
  var HSTAT = { overdue: ['已到期', 'sell'], due: ['明天卖', 'sell'], hold: ['持有', ''], pending: ['未到买入日', ''], unknown: ['不在面板', ''] };

  function viewHoldings(s) {
    var h = s.holdings || {};
    if (h.error) return '<section class="card"><h2>我的持仓</h2><p class="empty">没算出来：' + esc(h.error) + '</p></section>';
    var variants = Object.keys(h.plans || {});
    var v = state.pick.holdings; if (variants.indexOf(v) < 0) v = state.pick.holdings = variants[0];
    var p = (h.plans || {})[v] || {};
    var html = '<div class="banner ok">持仓只在电脑上录入和修改，手机只看。清单按所选策略的规则算；这里不下单、不连券商。</div>';
    html += chips('holdings', variants, function (k) { return k; }, v);
    if (p.error) return html + '<section class="card"><p class="empty">' + esc(p.error) + '</p></section>';

    // 持仓总汇总
    var rows = h.holdings || [];
    var totalValue = 0, totalPnlAmt = 0;
    rows.forEach(function (r) { totalValue += isNum(r.value) ? r.value : 0; totalPnlAmt += isNum(r.value) && isNum(r.pnl) ? r.value * r.pnl / 100 : 0; });

    html += '<section class="card"><h2>' + esc(p.plan_day ? md(p.plan_day) + '（' + wd(p.plan_day) + '）' : '明天') + '要做什么<small>策略 ' + esc(v) + '</small></h2>' +
      '<div class="kv"><span>账户总资产</span><span class="num">' + num(h.equity_wan, 1) + ' 万</span><span>持仓</span><span class="num">' + (h.n_holdings || 0) + ' 只</span>' +
      '<span>持仓市值</span><span class="num">' + money(totalValue) + ' 元</span><span>总浮盈</span><span class="num ' + (totalPnlAmt >= 0 ? 'up' : 'down') + '">' + (totalPnlAmt >= 0 ? '+' : '') + money(totalPnlAmt) + ' 元</span></div>';
    (p.notes || []).forEach(function (t) { html += '<p class="small muted">· ' + esc(t) + '</p>'; });
    html += '</section>';

    // 搜索框
    var hk = state.search.holdings || '';
    var dispHoldings = hk ? filterRows(rows, ['code', 'name', 'sleeve'], ['code', 'name', 'sleeve']) : rows;

    html += '<section class="card"><h2>卖出<small>' + (p.sells || []).length + ' 只</small></h2>';
    if (!(p.sells || []).length) html += '<p class="empty">没有要卖的。</p>';
    else html += '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th class="n">股数</th><th class="n">盈亏</th><th>说明</th></tr></thead><tbody>' + p.sells.map(function (r) {
      return '<tr' + rowCode(r.code) + '><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + '</span></td><td class="n num">' + money(r.shares) + '</td><td class="n">' + pctc(r.pnl, 1) + '</td><td class="wrap">' + esc(r.advice) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
    html += '</section>';

    html += '<section class="card"><h2>买入<small>' + (p.buys || []).length + ' 只' + (p.new_money ? ' · 约 ' + money(p.new_money) + ' 元' : '') + '</small></h2>';
    if (p.stale) html += '<p class="empty">数据已过期，不出买入计划。</p>';
    else if (!(p.buys || []).length) html += '<p class="empty">' + (p.gate_open ? '闸门开了，但没有可买的（名额满、仓位上限或买不起一手）。' : '闸门没开，不买。') + '</p>';
    else html += '<div class="scroll"><table class="tbl"><thead><tr><th>层</th><th>股票</th><th class="n">股数</th><th class="n">金额</th><th class="n">收盘</th></tr></thead><tbody>' + p.buys.map(function (r) {
      return '<tr' + rowCode(r.code) + '><td>' + esc(r.sleeve) + '</td><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + '</span></td><td class="n num">' + money(r.shares) + '</td><td class="n num">' + money(r.amount) + '</td><td class="n num">' + num(r.close, 2) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
    if ((p.spares || []).length) html += '<details><summary>备选 ' + p.spares.length + ' 只（买不进时顺延）</summary><p class="small">' + p.spares.map(function (r) { return esc(r.sleeve + short(r.code) + ' ' + (r.name || '')); }).join('、') + '</p></details>';
    html += '</section>';

    html += '<section class="card"><h2>全部持仓<small>' + dispHoldings.length + ' 只（共 ' + rows.length + ' 只）</small></h2>';
    var searchBar = '';
    if (rows.length) {
      searchBar = '<div class="search-bar"><input type="search" id="hold-search" placeholder="搜索代码/名称/层…" value="' + esc(hk) + '"></div>';
    }
    html += searchBar;
    if (!dispHoldings.length) {
      html += '<p class="empty">' + (hk ? '没有匹配的持仓。' : '还没有录入持仓。在电脑的“我的持仓”里录入，推送后这里会显示。') + '</p>';
    } else {
      html += '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th class="n">股数</th><th class="n">市值</th><th class="n">盈亏</th><th>状态</th></tr></thead><tbody>' + dispHoldings.map(function (r) {
        var st = HSTAT[r.status] || [r.status, ''];
        return '<tr' + rowCode(r.code) + '><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + (r.sleeve ? ' · ' + esc(r.sleeve) + '层' : '') + '</span></td><td class="n num">' + money(r.shares) + '</td><td class="n num">' + money(r.value) + '</td><td class="n">' + pctc(r.pnl, 1) + '</td><td><span class="tag ' + st[1] + '">' + st[0] + '</span>' +
          (r.days_held != null ? '<span class="nm">第 ' + r.days_held + ' 天</span>' : '') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    }
    return html + '</section>';
  }

  // ------------------------------------------------------------------ 说明
  function viewGuide(s) {
    var html = '<section class="card"><h2>怎么看这个页面</h2><ul class="plain">' +
      '<li><b>概览</b>是首页：现在的下跌恐慌程度、有没有信号、离触发还差多少、规则推演和历史类比、该盯什么。它只用策略自己的数据，不是涨停板情绪，也不是预测。</li>' +
      '<li><b>只读、纸面</b>：不下单、不连券商；信号只是按规则算出来的“明天可以考虑什么”。</li>' +
      '<li><b>数据每天收盘后更新一次</b>：电脑上的牛牛算完推上来，数据日期在顶部。过了下一个开盘就是旧数据。</li>' +
      '<li><b>红涨绿跌</b>：红色是上涨 / 盈利，绿色是下跌 / 亏损。</li>' +
      '<li><b>数据是加密的</b>：服务器上只有密文，口令只在这台手机和电脑上。</li></ul></section>';
    html += '<section class="card"><h2>八个策略</h2><ul class="plain">' +
      '<li><b>A</b> 大盘恐慌：全市场平均 z ≤ −1.5 时买“跌破布林下轨后收复”的股票。</li>' +
      '<li><b>B</b> 行业恐慌：某个申万一级行业 z ≤ −1.5 时，买该行业里同样形态的股票。</li>' +
      '<li><b>D</b> 三层合一：大盘（A）、成交额分档（C）、行业（B）三种恐慌各管一层，共用一笔钱。</li>' +
      '<li><b>D1</b> D 换成“离 60 日高点回撤最深优先”的候选排序。</li>' +
      '<li><b>D2</b> D1 加近高点过滤：大盘离近高点太近时不开新仓。</li>' +
      '<li><b>D3</b> D2 再把层优先级改成 C 先 A 后。</li>' +
      '<li><b>D4</b> D3 再加 B 层行业黑名单（房地产、国防军工）。</li></ul>' +
      '<p class="small muted">D2～D4 的回测数字都是样本内，真实表现要看“前向跟踪”。</p></section>';
    html += '<section class="card"><h2>E6 龙头扫板（研究中）</h2><p>和上面的抄底策略无关，是“期末50分”那条打板研究线里检验通过的一条：每天只看昨天涨停股里开盘最强、身位最高的那一只，' +
      '盘中摸到涨停价就挂涨停价买，收盘封住就拿、没封住就卖。「E6」页是它的前向记录和下一个交易日的名单，只记录不交易。</p></section>';
    if (s.results && s.results.rows) {
      html += '<section class="card"><h2>回测对照<small>2008 起，扣成本，1 倍</small></h2><div class="scroll"><table class="tbl"><thead><tr>' + s.results.head.map(function (h, i) { return '<th class="' + (i ? 'n' : '') + '">' + esc(h) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        s.results.rows.map(function (r) { return '<tr>' + r.map(function (c, i) { return '<td class="' + (i ? 'n num' : 'wrap') + '">' + esc(c) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>' +
        '<p class="small muted">“含退市”指补上了 290 只退市股的面板。</p></section>';
    }
    html += '<section class="card"><h2>这台手机</h2><p class="small muted">快照生成于 ' + esc(dt(s.generated_at)) + '。</p>' +
      '<button class="btn" id="forget">忘记口令并锁定</button></section>';
    return html;
  }

  // ------------------------------------------------------------------ 策略 E6（龙头扫板）前向记录（研究中，只记录不交易）
  var E6_NAME = { 'E6': 'E6 龙头扫板', 'E6-U': 'E6-U 行业唯一最高板', 'E6b': 'E6b 龙头开盘买' };
  function e6Tag(r) {
    var st = String(r.status || '');
    if (st.indexOf('持有中') === 0) return '<span class="tag open">持有中</span>';
    if (st === '已卖出') return '<span class="tag">已卖出</span>';
    return '<span class="tag off">' + esc(st.replace('，不做', '·不做')) + '</span>';
  }
  function e6Ret(r) { return isNum(r.ret) ? pctc(r.ret / 100, 1) : '<span class="muted">—</span>'; }
  function e6Curve(c) {
    if (!c || !c.equity || c.equity.length < 2) return '';
    var t = c.total || {}, ym = function (d) { return String(d || '').slice(0, 7); };
    var p100 = function (v, d) { return isNum(v) ? pctc(v / 100, d == null ? 1 : d) : '—'; };
    var html = '<section class="card"><h2>历史账户曲线<small>' + esc(ym(c.first)) + ' 至 ' + esc(ym(c.last)) + ' · 回测</small></h2><div class="tiles">' +
      '<div class="tile"><span>累计</span><b>' + (isNum(t.mult) ? '×' + t.mult.toFixed(1) : '—') + '</b></div>' +
      '<div class="tile"><span>年化</span><b>' + p100(t.cagr) + '</b></div>' +
      '<div class="tile"><span>最大回撤</span><b>' + p100(t.mdd) + '</b></div>' +
      '<div class="tile"><span>信号 / 每笔</span><b>' + esc(t.n) + ' / ' + p100(t.mean, 2) + '</b></div></div>' +
      chart(c.equity, c.dates.map(ym), { base: 1, label: 'E6 历史账户曲线', color: '#f6b72f', h: 150,
        fmt: function (v) { return '×' + v.toFixed(1); },
        tips: c.dates.map(function (d, i) { return ym(d) + '：×' + (isNum(c.equity[i]) ? c.equity[i].toFixed(2) : '—'); }) });
    var sg = c.segs || [];
    if (sg.length) {
      html += '<div class="scroll"><table class="tbl"><thead><tr><th>阶段</th><th class="n">信号</th><th class="n">每笔</th><th class="n">账户</th></tr></thead><tbody>' +
        sg.map(function (s) {
          var lb = String(s.label || ''), sp = lb.indexOf(' ');
          return '<tr><td>' + esc(sp > 0 ? lb.slice(0, sp) : lb) + (sp > 0 ? '<span class="nm">' + esc(lb.slice(sp + 1)) + '</span>' : '') + '</td><td class="n num">' + esc(s.n) +
            '</td><td class="n">' + p100(s.mean, 2) + '</td><td class="n num">' + (isNum(s.mult) ? '×' + s.mult.toFixed(2) : '—') +
            (isNum(s.cagr) ? '<span class="nm">年化 ' + s.cagr.toFixed(1) + '%</span>' : '') + '<span class="nm">回撤 ' + (isNum(s.mdd) ? s.mdd.toFixed(1) + '%' : '—') + '</span></td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    var ys = c.years || [];
    if (ys.length) {
      html += '<h3 class="sub">每年</h3><div class="scroll"><table class="tbl"><thead><tr><th class="num">年</th><th class="n">信号</th><th class="n">每笔</th><th class="n">账户</th><th class="n">回撤</th></tr></thead><tbody>' +
        ys.slice().reverse().map(function (y) {
          return '<tr><td class="num">' + esc(y.year) + '</td><td class="n num">' + esc(y.n) + '</td><td class="n">' + p100(y.mean, 2) + '</td><td class="n">' + p100(y.acct) + '</td><td class="n">' + p100(y.mdd) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    return html + '<p class="small muted">' + esc(c.note || '') + ' 点曲线上的点看当月数值。10-20 起是前向记录，看下面几张表。</p></section>';
  }
  function viewE6(s) {
    var e = s.e6;
    if (!e || e.error) {
      return '<section class="card"><h2>E6 龙头扫板</h2><p class="empty">' + (e && e.error ? '读不出来：' + esc(e.error) :
        '还没有 E6 的数据。台式机每个交易日 19:00 记录完会推上来。') + '</p></section>';
    }
    var html = '';
    if (e.data_date && s.data_date && e.data_date < s.data_date) {
      html += '<div class="banner warn">E6 记录只到 <b>' + md(e.data_date) + '</b>；台式机每个交易日 19:00 记一次，记完会再推上来。</div>';
    }
    // 1. 明天怎么做
    var nx = e.next || {};
    html += '<section class="card"><h2>下一个交易日怎么做<small>按 ' + md(nx.day) + ' 收盘</small></h2>' +
      '<p><b>E6 龙头扫板</b>：开盘后，把昨天涨停的主板非 ST 股按“开盘涨幅名次 + 昨日连板名次”打分，取第 1。开盘就涨停的不做；' +
      '盘中第一次摸到涨停价，<b>3 秒内</b>挂涨停价买。收盘还封住就拿，第一次没封住那天收盘卖，最多拿 5 天。</p>';
    if (nx.error) {
      html += '<p class="empty">名单还没算出来：' + esc(nx.error) + '</p>';
    } else {
      var top = nx.top || [];
      if (top.length) {
        html += '<h3 class="sub">昨日连板最高的几只（打分第 1 要开盘后才知道）</h3><div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th class="n">板</th><th>行业地位</th></tr></thead><tbody>' +
          top.map(function (r) {
            return '<tr' + rowCode(r.code) + '><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + '</span></td><td class="n num">' + esc(r.board) + '</td><td class="wrap small">' +
              (r.tag === '行业唯一最高板' ? '<span class="tag open">行业唯一</span>' : esc(r.tag || '')) + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }
      var hi = nx.e6b || [];
      if (hi.length) {
        html += '<p><b>E6b 龙头开盘买</b>（最高板 ' + esc(nx.max_board) + ' 板，开盘没涨停就按开盘价买）：' +
          hi.map(function (r) { return esc(r.name || short(r.code)); }).join('、') + '</p>' +
          '<p class="small muted">' + hi.map(function (r) { return esc((r.name || '') + '：' + (r.reason || '')); }).join('；') + '</p>';
      }
      html += '<p class="small muted">名单来自同花顺涨停池，连板数按日线重算。“行业唯一”指它是申万二级行业里唯一的最高板（E6-U），只作并行记录，2010–2018 检验它没有额外价值。</p>';
    }
    html += '</section>';
    // 1b. 历史账户曲线（回测，描述性）
    html += e6Curve(e.curve);
    // 2. 持有中
    var hold = e.holding || [];
    html += '<section class="card"><h2>持有中<small>纸面记录，按收盘盯市</small></h2>';
    if (!hold.length) html += '<p class="empty">现在没有持有中的记录。</p>';
    else html += '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th>规则</th><th class="num">买入日</th><th class="n">浮盈</th></tr></thead><tbody>' +
      hold.map(function (r) {
        return '<tr' + rowCode(r.code) + '><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + '</span></td><td>' + esc(r.rule) + '</td><td class="num">' + md(r.date) + '</td><td class="n">' + e6Ret(r) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    html += '</section>';
    // 3. 前向记录汇总
    var sm = e.summary || [];
    html += '<section class="card"><h2>前向记录<small>' + md(e.fwd_start) + ' 起 · 只记录不交易</small></h2>' +
      '<div class="scroll"><table class="tbl"><thead><tr><th>规则</th><th class="n">信号日</th><th class="n">做了</th><th class="n">已卖</th><th class="n">每笔</th><th class="n">买到</th></tr></thead><tbody>' +
      sm.map(function (r) {
        return '<tr><td>' + esc(r.rule) + '</td><td class="n num">' + esc(r.n_days) + '</td><td class="n num">' + esc(r.n_done) + '</td><td class="n num">' + esc(r.n_closed) +
          '</td><td class="n">' + (isNum(r.closed_mean) ? pctc(r.closed_mean / 100, 2) : '—') + '</td><td class="n num">' + (r.l1_judged ? esc(r.l1_filled) + '/' + esc(r.l1_judged) : '—') + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<p class="small muted">' + sm.map(function (r) { return esc(r.rule) + ' = ' + esc((E6_NAME[r.rule] || r.rule).replace(r.rule + ' ', '')); }).join('；') + '。' +
      '“做了”= 开盘没涨停、盘中摸到涨停价（E6）或开盘价买入（E6b）；“每笔”只算已卖出的，按涨停价 / 开盘价理想成交、扣 0.25%；“买到”是 E6 用触板股盘口录制近似判断的成交数 / 判断数，L2 日包到了再精确补算。正式评估在 E6 做满 30 次或 2027-04-30。</p></section>';
    // 4. 最近信号
    var sg = e.signals || [];
    html += '<section class="card"><h2>最近的信号<small>共 ' + esc(e.n_signals) + ' 条</small></h2>';
    if (!sg.length) html += '<p class="empty">还没有信号。</p>';
    else html += '<div class="scroll"><table class="tbl"><thead><tr><th class="num">日期</th><th>股票</th><th>状态</th><th class="n">收益</th></tr></thead><tbody>' +
      sg.map(function (r) {
        return '<tr' + rowCode(r.code) + '><td class="num">' + md(r.date) + '<span class="nm">' + esc(r.rule) + '</span></td><td>' + esc(r.name || short(r.code)) +
          '<span class="nm">' + esc(r.streak_y) + ' 板' + (isNum(r.gap) ? ' · 开 ' + pct(r.gap / 100, 1, true) : '') + '</span></td><td>' + e6Tag(r) + '</td><td class="n">' + e6Ret(r) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    html += '</section>';
    // 5. 历史检验
    html += '<section class="card"><h2>它为什么在这里<small>历史检验</small></h2><ul class="plain small">' +
      '<li>E6：2010–2018 年（规则定下来之前没看过的 9 年）每笔 +1.76%，457 笔，三段都为正。</li>' +
      '<li>能不能买到：2025 年按 L2 逐笔算，摸板后 3 秒挂单 87% 买到，买不到记 0 后每个信号 +2.01%；只有 31 个信号，统计上还证明不了。</li>' +
      '<li>E6b：2010–2018 每笔 +1.09%，但 2024、2025 年接近 0 或略负。</li>' +
      '<li>收益靠少数连板的票，中位数接近 0、胜率约一半；最怕的是封得最快的好板买不到。</li></ul>' +
      '<p class="small muted">研究线，前向记录只看不做；要不要真的用，等前向记录攒够再说。</p></section>';
    return html;
  }

  // ------------------------------------------------------------------ 外壳
  var TABS = [
    ['overview', '概览', '<path d="M3 12a9 9 0 0 1 18 0"/><path d="M12 12l4-4"/><circle cx="12" cy="12" r="1.2"/><path d="M5 19h14"/>'],
    ['signal', '信号','<path d="M13 3 5 13h6l-1 8 8-10h-6z"/>'],
    ['forward', '前向','<path d="M3 17l5-5 4 4 8-9"/><path d="M3 21h18"/>'],
    ['holdings', '持仓','<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>'],
    ['e6', 'E6', '<path d="M4 20h16"/><path d="M6 16l4-5 3 3 5-8"/><path d="M15 6h3v3"/>'],
    ['guide', '说明', '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="8" r=".6"/>']
  ];

  function render() {
    if (state.phase === 'loading') { app.innerHTML = '<div class="center">正在下载并解密…</div>'; return; }
    if (state.phase === 'error') {
      app.innerHTML = '<div class="gate"><h1>打不开</h1><p class="muted">' + esc(state.error) + '</p><p><button class="btn primary" id="retry">重试</button></p></div>';
      return bind();
    }
    if (state.phase === 'locked') {
      var d = state.env && state.env.data_date ? '<p class="small muted">数据截至 ' + esc(state.env.data_date) + '（密文）</p>' : '';
      var passInput = '<input id="pass" type="' + (state.passVisible ? 'text' : 'password') + '" placeholder="口令" autocapitalize="off" autocorrect="off" spellcheck="false" aria-label="口令">';
      var toggle = '<button type="button" id="pass-toggle">' + (state.passVisible ? '隐藏' : '显示') + '口令</button>';
      app.innerHTML = '<div class="gate"><h1>牛牛策略</h1><p class="muted">输入口令查看。口令在电脑上：<code>artifacts/_home/mobile_passphrase</code></p>' + d +
        '<form id="unlock" autocomplete="off">' + passInput +
        '<div class="err" id="err" role="alert">' + esc(state.error) + '</div>' +
        toggle +
        '<button class="btn primary" type="submit">解锁</button></form></div>';
      return bind();
    }
    var s = state.snap;
    var body = state.tab === 'overview' ? viewOverview(s) : state.tab === 'signal' ? viewSignal(s) : state.tab === 'forward' ? viewForward(s) : state.tab === 'holdings' ? viewHoldings(s) : state.tab === 'e6' ? viewE6(s) : viewGuide(s);
    var fr = freshness(s).map(function (b) { return '<div class="banner ' + b.k + '">' + b.t + '</div>'; }).join('');
    // 图表 tip 覆盖层
    var tipHtml = '';
    if (state.chartTip) {
      tipHtml = '<div id="nn-tip">' + esc(state.chartTip.text) + '</div>';     // 位置在下面用 CSSOM 设，CSP 不放行行内 style
    }
    app.innerHTML = '<header class="top"><div><h1>牛牛策略</h1><div class="sub">快照 ' + esc(dt(s.generated_at)) + ' · 纸面记录</div></div><button class="btn" id="refresh">刷新</button></header>' +
      '<main>' + (state.tab === 'guide' ? '' : fr) + body + tipHtml + '</main>' + stockSheet(s) +
      '<nav class="tabs" aria-label="页面">' + TABS.map(function (t) {
        return '<button data-tab="' + t[0] + '"' + (t[0] === state.tab ? ' aria-current="page"' : '') + '><svg viewBox="0 0 24 24" aria-hidden="true">' + t[2] + '</svg>' + t[1] + '</button>';
      }).join('') + '</nav>';
    var tip = document.getElementById('nn-tip');
    if (tip && state.chartTip) {
      tip.style.left = state.chartTip.x + 'px'; tip.style.top = state.chartTip.y + 'px';
      var tw = tip.offsetWidth;                                        // 别超出屏幕右边
      if (state.chartTip.x + tw > window.innerWidth - 8) tip.style.left = Math.max(8, window.innerWidth - tw - 8) + 'px';
    }
    bind();
  }

  function savePref() { ls(false, LS_PREF, JSON.stringify({ tab: state.tab, pick: state.pick, search: state.search, forwardFilter: state.forwardFilter })); }

  function bind() {
    var q = function (sel) { return app.querySelector(sel); };
    var form = q('#unlock');
    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var pass = q('#pass').value.trim(); if (!pass) return;
        q('#err').textContent = '解密中…';
        load(pass);
      });
      var tp = q('#pass-toggle'); if (tp) tp.addEventListener('click', function () { state.passVisible = !state.passVisible; render(); });
      var inp = q('#pass'); if (inp) inp.focus();
    }
    var retry = q('#retry'); if (retry) retry.addEventListener('click', function () { load(); });
    var rf = q('#refresh'); if (rf) {
      rf.addEventListener('click', function () { var y = window.scrollY; load().then(function () { window.scrollTo(0, y); }); });
    }
    var fg = q('#forget'); if (fg) fg.addEventListener('click', function () { ls(false, LS_PASS, null); state.snap = null; state.phase = 'locked'; state.error = ''; render(); });

    // 各页策略切换
    Array.prototype.forEach.call(app.querySelectorAll('[data-pick]'), function (b) {
      b.addEventListener('click', function () { state.pick[b.getAttribute('data-group')] = b.getAttribute('data-pick'); savePref(); var y = window.scrollY; render(); window.scrollTo(0, y); });
    });

    // 前向状态筛选
    Array.prototype.forEach.call(app.querySelectorAll('[data-ff]'), function (b) {
      b.addEventListener('click', function () { state.forwardFilter = b.getAttribute('data-ff'); savePref(); render(); });
    });

    // 页签切换
    Array.prototype.forEach.call(app.querySelectorAll('[data-tab]'), function (b) {
      b.addEventListener('click', function () { state.tab = b.getAttribute('data-tab'); savePref(); render(); window.scrollTo(0, 0); });
    });

    // 搜索输入
    var sigSearch = q('#sig-search'); if (sigSearch) {
      sigSearch.addEventListener('input', function () { state.search.signal = this.value; savePref(); render(); });
    }
    var holdSearch = q('#hold-search'); if (holdSearch) {
      holdSearch.addEventListener('input', function () { state.search.holdings = this.value; savePref(); render(); });
    }

    // 以下监听挂在 app / document / window 这些不会被重画的元素上，只能挂一次。
    // 以前每次 render() 都会再挂一遍：点一下、滚一下就触发越来越多次重画，用久了页面会卡死。
    if (bind.once) return;
    bind.once = true;

    // 点一行股票 → 弹出最近走势；点“关闭”或灰色背景收起
    app.addEventListener('click', function (e) {
      if (!e.target.closest) return;
      if (e.target.closest('#sheet-close') || e.target.id === 'sheet-back') { state.stock = null; state.chartTip = null; render(); return; }
      var tr = e.target.closest('tr[data-code]');
      if (tr && !e.target.closest('.sheet')) { state.stock = tr.getAttribute('data-code'); state.chartTip = null; render(); }
    });

    // 图表点击提示
    app.addEventListener('click', function (e) {
      var kc = e.target.closest ? e.target.closest('.kc') : null;
      if (kc) {
        var kr = kc.getBoundingClientRect();
        chartTipShow(Math.max(8, kr.left - 40), Math.max(8, kr.top - 4), kc.getAttribute('data-t'));
        return;
      }
      var pt = e.target.closest ? e.target.closest('.pt') : null;
      if (!pt) { chartTipHide(); return; }
      var i = pt.getAttribute('data-i'), v = pt.getAttribute('data-v');
      var rect = pt.getBoundingClientRect();
      chartTipShow(rect.left + window.scrollX, rect.top + window.scrollY - 30, pt.getAttribute('data-t') || ('第 ' + i + ' 点：' + v));
    });
    app.addEventListener('scroll', chartTipHide);
    window.addEventListener('scroll', chartTipHide, true);

    // 下拉刷新
    var startY = 0;
    function onStart(e) { startY = e.touches ? e.touches[0].clientY : e.clientY; }
    function onMove(e) {
      if (e.touches && e.touches.length > 1) { if (e.cancelable) e.preventDefault(); return; }   // 双指 → 不缩放
      if (state.loading) return;
      var y = e.touches ? e.touches[0].clientY : e.clientY;
      var d = y - startY;
      if (d > 0 && document.documentElement.scrollTop === 0 && document.body.scrollTop === 0) {
        e.preventDefault();
        var el = document.getElementById('nn-pull');
        if (!el) {
          el = document.createElement('div');
          el.id = 'nn-pull';
          document.body.insertBefore(el, document.body.firstChild);
        }
        el.textContent = '下拉刷新';
        if (d > 70) el.textContent = '释放刷新';
      }
    }
    function onEnd(e) {
      var el = document.getElementById('nn-pull');
      if (el) el.remove();
      if (state.loading) return;
      var y = e.changedTouches ? e.changedTouches[0].clientY : e.clientY;
      if (y - startY > 70) {
        state.loading = true;
        load().then(function () { state.loading = false; }).catch(function () { state.loading = false; });
      }
    }
    document.addEventListener('touchstart', onStart, { passive: false });
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('touchend', onEnd);

    // 禁止缩放：iOS Safari 不理会 user-scalable=no，要拦它自己的手势事件；双击放大靠拦第二次点按。
    if (!window.__nnNoZoom) {
      window.__nnNoZoom = true;
      ['gesturestart', 'gesturechange', 'gestureend'].forEach(function (name) {
        document.addEventListener(name, function (e) { e.preventDefault(); }, { passive: false });
      });
      var lastTap = 0, lastX = -99, lastY = -99;
      document.addEventListener('touchend', function (e) {
        var now = Date.now(), t = e.changedTouches && e.changedTouches[0];
        var x = t ? t.clientX : -99, y = t ? t.clientY : -99;
        // 只拦“同一个位置 300ms 内的第二下”（这才是双击放大）；在别处快速点下一下照常生效
        if (now - lastTap < 300 && Math.abs(x - lastX) < 25 && Math.abs(y - lastY) < 25 && e.cancelable) e.preventDefault();
        lastTap = now; lastX = x; lastY = y;
      }, { passive: false });
    }
  }

  // ------------------------------------------------------------------ 启动
  try {
    var pref = JSON.parse(ls(true, LS_PREF) || 'null');
    if (pref && typeof pref === 'object') {
      if (pref.pick && typeof pref.pick === 'object') ['signal', 'forward', 'holdings'].forEach(function (k) { if (typeof pref.pick[k] === 'string') pick[k] = pref.pick[k]; });
      if (pref.tab) state.tab = pref.tab;
      if (pref.search && typeof pref.search === 'object') state.search = pref.search;
      if (pref.forwardFilter) state.forwardFilter = pref.forwardFilter;
    }
  } catch (e) { /* 偏好坏了就用默认 */ }
  state.pick = pick;

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && state.phase === 'ready' && Date.now() - state.loadedAt > 10 * 60 * 1000) load();
  });
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) navigator.serviceWorker.register('sw.js').catch(function () { /* 没有也能用，只是没有离线外壳 */ });
  load();
})();