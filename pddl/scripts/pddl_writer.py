"""PDDL Writer - Generate PDDL problem file from collected data."""

import logging
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class PDDLWriter:
    """Generate PDDL problem file from data."""

    def __init__(self, problem_name: str, domain_name: str = "robot"):
        """
        Initialize PDDL writer.

        Args:
            problem_name: Name of the problem
            domain_name: Name of the domain
        """
        self.problem_name = problem_name
        self.domain_name = domain_name

    def generate_objects(self, types_map: Dict[str, str]) -> str:
        """
        Generate objects section.

        Args:
            types_map: Dict mapping object_id to type

        Returns:
            PDDL objects section string
        """
        # Group by type
        types_grouped = {}
        for obj_id, obj_type in types_map.items():
            if obj_type not in types_grouped:
                types_grouped[obj_type] = []
            types_grouped[obj_type].append(obj_id)

        # Generate PDDL
        lines = ["  (:objects"]

        # Add comment for each type group
        for obj_type in sorted(types_grouped.keys()):
            obj_ids = sorted(types_grouped[obj_type])
            lines.append(f"    ; {obj_type}")
            lines.append(f"    {' '.join(obj_ids)} - {obj_type}")
            lines.append("")

        # Remove last empty line and add closing
        lines = lines[:-1]
        lines.append("  )")

        return "\n".join(lines)

    def generate_init_topology(self, topology: Dict[str, Any]) -> List[str]:
        """
        Generate topology section of init.

        Args:
            topology: Dict with 'connections' and 'distances'

        Returns:
            List of PDDL init statements
        """
        lines = []

        lines.append("    ; ====================================================================")
        lines.append("    ; TOPOLOGY")
        lines.append("    ; ====================================================================")

        connections = topology['connections']

        # Group connections by pairs
        for from_id, to_id in sorted(connections):
            lines.append(f"    (hasPathTo {from_id} {to_id})")
            lines.append(f"    (hasPathTo {to_id} {from_id})")

        return lines

    def generate_init_robot(self, robot_info: Dict[str, Any]) -> List[str]:
        """
        Generate robot structure section of init.

        Args:
            robot_info: Dict with robot_id, hands, location

        Returns:
            List of PDDL init statements
        """
        lines = []

        lines.append("    ; ====================================================================")
        lines.append("    ; ROBOT STRUCTURE")
        lines.append("    ; ====================================================================")

        robot_id = robot_info['robot_id']

        # hasHand relationships
        for hand_id in sorted(robot_info['hands']):
            lines.append(f"    (hasHand {robot_id} {hand_id})")

        # Initial location
        if robot_info['location']:
            lines.append(f"    (robotIsInSpace {robot_id} {robot_info['location']})")

        # holds relationships
        if 'holds' in robot_info and robot_info['holds']:
            for hand_id, artifact_id in sorted(robot_info['holds']):
                lines.append(f"    (holds {hand_id} {artifact_id})")

        # isAdjacentTo relationships
        if 'adjacent' in robot_info and robot_info['adjacent']:
            for robot_id_adj, artifact_id in sorted(robot_info['adjacent']):
                lines.append(f"    (isAdjacentTo {robot_id_adj} {artifact_id})")

        return lines

    def generate_init_artifact_locations(self, artifact_locs: Dict[str, Dict[str, str]]) -> List[str]:
        """
        Generate artifact location section of init.

        Args:
            artifact_locs: Dict mapping artifact_id to location info

        Returns:
            List of PDDL init statements
        """
        lines = []

        lines.append("    ; ====================================================================")
        lines.append("    ; ARTIFACT LOCATIONS")
        lines.append("    ; ====================================================================")

        for artifact_id in sorted(artifact_locs.keys()):
            loc_info = artifact_locs[artifact_id]

            # Record all location relationships
            for rel_type, target_id in sorted(loc_info.items()):
                lines.append(f"    ({rel_type} {artifact_id} {target_id})")

        return lines

    def generate_init_affordances(self, affordances_map: Dict[str, List[str]]) -> List[str]:
        """
        Generate affordances section of init.

        Args:
            affordances_map: Dict mapping artifact_id to affordance instance IDs

        Returns:
            List of PDDL init statements
        """
        lines = []

        lines.append("    ; ====================================================================")
        lines.append("    ; AFFORDANCES")
        lines.append("    ; ====================================================================")

        for artifact_id in sorted(affordances_map.keys()):
            affordances = sorted(affordances_map[artifact_id])
            for affordance_id in affordances:
                lines.append(f"    ({affordance_id} {artifact_id})")

        return lines

    def generate_init_data_properties(self, data_properties: Dict[str, Dict[str, bool]],
                                      types_map: Dict[str, str]) -> List[str]:
        """
        Generate data properties section of init (isOpen, isSwitchedOn, doorIsOpen).

        Args:
            data_properties: Dict mapping object_id to property dict
            types_map: Dict mapping object_id to type (to check for Door type)

        Returns:
            List of PDDL init statements
        """
        lines = []

        lines.append("    ; ====================================================================")
        lines.append("    ; DATA PROPERTIES")
        lines.append("    ; ====================================================================")

        for obj_id in sorted(data_properties.keys()):
            props = data_properties[obj_id]
            obj_type = types_map.get(obj_id, "")

            for prop_name, value in sorted(props.items()):
                # Doors: prefer the dedicated property if present.
                if prop_name == "doorIsOpen":
                    if value:
                        lines.append(f"    (doorIsOpen {obj_id})")
                    else:
                        lines.append(f"    (not (doorIsOpen {obj_id}))")
                elif prop_name == "isOpen" and obj_type == "Door" and "doorIsOpen" not in props:
                    if value:
                        lines.append(f"    (doorIsOpen {obj_id})")
                    else:
                        lines.append(f"    (not (doorIsOpen {obj_id}))")
                elif prop_name == "isOpen":
                    if value:
                        lines.append(f"    (isOpen {obj_id})")
                    else:
                        lines.append(f"    (not (isOpen {obj_id}))")
                elif prop_name == "isSwitchedOn":
                    if value:
                        lines.append(f"    (isSwitchedOn {obj_id})")
                    else:
                        lines.append(f"    (not (isSwitchedOn {obj_id}))")

        return lines

    def generate_init_effects(self, effect_predicates: List[str]) -> List[str]:
        """
        Generate reified effects section of init (LLM common-sense injection).

        Args:
            effect_predicates: List of effect predicate strings

        Returns:
            List of PDDL init statements
        """
        if not effect_predicates:
            return []

        lines = []

        lines.append("    ; ====================================================================")
        lines.append("    ; REIFIED EFFECTS (LLM Common Sense Injection)")
        lines.append("    ; ====================================================================")

        for predicate in effect_predicates:
            lines.append(f"    {predicate}")

        return lines

    def generate_init(
        self,
        topology: Dict[str, Any],
        robot_info: Dict[str, Any],
        artifact_locs: Dict[str, Dict[str, str]],
        affordances_map: Dict[str, List[str]],
        data_properties: Dict[str, Dict[str, bool]],
        types_map: Dict[str, str],
        effect_predicates: List[str] = None
    ) -> str:
        """
        Generate complete init section.

        Args:
            topology: Topology data
            robot_info: Robot data
            artifact_locs: Artifact location data
            affordances_map: Affordances data
            data_properties: Boolean data properties
            types_map: Object types (for Door detection)
            effect_predicates: Reified effect predicates (optional)

        Returns:
            PDDL init section string
        """
        if effect_predicates is None:
            effect_predicates = []

        lines = ["  (:init"]
        lines.append("    (= (total-cost) 0)")
        lines.append("")

        # Add all subsections
        lines.extend(self.generate_init_topology(topology))
        lines.append("")

        lines.extend(self.generate_init_robot(robot_info))
        lines.append("")

        lines.extend(self.generate_init_artifact_locations(artifact_locs))
        lines.append("")

        lines.extend(self.generate_init_affordances(affordances_map))
        lines.append("")

        lines.extend(self.generate_init_data_properties(data_properties, types_map))

        # Add reified effects if any
        if effect_predicates:
            lines.append("")
            lines.extend(self.generate_init_effects(effect_predicates))

        lines.append("  )")

        return "\n".join(lines)

    def generate_goal(self, goal_formula: str) -> str:
        """
        Generate goal section.

        Args:
            goal_formula: PDDL goal formula (user-provided)

        Returns:
            PDDL goal section string
        """
        # Indent goal formula properly
        goal_lines = goal_formula.strip().split('\n')
        indented = ["    " + line.strip() for line in goal_lines]

        return "  (:goal\n" + "\n".join(indented) + "\n  )"

    def write_problem(
        self,
        output_path: str,
        objects: Dict[str, str],
        topology: Dict[str, Any],
        robot_info: Dict[str, Any],
        artifact_locs: Dict[str, Dict[str, str]],
        affordances_map: Dict[str, List[str]],
        goal_formula: str,
        data_properties: Dict[str, Dict[str, bool]] = None,
        effect_predicates: List[str] = None
    ):
        """
        Write complete PDDL problem file.

        Args:
            output_path: Path to output problem.pddl file
            objects: Object types map
            topology: Topology data
            robot_info: Robot data
            artifact_locs: Artifact location data
            affordances_map: Affordances data
            goal_formula: Goal formula string
            data_properties: Boolean data properties (optional)
            effect_predicates: Reified effect predicates (optional)
        """
        if data_properties is None:
            data_properties = {}
        if effect_predicates is None:
            effect_predicates = []

        lines = []

        # Header
        lines.append(";; ====================================================================")
        lines.append(f";; PDDL Problem: {self.problem_name}")
        lines.append(";; Auto-generated from knowledge graph")
        if effect_predicates:
            lines.append(";; Includes LLM-injected common-sense effects")
        lines.append(";; ====================================================================")
        lines.append("")

        # Problem definition
        lines.append(f"(define (problem {self.problem_name})")
        lines.append(f"  (:domain {self.domain_name})")
        lines.append("")

        # Objects
        lines.append(self.generate_objects(objects))
        lines.append("")

        # Init
        lines.append(self.generate_init(topology, robot_info, artifact_locs, affordances_map,
                                       data_properties, objects, effect_predicates))
        lines.append("")

        # Goal
        lines.append(self.generate_goal(goal_formula))
        lines.append("")

        # Metric
        lines.append("  (:metric minimize (total-cost))")
        lines.append(")")

        # Write to file
        output_file = Path(output_path)
        output_file.write_text("\n".join(lines))

        logger.debug("Wrote PDDL problem %s", output_path)
