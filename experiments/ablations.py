"""Ablation variants of OntoPlan (paper, Sec. 5.4).

- w/o Scene query: the Scene Explorer receives the full serialized scene (world.json) in its
  prompt and names the relevant objects in one LLM call, instead of querying the world model.
- w/o PDDL plan: the Planning Manager receives the PDDL domain, the navigation graph plus the
  discovered objects, and the Task Formalizer's conditions, and the LLM writes the action sequence
  directly (no Fast Downward, no state simulation, no replanning).

All other agents, prompts, and settings are those of the full system.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from agent.config import Configuration, chat_model
from agent.graph import build_workflow
from agent.state import AgentNames, OverallState
from world_model.core.config import get_config

VARIANTS = ("full", "no_scene_query", "no_pddl_plan")


def load_world_json(env_id: str, env_size: str) -> Dict[str, Any]:
    return json.loads((get_config().get_env_dir(env_id, env_size) / "world.json").read_text())


def _latest_reason(state: OverallState) -> str:
    for report in reversed(state.get("agent_reports", [])):
        if isinstance(report, dict) and report.get("agent") == AgentNames.FLOW_ORCHESTRATOR and report.get("reason"):
            return str(report["reason"]).strip()
    return ""


def _user_request(dialogue: List[Dict[str, str]]) -> str:
    out = ""
    if dialogue:
        out = "\n\n**User Request:**\n\n"
        for entry in dialogue:
            role = "User" if entry["role"] == "user" else "Assistant"
            out += f"**{role}**: {entry['content']}\n"
    return out


# ── w/o Scene query ──────────────────────────────────────────────────────────

def scene_explorer_no_tools_prompt(scene_graph_text: str, dialogue: List[Dict[str, str]], reason: str = "") -> str:
    directive = "\n\n**Flow Orchestrator Directive:**\n\n" + reason + "\n" if reason else ""
    return f"""You are the Scene Explorer. Your job is to identify all objects relevant to the user's task from the scene graph below.

## CONTEXT
{_user_request(dialogue)}{directive}
## SCENE GRAPH

The scene graph is the full world.json in JSON format.
- `"locations"`: every space, door, stairs, and opening with their neighbors and items.
- `"robot"`: the robot's current position (`robotIsInSpace`) and hand state.

{scene_graph_text}

## YOUR TASK

Read the scene graph above and identify every object, space, and connection relevant to the user's task.

Then write your exploration summary in the following format EXACTLY:

Task: <one-line restatement of what the user wants to do>
Found:
  - <role in task>: `obj_id` (category) in `space_id`
  - <role in task>: `space_id` connected via `door_id`
  ...
Not found: <anything the task required but not present in the scene graph — state explicitly>
Notes: <ambiguity resolutions, e.g. "chose `bedroom_7` over `bedroom_8` as it matched the user's description">

Rules:
- Every entity you mention MUST be wrapped in backticks using the exact ID from the scene graph (e.g., `cup_8`, `kitchen_20`, `door_5`).
- Do NOT invent IDs. Only use IDs that appear in the scene graph above.
- If multiple candidates exist for a role (e.g., 3 mugs), list ALL of them with their IDs and locations.
- If a required object is not in the scene graph, state it explicitly under "Not found".

Write your exploration summary now.
"""


def _world_lookup(world: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """id -> compact object info, used to verify the IDs named by the LLM."""
    lookup: Dict[str, Dict[str, Any]] = {}
    for loc_id, loc in world.get("locations", {}).items():
        storey = loc.get("storey", "")
        lookup[loc_id] = {"id": loc_id, "category": loc_id.rsplit("_", 1)[0], "type": loc.get("type", "space"),
                          "isInStorey": storey}
        for item_id, item in (loc.get("items") or {}).items():
            obj = {"id": item_id, "category": item_id.rsplit("_", 1)[0], "isInSpace": loc_id,
                   "isInStorey": storey, "affordance": item.get("affordance", [])}
            obj.update({k: item[k] for k in ("isOpen", "isSwitchedOn") if k in item})
            lookup[item_id] = obj
    return lookup


def scene_explorer_no_tools(state: OverallState, config: RunnableConfig) -> dict:
    cfg = Configuration.from_runnable_config(config)
    world = load_world_json(state["env_id"], state["env_size"])
    dialogue = state.get("dialogue_history", [])[state.get("episode_start", 0):]
    prompt = scene_explorer_no_tools_prompt(json.dumps(world, indent=2), dialogue, _latest_reason(state))
    llm = chat_model(cfg.scene_explorer_model, cfg.scene_explorer_temperature)
    summary = (llm.invoke([SystemMessage(content=prompt)]).content or "").strip()
    lookup = _world_lookup(world)
    ids = list(dict.fromkeys(re.findall(r"`([^`\s]+)`", summary)))
    return {
        "next_agent": AgentNames.FLOW_ORCHESTRATOR,
        "agent_reports": [{"agent": AgentNames.SCENE_EXPLORER, "exploration_result": summary}],
        "discovered_objects": [lookup[i] for i in ids if i in lookup],
    }


# ── w/o PDDL plan ────────────────────────────────────────────────────────────

DOMAIN_PATH = Path(__file__).resolve().parents[1] / "pddl" / "domain.pddl"


def planning_manager_no_pddl_prompt(scene_graph_text: str, dialogue: List[Dict[str, str]], at_end_condition: str,
                                    sometime_conditions: List[Dict[str, str]],
                                    always_conditions: List[Dict[str, str]]) -> str:
    last_user = next((e["content"] for e in reversed(dialogue) if e["role"] == "user"), "")
    task = f"\n**User task**: {last_user}\n" if last_user else ""
    conditions = f"\n**At-End Condition** (must be true when task is complete):\n  {at_end_condition}\n"
    if always_conditions:
        conditions += "\n**Always Conditions** (must hold throughout execution):\n"
        conditions += "".join(f"  - {a.get('predicate_formula', '')}: {a.get('description', '')}\n" for a in always_conditions)
    if sometime_conditions:
        conditions += "\n**Sometime Conditions** (intermediate states that must occur):\n"
        conditions += "".join(f"  - {s.get('predicate_formula', '')}: {s.get('description', '')}\n" for s in sometime_conditions)
    return f"""You are a robot task planner. Given the scene graph and task conditions below, generate a complete sequence of robot actions to accomplish the task.

## TASK
{task}
## GOAL CONDITIONS
{conditions}
## SCENE GRAPH

The scene graph shows the navigation structure and the objects discovered by the Scene Explorer.
- `"locations"`: every space, door, stairs, and opening with their connections. Each space's `"items"` lists only the objects that were discovered — undiscovered objects are not shown.
- `"robot"`: the robot's current position (`robotIsInSpace`) and hand state.

{scene_graph_text}

## PDDL DOMAIN

The robot's actions are defined by the PDDL domain below, the same domain used by the PDDL planner.
Use its action names and parameter order exactly. Robot constants: robot, left_hand, right_hand.

```pddl
{DOMAIN_PATH.read_text().strip()}
```

## INSTRUCTIONS

Generate a complete, executable sequence of PDDL actions that:
1. Satisfies all Sometime Conditions (in order — complete each intermediate state before moving to the next)
2. Achieves the At-End Condition as the final state
3. Respects all Always Conditions throughout

Planning guidelines:
- The robot starts at the location given in the scene graph under `"robot" → "robotIsInSpace"`.
- Navigation uses portal nodes (door_X, opening_X, stairs_X) as intermediate stops. Each `move` action moves the robot one hop: from a space to an adjacent portal, or from a portal to an adjacent space. Check the `"neighbor"` list of each location to find valid one-hop moves.
- To pass through a door (type "door"): `move` to the door node → `open-door` (if closed) → `move` to the destination space.
- To pass through an opening or stairs (type "opening"/"stairs"): `move` to the portal node → `move` to the destination space. No open-door needed.
- To pick up an item: navigate to its space → access it → pick it up.
- To open a container: navigate to its space → access it → open it.
- If placing inside an appliance (oven, microwave, dishwasher): open it first, place item inside, close it, power it on.
- If placing on a support: navigate to its space → access the support → place item on it.
- Use `right_hand` or `left_hand` for hand arguments; use both for bimanual items.

## OUTPUT FORMAT

Output ONLY the action sequence, one action per line, in this exact format:
(action-name arg1 arg2 ...)

**Example 1: Pick item from refrigerator and place on table**
(move robot living_room_5 door_3)
(open-door robot door_3)
(move robot door_3 kitchen_20)
(access robot refrigerator_15 kitchen_20)
(open robot refrigerator_15)
(pick-one-hand robot right_hand milk_8)
(close robot refrigerator_15)
(access robot island_table_2 kitchen_20)
(place-on-one-hand robot right_hand milk_8 island_table_2)

**Example 2: Cook item in appliance, then retrieve it — CRITICAL: after using an appliance, you must move away and return before accessing it again**
(access robot oven_5 kitchen_20)
(open robot oven_5)
(place-in-one-hand robot right_hand chicken_3 oven_5)
(close robot oven_5)
(power-on robot oven_5)
(move robot kitchen_20 opening_4)
(move robot opening_4 kitchen_20)
(access robot oven_5 kitchen_20)
(open robot oven_5)
(pick-one-hand robot right_hand chicken_3)
(close robot oven_5)
(access robot island_table_8 kitchen_20)
(place-on-one-hand robot right_hand chicken_3 island_table_8)

Do NOT include any explanation, comments, or non-action lines. Output only the action sequence.
"""


def _filtered_scene(world: Dict[str, Any], discovered: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Full navigation graph, but each space lists only the discovered objects
    (the same information scope as the PDDL plan tool)."""
    ids = {o.get("id") for o in discovered if isinstance(o, dict)}
    locations = {}
    for loc_id, loc in world.get("locations", {}).items():
        if loc.get("type") in ("door", "opening", "stairs"):
            locations[loc_id] = loc
        else:
            locations[loc_id] = {**loc, "items": {k: v for k, v in (loc.get("items") or {}).items() if k in ids}}
    return {"name": world.get("name", ""), "locations": locations, "robot": world.get("robot", {})}


def planning_manager_no_pddl(state: OverallState, config: RunnableConfig) -> dict:
    cfg = Configuration.from_runnable_config(config)
    world = load_world_json(state["env_id"], state["env_size"])
    scene = _filtered_scene(world, state.get("discovered_objects", []))
    dialogue = state.get("dialogue_history", [])[state.get("episode_start", 0):]
    prompt = planning_manager_no_pddl_prompt(
        json.dumps(scene, indent=2), dialogue, state.get("at_end_condition", ""),
        state.get("sometime_conditions", []), state.get("always_conditions", []))
    llm = chat_model(cfg.planning_manager_model, cfg.planning_manager_temperature)
    raw = (llm.invoke([SystemMessage(content=prompt)]).content or "").strip()
    actions = [l.strip() for l in raw.splitlines()
               if l.strip().startswith("(") and l.strip().endswith(")") and not l.strip().startswith(";")]
    return {
        "subgoal_results": [{
            "subgoal_index": 0, "goal_state": state.get("at_end_condition", ""),
            "description": "Direct LLM plan (no PDDL planner)",
            "status": "success" if actions else "failed",
            "plan": "\n".join(actions) if actions else None,
            "error_log": None if actions else "LLM produced no valid PDDL actions",
            "plan_metrics": {"plan_length": len(actions)},
        }],
        "next_agent": AgentNames.ROBOT,
        "agent_reports": [{"agent": AgentNames.PLANNING_MANAGER, "next_agent": AgentNames.ROBOT,
                           "reason": f"Direct plan: {len(actions)} actions generated"}],
    }


def build_variant(variant: str):
    """Uncompiled workflow for 'full', 'no_scene_query', or 'no_pddl_plan'."""
    if variant == "full":
        return build_workflow()
    if variant == "no_scene_query":
        return build_workflow(scene_explorer_node=scene_explorer_no_tools)
    if variant == "no_pddl_plan":
        return build_workflow(planning_manager_node=planning_manager_no_pddl)
    raise ValueError(f"Unknown variant {variant!r}; choose from {VARIANTS}")
