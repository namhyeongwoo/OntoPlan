"""Task Formalizer node - Defines PDDL goals and constraints."""

import logging
import re

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..state import OverallState, AgentNames, FlowOrchestratorReport
from ..config import Configuration, chat_model
from ..prompts import task_formalizer_prompt
from ..utils.formula_check import check_always_initial, check_formulas

logger = logging.getLogger(__name__)

@tool
def define_sometime_condition(predicate_formula: str, description: str) -> str:
    """Define a condition that must be satisfied at some point during execution.

    Sometime conditions are states that must occur at least once during the task,
    but are not necessarily part of the final goal.

    Args:
        predicate_formula: PDDL predicate formula (e.g., "(isOpen window_1)")
        description: Human-readable explanation of why this state is needed

    Returns:
        Confirmation message
    """
    return f"Sometime condition defined: {predicate_formula}"


@tool
def define_always_condition(predicate_formula: str, description: str) -> str:
    """Define a condition that must always be true throughout execution.

    Always conditions are constraints that must remain satisfied from start to finish.
    Use positive formulas (not negations when possible).

    Examples:
        - "Window must always be open": (isOpen window_1)
        - "Left hand must always be free": (isEmpty left_hand)
        - "Never use both hands": (or (isEmpty left_hand) (isEmpty right_hand))

    Args:
        predicate_formula: PDDL predicate formula that must always be true
        description: Human-readable explanation of why this constraint exists

    Returns:
        Confirmation message
    """
    return f"Always condition defined: {predicate_formula}"


@tool
def request_more_exploration(reason: str) -> str:
    """Request task coordinator to explore more objects.

    Use this when you need objects that are not in the discovered objects list.

    Args:
        reason: Explanation of what objects/information you need

    Returns:
        Confirmation message
    """
    return f"Requesting more exploration: {reason}"


@tool
def define_at_end_condition(goal_formula: str, reasoning: str) -> str:
    """Define the final goal state - what must be true when the task is complete.

    This MUST be called after defining all other conditions.

    Args:
        goal_formula: PDDL predicate formula for the final goal state
        reasoning: Explanation of the goal and why you defined the conditions above

    Returns:
        Confirmation message
    """
    return f"At-end condition defined: {goal_formula}"


def task_formalizer(state: OverallState, config: RunnableConfig) -> dict:
    """Task Formalizer agent node.

    Defines goal conditions using PDDL temporal constraint types:
    - at_end_condition: Final goal state
    - sometime_conditions: States that must occur at some point
    - always_conditions: States that must be true throughout execution

    Uses bind_tools for constraint definition (not actual Tool nodes).
    If generated conditions reference unknown object IDs, feeds back an error
    message and retries (up to MAX_RETRIES times).
    """
    MAX_RETRIES = 2

    def _extract_ids_from_pddl(formula: str) -> set[str]:
        """Extract object IDs from a PDDL s-expression by tokenising on
        whitespace and parentheses, then keeping only tokens that look like
        object IDs (contain an underscore followed by digits at the end).

        This handles compound names such as potted_plant_46, bed_1_77,
        storage_cabinet_154 correctly — unlike a simple [A-Za-z]+_\\d+ regex
        which would extract only the last word segment.
        """
        if not formula:
            return set()

        # Split on whitespace and parentheses to get raw tokens
        tokens = re.split(r"[\s()]+", formula)
        # Keep tokens that end with _<digits> (object ID pattern)
        return {t for t in tokens if re.search(r"_\d+$", t)}

    def _unknown_ids_in_formula(formula: str, known_ids: set[str]) -> set[str]:
        ids = _extract_ids_from_pddl(formula)
        return {i for i in ids if i not in known_ids}

    cfg = Configuration.from_runnable_config(config)

    # Only the current instruction (and its clarification turns) is shown to this agent
    dialogue_history = state.get("dialogue_history", [])[state.get("episode_start", 0):]
    discovered_objects = state.get("discovered_objects", [])
    agent_reports = state.get("agent_reports", [])

    known_ids: set[str] = {o.get("id") for o in discovered_objects if isinstance(o, dict) and o.get("id")}

    fo_reason = ""
    if isinstance(agent_reports, list) and agent_reports:
        for report in reversed(agent_reports):
            if isinstance(report, dict) and report.get("agent") == AgentNames.FLOW_ORCHESTRATOR:
                fo_reason = str(report.get("reason", "") or "").strip()
                if fo_reason:
                    break

    prompt = task_formalizer_prompt(
        dialogue_history=dialogue_history,
        discovered_objects=discovered_objects,
        flow_orchestrator_reason=fo_reason,
    )

    constraint_tools = [
        define_sometime_condition,
        define_always_condition,
        define_at_end_condition,  # MUST be called (unless requesting more exploration)
        request_more_exploration,
    ]
    llm_with_tools = chat_model(cfg.task_formalizer_model, cfg.task_formalizer_temperature).bind_tools(constraint_tools)

    def _extract_conditions(response):
        """Parse tool calls from a Task Formalizer response into structured condition lists."""
        sometime_conditions = []
        always_conditions = []
        at_end_formulas = []
        reason = "No reasoning provided"
        exploration_request = None
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                if tool_name == "define_sometime_condition":
                    sometime_conditions.append({
                        "predicate_formula": tool_args.get("predicate_formula", ""),
                        "description": tool_args.get("description", "")
                    })
                elif tool_name == "define_always_condition":
                    always_conditions.append({
                        "predicate_formula": tool_args.get("predicate_formula", ""),
                        "description": tool_args.get("description", "")
                    })
                elif tool_name == "define_at_end_condition":
                    formula = tool_args.get("goal_formula", "")
                    if formula:
                        at_end_formulas.append(formula)
                    reason = tool_args.get("reasoning", "No reasoning provided")
                elif tool_name == "request_more_exploration":
                    exploration_request = tool_args.get("reason", "Need more objects")
        return sometime_conditions, always_conditions, at_end_formulas, reason, exploration_request

    def _collect_unknown_ids(sometime_conditions, always_conditions, at_end_formulas):
        """Return a dict mapping condition description → unknown IDs, for all condition types."""
        errors = {}
        for f in at_end_formulas:
            u = _unknown_ids_in_formula(f, known_ids)
            if u:
                errors[f"at_end: {f}"] = u
        for cond in sometime_conditions:
            f = cond.get("predicate_formula", "")
            u = _unknown_ids_in_formula(f, known_ids)
            if u:
                errors[f"sometime: {f}"] = u
        for cond in always_conditions:
            f = cond.get("predicate_formula", "")
            u = _unknown_ids_in_formula(f, known_ids)
            if u:
                errors[f"always: {f}"] = u
        return errors

    def _collect_type_errors(sometime_conditions, always_conditions, at_end_formulas):
        """Return {condition label: [problems]} for conditions that do not fit the PDDL domain."""
        formulas = {f"at_end: {f}": f for f in at_end_formulas}
        formulas.update({f"sometime: {c.get('predicate_formula', '')}": c.get("predicate_formula", "") for c in sometime_conditions})
        formulas.update({f"always: {c.get('predicate_formula', '')}": c.get("predicate_formula", "") for c in always_conditions})
        try:
            problems = check_formulas(formulas)
            always = {f"always: {c.get('predicate_formula', '')}": c.get("predicate_formula", "") for c in always_conditions}
            for label, items in check_always_initial(always).items():
                problems.setdefault(label, []).extend(items)
            return problems
        except Exception as e:  # never block planning on the checker itself
            logger.warning("Condition type check skipped: %s", e)
            return {}

    messages = [SystemMessage(content=prompt)]

    # Inference loop: retry if unknown IDs are detected in any condition
    sometime_conditions = []
    always_conditions = []
    at_end_formulas = []
    reason = "No reasoning provided"
    exploration_request = None

    for attempt in range(MAX_RETRIES + 1):
        response = llm_with_tools.invoke(messages)

        sometime_conditions, always_conditions, at_end_formulas, reason, exploration_request = _extract_conditions(response)

        if exploration_request:
            break

        unknown_errors = _collect_unknown_ids(sometime_conditions, always_conditions, at_end_formulas)
        type_errors = {} if unknown_errors else _collect_type_errors(sometime_conditions, always_conditions, at_end_formulas)
        if not at_end_formulas and not unknown_errors:
            type_errors["at_end"] = ["define_at_end_condition was not called; every response must define the final goal state"]
        if not unknown_errors and not type_errors:
            break

        if attempt < MAX_RETRIES:
            messages.append(response)
            # Return stub tool results so the model sees its calls were received
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tc in response.tool_calls:
                    messages.append(ToolMessage(
                        content=f"Condition recorded: {tc.get('args', {})}",
                        tool_call_id=tc.get("id", tc.get("name", "unknown"))
                    ))
            if unknown_errors:
                error_lines = "\n".join(
                    f"  - {desc}: unknown IDs {sorted(ids)}"
                    for desc, ids in unknown_errors.items()
                )
                known_sample = sorted(known_ids)[:30]
                feedback = (
                    f"ERROR: Your conditions contain object IDs that do not exist in the discovered objects.\n"
                    f"{error_lines}\n\n"
                    f"These IDs were not found in the discovered objects list. "
                    f"You must only use IDs from the discovered objects. "
                    f"Sample of valid IDs: {known_sample}\n\n"
                    f"Please re-define ALL conditions using only valid object IDs."
                )
            else:
                error_lines = "\n".join(
                    f"  - {desc}: {'; '.join(problems)}" for desc, problems in type_errors.items()
                )
                feedback = (
                    f"ERROR: Some conditions cannot be planned as written.\n"
                    f"{error_lines}\n\n"
                    f"Please re-define ALL conditions to fix these problems."
                )
            messages.append(HumanMessage(content=feedback))
            logger.info("Invalid conditions (attempt %d), retrying: %s", attempt + 1, unknown_errors or type_errors)
        else:
            logger.warning("Invalid conditions persist after %d retries: %s", MAX_RETRIES, unknown_errors or type_errors)

    if len(at_end_formulas) == 0:
        at_end_condition = "(placeholder goal)"
    elif len(at_end_formulas) == 1:
        at_end_condition = at_end_formulas[0]
    else:
        at_end_condition = "(and " + " ".join(at_end_formulas) + ")"

    task_description = ""
    for msg in reversed(dialogue_history):
        if isinstance(msg, dict) and msg.get("role") == "user":
            task_description = msg.get("content", "")
            break

    if exploration_request:
        report: FlowOrchestratorReport = {
            "agent": AgentNames.TASK_FORMALIZER,
            "next_agent": AgentNames.FLOW_ORCHESTRATOR,
            "reason": exploration_request,
        }
        return {
            "next_agent": AgentNames.FLOW_ORCHESTRATOR,
            "agent_reports": [report]
        }

    return {
        "next_agent": AgentNames.PLANNING_MANAGER,
        "task_description": task_description,
        "at_end_condition": at_end_condition,
        "sometime_conditions": sometime_conditions,
        "always_conditions": always_conditions,
    }
