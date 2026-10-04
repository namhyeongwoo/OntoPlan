/* Ambiguous and infeasible instruction examples for the OntoPlan project page.
   Data: window.ONTOPLAN_CLARIFICATION (from the paper's appendix). */
(function () {
  "use strict";

  var D = window.ONTOPLAN_CLARIFICATION;
  var root = document.getElementById("cl-browser");
  if (!D || !root) return;

  var tabs = Array.prototype.slice.call(root.querySelectorAll("[data-set]"));
  var rows = document.getElementById("cl-rows");
  var legend = document.getElementById("cl-legend");

  var LEGEND = {
    ambiguous: "OntoPlan's clarification question and the user's answer, and whether the final plan reached the intended goal.",
    infeasible: "OntoPlan's first response to a request that cannot be carried out as stated."
  };

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // IDs such as juice_357 are shown in a monospace span
  function rich(tag, cls, text) {
    var span = el(tag, cls);
    text.split(/([a-z][a-z_]*_\d+)/g).forEach(function (part, i) {
      span.appendChild(i % 2 ? el("code", "", part) : document.createTextNode(part));
    });
    return span;
  }

  function turn(who, label, text, extra) {
    var t = el("div", "cl-turn " + who + (extra ? " " + extra : ""));
    t.appendChild(el("span", "cl-who", label));
    t.appendChild(rich("span", "cl-text", text));
    return t;
  }

  function note(label, text) {
    var p = rich("p", "cl-note", text);
    p.insertBefore(el("b", "", label + " "), p.firstChild);
    return p;
  }

  function load(set) {
    tabs.forEach(function (t) { t.setAttribute("aria-pressed", String(t.dataset.set === set)); });
    legend.textContent = LEGEND[set];
    rows.textContent = "";
    D[set].forEach(function (item) {
      var li = el("li", "cl-row");
      var tag = el("div", "cl-tag");
      tag.appendChild(el("span", "cl-id", item.id));
      var ok = set === "ambiguous" ? item.user : item.type === "Clarification Request";
      var outcome = set === "ambiguous" ? (item.user ? "Goal reached" : "Goal missed")
                                        : (ok ? "Asked for clarification" : "Returned a plan");
      tag.appendChild(el("span", "cl-out " + (ok ? "ok" : "no"), outcome));
      li.appendChild(tag);

      var ins = el("div", "cl-ins");
      ins.appendChild(el("p", "", item.instruction));
      ins.appendChild(set === "ambiguous" ? note("Intended:", item.intent) : note("Why infeasible:", item.reason));
      li.appendChild(ins);

      var ex = el("div", "cl-ex-turns");
      if (set === "ambiguous") {
        ex.appendChild(turn("onto", "OntoPlan", item.question));
        ex.appendChild(turn("user", "User", item.reply));
      } else {
        var plan = item.kind === "plan";
        ex.appendChild(turn("onto", plan ? "OntoPlan (plan)" : "OntoPlan", item.output, plan ? "plan" : ""));
      }
      li.appendChild(ex);
      rows.appendChild(li);
    });
  }

  tabs.forEach(function (t) { t.addEventListener("click", function () { load(t.dataset.set); }); });
  load("ambiguous");
})();
