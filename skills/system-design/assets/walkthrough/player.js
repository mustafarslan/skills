/* system-design walkthrough player.
   Reads the steps data embedded by scripts/render_walkthrough.py (<script id="wt-data">) and
   draws one step at a time: metric chips, an SVG stage with animated packets, a step card and a
   step timeline. No dependencies, no network. House style: greys, one yellow focus node, state
   carried by glyph + word, packet kinds carried by shape.

   Layout: nodes sit in grid cells chosen by the author. Edges run through the gutters between
   cells, so an edge never crosses a node; parallel edges in one gutter get their own lane. */
(function () {
  'use strict';

  var W = 160, H = 56, GX = 104, GY = 84, PAD = 56, LANE = 8, PORT = 12;
  var NS = 'http://www.w3.org/2000/svg';
  var GLYPH = { down: '✕ down', degraded: '! degraded', new: '+ new', removed: '− removed', ok: '' };
  var CHAPTER = { frame: 'Frame', numbers: 'Numbers', draft: 'Draft', problem: 'Problem', fix: 'Fix',
                  'case': 'Case', tradeoff: 'Trade-off', scale: '10x', recap: 'Recap' };
  var CALLOUT = { insight: ['◆', 'Key idea'], tip: ['→', 'Good to know'], warn: ['!', 'Watch out'] };
  var PACKET_NAME = { req: 'request', res: 'response', fail: 'failed request', retry: 'retry',
                      async: 'event / message', heartbeat: 'heartbeat' };

  // Easing from design-video/assets/lib/motion.js (ease.out / ease.inOut), as CSS-free functions.
  function bezier(x1, y1, x2, y2) {
    function poly(a1, a2) { return function (s) { return 3 * a1 * s * (1 - s) * (1 - s) + 3 * a2 * s * s * (1 - s) + s * s * s; }; }
    var X = poly(x1, x2), Y = poly(y1, y2);
    return function (x) {
      x = Math.min(1, Math.max(0, x));
      if (x === 0 || x === 1) return x;
      var lo = 0, hi = 1;
      for (var i = 0; i < 30; i++) { var mid = (lo + hi) / 2; if (X(mid) < x) lo = mid; else hi = mid; }
      return Y((lo + hi) / 2);
    };
  }
  var easeInOut = bezier(0.65, 0, 0.35, 1);

  var dataEl = document.getElementById('wt-data');
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent);
  var steps = data.steps || [];
  var nodesById = {}, edgesById = {}, metricsById = {};
  (data.nodes || []).forEach(function (n) { nodesById[n.id] = n; });
  (data.edges || []).forEach(function (e) { edgesById[e.id] = e; });
  (data.metrics || []).forEach(function (m) { metricsById[m.id] = m; });
  var grid = data.grid || { cols: 6, rows: 4 };

  var params = new URLSearchParams(location.search);
  var mq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var still = params.get('motion') === 'off' || !!(mq && mq.matches);
  var themeParam = params.get('theme');
  if (themeParam === 'light' || themeParam === 'dark') document.documentElement.setAttribute('data-theme', themeParam);

  // ---------- small DOM helpers ----------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function svg(tag, attrs, text) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  }

  // ---------- geometry ----------
  function cellOf(step, id) { return (step.cells && step.cells[id]) || nodesById[id].cell; }
  function rectOf(cell) {
    var x = PAD + cell[0] * (W + GX), y = PAD + cell[1] * (H + GY);
    return { x: x, y: y, w: W, h: H, cx: x + W / 2, cy: y + H / 2 };
  }
  function gv(k) { return PAD + k * (W + GX) - GX / 2; }
  function gh(k) { return PAD + k * (H + GY) - GY / 2; }
  // One frame for every step: the box around every node and edge any step shows, so the
  // diagram never jumps or rescales between steps.
  var frameBox = null;
  function computeFrame() {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    function add(x, y) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    steps.forEach(function (s) {
      var lay = layout(s);
      Object.keys(lay.rects).forEach(function (id) {
        var r = lay.rects[id];
        var z = nodesById[id].zone ? 16 : 0;
        add(r.x - 28 - z, r.y - 40 - z); add(r.x + r.w + 28 + z, r.y + r.h + 32 + z);
      });
      lay.edges.forEach(function (it) { it.pts.forEach(function (p) { add(p[0] - 12, p[1] - 14); add(p[0] + 12, p[1] + 12); }); });
    });
    if (!isFinite(x0)) { x0 = 0; y0 = 0; x1 = 400; y1 = 200; }
    frameBox = { x: Math.floor(x0), y: Math.floor(y0), w: Math.ceil(x1 - x0), h: Math.ceil(y1 - y0) };
  }

  function visibleEdges(step) {
    var vis = {}; step.show.forEach(function (id) { vis[id] = true; });
    var hidden = {}; (step.hide_edges || []).forEach(function (id) { hidden[id] = true; });
    return (data.edges || []).filter(function (e) { return vis[e.from] && vis[e.to] && !hidden[e.id]; });
  }

  // Abstract route of one edge: which side it leaves and enters, and which gutters it uses.
  function plan(e, a, b) {
    var ca = a[0], ra = a[1], cb = b[0], rb = b[1];
    var right = cb > ca, down = rb > ra;
    if (ra === rb && Math.abs(ca - cb) === 1)
      return { kind: 'h1', from: right ? 'r' : 'l', to: right ? 'l' : 'r', g: [['v', Math.max(ca, cb)]] };
    if (ca === cb && Math.abs(ra - rb) === 1)
      return { kind: 'v1', from: down ? 'b' : 't', to: down ? 't' : 'b', g: [['h', Math.max(ra, rb)]] };
    if (ra === rb)
      return { kind: 'hh', from: right ? 'r' : 'l', to: right ? 'l' : 'r',
               g: [['v', right ? ca + 1 : ca], ['h', ra], ['v', right ? cb : cb + 1]] };
    if (ca === cb)
      return { kind: 'vv', from: down ? 'b' : 't', to: down ? 't' : 'b',
               g: [['h', down ? ra + 1 : ra], ['v', ca + 1], ['h', down ? rb : rb + 1]] };
    if (e.route === 'vh')
      return { kind: 'Lv', from: down ? 'b' : 't', to: right ? 'l' : 'r',
               g: [['h', down ? ra + 1 : ra], ['v', right ? cb : cb + 1]] };
    return { kind: 'L', from: right ? 'r' : 'l', to: down ? 't' : 'b',
             g: [['v', right ? ca + 1 : ca], ['h', down ? rb : rb + 1]] };
  }

  function layout(step) {
    var rects = {};
    step.show.forEach(function (id) { rects[id] = rectOf(cellOf(step, id)); });
    var edges = visibleEdges(step);
    var plans = edges.map(function (e) { return { e: e, p: plan(e, cellOf(step, e.from), cellOf(step, e.to)) }; });

    // Ports: spread the edges that share one side of a node, ordered by where the other end is.
    var sides = {};
    plans.forEach(function (it) {
      [['from', it.e.from, it.e.to], ['to', it.e.to, it.e.from]].forEach(function (end) {
        var side = it.p[end[0]], key = end[1] + ':' + side, other = rects[end[2]];
        (sides[key] = sides[key] || []).push({ it: it, end: end[0], sort: side === 'l' || side === 'r' ? other.cy : other.cx });
      });
    });
    Object.keys(sides).forEach(function (key) {
      var list = sides[key].sort(function (p, q) { return p.sort - q.sort; });
      list.forEach(function (x, i) { x.it[x.end + 'Off'] = (i - (list.length - 1) / 2) * PORT; });
    });
    // Lanes: edges that share one gutter get their own offset in it.
    var lanes = {};
    plans.forEach(function (it, idx) { it.p.g.forEach(function (g, gi) { (lanes[g[0] + g[1]] = lanes[g[0] + g[1]] || []).push([idx, gi]); }); });
    var laneOff = {};
    Object.keys(lanes).forEach(function (k) {
      var list = lanes[k];
      list.forEach(function (x, i) { laneOff[x[0] + ':' + x[1]] = (i - (list.length - 1) / 2) * LANE; });
    });

    function port(r, side, off) {
      if (side === 'r') return [r.x + r.w, r.cy + off];
      if (side === 'l') return [r.x, r.cy + off];
      if (side === 't') return [r.cx + off, r.y];
      return [r.cx + off, r.y + r.h];
    }
    var out = plans.map(function (it, idx) {
      var A = rects[it.e.from], B = rects[it.e.to], p = it.p;
      var a = port(A, p.from, it.fromOff || 0), b = port(B, p.to, it.toOff || 0);
      function G(i) { var g = p.g[i], o = laneOff[idx + ':' + i] || 0; return g[0] === 'v' ? gv(g[1]) + o : gh(g[1]) + o; }
      var pts;
      if (p.kind === 'h1') pts = [a, [G(0), a[1]], [G(0), b[1]], b];
      else if (p.kind === 'v1') pts = [a, [a[0], G(0)], [b[0], G(0)], b];
      else if (p.kind === 'hh') pts = [a, [G(0), a[1]], [G(0), G(1)], [G(2), G(1)], [G(2), b[1]], b];
      else if (p.kind === 'vv') pts = [a, [a[0], G(0)], [G(1), G(0)], [G(1), G(2)], [b[0], G(2)], b];
      else if (p.kind === 'Lv') pts = [a, [a[0], G(0)], [G(1), G(0)], [G(1), b[1]], b];
      else pts = [a, [G(0), a[1]], [G(0), G(1)], [b[0], G(1)], b];
      return { e: it.e, pts: simplify(pts) };
    });
    return { rects: rects, edges: out };
  }

  function simplify(pts) {
    var out = [];
    pts.forEach(function (p) {
      var q = out[out.length - 1];
      if (q && Math.abs(q[0] - p[0]) < 0.01 && Math.abs(q[1] - p[1]) < 0.01) return;
      out.push(p);
    });
    for (var i = out.length - 2; i > 0; i--) {
      var a = out[i - 1], b = out[i], c = out[i + 1];
      if ((Math.abs(a[0] - b[0]) < 0.01 && Math.abs(b[0] - c[0]) < 0.01) ||
          (Math.abs(a[1] - b[1]) < 0.01 && Math.abs(b[1] - c[1]) < 0.01)) out.splice(i, 1);
    }
    return out;
  }
  function pathLen(pts) {
    var L = 0;
    for (var i = 1; i < pts.length; i++) L += Math.abs(pts[i][0] - pts[i - 1][0]) + Math.abs(pts[i][1] - pts[i - 1][1]);
    return L;
  }
  function pointAt(pts, f) {
    var target = pathLen(pts) * Math.min(1, Math.max(0, f));
    for (var i = 1; i < pts.length; i++) {
      var seg = Math.abs(pts[i][0] - pts[i - 1][0]) + Math.abs(pts[i][1] - pts[i - 1][1]);
      if (target <= seg || i === pts.length - 1) {
        var k = seg ? Math.min(1, target / seg) : 0;
        return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k];
      }
      target -= seg;
    }
    return pts[pts.length - 1];
  }
  function longestMid(pts) {
    var best = 0, mid = pts[0], horiz = true;
    for (var i = 1; i < pts.length; i++) {
      var seg = Math.abs(pts[i][0] - pts[i - 1][0]) + Math.abs(pts[i][1] - pts[i - 1][1]);
      if (seg > best) { best = seg; mid = [(pts[i][0] + pts[i - 1][0]) / 2, (pts[i][1] + pts[i - 1][1]) / 2]; horiz = pts[i][1] === pts[i - 1][1]; }
    }
    return { p: mid, horiz: horiz };
  }
  function d(pts) { return pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '); }

  // ---------- values and chips ----------
  function num(v) {
    if (v == null) return null;
    var m = String(v).replace(/,/g, '').match(/-?\d+(\.\d+)?\s*([kmgt](?![a-z]))?/i);
    if (!m) return null;
    var n = parseFloat(m[0]);
    var mult = { k: 1e3, m: 1e6, g: 1e9, t: 1e12 }[(m[2] || '').toLowerCase()] || 1;
    return n * mult;
  }
  function breached(def, value) {
    if (!def || !def.target) return false;
    var m = String(def.target).match(/^\s*(<=|>=|<|>|≤|≥)\s*(.+)$/);
    if (!m) return false;
    var t = num(m[2]), v = num(value);
    if (t == null || v == null) return false;
    var op = m[1];
    if (op === '<') return !(v < t);
    if (op === '<=' || op === '≤') return !(v <= t);
    if (op === '>') return !(v > t);
    return !(v >= t);
  }
  function metricAt(id, i) {
    for (var k = i; k >= 0; k--) if (steps[k].metrics && steps[k].metrics[id] != null) return String(steps[k].metrics[id]);
    return null;
  }

  // ---------- SVG scene ----------
  var svgSeq = 0;
  function arrowDefs(root) {
    var id = 'wt-arrow-' + (++svgSeq);
    root.setAttribute('data-arrow', id);
    var defs = svg('defs', {});
    var mk = svg('marker', { id: id, viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 8, markerHeight: 8, orient: 'auto-start-reverse' });
    mk.appendChild(svg('path', { d: 'M0,0 L8,4 L0,8 z', 'class': 'wt-arrowhead' }));
    defs.appendChild(mk);
    root.appendChild(defs);
  }

  function drawNode(g, n, r, step, hasGauge) {
    var focus = step.focus === n.id;
    var state = (step.state || {})[n.id];
    var cls = 'wt-shape' + (focus ? ' wt-focus' : '') + (n.type === 'ext' || n.type === 'actor' ? ' wt-ext' : '') +
              (state === 'down' ? ' wt-down' : '') + (state === 'removed' ? ' wt-removed' : '');
    var x = r.x, y = r.y, w = r.w, h = r.h, ty = 0;
    if (n.type === 'db' || n.type === 'cache') {
      g.appendChild(svg('path', { 'class': cls, d: 'M' + x + ',' + (y + 8) + ' a' + w / 2 + ',8 0 0,1 ' + w + ',0 v' + (h - 16) +
                                  ' a' + w / 2 + ',8 0 0,1 ' + (-w) + ',0 z' }));
      g.appendChild(svg('path', { 'class': 'wt-inner' + (focus ? ' wt-fx-stroke' : ''), d: 'M' + x + ',' + (y + 8) + ' a' + w / 2 + ',8 0 0,0 ' + w + ',0' }));
      ty = 6;
    } else {
      g.appendChild(svg('rect', { 'class': cls, x: x, y: y, width: w, height: h, rx: 2 }));
      if (n.type === 'queue') g.appendChild(svg('path', { 'class': 'wt-inner' + (focus ? ' wt-fx-stroke' : ''), d: 'M' + (x + 8) + ',' + (y + 8) + ' v' + (h - 16) + ' M' + (x + w - 8) + ',' + (y + 8) + ' v' + (h - 16) }));
    }
    var tx = x + (n.type === 'queue' ? 18 : 12);
    g.appendChild(svg('text', { 'class': 'wt-name' + (focus ? ' wt-fx' : ''), x: tx, y: y + 24 + ty }, n.label));
    if (n.sub) g.appendChild(svg('text', { 'class': 'wt-sub' + (focus ? ' wt-fx' : ''), x: tx, y: y + 42 + ty }, n.sub));
    if (state === 'down') {
      g.appendChild(svg('path', { 'class': 'wt-cross', d: 'M' + (x + w - 22) + ',' + (y + 8) + ' l14,14 m0,-14 l-14,14' }));
    }
    if (state && GLYPH[state]) {
      var sl = GLYPH[state], sy = y + h + (hasGauge ? 30 : 20), sw = sl.length * 7.4 + 10;
      g.appendChild(svg('rect', { 'class': 'wt-halo', x: r.cx - sw / 2, y: sy - 12, width: sw, height: 16 }));
      g.appendChild(svg('text', { 'class': 'wt-state', x: r.cx, y: sy, 'text-anchor': 'middle' }, sl));
    }
  }

  function drawOverlay(g, o, r, focus) {
    if (o.gauge != null) {
      var pct = Math.max(0, Math.min(100, +o.gauge));
      g.appendChild(svg('rect', { 'class': 'wt-gauge-bg', x: r.x, y: r.y + r.h + 6, width: r.w, height: 5 }));
      g.appendChild(svg('rect', { 'class': 'wt-gauge', x: r.x, y: r.y + r.h + 6, width: r.w * pct / 100, height: 5 }));
    }
    if (o.label) {
      var text = String(o.label), strong = /^[!✕]/.test(text);
      var tw = Math.max(40, text.length * 7.2 + 16);
      var bx = r.cx - tw / 2, by = r.y - 30;
      g.appendChild(svg('rect', { 'class': 'wt-badge' + (strong ? ' wt-badge-strong' : ''), x: bx, y: by, width: tw, height: 20, rx: 2 }));
      g.appendChild(svg('text', { 'class': 'wt-badge-text' + (strong ? ' wt-badge-text-strong' : ''), x: r.cx, y: by + 14, 'text-anchor': 'middle' }, text));
    }
  }

  function drawZones(g, step, rects) {
    (data.zones || []).forEach(function (z) {
      var members = step.show.filter(function (id) { return nodesById[id].zone === z.id; });
      if (!members.length) return;
      var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      members.forEach(function (id) { var r = rects[id]; x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y); x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.h); });
      var zx = x0 - 24, zy = y0 - 40, zw = x1 - x0 + 48, zh = y1 - y0 + 64;
      var down = (step.zone_state || {})[z.id] === 'down';
      g.appendChild(svg('rect', { 'class': 'wt-zone' + (down ? ' wt-zone-down' : ''), x: zx, y: zy, width: zw, height: zh, rx: 2 }));
      g.appendChild(svg('text', { 'class': 'wt-zone-label', x: zx + 10, y: zy + 16 }, z.label + (down ? '  ✕ down' : '')));
    });
  }

  function drawEdges(g, step, lay, arrow) {
    var cut = {}; (step.cut || []).forEach(function (id) { cut[id] = true; });
    lay.edges.forEach(function (it) {
      var e = it.e;
      var cls = 'wt-edge' + (e.mode === 'async' ? ' wt-async' : '') + (cut[e.id] ? ' wt-cut' : '');
      g.appendChild(svg('path', { 'class': cls, d: d(it.pts), 'marker-end': 'url(#' + arrow + ')', 'data-edge': e.id }));
      var mid = longestMid(it.pts);
      var text = cut[e.id] ? (e.label ? e.label + '  ✕ cut' : '✕ cut') : e.label;
      if (text) {
        var tw = text.length * 7.2 + 8, lx = mid.p[0], ly = mid.p[1];
        if (!mid.horiz) { lx += tw / 2 + 4; }
        else { ly -= 10; }
        g.appendChild(svg('rect', { 'class': 'wt-halo', x: lx - tw / 2, y: ly - 9, width: tw, height: 15 }));
        g.appendChild(svg('text', { 'class': cut[e.id] ? 'wt-cut-label' : 'wt-elabel', x: lx, y: ly + 3, 'text-anchor': 'middle' }, text));
      }
    });
  }

  function packetShape(kind, x, y, extra) {
    var gEl = svg('g', { 'class': 'wt-pkt wt-pkt-' + kind, transform: 'translate(' + x.toFixed(1) + ',' + y.toFixed(1) + ')' });
    if (kind === 'req') gEl.appendChild(svg('circle', { r: 4.5, 'class': 'wt-pkt-fill' }));
    else if (kind === 'res') gEl.appendChild(svg('circle', { r: 4.5, 'class': 'wt-pkt-hollow' }));
    else if (kind === 'retry') gEl.appendChild(svg('circle', { r: 5, 'class': 'wt-pkt-hollow wt-pkt-dashed' }));
    else if (kind === 'async') gEl.appendChild(svg('path', { d: 'M0,-5.5 L5.5,0 L0,5.5 L-5.5,0 z', 'class': 'wt-pkt-fill' }));
    else if (kind === 'heartbeat') gEl.appendChild(svg('circle', { r: 3, 'class': 'wt-pkt-hollow' }));
    else if (kind === 'fail') {
      gEl.appendChild(svg('rect', { x: -5.5, y: -5.5, width: 11, height: 11, 'class': 'wt-pkt-fill' }));
      gEl.appendChild(svg('path', { d: 'M-3,-3 L3,3 M3,-3 L-3,3', 'class': 'wt-pkt-x' }));
    }
    if (extra && extra.opacity != null) gEl.setAttribute('opacity', extra.opacity.toFixed(2));
    return gEl;
  }

  function flowsFor(step, lay) {
    var byId = {}; lay.edges.forEach(function (it) { byId[it.e.id] = it; });
    return (step.flows || []).filter(function (f) { return byId[f.edge]; }).map(function (f, i) {
      var it = byId[f.edge];
      var reverse = f.reverse != null ? !!f.reverse : f.packet === 'res';
      var pts = reverse ? it.pts.slice().reverse() : it.pts;
      var len = pathLen(pts);
      var rate = f.rate || 1;
      return { f: f, pts: pts, travel: Math.min(2.4, Math.max(0.7, len / 150)), period: 1 / rate, phase: (i * 0.37) % (1 / rate) };
    });
  }

  function drawHeld(g, flows) {
    flows.forEach(function (fl) {
      var n = fl.f.held | 0;
      if (!n) return;
      var len = pathLen(fl.pts), shown = Math.max(1, Math.min(n, 10, Math.floor((len - 24) / 9)));
      for (var k = 0; k < shown; k++) {
        var p = pointAt(fl.pts, 1 - (14 + k * 9) / len);
        g.appendChild(packetShape(fl.f.packet === 'async' ? 'async' : 'req', p[0], p[1]));
      }
      var q = pointAt(fl.pts, 1 - (14 + (shown - 1) * 4.5) / len);
      var label = n + ' waiting';
      g.appendChild(svg('rect', { 'class': 'wt-halo', x: q[0] - label.length * 3.6 - 4, y: q[1] + 8, width: label.length * 7.2 + 8, height: 15 }));
      g.appendChild(svg('text', { 'class': 'wt-elabel wt-held', x: q[0], y: q[1] + 19, 'text-anchor': 'middle' }, label));
    });
  }

  function drawStaticPackets(g, flows) {
    flows.forEach(function (fl) {
      if (fl.f.held) return;
      var p = pointAt(fl.pts, fl.f.packet === 'fail' ? 0.6 : 0.35);
      g.appendChild(packetShape(fl.f.packet, p[0], p[1]));
    });
  }

  function renderScene(i, opts) {
    opts = opts || {};
    var step = steps[i];
    var lay = layout(step);
    if (!frameBox) computeFrame();
    var fb = frameBox;
    var root = svg('svg', { viewBox: fb.x + ' ' + fb.y + ' ' + fb.w + ' ' + fb.h, width: '100%', role: 'img', 'class': 'wt-svg',
                            'aria-labelledby': 'wt-t' + i + (opts.print ? 'p' : '') + ' wt-d' + i + (opts.print ? 'p' : '') });
    root.appendChild(svg('title', { id: 'wt-t' + i + (opts.print ? 'p' : '') }, 'Step ' + (i + 1) + ': ' + step.title));
    var desc = 'Shows ' + step.show.map(function (id) { return nodesById[id].label + ((step.state || {})[id] ? ' (' + step.state[id] + ')' : ''); }).join(', ') +
               (step.focus ? '. Focus: ' + nodesById[step.focus].label + '.' : '.');
    root.appendChild(svg('desc', { id: 'wt-d' + i + (opts.print ? 'p' : '') }, desc));
    arrowDefs(root);
    root.appendChild(svg('rect', { 'class': 'wt-stage', x: fb.x, y: fb.y, width: fb.w, height: fb.h }));
    var gz = svg('g', {}), ge = svg('g', {}), gn = svg('g', {}), gp = svg('g', { 'class': 'wt-packets' });
    root.appendChild(gz); root.appendChild(ge); root.appendChild(gn);
    drawZones(gz, step, lay.rects);
    drawEdges(ge, step, lay, root.getAttribute('data-arrow'));
    var prev = opts.prev != null ? steps[opts.prev] : null;
    var prevShow = {}; if (prev) prev.show.forEach(function (id) { prevShow[id] = true; });
    var overlays = {}; (step.overlays || []).forEach(function (o) { (overlays[o.on] = overlays[o.on] || []).push(o); });
    step.show.forEach(function (id) {
      var n = nodesById[id], r = lay.rects[id];
      var g = svg('g', { 'class': 'wt-node', 'data-node': id });
      if (prev && !opts.print) {
        if (!prevShow[id]) g.setAttribute('class', 'wt-node wt-enter');
        else {
          var pc = cellOf(prev, id), c = cellOf(step, id);
          if (pc[0] !== c[0] || pc[1] !== c[1]) {
            var pr = rectOf(pc);
            g.setAttribute('data-from', (pr.x - r.x) + ',' + (pr.y - r.y));
          }
        }
      }
      drawNode(g, n, r, step, (overlays[id] || []).some(function (o) { return o.gauge != null; }));
      (overlays[id] || []).forEach(function (o) { drawOverlay(g, o, r, step.focus === id); });
      gn.appendChild(g);
    });
    if (prev && !opts.print) {
      prev.show.forEach(function (id) {
        if (step.show.indexOf(id) >= 0) return;
        var g = svg('g', { 'class': 'wt-node wt-leave' });
        drawNode(g, nodesById[id], rectOf(cellOf(prev, id)), { show: [], state: {} });
        gn.appendChild(g);
      });
    }
    var flows = flowsFor(step, lay);
    drawHeld(gn, flows);
    root.appendChild(gp);
    if (opts.print || still) drawStaticPackets(gp, flows);
    return { svg: root, flows: flows, packets: gp };
  }

  // ---------- page ----------
  var app = document.getElementById('wt');
  app.className = 'wt-app';
  var header = el('header', 'wt-head');
  var h1 = el('h1', 'wt-title', data.title || 'Walkthrough');
  header.appendChild(h1);
  if (data.summary) header.appendChild(el('p', 'wt-summary', data.summary));
  var tools = el('div', 'wt-tools');
  var btnReplay = el('button', 'wt-btn', 'Replay'), btnPause = el('button', 'wt-btn', still ? 'Paused' : 'Pause'),
      btnTheme = el('button', 'wt-btn', 'Theme');
  btnReplay.type = btnPause.type = btnTheme.type = 'button';
  btnPause.setAttribute('aria-pressed', still ? 'true' : 'false');
  tools.appendChild(btnReplay); tools.appendChild(btnPause); tools.appendChild(btnTheme);
  header.appendChild(tools);
  app.appendChild(header);

  var main = el('div', 'wt-main');
  var stageCol = el('section', 'wt-stagecol');
  stageCol.setAttribute('aria-label', 'Diagram');
  var chips = el('div', 'wt-chips');
  var stageBox = el('div', 'wt-stagebox');
  var panelsBox = el('div', 'wt-panels');
  var legend = el('div', 'wt-legend');
  stageCol.appendChild(chips); stageCol.appendChild(stageBox); stageCol.appendChild(panelsBox); stageCol.appendChild(legend);
  var card = el('aside', 'wt-card');
  card.setAttribute('aria-label', 'Step');
  main.appendChild(stageCol); main.appendChild(card);
  app.appendChild(main);
  var timeline = el('nav', 'wt-timeline');
  timeline.setAttribute('aria-label', 'Steps');
  app.appendChild(timeline);
  var live = el('p', 'wt-sr');
  live.setAttribute('aria-live', 'polite');
  app.appendChild(live);
  var help = el('p', 'wt-help', '← → step · R replay · Space pause');
  app.appendChild(help);

  // legend: only what this walkthrough uses
  (function () {
    var used = {}, async = false;
    steps.forEach(function (s) { (s.flows || []).forEach(function (f) { used[f.packet] = true; }); });
    (data.edges || []).forEach(function (e) { if (e.mode === 'async') async = true; });
    function item(svgEl, label) {
      var span = el('span', 'wt-legend-item');
      span.appendChild(svgEl); span.appendChild(document.createTextNode(label));
      legend.appendChild(span);
    }
    function mini(w) { return svg('svg', { width: w, height: 14, viewBox: '0 0 ' + w + ' 14', 'aria-hidden': 'true' }); }
    var s1 = mini(28); s1.appendChild(svg('path', { 'class': 'wt-edge', d: 'M2,7 H26' })); item(s1, 'sync call');
    if (async) { var s2 = mini(28); s2.appendChild(svg('path', { 'class': 'wt-edge wt-async', d: 'M2,7 H26' })); item(s2, 'async'); }
    Object.keys(PACKET_NAME).forEach(function (k) {
      if (!used[k]) return;
      var s = mini(14); s.appendChild(packetShape(k, 7, 7)); item(s, PACKET_NAME[k]);
    });
    var sf = mini(20); sf.appendChild(svg('rect', { x: 1, y: 2, width: 18, height: 10, rx: 2, 'class': 'wt-shape wt-focus' })); item(sf, 'focus of this step');
  })();

  // timeline
  var tlButtons = steps.map(function (s, i) {
    var b = el('button', 'wt-tl-step');
    b.type = 'button';
    b.appendChild(el('span', 'wt-tl-num', String(i + 1)));
    b.appendChild(el('span', 'wt-tl-label', s.short || s.title));
    b.addEventListener('click', function () { go(i); });
    timeline.appendChild(b);
    return b;
  });

  function renderChips(i) {
    chips.textContent = '';
    (data.metrics || []).forEach(function (m) {
      var v = metricAt(m.id, i);
      var pv = i > 0 ? metricAt(m.id, i - 1) : v;
      var bad = v != null && (breached(m, v) || (steps[i].breach || []).indexOf(m.id) >= 0);
      var chip = el('div', 'wt-chip' + (bad ? ' wt-chip-breach' : '') + (v !== pv && i > 0 ? ' wt-chip-flash' : ''));
      var lab = el('span', 'wt-chip-label', m.label + (m.target ? ' (' + m.target + (m.unit && !/[a-z%]/i.test(m.target) ? ' ' + m.unit : '') + ')' : ''));
      var val = el('span', 'wt-chip-value', (bad ? '! ' : '') + (v == null ? '—' : v + (m.unit && !/[a-z%]\s*$/i.test(v) ? ' ' + m.unit : '')));
      if (v !== pv && pv != null && i > 0) chip.title = 'was ' + pv;
      chip.appendChild(lab); chip.appendChild(val);
      chips.appendChild(chip);
    });
    chips.hidden = !(data.metrics || []).length;
  }

  function renderPanels(i) {
    panelsBox.textContent = '';
    (steps[i].panels || []).forEach(function (p) {
      var box = el('div', 'wt-panel');
      if (p.title) box.appendChild(el('p', 'wt-panel-title', p.title));
      if (p.type === 'chart' && p.points && p.points.length > 1) {
        var w = 260, h = 110, xs = p.points.map(function (q) { return q[0]; }), ys = p.points.map(function (q) { return q[1]; });
        var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min(0, Math.min.apply(null, ys)), y1 = Math.max.apply(null, ys);
        var sx = function (x) { return 28 + (x - x0) / ((x1 - x0) || 1) * (w - 40); };
        var sy = function (y) { return h - 20 - (y - y0) / ((y1 - y0) || 1) * (h - 32); };
        var c = svg('svg', { viewBox: '0 0 ' + w + ' ' + h, width: w, height: h, role: 'img', 'aria-label': p.title || 'chart', 'class': 'wt-chart' });
        c.appendChild(svg('path', { 'class': 'wt-axis', d: 'M28,8 V' + (h - 20) + ' H' + (w - 8) }));
        c.appendChild(svg('path', { 'class': 'wt-line', d: d(p.points.map(function (q) { return [sx(q[0]), sy(q[1])]; })) }));
        if (p.mark != null && p.points[p.mark]) {
          var mp = p.points[p.mark];
          c.appendChild(svg('circle', { 'class': 'wt-mark', cx: sx(mp[0]), cy: sy(mp[1]), r: 4 }));
          if (p.mark_label) c.appendChild(svg('text', { 'class': 'wt-elabel', x: sx(mp[0]) - 8, y: sy(mp[1]) + 4, 'text-anchor': 'end' }, p.mark_label));
        }
        if (p.x_label) c.appendChild(svg('text', { 'class': 'wt-elabel', x: w - 8, y: h - 4, 'text-anchor': 'end' }, p.x_label));
        if (p.y_label) c.appendChild(svg('text', { 'class': 'wt-elabel', x: 30, y: 16 }, p.y_label));
        box.appendChild(c);
      } else if (p.rows) {
        var t = el('table', 'wt-panel-table');
        p.rows.forEach(function (row, ri) {
          var tr = el('tr');
          row.forEach(function (cell) { tr.appendChild(el(ri === 0 && p.header ? 'th' : 'td', null, cell)); });
          t.appendChild(tr);
        });
        box.appendChild(t);
      }
      if (p.text) box.appendChild(el('p', 'wt-panel-text', p.text));
      panelsBox.appendChild(box);
    });
    if (steps[i].chapter === 'recap') {
      var tt = tradeoffTable(false);
      if (tt) {
        var box2 = el('div', 'wt-panel wt-panel-wide');
        box2.appendChild(el('p', 'wt-panel-title', 'Trade-offs (from the design doc)'));
        box2.appendChild(tt);
        panelsBox.appendChild(box2);
      }
    }
    panelsBox.hidden = !panelsBox.firstChild;
  }

  function tradeoffTable(compact) {
    var to = data._doc && data._doc.tradeoffs;
    if (!to || !to.rows || !to.rows.length) return null;
    var t = el('table', 'wt-table' + (compact ? ' wt-table-compact' : ''));
    var thead = el('thead'), tr = el('tr');
    to.header.forEach(function (h) { tr.appendChild(el('th', null, h)); });
    tr.appendChild(el('th', null, 'Step'));
    thead.appendChild(tr); t.appendChild(thead);
    var tb = el('tbody');
    to.rows.forEach(function (row) {
      var r = el('tr');
      row.forEach(function (c) { r.appendChild(el('td', null, c)); });
      var td = el('td');
      var si = -1;
      steps.forEach(function (s, k) { if (si < 0 && s.decision && norm(s.decision) === norm(row[0])) si = k; });
      if (si >= 0) {
        var a = el('a', 'wt-steplink', String(si + 1));
        a.href = '#step-' + (si + 1);
        a.addEventListener('click', function (ev) { ev.preventDefault(); go(si); });
        td.appendChild(a);
      }
      r.appendChild(td);
      tb.appendChild(r);
    });
    t.appendChild(tb);
    return t;
  }
  function norm(s) { return String(s).toLowerCase().replace(/[`*_]/g, '').replace(/\s+/g, ' ').trim(); }

  function renderCard(i) {
    var s = steps[i];
    card.textContent = '';
    var top = el('div', 'wt-card-top');
    top.appendChild(el('span', 'wt-stepno', 'Step ' + (i + 1) + ' / ' + steps.length));
    top.appendChild(el('span', 'wt-chapter', CHAPTER[s.chapter] || s.chapter));
    card.appendChild(top);
    card.appendChild(el('h2', 'wt-card-title', s.title));
    (s.body || []).forEach(function (p) { card.appendChild(el('p', 'wt-body', p)); });
    if (s.callout) {
      var c = CALLOUT[s.callout.kind] || CALLOUT.insight;
      var co = el('div', 'wt-callout wt-callout-' + (s.callout.kind || 'insight'));
      co.setAttribute('role', 'note');
      var lab = el('p', 'wt-callout-label');
      lab.appendChild(el('span', 'wt-glyph', c[0])); lab.appendChild(document.createTextNode(c[1]));
      co.appendChild(lab); co.appendChild(el('p', null, s.callout.text));
      card.appendChild(co);
    }
    if (s.changes && s.changes.length) {
      card.appendChild(el('p', 'wt-changes-title', 'What changed'));
      var ul = el('ul', 'wt-changes');
      s.changes.forEach(function (c) {
        var m = String(c).match(/^\s*([+\-~−])\s*(.*)$/);
        var kind = m ? (m[1] === '+' ? 'add' : m[1] === '~' ? 'mod' : 'del') : 'mod';
        var li = el('li', 'wt-change wt-change-' + kind);
        li.appendChild(el('span', 'wt-change-glyph', kind === 'add' ? '+' : kind === 'del' ? '−' : '~'));
        li.appendChild(document.createTextNode(m ? m[2] : c));
        ul.appendChild(li);
      });
      card.appendChild(ul);
    }
    if (s.doc_anchor && data._doc && data._doc.path) {
      var a = el('a', 'wt-doclink', 'Read this in the design doc →');
      a.href = data._doc.path + s.doc_anchor;
      card.appendChild(a);
    }
    var nav = el('div', 'wt-nav');
    var back = el('button', 'wt-btn', '← Back'), next = el('button', 'wt-btn wt-btn-primary', i + 1 < steps.length ? 'Next: ' + (steps[i + 1].short || 'next') + ' →' : 'Back to start');
    back.type = next.type = 'button';
    back.disabled = i === 0;
    back.addEventListener('click', function () { go(i - 1); });
    next.addEventListener('click', function () { go(i + 1 < steps.length ? i + 1 : 0); });
    nav.appendChild(back); nav.appendChild(next);
    card.appendChild(nav);
  }

  // ---------- animation loop ----------
  var cur = -1, scene = null, t = 0, last = null, paused = still, raf = 0;
  function frame(now) {
    raf = 0;
    if (last == null) last = now;
    var dt = (now - last) / 1000; last = now;
    if (!paused) t += Math.min(dt, 0.1);
    drawPackets();
    if (!paused) raf = requestAnimationFrame(frame);
  }
  function drawPackets() {
    if (!scene || still) return;
    var g = scene.packets;
    while (g.firstChild) g.removeChild(g.firstChild);
    scene.flows.forEach(function (fl) {
      if (fl.f.held) return;
      var kind = fl.f.packet, T = fl.travel, P = fl.period;
      var tail = kind === 'fail' ? T * 0.6 + 0.45 : T;
      var nMin = Math.ceil((t - fl.phase - tail) / P), nMax = Math.floor((t - fl.phase) / P);
      for (var n = Math.max(0, nMin); n <= nMax; n++) {
        var age = t - (fl.phase + n * P);
        if (age < 0) continue;
        if (kind === 'fail') {
          var stop = T * 0.6;
          if (age <= stop) { var p = pointAt(fl.pts, easeInOut(age / stop) * 0.6); g.appendChild(packetShape('fail', p[0], p[1])); }
          else { var q = pointAt(fl.pts, 0.6); g.appendChild(packetShape('fail', q[0], q[1], { opacity: 1 - (age - stop) / 0.45 })); }
        } else {
          var f = age / T;
          if (f > 1) continue;
          var pp = pointAt(fl.pts, f);
          g.appendChild(packetShape(kind, pp[0], pp[1], f > 0.9 ? { opacity: (1 - f) / 0.1 } : null));
        }
      }
    });
  }
  function kick() { if (!raf && !paused && !still) { last = null; raf = requestAnimationFrame(frame); } }

  function go(i, opts) {
    i = Math.max(0, Math.min(steps.length - 1, i));
    var prev = cur;
    cur = i;
    scene = renderScene(i, { prev: prev >= 0 && !(opts && opts.instant) ? prev : null });
    stageBox.textContent = '';
    stageBox.appendChild(scene.svg);
    // moved nodes slide from their old cell
    if (!still) {
      Array.prototype.forEach.call(scene.svg.querySelectorAll('[data-from]'), function (g) {
        var off = g.getAttribute('data-from').split(',');
        g.style.transform = 'translate(' + off[0] + 'px,' + off[1] + 'px)';
        g.getBoundingClientRect();
        g.classList.add('wt-moving');
        requestAnimationFrame(function () { g.style.transform = ''; });
      });
    }
    t = 0;
    renderChips(i); renderPanels(i); renderCard(i);
    tlButtons.forEach(function (b, k) {
      b.className = 'wt-tl-step' + (k < i ? ' wt-tl-done' : '') + (k === i ? ' wt-tl-current' : '');
      if (k === i) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
    });
    live.textContent = 'Step ' + (i + 1) + ' of ' + steps.length + ': ' + steps[i].title;
    if (!(opts && opts.fromHash)) {
      try { history.replaceState(null, '', location.pathname + location.search + '#step-' + (i + 1)); } catch (e) { /* file:// in some browsers */ }
    }
    drawPackets();
    kick();
  }

  btnReplay.addEventListener('click', function () { go(cur, { instant: false }); });
  btnPause.addEventListener('click', function () {
    if (still) return;
    paused = !paused;
    btnPause.textContent = paused ? 'Play' : 'Pause';
    btnPause.setAttribute('aria-pressed', paused ? 'true' : 'false');
    kick();
  });
  btnTheme.addEventListener('click', function () {
    var rootEl = document.documentElement;
    var isDark = rootEl.getAttribute('data-theme') === 'dark' ||
      (!rootEl.getAttribute('data-theme') && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    rootEl.setAttribute('data-theme', isDark ? 'light' : 'dark');
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.target && /input|textarea|select/i.test(ev.target.tagName)) return;
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.key === 'ArrowRight') { go(cur + 1); ev.preventDefault(); }
    else if (ev.key === 'ArrowLeft') { go(cur - 1); ev.preventDefault(); }
    else if (ev.key === 'Home') { go(0); ev.preventDefault(); }
    else if (ev.key === 'End') { go(steps.length - 1); ev.preventDefault(); }
    else if (ev.key === 'r' || ev.key === 'R') { go(cur); }
    else if (ev.key === ' ' && !(ev.target && ev.target.tagName === 'BUTTON')) { btnPause.click(); ev.preventDefault(); }
  });
  function fromHash() {
    var m = location.hash.match(/step-(\d+)/);
    return m ? parseInt(m[1], 10) - 1 : null;
  }
  window.addEventListener('hashchange', function () { var h = fromHash(); if (h != null && h !== cur) go(h, { fromHash: true }); });

  // ---------- print view: every step, settled, plus the trade-off table ----------
  (function () {
    var pr = el('div', 'wt-print');
    pr.id = 'wt-print';
    pr.appendChild(el('h1', null, data.title || 'Walkthrough'));
    steps.forEach(function (s, i) {
      var sec = el('section', 'wt-print-step');
      sec.appendChild(el('h2', null, (i + 1) + '. ' + s.title));
      sec.appendChild(renderScene(i, { print: true }).svg);
      (s.body || []).forEach(function (p) { sec.appendChild(el('p', null, p)); });
      if (s.callout) sec.appendChild(el('p', 'wt-print-callout', (CALLOUT[s.callout.kind] || CALLOUT.insight)[1] + ': ' + s.callout.text));
      if (s.changes && s.changes.length) {
        var ul = el('ul');
        s.changes.forEach(function (c) { ul.appendChild(el('li', null, c)); });
        sec.appendChild(ul);
      }
      pr.appendChild(sec);
    });
    var t = tradeoffTable(false);
    if (t) { pr.appendChild(el('h2', null, 'Trade-offs')); pr.appendChild(t); }
    document.body.appendChild(pr);
  })();

  var startQ = parseInt(params.get('step') || '', 10);
  var start = !isNaN(startQ) ? startQ - 1 : (fromHash() != null ? fromHash() : 0);
  go(start, { instant: true, fromHash: isNaN(startQ) && fromHash() != null });
  if (mq && mq.addEventListener) mq.addEventListener('change', function (e) { if (e.matches && params.get('motion') !== 'off') { still = true; paused = true; go(cur, { instant: true }); } });
})();
