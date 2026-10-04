"""GraphDBManager: thin HTTP client for the GraphDB repository that stores the world model."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .config import get_config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60  # seconds

# OWL 2 RL repository definition used when the configured repository does not exist yet.
# GraphDB 10+ reads the ruleset from the graphdb: namespace; the older owlim: keys are
# silently ignored and the repository falls back to RDFS-Plus, which lacks the property
# chains the ontology relies on (e.g. a carried object is in the robot's room).
REQUIRED_RULESET = "owl2-rl"
_REPOSITORY_CONFIG = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rep: <http://www.openrdf.org/config/repository#> .
@prefix sr: <http://www.openrdf.org/config/repository/sail#> .
@prefix sail: <http://www.openrdf.org/config/sail#> .
@prefix graphdb: <http://www.ontotext.com/config/graphdb#> .

[] a rep:Repository ;
   rep:repositoryID "{repository}" ;
   rdfs:label "OntoPlan repository" ;
   rep:repositoryImpl [
     rep:repositoryType "graphdb:SailRepository" ;
     sr:sailImpl [
       sail:sailType "graphdb:Sail" ;
       graphdb:ruleset "owl2-rl" ;
       graphdb:check-for-inconsistencies "false" ;
       graphdb:disable-sameAs "false"
     ]
   ] .
"""


class GraphDBManager:
    """SPARQL query/update and TTL loading against one GraphDB repository."""

    def __init__(self, graphdb_url: Optional[str] = None, repository: Optional[str] = None):
        """Connect to GraphDB. URL and repository default to world_model/config.yaml."""
        config = get_config()
        graphdb_config = config.get_graphdb_config()
        self.graphdb_url = (graphdb_url or graphdb_config["url"]).rstrip("/")
        self.repository = repository or graphdb_config["repository"]
        self.ONTOLOGY_NS = config.get_ontology_config()["namespace"]

        self.query_url = f"{self.graphdb_url}/repositories/{self.repository}"
        self.statements_url = f"{self.query_url}/statements"

        self._ensure_repository()

    def _ensure_repository(self) -> None:
        """Check the GraphDB server and create the repository (OWL 2 RL) if it is missing."""
        repo_url = f"{self.graphdb_url}/rest/repositories/{self.repository}"
        try:
            response = requests.get(repo_url, timeout=REQUEST_TIMEOUT)
        except requests.ConnectionError as e:
            raise ConnectionError(
                f"Cannot reach GraphDB at {self.graphdb_url}. Start GraphDB first (see INSTALL.md)."
            ) from e
        if response.status_code == 200:
            ruleset = (response.json().get("params", {}).get("ruleset", {}) or {}).get("value")
            if ruleset and ruleset != REQUIRED_RULESET:
                raise RuntimeError(
                    f"GraphDB repository '{self.repository}' uses ruleset '{ruleset}', but OntoPlan needs "
                    f"'{REQUIRED_RULESET}' for its property chains. Delete the repository (or choose another "
                    f"repository name in world_model/config.yaml) and OntoPlan will recreate it."
                )
            return

        logger.info("Creating GraphDB repository '%s' (OWL2-RL)", self.repository)
        response = requests.post(
            f"{self.graphdb_url}/rest/repositories",
            files={"config": ("config.ttl", _REPOSITORY_CONFIG.replace("{repository}", self.repository))},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code not in (200, 201, 204):
            raise ConnectionError(
                f"Repository '{self.repository}' does not exist and could not be created: "
                f"{response.status_code} {response.text[:200]}"
            )
        self._ensure_repository()  # verify the ruleset was applied

    def _post_update(self, sparql_update: str, params: Optional[Dict[str, str]] = None) -> None:
        response = requests.post(
            self.statements_url,
            headers={"Content-Type": "application/sparql-update"},
            params=params,
            data=sparql_update.encode("utf-8"),
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 204:
            raise RuntimeError(f"SPARQL update failed: {response.status_code} - {response.text[:200]}")

    def query(self, sparql_query: str, infer: bool = True) -> Dict[str, Any]:
        """Run a SPARQL query and return the JSON result.

        Args:
            sparql_query: SPARQL SELECT/ASK query
            infer: Include inferred (OWL 2 RL) triples
        """
        response = requests.post(
            self.query_url,
            headers={"Accept": "application/sparql-results+json"},
            params={"infer": "true" if infer else "false"},
            data={"query": sparql_query},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise RuntimeError(f"SPARQL query failed: {response.status_code} - {response.text[:200]}")
        return response.json()

    def update(self, sparql_update: str, infer: bool = True) -> None:
        """Run a SPARQL UPDATE.

        Args:
            sparql_update: SPARQL INSERT/DELETE/graph-management request
            infer: Whether the WHERE clause sees inferred triples. Use False when copying
                state, so that entailments are not stored as explicit facts.
        """
        self._post_update(sparql_update, params=None if infer else {"infer": "false"})

    def clear_all(self) -> None:
        """Drop the default graph and all named graphs."""
        self._post_update("DROP SILENT ALL")

    def load_file(self, path: str) -> None:
        """Load a Turtle (.ttl) or N-Triples (.nt) file into the default graph."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"RDF file not found: {path}")
        content_type = "application/n-triples" if file_path.suffix == ".nt" else "text/turtle"
        with open(file_path, "rb") as f:
            response = requests.post(self.statements_url, headers={"Content-Type": content_type}, data=f,
                                     timeout=REQUEST_TIMEOUT)
        if response.status_code != 204:
            raise RuntimeError(f"Failed to load {file_path.name}: {response.status_code} - {response.text[:200]}")

    def export_explicit(self, path: str) -> None:
        """Write all explicit (asserted, not inferred) triples to an N-Triples file."""
        response = requests.post(
            self.query_url,
            headers={"Accept": "application/n-triples"},
            params={"infer": "false"},
            data={"query": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Export failed: {response.status_code} - {response.text[:200]}")
        Path(path).write_bytes(response.content)

    def close(self) -> None:
        """No persistent connection is held; kept for call-site symmetry."""
