"""PDDL Domain Parser - Extract types and hierarchy from domain.pddl."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class PDDLDomainParser:
    """Parse PDDL domain file to extract types and hierarchy."""

    def __init__(self, domain_path: str):
        """Initialize parser with domain file path."""
        self.domain_path = Path(domain_path)
        self.types_hierarchy = {}  # type -> parent_type
        self.all_types = set()
        self._parse_domain()

    def _parse_domain(self):
        """Parse domain file and extract types."""
        with open(self.domain_path, 'r') as f:
            content = f.read()

        types_match = re.search(r'\(:types\s+(.*?)\)', content, re.DOTALL)
        if not types_match:
            logger.warning("No :types section found in %s", self.domain_path)
            return

        types_content = types_match.group(1)
        lines = types_content.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.startswith(';'):
                continue

            if '-' in line:
                parts = line.split('-')
                children = parts[0].strip().split()
                parent = parts[1].strip()

                self.all_types.add(parent)
                if parent not in self.types_hierarchy:
                    self.types_hierarchy[parent] = None

                for child in children:
                    child = child.strip()
                    if child:
                        self.all_types.add(child)
                        self.types_hierarchy[child] = parent
            else:
                types = line.split()
                for t in types:
                    t = t.strip()
                    if t:
                        self.all_types.add(t)
                        if t not in self.types_hierarchy:
                            self.types_hierarchy[t] = None

    def is_subtype_of(self, child_type: str, parent_type: str) -> bool:
        """Check if child_type is a subtype of parent_type."""
        if child_type == parent_type:
            return True

        current = child_type
        while current in self.types_hierarchy:
            parent = self.types_hierarchy[current]
            if parent == parent_type:
                return True
            current = parent

        return False
