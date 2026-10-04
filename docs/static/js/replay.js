/* Recorded-run players for the OntoPlan project page, drawn on the Klickitat scene graph
   (window.KLICKITAT) with the shared SceneGraph renderer.
   - Task replay   (#replay):  window.ONTOPLAN_REPLAYS, docs/scripts/build_task_replays.py
   - Session player (#session): window.ONTOPLAN_SESSION, docs/scripts/build_session.py */
(function () {
  "use strict";

  var GRAPHS = window.KLICKITAT, SceneGraph = window.OntoSceneGraph;
  if (!GRAPHS || !SceneGraph) return;

  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var AGENT = {
    user: "User", fo: "Flow Orchestrator", se: "Scene Explorer", tf: "Task Formalizer",
    pm: "Planning Manager", robot: "Robot", pddl: "PDDL plan tool", tool: "tool", world: "World model"
  };
  var STEP_MS = 1500, ACTION_MS = 560;
  var ROBOT = "#c89cf2", TRAIL = "rgba(200,156,242,0.75)", HELD = "#f5b041", QUERY = "rgba(127,176,227,0.85)";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function parse(action) {
    var p = action.split(/\s+/);
    return { name: p[0], args: p.slice(1) };
  }

  /* cfg: { prefix, items, size(item), title(item), sub(item), meta(item), done(item), autoplay } */
  function createPlayer(cfg) {
    var $ = function (id) { return document.getElementById(cfg.prefix + "-" + id); };
    var canvas = $("canvas"), picker = $("tasks"), logEl = $("log"), caption = $("caption"), progress = $("progress");
    var btnPlay = $("play"), btnPrev = $("prev"), btnNext = $("next"), btnRestart = $("restart"), btnSpeed = $("speed"), meta = $("meta");
    if (!canvas) return;

    var R = null, index = {}, events = [], rows = [];
    var cur = 0, frac = 0, playing = false, speed = 1, last = 0, started = false;
    var sg = new SceneGraph(canvas, {
      pad: [0.08, 0.04, 0.1, 0.04], labels: true,
      busy: function () { return playing; },
      overlay: function (ctx, P, t) { drawOverlay(ctx, P, t); }
    });

    /* ---------- timeline: messages, then plan actions, then the world-model update ---------- */
    function buildEvents() {
      events = [];
      R.trace.forEach(function (step) { if (step.who !== "world") events.push({ kind: "msg", step: step }); });
      var seg = 0, left = R.segments.length ? R.segments[0][1] : R.plan.length;
      R.plan.forEach(function (a, i) {
        while (left === 0 && seg < R.segments.length - 1) { seg++; left = R.segments[seg][1]; }
        events.push({ kind: "act", i: i, action: parse(a), seg: seg });
        left--;
      });
      R.trace.forEach(function (step) { if (step.who === "world") events.push({ kind: "msg", step: step }); });
      events.push({ kind: "done" });
    }

    function stateAt(n) {
      var st = { at: R.start, path: [R.start], held: {}, placed: {}, doors: {}, items: {}, touched: {} };
      Object.keys(R.doors || {}).forEach(function (d) { st.doors[d] = R.doors[d]; });
      Object.keys(R.states || {}).forEach(function (k) {
        st.items[k] = {};
        Object.keys(R.states[k]).forEach(function (s) { st.items[k][s] = R.states[k][s]; });
      });
      for (var i = 0; i < n; i++) {
        var a = parse(R.plan[i]), g = a.args, x;
        switch (a.name) {
          case "move": st.at = g[2]; st.path.push(g[2]); break;
          case "open-door": st.doors[g[1]] = true; st.touched[g[1]] = 1; break;
          case "close-door": st.doors[g[1]] = false; st.touched[g[1]] = 1; break;
          case "pick-one-hand": x = g[2]; st.held[x] = 1; delete st.placed[x]; break;
          case "pick-two-hands": x = g[3]; st.held[x] = 1; delete st.placed[x]; break;
          case "place-to-location-one-hand": case "place-in-one-hand": case "place-on-one-hand":
            x = g[2]; delete st.held[x]; st.placed[x] = g[3]; break;
          case "place-to-location-two-hands": case "place-in-two-hands": case "place-on-two-hands":
            x = g[3]; delete st.held[x]; st.placed[x] = g[4]; break;
          case "open": case "close": case "power-on": case "power-off":
            x = g[1]; st.items[x] = st.items[x] || {};
            if (a.name === "open" || a.name === "close") st.items[x].isOpen = a.name === "open";
            else st.items[x].isSwitchedOn = a.name === "power-on";
            st.touched[x] = 1; break;
        }
      }
      return st;
    }

    function actionsDone() {
      var n = 0;
      for (var k = 0; k < cur && k < events.length; k++) if (events[k].kind === "act") n++;
      return n;
    }

    /* ---------- drawing ---------- */
    function forbidden() {
      var out = [];
      R.trace.forEach(function (s) {
        (s.conds || []).forEach(function (c) {
          if (c[0] !== "always") return;
          var re = /\(not \(robotIsInSpace robot ([\w-]+)\)\)/g, m;
          while ((m = re.exec(c[1]))) out.push(m[1]);
        });
      });
      return out;
    }

    function label(ctx, x, y, text, color) {
      ctx.font = "500 11px 'JetBrains Mono', ui-monospace, monospace";
      ctx.textBaseline = "middle";
      var w = ctx.measureText(text).width;
      var lx = Math.min(Math.max(x + 10, 4), sg.w - w - 8);
      ctx.fillStyle = "rgba(8,12,22,0.8)";
      ctx.fillRect(lx - 4, y - 9, w + 8, 18);
      ctx.fillStyle = color || "#fff";
      ctx.fillText(text, lx, y);
    }

    function drawOverlay(ctx, P, t) {
      if (!R) return;
      var n = actionsDone(), st = stateAt(n);
      var ev = events[cur], moving = ev && ev.kind === "act" && ev.action.name === "move" && playing;
      var pos = function (id) { var i = index[id]; return i === undefined ? null : P[i]; };

      // paths returned by find_path calls so far (dashed)
      for (var k = 0; k <= cur && k < events.length; k++) {
        var s = events[k].kind === "msg" && events[k].step;
        (s && s.calls || []).forEach(function (c) {
          var pts = ((c.result && c.result.path) || []).map(pos).filter(Boolean);
          if (pts.length < 2) return;
          ctx.save();
          ctx.setLineDash([5, 4]); ctx.strokeStyle = QUERY; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
          for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
          ctx.stroke(); ctx.restore();
          var end = pts[pts.length - 1];
          label(ctx, end[0], end[1] - 14, c.args.to_id + " · " + (pts.length - 1) + " hops", "#bcd8f5");
        });
      }

      forbidden().forEach(function (id) {
        var p = pos(id); if (!p) return;
        ctx.strokeStyle = "#ff6b6b"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(p[0], p[1], 9, 0, 6.2832); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(p[0] - 5, p[1] - 5); ctx.lineTo(p[0] + 5, p[1] + 5);
        ctx.moveTo(p[0] + 5, p[1] - 5); ctx.lineTo(p[0] - 5, p[1] + 5); ctx.stroke();
        label(ctx, p[0], p[1] + 16, id + " · avoid", "#ff9b9b");
      });

      var pts = st.path.map(pos).filter(Boolean);
      var robotP = pts[pts.length - 1];
      if (moving) {
        var to = pos(ev.action.args[2]);
        var e = REDUCED ? 1 : Math.min(frac, 1), q = e < 0.5 ? 2 * e * e : 1 - Math.pow(-2 * e + 2, 2) / 2;
        if (robotP && to) robotP = [robotP[0] + (to[0] - robotP[0]) * q, robotP[1] + (to[1] - robotP[1]) * q];
      }
      if (pts.length > 1 || moving) {
        ctx.strokeStyle = TRAIL; ctx.lineWidth = 2.4; ctx.lineJoin = "round"; ctx.lineCap = "round";
        ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
        for (var j = 1; j < pts.length; j++) ctx.lineTo(pts[j][0], pts[j][1]);
        if (moving && robotP) ctx.lineTo(robotP[0], robotP[1]);
        ctx.stroke();
      }

      Object.keys(st.doors).forEach(function (d) {
        if (!st.touched[d] && n === 0) return;
        var p = pos(d); if (!p) return;
        var open = st.doors[d];
        ctx.strokeStyle = open ? "#5ccf8a" : "#9aa6b8"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(p[0], p[1], 7, 0, 6.2832); ctx.stroke();
        if (st.touched[d]) label(ctx, p[0], p[1] - 14, d + (open ? " · open" : " · closed"), open ? "#9be8b8" : "#c7cfdb");
      });
      Object.keys(st.items).forEach(function (x) {
        if (!st.touched[x]) return;
        var p = pos(st.placed[x] || x); if (!p) return;
        var s = st.items[x], bits = [];
        if (s.isOpen !== undefined) bits.push(s.isOpen ? "open" : "closed");
        if (s.isSwitchedOn !== undefined) bits.push(s.isSwitchedOn ? "on" : "off");
        label(ctx, p[0], p[1] + 15, x + " · " + bits.join(", "), "#ffd08a");
      });
      Object.keys(st.placed).forEach(function (x) {
        var p = pos(st.placed[x]); if (!p) return;
        ctx.fillStyle = HELD; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.rect(p[0] + 5, p[1] - 12, 8, 8); ctx.fill(); ctx.stroke();
        label(ctx, p[0] + 6, p[1] - 22, x + " → " + st.placed[x], "#ffd08a");
      });

      if (robotP) {
        var pulse = REDUCED ? 0.5 : (Math.sin(t * 0.005) + 1) / 2;
        ctx.fillStyle = "rgba(200,156,242,0.22)";
        ctx.beginPath(); ctx.arc(robotP[0], robotP[1], 12 + pulse * 4, 0, 6.2832); ctx.fill();
        ctx.fillStyle = ROBOT; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(robotP[0], robotP[1], 7, 0, 6.2832); ctx.fill(); ctx.stroke();
        var held = Object.keys(st.held);
        held.forEach(function (x, i) {
          ctx.fillStyle = HELD; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.rect(robotP[0] + 8 + i * 11, robotP[1] - 15, 8, 8); ctx.fill(); ctx.stroke();
        });
        label(ctx, robotP[0] + 2, robotP[1] + 17, "robot" + (held.length ? " · holds " + held.join(", ") : ""), "#e6d2fb");
      }
    }

    /* ---------- side panel ---------- */
    function fmtArgs(args) {
      return Object.keys(args).filter(function (k) { return k !== "subgoals" && k !== "task_description"; })
        .map(function (k) { return k + "=" + JSON.stringify(args[k]); }).join(", ");
    }

    function callCard(c) {
      var box = el("details", "rp-call");
      var sum = el("summary");
      sum.appendChild(el("code", "rp-fn", c.tool + "(" + fmtArgs(c.args) + ")"));
      box.appendChild(sum);
      if (c.args.subgoals) {
        var ol = el("ol", "rp-subgoals");
        c.args.subgoals.forEach(function (sgl) {
          var li = el("li");
          li.appendChild(el("code", "", sgl.goal_state));
          if (sgl.description) li.appendChild(el("span", "rp-desc", sgl.description));
          ol.appendChild(li);
        });
        box.appendChild(ol);
      }
      var r = c.result;
      if (r) {
        var res = el("div", "rp-result");
        res.appendChild(el("div", "rp-res-text", "→ " + r.text));
        if (r.ids && r.ids.length) res.appendChild(el("div", "rp-res-ids", r.ids.join(" · ") + (r.n > r.ids.length ? " · +" + (r.n - r.ids.length) : "")));
        if (r.path) res.appendChild(el("div", "rp-res-ids", r.path.join(" → ")));
        if (r.subgoals) r.subgoals.forEach(function (s) {
          res.appendChild(el("div", "rp-res-ids", (s[1] === "success" ? "✓ " : "✗ ") + s[0] + " · " + s[2] + " actions"));
        });
        box.appendChild(res);
        sum.appendChild(el("span", "rp-res-peek", r.path ? (r.path.length - 1) + " hops" : r.ids ? r.n + " results" : r.subgoals ? "plan found" : ""));
      }
      return box;
    }

    function msgRow(step) {
      var row = el("div", "rp-msg " + step.who);
      var head = el("div", "rp-who");
      head.appendChild(el("span", "rp-agent", AGENT[step.who]));
      if (step.to && step.to !== "tool") head.appendChild(el("span", "rp-to", "→ " + (AGENT[step.to] || step.to)));
      if (step.calls) head.appendChild(el("span", "rp-to", "tool call" + (step.calls.length > 1 ? "s (parallel)" : "")));
      if (step.answer) head.appendChild(el("span", "rp-tag", "answer"));
      if (step.who === "user" && /Do not ask follow-up questions/.test(step.text || "")) head.appendChild(el("span", "rp-tag", "fixed auto-reply"));
      (step.tags || []).forEach(function (t) { head.appendChild(el("span", "rp-tag accent", t)); });
      row.appendChild(head);
      if (step.text) row.appendChild(el("div", "rp-text", step.text));
      if (step.calls) step.calls.forEach(function (c) { row.appendChild(callCard(c)); });
      if (step.conds) {
        var box = el("div", "rp-conds");
        step.conds.forEach(function (c) {
          var line = el("div", "cond " + c[0]);
          line.appendChild(el("b", "", c[0]));
          line.appendChild(document.createTextNode(c[1]));
          box.appendChild(line);
        });
        row.appendChild(box);
      }
      if (step.subgoals) {
        var ol = el("ol", "rp-subgoals");
        step.subgoals.forEach(function (sgl) {
          var li = el("li");
          li.appendChild(el("code", "", sgl[0]));
          if (sgl[1]) li.appendChild(el("span", "rp-desc", sgl[1]));
          ol.appendChild(li);
        });
        row.appendChild(ol);
      }
      if (step.who === "world") {
        var diff = el("div", "rp-diff");
        step.removed.forEach(function (f) { diff.appendChild(el("div", "del", "− " + f.join(" "))); });
        step.added.forEach(function (f) { diff.appendChild(el("div", "add", "+ " + f.join(" "))); });
        row.appendChild(diff);
      }
      return row;
    }

    function buildLog() {
      logEl.textContent = "";
      rows = [];
      var actBox = null, lastSeg = -1;
      events.forEach(function (ev) {
        var row;
        if (ev.kind === "msg") {
          row = msgRow(ev.step);
        } else if (ev.kind === "act") {
          if (!actBox) {
            var wrap = el("div", "rp-msg robot");
            var head = el("div", "rp-who");
            head.appendChild(el("span", "rp-agent", "Robot"));
            head.appendChild(el("span", "rp-to", R.plan.length + " actions"));
            wrap.appendChild(head);
            actBox = el("ol", "rp-actions");
            wrap.appendChild(actBox);
            logEl.appendChild(wrap);
          }
          // headers for every subgoal up to this one, including those that needed no actions
          while (lastSeg < ev.seg && R.segments.length > 1) {
            lastSeg++;
            actBox.appendChild(el("li", "rp-seg", "subgoal " + (lastSeg + 1) + " · " + R.segments[lastSeg][0] +
              (R.segments[lastSeg][1] ? "" : " (already true, 0 actions)")));
          }
          row = el("li", "rp-act", R.plan[ev.i]);
          actBox.appendChild(row);
          rows.push(row);
          return;
        } else {
          row = el("div", "rp-msg done", cfg.done(R));
        }
        logEl.appendChild(row);
        rows.push(row);
      });
    }

    function idsIn(step) {
      var txt = (step.text || "") + " " + (step.conds || []).map(function (c) { return c[1]; }).join(" ") +
        " " + (step.subgoals || []).map(function (s) { return s[0]; }).join(" ");
      (step.calls || []).forEach(function (c) {
        txt += " " + JSON.stringify(c.args) + " " + ((c.result && c.result.ids) || []).join(" ");
      });
      (step.added || []).forEach(function (f) { txt += " " + f.join(" "); });
      var ids = [], m, re = /[a-z][a-z_]*_\d+(?:_\d+)?/g;
      while ((m = re.exec(txt))) if (index[m[0]] !== undefined && ids.indexOf(m[0]) < 0) ids.push(m[0]);
      return ids.slice(0, 14);
    }

    function syncPanel() {
      rows.forEach(function (r, k) {
        r.classList.toggle("future", k > cur);
        r.classList.toggle("now", k === cur);
      });
      var now = rows[cur];
      if (now) {
        var top = now.getBoundingClientRect().top - logEl.getBoundingClientRect().top + logEl.scrollTop;
        var bottom = top + now.offsetHeight;
        if (top < logEl.scrollTop || bottom > logEl.scrollTop + logEl.clientHeight) {
          logEl.scrollTo({ top: Math.max(top - logEl.clientHeight / 3, 0), behavior: REDUCED ? "auto" : "smooth" });
        }
      }
      var ev = events[cur], text;
      if (ev.kind === "msg") text = AGENT[ev.step.who] + (ev.step.calls ? " · " + ev.step.calls.map(function (c) { return c.tool; }).join(", ") :
        ev.step.to ? " → " + (AGENT[ev.step.to] || ev.step.to) : "");
      else if (ev.kind === "act") text = (ev.i + 1) + "/" + R.plan.length + "  (" + R.plan[ev.i] + ")";
      else text = "Done";
      caption.textContent = text;
      progress.style.width = (100 * cur / Math.max(events.length - 1, 1)) + "%";
      btnPlay.textContent = playing ? "Pause" : (cur >= events.length - 1 ? "Replay" : "Play");
      btnPlay.setAttribute("aria-pressed", String(playing));

      var ids = ev.kind === "act" ? ev.action.args.filter(function (a) { return a !== "robot" && !/_hand$/.test(a); })
        : ev.kind === "msg" ? idsIn(ev.step) : [];
      sg.highlight(ids.map(function (id) { return index[id]; }).filter(function (i) { return i !== undefined; }));
    }

    /* ---------- playback ---------- */
    function durationOf(ev) {
      if (!ev) return 0;
      if (ev.kind === "msg") {
        var len = (ev.step.text || "").length + (ev.step.calls ? 260 * ev.step.calls.length : 0) + (ev.step.added ? 400 : 0);
        return STEP_MS + Math.min(len * 4, 2600);
      }
      if (ev.kind === "act") return ACTION_MS;
      return 0;
    }
    function go(k) {
      cur = Math.max(0, Math.min(events.length - 1, k));
      frac = 0;
      if (cur >= events.length - 1) playing = false;
      syncPanel();
      sg.kick();
    }
    function tick(t) {
      if (!playing) return;
      if (!last) last = t;
      var dt = (t - last) * speed; last = t;
      var d = durationOf(events[cur]);
      frac += d ? dt / d : 1;
      if (frac >= 1) go(cur + 1);
      if (playing) requestAnimationFrame(tick);
    }
    function play() {
      if (cur >= events.length - 1) go(0);
      playing = true; last = 0;
      syncPanel(); sg.kick();
      requestAnimationFrame(tick);
    }
    function pause() { playing = false; syncPanel(); }

    function load(k) {
      R = cfg.items[k];
      var G = GRAPHS[cfg.size(R)];
      index = {};
      G.ids.forEach(function (id, i) { index[id] = i; });
      sg.setData(G);
      buildEvents();
      buildLog();
      Array.prototype.forEach.call(picker.children, function (b, j) { b.setAttribute("aria-pressed", String(j === k)); });
      meta.textContent = cfg.meta(R);
      playing = false;
      go(0);
    }

    cfg.items.forEach(function (r, k) {
      var b = el("button", "rp-task");
      b.type = "button";
      b.setAttribute("aria-pressed", "false");
      b.appendChild(el("span", "tid", cfg.tag(r)));
      var body = el("span", "rp-task-body");
      body.appendChild(el("span", "rp-task-title", cfg.title(r)));
      body.appendChild(el("span", "rp-task-text", cfg.sub(r)));
      b.appendChild(body);
      b.addEventListener("click", function () { load(k); if (!REDUCED) play(); });
      picker.appendChild(b);
    });
    btnPlay.addEventListener("click", function () { playing ? pause() : play(); });
    btnPrev.addEventListener("click", function () { pause(); go(cur - 1); });
    btnNext.addEventListener("click", function () { pause(); go(cur + 1); });
    btnRestart.addEventListener("click", function () { go(0); play(); });
    btnSpeed.addEventListener("click", function () {
      speed = speed === 1 ? 2 : speed === 2 ? 4 : 1;
      btnSpeed.textContent = speed + "×";
    });
    load(0);

    if (cfg.autoplay !== false && !REDUCED && "IntersectionObserver" in window) {
      new IntersectionObserver(function (es, obs) {
        if (es[0].isIntersecting && !started) { started = true; play(); obs.disconnect(); }
      }, { threshold: 0.45 }).observe(canvas);
    }
  }

  if (window.ONTOPLAN_REPLAYS) {
    createPlayer({
      prefix: "rp", items: window.ONTOPLAN_REPLAYS,
      size: function (r) { return r.size; },
      tag: function (r) { return r.size.charAt(0).toUpperCase() + " · " + r.id; },
      title: function (r) { return r.title; },
      sub: function (r) { return r.instruction; },
      meta: function (r) {
        return r.env + " · " + r.size + " · " + r.id + "  ·  " + r.stats.calls + " LLM calls · " + (r.stats.tokens / 1000).toFixed(1) + "k tokens";
      },
      done: function () { return "Done · scored as a Task Success by the benchmark evaluator."; }
    });
  }

  var S = window.ONTOPLAN_SESSION;
  if (S) {
    createPlayer({
      prefix: "ss", items: S.turns, autoplay: false,
      size: function () { return S.size; },
      tag: function (t) { return t.id; },
      title: function (t) { return t.title || t.id; },
      sub: function (t) { return t.user; },
      meta: function (t) { return S.env + " · " + S.size + " · one session · " + t.id; },
      done: function (t) {
        return t.plan.length ? "Turn complete · the next turn starts from this updated world model."
          : "Answered from the world model; no plan was needed.";
      }
    });
  }
})();
