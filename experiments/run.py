"""Run OntoPlan (or an ablation variant) on benchmark tasks and score the results.

Each task runs in a fresh session from the environment's initial state, following the
paper's non-interactive protocol: clarification questions get a fixed automatic reply.

    python -m experiments.run --variant full --name rerun
    python -m experiments.run --env Klickitat --size small --ids S01 S02 --name rerun

Results: experiments/results/<name>/<variant>/general/<env>_<size>_<id>.json (existing files
are skipped, so an interrupted run can be resumed). Summaries: python -m experiments.report
"""

import argparse
import json
import logging
import time
import traceback
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
import requests
from openai import OpenAIError

from agent.graph import RECURSION_LIMIT
from agent.state import AgentNames
from experiments.ablations import VARIANTS, build_variant
from experiments.benchmark import load_tasks
from experiments.evaluator import evaluate_plan

RESULTS_DIR = Path(__file__).resolve().parent / "results"
AUTO_REPLY = "Do not ask follow-up questions. Make reasonable assumptions and continue planning."
MAX_AUTO_REPLIES = 10

logger = logging.getLogger("experiments.run")


class LLMUsage(BaseCallbackHandler):
    """Record every LLM call with the graph node that made it."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self._node: Dict[Any, str] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        self._node[run_id] = (metadata or {}).get("langgraph_node", "")

    def on_llm_end(self, response, *, run_id, **kwargs):
        for generations in response.generations:
            for g in generations:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                metadata = getattr(getattr(g, "message", None), "response_metadata", None) or {}
                self.calls.append({"agent": self._node.pop(run_id, ""),
                                   "model": metadata.get("model_name", ""),
                                   "input_tokens": usage.get("input_tokens", 0),
                                   "output_tokens": usage.get("output_tokens", 0)})


def _extract_plan(values: Dict[str, Any]) -> List[str]:
    """Actions of the plan returned for this instruction.

    Only an approved plan (sent to the robot) counts; a run without one returns no plan.
    """
    def actions(text):
        return [l.strip() for l in (text or "").splitlines() if l.strip() and not l.strip().startswith(";")]

    return [a for sg in values.get("subgoal_results", []) if sg.get("status") == "success"  # one session per task
            for a in actions(sg.get("plan"))]


def _is_infrastructure_error(e: Exception) -> bool:
    """API or GraphDB failures: not a result of the method, so the task is run again later."""
    if isinstance(e, (OpenAIError, ConnectionError, TimeoutError, requests.RequestException)):
        return True
    return isinstance(e, RuntimeError) and str(e).startswith(("SPARQL", "Failed to load", "Export failed"))


def run_task(task: Dict[str, Any], variant: str) -> Dict[str, Any]:
    usage = LLMUsage()
    graph = build_variant(variant).compile(checkpointer=MemorySaver(), interrupt_after=[AgentNames.ROBOT])
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": RECURSION_LIMIT,
              "callbacks": [usage]}
    record: Dict[str, Any] = {"task": task, "variant": variant, "auto_replies": 0, "error": None}
    start = time.time()
    try:
        graph.invoke({"env_id": task["env"], "env_size": task["size"]}, config)
        reply = task["instruction"]
        while True:
            graph.invoke(Command(resume=reply), config)
            state = graph.get_state(config)
            waiting_for_user = state.next and state.next[0] == AgentNames.USER and not state.values.get("awaiting_instruction")
            if not waiting_for_user:
                break
            if record["auto_replies"] >= MAX_AUTO_REPLIES:
                record["error"] = f"stopped after {MAX_AUTO_REPLIES} clarification questions"
                break
            record["auto_replies"] += 1
            reply = AUTO_REPLY
    except Exception as e:
        record["traceback"] = traceback.format_exc()
        if _is_infrastructure_error(e):
            record["retry_error"] = f"{type(e).__name__}: {e}"
            return record
        record["error"] = f"{type(e).__name__}: {e}"  # a failure of the method; the task is scored as is
    record["seconds"] = round(time.time() - start, 1)

    values = graph.get_state(config).values
    plan = _extract_plan(values)
    record.update({
        "plan": plan,
        "conditions": {k: values.get(k) for k in ("at_end_condition", "always_conditions", "sometime_conditions")},
        "discovered_objects": [o.get("id") for o in values.get("discovered_objects", []) if isinstance(o, dict)],
        "agent_reports": values.get("agent_reports", []),
        "planning_calls": [{k: v for k, v in tc["args"].items() if k in ("subgoals", "task_description")}
                           for m in values.get("pddl_plan_history", []) for tc in getattr(m, "tool_calls", None) or []
                           if tc.get("name") == "pddl_plan"],
        "dialogue": values.get("dialogue_history", []),
        "llm_calls": usage.calls,
    })
    try:
        record["score"] = evaluate_plan(plan, task["expected"], task["env"], task["size"])
    except Exception as e:
        if not _is_infrastructure_error(e):
            raise
        record["retry_error"] = f"{type(e).__name__}: {e}"
        record["traceback"] = traceback.format_exc()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", default="full", choices=VARIANTS)
    parser.add_argument("--name", default="default", help="run name (results subdirectory)")
    parser.add_argument("--env")
    parser.add_argument("--size")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--dry-run", action="store_true", help="list the tasks without running them")
    parser.add_argument("--max-tpm", type=int, default=0,
                        help="pause between tasks to stay under this many tokens per minute (0 = no limit)")
    parser.add_argument("--max-errors", type=int, default=3,
                        help="stop after this many consecutive tasks fail with API or GraphDB errors")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
    tasks = load_tasks(env=args.env, size=args.size, ids=args.ids)
    out_dir = RESULTS_DIR / args.name / args.variant / "general"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(tasks)} tasks -> {out_dir}")
    recent = deque()  # (finish time, tokens) of tasks in the last minute, for --max-tpm
    retry_errors = 0
    for task in tasks:
        path = out_dir / f"{task['env']}_{task['size']}_{task['id']}.json"
        if path.exists() or args.dry_run:
            print(f"{'skip' if path.exists() else 'todo'} {path.name}")
            continue
        record = run_task(task, args.variant)
        tokens = sum(c["input_tokens"] + c["output_tokens"] for c in record["llm_calls"]) if "llm_calls" in record else 0

        if record.get("retry_error"):
            # Not saved as a result, so the next run retries this task
            path.with_suffix(".retry.json").write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))
            retry_errors += 1
            print(f"{path.stem:32s} RETRY LATER: {record['retry_error'][:160]}", flush=True)
            if retry_errors >= args.max_errors:
                print(f"Stopping after {retry_errors} consecutive API/GraphDB errors. Rerun the same command to resume.")
                break
            time.sleep(30 * retry_errors)
            continue
        retry_errors = 0
        path.with_suffix(".retry.json").unlink(missing_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))
        outcome = "success" if record["score"]["task_success"] else "fail"
        models = sorted({c.get("model") for c in record["llm_calls"] if c.get("model")})
        print(f"{path.stem:32s} {outcome:22s} plan={len(record['plan']):3d} tokens={tokens:6d} "
              f"{record['seconds']:5.0f}s {','.join(models)} {record['error'] or ''}", flush=True)

        if args.max_tpm:
            now = time.time()
            recent.append((now, tokens))
            while recent and now - recent[0][0] > 60:
                recent.popleft()
            used = sum(t for _, t in recent)
            if used > args.max_tpm:
                wait = 60 - (now - recent[0][0])
                print(f"  pausing {wait:.0f}s to stay under {args.max_tpm} tokens/min", flush=True)
                time.sleep(max(wait, 0))

if __name__ == "__main__":
    main()
