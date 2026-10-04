"""Build docs/static/data/klickitat.js for the project page scene-graph explorer.

Parses the Klickitat TTL files (static + dynamic) at each scale, computes a fixed
2D layout, and attaches the 30 Klickitat instructions from the paper appendix
with the entities named in their evaluation conditions.

Usage (from repo root):  python docs/scripts/build_scene_graph.py
Requires: networkx
"""

import json
import re
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
ENV_DIR = ROOT / "world_model/data/envs/Klickitat"
OUT = ROOT / "docs/static/data/klickitat.js"

TYPE_OF = {
    "Building": "building", "Storey": "storey", "Space": "space",
    "Door": "portal", "Stairs": "portal", "Opening": "portal",
    "Artifact": "artifact", "Robot": "robot", "Hand": "robot",
}
EDGE_PREDICATES = {
    "storeyIsInBuilding", "spaceIsInStorey", "isDoorOf", "isStairsOf", "isOpeningOf",
    "isOnFloorOf", "isOntopOf", "isInsideOf", "robotIsInSpace", "hasHand",
}

# Klickitat instructions from the appendix (Table: General Instruction Examples).
# `entities` lists the IDs named in the evaluation conditions.
TASKS = {
    "small": [
        ("S01", "I think I left my cell phone in the dining room on Floor B. Can you find it and bring it to the home office on Floor C?",
         [("at_end", "cell_phone_61 is in home_office_18")], ["cell_phone_61", "home_office_18"]),
        ("S02", "There should be a bottle in the kitchen on Floor B. Take it out and put it on the couch in the living room on Floor B.",
         [("at_end", "bottle_3 is on couch_31 or couch_33")], ["bottle_3", "couch_31", "couch_33"]),
        ("S03", "Move the sports ball from the playroom on Floor C to the home office on Floor C. Never go through the door connecting the lobby and the corridor on Floor B because it is under repair.",
         [("always", "the robot does not pass through door_5"), ("at_end", "sports_ball_2 is in home_office_18")], ["door_5", "sports_ball_2", "home_office_18"]),
        ("S04", "Move the vase in the living room on Floor B to the bathroom on Floor C. Use only your right hand for this task.",
         [("always", "left_hand remains empty"), ("at_end", "vase_80 or vase_84 is in bathroom_3, bathroom_4, or bathroom_5")], ["left_hand", "vase_80", "vase_84", "bathroom_3", "bathroom_4", "bathroom_5"]),
        ("S05", "There is a book in one of the bedrooms on Floor C. Bring it to the living room on Floor B.",
         [("at_end", "book_78 is in living_room_22 or living_room_23")], ["book_78", "living_room_22", "living_room_23"]),
        ("S06", "There aren't enough chairs in the dining room connected to the kitchen on Floor B. Can you bring one more chair from the other dining room on the same floor?",
         [("at_end", "at least one of chair_24, chair_25, or chair_26 is in dining_room_16")], ["chair_24", "chair_25", "chair_26", "dining_room_16"]),
        ("S07", "Move the potted plant from the staircase on Floor B to the lobby. I'm afraid people might bump into it.",
         [("at_end", "potted_plant_45 is in lobby_24")], ["potted_plant_45", "lobby_24"]),
        ("S08", "Move the vase from the bathroom on Floor C to the playroom. Use only your right hand.",
         [("always", "left_hand remains empty"), ("at_end", "vase_81 is in playroom_25")], ["left_hand", "vase_81", "playroom_25"]),
        ("S09", "I need to move a chair from the dining room on Floor B to the bedroom on Floor A. Please use the stairs leading to Floor A.",
         [("sometime", "robot passes through stairs_7"), ("at_end", "at least one chair from chair_18–chair_22 or chair_24–chair_26 is in bedroom_6")],
         ["stairs_7", "chair_18", "chair_19", "chair_20", "chair_21", "chair_22", "chair_24", "chair_25", "chair_26", "bedroom_6"]),
        ("S10", "Move one potted plant from the bedroom connected to the closet on Floor C to another bedroom. And make sure to close the door when you leave the room.",
         [("at_end", "potted_plant_46 or potted_plant_47 is in bedroom_6, bedroom_8, or bedroom_9, and door_6 is closed")],
         ["potted_plant_46", "potted_plant_47", "bedroom_6", "bedroom_8", "bedroom_9", "door_6"]),
    ],
    "medium": [
        ("M01", "Please turn on the coffee machine in the kitchen on Floor B. Also, bring the mug from the tray in the bedroom on Floor C and place it on the coffee machine.",
         [("at_end", "coffee_machine_170 is switched on, and mug_71 is on it")], ["coffee_machine_170", "mug_71"]),
        ("M02", "Turn on the TV in the living room on Floor B and gather the cushions scattered around the room onto the sofa.",
         [("at_end", "tv_211 is switched on, and cushions cushion_219–cushion_223 are on sofa_208")],
         ["tv_211", "cushion_219", "cushion_220", "cushion_221", "cushion_222", "cushion_223", "sofa_208"]),
        ("M03", "I think I left the refrigerator in the kitchen open. Could you take the juice out of it and place it on the dining table? And please close the refrigerator when you are done.",
         [("at_end", "juice_357 is on dining_table_112 or dining_table_131, and refrigerator_164 is closed")], ["juice_357", "dining_table_112", "dining_table_131", "refrigerator_164"]),
        ("M04", "Turn on the laptop in the home office on Floor C and take the hole punch out of the storage cabinet onto the desk.",
         [("at_end", "laptop_144 is switched on, and hole_punch_323 is on desk_139")], ["laptop_144", "hole_punch_323", "desk_139"]),
        ("M05", "Take the jeans out of the dresser in the closet on Floor C and put them on the armchair in the bedroom.",
         [("at_end", "jeans_294 is on armchair_48 or armchair_49")], ["jeans_294", "armchair_48", "armchair_49"]),
        ("M06", "Take the wine glasses out of the cupboard in the dining room on Floor B and set them on the dining table.",
         [("at_end", "wine_glass_121 and wine_glass_122 are on dining_table_112")], ["wine_glass_121", "wine_glass_122", "dining_table_112"]),
        ("M07", "Turn on the microwave in the kitchen on Floor B. And if the door leading to the dining room is closed, please open it.",
         [("at_end", "microwave_169 is switched on, and door_3 is open")], ["microwave_169", "door_3"]),
        ("M08", "Cook the chicken from the refrigerator in the kitchen on Floor B in the oven, then serve it on the island table in the kitchen.",
         [("sometime", "chicken_353 is inside oven_161 while it is closed and switched on"), ("at_end", "chicken_353 is on island_table_158")], ["chicken_353", "oven_161", "island_table_158"]),
        ("M09", "Heat up the beef from the refrigerator in the kitchen on Floor B in the microwave, then place it on the island table in the kitchen.",
         [("sometime", "beef_354 is inside microwave_169 while it is closed and switched on"), ("at_end", "beef_354 is on island_table_158")], ["beef_354", "microwave_169", "island_table_158"]),
        ("M10", "Wash the bowl from the storage cabinet in the kitchen on Floor A in the dishwasher, then put it back on top of the storage cabinet.",
         [("sometime", "bowl_341 is inside dishwasher_156 while it is closed and switched on"), ("at_end", "bowl_341 is on storage_cabinet_154")], ["bowl_341", "dishwasher_156", "storage_cabinet_154"]),
    ],
    "large": [
        ("L01", "Turn on the microwave in the kitchen on Floor B. But since the corridor is being cleaned, please go through the living room.",
         [("always", "the robot does not pass through corridor_12"), ("at_end", "microwave_169 is switched on")], ["corridor_12", "microwave_169"]),
        ("L02", "We need one more chair in the dining room on Floor A. Can you bring a chair from the dining room next to the corridor on Floor B?",
         [("at_end", "chair_132 or chair_133 is in dining_room_15")], ["chair_132", "chair_133", "dining_room_15"]),
        ("L03", "Turn on the TV in the living room on Floor B. But please avoid the stairs connecting the living room and the lobby on Floor B.",
         [("always", "the robot does not pass through stairs_4"), ("at_end", "tv_211 is switched on")], ["stairs_4", "tv_211"]),
        ("L04", "There should be a hole punch in the storage cabinet in the home office on Floor C. Take it out and put it on the desk.",
         [("at_end", "hole_punch_323 is on desk_139")], ["hole_punch_323", "desk_139"]),
        ("L05", "The lamps in the bedroom with a bathroom right next to you are on. Could you turn them all off so I can sleep comfortably?",
         [("at_end", "lamp_83 and lamp_84 are switched off")], ["lamp_83", "lamp_84"]),
        ("L06", "Take the milk from the refrigerator in the kitchen on Floor B and put it on the dining room table.",
         [("at_end", "milk_348 is on dining_table_112 or dining_table_131")], ["milk_348", "dining_table_112", "dining_table_131"]),
        ("L07", "Take the jeans out of the closet dresser on Floor C and lay them on the bed.",
         [("at_end", "jeans_294 is on bed_53 or bed_73")], ["jeans_294", "bed_53", "bed_73"]),
        ("L08", "Cook the cheese from the refrigerator in the kitchen on Floor B in the oven, then serve it on the island table in the kitchen.",
         [("sometime", "cheese_350 is inside oven_161 while it is closed and switched on"), ("at_end", "cheese_350 is on island_table_158")], ["cheese_350", "oven_161", "island_table_158"]),
        ("L09", "Heat up the milk from the refrigerator in the kitchen on Floor B in the microwave, then place it on the island table in the kitchen.",
         [("sometime", "milk_348 is inside microwave_169 while it is closed and switched on"), ("at_end", "milk_348 is on island_table_158")], ["milk_348", "microwave_169", "island_table_158"]),
        ("L10", "Wash the cup from the storage cabinet in the kitchen on Floor A in the dishwasher, then put it back on top of the storage cabinet.",
         [("sometime", "cup_343 is inside dishwasher_156 while it is closed and switched on"), ("at_end", "cup_343 is on storage_cabinet_154")], ["cup_343", "dishwasher_156", "storage_cabinet_154"]),
    ],
}

SUBJECT_RE = re.compile(r"^:(\w+)\s+rdf:type\s+:(\w+)")
PRED_RE = re.compile(r"^\s*:(\w+)\s+:(\w+)\s*[;.]\s*$")


def parse_ttl(paths):
    nodes, edges = {}, []
    for path in paths:
        subject = None
        for line in path.read_text().splitlines():
            m = SUBJECT_RE.match(line)
            if m:
                subject, cls = m.groups()
                if cls in TYPE_OF:
                    nodes[subject] = TYPE_OF[cls]
                continue
            m = PRED_RE.match(line)
            if m and subject:
                pred, obj = m.groups()
                if pred in EDGE_PREDICATES:
                    edges.append((subject, obj))
            if line.strip() == "":
                subject = None
    edges = [(a, b) for a, b in edges if a in nodes and b in nodes]
    return nodes, edges


def layout(nodes, edges, seed=7):
    g = nx.Graph()
    g.add_nodes_from(nodes)
    g.add_edges_from(edges)
    n = g.number_of_nodes()
    pos = nx.spring_layout(g, k=1.6 / n ** 0.5, iterations=300, seed=seed)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return {k: ((v[0] - x0) / (x1 - x0), (v[1] - y0) / (y1 - y0)) for k, v in pos.items()}


def main():
    data = {}
    for scale in ("small", "medium", "large"):
        d = ENV_DIR / scale
        nodes, edges = parse_ttl([d / "static.ttl", d / "dynamic.ttl"])
        pos = layout(nodes, edges)
        ids = list(nodes)
        index = {k: i for i, k in enumerate(ids)}
        tasks = []
        for tid, text, conds, ents in TASKS[scale]:
            missing = [e for e in ents if e not in index]
            assert not missing, f"{tid}: {missing} not in {scale} graph"
            tasks.append({"id": tid, "text": text, "conds": conds, "ents": [index[e] for e in ents]})
        data[scale] = {
            "ids": ids,
            "types": [nodes[k] for k in ids],
            "xy": [v for k in ids for v in (round(pos[k][0], 4), round(pos[k][1], 4))],
            "edges": [v for a, b in edges for v in (index[a], index[b])],
            "tasks": tasks,
        }
        print(f"{scale}: {len(ids)} nodes, {len(edges)} edges, "
              f"{sum(t == 'artifact' for t in data[scale]['types'])} artifacts")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.KLICKITAT = " + json.dumps(data, separators=(",", ":")) + ";\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
