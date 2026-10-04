"""Tests that need neither GraphDB nor an API key:  pytest tests/"""

from experiments.benchmark import load_tasks
from experiments.evaluator import ConditionChecker
from experiments.oracle import to_pddl
from pddl.scripts.pddl_goal_utils import split_conjuncts


def test_split_conjuncts_flattens_nested_and():
    formula = "(and (isSwitchedOn tv_1)  (and (not (doorIsOpen door_1)) (isOpen box_2)))"
    assert split_conjuncts(formula) == ["(isSwitchedOn tv_1)", "(not (doorIsOpen door_1))", "(isOpen box_2)"]
    assert split_conjuncts("(isOnFloorOf a  b)") == ["(isOnFloorOf a b)"]
    assert split_conjuncts("") == []


def test_to_pddl_maps_benchmark_conditions():
    assert to_pddl({"subject": "book_1", "predicate": "isInSpace", "object": "office_2"}) == "(artifactIsInSpace book_1 office_2)"
    assert to_pddl({"subject": "robot", "predicate": "isInSpace", "object": "hall_3"}) == "(robotIsInSpace robot hall_3)"
    assert to_pddl({"subject": "tv_1", "predicate": "isSwitchedOn", "object": "false"}) == "(not (isSwitchedOn tv_1))"
    assert to_pddl({"not": {"subject": "right_hand", "predicate": "holds", "object": "?x"}}) == "(isEmpty right_hand)"
    assert to_pddl({"or": [{"subject": "a", "predicate": "isOntopOf", "object": "b"},
                           {"subject": "a", "predicate": "isInsideOf", "object": "c"}]}) == "(or (isOntopOf a b) (isInsideOf a c))"


class _Manager:
    ONTOLOGY_NS = "http://example.org/OntoPlan#"


def test_condition_checker_patterns():
    checker = ConditionChecker(_Manager())
    assert checker._pattern({"subject": "a", "predicate": "isOntopOf", "object": "b"}) == ":a :isOntopOf :b"
    assert checker._pattern({"subject": "left_hand", "predicate": "isEmpty", "object": "true"}) == \
        "FILTER NOT EXISTS { :left_hand :holds ?_x }"
    assert "UNION" in checker._pattern({"or": [{"subject": "a", "predicate": "p", "object": "b"},
                                               {"subject": "a", "predicate": "p", "object": "c"}]})


def test_benchmark_composition():
    general = load_tasks()
    assert len(general) == 150
    for env in {t["env"] for t in general}:
        for size, prefix in (("small", "S"), ("medium", "M"), ("large", "L")):
            ids = sorted(t["id"] for t in general if t["env"] == env and t["size"] == size)
            assert ids == [f"{prefix}{i:02d}" for i in range(1, 11)]
