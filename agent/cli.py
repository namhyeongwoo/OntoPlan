"""Run OntoPlan in the terminal, without LangGraph Studio.

Examples:
    python -m agent.cli --env Klickitat --size small
    python -m agent.cli --env Klickitat --size small \\
        "Move the vase in the living room on Floor B to the bathroom on Floor C."
    python -m agent.cli --auto-reply "Bring me the book from the bedroom."

Without instructions the CLI reads them interactively and you answer clarification
questions yourself. With instructions on the command line (or --auto-reply), questions
get the paper's fixed reply. All instructions share one session, so later instructions
start from the world state left by earlier plans.
"""

import argparse
import logging
import time
import uuid

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .environment import ENV_IDS, ENV_SIZES
from .graph import RECURSION_LIMIT, build_workflow
from .state import AgentNames

# Fixed reply used in the paper's non-interactive protocol
AUTO_REPLY = "Do not ask follow-up questions. Make reasonable assumptions and continue planning."
MAX_CLARIFICATIONS = 5


class TokenCounter(BaseCallbackHandler):
    """Sum LLM token usage across all agents."""

    def __init__(self):
        self.calls = self.input_tokens = self.output_tokens = 0

    def on_llm_end(self, response, **kwargs):
        self.calls += 1
        for generations in response.generations:
            for g in generations:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                self.input_tokens += usage.get("input_tokens", 0)
                self.output_tokens += usage.get("output_tokens", 0)


def _pending_question(graph, config):
    for task in graph.get_state(config).tasks:
        for intr in task.interrupts:
            return intr.value
    return None


def _print_trace(values, start_report):
    """Print the agent trace of the current instruction in execution order."""

    def print_conditions():
        print(f"  [Task Formalizer] at_end: {values['at_end_condition']}")
        for kind in ("always", "sometime"):
            for cond in values.get(f"{kind}_conditions", []):
                print(f"  [Task Formalizer] {kind}: {cond.get('predicate_formula')}")

    conditions_shown = False
    for report in values.get("agent_reports", [])[start_report:]:
        agent = report.get("agent")
        if agent == AgentNames.FLOW_ORCHESTRATOR:
            print(f"  [Flow Orchestrator] -> {report.get('next_agent')}: {report.get('reason', '')}")
        elif agent == AgentNames.SCENE_EXPLORER:
            print(f"  [Scene Explorer] {report.get('exploration_result', '')}")
        elif agent == AgentNames.PLANNING_MANAGER:
            if values.get("at_end_condition") and not conditions_shown:
                print_conditions()
                conditions_shown = True
            print(f"  [Planning Manager] {report.get('reason', '')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("instructions", nargs="*", help="Instructions to run in order (interactive if omitted)")
    parser.add_argument("--env", default="Klickitat", choices=ENV_IDS)
    parser.add_argument("--size", default="small", choices=ENV_SIZES)
    parser.add_argument("--auto-reply", action="store_true",
                        help="Answer clarification questions with the paper's fixed reply instead of asking you")
    parser.add_argument("--quiet", action="store_true", help="Hide the agent trace")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="  %(name)s: %(message)s")
    for noisy in ("httpx", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    graph = build_workflow().compile(checkpointer=MemorySaver(), interrupt_after=[AgentNames.ROBOT])
    counter = TokenCounter()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": RECURSION_LIMIT,
              "callbacks": [counter]}

    graph.invoke({"env_id": args.env, "env_size": args.size}, config)
    print(f"OntoPlan | {args.env}/{args.size}")

    queue = list(args.instructions)
    while True:
        if queue:
            instruction = queue.pop(0)
            print(f"\nUser: {instruction}")
        elif args.instructions:
            break
        else:
            try:
                instruction = input("\nUser: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not instruction or instruction.lower() in ("exit", "quit"):
                break

        start = time.time()
        calls, tok_in, tok_out = counter.calls, counter.input_tokens, counter.output_tokens
        n_reports = len(graph.get_state(config).values.get("agent_reports", []))
        reply = instruction
        finished = False
        for _ in range(MAX_CLARIFICATIONS + 1):
            graph.invoke(Command(resume=reply), config)
            state = graph.get_state(config)
            if state.next and state.next[0] == AgentNames.USER and not state.values.get("awaiting_instruction"):
                question = _pending_question(graph, config)
                print(f"Assistant: {question}")
                if args.auto_reply or args.instructions:
                    reply = AUTO_REPLY
                    print(f"User (auto): {reply}")
                else:
                    reply = input("User: ").strip()
                continue
            finished = True
            break

        values = graph.get_state(config).values
        if not args.quiet:
            _print_trace(values, n_reports)
        if finished:
            robot = [m["content"] for m in values.get("dialogue_history", []) if m["role"] == "assistant"]
            print(f"Robot: {robot[-1] if robot else ''}")
        else:
            print(f"Stopped after {MAX_CLARIFICATIONS} clarification questions; the next input answers the last question.")
        print(f"  ({counter.calls - calls} LLM calls, {counter.input_tokens - tok_in + counter.output_tokens - tok_out:,} tokens, "
              f"{time.time() - start:.0f}s)")


if __name__ == "__main__":
    main()
