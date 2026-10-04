"""Compiles always-condition constraints into PDDL domain and problem files.

Always conditions must remain true throughout execution. Violations are detected
by injecting a (constraint-violated) flag that is set whenever a condition becomes false.
"""

import re
from pathlib import Path
from typing import Dict, List

from pddl.scripts.pddl_parser import PDDLDomainParser
from world_model.core.config import get_config
from world_model.core.manager import GraphDBManager


class PDDLConstraintCompiler:
    """Compile always-condition constraints into PDDL files."""

    def __init__(self):
        self.config = get_config()
        self.ONTOLOGY_NS = self.config.get_ontology_config()['namespace']

    def compile_domain(self, domain_content: str, always_conditions: List[str], domain_path: Path) -> str:
        """Add a (constraint-violated) flag that every action sets when an always-condition becomes false.

        Objects referenced by the conditions are declared as domain constants.
        """
        violation_formula = self._build_always_violation_formula(always_conditions)
        constant_types = self._extract_constants_from_state(violation_formula, domain_path)
        compiled = domain_content
        if constant_types:
            compiled = self._insert_constants(compiled, self._generate_constants_section(constant_types))
        compiled = self._add_violation_predicate(compiled)
        return self._compile_constraint_violations(compiled, violation_formula)

    def compile_problem(self, problem_content: str, always_conditions: List[str], domain_path: Path) -> str:
        """Move constants out of :objects, initialise the flag, and require (not (constraint-violated))."""
        violation_formula = self._build_always_violation_formula(always_conditions)
        constant_types = self._extract_constants_from_state(violation_formula, domain_path)
        compiled = problem_content
        if constant_types:
            compiled = self._remove_constants_from_objects(compiled, constant_types)
        compiled = self._update_problem_init(compiled)
        compiled = self._update_problem_goal(compiled)
        # The violation flag is set from each action's pre-state, so a violation caused by
        # the last action would go unnoticed; require the conditions in the final state too.
        return self._add_to_goal(compiled, always_conditions)

    def _add_to_goal(self, problem_content: str, formulas: List[str]) -> str:
        """Conjoin formulas to the (and ...) goal written by _update_problem_goal."""
        marker = "(not (constraint-violated))"
        idx = problem_content.rfind(marker)
        if idx == -1 or not formulas:
            return problem_content
        extra = "".join(f"\n      {f}" for f in formulas)
        return problem_content[:idx + len(marker)] + extra + problem_content[idx + len(marker):]

    def _build_always_violation_formula(self, always_conditions: List[str]) -> str:
        """Build a formula that becomes true iff any always-condition is violated.

        If conditions are C1..Cn (each should be a positive condition that must always hold),
        then violation is: (or (not C1) (not C2) ...).
        """
        conds = [c.strip() for c in (always_conditions or []) if str(c).strip()]
        if not conds:
            return ""
        if len(conds) == 1:
            return f"(not {conds[0]})"
        negated = [f"(not {c})" for c in conds]
        return "(or " + " ".join(negated) + ")"

    def _extract_constants_from_state(self, state: str, domain_path: Path) -> Dict[str, str]:
        """Extract constants and their types from forbidden state via GraphDB SPARQL query.

        Args:
            state: Formula that may contain object IDs
            domain_path: Path to domain file for PDDL type extraction

        Returns:
            Dict mapping object IDs to PDDL types (e.g., {"kitchen_19": "Location"})
        """
        if not state:
            return {}

        # Parse domain to get PDDL types
        parser = PDDLDomainParser(domain_path)
        pddl_types = set(parser.all_types)

        # Extract identifiers from state (excluding keywords)
        keywords = {'and', 'or', 'not'}
        tokens = re.findall(r'\b[a-zA-Z_][\w]*\b', state)

        # Filter out keywords only
        # We'll query GraphDB for all tokens and let it determine what exists
        object_ids = [t for t in tokens if t not in keywords]

        if not object_ids:
            return {}

        # Query GraphDB for types
        manager = GraphDBManager()
        try:
            values_clause = " ".join([f':{id}' for id in object_ids])

            sparql = f"""
PREFIX : <{self.ONTOLOGY_NS}>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?obj ?type WHERE {{
    VALUES ?obj {{ {values_clause} }}
    ?obj rdf:type ?type .
    FILTER(STRSTARTS(STR(?type), STR(:)))
}}
"""

            result = manager.query(sparql, infer=True)
            bindings = result['results']['bindings']

            # Group types by object
            obj_types = {}
            for b in bindings:
                obj_id = b['obj']['value'].split('#')[-1]
                type_name = b['type']['value'].split('#')[-1]

                if obj_id not in obj_types:
                    obj_types[obj_id] = []
                obj_types[obj_id].append(type_name)

            # Map to PDDL types (same logic as pddl_generator.py)
            constant_types = {}
            for obj_id in object_ids:
                class_names = obj_types.get(obj_id, [])

                # Find most specific class that matches a PDDL type
                domain_type = None
                for class_name in class_names:
                    if class_name in pddl_types:
                        domain_type = class_name
                        break

                if domain_type:
                    constant_types[obj_id] = domain_type
                # Silently skip objects not found in GraphDB (might be predicates misidentified)

            return constant_types

        finally:
            manager.close()

    def _generate_constants_section(self, constant_types: Dict[str, str]) -> str:
        """Generate PDDL constants section from extracted types."""
        if not constant_types:
            return ""

        constants_by_type = {}
        for const_name, const_type in constant_types.items():
            if const_type not in constants_by_type:
                constants_by_type[const_type] = []
            constants_by_type[const_type].append(const_name)

        lines = [
            "  ;; ====================================================================",
            "  ;; CONSTANTS (for compiled forbidden constraints)",
            "  ;; ====================================================================",
            "  (:constants"
        ]

        for type_name, names in constants_by_type.items():
            names_str = ' '.join(names)
            lines.append(f"    {names_str} - {type_name}")

        lines.append("  )")

        return '\n'.join(lines)

    def _insert_constants(self, domain_content: str, constants_section: str) -> str:
        """Insert constants section after types section."""
        if not constants_section:
            return domain_content

        types_pattern = r'(\(:types[^)]*\))'
        match = re.search(types_pattern, domain_content, re.DOTALL)

        if not match:
            return domain_content

        insert_pos = match.end()
        return domain_content[:insert_pos] + '\n\n' + constants_section + domain_content[insert_pos:]

    def _add_violation_predicate(self, domain_content: str) -> str:
        """Add (constraint-violated) predicate to domain."""
        predicates_pattern = r'(\(:predicates\s+)'
        match = re.search(predicates_pattern, domain_content)

        if not match:
            return domain_content

        insert_pos = match.end()

        violation_pred = """
    ;; COMPILED: Forbidden constraint violation flag
    (constraint-violated)
"""

        return domain_content[:insert_pos] + violation_pred + domain_content[insert_pos:]

    def _find_all_actions(self, domain_content: str) -> list:
        """Find ALL actions in domain. Returns list of tuples: (action_name, action_content)"""
        results = []

        # Action names contain hyphens (e.g. pick-one-hand), so \w alone is not enough
        action_pattern = r'\(:action\s+([\w-]+)\s+.*?(?=\(:action|\Z)'
        for match in re.finditer(action_pattern, domain_content, re.DOTALL):
            action_name = match.group(1)
            action_content = match.group(0)
            results.append((action_name, action_content))

        return results

    def _add_when_to_effect(self, action_content: str, forbidden_state: str) -> str:
        """Add (when forbidden_state (constraint-violated)) to action effect.

        Semantics:
          - Always-conditions must hold at *all* time steps.
          - Therefore, if a violation ever occurs, the plan is invalid.
          - We implement this with a *monotonic* flag: once (constraint-violated)
            becomes true, it never becomes false again.

        NOTE: forbidden_state should be a ground formula over constants.
        """
        # Find effect section
        effect_pattern = r'(:effect\s+\(and\s+)'
        match = re.search(effect_pattern, action_content)

        if not match:
            return action_content

        # Find where effect section ends
        effect_start = match.start()
        next_action_match = re.search(r'\(:action', action_content[effect_start + 10:])
        if next_action_match:
            effect_end = effect_start + 10 + next_action_match.start()
        else:
            effect_end = len(action_content)

        effect_section = action_content[effect_start:effect_end]

        # Find last closing paren of effect
        paren_count = 0
        last_close_paren = -1
        for i, char in enumerate(effect_section):
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
                if paren_count == 0:
                    last_close_paren = i
                    break

        if last_close_paren == -1:
            return action_content

        # Insert monotonic violation clause (no clearing)
        when_clause = (
            f"\n      ;; COMPILED FORBIDDEN: {forbidden_state}"
            f"\n      (when {forbidden_state}"
            f"\n        (constraint-violated))"
        )

        new_effect = effect_section[:last_close_paren] + when_clause + effect_section[last_close_paren:]

        return action_content[:effect_start] + new_effect + action_content[effect_end:]

    def _compile_constraint_violations(self, domain_content: str, violation_formula: str) -> str:
        """Compile constraint violations by modifying ALL actions.

        Adds when-clauses to detect when always-conditions are violated.

        Args:
            domain_content: Domain PDDL content
            violation_formula: Formula that becomes true when constraint violated
                              (e.g., "(not (isOpen window))" for always condition "(isOpen window)")

        Returns:
            Modified domain content with violation detection
        """
        if not violation_formula or not violation_formula.strip():
            return domain_content

        # Find ALL actions
        all_actions = self._find_all_actions(domain_content)

        # Build replacement map
        replacements = {}

        for _, action_content in all_actions:
            modified_action = self._add_when_to_effect(action_content, violation_formula)

            if modified_action != action_content:
                replacements[action_content] = modified_action

        # Apply all replacements
        for old_content, new_content in replacements.items():
            domain_content = domain_content.replace(old_content, new_content, 1)

        return domain_content

    def _remove_constants_from_objects(self, problem_content: str, constant_types: Dict[str, str]) -> str:
        """Remove constants from problem objects section to avoid duplicates."""
        if not constant_types:
            return problem_content

        constant_names = list(constant_types.keys())

        # Find objects section
        objects_pattern = r'(\(:objects\s+)(.*?)(\s*\))(?=\s*\()'
        match = re.search(objects_pattern, problem_content, re.DOTALL)

        if not match:
            return problem_content

        objects_start = match.start()
        objects_header = match.group(1)
        objects_body = match.group(2)
        objects_close = match.group(3)

        # Parse and filter objects
        lines = objects_body.split('\n')
        filtered_lines = []

        for line in lines:
            if '-' in line and not line.strip().startswith(';'):
                parts = line.split('-')
                if len(parts) == 2:
                    obj_names = parts[0].strip().split()
                    obj_type = parts[1].strip()

                    # Filter out constants
                    filtered_objs = [obj for obj in obj_names if obj not in constant_names]

                    if filtered_objs:
                        filtered_lines.append(f"    {' '.join(filtered_objs)} - {obj_type}")
                else:
                    filtered_lines.append(line)
            else:
                filtered_lines.append(line)

        # Reconstruct objects section
        new_objects_body = '\n'.join(filtered_lines)
        new_objects_section = objects_header + new_objects_body + objects_close

        return problem_content[:objects_start] + new_objects_section + problem_content[match.end():]

    def _update_problem_goal(self, problem_content: str) -> str:
        """Add (not (constraint-violated)) to problem goal.

        NOTE:
          The writer may generate either:
            (:goal <formula>)
          or:
            (:goal (and ...))

          We normalize to an (and ...) form so we can safely append
          (not (constraint-violated)).
        """
        # Only skip if the GOAL already references constraint-violated.
        # (Do NOT skip just because init contains (not (constraint-violated)).)
        goal_start = problem_content.find('(:goal')
        if goal_start == -1:
            return problem_content

        metric_match = re.search(r'\(:metric', problem_content[goal_start:])
        goal_end = goal_start + metric_match.start() if metric_match else len(problem_content)
        goal_section = problem_content[goal_start:goal_end]

        if 'constraint-violated' in goal_section:
            return problem_content

        # Extract the content after (:goal
        m = re.search(r'\(:goal\s*\n?', goal_section)
        if not m:
            return problem_content

        inner = goal_section[m.end():].strip()

        # Remove trailing ')' that closes the (:goal ...) block.
        # We do this by stripping exactly one final ')' if present.
        if inner.endswith(')'):
            inner_no_close = inner[:-1].rstrip()
        else:
            inner_no_close = inner

        # Determine if the goal is already an (and ...) expression
        inner_stripped = inner_no_close.strip()

        if inner_stripped.startswith('(and'):
            normalized_goal_body = inner_no_close
        else:
            # Wrap single formula into (and <formula>)
            # Keep indentation consistent with typical writer output.
            normalized_goal_body = f"(and {inner_stripped})"

        violation_check = (
            "\n      ;; COMPILED: Ensure no forbidden constraints violated\n"
            "      (not (constraint-violated))\n    "
        )

        # Insert before the closing paren of the top-level (and ...)
        and_idx = normalized_goal_body.find('(and')
        if and_idx == -1:
            return problem_content

        paren_count = 0
        and_close_paren = -1
        for i, ch in enumerate(normalized_goal_body[and_idx:]):
            if ch == '(':
                paren_count += 1
            elif ch == ')':
                paren_count -= 1
                if paren_count == 0:
                    and_close_paren = and_idx + i
                    break

        if and_close_paren == -1:
            return problem_content

        new_goal_body = normalized_goal_body[:and_close_paren] + violation_check + normalized_goal_body[and_close_paren:]

        # Reconstruct goal section with standard formatting
        new_goal_section = "  (:goal\n    " + new_goal_body.strip() + "\n  )\n\n"

        return problem_content[:goal_start] + new_goal_section + problem_content[goal_end:]

    def _update_problem_init(self, problem_content: str) -> str:
        """Ensure constraint-violated is false initially.

        We add (not (constraint-violated)) to init so that violation only happens
        if a forbidden state is reached.
        """
        if '(constraint-violated)' in problem_content:
            return problem_content

        init_start = problem_content.find('(:init')
        if init_start == -1:
            return problem_content

        # Insert just after (:init
        m = re.search(r'\(:init\s*\n', problem_content[init_start:])
        if not m:
            return problem_content

        insert_pos = init_start + m.end()
        insertion = "    ;; COMPILED: initialize violation flag\n    (not (constraint-violated))\n\n"
        return problem_content[:insert_pos] + insertion + problem_content[insert_pos:]
