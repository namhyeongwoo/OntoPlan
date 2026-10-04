/* Overview and World model figures, rebuilt from the slide shapes (data: window.ONTOPLAN_FIGURES,
   built by docs/scripts/build_figures.py). The World model is shown as it is. The Overview is a
   timeline, so it builds up step by step like an animated figure, holds, and starts again; it
   pauses off-screen and stays complete when reduced motion is requested. */
(function () {
  "use strict";

  var D = window.ONTOPLAN_FIGURES;
  if (!D) return;

  // Overview steps in the order of the timeline (parts are defined in build_figures.py)
  var STEPS = ["world-model", "instruction", "route-se", "scene-query", "scene-query-tool", "discovered", "ask-user", "answer",
               "route-tf", "formalize", "pddl-plan", "pddl-plan-tool", "final-plan", "approve"];
  var STEP_MS = 650, HOLD_MS = 3800, CLEAR_MS = 500;

  document.querySelectorAll("figure.svgfig").forEach(function (fig) {
    var data = D[fig.dataset.fig];
    var box = fig.querySelector(".fig-svg");
    if (!data || !box) return;
    box.innerHTML = data.svg;
    var svg = box.querySelector("svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", box.dataset.label || "");
    fig.classList.add("live");
    if (fig.dataset.mode === "loop") loop(svg);
  });

  function loop(svg) {
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) return;
    var parts = {};
    svg.querySelectorAll(".fs[data-part]").forEach(function (g) {
      (parts[g.dataset.part] = parts[g.dataset.part] || []).push(g);
    });
    // starts complete (so the page reads at rest), then clears and builds up
    var k = STEPS.length, timer = 0, running = false, inView = false;

    function hideAll() {
      STEPS.forEach(function (s) { (parts[s] || []).forEach(function (g) { g.classList.add("hid"); }); });
    }
    function next() {
      if (k < STEPS.length) {
        (parts[STEPS[k]] || []).forEach(function (g) { g.classList.remove("hid"); });
        k += 1;
        timer = setTimeout(next, k === STEPS.length ? HOLD_MS : STEP_MS);
      } else {
        svg.classList.add("clearing");
        timer = setTimeout(function () {
          hideAll();
          svg.classList.remove("clearing");
          k = 0;
          timer = setTimeout(next, STEP_MS);
        }, CLEAR_MS);
      }
    }
    function start() { if (!running) { running = true; timer = setTimeout(next, k === STEPS.length ? 1600 : STEP_MS); } }
    function stop() { running = false; clearTimeout(timer); }

    svg.classList.add("anim");
    new IntersectionObserver(function (es) {
      inView = es[0].isIntersecting;
      if (inView && !document.hidden) start(); else stop();
    }, { threshold: 0.35 }).observe(svg);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop(); else if (inView) start();
    });
  }
})();
