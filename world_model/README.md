# World model

The world model stores the scene as RDF in [GraphDB](https://graphdb.ontotext.com/) with OWL 2 RL reasoning. The agents access it only through the *Scene query* tool (read) and the *PDDL plan* tool (read state, write action effects).

```text
core/config.py         reads config.yaml (or config.example.yaml)
core/manager.py        GraphDB client: SPARQL query/update, TTL loading, repository creation
core/vector_store.py   FAISS index of category names used by semantic_search
tools/tools.py         query functions behind the scene_query tool
data/                  ontology and environments (see data/README.md)
```

## Layers

| File | Contents | Changes at run time |
|---|---|---|
| `data/schema.ttl` | Ontology: classes, properties, axioms. Classes and properties with `:pddl true` match the PDDL types and predicates in `pddl/domain.pddl` | No |
| `envs/<env>/<size>/static.ttl` | Storeys, spaces, doors, stairs, openings, connectivity | No |
| `envs/<env>/<size>/dynamic.ttl` | Objects, their locations and states, the robot and its hands | Yes, by action effects |

At session start the three layers are loaded into the default graph, which holds the live state. Named-graph copies of the initial state let planning reset the default graph without re-reading files. After each successful plan the explicit dynamic triples are saved as a checkpoint, so the next instruction in the session starts from the updated state.

## Scene query functions

These are exposed to the Scene Explorer as LangChain tools in `agent/tools/scene_query.py`.

**`semantic_search(query, reason, space_id=None, floor_id=None, object_id=None)`** matches the query to the closest scene category with embeddings, then filters instances with SPARQL. `space_id` and `floor_id` restrict the location; `object_id` returns things on or inside that object. When a spatial filter finds nothing, it falls back to a global search and says so in `hint`.

```python
semantic_search(query="water bottle")
semantic_search(query="chair", space_id="dining_room_16")
semantic_search(query="", object_id="refrigerator_164")
```

```json
{
  "hint": "Query 'cell phone' matched 'cell phone'. If empty or wrong match, retry with: laptop, microwave, book, kitchen. Showing results for 'cell phone'.",
  "results": [{"id": "cell_phone_61", "category": "cell phone", "isInSpace": "dining_room_17", "isInStorey": "Floor_B"}]
}
```

**`find_path(from_id, to_id, reason)`** returns the shortest path over the connectivity graph (GraphDB path search). Objects are resolved to the space that contains them.

## Adding an environment

1. Create `data/envs/MyEnv/small/` with `static.ttl` and `dynamic.ttl` following an existing environment.
2. Add `MyEnv` to `ENV_IDS` in `agent/environment.py`.
3. Start a session with `env_id="MyEnv"`; the category index is built on first use.
