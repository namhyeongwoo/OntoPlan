# Installation Guide

## Prerequisites

| Requirement | Version | Used for |
|---|---|---|
| Python | 3.11 | OntoPlan |
| Docker | 20.10+ | GraphDB (or install GraphDB Free natively) |
| g++ | 10+ (C++20) | Building Fast Downward |
| CMake | 3.21+ | Building Fast Downward |
| OpenAI API key | — | GPT-4o agents and category embeddings |

Linux and macOS are supported. On Windows, run everything inside [WSL](https://learn.microsoft.com/en-us/windows/wsl/install).

```bash
# Ubuntu 22.04+
sudo apt-get update && sudo apt-get install -y build-essential cmake

# Ubuntu 20.04 (default g++ 9 is too old)
sudo apt-get update && sudo apt-get install -y g++-10 make && pip install cmake
export CXX=g++-10

# macOS
xcode-select --install && brew install cmake
```

## 1. Clone with the Fast Downward submodule

```bash
git clone --recursive https://github.com/namhyeongwoo/OntoPlan.git
cd OntoPlan
```

If you cloned without `--recursive`, run `git submodule update --init`.

## 2. Python environment

```bash
conda create -n ontoplan python=3.11 -y
conda activate ontoplan
pip install -e .
```

`requirements.txt` pins the versions the code was tested with; `pip install -e .` installs them.

## 3. Build Fast Downward

```bash
cd pddl/fast-downward && ./build.py && cd ../..
```

The build takes a few minutes. The submodule is pinned to the Fast Downward commit the code was tested with.

## 4. Start GraphDB

```bash
docker run -d --name graphdb -p 7200:7200 ontotext/graphdb:10.7.0
```

Open <http://localhost:7200> to check that it is running. OntoPlan creates its repository (`OntoPlan`, OWL2-RL ruleset) on first run. To create it yourself instead, use **Setup → Repositories → Create new repository** with ID `OntoPlan` and ruleset `OWL2-RL`.

A native [GraphDB Free](https://graphdb.ontotext.com/) installation works as well.

## 5. API keys

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. LangSmith tracing is optional.

## 6. Configuration (optional)

Defaults are read from `world_model/config.example.yaml`. To change the GraphDB address, the repository name, or the embedding model, copy it and edit the copy:

```bash
cp world_model/config.example.yaml world_model/config.yaml
```

## 7. Verify

```bash
python -m agent.cli --env Klickitat --size small \
  "Move the vase in the living room on Floor B to the bathroom on Floor C."
```

The first run loads the environment into GraphDB and builds its category index. The command should end with `Done. 1/1 subgoals succeeded.` and a list of robot actions.

For the LangGraph Studio interface, run `langgraph dev` and start a thread with `{"env_id": "Klickitat", "env_size": "small"}`.

## Troubleshooting

**`Cannot reach GraphDB at http://localhost:7200`**: GraphDB is not running or listens elsewhere. Start the container (step 4) or set `graphdb.url` in `world_model/config.yaml`.

**`GraphDB repository 'OntoPlan' uses ruleset 'rdfsplus-optimized'`**: the repository was created without OWL 2 RL reasoning, which the ontology's property chains need (for example, an object the robot carries is in the robot's room). Delete the repository in the GraphDB Workbench (Setup → Repositories) and run OntoPlan again to recreate it, or create it yourself with ruleset `OWL2-RL`.

**Fast Downward not found**: the submodule is empty or not built. Run `git submodule update --init` and step 3.

**`error: 'concept' does not name a type` while building Fast Downward**: the compiler lacks C++20 support. Install g++ 10+, then:

```bash
export CXX=g++-10
cd pddl/fast-downward && rm -rf builds && ./build.py
```

**`openai.AuthenticationError`**: `OPENAI_API_KEY` in `.env` is missing or invalid.

**`langgraph: command not found`**: the environment is not activated, or `pip install -e .` did not finish.
