"""Configuration for agent."""

import os
from dataclasses import dataclass

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

# All agents use GPT-4o at temperature 0 (paper, Sec. 4.3). Set ONTOPLAN_MODEL to pin a
# specific snapshot, e.g. "gpt-4o-2024-08-06".
DEFAULT_MODEL = os.getenv("ONTOPLAN_MODEL", "gpt-4o")


def chat_model(model: str, temperature: float) -> ChatOpenAI:
    """OpenAI chat client shared by all agents.

    Rate-limit and transient errors are retried with exponential backoff
    (OPENAI_MAX_RETRIES, default 10; OPENAI_TIMEOUT seconds per request, default 120).
    """
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "10")),
        timeout=float(os.getenv("OPENAI_TIMEOUT", "120")),
    )


@dataclass
class Configuration:
    """Configuration for LLM agents."""

    # Flow Orchestrator
    flow_orchestrator_model: str = DEFAULT_MODEL
    flow_orchestrator_temperature: float = 0.0

    # Scene Explorer
    scene_explorer_model: str = DEFAULT_MODEL
    scene_explorer_temperature: float = 0.0

    # Task Formalizer
    task_formalizer_model: str = DEFAULT_MODEL
    task_formalizer_temperature: float = 0.0

    # Planning Manager
    planning_manager_model: str = DEFAULT_MODEL
    planning_manager_temperature: float = 0.0

    @classmethod
    def from_runnable_config(cls, config: RunnableConfig) -> "Configuration":
        """Create Configuration from RunnableConfig.

        Args:
            config: RunnableConfig from LangGraph

        Returns:
            Configuration instance
        """
        configurable = config.get("configurable", {})
        return cls(
            flow_orchestrator_model=configurable.get("flow_orchestrator_model", DEFAULT_MODEL),
            flow_orchestrator_temperature=configurable.get("flow_orchestrator_temperature", 0.0),
            scene_explorer_model=configurable.get("scene_explorer_model", DEFAULT_MODEL),
            scene_explorer_temperature=configurable.get("scene_explorer_temperature", 0.0),
            task_formalizer_model=configurable.get("task_formalizer_model", DEFAULT_MODEL),
            task_formalizer_temperature=configurable.get("task_formalizer_temperature", 0.0),
            planning_manager_model=configurable.get("planning_manager_model", DEFAULT_MODEL),
            planning_manager_temperature=configurable.get("planning_manager_temperature", 0.0),
        )
