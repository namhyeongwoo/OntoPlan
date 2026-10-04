"""Build docs/static/data/replays.js: recorded OntoPlan runs replayed on the project page.

Each replay is taken verbatim from a result file written by experiments.run (agent
reports, Task Formalizer conditions, Planning Manager subgoals, and the executed plan),
together with the initial states the page needs to animate the plan.

    python docs/scripts/build_task_replays.py --results experiments/results/final/full/general
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "static" / "data" / "replays.js"
GRAPH = ROOT / "docs" / "static" / "data" / "klickitat.js"

# (size, task id, short title shown on the selector)
TASKS = [
    ("small", "S02", "Clarify, then assume"),
    ("small", "S03", "Detour around a closed-off door"),
    ("medium", "M08", "Cook, then serve"),
    ("large", "L03", "Avoid the stairs in a large scene"),
]
AGENT = {"USER": "user", "flow_orchestrator": "fo", "scene_explorer": "se",
         "task_formalizer": "tf", "planning_manager": "pm"}


def trace(record):
    """Agent messages in order, as recorded."""
    steps = []
    for rep in record["agent_reports"]:
        who = AGENT.get(rep.get("agent"))
        if who == "user":
            steps.append({"who": "user", "text": rep["content"]})
        elif who == "fo":
            steps.append({"who": "fo", "to": AGENT.get(rep.get("next_agent"), rep.get("next_agent")),
                          "text": rep.get("reason", "")})
            if rep.get("question"):
                steps.append({"who": "fo", "to": "user", "text": rep["question"], "question": True})
        elif who == "se":
            steps.append({"who": "se", "text": rep.get("exploration_result", "")})
        elif who == "tf":  # only exploration requests are reported by the Task Formalizer
            steps.append({"who": "tf", "to": "fo", "text": rep.get("reason", "")})
        elif who == "pm":
            # Task Formalizer output (conditions) is stored in the state, not in a report
            cond = record["conditions"]
            lines = [["at_end", cond["at_end_condition"]]]
            lines += [["always", c["predicate_formula"]] for c in cond.get("always_conditions") or []]
            lines += [["sometime", c["predicate_formula"]] for c in cond.get("sometime_conditions") or []]
            steps.append({"who": "tf", "to": "pm", "conds": lines})
            for call in record.get("planning_calls", []):
                steps.append({"who": "pm", "to": "pddl",
                              "subgoals": [[sg["goal_state"], sg.get("description", "")] for sg in call["subgoals"]]})
            steps.append({"who": "pm", "to": "robot", "text": rep.get("reason", "")})
    return steps


def segments(record):
    """Plan segments per subgoal, from the final report ("[OK] <description> (<n> actions)")."""
    final = record["dialogue"][-1]["content"]
    return [[m.group(1), int(m.group(2))] for m in re.finditer(r"\[OK\] (.+?) \((\d+) actions\)", final)]


def initial_state(env, size, plan):
    world = json.loads((ROOT / "world_model" / "data" / "envs" / env / size / "world.json").read_text())
    ids = {a for action in plan for a in action.strip("()").split()[1:]}
    doors, states = {}, {}
    for loc_id, loc in world["locations"].items():
        if loc.get("type") == "door" and loc_id in ids:
            doors[loc_id] = bool(loc.get("doorIsOpen"))
        for item_id, item in (loc.get("items") or {}).items():
            if item_id in ids:
                states[item_id] = {k: item[k] for k in ("isOpen", "isSwitchedOn") if k in item}
    return world["robot"]["robotIsInSpace"], doors, states


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", default=str(ROOT / "experiments/results/final/full/general"))
    args = parser.parse_args()

    graph_text = GRAPH.read_text()
    graph = json.loads(graph_text[graph_text.index("{"):graph_text.rindex("}") + 1])
    replays = []
    for size, tid, title in TASKS:
        record = json.loads((Path(args.results) / f"Klickitat_{size}_{tid}.json").read_text())
        assert record["score"]["task_success"], f"{tid} is not a successful run"
        plan = record["plan"]
        missing = {a for action in plan for a in action.strip("()").split()[1:]} - set(graph[size]["ids"]) \
            - {"robot", "left_hand", "right_hand"}
        assert not missing, f"{tid}: ids missing from the scene graph: {missing}"
        start, doors, states = initial_state("Klickitat", size, plan)
        calls = record["llm_calls"]
        replays.append({
            "env": "Klickitat", "size": size, "id": tid, "title": title,
            "instruction": record["task"]["instruction"],
            "trace": trace(record),
            "plan": [a.strip("()") for a in plan],
            "segments": segments(record),
            "start": start, "doors": doors, "states": states,
            "stats": {"calls": len(calls),
                      "tokens": sum(c["input_tokens"] + c["output_tokens"] for c in calls),
                      "seconds": record.get("seconds")},
        })
    OUT.write_text("/* Generated by docs/scripts/build_task_replays.py from recorded runs. */\n"
                   "window.ONTOPLAN_REPLAYS = " + json.dumps(replays, separators=(",", ":")) + ";\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB, {len(replays)} replays)")


if __name__ == "__main__":
    main()
