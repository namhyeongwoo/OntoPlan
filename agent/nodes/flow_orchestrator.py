"""Flow Orchestrator node - Central orchestrator for routing."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from ..state import OverallState, AgentNames, FlowOrchestratorReport
from ..config import Configuration, chat_model
from ..prompts import flow_orchestrator_prompt

class CoordinatorDecision(BaseModel):
    """Structured decision from Flow Orchestrator."""

    user_intent: Literal["task_planning", "question_answering"] = Field(
        description="User's intent: task_planning (task to execute) or question_answering (information request)"
    )
    next_agent: Literal["USER", "scene_explorer", "task_formalizer"] = Field(
        description="Which agent to route to next"
    )
    reason: str = Field(
        description="Clear explanation of why this agent was chosen"
    )
    question: Optional[str] = Field(
        default=None,
        description="Question to ask user (ONLY if routing to USER)"
    )


def flow_orchestrator(state: OverallState, config: RunnableConfig) -> dict:
    """Flow Orchestrator agent node.

    Uses structured output to make routing decisions.
    """
    cfg = Configuration.from_runnable_config(config)

    dialogue_history = state.get("dialogue_history", [])
    agent_reports = state.get("agent_reports", [])
    discovered_objects = state.get("discovered_objects", [])

    prompt = flow_orchestrator_prompt(
        dialogue_history=dialogue_history,
        agent_reports=agent_reports,
        discovered_objects=discovered_objects,
    )

    llm = chat_model(cfg.flow_orchestrator_model, cfg.flow_orchestrator_temperature)

    messages = [SystemMessage(content=prompt)]

    try:
        result_obj = llm.with_structured_output(CoordinatorDecision, include_raw=True).invoke(messages)
        parsed_obj = result_obj.get("parsed") if isinstance(result_obj, dict) else getattr(result_obj, "parsed", None)
        decision = parsed_obj if parsed_obj is not None else result_obj

        if isinstance(decision, dict):
            decision = CoordinatorDecision(**decision)
        elif not isinstance(decision, CoordinatorDecision):
            decision = CoordinatorDecision.model_validate(decision)

    except Exception as e:
        decision = CoordinatorDecision(
            user_intent="task_planning",
            next_agent="scene_explorer",
            reason=f"Error in decision making: {e}. Defaulting to scene exploration.",
        )

    # The Task Formalizer asked for more exploration: send that request to the Scene Explorer
    # rather than back to the Task Formalizer, which would ask again with the same objects.
    last = agent_reports[-1] if agent_reports else {}
    if (isinstance(last, dict) and last.get("agent") == AgentNames.TASK_FORMALIZER
            and decision.next_agent == AgentNames.TASK_FORMALIZER):
        decision = CoordinatorDecision(
            user_intent=decision.user_intent,
            next_agent="scene_explorer",
            reason=f"The Task Formalizer needs more information: {last.get('reason', '')}",
        )

    report: FlowOrchestratorReport = {
        "agent": AgentNames.FLOW_ORCHESTRATOR,
        "next_agent": decision.next_agent,
        "reason": decision.reason,
    }

    result = {
        "next_agent": decision.next_agent,
        "agent_reports": [report],
    }

    if decision.next_agent == AgentNames.USER and decision.question:
        report["question"] = decision.question
        result["dialogue_history"] = [{"role": "assistant", "content": decision.question}]

    return result
