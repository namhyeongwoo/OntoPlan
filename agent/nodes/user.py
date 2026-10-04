"""USER node - Represents human user interaction."""

from langchain_core.messages import RemoveMessage
from langgraph.types import interrupt

from ..environment import activate_env, initialize_environment
from ..prompts import initial_user_prompt
from ..state import AgentNames, OverallState, UserReport

DEFAULT_ENV = ("Klickitat", "small")


def user_node(state: OverallState) -> dict:
    """User input node. Uses interrupt() to get user input.

    A new episode starts with the first message and with every message that follows a
    ROBOT report; clarification answers continue the current episode.
    """
    dialogue_history = state.get("dialogue_history", [])
    is_first_input = not dialogue_history
    new_episode = is_first_input or state.get("awaiting_instruction", False)

    if is_first_input:
        question = initial_user_prompt()
    elif new_episode:
        question = "Ready for next instruction."
    else:
        last_assistant = next(
            (m["content"] for m in reversed(dialogue_history) if isinstance(m, dict) and m.get("role") == "assistant"),
            None,
        )
        question = last_assistant or "Ready for next instruction."

    # interrupt() re-runs this node from the top on resume, so side effects come after it.
    user_response = interrupt(question)

    result: dict = {}
    if is_first_input:
        env_id = state.get("env_id") or DEFAULT_ENV[0]
        env_size = state.get("env_size") or DEFAULT_ENV[1]
        initialize_environment(env_id, env_size)
        result.update({"env_id": env_id, "env_size": env_size})
    else:
        activate_env(state["env_id"], state["env_size"])
        result.update({
            "planning_retry_count": 0,
            "task_description": "",
            "at_end_condition": "",
            "sometime_conditions": [],
            "always_conditions": [],
            "next_agent": "",
        })

    if new_episode:
        result["episode_start"] = len(dialogue_history)
        result["awaiting_instruction"] = False
        # Scene Explorer's tool-call history belongs to the previous instruction
        stale = [RemoveMessage(id=m.id) for m in state.get("scene_query_history", []) if getattr(m, "id", None)]
        if stale:
            result["scene_query_history"] = stale

    user_report: UserReport = {"agent": AgentNames.USER, "content": user_response}
    result.update({
        "agent_reports": [user_report],
        "dialogue_history": [{"role": "user", "content": user_response}],
    })
    return result
