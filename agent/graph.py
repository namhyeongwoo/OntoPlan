"""Main LangGraph definition for agent architecture."""

from typing import Literal
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode

from .state import OverallState, AgentNames
from .nodes import (
    user_node,
    robot_node,
    flow_orchestrator,
    scene_explorer,
    task_formalizer,
    planning_manager,
)
from .tools import scene_query_tools, pddl_plan


def route_flow_orchestrator(state: OverallState) -> Literal["USER", "scene_explorer", "task_formalizer"]:
    """Route from Flow Orchestrator."""
    next_agent = state.get("next_agent", AgentNames.USER)
    return next_agent


def route_scene_explorer(state: OverallState) -> Literal["scene_query", "flow_orchestrator"]:
    """Route from Scene Explorer."""
    next_agent = state.get("next_agent", AgentNames.FLOW_ORCHESTRATOR)
    return next_agent


def route_task_formalizer(state: OverallState) -> Literal["flow_orchestrator", "planning_manager"]:
    """Route from Task Formalizer."""
    next_agent = state.get("next_agent", AgentNames.FLOW_ORCHESTRATOR)
    return next_agent


def route_planning_manager(state: OverallState) -> Literal["pddl_plan", "ROBOT"]:
    """Route from Planning Manager."""
    next_agent = state.get("next_agent", AgentNames.ROBOT)
    return next_agent


def build_workflow(scene_explorer_node=scene_explorer, planning_manager_node=planning_manager) -> StateGraph:
    """Build the complete workflow graph.

    The node arguments let the ablation variants in experiments/ablations.py swap in a
    Scene Explorer without the Scene query tool or a Planning Manager without the PDDL plan tool.
    """
    workflow = StateGraph(OverallState)

    # Add agent nodes
    workflow.add_node(AgentNames.USER, user_node)
    workflow.add_node(AgentNames.ROBOT, robot_node)
    workflow.add_node(AgentNames.FLOW_ORCHESTRATOR, flow_orchestrator)
    workflow.add_node(AgentNames.SCENE_EXPLORER, scene_explorer_node)
    workflow.add_node(AgentNames.TASK_FORMALIZER, task_formalizer)
    workflow.add_node(AgentNames.PLANNING_MANAGER, planning_manager_node)

    # Add tool nodes (with separate message histories)
    workflow.add_node(AgentNames.SCENE_QUERY, ToolNode(scene_query_tools, messages_key="scene_query_history"))
    workflow.add_node(AgentNames.PDDL_PLAN, ToolNode([pddl_plan], messages_key="pddl_plan_history"))

    # START -> USER
    workflow.add_edge(START, AgentNames.USER)

    workflow.add_edge(AgentNames.USER, AgentNames.FLOW_ORCHESTRATOR)

    workflow.add_conditional_edges(
        AgentNames.FLOW_ORCHESTRATOR,
        route_flow_orchestrator,
        {
            AgentNames.USER: AgentNames.USER,
            AgentNames.SCENE_EXPLORER: AgentNames.SCENE_EXPLORER,
            AgentNames.TASK_FORMALIZER: AgentNames.TASK_FORMALIZER
        }
    )

    workflow.add_conditional_edges(
        AgentNames.SCENE_EXPLORER,
        route_scene_explorer,
        {
            AgentNames.SCENE_QUERY: AgentNames.SCENE_QUERY,
            AgentNames.FLOW_ORCHESTRATOR: AgentNames.FLOW_ORCHESTRATOR
        }
    )

    workflow.add_edge(AgentNames.SCENE_QUERY, AgentNames.SCENE_EXPLORER)

    workflow.add_conditional_edges(
        AgentNames.TASK_FORMALIZER,
        route_task_formalizer,
        {
            AgentNames.FLOW_ORCHESTRATOR: AgentNames.FLOW_ORCHESTRATOR,
            AgentNames.PLANNING_MANAGER: AgentNames.PLANNING_MANAGER
        }
    )

    workflow.add_conditional_edges(
        AgentNames.PLANNING_MANAGER,
        route_planning_manager,
        {
            AgentNames.PDDL_PLAN: AgentNames.PDDL_PLAN,
            AgentNames.ROBOT: AgentNames.ROBOT
        }
    )

    workflow.add_edge(AgentNames.PDDL_PLAN, AgentNames.PLANNING_MANAGER)

    workflow.add_edge(AgentNames.ROBOT, AgentNames.USER)

    return workflow


# One instruction can take up to ~70 super-steps (20 exploration turns and 5 planning
# calls, each followed by its tool node); LangGraph's default limit of 25 would abort it.
RECURSION_LIMIT = 150

_compiled_graph = None


def get_graph():
    """Get compiled graph (lazy initialization for langgraph dev)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_workflow().compile(
            interrupt_after=[AgentNames.ROBOT]
        ).with_config({"recursion_limit": RECURSION_LIMIT})
    return _compiled_graph


def __getattr__(name):
    if name == "graph":
        return get_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
