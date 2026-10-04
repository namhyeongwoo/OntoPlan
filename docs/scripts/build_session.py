"""Build docs/static/data/session.js: a recorded multi-turn OntoPlan session for the project page.

The input is a session record (node-by-node updates of one LangGraph session plus the
world-model facts after each turn). Messages, tool calls, tool results, conditions, and
plans are taken from the record; tool results are shortened for display.

    python docs/scripts/build_session.py session_record.json
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "static" / "data" / "session.js"
AGENT = {"USER": "user", "flow_orchestrator": "fo", "scene_explorer": "se",
         "task_formalizer": "tf", "planning_manager": "pm"}
STATE_PREDICATES = ("isOpen", "isSwitchedOn", "doorIsOpen")


def short_args(args):
    return {k: v for k, v in args.items() if k not in ("reason", "discovered_objects", "always_conditions",
                                                       "session_timestamp", "results_dir") and v not in (None, "")}


def summarize(tool, content):
    """A short, faithful view of a tool result."""
    try:
        d = json.loads(content)
    except ValueError:
        return {"text": content[:300]}
    if tool == "semantic_search":
        res = d.get("results", [])
        hint = d.get("hint", "").split(". ")[0]
        return {"text": hint + ".", "ids": [r.get("id") for r in res][:8], "n": len(res),
                "rows": [{k: r[k] for k in ("id", "isInStorey", "isInSpace", "isOntopOf", "isInsideOf") if k in r}
                         for r in res[:4]]}
    if tool == "find_path":
        nodes = [d["from_space"]] + [hop["to"] for hop in d.get("path", [])]
        return {"text": f"path_exists: {d.get('path_exists')}, path_length: {d.get('path_length')}", "path": nodes}
    if tool == "pddl_plan":
        rows = []
        for sg in d.get("subgoal_results", []):
            n = len([l for l in (sg.get("plan") or "").splitlines() if l.strip().startswith("(")])
            rows.append([sg.get("description", ""), sg.get("status"), n])
        return {"text": f"success: {d.get('success')}, plan_length: {d.get('total_plan_length')}, "
                        f"plan_cost: {d.get('total_plan_cost')}", "subgoals": rows}
    return {"text": content[:300]}


def plan_of(content):
    d = json.loads(content)
    plan, segments = [], []
    for sg in d.get("subgoal_results", []):
        acts = [l.strip().strip("()") for l in (sg.get("plan") or "").splitlines() if l.strip().startswith("(")]
        segments.append([sg.get("description", ""), len(acts)])
        plan += acts
    return plan, segments


TITLES = ["Spatial question answering", "Grounding and executable planning", "Follow-up on the updated world model"]


def tag(steps, turn):
    """Label the steps that show the capabilities highlighted in the paper's qualitative figure."""
    for st in steps:
        tags = []
        if any(c["tool"] == "find_path" for c in st.get("calls", [])):
            tags.append("spatial reasoning")
        if st.get("answer"):
            tags.append("question answering")
        if st["who"] == "tf" and any(c[0] == "sometime" for c in st.get("conds", [])):
            tags.append("common-sense goals")
        if any(c["tool"] == "pddl_plan" for c in st.get("calls", [])):
            tags.append("executable plan")
        if st["who"] == "user" and turn == 2:
            tags.append("sequential task")
        if tags:
            st["tags"] = tags


def facts_dict(facts):
    return {(s, p): o for s, p, o in facts}


def build(record):
    turns, prev = [], None
    for k, turn in enumerate(record["turns"]):
        steps, plan, segments, pending = [], [], [], {}
        for ev in turn["events"]:
            up = ev["update"]
            for msg in up.get("scene_query_history", []) + up.get("pddl_plan_history", []):
                if msg["type"] == "ai" and msg["tool_calls"]:
                    calls = [c for c in msg["tool_calls"] if c["name"] != "finish_exploration"]
                    if calls:
                        who = "pm" if any(c["name"] == "pddl_plan" for c in calls) else "se"
                        step = {"who": who, "to": "tool", "calls": [{"tool": c["name"], "args": short_args(c["args"])} for c in calls]}
                        steps.append(step)
                        pending = {"step": step, "i": 0}
                elif msg["type"] == "tool" and pending:
                    call = pending["step"]["calls"][pending["i"]]
                    call["result"] = summarize(msg["name"], msg["content"])
                    pending["i"] += 1
                    if pending["i"] >= len(pending["step"]["calls"]):
                        pending = {}
                    if msg["name"] == "pddl_plan":
                        plan, segments = plan_of(msg["content"])
            for rep in up.get("agent_reports", []):
                who = AGENT.get(rep.get("agent"))
                if who == "user":
                    steps.append({"who": "user", "text": rep["content"]})
                elif who == "fo":
                    nxt = AGENT.get(rep.get("next_agent"), rep.get("next_agent"))
                    if rep.get("question"):
                        steps.append({"who": "fo", "to": "user", "text": rep["question"], "answer": True})
                    else:
                        steps.append({"who": "fo", "to": nxt, "text": rep.get("reason", "")})
                elif who == "se":
                    steps.append({"who": "se", "to": "fo", "text": rep.get("exploration_result", "")})
                elif who == "tf":
                    steps.append({"who": "tf", "to": "fo", "text": rep.get("reason", "")})
                elif who == "pm":
                    steps.append({"who": "pm", "to": "robot", "text": rep.get("reason", "")})
            if up.get("at_end_condition"):
                conds = [["at_end", up["at_end_condition"]]]
                conds += [["always", c["predicate_formula"]] for c in up.get("always_conditions") or []]
                conds += [["sometime", c["predicate_formula"]] for c in up.get("sometime_conditions") or []]
                steps.append({"who": "tf", "to": "pm", "conds": conds})

        now = {tuple(f) for f in turn["facts_after"]}
        before = facts_dict(prev if prev is not None else now)
        start = before.get(("robot", "robotIsInSpace"))
        ids = {a for action in plan for a in action.split()[1:]}
        doors = {s: before.get((s, "doorIsOpen")) == "true" for (s, p) in before if p == "doorIsOpen" and s in ids}
        states = {}
        for (s, p), o in before.items():
            if s in ids and p in ("isOpen", "isSwitchedOn"):
                states.setdefault(s, {})[p] = o == "true"
        old = prev if prev is not None else now
        if plan:
            steps.append({"who": "world", "added": [list(f) for f in sorted(now - old)],
                          "removed": [list(f) for f in sorted(old - now)]})
        tag(steps, k)
        turns.append({"id": f"Turn {k + 1}", "title": TITLES[k] if k < len(TITLES) else "", "user": turn["user"],
                      "trace": steps, "plan": plan,
                      "segments": segments, "start": start, "doors": doors, "states": states})
        prev = now
    return turns


def main():
    record = json.loads(Path(sys.argv[1]).read_text())
    turns = build(record)
    OUT.write_text("/* Generated by docs/scripts/build_session.py from a recorded multi-turn session. */\n"
                   "window.ONTOPLAN_SESSION = " + json.dumps({"env": record["env"], "size": record["size"], "turns": turns},
                                                              separators=(",", ":")) + ";\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")
    for t in turns:
        print(t["id"], len(t["trace"]), "steps,", len(t["plan"]), "actions, start", t["start"], [s["who"] for s in t["trace"]])


if __name__ == "__main__":
    main()
