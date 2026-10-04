"""Loading an environment into GraphDB and tracking which environment is active."""

import logging
from pathlib import Path

from world_model.core.config import get_config
from world_model.core.manager import GraphDBManager
from world_model.core.vector_store import VectorStoreManager

logger = logging.getLogger(__name__)

ENV_IDS = ("Klickitat", "Lakeville", "Lindenwood", "Marstons", "Muleshoe")
ENV_SIZES = ("small", "medium", "large")


def activate_env(env_id: str, env_size: str) -> None:
    """Point the scene-query and planning tools at an environment already loaded in GraphDB."""
    config = get_config()
    if (config.get_active_env(), config.get_env_size()) != (env_id, env_size):
        config.set_active_env(env_id, env_size)
        from .tools.scene_query import reset_tools
        reset_tools()


CHECKPOINT_DIR = Path(__file__).resolve().parents[1] / "pddl" / "workspace"


def _checkpoint_path(env_id: str, env_size: str) -> Path:
    return CHECKPOINT_DIR / f"checkpoint_{env_id}_{env_size}.nt"


def reset_world_state(env_id: str, env_size: str) -> None:
    """Load the initial state of an environment into GraphDB and discard any checkpoint.

    The whole repository holds exactly one environment: schema, static, and dynamic
    layers are loaded into the default graph. (In GraphDB, queries and DELETEs without a
    GRAPH clause span every named graph, so backups are kept in files, not named graphs.)
    """
    if env_id not in ENV_IDS or env_size not in ENV_SIZES:
        raise ValueError(f"Unknown environment {env_id}/{env_size}. Choose from {ENV_IDS} x {ENV_SIZES}.")
    _checkpoint_path(env_id, env_size).unlink(missing_ok=True)
    config = get_config()
    env_dir = config.get_env_dir(env_id, env_size)
    manager = GraphDBManager()
    manager.clear_all()
    for path in (config.get_schema_path(), env_dir / "static.ttl", env_dir / "dynamic.ttl"):
        manager.load_file(str(path))
    config.set_active_env(env_id, env_size)


def save_checkpoint(env_id: str, env_size: str) -> None:
    """Save the explicit world state (without OWL entailments) after a successful plan."""
    path = _checkpoint_path(env_id, env_size)
    path.parent.mkdir(parents=True, exist_ok=True)
    GraphDBManager().export_explicit(str(path))


def restore_world_state(env_id: str, env_size: str) -> None:
    """Restore the state left by the last successful plan, or the initial state if none."""
    path = _checkpoint_path(env_id, env_size)
    if not path.exists():
        reset_world_state(env_id, env_size)
        return
    manager = GraphDBManager()
    manager.clear_all()
    manager.load_file(str(path))
    get_config().set_active_env(env_id, env_size)


def initialize_environment(env_id: str, env_size: str) -> None:
    """Load an environment into GraphDB for a new session and prepare its category index."""
    reset_world_state(env_id, env_size)
    config = get_config()
    manager = GraphDBManager()
    vector_store = VectorStoreManager(config, manager, env_id, env_size)
    if not vector_store.is_ready():
        logger.info("Building category index for %s/%s (first run only)", env_id, env_size)
        vector_store.build_from_graphdb()

    from .tools.scene_query import reset_tools
    reset_tools()
    logger.info("Environment %s/%s ready", env_id, env_size)
