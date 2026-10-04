# OntoPlan environment data

```text
schema.ttl                         OWL ontology shared by all environments
envs/<Environment>/<scale>/
  static.ttl                       storeys, spaces, doors, stairs, openings, connectivity
  dynamic.ttl                      objects, their locations and states, the robot and its hands
  world.json                       the same scene serialized as JSON (input of the no-Scene-query
                                   ablation and of the text-based baselines)
  vector_store/                    category embedding cache (generated on first run, not tracked)
```

Environments: Klickitat, Lakeville, Lindenwood, Marstons, Muleshoe. Scales: `small` (mapped from the source annotations), `medium` (manually augmented), `large` (Medium augmented to three times the object count).

## Source and terms of use

The environments are derived from the **3D Scene Graph** dataset:

> I. Armeni, Z.-Y. He, J. Gwak, A. R. Zamir, M. Fischer, J. Malik, and S. Savarese. *3D Scene Graph: A Structure for Unified Semantics, 3D Space, and Camera.* ICCV 2019. <https://3dscenegraph.stanford.edu/>

The source dataset is provided for non-commercial research purposes only, and these derived files are distributed under the same terms. They are not covered by the MIT License of the code. If you use them, cite the 3D Scene Graph paper and follow its terms of use.
