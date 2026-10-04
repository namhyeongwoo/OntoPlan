"""Configuration loader for world_model/config.yaml (falls back to config.example.yaml)."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

WORLD_MODEL_DIR = Path(__file__).resolve().parent.parent

# Load .env from the project root
_env_path = WORLD_MODEL_DIR.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

_DEFAULT_DIMENSIONS = {
    "text-embedding-3-small": 512,
    "text-embedding-3-large": 1024,
    "text-embedding-ada-002": 1536,
}


class ConfigLoader:
    """Load and manage configuration."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = WORLD_MODEL_DIR / "config.yaml"
            if not config_path.exists():
                config_path = WORLD_MODEL_DIR / "config.example.yaml"
                logger.info("world_model/config.yaml not found; using config.example.yaml")
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        with open(self.config_path, "r") as f:
            self._config: Dict[str, Any] = yaml.safe_load(f) or {}

    # ----- active environment (set per session from the LangGraph state) -----

    def get_active_env(self) -> Optional[str]:
        return self._config.get("active_env")

    def get_env_size(self) -> str:
        return self._config.get("env_size", "small")

    def set_active_env(self, env_id: str, env_size: Optional[str] = None) -> None:
        self._config["active_env"] = env_id
        if env_size is not None:
            self._config["env_size"] = env_size

    # ----- paths -----

    @property
    def DATA_DIR(self) -> Path:
        return WORLD_MODEL_DIR / self._config.get("data", {}).get("root", "data")

    def get_schema_path(self) -> Path:
        return WORLD_MODEL_DIR / self._config.get("data", {}).get("schema", "data/schema.ttl")

    def get_env_dir(self, env_id: str, env_size: str) -> Path:
        return self.DATA_DIR / "envs" / env_id / env_size

    # ----- services -----

    def get_ontology_config(self) -> Dict[str, Any]:
        ontology_config = self._config.setdefault("ontology", {})
        ontology_config.setdefault("namespace", "http://example.org/OntoPlan#")
        return ontology_config

    def get_graphdb_config(self) -> Dict[str, Any]:
        graphdb_config = self._config.get("graphdb") or {}
        for field in ("url", "repository"):
            if not graphdb_config.get(field):
                raise ValueError(f"Missing graphdb.{field} in {self.config_path.name}")
        return graphdb_config

    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return os.getenv("OPENAI_API_KEY")

    # ----- embeddings -----

    def _embedding(self, kind: str) -> Dict[str, Any]:
        return self._config.get("embedding", {}).get(kind, {})

    @property
    def EMBEDDING_CATEGORY_MODEL(self) -> str:
        return self._embedding("category").get("model", "text-embedding-3-small")

    @property
    def EMBEDDING_CATEGORY_DIMENSIONS(self) -> int:
        return self._embedding("category").get("dimensions") or _DEFAULT_DIMENSIONS.get(self.EMBEDDING_CATEGORY_MODEL, 512)


_config_loader: Optional[ConfigLoader] = None


def get_config() -> ConfigLoader:
    """Process-wide config instance."""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader
