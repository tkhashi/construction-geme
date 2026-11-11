#!/usr/bin/env python3
"""駅の例（複合ファイル）を組み立てる：地上駅・相対式2面2線＋駅ビル。
BUILDING_MODEL_SCHEMA v0.3 の Track／Platform／FareZone・FareGate／Complex の実証用。"""
import json

def wall(id_, level, axis, frm, to, kind, thickness, openings=()):
    return {"id": id_, "level": level, "kind": kind, "thickness": thickness,
            "line": {"axis": axis, "from": frm, "to": to},
            "openings": [{"id": f"op:{id_}-{i+1}", "kind": k, "offsetFromStart": off, "width": w,
                          "height": 2100, "sillHeight": 0} for i, (k, off, w) in enumerate(openings)]}

def room(id_, level, name, use, xf, xt, yf, yt, zone, ceil=3300):
    return {"id": id_, "level": level, "name": name, "use": use, "ceilingHeight": ceil,
            "cells": {"xFrom": xf, "xTo": xt, "yFrom": yf, "yTo": yt}, "zoneId": zone}

FULL_ST = {"xFrom": "X1", "xTo": "X4", "yFrom": "Y1", "yTo": "Y3"}

station = {
    "building": {"id": "bldg:station", "name": "駅舎（地上駅）", "use": "駅舎", "structure": "S",
                 "floorHeightDefault": 4200, "grossAreaTarget": 216},
    "grid": {"axesX": [{"name": "X1", "offset": 0}, {"name": "X2", "offset": 6000},
                       {"name": "X3", "offset": 12000}, {"name": "X4", "offset": 18000}],
             "axesY": [{"name": "Y1", "offset": 0}, {"name": "Y2", "offset": 6000},
                       {"name": "Y3", "offset": 12000}],
             "columnRule": "all-intersections", "columnExceptions": [],
             "beamRule": "all-grid-lines-both-directions-each-level"},
    "levels": [{"id": "L1", "name": "1F", "elevation": 0, "floorHeight": 4200}],
    "cores": [{"id": "core:MECH", "levelRange": ["L1"],
               "rect": {"xFrom": "X3", "xTo": "X4", "yFrom": "Y2", "yTo": "Y3"}}],
    "shafts": [{"id": "shaft:st-ps", "coreId": "core:MECH", "kind": "PS", "levelRange": ["L1"],
                "footprint": {"x": 12100, "y": 6100, "w": 1200, "d": 2400}}],
    "rooms": [
        room("room:ST-OUT", "L1", "改札外コンコース", "コンコース", "X1", "X2", "Y1", "Y2", "ST-W", 3600),
        room("room:ST-WAIT", "L1", "待合室", "待合室", "X2", "X3", "Y1", "Y2", "ST-C"),
        room("room:ST-OFFICE", "L1", "駅事務室", "駅事務室", "X3", "X4", "Y1", "Y2", "ST-E"),
        room("room:ST-IN", "L1", "改札内コンコース", "コンコース", "X1", "X2", "Y2", "Y3", "ST-W", 3600),
        room("room:ST-WC", "L1", "便所", "WC", "X2", "X3", "Y2", "Y3", "ST-C"),
        room("room:ST-MECH", "L1", "機械室", "機械室", "X3", "X4", "Y2", "Y3", "ST-E"),
    ],
    "walls": [
        wall("wall:ST-Y1", "L1", "Y1", "X1", "X4", "外壁", 200,
             [("両開き戸", 1800, 2400), ("片開き戸", 6600, 1000), ("サッシ", 13000, 3000)]),
        wall("wall:ST-Y2", "L1", "Y2", "X1", "X4", "間仕切", 120,
             [("両開き戸", 2400, 1800), ("片開き戸", 15000, 900)]),
        wall("wall:ST-Y3", "L1", "Y3", "X1", "X4", "外壁", 200,
             [("両開き戸", 2400, 1800), ("片開き戸", 13500, 1000)]),
        wall("wall:ST-X1", "L1", "X1", "Y1", "Y3", "外壁", 200),
        wall("wall:ST-X4", "L1", "X4", "Y1", "Y3", "外壁", 200),
        wall("wall:ST-X2in", "L1", "X2", "Y2", "Y3", "間仕切", 120, [("片開き戸", 2500, 900)]),
        wall("wall:ST-X3out", "L1", "X3", "Y1", "Y2", "間仕切", 120, [("片開き戸", 2500, 900)]),
    ],
    "zones": [
        {"id": "ST-W", "level": "L1", "cellRange": {"xFrom": "X1", "xTo": "X2", "yFrom": "Y1", "yTo": "Y3"}},
        {"id": "ST-C", "level": "L1", "cellRange": {"xFrom": "X2", "xTo": "X3", "yFrom": "Y1", "yTo": "Y3"}},
        {"id": "ST-E", "level": "L1", "cellRange": {"xFrom": "X3", "xTo": "X4", "yFrom": "Y1", "yTo": "Y3"}},
    ],
    "compartments": [
        {"id": "fc:ST-L1", "kind": "面積区画", "level": "L1",
         "rooms": ["room:ST-OUT", "room:ST-WAIT", "room:ST-OFFICE", "room:ST-IN", "room:ST-WC", "room:ST-MECH"]},
        {"id": "fc:ST-shaft", "kind": "竪穴区画", "shafts": ["shaft:st-ps"]},
    ],
    "fareZones": [
        {"id": "zone:out", "kind": "改札外", "level": "L1", "rooms": ["room:ST-OUT", "room:ST-WAIT"]},
        {"id": "zone:in", "kind": "改札内", "level": "L1",
         "rooms": ["room:ST-IN", "room:ST-WC", "room:ST-OFFICE", "room:ST-MECH"]},
    ],
    "fareGates": [{"id": "gate:main", "level": "L1", "fromZone": "zone:out", "toZone": "zone:in",
                   "passages": 3, "widePassages": 1}],
    "foundations": {"footings": {"rule": "each-column", "size": {"w": 2000, "d": 2000},
                                 "thickness": 700, "topElevation": -600},
                    "gradeBeams": "all-grid-lines-below-ground", "piles": None},
    "earthworks": [{"id": "ew:st", "kind": "根切り", "cells": FULL_ST, "depth": 1200}],
    "slabs": [{"id": "slab:ST-L1", "level": "L1", "kind": "土間コンクリート", "cells": FULL_ST,
               "thickness": 150, "onGround": True, "openings": []}],
    "roof": {"id": "roof:st", "topLevel": "L1", "kind": "陸屋根（シート防水）", "cells": FULL_ST,
             "parapetHeight": 600},
    "coverings": [{"id": "cov:st-wait", "target": "room:ST-WAIT", "part": "床", "name": "長尺塩ビシート"}],
    "genericElements": [
        {"id": "ge:footbridge", "name": "跨線橋", "attachTo": "platform:B", "note": "改札内コンコースから対向ホームへ"},
        {"id": "ge:canopy-a", "name": "ホーム上屋", "attachTo": "platform:A", "note": "有効長の大半を覆う"},
    ],
}

FULL_EB = {"xFrom": "X1", "xTo": "X3", "yFrom": "Y1", "yTo": "Y2"}
def eb_floor(lid, nm):
    return [
        room(f"room:EB-{nm}-T1", lid, "テナント", "テナント", "X1", "X2", "Y1", "Y2", f"EB-{nm}-W", 3600),
        room(f"room:EB-{nm}-CORE", lid, "コアホール", "コアホール", "X2", "X3", "Y1", "Y2", f"EB-{nm}-E", 3600),
    ]
def eb_walls(nm):
    return [
        wall(f"wall:EB-{nm}-Y1", nm and "L1" if nm == "1F" else "L2", "Y1", "X1", "X3", "外壁", 200,
             [("両開き戸", 2000, 2400), ("両開き戸", 10000, 2000)]),
        wall(f"wall:EB-{nm}-Y2", "L1" if nm == "1F" else "L2", "Y2", "X1", "X3", "外壁", 200,
             [("サッシ", 1500, 5000)]),
        wall(f"wall:EB-{nm}-X2", "L1" if nm == "1F" else "L2", "X2", "Y1", "Y2", "間仕切", 120,
             [("両開き戸", 3000, 1600)]),
        wall(f"wall:EB-{nm}-X1", "L1" if nm == "1F" else "L2", "X1", "Y1", "Y2", "外壁", 200),
        wall(f"wall:EB-{nm}-X3", "L1" if nm == "1F" else "L2", "X3", "Y1", "Y2", "シャフト壁", 200),
    ]

ekibiru = {
    "building": {"id": "bldg:ekibiru", "name": "駅ビル（商業）", "use": "商業", "structure": "S",
                 "floorHeightDefault": 4500, "grossAreaTarget": 256},
    "grid": {"axesX": [{"name": "X1", "offset": 0}, {"name": "X2", "offset": 8000},
                       {"name": "X3", "offset": 16000}],
             "axesY": [{"name": "Y1", "offset": 0}, {"name": "Y2", "offset": 8000}],
             "columnRule": "all-intersections", "columnExceptions": [],
             "beamRule": "all-grid-lines-both-directions-each-level"},
    "levels": [{"id": "L1", "name": "1F", "elevation": 0, "floorHeight": 4500},
               {"id": "L2", "name": "2F", "elevation": 4500, "floorHeight": 4500}],
    "cores": [{"id": "core:EB", "levelRange": ["L1", "L2"],
               "rect": {"xFrom": "X2", "xTo": "X3", "yFrom": "Y1", "yTo": "Y2"}}],
    "shafts": [
        {"id": "shaft:eb-stair", "coreId": "core:EB", "kind": "階段", "levelRange": ["L1", "L2"],
         "footprint": {"x": 8200, "y": 200, "w": 3400, "d": 7000},
         "stair": {"riser": 180, "steps": 25, "going": 260}},
        {"id": "shaft:eb-ev", "coreId": "core:EB", "kind": "EV", "levelRange": ["L1", "L2"],
         "footprint": {"x": 12000, "y": 5000, "w": 2300, "d": 2300}},
        {"id": "shaft:eb-ps", "coreId": "core:EB", "kind": "PS", "levelRange": ["L1", "L2"],
         "footprint": {"x": 14500, "y": 5000, "w": 1200, "d": 2400}},
    ],
    "rooms": eb_floor("L1", "1F") + eb_floor("L2", "2F"),
    "walls": eb_walls("1F") + eb_walls("2F"),
    "zones": [
        {"id": "EB-1F-W", "level": "L1", "cellRange": {"xFrom": "X1", "xTo": "X2", "yFrom": "Y1", "yTo": "Y2"}},
        {"id": "EB-1F-E", "level": "L1", "cellRange": {"xFrom": "X2", "xTo": "X3", "yFrom": "Y1", "yTo": "Y2"}},
        {"id": "EB-2F-W", "level": "L2", "cellRange": {"xFrom": "X1", "xTo": "X2", "yFrom": "Y1", "yTo": "Y2"}},
        {"id": "EB-2F-E", "level": "L2", "cellRange": {"xFrom": "X2", "xTo": "X3", "yFrom": "Y1", "yTo": "Y2"}},
    ],
    "compartments": [
        {"id": "fc:EB-1F", "kind": "面積区画", "level": "L1", "rooms": ["room:EB-1F-T1", "room:EB-1F-CORE"]},
        {"id": "fc:EB-2F", "kind": "面積区画", "level": "L2", "rooms": ["room:EB-2F-T1", "room:EB-2F-CORE"]},
        {"id": "fc:EB-stair", "kind": "竪穴区画", "shafts": ["shaft:eb-stair"]},
        {"id": "fc:EB-ev", "kind": "竪穴区画", "shafts": ["shaft:eb-ev"]},
        {"id": "fc:EB-ps", "kind": "竪穴区画", "shafts": ["shaft:eb-ps"]},
    ],
    "foundations": {"footings": {"rule": "each-column", "size": {"w": 2400, "d": 2400},
                                 "thickness": 800, "topElevation": -600},
                    "gradeBeams": "all-grid-lines-below-ground", "piles": None},
    "earthworks": [{"id": "ew:eb", "kind": "根切り", "cells": FULL_EB, "depth": 1500}],
    "slabs": [
        {"id": "slab:EB-L1", "level": "L1", "kind": "土間コンクリート", "cells": FULL_EB,
         "thickness": 150, "onGround": True, "openings": []},
        {"id": "slab:EB-L2", "level": "L2", "kind": "デッキ合成スラブ", "cells": FULL_EB,
         "thickness": 150, "openings": ["shaft:eb-stair", "shaft:eb-ev", "shaft:eb-ps"]},
    ],
    "roof": {"id": "roof:eb", "topLevel": "L2", "kind": "陸屋根（シート防水）", "cells": FULL_EB,
             "parapetHeight": 600},
}

doc = {
    "complex": {"id": "complex:station-01", "name": "生成例：小規模駅（地上駅・相対式2面2線＋駅ビル）",
                "links": [{"id": "link:1", "from": "bldg:station", "to": "bldg:ekibiru", "kind": "連絡通路"}]},
    "site": {
        "polygon": [[-8000, -18000], [130000, -18000], [130000, 22000], [-8000, 22000]],
        "buildingPlacement": {"origin": [0, 0], "rotationDeg": 0},
        "roads": [{"edge": "south", "name": "駅前広場・町道", "width": 8000}],
        "gates": [],
        "neighbors": [{"edge": "north", "type": "住宅"}, {"edge": "south", "type": "駅前広場"}],
        "tracks": [
            {"id": "track:1", "name": "下り線", "kind": "在来線", "centerOffset": -6000, "centerSpacing": 3600},
            {"id": "track:2", "name": "上り線", "kind": "在来線", "centerOffset": -9600, "centerSpacing": 3600},
        ],
        "platforms": [
            {"id": "platform:A", "level": "L1", "trackIds": ["track:1"], "form": "相対式",
             "rect": {"x": -2000, "y": -4520, "w": 124000, "d": 2000},
             "edgeOffset": 1480, "height": 1100, "usableWidth": 2000},
            {"id": "platform:B", "level": "L1", "trackIds": ["track:2"], "form": "相対式",
             "rect": {"x": -2000, "y": -13080, "w": 124000, "d": 2000},
             "edgeOffset": 1480, "height": 1100, "usableWidth": 2000},
        ],
    },
    "buildings": [station, ekibiru],
}

with open("building_model_station_example.json", "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
print("wrote building_model_station_example.json")
