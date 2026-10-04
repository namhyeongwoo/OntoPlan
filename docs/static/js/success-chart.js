/* Interactive success-rate chart for the OntoPlan project page.
   Data: window.ONTOPLAN_SUCCESS (task counts by method, scene scale, and metric). */
(function () {
  "use strict";

  var D = window.ONTOPLAN_SUCCESS;
  var root = document.getElementById("succ-chart");
  if (!D || !root) return;

  var SVGNS = "http://www.w3.org/2000/svg";
  var COLORS = { SayPlan: "#356B9B", DELTA: "#028090", OntoPlan: "#F24158" };
  var SIZES = ["small", "medium", "large"], SL = { small: "S", medium: "M", large: "L" };
  var NAMES = { plan_generation: "Plan Returned", plan_execution: "Plan Executable",
                goal_success: "Goal Reached", task_success: "Task Success" };
  var svg = document.getElementById("succ-svg");
  var tip = document.getElementById("succ-tip");
  var note = document.getElementById("succ-note");
  var buttons = Array.prototype.slice.call(root.querySelectorAll("[data-metric]"));
  var metric = "task_success";
  var W = 600, H = 470, M = { l: 50, r: 12, t: 22, b: 58 };
  var bars = [];  // {method, size, rect, label, marker}
  var lines = {};

  function el(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  function y(p) { return M.t + (H - M.t - M.b) * (1 - p / 100); }
  function rate(m, s) { var c = D.data[m][s][metric]; return 100 * c[0] / c[1]; }

  function build() {
    var cw = svg.parentNode.clientWidth || 600;
    W = Math.max(330, Math.min(600, cw)); H = Math.round(W * (W < 480 ? 0.95 : 0.78));
    M.l = W < 480 ? 42 : 50;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    bars = []; lines = {};

    for (var p = 0; p <= 100; p += 20) {
      el("line", { x1: M.l, x2: W - M.r, y1: y(p), y2: y(p), class: p ? "tk-grid" : "tk-axis" }, svg);
      var t = el("text", { x: M.l - 8, y: y(p) + 4, class: "tk-ax", "text-anchor": "end" }, svg);
      t.textContent = p + "%";
    }
    el("line", { x1: M.l, x2: M.l, y1: M.t, y2: H - M.b, class: "tk-axis" }, svg);

    var groupW = (W - M.l - M.r) / D.methods.length, barW = groupW / 4;
    D.methods.forEach(function (m, gi) {
      var color = COLORS[m];
      SIZES.forEach(function (s, si) {
        var cx = M.l + groupW * gi + groupW * (si + 0.5) / 3 + (1 - si) * 2;
        var g = el("g", { class: "sc-bar", tabindex: "0" }, svg);
        // full-height bar scaled to the rate, so switching metrics animates the height
        var rect = el("rect", { x: cx - barW / 2, y: y(100), width: barW, height: y(0) - y(100), rx: 2,
          fill: color, "fill-opacity": 0.88, stroke: "#141c28", "stroke-width": 0.9 }, g);
        var label = el("text", { x: cx, class: "sc-val", "text-anchor": "middle" }, svg);
        var tick = el("text", { x: cx, y: H - M.b + 18, class: "tk-ax", "text-anchor": "middle" }, svg);
        tick.textContent = SL[s];
        bars.push({ m: m, s: s, cx: cx, g: g, rect: rect, label: label });
      });
      lines[m] = el("polyline", { class: "sc-line" }, svg);
      var name = el("text", { x: M.l + groupW * (gi + 0.5), y: H - M.b + 42, class: "tk-method", "text-anchor": "middle", fill: color }, svg);
      name.textContent = m;
    });
    // markers on top of the trend lines
    bars.forEach(function (b) { b.dot = el("circle", { cx: b.cx, r: 3.2, class: "sc-dot" }, svg); });
    bars.forEach(function (b) { svg.appendChild(b.label); });
    update();
  }

  function update() {
    var pts = {};
    bars.forEach(function (b) {
      var v = rate(b.m, b.s), c = D.data[b.m][b.s][metric];
      b.rect.style.transform = "scaleY(" + Math.max(v / 100, 0.002) + ")";
      b.label.setAttribute("y", y(v) - 10);
      b.label.textContent = Math.round(v) + "%";
      b.dot.setAttribute("cy", y(v));
      (pts[b.m] = pts[b.m] || []).push(b.cx + "," + y(v));
      b.g.dataset.tip = b.m + " · " + b.s + "\n" + NAMES[metric] + ": " + c[0] + " / " + c[1] + " tasks (" + Math.round(v) + "%)";
      b.g.setAttribute("aria-label", b.m + " " + b.s + " " + NAMES[metric] + " " + Math.round(v) + " percent");
    });
    Object.keys(lines).forEach(function (m) { lines[m].setAttribute("points", pts[m].join(" ")); });
    // trend lines and labels appear once the bars have grown to their new height
    svg.classList.remove("settled");
    clearTimeout(update.timer);
    update.timer = setTimeout(function () { svg.classList.add("settled"); }, 420);
    svg.setAttribute("aria-label", NAMES[metric] + " rate by method and scene scale");
    // overall rate per method across the 150 tasks
    note.textContent = "";
    D.methods.forEach(function (m) {
      var ok = 0, n = 0;
      SIZES.forEach(function (s) { ok += D.data[m][s][metric][0]; n += D.data[m][s][metric][1]; });
      var row = document.createElement("div");
      var b = document.createElement("b"); b.textContent = m; b.style.color = COLORS[m];
      row.appendChild(b);
      row.appendChild(document.createTextNode(" " + (ok / n).toFixed(2) + "  (" + ok + " / " + n + ")"));
      note.appendChild(row);
    });
  }

  function showTip(target, cx, cy) {
    var r = svg.parentNode.getBoundingClientRect();
    tip.textContent = target.dataset.tip;
    tip.hidden = false;
    tip.style.left = Math.min(Math.max(cx - r.left, 80), r.width - 80) + "px";
    tip.style.top = (cy - r.top) + "px";
  }
  svg.addEventListener("pointermove", function (ev) {
    var t = ev.target.closest("[data-tip]");
    if (t) showTip(t, ev.clientX, ev.clientY); else tip.hidden = true;
  });
  svg.addEventListener("pointerleave", function () { tip.hidden = true; });
  svg.addEventListener("focusin", function (ev) {
    var t = ev.target.closest("[data-tip]");
    if (t) { var b = t.getBoundingClientRect(); showTip(t, b.left + b.width / 2, b.top + b.height - 4); }
  });
  svg.addEventListener("focusout", function () { tip.hidden = true; });

  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      metric = b.dataset.metric;
      buttons.forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
      tip.hidden = true;
      update();
    });
  });

  build();
  if ("ResizeObserver" in window) {
    var lastW = 0;
    new ResizeObserver(function () {
      var cw = svg.parentNode.clientWidth;
      if (Math.abs(cw - lastW) > 20) { lastW = cw; tip.hidden = true; build(); }
    }).observe(svg.parentNode);
  }
})();
