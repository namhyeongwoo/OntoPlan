# Reproducing the experiments

Requires the installation in `INSTALL.md` (GraphDB running, Fast Downward built, `OPENAI_API_KEY` set).
Runs call GPT-4o; one pass over the 150 general tasks uses roughly 3M tokens.

```bash
# OntoPlan on the 150 general tasks (results/<name>/full/general/*.json)
python -m experiments.run --name paper

# Ablations (paper, Sec. 5.4)
python -m experiments.run --variant no_scene_query --name paper
python -m experiments.run --variant no_pddl_plan   --name paper

# Tables
python -m experiments.report --name paper
```

Runs are resumable: finished tasks are skipped. Use `--env`, `--size`, and `--ids` to run a subset.

Set `ONTOPLAN_MODEL` (e.g. `gpt-4o-2024-08-06`) to keep every run on the same GPT-4o snapshot, and pass
`--max-tpm` to stay under your tokens-per-minute limit. A task that fails because of the API or GraphDB
(rate limit, outage, out of memory) is not counted: it is written to `<task>.retry.json` and runs again
when you repeat the command.

## Modules

| File | Purpose |
|---|---|
| `run.py` | runs a variant on the general tasks, one fresh session per task, and scores the returned plan |
| `evaluator.py` | executes a plan on the world model and checks `at_end`, `always`, `sometime`, and `ordering` |
| `ablations.py` | `no_scene_query` (full scene in the prompt) and `no_pddl_plan` (LLM writes the actions) |
| `report.py` | per-environment, per-scale, and ablation summaries |
| `oracle.py` | solves every task from its expected conditions without an LLM, to check that it is solvable |
| `benchmark.py` | loads the tasks in `benchmark/` |
