"""Scene query tool: LangChain wrappers around the world-model query functions."""

import logging
from typing import Any, Dict, Optional

from langchain_core.tools import tool

from world_model.core.config import get_config
from world_model.core.manager import GraphDBManager
from world_model.core.vector_store import VectorStoreManager
from world_model.tools.tools import GraphDBTools

logger = logging.getLogger(__name__)

_graph_tools: Optional[GraphDBTools] = None


def reset_tools() -> None:
    """Drop the cached tools so the next call binds to the active environment."""
    global _graph_tools
    _graph_tools = None


def _get_tools() -> GraphDBTools:
    global _graph_tools
    if _graph_tools is None:
        config = get_config()
        env_id, env_size = config.get_active_env(), config.get_env_size()
        if not env_id:
            raise RuntimeError("No active environment. Start a session with env_id and env_size.")
        manager = GraphDBManager()
        _graph_tools = GraphDBTools(manager, VectorStoreManager(config, manager, env_id, env_size))
    return _graph_tools


def get_object_info(object_ids: str) -> Dict[str, Any]:
    """Get complete information about object(s) by ID.

    Args:
        object_ids: Single object ID or comma-separated list (e.g., "mug_5" or "mug_5,kitchen_20")

    Returns:
        Dictionary with all ontology properties, or list of dicts for multiple IDs.
    """
    ids = [i.strip() for i in object_ids.split(",")]
    return _get_tools().get_object_info(ids[0] if len(ids) == 1 else ids)


@tool
def find_path(from_id: str, to_id: str, reason: str) -> Optional[Dict[str, Any]]:
    """Find shortest path between two locations.

    Automatically resolves objects to their containing spaces.

    Args:
        from_id: Source object or space ID (e.g., "robot", "kitchen_20")
        to_id: Target object or space ID (e.g., "mug_5", "bedroom_11")
        reason: Why you are calling this tool (brief)

    Returns:
        Dictionary with path information (nodes, distance)
    """
    return _get_tools().find_path(from_id, to_id, reason)


@tool
def semantic_search(
    query: str,
    reason: str = "",
    space_id: Optional[str] = None,
    floor_id: Optional[str] = None,
    object_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for objects in the environment using natural language.

    Combines embedding-based category matching with spatial filtering.
    Returns matching instances directly — no separate filter call needed.

    Args:
        query: Natural language description of what to find (e.g., "water bottle", "refrigerator", "door", "stairs").
               Pass empty string "" when using only spatial filters.
        space_id: Optional space ID to narrow results to a specific room (e.g., "kitchen_1").
                  For portals (Door/Stairs/Opening), matches the spaces they connect to.
        floor_id: Optional storey ID to narrow results to a floor (e.g., "ground_floor_1").
        object_id: Optional object ID to find things ON or INSIDE it (e.g., "desk_5", "refrigerator_3").

    Returns:
        {
            "hint": "Query 'water bottle' matched 'water_bottle'. Similar: bottle, flask, jug. Showing water_bottle results.",
            "results": [{"id": ..., "category": ..., "isInSpace": ..., "isInStorey": ..., "isOntopOf": ..., "isInsideOf": ..., "isOpen": ...}, ...]
        }
        Portal results (Door/Stairs/Opening) include "isDoorOf"/"isStairsOf"/"isOpeningOf" instead of "isInSpace".

    Examples:
        # Find all water bottles globally
        semantic_search(query="water bottle")

        # Find chairs in a specific room
        semantic_search(query="chair", space_id="living_room_1")

        # Find everything on a desk
        semantic_search(query="", object_id="desk_5")

        # Find books on a shelf
        semantic_search(query="book", object_id="shelf_3")

        # Find doors connected to kitchen
        semantic_search(query="door", space_id="kitchen_1")

        # Find stairs on the ground floor
        semantic_search(query="stairs", floor_id="ground_floor_1")
    """
    return _get_tools().semantic_search(
        query=query, reason=reason, space_id=space_id, floor_id=floor_id, object_id=object_id
    )


def get_space_overview() -> str:
    """Return floor→space structure string for SE initial context."""
    return _get_tools().get_space_overview()


# Tool list for ToolNode
scene_query_tools = [semantic_search, find_path]
