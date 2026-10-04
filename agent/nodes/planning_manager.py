"""Planning Manager node - Manages subgoal planning and execution."""

import json
from typing import Any, Dict, Optional
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..state import OverallState, AgentNames, PlanningManagerReport, SubgoalExecutionResult
from ..config import Configuration, chat_model
from ..prompts import planning_manager_prompt
from ..tools import pddl_plan
from ..environment import activate_env

@tool
def approve_plan(reasoning: str) -> str:
    """Approve the generated plan and finish planning.

    Call this when:
    - All subgoals were successfully planned
    - The plan aligns with user's intent from conversation context

    Args:
        reasoning: Explanation of why the plan is approved (1-2 sentences)

    Returns:
        Confirmation message
    """
    return f"Plan approved: {reasoning}"


def _extract_latest_pddl_result(pddl_plan_history: list[Any]) -> Optional[Dict[str, Any]]:
    """Extract the latest pddl_plan tool result from ToolMessage history."""
    for msg in reversed(pddl_plan_history or []):
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content
        if not isinstance(content, str) or not content:
            continue
        try:
            result_data = json.loads(content)
        except Exception:
            continue
        if isinstance(result_data, dict) and "subgoal_results" in result_data:
            return result_data
    return None


def _all_subgoals_success(pddl_result: Optional[Dict[str, Any]]) -> bool:
    if not pddl_result:
        return False
    subgoal_results = pddl_result.get("subgoal_results")
    if not isinstance(subgoal_results, list) or not subgoal_results:
        return False
    return all((sg or {}).get("status") == "success" for sg in subgoal_results)


def _previous_subgoals(pddl_plan_history: list[Any]) -> Optional[list]:
    """Subgoals of the latest pddl_plan call."""
    for msg in reversed(pddl_plan_history or []):
        for tc in getattr(msg, "tool_calls", None) or []:
            if tc.get("name") == "pddl_plan":
                return tc.get("args", {}).get("subgoals")
    return None


def _goal_states(subgoals: Optional[list]) -> list:
    return [(sg or {}).get("goal_state", "").split() for sg in subgoals or [] if isinstance(sg, dict)]


def _default_subgoals(sometime_conditions: list, at_end_condition: str) -> list:
    """Task Formalizer's conditions in their default order: sometime conditions, then at_end."""
    subgoals = [{"goal_state": c.get("predicate_formula", ""), "description": c.get("description", ""),
                 "name": f"sometime_{i}", "order": i} for i, c in enumerate(sometime_conditions)]
    subgoals.append({"goal_state": at_end_condition, "description": "Final goal", "name": "at_end",
                     "order": len(subgoals)})
    return subgoals


def planning_manager(state: OverallState, config: RunnableConfig) -> dict:
    """Planning Manager agent node.

    Uses ReAct pattern with single unified prompt:
    - Initial entry: LLM calls pddl_plan directly
    - After pddl_plan: LLM analyzes results → approve_plan (finish) or pddl_plan (retry)

    IMPORTANT: Only ONE LLM inference per invocation.
    """
    cfg = Configuration.from_runnable_config(config)
    activate_env(state["env_id"], state["env_size"])

    MAX_RETRIES = 5  # pddl_plan (plan-generation) calls per instruction (paper, Appendix E.1)

    # Only the current instruction (and its clarification turns) is shown to this agent
    dialogue_history = state.get("dialogue_history", [])[state.get("episode_start", 0):]
    discovered_objects = state.get("discovered_objects", [])
    pddl_plan_history = state.get("pddl_plan_history", [])
    planning_retry_count = state.get("planning_retry_count", 0)

    at_end_condition = state.get("at_end_condition", "")
    sometime_conditions = state.get("sometime_conditions", [])
    always_conditions = state.get("always_conditions", [])

    # Check retry count limit
    if planning_retry_count >= MAX_RETRIES:
        error_msg = AIMessage(
            content=f"Maximum retry limit ({MAX_RETRIES}) reached. Cannot continue planning.",
            name=AgentNames.PLANNING_MANAGER,
        )
        report: PlanningManagerReport = {
            "agent": AgentNames.PLANNING_MANAGER,
            "next_agent": AgentNames.ROBOT,
            "reason": f"Maximum retries ({MAX_RETRIES}) exceeded",
        }
        return {
            "pddl_plan_history": [error_msg],
            "next_agent": AgentNames.ROBOT,
            "agent_reports": [report],
        }

    # Multi-turn stale result guard:
    # pddl_plan_history uses an accumulating reducer (add_messages), so results
    # from previous turns persist. Use planning_retry_count to distinguish:
    #   retry_count == 0  -> fresh turn, no PDDL run yet -> ignore stale results
    #   retry_count >= 1  -> PDDL ran this turn -> read results normally
    if planning_retry_count == 0:
        pddl_plan_result = None
    else:
        pddl_plan_result = _extract_latest_pddl_result(pddl_plan_history)

    # Auto-approve shortcut: if all subgoals succeeded, skip the LLM call
    # and route directly to ROBOT. Saves one LLM inference per successful plan.
    if pddl_plan_result is not None and _all_subgoals_success(pddl_plan_result):
        execution_results: list[SubgoalExecutionResult] = []
        for sg_result in pddl_plan_result.get("subgoal_results", []):
            exec_result: SubgoalExecutionResult = {
                "subgoal_index": (sg_result or {}).get("subgoal_index", 0),
                "goal_state": (sg_result or {}).get("goal_state", ""),
                "description": (sg_result or {}).get("description", ""),
                "status": (sg_result or {}).get("status", "pending"),
                "plan": (sg_result or {}).get("plan"),
                "error_log": (sg_result or {}).get("error"),
                "plan_metrics": (sg_result or {}).get("metrics"),
            }
            execution_results.append(exec_result)

        report: PlanningManagerReport = {
            "agent": AgentNames.PLANNING_MANAGER,
            "next_agent": AgentNames.ROBOT,
            "reason": "All subgoals succeeded - auto-approved",
        }
        return {
            "subgoal_results": execution_results,
            "next_agent": AgentNames.ROBOT,
            "agent_reports": [report],
        }

    prompt = planning_manager_prompt(
        dialogue_history=dialogue_history,
        discovered_objects=discovered_objects,
        task_description=state.get("task_description", ""),
        at_end_condition=at_end_condition,
        sometime_conditions=sometime_conditions,
        always_conditions=always_conditions,
        pddl_result=pddl_plan_result,
    )

    llm_messages = [SystemMessage(content=prompt)]

    all_tools = [pddl_plan, approve_plan]
    llm_with_tools = chat_model(cfg.planning_manager_model, cfg.planning_manager_temperature).bind_tools(all_tools)

    response = llm_with_tools.invoke(llm_messages)

    tool_calls = getattr(response, "tool_calls", None) or []
    if len(tool_calls) != 1:
        error_msg = AIMessage(
            content=f"Planning Manager must call exactly one tool, but got {len(tool_calls)} tool calls.",
            name=AgentNames.PLANNING_MANAGER,
        )
        report: PlanningManagerReport = {
            "agent": AgentNames.PLANNING_MANAGER,
            "next_agent": AgentNames.ROBOT,
            "reason": "Invalid tool call count",
        }
        return {
            "pddl_plan_history": [error_msg],
            "next_agent": AgentNames.ROBOT,
            "agent_reports": [report],
        }

    tool_call = tool_calls[0]
    tool_name = tool_call.get("name", "")
    tool_args = tool_call.get("args", {})

    if tool_name == "pddl_plan":
        discovered_object_ids = [obj.get("id") for obj in discovered_objects if isinstance(obj, dict) and "id" in obj]

        # At temperature 0 a retry with the same input repeats the same subgoals. If the model
        # resubmits subgoals that already failed, fall back to the Task Formalizer's conditions
        # in their default order instead of spending a retry on the same failure.
        if pddl_plan_result is not None and _goal_states(tool_call["args"].get("subgoals")) == \
                _goal_states(_previous_subgoals(pddl_plan_history)):
            default = _default_subgoals(sometime_conditions, at_end_condition)
            if _goal_states(default) != _goal_states(tool_call["args"].get("subgoals")):
                tool_call["args"]["subgoals"] = default

        tool_call["args"]["discovered_objects"] = discovered_object_ids
        tool_call["args"]["always_conditions"] = always_conditions

        if not tool_call["args"].get("subgoals"):
            error_msg = AIMessage(
                content="Cannot call pddl_plan: missing required argument 'subgoals' (not provided by model and not found in state).",
                name=AgentNames.PLANNING_MANAGER,
            )
            report: PlanningManagerReport = {
                "agent": AgentNames.PLANNING_MANAGER,
                "next_agent": AgentNames.ROBOT,
                "reason": "Missing required pddl_plan arg: subgoals",
            }
            return {
                "pddl_plan_history": [error_msg],
                "next_agent": AgentNames.ROBOT,
                "agent_reports": [report],
            }

        if "task_description" not in tool_call["args"] or not tool_call["args"]["task_description"]:
            tool_call["args"]["task_description"] = state.get("task_description", "")

        response.name = AgentNames.PLANNING_MANAGER

        # Always increment retry count so that on re-entry, PO knows PDDL
        # has been called this turn (retry_count >= 1) and can read results.
        # Without this, retry_count stays 0 on first call and the stale
        # result guard above would incorrectly discard valid results.
        return {
            "pddl_plan_history": [response],
            "planning_retry_count": planning_retry_count + 1,
            "next_agent": AgentNames.PDDL_PLAN,
        }

    if tool_name == "approve_plan":
        reasoning = tool_args.get("reasoning", "Plan approved")

        if not _all_subgoals_success(pddl_plan_result):
            error_msg = AIMessage(
                content="approve_plan was called, but not all subgoals are successful. Retrying planning.",
                name=AgentNames.PLANNING_MANAGER,
            )
            report: PlanningManagerReport = {
                "agent": AgentNames.PLANNING_MANAGER,
                "next_agent": AgentNames.PDDL_PLAN,
                "reason": "Approval requested without full success",
            }
            return {
                "pddl_plan_history": [error_msg],
                "planning_retry_count": planning_retry_count + 1,
                "next_agent": AgentNames.PDDL_PLAN,
                "agent_reports": [report],
            }

        execution_results: list[SubgoalExecutionResult] = []
        for sg_result in (pddl_plan_result or {}).get("subgoal_results", []):
            exec_result: SubgoalExecutionResult = {
                "subgoal_index": (sg_result or {}).get("subgoal_index", 0),
                "goal_state": (sg_result or {}).get("goal_state", ""),
                "description": (sg_result or {}).get("description", ""),
                "status": (sg_result or {}).get("status", "pending"),
                "plan": (sg_result or {}).get("plan"),
                "error_log": (sg_result or {}).get("error"),
                "plan_metrics": (sg_result or {}).get("metrics"),
            }
            execution_results.append(exec_result)

        response.name = AgentNames.PLANNING_MANAGER
        report: PlanningManagerReport = {
            "agent": AgentNames.PLANNING_MANAGER,
            "next_agent": AgentNames.ROBOT,
            "reason": reasoning,
        }

        return {
            "pddl_plan_history": [response],
            "subgoal_results": execution_results,
            "next_agent": AgentNames.ROBOT,
            "agent_reports": [report],
        }

    error_msg = AIMessage(
        content=f"Unknown tool called: {tool_name}",
        name=AgentNames.PLANNING_MANAGER,
    )
    report: PlanningManagerReport = {
        "agent": AgentNames.PLANNING_MANAGER,
        "next_agent": AgentNames.ROBOT,
        "reason": f"Unknown tool called: {tool_name}",
    }
    return {
        "pddl_plan_history": [error_msg],
        "next_agent": AgentNames.ROBOT,
        "agent_reports": [report],
    }
