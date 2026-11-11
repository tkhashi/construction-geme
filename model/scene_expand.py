#!/usr/bin/env python3
"""現場3Dビュー生成 S3D-1 描画キュー展開エンジン。

建物モデル v0.7 ＋ ConstructionPlan ＋ ゲーム換算（integration）＋ 設備推論を
固定入力とし、展開規則テーブル（scene_rules.json）に従って ScenePlan
（配置イベント列）を決定的に生成する。仕様の正は SCENE3D_PIPELINE.md。

- 全段は (入力, シード) の純関数。乱数・現在時刻は使わない。
- 規則はコードに直書きせず scene_rules.json を読む。直すのは規則側。
- 使い方：python3 scene_expand.py <建物モデル.json>
  計画・換算・設備はファイル名の stem から自動で対応付ける。
"""
import hashlib
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
RULES_PATH = HERE / "scene_rules.json"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def r3(x: float) -> float:
    """座標・時刻の丸め（決定性と比較可能性のため）"""
    return round(float(x), 3)


# ---------------------------------------------------------------- 文脈
class Ctx:
    def __init__(self, building_path: Path):
        self.building_path = building_path
        # 計画・換算・設備は建物ファイル名から generated_ を除いた stem で対応付ける
        stem = building_path.stem.removeprefix("generated_")
        self.stem = stem
        plan_path = HERE / f"generated_construction_plan_{stem}.json"
        game_path = HERE / "integration" / f"generated_game_schedule_{stem}.json"
        equip_path = HERE / f"generated_equipment_{stem}.json"
        self.input_files = {
            "building": building_path,
            "plan": plan_path,
            "gameSchedule": game_path,
            "equipment": equip_path,
            "rules": RULES_PATH,
        }
        self.input_hashes = {}
        raw = {}
        for key, path in self.input_files.items():
            data = path.read_bytes()
            self.input_hashes[key] = sha256_bytes(data)
            raw[key] = json.loads(data)
        self.building = raw["building"]
        self.plan = raw["plan"]
        self.game = raw["gameSchedule"]
        self.equipment = raw["equipment"]
        self.rules = raw["rules"]
        self.seed = self.plan["meta"].get("seed")
        self.members = []
        self.events = []
        self.actors = []
        self._actor_ids = set()
        self.gaps = []
        self.stats = {"unmatchedTasks": [], "skippedRuns": 0}
        self._build_geometry()
        self._build_tasks()
        # 生成器間で受け渡す部材レジストリ
        self.reg = {
            "tempMembers": [],        # prep-2/4 の仮設（引渡しで撤去）
            "retaining": [],
            "excTiles": [],           # (memberId, zoneId)
            "piles": [],
            "fndForms": {},           # zone -> [ids]
            "gradeForms": {},
            "footings": {},
            "sectionMembers": {},     # sectionNo -> [ids]
            "deckMembers": {},        # level -> [ids]（セル順）
            "scaffold": {},           # face -> [ids]
            "facePanels": {},         # face -> [ids]
            "cubicle": None,
            "cubiclePad": None,
            "evCars": [],
            "awps": {},               # level -> [actorIds]
            "zoneWallBoards": {},     # zone -> [ids]
            "zoneCeilings": {},       # zone -> [ids]
            "yardCount": 0,
        }

    # ------------------------------------------------ 幾何インデックス
    def _build_geometry(self):
        b = self.building
        self.ax_off = {a["name"]: a["offset"] / 1000.0 for a in b["grid"]["axesX"]}
        self.ay_off = {a["name"]: a["offset"] / 1000.0 for a in b["grid"]["axesY"]}
        self.ax_names = [a["name"] for a in b["grid"]["axesX"]]
        self.ay_names = [a["name"] for a in b["grid"]["axesY"]]
        self.ax_idx = {n: i for i, n in enumerate(self.ax_names)}
        self.ay_idx = {n: i for i, n in enumerate(self.ay_names)}
        self.ax_pos = [self.ax_off[n] for n in self.ax_names]
        self.ay_pos = [self.ay_off[n] for n in self.ay_names]
        self.struct_x = [self.ax_idx[n] for n in b["grid"]["structuralAxesX"]]
        self.struct_y = [self.ay_idx[n] for n in b["grid"]["structuralAxesY"]]

        def ranges_cells(ranges):
            cells = set()
            for r in ranges:
                for i in range(self.ax_idx[r["xFrom"]], self.ax_idx[r["xTo"]]):
                    for j in range(self.ay_idx[r["yFrom"]], self.ay_idx[r["yTo"]]):
                        cells.add((i, j))
            return cells

        self.levels = []
        self.level_by_id = {}
        for lv in b["levels"]:
            cells = ranges_cells(lv["footprint"])
            cfz = set()
            for c in b["structure"]["columnFreeZones"]:
                if lv["id"] in c["levels"]:
                    cfz |= ranges_cells(c["cellRanges"])
            solid = cells - cfz
            entry = {
                "id": lv["id"], "elev": lv["elevation"] / 1000.0,
                "fh": lv["floorHeight"] / 1000.0,
                "cells": cells, "cfz": cfz, "solid": solid,
            }
            self.levels.append(entry)
            self.level_by_id[lv["id"]] = entry
        self.top_level = self.levels[-1]
        # シャフト矩形と階別開口セル
        self.shafts = {s["id"]: s for s in b["shafts"]}
        self.shaft_rect = {}
        for sid, s in self.shafts.items():
            fp = s["footprint"]
            self.shaft_rect[sid] = (fp["x"] / 1000.0, fp["y"] / 1000.0,
                                    (fp["x"] + fp["w"]) / 1000.0, (fp["y"] + fp["d"]) / 1000.0)
        for entry in self.levels:
            openings = set()
            slab = next((s for s in b["slabs"] if s["level"] == entry["id"]), None)
            if slab:
                for sid in slab.get("openings", []):
                    if sid in self.shaft_rect:
                        openings |= self._rect_cells(self.shaft_rect[sid])
            entry["floor"] = entry["solid"] - openings
        # 屋根セル
        self.roof_cells = ranges_cells(b["roof"]["cellRanges"])
        self.roof_level_id = b["roof"]["topLevel"]
        roof_lv = self.level_by_id[self.roof_level_id]
        self.roof_z = roof_lv["elev"] + roof_lv["fh"]
        # 工区
        self.zones = {}
        for z in b["zones"]:
            self.zones[z["id"]] = {"id": z["id"], "level": z["level"],
                                   "cells": ranges_cells(z["cellRanges"])}
        # 柱位置（階別）: CP-0 の記録値と一致する導出（較正済み）
        exc = {}
        for e in b["grid"]["columnExceptions"]:
            name_x, name_y = e["at"].split("-")
            for lid in e["levels"]:
                exc.setdefault(lid, set()).add((self.ax_idx[name_x], self.ay_idx[name_y]))
        self.columns = {}
        for entry in self.levels:
            cols = set()
            for ai in self.struct_x:
                for aj in self.struct_y:
                    adj = [(ai - 1, aj - 1), (ai, aj - 1), (ai - 1, aj), (ai, aj)]
                    if not any(c in entry["cells"] for c in adj):
                        continue
                    if all(c in entry["cfz"] for c in adj):
                        continue
                    if (ai, aj) in exc.get(entry["id"], set()):
                        continue
                    cols.add((ai, aj))
            self.columns[entry["id"]] = cols
        # 部屋・壁
        self.rooms = {r["id"]: r for r in b["rooms"]}
        self.walls = b["walls"]
        # 敷地
        poly = b["site"]["polygon"]
        xs = [p[0] / 1000.0 for p in poly]
        ys = [p[1] / 1000.0 for p in poly]
        self.site_bbox = (min(xs), min(ys), max(xs), max(ys))
        self.gates = b["site"]["gates"]
        fp = self.level_by_id["L1"]["cells"]
        fxs = [self.cell_rect(c)[0] for c in fp] + [self.cell_rect(c)[2] for c in fp]
        fys = [self.cell_rect(c)[1] for c in fp] + [self.cell_rect(c)[3] for c in fp]
        self.fp_bbox = (min(fxs), min(fys), max(fxs), max(fys))
        self.centroid = ((self.fp_bbox[0] + self.fp_bbox[2]) / 2,
                         (self.fp_bbox[1] + self.fp_bbox[3]) / 2)
        # 敷地ポリゴン（m）と L1 フットプリント矩形群。仮囲い・ゲート・仮設配置の
        # ポリゴン判定（2026-11-11 実境界化）に使う
        self.site_poly = [(p[0] / 1000.0, p[1] / 1000.0) for p in poly]
        self.fp_rects = [self.cell_rect(c) for c in fp]
        # 入力観察: 敷地ポリゴン（placeholder 矩形）が建物平面を包まない場合は gap に記録
        sx0, sy0, sx1, sy1 = self.site_bbox
        fx0, fy0, fx1, fy1 = self.fp_bbox
        if fx0 < sx0 - 1e-9 or fy0 < sy0 - 1e-9 or fx1 > sx1 + 1e-9 or fy1 > sy1 + 1e-9:
            self.gaps.append({"kind": "sitePolygon", "status": "gap",
                              "note": f"敷地ポリゴン {self.site_bbox} が建物平面 {self.fp_bbox} を包んでいない"
                                      "（建物モデル側の placeholder 制限・要確認）。配置は平面基準で行い、検証は実効敷地で判定する"})
        self.depth = b["earthworks"][0]["depth"] / 1000.0 if b.get("earthworks") else 1.5
        # クレーン・ステーション（敷地内、建物外周）
        self.stations = self._crane_stations()

    def _rect_cells(self, rect):
        x0, y0, x1, y1 = rect
        cells = set()
        for i in range(len(self.ax_pos) - 1):
            for j in range(len(self.ay_pos) - 1):
                cx0, cy0, cx1, cy1 = self.cell_rect((i, j))
                if cx0 < x1 - 0.01 and cx1 > x0 + 0.01 and cy0 < y1 - 0.01 and cy1 > y0 + 0.01:
                    cells.add((i, j))
        return cells

    def cell_rect(self, c):
        i, j = c
        return (self.ax_pos[i], self.ay_pos[j], self.ax_pos[i + 1], self.ay_pos[j + 1])

    def cells_centroid(self, cells):
        rs = [self.cell_rect(c) for c in cells]
        return ((min(r[0] for r in rs) + max(r[2] for r in rs)) / 2,
                (min(r[1] for r in rs) + max(r[3] for r in rs)) / 2)

    def cells_bbox(self, cells):
        rs = [self.cell_rect(c) for c in cells]
        return (min(r[0] for r in rs), min(r[1] for r in rs),
                max(r[2] for r in rs), max(r[3] for r in rs))

    def point_cell(self, x, y):
        # 線形で十分（軸数は最大でも数十）
        i = 0
        for k in range(len(self.ax_pos) - 1):
            if self.ax_pos[k] <= x:
                i = k
        j = 0
        for k in range(len(self.ay_pos) - 1):
            if self.ay_pos[k] <= y:
                j = k
        return (i, j)

    def zone_of_point(self, x, y, level_id):
        cell = self.point_cell(x, y)
        cands = [z for z in self.zones.values() if z["level"] == level_id and cell in z["cells"]]
        if cands:
            return sorted(z["id"] for z in cands)[0]
        # 境界上などセルが属さない場合は最寄り工区（決定的）
        best, bestd = None, None
        for z in self.zones.values():
            if z["level"] != level_id:
                continue
            cx, cy = self.cells_centroid(z["cells"])
            d = (cx - x) ** 2 + (cy - y) ** 2
            if bestd is None or d < bestd or (d == bestd and z["id"] < best):
                best, bestd = z["id"], d
        return best

    def _crane_stations(self):
        step = float(self.rules["global"]["craneStationStepM"])
        off = float(self.rules["global"]["craneStationOffsetM"])
        x0, y0, x1, y1 = self.fp_bbox
        pts = []
        n = max(1, round((x1 - x0) / step))
        for k in range(n + 1):
            x = x0 + (x1 - x0) * k / n
            pts.append((x, y0 - off))
            pts.append((x, y1 + off))
        pts.append((x0 - off, (y0 + y1) / 2))
        pts.append((x1 + off, (y0 + y1) / 2))
        return pts

    def nearest_station(self, x, y):
        return min(self.stations, key=lambda p: ((p[0] - x) ** 2 + (p[1] - y) ** 2, p))

    def clamp_site_y(self, x, y, inset):
        """敷地南側に置くイベント・部材位置の y をポリゴン内へ寄せる。
        (x, y) が敷地ポリゴン内ならそのまま（矩形敷地では従来位置と一致）。
        外なら、その x における敷地最南境界 + inset を返す。"""
        if _point_in_poly(x, y, self.site_poly):
            return y
        hit = _cast_boundary(self.site_poly, "south", x)
        if hit is None:
            return y
        return hit[1] + inset

    def _build_tasks(self):
        self.tasks = {t["id"]: t for t in self.plan["tasks"]}
        self.game_tasks = {t["id"]: t for t in self.game["tasks"]}
        # 節→階の対応は計画のデッキタスクから読む
        self.sections = {}
        for t in self.plan["tasks"]:
            m = re.match(r"^frm-s(\d+)-(L\d+)-d$", t["id"])
            if m:
                self.sections.setdefault(int(m.group(1)), []).append(m.group(2))
        for v in self.sections.values():
            v.sort(key=lambda lid: self.level_by_id[lid]["elev"])

    # ------------------------------------------------ 出力の蓄積
    def add_actor(self, aid, kind, boxes, label=None, trade=None, headcount=None):
        if aid in self._actor_ids:
            return aid
        self._actor_ids.add(aid)
        a = {"id": aid, "kind": kind, "boxes": boxes, "faces": boxes * 6}
        if label:
            a["label"] = label
        if trade:
            a["trade"] = trade
        if headcount:
            a["headcount"] = headcount
        self.actors.append(a)
        return aid

    def add_member(self, kind, task_id, box, faces=6, basis="rule", zone=None, level=None, face=None):
        mid = f"m-{len(self.members) + 1:06d}"
        m = {"id": mid, "kind": kind, "task": task_id,
             "box": {"x": r3(box[0]), "y": r3(box[1]), "z": r3(box[2]),
                     "dx": r3(box[3]), "dy": r3(box[4]), "dz": r3(box[5])},
             "faces": faces, "basis": basis}
        if zone:
            m["zone"] = zone
        if level:
            m["level"] = level
        if face:
            m["face"] = face
        self.members.append(m)
        return mid

    def task_time(self, task_id, u):
        t = self.tasks[task_id]
        real = t["es"] + u * (t["ef"] - t["es"])
        gt = self.game_tasks.get(task_id)
        if gt:
            g0 = gt["gameStart"] - 1
            game = g0 + u * (gt["gameEnd"] - g0)
        else:
            game = None
        return real, game

    def add_event(self, etype, task_id, u, member=None, members=None, actor=None,
                  at=None, via=None, state=None, note=None, u_end=None):
        real, game = self.task_time(task_id, u)
        e = {"id": f"e-{len(self.events) + 1:06d}", "type": etype, "task": task_id,
             "u": r3(u), "t": r3(real)}
        if game is not None:
            e["g"] = r3(game)
        if member:
            e["member"] = member
        if members:
            e["members"] = members
        if actor:
            e["actor"] = actor
        if at is not None:
            e["at"] = [r3(at[0]), r3(at[1]), r3(at[2])]
        if via is not None:
            e["via"] = [r3(via[0]), r3(via[1]), r3(via[2])]
        if state:
            e["state"] = state
        if note:
            e["note"] = note
        if u_end is not None:
            e["uEnd"] = r3(u_end)
        self.events.append(e)
        return e

    def work_event(self, task, trade, at, u0=0.05, u1=0.95):
        crew = self.rules["global"]["crewByTrade"].get(trade, 3)
        aid = self.add_actor(f"crew:{trade}", "crew", boxes=crew * 2, trade=trade, headcount=crew)
        self.add_event("work", task["id"], u0, actor=aid, at=(at[0], at[1], at[2] if len(at) > 2 else 0.0), u_end=u1)

    def place_spread(self, task_id, member_ids, u0, u1, etype="place"):
        n = len(member_ids)
        for k, mid in enumerate(member_ids):
            u = u0 + (k + 0.5) / n * (u1 - u0) if n else u0
            self.add_event(etype, task_id, min(u, 0.999), member=mid)

    def bulk_state(self, task_id, member_ids, state, u, chunk=100):
        for k in range(0, len(member_ids), chunk):
            self.add_event("state", task_id, u, members=member_ids[k:k + chunk], state=state)

    def bulk_remove(self, task_id, member_ids, u, chunk=100):
        for k in range(0, len(member_ids), chunk):
            self.add_event("remove", task_id, u, members=member_ids[k:k + chunk])


def spread_u(k, n, u0, u1):
    return u0 + (k + 0.5) / n * (u1 - u0) if n else u0


# ---------------------------------------------------------------- 敷地ポリゴン幾何
# 2026-11-11: 敷地ポリゴン実境界化（蘇我=道路街区由来、亀有=OSM landuse 由来の
# 非矩形ポリゴン）に対応するための純 stdlib 幾何。矩形ポリゴンでは従来の
# bbox 基準配置と一致する結果を返すこと（回帰条件）。

def _point_in_poly(x, y, poly):
    """レイキャスティング。辺上の点は内側扱い。"""
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        # 辺上判定（線分までの距離がほぼ 0）
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        if L2 > 0:
            t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / L2))
            if math.hypot(x - (x0 + dx * t), y - (y0 + dy * t)) < 1e-9:
                return True
    inside = False
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xin = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xin:
                inside = not inside
    return inside


def _seg_intersect(a, b, c, d):
    def cr(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2 = cr(c, d, a), cr(c, d, b)
    d3, d4 = cr(a, b, c), cr(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _rect_in_poly(rx0, ry0, rx1, ry1, poly):
    pts = [(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1),
           ((rx0 + rx1) / 2, (ry0 + ry1) / 2), ((rx0 + rx1) / 2, ry0),
           ((rx0 + rx1) / 2, ry1), (rx0, (ry0 + ry1) / 2), (rx1, (ry0 + ry1) / 2)]
    if not all(_point_in_poly(x, y, poly) for x, y in pts):
        return False
    rect_edges = [((rx0, ry0), (rx1, ry0)), ((rx1, ry0), (rx1, ry1)),
                  ((rx1, ry1), (rx0, ry1)), ((rx0, ry1), (rx0, ry0))]
    n = len(poly)
    for i in range(n):
        e = (poly[i], poly[(i + 1) % n])
        for re_ in rect_edges:
            if _seg_intersect(e[0], e[1], re_[0], re_[1]):
                return False
    return True


def _box_hits_rects(box, rects):
    """box=(x0,y0,x1,y1) が矩形群のいずれかと面積を持って重なるか（SV-01 ハードゲートと同じ基準）。"""
    bx0, by0, bx1, by1 = box
    for (rx0, ry0, rx1, ry1) in rects:
        if bx1 > rx0 + 1e-6 and bx0 < rx1 - 1e-6 and by1 > ry0 + 1e-6 and by0 < ry1 - 1e-6:
            return True
    return False


def _rect_dist(box, rects):
    """box と矩形群の最小距離（重なれば 0）。"""
    bx0, by0, bx1, by1 = box
    best = None
    for (rx0, ry0, rx1, ry1) in rects:
        dx = max(rx0 - bx1, bx0 - rx1, 0.0)
        dy = max(ry0 - by1, by0 - ry1, 0.0)
        d = math.hypot(dx, dy)
        if best is None or d < best:
            best = d
    return best if best is not None else 0.0


def _cast_boundary(poly, side, at):
    """side 方向の境界キャスト。south/north は鉛直線 x=at との交点の最南/最北、
    west/east は水平線 y=at との交点の最西/最東を返す。
    戻り値 (x, y, edge_idx, t) または None（交わらない）。同点が複数辺にある場合は
    side と平行な辺（南・北なら水平辺、西・東なら垂直辺）を優先する。"""
    hits = []
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if side in ("south", "north"):
            if abs(x1 - x0) < 1e-12:
                if abs(x0 - at) < 1e-9:
                    hits += [(x0, y0, i, 0.0), (x1, y1, i, 1.0)]
            elif min(x0, x1) - 1e-9 <= at <= max(x0, x1) + 1e-9:
                t = (at - x0) / (x1 - x0)
                hits.append((at, y0 + t * (y1 - y0), i, t))
        else:
            if abs(y1 - y0) < 1e-12:
                if abs(y0 - at) < 1e-9:
                    hits += [(x0, y0, i, 0.0), (x1, y1, i, 1.0)]
            elif min(y0, y1) - 1e-9 <= at <= max(y0, y1) + 1e-9:
                t = (at - y0) / (y1 - y0)
                hits.append((x0 + t * (x1 - x0), at, i, t))
    if not hits:
        return None
    if side == "south":
        ext = min(h[1] for h in hits)
        cand = [h for h in hits if abs(h[1] - ext) < 1e-9]
    elif side == "north":
        ext = max(h[1] for h in hits)
        cand = [h for h in hits if abs(h[1] - ext) < 1e-9]
    elif side == "west":
        ext = min(h[0] for h in hits)
        cand = [h for h in hits if abs(h[0] - ext) < 1e-9]
    else:
        ext = max(h[0] for h in hits)
        cand = [h for h in hits if abs(h[0] - ext) < 1e-9]
    if len(cand) > 1:
        def par(h):
            x0, y0 = poly[h[2]]
            x1, y1 = poly[(h[2] + 1) % n]
            L = math.hypot(x1 - x0, y1 - y0) or 1.0
            return abs((x1 - x0) / L) if side in ("south", "north") else abs((y1 - y0) / L)
        cand.sort(key=lambda h: (-par(h), h[2]))
    return cand[0]


def _ring_walk(edges, edge_i, t, offset):
    """ポリゴン周上を (edge_i, t) から arc-length offset（符号付き、頂点順方向が正）へ移動。
    edges は (x0, y0, x1, y1, L, ux, uy) の列。戻り値 (x, y, edge_j, t_j)。"""
    n = len(edges)
    i = edge_i
    s = t * edges[i][4]
    rem = offset
    while rem > 0:
        avail = edges[i][4] - s
        if rem <= avail:
            s += rem
            rem = 0.0
        else:
            rem -= avail
            i = (i + 1) % n
            s = 0.0
    while rem < 0:
        if -rem <= s:
            s += rem
            rem = 0.0
        else:
            rem += s
            i = (i - 1) % n
            s = edges[i][4]
    x0, y0, x1, y1, L, ux, uy = edges[i]
    tt = s / L if L > 0 else 0.0
    return (x0 + (x1 - x0) * tt, y0 + (y1 - y0) * tt, i, tt)


# ---------------------------------------------------------------- 生成器
def gen_action_only(ctx: Ctx, task, rule):
    pos = ctx.reg.get("officePos") or (ctx.site_bbox[0] + 8, ctx.site_bbox[1] + 4, 0)
    ctx.add_event("action", task["id"], 0.5, at=(pos[0], pos[1], 0.0),
                  note=rule.get("desc", ""))
    ctx.work_event(task, task["trade"], (pos[0], pos[1]))


def gen_site_setup(ctx: Ctx, task, rule):
    # 2026-11-11 実境界化: 仮囲い・ゲートは敷地ポリゴン（非矩形あり）の辺上に置く。
    # ゲート位置は atMm のキャスト（南・北は x=atMm の最南/最北交点、西・東は
    # y=atMm の最西/最東交点）で決める。矩形ポリゴンでは従来の bbox 配置と一致する。
    # ゲートボックスが建物フットプリントと重なる場合は、重ならない位置まで
    # 境界を沿って決定的にずらす（ずらせなければ gap）。仮囲いピースも同様に、
    # フットプリントと重なるピースだけを局所的に分割して辺上に収める。
    poly = ctx.site_poly
    tid = task["id"]
    n = len(poly)
    edges = []
    for k in range(n):
        x0, y0 = poly[k]
        x1, y1 = poly[(k + 1) % n]
        length = math.hypot(x1 - x0, y1 - y0) or 1e-9
        edges.append((x0, y0, x1, y1, length, (x1 - x0) / length, (y1 - y0) / length))
    sx0, sy0, sx1, sy1 = ctx.site_bbox

    def gate_box_at(x, y, ei, w):
        ux, uy = edges[ei][5], edges[ei][6]
        dx = abs(ux) * w + abs(uy) * 0.3
        dy = abs(uy) * w + abs(ux) * 0.3
        return (x - dx / 2, y - dy / 2, dx, dy)

    # --- ゲート配置（キャスト＋必要なら境界沿いの移動）
    placed = {}       # gate index -> (x, y, edge_idx)
    gate_skips = {}   # edge_idx -> [(along, width)]
    for gi, g in enumerate(ctx.gates):
        at = g["atMm"] / 1000.0
        w = g["width"] / 1000.0
        hit = _cast_boundary(poly, g["edge"], at)
        if hit is None:
            # atMm のキャスト線が敷地ポリゴンと交わらないゲートは発明して置かない
            ctx.gaps.append({"kind": "siteGate", "status": "gap",
                             "note": f"ゲート「{g['name']}」({g['edge']}) の atMm={g['atMm']} のキャスト線が"
                                     f"敷地ポリゴンと交わらない。建物モデル側の要確認事項として配置しない"})
            continue
        x, y, ei, t = hit
        bx = gate_box_at(x, y, ei, w)
        if _box_hits_rects((bx[0], bx[1], bx[0] + bx[2], bx[1] + bx[3]), ctx.fp_rects):
            found = None
            for k in range(1, 81):
                for sgn in (1, -1):
                    wx, wy, wi, wt = _ring_walk(edges, ei, t, sgn * k * 0.5)
                    wb = gate_box_at(wx, wy, wi, w)
                    if not _box_hits_rects((wb[0], wb[1], wb[0] + wb[2], wb[1] + wb[3]), ctx.fp_rects):
                        found = (wx, wy, wi, wt)
                        break
                if found:
                    break
            if not found:
                ctx.gaps.append({"kind": "siteGate", "status": "gap",
                                 "note": f"ゲート「{g['name']}」({g['edge']}) は境界沿いに建物フットプリントと"
                                         f"重ならない配置位置が無い。建物モデル側の要確認事項として配置しない"})
                continue
            x, y, ei, t = found
        placed[gi] = (x, y, ei)
        # フェンス間引き登録: 配置点のある辺（頂点上なら隣接辺にも）へ along 位置を記録
        regs = [(ei, t * edges[ei][4])]
        if t < 1e-6:
            regs.append(((ei - 1) % n, edges[(ei - 1) % n][4]))
        if t > 1 - 1e-6:
            regs.append(((ei + 1) % n, 0.0))
        for (ej, along) in regs:
            gate_skips.setdefault(ej, []).append((along, w))
    # 配置済みゲート位置を他生成器（引込位置の目安）へ共有
    ctx.reg["gatePlaced"] = {gi: (placed[gi][0], placed[gi][1]) for gi in placed}

    # --- 仮囲い（辺ごと。ゲート範囲は間引き、フットプリントと重なるピースは局所分割）
    fence_ids = []
    for k in range(n):
        x0, y0, x1, y1, length, ux, uy = edges[k]
        cnt = max(1, int(length // 6.0))
        for s in range(cnt):
            seg_ids = []
            stack = [(length * s / cnt, length * (s + 1) / cnt)]
            while stack:
                d0, d1 = stack.pop()
                mid = (d0 + d1) / 2
                if any(abs(mid - along) < w / 2 for along, w in gate_skips.get(k, [])):
                    continue
                cx, cy = x0 + ux * mid, y0 + uy * mid
                L = d1 - d0
                dx = abs(ux) * L + abs(uy) * 0.1
                dy = abs(uy) * L + abs(ux) * 0.1
                if L > 0.75 and _box_hits_rects((cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2), ctx.fp_rects):
                    stack.append((d0, mid))
                    stack.append((mid, d1))
                    continue
                seg_ids.append(ctx.add_member("tempFence", tid,
                                              (cx - dx / 2, cy - dy / 2, 0.0, dx, dy, 3.0), basis="default"))
            fence_ids.extend(reversed(seg_ids))
    # --- ゲート部材
    gate_ids = []
    for gi, g in enumerate(ctx.gates):
        if gi not in placed:
            continue
        x, y, ei = placed[gi]
        w = g["width"] / 1000.0
        bx = gate_box_at(x, y, ei, w)
        gate_ids.append(ctx.add_member("tempGate", tid, (bx[0], bx[1], 0.0, bx[2], bx[3], 3.0), basis="default"))
    # --- 仮設事務所クラスタ（南西の空地。実境界では bbox 左下が区画外になり得るため、
    # 従来位置がポリゴン外・建物近接なら、ポリゴン内の空地を決定的に探す）
    office_ids = []
    ox, oy = sx0 + 3.0, sy0 + 2.0
    cluster = (ox, oy, ox + 31.0, oy + 4.0)
    if not (_rect_in_poly(*cluster, poly) and not _box_hits_rects(cluster, ctx.fp_rects)):
        found = None
        for ddx in range(0, 301):
            for ddy in range(0, 121):
                cx0, cy0 = sx0 + 3.0 + ddx, sy0 + 2.0 + ddy
                c = (cx0, cy0, cx0 + 31.0, cy0 + 4.0)
                if _rect_in_poly(*c, poly) and _rect_dist(c, ctx.fp_rects) >= 3.0:
                    found = (cx0, cy0)
                    break
            if found:
                break
        if found:
            ox, oy = found
        else:
            ctx.gaps.append({"kind": "siteOffice", "status": "gap",
                             "note": "仮設事務所クラスタ（31m×4m）の配置可能な空地が敷地ポリゴン内に"
                                     "見つからない。従来位置（bbox 左下）に仮置きする"})
    office_ids.append(ctx.add_member("tempOffice", tid, (ox, oy, 0.0, 10.0, 4.0, 3.0), basis="default"))
    office_ids.append(ctx.add_member("tempOffice", tid, (ox + 12.0, oy, 0.0, 8.0, 4.0, 3.0), basis="default"))
    office_ids.append(ctx.add_member("tempToilet", tid, (ox + 22.0, oy, 0.0, 4.0, 3.0, 2.6), basis="default"))
    office_ids.append(ctx.add_member("tempSmoking", tid, (ox + 28.0, oy, 0.0, 3.0, 3.0, 2.6), basis="default"))
    ctx.reg["officePos"] = (ox + 5.0, oy + 2.0, 0.0)
    ctx.reg["tempMembers"] += fence_ids + gate_ids + office_ids
    order = fence_ids + gate_ids + office_ids
    ctx.place_spread(tid, order, 0.05, 0.9)
    ctx.work_event(task, "仮設", (ctx.centroid[0], ctx.clamp_site_y(ctx.centroid[0], ctx.site_bbox[1] + 6, 6.0)))


def gen_survey(ctx: Ctx, task, rule):
    x0, y0, x1, y1 = ctx.fp_bbox
    ids = []
    for cx, cy in [(x0 - 1.5, y0 - 1.5), (x1 + 1.5, y0 - 1.5), (x0 - 1.5, y1 + 1.5), (x1 + 1.5, y1 + 1.5)]:
        ids.append(ctx.add_member("batterBoard", task["id"], (cx - 0.9, cy - 0.15, 0.0, 1.8, 0.3, 1.0), basis="default"))
    ctx.place_spread(task["id"], ids, 0.1, 0.6)
    ctx.reg["tempMembers"] += ids
    ctx.work_event(task, "墨出し", ctx.centroid)


def gen_temp_utility(ctx: Ctx, task, rule):
    south_gates = [g for g in ctx.gates if g["edge"] == "south"]
    gx = (south_gates[0]["atMm"] / 1000.0) if south_gates else ctx.centroid[0]
    gy = ctx.clamp_site_y(gx, ctx.fp_bbox[1] - 3.0, 3.0)
    pole = ctx.add_member("tempPole", task["id"], (gx, gy, 0.0, 0.3, 0.3, 7.0), basis="default")
    panel = ctx.add_member("tempPanel", task["id"], (gx + 1.2, gy, 0.0, 1.2, 0.4, 1.8), basis="default")
    ctx.reg["tempMembers"] += [pole, panel]
    ctx.place_spread(task["id"], [pole, panel], 0.2, 0.7)
    ctx.work_event(task, "設備", (gx, gy))


def _boundary_runs(ctx: Ctx, cells):
    """セル集合の外周を、共線な単位辺のランにまとめる。[(x0,y0,x1,y1,side)]"""
    runs = []
    # 南辺（セルの下側）と北辺
    for side in ("S", "N", "W", "E"):
        segs = []
        for (i, j) in cells:
            x0, y0, x1, y1 = ctx.cell_rect((i, j))
            if side == "S" and (i, j - 1) not in cells:
                segs.append((x0, y0, x1, y0))
            if side == "N" and (i, j + 1) not in cells:
                segs.append((x0, y1, x1, y1))
            if side == "W" and (i - 1, j) not in cells:
                segs.append((x0, y0, x0, y1))
            if side == "E" and (i + 1, j) not in cells:
                segs.append((x1, y0, x1, y1))
        segs.sort()
        cur = None
        for s in segs:
            if cur and abs(cur[2] - s[0]) < 1e-9 and abs(cur[3] - s[1]) < 1e-9:
                cur = (cur[0], cur[1], s[2], s[3])
            else:
                if cur:
                    runs.append((*cur, side))
                cur = s
        if cur:
            runs.append((*cur, side))
    return runs


def gen_retaining(ctx: Ctx, task, rule):
    cells = ctx.level_by_id["L1"]["cells"]
    runs = _boundary_runs(ctx, cells)
    ids = []
    for (x0, y0, x1, y1, side) in runs:
        length = math.hypot(x1 - x0, y1 - y0)
        cnt = max(1, math.ceil(length / 3.6))
        for k in range(cnt):
            t0, t1 = k / cnt, (k + 1) / cnt
            cx = x0 + (x1 - x0) * (t0 + t1) / 2
            cy = y0 + (y1 - y0) * (t0 + t1) / 2
            L = length / cnt
            horiz = abs(y1 - y0) < 1e-9
            # 外側へ 0.15 ずらす
            ox, oy = 0.0, 0.0
            if side == "S":
                oy = -0.15
            elif side == "N":
                oy = 0.15
            elif side == "W":
                ox = -0.15
            else:
                ox = 0.15
            box = (cx + ox - (L if horiz else 0.25) / 2, cy + oy - (0.25 if horiz else L) / 2,
                   -ctx.depth - 0.3, L if horiz else 0.25, 0.25 if horiz else L, ctx.depth + 0.8)
            ids.append(ctx.add_member("retainingPanel", task["id"], box, basis="inferred"))
    ctx.reg["retaining"] = ids
    ctx.place_spread(task["id"], ids, 0.03, 0.95)
    ctx.work_event(task, "土工", ctx.centroid)


def _run_rect(ctx: Ctx, run):
    x0 = ctx.cell_rect(run[0])[0]
    x1 = ctx.cell_rect(run[-1])[2]
    y0 = ctx.cell_rect(run[0])[1]
    y1 = ctx.cell_rect(run[0])[3]
    return (x0, y0, x1, y1)


def _row_run_boxes(ctx: Ctx, cells):
    """面状の進捗表現（掘削底・捨てコン・防水シート等）を行ごとの連続ランに集約した
    ボックス列。地表面・シートはロール/帯で進むため、セル単位ではなく帯単位が実態。
    集約方針は scene_rules.json の aggregation に記録。"""
    rows = {}
    for c in cells:
        rows.setdefault(c[1], []).append(c)
    out = []
    for j in sorted(rows):
        cs = sorted(rows[j])
        run = [cs[0]]
        for c in cs[1:]:
            if c[0] == run[-1][0] + 1:
                run.append(c)
            else:
                out.append(_run_rect(ctx, run))
                run = [c]
        out.append(_run_rect(ctx, run))
    return out


def _bay_boxes(ctx: Ctx, cells):
    """セルを（行 × 構造スパン）でグループ化したボックス列。デッキプレート・配筋マット・
    土間は構造ベイ単位で施工されるため、ベイ単位を1部材とする（集約方針は rules に記録）。"""
    import bisect
    sidx = sorted(ctx.ax_pos[a] for a in ctx.struct_x)
    groups = {}
    for c in cells:
        x0, y0, x1, y1 = ctx.cell_rect(c)
        bay = bisect.bisect_right(sidx, (x0 + x1) / 2 + 1e-9) - 1
        groups.setdefault((c[1], bay), []).append(c)
    out = []
    for key in sorted(groups):
        out.append(_run_rect(ctx, sorted(groups[key])))
    return out


def gen_excavation(ctx: Ctx, task, rule):
    cells = sorted(ctx.level_by_id["L1"]["cells"], key=lambda c: (c[1], c[0]))
    ids = []
    for (x0, y0, x1, y1) in _row_run_boxes(ctx, cells):
        mid = ctx.add_member("excavationTile", task["id"],
                             (x0, y0, -ctx.depth - 0.3, x1 - x0, y1 - y0, 0.3), basis="rule")
        ids.append(mid)
        zone = ctx.zone_of_point((x0 + x1) / 2, (y0 + y1) / 2, "L1")
        ctx.reg["excTiles"].append((mid, zone))
    ctx.place_spread(task["id"], ids, 0.02, 0.98)
    ex = ctx.add_actor("machine:excavator-1", "excavator", boxes=10, label="ユンボ")
    du = ctx.add_actor("machine:dump-1", "dumpTruck", boxes=8, label="ダンプ")
    for k, frac in enumerate((0.15, 0.5, 0.85)):
        c = cells[int(frac * (len(cells) - 1))]
        x0, y0, x1, y1 = ctx.cell_rect(c)
        ctx.add_event("move", task["id"], frac, actor=ex, at=((x0 + x1) / 2, (y0 + y1) / 2, -ctx.depth))
        ev_x = ctx.gates[0]["atMm"] / 1000.0 if ctx.gates else (x0 + x1) / 2
        ctx.add_event("move", task["id"], min(frac + 0.05, 0.99), actor=du,
                      at=(ev_x, ctx.clamp_site_y(ev_x, ctx.site_bbox[1] + 2, 2.0), 0.0))
    ctx.work_event(task, "土工", ctx.centroid)


def gen_blinding(ctx: Ctx, task, rule):
    cells = sorted(ctx.level_by_id["L1"]["cells"], key=lambda c: (c[1], c[0]))
    ids = []
    for (x0, y0, x1, y1) in _row_run_boxes(ctx, cells):
        ids.append(ctx.add_member("blinding", task["id"],
                                  (x0, y0, -ctx.depth, x1 - x0, y1 - y0, 0.06), basis="rule"))
    ctx.place_spread(task["id"], ids, 0.05, 0.6)
    # 地下ピット（EVシャフト直下）
    pit_ids = []
    for sid, s in sorted(ctx.shafts.items()):
        if s["kind"] != "EV":
            continue
        x0, y0, x1, y1 = ctx.shaft_rect[sid]
        pit_ids.append(ctx.add_member("pitFloor", task["id"], (x0, y0, -2.7, x1 - x0, y1 - y0, 0.2), basis="inferred"))
        pit_ids.append(ctx.add_member("pitWall", task["id"], (x0, y0, -2.7, x1 - x0, 0.25, 1.2), basis="inferred"))
        pit_ids.append(ctx.add_member("pitWall", task["id"], (x0, y1 - 0.25, -2.7, x1 - x0, 0.25, 1.2), basis="inferred"))
        pit_ids.append(ctx.add_member("pitWall", task["id"], (x0, y0, -2.7, 0.25, y1 - y0, 1.2), basis="inferred"))
        pit_ids.append(ctx.add_member("pitWall", task["id"], (x1 - 0.25, y0, -2.7, 0.25, y1 - y0, 1.2), basis="inferred"))
    ctx.place_spread(task["id"], pit_ids, 0.6, 0.95)
    ctx.work_event(task, "土工", ctx.centroid)


def _pile_member(ctx: Ctx, task_id, ai, aj):
    """杭1本。天端は杭頭処理後の -1.35m、杭長は既定12m（地盤未特定のため default）。"""
    x = ctx.ax_pos[ai]
    y = ctx.ay_pos[aj]
    z_bottom = -(ctx.depth + 12.0)
    return ctx.add_member("pile", task_id,
                          (x - 0.45, y - 0.45, z_bottom, 0.9, 0.9, -1.35 - z_bottom),
                          basis="rule")


def gen_pile_test(ctx: Ctx, task, rule):
    cols = sorted(ctx.columns["L1"], key=lambda p: (ctx.ay_pos[p[1]], ctx.ax_pos[p[0]]))
    ai, aj = cols[0]
    mid = _pile_member(ctx, task["id"], ai, aj)
    ctx.reg["piles"].append(mid)
    rig = ctx.add_actor("machine:pile-rig", "pileDriver", boxes=10, label="杭打ち機")
    ctx.add_event("move", task["id"], 0.2, actor=rig, at=(ctx.ax_pos[ai], ctx.ay_pos[aj], 0.0))
    ctx.add_event("place", task["id"], 0.6, member=mid)
    ctx.work_event(task, "杭", (ctx.ax_pos[ai], ctx.ay_pos[aj]))


def gen_piles(ctx: Ctx, task, rule):
    cols = sorted(ctx.columns["L1"], key=lambda p: (ctx.ay_pos[p[1]], ctx.ax_pos[p[0]]))
    rig = ctx.add_actor("machine:pile-rig", "pileDriver", boxes=10, label="杭打ち機")
    ids = []
    for k, (ai, aj) in enumerate(cols):
        if k == 0:
            continue  # 試験杭で打設済みの位置は pile-1 側に部材がある
        mid = _pile_member(ctx, task["id"], ai, aj)
        ids.append(mid)
        u = spread_u(len(ids) - 1, len(cols) - 1, 0.03, 0.97)
        ctx.add_event("place", task["id"], u, member=mid)
        if k % 15 == 0:
            ctx.add_event("move", task["id"], u, actor=rig, at=(ctx.ax_pos[ai], ctx.ay_pos[aj], 0.0))
    ctx.reg["piles"] += ids
    ctx.work_event(task, "杭", ctx.centroid)


def gen_pile_head(ctx: Ctx, task, rule):
    ctx.bulk_state(task["id"], ctx.reg["piles"], "杭頭処理", 0.5)


def _grade_beam_runs(ctx: Ctx, level_id="L1"):
    """全軸線の下の基礎梁ラン（共線連続区間）。[(x0,y0,x1,y1)]"""
    cells = ctx.level_by_id[level_id]["cells"]
    runs = []
    # X方向ライン（Y軸ごと）
    for j in range(len(ctx.ay_pos)):
        cur = None
        for i in range(len(ctx.ax_pos) - 1):
            inside = (i, j - 1) in cells or (i, j) in cells
            if inside:
                if cur is None:
                    cur = [ctx.ax_pos[i], ctx.ay_pos[j], ctx.ax_pos[i + 1], ctx.ay_pos[j]]
                else:
                    cur[2] = ctx.ax_pos[i + 1]
            else:
                if cur:
                    runs.append(tuple(cur))
                    cur = None
        if cur:
            runs.append(tuple(cur))
    for i in range(len(ctx.ax_pos)):
        cur = None
        for j in range(len(ctx.ay_pos) - 1):
            inside = (i - 1, j) in cells or (i, j) in cells
            if inside:
                if cur is None:
                    cur = [ctx.ax_pos[i], ctx.ay_pos[j], ctx.ax_pos[i], ctx.ay_pos[j + 1]]
                else:
                    cur[3] = ctx.ay_pos[j + 1]
            else:
                if cur:
                    runs.append(tuple(cur))
                    cur = None
        if cur:
            runs.append(tuple(cur))
    return runs


def gen_footing_form(ctx: Ctx, task, rule):
    zone_id = re.match(r"^fnd-(.+)-1$", task["id"]).group(1)
    tid = task["id"]
    fnd = ctx.building["foundations"]["footings"]
    w = fnd["size"]["w"] / 1000.0
    top = fnd["topElevation"] / 1000.0
    th = fnd["thickness"] / 1000.0
    form_ids, beam_ids = [], []
    cols = sorted(ctx.columns["L1"], key=lambda p: (ctx.ay_pos[p[1]], ctx.ax_pos[p[0]]))
    for (ai, aj) in cols:
        x, y = ctx.ax_pos[ai], ctx.ay_pos[aj]
        if ctx.zone_of_point(x, y, "L1") != zone_id:
            continue
        form_ids.append(ctx.add_member("footingForm", tid,
                                       (x - w / 2 - 0.15, y - w / 2 - 0.15, top - th, w + 0.3, w + 0.3, th),
                                       basis="rule", zone=zone_id, level="L1"))
    for (x0, y0, x1, y1) in _grade_beam_runs(ctx):
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if ctx.zone_of_point(mx, my, "L1") != zone_id:
            continue
        horiz = abs(y1 - y0) < 1e-9
        L = abs(x1 - x0) if horiz else abs(y1 - y0)
        box = (min(x0, x1) - (0 if horiz else 0.45), min(y0, y1) - (0.45 if horiz else 0),
               top - th, L if horiz else 0.9, 0.9 if horiz else L, th)
        beam_ids.append(ctx.add_member("gradeBeamForm", tid, box, basis="rule", zone=zone_id, level="L1"))
    ctx.reg["fndForms"][zone_id] = form_ids
    ctx.reg["gradeForms"][zone_id] = beam_ids
    ctx.place_spread(tid, form_ids + beam_ids, 0.05, 0.95)
    cx, cy = ctx.cells_centroid(ctx.zones[zone_id]["cells"])
    ctx.work_event(task, "基礎", (cx, cy))


def gen_footing_pour(ctx: Ctx, task, rule):
    zone_id = re.match(r"^fnd-(.+)-2$", task["id"]).group(1)
    tid = task["id"]
    fnd = ctx.building["foundations"]["footings"]
    w = fnd["size"]["w"] / 1000.0
    top = fnd["topElevation"] / 1000.0
    th = fnd["thickness"] / 1000.0
    ids = []
    cols = sorted(ctx.columns["L1"], key=lambda p: (ctx.ay_pos[p[1]], ctx.ax_pos[p[0]]))
    for (ai, aj) in cols:
        x, y = ctx.ax_pos[ai], ctx.ay_pos[aj]
        if ctx.zone_of_point(x, y, "L1") != zone_id:
            continue
        ids.append(ctx.add_member("footing", tid, (x - w / 2, y - w / 2, top - th, w, w, th),
                                  basis="rule", zone=zone_id, level="L1"))
    beam_ids = []
    for (x0, y0, x1, y1) in _grade_beam_runs(ctx):
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if ctx.zone_of_point(mx, my, "L1") != zone_id:
            continue
        horiz = abs(y1 - y0) < 1e-9
        L = abs(x1 - x0) if horiz else abs(y1 - y0)
        box = (min(x0, x1) - (0 if horiz else 0.35), min(y0, y1) - (0.35 if horiz else 0),
               top - th, L if horiz else 0.7, 0.7 if horiz else L, th)
        beam_ids.append(ctx.add_member("gradeBeam", tid, box, basis="rule", zone=zone_id, level="L1"))
    ctx.reg["footings"][zone_id] = ids
    ctx.reg["gradeBeams"] = beam_ids
    ctx.place_spread(tid, ids + beam_ids, 0.05, 0.85)
    ctx.bulk_state(tid, ids + beam_ids, "養生", 0.95)
    pump = ctx.add_actor("machine:pump", "pumpTruck", boxes=9, label="ポンプ車")
    cx, cy = ctx.cells_centroid(ctx.zones[zone_id]["cells"])
    ctx.add_event("move", tid, 0.1, actor=pump, at=(cx, ctx.fp_bbox[1] - 5, 0.0))
    ctx.work_event(task, "コンクリート", (cx, cy))


def gen_backfill(ctx: Ctx, task, rule):
    zone_id = re.match(r"^fnd-(.+)-3$", task["id"]).group(1)
    tid = task["id"]
    forms = ctx.reg["fndForms"].get(zone_id, []) + ctx.reg["gradeForms"].get(zone_id, [])
    ctx.bulk_remove(tid, forms, 0.3)
    tiles = [mid for (mid, z) in ctx.reg["excTiles"] if z == zone_id]
    ctx.bulk_state(tid, tiles, "埋戻し", 0.7)
    # 最後の埋戻しタスクで山留めを撤去
    fnd3 = [t for t in ctx.plan["tasks"] if re.match(r"^fnd-.+-3$", t["id"])]
    if task["id"] == max(fnd3, key=lambda t: t["ef"])["id"]:
        ctx.bulk_remove(tid, ctx.reg["retaining"], 0.9)
    cx, cy = ctx.cells_centroid(ctx.zones[zone_id]["cells"])
    ctx.work_event(task, "基礎", (cx, cy))


# ---------------------------------------------------------------- 躯体
def _girder_box(x0, y0, x1, y1, z_top, girder_d):
    """大梁1本のボックス。せい girder_d（鉛直）、フランジ幅 0.35。"""
    horiz = abs(y1 - y0) < 1e-9
    L = abs(x1 - x0) if horiz else abs(y1 - y0)
    if horiz:
        return (min(x0, x1), y0 - 0.175, z_top - girder_d, L, 0.35, girder_d)
    return (x0 - 0.175, min(y0, y1), z_top - girder_d, 0.35, L, girder_d)


def _girder_segments(ctx: Ctx, level_id):
    """その階のスラブ片に支持される大梁区間（スパン単位、吹抜けで分断）。
    戻り値: [(x0,y0,x1,y1)]（水平区間）。level_id='ROOF' で屋根セルを使う。"""
    if level_id == "ROOF":
        cells = ctx.roof_cells
    else:
        cells = ctx.level_by_id[level_id]["solid"]
    segs = []
    # X方向（Y構造軸のライン上を X構造軸のスパンで）
    for aj in ctx.struct_y:
        for k in range(len(ctx.struct_x) - 1):
            ai0, ai1 = ctx.struct_x[k], ctx.struct_x[k + 1]
            # スパン内の全単位セルについて、両側どちらかにスラブ片があること
            ok = True
            for i in range(ai0, ai1):
                if (i, aj - 1) not in cells and (i, aj) not in cells:
                    ok = False
                    break
            if ok:
                segs.append((ctx.ax_pos[ai0], ctx.ay_pos[aj], ctx.ax_pos[ai1], ctx.ay_pos[aj]))
    for ai in ctx.struct_x:
        for k in range(len(ctx.struct_y) - 1):
            aj0, aj1 = ctx.struct_y[k], ctx.struct_y[k + 1]
            ok = True
            for j in range(aj0, aj1):
                if (ai - 1, j) not in cells and (ai, j) not in cells:
                    ok = False
                    break
            if ok:
                segs.append((ctx.ax_pos[ai], ctx.ay_pos[aj0], ctx.ax_pos[ai], ctx.ay_pos[aj1]))
    return segs


def gen_steel_section(ctx: Ctx, task, rule):
    sec = int(re.match(r"^frm-s(\d+)-1$", task["id"]).group(1))
    tid = task["id"]
    levels = ctx.sections.get(sec, [])
    if not levels:
        ctx.gaps.append(f"{tid}: 節に対応するデッキタスクが計画に無い")
        return
    col_size = ctx.building["structure"]["columnSizeMm"] / 1000.0
    girder_d = ctx.building["structure"]["girderDepthMm"] / 1000.0
    reach = float(ctx.rules["global"]["craneReachM"])
    crane = ctx.add_actor("crane:rough", "roughCrane", boxes=12, label="ラフタークレーン")
    member_ids = []
    # ---- 柱（節の柱は1部材として建つ）
    col_events = []  # (memberId, x, y, zBase)
    for lid in levels:
        pass
    positions = sorted(set().union(*[ctx.columns[l] for l in levels]),
                       key=lambda p: (ctx.ay_pos[p[1]], ctx.ax_pos[p[0]]))
    # 節内での柱の存在区間（連続する階）
    col_members = []
    for (ai, aj) in positions:
        present = [l for l in levels if (ai, aj) in ctx.columns[l]]
        if not present:
            continue
        # 連続区間に分割
        groups = [[present[0]]]
        for l in present[1:]:
            prev = groups[-1][-1]
            if ctx.levels.index(ctx.level_by_id[l]) == ctx.levels.index(ctx.level_by_id[prev]) + 1:
                groups[-1].append(l)
            else:
                groups.append([l])
        for g in groups:
            z0 = ctx.level_by_id[g[0]]["elev"]
            top = ctx.level_by_id[g[-1]]
            z1 = top["elev"] + top["fh"]
            x, y = ctx.ax_pos[ai], ctx.ay_pos[aj]
            mid = ctx.add_member("column", tid,
                                 (x - col_size / 2, y - col_size / 2, z0, col_size, col_size, z1 - z0),
                                 basis="rule", level=g[0])
            col_members.append((mid, x, y, z0))
            member_ids.append(mid)
    n = len(col_members)
    for k, (mid, x, y, z0) in enumerate(col_members):
        # 仮置き（自位置の南側前面に台付け）
        same_x_rank = sum(1 for (_, x2, _, _) in col_members[:k] if x2 == x)
        stock_pos = (x, ctx.fp_bbox[1] - 4.5 - same_x_rank * 1.4, 0.4)
        u_stock = spread_u(k, n, 0.02, 0.12)
        ctx.add_event("stock", tid, u_stock, member=mid, at=stock_pos, note="トラック搬入→仮置き")
        u_lift = spread_u(k, n, 0.12, 0.85)
        sx, sy = ctx.nearest_station(x, y)
        dist = math.hypot(x - sx, y - sy)
        if dist > reach:
            # 横引き：届く着地點へ揚重してから同一フロアを横移動
            lx = min(max(x, ctx.fp_bbox[0] + 1), ctx.fp_bbox[2] - 1)
            ly = ctx.fp_bbox[1] + 1 if abs(y - ctx.fp_bbox[1]) < abs(y - ctx.fp_bbox[3]) else ctx.fp_bbox[3] - 1
            ctx.add_event("lift", tid, u_lift, member=mid, at=(lx, ly, z0), note="揚重（着地點まで）")
            ctx.add_event("carry", tid, min(u_lift + 0.01, 0.99), member=mid,
                          at=(x, y, z0), via=(lx, ly, z0), note="横引き（台車）")
        else:
            ctx.add_event("lift", tid, u_lift, member=mid, at=(x, y, z0), note="揚重")
        ctx.add_event("place", tid, min(u_lift + 0.015, 0.995), member=mid, at=(x, y, z0))
        if k in (0, n // 3, 2 * n // 3):
            ctx.add_event("move", tid, u_lift, actor=crane, at=(sx, sy, 0.0))
    # ---- 大梁（床梁は「その階をデッキタスクに持つ節」で建てる。最上節は屋根梁も）
    girder_ids = []
    for lid in levels:
        if lid == "L1":
            continue
        z_top = ctx.level_by_id[lid]["elev"]
        for (x0, y0, x1, y1) in _girder_segments(ctx, lid):
            girder_ids.append(ctx.add_member("girder", tid,
                                             _girder_box(x0, y0, x1, y1, z_top, girder_d),
                                             basis="rule", level=lid))
    if sec == max(ctx.sections.keys()):
        for (x0, y0, x1, y1) in _girder_segments(ctx, "ROOF"):
            girder_ids.append(ctx.add_member("girder", tid,
                                             _girder_box(x0, y0, x1, y1, ctx.roof_z, girder_d),
                                             basis="rule", level=ctx.roof_level_id))
    girder_ids.sort(key=lambda mid: (ctx.members[int(mid.split("-")[1]) - 1]["box"]["z"],
                                     ctx.members[int(mid.split("-")[1]) - 1]["box"]["y"],
                                     ctx.members[int(mid.split("-")[1]) - 1]["box"]["x"]))
    # 大梁も柱と同じく 搬入→揚重（届かなければ横引き）→建込み の列で1本ずつ現れる
    g_centers = []
    for mid in girder_ids:
        mb = ctx.members[int(mid.split("-")[1]) - 1]["box"]
        g_centers.append((mb["x"] + mb["dx"] / 2, mb["y"] + mb["dy"] / 2, mb["z"]))
    n_g = len(girder_ids)
    for k, mid in enumerate(girder_ids):
        gx_c, gy_c, gz = g_centers[k]
        rank = sum(1 for (x2, _y2, _z2) in g_centers[:k] if x2 == gx_c)
        ctx.add_event("stock", tid, spread_u(k, n_g, 0.40, 0.50), member=mid,
                      at=(gx_c, ctx.fp_bbox[1] - 4.5 - rank * 1.4, 0.4), note="トラック搬入→仮置き")
        sx, sy = ctx.nearest_station(gx_c, gy_c)
        dist = math.hypot(gx_c - sx, gy_c - sy)
        u_place = spread_u(k, n_g, 0.55, 0.97)
        u_lift = max(0.5, u_place - 0.02)
        if dist > reach:
            lx = min(max(gx_c, ctx.fp_bbox[0] + 1), ctx.fp_bbox[2] - 1)
            ly = ctx.fp_bbox[1] + 1 if abs(gy_c - ctx.fp_bbox[1]) < abs(gy_c - ctx.fp_bbox[3]) else ctx.fp_bbox[3] - 1
            ctx.add_event("lift", tid, u_lift, member=mid, at=(lx, ly, gz), note="揚重（着地点まで）")
            ctx.add_event("carry", tid, min(u_lift + 0.008, 0.99), member=mid,
                          at=(gx_c, gy_c, gz), via=(lx, ly, gz), note="横引き（台車）")
        else:
            ctx.add_event("lift", tid, u_lift, member=mid, at=(gx_c, gy_c, gz), note="揚重")
        ctx.add_event("place", tid, u_place, member=mid, at=(gx_c, gy_c, gz))
    member_ids += girder_ids
    # ---- ブレース
    brace_ids = []
    for el in ctx.building["structure"]["seismicElements"]:
        for lid in el["levelRange"]:
            if lid not in levels:
                continue
            r = el["cell"]
            # その階の実平面にセルが無い（セットバック等）ブレースは建てられない。
            # モデル側の levelRange は階ごとの平面縮小を見ていないため、実スラブ側で判定する。
            ci = ctx.ax_idx[r["xFrom"]]
            cj = ctx.ay_idx[r["yFrom"]]
            if (ci, cj) not in ctx.level_by_id[lid]["cells"]:
                ctx.stats["skippedBraces"] = ctx.stats.get("skippedBraces", 0) + 1
                continue
            x0 = ctx.ax_off[r["xFrom"]]
            x1 = ctx.ax_off[r["xTo"]]
            y0 = ctx.ay_off[r["yFrom"]]
            y1 = ctx.ay_off[r["yTo"]]
            lv = ctx.level_by_id[lid]
            if el["direction"] == "X":
                box = (x0, (y0 + y1) / 2 - 0.09, lv["elev"], x1 - x0, 0.18, lv["fh"])
            else:
                box = ((x0 + x1) / 2 - 0.09, y0, lv["elev"], 0.18, y1 - y0, lv["fh"])
            brace_ids.append(ctx.add_member("brace", tid, box, basis="inferred", level=lid))
    ctx.place_spread(tid, brace_ids, 0.5, 0.97)
    member_ids += brace_ids
    # ---- 階段（コア内。階ごとに鉄骨と一体で設置される）
    stair_ids = []
    for sid, s in sorted(ctx.shafts.items()):
        if s["kind"] != "階段":
            continue
        x0, y0, x1, y1 = ctx.shaft_rect[sid]
        for lid in levels:
            if lid not in (s.get("levelRange") or []):
                continue
            lv = ctx.level_by_id[lid]
            stair_ids.append(ctx.add_member("stairFlight", tid,
                                            (x0, y0, lv["elev"], x1 - x0, (y1 - y0) / 2, lv["fh"] / 2),
                                            basis="rule", level=lid))
            stair_ids.append(ctx.add_member("stairFlight", tid,
                                            (x0, y0 + (y1 - y0) / 2, lv["elev"] + lv["fh"] / 2,
                                             x1 - x0, (y1 - y0) / 2, lv["fh"] / 2),
                                            basis="rule", level=lid))
    ctx.place_spread(tid, stair_ids, 0.6, 0.98)
    member_ids += stair_ids
    ctx.reg["sectionMembers"][sec] = member_ids
    top = ctx.level_by_id[levels[-1]]
    ctx.work_event(task, "鉄骨", (ctx.centroid[0], ctx.centroid[1], top["elev"] + top["fh"]))


def gen_steel_torque(ctx: Ctx, task, rule):
    sec = int(re.match(r"^frm-s(\d+)-2$", task["id"]).group(1))
    ids = ctx.reg["sectionMembers"].get(sec, [])
    for k in range(0, len(ids), 100):
        ctx.add_event("state", task["id"], 0.5, members=ids[k:k + 100], state="本締め")
    top_levels = ctx.sections.get(sec, [])
    z = 0.0
    if top_levels:
        lv = ctx.level_by_id[top_levels[-1]]
        z = lv["elev"] + lv["fh"]
    ctx.work_event(task, "鉄骨", (ctx.centroid[0], ctx.centroid[1], z))


def gen_deck(ctx: Ctx, task, rule):
    m = re.match(r"^frm-s(\d+)-(L\d+)-d$", task["id"])
    lid = m.group(2)
    tid = task["id"]
    lv = ctx.level_by_id[lid]
    slab = next((s for s in ctx.building["slabs"] if s["level"] == lid), None)
    if slab and slab.get("onGround"):
        ctx.add_event("action", tid, 0.5, at=(ctx.centroid[0], ctx.centroid[1], lv["elev"]),
                      note="先行仕込み（スリーブ・インサート確認）。1Fは土間のためデッキなし")
        ctx.work_event(task, "鉄骨", (ctx.centroid[0], ctx.centroid[1], lv["elev"]))
        ctx.reg["deckMembers"][lid] = []
        return
    cells = sorted(lv["floor"], key=lambda c: (c[1], c[0]))
    # 小梁：行ごとのラン（デッキ支持）
    joist_ids = []
    rows = {}
    for c in cells:
        rows.setdefault(c[1], []).append(c)
    for j, cs in sorted(rows.items()):
        cs.sort()
        run = [cs[0]]
        for c in cs[1:]:
            if c[0] == run[-1][0] + 1:
                run.append(c)
            else:
                _add_joist(ctx, tid, run, lv, joist_ids)
                run = [c]
        _add_joist(ctx, tid, run, lv, joist_ids)
    ctx.place_spread(tid, joist_ids, 0.03, 0.4)
    deck_ids = []
    for (x0, y0, x1, y1) in _bay_boxes(ctx, cells):
        deck_ids.append(ctx.add_member("deckPanel", tid,
                                       (x0, y0, lv["elev"] - 0.06, x1 - x0, y1 - y0, 0.06),
                                       basis="rule", level=lid))
    ctx.reg["deckMembers"][lid] = deck_ids
    ctx.place_spread(tid, deck_ids, 0.35, 0.98)
    ctx.work_event(task, "鉄骨", (ctx.centroid[0], ctx.centroid[1], lv["elev"]))


def _add_joist(ctx, tid, run, lv, out=None):
    x0 = ctx.cell_rect(run[0])[0]
    x1 = ctx.cell_rect(run[-1])[2]
    y0 = ctx.cell_rect(run[0])[1]
    y1 = ctx.cell_rect(run[0])[3]
    mid = ctx.add_member("joist", tid, (x0, (y0 + y1) / 2 - 0.1, lv["elev"] - 0.26, x1 - x0, 0.2, 0.2),
                         basis="inferred", level=lv["id"])
    if out is not None:
        out.append(mid)
    return mid


def gen_floor_pour(ctx: Ctx, task, rule):
    m = re.match(r"^frm-s(\d+)-(L\d+)-c$", task["id"])
    lid = m.group(2)
    tid = task["id"]
    lv = ctx.level_by_id[lid]
    cells = sorted(lv["floor"], key=lambda c: (c[1], c[0]))
    # 配筋束（工区ごとに仮置き）
    zones_here = sorted({ctx.zone_of_point((ctx.cell_rect(c)[0] + ctx.cell_rect(c)[2]) / 2,
                                            (ctx.cell_rect(c)[1] + ctx.cell_rect(c)[3]) / 2, lid) for c in cells})
    bundle_ids = []
    for zid in zones_here:
        if zid is None:
            continue
        cx, cy = ctx.cells_centroid(ctx.zones[zid]["cells"])
        bundle_ids.append(ctx.add_member("rebarBundle", tid, (cx - 3.0, cy - 1.0, lv["elev"] + 0.1, 6.0, 0.8, 0.6),
                                         basis="rule", zone=zid, level=lid))
    ctx.place_spread(tid, bundle_ids, 0.02, 0.1, etype="stock")
    ctx.bulk_remove(tid, bundle_ids, 0.5)  # 配筋が進むと束は消費される
    # 配筋マット（構造ベイ単位。本数はメタデータ bars に保持し、1本ずつの情報は失わない）
    mat_ids = []
    spacing = 0.2
    for (x0, y0, x1, y1) in _bay_boxes(ctx, cells):
        bars = int((x1 - x0) / spacing) + int((y1 - y0) / spacing)
        mid = ctx.add_member("rebarMat", tid, (x0, y0, lv["elev"] + 0.02, x1 - x0, y1 - y0, 0.04),
                             faces=2, basis="rule", level=lid)
        ctx.members[-1]["bars"] = bars
        mat_ids.append(mid)
    ctx.place_spread(tid, mat_ids, 0.08, 0.45)
    slab = next((s for s in ctx.building["slabs"] if s["level"] == lid), None)
    if slab and slab.get("onGround"):
        slab_ids = []
        for (x0, y0, x1, y1) in _bay_boxes(ctx, cells):
            slab_ids.append(ctx.add_member("groundSlab", tid,
                                           (x0, y0, 0.0, x1 - x0, y1 - y0, slab["thickness"] / 1000.0),
                                           basis="rule", level=lid))
        ctx.place_spread(tid, slab_ids, 0.45, 0.9)
        ctx.bulk_state(tid, slab_ids, "養生", 0.97)
    else:
        deck_ids = ctx.reg["deckMembers"].get(lid, [])
        # 打設フロント：デッキ部材へベイ順に state=打設
        chunk = 25
        for k in range(0, len(deck_ids), chunk):
            u = spread_u(k // chunk, max(1, math.ceil(len(deck_ids) / chunk)), 0.45, 0.9)
            ctx.add_event("state", tid, u, members=deck_ids[k:k + chunk], state="打設")
        ctx.bulk_state(tid, deck_ids, "養生", 0.97)
    pump = ctx.add_actor("machine:pump", "pumpTruck", boxes=9, label="ポンプ車")
    ctx.add_event("move", tid, 0.45, actor=pump, at=(ctx.centroid[0], ctx.fp_bbox[1] - 5, 0.0))
    ctx.work_event(task, "コンクリート", (ctx.centroid[0], ctx.centroid[1], lv["elev"]))


# ---------------------------------------------------------------- 屋上・外装
def gen_roof_base(ctx: Ctx, task, rule):
    tid = task["id"]
    runs = _boundary_runs(ctx, ctx.roof_cells)
    parapet_h = ctx.building["roof"].get("parapetHeight", 600) / 1000.0
    ids = []
    for (x0, y0, x1, y1, side) in runs:
        length = math.hypot(x1 - x0, y1 - y0)
        cnt = max(1, math.ceil(length / 7.6))
        for k in range(cnt):
            t0, t1 = k / cnt, (k + 1) / cnt
            cx = x0 + (x1 - x0) * (t0 + t1) / 2
            cy = y0 + (y1 - y0) * (t0 + t1) / 2
            L = length / cnt
            horiz = abs(y1 - y0) < 1e-9
            box = (cx - (L if horiz else 0.25) / 2, cy - (0.25 if horiz else L) / 2,
                   ctx.roof_z, L if horiz else 0.25, 0.25 if horiz else L, parapet_h)
            ids.append(ctx.add_member("parapet", tid, box, basis="inferred", level=ctx.roof_level_id))
    ctx.place_spread(tid, ids, 0.03, 0.25)
    cells = sorted(ctx.roof_cells, key=lambda c: (c[1], c[0]))
    sheet_ids = []
    for (x0, y0, x1, y1) in _row_run_boxes(ctx, cells):
        sheet_ids.append(ctx.add_member("roofSheet", tid, (x0, y0, ctx.roof_z + 0.02, x1 - x0, y1 - y0, 0.03),
                                        basis="rule", level=ctx.roof_level_id))
    ctx.place_spread(tid, sheet_ids, 0.2, 0.95)
    ctx.work_event(task, "防水", (ctx.centroid[0], ctx.centroid[1], ctx.roof_z))


def gen_roof_finish(ctx: Ctx, task, rule):
    tid = task["id"]
    cells = sorted(ctx.roof_cells, key=lambda c: (c[1], c[0]))
    ids = []
    for (x0, y0, x1, y1) in _row_run_boxes(ctx, cells):
        ids.append(ctx.add_member("roofProtection", tid, (x0, y0, ctx.roof_z + 0.05, x1 - x0, y1 - y0, 0.06),
                                  basis="rule", level=ctx.roof_level_id))
    ctx.place_spread(tid, ids, 0.05, 0.8)
    drain_ids = []
    seen = set()
    for r in ctx.building["roof"]["cellRanges"]:
        x0 = ctx.ax_off[r["xFrom"]] + 2.0
        y0 = ctx.ay_off[r["yFrom"]] + 2.0
        key = (round(x0), round(y0))
        if key in seen:
            continue
        seen.add(key)
        drain_ids.append(ctx.add_member("roofDrain", tid, (x0, y0, ctx.roof_z + 0.05, 0.5, 0.5, 0.15),
                                        basis="default", level=ctx.roof_level_id))
    ctx.place_spread(tid, drain_ids, 0.8, 0.9)
    ctx.add_event("inspect", tid, 0.97, at=(ctx.centroid[0], ctx.centroid[1], ctx.roof_z), note="ドレン通水確認")
    ctx.work_event(task, "防水", (ctx.centroid[0], ctx.centroid[1], ctx.roof_z))


def _wall_face(ctx: Ctx, wall):
    line = wall["line"]
    if line["axis"].startswith("Y"):
        y = ctx.ay_off[line["axis"]]
        return "南面" if y <= ctx.centroid[1] else "北面"
    x = ctx.ax_off[line["axis"]]
    return "西面" if x <= ctx.centroid[0] else "東面"


def _wall_geom(ctx: Ctx, wall):
    """壁ラインの (x0,y0,x1,y1, horiz, level) を返す"""
    line = wall["line"]
    lv = ctx.level_by_id[wall["level"]]
    if line["axis"].startswith("Y"):
        y = ctx.ay_off[line["axis"]]
        return (ctx.ax_off[line["from"]], y, ctx.ax_off[line["to"]], y, True, lv)
    x = ctx.ax_off[line["axis"]]
    return (x, ctx.ay_off[line["from"]], x, ctx.ay_off[line["to"]], False, lv)


def gen_face_scaffold(ctx: Ctx, task, rule):
    face = re.match(r"^face-(.+)-1$", task["id"]).group(1)
    tid = task["id"]
    ids = []
    for entry in ctx.levels:
        cells = entry["solid"]
        runs = [r for r in _boundary_runs(ctx, cells)
                if (face == "南面" and r[4] == "S") or (face == "北面" and r[4] == "N")
                or (face == "西面" and r[4] == "W") or (face == "東面" and r[4] == "E")]
        for (x0, y0, x1, y1, side) in runs:
            length = math.hypot(x1 - x0, y1 - y0)
            cnt = max(1, math.ceil(length / 3.6))
            for k in range(cnt):
                t0, t1 = k / cnt, (k + 1) / cnt
                cx = x0 + (x1 - x0) * (t0 + t1) / 2
                cy = y0 + (y1 - y0) * (t0 + t1) / 2
                L = length / cnt
                horiz = side in ("S", "N")
                ox = 0.0 if horiz else (1.1 if side == "E" else -1.1)
                oy = (1.1 if side == "N" else -1.1) if horiz else 0.0
                box = (cx + ox - (L if horiz else 0.9) / 2, cy + oy - (0.9 if horiz else L) / 2,
                       entry["elev"], L if horiz else 0.9, 0.9 if horiz else L, entry["fh"])
                ids.append(ctx.add_member("scaffoldUnit", tid, box, basis="rule", level=entry["id"], face=face))
    ctx.reg["scaffold"][face] = ids
    ctx.place_spread(tid, ids, 0.05, 0.9)
    cx, cy = ctx.centroid
    fy = ctx.fp_bbox[1] if face == "南面" else ctx.fp_bbox[3] if face == "北面" else cy
    fx = ctx.fp_bbox[0] if face == "西面" else ctx.fp_bbox[2] if face == "東面" else cx
    ctx.work_event(task, "鳶", (fx, fy))


def gen_face_panel(ctx: Ctx, task, rule):
    face = re.match(r"^face-(.+)-2$", task["id"]).group(1)
    tid = task["id"]
    walls = [w for w in ctx.walls if w["kind"] == "外壁" and _wall_face(ctx, w) == face]
    walls.sort(key=lambda w: (ctx.level_by_id[w["level"]]["elev"], _wall_geom(ctx, w)[1], _wall_geom(ctx, w)[0]))
    ids = []
    for w in walls:
        x0, y0, x1, y1, horiz, lv = _wall_geom(ctx, w)
        th = (w.get("thickness") or 200) / 1000.0
        H = lv["fh"]
        length = abs(x1 - x0) if horiz else abs(y1 - y0)
        ops = sorted(w.get("openings", []), key=lambda o: o["offsetFromStart"])
        cursor = 0.0
        segs = []  # (start, len, z0, h)
        for o in ops:
            off = o["offsetFromStart"] / 1000.0
            ow = o["width"] / 1000.0
            oh = o["height"] / 1000.0
            sill = (o.get("sillHeight") or 0) / 1000.0
            if off > cursor:
                segs.append((cursor, off - cursor, 0.0, H))
            if sill > 0:
                segs.append((off, ow, 0.0, sill))
            if sill + oh < H:
                segs.append((off, ow, sill + oh, H - sill - oh))
            cursor = max(cursor, off + ow)
        if cursor < length:
            segs.append((cursor, length - cursor, 0.0, H))
        for (s, L, z0, h) in segs:
            if L <= 0.01 or h <= 0.01:
                continue
            if horiz:
                box = (min(x0, x1) + s, y0 - th / 2, lv["elev"] + z0, L, th, h)
            else:
                box = (x0 - th / 2, min(y0, y1) + s, lv["elev"] + z0, th, L, h)
            ids.append(ctx.add_member("extWallPanel", tid, box, basis="rule",
                                      level=w["level"], face=face))
    ctx.reg["facePanels"][face] = ids
    ctx.place_spread(tid, ids, 0.03, 0.97)
    cx, cy = ctx.centroid
    ctx.work_event(task, "外装", (cx, cy))


def gen_face_sash(ctx: Ctx, task, rule):
    face = re.match(r"^face-(.+)-3$", task["id"]).group(1)
    tid = task["id"]
    walls = [w for w in ctx.walls if w["kind"] == "外壁" and _wall_face(ctx, w) == face]
    walls.sort(key=lambda w: (ctx.level_by_id[w["level"]]["elev"], _wall_geom(ctx, w)[1], _wall_geom(ctx, w)[0]))
    ids = []
    outward = {"南面": (0, -1), "北面": (0, 1), "西面": (-1, 0), "東面": (1, 0)}[face]
    for w in walls:
        x0, y0, x1, y1, horiz, lv = _wall_geom(ctx, w)
        for o in sorted(w.get("openings", []), key=lambda o: o["offsetFromStart"]):
            off = o["offsetFromStart"] / 1000.0
            ow = o["width"] / 1000.0
            oh = o["height"] / 1000.0
            sill = (o.get("sillHeight") or 0) / 1000.0
            kind = {"サッシ": "sash", "両開き戸": "doorExt", "片開き戸": "doorExt",
                    "シャッター": "shutter"}.get(o["kind"], "sash")
            if o.get("role") == "shopfront":
                kind = "shopfront"
            elif o.get("role") == "entrance":
                kind = "doorExt"
            elif o.get("role") == "loading":
                kind = "shutter"
            if horiz:
                cx = min(x0, x1) + off + ow / 2 + outward[0] * 0.06
                box = (min(x0, x1) + off, y0 + outward[1] * 0.06 - 0.06, lv["elev"] + sill, ow, 0.12, oh)
            else:
                box = (x0 + outward[0] * 0.06 - 0.06, min(y0, y1) + off, lv["elev"] + sill, 0.12, ow, oh)
            ids.append(ctx.add_member(kind, tid, box, basis="rule", level=w["level"], face=face))
    # 庇（genericElements の attachTo がこの面の壁なら）
    wall_face = {w["id"]: _wall_face(ctx, w) for w in ctx.walls if w["kind"] == "外壁"}
    for ge in ctx.building.get("genericElements", []):
        if wall_face.get(ge.get("attachTo")) != face:
            continue
        w = next((x for x in ctx.walls if x["id"] == ge["attachTo"]), None)
        if not w:
            continue
        x0, y0, x1, y1, horiz, lv = _wall_geom(ctx, w)
        ops = [o for o in w.get("openings", []) if o["kind"] in ("両開き戸", "片開き戸")]
        if not ops:
            continue
        o = ops[0]
        off = o["offsetFromStart"] / 1000.0
        ow = o["width"] / 1000.0
        if horiz:
            box = (min(x0, x1) + off - 0.4, y0 + outward[1] * 0.85 - 0.85, lv["elev"] + 2.3, ow + 0.8, 1.7, 0.15)
        else:
            box = (x0 + outward[0] * 0.85 - 0.85, min(y0, y1) + off - 0.4, lv["elev"] + 2.3, 1.7, ow + 0.8, 0.15)
        ids.append(ctx.add_member("canopy", tid, box, basis="default", level=w["level"], face=face))
    ctx.place_spread(tid, ids, 0.05, 0.95)
    ctx.work_event(task, "外装", ctx.centroid)


def gen_face_seal(ctx: Ctx, task, rule):
    face = re.match(r"^face-(.+)-4$", task["id"]).group(1)
    ids = ctx.reg["facePanels"].get(face, [])
    ctx.bulk_state(task["id"], ids, "シーリング・雨仕舞い", 0.6)
    ctx.add_event("inspect", task["id"], 0.9, at=(ctx.centroid[0], ctx.centroid[1], 3.0), note="雨仕舞い確認")
    ctx.work_event(task, "外装", ctx.centroid)


def gen_face_scaffold_out(ctx: Ctx, task, rule):
    face = re.match(r"^face-(.+)-5$", task["id"]).group(1)
    ids = ctx.reg["scaffold"].get(face, [])
    ctx.bulk_remove(task["id"], ids, 0.5)
    ctx.work_event(task, "鳶", ctx.centroid)


# ---------------------------------------------------------------- 電気・受電
def _room_rect(ctx: Ctx, room):
    c = room["cells"]
    return (ctx.ax_off[c["xFrom"]], ctx.ay_off[c["yFrom"]],
            ctx.ax_off[c["xTo"]], ctx.ay_off[c["yTo"]])


def _rect_cells_inside(ctx: Ctx, cellset, x0, y0, x1, y1):
    """矩形と交わる全セルが cellset に含まれるか"""
    import bisect
    xs, ys = ctx.ax_pos, ctx.ay_pos
    i_lo = max(0, bisect.bisect_right(xs, x0 + 1e-9) - 1)
    i_hi = min(len(xs) - 2, bisect.bisect_left(xs, x1 - 1e-9) - 1)
    j_lo = max(0, bisect.bisect_right(ys, y0 + 1e-9) - 1)
    j_hi = min(len(ys) - 2, bisect.bisect_left(ys, y1 - 1e-9) - 1)
    for i in range(i_lo, i_hi + 1):
        for j in range(j_lo, j_hi + 1):
            if (i, j) not in cellset:
                return False
    return True


def _path_segments(ctx: Ctx, run, z_center, width, height):
    """設備ラン（シャフト→部屋）の経路をボックス列にする。
    経路候補（X先行／Y先行／工区中心経由）を決定的な順で試し、その階の実平面
    （footprint − 吹抜け）に収まる最初の候補を採用する。平面の凹部や吹抜けを
    横切る経路は「実スラブ片を基準にしていない」配置として排除する。"""
    if run.get("fromShaft") not in ctx.shaft_rect:
        return []
    sx0, sy0, sx1, sy1 = ctx.shaft_rect[run["fromShaft"]]
    sx, sy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
    room = ctx.rooms.get(run.get("to") or "")
    if room is None:
        return []
    rx0, ry0, rx1, ry1 = _room_rect(ctx, room)
    rx, ry = (rx0 + rx1) / 2, (ry0 + ry1) / 2

    def seg_boxes(waypoints):
        boxes = []
        for (ax_, ay_), (bx_, by_) in zip(waypoints, waypoints[1:]):
            if abs(bx_ - ax_) > 0.05:
                boxes.append((min(ax_, bx_), ay_ - width / 2, z_center - height / 2,
                              abs(bx_ - ax_), width, height))
            elif abs(by_ - ay_) > 0.05:
                boxes.append((ax_ - width / 2, min(ay_, by_), z_center - height / 2,
                              width, abs(by_ - ay_), height))
        return boxes

    routes = [[(sx, sy), (rx, sy), (rx, ry)],
              [(sx, sy), (sx, ry), (rx, ry)]]
    zid = room.get("zoneId")
    if zid in ctx.zones:
        zx, zy = ctx.cells_centroid(ctx.zones[zid]["cells"])
        routes.append([(sx, sy), (zx, sy), (zx, zy), (rx, zy), (rx, ry)])
        routes.append([(sx, sy), (sx, zy), (rx, zy), (rx, ry)])
    lid = run.get("level")
    if lid in ctx.level_by_id:
        for cellset_key in ("solid", "cells"):
            cellset = ctx.level_by_id[lid][cellset_key]
            for rt in routes:
                boxes = seg_boxes(rt)
                if all(_rect_cells_inside(ctx, cellset, b[0], b[1], b[0] + b[3], b[1] + b[4])
                       for b in boxes):
                    if cellset_key == "cells":
                        ctx.stats["pathViaVoid"] = ctx.stats.get("pathViaVoid", 0) + 1
                    return boxes
        ctx.stats["pathFallback"] = ctx.stats.get("pathFallback", 0) + 1
    return seg_boxes(routes[0])


def gen_elec_service(ctx: Ctx, task, rule):
    tid = task["id"]
    south_gates = [g for g in ctx.gates if g["edge"] == "south"]
    gx = (south_gates[0]["atMm"] / 1000.0) if south_gates else ctx.centroid[0]
    base_y = ctx.clamp_site_y(gx, ctx.site_bbox[1] + 1.0, 1.0)
    pole = ctx.add_member("servicePole", tid, (gx, base_y, 0.0, 0.35, 0.35, 8.0), basis="default")
    trench = ctx.add_member("buriedCable", tid,
                            (gx - 0.3, base_y, -0.75, 0.6, max(1.0, ctx.fp_bbox[1] - base_y), 0.15),
                            basis="inferred")
    ctx.place_spread(tid, [pole, trench], 0.1, 0.5)
    # キュービクル基礎（屋上、DSを持つ最小コアの直上）
    ds_cores = sorted({ctx.shafts[s]["coreId"] for s in ctx.shafts
                       if ctx.shafts[s]["kind"] == "DS" and ctx.shafts[s].get("coreId")})
    pad_id = None
    if ds_cores:
        core = next((c for c in ctx.building["cores"] if c["id"] == ds_cores[0]), None)
        if core:
            r = core["rect"]
            x0, x1 = ctx.ax_off[r["xFrom"]] + 0.5, ctx.ax_off[r["xTo"]] - 0.5
            y0, y1 = ctx.ay_off[r["yFrom"]] + 0.5, ctx.ay_off[r["yTo"]] - 0.5
            pad_id = ctx.add_member("cubiclePad", tid, (x0, y0, ctx.roof_z + 0.1, x1 - x0, y1 - y0, 0.15),
                                    basis="inferred", level=ctx.roof_level_id)
            ctx.reg["cubiclePad"] = ((x0 + x1) / 2, (y0 + y1) / 2, ctx.roof_z + 0.25)
            ctx.add_event("place", tid, 0.8, member=pad_id)
    ctx.work_event(task, "電気", (gx, ctx.fp_bbox[1] - 3))


def gen_elec_cubicle(ctx: Ctx, task, rule):
    tid = task["id"]
    pad = ctx.reg.get("cubiclePad")
    cub_id = None
    if pad:
        cub_id = ctx.add_member("cubicle", tid, (pad[0] - 1.8, pad[1] - 1.2, pad[2], 3.6, 2.4, 2.8),
                                basis="rule", level=ctx.roof_level_id)
        ctx.reg["cubicle"] = cub_id
        gx = ctx.gates[0]["atMm"] / 1000.0 if ctx.gates else pad[0]
        ctx.add_event("stock", tid, 0.1, member=cub_id, at=(gx, ctx.clamp_site_y(gx, ctx.site_bbox[1] + 3, 3.0), 0.0), note="搬入")
        ctx.add_event("lift", tid, 0.45, member=cub_id, at=(pad[0], pad[1], pad[2]), note="クレーン揚重")
        ctx.add_event("place", tid, 0.6, member=cub_id, at=(pad[0], pad[1], pad[2]))
    # 幹線立管（EPS兼用シャフト内）
    riser_ids = []
    for run in ctx.equipment["runs"]:
        if run["system"] == "電気" and "立管" in run["kind"] and run.get("fromShaft") in ctx.shaft_rect:
            x0, y0, x1, y1 = ctx.shaft_rect[run["fromShaft"]]
            top = ctx.top_level["elev"] + ctx.top_level["fh"]
            rs = min(0.4, (x1 - x0) - 0.2, (y1 - y0) - 0.2)
            riser_ids.append(ctx.add_member("trunkRiser", tid,
                                            ((x0 + x1) / 2 - rs / 2, (y0 + y1) / 2 - rs / 2, 0.0, rs, rs, top),
                                            basis="inferred"))
    ctx.place_spread(tid, riser_ids, 0.6, 0.95)
    ctx.work_event(task, "電気", (ctx.centroid[0], ctx.centroid[1], ctx.roof_z))


# ---------------------------------------------------------------- 検査
def _insp_target(ctx: Ctx, task_id):
    m = re.match(r"^insp-(.+)-(doc|app|act)$", task_id)
    key = m.group(1) if m else ""
    if key.startswith("fnd-"):
        zid = key[4:]
        if zid in ctx.zones:
            cx, cy = ctx.cells_centroid(ctx.zones[zid]["cells"])
            return (cx, cy, 0.0)
    if key == "steel-prod":
        return (ctx.centroid[0], ctx.fp_bbox[1] - 5, 0.0)
    if key.startswith("steel-s"):
        sec = int(key.split("-s")[1])
        lv = ctx.level_by_id[ctx.sections[sec][-1]]
        return (ctx.centroid[0], ctx.centroid[1], lv["elev"] + lv["fh"])
    if key.startswith("wp-") or key.startswith("conc-"):
        zid = key.split("-", 1)[1]
        if zid in ctx.zones:
            lv = ctx.level_by_id[ctx.zones[zid]["level"]]
            cx, cy = ctx.cells_centroid(ctx.zones[zid]["cells"])
            return (cx, cy, lv["elev"] + lv["fh"] - 1.0)
    if key == "power":
        return ctx.reg.get("cubiclePad") or (ctx.centroid[0], ctx.centroid[1], ctx.roof_z)
    if key == "ev":
        ev = [s for s in ctx.shafts.values() if s["kind"] == "EV"]
        if ev:
            x0, y0, x1, y1 = ctx.shaft_rect[sorted(ev, key=lambda s: s["id"])[0]["id"]]
            return ((x0 + x1) / 2, (y0 + y1) / 2, 0.0)
    # fire / final / mid などは主出入口付近
    return (ctx.centroid[0], ctx.fp_bbox[1], 0.0)


def gen_insp_doc(ctx: Ctx, task, rule):
    pos = ctx.reg.get("officePos") or (ctx.site_bbox[0] + 8, ctx.site_bbox[1] + 4, 0)
    ctx.add_event("action", task["id"], 0.5, at=(pos[0], pos[1], 0.0), note="書類作成")
    ctx.work_event(task, "監督", (pos[0], pos[1]))


def gen_insp_app(ctx: Ctx, task, rule):
    pos = ctx.reg.get("officePos") or (ctx.site_bbox[0] + 8, ctx.site_bbox[1] + 4, 0)
    ctx.add_event("action", task["id"], 0.5, at=(pos[0], pos[1], 0.0), note="申請・依頼")
    ctx.work_event(task, "監督", (pos[0], pos[1]))


def gen_insp_act(ctx: Ctx, task, rule):
    pos = _insp_target(ctx, task["id"])
    insp = ctx.add_actor("inspector", "inspector", boxes=2, label="検査員")
    ctx.add_event("inspect", task["id"], 0.5, actor=insp, at=pos, note=task["name"])
    if task["id"] == "insp-power-act":
        ctx.add_event("gate", task["id"], 0.9, at=pos, state="受電", note="受電ゲート成立（試運転・EV・内装電気の前提）")
    ctx.work_event(task, "検査", pos)


# ---------------------------------------------------------------- 高所作業車
def gen_lift_in(ctx: Ctx, task, rule):
    lid = re.match(r"^lift-in-(L\d+)$", task["id"]).group(1)
    tid = task["id"]
    lv = ctx.level_by_id[lid]
    n = int(ctx.rules["global"]["awpPerLevel"])
    zones_here = sorted((z for z in ctx.zones.values() if z["level"] == lid), key=lambda z: z["id"])
    first_zone = zones_here[0]
    zx, zy = ctx.cells_centroid(first_zone["cells"])
    landing = (ctx.centroid[0], ctx.fp_bbox[1] + 0.5, lv["elev"])
    gx = ctx.gates[0]["atMm"] / 1000.0 if ctx.gates else ctx.centroid[0]
    ids = []
    for k in range(n):
        aid = ctx.add_actor(f"awp:{lid}-{k + 1}", "awp", boxes=6, label=f"高所作業車 {lid}-{k + 1}")
        ids.append(aid)
        ctx.add_event("stock", tid, 0.05 + 0.1 * k, actor=aid, at=(gx + k * 4, ctx.clamp_site_y(gx + k * 4, ctx.site_bbox[1] + 3, 3.0), 0.0), note="搬入（ゲート）")
        ctx.add_event("lift", tid, 0.35 + 0.15 * k, actor=aid, at=landing, note="クレーン揚重で階へ搬入")
        ctx.add_event("move", tid, 0.7 + 0.1 * k, actor=aid, at=(zx + k * 6, zy, lv["elev"]), note="階内へ自走")
    ctx.reg["awps"][lid] = ids
    ctx.work_event(task, "揚重", landing)


def gen_lift_out(ctx: Ctx, task, rule):
    lid = re.match(r"^lift-out-(L\d+)$", task["id"]).group(1)
    tid = task["id"]
    lv = ctx.level_by_id[lid]
    landing = (ctx.centroid[0], ctx.fp_bbox[1] + 0.5, lv["elev"])
    for k, aid in enumerate(ctx.reg["awps"].get(lid, [])):
        ctx.add_event("move", tid, 0.2 + 0.1 * k, actor=aid, at=landing, note="搬出位置へ自走")
        ctx.add_event("lift", tid, 0.5 + 0.1 * k, actor=aid, at=(landing[0], ctx.clamp_site_y(landing[0], ctx.site_bbox[1] + 3, 3.0), 0.0), note="クレーンで吊り下ろし")
        ctx.add_event("remove", tid, 0.85, actor=aid, note="搬出完了")
    ctx.work_event(task, "揚重", landing)


# ---------------------------------------------------------------- 工区内装・設備
def _zone_ctx(ctx: Ctx, task):
    m = re.match(r"^z-(.+)-[a-z0-9]+$", task["id"])
    zid = task.get("zone") or (m.group(1) if m else None)
    z = ctx.zones[zid]
    lv = ctx.level_by_id[z["level"]]
    cx, cy = ctx.cells_centroid(z["cells"])
    return zid, z, lv, (cx, cy)


def _zone_walls(ctx: Ctx, zid, lv_id, kind):
    out = []
    z = ctx.zones[zid]
    for w in ctx.walls:
        if w["kind"] != kind or w["level"] != lv_id:
            continue
        x0, y0, x1, y1, horiz, lv = _wall_geom(ctx, w)
        cell = ctx.point_cell((x0 + x1) / 2, (y0 + y1) / 2)
        if cell in z["cells"]:
            out.append(w)
    out.sort(key=lambda w: w["id"])
    return out


def _zone_runs(ctx: Ctx, zid, lid, system, kind_part):
    out = []
    for run in ctx.equipment["runs"]:
        if run["system"] != system or kind_part not in run["kind"]:
            continue
        if run.get("level") != lid:
            continue
        room = ctx.rooms.get(run.get("to") or "")
        if room is None:
            ctx.stats["skippedRuns"] += 1
            continue
        if room.get("zoneId") != zid:
            continue
        out.append(run)
    out.sort(key=lambda r: r["id"] if "id" in r else (r["fromShaft"], r["to"]))
    return out


def gen_zone_survey(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ctx.add_event("action", task["id"], 0.5, at=(c[0], c[1], lv["elev"]), note="内装墨出し")
    ctx.work_event(task, "墨出し", (c[0], c[1], lv["elev"]))


def gen_zone_lgs(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ids = []
    for w in _zone_walls(ctx, zid, lv["id"], "間仕切"):
        x0, y0, x1, y1, horiz, _ = _wall_geom(ctx, w)
        L = abs(x1 - x0) if horiz else abs(y1 - y0)
        if horiz:
            box = (min(x0, x1), y0 - 0.05, lv["elev"], L, 0.1, lv["fh"])
        else:
            box = (x0 - 0.05, min(y0, y1), lv["elev"], 0.1, L, lv["fh"])
        ids.append(ctx.add_member("lgsFrame", task["id"], box, basis="rule", zone=zid, level=lv["id"]))
    ctx.place_spread(task["id"], ids, 0.05, 0.95)
    ctx.work_event(task, "軽鉄", (c[0], c[1], lv["elev"]))


def gen_zone_ps(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ids = []
    for sid, s in sorted(ctx.shafts.items()):
        if s["kind"] != "PS":
            continue
        x0, y0, x1, y1 = ctx.shaft_rect[sid]
        if ctx.point_cell((x0 + x1) / 2, (y0 + y1) / 2) not in z["cells"]:
            continue
        rs = min(0.35, (x1 - x0) - 0.3, (y1 - y0) - 0.3)
        ids.append(ctx.add_member("psRiser", task["id"],
                                  ((x0 + x1) / 2 - rs / 2, (y0 + y1) / 2 - rs / 2, lv["elev"], rs, rs, lv["fh"]),
                                  basis="inferred", zone=zid, level=lv["id"]))
    ctx.place_spread(task["id"], ids, 0.1, 0.9)
    ctx.work_event(task, "衛生", (c[0], c[1], lv["elev"]))


def _duct_z(lv):
    return lv["elev"] + lv["fh"] - 0.85


def gen_zone_hanger(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ids = []
    for run in _zone_runs(ctx, zid, lv["id"], "空調", "横引き"):
        for box in _path_segments(ctx, run, _duct_z(lv) + 0.35, 0.3, 0.06):
            ids.append(ctx.add_member("hangerSet", task["id"], box, basis="rule", zone=zid, level=lv["id"]))
    ctx.place_spread(task["id"], ids, 0.05, 0.9)
    ctx.work_event(task, "設備支持", (c[0], c[1], lv["elev"] + lv["fh"] - 1.0))


def gen_zone_hvac(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    tid = task["id"]
    duct_ids, pipe_ids, unit_ids = [], [], []
    for run in _zone_runs(ctx, zid, lv["id"], "空調", "横引き"):
        for box in _path_segments(ctx, run, _duct_z(lv), 0.9, 0.45):
            duct_ids.append(ctx.add_member("duct", tid, box, basis="inferred", zone=zid, level=lv["id"]))
        for box in _path_segments(ctx, run, _duct_z(lv) - 0.45, 0.12, 0.12):
            # 冷媒管は液管＋ガス管のペアを1式として表す（集約方針は rules の aggregation）
            if box[3] >= box[4]:
                pair = (box[0], box[1] + 0.65, box[2], box[3], 0.30, box[5])
            else:
                pair = (box[0] + 0.65, box[1], box[2], 0.30, box[4], box[5])
            mid = ctx.add_member("refrigerantPipe", tid, pair,
                                 basis="inferred", zone=zid, level=lv["id"])
            ctx.members[-1]["pair"] = True
            pipe_ids.append(mid)
        room = ctx.rooms.get(run.get("to") or "")
        if room:
            rx0, ry0, rx1, ry1 = _room_rect(ctx, room)
            unit_ids.append(ctx.add_member("indoorUnit", tid,
                                           ((rx0 + rx1) / 2 - 0.65, (ry0 + ry1) / 2 - 0.65,
                                            lv["elev"] + lv["fh"] - 1.2, 1.3, 1.3, 0.35),
                                           basis="inferred", zone=zid, level=lv["id"]))
    # DS立管（この階・この工区分）
    for run in ctx.equipment["runs"]:
        if run["system"] == "空調" and "立管" in run["kind"] and run.get("fromShaft") in ctx.shaft_rect:
            x0, y0, x1, y1 = ctx.shaft_rect[run["fromShaft"]]
            if ctx.point_cell((x0 + x1) / 2, (y0 + y1) / 2) not in z["cells"]:
                continue
            rw = min(0.9, (x1 - x0) - 0.2, (y1 - y0) - 0.2)
            duct_ids.append(ctx.add_member("ductRiser", tid,
                                           ((x0 + x1) / 2 - rw / 2, (y0 + y1) / 2 - rw / 2, lv["elev"], rw, rw, lv["fh"]),
                                           basis="inferred", zone=zid, level=lv["id"]))
    ctx.place_spread(tid, duct_ids, 0.03, 0.5)
    ctx.place_spread(tid, pipe_ids, 0.4, 0.8)
    ctx.place_spread(tid, unit_ids, 0.7, 0.97)
    ctx.work_event(task, "空調", (c[0], c[1], lv["elev"] + lv["fh"] - 1.0))


def gen_zone_plumb(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ids = []
    for run in _zone_runs(ctx, zid, lv["id"], "衛生", "横引き"):
        for box in _path_segments(ctx, run, lv["elev"] + lv["fh"] - 1.25, 0.18, 0.18):
            ids.append(ctx.add_member("plumbPipe", task["id"], box, basis="inferred", zone=zid, level=lv["id"]))
    ctx.place_spread(task["id"], ids, 0.05, 0.9)
    ctx.work_event(task, "衛生", (c[0], c[1], lv["elev"] + lv["fh"] - 1.2))


def gen_zone_elec(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    tid = task["id"]
    ids = []
    covered = False
    for run in _zone_runs(ctx, zid, lv["id"], "電気", "横引き"):
        covered = True
        for box in _path_segments(ctx, run, lv["elev"] + lv["fh"] - 0.6, 0.45, 0.08):
            ids.append(ctx.add_member("cableRack", tid, box, basis="inferred", zone=zid, level=lv["id"]))
    if not covered:
        # ランが無い工区は EPS（最寄りPS）→工区中心のラックを推論生成
        ps = [(sid, s) for sid, s in ctx.shafts.items() if s["kind"] == "PS"]
        if ps:
            sid, _s = min(ps, key=lambda kv: ((ctx.shaft_rect[kv[0]][0] - c[0]) ** 2 +
                                              (ctx.shaft_rect[kv[0]][1] - c[1]) ** 2, kv[0]))
            fake = {"fromShaft": sid, "to": None}
            x0, y0, x1, y1 = ctx.shaft_rect[sid]
            sx, sy = (x0 + x1) / 2, (y0 + y1) / 2
            zc = lv["elev"] + lv["fh"] - 0.6
            if abs(c[0] - sx) > 0.05:
                ids.append(ctx.add_member("cableRack", tid,
                                          (min(sx, c[0]), sy - 0.225, zc - 0.04, abs(c[0] - sx), 0.45, 0.08),
                                          basis="inferred", zone=zid, level=lv["id"]))
            if abs(c[1] - sy) > 0.05:
                ids.append(ctx.add_member("cableRack", tid,
                                          (c[0] - 0.225, min(sy, c[1]), zc - 0.04, 0.45, abs(c[1] - sy), 0.08),
                                          basis="inferred", zone=zid, level=lv["id"]))
    ctx.place_spread(tid, ids, 0.05, 0.9)
    ctx.work_event(task, "電気", (c[0], c[1], lv["elev"] + lv["fh"] - 0.8))


def _zone_rooms(ctx: Ctx, zid):
    rooms = [r for r in ctx.rooms.values() if r.get("zoneId") == zid]
    rooms.sort(key=lambda r: r["id"])
    return rooms


def gen_zone_board(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    tid = task["id"]
    frame_ids, ceil_ids = [], []
    for room in _zone_rooms(ctx, zid):
        x0, y0, x1, y1 = _room_rect(ctx, room)
        ch = (room.get("ceilingHeight") or 2800) / 1000.0
        frame_ids.append(ctx.add_member("ceilFrame", tid, (x0, y0, lv["elev"] + ch - 0.05, x1 - x0, y1 - y0, 0.05),
                                        basis="rule", zone=zid, level=lv["id"]))
        ceil_ids.append(ctx.add_member("ceilingBoard", tid, (x0, y0, lv["elev"] + ch, x1 - x0, y1 - y0, 0.03),
                                       basis="rule", zone=zid, level=lv["id"]))
    ctx.reg["zoneCeilings"][zid] = ceil_ids
    board_ids = []
    for w in _zone_walls(ctx, zid, lv["id"], "間仕切"):
        x0, y0, x1, y1, horiz, _ = _wall_geom(ctx, w)
        L = abs(x1 - x0) if horiz else abs(y1 - y0)
        if horiz:
            box = (min(x0, x1), y0 - 0.07, lv["elev"], L, 0.14, lv["fh"])
        else:
            box = (x0 - 0.07, min(y0, y1), lv["elev"], 0.14, L, lv["fh"])
        board_ids.append(ctx.add_member("wallBoard", tid, box, basis="rule", zone=zid, level=lv["id"]))
    ctx.reg["zoneWallBoards"][zid] = board_ids
    ctx.place_spread(tid, frame_ids, 0.03, 0.4)
    ctx.place_spread(tid, board_ids, 0.3, 0.9)
    ctx.place_spread(tid, ceil_ids, 0.4, 0.97)
    ctx.work_event(task, "ボード", (c[0], c[1], lv["elev"]))


def gen_zone_mep2(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ids = []
    for room in _zone_rooms(ctx, zid):
        x0, y0, x1, y1 = _room_rect(ctx, room)
        ids.append(ctx.add_member("outletSet", task["id"],
                                  (x0 + 0.3, y0 + 0.3, lv["elev"] + 0.3, 0.25, 0.12, 0.4),
                                  basis="default", zone=zid, level=lv["id"]))
    ctx.place_spread(task["id"], ids, 0.1, 0.9)
    ctx.work_event(task, "設備2次", (c[0], c[1], lv["elev"]))


def gen_zone_finish(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ctx.bulk_state(task["id"], ctx.reg["zoneWallBoards"].get(zid, []), "仕上げ", 0.5)
    ctx.bulk_state(task["id"], ctx.reg["zoneCeilings"].get(zid, []), "仕上げ", 0.6)
    ctx.work_event(task, "仕上げ", (c[0], c[1], lv["elev"]))


def gen_zone_floor(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ids = []
    for room in _zone_rooms(ctx, zid):
        x0, y0, x1, y1 = _room_rect(ctx, room)
        ids.append(ctx.add_member("floorFinish", task["id"],
                                  (x0, y0, lv["elev"] + 0.16, x1 - x0, y1 - y0, 0.03),
                                  basis="rule", zone=zid, level=lv["id"]))
    ctx.place_spread(task["id"], ids, 0.05, 0.95)
    ctx.work_event(task, "床", (c[0], c[1], lv["elev"]))


def gen_zone_door(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ids = []
    for w in _zone_walls(ctx, zid, lv["id"], "間仕切"):
        x0, y0, x1, y1, horiz, _ = _wall_geom(ctx, w)
        for o in sorted(w.get("openings", []), key=lambda o: o["offsetFromStart"]):
            if o["kind"] == "サッシ" or (o.get("sillHeight") or 0) > 0:
                continue
            off = o["offsetFromStart"] / 1000.0
            ow = o["width"] / 1000.0
            oh = o["height"] / 1000.0
            if horiz:
                box = (min(x0, x1) + off, y0 - 0.04, lv["elev"], ow, 0.08, oh)
            else:
                box = (x0 - 0.04, min(y0, y1) + off, lv["elev"], 0.08, ow, oh)
            ids.append(ctx.add_member("doorLeaf", task["id"], box, basis="rule", zone=zid, level=lv["id"]))
    ctx.place_spread(task["id"], ids, 0.05, 0.9)
    ctx.work_event(task, "建具", (c[0], c[1], lv["elev"]))


def gen_zone_fixture(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    tid = task["id"]
    ids = []
    for room in _zone_rooms(ctx, zid):
        x0, y0, x1, y1 = _room_rect(ctx, room)
        ch = (room.get("ceilingHeight") or 2800) / 1000.0
        ids.append(ctx.add_member("lightSet", tid,
                                  ((x0 + x1) / 2 - 0.6, (y0 + y1) / 2 - 0.15, lv["elev"] + ch - 0.1, 1.2, 0.3, 0.08),
                                  basis="default", zone=zid, level=lv["id"]))
        name = (room.get("name") or "") + (room.get("use") or "")
        if any(k in name for k in ("トイレ", "洗面", "WC", "給湯", "シャワー", "便所")):
            ids.append(ctx.add_member("plumbFixtureSet", tid,
                                      (x0 + 0.4, y0 + 0.4, lv["elev"] + 0.45, 0.6, 0.5, 0.9),
                                      basis="default", zone=zid, level=lv["id"]))
    for run in _zone_runs(ctx, zid, lv["id"], "空調", "横引き"):
        room = ctx.rooms.get(run.get("to") or "")
        if room:
            rx0, ry0, rx1, ry1 = _room_rect(ctx, room)
            ch = (room.get("ceilingHeight") or 2800) / 1000.0
            ids.append(ctx.add_member("diffuser", tid,
                                      ((rx0 + rx1) / 2 - 0.25, (ry0 + ry1) / 2 - 0.25,
                                       lv["elev"] + ch - 0.06, 0.5, 0.5, 0.06),
                                      basis="default", zone=zid, level=lv["id"]))
    ctx.place_spread(tid, ids, 0.05, 0.95)
    ctx.work_event(task, "器具付け", (c[0], c[1], lv["elev"]))


def gen_zone_clean(ctx: Ctx, task, rule):
    zid, z, lv, c = _zone_ctx(ctx, task)
    ctx.add_event("action", task["id"], 0.5, at=(c[0], c[1], lv["elev"]), note="美装・引渡し確認")
    ctx.work_event(task, "美装", (c[0], c[1], lv["elev"]))


# ---------------------------------------------------------------- EV
def _ev_shafts(ctx: Ctx):
    gi = ctx.building.get("gameIntegration", {})
    ids = list(gi.get("evPassengerShafts", [])) + list(gi.get("evFreightShafts", []))
    ids = [i for i in ids if i in ctx.shafts]
    if not ids:
        ids = sorted(s for s in ctx.shafts if ctx.shafts[s]["kind"] == "EV")
    return sorted(set(ids))


def gen_ev_rail(ctx: Ctx, task, rule):
    tid = task["id"]
    top = ctx.top_level["elev"] + ctx.top_level["fh"]
    ids = []
    for sid in _ev_shafts(ctx):
        x0, y0, x1, y1 = ctx.shaft_rect[sid]
        ids.append(ctx.add_member("evRail", tid, (x0 + 0.25, (y0 + y1) / 2 - 0.1, 0.0, 0.12, 0.2, top), basis="rule"))
        ids.append(ctx.add_member("evRail", tid, (x1 - 0.37, (y0 + y1) / 2 - 0.1, 0.0, 0.12, 0.2, top), basis="rule"))
    ctx.place_spread(tid, ids, 0.05, 0.9)
    first = _ev_shafts(ctx)[0]
    x0, y0, x1, y1 = ctx.shaft_rect[first]
    ctx.work_event(task, "EV", ((x0 + x1) / 2, (y0 + y1) / 2))


def gen_ev_car(ctx: Ctx, task, rule):
    tid = task["id"]
    top = ctx.top_level["elev"] + ctx.top_level["fh"]
    car_ids, mach_ids = [], []
    for sid in _ev_shafts(ctx):
        x0, y0, x1, y1 = ctx.shaft_rect[sid]
        car = ctx.add_member("evCar", tid, (x0 + 0.3, y0 + 0.3, 0.1, x1 - x0 - 0.6, y1 - y0 - 0.6, 2.4), basis="rule")
        car_ids.append(car)
        mach_ids.append(ctx.add_member("evMachine", tid,
                                       ((x0 + x1) / 2 - 0.8, (y0 + y1) / 2 - 0.6, top - 1.1, 1.6, 1.2, 1.0), basis="rule"))
    ctx.reg["evCars"] = car_ids
    ctx.place_spread(tid, car_ids + mach_ids, 0.1, 0.9)
    ctx.work_event(task, "EV", ctx.centroid)


def gen_ev_test(ctx: Ctx, task, rule):
    tid = task["id"]
    top = ctx.top_level["elev"] + ctx.top_level["fh"]
    for k, mid in enumerate(ctx.reg["evCars"]):
        box = ctx.members[int(mid.split("-")[1]) - 1]["box"]
        ctx.add_event("move", tid, spread_u(k, len(ctx.reg["evCars"]), 0.2, 0.7), member=mid,
                      at=(box["x"] + box["dx"] / 2, box["y"] + box["dy"] / 2, top - 2.6), note="試運転（昇降）")
        ctx.add_event("state", tid, 0.8, member=mid, state="試運転調整")
    ctx.work_event(task, "EV", ctx.centroid)


def gen_ev_release(ctx: Ctx, task, rule):
    ctx.bulk_state(task["id"], ctx.reg["evCars"], "養生・工事用解放", 0.5)
    ctx.work_event(task, "EV", ctx.centroid)


# ---------------------------------------------------------------- 外構
def _sectors(ctx: Ctx):
    sx0, sy0, sx1, sy1 = ctx.site_bbox
    fx0, fy0, fx1, fy1 = ctx.fp_bbox
    return [("南駐車場", (sx0, sy0, sx1, fy0)), ("北駐車場", (sx0, fy1, sx1, sy1)),
            ("東荷捌き場", (fx1, fy0, sx1, fy1)), ("西緑地", (sx0, fy0, fx0, fy1))]


def _sector_tiles(ctx: Ctx, rect, pitch=12.0):
    # 2026-11-11 実境界化: セクタ矩形（bbox 基準）のうち敷地ポリゴンの内側だけを敷く。
    # ポリゴン内に収まるタイルはそのまま、境界を跨ぐタイルは 3m に細分して内側のみ残す
    # （矩形敷地では細分は発生せず従来と一致する）。
    x0, y0, x1, y1 = rect
    poly = ctx.site_poly
    tiles = []
    x = x0
    while x < x1 - 0.01:
        y = y0
        while y < y1 - 0.01:
            w, d = min(pitch, x1 - x), min(pitch, y1 - y)
            corners_in = all(_point_in_poly(px, py, poly)
                             for px, py in ((x, y), (x + w, y), (x + w, y + d), (x, y + d)))
            if corners_in:
                tiles.append((x, y, w, d))
            elif _point_in_poly(x + w / 2, y + d / 2, poly):
                sub = 3.0
                sx = x
                while sx < x + w - 0.01:
                    sy = y
                    while sy < y + d - 0.01:
                        sw, sd = min(sub, x + w - sx), min(sub, y + d - sy)
                        if _point_in_poly(sx + sw / 2, sy + sd / 2, poly):
                            tiles.append((sx, sy, sw, sd))
                        sy += sub
                    sx += sub
            y += pitch
        x += pitch
    return tiles


def gen_ext_buried(ctx: Ctx, task, rule):
    tid = task["id"]
    ids = []
    for name, rect in _sectors(ctx):
        x0, y0, x1, y1 = rect
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        for frac in (0.33, 0.66):
            if (x1 - x0) >= (y1 - y0):
                if not _point_in_poly((x0 + x1) / 2, y0 + (y1 - y0) * frac, ctx.site_poly):
                    continue
                ids.append(ctx.add_member("buriedPipe", tid,
                                          (x0 + 0.5, y0 + (y1 - y0) * frac - 0.15, -0.85, x1 - x0 - 1.0, 0.3, 0.2),
                                          basis="inferred"))
            else:
                if not _point_in_poly(x0 + (x1 - x0) * frac, (y0 + y1) / 2, ctx.site_poly):
                    continue
                ids.append(ctx.add_member("buriedPipe", tid,
                                          (x0 + (x1 - x0) * frac - 0.15, y0 + 0.5, -0.85, 0.3, y1 - y0 - 1.0, 0.2),
                                          basis="inferred"))
    ctx.place_spread(tid, ids, 0.05, 0.9)
    ex = ctx.add_actor("machine:excavator-2", "excavator", boxes=10, label="ユンボ（外構）")
    ev_y = ctx.clamp_site_y(ctx.centroid[0], ctx.site_bbox[1] + 6, 6.0)
    ctx.add_event("move", tid, 0.3, actor=ex, at=(ctx.centroid[0], ev_y, 0.0))
    ctx.work_event(task, "外構", (ctx.centroid[0], ev_y))


def gen_ext_base(ctx: Ctx, task, rule):
    tid = task["id"]
    ids = []
    for name, rect in _sectors(ctx):
        for (x, y, w, d) in _sector_tiles(ctx, rect):
            ids.append(ctx.add_member("extBase", tid, (x, y, 0.0, w, d, 0.1), basis="rule"))
    ctx.place_spread(tid, ids, 0.03, 0.95)
    ctx.work_event(task, "外構", (ctx.centroid[0], ctx.clamp_site_y(ctx.centroid[0], ctx.site_bbox[1] + 6, 6.0)))


def gen_ext_pave(ctx: Ctx, task, rule):
    tid = task["id"]
    ids = []
    for name, rect in _sectors(ctx):
        if name == "西緑地":
            continue  # 緑地は舗装しない
        for (x, y, w, d) in _sector_tiles(ctx, rect):
            ids.append(ctx.add_member("extPave", tid, (x, y, 0.1, w, d, 0.06), basis="rule"))
    ctx.place_spread(tid, ids, 0.03, 0.95)
    fin = ctx.add_actor("machine:finisher", "finisher", boxes=9, label="アスファルトフィニッシャー")
    rol = ctx.add_actor("machine:roller", "roller", boxes=8, label="ロードローラー")
    ctx.add_event("move", tid, 0.2, actor=fin, at=(ctx.fp_bbox[0] + 10, ctx.clamp_site_y(ctx.fp_bbox[0] + 10, ctx.site_bbox[1] + 6, 6.0), 0.0))
    ctx.add_event("move", tid, 0.25, actor=rol, at=(ctx.fp_bbox[0] + 16, ctx.clamp_site_y(ctx.fp_bbox[0] + 16, ctx.site_bbox[1] + 6, 6.0), 0.0))
    ctx.work_event(task, "外構", (ctx.centroid[0], ctx.clamp_site_y(ctx.centroid[0], ctx.site_bbox[1] + 6, 6.0)))


def gen_ext_finish(ctx: Ctx, task, rule):
    tid = task["id"]
    ids = []
    for name, rect in _sectors(ctx):
        x0, y0, x1, y1 = rect
        if name in ("南駐車場", "北駐車場"):
            x = x0 + 3.0
            while x < x1 - 5.0:
                for frac in (0.3, 0.7):
                    # 区画線は 5m のボックス全体が敷地ポリゴンに収まる場所にだけ引く
                    if not _rect_in_poly(x, y0 + (y1 - y0) * frac - 2.5, x + 0.15, y0 + (y1 - y0) * frac + 2.5, ctx.site_poly):
                        continue
                    ids.append(ctx.add_member("lineMarking", tid,
                                              (x, y0 + (y1 - y0) * frac - 2.5, 0.17, 0.15, 5.0, 0.01),
                                              faces=2, basis="default"))
                x += 2.5
            for frac in (0.25, 0.75):
                if not _rect_in_poly(x0 + (x1 - x0) * frac - 0.15, (y0 + y1) / 2 - 0.15,
                                      x0 + (x1 - x0) * frac + 0.15, (y0 + y1) / 2 + 0.15, ctx.site_poly):
                    continue
                ids.append(ctx.add_member("lightPole", tid,
                                          (x0 + (x1 - x0) * frac - 0.15, (y0 + y1) / 2 - 0.15, 0.0, 0.3, 0.3, 6.0),
                                          basis="default"))
        if name == "西緑地":
            y = y0 + 4.0
            while y < y1 - 2.0:
                if _rect_in_poly(x0 + (x1 - x0) / 2 - 0.8, y, x0 + (x1 - x0) / 2 + 0.8, y + 1.6, ctx.site_poly):
                    ids.append(ctx.add_member("tree", tid, (x0 + (x1 - x0) / 2 - 0.8, y, 0.0, 1.6, 1.6, 3.2),
                                              faces=12, basis="default"))
                y += 12.0
        if name == "東荷捌き場":
            if _rect_in_poly((x0 + x1) / 2 - 0.15, (y0 + y1) / 2 - 0.15,
                             (x0 + x1) / 2 + 0.15, (y0 + y1) / 2 + 0.15, ctx.site_poly):
                ids.append(ctx.add_member("lightPole", tid,
                                          ((x0 + x1) / 2 - 0.15, (y0 + y1) / 2 - 0.15, 0.0, 0.3, 0.3, 6.0), basis="default"))
    ctx.place_spread(tid, ids, 0.05, 0.95)
    ctx.work_event(task, "外構", (ctx.centroid[0], ctx.clamp_site_y(ctx.centroid[0], ctx.site_bbox[1] + 6, 6.0)))


# ---------------------------------------------------------------- 引渡し
def gen_close_test(ctx: Ctx, task, rule):
    for zid in sorted(ctx.zones.keys()):
        lv = ctx.level_by_id[ctx.zones[zid]["level"]]
        cx, cy = ctx.cells_centroid(ctx.zones[zid]["cells"])
        ctx.add_event("action", task["id"], 0.5, at=(cx, cy, lv["elev"]), note=f"{zid} 試運転調整")
    ctx.work_event(task, "設備", ctx.centroid)


def gen_close_inspect(ctx: Ctx, task, rule):
    insp = ctx.add_actor("inspector", "inspector", boxes=2, label="検査員")
    pos = (ctx.centroid[0], ctx.fp_bbox[1], 0.0)
    ctx.add_event("inspect", task["id"], 0.4, actor=insp, at=pos, note=task["name"])
    ctx.work_event(task, "監督", pos)


def gen_close_handover(ctx: Ctx, task, rule):
    ctx.bulk_remove(task["id"], ctx.reg["tempMembers"], 0.6)
    pos = (ctx.centroid[0], ctx.fp_bbox[1], 0.0)
    ctx.add_event("action", task["id"], 0.8, at=pos, note="引渡し")
    ctx.add_event("gate", task["id"], 0.95, at=pos, state="引渡し", note="竣工・引渡し")
    ctx.work_event(task, "監督", pos)


# ---------------------------------------------------------------- ディスパッチ
GENERATORS = {
    "actionOnly": gen_action_only,
    "siteSetup": gen_site_setup,
    "survey": gen_survey,
    "tempUtility": gen_temp_utility,
    "retaining": gen_retaining,
    "excavation": gen_excavation,
    "blinding": gen_blinding,
    "pileTest": gen_pile_test,
    "piles": gen_piles,
    "pileHead": gen_pile_head,
    "footingForm": gen_footing_form,
    "footingPour": gen_footing_pour,
    "backfill": gen_backfill,
    "steelSection": gen_steel_section,
    "steelTorque": gen_steel_torque,
    "deck": gen_deck,
    "floorPour": gen_floor_pour,
    "roofBase": gen_roof_base,
    "roofFinish": gen_roof_finish,
    "faceScaffold": gen_face_scaffold,
    "facePanel": gen_face_panel,
    "faceSash": gen_face_sash,
    "faceSeal": gen_face_seal,
    "faceScaffoldOut": gen_face_scaffold_out,
    "elecService": gen_elec_service,
    "elecCubicle": gen_elec_cubicle,
    "inspDoc": gen_insp_doc,
    "inspApp": gen_insp_app,
    "inspAct": gen_insp_act,
    "liftIn": gen_lift_in,
    "liftOut": gen_lift_out,
    "zoneSurvey": gen_zone_survey,
    "zoneLgs": gen_zone_lgs,
    "zonePs": gen_zone_ps,
    "zoneHanger": gen_zone_hanger,
    "zoneHvac": gen_zone_hvac,
    "zonePlumb": gen_zone_plumb,
    "zoneElec": gen_zone_elec,
    "zoneBoard": gen_zone_board,
    "zoneMep2": gen_zone_mep2,
    "zoneFinish": gen_zone_finish,
    "zoneFloor": gen_zone_floor,
    "zoneDoor": gen_zone_door,
    "zoneFixture": gen_zone_fixture,
    "zoneClean": gen_zone_clean,
    "evRail": gen_ev_rail,
    "evCar": gen_ev_car,
    "evTest": gen_ev_test,
    "evRelease": gen_ev_release,
    "extBuried": gen_ext_buried,
    "extBase": gen_ext_base,
    "extPave": gen_ext_pave,
    "extFinish": gen_ext_finish,
    "closeTest": gen_close_test,
    "closeInspect": gen_close_inspect,
    "closeHandover": gen_close_handover,
}


def expand(building_path: Path) -> dict:
    ctx = Ctx(building_path)
    kind_rules = []
    for kr in ctx.rules["taskKinds"]:
        if kr.get("idRegex"):
            kind_rules.append((re.compile(kr["idRegex"]), kr))
    gap_kinds = [kr for kr in ctx.rules["taskKinds"] if kr.get("generator") is None]
    for kr in gap_kinds:
        ctx.gaps.append({
            "kind": kr["kind"], "status": "gap",
            "note": kr.get("gapNote", kr.get("desc", "")),
        })
    tasks_sorted = sorted(ctx.plan["tasks"], key=lambda t: (t["es"], t["ef"], t["id"]))
    matched = {}
    for task in tasks_sorted:
        hit = None
        for pat, kr in kind_rules:
            if pat.match(task["id"]):
                hit = kr
                break
        if hit is None:
            ctx.stats["unmatchedTasks"].append(task["id"])
            continue
        matched[task["id"]] = hit["kind"]
        gen = GENERATORS.get(hit["generator"] or "")
        if gen is None:
            continue
        gen(ctx, task, hit)
    # イベントは時刻順に並べ直す（同点は生成順＝id順で決定的）
    events = sorted(ctx.events, key=lambda e: (e["t"], e["id"]))
    face_members = sum(m["faces"] for m in ctx.members)
    face_actors = sum(a["faces"] for a in ctx.actors)
    detail_kinds = set(ctx.rules.get("viewTiers", {}).get("detailKinds", []))
    face_detail = sum(m["faces"] for m in ctx.members if m["kind"] in detail_kinds)
    face_standard = face_members - face_detail + face_actors
    crane_plan = {}
    for m in ctx.plan.get("methods", []):
        if "クレーン" in m.get("item", "") or "揚重" in m.get("item", ""):
            crane_plan[m["item"]] = m["choice"]
    content = {"actors": ctx.actors, "members": ctx.members, "events": events}
    content_hash = sha256_bytes(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode())
    out = {
        "schema": "scene3d/1.0",
        "meta": {
            "generator": "scene_expand.py v1.0 (S3D-1 描画キュー展開)",
            "building": ctx.building["building"]["name"],
            "buildingId": ctx.building["building"]["id"],
            "seed": ctx.seed,
            "difficulty": ctx.plan["meta"].get("difficulty"),
            "inputFiles": {k: p.name for k, p in ctx.input_files.items()},
            "inputHashes": ctx.input_hashes,
            "rulesVersion": ctx.rules["meta"]["version"],
            "cranePlan": crane_plan,
            "contentHash": content_hash,
        },
        "timeAxis": {
            "totalRealDays": ctx.plan["schedules"]["totalWorkingDays"],
            "totalGameDays": ctx.game["totalGameDays"],
            "durationScale": ctx.game["meta"]["durationScale"],
            "note": "イベントの t は実働日（小数）、g はゲーム日（小数・0始まり）。換算は integration 層の結果を受けたもので、ここでは再換算しない（DP-1）",
        },
        "actors": ctx.actors,
        "members": ctx.members,
        "events": events,
        "stats": {
            "memberCount": len(ctx.members),
            "eventCount": len(events),
            "actorCount": len(ctx.actors),
            "faceEstimateMembers": face_members,
            "faceEstimateActors": face_actors,
            "faceEstimateTotal": face_members + face_actors,
            "faceEstimateDetail": face_detail,
            "faceEstimateStandardView": face_standard,
            "tasksMatched": len(matched),
            "tasksTotal": len(ctx.plan["tasks"]),
            "unmatchedTasks": ctx.stats["unmatchedTasks"],
            "skippedRuns": ctx.stats["skippedRuns"],
            "skippedBraces": ctx.stats.get("skippedBraces", 0),
            "pathViaVoid": ctx.stats.get("pathViaVoid", 0),
            "pathFallback": ctx.stats.get("pathFallback", 0),
            "columnPositionsL1": len(ctx.columns["L1"]),
        },
        "gaps": ctx.gaps,
    }
    return out


def main():
    building_path = Path(sys.argv[1])
    if not building_path.is_absolute():
        building_path = HERE / building_path
    out = expand(building_path)
    out_path = HERE / f"generated_scene3d_{building_path.stem.removeprefix('generated_')}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    s = out["stats"]
    print(f"建物: {out['meta']['building']}")
    print(f"部材 {s['memberCount']} / イベント {s['eventCount']} / アクター {s['actorCount']}"
          f" / 面数見積 全詳細 {s['faceEstimateTotal']} / 全体表示 {s['faceEstimateStandardView']}"
          f"（詳細階層 {s['faceEstimateDetail']}）")
    print(f"タスク対応: {s['tasksMatched']}/{s['tasksTotal']}"
          + (f" 未対応: {s['unmatchedTasks']}" if s["unmatchedTasks"] else ""))
    print(f"contentHash: {out['meta']['contentHash'][:16]}…")
    print(f"出力: {out_path}")


if __name__ == "__main__":
    main()
