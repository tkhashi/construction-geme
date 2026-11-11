#!/usr/bin/env python3
"""S3D-2 検証（SVルール）— ScenePlan（generated_scene3d_*.json）の独立検証。

生成物ではなく入力（建物モデル・計画・規則）を正として幾何と順序を再計算し、
ScenePlan が仕様（SCENE3D_PIPELINE.md の SV-01〜SV-07）に適合するか判定する。
落ちたら直すのは生成物ではなく入力・展開規則・エンジン側。

使い方:
  python3 scene_validate.py                      # 3物件まとめて検証
  python3 scene_validate.py generated_game_mall.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EPS = 1e-6


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 独立幾何
class Geo:
    """建物モデルから検証側で独立に再計算する幾何インデックス（エンジンと実装を共有しない）"""

    def __init__(self, b: dict):
        self.b = b
        self.ax_off = {a["name"]: a["offset"] / 1000.0 for a in b["grid"]["axesX"]}
        self.ay_off = {a["name"]: a["offset"] / 1000.0 for a in b["grid"]["axesY"]}
        self.ax_names = [a["name"] for a in b["grid"]["axesX"]]
        self.ay_names = [a["name"] for a in b["grid"]["axesY"]]
        sx = b["grid"]["structuralAxesX"]
        sy = b["grid"]["structuralAxesY"]
        self.struct_x = [a["name"] if isinstance(a, dict) else a for a in sx]
        self.struct_y = [a["name"] if isinstance(a, dict) else a for a in sy]
        self.levels = {}
        for lv in b["levels"]:
            cells = set()
            for r in lv["footprint"]:
                for i in range(self.ax_names.index(r["xFrom"]), self.ax_names.index(r["xTo"])):
                    for j in range(self.ay_names.index(r["yFrom"]), self.ay_names.index(r["yTo"])):
                        cells.add((i, j))
            cfz = set()
            for z in b["structure"].get("columnFreeZones", []):
                if lv["id"] in z.get("levels", []):
                    for r in z["cellRanges"]:
                        for i in range(self.ax_names.index(r["xFrom"]), self.ax_names.index(r["xTo"])):
                            for j in range(self.ay_names.index(r["yFrom"]), self.ay_names.index(r["yTo"])):
                                cfz.add((i, j))
            shaft_cells = set()
            slab = next((s for s in b["slabs"] if s["level"] == lv["id"]), None)
            for sid in (slab or {}).get("openings", []):
                sh = next((s for s in b["shafts"] if s["id"] == sid), None)
                if sh is None:
                    continue
                fp = sh["footprint"]
                sx0, sy0 = fp["x"] / 1000.0, fp["y"] / 1000.0
                sx1, sy1 = sx0 + fp["w"] / 1000.0, sy0 + fp["d"] / 1000.0
                for (i, j) in cells:
                    cx0, cy0, cx1, cy1 = self.cell_rect(i, j)
                    if cx0 < sx1 - 1e-9 and sx0 < cx1 - 1e-9 and cy0 < sy1 - 1e-9 and sy0 < cy1 - 1e-9:
                        shaft_cells.add((i, j))
            self.levels[lv["id"]] = {
                "solid": cells, "cfz": cfz,
                "floor": cells - cfz - shaft_cells,
                "elev": lv["elevation"] / 1000.0, "fh": lv["floorHeight"] / 1000.0,
            }
        self.top_level_id = b["levels"][-1]["id"]
        self.roof_cells = set()
        for r in b["roof"]["cellRanges"]:
            for i in range(self.ax_names.index(r["xFrom"]), self.ax_names.index(r["xTo"])):
                for j in range(self.ay_names.index(r["yFrom"]), self.ay_names.index(r["yTo"])):
                    self.roof_cells.add((i, j))
        self.shaft_rect = {}
        self.shaft_kind = {}
        for s in b["shafts"]:
            fp = s["footprint"]
            self.shaft_rect[s["id"]] = (fp["x"] / 1000.0, fp["y"] / 1000.0,
                                        (fp["x"] + fp["w"]) / 1000.0, (fp["y"] + fp["d"]) / 1000.0)
            self.shaft_kind[s["id"]] = s["kind"]
        poly = [(p[0] / 1000.0, p[1] / 1000.0) for p in b["site"]["polygon"]]
        self.site_bbox = (min(p[0] for p in poly), min(p[1] for p in poly),
                          max(p[0] for p in poly), max(p[1] for p in poly))
        # 建物平面 bbox（全階 solid の和集合）
        all_cells = set()
        for lv in self.levels.values():
            all_cells |= lv["solid"]
        xs, ys = [], []
        for (i, j) in all_cells:
            x0, y0, x1, y1 = self.cell_rect(i, j)
            xs += [x0, x1]
            ys += [y0, y1]
        self.fp_bbox = (min(xs), min(ys), max(xs), max(ys))
        # 実効敷地 = 敷地ポリゴン ∪ 建物平面。ポリゴンは placeholder 矩形であり、
        # 平面を包まない物件がある（亀有: 北側 16m 不足）。その場合は入力側の
        # 既知制限として警告し、部材の飛び出し判定は実効敷地に対して行う。
        self.eff_site_bbox = (min(self.site_bbox[0], self.fp_bbox[0]),
                              min(self.site_bbox[1], self.fp_bbox[1]),
                              max(self.site_bbox[2], self.fp_bbox[2]),
                              max(self.site_bbox[3], self.fp_bbox[3]))
        self.site_warning = None
        if self.eff_site_bbox != self.site_bbox:
            self.site_warning = (
                f"敷地ポリゴン {self.site_bbox} が建物平面 {self.fp_bbox} を包んでいない"
                "（建物モデル側の placeholder 制限・要確認）。SV-01 の敷地判定は実効敷地で実施")
        self._rows_cache = {}

    def cell_rect(self, i, j):
        return (self.ax_off[self.ax_names[i]], self.ay_off[self.ay_names[j]],
                self.ax_off[self.ax_names[i + 1]], self.ay_off[self.ay_names[j + 1]])

    def rows(self, cells):
        """セル集合 → 行 j ごとの (y0, y1, マージ済み x 区間) """
        key = id(cells)
        if key in self._rows_cache:
            return self._rows_cache[key]
        by_row = {}
        for (i, j) in cells:
            by_row.setdefault(j, []).append(i)
        out = {}
        for j, idxs in by_row.items():
            idxs.sort()
            ivs = []
            start = prev = idxs[0]
            for i in idxs[1:]:
                if i == prev + 1:
                    prev = i
                else:
                    ivs.append((self.ax_off[self.ax_names[start]], self.ax_off[self.ax_names[prev + 1]]))
                    start = prev = i
            ivs.append((self.ax_off[self.ax_names[start]], self.ax_off[self.ax_names[prev + 1]]))
            out[j] = (self.ay_off[self.ay_names[j]], self.ay_off[self.ay_names[j + 1]], ivs)
        self._rows_cache[key] = out
        return out

    def region_rows(self, region, level_id):
        if region == "roof":
            return self.rows(self.roof_cells)
        lv = self.levels[level_id]
        return self.rows(lv["solid"] if region == "solid" else lv["floor"])

    def columns_l1(self):
        """較正済み柱位置規則の独立再計算（CP-0 との突合せ用）"""
        b = self.b
        exc = {}
        for e in b["grid"].get("columnExceptions", []):
            ai = e["at"].split("-")[0]
            aj = e["at"].split("-")[1]
            exc.setdefault((ai, aj), set()).update(e["levels"])
        lv = self.levels["L1"]
        cfz_all = set()
        for z in b["structure"].get("columnFreeZones", []):
            if "L1" in z.get("levels", []):
                for r in z["cellRanges"]:
                    for i in range(self.ax_names.index(r["xFrom"]), self.ax_names.index(r["xTo"])):
                        for j in range(self.ay_names.index(r["yFrom"]), self.ay_names.index(r["yTo"])):
                            cfz_all.add((i, j))
        pos = []
        for an in self.struct_x:
            for bn in self.struct_y:
                ai = self.ax_names.index(an)
                aj = self.ay_names.index(bn)
                adj = [(ai - 1, aj - 1), (ai, aj - 1), (ai - 1, aj), (ai, aj)]
                inside = [c for c in adj if c in lv["solid"]]
                if not inside:
                    continue
                if len(inside) == 4 and all(c in cfz_all for c in inside):
                    continue
                if "L1" in exc.get((an, bn), set()):
                    continue
                pos.append((self.ax_off[an], self.ay_off[bn]))
        return pos

    def crane_stations(self, step, off):
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


def _coverage_gap(rows, x0, y0, x1, y1):
    """高速パス: ボックスが領域に完全に覆われていれば 0、そうでなければ正の値（概算）"""
    js = sorted(j for j, (ry0, ry1, _ivs) in rows.items() if ry1 > y0 + 1e-9 and ry0 < y1 - 1e-9)
    if not js:
        return 1.0
    over = max(rows[js[0]][0] - y0, y1 - rows[js[-1]][1], 0.0)
    for j in js:
        _ry0, _ry1, ivs = rows[j]
        cur = x0
        for (ix0, ix1) in ivs:
            if ix1 <= x0 + 1e-9 or ix0 >= x1 - 1e-9:
                continue
            if ix0 > cur + 1e-9:
                over = max(over, ix0 - cur)
            cur = max(cur, ix1)
        if cur < x1 - 1e-9:
            over = max(over, x1 - cur)
    return over


def _dist_to_rects(rects, px, py):
    best = float("inf")
    for (rx0, ry0, rx1, ry1) in rects:
        dx = max(rx0 - px, 0.0, px - rx1)
        dy = max(ry0 - py, 0.0, py - ry1)
        d = math.hypot(dx, dy)
        if d < best:
            best = d
    return best


def box_overhang(rows, x0, y0, x1, y1):
    """ボックス平面が領域からはみ出す最大距離 [m]。
    完全内包なら 0（高速パス）。はみ出しがある場合は候補点（角・辺中点・中心・
    領域境界との交点）から領域までのユークリッド距離の最大で測る。"""
    if _coverage_gap(rows, x0, y0, x1, y1) <= 1e-9:
        return 0.0
    rects = []
    for (ry0, ry1, ivs) in rows.values():
        for (ix0, ix1) in ivs:
            rects.append((ix0, ry0, ix1, ry1))
    cand = [(x0, y0), (x0, y1), (x1, y0), (x1, y1),
            ((x0 + x1) / 2, (y0 + y1) / 2), ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1),
            (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
    for (ry0, ry1, ivs) in rows.values():
        for yy in (ry0, ry1):
            if y0 < yy < y1:
                cand.append((x0, yy))
                cand.append((x1, yy))
        for (ix0, ix1) in ivs:
            for xx in (ix0, ix1):
                if x0 < xx < x1:
                    cand.append((xx, y0))
                    cand.append((xx, y1))
    return max(_dist_to_rects(rects, px, py) for (px, py) in cand)


def rect_overhang(rect, x0, y0, x1, y1):
    rx0, ry0, rx1, ry1 = rect
    return max(rx0 - x0, ry0 - y0, x1 - rx1, y1 - ry1, 0.0)


def box_hits_rows(rows, x0, y0, x1, y1, eps=1e-6):
    """ボックス平面が領域（行マージ済み区間）と面積を持って重なるか。
    SV-01 の仮囲い・ゲート用ハードゲート（フットプリント交差判定）に使う。"""
    for (ry0, ry1, ivs) in rows.values():
        if ry1 <= y0 + eps or ry0 >= y1 - eps:
            continue
        for (ix0, ix1) in ivs:
            if ix1 > x0 + eps and ix0 < x1 - eps:
                return True
    return False


# ---------------------------------------------------------------- 種別分類
# kind -> (region種別, 許容キー)。region: solid/floor/roof/site/shaft:*/core/foundation
REGION_OF_KIND = {}


def _reg(kinds, region, tol):
    for k in kinds:
        REGION_OF_KIND[k] = (region, tol)


def build_classification(tol):
    _reg(["column", "girder", "brace", "joist", "deckPanel", "rebarMat", "rebarBundle", "groundSlab"],
         "solid", tol["frame"])
    _reg(["extWallPanel"], "solid", tol["extWallPanel"])
    _reg(["sash", "doorExt", "shopfront", "shutter"], "solid", tol["sash"])
    _reg(["canopy"], "solid", tol["canopy"])
    _reg(["scaffoldUnit"], "solidL1", tol["scaffoldUnit"])
    _reg(["retainingPanel", "excavationTile", "blinding"], "solidL1", tol["site"])
    _reg(["lgsFrame", "wallBoard", "ceilFrame", "ceilingBoard", "floorFinish", "doorLeaf",
          "outletSet", "lightSet", "diffuser", "plumbFixtureSet", "indoorUnit",
          "duct", "cableRack", "plumbPipe", "refrigerantPipe", "hangerSet"],
         "solid", tol["interior"])
    _reg(["roofSheet", "roofProtection", "parapet", "roofDrain", "cubicle", "cubiclePad"],
         "roof", tol["roof"])
    _reg(["stairFlight"], "shaft:階段", tol["interior"])
    _reg(["evRail", "evCar", "evMachine"], "shaft:EV", tol["interior"])
    _reg(["psRiser"], "shaft:PS", tol["interior"])
    _reg(["ductRiser"], "shaft:DS", tol["interior"])
    _reg(["trunkRiser"], "shaft:any", tol["interior"])
    _reg(["pile", "footing", "footingForm", "gradeBeam", "gradeBeamForm", "pitFloor", "pitWall", "buriedCable"],
         "foundation", tol.get("foundation", tol["site"]))
    _reg(["batterBoard"], "site", tol.get("batterBoard", 2.0))
    _reg(["tempFence", "tempGate", "tempOffice", "tempToilet", "tempSmoking", "tempPole", "tempPanel",
          "servicePole", "extBase", "extPave", "lineMarking", "lightPole", "tree", "buriedPipe"],
         "site", tol["site"])


EXT_KINDS = {"extWallPanel", "sash", "doorExt", "shopfront", "shutter", "canopy"}
INT_KINDS = {"lgsFrame", "wallBoard", "ceilFrame", "ceilingBoard", "floorFinish", "doorLeaf",
             "outletSet", "lightSet", "diffuser", "plumbFixtureSet", "indoorUnit",
             "duct", "ductRiser", "plumbPipe", "cableRack", "refrigerantPipe", "hangerSet", "psRiser"}
CONCEALED_KINDS = {"duct", "plumbPipe", "cableRack", "refrigerantPipe"}


def infer_level(geo: Geo, member):
    if member.get("level"):
        return member["level"]
    zc = member["box"]["z"] + member["box"]["dz"] / 2
    for lid, lv in geo.levels.items():
        if lv["elev"] - 0.01 <= zc < lv["elev"] + lv["fh"] + 0.01:
            return lid
    return geo.top_level_id


# ---------------------------------------------------------------- SV 実装
def sv01(geo, scene, tol):
    build_classification(tol)
    fails = []
    worst = (0.0, None)
    col_positions = {(round(x, 3), round(y, 3)) for (x, y) in geo.columns_l1()}
    rows_cache = {}
    l1_rows = geo.rows(geo.levels["L1"]["solid"])
    fence_gate_checked = 0
    for m in scene["members"]:
        kind = m["kind"]
        if kind not in REGION_OF_KIND:
            fails.append(f"未分類の部材種別: {kind} ({m['id']})")
            continue
        region, t = REGION_OF_KIND[kind]
        box = m["box"]
        x0, y0 = box["x"], box["y"]
        x1, y1 = x0 + box["dx"], y0 + box["dy"]
        if kind in ("tempFence", "tempGate"):
            # ハードゲート（2026-11-11）: 仮囲い・ゲートに限って実効敷地（ポリゴン∪平面）
            # の回避をやめる。実ポリゴン bbox での内包判定に加え、建物フットプリント
            # （L1セル群）と交差したら FAIL とする（亀有の仮囲い干渉の再発防止）。
            fence_gate_checked += 1
            over = rect_overhang(geo.site_bbox, x0, y0, x1, y1)
            if box_hits_rows(l1_rows, x0, y0, x1, y1):
                fails.append(f"{kind} {m['id']}: 建物フットプリント（L1）と交差している (task {m['task']})")
                continue
        elif region == "site":
            over = rect_overhang(geo.eff_site_bbox, x0, y0, x1, y1)
        elif region == "foundation":
            over = rect_overhang(geo.eff_site_bbox, x0, y0, x1, y1)
            if kind in ("pile", "footing", "footingForm"):
                c = (round(x0 + box["dx"] / 2, 3), round(y0 + box["dy"] / 2, 3))
                if c not in col_positions:
                    fails.append(f"{kind} {m['id']}: 中心 {c} が柱位置に一致しない")
                    continue
            if kind in ("pitFloor", "pitWall"):
                ev_rects = [r for sid, r in geo.shaft_rect.items() if geo.shaft_kind[sid] == "EV"]
                if not any(rect_overhang(r, x0, y0, x1, y1) <= 0.3 for r in ev_rects):
                    fails.append(f"{kind} {m['id']}: EVシャフト直下に無い")
                    continue
                over = 0.0
        elif region.startswith("shaft:"):
            want = region.split(":")[1]
            rects = [r for sid, r in geo.shaft_rect.items()
                     if want == "any" or geo.shaft_kind[sid] == want]
            over = min((rect_overhang(r, x0, y0, x1, y1) for r in rects), default=float("inf"))
        else:
            level_id = "L1" if region == "solidL1" else infer_level(geo, m)
            rgn = "solid" if region in ("solid", "solidL1") else region
            key = (rgn, level_id)
            if key not in rows_cache:
                rows_cache[key] = geo.region_rows(rgn, level_id)
            over = box_overhang(rows_cache[key], x0, y0, x1, y1)
        if over > worst[0]:
            worst = (over, kind)
        if over > t + 1e-9:
            if len(fails) < 15:
                fails.append(f"{kind} {m['id']}: はみ出し {over:.2f}m > 許容 {t}m (task {m['task']})")
    return (not fails), fails, (f"最大はみ出し {worst[0]:.2f}m（{worst[1]}）"
                                f" / 仮囲い・ゲート {fence_gate_checked} 件は実ポリゴン＋フットプリント交差で判定")


def sv02(geo, scene, plan):
    fails = []
    frm_ef = max(t["ef"] for t in plan["tasks"] if t["id"].startswith("frm-"))
    task_es = {t["id"]: t["es"] for t in plan["tasks"]}
    for m in scene["members"]:
        if m["kind"] in EXT_KINDS or m["kind"] in INT_KINDS:
            es = task_es.get(m["task"])
            if es is None or es < frm_ef - 1e-6:
                fails.append(f"{m['kind']} {m['id']}: タスク {m['task']} の es={es} が躯体完了 {frm_ef} より前")
                if len(fails) >= 10:
                    break
    # 天井ボードは隠蔽設備の後
    place_t = {}
    for e in scene["events"]:
        if e["type"] == "place" and e.get("member"):
            place_t[e["member"]] = e["t"]
    concealed_max = {}
    for m in scene["members"]:
        if m["kind"] in CONCEALED_KINDS and m.get("zone") and m["id"] in place_t:
            concealed_max[m["zone"]] = max(concealed_max.get(m["zone"], -1), place_t[m["id"]])
    n_ceiling = 0
    for m in scene["members"]:
        if m["kind"] == "ceilingBoard" and m.get("zone") in concealed_max:
            n_ceiling += 1
            if place_t.get(m["id"], -1) < concealed_max[m["zone"]] - 1e-6:
                fails.append(f"ceilingBoard {m['id']}: 工区 {m['zone']} の隠蔽設備完了前に出現")
                if len(fails) >= 15:
                    break
    return (not fails), fails, f"躯体完了 ef={frm_ef} / 天井ボード検査対象 {n_ceiling} 枚"


def sv03(scene, plan, game):
    fails = []
    tasks = {t["id"]: t for t in plan["tasks"]}
    gtasks = {t["id"]: t for t in game["tasks"]}
    member_ids = {m["id"] for m in scene["members"]}
    actor_ids = {a["id"] for a in scene["actors"]}
    placed = set()
    appeared = set()
    for e in scene["events"]:
        t = tasks.get(e["task"])
        if t is None:
            fails.append(f"event {e['id']}: 計画に無いタスク {e['task']}")
            continue
        if not (0.0 - EPS <= e["u"] <= 1.0 + EPS):
            fails.append(f"event {e['id']}: u={e['u']} が範囲外")
        if not (t["es"] - 1e-4 <= e["t"] <= t["ef"] + 1e-4):
            fails.append(f"event {e['id']}: t={e['t']} がタスク期間 [{t['es']}, {t['ef']}] 外（{e['task']}）")
        gt = gtasks.get(e["task"])
        if gt is not None and "g" in e:
            if not (gt["gameStart"] - 1 - 1e-4 <= e["g"] <= gt["gameEnd"] + 1e-4):
                fails.append(f"event {e['id']}: g={e['g']} がゲーム期間外（{e['task']}）")
        if e.get("member") and e["member"] not in member_ids:
            fails.append(f"event {e['id']}: 存在しない部材 {e['member']}")
        if e.get("members"):
            for mid in e["members"]:
                if mid not in member_ids:
                    fails.append(f"event {e['id']}: 存在しない部材 {mid}")
        if e.get("actor") and e["actor"] not in actor_ids:
            fails.append(f"event {e['id']}: 存在しないアクター {e['actor']}")
        if e["type"] == "place" and e.get("member"):
            placed.add(e["member"])
        if e["type"] in ("place", "stock") and e.get("member"):
            appeared.add(e["member"])
        if len(fails) >= 15:
            break
    missing = member_ids - appeared
    if missing:
        fails.append(f"出現イベント（place/stock）の無い部材が {len(missing)} 件（例: {sorted(missing)[:5]}）")
    return (not fails), fails, f"イベント {len(scene['events'])} 件 / 出現済み部材 {len(appeared)}/{len(member_ids)}（うち place {len(placed)}）"


def sv04(building_path: Path, scene):
    sys.path.insert(0, str(HERE))
    import scene_expand
    h1 = scene_expand.expand(building_path)["meta"]["contentHash"]
    h2 = scene_expand.expand(building_path)["meta"]["contentHash"]
    file_hash = scene["meta"]["contentHash"]
    ok = h1 == h2 == file_hash
    return ok, [] if ok else [f"ハッシュ不一致: 再生成1 {h1[:12]} / 再生成2 {h2[:12]} / ファイル {file_hash[:12]}"], h1


def sv05(scene, rules):
    budget = int(rules["global"]["faceBudgetOpaque"])
    std = scene["stats"]["faceEstimateStandardView"]
    total = scene["stats"]["faceEstimateTotal"]
    ok = std <= budget
    return ok, [] if ok else [f"全体表示の面数見積 {std} が予算 {budget} を超過"], \
        f"全体表示 {std} 面（予算 {budget}）／全詳細 {total} 面"


def sv06(geo, scene, cp0):
    pos = set()
    for m in scene["members"]:
        if m["kind"] == "column" and abs(m["box"]["z"]) < 1e-9:
            pos.add((round(m["box"]["x"] + m["box"]["dx"] / 2, 3),
                     round(m["box"]["y"] + m["box"]["dy"] / 2, 3)))
    expect = cp0["quantities"]["columnCount1F"]
    ok = len(pos) == expect
    return ok, [] if ok else [f"1F柱位置 {len(pos)} が CP-0 の {expect} と不一致"], f"1F柱位置 {len(pos)}（CP-0: {expect}）"


def sv07(geo, scene, rules):
    reach = float(rules["global"]["craneReachM"])
    step = float(rules["global"]["craneStationStepM"])
    off = float(rules["global"]["craneStationOffsetM"])
    stations = geo.crane_stations(step, off)
    carry = {e["member"] for e in scene["events"] if e["type"] == "carry" and e.get("member")}
    fails = []
    n_carry = 0
    for m in scene["members"]:
        if m["kind"] not in ("column", "girder"):
            continue
        cx = m["box"]["x"] + m["box"]["dx"] / 2
        cy = m["box"]["y"] + m["box"]["dy"] / 2
        d = min(math.hypot(cx - sx, cy - sy) for (sx, sy) in stations)
        if d > reach + 1e-6:
            if m["id"] in carry:
                n_carry += 1
            else:
                fails.append(f"{m['kind']} {m['id']}: 最寄りステーション {d:.1f}m > 届く距離 {reach}m なのに横引きが無い")
                if len(fails) >= 10:
                    break
    crane = scene["meta"].get("cranePlan", {})
    if crane.get("タワークレーン") != "採用しない":
        fails.append(f"タワークレーン計画が想定外: {crane}")
    if "ラフター" not in crane.get("揚重", ""):
        fails.append(f"揚重計画がラフター基準でない: {crane}")
    return (not fails), fails, f"横引きで解決した部材 {n_carry} 件 / ステーション {len(stations)} 箇所"


# ---------------------------------------------------------------- 実行
def validate(building_path: Path) -> dict:
    stem = building_path.stem.removeprefix("generated_")
    b = load(building_path)
    plan = load(HERE / f"generated_construction_plan_{stem}.json")
    game = load(HERE / "integration" / f"generated_game_schedule_{stem}.json")
    cp0 = load(HERE / f"generated_plan_cp0_{stem}.json")
    rules = load(HERE / "scene_rules.json")
    scene = load(HERE / f"generated_scene3d_{stem}.json")
    geo = Geo(b)
    tol = rules["tolerancesM"]
    results = {}
    results["SV-01 支持・突出"] = sv01(geo, scene, tol)
    results["SV-02 出現順序"] = sv02(geo, scene, plan)
    results["SV-03 時刻・参照"] = sv03(scene, plan, game)
    results["SV-04 決定性"] = sv04(building_path, scene)
    results["SV-05 面数予算"] = sv05(scene, rules)
    results["SV-06 柱本数突合"] = sv06(geo, scene, cp0)
    results["SV-07 クレーン計画"] = sv07(geo, scene, rules)
    return {"building": b["building"]["name"], "stem": stem, "results": results, "scene": scene,
            "site_warning": geo.site_warning}


def main():
    if len(sys.argv) > 1:
        paths = [Path(sys.argv[1])]
    else:
        paths = [HERE / "generated_game_mall.json",
                 HERE / "generated_commercial_seeded2.json",
                 HERE / "generated_commercial_seeded2_kameari.json"]
    all_ok = True
    for p in paths:
        if not p.is_absolute():
            p = HERE / p
        v = validate(p)
        s = v["scene"]["stats"]
        print(f"■ {v['building']}（{v['stem']}）部材 {s['memberCount']} / イベント {s['eventCount']}")
        if v.get("site_warning"):
            print(f"  ⚠ {v['site_warning']}")
        for name, (ok, fails, info) in v["results"].items():
            mark = "PASS" if ok else "FAIL"
            if not ok:
                all_ok = False
            print(f"  {name}: {mark} — {info}")
            for f in fails[:5]:
                print(f"      ✗ {f}")
    print("=== 総合:", "全SV PASS" if all_ok else "FAIL あり", "===")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
