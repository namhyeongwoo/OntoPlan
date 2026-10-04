"""Category embedding index used by `semantic_search` to map free-text queries to scene categories."""

import logging
import pickle
from typing import Any, Dict, List

import faiss
import numpy as np
from openai import OpenAI

logger = logging.getLogger(__name__)

# Portal classes have no :category property; their names are injected into the index
# so that queries such as "door" or "stairs" match directly.
PORTAL_CATEGORY_MAP = {"door": "Door", "stairs": "Stairs", "opening": "Opening"}


class VectorStoreManager:
    """Per-environment FAISS index over object and space category names (OpenAI embeddings)."""

    def __init__(self, config, graphdb_manager, env_id: str, env_size: str):
        self.graphdb_manager = graphdb_manager
        self.env_id = env_id
        self.env_size = env_size
        self.ONTOLOGY_NS = config.get_ontology_config()["namespace"]

        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set (see .env.example)")
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)

        self.category_model = config.EMBEDDING_CATEGORY_MODEL
        self.category_dimensions = config.EMBEDDING_CATEGORY_DIMENSIONS

        self.store_dir = config.get_env_dir(env_id, env_size) / "vector_store"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.category_index_path = self.store_dir / "category.faiss"
        self.category_metadata_path = self.store_dir / "category_metadata.pkl"

        self.category_index = None
        self.category_name_to_idx: Dict[str, int] = {}
        self.category_idx_to_metadata: Dict[int, Dict[str, Any]] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load the cached index if it was built with the configured model and dimensions."""
        if not (self.category_index_path.exists() and self.category_metadata_path.exists()):
            return
        try:
            with open(self.category_metadata_path, "rb") as f:
                metadata = pickle.load(f)
            if (metadata.get("model"), metadata.get("dimensions")) != (self.category_model, self.category_dimensions):
                logger.info(
                    "Cached category index for %s/%s uses %s/%s; config asks for %s/%s. Rebuilding.",
                    self.env_id, self.env_size, metadata.get("model"), metadata.get("dimensions"),
                    self.category_model, self.category_dimensions,
                )
                return
            self.category_index = faiss.read_index(str(self.category_index_path))
            self.category_name_to_idx = metadata["name_to_idx"]
            self.category_idx_to_metadata = metadata["idx_to_metadata"]
        except Exception as e:  # corrupted or incompatible cache: rebuild
            logger.warning("Could not load category index (%s). Rebuilding.", e)
            self.category_index = None

    def is_ready(self) -> bool:
        return self.category_index is not None

    def _save_index(self) -> None:
        faiss.write_index(self.category_index, str(self.category_index_path))
        metadata = {
            "name_to_idx": self.category_name_to_idx,
            "idx_to_metadata": self.category_idx_to_metadata,
            "model": self.category_model,
            "dimensions": self.category_dimensions,
        }
        with open(self.category_metadata_path, "wb") as f:
            pickle.dump(metadata, f)

    def _embed(self, texts: List[str]) -> np.ndarray:
        vectors: List[List[float]] = []
        for i in range(0, len(texts), 2048):  # API batch limit
            response = self.client.embeddings.create(
                input=texts[i:i + 2048], model=self.category_model, dimensions=self.category_dimensions
            )
            vectors.extend(item.embedding for item in response.data)
        array = np.array(vectors, dtype=np.float32)
        faiss.normalize_L2(array)
        return array

    def _fetch_categories(self) -> Dict[str, bool]:
        """Return {category: is_space} for all artifacts and (non-portal) spaces.

        Instances without a :category are indexed as "unknown".
        """
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
SELECT DISTINCT ?category ?isSpace WHERE {{
    {{ ?obj a :Artifact . OPTIONAL {{ ?obj :category ?category }} BIND(false AS ?isSpace) }}
    UNION
    {{ ?obj a :Space . OPTIONAL {{ ?obj :category ?category }}
       FILTER NOT EXISTS {{ ?obj a :Door }} FILTER NOT EXISTS {{ ?obj a :Stairs }} FILTER NOT EXISTS {{ ?obj a :Opening }}
       BIND(true AS ?isSpace) }}
}}"""
        bindings = self.graphdb_manager.query(sparql, infer=True).get("results", {}).get("bindings", [])
        categories: Dict[str, bool] = {}
        for b in bindings:
            name = b.get("category", {}).get("value", "unknown")
            is_space = "category" in b and b["isSpace"]["value"] == "true"
            categories[name] = categories.get(name, False) or is_space
        return categories

    def build_from_graphdb(self) -> None:
        """Embed all category names in the loaded environment and save the index."""
        categories = self._fetch_categories()
        if not categories:
            raise RuntimeError(f"No categories found in GraphDB for {self.env_id}/{self.env_size}")

        names = sorted(set(categories) | set(PORTAL_CATEGORY_MAP))
        embeddings = self._embed(names)

        # HNSW index with the parameters used in the paper's experiments
        self.category_index = faiss.IndexHNSWFlat(self.category_dimensions, 32)
        self.category_index.hnsw.efConstruction = 200
        self.category_index.hnsw.efSearch = 64
        self.category_index.add(embeddings)
        self.category_name_to_idx = {name: i for i, name in enumerate(names)}
        self.category_idx_to_metadata = {
            i: {"category": name, "portal_class": PORTAL_CATEGORY_MAP.get(name), "is_space": categories.get(name, False)}
            for i, name in enumerate(names)
        }
        self._save_index()
        logger.info("Built category index for %s/%s (%d categories)", self.env_id, self.env_size, len(names))

    def search_categories(self, query: str, k: int = 5) -> List[str]:
        """Return the k category names closest to the query."""
        if self.category_index is None:
            raise RuntimeError("Category index not built; call build_from_graphdb() first")
        _, indices = self.category_index.search(self._embed([query]), k)
        return [self.category_idx_to_metadata[i]["category"] for i in indices[0] if i != -1]
