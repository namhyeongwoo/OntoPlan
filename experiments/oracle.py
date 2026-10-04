"""Check that every benchmark task is solvable, without any LLM.

The expected conditions of each task are translated to PDDL and handed to the
PDDL plan tool directly (sometime conditions and ordering "before" states first,
then the final goal, with always conditions as trajectory constraints). The
resulting plan is then scored with the benchmark evaluator. A task that fails here
points to a problem in the scene data or in the task's expected conditions.

    python -m experiments.oracle                      # all general tasks
    python -m experiments.oracle --env Lindenwood --size large
"""

import argparse
import json
from typing import Any, Dict, List

from agent.environment import reset_world_state
from agent.tools.pddl_plan import pddl_plan
from experiments.benchmark import load_tasks
from experiments.evaluator import evaluate_plan


def to_pddl(cond: Any) -> str:
    """Translate a benchmark condition (JSON) into a PDDL formula over the domain predicates."""
    if isinstance(cond, list):
        return to_pddl({"and": cond})
    if "and" in cond:
        return "(and " + " ".join(to_pddl(c) for c in cond["and"]) + ")"
    if "or" in cond:
        return "(or " + " ".join(to_pddl(c) for c in cond["or"]) + ")"
    if "not" in cond:
        inner = cond["not"]
        if inner.get("predicate") == "holds" and str(inner.get("object", "")).startswith("?"):
            return f"(isEmpty {inner['subject']})"  # "holds nothing"
        return f"(not {to_pddl(inner)})"
    s, p, o = cond["subject"], cond["predicate"], cond["object"]
    if p == "isInSpace":
        return f"(robotIsInSpace {s} {o})" if s == "robot" else f"(artifactIsInSpace {s} {o})"
    if o in ("true", "false"):
        atom = f"({p} {s})"
        return atom if o == "true" else f"(not {atom})"
    if p == "holds" and o.startswith("?"):
        return f"(not (isEmpty {s}))"
    return f"({p} {s} {o})"


def _ids(cond: Any) -> List[str]:
    if isinstance(cond, list):
        return [i for c in cond for i in _ids(c)]
    for key in ("and", "or"):
        if key in cond:
            return [i for c in cond[key] for i in _ids(c)]
    if "not" in cond:
        return _ids(cond["not"])
    return [x for x in (cond["subject"], cond["object"]) if x not in ("true", "false") and not x.startswith("?")]


def solve_task(task: Dict[str, Any]) -> Dict[str, Any]:
    expected = task["expected"]
    steps = [to_pddl(c) for c in expected.get("sometime") or []]
    steps += [to_pddl(o["before"]) for o in expected.get("ordering") or []]
    at_end = to_pddl(expected["at_end"]) if expected.get("at_end") else None
    if at_end:
        steps.append(at_end)
    objects = sorted({i for k in ("at_end", "always", "sometime") for i in _ids(expected.get(k) or [])}
                     | {i for o in expected.get("ordering") or [] for i in _ids([o["before"], o["after"]])})

    reset_world_state(task["env"], task["size"])
    out = json.loads(pddl_plan.invoke({
        "subgoals": [{"goal_state": g, "description": g, "name": f"step{i}", "order": i} for i, g in enumerate(steps)],
        "task_description": task["instruction"],
        "always_conditions": [{"predicate_formula": to_pddl(c)} for c in expected.get("always") or []],
        "discovered_objects": objects,
        "state": {"at_end_condition": at_end or ""},
    }))
    plan = [line.strip() for sg in out["subgoal_results"] if sg["status"] == "success"
            for line in (sg.get("plan") or "").splitlines() if line.strip() and not line.startswith(";")]
    failed = [sg for sg in out["subgoal_results"] if sg["status"] != "success"]
    score = evaluate_plan(plan, expected, task["env"], task["size"])
    return {
        "id": f"{task['env']}/{task['size']}/{task['id']}",
        "solved": out["success"],
        "task_success": score["task_success"],
        "plan_length": len(plan),
        "planner_error": failed[0].get("error") if failed else None,
        "checks": score["checks"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env")
    parser.add_argument("--size")
    parser.add_argument("--out", help="write per-task results to this JSON file")
    args = parser.parse_args()

    results = []
    for task in load_tasks(env=args.env, size=args.size):
        r = solve_task(task)
        results.append(r)
        status = "ok" if r["task_success"] else "FAIL"
        print(f"{status:4s} {r['id']:28s} plan={r['plan_length']:3d} {r['planner_error'] or ''}"[:220], flush=True)
    bad = [r for r in results if not r["task_success"]]
    print(f"\n{len(results) - len(bad)}/{len(results)} tasks solvable and scored as successful")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
