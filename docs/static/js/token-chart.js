/* Interactive token-usage chart (log scale) for the OntoPlan project page.
   Data: window.ONTOPLAN_TOKENS (per-task totals and per-call input tokens). */
(function () {
  "use strict";

  var T = window.ONTOPLAN_TOKENS;
  var root = document.getElementById("tok-chart");
  if (!T || !root) return;

  var SVGNS = "http://www.w3.org/2000/svg";
  var COLORS = { SayPlan: "#356B9B", DELTA: "#028090", OntoPlan: "#F24158" };
  var SIZES = ["small", "medium", "large"], SL = { small: "S", medium: "M", large: "L" };
  var W = 600, H = 470, M = { l: 58, r: 12, t: 14, b: 58 };  // W, H follow the container width (see draw)
  var svg = document.getElementById("tok-svg");
  var tip = document.getElementById("tok-tip");
  var summary = document.getElementById("tok-summary");
  var buttons = Array.prototype.slice.call(root.querySelectorAll("[data-metric]"));
  var metric = "tasks";

  function quantile(sorted, q) {
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }
  function stats(values) {
    var s = values.slice().sort(function (a, b) { return a - b; });
    var q1 = quantile(s, 0.25), q3 = quantile(s, 0.75), iqr = q3 - q1;
    var lo = s.find(function (v) { return v >= q1 - 1.5 * iqr; });
    var hi = s.slice().reverse().find(function (v) { return v <= q3 + 1.5 * iqr; });
    var mean = s.reduce(function (a, b) { return a + b; }, 0) / s.length;
    return { q1: q1, med: quantile(s, 0.5), q3: q3, lo: lo, hi: hi, mean: mean, n: s.length,
             out: s.filter(function (v) { return v < lo || v > hi; }) };
  }
  function fmt(v) {
    if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(1) + "k";
    return String(Math.round(v));
  }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(x, y, str, attrs, parent) {
    var t = el("text", Object.assign({ x: x, y: y }, attrs || {}), parent);
    t.textContent = str;
    return t;
  }

  // Deterministic jitter so dots do not move between redraws
  function jitter(i) { var x = Math.sin(i * 12.9898) * 43758.5453; return x - Math.floor(x) - 0.5; }

  function values(method, size) {
    var d = T.data[method][size];
    return metric === "tasks" ? d.tasks.map(function (r) { return r[2]; }) : d.calls;
  }

  function draw() {
    // Match the drawing width to the rendered width so labels keep a readable size on phones
    var cw = svg.parentNode.clientWidth || 600;
    W = Math.max(330, Math.min(600, cw)); H = Math.round(W * (W < 480 ? 0.95 : 0.78));
    M.l = W < 480 ? 46 : 58;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var all = [];
    T.methods.forEach(function (m) { SIZES.forEach(function (s) { all = all.concat(values(m, s)); }); });
    var lo = Math.pow(10, Math.floor(Math.log10(Math.min.apply(null, all))));
    var hi = Math.max.apply(null, all) * 1.25;
    var y = function (v) { return M.t + (H - M.t - M.b) * (1 - (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))); };

    // y grid and labels
    for (var p = Math.log10(lo); Math.pow(10, p) <= hi; p++) {
      var v = Math.pow(10, p), yy = y(v);
      el("line", { x1: M.l, x2: W - M.r, y1: yy, y2: yy, class: "tk-grid" }, svg);
      text(M.l - 8, yy + 4, v >= 1e6 ? (v / 1e6) + "M" : v >= 1e3 ? (v / 1e3) + "K" : String(v), { class: "tk-ax", "text-anchor": "end" }, svg);
      for (var k = 2; k < 10 && v * k <= hi; k++) {
        el("line", { x1: M.l, x2: W - M.r, y1: y(v * k), y2: y(v * k), class: "tk-grid minor" }, svg);
      }
    }
    el("line", { x1: M.l, x2: M.l, y1: M.t, y2: H - M.b, class: "tk-axis" }, svg);
    el("line", { x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b, class: "tk-axis" }, svg);

    var groupW = (W - M.l - M.r) / T.methods.length, boxW = groupW / 4.2;
    T.methods.forEach(function (m, gi) {
      var color = COLORS[m];
      SIZES.forEach(function (s, si) {
        var cx = M.l + groupW * gi + groupW * (si + 0.5) / 3 + (1 - si) * 2;
        var vals = values(m, s), st = stats(vals);
        var g = el("g", { class: "tk-box", tabindex: "0", role: "img",
          "aria-label": m + " " + s + ": median " + fmt(st.med) + ", mean " + fmt(st.mean) }, svg);
        // per-task dots
        if (metric === "tasks") {
          T.data[m][s].tasks.forEach(function (r, i) {
            var c = el("circle", { cx: cx + jitter(i + si * 97 + gi * 331) * boxW * 0.9, cy: y(r[2]), r: 2.4,
              fill: color, "fill-opacity": 0.45, class: "tk-dot" }, svg);
            c.dataset.tip = r[0] + " " + r[1] + " · " + fmt(r[2]) + " tokens";
          });
        } else {
          st.out.forEach(function (v) { el("circle", { cx: cx, cy: y(v), r: 1.8, fill: color, "fill-opacity": 0.35 }, g); });
        }
        el("line", { x1: cx, x2: cx, y1: y(st.lo), y2: y(st.q1), class: "tk-whisk" }, g);
        el("line", { x1: cx, x2: cx, y1: y(st.q3), y2: y(st.hi), class: "tk-whisk" }, g);
        el("line", { x1: cx - boxW * 0.25, x2: cx + boxW * 0.25, y1: y(st.lo), y2: y(st.lo), class: "tk-whisk" }, g);
        el("line", { x1: cx - boxW * 0.25, x2: cx + boxW * 0.25, y1: y(st.hi), y2: y(st.hi), class: "tk-whisk" }, g);
        el("rect", { x: cx - boxW / 2, y: y(st.q3), width: boxW, height: Math.max(y(st.q1) - y(st.q3), 1.5),
          fill: color, "fill-opacity": metric === "tasks" ? 0.55 : 0.85, stroke: "#141c28", "stroke-width": 0.9, rx: 1.5 }, g);
        el("line", { x1: cx - boxW / 2, x2: cx + boxW / 2, y1: y(st.med), y2: y(st.med), stroke: "#141c28", "stroke-width": 1.8 }, g);
        el("circle", { cx: cx, cy: y(st.mean), r: 3, fill: "#fff", stroke: "#141c28", "stroke-width": 1.1 }, g);
        g.dataset.tip = m + " · " + s + " (n=" + st.n + (metric === "tasks" ? " tasks" : " calls") + ")\nmedian " +
          fmt(st.med) + " · mean " + fmt(st.mean) + "\nIQR " + fmt(st.q1) + " – " + fmt(st.q3);
        text(cx, H - M.b + 18, SL[s], { class: "tk-ax", "text-anchor": "middle" }, svg);
      });
      text(M.l + groupW * (gi + 0.5), H - M.b + 42, m, { class: "tk-method", "text-anchor": "middle", fill: color }, svg);
    });
    svg.setAttribute("aria-label", (metric === "tasks" ? "Total tokens per task" : "Input tokens per call") +
      " by method and scene scale, log scale");

    // summary: mean per scale and Large-to-Small ratio
    summary.textContent = "";
    T.methods.forEach(function (m) {
      var means = SIZES.map(function (s) { return stats(values(m, s)).mean; });
      var row = document.createElement("div");
      var name = document.createElement("b"); name.textContent = m; name.style.color = COLORS[m];
      row.appendChild(name);
      row.appendChild(document.createTextNode(" " + means.map(fmt).join(" / ") + "  ·  L/S " + (means[2] / means[0]).toFixed(2) + "×"));
      summary.appendChild(row);
    });
  }

  function showTip(target, ev) {
    var r = root.querySelector(".tk-stage").getBoundingClientRect();
    tip.textContent = target.dataset.tip;
    tip.hidden = false;
    var x = (ev.clientX || r.left + r.width / 2) - r.left, yy = (ev.clientY || r.top) - r.top;
    tip.style.left = Math.min(Math.max(x, 70), r.width - 70) + "px";
    tip.style.top = yy + "px";
  }
  svg.addEventListener("pointermove", function (ev) {
    var t = ev.target.closest("[data-tip]");
    if (t) showTip(t, ev); else tip.hidden = true;
  });
  svg.addEventListener("pointerleave", function () { tip.hidden = true; });
  svg.addEventListener("focusin", function (ev) {
    var t = ev.target.closest("[data-tip]");
    if (t) { var b = t.getBoundingClientRect(); showTip(t, { clientX: b.left + b.width / 2, clientY: b.top }); }
  });
  svg.addEventListener("focusout", function () { tip.hidden = true; });

  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      metric = b.dataset.metric;
      buttons.forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
      tip.hidden = true;
      draw();
    });
  });
  draw();
  if ("ResizeObserver" in window) {
    var lastW = 0;
    new ResizeObserver(function () {
      var cw = svg.parentNode.clientWidth;
      if (Math.abs(cw - lastW) > 20) { lastW = cw; tip.hidden = true; draw(); }
    }).observe(svg.parentNode);
  }
})();
