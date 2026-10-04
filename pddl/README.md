# PDDL planning

`domain.pddl` defines the robot's 16 primitive actions over the same vocabulary as the ontology: types match ontology classes (`Space`, `Door`, `Stairs`, `Opening`, `Robot`, `Hand`, `Artifact`) and predicates match ontology properties with the same names.

```text
domain.pddl             PDDL domain
scripts/pddl_parser.py  reads the type hierarchy from the domain
scripts/pddl_generator.py  extracts task-relevant objects, topology, and state from GraphDB
scripts/pddl_writer.py  writes problem.pddl
scripts/pddl_goal_utils.py  object extraction from goal formulas
fast-downward/          Fast Downward (git submodule)
```

## How the PDDL plan tool uses it

`agent/tools/pddl_plan.py` receives ordered subgoals and, for each one:

1. restores the current world state (initial state or the last checkpoint),
2. builds a problem from the discovered objects, their location chains, the topology around them, and the robot's state,
3. compiles `always` conditions into the domain as a `constraint-violated` flag that every action sets when a condition becomes false,
4. runs Fast Downward (`lazy_wastar`, FF heuristic, weight 2, 60 s per subgoal),
5. applies the plan's effects to the world model, so the next subgoal starts from the result.

Working files are written to `pddl/workspace/` and overwritten on every call.

## Goal predicates

```lisp
(isOnFloorOf <artifact> <space>)      ; on the floor of a space
(isInsideOf <artifact> <artifact>)    ; inside a container
(isOntopOf <artifact> <artifact>)     ; on a surface
(artifactIsInSpace <artifact> <space>) ; anywhere in a space (derived)
(holds <hand> <artifact>)
(isSwitchedOn <artifact>)
(isOpen <artifact>)
(doorIsOpen <door>)
(robotIsInSpace robot <location>)
```
