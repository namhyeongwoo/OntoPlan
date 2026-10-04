# OntoPlan benchmark

Task instructions and evaluation conditions used in the paper.

```text
general/<Environment>.json   150 general tasks: 5 environments x 3 scales x 10 tasks (S01-S10, M01-M10, L01-L10)
```

The scenes are in `world_model/data/envs/` (see its README for the terms of use). The ambiguous and infeasible
instructions used for the paper's qualitative analysis are listed in its appendix.

## Task format

```json
{
  "id": "S01",
  "env": "Klickitat",
  "size": "small",
  "instruction": "I think I left my cell phone in the dining room on Floor B. Can you find it and bring it to the home office on Floor C?",
  "expected": {
    "at_end":   {"subject": "cell_phone_61", "predicate": "isInSpace", "object": "home_office_18"},
    "always":   [],
    "sometime": [],
    "ordering": []
  }
}
```

`expected` holds the checks used for scoring:

| Key | Meaning |
|---|---|
| `at_end` | must hold in the final state |
| `always` | list; each must hold in the initial state and after every action |
| `sometime` | list; each must hold after at least one action |
| `ordering` | list of `{"before", "after"}`; `before` must first hold no later than `after` |

A condition is a triple `{"subject", "predicate", "object"}` over the ontology vocabulary, or a combination with `{"and": [...]}`, `{"or": [...]}`, `{"not": {...}}`. Boolean properties use `"true"`/`"false"` as the object. `isInSpace` includes objects that are carried or contained, as inferred by the ontology.

## Scoring

`experiments/evaluator.py` executes a returned plan action by action on the world model, starting from the task's initial state, and reports:

- **Plan Returned** (`plan_generation`): a plan was returned;
- **Plan Executable** (`plan_execution`): every action's preconditions held;
- **Goal Reached** (`goal_success`): `at_end` holds in the reached state (also for partially executed plans);
- **Task Success** (`task_success`): the plan executed fully and all checks passed.

See `experiments/README.md` for running OntoPlan on the benchmark.
