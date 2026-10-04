"""State definition for agent architecture."""

from typing import Literal, List, Dict, Any, Optional
from typing_extensions import TypedDict, Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
import operator


class AgentNames:
    """Constants for agent node names."""

    USER = "USER"
    FLOW_ORCHESTRATOR = "flow_orchestrator"
    SCENE_EXPLORER = "scene_explorer"
    TASK_FORMALIZER = "task_formalizer"
    PLANNING_MANAGER = "planning_manager"
    ROBOT = "ROBOT"

    # Tool nodes
    SCENE_QUERY = "scene_query"
    PDDL_PLAN = "pddl_plan"


# Report type definitions
class UserReport(TypedDict):
    """Report from USER node."""
    agent: str  # "USER"
    content: str  # User input


class FlowOrchestratorReport(TypedDict, total=False):
    """Report from Flow Orchestrator."""
    agent: str  # "flow_orchestrator"
    next_agent: str
    reason: str  # Routing decision reason
    question: str  # Question to ask user (when routing to USER)


class SceneExplorerReport(TypedDict):
    """Report from Scene Explorer."""
    agent: str  # "scene_explorer"
    exploration_result: str  # Brief exploration summary


class PlanningManagerReport(TypedDict):
    """Report from Planning Manager."""
    agent: str  # "planning_manager"
    next_agent: str
    reason: str  # Routing decision reason


class SubgoalExecutionResult(TypedDict):
    """Execution result for a single subgoal."""
    subgoal_index: int
    goal_state: str
    description: str
    status: Literal["success", "failed", "pending"]
    plan: Optional[str]  # Generated plan (on success)
    error_log: Optional[str]  # Error message (on failure)
    plan_metrics: Optional[Dict[str, Any]]  # Plan length, cost, etc.


class OverallState(TypedDict, total=False):
    """Global state shared across all agents."""

    # Environment configuration (set at session start)
    env_id: str  # Environment ID (e.g., "Klickitat")
    env_size: str  # Environment size (e.g., "small", "medium", "large")

    # Accumulated context from all agent reports
    agent_reports: Annotated[List[Dict[str, Any]], operator.add]

    # Conversation context between USER and flow_orchestrator
    dialogue_history: Annotated[List[Dict[str, str]], operator.add]

    # Discovered objects with full info (accumulated across scene explorations)
    discovered_objects: Annotated[List[Dict[str, Any]], operator.add]

    # Scene Explorer tool call history (separate from main messages)
    scene_query_history: Annotated[List[AnyMessage], add_messages]

    # Task Formalizer output (for Planning Manager)
    task_description: str  # Natural language summary of the user's task
    at_end_condition: str  # PDDL formula for final goal (state at the end)
    sometime_conditions: List[Dict[str, str]]  # States that must be satisfied at some point
    always_conditions: List[Dict[str, str]]  # States that must always be true throughout execution

    # Planning Manager tool call history (separate from main messages)
    pddl_plan_history: Annotated[List[AnyMessage], add_messages]

    # Subgoal execution results (Planning Manager → ROBOT)
    subgoal_results: Annotated[List[SubgoalExecutionResult], operator.add]
    planning_retry_count: int  # Prevents infinite retry loops

    # Routing
    next_agent: Optional[str]

    # Multi-turn episodes (one episode = one instruction, including its clarification turns)
    episode_start: int  # Index in dialogue_history where the current instruction starts
    awaiting_instruction: bool  # True after ROBOT reports; the next user message starts a new episode
    _shown_subgoal_count: int  # Number of subgoal_results already reported by ROBOT
