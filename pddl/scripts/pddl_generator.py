"""PDDL Generator - Extract PDDL problem data from knowledge graph."""

import logging
from typing import Dict, List, Any
from world_model.core.manager import GraphDBManager
from world_model.core.config import get_config

logger = logging.getLogger(__name__)


class PDDLGenerator:
    """Generate PDDL problem data from knowledge graph via SPARQL."""

    def __init__(self, manager: GraphDBManager, domain_parser):
        """
        Initialize PDDL generator.

        Args:
            manager: GraphDBManager instance
            domain_parser: PDDLDomainParser instance
        """
        self.manager = manager
        self.parser = domain_parser

        config = get_config()
        self.ONTOLOGY_NS = config.get_ontology_config()['namespace']

    def get_types(self, ids: List[str]) -> Dict[str, str]:
        """Get domain types for given IDs - uses classes that match PDDL types.

        Uses infer=False with explicit (rdfs:subClassOf)* traversal and tracks
        whether each type is directly asserted or inherited via subClassOf.
        Direct types are preferred over ancestor types so that, e.g., a Door
        is correctly classified as Door rather than its ancestor Space
        (given Portal rdfs:subClassOf Space in the schema).
        """
        types_map = {}
        pddl_types = set(self.parser.all_types)

        values_clause = " ".join([f':{id}' for id in ids])

        # Retrieve direct rdf:type assertions and their ancestors separately.
        # infer=False avoids OWL range inference side-effects (e.g.,
        # robotIsInSpace rdfs:range :Space causing door entities to be typed
        # as :Space via range axiom when the robot stands at a door).
        # The (rdfs:subClassOf)+ branch covers artifact subclasses whose direct
        # type is not a PDDL type (e.g. Oven → Artifact).
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?obj ?type ?isDirect WHERE {{
    VALUES ?obj {{ {values_clause} }}
    ?obj rdf:type ?directType .
    FILTER(STRSTARTS(STR(?directType), STR(:)))
    {{
        BIND(?directType AS ?type)
        BIND(true AS ?isDirect)
    }} UNION {{
        ?directType (rdfs:subClassOf)+ ?type .
        FILTER(STRSTARTS(STR(?type), STR(:)))
        BIND(false AS ?isDirect)
    }}
}}
"""

        result = self.manager.query(sparql, infer=False)
        bindings = result['results']['bindings']

        # Separate direct types from ancestor types per object
        obj_direct = {}
        obj_ancestors = {}
        for b in bindings:
            obj_id = b['obj']['value'].split('#')[-1]
            type_name = b['type']['value'].split('#')[-1]
            is_direct = b.get('isDirect', {}).get('value', 'false').lower() == 'true'

            if is_direct:
                obj_direct.setdefault(obj_id, []).append(type_name)
            else:
                obj_ancestors.setdefault(obj_id, []).append(type_name)

        # Map to PDDL types: direct type takes priority over ancestor type
        for obj_id in ids:
            domain_type = None

            for class_name in obj_direct.get(obj_id, []):
                if class_name in pddl_types:
                    domain_type = class_name
                    break

            if not domain_type:
                for class_name in obj_ancestors.get(obj_id, []):
                    if class_name in pddl_types:
                        domain_type = class_name
                        break

            if domain_type:
                types_map[obj_id] = domain_type
            else:
                all_types = obj_direct.get(obj_id, []) + obj_ancestors.get(obj_id, [])
                logger.debug("Skipping %s: classes %s have no PDDL type", obj_id, all_types)

        return types_map

    def get_robot_info(self) -> Dict[str, Any]:
        """Get robot and hand information with all relationships in a single query."""
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT ?robot ?hand ?location ?heldArtifact ?adjacentArtifact WHERE {{
    ?robot a :Robot .
    OPTIONAL {{ ?robot :hasHand ?hand . }}
    OPTIONAL {{ ?robot :robotIsInSpace ?location . }}
    OPTIONAL {{ ?hand :holds ?heldArtifact . }}
    OPTIONAL {{ ?robot :isAdjacentTo ?adjacentArtifact . }}
}}
"""

        result = self.manager.query(sparql, infer=True)
        bindings = result['results']['bindings']

        if not bindings:
            return None

        # Collect robot info
        robot_id = None
        hands = set()
        location = None
        holds_relations = []
        adjacent_relations = []

        for b in bindings:
            if not robot_id:
                robot_id = b['robot']['value'].split('#')[-1]

            if 'hand' in b:
                hands.add(b['hand']['value'].split('#')[-1])

            if 'location' in b and not location:
                location = b['location']['value'].split('#')[-1]

            if 'heldArtifact' in b and 'hand' in b:
                hand_id = b['hand']['value'].split('#')[-1]
                artifact_id = b['heldArtifact']['value'].split('#')[-1]
                relation = (hand_id, artifact_id)
                if relation not in holds_relations:
                    holds_relations.append(relation)

            if 'adjacentArtifact' in b:
                robot_id_adj = b['robot']['value'].split('#')[-1]
                artifact_id = b['adjacentArtifact']['value'].split('#')[-1]
                relation = (robot_id_adj, artifact_id)
                if relation not in adjacent_relations:
                    adjacent_relations.append(relation)

        return {
            "robot_id": robot_id,
            "hands": list(hands),
            "location": location,
            "holds": holds_relations,
            "adjacent": adjacent_relations
        }

    def get_topology_with_paths(self, location_ids: List[str]) -> Dict[str, Any]:
        """
        Get full topology by fetching all hasPathTo triples from the KG.

        Ignores location_ids for topology construction — returns the complete
        navigation graph so the planner always has all alternative routes.
        location_ids are still included in the returned locations set so that
        the caller can collect all required objects.

        Args:
            location_ids: Location IDs from goal + robot (included in returned set)

        Returns:
            Dict with 'locations' (all locations in KG), 'connections', and 'distances'
        """
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT ?start ?end WHERE {{
    ?start :hasPathTo ?end .
}}
"""
        result = self.manager.query(sparql, infer=True)
        bindings = result['results']['bindings']

        all_locations = set(location_ids)
        all_edges = set()

        for b in bindings:
            start = b['start']['value'].split('#')[-1]
            end = b['end']['value'].split('#')[-1]
            all_locations.add(start)
            all_locations.add(end)
            all_edges.add((start, end))

        connections = []
        distances = {}
        seen_pairs = set()

        for start, end in all_edges:
            pair = tuple(sorted([start, end]))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                connections.append((start, end))
                distances[(start, end)] = 1
                distances[(end, start)] = 1

        return {
            "locations": all_locations,
            "connections": connections,
            "distances": distances
        }

    def get_artifact_locations(self, artifact_ids: List[str]) -> Dict[str, Dict[str, str]]:
        """
        Get location information for artifacts and all related containers/surfaces.

        Strategy:
        Find all artifacts in the containment chain (bidirectional) and their location relationships.

        Args:
            artifact_ids: Initial artifact IDs from goal

        Returns:
            Dict mapping artifact_id to location relationships
        """
        locations_map = {}
        values_clause = " ".join([f':{id}' for id in artifact_ids])

        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT DISTINCT ?artifact ?rel ?target WHERE {{
    VALUES ?goal {{ {values_clause} }}

    # Find all artifacts in containment chain (bidirectional)
    {{
        # Goal artifact itself
        BIND(?goal AS ?artifact)
    }}
    UNION
    {{
        # Artifacts above the goal (containers)
        ?goal (:isInsideOf|:isOntopOf)+ ?artifact .
    }}
    UNION
    {{
        # Artifacts below the goal (contents)
        ?artifact (:isInsideOf|:isOntopOf)+ ?goal .
    }}

    # Must be an Artifact
    ?artifact a :Artifact .

    # Get location relationships (only 3 PDDL predicates)
    OPTIONAL {{
        ?artifact ?rel ?target .
        FILTER(?rel IN (:isInsideOf, :isOntopOf, :isOnFloorOf))
    }}
}}
"""

        # Explicit facts only: isOntopOf/isInsideOf are transitive in the ontology, so with
        # inference an object on a bowl on a table would also be "on the table", and only one
        # target per relation is kept below. Locations are always asserted explicitly.
        result = self.manager.query(sparql, infer=False)
        bindings = result['results']['bindings']

        # Map GraphDB properties to PDDL predicates (1:1 mapping)
        property_to_pddl = {
            'isOnFloorOf': 'isOnFloorOf',
            'isInsideOf': 'isInsideOf',
            'isOntopOf': 'isOntopOf'
        }

        # Organize by artifact
        for b in bindings:
            artifact_id = b['artifact']['value'].split('#')[-1]

            if artifact_id not in locations_map:
                locations_map[artifact_id] = {}

            # Add relationship if exists
            if 'rel' in b and 'target' in b:
                rel_name = b['rel']['value'].split('#')[-1]
                target_id = b['target']['value'].split('#')[-1]

                # Map to PDDL predicate name
                pddl_predicate = property_to_pddl.get(rel_name, rel_name)
                locations_map[artifact_id][pddl_predicate] = target_id

        return locations_map

    def get_blocked_artifacts(self, artifact_ids: List[str], problem_ids: List[str]) -> List[str]:
        """Artifacts with something on top that is not part of the PDDL problem.

        Such an artifact cannot be picked up (canManipulate requires nothing on top), but the
        planner cannot see why, so its pick affordances must be withheld.
        """
        if not artifact_ids:
            return []
        values = " ".join(f":{a}" for a in artifact_ids)
        listed = ", ".join(f":{a}" for a in problem_ids) or ":__none__"
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
SELECT DISTINCT ?a WHERE {{
    VALUES ?a {{ {values} }}
    ?z :isOntopOf ?a .
    FILTER(?z NOT IN ({listed}))
}}
"""
        result = self.manager.query(sparql, infer=True)
        return [b["a"]["value"].split("#")[-1] for b in result["results"]["bindings"]]

    def get_affordances(self, artifact_ids: List[str]) -> Dict[str, List[str]]:
        """Get affordances for artifacts and map to PDDL predicates."""
        affordances_map = {}
        values_clause = " ".join([f':{id}' for id in artifact_ids])

        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?artifact ?affordance WHERE {{
    VALUES ?artifact {{ {values_clause} }}
    ?artifact :affords ?affordance .
}}
"""

        result = self.manager.query(sparql, infer=True)
        bindings = result['results']['bindings']

        # Group by artifact
        for b in bindings:
            artifact_id = b['artifact']['value'].split('#')[-1]
            affordance_id = b['affordance']['value'].split('#')[-1]

            # Affordance ID is the PDDL predicate name (e.g., "Unimanual", "Bimanual")
            if artifact_id not in affordances_map:
                affordances_map[artifact_id] = []
            if affordance_id not in affordances_map[artifact_id]:
                affordances_map[artifact_id].append(affordance_id)

        return affordances_map

    def get_data_properties(self, object_ids: List[str]) -> Dict[str, Dict[str, bool]]:
        """Get boolean data properties for objects (isOpen, isSwitchedOn).

        Args:
            object_ids: List of object IDs to query

        Returns:
            Dict mapping object_id to dict of property names and boolean values
            Example: {"door_5": {"isOpen": True}, "tv_52": {"isSwitchedOn": False}}
        """
        if not object_ids:
            return {}

        data_properties_map = {}
        values_clause = " ".join([f':{id}' for id in object_ids])

        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?obj ?prop ?value WHERE {{
    VALUES ?obj {{ {values_clause} }}
    ?obj ?prop ?value .

    FILTER(?prop IN (:isOpen, :doorIsOpen, :isSwitchedOn))
    FILTER(DATATYPE(?value) = xsd:boolean)
}}
"""

        result = self.manager.query(sparql, infer=True)
        bindings = result['results']['bindings']

        for b in bindings:
            obj_id = b['obj']['value'].split('#')[-1]
            prop_name = b['prop']['value'].split('#')[-1]
            value_str = b['value']['value']

            value = value_str.lower() == 'true'

            if obj_id not in data_properties_map:
                data_properties_map[obj_id] = {}

            data_properties_map[obj_id][prop_name] = value

        return data_properties_map

    def get_all_required_objects(
        self,
        artifact_locs: Dict[str, Dict[str, str]],
        topology_result: Dict[str, Any],
        robot_info: Dict[str, Any]
    ) -> List[str]:
        """
        Collect all object IDs needed (artifacts, locations, robot, hands).

        Args:
            artifact_locs: Artifact location map (already includes all artifacts in chain)
            topology_result: Topology with expanded locations
            robot_info: Robot information from get_robot_info()

        Returns:
            Sorted list of all object IDs
        """
        all_ids = set()

        # Add all artifacts from location chain
        all_ids.update(artifact_locs.keys())

        # Add all targets from artifact locations (containers, surfaces, spaces)
        for loc_info in artifact_locs.values():
            all_ids.update(loc_info.values())

        # Add all locations from topology
        all_ids.update(topology_result["locations"])

        # Add robot and hands
        if robot_info:
            all_ids.add(robot_info["robot_id"])
            all_ids.update(robot_info["hands"])
            # Add artifacts that robot is holding (they need to be in :objects)
            if "holds" in robot_info and robot_info["holds"]:
                for hand_id, artifact_id in robot_info["holds"]:
                    all_ids.add(artifact_id)
            # Add artifacts that robot is adjacent to (they need to be in :objects)
            if "adjacent" in robot_info and robot_info["adjacent"]:
                for robot_id_adj, artifact_id in robot_info["adjacent"]:
                    all_ids.add(artifact_id)

        return sorted(all_ids)
