"""Scene query functions over the world model: object info, path finding, and semantic search."""

import re
from typing import Any, Dict, List, Optional, Union

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


def _invalid_ids(*ids: Optional[str]) -> List[str]:
    """Return the given IDs that are not plain IRI local names (e.g. 'living room')."""
    return [i for i in ids if i is not None and not _ID_PATTERN.match(i)]


class GraphDBTools:
    """Scene query functions backed by GraphDB (SPARQL) and the category vector index."""

    def __init__(self, manager, vector_store=None):
        """
        Args:
            manager: GraphDBManager connected to the world-model repository
            vector_store: VectorStoreManager for the active environment (needed by semantic_search)
        """
        self.manager = manager
        self.vector_store = vector_store
        self.ONTOLOGY_NS = manager.ONTOLOGY_NS

    def _query(self, sparql_query: str, infer: bool = True) -> Dict[str, Any]:
        return self.manager.query(sparql_query, infer=infer)

    def get_object_info(self, object_ids: Union[str, List[str]]) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """Get complete information about object(s).

        Args:
            object_ids: Single ID or list of IDs

        Returns:
            - If single ID: Dictionary with object info, or None if not found
            - If list of IDs: List of dictionaries

        Examples:
            info = tools.get_object_info("mug_5")
            infos = tools.get_object_info(["mug_5", "kitchen_20"])
        """
        is_single = isinstance(object_ids, str)
        requested = [object_ids] if is_single else list(object_ids)
        valid = [i for i in requested if not _invalid_ids(i)]

        objects_map: Dict[str, Dict[str, Any]] = {}
        if valid:
            values_clause = " ".join(f":{i}" for i in valid)
            sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT ?obj ?prop ?value WHERE {{
    VALUES ?obj {{ {values_clause} }}
    ?obj ?prop ?value .
    ?prop :llm_readable true .
}}
"""
            bindings = self._query(sparql, infer=True).get('results', {}).get('bindings', [])
            for b in bindings:
                obj_id = b['obj']['value'].split('#')[-1]
                prop = b['prop']['value'].split('#')[-1]
                value_data = b['value']
                obj = objects_map.setdefault(obj_id, {"id": obj_id})
                if prop in ('id', 'affords'):
                    continue
                value = value_data['value'].split('#')[-1] if value_data['type'] == 'uri' else value_data['value']
                if prop in ('objectIsInSpace', 'robotIsInSpace'):
                    prop = 'isInSpace'
                elif prop in ('roomIsInStorey', 'corridorIsInStorey'):
                    prop = 'isInStorey'
                if prop in obj:
                    if not isinstance(obj[prop], list):
                        obj[prop] = [obj[prop]]
                    if value not in obj[prop]:
                        obj[prop].append(value)
                else:
                    obj[prop] = value

        # Keep input order; mark missing IDs
        if is_single:
            return objects_map.get(requested[0]) or {"_message": f"⚠️ Object '{requested[0]}' not found."}
        return [objects_map.get(i) or {"id": i, "_not_found": True, "_message": f"⚠️ Object '{i}' not found."}
                for i in requested]

    def _get_compact_info(self, object_ids: List[str], class_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get compact object info for exploration (fewer fields than get_object_info).

        Space returns: category, isInStorey, hasArtifact, hasDoor, hasOpening, hasStairs, isConnectedTo
        Others return: category, isInSpace, isInStorey, isInsideOf, isOntopOf, isOpen, isSwitchedOn, supports, contains
        """
        if not object_ids:
            return []

        values_clause = " ".join([f':{id}' for id in object_ids])

        if class_name == "Space":
            props = ["category", "isInStorey", "hasArtifact", "hasDoor", "hasOpening", "hasStairs", "isConnectedTo"]
        elif class_name in ("Door", "Opening", "Stairs"):
            # Portal types connect to spaces via isDoorOf/isOpeningOf/isStairsOf, not isInSpace
            props = ["category", "isDoorOf", "isOpeningOf", "isStairsOf", "isOpen"]
        else:
            props = ["category", "isInSpace", "isInStorey", "isInsideOf", "isOntopOf", "isOpen", "isSwitchedOn", "supports", "contains"]

        props_clause = " ".join([f':{p}' for p in props])

        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT ?obj ?prop ?value WHERE {{
    VALUES ?obj {{ {values_clause} }}
    VALUES ?prop {{ {props_clause} }}
    ?obj ?prop ?value .
}}
"""
        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])

        objects_map: Dict[str, Dict[str, Any]] = {}
        for b in bindings:
            obj_id = b['obj']['value'].split('#')[-1]
            prop = b['prop']['value'].split('#')[-1]
            value_data = b['value']

            if obj_id not in objects_map:
                objects_map[obj_id] = {"id": obj_id}

            value = value_data['value'].split('#')[-1] if value_data['type'] == 'uri' else value_data['value']

            if prop in objects_map[obj_id]:
                if not isinstance(objects_map[obj_id][prop], list):
                    objects_map[obj_id][prop] = [objects_map[obj_id][prop]]
                if value not in objects_map[obj_id][prop]:
                    objects_map[obj_id][prop].append(value)
            else:
                objects_map[obj_id][prop] = value

        return [objects_map[id] for id in object_ids if id in objects_map]

    def find_path(self, from_id: str, to_id: str, reason: str) -> Optional[Dict[str, Any]]:
        """Find shortest path between two locations using GraphDB path search.

        Args:
            from_id: Source object or space ID
            to_id: Target object or space ID

        Returns:
            Dictionary with path information including edges, or None if no path exists
        """
        bad = _invalid_ids(from_id, to_id)
        if bad:
            return {"_message": f"⚠️ Invalid ID(s) {bad}: use exact IDs returned by semantic_search."}

        # First, resolve objects to their containing spaces
        from_space = self._resolve_to_space(from_id)
        if not from_space:
            types = self._get_entity_types(from_id)
            if not types:
                return {"_message": f"⚠️ Source '{from_id}' not found."}
            return {"_message": f"⚠️ Source '{from_id}' could not be resolved to a space."}

        to_space = self._resolve_to_space(to_id)
        if not to_space:
            types = self._get_entity_types(to_id)
            if not types:
                return {"_message": f"⚠️ Destination '{to_id}' not found."}
            return {"_message": f"⚠️ Destination '{to_id}' could not be resolved to a space."}

        # Find shortest path using GraphDB path search
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
PREFIX path: <http://www.ontotext.com/path#>

SELECT ?start ?end WHERE {{
    SERVICE <http://www.ontotext.com/path#search> {{
        <urn:path> path:findPath path:shortestPath ;
                   path:sourceNode :{from_space} ;
                   path:destinationNode :{to_space} ;
                   path:startNode ?start ;
                   path:endNode ?end ;
                   path:maxPathLength -1 .

        SERVICE <urn:path> {{
            ?start :hasPathTo ?end .
        }}
    }}
}}
"""

        result = self._query(sparql, infer=True)
        bindings = result['results']['bindings']

        if not bindings:
            return {"_message": f"ℹ️ No path exists between '{from_id}' and '{to_id}'."}

        # Extract path edges
        path_edges = []
        for b in bindings:
            start = b['start']['value'].split('#')[-1]
            end = b['end']['value'].split('#')[-1]
            path_edges.append({"from": start, "to": end})

        return {
            "from": from_id,
            "to": to_id,
            "from_space": from_space,
            "to_space": to_space,
            "path_exists": True,
            "path_length": len(path_edges),
            "path": path_edges
        }

    def _resolve_to_space(self, object_id: str) -> Optional[str]:
        """Resolve object to its containing space.

        Args:
            object_id: Object or space ID

        Returns:
            Space ID or None
        """
        # Check if object is a Space
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT ?type WHERE {{
    :{object_id} a ?type .
}}
"""

        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])

        # Handle both # and / separators
        types = [b['type']['value'].split('#')[-1] for b in bindings]

        if 'Space' in types:
            return object_id

        # If not a Space, find containing space using isInSpace (reasoning infers from subproperties)
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT ?space WHERE {{
    :{object_id} :isInSpace ?space .
}}
LIMIT 1
"""

        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])

        if bindings:
            # Handle both # and / separators
            return bindings[0]['space']['value'].split('#')[-1]

        return None

    def _get_entity_types(self, entity_id: str) -> List[str]:
        """Return ontology class types for an entity. Returns [] if entity doesn't exist."""
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT ?type WHERE {{
    :{entity_id} a ?type .
    FILTER(?type IN (:Artifact, :Space, :Door, :Opening, :Stairs, :Storey, :Building))
}}
"""
        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])
        return [b['type']['value'].split('#')[-1] for b in bindings]

    def _execute_filter_query(self,
                              class_name: Optional[str],
                              category: Optional[str],
                              relationships: Optional[Dict[str, str]]) -> List[str]:
        """Execute filter SPARQL and return matching IDs only (no enrichment).

        Portal types (Door, Opening, Stairs) are handled transparently:
        - in_space  → rewritten to isDoorOf / isOpeningOf / isStairsOf
        - in_storey → rewritten to portal_prop → space → isInStorey (indirect path)
        """
        _PORTAL_PROP = {'Door': 'isDoorOf', 'Opening': 'isOpeningOf', 'Stairs': 'isStairsOf'}

        where_clauses = []

        if class_name:
            where_clauses.append(f"?obj a :{class_name} .")
        if category:
            where_clauses.append(f'?obj :category "{category}" .')
        if relationships:
            portal_prop = _PORTAL_PROP.get(class_name) if class_name else None
            for rel_type, target_id in relationships.items():
                if portal_prop and rel_type == 'isInSpace':
                    # Door/Opening/Stairs are linked via isDoorOf/isOpeningOf/isStairsOf, not isInSpace
                    where_clauses.append(f"?obj :{portal_prop} :{target_id} .")
                elif portal_prop and rel_type == 'isInStorey':
                    # Door/Opening/Stairs → connected space → storey (indirect path)
                    where_clauses.append(f"?obj :{portal_prop} ?_space .")
                    where_clauses.append(f"?_space :isInStorey :{target_id} .")
                else:
                    where_clauses.append(f"?obj :{rel_type} :{target_id} .")
        if not where_clauses:
            return []

        where_clause = "\n    ".join(where_clauses)
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT DISTINCT ?obj WHERE {{
    {where_clause}
}}
ORDER BY ?obj
"""
        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])
        return [b['obj']['value'].split('#')[-1] for b in bindings]

    def get_space_overview(self) -> str:
        """Return a compact floor→space structure string for SE initial context.

        Format:
            Floor_A: kitchen_19 (kitchen), living_room_21 (living_room), ...
            Floor_B: kitchen_20 (kitchen), living_room_22 (living_room), ...

        Only includes Space instances (not Artifact/Portal types).
        """
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
SELECT ?space ?category ?storey WHERE {{
    ?space a :Space .
    FILTER NOT EXISTS {{ ?space a :Door . }}
    FILTER NOT EXISTS {{ ?space a :Opening . }}
    FILTER NOT EXISTS {{ ?space a :Stairs . }}
    OPTIONAL {{ ?space :category ?category . }}
    OPTIONAL {{ ?space :isInStorey ?storey . }}
}}
ORDER BY ?storey ?space
"""
        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])

        from collections import defaultdict
        storey_map: dict = defaultdict(list)
        no_storey: list = []

        for b in bindings:
            space_id = b['space']['value'].split('#')[-1]
            category = b.get('category', {}).get('value', '') if 'category' in b else ''
            storey = b.get('storey', {}).get('value', '').split('#')[-1] if 'storey' in b else ''

            entry = f"{space_id} ({category})" if category else space_id
            if storey:
                if entry not in storey_map[storey]:
                    storey_map[storey].append(entry)
            else:
                if entry not in no_storey:
                    no_storey.append(entry)

        lines = []
        for storey in sorted(storey_map.keys()):
            lines.append(f"  {storey}: {', '.join(storey_map[storey])}")
        if no_storey:
            lines.append(f"  (no storey): {', '.join(no_storey)}")

        # Append robot's current location
        robot_sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
SELECT ?space WHERE {{
    :robot :robotIsInSpace ?space .
}}
LIMIT 1
"""
        robot_result = self._query(robot_sparql, infer=True)
        robot_bindings = robot_result.get('results', {}).get('bindings', [])
        if robot_bindings:
            robot_space = robot_bindings[0]['space']['value'].split('#')[-1]
            # Find the storey for robot's space
            robot_storey = None
            for storey, spaces in storey_map.items():
                if any(robot_space in e for e in spaces):
                    robot_storey = storey
                    break
            if robot_storey:
                lines.append(f"\nRobot is currently in: {robot_space} ({robot_storey})")
            else:
                lines.append(f"\nRobot is currently in: {robot_space}")

        return "\n".join(lines) if lines else "(no spaces found)"

    def _detect_portal_class(self, category: str) -> Optional[str]:
        """Return 'Door', 'Opening', or 'Stairs' if objects of this category belong to a portal class."""
        if not category:
            return None
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
SELECT DISTINCT ?cls WHERE {{
    ?obj :category "{category}" .
    VALUES ?cls {{ :Door :Opening :Stairs }}
    ?obj a ?cls .
}}
LIMIT 1
"""
        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])
        if bindings:
            return bindings[0]['cls']['value'].split('#')[-1]
        return None

    def _execute_object_container_query(
        self,
        class_name: Optional[str],
        category: Optional[str],
        object_id: str,
    ) -> List[str]:
        """Return IDs of objects ON TOP OF or INSIDE object_id."""
        type_clause = f"    ?obj a :{class_name} .\n" if class_name else ""
        cat_clause = f'    ?obj :category "{category}" .\n' if category else ""
        sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>

SELECT DISTINCT ?obj WHERE {{
{type_clause}{cat_clause}    {{ ?obj :isOntopOf :{object_id} . }} UNION {{ ?obj :isInsideOf :{object_id} . }}
}}
ORDER BY ?obj
"""
        result = self._query(sparql, infer=True)
        bindings = result.get('results', {}).get('bindings', [])
        return [b['obj']['value'].split('#')[-1] for b in bindings]

    def semantic_search(
        self,
        query: str,
        reason: str = "",
        space_id: Optional[str] = None,
        floor_id: Optional[str] = None,
        object_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Unified scene query: embedding-based category match + spatial filter, returns instances directly.

        Args:
            query: Natural language description (e.g., "water bottle", "door", "stairs")
            space_id: Optional space ID filter (portal types use isDoorOf/isStairsOf rewrite)
            floor_id: Optional storey ID filter
            object_id: Optional — find objects ON TOP OF or INSIDE this object

        Returns:
            {
                "hint": "Query 'X' matched 'Y'. Similar: A, B, C. Showing Y results.",
                "results": [compact object dicts with id, category, location, state]
            }
        """
        out: Dict[str, Any] = {"hint": "", "results": []}
        bad = _invalid_ids(space_id, floor_id, object_id)
        if bad:
            out["hint"] = f"Invalid ID(s) {bad}: space_id/floor_id/object_id must be exact IDs (e.g. 'kitchen_20', 'Floor_B')."
            return out

        top1_category: Optional[str] = None
        class_name: Optional[str] = None

        if query.strip():
            top_cats = self.vector_store.search_categories(query, k=5)
            if not top_cats:
                out["hint"] = f"No matching category found for '{query}'."
                return out

            top1_category = top_cats[0]
            similar = top_cats[1:]

            hint = f"Query '{query}' matched '{top1_category}'."
            if similar:
                hint += f" If empty or wrong match, retry with: {', '.join(similar)}."
            hint += f" Showing results for '{top1_category}'."
            out["hint"] = hint

            # Direct mapping for portal category names — Door/Stairs/Opening instances have no
            # :category property in the KG, so vector-store metadata and _detect_portal_class both fail.
            _PORTAL_CATEGORY_DIRECT = {"door": "Door", "stairs": "Stairs", "opening": "Opening"}
            class_name = _PORTAL_CATEGORY_DIRECT.get(top1_category.lower()) if top1_category else None

            # Check portal_class / is_space from vector store metadata (avoids SPARQL round-trips)
            if not class_name and self.vector_store:
                idx = self.vector_store.category_name_to_idx.get(top1_category)
                if idx is not None:
                    meta = self.vector_store.category_idx_to_metadata.get(idx, {})
                    class_name = meta.get("portal_class")
                    if not class_name and meta.get("is_space"):
                        class_name = "Space"
            if not class_name:
                class_name = self._detect_portal_class(top1_category)
        else:
            out["hint"] = "No query provided; filtering by spatial parameter only."

        # Portal objects (Door/Stairs/Opening) have no :category property — don't filter by it
        _PORTAL_CLASSES = {"Door", "Stairs", "Opening"}
        query_category = None if class_name in _PORTAL_CLASSES else top1_category

        if object_id:
            ids = self._execute_object_container_query(class_name, query_category, object_id)
        else:
            relationships: Dict[str, str] = {}
            if space_id:
                relationships["isInSpace"] = space_id
            if floor_id:
                relationships["isInStorey"] = floor_id
            ids = self._execute_filter_query(
                class_name, query_category, relationships or None
            )

            # Fallback: if spatial filter was applied but returned nothing, retry globally
            if not ids and relationships:
                global_ids = self._execute_filter_query(class_name, top1_category, None)
                if global_ids:
                    if class_name == "Space" and "isInSpace" in relationships:
                        # Spaces are never isInSpace of another space — space_id filter is not applicable.
                        # Return all results; use isConnectedTo in each result to determine adjacency.
                        out["hint"] += (
                            f" Note: space_id filter does not apply to room/space types."
                            f" Showing all {len(global_ids)} result(s); check isConnectedTo for adjacency."
                        )
                    else:
                        filter_desc = " and ".join(
                            f"{k.replace('isInSpace', 'space').replace('isInStorey', 'floor')} '{v}'"
                            for k, v in relationships.items()
                        )
                        out["hint"] += (
                            f" No results in {filter_desc}."
                            f" Showing {len(global_ids)} global result(s) as fallback — verify isInSpace to confirm correct location."
                        )
                    ids = global_ids

        if ids:
            out["results"] = self._get_compact_info(ids, class_name)

        # Append contextual info for space_id filter
        if space_id:
            space_info = self._get_compact_info([space_id], "Space")
            if space_info:
                s = space_info[0]
                storey = s.get("isInStorey", "?")
                connected = s.get("isConnectedTo", [])
                if isinstance(connected, str):
                    connected = [connected]
                connected_str = ", ".join(connected) if connected else "none"
                out["hint"] += f" [space_id={space_id}: floor={storey}, connected to: {connected_str}]"

        # Append contextual info for object_id filter
        if object_id:
            obj_info_list = self._get_compact_info([object_id])
            if obj_info_list:
                obj_info = obj_info_list[0]
                in_space = obj_info.get("isInSpace", "?")
                storey = obj_info.get("isInStorey", "?")
                out["hint"] += f" [object_id={object_id}: in {in_space} ({storey})]"

        return out



