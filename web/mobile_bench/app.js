/* 牛牛策略（手机只读版）：下载加密快照 data.json → 用口令在本机解密 → 显示。没有任何写入，也不向任何地方发送数据。
   加密格式见 src/quantlab/dipbuy/mobile_export.py：AES-256-GCM，密钥 = PBKDF2-SHA256(口令, 盐, 迭代次数)，附加认证数据 = 格式串。 */
(function () {
  'use strict';

  var ENVELOPE_FORMAT = 'niuniu-mobile-envelope-v1';
  var SNAPSHOT_FORMAT = 'niuniu-mobile-snapshot-v1';
  var LS_PASS = 'niuniu_mobile_pass';
  var LS_PREF = 'niuniu_mobile_pref';
  var app = document.getElementById('app');

  var state = { phase: 'loading', snap: null, env: null, error: '', tab: 'signal', loadedAt: 0,
                pick: { signal: 'fusion', forward: 'fusion', holdings: 'D' } };

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
  function b64(s) { var bin = atob(s), out = new Uint8Array(bin.length); for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i); return out; }

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

  function load(passFromUser) {
    state.phase = 'loading'; render();
    return fetch('data.json?ts=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('下载失败（' + r.status + '）'); return r.json(); })
      .then(function (env) {
        state.env = env;
        var pass = passFromUser || ls(true, LS_PASS);
        if (!pass) { state.phase = 'locked'; state.error = ''; render(); return null; }
        return decrypt(env, pass).then(function (snap) {
          if (passFromUser) ls(false, LS_PASS, passFromUser);
          state.snap = snap; state.phase = 'ready'; state.loadedAt = Date.now(); render();
        }, function (e) {
          if (e && e.name === 'OperationError') { ls(false, LS_PASS, null); state.error = '口令不对'; } else { state.error = e.message || String(e); }
          state.phase = 'locked'; render();
        });
      })
      .catch(function (e) { state.phase = 'error'; state.error = (e && e.message) || String(e); render(); });
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

  // ------------------------------------------------------------------ 图
  function chart(vals, labels, opt) {
    opt = opt || {};
    var pts = [];
    for (var i = 0; i < vals.length; i++) if (isNum(vals[i])) pts.push([i, vals[i]]);
    if (pts.length < 2) return '<p class="empty">曲线要至少两个点。</p>';
    var W = 320, H = opt.h || 120, L = 4, R = 38, T = 8, B = 16;
    var min = Math.min.apply(null, pts.map(function (p) { return p[1]; })), max = Math.max.apply(null, pts.map(function (p) { return p[1]; }));
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
    svg += '<text x="' + (W - R + 4) + '" y="' + (T + 8) + '">' + esc(fmt(max - span * 0.06 / 1.12)) + '</text>';
    svg += '<text x="' + (W - R + 4) + '" y="' + (H - B) + '">' + esc(fmt(min + span * 0.06 / 1.12)) + '</text>';
    if (labels && labels.length) {
      svg += '<text x="' + L + '" y="' + (H - 3) + '">' + esc(labels[0]) + '</text>';
      svg += '<text x="' + (W - R) + '" y="' + (H - 3) + '" text-anchor="end">' + esc(labels[labels.length - 1]) + '</text>';
    }
    return svg + '</svg>';
  }

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
        html += '<tr><td>' + k + ' ' + esc(sl.name) + '</td><td>' + esc(sl.detail || '—') + (sl.blacklisted ? ' <span class="tag">黑名单</span>' : '') + '</td><td class="n num">' + num(sl.z, 2) +
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

    var picks = sig.picks || [];
    var plan = picks.filter(function (p) { return p.in_plan !== false; });
    html += '<section class="card"><h2>候选股<small>' + (picks.length ? '计划买 ' + plan.length + ' 只，其余备选' : '') + '</small></h2>';
    if (!picks.length) {
      html += '<p class="empty">' + (sig.gate_open ? '闸门开了，但今天没有可买的股票。' : '闸门没开，没有候选。') + '</p>';
    } else {
      html += '<div class="scroll"><table class="tbl"><thead><tr><th>#</th><th>股票</th>' + (isFusion ? '<th>层</th>' : '') + '<th class="n">收盘</th><th class="n">20 日</th>' +
        (isFusion && picks.some(function (p) { return p.plan_shares != null; }) ? '<th class="n">股数</th>' : '') + '</tr></thead><tbody>';
      picks.forEach(function (p) {
        html += '<tr' + (p.in_plan === false ? ' class="muted"' : '') + '><td class="num">' + esc(p.rank) + '</td><td>' + esc(short(p.code)) + '<span class="nm">' + esc(p.name || '') + (p.group ? ' · ' + esc(p.group) : '') + '</span></td>' +
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
        chart(rec.map(function (r) { return r[key]; }), rec.map(function (r) { return md(r.date); }), { base: sig.z_threshold, label: '大盘 z', h: 100 }) + '</section>';
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
    var html = '<div class="banner ok">前向跟踪 = 参数冻结后，每天把当天的信号记下来，之后用真实行情结算。只有这个数字才能说明策略在样本外是否有效；样本内回测不算。</div>';
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

    if (f.portfolio && f.portfolio.curve) {
      var c = f.portfolio.curve, eq = c.equity, last = eq.filter(isNum).slice(-1)[0];
      html += '<section class="card"><h2>前向净值<small>本金 = 1，含成本</small></h2><div class="tiles">' +
        '<div class="tile"><span>累计</span><b>' + pctc(isNum(last) ? last - 1 : null, 1) + '</b></div>' +
        '<div class="tile"><span>最大回撤</span><b>' + pctc(maxDrawdown(eq), 1) + '</b></div></div>' +
        chart(eq, c.dates.map(md), { base: 1, label: '前向净值' }) +
        ((f.portfolio.mismatched || []).length ? '<p class="small muted">有 ' + f.portfolio.mismatched.length + ' 天的记录和现在重算的候选不完全一致（数据修订等），以记录为准。</p>' : '') + '</section>';
      var op = f.portfolio.open_positions || [];
      if (op.length) {
        html += '<section class="card"><h2>模拟持仓<small>' + op.length + ' 只</small></h2><div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th>信号日</th><th class="n">浮盈</th></tr></thead><tbody>' +
          op.map(function (p) { return '<tr><td>' + esc(short(p.code)) + '<span class="nm">' + esc(p.name || p.sleeve || '') + '</span></td><td class="num">' + md(p.signal) + '</td><td class="n">' + pctc(p.ret != null ? p.ret : p.mtm, 1) + '</td></tr>'; }).join('') +
          '</tbody></table></div></section>';
      }
    }
    var recs = f.records || [];
    html += '<section class="card"><h2>信号记录<small>最近 ' + recs.length + ' 条</small></h2>';
    recs.forEach(function (r) {
      var ret = r.status === 'closed' ? r.mean_ret : r.mean_mtm;
      html += '<details><summary><b class="num">' + md(r.signal_date) + '</b> <span class="tag">' + esc(STATUS[r.status] || r.status) + '</span> ' +
        (r.fired && r.fired.length ? '<span class="muted small">' + esc(r.fired.join('/')) + '</span> ' : '') + pctc(ret, 2) + '</summary>' +
        '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th>层</th><th class="n">收益</th></tr></thead><tbody>' +
        (r.rows || []).map(function (p) { return '<tr><td>' + esc(short(p.code)) + '<span class="nm">' + esc(p.name || '') + '</span></td><td>' + esc(p.sleeve || '') + '</td><td class="n">' + (p.status === 'not_filled' ? '<span class="muted">没买进</span>' : pctc(p.ret != null ? p.ret : p.mtm, 1)) + '</td></tr>'; }).join('') +
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

    html += '<section class="card"><h2>' + esc(p.plan_day ? md(p.plan_day) + '（' + wd(p.plan_day) + '）' : '明天') + '要做什么<small>策略 ' + esc(v) + '</small></h2>';
    html += '<div class="kv"><span>账户总资产</span><span class="num">' + num(h.equity_wan, 1) + ' 万</span><span>持仓</span><span class="num">' + (h.n_holdings || 0) + ' 只</span></div>';
    (p.notes || []).forEach(function (t) { html += '<p class="small muted">· ' + esc(t) + '</p>'; });
    html += '</section>';

    html += '<section class="card"><h2>卖出<small>' + (p.sells || []).length + ' 只</small></h2>';
    if (!(p.sells || []).length) html += '<p class="empty">没有要卖的。</p>';
    else html += '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th class="n">股数</th><th class="n">盈亏</th><th>说明</th></tr></thead><tbody>' + p.sells.map(function (r) {
      return '<tr><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + '</span></td><td class="n num">' + money(r.shares) + '</td><td class="n">' + pctc(r.pnl, 1) + '</td><td class="wrap">' + esc(r.advice) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
    html += '</section>';

    html += '<section class="card"><h2>买入<small>' + (p.buys || []).length + ' 只' + (p.new_money ? ' · 约 ' + money(p.new_money) + ' 元' : '') + '</small></h2>';
    if (p.stale) html += '<p class="empty">数据已过期，不出买入计划。</p>';
    else if (!(p.buys || []).length) html += '<p class="empty">' + (p.gate_open ? '闸门开了，但没有可买的（名额满、仓位上限或买不起一手）。' : '闸门没开，不买。') + '</p>';
    else html += '<div class="scroll"><table class="tbl"><thead><tr><th>层</th><th>股票</th><th class="n">股数</th><th class="n">金额</th><th class="n">收盘</th></tr></thead><tbody>' + p.buys.map(function (r) {
      return '<tr><td>' + esc(r.sleeve) + '</td><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + '</span></td><td class="n num">' + money(r.shares) + '</td><td class="n num">' + money(r.amount) + '</td><td class="n num">' + num(r.close, 2) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
    if ((p.spares || []).length) html += '<details><summary>备选 ' + p.spares.length + ' 只（买不进时顺延）</summary><p class="small">' + p.spares.map(function (r) { return esc(r.sleeve + short(r.code) + ' ' + (r.name || '')); }).join('、') + '</p></details>';
    html += '</section>';

    var rows = h.holdings || [];
    html += '<section class="card"><h2>全部持仓<small>' + rows.length + ' 只</small></h2>';
    if (!rows.length) html += '<p class="empty">还没有录入持仓。在电脑的“我的持仓”里录入，推送后这里会显示。</p>';
    else html += '<div class="scroll"><table class="tbl"><thead><tr><th>股票</th><th class="n">股数</th><th class="n">市值</th><th class="n">盈亏</th><th>状态</th></tr></thead><tbody>' + rows.map(function (r) {
      var st = HSTAT[r.status] || [r.status, ''];
      return '<tr><td>' + esc(short(r.code)) + '<span class="nm">' + esc(r.name || '') + (r.sleeve ? ' · ' + esc(r.sleeve) + '层' : '') + '</span></td><td class="n num">' + money(r.shares) + '</td><td class="n num">' + money(r.value) + '</td><td class="n">' + pctc(r.pnl, 1) + '</td><td><span class="tag ' + st[1] + '">' + st[0] + '</span>' +
        (r.days_held != null ? '<span class="nm">第 ' + r.days_held + ' 天</span>' : '') + '</td></tr>';
    }).join('') + '</tbody></table></div>';
    return html + '</section>';
  }

  // ------------------------------------------------------------------ 说明
  function viewGuide(s) {
    var html = '<section class="card"><h2>怎么看这个页面</h2><ul class="plain">' +
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
    if (s.results && s.results.rows) {
      html += '<section class="card"><h2>回测对照<small>2008 起，扣成本，1 倍</small></h2><div class="scroll"><table class="tbl"><thead><tr>' + s.results.head.map(function (h, i) { return '<th class="' + (i ? 'n' : '') + '">' + esc(h) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        s.results.rows.map(function (r) { return '<tr>' + r.map(function (c, i) { return '<td class="' + (i ? 'n num' : 'wrap') + '">' + esc(c) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>' +
        '<p class="small muted">“含退市”指补上了 290 只退市股的面板。</p></section>';
    }
    html += '<section class="card"><h2>这台手机</h2><p class="small muted">快照生成于 ' + esc(dt(s.generated_at)) + '。</p>' +
      '<button class="btn" id="forget">忘记口令并锁定</button></section>';
    return html;
  }

  // ------------------------------------------------------------------ 外壳
  var TABS = [
    ['signal', '今日信号', '<path d="M13 3 5 13h6l-1 8 8-10h-6z"/>'],
    ['forward', '前向跟踪', '<path d="M3 17l5-5 4 4 8-9"/><path d="M3 21h18"/>'],
    ['holdings', '我的持仓', '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>'],
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
      app.innerHTML = '<div class="gate"><h1>牛牛策略</h1><p class="muted">输入口令查看。口令在电脑上：<code>artifacts/_home/mobile_passphrase</code></p>' + d +
        '<form id="unlock" autocomplete="off"><input id="pass" type="password" placeholder="口令" autocapitalize="off" autocorrect="off" spellcheck="false" aria-label="口令">' +
        '<div class="err" id="err" role="alert">' + esc(state.error) + '</div><button class="btn primary" type="submit">解锁</button></form></div>';
      return bind();
    }
    var s = state.snap;
    var body = state.tab === 'signal' ? viewSignal(s) : state.tab === 'forward' ? viewForward(s) : state.tab === 'holdings' ? viewHoldings(s) : viewGuide(s);
    var fr = freshness(s).map(function (b) { return '<div class="banner ' + b.k + '">' + b.t + '</div>'; }).join('');
    app.innerHTML = '<header class="top"><div><h1>牛牛策略</h1><div class="sub">快照 ' + esc(dt(s.generated_at)) + ' · 纸面记录</div></div><button class="btn" id="refresh">刷新</button></header>' +
      '<main>' + (state.tab === 'guide' ? '' : fr) + body + '</main>' +
      '<nav class="tabs" aria-label="页面">' + TABS.map(function (t) {
        return '<button data-tab="' + t[0] + '"' + (t[0] === state.tab ? ' aria-current="page"' : '') + '><svg viewBox="0 0 24 24" aria-hidden="true">' + t[2] + '</svg>' + t[1] + '</button>';
      }).join('') + '</nav>';
    bind();
  }

  function savePref() { ls(false, LS_PREF, JSON.stringify({ tab: state.tab, pick: state.pick })); }

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
      var inp = q('#pass'); if (inp) inp.focus();
    }
    var retry = q('#retry'); if (retry) retry.addEventListener('click', function () { load(); });
    var rf = q('#refresh'); if (rf) rf.addEventListener('click', function () { var y = window.scrollY; load().then(function () { window.scrollTo(0, y); }); });
    var fg = q('#forget'); if (fg) fg.addEventListener('click', function () { ls(false, LS_PASS, null); state.snap = null; state.phase = 'locked'; state.error = ''; render(); });
    Array.prototype.forEach.call(app.querySelectorAll('[data-tab]'), function (b) {
      b.addEventListener('click', function () { state.tab = b.getAttribute('data-tab'); savePref(); render(); window.scrollTo(0, 0); });
    });
    Array.prototype.forEach.call(app.querySelectorAll('[data-pick]'), function (b) {
      b.addEventListener('click', function () { state.pick[b.getAttribute('data-group')] = b.getAttribute('data-pick'); savePref(); var y = window.scrollY; render(); window.scrollTo(0, y); });
    });
  }

  // ------------------------------------------------------------------ 启动
  try {
    var pref = JSON.parse(ls(true, LS_PREF) || 'null');
    if (pref && typeof pref === 'object') {
      if (['signal', 'forward', 'holdings', 'guide'].indexOf(pref.tab) >= 0) state.tab = pref.tab;
      if (pref.pick && typeof pref.pick === 'object') ['signal', 'forward', 'holdings'].forEach(function (k) { if (typeof pref.pick[k] === 'string') state.pick[k] = pref.pick[k]; });
    }
  } catch (e) { /* 偏好坏了就用默认 */ }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && state.phase === 'ready' && Date.now() - state.loadedAt > 10 * 60 * 1000) load();
  });
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) navigator.serviceWorker.register('sw.js').catch(function () { /* 没有也能用，只是没有离线外壳 */ });
  load();
})();
