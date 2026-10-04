"""ROBOT node - Represents robot execution."""

import json

from langchain_core.messages import ToolMessage

from ..state import AgentNames, OverallState


def _planning_failure_summary(state: OverallState) -> str:
    """Explain why planning ended without an approved plan."""
    reason = next(
        (r.get("reason", "") for r in reversed(state.get("agent_reports", []))
         if isinstance(r, dict) and r.get("agent") == AgentNames.PLANNING_MANAGER),
        "",
    )
    lines = ["Planning failed. No actions were executed."]
    if reason:
        lines.append(f"Reason: {reason}")
    # pddl_plan_history spans episodes; only read it if pddl_plan ran for this instruction
    history = state.get("pddl_plan_history", []) if state.get("planning_retry_count", 0) > 0 else []
    for msg in reversed(history):
        if isinstance(msg, ToolMessage):
            try:
                failed = [sg for sg in json.loads(msg.content).get("subgoal_results", []) if sg.get("status") != "success"]
            except (TypeError, ValueError, AttributeError):
                break
            for sg in failed:
                lines.append(f"  [FAIL] {sg.get('description', '')}: {sg.get('error', '')}")
            break
    return "\n".join(lines)


def robot_node(state: OverallState) -> dict:
    """Robot execution node: report the approved plan (or the planning failure) to the user."""
    subgoal_results = state.get("subgoal_results", [])
    shown = state.get("_shown_subgoal_count", 0)
    new_results = subgoal_results[shown:]

    if not new_results:
        return {
            "dialogue_history": [{"role": "assistant", "content": _planning_failure_summary(state)}],
            "awaiting_instruction": True,
        }

    success = sum(1 for s in new_results if s.get("status") == "success")
    lines = [f"Done. {success}/{len(new_results)} subgoals succeeded."]
    total_actions = 0
    for sg in new_results:
        marker = "OK" if sg.get("status") == "success" else "FAIL"
        plan = sg.get("plan") or ""
        plan_steps = [l.strip() for l in str(plan).splitlines() if l.strip() and not l.strip().startswith(";")]
        total_actions += len(plan_steps)
        lines.append(f"  [{marker}] {sg.get('description', '')} ({len(plan_steps)} actions)")
        lines.extend(f"    {step}" for step in plan_steps)
        if sg.get("status") != "success" and sg.get("error_log"):
            lines.append(f"    Error: {sg['error_log']}")
    lines.append(f"Total: {total_actions} robot actions.")
    return {
        "dialogue_history": [{"role": "assistant", "content": "\n".join(lines)}],
        "_shown_subgoal_count": len(subgoal_results),
        "awaiting_instruction": True,
    }
