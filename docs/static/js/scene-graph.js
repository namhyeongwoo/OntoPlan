/* Scene-graph canvas for the OntoPlan project page.
   Data: window.KLICKITAT, built by docs/scripts/build_scene_graph.py. */
(function () {
  "use strict";

  var DATA = window.KLICKITAT;
  if (!DATA) return;

  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var COLORS = {
    building: "#c7cfdb", storey: "#c7cfdb", space: "#4fb5c0",
    portal: "#f5b041", artifact: "#7ba4ca", robot: "#b88be0"
  };
  var RADIUS = { building: 5.5, storey: 4.6, space: 3.8, portal: 2.5, artifact: 2.0, robot: 3.2 };
  var TYPE_LABEL = {
    building: "Building", storey: "Storey", space: "Space",
    portal: "Door / stairs / opening", artifact: "Object", robot: "Robot / hand"
  };
  var ACCENT = "#f2677a";

  function SceneGraph(canvas, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.opts = opts || {};
    this.focus = new Set();
    this.context = new Set();
    this.mix = 0;          // 0 = no highlight, 1 = full highlight
    this.target = 0;
    this.hover = -1;
    this.visible = true;
    this.running = false;
    this.phase = [];
    var self = this;
    new ResizeObserver(function () { self.resize(); }).observe(canvas);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) {
        self.visible = es[0].isIntersecting;
        if (self.visible) self.kick();
      }).observe(canvas);
    }
  }

  SceneGraph.prototype.setData = function (d) {
    this.d = d;
    var n = d.ids.length;
    this.adj = [];
    for (var i = 0; i < n; i++) this.adj.push([]);
    for (var e = 0; e < d.edges.length; e += 2) {
      this.adj[d.edges[e]].push(d.edges[e + 1]);
      this.adj[d.edges[e + 1]].push(d.edges[e]);
    }
    this.phase = [];
    for (var j = 0; j < n; j++) this.phase.push(Math.random() * Math.PI * 2);
    this.size = n > 800 ? 0.62 : n > 300 ? 0.8 : 1;
    this.focus = new Set();
    this.context = new Set();
    this.mix = 0; this.target = 0;
    this.kick();
  };

  SceneGraph.prototype.highlight = function (indices) {
    var f = new Set(indices), c = new Set(), adj = this.adj;
    f.forEach(function (i) { adj[i].forEach(function (j) { if (!f.has(j)) c.add(j); }); });
    this.focus = f; this.context = c;
    this.mix = Math.min(this.mix, 0.35);
    this.target = f.size ? 1 : 0;
    this.kick();
  };

  SceneGraph.prototype.resize = function () {
    var r = this.canvas.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = r.width; this.h = r.height; this.dpr = dpr;
    this.canvas.width = Math.round(r.width * dpr);
    this.canvas.height = Math.round(r.height * dpr);
    this.kick();
  };

  SceneGraph.prototype.pos = function (i, t) {
    var p = this.opts.pad || [0.06, 0.06, 0.06, 0.06]; // top right bottom left
    var x = this.d.xy[2 * i], y = this.d.xy[2 * i + 1];
    var px = this.w * (p[3] + x * (1 - p[1] - p[3]));
    var py = this.h * (p[0] + y * (1 - p[0] - p[2]));
    if (this.opts.drift && !REDUCED) {
      var ph = this.phase[i];
      px += Math.sin(t * 0.00045 + ph) * 3.2;
      py += Math.cos(t * 0.00038 + ph * 1.3) * 3.2;
    }
    return [px, py];
  };

  SceneGraph.prototype.kick = function () {
    if (this.running || !this.d) return;
    this.running = true;
    var self = this;
    requestAnimationFrame(function loop(t) {
      self.draw(t);
      var animating = (self.opts.drift && !REDUCED) || Math.abs(self.target - self.mix) > 0.002 ||
        (self.opts.busy && self.opts.busy());
      if (animating && self.visible && !document.hidden) requestAnimationFrame(loop);
      else self.running = false;
    });
  };

  SceneGraph.prototype.draw = function (t) {
    var ctx = this.ctx, d = this.d, n = d.ids.length, self = this;
    if (!this.w) return;
    this.mix += (this.target - this.mix) * (REDUCED ? 1 : 0.12);
    var m = this.mix, s = this.size;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);

    var P = new Array(n);
    for (var i = 0; i < n; i++) P[i] = this.pos(i, t);

    // edges
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(200,212,230," + (0.16 - 0.1 * m) + ")";
    ctx.beginPath();
    for (var e = 0; e < d.edges.length; e += 2) {
      var a = P[d.edges[e]], b = P[d.edges[e + 1]];
      ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
    }
    ctx.stroke();
    if (m > 0.01) {
      ctx.strokeStyle = "rgba(242,103,122," + (0.85 * m) + ")";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      for (var k = 0; k < d.edges.length; k += 2) {
        var u = d.edges[k], v = d.edges[k + 1];
        if (this.focus.has(u) || this.focus.has(v)) {
          ctx.moveTo(P[u][0], P[u][1]); ctx.lineTo(P[v][0], P[v][1]);
        }
      }
      ctx.stroke();
    }

    // nodes
    for (var j = 0; j < n; j++) {
      if (this.focus.has(j)) continue;
      var ty = d.types[j], r = RADIUS[ty] * (ty === "artifact" ? s : Math.max(s, 0.85));
      var ctxNode = this.context.has(j);
      ctx.globalAlpha = ctxNode ? 0.95 : 0.9 - 0.68 * m;
      ctx.fillStyle = COLORS[ty];
      ctx.beginPath(); ctx.arc(P[j][0], P[j][1], r, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;

    // focus nodes with glow and pulse
    if (this.focus.size) {
      var pulse = REDUCED ? 0.5 : (Math.sin(t * 0.004) + 1) / 2;
      this.focus.forEach(function (fi) {
        var p = P[fi], r = Math.max(RADIUS[d.types[fi]], 2.6) * 1.35;
        ctx.globalAlpha = m;
        ctx.fillStyle = "rgba(242,103,122,0.18)";
        ctx.beginPath(); ctx.arc(p[0], p[1], r + 5 + pulse * 4, 0, 6.2832); ctx.fill();
        ctx.fillStyle = ACCENT;
        ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 6.2832); ctx.fill();
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.2;
        ctx.stroke();
      });
      if (this.opts.labels !== false) {
        ctx.font = "500 11px 'JetBrains Mono', ui-monospace, monospace";
        ctx.textBaseline = "middle";
        this.focus.forEach(function (fi) {
          var p = P[fi], label = d.ids[fi];
          var tw = ctx.measureText(label).width;
          var lx = Math.min(Math.max(p[0] + 9, 4), self.w - tw - 8);
          ctx.globalAlpha = m;
          ctx.fillStyle = "rgba(8,12,22,0.72)";
          ctx.fillRect(lx - 3, p[1] - 8, tw + 6, 16);
          ctx.fillStyle = "#fff";
          ctx.fillText(label, lx, p[1]);
        });
      }
      ctx.globalAlpha = 1;
    }

    // caller-drawn layer (task replay)
    if (this.opts.overlay) this.opts.overlay(ctx, P, t, this);

    // hover ring
    if (this.hover >= 0) {
      var hp = P[this.hover];
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(hp[0], hp[1], 7, 0, 6.2832); ctx.stroke();
    }
    this.P = P;
  };

  SceneGraph.prototype.nearest = function (x, y, maxDist) {
    if (!this.P) return -1;
    var best = -1, bd = maxDist * maxDist;
    for (var i = 0; i < this.P.length; i++) {
      var dx = this.P[i][0] - x, dy = this.P[i][1] - y, dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = i; }
    }
    return best;
  };

  function entityLine(d, task, max) {
    var names = task.ents.map(function (i) { return d.ids[i]; });
    if (names.length > max) return names.slice(0, max).join(" · ") + " · +" + (names.length - max);
    return names.join(" · ");
  }

  window.OntoSceneGraph = SceneGraph;
  window.OntoSceneGraph.COLORS = COLORS;
  window.OntoSceneGraph.TYPE_LABEL = TYPE_LABEL;

  /* ---------- Hero: each Small-scale task shows its goal, then the plan OntoPlan returned ---------- */
  var heroCanvas = document.getElementById("hero-canvas");
  if (heroCanvas) {
    var hd = DATA.small;
    var PLANS = window.ONTOPLAN_HERO_PLANS || {};
    var index = {};
    hd.ids.forEach(function (id, i) { index[id] = i; });
    var tasks = hd.tasks.filter(function (t) { return PLANS[t.id]; });
    if (!tasks.length) tasks = hd.tasks;
    var ROBOT = "#b88be0", TRAIL = "rgba(201,166,240,0.9)", OBJ = "#7ba4ca";
    var GOAL_MS = 2600, DONE_MS = 2400, FADE_MS = 350;

    // playback state: the robot's visited nodes, its current move, what it holds, and where things were put
    var run = null;
    function startRun(task) {
      var plan = PLANS[task.id] || [];
      var first = plan.filter(function (a) { return a[0] === "move"; })[0];
      run = { plan: plan, k: -1, t0: 0, dt: Math.max(160, Math.min(520, 6000 / Math.max(plan.length, 1))),
              at: first ? index[first[2]] : -1, from: -1, trail: first ? [index[first[2]]] : [],
              held: -1, placed: [], playing: false };
    }
    function easeInOut(q) { return q < 0.5 ? 2 * q * q : 1 - Math.pow(-2 * q + 2, 2) / 2; }

    var hero = new SceneGraph(heroCanvas, {
      drift: true, pad: [0.05, 0.05, 0.2, 0.05],
      overlay: function (ctx, P, t) {
        if (!run || run.at < 0) return;
        var robotP = P[run.at];
        if (run.from >= 0 && run.playing) {
          var q = easeInOut(Math.min(1, (t - run.t0) / (run.dt * 0.9)));
          var a = P[run.from], b = P[run.at];
          robotP = [a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q];
        }
        // trail through the visited spaces and portals
        if (run.trail.length > 1 || run.playing) {
          ctx.save();
          ctx.strokeStyle = TRAIL; ctx.lineWidth = 2.2; ctx.lineJoin = "round"; ctx.lineCap = "round";
          ctx.shadowColor = "rgba(184,139,224,0.6)"; ctx.shadowBlur = 6;
          ctx.beginPath();
          var tr = run.trail;
          ctx.moveTo(P[tr[0]][0], P[tr[0]][1]);
          for (var i = 1; i < tr.length - (run.from >= 0 && run.playing ? 1 : 0); i++) ctx.lineTo(P[tr[i]][0], P[tr[i]][1]);
          ctx.lineTo(robotP[0], robotP[1]);
          ctx.stroke();
          ctx.restore();
        }
        // objects already put down, at their destination
        run.placed.forEach(function (pl) {
          var p = P[pl[1]];
          ctx.fillStyle = OBJ; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.rect(p[0] + 6, p[1] - 12, 7, 7); ctx.fill(); ctx.stroke();
        });
        // the robot, and what it carries
        var pulse = REDUCED ? 0.5 : (Math.sin(t * 0.005) + 1) / 2;
        ctx.fillStyle = "rgba(184,139,224,0.22)";
        ctx.beginPath(); ctx.arc(robotP[0], robotP[1], 9 + pulse * 3, 0, 6.2832); ctx.fill();
        ctx.fillStyle = ROBOT; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.arc(robotP[0], robotP[1], 5, 0, 6.2832); ctx.fill(); ctx.stroke();
        if (run.held >= 0) {
          ctx.fillStyle = OBJ;
          ctx.beginPath(); ctx.rect(robotP[0] + 7, robotP[1] - 13, 7, 7); ctx.fill(); ctx.stroke();
        }
      }
    });
    hero.setData(hd);

    var ticker = heroCanvas.parentNode.querySelector(".ticker");
    var tkId = document.getElementById("tk-id");
    var tkLbl = document.getElementById("tk-lbl");
    var tkText = document.getElementById("tk-text");
    var tkEnts = document.getElementById("tk-ents");
    var tkBar = document.getElementById("tk-bar");
    var ti = 0, timer = 0;

    function actionText(a) {
      return a[0] + " " + a.slice(1).filter(function (x) { return x !== "robot" && !/_hand$/.test(x); }).join(" ");
    }
    function showGoal(task) {
      startRun(task);
      hero.highlight(task.ents);
      tkId.textContent = task.id;
      tkLbl.textContent = "Klickitat · goal";
      tkText.textContent = task.text;
      tkEnts.textContent = entityLine(hd, task, 6);
      tkBar.style.transform = "scaleX(0)";
    }
    function step() {
      var a = run.plan[run.k];
      run.t0 = performance.now();
      run.from = -1;
      if (a[0] === "move" && index[a[3]] !== undefined) {
        run.from = run.at; run.at = index[a[3]]; run.trail.push(run.at);
      } else if (/^pick/.test(a[0])) {
        run.held = index[a[a.length - 1]];
      } else if (/^place/.test(a[0])) {
        var dest = index[a[a.length - 1]];
        if (run.held >= 0 && dest !== undefined) run.placed.push([run.held, dest]);
        run.held = -1;
      }
      tkLbl.textContent = "Klickitat · plan " + (run.k + 1) + " / " + run.plan.length;
      tkEnts.textContent = actionText(a);
      tkBar.style.transform = "scaleX(" + ((run.k + 1) / run.plan.length) + ")";
    }
    function next() {
      var task = tasks[ti];
      if (!run.playing && run.k < 0) {
        if (!run.plan.length) { timer = setTimeout(advance, GOAL_MS); return; }
        run.playing = true;
      }
      run.k += 1;
      if (run.k < run.plan.length) {
        step();
        timer = setTimeout(next, run.dt);
      } else {
        run.playing = false; run.from = -1;
        tkLbl.textContent = "Klickitat · plan executed";
        tkEnts.textContent = run.plan.length + " actions · goal reached";
        timer = setTimeout(advance, DONE_MS);
      }
    }
    function advance() {
      ticker.classList.add("fade");
      timer = setTimeout(function () {
        ti = (ti + 1) % tasks.length;
        showGoal(tasks[ti]);
        ticker.classList.remove("fade");
        timer = setTimeout(next, GOAL_MS);
      }, FADE_MS);
    }
    function pausedLoop() {
      // wait while the hero is off-screen or the tab is hidden, then carry on
      if (document.hidden || !hero.visible) { timer = setTimeout(pausedLoop, 500); return; }
      next();
    }

    showGoal(tasks[0]);
    if (!REDUCED) {
      var _next = next;
      next = function () { if (document.hidden || !hero.visible) { timer = setTimeout(pausedLoop, 500); return; } _next(); };
      timer = setTimeout(next, GOAL_MS);
    }
  }

  /* ---------- Explorer ---------- */
  var exCanvas = document.getElementById("explore-canvas");
  if (exCanvas) {
    var ex = new SceneGraph(exCanvas, { pad: [0.13, 0.04, 0.1, 0.04] });
    var list = document.getElementById("ex-tasks");
    var counts = document.getElementById("ex-counts");
    var tip = document.getElementById("ex-tip");
    var scaleButtons = Array.prototype.slice.call(document.querySelectorAll(".seg button"));
    var current = "small";

    var selectTask = function (btn, task) {
      Array.prototype.forEach.call(list.children, function (c) { c.setAttribute("aria-pressed", String(c === btn)); });
      ex.highlight(task.ents);
    };

    var setScale = function (scale) {
      current = scale;
      var d = DATA[scale];
      ex.setData(d);
      scaleButtons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.scale === scale)); });
      var nObj = d.types.filter(function (t) { return t === "artifact"; }).length;
      counts.textContent = d.ids.length.toLocaleString("en-US") + " nodes · " +
        (d.edges.length / 2).toLocaleString("en-US") + " edges · " + nObj.toLocaleString("en-US") + " objects";
      list.textContent = "";
      d.tasks.forEach(function (task, k) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "task";
        b.id = "task-" + task.id;
        b.setAttribute("aria-pressed", "false");
        var tid = document.createElement("span"); tid.className = "tid"; tid.textContent = task.id;
        var body = document.createElement("span");
        var text = document.createElement("span"); text.textContent = task.text;
        var conds = document.createElement("span"); conds.className = "conds";
        task.conds.forEach(function (c) {
          var line = document.createElement("span"); line.className = "cond " + c[0];
          var tag = document.createElement("b"); tag.textContent = c[0];
          line.appendChild(tag); line.appendChild(document.createTextNode(c[1]));
          conds.appendChild(line);
        });
        body.appendChild(text); body.appendChild(conds);
        b.appendChild(tid); b.appendChild(body);
        b.addEventListener("click", function () { selectTask(b, task); });
        list.appendChild(b);
        if (k === 0) selectTask(b, task);
      });
    };
    scaleButtons.forEach(function (b) { b.addEventListener("click", function () { setScale(b.dataset.scale); }); });
    setScale("small");

    var onMove = function (ev) {
      var r = exCanvas.getBoundingClientRect();
      var x = ev.clientX - r.left, y = ev.clientY - r.top;
      var i = ex.nearest(x, y, ev.pointerType === "touch" ? 18 : 12);
      ex.hover = i;
      if (i >= 0) {
        var d = DATA[current];
        tip.hidden = false;
        tip.textContent = d.ids[i] + "  ·  " + TYPE_LABEL[d.types[i]];
        tip.style.left = Math.min(Math.max(ex.P[i][0], 80), r.width - 80) + "px";
        tip.style.top = ex.P[i][1] + "px";
      } else {
        tip.hidden = true;
      }
      ex.kick();
    };
    exCanvas.addEventListener("pointermove", onMove);
    exCanvas.addEventListener("pointerdown", onMove);
    exCanvas.addEventListener("pointerleave", function () { ex.hover = -1; tip.hidden = true; ex.kick(); });
  }

  /* ---------- Active section in the top nav ---------- */
  var links = Array.prototype.slice.call(document.querySelectorAll(".navlinks a"));
  if ("IntersectionObserver" in window && links.length) {
    var byId = {};
    links.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var groups = { "world-model": "world-model", architecture: "world-model", overview: "overview", abstract: "overview",
      highlights: "overview", replay: "replay", scalability: "scalability", clarification: "scalability",
      qualitative: "scalability", dataset: "scalability", bibtex: "bibtex" };
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var key = groups[en.target.id];
        links.forEach(function (a) { a.classList.toggle("on", a === byId[key]); });
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    document.querySelectorAll("main section[id]").forEach(function (sec) { obs.observe(sec); });
  }
})();
