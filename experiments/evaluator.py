"""Symbolic plan evaluation used for all methods (OntoPlan, ablations, baselines).

A plan is executed action by action on the world model from the task's initial state.
After every action the trajectory checks are updated:
  - always:   must hold in the initial state and after every executed action
  - sometime: must hold after at least one executed action
  - ordering: the `before` condition must first hold no later than the `after` condition
Execution stops at the first action whose preconditions fail. `at_end` is checked on the
state that was reached, so Goal Success can exceed Plan Execution (paper, Sec. 4.2).

Conditions use the benchmark's JSON format, e.g.
  {"subject": "book_78", "predicate": "isOntopOf", "object": "table_15"}
  {"and": [...]}, {"or": [...]}, {"not": {...}}
Boolean properties use "true"/"false" as the object; `isEmpty` is evaluated as "holds nothing".
"""

from typing import Any, Dict, List, Optional, Union

from agent.environment import reset_world_state
from agent.utils.action_executor import ActionExecutor
from world_model.core.manager import GraphDBManager

Condition = Union[Dict[str, Any], List[Any]]


class ConditionChecker:
    """Translate benchmark conditions to SPARQL ASK queries over the live world state."""

    def __init__(self, manager: GraphDBManager):
        self.manager = manager
        self.ns = manager.ONTOLOGY_NS

    def _pattern(self, cond: Condition) -> str:
        if isinstance(cond, list):
            return " .\n  ".join(self._pattern(c) for c in cond)
        if "and" in cond:
            return " .\n  ".join(self._pattern(c) for c in cond["and"])
        if "or" in cond:
            return " UNION ".join(f"{{ {self._pattern(c)} }}" for c in cond["or"])
        if "not" in cond:
            return f"FILTER NOT EXISTS {{ {self._pattern(cond['not'])} }}"
        s, p, o = cond["subject"], cond["predicate"], cond["object"]
        if p == "isEmpty":  # closed-world negation: the hand holds nothing
            return (f"FILTER NOT EXISTS {{ :{s} :holds ?_x }}" if o == "true"
                    else f"FILTER EXISTS {{ :{s} :holds ?_x }}")
        obj = o if o in ("true", "false") or o.startswith("?") else f":{o}"
        return f":{s} :{p} {obj}"

    def holds(self, cond: Condition) -> bool:
        query = f"PREFIX : <{self.ns}>\nASK {{\n  {self._pattern(cond)}\n}}"
        return bool(self.manager.query(query, infer=True).get("boolean", False))

    def explain(self, cond: Condition) -> Dict[str, Any]:
        """holds() plus a per-branch breakdown for top-level and/or conditions."""
        result: Dict[str, Any] = {"condition": cond, "passed": self.holds(cond)}
        for op in ("and", "or"):
            if isinstance(cond, dict) and op in cond:
                result["details"] = {"type": op, "sub_conditions": [
                    {"index": i, "condition": c, "passed": self.holds(c)} for i, c in enumerate(cond[op])]}
        return result


def evaluate_plan(plan: Optional[List[str]], expected: Dict[str, Any], env_id: str, env_size: str) -> Dict[str, Any]:
    """Execute a plan from the initial state of env_id/env_size and score it.

    Args:
        plan: actions such as "move robot kitchen_20 door_3" (parentheses optional); None = no plan
        expected: benchmark conditions with keys at_end, always, sometime, ordering

    Returns:
        dict with plan_generation, plan_execution, goal_success, task_success and per-check details
    """
    always = expected.get("always") or []
    sometime = expected.get("sometime") or []
    ordering = expected.get("ordering") or []
    result: Dict[str, Any] = {
        "plan_generation": bool(plan), "plan_execution": False,
        "goal_success": False, "task_success": False,
        "plan_length": len(plan or []), "executed_actions": 0, "checks": {},
    }
    if not plan:
        return result

    reset_world_state(env_id, env_size)
    manager = GraphDBManager()
    checker = ConditionChecker(manager)
    executor = ActionExecutor()

    always_violations: Dict[int, Dict[str, Any]] = {}
    sometime_first: Dict[int, int] = {}
    order_first: Dict[str, int] = {}
    execution_error = None
    for i, cond in enumerate(always):  # step 0: the initial state
        if not checker.holds(cond):
            always_violations[i] = {"condition_index": i, "condition": cond, "failed_at_step": 0, "action": None}
    for step, action in enumerate(plan, start=1):
        parts = action.strip().strip("()").split()
        outcome = executor.execute_action(parts[0], parts[1:])
        if not outcome["success"]:
            execution_error = {"step": step, "action": action, "error": outcome.get("error")}
            break
        result["executed_actions"] = step
        for i, cond in enumerate(always):
            if i not in always_violations and not checker.holds(cond):
                always_violations[i] = {"condition_index": i, "condition": cond, "failed_at_step": step, "action": action}
        for i, cond in enumerate(sometime):
            if i not in sometime_first and checker.holds(cond):
                sometime_first[i] = step
        for i, constraint in enumerate(ordering):
            for side in ("before", "after"):
                key = f"{i}:{side}"
                if key not in order_first and checker.holds(constraint[side]):
                    order_first[key] = step

    checks = result["checks"]
    if execution_error:
        checks["execution_error"] = execution_error
    if always:
        checks["always"] = {"passed": not always_violations, "violations": list(always_violations.values())}
    if sometime:
        checks["sometime"] = {"passed": len(sometime_first) == len(sometime),
                              "satisfied_at_step": {str(i): s for i, s in sometime_first.items()}}
    if ordering:
        ok = True
        for i in range(len(ordering)):
            after = order_first.get(f"{i}:after")
            before = order_first.get(f"{i}:before")
            if after is not None and (before is None or before > after):
                ok = False
        checks["ordering"] = {"passed": ok, "first_step": order_first}
    if expected.get("at_end"):
        checks["at_end"] = checker.explain(expected["at_end"])

    executor.close()
    result["plan_execution"] = execution_error is None
    result["goal_success"] = checks.get("at_end", {"passed": True})["passed"]
    result["task_success"] = (result["plan_execution"] and result["goal_success"]
                              and all(checks[k]["passed"] for k in ("always", "sometime", "ordering") if k in checks))
    return result
