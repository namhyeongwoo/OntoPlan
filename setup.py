from pathlib import Path

from setuptools import find_packages, setup

requirements = [
    line.strip()
    for line in Path(__file__).with_name("requirements.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]

setup(
    name="ontoplan",
    version="1.0.0",
    description="OntoPlan: ontology-grounded scene representation and agentic framework for robot task planning",
    author="Hyeongwoo Nam, Woongje Cho, Juwon Kim, Jongeun Choi",
    url="https://github.com/namhyeongwoo/OntoPlan",
    license="MIT",
    packages=find_packages(include=["agent*", "world_model*", "pddl", "pddl.scripts"]),
    python_requires=">=3.11",
    install_requires=requirements,
)
