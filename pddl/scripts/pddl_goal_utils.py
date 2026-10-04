"""PDDL Goal Utilities - Extract and classify objects from goal formula."""

import re
from typing import List, Set, Tuple, Dict
from world_model.core.manager import GraphDBManager
from world_model.core.config import get_config

config = get_config()
ONTOLOGY_NS = config.get_ontology_config()['namespace']


def extract_identifiers_from_goal(goal_formula: str) -> Set[str]:
    """Extract all potential identifiers from PDDL goal formula."""
    keywords = {
        'and', 'or', 'not', 'forall', 'exists', 'when', 'imply',
        'either', 'increase', 'decrease', 'assign'
    }

    pattern = r'\b([a-zA-Z][a-zA-Z0-9_-]*)\b'
    identifiers = re.findall(pattern, goal_formula)
    return {id for id in identifiers if id.lower() not in keywords}


def filter_valid_object_ids(identifiers: Set[str], manager: GraphDBManager) -> List[str]:
    """Filter identifiers to only include valid object IDs (not properties) that exist in GraphDB."""
    if not identifiers:
        return []

    # Build VALUES clause
    values_clause = " ".join([f':{id}' for id in identifiers])

    sparql = f"""
PREFIX : <{ONTOLOGY_NS}>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>

SELECT DISTINCT ?id WHERE {{
    VALUES ?obj {{ {values_clause} }}
    BIND(REPLACE(REPLACE(STR(?obj), STR(:), ''), '/', '') AS ?id)

    # Must have a type (not be a property definition)
    ?obj rdf:type ?type .

    # Exclude properties
    FILTER NOT EXISTS {{ ?obj rdf:type owl:ObjectProperty }}
    FILTER NOT EXISTS {{ ?obj rdf:type owl:DatatypeProperty }}
}}
"""

    result = manager.query(sparql, infer=True)
    return [b['id']['value'] for b in result['results']['bindings']]


def extract_object_ids_from_goal(goal_formula: str, manager: GraphDBManager) -> List[str]:
    """Extract valid object IDs from PDDL goal formula."""
    identifiers = extract_identifiers_from_goal(goal_formula)
    return filter_valid_object_ids(identifiers, manager)


def classify_objects_by_domain_type(
    object_ids: List[str],
    types_map: Dict[str, str],
    domain_parser
) -> Tuple[List[str], List[str]]:
    """Classify object IDs into artifacts and locations based on domain type hierarchy."""
    artifact_ids = []
    location_ids = []

    for obj_id in object_ids:
        obj_type = types_map.get(obj_id)

        if not obj_type:
            continue

        if domain_parser.is_subtype_of(obj_type, "Location") or obj_type == "Location":
            location_ids.append(obj_id)
        elif obj_type == "Artifact":
            artifact_ids.append(obj_id)

    return artifact_ids, location_ids


def _tokenize(formula: str) -> List[str]:
    return re.findall(r"\(|\)|[^\s()]+", formula)


def _parse(tokens: List[str], i: int = 0):
    """Parse one s-expression starting at tokens[i]; return (expr, next_index)."""
    if tokens[i] != "(":
        return tokens[i], i + 1
    expr, i = [], i + 1
    while tokens[i] != ")":
        sub, i = _parse(tokens, i)
        expr.append(sub)
    return expr, i + 1


def _render(expr) -> str:
    return expr if isinstance(expr, str) else "(" + " ".join(_render(e) for e in expr) + ")"


def split_conjuncts(formula: str) -> List[str]:
    """Top-level conjuncts of a goal formula in canonical spacing.

    "(and (a x) (and (b y) (c z)))" -> ["(a x)", "(b y)", "(c z)"]
    """
    tokens = _tokenize(formula or "")
    if not tokens:
        return []
    expr, _ = _parse(tokens)
    if isinstance(expr, list) and expr and expr[0] == "and":
        return [c for sub in expr[1:] for c in split_conjuncts(_render(sub))]
    return [_render(expr)]
