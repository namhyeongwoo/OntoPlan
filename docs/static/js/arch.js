/* Agentic workflow: what sets the four agents apart. The shared memory (left) and the routing
   targets (right) stay in place; choosing an agent shows its role, the fields it reads and
   writes, and where it can hand control next. Content follows the paper's architecture figure. */
(function () {
  "use strict";

  var fig = document.getElementById("arch");
  if (!fig) return;
  var plate = fig.querySelector(".arch-plate");
  var ICONS = "static/images/icons/";
  var SVGNS = "http://www.w3.org/2000/svg";

  var FIELDS = ["dialogue_history", "routing_reason", "agent_reports", "discovered_objects", "space_overview",
                "tool_history", "task_description", "task_conditions", "final_plan"];
  var TARGETS = [
    ["user", "USER", "user.svg"], ["fo", "Flow Orchestrator", "agent-fo.svg"], ["se", "Scene Explorer", "agent-se.svg"],
    ["tf", "Task Formalizer", "agent-tf.svg"], ["pm", "Planning Manager", "agent-pm.svg"],
    ["sq", "Scene query", "tool.svg"], ["pp", "PDDL plan", "tool.svg"], ["robot", "ROBOT", "robot.svg"]
  ];
  var AGENTS = [
    { id: "fo", name: "Flow Orchestrator", role: "Interpret intent and route workflow",
      note: "The only agent that talks to the user. It reads the dialogue and the other agents' reports, decides what the user means, and sends the work on, or asks the user when the intent is unclear.",
      read: ["agent_reports", "dialogue_history", "discovered_objects"], write: ["routing_reason", "dialogue_history", "agent_reports"],
      routes: ["user", "se", "tf"] },
    { id: "se", name: "Scene Explorer", role: "Ground task-relevant scene context",
      note: "Starts from a compact overview of the spaces and queries the world model for the objects the task needs, recording what it found for the others.",
      read: ["dialogue_history", "routing_reason", "space_overview", "tool_history"], write: ["tool_history", "discovered_objects", "agent_reports"],
      routes: ["sq", "fo"] },
    { id: "tf", name: "Task Formalizer", role: "Translate grounded intent into task conditions",
      note: "Turns the grounded intent into an at-end goal and always / sometime constraints over the discovered objects.",
      read: ["dialogue_history", "routing_reason", "discovered_objects"], write: ["task_description", "task_conditions", "agent_reports"],
      routes: ["fo", "pm"] },
    { id: "pm", name: "Planning Manager", role: "Arrange subgoals and validate plans",
      note: "Orders the conditions into subgoals, plans them with the PDDL plan tool, checks the result, and hands the final plan to the robot.",
      read: ["task_description", "task_conditions", "tool_history", "discovered_objects"], write: ["tool_history", "agent_reports", "final_plan"],
      routes: ["pp", "robot"] }
  ];

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function icon(name, cls) {
    var i = el("img", "ic" + (cls ? " " + cls : ""));
    i.src = ICONS + name; i.alt = ""; i.width = 16; i.height = 16;
    return i;
  }
  function svgEl(tag, attrs) {
    var e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }

  /* ---------- Markup ---------- */
  var root = el("div", "ax");
  var tabs = el("div", "ax-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Agent");
  var tabEls = AGENTS.map(function (a) {
    var t = el("button", "ax-tab ax-" + a.id);
    t.type = "button";
    t.setAttribute("role", "tab");
    t.appendChild(icon("agent-" + a.id + ".svg", "big"));
    t.appendChild(el("span", "", a.name));
    t.addEventListener("click", function () { select(a.id); });
    tabs.appendChild(t);
    return t;
  });
  root.appendChild(tabs);

  var stage = el("div", "ax-stage");
  stage.setAttribute("role", "tabpanel");
  var mem = el("div", "ax-col ax-mem");
  mem.appendChild(el("div", "ax-h", "Shared memory · " + FIELDS.length + " fields"));
  var fieldEls = {};
  FIELDS.forEach(function (f) {
    var c = el("div", "ax-field");
    c.tabIndex = 0;
    c.appendChild(el("code", "", f));
    var marks = el("span", "ax-marks");
    marks.appendChild(icon("read.svg", "r"));
    marks.appendChild(icon("write.svg", "w"));
    c.appendChild(marks);
    c.addEventListener("pointerenter", function () { fieldNote(f); });
    c.addEventListener("focus", function () { fieldNote(f); });
    c.addEventListener("pointerleave", restoreNote);
    c.addEventListener("blur", restoreNote);
    mem.appendChild(c);
    fieldEls[f] = c;
  });
  var center = el("div", "ax-col ax-center");
  var card = el("div", "ax-card");
  center.appendChild(card);
  var routes = el("div", "ax-col ax-routes");
  routes.appendChild(el("div", "ax-h", "Routes to"));
  var targetEls = {};
  TARGETS.forEach(function (t) {
    var c = el("div", "ax-target ax-t-" + t[0]);
    c.appendChild(icon(t[2]));
    c.appendChild(el("span", "", t[1]));
    routes.appendChild(c);
    targetEls[t[0]] = c;
  });
  var lines = svgEl("svg", { "class": "ax-lines", "aria-hidden": "true" });
  stage.appendChild(lines);
  stage.appendChild(mem);
  stage.appendChild(el("div", "ax-gap"));
  stage.appendChild(center);
  stage.appendChild(el("div", "ax-gap"));
  stage.appendChild(routes);
  root.appendChild(stage);

  var key = el("div", "ax-key");
  key.innerHTML = '<span><i class="k-read"></i>reads</span><span><i class="k-write"></i>writes</span><span><i class="k-route"></i>can route to</span>';
  root.appendChild(key);
  plate.textContent = "";
  plate.appendChild(root);
  var note = el("p", "hot-note on");
  note.setAttribute("aria-live", "polite");
  fig.appendChild(note);

  /* ---------- State ---------- */
  var current = null;

  function select(id) {
    current = AGENTS.filter(function (a) { return a.id === id; })[0];
    var a = current;
    tabEls.forEach(function (t, i) {
      var on = AGENTS[i].id === id;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    });
    stage.dataset.agent = id;
    card.className = "ax-card ax-" + id;
    card.textContent = "";
    var h = el("h4");
    h.appendChild(icon("agent-" + id + ".svg", "big"));
    h.appendChild(document.createTextNode(a.name));
    card.appendChild(h);
    var role = el("p", "ax-role");
    role.appendChild(icon("prompt.svg"));
    role.appendChild(el("span", "", a.role));
    card.appendChild(role);
    var stats = el("div", "ax-stats");
    [[a.read.length, "reads"], [a.write.length, "writes"], [a.routes.length, "routes"]].forEach(function (st) {
      var d = el("div", "ax-stat");
      d.appendChild(el("b", "", String(st[0])));
      d.appendChild(el("span", "", st[1]));
      stats.appendChild(d);
    });
    card.appendChild(stats);
    FIELDS.forEach(function (f) {
      var r = a.read.indexOf(f) >= 0, w = a.write.indexOf(f) >= 0;
      var c = fieldEls[f];
      c.classList.toggle("is-r", r);
      c.classList.toggle("is-w", w);
      c.classList.toggle("off", !r && !w);
      c.setAttribute("aria-label", f + (r && w ? ": read and written" : r ? ": read" : w ? ": written" : ": not used") + " by the " + a.name);
    });
    TARGETS.forEach(function (t) {
      var c = targetEls[t[0]];
      c.classList.toggle("on", a.routes.indexOf(t[0]) >= 0);
      c.classList.toggle("self", t[0] === id);
    });
    restoreNote();
    draw();
  }

  function restoreNote() { if (current) note.textContent = current.note; }
  function fieldNote(f) {
    var r = [], w = [];
    AGENTS.forEach(function (a) {
      if (a.read.indexOf(f) >= 0) r.push(a.name);
      if (a.write.indexOf(f) >= 0) w.push(a.name);
    });
    function list(xs) { return xs.length === 4 ? "all four agents" : xs.length > 1 ? xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1] : xs[0]; }
    note.textContent = f + ": " + (w.length ? "written by " + list(w) : "given at the start of a session") +
                       (r.length ? "; read by " + list(r) + "." : ".");
  }

  /* ---------- Lines ---------- */
  function draw() {
    lines.textContent = "";
    if (!current || getComputedStyle(lines).display === "none") return;
    var box = stage.getBoundingClientRect();
    lines.setAttribute("viewBox", "0 0 " + box.width + " " + box.height);
    var cr = card.getBoundingClientRect();
    var cx0 = cr.left - box.left, cx1 = cr.right - box.left, ctop = cr.top - box.top, ch = cr.height;
    var color = getComputedStyle(card).getPropertyValue("--ax-c").trim() || "#404756";
    var defs = svgEl("defs", {});
    [["ar-read", "#8b919c"], ["ar-agent", color]].forEach(function (m) {
      var mk = svgEl("marker", { id: m[0], viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto" });
      mk.appendChild(svgEl("path", { d: "M0,1 L9,5 L0,9", fill: "none", stroke: m[1], "stroke-width": "1.8" }));
      defs.appendChild(mk);
    });
    lines.appendChild(defs);

    // one line per (field, direction), fanned out along the card's left edge in field order
    var links = [];
    FIELDS.forEach(function (f) {
      if (current.read.indexOf(f) >= 0) links.push([f, "r"]);
      if (current.write.indexOf(f) >= 0) links.push([f, "w"]);
    });
    links.forEach(function (l, i) {
      var fr = fieldEls[l[0]].getBoundingClientRect();
      var both = current.read.indexOf(l[0]) >= 0 && current.write.indexOf(l[0]) >= 0;
      var fy = fr.top - box.top + fr.height / 2 + (both ? (l[1] === "r" ? -4 : 4) : 0);
      var fx = fr.right - box.left + 3;
      var ay = ctop + 22 + (ch - 44) * (links.length === 1 ? 0.5 : i / (links.length - 1));
      var ax = cx0 - 3;
      var mid = (fx + ax) / 2;
      var d = l[1] === "r"
        ? "M" + fx + "," + fy + " C" + mid + "," + fy + " " + mid + "," + ay + " " + ax + "," + ay
        : "M" + ax + "," + ay + " C" + mid + "," + ay + " " + mid + "," + fy + " " + fx + "," + fy;
      var attrs = { "class": l[1] === "r" ? "ln-read" : "ln-write", d: d, stroke: l[1] === "r" ? "#8b919c" : color,
                    "marker-end": "url(#" + (l[1] === "r" ? "ar-read" : "ar-agent") + ")" };
      lines.appendChild(svgEl("path", attrs));
      if (l[1] === "r") lines.appendChild(svgEl("circle", { cx: fx + 1, cy: fy, r: 2.6, fill: "#8b919c" }));
    });
    current.routes.forEach(function (t, i) {
      var tr = targetEls[t].getBoundingClientRect();
      var ty = tr.top - box.top + tr.height / 2, tx = tr.left - box.left - 3;
      var ay = ctop + ch / 2 + (i - (current.routes.length - 1) / 2) * 16;
      var mid = (cx1 + tx) / 2;
      lines.appendChild(svgEl("path", { "class": "ln-route", stroke: color,
                                        d: "M" + (cx1 + 3) + "," + ay + " C" + mid + "," + ay + " " + mid + "," + ty + " " + tx + "," + ty,
                                        "marker-end": "url(#ar-agent)" }));
    });
  }

  tabs.addEventListener("keydown", function (ev) {
    var i = AGENTS.indexOf(current), n = AGENTS.length;
    if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
      ev.preventDefault();
      var j = (i + (ev.key === "ArrowRight" ? 1 : n - 1)) % n;
      select(AGENTS[j].id);
      tabEls[j].focus();
    }
  });
  if ("ResizeObserver" in window) new ResizeObserver(draw).observe(stage);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
  select("fo");
})();
