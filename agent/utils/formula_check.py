"""Check Task Formalizer conditions against the PDDL domain before planning.

Catches predicates that do not exist, wrong argument counts, names that are not object
IDs (e.g. "juice" instead of juice_357), and arguments of the wrong type (e.g. a room
used where the domain expects an artifact), so the Task Formalizer can correct them
instead of the planner failing later.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

from pddl.scripts.pddl_generator import PDDLGenerator
from pddl.scripts.pddl_goal_utils import split_conjuncts
from pddl.scripts.pddl_parser import PDDLDomainParser
from world_model.core.manager import GraphDBManager

DOMAIN_PATH = Path(__file__).resolve().parents[2] / "pddl" / "domain.pddl"
_CONNECTIVES = {"and", "or", "not", "imply", "forall", "exists", "when"}

# Suggestions for the most common type confusions
_HINTS = {
    ("isInsideOf", 2, "Location"): "use (isOnFloorOf <artifact> <space>) to put something in a room",
    ("isOntopOf", 2, "Location"): "use (isOnFloorOf <artifact> <space>) to put something in a room",
    ("isOnFloorOf", 2, "Artifact"): "use isOntopOf or isInsideOf for a surface or container",
    ("isOpen", 1, "Door"): "use (doorIsOpen <door>) for doors",
    ("doorIsOpen", 1, "Artifact"): "use (isOpen <artifact>) for containers and appliances",
}


@lru_cache(maxsize=1)
def _domain() -> Tuple[Dict[str, List[str]], PDDLDomainParser]:
    """Predicate signatures {name: [arg types]} from :predicates."""
    text = DOMAIN_PATH.read_text()
    block = text[text.index("(:predicates"):text.index("(:derived") if "(:derived" in text else None]
    signatures = {}
    for name, args in re.findall(r"\((\w+)((?:\s+\?\w+\s*-\s*\w+)*)\s*\)", block):
        signatures[name] = re.findall(r"-\s*(\w+)", args)
    return signatures, PDDLDomainParser(DOMAIN_PATH)


def _atoms(formula: str) -> List[List[str]]:
    """Ground atoms (predicate + arguments) in a formula; atoms with variables are skipped."""
    atoms = []
    for body in re.findall(r"\(([^()]*)\)", formula):
        parts = body.split()
        if parts and parts[0] not in _CONNECTIVES and parts[0] != "=" and not any(p.startswith("?") for p in parts):
            atoms.append(parts)
    return atoms


def check_formulas(formulas: Dict[str, str]) -> Dict[str, List[str]]:
    """Return {label: [problems]} for formulas that do not fit the domain.

    Args:
        formulas: {label: PDDL formula}, e.g. {"at_end: (isOntopOf a b)": "(isOntopOf a b)"}
    """
    signatures, parser = _domain()
    atoms = {label: _atoms(f) for label, f in formulas.items()}
    ids = sorted({arg for parts in atoms.values() for a in parts for arg in a[1:]})
    types = PDDLGenerator(GraphDBManager(), parser).get_types(ids) if ids else {}

    problems: Dict[str, List[str]] = {}
    for label, label_atoms in atoms.items():
        for pred, *args in label_atoms:
            if pred not in signatures:
                problems.setdefault(label, []).append(f"unknown predicate '{pred}'")
                continue
            expected = signatures[pred]
            if len(args) != len(expected):
                problems.setdefault(label, []).append(
                    f"({pred} ...) takes {len(expected)} argument(s) ({', '.join(expected)}), got {len(args)}")
                continue
            for pos, (arg, want) in enumerate(zip(args, expected), start=1):
                have = types.get(arg)
                if not have:
                    problems.setdefault(label, []).append(
                        f"'{arg}' is not an object ID; use the exact ID from Available Objects")
                elif not parser.is_subtype_of(have, want):
                    msg = f"argument {pos} of {pred} must be {want}, but {arg} is a {have}"
                    hint = _HINTS.get((pred, pos, have))
                    if not hint and parser.is_subtype_of(have, "Location"):
                        hint = _HINTS.get((pred, pos, "Location"))
                    problems.setdefault(label, []).append(msg + (f"; {hint}" if hint else ""))
    return problems


def check_always_initial(formulas: Dict[str, str]) -> Dict[str, List[str]]:
    """Return {label: [problems]} for always conditions that are already false at the start.

    An always condition must hold from the initial state, so forbidding the space the
    robot is standing in makes every plan impossible (usually the wrong ID was chosen).
    """
    location = PDDLGenerator(GraphDBManager(), _domain()[1]).get_robot_info().get("location")
    problems: Dict[str, List[str]] = {}
    for label, formula in formulas.items():
        for conjunct in split_conjuncts(formula):
            m = re.fullmatch(r"\(not \(robotIsInSpace robot (\S+)\)\)", conjunct)
            if m and m.group(1) == location:
                problems.setdefault(label, []).append(
                    f"the robot is currently in {location}, so {conjunct} is already false at the start and "
                    f"no plan can satisfy it; if the user meant a different place, use that place's ID "
                    f"(request more exploration if it is not in Available Objects)")
    return problems
