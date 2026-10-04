"""Scene Explorer node - ReAct pattern for scene exploration."""

import re
from typing import List
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..state import OverallState, AgentNames, SceneExplorerReport
from ..config import Configuration, chat_model
from ..prompts import scene_explorer_prompt
from ..tools import scene_query_tools
from ..tools.scene_query import get_space_overview
from ..environment import activate_env


@tool
def finish_exploration(exploration_summary: str) -> str:
    """Finish scene exploration and return to Flow Orchestrator.

    Call this tool only after verifying that every object required by the user's task has been searched for.

    The summary must cover three things in relation to the user's task:
    1. FOUND: Every discovered object/space/door with its exact backtick-wrapped ID and its role in the task.
       When multiple candidates exist for the same role (e.g., several beds, several dining tables),
       list ALL of them with their locations — do NOT pre-select one. The Flow Orchestrator decides.
    2. NOT FOUND: Anything the task required but could not be located (state explicitly).
    3. NOTES: Observations that help the Flow Orchestrator choose (e.g. which refrigerator is open,
       which room contains both the source object and a relevant destination).

    IMPORTANT:
    - EVERY entity you mention MUST be written as a backtick-wrapped ID token (e.g., `bottle_65`, `bathroom_4`, `door_10`).
    - Do NOT invent IDs. Only use IDs returned by the tools.
    - Be specific about each object's role in the task (source, destination, obstacle, container, etc.).
    - Do NOT make choices between candidates — report all and let the Flow Orchestrator decide.

    Args:
        exploration_summary: Summary covering found objects (with backtick IDs), not-found items, and ambiguity notes.

    Returns:
        Confirmation message
    """
    return "Exploration finished."


def scene_explorer(state: OverallState, config: RunnableConfig) -> dict:
    """Scene Explorer agent node.

    Uses ReAct pattern: repeatedly calls tools,
    and decides whether to continue exploring or return to Flow Orchestrator.

    IMPORTANT: Only ONE LLM inference per invocation.
    """

    def _parse_ids_from_summary(text: str) -> List[str]:
        """Extract backtick-wrapped IDs from exploration_summary."""
        if not text:
            return []

        # Capture everything between backticks (IDs have no spaces)
        ids = re.findall(r"`([^`\s]+)`", text)

        # stable de-duplication
        return list(dict.fromkeys(ids))

    def _verify_ids_exist(ids: List[str]) -> List[dict]:
        """Verify ids exist in GraphDB by fetching object info.

        Returns a list of object dicts for ids that exist. Unknown ids are dropped.
        """
        if not ids:
            return []

        from ..tools import get_object_info

        try:
            result = get_object_info(",".join(ids))
        except Exception:
            return []

        if isinstance(result, dict):
            return [result] if result.get("id") and not result.get("_not_found") else []
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict) and r.get("id") and not r.get("_not_found")]
        return []

    MAX_EXPLORATION_TURNS = 20  # scene-exploration calls per instruction (paper, Appendix E.1)

    cfg = Configuration.from_runnable_config(config)
    activate_env(state["env_id"], state["env_size"])

    # Only the current instruction (and its clarification turns) is shown to this agent
    dialogue_history = state.get("dialogue_history", [])[state.get("episode_start", 0):]
    scene_query_history = state.get("scene_query_history", [])
    agent_reports = state.get("agent_reports", [])
    completed_turns = sum(1 for m in scene_query_history if isinstance(m, AIMessage))

    # The prompt asks the model to finish at the last turn; stop here if it did not.
    if completed_turns > MAX_EXPLORATION_TURNS:
        report: SceneExplorerReport = {
            "agent": AgentNames.SCENE_EXPLORER,
            "exploration_result": f"Exploration stopped after {MAX_EXPLORATION_TURNS} turns without finish_exploration.",
        }
        return {"next_agent": AgentNames.FLOW_ORCHESTRATOR, "agent_reports": [report], "discovered_objects": []}

    tc_reason = ""
    if isinstance(agent_reports, list) and agent_reports:
        for report in reversed(agent_reports):
            if isinstance(report, dict) and report.get("agent") == AgentNames.FLOW_ORCHESTRATOR:
                tc_reason = str(report.get("reason", "") or "").strip()
                if tc_reason:
                    break

    try:
        space_overview = get_space_overview()
    except Exception:
        space_overview = ""

    prompt = scene_explorer_prompt(
        dialogue_history=dialogue_history,
        flow_orchestrator_reason=tc_reason,
        current_turn=completed_turns + 1,
        max_turns=MAX_EXPLORATION_TURNS,
        space_overview=space_overview,
    )

    llm_messages = [SystemMessage(content=prompt)]

    if scene_query_history:
        # Sanitize: remove AIMessages with orphaned tool_calls that lack matching
        # ToolMessage responses — prevents OpenAI 400 errors on tool_call_id mismatches.
        # finish_exploration is handled locally (not by ToolNode), so its AIMessage
        # is always trailing-orphaned and must be stripped.

        # Phase 1: strip trailing orphaned AIMessages
        sanitized = list(scene_query_history)
        while sanitized:
            last = sanitized[-1]
            if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
                sanitized.pop()
            else:
                break

        # Phase 2: validate mid-sequence AIMessages — drop pairs where
        # tool_call_ids have no matching ToolMessage responses.
        cleaned = []
        i = 0
        while i < len(sanitized):
            msg = sanitized[i]
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                needed_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
                j = i + 1
                found_ids = set()
                while j < len(sanitized) and isinstance(sanitized[j], ToolMessage):
                    tid = getattr(sanitized[j], "tool_call_id", None)
                    if tid:
                        found_ids.add(tid)
                    j += 1
                if needed_ids <= found_ids:
                    cleaned.extend(sanitized[i:j])
                    i = j
                else:
                    i = j  # skip orphaned AIMessage + partial ToolMessages
            else:
                cleaned.append(msg)
                i += 1

        llm_messages.extend(cleaned)

    all_tools = scene_query_tools + [finish_exploration]
    llm_with_tools = chat_model(cfg.scene_explorer_model, cfg.scene_explorer_temperature).bind_tools(all_tools)

    response_obj = llm_with_tools.invoke(llm_messages)

    if hasattr(response_obj, 'tool_calls') and response_obj.tool_calls:
        for tool_call in response_obj.tool_calls:
            if tool_call.get('name') == 'finish_exploration':
                tool_args = tool_call.get('args', {})
                exploration_result = tool_args.get('exploration_summary', 'Exploration complete')

                parsed_ids = _parse_ids_from_summary(exploration_result)
                verified_objects = _verify_ids_exist(parsed_ids)

                report: SceneExplorerReport = {
                    "agent": AgentNames.SCENE_EXPLORER,
                    "exploration_result": exploration_result,
                }

                response_obj.name = AgentNames.SCENE_EXPLORER

                return {
                    "scene_query_history": [response_obj],
                    "next_agent": AgentNames.FLOW_ORCHESTRATOR,
                    "agent_reports": [report],
                    "discovered_objects": verified_objects,
                }

        response_obj.name = AgentNames.SCENE_EXPLORER
        return {
            "scene_query_history": [response_obj],
            "next_agent": AgentNames.SCENE_QUERY,
        }

    error_msg = AIMessage(
        content="Scene Explorer did not call any tools. Finishing exploration.",
        name=AgentNames.SCENE_EXPLORER
    )
    report: SceneExplorerReport = {
        "agent": AgentNames.SCENE_EXPLORER,
        "exploration_result": "No tools called, exploration incomplete",
    }

    return {
        "scene_query_history": [error_msg],
        "next_agent": AgentNames.FLOW_ORCHESTRATOR,
        "agent_reports": [report],
        "discovered_objects": [],
    }
