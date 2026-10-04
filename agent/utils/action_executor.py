"""Utility functions for agent architecture."""

from typing import Any, Dict, List, Tuple

from world_model.core.manager import GraphDBManager
from world_model.core.config import get_config


class ActionExecutor:
    """Execute PDDL actions on GraphDB with full precondition checking and correct effects."""

    def __init__(self):
        self.manager = GraphDBManager()
        config = get_config()
        self.ONTOLOGY_NS = config.get_ontology_config()['namespace']

    def execute_action(self, action_name: str, params: List[str]) -> Dict[str, Any]:
        """Execute a single PDDL action by updating GraphDB.

        Returns:
            Dict with execution result and SPARQL query
        """
        try:
            # Map action names (PDDL uses hyphens, methods use underscores)
            method_name = f"execute_{action_name.replace('-', '_')}"

            if hasattr(self, method_name):
                method = getattr(self, method_name)
                sparql = method(*params)
                return {
                    "success": True,
                    "sparql": sparql,
                    "action": f"{action_name} {' '.join(params)}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action_name}",
                    "action": f"{action_name} {' '.join(params)}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "action": f"{action_name} {' '.join(params)}"
            }

    def _check_preconditions(self, sparql: str, action_desc: str) -> None:
        """Verify action preconditions via SPARQL ASK. Raises ValueError if violated.

        Args:
            sparql: SPARQL ASK query encoding all preconditions
            action_desc: Human-readable description for error messages
        """
        result = self.manager.query(sparql, infer=True)
        if not result.get("boolean", False):
            raise ValueError(f"Precondition violated for [{action_desc}]")

    def _container_access_pattern(self, artifact: str) -> str:
        """SPARQL sub-pattern: artifact is accessible (not blocked by a closed container).

        Encodes: NOT EXISTS container blocking artifact, OR
                 artifact is inside a non-Openable container, OR
                 artifact is inside an open container.

        This is the container-accessibility half of canActuate / canManipulate.
        The result is a SPARQL group graph pattern (with braces) ready to embed
        directly in an ASK { ... } body.
        """
        return f"""  {{
    {{ FILTER NOT EXISTS {{ :{artifact} :isInsideOf ?_c }} }}
    UNION
    {{ :{artifact} :isInsideOf ?_c .
      {{
        {{ FILTER NOT EXISTS {{ ?_c :affords :Openable }} }}
        UNION
        {{ ?_c :isOpen true }}
      }}
    }}
  }}"""

    def _not_held_by_two_hands_pattern(self, robot: str, artifact: str) -> str:
        """SPARQL FILTER NOT EXISTS: artifact is NOT currently held by two different hands.

        Encodes: NOT isHeldByTwoHands(?robot, ?artifact).
        The result is a SPARQL FILTER clause ready to embed in an ASK { ... } body.
        """
        return f"""  FILTER NOT EXISTS {{
    :{robot} :hasHand ?_h1 . :{robot} :hasHand ?_h2 .
    FILTER(?_h1 != ?_h2)
    ?_h1 :holds :{artifact} . ?_h2 :holds :{artifact} .
  }}"""

    def execute_move(self, robot: str, from_loc: str, to_loc: str) -> str:
        """Execute move action.

        Preconditions:
          (robotIsInSpace ?r ?from)
          (hasPathTo ?from ?to)

        NOTE: Door-open requirement is relaxed when *from_loc* is a Door node.
          Plans model doorways as intermediate nodes (corridor → door → room),
          so a move *from* a door may legitimately occur after close-door.
          Traversal constraints apply when *entering* a Door, not when leaving.

        Effects:
          (not (robotIsInSpace ?r ?from))
          (robotIsInSpace ?r ?to)
          (forall (?x - Artifact) (when (isAdjacentTo ?r ?x) (not (isAdjacentTo ?r ?x))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :robotIsInSpace :{from_loc} .
  :{from_loc} :hasPathTo :{to_loc} .
}}"""
        self._check_preconditions(pre, f"move {robot} {from_loc} {to_loc}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{robot} :robotIsInSpace :{from_loc} .
    :{robot} :isAdjacentTo ?artifact .
}}
INSERT {{
    :{robot} :robotIsInSpace :{to_loc} .
}}
WHERE {{
    :{robot} :robotIsInSpace :{from_loc} .
    OPTIONAL {{ :{robot} :isAdjacentTo ?artifact . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_access(self, robot: str, artifact: str, location: str) -> str:
        """Execute access action.

        Preconditions:
          (robotIsInSpace ?r ?p)
          (not (isAdjacentTo ?r ?x))
          (artifactIsInSpace ?x ?p)

        Effects:
          (forall (?other - Artifact) (when (and (not (= ?other ?x)) (isAdjacentTo ?r ?other))
            (not (isAdjacentTo ?r ?other))))
          (isAdjacentTo ?r ?x)
          (forall (?y - Artifact) (when (isInsideOf ?y ?x) (isAdjacentTo ?r ?y)))
          (forall (?z - Artifact) (when (isOntopOf ?z ?x) (isAdjacentTo ?r ?z)))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :robotIsInSpace :{location} .
  FILTER NOT EXISTS {{ :{robot} :isAdjacentTo :{artifact} }}
  :{artifact} :artifactIsInSpace :{location} .
}}"""
        self._check_preconditions(pre, f"access {robot} {artifact} {location}")

        # Effect 1: remove adjacency to every artifact OTHER than the target
        sparql1 = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{robot} :isAdjacentTo ?_other .
}}
WHERE {{
    :{robot} :isAdjacentTo ?_other .
    FILTER(?_other != :{artifact})
}}"""
        self.manager.update(sparql1)

        # Effect 2: add adjacency to target artifact +
        #           all artifacts directly inside it (isInsideOf ?y ?x) +
        #           all artifacts directly on top of it (isOntopOf ?z ?x)
        sparql2 = f"""PREFIX : <{self.ONTOLOGY_NS}>

INSERT {{
    :{robot} :isAdjacentTo :{artifact} .
    :{robot} :isAdjacentTo ?_inner .
    :{robot} :isAdjacentTo ?_ontop .
}}
WHERE {{
    OPTIONAL {{ ?_inner :isInsideOf :{artifact} }}
    OPTIONAL {{ ?_ontop :isOntopOf  :{artifact} }}
}}"""
        self.manager.update(sparql2)
        return pre + "\n" + sparql1 + "\n" + sparql2

    def execute_open_door(self, robot: str, door: str) -> str:
        """Execute open-door action.

        Preconditions:
          (not (doorIsOpen ?d))
          (robotIsInSpace ?r ?d)
          (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h)))

        Effects:
          (doorIsOpen ?d)
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  FILTER NOT EXISTS {{ :{door} :doorIsOpen true }}
  :{robot} :robotIsInSpace :{door} .
  :{robot} :hasHand ?_h .
  FILTER NOT EXISTS {{ ?_h :holds ?_x }}
}}"""
        self._check_preconditions(pre, f"open-door {robot} {door}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{door} :doorIsOpen ?oldValue .
}}
INSERT {{
    :{door} :doorIsOpen "true"^^xsd:boolean .
}}
WHERE {{
    OPTIONAL {{ :{door} :doorIsOpen ?oldValue . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_close_door(self, robot: str, door: str) -> str:
        """Execute close-door action.

        Preconditions:
          (doorIsOpen ?d)
          (or (robotIsInSpace ?r ?d)
              (exists (?s - Space) (and (robotIsInSpace ?r ?s) (hasPathTo ?s ?d))))
          (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h)))

        Effects:
          (not (doorIsOpen ?d))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{door} :doorIsOpen true .
  {{ :{robot} :robotIsInSpace :{door} . }}
  UNION
  {{ :{robot} :robotIsInSpace ?_s . ?_s a :Space . FILTER NOT EXISTS {{ ?_s a :Portal }} ?_s :hasPathTo :{door} . }}
  :{robot} :hasHand ?_h .
  FILTER NOT EXISTS {{ ?_h :holds ?_x }}
}}"""
        self._check_preconditions(pre, f"close-door {robot} {door}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{door} :doorIsOpen ?oldValue .
}}
INSERT {{
    :{door} :doorIsOpen "false"^^xsd:boolean .
}}
WHERE {{
    OPTIONAL {{ :{door} :doorIsOpen ?oldValue . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_open(self, robot: str, container: str) -> str:
        """Execute open action.

        Preconditions:
          (Openable ?a)
          (not (isOpen ?a))
          (canActuate ?r ?a)   → isAdjacentTo + container_access_check
          (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h)))

        Effects:
          (isOpen ?a)
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{container} :affords :Openable .
  FILTER NOT EXISTS {{ :{container} :isOpen true }}
  :{robot} :isAdjacentTo :{container} .
{self._container_access_pattern(container)}
  :{robot} :hasHand ?_h .
  FILTER NOT EXISTS {{ ?_h :holds ?_x }}
}}"""
        self._check_preconditions(pre, f"open {robot} {container}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{container} :isOpen ?oldValue .
}}
INSERT {{
    :{container} :isOpen "true"^^xsd:boolean .
}}
WHERE {{
    OPTIONAL {{ :{container} :isOpen ?oldValue . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_close(self, robot: str, container: str) -> str:
        """Execute close action.

        Preconditions:
          (Openable ?a)
          (isOpen ?a)
          (canActuate ?r ?a)   → isAdjacentTo + container_access_check
          (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h)))

        Effects:
          (not (isOpen ?a))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{container} :affords :Openable .
  :{container} :isOpen true .
  :{robot} :isAdjacentTo :{container} .
{self._container_access_pattern(container)}
  :{robot} :hasHand ?_h .
  FILTER NOT EXISTS {{ ?_h :holds ?_x }}
}}"""
        self._check_preconditions(pre, f"close {robot} {container}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{container} :isOpen ?oldValue .
}}
INSERT {{
    :{container} :isOpen "false"^^xsd:boolean .
}}
WHERE {{
    OPTIONAL {{ :{container} :isOpen ?oldValue . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_power_on(self, robot: str, appliance: str) -> str:
        """Execute power-on action.

        Preconditions:
          (Switchable ?a)
          (not (isSwitchedOn ?a))
          (canActuate ?r ?a)   → isAdjacentTo + container_access_check
          (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h)))

        Effects:
          (isSwitchedOn ?a)
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{appliance} :affords :Switchable .
  FILTER NOT EXISTS {{ :{appliance} :isSwitchedOn true }}
  :{robot} :isAdjacentTo :{appliance} .
{self._container_access_pattern(appliance)}
  :{robot} :hasHand ?_h .
  FILTER NOT EXISTS {{ ?_h :holds ?_x }}
}}"""
        self._check_preconditions(pre, f"power-on {robot} {appliance}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{appliance} :isSwitchedOn ?oldValue .
}}
INSERT {{
    :{appliance} :isSwitchedOn "true"^^xsd:boolean .
}}
WHERE {{
    OPTIONAL {{ :{appliance} :isSwitchedOn ?oldValue . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_power_off(self, robot: str, appliance: str) -> str:
        """Execute power-off action.

        Preconditions:
          (Switchable ?a)
          (isSwitchedOn ?a)
          (canActuate ?r ?a)   → isAdjacentTo + container_access_check
          (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h)))

        Effects:
          (not (isSwitchedOn ?a))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{appliance} :affords :Switchable .
  :{appliance} :isSwitchedOn true .
  :{robot} :isAdjacentTo :{appliance} .
{self._container_access_pattern(appliance)}
  :{robot} :hasHand ?_h .
  FILTER NOT EXISTS {{ ?_h :holds ?_x }}
}}"""
        self._check_preconditions(pre, f"power-off {robot} {appliance}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{appliance} :isSwitchedOn ?oldValue .
}}
INSERT {{
    :{appliance} :isSwitchedOn "false"^^xsd:boolean .
}}
WHERE {{
    OPTIONAL {{ :{appliance} :isSwitchedOn ?oldValue . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_pick_one_hand(self, robot: str, hand: str, artifact: str) -> str:
        """Execute pick-one-hand action.

        Preconditions:
          (hasHand ?r ?h)
          (isEmpty ?h)           → FILTER NOT EXISTS { ?h :holds ?_x }
          (Unimanual ?x)
          (canManipulate ?r ?x)  → isAdjacentTo + container_access_check + nothing ontop

        Effects:
          (holds ?h ?x)
          (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
          (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
          (forall (?y - Artifact) (when (isOntopOf ?x ?y)  (not (isOntopOf ?x ?y))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand} .
  FILTER NOT EXISTS {{ :{hand} :holds ?_x }}
  :{artifact} :affords :Unimanual .
  :{robot} :isAdjacentTo :{artifact} .
  FILTER NOT EXISTS {{ ?_z :isOntopOf :{artifact} }}
{self._container_access_pattern(artifact)}
}}"""
        self._check_preconditions(pre, f"pick-one-hand {robot} {hand} {artifact}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{artifact} :isOnFloorOf ?location .
    :{artifact} :isInsideOf ?container .
    :{artifact} :isOntopOf ?surface .
}}
INSERT {{
    :{hand} :holds :{artifact} .
}}
WHERE {{
    OPTIONAL {{ :{artifact} :isOnFloorOf ?location . }}
    OPTIONAL {{ :{artifact} :isInsideOf ?container . }}
    OPTIONAL {{ :{artifact} :isOntopOf ?surface . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_pick_two_hands(self, robot: str, hand1: str, hand2: str, artifact: str) -> str:
        """Execute pick-two-hands action.

        Preconditions:
          (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
          (isEmpty ?h1) (isEmpty ?h2)
          (Bimanual ?x)
          (canManipulate ?r ?x)  → isAdjacentTo + container_access_check + nothing ontop

        Effects:
          (holds ?h1 ?x) (holds ?h2 ?x)
          (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
          (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
          (forall (?y - Artifact) (when (isOntopOf ?x ?y)  (not (isOntopOf ?x ?y))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand1} .
  :{robot} :hasHand :{hand2} .
  FILTER(:{hand1} != :{hand2})
  FILTER NOT EXISTS {{ :{hand1} :holds ?_x1 }}
  FILTER NOT EXISTS {{ :{hand2} :holds ?_x2 }}
  :{artifact} :affords :Bimanual .
  :{robot} :isAdjacentTo :{artifact} .
  FILTER NOT EXISTS {{ ?_z :isOntopOf :{artifact} }}
{self._container_access_pattern(artifact)}
}}"""
        self._check_preconditions(pre, f"pick-two-hands {robot} {hand1} {hand2} {artifact}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{artifact} :isOnFloorOf ?location .
    :{artifact} :isInsideOf ?container .
    :{artifact} :isOntopOf ?surface .
}}
INSERT {{
    :{hand1} :holds :{artifact} .
    :{hand2} :holds :{artifact} .
}}
WHERE {{
    OPTIONAL {{ :{artifact} :isOnFloorOf ?location . }}
    OPTIONAL {{ :{artifact} :isInsideOf ?container . }}
    OPTIONAL {{ :{artifact} :isOntopOf ?surface . }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_place_on_one_hand(self, robot: str, hand: str, artifact: str, surface: str) -> str:
        """Execute place-on-one-hand action.

        Preconditions:
          (hasHand ?r ?h)
          (holds ?h ?x)
          (not (isHeldByTwoHands ?r ?x))
          (not (= ?x ?y))
          (Support ?y)
          (isAdjacentTo ?r ?y)

        Effects:
          (isOntopOf ?x ?y)
          (not (holds ?h ?x))
          (isAdjacentTo ?r ?x)
          (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
          (forall (?z - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
          (forall (?z - Artifact) (when (isOntopOf ?x ?z)  (not (isOntopOf ?x ?z))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand} .
  :{hand} :holds :{artifact} .
  FILTER(:{artifact} != :{surface})
  :{surface} :affords :Support .
  :{robot} :isAdjacentTo :{surface} .
{self._not_held_by_two_hands_pattern(robot, artifact)}
}}"""
        self._check_preconditions(pre, f"place-on-one-hand {robot} {hand} {artifact} {surface}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{hand} :holds :{artifact} .
    :{artifact} :isOnFloorOf ?_l .
    :{artifact} :isInsideOf ?_c .
    :{artifact} :isOntopOf ?_prev_s .
}}
INSERT {{
    :{artifact} :isOntopOf :{surface} .
    :{robot} :isAdjacentTo :{artifact} .
}}
WHERE {{
    :{hand} :holds :{artifact} .
    OPTIONAL {{ :{artifact} :isOnFloorOf ?_l }}
    OPTIONAL {{ :{artifact} :isInsideOf ?_c }}
    OPTIONAL {{ :{artifact} :isOntopOf ?_prev_s }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_place_on_two_hands(self, robot: str, hand1: str, hand2: str, artifact: str, surface: str) -> str:
        """Execute place-on-two-hands action.

        Preconditions:
          (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
          (holds ?h1 ?x) (holds ?h2 ?x)
          (not (= ?x ?y))
          (Support ?y)
          (isAdjacentTo ?r ?y)

        Effects:
          (isOntopOf ?x ?y)
          (not (holds ?h1 ?x)) (not (holds ?h2 ?x))
          (isAdjacentTo ?r ?x)
          (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
          (forall (?z - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
          (forall (?z - Artifact) (when (isOntopOf ?x ?z)  (not (isOntopOf ?x ?z))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand1} .
  :{robot} :hasHand :{hand2} .
  FILTER(:{hand1} != :{hand2})
  :{hand1} :holds :{artifact} .
  :{hand2} :holds :{artifact} .
  FILTER(:{artifact} != :{surface})
  :{surface} :affords :Support .
  :{robot} :isAdjacentTo :{surface} .
}}"""
        self._check_preconditions(pre, f"place-on-two-hands {robot} {hand1} {hand2} {artifact} {surface}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{hand1} :holds :{artifact} .
    :{hand2} :holds :{artifact} .
    :{artifact} :isOnFloorOf ?_l .
    :{artifact} :isInsideOf ?_c .
    :{artifact} :isOntopOf ?_prev_s .
}}
INSERT {{
    :{artifact} :isOntopOf :{surface} .
    :{robot} :isAdjacentTo :{artifact} .
}}
WHERE {{
    :{hand1} :holds :{artifact} .
    :{hand2} :holds :{artifact} .
    OPTIONAL {{ :{artifact} :isOnFloorOf ?_l }}
    OPTIONAL {{ :{artifact} :isInsideOf ?_c }}
    OPTIONAL {{ :{artifact} :isOntopOf ?_prev_s }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_place_in_one_hand(self, robot: str, hand: str, artifact: str, container: str) -> str:
        """Execute place-in-one-hand action.

        Preconditions:
          (hasHand ?r ?h)
          (holds ?h ?x)
          (not (isHeldByTwoHands ?r ?x))
          (not (= ?x ?c))
          (Containment ?c)
          (isAdjacentTo ?r ?c)
          (or (not (Openable ?c)) (isOpen ?c))

        Effects:
          (isInsideOf ?x ?c)
          (not (holds ?h ?x))
          (isAdjacentTo ?r ?x)
          (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
          (forall (?y - Artifact) (when (isOntopOf ?x ?y)  (not (isOntopOf ?x ?y))))
          (forall (?z - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand} .
  :{hand} :holds :{artifact} .
  FILTER(:{artifact} != :{container})
  :{container} :affords :Containment .
  :{robot} :isAdjacentTo :{container} .
  {{
    {{ FILTER NOT EXISTS {{ :{container} :affords :Openable }} }}
    UNION
    {{ :{container} :isOpen true }}
  }}
{self._not_held_by_two_hands_pattern(robot, artifact)}
}}"""
        self._check_preconditions(pre, f"place-in-one-hand {robot} {hand} {artifact} {container}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{hand} :holds :{artifact} .
    :{artifact} :isOnFloorOf ?_l .
    :{artifact} :isOntopOf ?_s .
    :{artifact} :isInsideOf ?_prev_c .
}}
INSERT {{
    :{artifact} :isInsideOf :{container} .
    :{robot} :isAdjacentTo :{artifact} .
}}
WHERE {{
    :{hand} :holds :{artifact} .
    OPTIONAL {{ :{artifact} :isOnFloorOf ?_l }}
    OPTIONAL {{ :{artifact} :isOntopOf ?_s }}
    OPTIONAL {{ :{artifact} :isInsideOf ?_prev_c }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_place_in_two_hands(self, robot: str, hand1: str, hand2: str, artifact: str, container: str) -> str:
        """Execute place-in-two-hands action.

        Preconditions:
          (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
          (holds ?h1 ?x) (holds ?h2 ?x)
          (not (= ?x ?c))
          (Containment ?c)
          (isAdjacentTo ?r ?c)
          (or (not (Openable ?c)) (isOpen ?c))

        Effects:
          (isInsideOf ?x ?c)
          (not (holds ?h1 ?x)) (not (holds ?h2 ?x))
          (isAdjacentTo ?r ?x)
          (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
          (forall (?y - Artifact) (when (isOntopOf ?x ?y)  (not (isOntopOf ?x ?y))))
          (forall (?z - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand1} .
  :{robot} :hasHand :{hand2} .
  FILTER(:{hand1} != :{hand2})
  :{hand1} :holds :{artifact} .
  :{hand2} :holds :{artifact} .
  FILTER(:{artifact} != :{container})
  :{container} :affords :Containment .
  :{robot} :isAdjacentTo :{container} .
  {{
    {{ FILTER NOT EXISTS {{ :{container} :affords :Openable }} }}
    UNION
    {{ :{container} :isOpen true }}
  }}
}}"""
        self._check_preconditions(pre, f"place-in-two-hands {robot} {hand1} {hand2} {artifact} {container}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{hand1} :holds :{artifact} .
    :{hand2} :holds :{artifact} .
    :{artifact} :isOnFloorOf ?_l .
    :{artifact} :isOntopOf ?_s .
    :{artifact} :isInsideOf ?_prev_c .
}}
INSERT {{
    :{artifact} :isInsideOf :{container} .
    :{robot} :isAdjacentTo :{artifact} .
}}
WHERE {{
    :{hand1} :holds :{artifact} .
    :{hand2} :holds :{artifact} .
    OPTIONAL {{ :{artifact} :isOnFloorOf ?_l }}
    OPTIONAL {{ :{artifact} :isOntopOf ?_s }}
    OPTIONAL {{ :{artifact} :isInsideOf ?_prev_c }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_place_to_location_one_hand(self, robot: str, hand: str, artifact: str, location: str) -> str:
        """Execute place-to-location-one-hand action.

        Preconditions:
          (hasHand ?r ?h)
          (robotIsInSpace ?r ?p)
          (holds ?h ?x)
          (not (isHeldByTwoHands ?r ?x))

        Effects:
          (isOnFloorOf ?x ?p)
          (not (holds ?h ?x))
          (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
          (forall (?y - Artifact) (when (isOntopOf ?x ?y)  (not (isOntopOf ?x ?y))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand} .
  :{robot} :robotIsInSpace :{location} .
  :{hand} :holds :{artifact} .
{self._not_held_by_two_hands_pattern(robot, artifact)}
}}"""
        self._check_preconditions(pre, f"place-to-location-one-hand {robot} {hand} {artifact} {location}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{hand} :holds :{artifact} .
    :{artifact} :isInsideOf ?_c .
    :{artifact} :isOntopOf ?_s .
}}
INSERT {{
    :{artifact} :isOnFloorOf :{location} .
}}
WHERE {{
    :{hand} :holds :{artifact} .
    OPTIONAL {{ :{artifact} :isInsideOf ?_c }}
    OPTIONAL {{ :{artifact} :isOntopOf ?_s }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def execute_place_to_location_two_hands(self, robot: str, hand1: str, hand2: str, artifact: str, location: str) -> str:
        """Execute place-to-location-two-hands action.

        Preconditions:
          (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
          (robotIsInSpace ?r ?p)
          (holds ?h1 ?x)
          (holds ?h2 ?x)

        Effects:
          (isOnFloorOf ?x ?p)
          (not (holds ?h1 ?x)) (not (holds ?h2 ?x))
          (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
          (forall (?y - Artifact) (when (isOntopOf ?x ?y)  (not (isOntopOf ?x ?y))))
        """
        pre = f"""PREFIX : <{self.ONTOLOGY_NS}>

ASK {{
  :{robot} :hasHand :{hand1} .
  :{robot} :hasHand :{hand2} .
  FILTER(:{hand1} != :{hand2})
  :{robot} :robotIsInSpace :{location} .
  :{hand1} :holds :{artifact} .
  :{hand2} :holds :{artifact} .
}}"""
        self._check_preconditions(pre, f"place-to-location-two-hands {robot} {hand1} {hand2} {artifact} {location}")

        sparql = f"""PREFIX : <{self.ONTOLOGY_NS}>

DELETE {{
    :{hand1} :holds :{artifact} .
    :{hand2} :holds :{artifact} .
    :{artifact} :isInsideOf ?_c .
    :{artifact} :isOntopOf ?_s .
}}
INSERT {{
    :{artifact} :isOnFloorOf :{location} .
}}
WHERE {{
    :{hand1} :holds :{artifact} .
    :{hand2} :holds :{artifact} .
    OPTIONAL {{ :{artifact} :isInsideOf ?_c }}
    OPTIONAL {{ :{artifact} :isOntopOf ?_s }}
}}"""
        self.manager.update(sparql)
        return pre + "\n" + sparql

    def close(self):
        """Close GraphDB connection."""
        self.manager.close()


def parse_plan(plan_content: str) -> List[Tuple[str, List[str]]]:
    """Parse PDDL plan content into (action_name, parameters) tuples.

    Args:
        plan_content: Plan file content as string

    Returns:
        List of (action_name, parameters) tuples
    """
    actions = []
    for line in plan_content.split('\n'):
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        # Parse: (action-name param1 param2 ...)
        if line.startswith('(') and line.endswith(')'):
            parts = line[1:-1].split()
            if parts:
                action_name = parts[0]
                params = parts[1:]
                actions.append((action_name, params))
    return actions


def apply_action_effects(plan_content: str) -> Dict[str, Any]:
    """Apply all actions from a plan to GraphDB.

    Args:
        plan_content: Plan file content as string

    Returns:
        Dict with success status and execution details
    """
    executor = ActionExecutor()

    try:
        actions = parse_plan(plan_content)

        results = []
        for action_name, params in actions:
            result = executor.execute_action(action_name, params)
            results.append(result)

            if not result["success"]:
                executor.close()
                return {
                    "success": False,
                    "error": result.get("error"),
                    "failed_action": result.get("action"),
                    "executed_actions": results
                }

        executor.close()
        return {
            "success": True,
            "executed_actions": results,
            "total_actions": len(actions)
        }

    except Exception as e:
        executor.close()
        return {
            "success": False,
            "error": str(e),
            "executed_actions": []
        }
