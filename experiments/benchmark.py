"""Loading the benchmark tasks (benchmark/general/*.json)."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

BENCHMARK_DIR = Path(__file__).resolve().parents[1] / "benchmark"
ENVS = ("Klickitat", "Lakeville", "Lindenwood", "Marstons", "Muleshoe")
SIZES = ("small", "medium", "large")


def load_tasks(env: Optional[str] = None, size: Optional[str] = None,
               ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Return the 150 general tasks (optionally filtered) as dicts with id, env, size, instruction, expected."""
    tasks = [t for e in ENVS for t in json.loads((BENCHMARK_DIR / "general" / f"{e}.json").read_text())["tasks"]]
    return [t for t in tasks
            if (env is None or t["env"] == env) and (size is None or t["size"] == size)
            and (ids is None or t["id"] in ids)]
