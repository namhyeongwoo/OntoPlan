"""PDDL plan tool: solves ordered subgoals with Fast Downward over the current world state."""

import json
import logging
import re
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils import PDDLConstraintCompiler, apply_action_effects
from pddl.scripts.pddl_generator import PDDLGenerator
from pddl.scripts.pddl_goal_utils import classify_objects_by_domain_type, extract_object_ids_from_goal, split_conjuncts
from pddl.scripts.pddl_parser import PDDLDomainParser
from pddl.scripts.pddl_writer import PDDLWriter
from world_model.core.config import get_config
from world_model.core.manager import GraphDBManager
from agent.environment import restore_world_state, save_checkpoint

logger = logging.getLogger(__name__)

PDDL_DIR = Path(__file__).resolve().parents[2] / "pddl"
PLANNER_TIMEOUT = 60  # seconds per subgoal

# Fast Downward driver exit codes (https://www.fast-downward.org/ExitCodes)
_FD_EXIT_CODES = {
    11: "task proved unsolvable",
    12: "search stopped without finding a solution",
    22: "out of memory",
    23: "search timed out",
    30: "translator critical error",
    31: "translator input error (undefined object/predicate or malformed formula)",
    32: "search input error",
    33: "unsupported feature",
}
_FD_KEY_LINE = re.compile(
    r"undefined|got:|error|unsolvable|no solution|completely explored|search stopped|"
    r"simplified to|trivially|not declared|unknown|mismatch|expected",
    re.IGNORECASE,
)


def _run_planner(cmd: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run Fast Downward; on timeout, kill the whole process group.

    fast-downward.py starts the translator and the search as child processes, so killing
    only the driver would leave the search running (and writing sas_plan) in the background.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=PLANNER_TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _summarize_planner_failure(returncode: int, output: str, always_formulas: Optional[List[str]],
                               robot_location: Optional[str]) -> str:
    """Condense Fast Downward output into the lines that explain the failure."""
    reason = _FD_EXIT_CODES.get(returncode, f"exit code {returncode}")
    key_lines = []
    for line in output.splitlines():
        line = line.strip()
        if line and not line.startswith("INFO") and _FD_KEY_LINE.search(line) and line not in key_lines:
            key_lines.append(line)
    message = f"Planning failed: {reason}."
    if key_lines:
        message += " Planner output: " + " / ".join(key_lines[-6:])
    if always_formulas and returncode in (11, 12):
        message += (
            f" Note: always conditions {always_formulas} must hold from the initial state onward"
            f" (robot currently in {robot_location}); a condition that is already false, or that blocks"
            f" every route, makes the task unsolvable."
        )
    return message


def _get_env_info():
    """Get active environment info with fallbacks."""
    config = get_config()
    env_id = config.get_active_env()
    env_size = config.get_env_size()

    if not env_id:
        raise RuntimeError("No active environment. Start a session with env_id and env_size.")
    return config, env_id, env_size


def build_planner_command(solver: str = "lazy_wastar", heuristic: str = "ff", weight: int = 2) -> str:
    """Build Fast Downward search command."""
    if solver == 'lazy_wastar':
        return f"lazy_wastar([{heuristic}()], w={weight})"
    elif solver == 'astar':
        return f"astar({heuristic}())"
    elif solver == 'lama':
        return "lazy(alt([lama_synergy()], boost=1000), preferred=[lama_synergy()])"
    else:
        return f"lazy_wastar([{heuristic}()], w={weight})"



def _solve_single_goal(
    goal_formula: str,
    task_name: str,
    domain_path: Path,
    problem_dir: Path,
    solution_dir: Path,
    pddl_dir: Path,
    always_conditions: Optional[List[str]] = None,
    discovered_objects: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Solve a single PDDL goal and return the result.

    Args:
        goal_formula: PDDL goal formula
        task_name: Task name for file naming
        domain_path: Path to domain.pddl
        problem_dir: Directory to save problem files
        solution_dir: Directory to save solution files
        pddl_dir: Path to pddl directory (contains fast-downward)
        always_conditions: Optional list of always-condition formulas to compile
        discovered_objects: Optional list of all discovered object IDs (prevents omission)

    Returns:
        Dict with success, plan_content, plan_path, metrics, or error
    """
    try:
        domain_name = "robot"

        # Verify domain exists
        if not domain_path.exists():
            return {
                "success": False,
                "error": f"Domain file not found at {domain_path}"
            }

        # Parse domain
        parser = PDDLDomainParser(domain_path)

        # Connect to GraphDB
        manager = GraphDBManager()

        # Initialize generator
        generator = PDDLGenerator(manager, parser)

        # Use discovered_objects if provided, otherwise extract from goal
        if discovered_objects:
            # Use all discovered objects (prevents omission)
            base_object_ids = discovered_objects
        else:
            # Fallback: extract from goal only
            base_object_ids = extract_object_ids_from_goal(goal_formula, manager)

        # Get object types
        base_types_map = generator.get_types(base_object_ids)

        # Classify by domain type
        artifact_ids, location_ids = classify_objects_by_domain_type(
            base_object_ids, base_types_map, parser
        )

        # Get artifact locations (automatically includes full location chain)
        artifact_locs = generator.get_artifact_locations(artifact_ids)

        # Extract Space IDs from artifact locations
        space_ids = set()
        for loc_info in artifact_locs.values():
            for rel_type, target_id in loc_info.items():
                if rel_type == "isOnFloorOf":  # Target is a Space
                    space_ids.add(target_id)

        # Get robot info
        robot_info = generator.get_robot_info()
        if not robot_info:
            manager.close()
            return {
                "success": False,
                "error": "No robot found in knowledge graph"
            }

        # Add robot's current location
        robot_location = robot_info.get('location')
        if robot_location:
            space_ids.add(robot_location)

        # Convert any goal locations to list
        location_ids = list(set(location_ids) | space_ids)

        # Get topology with expanded locations (single optimized query)
        topology_result = generator.get_topology_with_paths(location_ids)

        # Collect all required objects
        all_object_ids = generator.get_all_required_objects(artifact_locs, topology_result, robot_info)

        # Ensure all necessary objects are included
        all_object_ids_list = list(all_object_ids)

        # Add all base objects (from discovered_objects or goal)
        for obj_id in base_object_ids:
            if obj_id not in all_object_ids_list:
                all_object_ids_list.append(obj_id)

        # Map types (pass as list)
        types_map = generator.get_types(all_object_ids_list)

        # Extract topology for PDDL (connections and distances only)
        topology = {
            "connections": topology_result["connections"],
            "distances": topology_result["distances"]
        }

        # Get affordances for all artifacts in location chain and held artifacts
        all_artifact_ids = list(artifact_locs.keys())
        # Add artifacts that robot is holding
        if robot_info and "holds" in robot_info and robot_info["holds"]:
            for hand_id, artifact_id in robot_info["holds"]:
                if artifact_id not in all_artifact_ids:
                    all_artifact_ids.append(artifact_id)
        affordances_map = generator.get_affordances(all_artifact_ids)
        # Things outside the problem lying on an artifact make it impossible to pick up
        for blocked in generator.get_blocked_artifacts(all_artifact_ids, all_object_ids_list):
            if blocked in affordances_map:
                affordances_map[blocked] = [a for a in affordances_map[blocked] if a not in ("Unimanual", "Bimanual")]

        # Get data properties (isOpen, isSwitchedOn) for all objects
        data_properties = generator.get_data_properties(all_object_ids_list)

        # Write problem file
        problem_path = problem_dir / "problem.pddl"
        writer = PDDLWriter(task_name, domain_name)
        writer.write_problem(
            problem_path,
            types_map,
            topology,
            robot_info,
            artifact_locs,
            affordances_map,
            goal_formula,
            data_properties,
            []  # No reified effects for now
        )

        manager.close()

        # Compile problem if always conditions exist
        # Note: domain is already compiled by caller (_compile_domain_once)
        actual_problem_path = problem_path

        if always_conditions and len(always_conditions) > 0:
            # Compile only the problem file
            # Domain is already compiled and passed via domain_path parameter
            compiled_problem = PDDLConstraintCompiler().compile_problem(
                problem_path.read_text(), always_conditions, domain_path
            )
            compiled_problem_path = problem_dir / "problem_compiled.pddl"
            compiled_problem_path.write_text(compiled_problem)
            actual_problem_path = compiled_problem_path

        # Run Fast Downward
        fd_path = pddl_dir / "fast-downward" / "fast-downward.py"
        if not fd_path.exists():
            return {
                "success": False,
                "error": f"Fast Downward not found at {fd_path}"
            }

        search_cmd = build_planner_command()
        solution_path = solution_dir / "solution.plan"
        sas_plan_path = pddl_dir / "sas_plan"

        # Measure planning time
        planning_start_time = time.time()
        result = _run_planner(
            [
                sys.executable, str(fd_path),
                str(domain_path),  # Already compiled if forbidden states exist
                str(actual_problem_path),
                "--search", search_cmd
            ],
            cwd=pddl_dir,
        )
        planning_time = time.time() - planning_start_time

        # Check result
        if result.returncode == 0:
            # Success - read solution
            if sas_plan_path.exists():
                shutil.copy(sas_plan_path, solution_path)
                sas_plan_path.unlink()

            if solution_path.exists():
                with open(solution_path, 'r') as f:
                    plan_content = f.read()

                # Extract plan metrics
                metrics = {}
                for line in result.stdout.split('\n'):
                    if 'Plan length' in line:
                        match = re.search(r'Plan length: (\d+)', line)
                        if match:
                            metrics['plan_length'] = int(match.group(1))
                    elif 'Plan cost' in line:
                        match = re.search(r'Plan cost: ([\d.]+)', line)
                        if match:
                            metrics['plan_cost'] = float(match.group(1))

                # Add planning time
                metrics['planning_time_seconds'] = round(planning_time, 3)

                return {
                    "success": True,
                    "plan_content": plan_content,
                    "plan_path": str(solution_path),
                    "metrics": metrics
                }
            else:
                return {
                    "success": False,
                    "error": "Planning completed but solution file not found",
                    "planner_output": result.stdout
                }
        else:
            return {
                "success": False,
                "error": _summarize_planner_failure(
                    result.returncode, result.stdout + "\n" + result.stderr, always_conditions, robot_location
                ),
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Planner timed out after {PLANNER_TIMEOUT} seconds"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"{type(e).__name__}: {str(e)}"
        }


def _compile_domain_once(
    domain_path: Path,
    always_formulas: List[str],
    output_dir: Path
) -> Path:
    """Compile domain file once with always-condition constraints.

    Args:
        domain_path: Original domain.pddl path
        always_formulas: List of always-condition formulas
        output_dir: Directory to save compiled domain

    Returns:
        Path to compiled domain (or original if no always conditions)
    """
    if not always_formulas or len(always_formulas) == 0:
        return domain_path

    output_dir.mkdir(parents=True, exist_ok=True)
    compiled_domain_path = output_dir / "domain_compiled.pddl"

    # Check if already compiled
    if compiled_domain_path.exists():
        return compiled_domain_path

    compiled_domain = PDDLConstraintCompiler().compile_domain(domain_path.read_text(), always_formulas, domain_path)

    # Write compiled domain
    with open(compiled_domain_path, 'w') as f:
        f.write(compiled_domain)

    return compiled_domain_path


@tool
def pddl_plan(
    subgoals: List[Dict[str, Any]],
    task_description: str,
    always_conditions: Optional[List[Dict[str, Any]]] = None,
    discovered_objects: Optional[List[str]] = None,
    session_timestamp: str = "",
    results_dir: Optional[str] = None,
    state: Annotated[Optional[dict], InjectedState] = None,
) -> str:
    """Plan with an ordered list of subgoals.

    IMPORTANT (LLM-facing): The LLM must provide **only** the required fields below.
    The system auto-injects the other parameters.

    Required args (LLM must include):
    - subgoals: list of subgoal dicts (length >= 1)
    - task_description: short one-sentence summary

    Auto-injected by the system (LLM should NOT worry about these):
    - always_conditions, discovered_objects, session_timestamp, results_dir

    Subgoal schema (each item in `subgoals`):
    - goal_state: PDDL formula string
    - description: short description
    - name: short snake_case name
    - order: integer starting at 0

    Minimal valid example:
    {"subgoals": [{"goal_state": "(isOnFloorOf mug_1 kitchen_1)", "description": "Move mug", "name": "move_mug", "order": 0}],
     "task_description": "Move the mug to the kitchen."}

    Returns: JSON string (tool output).
    """
    pddl_dir = PDDL_DIR
    domain_path = pddl_dir / "domain.pddl"

    _, env_id, env_size = _get_env_info()
    # Every call starts from the state left by the last approved plan (or the initial state),
    # so a failed attempt never leaks into the retry.
    restore_world_state(env_id, env_size)

    run_dir = pddl_dir / "workspace"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Clean up previous run files to ensure retry starts fresh
    for subdir in run_dir.iterdir():
        if subdir.is_dir() and subdir.name.startswith("subgoal_"):
            shutil.rmtree(subdir)
    compiled_dir_path = run_dir / "compiled"
    if compiled_dir_path.exists():
        shutil.rmtree(compiled_dir_path)

    # Extract always-condition formulas (convert from dict to list of strings)
    always_formulas = None
    if always_conditions:
        always_formulas = [ac.get("predicate_formula", "") for ac in always_conditions if ac.get("predicate_formula")]

    # Compile domain ONCE if always conditions exist
    compiled_dir = run_dir / "compiled"
    actual_domain_path = _compile_domain_once(domain_path, always_formulas, compiled_dir)

    # Sort subgoals by order
    sorted_subgoals = sorted(subgoals, key=lambda x: x.get("order", 0))

    subgoal_results = []
    total_plan_length = 0
    total_plan_cost = 0.0

    # Final-goal conjuncts already achieved by earlier subgoals are kept as goals of later
    # subgoals, so a later subgoal cannot undo them (e.g. reopen a door closed earlier).
    # Sometime conditions are intermediate states and are not protected.
    at_end_parts = set(split_conjuncts((state or {}).get("at_end_condition", "")))
    protected: List[str] = []

    for idx, subgoal in enumerate(sorted_subgoals):
        goal_state = subgoal.get("goal_state", "")
        description = subgoal.get("description", "")
        subgoal_name = subgoal.get("name", "")
        own_parts = split_conjuncts(goal_state)
        extra = [p for p in protected if p not in own_parts]
        planner_goal = f"(and {' '.join(own_parts + extra)})" if extra else goal_state

        subgoal_dir_name = f"subgoal_{idx}_{subgoal_name}" if subgoal_name else f"subgoal_{idx}"
        subgoal_dir = run_dir / subgoal_dir_name
        subgoal_dir.mkdir(exist_ok=True)

        def solve_and_apply(goal: str, name: str, workdir: Path) -> Dict[str, Any]:
            """Plan for one goal from the current state and apply the plan's effects."""
            workdir.mkdir(parents=True, exist_ok=True)
            result = _solve_single_goal(goal, name, actual_domain_path, workdir, workdir, pddl_dir,
                                        always_formulas, discovered_objects)
            if result["success"]:
                applied = apply_action_effects(result["plan_content"])
                if not applied["success"]:
                    result = {"success": False, "error": f"Failed to apply plan: {applied.get('error')}"}
            return result

        solve_result = solve_and_apply(planner_goal, subgoal_dir_name, subgoal_dir)
        # If keeping earlier final-goal parts makes this subgoal unsolvable, plan for the
        # subgoal alone (the behaviour without protection)
        if not solve_result["success"] and extra and solve_result.get("error", "").startswith("Planning failed"):
            unprotected = solve_and_apply(goal_state, subgoal_dir_name, subgoal_dir)
            if unprotected["success"]:
                solve_result, extra = unprotected, []

        # A conjunctive goal over several objects can exceed the search time limit even when
        # each part is easy. Then achieve the parts one after another, keeping earlier parts.
        if not solve_result["success"] and "timed out" in solve_result.get("error", "") and len(own_parts) > 1:
            logger.info("Subgoal %d timed out; solving its %d parts sequentially", idx, len(own_parts))
            pieces, done_parts, metrics = [], [], {"plan_length": 0, "plan_cost": 0.0}
            for j, part in enumerate(own_parts):
                goal = f"(and {' '.join([part] + done_parts + extra)})" if done_parts or extra else part
                piece = solve_and_apply(goal, f"{subgoal_dir_name}_part{j}", subgoal_dir / f"part_{j}")
                if not piece["success"]:
                    solve_result = {"success": False, "error": f"Part {j + 1}/{len(own_parts)} {part}: {piece.get('error')}"}
                    break
                pieces.append(piece["plan_content"])
                done_parts.append(part)
                for key in metrics:
                    metrics[key] += piece.get("metrics", {}).get(key, 0)
            else:
                solve_result = {"success": True, "plan_content": "\n".join(pieces), "metrics": metrics,
                                "plan_path": str(subgoal_dir)}

        if solve_result["success"]:
            metrics = solve_result.get("metrics", {})
            subgoal_results.append({
                "subgoal_index": idx,
                "goal_state": goal_state,
                "description": description,
                "status": "success",
                "plan": solve_result["plan_content"],
                "plan_path": solve_result.get("plan_path"),
                "metrics": metrics
            })
            total_plan_length += metrics.get("plan_length", 0)
            total_plan_cost += metrics.get("plan_cost", 0.0)
            if own_parts and set(own_parts) <= at_end_parts:
                protected.extend(p for p in own_parts if p not in protected)
        else:
            subgoal_results.append({
                "subgoal_index": idx,
                "goal_state": goal_state,
                "description": description,
                "status": "failed",
                "error": solve_result.get("error", "Unknown error")
            })
            break

    overall_success = all(r["status"] == "success" for r in subgoal_results)

    if overall_success and subgoal_results:
        save_checkpoint(env_id, env_size)

    result = {
        "success": overall_success,
        "input_subgoals": subgoals,
        "subgoal_results": subgoal_results,
        "total_plan_length": total_plan_length,
        "total_plan_cost": total_plan_cost
    }

    return json.dumps(result, ensure_ascii=False)
