(function () {
  'use strict';

  var ENVELOPE_FORMAT = 'niuniu-mobile-envelope-v1';
  var SNAPSHOT_FORMAT = 'niuniu-mobile-snapshot-v1';
  var LS_PASS = 'niuniu_mobile_pass';
  var LS_PREF = 'niuniu_mobile_pref';
  var app = document.getElementById('app');

  var state = {
    phase: 'loading', snap: null, env: null, error: '', tab: 'today', loadedAt: 0,
    f: 'F1',                           // 「今天」按哪个组合排（F1 / F2）
    detail: null,                      // 「策略」页正在看哪一个（null = 列表）
    loading: false,                    // 下载/解密进行中
    offline: false,                    // 是否来自 Service Worker 离线缓存
    passVisible: false,                // 口令明文显示开关
    search: { signal: '', forward: '', holdings: '' }, // 各页搜索关键词
    forwardFilter: 'all',              // 前向记录状态筛选：all/waiting/open/closed
    chartTip: null,                    // 图表提示 {x, y, text}
    stock: null                        // 正在看走势的股票代码
  };

  var pick = { signal: 'fusion', forward: 'fusion', holdings: 'F1' };

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
    if (opt.log) {          // 对数纵轴：倍数跨好几个数量级时用；提示文字仍用原值（opt.tips）
      var f0 = opt.fmt || function (v) { return v.toFixed(2); };
      vals = vals.map(function (v) { return isNum(v) && v > 0 ? Math.log(v) / Math.LN10 : null; });
      opt = Object.assign({}, opt, { log: false, base: opt.base != null ? Math.log(opt.base) / Math.LN10 : null, fmt: function (x) { return f0(Math.pow(10, x)); } });
    }
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
        '<p class="small">按规则：下一个开盘日（' + md(o.plan_day) + '）开盘买、持有 20 个交易日。候选在「策略」里各本的详情，按你的资金算的买卖清单在「持仓」页。</p>';
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
  function viewSignal(s, only) {          // only：「策略」详情页只看这一本，不显示切换条
    var kind = only || state.pick.signal;
    if (s.kinds.indexOf(kind) < 0) kind = state.pick.signal = s.kinds[0];
    var sig = s.signals[kind] || {};
    var html = '';
    if (!only) {
      var open = s.kinds.filter(function (k) { return s.signals[k] && s.signals[k].gate_open; });
      var when = '<b>' + md(s.data_date) + ' 收盘时</b>';
      html += '<div class="banner ' + (open.length ? 'warn' : 'ok') + '">' +
        (open.length ? when + '有开仓信号：' + open.map(function (k) { return esc(s.labels[k]); }).join('、') : when + '没有任何一本触发开仓信号。空仓等待是正常状态。') + '</div>';
      html += chips('signal', s.kinds, function (k) { return shortLabel(s, k); }, kind, function (k) { return s.signals[k] && s.signals[k].gate_open; });
    }
    if (sig.error) return html + '<section class="card"><h2>' + esc(s.labels[kind]) + '</h2><p class="empty">这一本没算出来：' + esc(sig.error) + '</p></section>';

    var isFusion = !!sig.sleeves;
    html += '<section class="card"><h2>' + esc(only ? '最新的信号' : s.labels[kind]) + '<small>' + md(sig.date) + ' 收盘后</small></h2>';
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

  function viewForward(s, only) {
    var kind = only || state.pick.forward;
    if (s.kinds.indexOf(kind) < 0) kind = state.pick.forward = s.kinds[0];
    var f = s.forward[kind] || {};
    var html = '';
    if (!only) {
      html += '<div class="banner ok">前向跟踪 = 参数冻结后，每天把当天的信号记下来，之后用真实后续行情结算。只有这个数字才能说明策略在样本外是否有效；样本内回测不算。</div>';
      html += chips('forward', s.kinds, function (k) { return shortLabel(s, k); }, kind);
    }
    if (f.error) return html + '<section class="card"><h2>' + esc(s.labels[kind]) + '</h2><p class="empty">这一本没算出来：' + esc(f.error) + '</p></section>';
    var sm = f.summary || {};
    html += '<section class="card"><h2>' + esc(only ? '前向记录' : s.labels[kind]) + '<small>' + (f.start_date ? '从 ' + f.start_date + ' 开始记录' : '') + '</small></h2>';
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
    variants = variants.filter(function (k) { return k.charAt(0) === 'F'; }).concat(variants.filter(function (k) { return k.charAt(0) !== 'F'; }));   // F 放前面
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
      (p.f ? '<span>E6 那份（' + pct(p.f.w_e6, 0) + '）</span><span class="num">' + wan(p.f.e6_amount) + '</span><span>D4 那份（' + pct(p.f.w_d4, 0) + '），下面的清单按它算</span><span class="num">' + wan(p.f.d4_amount) + '</span>' : '') +
      '<span>持仓市值</span><span class="num">' + money(totalValue) + ' 元</span><span>总浮盈</span><span class="num ' + (totalPnlAmt >= 0 ? 'up' : 'down') + '">' + (totalPnlAmt >= 0 ? '+' : '') + money(totalPnlAmt) + ' 元</span></div>';
    (p.notes || []).forEach(function (t) { html += '<p class="small muted">· ' + esc(t) + '</p>'; });
    html += '</section>';

    // 搜索框
    var hk = state.search.holdings || '';
    var dispHoldings = hk ? filterRows(rows, hk, ['code', 'name', 'sleeve']) : rows;

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
      '<li><b>今天</b>是首页：按交易日的时间顺序排好今天（收盘后就是下一个交易日）要做的事，金额按你选的 F1～F4 和电脑上填的账户总资产算。</li>' +
      '<li><b>策略</b>：每个策略一行，点进去看规则、最新信号、回测曲线和前向记录。</li>' +
      '<li><b>持仓</b>：电脑上录入的持仓，和按所选策略算出的明天买卖清单。</li>' +
      '<li><b>市场</b>：现在的下跌恐慌程度、有没有信号、离触发还差多少、规则推演和历史类比、该盯什么，另有涨停板情绪。它只用策略自己的数据，不是预测。</li>' +
      '<li><b>只读、纸面</b>：不下单、不连券商；信号只是按规则算出来的“明天可以考虑什么”。</li>' +
      '<li><b>数据每天收盘后更新一次</b>：电脑上的牛牛算完推上来，数据日期在顶部。过了下一个开盘就是旧数据。</li>' +
      '<li><b>红涨绿跌</b>：红色是上涨 / 盈利，绿色是下跌 / 亏损。</li>' +
      '<li><b>数据是加密的</b>：服务器上只有密文，口令只在这台手机和电脑上。</li></ul></section>';
    html += '<section class="card"><h2>F 系列</h2><ul class="plain">' +
      '<li><b>F1</b> 30% E6 + 70% D4：总资产分两份，E6 那份照 E6 全仓一只票，D4 那份照 D4 的规则；每月第一个开市日把两份调回 30 : 70。</li>' +
      '<li><b>F2</b> 50% E6 + 50% D4：同上，比例 50 : 50。</li>' +
      '<li><b>F3</b>（候选）E6 加两个条件，全部钱全仓一只：E6 第 1 只所在的申万一级行业昨天没有别的涨停，并且昨收大盘 z 不在 −0.4～+0.6 的平稳段，才做。</li>' +
      '<li><b>F4</b>（候选）E6 只去掉平稳段，全部钱全仓一只：昨收大盘 z 不在 −0.4～+0.6 就做，不看行业。比 F3 信号多、近几年赚得多，回撤也大。</li>' +
      '<li><b>F5</b>（候选）F4 的日子，买法换成"涨幅 ≥ 7% 且 30 秒涨 ≥ 3 个点就提前挂涨停价"。这个买法在 2023–2026 年上找出来，2017–2022 年检验没通过（每天只多 +0.2%）。10-28 起卖法改成每天 14:50 看、没封住当时就卖。</li>' +
      '<li><b>F5-1</b>（候选）F5 + 持仓日开板放巨量就卖：此刻不在涨停、到这一分钟的累计量超过前几天同一分钟平均的 5 倍。门槛只在 7 笔上看过，只记前向。</li>' +
      '<li><b>F6</b>（检验没通过）F5 + 下单时别的昨日涨停至少 1 只封着才买。2017–2022 年上结果反过来，只作对照。</li></ul>' +
      '<p class="small muted">F1、F2：两者每天的涨跌几乎不相关（相关系数 0.08），E6 亏钱的年份 D4 多是赚的，所以合在一起回撤小很多；比例是看过 2010–2026 的回测后定的。' +
      'F3、F4 的条件也是在看过的回测上挑出来的，还没检验。都以 10-22 起的前向记录为准。</p></section>';
    html += '<section class="card"><h2>抄底策略</h2><ul class="plain">' +
      '<li><b>A</b> 大盘恐慌：全市场平均 z ≤ −1.5 时买“跌破布林下轨后收复”的股票。</li>' +
      '<li><b>B</b> 行业恐慌：某个申万一级行业 z ≤ −1.5 时，买该行业里同样形态的股票。</li>' +
      '<li><b>D</b> 三层合一：大盘（A）、成交额分档（C）、行业（B）三种恐慌各管一层，共用一笔钱。</li>' +
      '<li><b>D1</b> D 换成“离 60 日高点回撤最深优先”的候选排序。</li>' +
      '<li><b>D2</b> D1 加近高点过滤：大盘离近高点太近时不开新仓。</li>' +
      '<li><b>D3</b> D2 再把层优先级改成 C 先 A 后。</li>' +
      '<li><b>D4</b> D3 再加 B 层行业黑名单（房地产、国防军工）。</li></ul>' +
      '<p class="small muted">D2～D4 的回测数字都是样本内，真实表现要看“前向跟踪”。</p></section>';
    html += '<section class="card"><h2>E6 龙头扫板</h2><p>和上面的抄底策略无关，是“期末50分”那条打板研究线里检验通过的一条：每天只看昨天涨停股里开盘最强、身位最高的那一只，' +
      '盘中摸到涨停价就挂涨停价买，收盘封住就拿、没封住就卖。它在「策略」里，有前向记录、9:25 的提醒和下一个交易日的名单。</p></section>';
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
  function xmult(v) {      // 倍数：太大时用万 / 亿
    if (!isNum(v)) return '—';
    if (v >= 1e8) return (v / 1e8).toFixed(1) + ' 亿倍';
    if (v >= 1e4) return (v / 1e4).toFixed(1) + ' 万倍';
    return '×' + (v >= 100 ? v.toFixed(0) : v.toFixed(v >= 10 ? 1 : 2));
  }
  function e6Curve(c, title, log) {
    if (!c || !c.equity || c.equity.length < 2) return '';
    var t = c.total || {}, ym = function (d) { return String(d || '').slice(0, 7); };
    var p100 = function (v, d) { return isNum(v) ? pctc(v / 100, d == null ? 1 : d) : '—'; };
    var html = '<section class="card"><h2>' + esc(title || '历史账户曲线') + '<small>' + esc(ym(c.first)) + ' 至 ' + esc(ym(c.last)) + ' · 回测' + (log ? ' · 对数刻度' : '') + '</small></h2><div class="tiles">' +
      '<div class="tile"><span>累计</span><b>' + xmult(t.mult) + '</b></div>' +
      '<div class="tile"><span>年化</span><b>' + p100(t.cagr) + '</b></div>' +
      '<div class="tile"><span>最大回撤</span><b>' + p100(t.mdd) + '</b></div>' +
      '<div class="tile"><span>交易 / 每笔</span><b>' + esc(t.n) + ' / ' + p100(t.mean, 2) + '</b></div></div>' +
      chart(c.equity, c.dates.map(ym), { base: 1, log: !!log, label: title || 'E6 历史账户曲线', color: '#f6b72f', h: 150,
        fmt: function (v) { return v >= 1e8 ? (v / 1e8).toFixed(1) + '亿' : v >= 1e4 ? (v / 1e4).toFixed(1) + '万' : xmult(v); },   // 纵轴标签要短
        tips: c.dates.map(function (d, i) { return ym(d) + '：' + xmult(c.equity[i]); }) });
    var sg = c.segs || [];
    if (sg.length) {
      html += '<div class="scroll"><table class="tbl"><thead><tr><th>阶段</th><th class="n">交易</th><th class="n">每笔</th><th class="n">账户</th></tr></thead><tbody>' +
        sg.map(function (s) {
          var lb = String(s.label || ''), sp = lb.indexOf(' ');
          return '<tr><td>' + esc(sp > 0 ? lb.slice(0, sp) : lb) + (sp > 0 ? '<span class="nm">' + esc(lb.slice(sp + 1)) + '</span>' : '') + '</td><td class="n num">' + esc(s.n) +
            '</td><td class="n">' + p100(s.mean, 2) + '</td><td class="n num">' + xmult(s.mult) +
            (isNum(s.cagr) ? '<span class="nm">年化 ' + s.cagr.toFixed(1) + '%</span>' : '') + '<span class="nm">回撤 ' + (isNum(s.mdd) ? s.mdd.toFixed(1) + '%' : '—') + '</span></td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    var ys = c.years || [];
    if (ys.length) {
      html += '<h3 class="sub">每年</h3><div class="scroll"><table class="tbl"><thead><tr><th class="num">年</th><th class="n">交易</th><th class="n">每笔</th><th class="n">账户</th><th class="n">回撤</th></tr></thead><tbody>' +
        ys.slice().reverse().map(function (y) {
          return '<tr><td class="num">' + esc(y.year) + '</td><td class="n num">' + esc(y.n) + '</td><td class="n">' + p100(y.mean, 2) + '</td><td class="n">' + p100(y.acct) + '</td><td class="n">' + p100(y.mdd) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    return html + '<p class="small muted">' + esc(c.note || '') + ' 点曲线上的点看当月数值。10-20 起是前向记录，看下面几张表。</p></section>';
  }
  function e6Live(lv) {
    if (!lv || !lv.day) return '';
    var now = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);     // 北京时间的今天
    var old = lv.day !== now;
    var html = '<section class="card"><h2>今天的提醒<small>' + md(lv.day) + (old ? ' · 不是今天的，交易日 9:25 后更新' : '') + ' · 只提醒，不下单</small></h2>';
    if (lv.error) html += '<div class="banner warn">' + esc(lv.error) + '</div>';
    var o = lv.open;
    if (o && o.pick) {
      var p = o.pick;
      html += '<p class="small muted">' + esc(String(o.at || '').slice(11, 19)) + ' 按 9:25 开盘价排名（候选 ' + esc(o.n_cands) + ' 只，取到开盘价 ' + esc(o.n_quoted) + ' 只）' + (o.replay ? ' · 回放' : '') + '</p>' +
        '<div class="tiles"><div class="tile"><span>E6 第 1 只</span><b>' + esc(p.name || short(p.code)) + '</b></div>' +
        '<div class="tile"><span>涨停价</span><b class="num">' + (isNum(p.lim) ? p.lim.toFixed(2) : '—') + '</b></div>' +
        '<div class="tile"><span>开盘</span><b>' + (isNum(p.gap) ? pctc(p.gap / 100, 2) : '—') + '</b></div>' +
        '<div class="tile"><span>昨日连板</span><b>' + esc(p.streak_y) + ' 板</b></div></div>' +
        '<div class="banner ' + (o.skip ? 'warn' : 'ok') + '"><b>' + esc(o.action || '') + '</b></div>' +
        F_FILT.map(function (fid) {
          var g = o[fid.toLowerCase()];
          return g ? '<p class="small"><b>' + fid + '：</b>' + esc(g.action || g.error || '') + (g.error ? '' : '　' + f3Facts(g)) + '</p>' : '';
        }).join('');
      if (!o.skip) {
        html += '<p class="small">同花顺云条件单：选按股价触发的条件单，股票 ' + esc(short(p.code)) + '，条件"最新价 ≥ ' + (isNum(p.lim) ? p.lim.toFixed(2) : '涨停价') +
          '"，委托价 ' + (isNum(p.lim) ? p.lim.toFixed(2) : '涨停价') + '（涨停价），数量用全部可用资金（全仓一只），有效期当天。具体菜单名以 App 为准。没碰到涨停价就不会买，今天就没交易。</p>';
      }
      var top = o.top || [];
      if (top.length > 1) {
        html += '<div class="scroll"><table class="tbl"><thead><tr><th class="n">名次</th><th>股票</th><th class="n">开盘</th><th class="n">昨日</th></tr></thead><tbody>' +
          top.map(function (r) {
            return '<tr' + rowCode(r.code) + '><td class="n num">' + esc(r.rk) + '</td><td>' + esc(r.name || short(r.code)) + (r.open_lim ? ' <span class="tag off">开盘涨停</span>' : '') +
              '</td><td class="n">' + (isNum(r.gap) ? pctc(r.gap / 100, 1) : '—') + '</td><td class="n num">' + esc(r.streak_y) + ' 板</td></tr>';
          }).join('') + '</tbody></table></div>';
      }
    } else if (!lv.error) {
      html += '<p class="empty">9:25 的名单还没出来（交易日 9:25:30 左右更新）。</p>';
    }
    var c = lv.close;
    if (c) {
      var hs = c.holdings || [];
      html += '<h3 class="sub">14:50 持仓<small class="muted"> ' + esc(String(c.at || '').slice(11, 16)) + '，按前向记录、全仓一只票的口径</small></h3>';
      html += hs.length ? '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th class="n">现在</th><th>怎么办</th></tr></thead><tbody>' +
        hs.map(function (h) {
          return '<tr' + rowCode(h.code) + '><td>' + esc(h.name || short(h.code)) + '<span class="nm">' + md(h.buy) + ' 买 · 第 ' + esc(h.n) + ' 天</span></td><td class="n">' +
            (isNum(h.chg) ? pctc(h.chg / 100, 1) : '—') + '</td><td class="wrap small">' + (h.sealed ? '<span class="tag open">封住</span> ' : '') + esc(h.action) + '</td></tr>';
        }).join('') + '</tbody></table></div>' : '<p class="empty">E6 现在没有持仓，不用卖。</p>';
      F_FILT.forEach(function (fid) {      // F3 / F4 自己的全仓账户拿着、E6 没拿的那只
        var h3 = (c[fid.toLowerCase() + '_holdings'] || [])[0];
        if (h3 && !hs.some(function (h) { return h.code === h3.code; })) {
          html += '<p class="small"><b>' + fid + ' 持仓 ' + esc(h3.name || short(h3.code)) + '</b>（' + md(h3.buy) + ' 买 · 第 ' + esc(h3.n) + ' 天）：' + (h3.sealed ? '<span class="tag open">封住</span> ' : '') + esc(h3.action) + '</p>';
        }
      });
    }
    return html + '</section>';
  }
  function e6Curves(c) {
    if (!c) return '';
    // 默认全仓一只票（用户 10-20 定），放前面；1/6 资金那条作对照
    return (c.full ? e6Curve(Object.assign({}, c.full, { first: c.first, last: c.last }), '账户曲线 · 全仓一只票（默认）', true) : '') +
      e6Curve(c, '账户曲线 · 每个信号 1/6 资金（对照）', false);
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
    // 0. 今天 9:25 / 14:50 的提醒
    html += e6Live(e.live);
    // 1. 明天怎么做
    var nx = e.next || {};
    html += '<section class="card"><h2>下一个交易日怎么做<small>按 ' + md(nx.day) + ' 收盘</small></h2>' +
      '<p><b>E6 龙头扫板</b>：开盘后，把昨天涨停的主板非 ST 股按“开盘涨幅名次 + 昨日连板名次”打分，取第 1。开盘就涨停的不做；' +
      '盘中第一次摸到涨停价，<b>3 秒内</b>挂涨停价买。收盘还封住就拿，第一次没封住那天收盘卖，最多拿 5 天。' +
      '交易日 9:25:30 左右，最上面的“今天的提醒”会给出第 1 只和云条件单怎么设，14:50 再看持仓。</p>';
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
    html += e6Curves(e.curve);
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

  // ------------------------------------------------------------------ 「今天」：交易日时间轴（2026-10-21 重新设计的首页）
  var F_IDS = ['F1', 'F2', 'F3', 'F4', 'F5', 'F5-1', 'F6'], F_FILT = ['F3', 'F4', 'F5', 'F5-1', 'F6'];
  function isFilt(d) { return !!d && d.kind === 'e6_filter'; }   // F3 / F4 / F5：E6 全仓一只票再加条件（候选），没有 D4 那份、不调仓
  function isSpeed(d) { return !!(d && d.buy && d.buy.kind === 'speed'); }   // F5（10-23）：日子同 F4，买法换成 30 秒涨速提前挂涨停价
  function speedTxt(d) {
    var b = (d && d.buy) || {};
    return '涨幅 ≥ ' + Math.round((b.lv || 0.07) * 100) + '% 且最近 ' + (b.w || 30) + ' 秒涨了 ≥ ' + Math.round((b.sp || 0.03) * 100) + ' 个点';
  }
  function isPeer(d) { return !!(d && d.peer); }   // F6（10-27）：F5 + 下单那一刻别的昨日涨停一只都没封就不买
  var PEER_TXT = '下单前看一眼涨停池：昨天涨停的那些票（不算它自己）此刻至少还有 1 只封在涨停价才买，一只都没有就不买';
  function fKey(d) { return String(d.id || '').toLowerCase(); }   // 快照里各自的字段：open.f3、close.f3_holdings、forward.f3_holding…
  function isVol(d) { return !!(d && d.exit && d.exit.kind === 'vol_ratio'); }   // F5-1（10-29）：F5 + 持仓日开板放巨量就卖
  function liveKey(d) { return d && d.base ? String(d.base).toLowerCase() : fKey(d); }   // 9:25 的买入提醒：F5-1 买法同 F5，用 open.f5
  function volTxt(d) {
    var x = (d && d.exit && d.exit.x) || 5;
    return '此刻价格不在涨停价，并且从 9:25 竞价起到这一分钟的累计成交量超过前 5 个交易日（去掉一字板和缩量日）到同一分钟累计量平均的 ' + x + ' 倍';
  }
  function useInd(d) { return !!(d && d.cond && d.cond.max_other != null); }   // F3 看行业（条件①），F4 不看
  function condTxt(d) { return (useInd(d) ? '它所在行业昨天没有别的涨停、' : '') + '昨收大盘 z 不在平稳段'; }
  // 预览用：网址带 ?now=2026-10-22T10:05 就当成北京时间那一刻（只影响「今天」的时间轴，方便在电脑上核对各个时段的样子）
  var NOW_FAKE = (function () { var m = /[?&]now=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/.exec(location.search || ''); return m ? Date.parse(m[1] + ':00Z') : null; })();
  function bjNow() { return new Date(NOW_FAKE != null && isFinite(NOW_FAKE) ? NOW_FAKE : Date.now() + 8 * 3600000); }   // 取 getUTC* 就是北京时间
  function bjToday() { return bjNow().toISOString().slice(0, 10); }
  function bjMin() { var t = bjNow(); return t.getUTCHours() * 60 + t.getUTCMinutes(); }
  function hm(m) { return ('0' + Math.floor(m / 60)).slice(-2) + ':' + ('0' + (m % 60)).slice(-2); }
  function wan(x) { return isNum(x) ? (x / 1e4).toFixed(1) + ' 万' : '—'; }
  function ym(d) { return String(d || '').slice(0, 7); }
  function fDefs(s) { return s.f && !s.f.error && s.f.defs ? s.f.defs : []; }
  function fDef(s, id) {
    var ds = fDefs(s), want = id || state.f;
    for (var i = 0; i < ds.length; i++) if (ds[i].id === want) return ds[i];
    return id ? null : (ds[0] || null);
  }
  function fSwitch(s) {
    var ds = fDefs(s), cur = fDef(s);
    if (ds.length < 2 || !cur) return '';
    return '<div class="seg' + (ds.length > 2 ? ' n' + Math.min(ds.length, 7) : '') + '" role="group" aria-label="按哪个策略排">' + ds.map(function (d) {
      return '<button data-f="' + esc(d.id) + '" aria-pressed="' + (d.id === cur.id) + '">' + esc(d.id) + '</button>';
    }).join('') + '</div>';
  }
  function allocBar(s, d, noName) {
    var f = s.f;
    if (!f) return '<p class="empty">还没有策略 F 的数据：台式机每个交易日 19:30 算一次，算完会推上来。</p>';
    if (f.error) return '<div class="banner warn">策略 F 读不出来：' + esc(f.error) + '</div>';
    if (!d) return '';
    if (isFilt(d)) {
      return '<div class="alloc">' +
        '<div class="alloc-row"><span>总资产 <b class="num">' + wan(f.equity) + '</b></span>' + (noName ? '' : '<span class="muted small">' + esc(d.name || d.id) + '</span>') + '</div>' +
        '<svg class="alloc-bar" viewBox="0 0 300 8" preserveAspectRatio="none" aria-hidden="true"><rect class="a-e6" x="0" y="0" width="300" height="8"/></svg>' +
        '<div class="alloc-row small"><span><i class="sw sw-e6"></i>全部钱按 ' + esc(d.id) + ' 做（全仓一只） <b class="num">' + wan(d.e6_amount) + '</b></span><span class="tag off">候选</span></div></div>';
    }
    var W = 300, x = Math.round(W * d.w_e6);
    return '<div class="alloc">' +
      '<div class="alloc-row"><span>总资产 <b class="num">' + wan(f.equity) + '</b></span>' + (noName ? '' : '<span class="muted small">' + esc(d.name || d.id) + '</span>') + '</div>' +
      '<svg class="alloc-bar" viewBox="0 0 ' + W + ' 8" preserveAspectRatio="none" aria-hidden="true"><rect class="a-e6" x="0" y="0" width="' + x + '" height="8"/>' +
      '<rect class="a-d4" x="' + (x + 2) + '" y="0" width="' + Math.max(0, W - x - 2) + '" height="8"/></svg>' +
      '<div class="alloc-row small"><span><i class="sw sw-e6"></i>E6 那份 ' + pct(d.w_e6, 0) + ' <b class="num">' + wan(d.e6_amount) + '</b></span>' +
      '<span><i class="sw sw-d4"></i>D4 那份 ' + pct(d.w_d4, 0) + ' <b class="num">' + wan(d.d4_amount) + '</b></span></div></div>';
  }
  function e6HoldNow(s) {
    // E6 那份现在拿着的票：今天 14:50 查过就用那次的；否则 9:25 记下的；否则 F 的前向记录（截至最近收盘）
    var lv = (s.e6 || {}).live || {}, day = s.plan_day;
    if (lv.day === day && lv.close) return (lv.close.holdings || [])[0] || null;
    if (lv.day === day && lv.open && lv.open.pick) return lv.open.holding || null;
    return (s.f && s.f.forward && s.f.forward.e6_holding) || null;
  }
  function names4(rows) {
    return rows.slice(0, 4).map(function (r) { return esc(r.name || short(r.code)); }).join('、') + (rows.length > 4 ? ' 等 ' + rows.length + ' 只' : '');
  }
  // ---- F3 / F4 的「今天」：只有 E6 那一条线，再加条件
  function filtHold(s, d) {
    // F3 / F4 自己的全仓账户拿着的票：今天 14:50 查过就用那次的；否则 9:25 记下的；否则 F 的前向记录（截至最近收盘）
    var lv = (s.e6 || {}).live || {}, day = s.plan_day, k = fKey(d);
    if (lv.day === day && lv.close && lv.close[k + '_holdings']) return lv.close[k + '_holdings'][0] || null;
    if (lv.day === day && lv.open && lv.open[k] && !lv.open[k].error) return lv.open[k].holding || null;
    return (s.f && s.f.forward && s.f.forward[k + '_holding']) || null;
  }
  function f3Facts(g) {
    if (!g) return '';
    var a = [];
    if (g.ind) a.push(esc(g.ind) + '：同行业昨天别的涨停 ' + esc(g.n_other == null ? '—' : g.n_other) + ' 只');
    if (isNum(g.z)) a.push('昨收大盘 z ' + num(g.z, 2) + (g.calm ? '（平稳段）' : ''));
    return a.length ? '<span class="small muted">' + a.join('；') + '</span>' : '';
  }
  function todayItemsFilt(s, d) {
    var day = s.plan_day, lv = (s.e6 || {}).live || {}, live = lv.day === day, items = [], c3 = d.cond || {}, id = esc(d.id), k = fKey(d), lk = liveKey(d);
    var pr = lv.prep && lv.prep.day === day ? lv.prep : null, g0 = pr && pr.f3 ? pr.f3 : null;      // 08:40 按天的那部分（z），F3 / F4 共用
    var zline = g0 && !g0.error && isNum(g0.z) ? '昨收大盘 z ' + num(g0.z, 2) + '：' + (g0.calm ? '在平稳段（' + num(c3.z_lo, 1) + '～+' + num(c3.z_hi, 1) + '），' + id + ' 今天不做。' : '不在平稳段，今天可以做。') :
      (g0 && g0.error ? id + ' 的条件没算出来：' + esc(g0.error) : '');
    items.push({ m: 520, t: '08:40', tone: 'e6', title: pr ? (pr.error ? 'E6 候选没准备好' : 'E6 候选 ' + esc(pr.n) + ' 只，' + id + ' 条件已算') : 'E6 准备候选、算 ' + id + ' 条件',
      body: pr && pr.error ? esc(pr.error) : (zline || (useInd(d) ? '台式机列出昨天涨停的主板非 ST 股，并算好每只所在行业昨天还有几只别的涨停、昨收大盘 z。' : '台式机列出昨天涨停的主板非 ST 股，并算好昨收大盘 z。')) });
    var o = live ? lv.open : null, hold = filtHold(s, d), it = { m: 565, t: '09:25', tone: 'e6' };
    if (live && lv.error && !(o && o.pick)) { it.title = 'E6 名单没算出来'; it.body = esc(lv.error); }
    else if (o && o.pick) {
      var p = o.pick, g = o[lk] || {}, lim = isNum(p.lim) ? p.lim.toFixed(2) : '涨停价';
      it.title = id + '：' + esc(p.name || short(p.code));
      if (!o[lk]) it.body = '这次 9:25 的提醒还没算 ' + id + '（台式机程序是旧的），按条件自己判断：' + condTxt(d) + '。';
      else if (g.error || g.skip) it.body = esc(g.action || g.error || '今天不做') + '<br>' + f3Facts(g);
      else if (isSpeed(d)) {
        var sp = g.speed || {};
        it.act = true;
        it.body = '开盘 ' + (isNum(p.gap) ? pctc(p.gap / 100, 2) : '—') + '，昨天 ' + esc(p.streak_y) + ' 板；昨收大盘 z 不在平稳段。<b>盯盘</b>：摸到涨停之前，' +
          '价格 ≥ <b class="num">' + (isNum(sp.px7) ? sp.px7.toFixed(2) : '涨 7%') + '</b> 并且最近 30 秒涨了 ≥ <b class="num">' + (isNum(sp.d30) ? sp.d30.toFixed(2) + ' 元' : '3 个点') + '</b>（3 个点）' +
          '→ 马上以 <b class="num">' + lim + '</b> 挂买单，全部可用资金。一直没出现，就照 F4 等摸到涨停价再挂——可以先设好这张云条件单兜底：' +
          '<div class="order kv"><span>股票</span><span>' + esc(p.name || '') + ' <span class="num">' + esc(short(p.code)) + '</span></span>' +
          '<span>触发</span><span class="num">最新价 ≥ ' + lim + '</span><span>委托价</span><span class="num">' + lim + '（涨停价）</span>' +
          '<span>金额</span><span class="num">全部可用资金（' + id + ' 全仓一只）</span><span>有效期</span><span>当天</span></div>' +
          '<span class="small muted">同花顺云条件单设不了"30 秒涨 3 个点"，提前那一下要自己看盘或用程序。</span>' +
          (isPeer(d) ? '<div class="banner warn small">' + id + ' 多一条：' + PEER_TXT + '（兜底的云条件单也一样，触发前先看）。</div>' : '') + f3Facts(g);
      }
      else {
        it.act = true;
        it.body = '开盘 ' + (isNum(p.gap) ? pctc(p.gap / 100, 2) : '—') + '，昨天 ' + esc(p.streak_y) + ' 板；' + (useInd(d) ? '两个条件都满足' : '昨收大盘 z 不在平稳段') + '。设一张云条件单：' +
          '<div class="order kv"><span>股票</span><span>' + esc(p.name || '') + ' <span class="num">' + esc(short(p.code)) + '</span></span>' +
          '<span>触发</span><span class="num">最新价 ≥ ' + lim + '</span><span>委托价</span><span class="num">' + lim + '（涨停价）</span>' +
          '<span>金额</span><span class="num">全部可用资金（' + id + ' 全仓一只）</span><span>有效期</span><span>当天</span></div>' + f3Facts(g);
      }
    } else {
      it.title = id + '：看 E6 第 1 只';
      it.body = hold ? id + ' 还拿着 ' + esc(hold.name || short(hold.code)) + '，今天的信号跳过。' :
        '9:25:30 左右出来。E6 第 1 只开盘没涨停、' + condTxt(d) + '，' + (useInd(d) ? '三条' : '两条') + '都满足才' +
        (isSpeed(d) ? '买：盘中一旦' + speedTxt(d) + '就挂涨停价，没出现就摸板再挂' : '设云条件单') + '，金额用全部可用资金。' +
        (isPeer(d) ? '另外，' + PEER_TXT + '。' : '');
    }
    items.push(it);
    var c = live ? lv.close : null, e = { m: 890, t: '14:50', tone: 'e6' };
    if (c && c[k + '_holdings']) {
      var hs = c[k + '_holdings'];
      e.title = hs.length ? id + ' 持仓：' + esc(hs[0].name || short(hs[0].code)) : id + ' 没有持仓';
      e.body = hs.length ? (hs[0].sealed ? '<span class="tag open">封住</span> ' : '<span class="tag sell">没封住</span> ') + esc(hs[0].action) : '不用卖。';
      e.act = !!(hs.length && !hs[0].sealed);
    } else if (hold) {
      e.title = '看 ' + id + ' 持仓封没封住';
      e.body = esc(hold.name || short(hold.code)) + '：14:50 还封在涨停就接着拿（最多 5 天），没封住就收盘前卖。' +
        (isVol(d) ? '另外盘中一旦' + volTxt(d) + '，就马上卖（现在没有这条的提醒，要自己看量）。' : '');
    } else {
      e.title = id + ' 持仓';
      e.body = '现在没有持仓。早上买到的当天不卖，下一个交易日 14:50 再看。';
    }
    items.push(e);
    items.push({ m: 1140, t: '19:00', tone: 'sys', title: '收盘后更新', body: isSpeed(d) ?
      '记 E6 前向记录，推上下一个交易日的计划。' + id + ' 有没有提前买到、价钱多少，要等当天的逐笔数据下下来才补算。' :
      '记 E6 前向记录；19:30 按其中符合 ' + id + ' 条件的信号记 ' + id + ' 的全仓账户，推上下一个交易日的计划。' });
    return items.sort(function (x, y) { return x.m - y.m; });
  }
  function todayItems(s, d) {
    if (isFilt(d)) return todayItemsFilt(s, d);
    var day = s.plan_day, lv = (s.e6 || {}).live || {}, live = lv.day === day;
    var plan = ((s.holdings || {}).plans || {})[d ? d.id : 'D4'] || {};
    var amt = d ? '约 ' + wan(d.e6_amount) + '（E6 那份）' : '全部可用资金';
    var rb = s.f && !s.f.error ? s.f.rebalance : null, items = [];
    if (d && rb && rb.on_plan_day) {
      items.push({ m: 540, t: '开盘前', tone: 'f', act: true, title: '月初调仓：两份调回 ' + pct(d.w_e6, 0) + ' : ' + pct(d.w_d4, 0),
        body: 'E6 那份定为 <b class="num">' + wan(d.e6_amount) + '</b>，D4 那份 <b class="num">' + wan(d.d4_amount) + '</b>。已有的持仓不用卖，从今天起两边的新仓按新金额算。' });
    }
    var pr = lv.prep && lv.prep.day === day ? lv.prep : null;
    items.push({ m: 520, t: '08:40', tone: 'e6', title: pr ? (pr.error ? 'E6 候选没准备好' : 'E6 候选 ' + esc(pr.n) + ' 只') : 'E6 准备候选',
      body: pr ? (pr.error ? esc(pr.error) : md(pr.prev) + ' 收盘涨停的主板非 ST 股，9:25 按开盘价排名。') : '台式机自动列出昨天涨停的主板非 ST 股。' });
    var o = live ? lv.open : null, hold = e6HoldNow(s), it = { m: 565, t: '09:25', tone: 'e6' };
    if (live && lv.error && !(o && o.pick)) { it.title = 'E6 名单没算出来'; it.body = esc(lv.error); }
    else if (o && o.pick) {
      var p = o.pick, lim = isNum(p.lim) ? p.lim.toFixed(2) : '涨停价';
      it.title = 'E6 第 1 只：' + esc(p.name || short(p.code));
      if (o.skip) it.body = esc(o.action || '今天不做');
      else {
        it.act = true;
        it.body = '开盘 ' + (isNum(p.gap) ? pctc(p.gap / 100, 2) : '—') + '，昨天 ' + esc(p.streak_y) + ' 板。设一张云条件单：' +
          '<div class="order kv"><span>股票</span><span>' + esc(p.name || '') + ' <span class="num">' + esc(short(p.code)) + '</span></span>' +
          '<span>触发</span><span class="num">最新价 ≥ ' + lim + '</span><span>委托价</span><span class="num">' + lim + '（涨停价）</span>' +
          '<span>金额</span><span class="num">' + amt + '</span><span>有效期</span><span>当天</span></div>' +
          '<span class="small">没摸到涨停价就不会买，今天 E6 就没有交易。</span>';
      }
    } else {
      it.title = 'E6 第 1 只';
      it.body = hold ? 'E6 那份还拿着 ' + esc(hold.name || short(hold.code)) + '，今天的信号跳过。' :
        '9:25:30 左右出来。第 1 只开盘就涨停的当天不做；没涨停就设云条件单，金额' + amt + '。';
    }
    items.push(it);
    var sells = plan.sells || [], buys = plan.buys || [];
    var openSells = sells.filter(function (r) { return r.status === 'overdue'; }), closeSells = sells.filter(function (r) { return r.status !== 'overdue'; });
    var b = { m: 570, t: '09:30', tone: 'd4' };
    if (plan.error) { b.title = 'D4 清单没算出来'; b.body = esc(plan.error); }
    else if (plan.stale) { b.title = 'D4 清单过期了'; b.body = '数据还没更新到最新，先不要照着买。'; }
    else if (buys.length || openSells.length) {
      b.act = true;
      b.title = 'D4 开盘' + (buys.length ? '买 ' + buys.length + ' 只' : '') + (buys.length && openSells.length ? '、' : '') + (openSells.length ? '卖 ' + openSells.length + ' 只' : '');
      b.body = (buys.length ? '买 ' + names4(buys) + '，合计约 <b class="num">' + money(plan.new_money) + '</b> 元。' : '') +
        (openSells.length ? '卖（已到期）' + names4(openSells) + '。' : '') + ' <button class="link" data-go="holdings">看清单</button>';
    } else {
      b.title = 'D4 开盘不用动';
      b.body = plan.gate_open ? '闸门开着，但没有要买的（名额满或买不起一手）。' : '闸门没开，不开新仓。';
    }
    items.push(b);
    var c = live ? lv.close : null, e = { m: 890, t: '14:50', tone: 'e6' };
    if (c) {
      var hs = c.holdings || [];
      e.title = hs.length ? 'E6 持仓：' + esc(hs[0].name || short(hs[0].code)) : 'E6 没有持仓';
      e.body = hs.length ? (hs[0].sealed ? '<span class="tag open">封住</span> ' : '<span class="tag sell">没封住</span> ') + esc(hs[0].action) : '不用卖。';
      e.act = !!(hs.length && !hs[0].sealed);
    } else if (hold) {
      e.title = '看 E6 持仓封没封住';
      e.body = esc(hold.name || short(hold.code)) + '：14:50 还封在涨停就接着拿（最多 5 天），没封住就收盘前卖。';
    } else {
      e.title = 'E6 持仓';
      e.body = '现在没有持仓。早上买到的当天不卖，下一个交易日 14:50 再看。';
    }
    items.push(e);
    if (closeSells.length) items.push({ m: 895, t: '14:55', tone: 'd4', act: true, title: 'D4 收盘前卖 ' + closeSells.length + ' 只', body: names4(closeSells) + '：拿满 20 个交易日，收盘前卖出。' });
    items.push({ m: 1140, t: '19:00', tone: 'sys', title: '收盘后更新', body: '记 E6 和 F 的前向记录，推上下一个交易日的计划。' });
    return items.sort(function (x, y) { return x.m - y.m; });
  }
  function nowLine(mode, now) {
    var label = mode === 'stale' ? '这份计划已经过期' : mode === 'ahead' ? '现在，下面是下一个交易日的安排' : now >= 900 ? '现在，已收盘' : now < 555 ? '现在，还没开盘' : '现在';
    return '<li class="tl-now"><time class="num">' + (mode === 'stale' ? '' : hm(now)) + '</time><span>' + label + '</span></li>';
  }
  // 首页顶部一条实盘状态（数据来自本机 auto_trade.py，经服务器隧道取）
  function liveStrip() {
    if (!liveTrade.loaded) { fetchLiveTrade().then(function () { if (!state.detail) render(); }); return ''; }
    var t = liveTrade.data || {};
    if (liveTrade.error) return '<section class="card tight"><div class="banner warn small">实盘状态取不到：' + esc(liveTrade.error) + '</div></section>';
    var modeTxt = { stopped: '已停止', observe: '观察模式', live: '实盘模式', handoff: '等待人工确认' };
    var chip = t.running ? '● 实盘运行中' : '○ 实盘未运行';
    var txt = (t.step || '') + (t.position ? '｜持仓 ' + (t.position.name || t.position.code) + '×' + t.position.quantity : '');
    return '<section class="card tight"><div class="banner ' + (t.running ? 'ok' : 'warn') + ' small"><b>' + chip + '</b> — ' +
      esc(modeTxt[t.mode] || t.mode || '') + (txt ? '｜' + esc(txt) : '') + '</div></section>';
  }

  function viewToday(s) {
    var d = fDef(s), day = s.plan_day, today = bjToday(), now = bjMin();
    var mode = day === today ? 'today' : day > today ? 'ahead' : 'stale';
    var html = liveStrip() + '<section class="hero"><div class="hero-day"><span class="hero-k">' + (mode === 'today' ? '今天' : mode === 'ahead' ? '下一个交易日' : '计划日') + '</span>' +
      '<b class="num">' + esc(md(day)) + '</b><span>' + esc(wd(day)) + '</span></div>' + fSwitch(s) + '</section>';
    html += allocBar(s, d);
    var items = todayItems(s, d), k = -1;
    if (mode === 'today') items.forEach(function (x, i) { if (now >= x.m) k = i; });
    html += '<ol class="tl">';
    if (k < 0) html += nowLine(mode, now);
    items.forEach(function (x, i) {
      var cls = mode !== 'today' ? 'is-next' : i < k ? 'is-past' : i === k ? 'is-now' : 'is-next';
      html += '<li class="tl-i ' + cls + (x.act ? ' is-act' : '') + ' t-' + x.tone + '"><time class="num">' + esc(x.t) + '</time><div class="tl-b"><b>' + x.title + '</b>' +
        (x.body ? '<div class="tl-d">' + x.body + '</div>' : '') + '</div></li>';
      if (i === k) html += nowLine(mode, now);
    });
    html += '</ol>';
    var rb = s.f && !s.f.error ? s.f.rebalance : null;
    html += '<p class="small muted foot">' + (rb && !rb.on_plan_day && d && !isFilt(d) ? '下次调仓 ' + esc(md(rb.next)) + '（' + esc(wd(rb.next)) + '），两份调回 ' + pct(d.w_e6, 0) + ' : ' + pct(d.w_d4, 0) + '。' : '') +
      '只提醒，不下单；金额按电脑上填的账户总资产算。' + (d ? ' <button class="link" data-open="' + esc(d.id) + '">' + esc(d.id) + ' 的规则和回测</button>' : '') + '</p>';
    return html;
  }

  // ------------------------------------------------------------------ 「策略」：列表 + 详情
  var KIND_DESC = { fusion: 'A、C、B 三层恐慌合一，共用一笔钱', fusion1: 'D 换成离 60 日高点回撤最深的优先', fusion2: 'D1 加近高点过滤', fusion3: 'D2 改成 C 层优先',
                    fusion4: 'D3 加 B 层行业黑名单', market: '全市场恐慌时买跌破布林下轨后收复的', industry: '某个行业恐慌时买这个行业里的' };
  function sRow(id, title, sub, right, right2) {
    return '<button class="row" data-open="' + esc(id) + '"><span class="r-t"><b>' + title + '</b>' + (sub ? '<span>' + sub + '</span>' : '') + '</span>' +
      '<span class="r-v">' + (right || '') + (right2 ? '<span>' + right2 + '</span>' : '') + '</span><span class="chev" aria-hidden="true">›</span></button>';
  }
  function sGroup(title, rows, empty) {
    return '<section class="group">' + (title ? '<h2>' + esc(title) + '</h2>' : '') + '<div class="list">' + (rows.length ? rows.join('') : '<p class="empty pad">' + esc(empty || '') + '</p>') + '</div></section>';
  }
  function viewStrategies(s) {
    var html = sGroup('F 系列', fDefs(s).map(function (d) {
      var t = (d.backtest || {}).total || {};
      return sRow(d.id, esc(d.name || d.id), isFilt(d) ? (isVol(d) ? 'F5 + 持仓日开板放巨量就卖' : isPeer(d) ? 'F5 + 下单时别的昨日涨停至少 1 只封着' : isSpeed(d) ? 'F4 的日子，30 秒涨速提前挂涨停价' : useInd(d) ? 'E6 加两个条件' : 'E6 只去掉大盘平稳段') +
        (isVol(d) ? '，全仓一只；放量门槛只在 7 笔上看过，只记前向' : isPeer(d) ? '，全仓一只；2017–2022 检验没通过，只作对照' : isSpeed(d) ? '，全仓一只；涨速买法 2017–2022 检验没通过，只记前向' : '，全仓一只；还没检验，只记前向') : '每月第一个开市日调回比例',
        (isSpeed(d) ? '回测（' + esc(String((d.backtest || {}).first || '').slice(0, 4)) + ' 起）年化 ' : '回测年化 ') + pct(t.cagr, 0), '最大回撤 ' + pct(t.mdd, 0));
    }), s.f && s.f.error ? '策略 F 读不出来：' + s.f.error : '还没有策略 F 的数据（台式机每个交易日 19:30 算）。');
    html += sGroup('抄底', s.kinds.map(function (k) {
      var sg = s.signals[k] || {}, fw = s.forward[k] || {}, c = fw.portfolio && fw.portfolio.curve, last = c ? c.equity.filter(isNum).slice(-1)[0] : null;
      return sRow(k, esc(s.labels[k] || k), esc(KIND_DESC[k] || ''),
        sg.error ? '<span class="tag off">没算出来</span>' : sg.gate_open ? '<span class="tag open">有信号</span>' : '<span class="tag off">没信号</span>',
        isNum(last) ? '前向 ' + pct(last - 1, 1, true) : '');
    }));
    var e = s.e6 || {}, sm = (e.summary || []).filter(function (r) { return r.rule === 'E6'; })[0] || {};
    html += sGroup('打板', [sRow('e6', 'E6 龙头扫板', '打分第 1、盘中摸板就买、封住就拿', e.error ? '<span class="tag off">读不出来</span>' : '', '前向做了 ' + esc(sm.n_done || 0) + ' 次')]);
    html += sGroup('', [sRow('guide', '说明', '怎么看这个页面、每个策略是什么', '', '')]);
    return html;
  }
  function viewF(s, id) {
    var f = s.f;
    if (!f || f.error) return '<section class="card"><h2>' + esc(id) + '</h2><p class="empty">' + (f && f.error ? '读不出来：' + esc(f.error) : '还没有策略 F 的数据：台式机每个交易日 19:30 算一次。') + '</p></section>';
    var d = fDef(s, id);
    if (!d) return '<p class="empty">没有 ' + esc(id) + '。</p>';
    if (isFilt(d)) return viewFilt(s, d);
    var bt = d.backtest || {}, t = bt.total || {}, rb = f.rebalance || {}, fb = f.backtest || {};
    var html = '<section class="card"><h2>' + esc(d.name) + '</h2>' + allocBar(s, d, true) +
      '<ul class="plain small"><li><b>E6 那份</b>：照 E6 全仓一只票。9:25 打分第 1 开盘没涨停就设云条件单，摸到涨停价按涨停价买，金额用这一份；收盘封住就拿，没封住当天卖，最多 5 天。</li>' +
      '<li><b>D4 那份</b>：照 D4 的规则，只是每只的权重按这一份的钱算；买卖清单在「持仓」页选 ' + esc(d.id) + '。</li>' +
      '<li><b>调仓</b>：' + esc(rb.rule || '每月第一个开市日') + '把两份调回 ' + pct(d.w_e6, 0) + ' : ' + pct(d.w_d4, 0) + '，下次 ' + esc(md(rb.next)) + '（' + esc(wd(rb.next)) + '）。已有持仓不用卖，新开仓按新的金额。</li></ul></section>';
    var fw = f.forward || {}, ser = (fw.series || {})[id] || [];
    html += '<section class="card"><h2>前向记录<small>' + esc(md(fw.start)) + ' 收盘为起点</small></h2>';
    if ((fw.dates || []).length >= 2 && ser.length >= 2) {
      html += '<div class="tiles"><div class="tile"><span>累计</span><b>' + pctc(ser[ser.length - 1] - 1, 1) + '</b></div><div class="tile"><span>最大回撤</span><b>' + pctc(maxDrawdown(ser), 1) + '</b></div></div>' +
        chart(ser, fw.dates.map(md), { base: 1, label: id + ' 前向记录', h: 120 });
    } else {
      html += '<p class="empty">' + esc(fw.note || '从下一个交易日起记录。') + '</p>';
    }
    html += '<p class="small muted">E6 那份用 E6 的前向记录（全仓一只票，数据到 ' + esc(md(fw.e6_data_date)) + '），D4 那份用 D4 的前向组合（' + esc(md(fw.d4_start)) + ' 起）。每个交易日 19:30 记一次。</p></section>';
    html += '<section class="card"><h2>回测<small>' + esc(ym(fb.first)) + ' 至 ' + esc(ym(fb.last)) + '，对数刻度</small></h2><div class="tiles">' +
      '<div class="tile"><span>年化</span><b>' + pctc(t.cagr, 1) + '</b></div><div class="tile"><span>最大回撤</span><b>' + pctc(t.mdd, 1) + '</b></div>' +
      '<div class="tile"><span>年化 ÷ 回撤</span><b class="num">' + num(t.calmar, 2) + '</b></div><div class="tile"><span>最长没创新高</span><b class="num">' + esc(t.uw_days == null ? '—' : t.uw_days) + ' 天</b></div></div>' +
      chart(bt.equity || [], (bt.dates || []).map(ym), { base: 1, log: true, label: id + ' 回测', h: 150, fmt: function (v) { return v >= 1e4 ? (v / 1e4).toFixed(1) + '万' : xmult(v); },
        tips: (bt.dates || []).map(function (x, i) { return ym(x) + '：' + xmult(bt.equity[i]); }) });
    var c3 = function (x) { x = x || {}; return pctc(x.cagr, 0) + '<span class="nm">回撤 ' + pct(x.mdd, 0) + '</span>'; };
    html += '<div class="scroll"><table class="tbl"><thead><tr><th>阶段</th><th class="n">' + esc(id) + '</th><th class="n">E6 单独</th><th class="n">D4 单独</th></tr></thead><tbody>' +
      (bt.segs || []).map(function (g) { return '<tr><td class="num">' + esc(g.label) + '</td><td class="n">' + c3(g.f) + '</td><td class="n">' + c3(g.e6) + '</td><td class="n">' + c3(g.d4) + '</td></tr>'; }).join('') +
      '<tr><td>全程</td><td class="n">' + c3(t) + '</td><td class="n">' + c3((fb.E6 || {}).total) + '</td><td class="n">' + c3((fb.D4 || {}).total) + '</td></tr></tbody></table></div>';
    var ys = bt.years || [];
    if (ys.length) {
      html += '<h3 class="sub">每年</h3><div class="scroll"><table class="tbl"><thead><tr><th>年</th><th class="n">' + esc(id) + '</th><th class="n">E6</th><th class="n">D4</th></tr></thead><tbody>' +
        ys.slice().reverse().map(function (y) { return '<tr><td class="num">' + esc(y.year) + '</td><td class="n">' + pctc(y.f, 1) + '</td><td class="n">' + pctc(y.e6, 1) + '</td><td class="n">' + pctc(y.d4, 1) + '</td></tr>'; }).join('') +
        '</tbody></table></div>';
    }
    html += '<p class="small muted">' + esc(f.note || '') + ' 两边每天涨跌的相关系数 ' + num(fb.corr_daily, 2) + '。最长没创新高按交易日数。</p></section>';
    html += '<section class="card"><h2>组成</h2><p class="small">两份各自的信号、持仓和前向记录：</p><div class="btn-row"><button class="btn" data-open="e6">E6 龙头扫板</button><button class="btn" data-open="fusion4">策略 D4</button></div></section>';
    return html;
  }
  // ------------------------------------------------------------------ 实盘状态（F5 详情页）
  var liveTrade = { loaded: false, data: null, error: '' };
  function fetchLiveTrade() {
    return abortableFetch('/api/trade/status', 15000)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) { liveTrade.loaded = true; liveTrade.data = d; liveTrade.error = ''; })
      .catch(function (e) { liveTrade.loaded = true; liveTrade.error = String(e.message || e); });
  }
  function viewLiveTrade(d) {
    if (!liveTrade.loaded) { fetchLiveTrade().then(function () { if (state.detail === d.id) render(); }); return '<section class="card"><p class="muted small">实盘状态加载中…</p></section>'; }
    if (liveTrade.error) return '<section class="card"><h2>实盘运行</h2><div class="banner warn">接口不可用：' + esc(liveTrade.error) + '</div>' +
      '<p class="small muted">自动交易程序在 Windows 电脑上运行，服务器转发 /api/trade/status。电脑关机或程序未启动时这里看不到。</p></section>';
    var t = liveTrade.data || {};
    var run = t.running, mode = t.mode || 'stopped';
    var modeTxt = { stopped: '已停止', observe: '观察模式（不下单）', live: '实盘模式', handoff: '等待人工确认' };
    var st = run ? 'ok' : 'warn';
    var html = '<section class="card"><h2>实盘运行' + (t.account ? '<small>' + esc(t.account) + '</small>' : '') + '</h2>' +
      '<div class="banner ' + st + '"><b>' + (run ? '● 运行中' : '○ 未运行') + '</b> — ' + esc(modeTxt[mode] || mode) + '</div>';
    if (t.step) html += '<p class="small">当前步骤：' + esc(t.step) + '</p>';
    if (t.last_run) html += '<p class="small muted">上次执行：' + esc(dt(t.last_run)) + '</p>';
    if (t.position) {
      html += '<h3 class="sub">当前持仓</h3><div class="tiles">' +
        '<div class="tile"><span>股票</span><b>' + esc(t.position.name || t.position.code) + '</b></div>' +
        '<div class="tile"><span>数量</span><b class="num">' + esc(t.position.quantity || '—') + '</b></div>' +
        '<div class="tile"><span>买入日</span><b>' + esc(String(t.position.bought || '').slice(5)) + '</b></div>' +
        (t.position.holding_day != null ? '<div class="tile"><span>第几天</span><b class="num">' + esc(t.position.holding_day) + '</b></div>' : '') +
        '</div>';
    } else if (run) {
      html += '<p class="small muted">当前空仓。</p>';
    }
    var f5 = t.f5 || {}, pp = f5.prep || {}, pk = f5.pick;
    if (pp.day) {
      html += '<h3 class="sub">今天怎么判的<small>' + esc(md(pp.day)) + '，D = ' + esc(md(pp.prev)) + '</small></h3>' +
        '<div class="tiles">' +
        '<div class="tile"><span>候选</span><b class="num">' + esc(pp.n_cands == null ? '—' : pp.n_cands) + ' 只</b></div>' +
        '<div class="tile"><span>大盘 z</span><b class="num">' + num(pp.z, 2) + '</b></div>' +
        '<div class="tile"><span>平稳段</span><b>' + (pp.calm === true ? '是（不做）' : pp.calm === false ? '否（可以做）' : '—') + '</b></div>' +
        '</div>';
      if (pk) {
        html += '<p class="small">第 1 只：<b>' + esc(pk.name) + '</b>（' + esc(short(pk.code)) + '）开盘 ' + num(pk.open, 2) +
          (isNum(pk.gap) ? '（' + pctc(pk.gap, 2) + '）' : '') + '，昨 ' + esc(pk.streak_y) + ' 连板，昨收 ' + num(pk.pre, 2) +
          '，涨停 ' + num(pk.lim, 2) + '</p>';
      }
      if (f5.no_trade_reason) html += '<div class="banner warn"><b>今天不做</b> — ' + esc(f5.no_trade_reason) + '</div>';
      else if (pk && pk.trading) html += '<div class="banner ok"><b>今天做 ' + esc(pk.name) + '</b> — 盯盘等 30 秒涨速或摸板，以 ' + num(pk.lim, 2) + ' 买入</div>';
      var tp = f5.top || [];
      if (tp.length) {
        html += '<div class="scroll"><table class="tbl"><thead><tr><th>#</th><th>股票</th><th class="n">开盘涨幅</th><th class="n">连板</th></tr></thead><tbody>' +
          tp.map(function (r) { return '<tr' + rowCode(r.code) + '><td class="num">' + esc(r.rk) + '</td><td>' + esc(r.name || short(r.code)) +
            (r.open_lim ? ' <span class="tag off">开板涨停</span>' : '') + '</td><td class="num">' + pctc(r.gap, 2) +
            '</td><td class="num">' + esc(r.streak_y) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      }
    }
    if (t.pending) html += '<h3 class="sub">待核对委托</h3><p class="small">' + esc(t.pending.code) + ' ' + esc(t.pending.side) + ' ' + esc(t.pending.quantity) + ' @ ' + esc(t.pending.price) +
      (t.pending.order_id ? '（编号 ' + esc(t.pending.order_id) + '）' : '（无编号）') + '</p>';
    if (t.today_pnl != null) html += '<h3 class="sub">今日盈亏</h3><p>' + pctc(t.today_pnl, 2) + '</p>';
    if (t.today_signals && t.today_signals.length) {
      html += '<h3 class="sub">今日信号</h3><div class="scroll"><table class="tbl"><thead><tr><th>时间</th><th>事件</th></tr></thead><tbody>' +
        t.today_signals.map(function (ev) { return '<tr><td class="num">' + esc(String(ev.at || '').slice(11, 19)) + '</td><td class="small">' + esc(ev.text) + '</td></tr>'; }).join('') +
        '</tbody></table></div>';
    }
    if (t.message) html += '<p class="small muted">' + esc(t.message) + '</p>';
    var hb = t.heartbeat_age_seconds;
    if (isNum(hb) && hb > 300 && run) html += '<div class="banner warn">本机程序已经 ' + Math.round(hb / 60) + ' 分钟没有更新心跳，可能已停止或被系统挂起。</div>';
    html += '<p class="small muted">交易程序跑在你 Windows 电脑上，服务器用 SSH 隧道直接调用本机服务（心跳 ' +
      (isNum(hb) ? (hb < 120 ? hb + ' 秒前' : Math.round(hb / 60) + ' 分钟前') : '未知') + '）' +
      '。电脑关机或程序未启动时这里看到的是最后一次状态。' +
      '<button class="btn" id="live-refresh">刷新实盘状态</button></p></section>';
    return html;
  }

  function viewFilt(s, d) {
    var f = s.f, bt = d.backtest || {}, t = bt.total || {}, e = bt.e6_total || {}, fw = f.forward || {}, c3 = d.cond || {}, id = esc(d.id), k = fKey(d), ind = useInd(d);
    var lo = num(c3.z_lo, 1), hi = '+' + num(c3.z_hi, 1);
    var html = '<section class="card"><h2>' + esc(d.name) + '</h2>' + allocBar(s, d, true) +
      '<div class="banner warn">' + esc(d.note || '候选，还没检验。') + '</div></section>';
    // 实盘运行状态（F5 详情顶部；交易程序按 F5 做，F6 / F5-1 页不显示，免得以为它在做 F6 / F5-1）
    if (isSpeed(d) && !isPeer(d) && !isVol(d)) html += viewLiveTrade(d);
    // 1. 信号怎么来：一步一步写全，不用再去翻 E6 页
    var steps = [
      '<b>候选</b>：昨天收盘涨停的主板非 ST 股（上市满 60 个交易日）。',
      '<b>选第 1 只</b>：9:25 开盘后，按“开盘涨幅名次 + 昨日连板名次”打分，只看第 1 只（就是 E6 的第 1 只），其余都不看。',
      '<b>第 1 只开盘就涨停</b> → 今天不做（不排队、不追回封）。'];
    if (ind) steps.push('<b>看行业</b>：第 1 只所在的申万一级行业，昨天还有别的票收盘涨停 → 今天不做。');
    steps.push('<b>看大盘</b>：昨天收盘的大盘 z 在 ' + lo + ' ～ ' + hi + ' 之间（平稳段）→ 今天不做；低于 ' + lo + '（偏弱）或不低于 ' + hi + '（偏强、过热）才做。' +
      (ind ? '' : '不看行业。') + 'z 就是「市场」页的大盘恐慌程度。');
    if (isSpeed(d)) {
      steps.push('<b>买（和 F4 不一样的地方）</b>：上面都过了，就盯盘——摸到涨停之前，一旦' + speedTxt(d) + '（都按昨收算，比如昨收 10 元：价格 ≥ 10.70，且 30 秒内涨了 ≥ 0.30 元），' +
        '马上以涨停价挂买单，金额 = 全部可用资金。一直没出现，就照 F4 等最新价 ≥ 涨停价再以涨停价买（可以先设好这张云条件单兜底）。盘中没摸到涨停价也没提前触发，这天没交易。');
      steps.push('<b>为什么提前</b>：封得快的票，摸板后 3 秒再挂单常常已经排不上；涨得急的时候提前几秒挂，能多买到这种票，买价也平均低 1% 左右。' +
        '代价是偶尔提前买进了、当天却没涨停。同花顺云条件单设不了"30 秒涨 3 个点"，要自己看盘或用程序。');
      if (isPeer(d)) {
        steps.push('<b>下单前再看一眼（和 F5 不一样的地方）</b>：' + PEER_TXT + '。只看"此刻封在涨停价上"的：最新价等于它自己的涨停价、买一挂着涨停价。' +
          '道理：要买的这只在冲板，别的昨日涨停股一只都没封住，说明当天接力的钱很弱，冲上去也容易被砸开。' +
          '2023–2026 年的逐笔里这种情况 17 笔，每笔 −1.5%（当天封住只有 47%），其余 78 笔每笔 +6.3%。' +
          '<b>但在没用过的 2017–2022 年上检验，结果反过来</b>：一只都没封的 70 笔每笔 +4.5%，照买的 138 笔 +2.3%（p 0.82），这条不成立，只作对照。');
      }
    } else {
      steps.push('<b>买</b>：上面都过了，就设一张云条件单：最新价 ≥ 涨停价时以涨停价买入，金额 = 全部可用资金，当天有效。盘中没摸到涨停价就不会买，这天没交易。');
    }
    if (isSpeed(d)) {
      steps.push('<b>卖（10-28 起）</b>：买入后从下一个交易日起，每天 14:50 看一眼：还封在涨停（买一在涨停价、卖一没挂单）就接着拿，没封住就马上卖，不等收盘；' +
        '最多拿 5 天，第 5 天 14:50 直接卖。回测 2020 年起按 14:50 那一刻的价格算（2017–2019 年没有分钟线，照收盘算）。' +
        '这一改是在用过的 2020–2026 年数据上看的（14:50 卖和收盘卖每笔差不到 0.3 个点、回撤略小），不是正式检验。');
    } else {
      steps.push('<b>卖</b>：买入后每个交易日 14:50 看一眼：还封在涨停（买一在涨停价、卖一没挂单）就接着拿，没封住就收盘前卖；最多拿 5 天。');
    }
    if (isVol(d)) {
      steps.push('<b>多一条卖法（和 F5 不一样的地方）</b>：持仓日 9:30 起每分钟看，一旦' + volTxt(d) + '，就马上卖（不等 14:50）。' +
        '"前 5 个交易日"往前最多找 20 天，去掉一字板（全天最高 = 最低）和量很少的日子（不到这 20 天日量中位的 0.3 倍），少于 3 天就这天不用这一条。' +
        '道理：开板了、量又是平时同一时间的好几倍，多半是在出货。2020–2026 年的逐笔里，累计量比 > 5 的 7 笔全部卖对、平均少亏 8.6 个点；' +
        '<b>只到 4～5 倍的 7 笔不行</b>（两笔卖掉后又涨了 18% 和 36%）。门槛是看着这几笔定的，次数太少，没检验过。现在没有盘中提醒，要自己看量。');
    }
    steps.push('<b>仓位</b>：全部钱只拿一只票；拿着的时候来的信号跳过，卖出当天来的也跳过（钱收盘才回来）。没有 D4 那份，不调仓。');
    html += '<section class="card"><h2>信号怎么来<small>每个交易日最多 1 个</small></h2><ol class="steps small">' +
      steps.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ol></section>';
    // 2. 今天 / 下一个交易日：现在能不能做
    var lk = liveKey(d), lv = (s.e6 || {}).live || {}, pd = s.plan_day, zn = fw.z_now, hold = filtHold(s, d), live = lv.day === pd && lv.open && lv.open[lk];
    html += '<section class="card"><h2>' + (live ? '今天' : '下一个交易日') + '<small>' + esc(md(pd)) + '（' + esc(wd(pd)) + '）</small></h2>';
    if (live) {
      var g = lv.open[lk], p = lv.open.pick || {};
      html += '<p class="small muted">9:25 第 1 只：' + esc(p.name || short(p.code)) + (isNum(p.gap) ? '，开盘 ' + pctc(p.gap / 100, 2) : '') + '</p>' +
        '<div class="banner ' + (g.skip || g.error ? 'warn' : 'ok') + '"><b>' + esc(g.action || g.error || '') + '</b></div>' + f3Facts(g);
    } else {
      var zl;
      if (zn && isNum(zn.z)) {
        zl = esc(md(zn.date)) + ' 收盘大盘 z <b class="num">' + num(zn.z, 2) + '</b>：' + (zn.calm ?
          '在平稳段，<b>' + esc(md(pd)) + ' ' + id + ' 不做</b>，9:25 不用看。' :
          '不在平稳段，大盘这一条满足。9:25 看 E6 第 1 只：开盘没涨停' + (ind ? '、它所在行业昨天没有别的涨停' : '') +
          (isSpeed(d) ? '，就盯盘：' + speedTxt(d) + '就提前挂涨停价，没出现就摸板再挂。' : '，就设条件单。') +
          (isPeer(d) ? PEER_TXT + '。' : ''));
      } else {
        zl = '昨收大盘 z 还没算出来（台式机每个交易日 19:30 算完推上来）。';
      }
      html += '<p>' + zl + '</p>';
      if (hold) html += '<p>' + id + ' 现在拿着 <b>' + esc(hold.name || short(hold.code)) + '</b>（' + esc(md(hold.buy)) + ' 买），新信号跳过；14:50 看它封没封住。</p>';
      var top = ((s.e6 || {}).next || {}).top || [];
      if (top.length && !hold && !(zn && zn.calm)) {
        html += '<p class="small muted">昨天连板最高：' + top.slice(0, 5).map(function (r) { return esc(r.name || short(r.code)) + ' ' + esc(r.board) + ' 板'; }).join('、') +
          '。打分第 1 要 9:25 开盘后才知道。</p>';
      }
      html += '<p class="small muted">9:25:30 左右出结果，「今天」页选 ' + id + ' 和 E6 页都会显示。</p>';
    }
    html += '</section>';
    var ser = (fw.series || {})[d.id] || [], ok = ser.filter(isNum);
    html += '<section class="card"><h2>前向记录<small>' + esc(md(fw.start)) + ' 收盘为起点</small></h2>';
    if ((fw.dates || []).length >= 2 && ok.length >= 2) {
      html += '<div class="tiles"><div class="tile"><span>累计</span><b>' + pctc(ok[ok.length - 1] - 1, 1) + '</b></div><div class="tile"><span>最大回撤</span><b>' + pctc(maxDrawdown(ok), 1) + '</b></div></div>' +
        chart(ser, fw.dates.map(md), { base: 1, label: d.id + ' 前向记录', h: 120 });
    } else {
      html += '<p class="empty">' + esc((isSpeed(d) && fw[k + '_note']) || fw.note || '从下一个交易日起记录，每个交易日 19:30 记一次。') + '</p>';
    }
    var sg = fw[k + '_signals'] || [];
    if (sg.length && isSpeed(d)) {     // F5：按逐笔推断的买法结果
      html += '<h3 class="sub">每天的第 1 只，' + id + ' 怎么做的</h3><div class="scroll"><table class="tbl"><thead><tr><th>日期</th><th>第 1 只</th><th>' + id + '</th></tr></thead><tbody>' +
        sg.map(function (r) {
          var tag, why = '';
          if (!r.ok) { tag = '<span class="tag off">不做</span>'; why = (r.reasons || []).join('；'); }
          else if (r.l2 === '提前买') { tag = '<span class="tag open">提前买</span>'; why = isNum(r.disc) ? '比涨停价便宜 ' + pct(r.disc, 1) : ''; }
          else if (r.l2 === '摸板后买到') { tag = '<span class="tag open">摸板后买到</span>'; }
          else if (r.l2 === '待逐笔') { tag = '<span class="tag off">待逐笔</span>'; why = '条件满足，等这天的逐笔数据补算'; }
          else { tag = '<span class="tag off">' + esc(r.l2 || '没交易') + '</span>'; why = String(r.status || ''); }
          return '<tr' + rowCode(r.code) + '><td class="num">' + esc(md(r.date)) + '</td><td>' + esc(r.name || short(r.code)) +
            '<span class="nm">' + (isNum(r.z) ? 'z ' + num(r.z, 2) : '') + '</span></td><td class="wrap small">' + tag + ' ' + esc(why) + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="small muted">买到没有、价钱多少按逐笔数据推断（挂单 3 秒后到，排不到就算没买到）' +
        (isPeer(d) ? '；"别的昨日涨停一只都没封"也按下单那一刻的逐笔数' : '') + '；逐笔数据现在到 ' + esc(md(fw[k + '_l2_last'])) + '。</p>';
    }
    if (sg.length && !isSpeed(d)) {
      html += '<h3 class="sub">每天的第 1 只，' + id + ' 怎么做的</h3><div class="scroll"><table class="tbl"><thead><tr><th>日期</th><th>第 1 只</th><th>' + id + '</th><th class="n">收益</th></tr></thead><tbody>' +
        sg.map(function (r) {
          var st = String(r.status || ''), tag, why;
          if (!r.ok) { tag = '<span class="tag off">不做</span>'; why = (r.reasons || []).join('；'); }
          else if (r.taken) { tag = '<span class="tag open">做了</span>'; why = st; }
          else if (/^(持有中|已卖出)/.test(st)) { tag = '<span class="tag off">跳过</span>'; why = '条件满足，但 ' + d.id + ' 当时拿着别的票'; }
          else { tag = '<span class="tag off">没交易</span>'; why = '条件满足，但' + st; }
          return '<tr' + rowCode(r.code) + '><td class="num">' + esc(md(r.date)) + '</td><td>' + esc(r.name || short(r.code)) +
            '<span class="nm">' + (ind && r.ind ? esc(r.ind) + ' · ' : '') + (isNum(r.z) ? 'z ' + num(r.z, 2) : '') + '</span></td>' +
            '<td class="wrap small">' + tag + ' ' + esc(why) + '</td>' +
            '<td class="n">' + (r.taken && isNum(r.ret) ? pctc(r.ret / 100, 1) : '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    html += isSpeed(d) ? '<p class="small muted">日子同 F4，从 E6 的前向记录里挑出符合条件的信号，按逐笔推断的买法' + (isPeer(d) ? '（再去掉下单时别的昨日涨停一只都没封的）' : '') +
      '另记一个全仓一只票的账户；逐笔数据下到哪天，就补算到哪天。</p></section>' :
      '<p class="small muted">从 E6 的前向记录里挑出符合' + (ind ? '两个条件' : '条件') + '的信号，另记一个全仓一只票的账户（数据到 ' + esc(md(fw.e6_data_date)) + '）。' +
      '“没交易”= 条件满足，但第 1 只开盘就涨停或盘中没摸到涨停价。</p></section>';
    // 回测里做过的笔：默认最近 15 笔，可展开全部（快照 10-27 起带全部笔）
    var rcAll = bt.recent || [], showAll = !!(state.btAll && state.btAll[d.id]), N_RC = 15;
    var rc = showAll ? rcAll : rcAll.slice(0, N_RC);
    if (rc.length) {
      html += '<section class="card"><h2>' + (showAll ? '回测里做过的全部 ' : '回测里最近做过的 ') + rc.length + ' 笔<small>全仓一只票，到 ' + esc(md(bt.last)) + '</small></h2><div class="scroll"><table class="tbl"><thead><tr>' +
        '<th>买入日</th><th>股票</th>' + (isSpeed(d) ? '<th>买法</th>' : '') + '<th class="n">昨收 z</th><th class="n">收益</th></tr></thead><tbody>' +
        rc.map(function (r) {
          return '<tr' + rowCode(r.code) + '><td class="num">' + esc(String(r.date || '').slice(2)) + '</td><td>' + esc(r.name || short(r.code)) +
            (ind && r.ind ? '<span class="nm">' + esc(r.ind) + '</span>' : '') + '</td>' +
            (isSpeed(d) ? '<td class="small">' + esc(r.how || '—') + (r.how === '提前' && isNum(r.disc) ? '<span class="nm">便宜 ' + pct(r.disc, 1) + '</span>' : '') +
              (r.vol ? ' <span class="tag sell">放量卖</span>' : '') + '</td>' : '') +
            '<td class="n num">' + (isNum(r.z) ? num(r.z, 2) : '—') + '</td><td class="n">' + pctc(r.ret, 1) + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="small muted">' + (isSpeed(d) ? '买法和价钱按逐笔推断：“提前”= ' + speedTxt(d) + '后 3 秒挂涨停价买到，“便宜”是买价比涨停价低多少；“摸板后”= 没提前触发，摸板后 3 秒挂单买到。' +
          '连板就拿最多 5 天、扣 0.25%。' : '收益按摸板涨停价买到、连板就拿最多 5 天、扣 0.25% 算。') + '日期是 年-月-日。</p>' +
        (rcAll.length > N_RC ? '<p><button class="btn" data-btall="' + id + '">' + (showAll ? '收起，只看最近 ' + N_RC + ' 笔' : '展开全部 ' + rcAll.length + ' 笔') + '</button></p>' : '') +
        '</section>';
    }
    var p100 = function (v, dgt) { return isNum(v) ? pctc(v, dgt == null ? 1 : dgt) : '—'; };
    html += '<section class="card"><h2>回测<small>' + esc(ym(bt.first)) + ' 至 ' + esc(ym(bt.last)) + '，对数刻度</small></h2><div class="tiles">' +
      '<div class="tile"><span>年化</span><b>' + p100(t.cagr) + '</b></div><div class="tile"><span>最大回撤</span><b>' + p100(t.mdd) + '</b></div>' +
      '<div class="tile"><span>年化 ÷ 回撤</span><b class="num">' + num(t.calmar, 2) + '</b></div><div class="tile"><span>最长没创新高</span><b class="num">' + esc(t.uw_days == null ? '—' : t.uw_days) + ' 天</b></div>' +
      '<div class="tile"><span>信号</span><b class="num">' + esc(bt.n_signals == null ? '—' : bt.n_signals) + '<span class="nm"> / E6 ' + esc(bt.n_e6_signals == null ? '—' : bt.n_e6_signals) + '</span></b></div>' +
      '<div class="tile"><span>每笔 / 胜率</span><b>' + p100(bt.per_trade) + '<span class="nm"> / ' + (isNum(bt.win) ? (bt.win * 100).toFixed(0) + '%' : '—') + '</span></b></div></div>' +
      chart(bt.equity || [], (bt.dates || []).map(ym), { base: 1, log: true, label: d.id + ' 回测', h: 150, fmt: function (v) { return v >= 1e4 ? (v / 1e4).toFixed(1) + '万' : xmult(v); },
        tips: (bt.dates || []).map(function (x, i) { return ym(x) + '：' + xmult(bt.equity[i]); }) });
    var c2 = function (x) { x = x || {}; return pctc(x.cagr, 0) + '<span class="nm">回撤 ' + pct(x.mdd, 0) + '</span>'; };
    var cmp = (isPeer(d) || isVol(d)) ? 'F5 同口径' : isSpeed(d) ? 'F4 同口径' : 'E6 全仓';
    if (isSpeed(d)) {
      var it2 = bt.ideal_total || {};
      html += '<p class="small">' + (isVol(d) ? '持仓日开板放巨量、提前卖掉的 <b class="num">' + esc(bt.n_volsell == null ? '—' : bt.n_volsell) + '</b> 笔（F5 会照 14:50 规则拿）。' : '') + (isPeer(d) ? '下单时别的昨日涨停一只都没封、没买的 <b class="num">' + esc(bt.n_skip == null ? '—' : bt.n_skip) + '</b> 次（F5 会买）。' : '') + '提前买 <b class="num">' + esc(bt.n_early == null ? '—' : bt.n_early) + '</b> 次（其中当天没摸到涨停 ' + esc(bt.n_early_notouch == null ? '—' : bt.n_early_notouch) +
        ' 次；摸板后 3 秒本来排不上、提前才买到的 ' + esc(bt.n_grab == null ? '—' : bt.n_grab) + ' 次）。对照：' + esc(bt.cmp_label || 'F4') + ' 年化 ' + p100(e.cagr) + '、回撤 ' + p100(e.mdd) +
        '；F4 理想成交（摸板就按涨停价买到）年化 ' + p100(it2.cagr) + '、回撤 ' + p100(it2.mdd) + '。</p>';
    }
    html += '<div class="scroll"><table class="tbl"><thead><tr><th>阶段</th><th class="n">' + id + '</th><th class="n">' + cmp + '</th></tr></thead><tbody>' +
      (bt.segs || []).map(function (g) { return '<tr><td class="num">' + esc(g.label) + '</td><td class="n">' + c2(g.f) + '</td><td class="n">' + c2(g.e6) + '</td></tr>'; }).join('') +
      '<tr><td>全程</td><td class="n">' + c2(t) + '</td><td class="n">' + c2(e) + '</td></tr></tbody></table></div>';
    var ys = bt.years || [];
    if (ys.length) {
      html += '<h3 class="sub">每年</h3><div class="scroll"><table class="tbl"><thead><tr><th>年</th><th class="n">' + id + '</th><th class="n">' + cmp + '</th></tr></thead><tbody>' +
        ys.slice().reverse().map(function (y) { return '<tr><td class="num">' + esc(y.year) + '</td><td class="n">' + pctc(y.f, 1) + '<span class="nm">回撤 ' + pct(y.f_mdd, 0) + '</span></td><td class="n">' + pctc(y.e6, 1) + '</td></tr>'; }).join('') +
        '</tbody></table></div>';
    }
    html += isSpeed(d) ?
      '<p class="small muted">只算有逐笔数据的日子（' + esc(ym(bt.first)) + ' 到 ' + esc(md(bt.l2_last)) + '；2017–2022 年是 10-27 补上的，那几年也是做检验用的数据）。' +
      '成交按逐笔推断：挂单 3 秒后到，排不到就算没买到（记 0），不是理想成交；' +
      (isPeer(d) ? '“F5 同口径”是 F5 同样按逐笔推断、不看别的涨停封没封。"封着"按下单那一刻之前的最后一笔成交 ≥ 它自己的涨停价算。' +
        '这条规则是在 2023–2026 年上找出来的，预先登记后在 2017–2022 年的逐笔上检验了一次：没通过。' :
        isVol(d) ? '“F5 同口径”是 F5 同样按逐笔推断、只用 14:50 规则卖。量比按今天和前几天的逐笔算，只用在逐笔里都有这只票的持仓日（其余照 F5）；' +
          '卖价按触发那一分钟末的最新成交价，没算滑点。' :
        '“F4 同口径”是 F4 摸板后 3 秒挂单、同样按逐笔推断。') + '买卖合计扣 0.25%、空仓不计息，没算容量。最长没创新高按交易日数。</p></section>' :
      '<p class="small muted">理想成交（摸板按涨停价买到）、买卖合计扣 0.25%、空仓不计息，没算容量。' + (useInd(d) ? '行业是现在的申万一级分类，涨停按收盘算。' : '') + '最长没创新高按交易日数。</p></section>';
    html += '<section class="card"><h2>组成</h2><p class="small">' + id + ' 的买卖都来自 E6，' +
      (isVol(d) ? '日子、买法和 14:50 卖法同 F5，再多一条：持仓日开板放巨量就提前卖' :
        isPeer(d) ? '日子和买法同 F5（大盘平稳段不做、30 秒涨速提前挂涨停价），再多一条：下单时别的昨日涨停一只都没封就不买' :
        isSpeed(d) ? '日子同 F4（大盘平稳段不做），买法换成 30 秒涨速提前挂涨停价' : useInd(d) ? '只是多了两个条件' : '只是大盘平稳段不做') +
      '：</p><div class="btn-row"><button class="btn" data-open="e6">E6 龙头扫板</button>' + (isSpeed(d) ? '<button class="btn" data-open="F4">F4</button>' : '') +
      ((isPeer(d) || isVol(d)) ? '<button class="btn" data-open="F5">F5</button>' : '') + '</div></section>';
    return html;
  }
  function detailTitle(s, id) {
    if (F_IDS.indexOf(id) >= 0) return id;
    if (id === 'e6') return 'E6 龙头扫板';
    if (id === 'guide') return '说明';
    return (s.labels && s.labels[id]) || id;
  }
  function viewDetail(s, id) {
    if (F_IDS.indexOf(id) >= 0) return viewF(s, id);
    if (id === 'e6') return viewE6(s);
    if (id === 'guide') return viewGuide(s);
    if (s.kinds.indexOf(id) >= 0) return '<p class="lead">' + esc(KIND_DESC[id] || '') + '</p>' + viewSignal(s, id) + viewForward(s, id);
    state.detail = null;
    return viewStrategies(s);
  }

  // ------------------------------------------------------------------ 外壳
  var TABS = [
    ['today', '今天', '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'],
    ['strategies', '策略', '<path d="M12 3 3 8l9 5 9-5z"/><path d="M3 13l9 5 9-5"/>'],
    ['holdings', '持仓', '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>'],
    ['market', '市场', '<path d="M3 12a9 9 0 0 1 18 0"/><path d="M12 12l4-4"/><circle cx="12" cy="12" r="1.2"/><path d="M5 19h14"/>']
  ];
  var OLD_TAB = { overview: 'market', signal: 'strategies', forward: 'strategies', e6: 'strategies', guide: 'strategies' };

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
    if (OLD_TAB[state.tab]) state.tab = OLD_TAB[state.tab];
    if (!TABS.some(function (t) { return t[0] === state.tab; })) state.tab = 'today';
    var inDetail = state.tab === 'strategies' && !!state.detail;
    var body = state.tab === 'today' ? viewToday(s) : state.tab === 'strategies' ? (inDetail ? viewDetail(s, state.detail) : viewStrategies(s)) :
      state.tab === 'holdings' ? viewHoldings(s) : viewOverview(s);
    inDetail = state.tab === 'strategies' && !!state.detail;          // viewDetail 遇到不认识的会退回列表
    var fr = freshness(s).filter(function (b) { return b.k !== 'ok' || state.tab !== 'today'; })     // 「今天」的抬头已经写了日期，绿色那条不重复
      .map(function (b) { return '<div class="banner ' + b.k + '">' + b.t + '</div>'; }).join('');
    // 图表 tip 覆盖层
    var tipHtml = '';
    if (state.chartTip) {
      tipHtml = '<div id="nn-tip">' + esc(state.chartTip.text) + '</div>';     // 位置在下面用 CSSOM 设，CSP 不放行行内 style
    }
    var head = inDetail ?
      '<header class="top detail"><button class="btn back" data-back="1" aria-label="回到策略列表">‹ 策略</button><h1>' + esc(detailTitle(s, state.detail)) + '</h1><button class="btn" id="refresh">刷新</button></header>' :
      '<header class="top"><div><h1>' + esc(({ today: '牛牛策略', strategies: '策略', holdings: '持仓', market: '市场' })[state.tab]) + '</h1><div class="sub">快照 ' + esc(dt(s.generated_at)) + '，只提醒不下单</div></div><button class="btn" id="refresh">刷新</button></header>';
    app.innerHTML = head +
      '<main class="tab-' + esc(state.tab) + '">' + (inDetail && state.detail === 'guide' ? '' : fr) + body + tipHtml + '</main>' + stockSheet(s) +
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

  function savePref() { ls(false, LS_PREF, JSON.stringify({ tab: state.tab, pick: state.pick, search: state.search, forwardFilter: state.forwardFilter, f: state.f, detail: state.detail })); }
  function keepScroll(fn) { var y = window.scrollY; fn(); render(); window.scrollTo(0, y); }

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
    var lr = q('#live-refresh'); if (lr) {
      lr.addEventListener('click', function () { liveTrade.loaded = false; render(); });
    }
    // F 系列详情：回测笔数展开 / 收起（收起时回到这张卡片，不留在长表格下面）
    Array.prototype.forEach.call(app.querySelectorAll('[data-btall]'), function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-btall'), was;
        state.btAll = state.btAll || {}; was = !!state.btAll[k]; state.btAll[k] = !was;
        var card = b.closest('section'), top = card ? card.getBoundingClientRect().top + window.scrollY : window.scrollY, y = window.scrollY;
        render();
        window.scrollTo(0, was ? Math.min(y, top - 12) : y);
      });
    });
    var fg = q('#forget'); if (fg) fg.addEventListener('click', function () { ls(false, LS_PASS, null); state.snap = null; state.phase = 'locked'; state.error = ''; render(); });

    // 各页策略切换
    Array.prototype.forEach.call(app.querySelectorAll('[data-pick]'), function (b) {
      b.addEventListener('click', function () { state.pick[b.getAttribute('data-group')] = b.getAttribute('data-pick'); savePref(); var y = window.scrollY; render(); window.scrollTo(0, y); });
    });

    // 前向状态筛选
    Array.prototype.forEach.call(app.querySelectorAll('[data-ff]'), function (b) {
      b.addEventListener('click', function () { state.forwardFilter = b.getAttribute('data-ff'); savePref(); render(); });
    });

    // 页签切换（在策略详情里再点「策略」= 回到列表）
    Array.prototype.forEach.call(app.querySelectorAll('[data-tab]'), function (b) {
      b.addEventListener('click', function () {
        var t = b.getAttribute('data-tab');
        if (t === 'strategies' && state.tab === 'strategies') state.detail = null;
        state.tab = t; savePref(); render(); window.scrollTo(0, 0);
      });
    });
    // F1 / F2 切换：「今天」和「持仓」跟着一起换
    Array.prototype.forEach.call(app.querySelectorAll('[data-f]'), function (b) {
      b.addEventListener('click', function () {
        keepScroll(function () {
          state.f = b.getAttribute('data-f');
          if (F_FILT.indexOf(state.f) < 0) state.pick.holdings = state.f;          // F3 / F4 没有 D4 那份，持仓页的清单不跟着换
          savePref();
        });
      });
    });
    // 打开某个策略的详情 / 回到列表 / 跳到别的页
    Array.prototype.forEach.call(app.querySelectorAll('[data-open]'), function (b) {
      b.addEventListener('click', function () { state.tab = 'strategies'; state.detail = b.getAttribute('data-open'); savePref(); render(); window.scrollTo(0, 0); });
    });
    Array.prototype.forEach.call(app.querySelectorAll('[data-back]'), function (b) {
      b.addEventListener('click', function () { state.detail = null; savePref(); render(); window.scrollTo(0, 0); });
    });
    Array.prototype.forEach.call(app.querySelectorAll('[data-go]'), function (b) {
      b.addEventListener('click', function () { state.tab = b.getAttribute('data-go'); state.detail = null; savePref(); render(); window.scrollTo(0, 0); });
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
      if (pref.tab) state.tab = OLD_TAB[pref.tab] || pref.tab;       // 老版本的页签（概览/信号/前向/E6/说明）换成新的
      if (pref.search && typeof pref.search === 'object') state.search = pref.search;
      if (pref.forwardFilter) state.forwardFilter = pref.forwardFilter;
      if (F_IDS.indexOf(pref.f) >= 0) state.f = pref.f;
      if (typeof pref.detail === 'string') state.detail = pref.detail;
      if (pref.tab === 'e6') state.detail = 'e6';
    }
  } catch (e) { /* 偏好坏了就用默认 */ }
  state.pick = pick;

  // 「今天」的“现在”那条线每分钟挪一次（只在看「今天」、页面在前台、没打开个股时重画）
  setInterval(function () {
    if (state.phase === 'ready' && state.tab === 'today' && !state.stock && !state.chartTip && !document.hidden) keepScroll(function () {});
  }, 60000);

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && state.phase === 'ready' && Date.now() - state.loadedAt > 10 * 60 * 1000) load();
  });
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) navigator.serviceWorker.register('sw.js').catch(function () { /* 没有也能用，只是没有离线外壳 */ });
  load();
})();