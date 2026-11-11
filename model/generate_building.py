#!/usr/bin/env python3
"""建物生成器（最小試作）— USE_RULES のルールをパラメータから実行し、
BUILDING_MODEL_SCHEMA v0.3 の建物モデル JSON を生成する。
対応：商業施設（形状パラメータ rectangle/stepped/L/setback）・マンション（片廊下型）
・シード生成 seeded（実在建物の外形シードから商業レイアウトを割り付け）。
生成物は validate_building_model.py で検証する。
使い方: python3 generate_building.py commercial [out.json] [shape] / mansion [out.json]
       python3 generate_building.py seeded <out.json> <conversion.json>
       python3 generate_building.py seeded2 <out.json> <conversion.json> <annotation.json>
       （seeded2 は INTERIOR_MODEL_V2 の3層方式：annotation=公開資料の制約＋建築計画ノルムの裏側フィル）
       （conversion.json は footprint_to_plate.py の出力。バンド方式：中央モール帯から
        外側へ テナント→モール→テナント を繰り返し、北側最外帯はサービスに寄せる。
        階数は計測高さ÷5.4m で推定。階別セットバックは元データに無いため未対応。）"""
import json, sys

# ---------- 共通の組み立て部品 ----------

def axes(spans):
    out, acc = [], 0
    for i, s in enumerate(spans):
        out.append({"name": f"A{i+1}", "offset": acc})
        acc += s
    out.append({"name": f"A{len(spans)+1}", "offset": acc})
    return out

def make_axes(spans, prefix):
    out, acc = [], 0
    for i, s in enumerate(spans):
        out.append({"name": f"{prefix}{i+1}", "offset": acc})
        acc += s
    out.append({"name": f"{prefix}{len(spans)+1}", "offset": acc})
    return out

def select_structural_axes(spans, target=9000):
    """SPAN_STANDARD.md の構造軸選定：補助軸（部屋割りグリッド）のうち、端から
    約 target mm ピッチの位置に最も近い軸を構造軸として選ぶ。両端の軸は必ず含む。
    柱・大梁は構造軸の交点にのみ置く（構造軸/補助軸の分離）。"""
    offs = [0]
    for s in spans:
        offs.append(offs[-1] + s)
    total = offs[-1]
    chosen = {0, len(offs) - 1}
    k = 1
    while k * target < total:
        t = k * target
        chosen.add(min(range(len(offs)), key=lambda i: abs(offs[i] - t)))
        k += 1
    return sorted(chosen)

def room(id_, level, name, use, xi0, xi1, yi0, yi1, zone, ceil=3600):
    return {"id": id_, "level": level, "name": name, "use": use, "ceilingHeight": ceil,
            "cells": {"xFrom": f"X{xi0+1}", "xTo": f"X{xi1+1}",
                      "yFrom": f"Y{yi0+1}", "yTo": f"Y{yi1+1}"}, "zoneId": zone}

def build_walls(rooms, level, nx, ny, decide, idprefix):
    """セル→Room の割り当てから全ての境界に壁を立てる。
    decide(useA, useB, horizontal, axis_name) -> (kind, opening|None, skip)
    useA/useB は外側が None。horizontal=True は Y 軸上の壁（左右に連なる）。"""
    cell = {}
    for r in rooms:
        c = r["cells"]
        xi0 = int(c["xFrom"][1:]) - 1; xi1 = int(c["xTo"][1:]) - 1
        yi0 = int(c["yFrom"][1:]) - 1; yi1 = int(c["yTo"][1:]) - 1
        for i in range(xi0, xi1):
            for j in range(yi0, yi1):
                cell[(i, j)] = r
    walls = []
    def emit(axis, frm, to, kind, opening):
        wid = f"wall:{idprefix}-{axis}-{frm}-{to}"
        ops = []
        if opening:
            k, wdt, seg_start, seg_len = opening
            ops.append({"id": f"op:{wid}-1", "kind": k, "offsetFromStart": seg_start + (seg_len - wdt) // 2,
                        "width": wdt, "height": 2100, "sillHeight": 0 if k != "サッシ" else 300})
        walls.append({"id": wid, "level": level, "kind": kind,
                      "thickness": 200 if kind in ("外壁", "シャフト壁", "戸境") else 120,
                      "line": {"axis": axis, "from": frm, "to": to}, "openings": ops})
    # 水平壁（Y軸上）：境界 b=0..ny、各 x セル
    for b in range(ny + 1):
        for i in range(nx):
            below = cell.get((i, b - 1)) if b > 0 else None
            above = cell.get((i, b)) if b < ny else None
            if below is above:
                continue
            kind, opening, skip = decide(below["use"] if below else None,
                                         above["use"] if above else None, True, f"Y{b+1}")
            if skip:
                continue
            op = (opening[0], opening[1], 0, 0) if opening else None
            emit(f"Y{b+1}", f"X{i+1}", f"X{i+2}", kind, None if not opening else
                 (opening[0], opening[1], SPANX[i] * 0, SPANX[i]))
    # 垂直壁（X軸上）：境界 a=0..nx、各 y セル
    for a in range(nx + 1):
        for j in range(ny):
            left = cell.get((a - 1, j)) if a > 0 else None
            right = cell.get((a, j)) if a < nx else None
            if left is right:
                continue
            kind, opening, skip = decide(left["use"] if left else None,
                                         right["use"] if right else None, False, f"X{a+1}")
            if skip:
                continue
            emit(f"X{a+1}", f"Y{j+1}", f"Y{j+2}", kind, None if not opening else
                 (opening[0], opening[1], 0, SPANY[j]))
    # 同一線上の連続セグメントを統合する（セル単位では壁の本数が過剰になる）。
    # 開口は統合後の始点からのオフセットに振り直し、ID は統合後のスパンで付け直す
    def _cum(spans):
        out = [0]
        for s in spans:
            out.append(out[-1] + s)
        return out
    _cx, _cy = _cum(SPANX), _cum(SPANY)
    def _off(name):
        return _cx[int(name[1:]) - 1] if name.startswith("X") else _cy[int(name[1:]) - 1]
    from collections import defaultdict as _ddm
    _groups = _ddm(list)
    for w in walls:
        _groups[(w["line"]["axis"], w["kind"], w["thickness"])].append(w)
    merged = []
    for (axis, kind, th), ws in _groups.items():
        ws.sort(key=lambda w: _off(w["line"]["from"]))
        cur = None
        for w in ws:
            ln = w["line"]
            s, e = _off(ln["from"]), _off(ln["to"])
            if cur is not None and s == cur["_end"]:
                cur["_end"] = e
                cur["_to"] = ln["to"]
                for o in w["openings"]:
                    no = dict(o)
                    no["offsetFromStart"] = (s - cur["_start"]) + o["offsetFromStart"]
                    cur["openings"].append(no)
            else:
                if cur is not None:
                    merged.append(cur)
                cur = dict(w)
                cur["openings"] = [dict(o) for o in w["openings"]]
                cur["_start"], cur["_end"], cur["_to"] = s, e, ln["to"]
        if cur is not None:
            merged.append(cur)
    out_walls = []
    for w in merged:
        axis = w["line"]["axis"]
        frm, to = w["line"]["from"], w.pop("_to")
        w.pop("_start"); w.pop("_end")
        prefix = "-".join(w["id"].split("-")[:-3])
        w["id"] = f"{prefix}-{axis}-{frm}-{to}"
        w["line"] = {"axis": axis, "from": frm, "to": to}
        for k, o in enumerate(w["openings"]):
            o["id"] = f"op:{w['id']}-{k+1}"
        out_walls.append(w)
    return out_walls

SPANX = []
SPANY = []

def base_parts(bid, name, use, structure, spans_x, spans_y, floor_heights, sprinkler=False):
    global SPANX, SPANY
    SPANX, SPANY = spans_x, spans_y
    levels, acc = [], 0
    for i, fh in enumerate(floor_heights):
        levels.append({"id": f"L{i+1}", "name": f"{i+1}F", "elevation": acc, "floorHeight": fh})
        acc += fh
    grid = {"axesX": make_axes(spans_x, "X"), "axesY": make_axes(spans_y, "Y"),
            "columnRule": "all-intersections", "columnExceptions": [],
            "beamRule": "all-grid-lines-both-directions-each-level"}
    # 構造軸/補助軸の分離（SPAN_STANDARD.md、大規模商業・S造が対象）：
    # グリッド自体は部屋割りの補助軸として細かくてよいが、柱・大梁は
    # 9mモジュール（実務レンジ8〜10m）で選んだ構造軸上にのみ配置する。
    if use.startswith("商業"):
        six = select_structural_axes(spans_x)
        siy = select_structural_axes(spans_y)
        grid["structuralAxesX"] = [f"X{i + 1}" for i in six]
        grid["structuralAxesY"] = [f"Y{i + 1}" for i in siy]
        if len(six) < len(spans_x) + 1 or len(siy) < len(spans_y) + 1:
            grid["columnRule"] = "structural-intersections"
            grid["beamRule"] = "structural-grid-lines-both-directions-each-level"
            grid["structuralModule"] = {
                "targetMm": 9000, "rangeMm": [8000, 10000],
                "basis": "SPAN_STANDARD.md：構造軸と補助軸を分離し、柱・大梁は構造軸のみ。"
                         "構造軸は端から約9mピッチに最も近い既存軸を選定（シードグリッドの"
                         "量子化により個別スパンはレンジから外れる場合がある）"}
        else:
            grid["structuralModule"] = {
                "targetMm": 9000, "rangeMm": [8000, 10000],
                "basis": "SPAN_STANDARD.md：全軸が基準レンジ（8〜10m）内の構造軸"}
    b = {"building": {"id": bid, "name": name, "use": use, "structure": structure,
                      "floorHeightDefault": floor_heights[0],
                      "grossAreaTarget": sum(spans_x) * sum(spans_y) * len(levels) // 1000000},
         "grid": grid,
         "levels": levels,
         "foundations": {"footings": {"rule": "each-column", "size": {"w": 2400, "d": 2400},
                                      "thickness": 800, "topElevation": -600},
                         "gradeBeams": "all-grid-lines-below-ground", "piles": None}}
    if sprinkler:
        b["building"]["sprinklerFull"] = True
    full = {"xFrom": "X1", "xTo": f"X{len(spans_x)+1}", "yFrom": "Y1", "yTo": f"Y{len(spans_y)+1}"}
    b["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cells": full, "depth": 1500}]
    b["roof"] = {"id": "roof:main", "topLevel": f"L{len(levels)}", "kind": "陸屋根（シート防水）",
                 "cells": full, "parapetHeight": 600}
    return b, full

def commercial_decide(useA, useB, horiz, axis):
    pair = {useA, useB}
    if "吹抜け" in pair:
        if "モール" in pair:
            return ("間仕切", None, True)
        if pair & {"テナント", "飲食"}:
            return ("間仕切", ("両開き戸", 1600), False)
        return ("間仕切", None, False)
    if useA is None or useB is None:
        inner = useB if useA is None else useA
        if not horiz and inner in ("テナント", "飲食"):
            # 棟端の区画は外から直接入れる出入口を持つ（雁行の段差部もここで受ける）
            return ("外壁", ("両開き戸", 2000), False)
        if inner == "テナント":
            return ("外壁", ("サッシ", 5000), False)
        if inner == "モール":
            return ("外壁", ("両開き戸", 2400), False)
        if inner == "物販":
            return ("外壁", ("両開き戸", 2400), False)
        if inner == "大型店":
            return ("外壁", ("両開き戸", 2000), False)
        if inner == "バックヤード":
            return ("外壁", ("シャッター", 3000), False)
        if inner == "飲食":
            return ("外壁", ("サッシ", 5000), False)
        return ("外壁", ("片開き戸", 1000), False)
    if pair == {"テナント", "モール"} or pair == {"飲食", "モール"}:
        return ("間仕切", ("両開き戸", 1600), False)
    if pair == {"モール", "コアホール"}:
        return ("間仕切", ("両開き戸", 1600), False)
    if pair == {"モール", "WC"}:
        return ("間仕切", ("片開き戸", 900), False)
    if pair == {"物販", "物販"}:
        return ("間仕切", ("シャッター", 3000), False)  # 売場内の区画は防火シャッター
    if pair == {"大型店", "モール"}:
        return ("間仕切", ("両開き戸", 2000), False)
    if pair == {"大型店", "物販"}:
        return ("間仕切", ("片開き戸", 900), False)
    if pair == {"物販", "モール"}:
        return ("間仕切", ("両開き戸", 2400), False)
    if pair in ({"物販", "バックヤード"}, {"物販", "コアホール"}):
        return ("間仕切", ("片開き戸", 900), False)
    if pair == {"フードコート", "モール"}:
        return ("間仕切", ("両開き戸", 2400), False)
    if pair == {"フードコート", "フードコート"}:
        return ("間仕切", ("両開き戸", 1600), False)
    if pair == {"フードコート", "物販"}:
        return ("間仕切", ("両開き戸", 2000), False)
    if pair == {"フードコート", "飲食"}:
        return ("間仕切", ("両開き戸", 1600), False)
    if pair == {"大型店", "大型店"}:
        return ("間仕切", ("シャッター", 3000), False)
    if pair in ({"大型店", "テナント"}, {"大型店", "バックヤード"}, {"大型店", "飲食"},
                {"WC", "コアホール"}, {"WC", "テナント"}, {"WC", "バックヤード"}):
        return ("間仕切", ("片開き戸", 900), False)
    if pair in ({"テナント", "コアホール"}, {"大型店", "コアホール"}, {"飲食", "コアホール"},
                {"コアホール", "コアホール"}, {"フードコート", "コアホール"}):
        return ("間仕切", ("片開き戸", 900), False)
    if pair in ({"防災センター", "コアホール"}, {"バックヤード", "コアホール"},
                {"防災センター", "バックヤード"}, {"防災センター", "テナント"},
                {"防災センター", "モール"}, {"バックヤード", "テナント"},
                {"バックヤード", "飲食"}, {"バックヤード", "バックヤード"}):
        return ("間仕切", ("片開き戸", 900), False)
    return ("間仕切", None, False)

# ---------- 商業施設 ----------
# USE_RULES §1：グリッドは駐車モジュール（9m）、モール8m、コアは北側に約100m間隔、
# 階段は歩行距離から逆算、飲食は最上階、貨物EVは2基以上、防災センターは1F。

def gen_commercial(spans_n=8, span=9000, floors=3, shape="rectangle"):
    """shape: rectangle（長方形）/ stepped（雁行）/ L（L字）/ setback（階別セットバック）。
    形状は「列ごとのスパン区間」で表す：行（南テナント／モール／北）ごとに
    その階で存在するスパンの区間 [start, end) を返す。プレート＝区間の和集合。"""
    if shape == "stepped":
        nx = spans_n + 2
        def intervals(li):
            return (0, spans_n), (1, spans_n + 1), (2, spans_n + 2)
    elif shape == "L":
        nx = spans_n
        def intervals(li):
            return (0, spans_n), (0, spans_n), (0, spans_n - 3)
    elif shape == "setback":
        nx = spans_n
        def intervals(li):
            if li == 0:
                return (0, spans_n), (0, spans_n), (0, spans_n)
            if li == 1:
                return (0, spans_n - 1), (0, spans_n - 1), (0, spans_n - 1)
            return (0, spans_n - 2), (0, spans_n - 2), (0, spans_n - 3)
    else:
        nx = spans_n
        def intervals(li):
            return (0, spans_n), (0, spans_n), (0, spans_n)
    spans_x = [span] * nx
    spans_y = [14000, 8000, 14000]
    fh = [5400] * floors
    b, full = base_parts("bldg:gen-commercial", f"生成：商業施設（{shape}）", "商業", "S",
                         spans_x, spans_y, fh, sprinkler=True)
    X = {a["name"]: a["offset"] for a in b["grid"]["axesX"]}
    levels_all = [f"L{i+1}" for i in range(floors)]
    # コアは最上階の北区間から決める（全階で同じスパンに立つ＝縦連続）
    tn0, tn1 = intervals(floors - 1)[2]
    core_spans = sorted({tn0, (tn0 + tn1) // 2, tn1 - 1})
    # 南列が北列より大きく張り出す形状（L字など）では南端にもコアを置く（歩行距離の担保）
    _s_end = min(intervals(li)[0][1] for li in range(floors))
    _s_start = max(intervals(li)[0][0] for li in range(floors))
    south_core_spans = []
    if _s_end - tn1 >= 3:
        south_core_spans.append(_s_end - 1)
    if tn0 - _s_start >= 3:
        south_core_spans.append(_s_start)
    rooms, walls, zones, compartments = [], [], [], []
    shafts, cores = [], []

    for ci, cs in enumerate(core_spans):
        cid = f"core:C{ci}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{cs+1}", "xTo": f"X{cs+2}", "yFrom": "Y3", "yTo": "Y4"}})
        x0, y0 = X[f"X{cs+1}"], 22000
        defs = [("stair", "階段", x0 + 200, y0 + 200, 3400, 9000, {"riser": 180, "steps": 30, "going": 260}),
                ("ev", "EV", x0 + 3800, y0 + 200, 2300, 2300, None),
                ("ps", "PS", x0 + 6300, y0 + 200, 1200, 3000, None),
                ("ds", "DS", x0 + 7700, y0 + 200, 1000, 3000, None)]
        if ci in (0, len(core_spans) - 1):
            defs.append(("fev", "EV", x0 + 3800, y0 + 8000, 2600, 2600, {"freight": True}))
        for suf, kind, fx, fy, w, d, extra in defs:
            s = {"id": f"shaft:{cid.split(':')[1]}-{suf}", "coreId": cid, "kind": kind,
                 "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
            if suf == "stair":
                s["stair"] = extra
            elif suf == "fev":
                s["freight"] = True
            shafts.append(s)
            compartments.append({"id": f"fc:shaft-{cid.split(':')[1]}-{suf}", "kind": "竪穴区画",
                                 "shafts": [s["id"]]})
    for si, cs in enumerate(south_core_spans):
        cid = f"core:S{si}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{cs+1}", "xTo": f"X{cs+2}", "yFrom": "Y1", "yTo": "Y2"}})
        x0 = X[f"X{cs+1}"]
        for suf, kind, fx, fy, w, d, extra in (
                ("stair", "階段", x0 + 200, 200, 3400, 9000, {"riser": 180, "steps": 30, "going": 260}),
                ("ev", "EV", x0 + 3800, 200, 2300, 2300, None),
                ("ps", "PS", x0 + 6300, 200, 1200, 3000, None)):
            s = {"id": f"shaft:S{si}-{suf}", "coreId": cid, "kind": kind,
                 "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
            if suf == "stair":
                s["stair"] = extra
            shafts.append(s)
            compartments.append({"id": f"fc:shaft-S{si}-{suf}", "kind": "竪穴区画",
                                 "shafts": [s["id"]]})
    # 吹抜け：最上階モール区間の中央2スパン（コア位置は全階共通）
    tm0, tm1 = intervals(floors - 1)[1]
    v0 = tm0 + (tm1 - tm0) // 2 - 1
    void_spans = (v0, v0 + 1)
    if floors > 1:
        cores.append({"id": "core:AT", "levelRange": levels_all[1:],
                      "rect": {"xFrom": f"X{v0+1}", "xTo": f"X{v0+3}", "yFrom": "Y2", "yTo": "Y3"}})
        shafts.append({"id": "shaft:AT-void", "coreId": "core:AT", "kind": "吹抜け",
                       "levelRange": levels_all[1:],
                       "footprint": {"x": X[f"X{v0+1}"] + 200, "y": 14200,
                                     "w": 2 * span - 400, "d": 7600}})
        compartments.append({"id": "fc:shaft-AT", "kind": "竪穴区画", "shafts": ["shaft:AT-void"]})

    footprints = {}
    for li in range(floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        (s0, s1), (m0, m1), (n0, n1) = intervals(li)
        fp = [{"xFrom": f"X{a+1}", "xTo": f"X{c+1}", "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"}
              for j, (a, c) in enumerate(((s0, s1), (m0, m1), (n0, n1)))]
        footprints[lid] = fp
        if shape != "rectangle":
            b["levels"][li]["footprint"] = fp
        fl = []
        def R(suf, name, use, xi0, xi1, yi0, yi1, zone=True, ceil=3600):
            mid = (xi0 + xi1) / 2
            zid = f"{ln}-W" if mid < nx / 3 else f"{ln}-C" if mid < 2 * nx / 3 else f"{ln}-E"
            r = room(f"room:{ln}-{suf}", lid, name, use, xi0, xi1, yi0, yi1,
                     zid if zone else None, ceil)
            fl.append(r); rooms.append(r)
            return r
        # 南列
        if li == 0:
            R("SM", "食品スーパー", "テナント", s0, s0 + 2, 0, 1)
            for i in range(s0 + 2, s1):
                if i in south_core_spans:
                    R(f"SCORE{i}", "コアホール", "コアホール", i, i + 1, 0, 1)
                else:
                    R(f"S{i+1}", f"テナントS{i+1}", "テナント", i, i + 1, 0, 1)
        elif li == floors - 1:
            half = (s0 + s1) // 2
            for i in range(s0, half):
                R(f"S{i+1}", f"レストランS{i+1}", "飲食", i, i + 1, 0, 1)
            _scs = [cs for cs in south_core_spans if half <= cs < s1]
            if _scs:
                _sc = _scs[0]
                if _sc > half:
                    R("FC", "フードコート", "飲食", half, _sc, 0, 1, ceil=4200)
                R(f"SCORE{_sc}", "コアホール", "コアホール", _sc, _sc + 1, 0, 1)
                if _sc + 1 < s1:
                    R("FC2", "フードコート", "飲食", _sc + 1, s1, 0, 1, ceil=4200)
            else:
                R("FC", "フードコート", "飲食", half, s1, 0, 1, ceil=4200)
        else:
            for i in range(s0, s1):
                if i in south_core_spans:
                    R(f"SCORE{i}", "コアホール", "コアホール", i, i + 1, 0, 1)
                else:
                    R(f"S{i+1}", f"テナントS{i+1}", "テナント", i, i + 1, 0, 1)
        # モール列
        if li == 0:
            R("MALL", "モール", "モール", m0, m1, 1, 2, zone=False, ceil=4800)
        else:
            if m0 < void_spans[0]:
                R("MALLW", "モール（西）", "モール", m0, void_spans[0], 1, 2, zone=False, ceil=4800)
            R("VOID", "吹抜け", "吹抜け", void_spans[0], void_spans[1] + 1, 1, 2, zone=False, ceil=4800)
            if void_spans[1] + 1 < m1:
                R("MALLE", "モール（東）", "モール", void_spans[1] + 1, m1, 1, 2, zone=False, ceil=4800)
        # 北列：割当を先に決める（コア→バックヤード→防災→WC→残り）
        assign = {}
        for cs in core_spans:
            if n0 <= cs < n1:
                assign[cs] = ("CORE",)
        if li == 0:
            placed = False
            for i in range(n0, n1 - 1):
                if i not in assign and (i + 1) not in assign:
                    assign[i] = ("BY", 2)
                    assign[i + 1] = ("BY-skip",)
                    placed = True
                    break
            if not placed:
                for i in range(n0, n1):
                    if i not in assign:
                        assign[i] = ("BY", 1)
                        break
            for i in range(n0, n1):
                if i not in assign:
                    assign[i] = ("BOUSAI",)
                    break
        for cs in core_spans:
            for cand in (cs + 1, cs - 1):
                if n0 <= cand < n1 and cand not in assign:
                    assign[cand] = ("WC",)
                    break
        i = n0
        while i < n1:
            a = assign.get(i)
            if a and a[0] == "CORE":
                ci = core_spans.index(i)
                R(f"CORE{ci}", "コアホール", "コアホール", i, i + 1, 2, 3)
                i += 1
            elif a and a[0] == "BY":
                R("BY", "バックヤード・荷捌き", "バックヤード", i, i + a[1], 2, 3)
                i += a[1]
            elif a and a[0] == "BY-skip":
                i += 1
            elif a and a[0] == "BOUSAI":
                R("BOUSAI", "防災センター", "防災センター", i, i + 1, 2, 3)
                i += 1
            elif a and a[0] == "WC":
                R(f"WC{i+1}", "便所・サービス", "WC", i, i + 1, 2, 3, ceil=3000)
                i += 1
            elif li == floors - 1:
                R(f"N{i+1}", f"レストランN{i+1}", "飲食", i, i + 1, 2, 3)
                i += 1
            else:
                R(f"N{i+1}", f"テナントN{i+1}", "テナント", i, i + 1, 2, 3)
                i += 1
        # 工区：プレートを x 方向3帯に分け、帯×行の区間を cellRanges に
        for suf, b0, b1 in (("W", 0, nx // 3), ("C", nx // 3, 2 * nx // 3), ("E", 2 * nx // 3, nx)):
            ranges = []
            for j, (a, c) in enumerate(((s0, s1), (m0, m1), (n0, n1))):
                lo, hi = max(a, b0), min(c, b1)
                if lo < hi:
                    ranges.append({"xFrom": f"X{lo+1}", "xTo": f"X{hi+1}",
                                   "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
            if ranges:
                zones.append({"id": f"{ln}-{suf}", "level": lid, "cellRanges": ranges})
        # 面積区画：東西2分割（SP全面で各 ≦3000㎡）
        mid_x = X[f"X{(m0 + m1) // 2 + 1}"]
        grpA = [r["id"] for r in fl if (X[r["cells"]["xFrom"]] + X[r["cells"]["xTo"]]) / 2 <= mid_x]
        grpB = [r["id"] for r in fl if r["id"] not in grpA]
        compartments.append({"id": f"fc:{ln}-A", "kind": "面積区画", "level": lid, "rooms": grpA})
        compartments.append({"id": f"fc:{ln}-B", "kind": "面積区画", "level": lid, "rooms": grpB})
        # 壁
        decide = commercial_decide
        walls += build_walls(fl, lid, nx, 3, decide, f"C-{ln}")
    b.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
              "zones": zones, "compartments": compartments})
    slabs = []
    for li in range(floors):
        lid = f"L{li+1}"
        ops = [s["id"] for s in shafts if lid in s["levelRange"]] if li > 0 else []
        sl = {"id": f"slab:{lid}", "level": lid,
              "kind": "土間コンクリート" if li == 0 else "デッキ合成スラブ",
              "thickness": 150, "openings": ops,
              **({"onGround": True} if li == 0 else {})}
        if shape == "rectangle":
            sl["cells"] = full
        else:
            sl["cellRanges"] = footprints[lid]
        slabs.append(sl)
    b["slabs"] = slabs
    if shape != "rectangle":
        b["roof"] = {"id": "roof:main", "topLevel": f"L{floors}", "kind": "陸屋根（シート防水）",
                     "cellRanges": footprints[f"L{floors}"], "parapetHeight": 600}
        b["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cellRanges": footprints["L1"],
                            "depth": 1500}]
    b["site"] = {"polygon": [[-15000, -12000], [110000, -12000], [110000, 50000], [-15000, 50000]],
                 "buildingPlacement": {"origin": [0, 0], "rotationDeg": 0},
                 "roads": [{"edge": "south", "name": "幹線道路", "width": 12000}],
                 "gates": [{"edge": "south", "name": "南ゲート", "atMm": 20000, "width": 8000}],
                 "neighbors": [{"edge": "north", "type": "住宅"}, {"edge": "south", "type": "道路"}]}
    core_room = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "コアホール"), None)
    mall_room = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "モール"), None)
    wc_room = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "WC"), None)
    ps_id = next((s["id"] for s in shafts if s["kind"] == "PS"), None)
    if core_room and mall_room and wc_room and ps_id:
        b["equipmentRuns"] = [{"id": "run:water-1F", "kind": "給水", "level": "L1",
                               "fromShaft": ps_id, "route": [core_room, mall_room, wc_room]}]
    if mall_room:
        b["coverings"] = [{"id": "cov:mall-floor", "target": mall_room, "part": "床", "name": "磁器質タイル"}]
    b["reinforcement"] = [{"id": "re:slab", "target": "slab:L2", "kind": "スラブ配筋", "spec": "D13@200 ダブル"},
                          {"id": "re:footing", "target": "foundation:each-column", "kind": "基礎配筋",
                           "spec": "主筋D19・あばら筋D13@150"}]
    ent = next((w for w in walls if w["level"] == "L1"
                and any(o["kind"] == "両開き戸" for o in w["openings"])
                and (w["line"]["axis"] in ("X1", f"X{nx+1}"))), None)
    b["genericElements"] = ([{"id": "ge:canopy", "name": "庇", "attachTo": ent["id"],
                              "note": "主出入口上部"}] if ent else [])
    # L4：構造推論
    plate1 = set()
    for r in footprints["L1"]:
        for i in range(int(r["xFrom"][1:]) - 1, int(r["xTo"][1:]) - 1):
            for j in range(int(r["yFrom"][1:]) - 1, int(r["yTo"][1:]) - 1):
                plate1.add((i, j))
    attach_structure(b, system="S", plate=plate1, levels_all=levels_all,
                     fh_list=[l["floorHeight"] for l in b["levels"]],
                     core_cells_list=[{(cs, 2)} for cs in core_spans] +
                                     [{(cs, 0)} for cs in south_core_spans],
                     free_zones=[{"name": "吹抜け（アトリウム）", "levels": levels_all,
                                  "cells": {(i, 1) for i in range(void_spans[0], void_spans[1] + 2)},
                                  "treatment": "大梁"}] if floors > 1 else [],
                     use="商業")
    return b


# ---------- ゲーム物件（現場監督ゲーム本編用：S造3階・延床約60,000㎡） ----------
# BUILDING_SETTING の物件設定を生成器の部品で1棟に確定させる。
# 平面は直交多角形の雁行＋3Fセットバック（斜めカットはスキーマ未対応のため直交近似）。
# グリッド：X 9.8m×22スパン（215.6m）／Y 10m×10行（100m）。1セル=98㎡。
# 行構成（南→北）：店舗／モール／島店舗（コア入り）／中央モール＋吹抜け／島店舗／モール／北店舗・荷捌き。
# コアは南島4・北島4（階段・客用EV・PS・DS、北島の両端コアに荷物用EV）、
# 中央にエスカレーター2基と吹抜けアトリウム（2・3F）。

def gen_game_mall():
    nx, ny = 22, 10
    spans_x = [9800] * nx
    spans_y = [10000] * ny
    fh = [5800] * 3
    floors = 3
    def intervals(li):
        iv = [(0, 20), (0, 20), (0, 21), (0, 21), (1, 21),
              (1, 21), (1, 22), (1, 22), (2, 22), (2, 22)]
        if li == 2:  # 3Fは北東と南東をセットバック
            iv[0] = (0, 19); iv[8] = (2, 21); iv[9] = (2, 20)
        return iv
    b, full = base_parts("bldg:game-mall", "パークサイドモール（ゲーム物件）", "商業", "S",
                         spans_x, spans_y, fh, sprinkler=True)
    X = {a["name"]: a["offset"] for a in b["grid"]["axesX"]}
    Y = {a["name"]: a["offset"] for a in b["grid"]["axesY"]}
    levels_all = [f"L{i+1}" for i in range(floors)]
    south_cores = [2, 7, 12, 17]
    north_cores = [3, 8, 13, 18]
    ATR = (9, 13, 4, 6)  # 吹抜け：Xセル9..12／Y行4..5

    cores, shafts, compartments = [], [], []
    def add_core(cid, c, j0, freight=False, stair_d=9000):
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{c+1}", "xTo": f"X{c+2}",
                               "yFrom": f"Y{j0+1}", "yTo": f"Y{j0+3}"}})
        x0, y0 = X[f"X{c+1}"], Y[f"Y{j0+1}"]
        defs = [("stair", "階段", x0 + 200, y0 + 200, 3400, stair_d,
                 {"riser": 200, "steps": 29, "going": 260}),
                ("ev", "EV", x0 + 3800, y0 + 200, 2300, 2300, None),
                ("ps", "PS", x0 + 6300, y0 + 200, 1200, 3000, None),
                ("ds", "DS", x0 + 7700, y0 + 200, 1000, 3000, None)]
        if freight:
            defs.append(("fev", "EV", x0 + 3800, y0 + 10200, 2600, 2600, {"freight": True}))
        for suf, kind, fx, fy, w, d, extra in defs:
            s = {"id": f"shaft:{cid.split(':')[1]}-{suf}", "coreId": cid, "kind": kind,
                 "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
            if suf == "stair":
                s["stair"] = extra
            elif suf == "fev":
                s["freight"] = True
            shafts.append(s)
            compartments.append({"id": f"fc:shaft-{cid.split(':')[1]}-{suf}", "kind": "竪穴区画",
                                 "shafts": [s["id"]]})
    for ci, c in enumerate(south_cores):
        add_core(f"core:G{ci}", c, 2)
    for ci, c in enumerate(north_cores):
        # 北島コアは階段室を2行分の奥行に渡らせ、北列店舗からの歩行距離を確保する
        add_core(f"core:H{ci}", c, 6, freight=ci in (0, len(north_cores) - 1), stair_d=19000)
    # サービスコア（北列・荷捌き隣接）：荷物用EV＋PS。荷捌きと貨物EVの隣接（V-L3-1）を担う
    cores.append({"id": "core:SV", "levelRange": levels_all,
                  "rect": {"xFrom": "X5", "xTo": "X6", "yFrom": "Y10", "yTo": "Y11"}})
    _svx, _svy = X["X5"], Y["Y10"]
    for suf, kind, fx, fy, w, d, fr in (
            ("fev", "EV", _svx + 400, _svy + 400, 2600, 2600, True),
            ("ps", "PS", _svx + 3400, _svy + 400, 1200, 3000, False)):
        s = {"id": f"shaft:SV-{suf}", "coreId": "core:SV", "kind": kind,
             "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
        if fr:
            s["freight"] = True
        shafts.append(s)
        compartments.append({"id": f"fc:shaft-SV-{suf}", "kind": "竪穴区画", "shafts": [s["id"]]})
    # アトリウムコア（吹抜け＋エスカレーター）
    ax0, ax1, ay0, ay1 = ATR
    cores.append({"id": "core:AT", "levelRange": levels_all[1:],
                  "rect": {"xFrom": f"X{ax0+1}", "xTo": f"X{ax1+1}",
                           "yFrom": f"Y{ay0+1}", "yTo": f"Y{ay1+1}"}})
    cores.append({"id": "core:ESC", "levelRange": levels_all,
                  "rect": {"xFrom": f"X{ax0+1}", "xTo": f"X{ax1+1}",
                           "yFrom": f"Y{ay0+1}", "yTo": f"Y{ay1+1}"}})
    vx, vy = X[f"X{ax0+1}"], Y[f"Y{ay0+1}"]
    shafts.append({"id": "shaft:AT-void", "coreId": "core:AT", "kind": "吹抜け",
                   "levelRange": levels_all[1:],
                   "footprint": {"x": vx + 200, "y": vy + 200,
                                 "w": (ax1 - ax0) * 9800 - 400, "d": (ay1 - ay0) * 10000 - 400}})
    compartments.append({"id": "fc:shaft-AT", "kind": "竪穴区画", "shafts": ["shaft:AT-void"]})
    for k in range(2):
        sid = f"shaft:ESC-{k+1}"
        shafts.append({"id": sid, "coreId": "core:ESC", "kind": "エスカレーター",
                       "levelRange": levels_all,
                       "footprint": {"x": vx + 600, "y": vy + 1200 + k * 3000, "w": 7000, "d": 1500}})
        compartments.append({"id": f"fc:shaft-ESC-{k+1}", "kind": "竪穴区画", "shafts": [sid]})

    rooms, walls, zones = [], [], []
    footprints = {}
    for li in range(floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        iv = intervals(li)
        footprints[lid] = [{"xFrom": f"X{a+1}", "xTo": f"X{c+1}",
                            "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"}
                           for j, (a, c) in enumerate(iv)]
        b["levels"][li]["footprint"] = footprints[lid]
        fl = []
        def R(suf, name, use, xi0, xi1, yi0, yi1, zone=True, ceil=3600):
            zid = None
            if zone:
                mid = (xi0 + xi1) / 2
                zid = f"{ln}-W" if mid <= 7 else f"{ln}-C" if mid <= 14 else f"{ln}-E"
            r = room(f"room:{ln}-{suf}", lid, name, use, xi0, xi1, yi0, yi1, zid, ceil)
            fl.append(r); rooms.append(r)
            return r
        def mall_row(sufpre, j):
            a, bb = iv[j]
            x = a
            while x < bb:
                w = min(3, bb - x)
                R(f"{sufpre}-{x}", "モール", "モール", x, x + w, j, j + 1, zone=False, ceil=4800)
                x += w
        def island(sufpre, j0, core_cols, top_use, top_name):
            a = max(iv[j0][0], iv[j0 + 1][0]); bb = min(iv[j0][1], iv[j0 + 1][1])
            x = a
            while x < bb:
                if x in core_cols:
                    R(f"CORE{x}", "コアホール", "コアホール", x, x + 1, j0, j0 + 2)
                    x += 1
                    continue
                w = 1 if (x + 1) in core_cols else min(2, bb - x)
                use, name = top_use, f"{top_name}{x+1}"
                if li == 1 and sufpre == "SI" and 9 <= x <= 11:
                    use, name = "大型店", f"大型専門店{x+1}"
                R(f"{sufpre}{x+1}", name, use, x, x + w, j0, j0 + 2)
                x += w
        # 南列（j0）
        a, bb = iv[0]
        if li == 0:
            R("SM", "食品スーパー", "テナント", a, a + 3, 0, 1)
            x = a + 3
            while x < bb:
                w = min(2, bb - x); R(f"S{x+1}", f"テナントS{x+1}", "テナント", x, x + w, 0, 1); x += w
        elif li == 2:
            half = (a + bb) // 2
            x = a
            while x < half:
                w = min(2, half - x); R(f"S{x+1}", f"レストランS{x+1}", "飲食", x, x + w, 0, 1); x += w
            R("FC", "フードコート", "飲食", half, half + 3, 0, 1, ceil=4200)
            x = half + 3
            while x < bb:
                w = min(2, bb - x); R(f"S{x+1}", f"レストランS{x+1}", "飲食", x, x + w, 0, 1); x += w
        else:
            x = a
            while x < bb:
                w = min(2, bb - x); R(f"S{x+1}", f"テナントS{x+1}", "テナント", x, x + w, 0, 1); x += w
        mall_row("M1", 1)
        island("SI", 2, south_cores, "飲食" if li == 2 else "テナント",
               "レストランSI" if li == 2 else "テナントSI")
        # 中央モール＋吹抜け（j4-5）
        ca = max(iv[4][0], iv[5][0]); cb = min(iv[4][1], iv[5][1])
        if ca < ax0:
            R("MALLW", "モール（西）", "モール", ca, ax0, 4, 6, zone=False, ceil=4800)
        if li == 0:
            R("ATR", "モール（アトリウム）", "モール", ax0, ax1, 4, 6, zone=False, ceil=4800)
        else:
            R("VOID", "吹抜け", "吹抜け", ax0, ax1, 4, 6, zone=False, ceil=4800)
        if ax1 < cb:
            R("MALLE", "モール（東）", "モール", ax1, cb, 4, 6, zone=False, ceil=4800)
        island("NI", 6, north_cores, "テナント", "テナントNI")
        mall_row("M8", 8)
        # 北列（j9）：荷捌き→サービスコア（荷物用EV）→（1Fのみ防災）→WC→店舗
        a, bb = iv[9]
        R("BY", "バックヤード・荷捌き", "バックヤード", a, a + 2, 9, 10)
        R("SVCORE", "コアホール", "コアホール", a + 2, a + 3, 9, 10)
        x = a + 3
        if li == 0:
            R("BOUSAI", "防災センター", "防災センター", x, x + 1, 9, 10)
            x += 1
        while x < bb:
            if x in (9, 14):
                R(f"WC{x+1}", "便所・サービス", "WC", x, x + 1, 9, 10, ceil=3000)
                x += 1
                continue
            w = 1 if (x + 1) in (9, 14) else min(2, bb - x)
            if li == 2:
                R(f"N{x+1}", f"レストランN{x+1}", "飲食", x, x + w, 9, 10)
            else:
                R(f"N{x+1}", f"テナントN{x+1}", "テナント", x, x + w, 9, 10)
            x += w
        # 工区（X方向3帯×行区間）
        for suf, b0, b1 in (("W", 0, 7), ("C", 7, 14), ("E", 14, nx)):
            ranges = []
            for j, (ja, jc) in enumerate(iv):
                lo, hi = max(ja, b0), min(jc, b1)
                if lo < hi:
                    ranges.append({"xFrom": f"X{lo+1}", "xTo": f"X{hi+1}",
                                   "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
            if ranges:
                zones.append({"id": f"{ln}-{suf}", "level": lid, "cellRanges": ranges})
        # 面積区画：中心X順に貪欲分割（SP全面・各区画 ≦2950㎡）
        def _cx(r):
            return (int(r["cells"]["xFrom"][1:]) + int(r["cells"]["xTo"][1:])) / 2
        def _area(r):
            c = r["cells"]
            return (X[c["xTo"]] - X[c["xFrom"]]) * (Y[c["yTo"]] - Y[c["yFrom"]]) / 1e6
        groups, cur, carea = [], [], 0.0
        for r in sorted(fl, key=lambda r: (_cx(r), r["id"])):
            ar = _area(r)
            if cur and carea + ar > 2950:
                groups.append(cur); cur, carea = [], 0.0
            cur.append(r["id"]); carea += ar
        if cur:
            groups.append(cur)
        for gi, g in enumerate(groups):
            compartments.append({"id": f"fc:{ln}-{gi+1}", "kind": "面積区画", "level": lid, "rooms": g})
        walls += build_walls(fl, lid, nx, ny, commercial_decide, f"GM-{ln}")
    b.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
              "zones": zones, "compartments": compartments})
    slabs = []
    for li in range(floors):
        lid = f"L{li+1}"
        ops = [s["id"] for s in shafts if lid in s["levelRange"]] if li > 0 else []
        slabs.append({"id": f"slab:{lid}", "level": lid,
                      "kind": "土間コンクリート" if li == 0 else "デッキ合成スラブ",
                      "thickness": 150, "openings": ops, "cellRanges": footprints[lid],
                      **({"onGround": True} if li == 0 else {})})
    b["slabs"] = slabs
    b["roof"] = {"id": "roof:main", "topLevel": f"L{floors}", "kind": "陸屋根（シート防水）",
                 "cellRanges": footprints[f"L{floors}"], "parapetHeight": 600}
    b["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cellRanges": footprints["L1"],
                        "depth": 1500}]
    plate_cells = sum((c - a) for li in range(floors) for (a, c) in intervals(li))
    b["building"]["grossAreaTarget"] = plate_cells * 98
    b["site"] = {"polygon": [[-15000, -12000], [232000, -12000], [232000, 112000], [-15000, 112000]],
                 "buildingPlacement": {"origin": [0, 0], "rotationDeg": 0},
                 "roads": [{"edge": "south", "name": "幹線道路", "width": 12000}],
                 "gates": [{"edge": "south", "name": "南ゲート", "atMm": 100000, "width": 8000},
                           {"edge": "west", "name": "西ゲート", "atMm": 30000, "width": 7000}],
                 "neighbors": [{"edge": "north", "type": "住宅"}, {"edge": "south", "type": "道路"}]}
    core_room = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "コアホール"), None)
    mall_room = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "モール"), None)
    wc_room = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "WC"), None)
    ps_id = next((s["id"] for s in shafts if s["kind"] == "PS"), None)
    if core_room and mall_room and wc_room and ps_id:
        b["equipmentRuns"] = [{"id": "run:water-1F", "kind": "給水", "level": "L1",
                               "fromShaft": ps_id, "route": [core_room, mall_room, wc_room]}]
    if mall_room:
        b["coverings"] = [{"id": "cov:mall-floor", "target": mall_room, "part": "床", "name": "磁器質タイル"}]
    b["reinforcement"] = [{"id": "re:slab", "target": "slab:L2", "kind": "スラブ配筋", "spec": "D13@200 ダブル"},
                          {"id": "re:footing", "target": "foundation:each-column", "kind": "基礎配筋",
                           "spec": "主筋D19・あばら筋D13@150"}]
    ent = next((w for w in walls if w["level"] == "L1"
                and any(o["kind"] == "両開き戸" for o in w["openings"])
                and (w["line"]["axis"] in ("X1", f"X{nx+1}"))), None)
    b["genericElements"] = ([{"id": "ge:canopy", "name": "庇", "attachTo": ent["id"],
                              "note": "主出入口上部"}] if ent else [])
    plate1 = {(i, j) for j, (a, c) in enumerate(intervals(0)) for i in range(a, c)}
    attach_structure(b, system="S", plate=plate1, levels_all=levels_all,
                     fh_list=fh,
                     core_cells_list=[{(c, 2), (c, 3)} for c in south_cores] +
                                     [{(c, 6), (c, 7)} for c in north_cores],
                     free_zones=[{"name": "吹抜け（アトリウム）", "levels": levels_all[1:],
                                  "cells": {(i, j) for i in range(ax0, ax1) for j in range(4, 6)},
                                  "treatment": "大梁"}],
                     use="商業")
    # ゲーム統合用の対応付け（検証器は未知キーを無視する）
    b["gameIntegration"] = {
        "note": "本編（立て直しの14日間）との対応付け。第2段階の統合で確定。",
        "zoneMap": {f"{f}F-{s}": f"F{f}{s}" for f in (1, 2, 3) for s in ("W", "C", "E")},
        "commonAreas": ["モール（各階）", "吹抜けアトリウム（core:AT）", "コアホール"],
        "evPassengerShafts": [s["id"] for s in shafts if s["kind"] == "EV" and not s.get("freight")],
        "evFreightShafts": [s["id"] for s in shafts if s.get("freight")],
        "escalatorShafts": [s["id"] for s in shafts if s["kind"] == "エスカレーター"],
        "mainCoreForGameEV": "core:G2",
        "loadingRoom1F": next((r["id"] for r in rooms if "荷捌き" in r["name"]), None),
    }
    return b


# ---------- マンション ----------
# USE_RULES §2：形式が住戸モジュールを決める（片廊下型＝間口6m）、PSは住戸ごと全階同一位置、
# 界壁は開口ゼロ、EVは ceil(戸数/50)、歩行距離50mをコア配置で担保。

def gen_mansion(units_n=9, unit_w=6000, floors=8):
    spans_x = [unit_w] * units_n
    spans_y = [9500, 1500]                    # 住戸列／共用廊下（片廊下型）
    fh = [3150] * floors                      # 蹴上175×18段＝3150
    b, full = base_parts("bldg:gen-mansion", "生成：マンション（片廊下型）", "マンション", "RC",
                         spans_x, spans_y, fh)
    core_idx = [0, units_n // 2, units_n - 1]
    unit_idx = [i for i in range(units_n) if i not in core_idx]
    levels_all = [f"L{i+1}" for i in range(floors)]
    rooms, walls, zones, compartments = [], [], [], []
    shafts, cores = [], []

    # コア（階段室）：両端＋中央。EVは中央コアに1基（45戸 ÷ 50）
    for ci, cs in enumerate(core_idx):
        cid = f"core:M{ci}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{cs+1}", "xTo": f"X{cs+2}", "yFrom": "Y1", "yTo": "Y2"}})
        x0 = cs * unit_w
        shafts.append({"id": f"shaft:{cid.split(':')[1]}-stair", "coreId": cid, "kind": "階段",
                       "levelRange": levels_all,
                       "footprint": {"x": x0 + 200, "y": 200, "w": 2600, "d": 5000},
                       "stair": {"riser": 175, "steps": 18, "going": 240}})
        compartments.append({"id": f"fc:shaft-{cid.split(':')[1]}", "kind": "竪穴区画",
                             "shafts": [f"shaft:{cid.split(':')[1]}-stair"]})
        if ci == 1:
            shafts.append({"id": "shaft:M1-ev", "coreId": cid, "kind": "EV", "levelRange": levels_all,
                           "footprint": {"x": x0 + 3000, "y": 200, "w": 2300, "d": 2300}})
            compartments.append({"id": "fc:shaft-M1-ev", "kind": "竪穴区画", "shafts": ["shaft:M1-ev"]})
    # 住戸PS：住戸ごとに水回り脇1箇所、全階同一位置（縦連続）
    ps_ids = []
    for i in unit_idx:
        cid = f"core:U{i+1}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{i+1}", "xTo": f"X{i+2}", "yFrom": "Y1", "yTo": "Y2"}})
        sid = f"shaft:PS-U{i+1}"
        shafts.append({"id": sid, "coreId": cid, "kind": "PS", "levelRange": levels_all,
                       "footprint": {"x": (i + 1) * unit_w - 1100, "y": 7600, "w": 900, "d": 1700}})
        ps_ids.append(sid)
    compartments.append({"id": "fc:shaft-PS", "kind": "竪穴区画", "shafts": ps_ids})

    specials_1f = {1: ("ENT", "エントランス", "エントランス"), 2: ("MGR", "管理室", "管理室"),
                   units_n - 2: ("MEET", "集会室", "集会室")}
    # 試験準拠の共用・管理・設備セット（令和3年 設計製図試験「集合住宅」の要求室表が雛形。
    # INTERIOR_MODEL_V2 §11／USE_RULES §2.9）：空いている1F住戸列に割当てる（列が足りなければ後ろから省略）
    _svc = [("GOMI", "ゴミ保管庫", "ゴミ保管庫"), ("ELEC", "電気室", "電気室"),
            ("TANK", "受水槽室", "受水槽室"), ("PUMP", "消火ポンプ室", "消火ポンプ室")]
    _free = [i for i in range(units_n) if i not in core_idx and i not in specials_1f]
    for (suf, nm, use), i in zip(_svc, _free):
        specials_1f[i] = (suf, nm, use)
    unit_no = {}
    for li in range(floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        fl = []
        def R(suf, name, use, xi0, xi1, zone=True, ceil=2700):
            r = room(f"room:{ln}-{suf}", lid, name, use, xi0, xi1, 0, 1,
                     (f"{ln}-W" if xi0 < units_n // 3 else f"{ln}-C" if xi0 < 2 * units_n // 3 else f"{ln}-E")
                     if zone else None, ceil)
            fl.append(r); rooms.append(r)
            return r
        seq = 0
        for i in range(units_n):
            if i in core_idx:
                R(f"CORE{i+1}", "階段室・EVホール", "コア", i, i + 1)
            elif li == 0 and i in specials_1f:
                suf, name, use = specials_1f[i]
                R(suf, name, use, i, i + 1, ceil=3000)
            else:
                seq += 1
                unit_no[(li, i)] = (li + 1) * 100 + seq
                R(f"U{i+1}", f"{unit_no[(li, i)]}号室", "住戸", i, i + 1)
        corr = room(f"room:{ln}-CORR", lid, "共用廊下", "共用廊下", 0, units_n, 1, 2, None, 2400)
        fl.append(corr); rooms.append(corr)
        t1, t2 = units_n // 3, 2 * units_n // 3
        for suf, a, bb in (("W", 0, t1), ("C", t1, t2), ("E", t2, units_n)):
            zones.append({"id": f"{ln}-{suf}", "level": lid,
                          "cellRange": {"xFrom": f"X{a+1}", "xTo": f"X{bb+1}",
                                        "yFrom": "Y1", "yTo": "Y3"}})
        compartments.append({"id": f"fc:{ln}", "kind": "面積区画", "level": lid,
                             "rooms": [r["id"] for r in fl]})
        def decide(useA, useB, horiz, axis):
            pair = {useA, useB}
            if useA is None or useB is None:
                inner = useB if useA is None else useA
                if inner == "住戸":
                    return ("外壁", ("サッシ", 3600), False)
                if inner == "エントランス":
                    return ("外壁", ("両開き戸", 1800), False)
                if inner == "コア":
                    return ("外壁", ("片開き戸", 1000), False)
                return ("外壁", None, False)
            if pair == {"住戸", "住戸"} or pair == {"住戸", "コア"}:
                return ("戸境", None, False)
            if pair == {"住戸", "共用廊下"}:
                return ("間仕切", ("片開き戸", 900), False)
            if pair == {"コア", "共用廊下"}:
                return ("間仕切", ("片開き戸", 1000), False)
            if pair == {"エントランス", "共用廊下"}:
                return ("間仕切", ("両開き戸", 1600), False)
            if "共用廊下" in pair and pair & {"管理室", "集会室", "ゴミ保管庫", "電気室", "受水槽室", "消火ポンプ室"}:
                return ("間仕切", ("片開き戸", 1000), False)
            if pair == {"管理室", "エントランス"}:
                return ("間仕切", ("片開き戸", 900), False)
            return ("間仕切", None, False)
        walls += build_walls(fl, lid, units_n, 2, decide, f"M-{ln}")
    b.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
              "zones": zones, "compartments": compartments})
    slabs = []
    for li in range(floors):
        lid = f"L{li+1}"
        ops = [s["id"] for s in shafts if lid in s["levelRange"]] if li > 0 else []
        slabs.append({"id": f"slab:{lid}", "level": lid,
                      "kind": "土間コンクリート" if li == 0 else "RCスラブ",
                      "cells": full, "thickness": 200, "openings": ops,
                      **({"onGround": True} if li == 0 else {})})
    b["slabs"] = slabs
    b["site"] = {"polygon": [[-10000, -10000], [70000, -10000], [70000, 30000], [-10000, 30000]],
                 "buildingPlacement": {"origin": [0, 0], "rotationDeg": 0},
                 "roads": [{"edge": "south", "name": "前面道路", "width": 6000}],
                 "gates": [{"edge": "south", "name": "敷地出入口", "atMm": 24000, "width": 4000}],
                 "neighbors": [{"edge": "north", "type": "住宅"}, {"edge": "south", "type": "道路"}]}
    b["reinforcement"] = [{"id": "re:slab", "target": "slab:L2", "kind": "スラブ配筋", "spec": "D13@200 ダブル"},
                          {"id": "re:footing", "target": "foundation:each-column", "kind": "基礎配筋",
                           "spec": "主筋D22・あばら筋D13@150"}]
    b["genericElements"] = [
        {"id": f"ge:balcony-{ln}-{i+1}", "name": "バルコニー",
         "attachTo": f"room:{ln}-U{i+1}", "note": "奥行1800・手すり1100・隔板あり"}
        for (li, i) in unit_no for ln in [f"{li+1}F"]]
    # L4：構造推論（8階→RCラーメン）
    attach_structure(b, system="RC", plate={(i, j) for i in range(units_n) for j in range(2)},
                     levels_all=levels_all, fh_list=fh,
                     core_cells_list=[{(cs, 0)} for cs in core_idx],
                     use="マンション")
    fix_daylight(b)
    return b


# ---------- シード生成（実在建物の外形から） ----------
# footprint_to_plate.py の変換結果（grid＋footprint＋source_properties）を読み、
# 任意プレートの内側に商業レイアウトを割り付ける。
# バンド方式：中央モール帯を置き、外側へ テナント→モール→テナント と繰り返す。
# 北側の最外帯はサービス（バックヤード）に寄せる。コアは北テナント帯に等間隔。

def _decompose(cells, max_w):
    """セル集合を貪欲に矩形分解する（max_w は列数の上限）。"""
    rest = set(cells)
    rects = []
    while rest:
        i0, j0 = min(rest, key=lambda c: (c[1], c[0]))
        w = 0
        while w < max_w and (i0 + w, j0) in rest:
            w += 1
        h = 1
        while all((i0 + dx, j0 + h) in rest for dx in range(w)):
            h += 1
        rect = (i0, j0, w, h)
        rects.append(rect)
        for dx in range(w):
            for dy in range(h):
                rest.discard((i0 + dx, j0 + dy))
    # 縦方向に隣接し x 区間が一致する矩形をマージ（帯の分割を減らす）
    merged = True
    while merged:
        merged = False
        for a in range(len(rects)):
            for bidx in range(len(rects)):
                if a == bidx:
                    continue
                x1, y1, w1, h1 = rects[a]
                x2, y2, w2, h2 = rects[bidx]
                if x1 == x2 and w1 == w2 and y1 + h1 == y2:
                    rects[a] = (x1, y1, w1, h1 + h2)
                    rects.pop(bidx)
                    merged = True
                    break
            if merged:
                break
    return rects

def _decompose_banded(cells, max_w, max_h):
    """セル集合を行バンド（高さ max_h 以下）に分けてから矩形分解する。
    階段状の領域でも縦長ストリップになりにくく、モール平行の横長な室が得られる。"""
    rows = sorted({j for (i, j) in cells})
    rects = []
    for k in range(0, len(rows), max_h):
        band = {(i, j) for (i, j) in cells if j in rows[k:k + max_h]}
        rects += _decompose(band, max_w)
    return rects


def split_area_grid(a0, b0, w_, h_, X, Y, limit=2800):
    """面積上限で割る際に、長辺を割り続けるのではなく縦横に格子状に割る（≒正方形のピース）。"""
    wm_ = X[f"X{a0+w_+1}"] - X[f"X{a0+1}"]
    dm_ = Y[f"Y{b0+h_+1}"] - Y[f"Y{b0+1}"]
    area = wm_ * dm_ / 1e6
    if area <= limit or (w_ == 1 and h_ == 1):
        return [(a0, b0, w_, h_)]
    n = area / limit
    nx = max(1, min(w_, round((n * wm_ / dm_) ** 0.5)))
    ny = max(1, min(h_, -(-int(n) // nx)))
    while nx * ny < n and ny < h_:
        ny += 1
    while nx * ny < n and nx < w_:
        nx += 1
    out = []
    xs = [a0 + (w_ * k) // nx for k in range(nx + 1)]
    ys = [b0 + (h_ * k) // ny for k in range(ny + 1)]
    for ix in range(nx):
        for iy in range(ny):
            out.append((xs[ix], ys[iy], xs[ix + 1] - xs[ix], ys[iy + 1] - ys[iy]))
    return out


# ---------- L4：構造推論（INTERIOR_MODEL_V2 §7） ----------
def attach_structure(b, *, system, plate, levels_all, fh_list, core_cells_list=(),
                     free_zones=(), ground_prior="unknown", use="商業",
                     system_basis=None, ground_override=None, frame_method=None):
    """構造計画の原則から躯体を推論し、建物モデルに structure ブロックと
    grid.columnExceptions を書き込む。すべて推論であり根拠（basis）を併記する。
    free_zones: [{name, levels:[lid...], cells:set, treatment}]"""
    from collections import Counter
    X = {a["name"]: a["offset"] for a in b["grid"]["axesX"]}
    Y = {a["name"]: a["offset"] for a in b["grid"]["axesY"]}
    spans_x = [b_ - a_ for a_, b_ in zip([a["offset"] for a in b["grid"]["axesX"]],
                                        [a["offset"] for a in b["grid"]["axesX"]][1:])]
    spans_y = [b_ - a_ for a_, b_ in zip([a["offset"] for a in b["grid"]["axesY"]],
                                        [a["offset"] for a in b["grid"]["axesY"]][1:])]
    span_max = max(spans_x + spans_y)
    # 構造軸（SPAN_STANDARD の分離がある場合、大梁せいと柱例外は構造軸基準で決める）
    Xn_ = [a["name"] for a in b["grid"]["axesX"]]
    Yn_ = [a["name"] for a in b["grid"]["axesY"]]
    sax = b["grid"].get("structuralAxesX") or Xn_
    say = b["grid"].get("structuralAxesY") or Yn_
    _sox = [X[n] for n in sax]
    _soy = [Y[n] for n in say]
    struct_span_max = max([c - a for a, c in zip(_sox, _sox[1:])] +
                          [c - a for a, c in zip(_soy, _soy[1:])], default=span_max)
    struct_points = None
    if sax != Xn_ or say != Yn_:
        struct_points = {(Xn_.index(xn), Yn_.index(yn)) for xn in sax for yn in say}
    total_h = sum(fh_list)
    floors = len(levels_all)
    basis_sys = system_basis or {"S": "用途×階数×スパン：低層・大スパンの商業はS造が典型【実務】",
                 "RC": "用途×階数：中層の共同住宅・事務所はRCラーメンが標準【指針】",
                 "壁式RC": "5階以下・軒高20m以下は壁式RCの適用範囲【基準】",
                 "SRC": "階数・高さ帯の標準としてSRC【指針】"}.get(system, "推論")
    # モジュールの根拠
    sx = spans_x[0] if spans_x else 0
    if use == "商業":
        if struct_points is not None:
            mod_basis = f"構造軸は SPAN_STANDARD の9mモジュール（実務レンジ8〜10m）で、部屋割り用補助軸（{sx}mmグリッド）から約9mピッチに最も近い軸を選定【実務】。柱・大梁は構造軸のみに配置し、補助軸には置かない"
        elif abs(sx - 7000) <= 600:
            mod_basis = "駐車モジュール：車室2.3m幅×3台≒7m（旧来モジュール）と整合【実務】"
        elif abs(sx - 9000) <= 600:
            mod_basis = "駐車モジュール：車室2.5m幅×3台＋α≒9m と整合【実務】"
        else:
            mod_basis = f"駐車モジュールとの整合は弱い（スパン{sx}mm）。外形フィット由来のグリッド"
    elif use == "駅舎":
        mod_basis = "軌道・ホームモジュール（USE_RULES §3）に柱通りを一致"
    else:
        mod_basis = "住戸モジュール（間口×奥行）に柱通りを一致【実務】"
    col_size = 400 if system == "S" else 800 if system == "SRC" else 200 if system == "壁式RC" else 750
    if system == "S":
        girder = round(struct_span_max / 17.5 / 50) * 50
        depth_basis = f"S大梁せい＝構造軸最大スパン{struct_span_max}mm の 1/15〜1/20【実務】→ {girder}mm"
    elif system == "壁式RC":
        girder = 0
        depth_basis = "壁式：梁ではなく耐力壁で構成"
    else:
        girder = round(struct_span_max / 11 / 50) * 50
        depth_basis = f"RC大梁せい＝構造軸最大スパン{struct_span_max}mm の 1/10〜1/12【実務】→ {girder}mm"
    # 耐震要素
    seismic = []
    rowcount = Counter(j for (i, j) in plate)
    if plate:
        maxc = max(rowcount.values())
        slab_rows = [j for j in range(max(Y) and (max(j for (i, j) in plate) + 1))
                     if rowcount.get(j, 0) >= 0.6 * maxc]
        rowmax = {j: max(a for (a, bb) in plate if bb == j) for j in slab_rows}
        rowmin = {j: min(a for (a, bb) in plate if bb == j) for j in slab_rows}
        from collections import Counter as C2
        east_col = C2(rowmax.values()).most_common(1)[0][0]
        west_col = C2(rowmin.values()).most_common(1)[0][0]
        kind = "ブレース" if system == "S" else "耐震壁"
        sid = 0
        _seis_seen = set()
        def add_seismic(cell, direction):
            nonlocal sid
            if (cell, direction) in _seis_seen:
                return
            _seis_seen.add((cell, direction))
            sid += 1
            i, j = cell
            seismic.append({"id": f"seis:{sid}", "kind": kind, "direction": direction,
                            "levelRange": list(levels_all),
                            "cell": {"xFrom": f"X{i+1}", "xTo": f"X{i+2}",
                                     "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"},
                            "basis": "重心≒剛心：外周にバランス配置し下階まで連続【指針】"})
        if slab_rows:
            for row, direction in ((max(slab_rows), "X"), (min(slab_rows), "X")):
                xs = sorted(a for (a, bb) in plate if bb == row)
                for fr in (0.06, 0.27, 0.48, 0.69, 0.9):
                    add_seismic((xs[min(len(xs) - 2, int(fr * len(xs)))], row), direction)
            for col in (west_col, east_col):
                ys = sorted(bb for (a, bb) in plate if a == col and bb in slab_rows)
                for fr in (0.2, 0.65):
                    add_seismic((col, ys[min(len(ys) - 2, int(fr * len(ys)))]), "Y")
        for cells_ in core_cells_list:
            ci = sorted(cells_)
            if ci:
                add_seismic(ci[0], "X")
                add_seismic(ci[-1], "Y")
    # 無柱区画 → 柱例外
    exceptions = {}
    zones_out = []
    for zi, z in enumerate(free_zones):
        cells_ = {(i, j) for (i, j) in z["cells"] if (i, j) in plate}
        if not cells_:
            continue
        zid = f"cfz:{zi+1}"
        zones_out.append({"id": zid, "name": z["name"], "levels": list(z["levels"]),
                          "cellRanges": _ranges_of_cells(cells_),
                          "treatment": z.get("treatment", "大梁"),
                          "basis": z.get("basis", "大空間は内部の柱を抜き、梁で受ける【実務】")})
        cand = set()
        for (i, j) in cells_:
            for p in ((i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)):
                cand.add(p)
        for (pi, pj) in cand:
            if struct_points is not None and (pi, pj) not in struct_points:
                continue  # 柱例外は構造軸の交点にだけ付ける（補助軸には柱が無い）
            adj = [(pi - 1, pj - 1), (pi, pj - 1), (pi - 1, pj), (pi, pj)]
            if len([c for c in adj if c in cells_]) >= 3:
                for lid in z["levels"]:
                    exceptions.setdefault((pi, pj), {}).setdefault(lid, z["name"])
    exc_list = []
    for (pi, pj), by_level in sorted(exceptions.items()):
        lvs = sorted(by_level)
        exc_list.append({"at": f"X{pi+1}-Y{pj+1}", "levels": lvs,
                         "reason": "／".join(sorted(set(by_level.values())))})
    b["grid"]["columnExceptions"] = exc_list
    # 基礎の仮定（地盤は公開情報で確定不可：地域priorからの仮定として保持）
    ground = {
        "coastal-lowland": {"foundation": "杭基礎", "bearingLayer": "深い（推定）", "liquefactionRisk": "高",
                            "basis": ["地形prior：海岸低地・埋立系は支持層が深く液状化リスクが高い【実務】",
                                      "地耐力20kN/㎡以下は杭基礎（告示1347号の考え方）【基準】"]},
        "riverine-lowland": {"foundation": "杭基礎", "bearingLayer": "深い（推定）", "liquefactionRisk": "中〜高",
                             "basis": ["地形prior：河川低地は支持層が深い傾向【実務】",
                                       "地耐力20kN/㎡以下は杭基礎（告示1347号の考え方）【基準】"]},
        "upland": {"foundation": "直接基礎（独立・べた）", "bearingLayer": "浅い（推定）", "liquefactionRisk": "低",
                   "basis": ["地形prior：台地・丘陵は支持層が浅い【実務】"]},
    }.get(ground_prior, {"foundation": "杭基礎", "bearingLayer": "不明", "liquefactionRisk": "不明",
                         "basis": ["地域情報なし：大規模建物の既定として杭基礎を仮置き（要地盤調査）"]})
    if ground_override:
        ground = {"foundation": ground_override["foundation"], "bearingLayer": "シード指定",
                  "liquefactionRisk": "シード指定", "basis": [ground_override["basis"]]}
    # 施工属性
    if system == "S":
        sets = max(1, -(-total_h // 15000), -(-floors // 3))
        constr = {"frameCycle": f"S造建方：節分割 {sets} 節（1節＝高さ15m以下・3フロア以下【指針】）",
                  "crane": "タワークレーン" if total_h >= 50000 else "ラフタークレーン（高さ50m程度まで）",
                  "note": "柱→梁→ブレースの順に建方。グリッド規則性が建方サイクルの安定に直結"}
    elif system == "壁式RC":
        constr = {"frameCycle": "壁式RC：1フロア2〜4週サイクル（中層の目安）【実務】",
                  "crane": "ラフタークレーン（高さ50m程度まで）",
                  "note": "耐力壁のグリッド＝住戸プラン。型枠転用がサイクルを決める"}
    else:
        constr = {"frameCycle": "RC：1フロア2〜4週サイクル（中層の目安）【実務】。打設工区はポンプ1台150㎥・面積300㎡目安",
                  "crane": "タワークレーン" if total_h >= 50000 else "ラフタークレーン（高さ50m程度まで）",
                  "note": "柱・壁グリッドの規則性＝型枠転用率＝サイクル安定性"}
    # 基礎の明示：杭基礎と仮定した場合は foundations.piles にも規則として残す（null のままにしない）
    if ground.get("foundation") == "杭基礎" and b.get("foundations", {}).get("piles") is None:
        b["foundations"]["piles"] = {"rule": "each-structural-column", "kind": "不明（仮定）",
                                     "basis": "groundAssumption（地域priorからの仮定）に従う。杭種別・径・長さは未特定"}
    b["structure"] = {
        "system": system, "systemBasis": basis_sys,
        "moduleBasis": mod_basis,
        "columnSizeMm": col_size, "girderDepthMm": girder, "girderDepthBasis": depth_basis,
        "structuralSpanMaxMm": struct_span_max,
        "seismicElements": seismic, "columnFreeZones": zones_out,
        "groundAssumption": ground, "constructionDerived": constr,
        "note": "L4構造推論の出力。実構造ではなく、構造計画の原則からの推論（INTERIOR_MODEL_V2 §7）",
    }
    if frame_method:
        b["structure"]["frameMethod"] = frame_method
    return b


def _ranges_of_cells(cells):
    """セル集合を行ごとの範囲リストに変換する。"""
    rows = {}
    for (i, j) in cells:
        rows.setdefault(j, []).append(i)
    out = []
    for j in sorted(rows):
        xs = sorted(rows[j])
        run = start = xs[0]
        for x in xs[1:] + [None]:
            if x is None or x != run + 1:
                out.append({"xFrom": f"X{start+1}", "xTo": f"X{run+2}",
                            "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
                if x is not None:
                    start = x
            run = x if x is not None else run
    return out


def station_decide(useA, useB, horiz, axis):
    pair = {useA, useB}
    if useA is None or useB is None:
        inner = useB if useA is None else useA
        if inner == "コンコース":
            return ("外壁", ("両開き戸", 2400), False)
        if inner in ("待合室", "テナント"):
            return ("外壁", ("サッシ", 5000), False)
        return ("外壁", ("片開き戸", 1000), False)
    if pair == {"コンコース", "コンコース"}:
        return ("間仕切", ("両開き戸", 2400), False)  # 改札口の位置（改札自体は FareGate で表す）
    if pair in ({"コンコース", "待合室"}, {"コンコース", "テナント"}):
        return ("間仕切", ("両開き戸", 1600), False)
    return ("間仕切", ("片開き戸", 900), False)


def gen_station(form="相対式", n_spans=12, span=10000, ekibiru_floors=2):
    """地上駅＋駅ビルの複合ファイルをパラメトリック生成する（手組み例 build_station_example の一般化）。
    駅舎：改札外（南列）／改札内（北列）の2列構成。ホーム・軌道は site 側に置く。"""
    # --- 駅舎 ---
    spans_x = [span] * n_spans
    spans_y = [5500, 5500]
    fh_st = [4200]
    st, full_st = base_parts("bldg:station", "駅舎（地上駅）", "駅舎", "S", spans_x, spans_y, fh_st)
    levels_all = ["L1"]
    def seg(a, b):
        return (a, b)  # スパン index 区間 [a, b)
    layout = [
        # (suffix, name, use, x0, x1, row) row: 0=南（改札外）, 1=北（改札内）
        ("OUT", "改札外コンコース", "コンコース", 0, 5, 0),
        ("WAIT", "待合室", "待合室", 5, 7, 0),
        ("SHOP", "売店", "テナント", 7, 9, 0),
        ("OFFICE", "駅事務室", "駅事務室", 9, 12, 0),
        ("IN", "改札内コンコース", "コンコース", 0, 5, 1),
        ("WC", "便所", "WC", 5, 6, 1),
        ("ELEC", "電気室", "電気室", 6, 7, 1),
        ("SIG", "信号通信室", "信号通信室", 7, 8, 1),
        ("MECH", "機械室", "機械室", 8, 9, 1),
        ("STORE", "倉庫", "倉庫", 9, 10, 1),
        ("BOH", "駅務室・防災", "駅務室", 10, 12, 1),
    ]
    rooms = []
    for suf, name, use, x0, x1, row in layout:
        zid = "ST-W" if x0 < n_spans // 3 else "ST-C" if x0 < 2 * n_spans // 3 else "ST-E"
        rooms.append(room(f"room:ST-{suf}", "L1", name, use, x0, x1, row, row + 1, zid,
                          3600 if use == "コンコース" else 3300))
    walls = build_walls(rooms, "L1", n_spans, 2, station_decide, "ST")
    zones = [{"id": f"ST-{s}", "level": "L1",
              "cellRange": {"xFrom": f"X{a+1}", "xTo": f"X{b+1}", "yFrom": "Y1", "yTo": "Y3"}}
             for s, a, b in (("W", 0, n_spans // 3), ("C", n_spans // 3, 2 * n_spans // 3),
                             ("E", 2 * n_spans // 3, n_spans))]
    cores = [{"id": "core:MECH", "levelRange": levels_all,
              "rect": {"xFrom": f"X{9}", "xTo": f"X{10}", "yFrom": "Y2", "yTo": "Y3"}}]
    shafts = [{"id": "shaft:st-ps", "coreId": "core:MECH", "kind": "PS", "levelRange": levels_all,
               "footprint": {"x": (9 - 1) * span + 100, "y": 5700, "w": 1200, "d": 2400}}]
    compartments = [{"id": "fc:ST-L1", "kind": "面積区画", "level": "L1",
                     "rooms": [r["id"] for r in rooms]},
                    {"id": "fc:ST-shaft", "kind": "竪穴区画", "shafts": ["shaft:st-ps"]}]
    st.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
               "zones": zones, "compartments": compartments})
    st["slabs"] = [{"id": "slab:ST-L1", "level": "L1", "kind": "土間コンクリート",
                    "cells": full_st, "thickness": 150, "onGround": True, "openings": []}]
    st["fareZones"] = [
        {"id": "zone:out", "kind": "改札外", "level": "L1",
         "rooms": [r["id"] for r in rooms if r["cells"]["yFrom"] == "Y1"]},
        {"id": "zone:in", "kind": "改札内", "level": "L1",
         "rooms": [r["id"] for r in rooms if r["cells"]["yFrom"] == "Y2"]},
    ]
    st["fareGates"] = [{"id": "gate:main", "level": "L1", "fromZone": "zone:out", "toZone": "zone:in",
                         "passages": 4, "widePassages": 1}]
    st["coverings"] = [{"id": "cov:st-wait", "target": "room:ST-WAIT", "part": "床", "name": "長尺塩ビシート"}]
    plat_len = n_spans * span
    attach_structure(st, system="S", plate={(i, j) for i in range(n_spans) for j in range(2)},
                     levels_all=levels_all, fh_list=fh_st, use="駅舎")
    # --- 駅ビル ---
    eb, full_eb = base_parts("bldg:ekibiru", "駅ビル（商業）", "商業", "S", [8000, 8000], [8000],
                             [4500] * ekibiru_floors)
    eb_levels = [f"L{i+1}" for i in range(ekibiru_floors)]
    eb_rooms, eb_walls = [], []
    for li in range(ekibiru_floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        fl = [room(f"room:EB-{ln}-T1", lid, "テナント", "テナント", 0, 1, 0, 1, f"EB-{ln}-W", 3600),
              room(f"room:EB-{ln}-CORE", lid, "コアホール", "コアホール", 1, 2, 0, 1, f"EB-{ln}-E", 3600)]
        eb_rooms += fl
        eb_walls += build_walls(fl, lid, 2, 1, commercial_decide, f"EB-{ln}")
    eb_cores = [{"id": "core:EB", "levelRange": eb_levels,
                 "rect": {"xFrom": "X2", "xTo": "X3", "yFrom": "Y1", "yTo": "Y2"}}]
    eb_shafts = [
        {"id": "shaft:eb-stair", "coreId": "core:EB", "kind": "階段", "levelRange": eb_levels,
         "footprint": {"x": 8200, "y": 200, "w": 3400, "d": 7000},
         "stair": {"riser": 180, "steps": 25, "going": 260}},
        {"id": "shaft:eb-ev", "coreId": "core:EB", "kind": "EV", "levelRange": eb_levels,
         "footprint": {"x": 12000, "y": 5000, "w": 2300, "d": 2300}},
        {"id": "shaft:eb-ps", "coreId": "core:EB", "kind": "PS", "levelRange": eb_levels,
         "footprint": {"x": 14500, "y": 5000, "w": 1200, "d": 2400}},
    ]
    eb_zones = [{"id": f"EB-{ln}-{s}", "level": lid,
                 "cellRange": {"xFrom": f"X{a+1}", "xTo": f"X{a+2}", "yFrom": "Y1", "yTo": "Y2"}}
                for li in range(ekibiru_floors) for lid, ln, s, a in
                ((f"L{li+1}", f"{li+1}F", "W", 0), (f"L{li+1}", f"{li+1}F", "E", 1))]
    eb_comp = [{"id": f"fc:EB-{ln}", "kind": "面積区画", "level": f"L{li+1}",
                "rooms": [f"room:EB-{ln}-T1", f"room:EB-{ln}-CORE"]}
               for li in range(ekibiru_floors) for ln in [f"{li+1}F"]] + \
              [{"id": f"fc:EB-{s}", "kind": "竪穴区画", "shafts": [f"shaft:eb-{s}"]}
               for s in ("stair", "ev", "ps")]
    eb.update({"cores": eb_cores, "shafts": eb_shafts, "rooms": eb_rooms, "walls": eb_walls,
               "zones": eb_zones, "compartments": eb_comp})
    eb["slabs"] = [{"id": f"slab:EB-L{li+1}", "level": f"L{li+1}",
                    "kind": "土間コンクリート" if li == 0 else "デッキ合成スラブ",
                    "cells": full_eb, "thickness": 150,
                    "openings": [] if li == 0 else [s["id"] for s in eb_shafts],
                    **({"onGround": True} if li == 0 else {})} for li in range(ekibiru_floors)]
    attach_structure(eb, system="S", plate={(i, 0) for i in range(2)}, levels_all=eb_levels,
                     fh_list=[4500] * ekibiru_floors, core_cells_list=[{(1, 0)}], use="商業")
    # --- site（軌道・ホーム） ---
    if form == "島式":
        tracks = [{"id": "track:1", "name": "下り線", "kind": "在来線", "centerOffset": -4800, "centerSpacing": 8400},
                  {"id": "track:2", "name": "上り線", "kind": "在来線", "centerOffset": -13200, "centerSpacing": 8400}]
        platforms = [{"id": "platform:A", "level": "L1", "trackIds": ["track:1", "track:2"], "form": "島式",
                      "rect": {"x": -2000, "y": -11700, "w": plat_len + 4000, "d": 5400},
                      "edgeOffset": 1500, "height": 1100, "usableWidth": 5400}]
    else:
        tracks = [{"id": "track:1", "name": "下り線", "kind": "在来線", "centerOffset": -6000, "centerSpacing": 3600},
                  {"id": "track:2", "name": "上り線", "kind": "在来線", "centerOffset": -9600, "centerSpacing": 3600}]
        platforms = [{"id": "platform:A", "level": "L1", "trackIds": ["track:1"], "form": "相対式",
                      "rect": {"x": -2000, "y": -4520, "w": plat_len + 4000, "d": 2000},
                      "edgeOffset": 1480, "height": 1100, "usableWidth": 2000},
                     {"id": "platform:B", "level": "L1", "trackIds": ["track:2"], "form": "相対式",
                      "rect": {"x": -2000, "y": -13080, "w": plat_len + 4000, "d": 2000},
                      "edgeOffset": 1480, "height": 1100, "usableWidth": 2000}]
    site = {"polygon": [[-8000, -18000], [plat_len + 10000, -18000],
                        [plat_len + 10000, 22000], [-8000, 22000]],
            "buildingPlacement": {"origin": [0, 0], "rotationDeg": 0},
            "roads": [{"edge": "south", "name": "駅前広場・町道", "width": 8000}],
            "gates": [], "neighbors": [{"edge": "north", "type": "住宅"}, {"edge": "south", "type": "駅前広場"}],
            "tracks": tracks, "platforms": platforms}
    st["genericElements"] = [
        {"id": "ge:footbridge", "name": "跨線橋", "attachTo": "platform:A", "note": "改札内コンコースから対向ホームへ"},
        {"id": "ge:canopy-a", "name": "ホーム上屋", "attachTo": "platform:A", "note": "有効長の大半を覆う"},
    ] if form != "島式" else [
        {"id": "ge:canopy-a", "name": "ホーム上屋", "attachTo": "platform:A", "note": "有効長の大半を覆う"}]
    return {"complex": {"id": "complex:station-gen", "name": f"生成：駅（地上駅・{form}＋駅ビル）",
                        "links": [{"id": "link:1", "from": "bldg:station", "to": "bldg:ekibiru",
                                   "kind": "連絡通路"}]},
            "site": site, "buildings": [st, eb]}


def gen_seeded_station(conv, ann=None, form="相対式"):
    """シード版駅：実在駅の外形（変換結果）に駅舎レイアウトを割り当て、駅ビルとの複合にする。
    駅舎は1階のみ：南（モデル-Y側）＝改札外、北（+Y側）＝改札内とし、改札行（fareRow）より
    北の最外行を駅務諸室帯とする。上層は駅ビル（別建物・テナント＋コア3箇所）として起こす。
    軌道・ホームは北側（+Y）に置く。fareRow は annotation で上書きできる。"""
    ann = ann or {}
    grid = conv["grid"]
    spans_x = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesX"]],
                                        [a["offset"] for a in grid["axesX"]][1:])]
    spans_y = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesY"]],
                                        [a["offset"] for a in grid["axesY"]][1:])]
    nx, ny = len(spans_x), len(spans_y)
    X = {a["name"]: a["offset"] for a in grid["axesX"]}
    Y = {a["name"]: a["offset"] for a in grid["axesY"]}
    plate = set()
    for r in conv["footprint"]:
        for i in range(int(r["xFrom"][1:]) - 1, int(r["xTo"][1:]) - 1):
            for j in range(int(r["yFrom"][1:]) - 1, int(r["yTo"][1:]) - 1):
                plate.add((i, j))
    props = conv.get("source_properties", {})
    total_floors = ann.get("floors") or (int(props["building:levels"]) if props.get("building:levels") else 2)
    rows_all = sorted({j for (_, j) in plate})
    fare_row = ann.get("fareRow")
    if fare_row is None:
        fare_row = rows_all[0] + round(0.55 * (rows_all[-1] - rows_all[0]))
    col_max = {i: max(j for (ii, j) in plate if ii == i) for i in range(nx)
               if any(ii == i for (ii, _) in plate)}
    row_span = {j: (min(i for (i, jj) in plate if jj == j), max(i for (i, jj) in plate if jj == j))
                for j in rows_all}

    def row_frac(i, j):
        x0, x1 = row_span[j]
        return (i - x0) / max(1, (x1 - x0))

    # ---- 駅舎（L1）：セル割当 ----
    boh = (("WC", "WC"), ("電気室", "電気室"), ("信号通信室", "信号通信室"),
           ("機械室", "機械室"), ("倉庫", "倉庫"), ("駅務室", "駅務室・防災"))  # (use, name)
    assigned = {}
    for (i, j) in plate:
        fr = row_frac(i, j)
        if j <= fare_row:
            if j >= fare_row - 1 or fr < 0.30:
                assigned[(i, j)] = ("コンコース", "改札外コンコース", "out")
            elif fr < 0.50:
                assigned[(i, j)] = ("待合室", "待合室", "out")
            elif fr < 0.70:
                assigned[(i, j)] = ("テナント", "売店", "out")
            else:
                assigned[(i, j)] = ("駅事務室", "駅事務室", "out")
        elif j == col_max[i]:
            use, nm = boh[min(5, int(fr * 6))]
            assigned[(i, j)] = (use, nm, "in")
        else:
            assigned[(i, j)] = ("コンコース", "改札内コンコース", "in")
    from collections import defaultdict as _dds
    groups = _dds(set)
    for cell, (use, nm, band) in assigned.items():
        groups[(use, nm, band)].add(cell)
    st, full = base_parts("bldg:station-seeded", ann.get("buildingName", "生成：シード駅舎"),
                          "駅舎", "S", spans_x, spans_y, [4200])
    st["levels"][0]["footprint"] = conv["footprint"]
    rooms, room_band = [], {}
    seq = {}
    for (use, nm, band), cells in sorted(groups.items()):
        for (i0, j0, w, h) in _decompose(cells, 6):
            seq[nm] = seq.get(nm, 0) + 1
            suf = nm if seq[nm] == 1 else f"{nm}{seq[nm]}"
            zid = "ST-W" if i0 < nx // 3 else "ST-C" if i0 < 2 * nx // 3 else "ST-E"
            rooms.append(room(f"room:ST-{suf}", "L1", suf, use, i0, i0 + w, j0, j0 + h, zid,
                              3600 if use == "コンコース" else 3300))
            room_band[rooms[-1]["id"]] = band
    # 機械室のセルに PS コア
    mech = max((r for r in rooms if r["use"] == "機械室"),
               key=lambda r: (int(r["cells"]["xTo"][1:]) - int(r["cells"]["xFrom"][1:])) *
                             (int(r["cells"]["yTo"][1:]) - int(r["cells"]["yFrom"][1:])))
    mc = mech["cells"]
    ci, cj = int(mc["xFrom"][1:]) - 1, int(mc["yFrom"][1:]) - 1
    cores = [{"id": "core:ST-MECH", "levelRange": ["L1"],
              "rect": {"xFrom": mc["xFrom"], "xTo": f"X{ci+2}", "yFrom": mc["yFrom"], "yTo": f"Y{cj+2}"}}]
    shafts = [{"id": "shaft:st-ps", "coreId": "core:ST-MECH", "kind": "PS", "levelRange": ["L1"],
               "footprint": {"x": X[mc["xFrom"]] + 100, "y": Y[mc["yFrom"]] + 200, "w": 1200, "d": 2400}}]
    walls = build_walls(rooms, "L1", nx, ny, station_decide, "ST")
    zones = []
    for suf, b0, b1 in (("W", 0, nx // 3), ("C", nx // 3, 2 * nx // 3), ("E", 2 * nx // 3, nx)):
        ranges = []
        for j in range(ny):
            run = None
            for i in range(b0, b1 + 1):
                inside = i < b1 and (i, j) in plate
                if inside and run is None:
                    run = i
                if not inside and run is not None:
                    ranges.append({"xFrom": f"X{run+1}", "xTo": f"X{i+1}",
                                   "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
                    run = None
        if ranges:
            zones.append({"id": f"ST-{suf}", "level": "L1", "cellRanges": ranges})
    compartments = [{"id": "fc:ST-L1", "kind": "面積区画", "level": "L1",
                     "rooms": [r["id"] for r in rooms]},
                    {"id": "fc:ST-shaft", "kind": "竪穴区画", "shafts": ["shaft:st-ps"]}]
    st.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
               "zones": zones, "compartments": compartments})
    st["slabs"] = [{"id": "slab:ST-L1", "level": "L1", "kind": "土間コンクリート",
                    "cellRanges": conv["footprint"], "thickness": 150, "onGround": True, "openings": []}]
    st["roof"] = {"id": "roof:main", "topLevel": "L1", "kind": "陸屋根（シート防水）",
                  "cellRanges": conv["footprint"], "parapetHeight": 600}
    st["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cellRanges": conv["footprint"], "depth": 1500}]
    st["fareZones"] = [
        {"id": "zone:out", "kind": "改札外", "level": "L1",
         "rooms": [rid for rid, bd in room_band.items() if bd == "out"]},
        {"id": "zone:in", "kind": "改札内", "level": "L1",
         "rooms": [rid for rid, bd in room_band.items() if bd == "in"]},
    ]
    st["fareGates"] = [{"id": "gate:main", "level": "L1", "fromZone": "zone:out", "toZone": "zone:in",
                         "passages": 4, "widePassages": 1}]
    attach_structure(st, system="S", plate=plate, levels_all=["L1"], fh_list=[4200],
                     core_cells_list=[{(ci, cj)}], use="駅舎")
    fix_doors(st)

    # ---- 駅ビル（上層を別建物として起こす） ----
    eb_floors = ann.get("ekibiruFloors") or max(1, total_floors - 1)
    eb, full_eb = base_parts("bldg:ekibiru-seeded", ann.get("ekibiruName", "生成：シード駅ビル"),
                             "商業", "S", spans_x, spans_y, [4500] * eb_floors, sprinkler=True)
    eb_levels = [f"L{i+1}" for i in range(eb_floors)]
    for li in range(eb_floors):
        eb["levels"][li]["footprint"] = conv["footprint"]
    # コア配置：歩行距離（40m）の担保に、プレート内へ約4セル間隔の格子状に置く。
    # 雁行した縁などで届かないセルが残れば、最も遠いセルにコアを足して再計算する
    _cols = sorted({i for (i, _) in plate})
    _rows = sorted({j for (_, j) in plate})
    core_cells = {(i, j) for i in _cols[::4] for j in _rows[::4] if (i, j) in plate}
    if not core_cells:
        core_cells = {(nx // 2, fare_row)}
    from collections import deque as _dq

    def _walk_max(sources):
        dist = {c: 0 for c in sources}
        dq = _dq(sources)
        Xn_ = [a["name"] for a in grid["axesX"]]
        Yn_ = [a["name"] for a in grid["axesY"]]
        while dq:
            c = dq.popleft()
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + d[0], c[1] + d[1])
                if n in plate and n not in dist:
                    step = spans_x[n[0]] if d[0] else spans_y[n[1]]
                    dist[n] = dist[c] + step
                    dq.append(n)
            for d in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                n = (c[0] + d[0], c[1] + d[1])
                if n in plate and n not in dist and \
                        (c[0] + d[0], c[1]) in plate and (c[0], c[1] + d[1]) in plate:
                    dist[n] = dist[c] + int(0.707 * (spans_x[n[0]] + spans_y[n[1]]))
                    dq.append(n)
        far = max(plate, key=lambda c: dist.get(c, 10 ** 9))
        return far, dist.get(far, 10 ** 9)

    for _ in range(8):
        _far, _d = _walk_max(core_cells)
        if _d <= 38000:
            break
        core_cells.add(_far)
    core_list = sorted(core_cells)
    eb_cores, eb_shafts = [], []
    for k, (cc, cj) in enumerate(core_list):
        cid = f"core:EB{k}"
        eb_cores.append({"id": cid, "levelRange": eb_levels,
                         "rect": {"xFrom": f"X{cc+1}", "xTo": f"X{cc+2}",
                                  "yFrom": f"Y{cj+1}", "yTo": f"Y{cj+2}"}})
        x0, y0 = X[f"X{cc+1}"], Y[f"Y{cj+1}"]
        eb_shafts.append({"id": f"shaft:eb{k}-stair", "coreId": cid, "kind": "階段",
                          "levelRange": eb_levels,
                          "footprint": {"x": x0 + 200, "y": y0 + 200, "w": 3400, "d": 7000},
                          "stair": {"riser": 180, "steps": 25, "going": 260}})
        eb_shafts.append({"id": f"shaft:eb{k}-ps", "coreId": cid, "kind": "PS",
                          "levelRange": eb_levels,
                          "footprint": {"x": x0 + 4200, "y": y0 + 200, "w": 1200, "d": 2400}})
    def decompose33(cells):
        out = []
        for (i0, j0, w, h) in _decompose(cells, 3):
            jj = j0
            while jj < j0 + h:
                hh = min(3, j0 + h - jj)
                out.append((i0, jj, w, hh))
                jj += hh
        return out
    eb_rooms, eb_walls, eb_zones, eb_comp = [], [], [], []
    for li in range(eb_floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        fl = []
        tenant_cells = plate - core_cells
        for k, (i0, j0, w, h) in enumerate(decompose33(tenant_cells)):
            zid = f"EB-{ln}-{'W' if i0 < nx // 3 else 'C' if i0 < 2 * nx // 3 else 'E'}"
            fl.append(room(f"room:EB-{ln}-T{k+1}", lid, f"テナント{k+1}", "テナント",
                           i0, i0 + w, j0, j0 + h, zid, 3600))
        for k, (cc, cj) in enumerate(core_list):
            fl.append(room(f"room:EB-{ln}-CORE{k}", lid, "コアホール", "コアホール",
                           cc, cc + 1, cj, cj + 1, f"EB-{ln}-C", 3600))
        eb_rooms += fl
        eb_walls += build_walls(fl, lid, nx, ny, commercial_decide, f"EB-{ln}")
        for suf, b0, b1 in (("W", 0, nx // 3), ("C", nx // 3, 2 * nx // 3), ("E", 2 * nx // 3, nx)):
            ranges = []
            for j in range(ny):
                run = None
                for i in range(b0, b1 + 1):
                    inside = i < b1 and (i, j) in plate
                    if inside and run is None:
                        run = i
                    if not inside and run is not None:
                        ranges.append({"xFrom": f"X{run+1}", "xTo": f"X{i+1}",
                                       "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
                        run = None
            if ranges:
                eb_zones.append({"id": f"EB-{ln}-{suf}", "level": lid, "cellRanges": ranges})
        # 面積区画：X方向に貪欲に分割（1区画 ≦ 2,900㎡ 目安）
        fl_sorted = sorted(fl, key=lambda r: X[r["cells"]["xFrom"]])
        chunk, acc = [], 0.0
        ci_ = 0
        for r in fl_sorted:
            c = r["cells"]
            a = (X[c["xTo"]] - X[c["xFrom"]]) * (Y[c["yTo"]] - Y[c["yFrom"]]) / 1e6
            if chunk and acc + a > 2900:
                eb_comp.append({"id": f"fc:EB-{ln}-{ci_}", "kind": "面積区画", "level": lid,
                                "rooms": [x["id"] for x in chunk]})
                chunk, acc, ci_ = [], 0.0, ci_ + 1
            chunk.append(r)
            acc += a
        if chunk:
            eb_comp.append({"id": f"fc:EB-{ln}-{ci_}", "kind": "面積区画", "level": lid,
                            "rooms": [x["id"] for x in chunk]})
    eb_comp += [{"id": f"fc:EB-shaft-{s['id'].split(':')[1]}", "kind": "竪穴区画", "shafts": [s["id"]]}
                for s in eb_shafts]
    eb.update({"cores": eb_cores, "shafts": eb_shafts, "rooms": eb_rooms, "walls": eb_walls,
               "zones": eb_zones, "compartments": eb_comp})
    eb["slabs"] = [{"id": f"slab:EB-L{li+1}", "level": f"L{li+1}",
                    "kind": "土間コンクリート" if li == 0 else "デッキ合成スラブ",
                    "cellRanges": conv["footprint"], "thickness": 150,
                    "openings": [] if li == 0 else [s["id"] for s in eb_shafts],
                    **({"onGround": True} if li == 0 else {})} for li in range(eb_floors)]
    eb["roof"] = {"id": "roof:main", "topLevel": f"L{eb_floors}", "kind": "陸屋根（シート防水）",
                  "cellRanges": conv["footprint"], "parapetHeight": 600}
    eb["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cellRanges": conv["footprint"], "depth": 1500}]
    attach_structure(eb, system="S", plate=plate, levels_all=eb_levels,
                     fh_list=[4500] * eb_floors,
                     core_cells_list=[{cell} for cell in core_list], use="商業")
    fix_doors(eb)

    # ---- site（軌道・ホームは北側=+Y） ----
    total_w, total_d = X[f"X{nx+1}"], Y[f"Y{ny+1}"]
    if form == "島式":
        tracks = [{"id": "track:1", "name": "下り線", "kind": "在来線",
                   "centerOffset": total_d + 9600, "centerSpacing": 8400},
                  {"id": "track:2", "name": "上り線", "kind": "在来線",
                   "centerOffset": total_d + 1200, "centerSpacing": 8400}]
        platforms = [{"id": "platform:A", "level": "L1", "trackIds": ["track:1", "track:2"],
                      "form": "島式",
                      "rect": {"x": -2000, "y": total_d + 2700, "w": total_w + 4000, "d": 5400},
                      "edgeOffset": 1500, "height": 1100, "usableWidth": 5400}]
    else:
        tracks = [{"id": "track:1", "name": "下り線", "kind": "在来線",
                   "centerOffset": total_d + 4480, "centerSpacing": 3600},
                  {"id": "track:2", "name": "上り線", "kind": "在来線",
                   "centerOffset": total_d + 8080, "centerSpacing": 3600}]
        platforms = [{"id": "platform:A", "level": "L1", "trackIds": ["track:1"], "form": "相対式",
                      "rect": {"x": -2000, "y": total_d + 1000, "w": total_w + 4000, "d": 2000},
                      "edgeOffset": 1480, "height": 1100, "usableWidth": 2000},
                     {"id": "platform:B", "level": "L1", "trackIds": ["track:2"], "form": "相対式",
                      "rect": {"x": -2000, "y": total_d + 9560, "w": total_w + 4000, "d": 2000},
                      "edgeOffset": 1480, "height": 1100, "usableWidth": 2000}]
    site = {"polygon": [[-8000, -10000], [total_w + 10000, -10000],
                        [total_w + 10000, total_d + 16000], [-8000, total_d + 16000]],
            "buildingPlacement": {"origin": [0, 0],
                                  "rotationDeg": round(conv.get("main_axis_deg", 0), 1)},
            "roads": [{"edge": "south", "name": "駅前広場・町道", "width": 8000}],
            "gates": [], "neighbors": [{"edge": "north", "type": "住宅"}, {"edge": "south", "type": "駅前広場"}],
            "tracks": tracks, "platforms": platforms}
    st["genericElements"] = [
        {"id": "ge:canopy-a", "name": "ホーム上屋", "attachTo": "platform:A", "note": "有効長の大半を覆う"}]
    return {"complex": {"id": "complex:station-seeded", "name": ann.get("complexName", "生成：シード駅"),
                        "links": [{"id": "link:1", "from": "bldg:station-seeded",
                                   "to": "bldg:ekibiru-seeded", "kind": "連絡通路"}]},
            "site": site, "buildings": [st, eb]}


def gen_seeded(conv_path):
    conv = json.load(open(conv_path, encoding="utf-8"))
    props = conv.get("source_properties", {})
    grid = conv["grid"]
    spans_x = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesX"]],
                                        [a["offset"] for a in grid["axesX"]][1:])]
    spans_y = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesY"]],
                                        [a["offset"] for a in grid["axesY"]][1:])]
    nx, ny = len(spans_x), len(spans_y)
    X = {a["name"]: a["offset"] for a in grid["axesX"]}
    Y = {a["name"]: a["offset"] for a in grid["axesY"]}
    plate = set()
    for r in conv["footprint"]:
        for i in range(int(r["xFrom"][1:]) - 1, int(r["xTo"][1:]) - 1):
            for j in range(int(r["yFrom"][1:]) - 1, int(r["yTo"][1:]) - 1):
                plate.add((i, j))
    height_m = props.get("measured_height") or 16.2  # PLATEAU の計測高さはメートル
    floors = max(1, min(6, round(height_m / 5.4)))
    fh = [5400] * floors
    label = props.get("usage") or "商業施設"
    b, full = base_parts("bldg:gen-seeded", f"生成：シード商業（{label}）", "商業", "S",
                         spans_x, spans_y, fh, sprinkler=True)
    for li in range(floors):
        b["levels"][li]["footprint"] = conv["footprint"]
    levels_all = [f"L{i+1}" for i in range(floors)]

    # --- バンド割当（行ごと） ---
    row_width = {j: sum(1 for (i, jj) in plate if jj == j) for j in range(ny)}
    mid = ny // 2
    mall_rows = None
    for cand in range(mid - 2, mid + 3):
        pair = [cand, cand + 1]
        if all(0 <= j < ny and row_width.get(j, 0) >= 0.7 * nx for j in pair):
            mall_rows = pair
            break
    if mall_rows is None:
        mall_rows = [mid - 1, mid]
    def assign_side(rows_outward, north=False):
        bands = []
        pattern = ["tenant", "mall", "tenant"]
        i, p = 0, 0
        while i < len(rows_outward):
            t = pattern[min(p, 2)]
            take = rows_outward[i:i + 2] if p < 2 else rows_outward[i:]
            bands.append([t, list(take)])
            i += len(take); p += 1
        if north and bands and bands[-1][0] == "tenant" and len(bands[-1][1]) >= 3:
            svc = bands[-1][1][2:]
            bands[-1][1] = bands[-1][1][:2]
            bands.append(["service", svc])
        return bands
    south_rows = list(range(mall_rows[0] - 1, -1, -1))
    north_rows = list(range(mall_rows[1] + 1, ny))
    band_of_row = {j: "mall" for j in mall_rows}
    for t, rows_ in assign_side(south_rows):
        for j in rows_:
            band_of_row[j] = t
    north_bands = assign_side(north_rows, north=True)
    for t, rows_ in north_bands:
        for j in rows_:
            band_of_row[j] = t
    north_tenant_rows = [j for t, rows_ in north_bands if t == "tenant" for j in rows_][:2]

    # --- コア配置（北テナント帯に 2×2 セル、全階共通） ---
    core_blocks = []
    if north_tenant_rows:
        r0 = min(north_tenant_rows)
        for ci in range(2, nx - 2, 12):
            block = {(ci + dx, r0 + dy) for dx in range(2) for dy in range(2)
                     if r0 + dy <= max(north_tenant_rows)}
            if len(block) == 4 and block <= plate:
                core_blocks.append((ci, r0))
    cores, shafts, compartments = [], [], []
    for ci, (cx, cy) in enumerate(core_blocks):
        cid = f"core:S{ci}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{cx+1}", "xTo": f"X{cx+3}",
                               "yFrom": f"Y{cy+1}", "yTo": f"Y{cy+3}"}})
        x0, y0 = X[f"X{cx+1}"], Y[f"Y{cy+1}"]
        defs = [("stair", "階段", x0 + 200, y0 + 200, 3200, 8000, {"riser": 180, "steps": 30, "going": 260}),
                ("ev", "EV", x0 + 3600, y0 + 200, 2300, 2300, None),
                ("ps", "PS", x0 + 6100, y0 + 200, 1100, 2800, None),
                ("ds", "DS", x0 + 7300, y0 + 200, 900, 2800, None)]
        if ci in (0, len(core_blocks) - 1):
            defs.append(("fev", "EV", x0 + 3600, y0 + 8000, 2400, 2400, {"freight": True}))
        for suf, kind, fx, fy, w, d, extra in defs:
            s = {"id": f"shaft:{cid.split(':')[1]}-{suf}", "coreId": cid, "kind": kind,
                 "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
            if suf == "stair":
                s["stair"] = extra
            elif suf == "fev":
                s["freight"] = True
            shafts.append(s)
            compartments.append({"id": f"fc:shaft-{cid.split(':')[1]}-{suf}", "kind": "竪穴区画",
                                 "shafts": [s["id"]]})
    core_cells = {(cx + dx, cy + dy) for (cx, cy) in core_blocks for dx in range(2) for dy in range(2)}

    # --- 吹抜け（上階の中央モール帯） ---
    mall_cells_all = {(i, j) for (i, j) in plate if band_of_row[j] == "mall" and j in mall_rows}
    void_cells = set()
    if floors > 1 and mall_cells_all:
        xs = sorted(i for (i, j) in mall_cells_all)
        vc = xs[len(xs) // 2]
        void_cells = {(i, j) for (i, j) in mall_cells_all if vc - 2 <= i < vc + 2}
        vx0 = min(i for (i, j) in void_cells); vy0 = min(j for (i, j) in void_cells)
        vx1 = max(i for (i, j) in void_cells); vy1 = max(j for (i, j) in void_cells)
        cores.append({"id": "core:AT", "levelRange": levels_all[1:],
                      "rect": {"xFrom": f"X{vx0+1}", "xTo": f"X{vx1+2}",
                               "yFrom": f"Y{vy0+1}", "yTo": f"Y{vy1+2}"}})
        shafts.append({"id": "shaft:AT-void", "coreId": "core:AT", "kind": "吹抜け",
                       "levelRange": levels_all[1:],
                       "footprint": {"x": X[f"X{vx0+1}"] + 200, "y": Y[f"Y{vy0+1}"] + 200,
                                     "w": X[f"X{vx1+2}"] - X[f"X{vx0+1}"] - 400,
                                     "d": Y[f"Y{vy1+2}"] - Y[f"Y{vy0+1}"] - 400}})
        compartments.append({"id": "fc:shaft-AT", "kind": "竪穴区画", "shafts": ["shaft:AT-void"]})

    rooms, walls, zones = [], [], []
    MAXW = {"mall": 10, "tenant": 3, "service": 6}
    for li in range(floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        fl = []
        reserved = {}
        for ci, (cx, cy) in enumerate(core_blocks):
            for dx in range(2):
                for dy in range(2):
                    reserved[(cx + dx, cy + dy)] = ("CORE", ci)
        wc_cells = set()
        for (cx, cy) in core_blocks:
            cand = (cx + 2, cy)
            if cand in plate and cand not in reserved and band_of_row.get(cand[1]) == "tenant":
                wc_cells.add(cand)
                reserved[cand] = ("WC",)
        if li >= 1:
            for c in void_cells:
                reserved[c] = ("VOID",)
        def add_room(suf, name, use, i0, j0, w, h, ceil=3600):
            mid = i0 + w / 2
            zid = f"{ln}-W" if mid < nx / 3 else f"{ln}-C" if mid < 2 * nx / 3 else f"{ln}-E"
            r = room(f"room:{ln}-{suf}", lid, name, use, i0, i0 + w, j0, j0 + h,
                     zid if use != "モール" else None, ceil)
            fl.append(r); rooms.append(r)
            return r
        for ci, (cx, cy) in enumerate(core_blocks):
            add_room(f"CORE{ci}", "コアホール", "コアホール", cx, cy, 2, 2)
        for k, (i, j) in enumerate(sorted(wc_cells)):
            add_room(f"WC{k}", "便所・サービス", "WC", i, j, 1, 1, ceil=3000)
        if li >= 1 and void_cells:
            vx0 = min(i for (i, j) in void_cells); vy0 = min(j for (i, j) in void_cells)
            vx1 = max(i for (i, j) in void_cells); vy1 = max(j for (i, j) in void_cells)
            add_room("VOID", "吹抜け", "吹抜け", vx0, vy0, vx1 - vx0 + 1, vy1 - vy0 + 1, ceil=4800)
        counters = {"mall": 0, "tenant": 0, "service": 0}
        for band in ("mall", "tenant", "service"):
            cells = {(i, j) for (i, j) in plate if band_of_row[j] == band and (i, j) not in reserved}
            for (i0, j0, w, h) in _decompose(cells, MAXW[band]):
                counters[band] += 1
                n = counters[band]
                if band == "mall":
                    add_room(f"MALL{n}", "モール", "モール", i0, j0, w, h, ceil=4800)
                elif band == "tenant":
                    def split_ratio(a0, b0, w_, h_):
                        wm_ = X[f"X{a0+w_+1}"] - X[f"X{a0+1}"]
                        dm_ = Y[f"Y{b0+h_+1}"] - Y[f"Y{b0+1}"]
                        if max(wm_, dm_) / min(wm_, dm_) <= 3 or (w_ == 1 and h_ == 1):
                            return [(a0, b0, w_, h_)]
                        if wm_ >= dm_ and w_ > 1:
                            w1 = w_ // 2
                            return split_ratio(a0, b0, w1, h_) + split_ratio(a0 + w1, b0, w_ - w1, h_)
                        h1 = h_ // 2
                        return split_ratio(a0, b0, w_, h1) + split_ratio(a0, b0 + h1, w_, h_ - h1)
                    for k, (a0, b0, w_, h_) in enumerate(split_ratio(i0, j0, w, h)):
                        n_ = n if k == 0 else f"{n}-{k}"
                        if li == floors - 1 and b0 < mall_rows[0]:
                            add_room(f"R{n_}", f"レストラン{n_}", "飲食", a0, b0, w_, h_)
                        else:
                            area = w_ * spans_x[0] * h_ * spans_y[0] / 1e6
                            add_room(f"T{n_}", "大型テナント" if area >= 400 else f"テナント{n_}",
                                     "テナント", a0, b0, w_, h_)
                else:
                    if li == 0 and n == 1:
                        add_room("BOUSAI", "防災センター", "防災センター", i0, j0, w, h)
                    else:
                        add_room(f"BY{n}", "バックヤード・サービス", "バックヤード", i0, j0, w, h)
        # 工区：プレートを x 方向3帯に
        for suf, b0, b1 in (("W", 0, nx // 3), ("C", nx // 3, 2 * nx // 3), ("E", 2 * nx // 3, nx)):
            ranges = []
            for j in range(ny):
                run = None
                for i in range(b0, b1 + 1):
                    inside = i < b1 and (i, j) in plate
                    if inside and run is None:
                        run = i
                    if not inside and run is not None:
                        ranges.append({"xFrom": f"X{run+1}", "xTo": f"X{i+1}",
                                       "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
                        run = None
            if ranges:
                zones.append({"id": f"{ln}-{suf}", "level": lid, "cellRanges": ranges})
        # 面積区画：x 順に貪欲に 2,900㎡ 以下へ
        def room_area(r):
            c = r["cells"]
            return (X[c["xTo"]] - X[c["xFrom"]]) * (Y[c["yTo"]] - Y[c["yFrom"]]) / 1e6
        groups, cur, cur_area = [], [], 0.0
        for r in sorted(fl, key=lambda r: X[r["cells"]["xFrom"]]):
            a = room_area(r)
            if cur and cur_area + a > 2900:
                groups.append(cur); cur, cur_area = [], 0.0
            cur.append(r["id"]); cur_area += a
        if cur:
            groups.append(cur)
        for gi, g in enumerate(groups):
            compartments.append({"id": f"fc:{ln}-{gi}", "kind": "面積区画", "level": lid, "rooms": g})
        walls += build_walls(fl, lid, nx, ny, commercial_decide, f"S-{ln}")
    b.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
              "zones": zones, "compartments": compartments})
    slabs = []
    for li in range(floors):
        lid = f"L{li+1}"
        ops = [s["id"] for s in shafts if lid in s["levelRange"]] if li > 0 else []
        slabs.append({"id": f"slab:{lid}", "level": lid,
                      "kind": "土間コンクリート" if li == 0 else "デッキ合成スラブ",
                      "cellRanges": conv["footprint"], "thickness": 150, "openings": ops,
                      **({"onGround": True} if li == 0 else {})})
    b["slabs"] = slabs
    b["roof"] = {"id": "roof:main", "topLevel": f"L{floors}", "kind": "陸屋根（シート防水）",
                 "cellRanges": conv["footprint"], "parapetHeight": 600}
    b["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cellRanges": conv["footprint"], "depth": 1500}]
    b["site"] = {"polygon": [[-15000, -12000], [400000, -12000], [400000, 140000], [-15000, 140000]],
                 "buildingPlacement": {"origin": [0, 0], "rotationDeg": round(conv.get("main_axis_deg", 0), 1)},
                 "roads": [], "gates": [], "neighbors": []}
    mall1 = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "モール"), None)
    if mall1:
        b["coverings"] = [{"id": "cov:mall-floor", "target": mall1, "part": "床", "name": "磁器質タイル"}]
    b["reinforcement"] = [{"id": "re:slab", "target": "slab:L2" if floors > 1 else "slab:L1",
                           "kind": "スラブ配筋", "spec": "D13@200 ダブル"},
                          {"id": "re:footing", "target": "foundation:each-column", "kind": "基礎配筋",
                           "spec": "主筋D19・あばら筋D13@150"}]
    return b



# ---------- シード生成 v2（annotation 制約＋L3裏側フィル） ----------
# INTERIOR_MODEL_V2 の3層：L1 外形（変換結果）＋L2 公開部分（annotation=guide）
# ＋L3 非公開部分（建築計画ノルム=program）。残りは推定フィル（inferred）。
# 部屋には source（guide/program/inferred）を付ける。

def gen_seeded2(conv_path, ann_path):
    conv = json.load(open(conv_path, encoding="utf-8"))
    ann = json.load(open(ann_path, encoding="utf-8"))
    grid = conv["grid"]
    spans_x = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesX"]],
                                        [a["offset"] for a in grid["axesX"]][1:])]
    spans_y = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesY"]],
                                        [a["offset"] for a in grid["axesY"]][1:])]
    nx, ny = len(spans_x), len(spans_y)
    X = {a["name"]: a["offset"] for a in grid["axesX"]}
    Y = {a["name"]: a["offset"] for a in grid["axesY"]}
    plate = set()
    for r in conv["footprint"]:
        for i in range(int(r["xFrom"][1:]) - 1, int(r["xTo"][1:]) - 1):
            for j in range(int(r["yFrom"][1:]) - 1, int(r["yTo"][1:]) - 1):
                plate.add((i, j))
    rows_span = {}
    for j in range(ny):
        xs = [i for (i, jj) in plate if jj == j]
        if xs:
            rows_span[j] = (min(xs), max(xs))
    from collections import Counter
    slab_east = Counter(x1 for (_, x1) in rows_span.values()).most_common(1)[0][0]
    slab_west = Counter(x0 for (x0, _) in rows_span.values()).most_common(1)[0][0]
    # サービス面の解決：annotation の serviceFace は実方位。変換の主軸方位からモデル端へ寄せる
    svc_plus = True
    if ann.get("serviceFace") and conv.get("main_axis_deg") is not None:
        import math as _m2
        _a2 = _m2.radians(conv["main_axis_deg"])
        _sv2 = {"E": (1, 0), "W": (-1, 0), "N": (0, 1), "S": (0, -1)}[ann["serviceFace"]]
        svc_plus = (_m2.cos(_a2) * _sv2[0] + _m2.sin(_a2) * _sv2[1]) >= 0
    def frac(i, j):
        x0, x1 = rows_span[j]
        return (i - x0) / max(1, (x1 - x0))
    # アンカー域の判定：anchorFracFrom（モデル座標）または anchorSide（実方位）＋anchorSize。
    # anchorSide は変換結果の方位（main_axis_deg）からモデル端へ解決する。
    if ann.get("anchorSide"):
        import math as _math
        _ang = _math.radians(conv.get("main_axis_deg", 0))
        _xv = (_math.cos(_ang), _math.sin(_ang))
        _sv = {"E": (1, 0), "W": (-1, 0), "N": (0, 1), "S": (0, -1)}[ann["anchorSide"]]
        _size = ann.get("anchorSize", 0.32)
        if _xv[0] * _sv[0] + _xv[1] * _sv[1] >= 0:
            _a_from, _a_to = 1 - _size, 1.0
        else:
            _a_from, _a_to = 0.0, _size
    else:
        _a_from, _a_to = ann["anchorFracFrom"], 1.0
    def in_anchor(i, j):
        return _a_from <= frac(i, j) <= _a_to
    floors = ann["floors"]
    fh = [ann.get("floorHeight", 5400)] * floors
    levels_all = [f"L{i+1}" for i in range(floors)]
    # シードの建物仕様（annotation.spec）：値がある項目は生成器の推論より優先する。
    # 値が無い（不明）項目は従来どおり生成器が推論で補い、モデル側に根拠を残す
    spec = ann.get("spec", {})
    def spec_val(k):
        v = spec.get(k, {})
        return v.get("value") if isinstance(v, dict) else v
    sys_seed = spec_val("structureSystem")
    structure_system = sys_seed if sys_seed in ("S", "RC", "SRC", "壁式RC") else "S"
    building_structure = "RC" if structure_system == "壁式RC" else structure_system
    sprinkler_seed = spec_val("sprinkler")
    ceil_seed = spec_val("ceilingHeightMm")
    b, full = base_parts("bldg:gen-seeded2", ann.get("buildingName", "生成：シード商業v2"),
                         "商業", building_structure, spans_x, spans_y, fh,
                         sprinkler=True if sprinkler_seed is None else bool(sprinkler_seed))
    if spec:
        b["building"]["seedSpec"] = spec
    # 特記仕様書1頁相当のシード（工事概要／法規条件／設備概要）：注釈にあればそのままモデルへ写す
    for _blk in ("outline", "zoning", "systems"):
        if ann.get(_blk):
            b["building"][_blk] = ann[_blk]
    for li in range(floors):
        b["levels"][li]["footprint"] = conv["footprint"]
    mall_rows = ann["mallRows"]
    mall_min, mall_max = min(mall_rows), max(mall_rows)
    n_tenant_rows = [mall_max + 1, mall_max + 2]
    fc = ann["foodCourt"]

    # --- サービスコア（業務用EV＋階段、荷捌き隣接）全階共通 ---
    sv_core = (slab_east - 3, mall_min - 1) if svc_plus else (slab_west + 2, mall_min - 1)  # 2x2 の左下セル
    sv_cells = {(sv_core[0] + dx, sv_core[1] + dy) for dx in range(2) for dy in range(2)}
    cores = [{"id": "core:SV", "levelRange": levels_all,
              "rect": {"xFrom": f"X{sv_core[0]+1}", "xTo": f"X{sv_core[0]+3}",
                       "yFrom": f"Y{sv_core[1]+1}", "yTo": f"Y{sv_core[1]+3}"}}]
    x0, y0 = X[f"X{sv_core[0]+1}"], Y[f"Y{sv_core[1]+1}"]
    shafts = [
        {"id": "shaft:SV-fev", "coreId": "core:SV", "kind": "EV", "levelRange": levels_all,
         "footprint": {"x": x0 + 200, "y": y0 + 200, "w": 2400, "d": 2400}, "freight": True},
        {"id": "shaft:SV-stair", "coreId": "core:SV", "kind": "階段", "levelRange": levels_all,
         "footprint": {"x": x0 + 2800, "y": y0 + 200, "w": 3200, "d": 8000},
         "stair": {"riser": 180, "steps": 30, "going": 260}},
        {"id": "shaft:SV-ps", "coreId": "core:SV", "kind": "PS", "levelRange": levels_all,
         "footprint": {"x": x0 + 6200, "y": y0 + 200, "w": 1100, "d": 2800}},
    ]
    compartments = [{"id": f"fc:shaft-SV-{s['id'].split('-')[-1]}", "kind": "竪穴区画",
                     "shafts": [s["id"]]} for s in shafts]

    # --- 客用コア（annotation の coreFracs、北テナント帯） ---
    core_blocks = []
    for fr in ann.get("coreFracs", []):
        target = round(fr * nx)
        placed = None
        for cand in range(target - 1, target + 3):
            for cc in (cand, cand - 1, cand + 1, cand - 2, cand + 2):
                block = {(cc + dx, n_tenant_rows[0] + dy) for dx in range(2) for dy in range(2)}
                if block <= plate and not (block & sv_cells) and \
                        all(abs(cc - cb[0]) > 3 for cb in core_blocks):
                    placed = (cc, n_tenant_rows[0])
                    break
            if placed:
                break
        if placed:
            core_blocks.append(placed)
    # 南側コア（深いプレートでは北帯だけでは歩行距離が届かない。モール南側のテナント帯にも階段を置く）
    if mall_min >= 6:
        north_cores = list(core_blocks)
        for (cx, cy) in north_cores:
            block = {(cx + dx, mall_min - 3 + dy) for dx in range(2) for dy in range(2)}
            if block <= plate and not (block & sv_cells) and \
                    all(abs(cx - bx) > 3 or abs(mall_min - 3 - by) > 3 for (bx, by) in core_blocks):
                core_blocks.append((cx, mall_min - 3))
    for ci, (cx, cy) in enumerate(core_blocks):
        cid = f"core:C{ci}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{cx+1}", "xTo": f"X{cx+3}",
                               "yFrom": f"Y{cy+1}", "yTo": f"Y{cy+3}"}})
        x0, y0 = X[f"X{cx+1}"], Y[f"Y{cy+1}"]
        defs = [("stair", "階段", x0 + 200, y0 + 200, 3200, 8000),
                ("ev", "EV", x0 + 3600, y0 + 200, 2300, 2300),
                ("ps", "PS", x0 + 6100, y0 + 200, 1100, 2800),
                ("ds", "DS", x0 + 7300, y0 + 200, 900, 2800)]
        for suf, kind, fx, fy, w, d in defs:
            s = {"id": f"shaft:C{ci}-{suf}", "coreId": cid, "kind": kind,
                 "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
            if suf == "stair":
                s["stair"] = {"riser": 180, "steps": 30, "going": 260}
            shafts.append(s)
            compartments.append({"id": f"fc:shaft-C{ci}-{suf}", "kind": "竪穴区画", "shafts": [s["id"]]})
    core_cells = {(cx + dx, cy + dy) for (cx, cy) in core_blocks for dx in range(2) for dy in range(2)}

    # --- 核店舗内部の専用階段（歩行距離の担保：大規模売場は階段を格子状に分散させる） ---
    # 対象は主スラブ行（スパンの長い行）におけるアンカー域のみ。短い端行の frac は位置がずれる
    _max_span = max(x1 - x0 for (x0, x1) in rows_span.values())
    _main_rows = [j for j, (x0, x1) in rows_span.items() if x1 - x0 >= 0.5 * _max_span]
    anchor_stairs = []
    _axs = sorted({i for (i, j) in plate if j in _main_rows and in_anchor(i, j)})
    if _axs:
        _rows_a = sorted({j for (i, j) in plate if in_anchor(i, j)})
        _cand_lines = sorted({mall_min - 2, mall_max + 1} |
                             set(range(_rows_a[0] + 1, _rows_a[-1] - 1, 6)) |
                             {_rows_a[0], _rows_a[0] + 1, _rows_a[-1] - 2})
        _lines, _last = [], None
        for _j in _cand_lines:
            if _last is None or _j - _last >= 4:
                _lines.append(_j)
                _last = _j
        _xs = list(range(_axs[0] + 2, _axs[-1] - 2, 5))
        if _axs[-1] - 3 not in _xs:
            _xs.append(_axs[-1] - 3)
        _placed = []
        for _x in _xs:
            for _j in _lines:
                _block = {(_x + dx, _j + dy) for dx in range(2) for dy in range(2)}
                _in_anchor = sum(1 for c in _block if _a_from - 0.02 <= frac(*c) <= _a_to + 0.02)
                if _block <= plate and _in_anchor >= 3 and not (_block & sv_cells) and \
                        all(abs(_x - bx) > 3 or abs(_j - by) > 3 for (bx, by) in _placed + core_blocks):
                    _placed.append((_x, _j))
        anchor_stairs = _placed[:30]
    for ai, (ax, ay) in enumerate(anchor_stairs):
        cid = f"core:A{ai}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{ax+1}", "xTo": f"X{ax+3}",
                               "yFrom": f"Y{ay+1}", "yTo": f"Y{ay+3}"}})
        x0, y0 = X[f"X{ax+1}"], Y[f"Y{ay+1}"]
        for suf, kind, fx, fy, w, d in (("stair", "階段", x0 + 200, y0 + 200, 3200, 8000),
                                        ("ps", "PS", x0 + 6100, y0 + 200, 1100, 2800)):
            s = {"id": f"shaft:A{ai}-{suf}", "coreId": cid, "kind": kind,
                 "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
            if suf == "stair":
                s["stair"] = {"riser": 180, "steps": 30, "going": 260}
            shafts.append(s)
            compartments.append({"id": f"fc:shaft-A{ai}-{suf}", "kind": "竪穴区画", "shafts": [s["id"]]})
    anchor_stair_cells = {(ax + dx, ay + dy) for (ax, ay) in anchor_stairs
                          for dx in range(2) for dy in range(2)}

    # --- テナント帯の間引き階段（コア間隔が広い継ぎ目に階段のみのコアを足す） ---
    gap_stairs = []
    _band_rows = [n_tenant_rows[0]] + ([mall_min - 3] if mall_min >= 6 else [])
    _core_xs = sorted({cx for (cx, cy) in core_blocks})
    for _a, _b in zip(_core_xs, _core_xs[1:]):
        if _b - _a > 8:
            _mid = (_a + _b) // 2
            for _by in _band_rows:
                _block = {(_mid + dx, _by + dy) for dx in range(2) for dy in range(2)}
                if _block <= plate and not (_block & sv_cells) and \
                        all(abs(_mid - bx) > 3 or abs(_by - byy) > 3
                            for (bx, byy) in core_blocks + anchor_stairs + gap_stairs):
                    gap_stairs.append((_mid, _by))
    for gi, (gx, gy) in enumerate(gap_stairs):
        cid = f"core:G{gi}"
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{gx+1}", "xTo": f"X{gx+3}",
                               "yFrom": f"Y{gy+1}", "yTo": f"Y{gy+3}"}})
        x0, y0 = X[f"X{gx+1}"], Y[f"Y{gy+1}"]
        for suf, kind, fx, fy, w, d in (("stair", "階段", x0 + 200, y0 + 200, 3200, 8000),
                                        ("ps", "PS", x0 + 6100, y0 + 200, 1100, 2800)):
            s = {"id": f"shaft:G{gi}-{suf}", "coreId": cid, "kind": kind,
                 "levelRange": levels_all, "footprint": {"x": fx, "y": fy, "w": w, "d": d}}
            if suf == "stair":
                s["stair"] = {"riser": 180, "steps": 30, "going": 260}
            shafts.append(s)
            compartments.append({"id": f"fc:shaft-G{gi}-{suf}", "kind": "竪穴区画", "shafts": [s["id"]]})
    gap_stair_cells = {(gx + dx, gy + dy) for (gx, gy) in gap_stairs
                        for dx in range(2) for dy in range(2)}

    # --- 吹抜け（court、上階のモール帯） ---
    void_cells = set()
    if floors > 1:
        cf0, cf1 = ann["courtFracRange"]
        void_cells = {(i, j) for (i, j) in plate if j in mall_rows and cf0 <= frac(i, j) <= cf1}
        vx0 = min(i for (i, j) in void_cells); vy0 = min(j for (i, j) in void_cells)
        vx1 = max(i for (i, j) in void_cells); vy1 = max(j for (i, j) in void_cells)
        cores.append({"id": "core:AT", "levelRange": levels_all[1:],
                      "rect": {"xFrom": f"X{vx0+1}", "xTo": f"X{vx1+2}",
                               "yFrom": f"Y{vy0+1}", "yTo": f"Y{vy1+2}"}})
        shafts.append({"id": "shaft:AT-void", "coreId": "core:AT", "kind": "吹抜け",
                       "levelRange": levels_all[1:],
                       "footprint": {"x": X[f"X{vx0+1}"] + 200, "y": Y[f"Y{vy0+1}"] + 200,
                                     "w": X[f"X{vx1+2}"] - X[f"X{vx0+1}"] - 400,
                                     "d": Y[f"Y{vy1+2}"] - Y[f"Y{vy0+1}"] - 400}})
        compartments.append({"id": "fc:shaft-AT", "kind": "竪穴区画", "shafts": ["shaft:AT-void"]})

    rooms, walls, zones = [], [], []
    def split_ratio(a0, b0, w_, h_):
        wm_ = X[f"X{a0+w_+1}"] - X[f"X{a0+1}"]
        dm_ = Y[f"Y{b0+h_+1}"] - Y[f"Y{b0+1}"]
        if max(wm_, dm_) / min(wm_, dm_) <= 3 or (w_ == 1 and h_ == 1):
            return [(a0, b0, w_, h_)]
        if wm_ >= dm_ and w_ > 1:
            w1 = w_ // 2
            return split_ratio(a0, b0, w1, h_) + split_ratio(a0 + w1, b0, w_ - w1, h_)
        h1 = h_ // 2
        return split_ratio(a0, b0, w_, h1) + split_ratio(a0, b0 + h1, w_, h_ - h1)

    def split_area(a0, b0, w_, h_, limit=2800):
        area = (X[f"X{a0+w_+1}"] - X[f"X{a0+1}"]) * (Y[f"Y{b0+h_+1}"] - Y[f"Y{b0+1}"]) / 1e6
        if area <= limit or (w_ == 1 and h_ == 1):
            return [(a0, b0, w_, h_)]
        wm_ = X[f"X{a0+w_+1}"] - X[f"X{a0+1}"]
        dm_ = Y[f"Y{b0+h_+1}"] - Y[f"Y{b0+1}"]
        if wm_ >= dm_ and w_ > 1:
            w1 = w_ // 2
            return split_area(a0, b0, w1, h_, limit) + split_area(a0 + w1, b0, w_ - w1, h_, limit)
        h1 = h_ // 2
        return split_area(a0, b0, w_, h1, limit) + split_area(a0, b0 + h1, w_, h_ - h1, limit)

    level_anchor_free = {}  # 階別アンカーの無柱区画（L4構造推論へ渡す）
    big_room_names = {la["name"] for la in ann.get("levelAnchors", [])}
    for li in range(floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        fl = []
        assigned = {}  # (i,j) -> (use, name, source)
        def claim(cells, use, name, source):
            for c in cells:
                if c in plate and c not in assigned:
                    assigned[c] = (use, name, source)
        # L3: サービス帯（サービス面の端。svc_plus でモデル±X端を切替）
        if svc_plus:
            svc_cells = {(i, j) for (i, j) in plate if rows_span[j][1] == slab_east
                         and i >= slab_east - 2} - sv_cells
        else:
            svc_cells = {(i, j) for (i, j) in plate if rows_span[j][0] == slab_west
                         and i <= slab_west + 2} - sv_cells
        if li == 0:
            for c in svc_cells:
                j = c[1]
                nm = "ゴミ置場" if j <= 3 else "ポンプ室" if j <= 5 else \
                     "納品所・荷捌き" if j <= mall_max + 1 else "従業員通用口・バックヤード"
                assigned[c] = ("バックヤード", nm, "program")
        else:
            claim(svc_cells, "バックヤード", "バックヤード・倉庫", "program")
        claim(sv_cells, "コアホール", "サービスコア（業務用）", "program")
        # L2: 核店舗（主スラブ行のみ。短い端行では frac の位置がずれるため対象外。
        # 行ごとに2セル未満の細片もアンカーに含めない：段型の縁のスライス対策）
        _ac = {(i, j) for (i, j) in plate
               if j in _main_rows and in_anchor(i, j)} - set(assigned)
        from collections import defaultdict as _dd
        _byrow = _dd(list)
        for (i, j) in _ac:
            _byrow[j].append(i)
        anchor_cells = {(i, j) for j, xs in _byrow.items() if len(xs) >= 2 for i in xs}
        # L2: モール／吹抜け
        mall_cells = {(i, j) for (i, j) in plate if j in mall_rows} - set(assigned) - anchor_cells
        if li >= 1:
            claim(void_cells & mall_cells, "吹抜け", "吹抜け（サンコート）", "guide")
            mall_cells -= void_cells
        claim(mall_cells, "モール", "モール", "guide")
        # L2: 準核（アンカー占有域には入り込まない：優先順位 anchor > 準核・FC）
        # side は実方位のラベル（記録用）。行帯は rows（"north"=モールより+Y側／"south"=-Y側）で
        # 指定でき、無い場合は side から決める（NW→north、それ以外→south）。
        # 位置は fracTo（モデル-X端から）または fracFrom（モデル+X端から）で指定する
        for qa in ann.get("quasiAnchors", []):
            qrows = qa.get("rows") or ("north" if qa["side"] == "NW" else "south")
            if "fracFrom" in qa:
                qcells = {(i, j) for (i, j) in plate if frac(i, j) >= qa["fracFrom"]}
            else:
                qcells = {(i, j) for (i, j) in plate if frac(i, j) <= qa["fracTo"]}
            if qrows == "north":
                qcells = {(i, j) for (i, j) in qcells if j > mall_max}
            else:
                qcells = {(i, j) for (i, j) in qcells if j < mall_min}
            quse = qa.get("use") or ("テナント" if qrows == "north" else "大型店")
            claim(qcells - set(assigned) - anchor_cells, quse, qa["name"], "guide")
        # コア・WC
        claim(core_cells, "コアホール", "コアホール", "guide")
        claim(anchor_stair_cells, "コアホール", "コアホール（核店舗専用階段）", "guide")
        claim(gap_stair_cells, "コアホール", "コアホール（階段）", "guide")
        wc_cells = set()
        for (cx, cy) in core_blocks:
            cand = (cx + 2, cy)
            if cand in plate and cand not in assigned:
                wc_cells.add(cand)
        claim(wc_cells, "WC", "便所・サービス", "program")
        # L2: フードコート（対象階のみ。アンカー占有域には入り込まない）
        if (li + 1) in fc.get("levels", []):
            f0, f1 = fc["fracRange"]
            claim({(i, j) for (i, j) in plate if j in fc["seatRows"] and f0 <= frac(i, j) <= f1}
                  - set(assigned) - anchor_cells, "フードコート", "フードコート（客席）", "guide")
        # L2: 階別アンカー（その階だけの大区画。例：最上階のシネマ）
        for la in ann.get("levelAnchors", []):
            if (li + 1) not in la.get("levels", []):
                continue
            f0, f1 = la["fracRange"]
            cells = {(i, j) for (i, j) in plate if f0 <= frac(i, j) <= f1}
            if la.get("excludeMallRows", True):
                cells = {(i, j) for (i, j) in cells if j not in mall_rows}
            if la.get("rows") == "north":
                cells = {(i, j) for (i, j) in cells if j > mall_max}
            elif la.get("rows") == "south":
                cells = {(i, j) for (i, j) in cells if j < mall_min}
            got = {(i, j) for (i, j) in cells if (i, j) not in assigned and (i, j) not in anchor_cells}
            # 行ごとの frac は短い行で位置がずれるため、最大の連結成分だけを残す（飛び地の除去）
            if got:
                seen, comps = set(), []
                for c in got:
                    if c in seen:
                        continue
                    stack, comp = [c], set()
                    while stack:
                        p = stack.pop()
                        if p in got and p not in seen:
                            seen.add(p); comp.add(p)
                            stack += [(p[0] + 1, p[1]), (p[0] - 1, p[1]), (p[0], p[1] + 1), (p[0], p[1] - 1)]
                    comps.append(comp)
                got = max(comps, key=len)
            claim(got, la["use"], la["name"], "guide")
            if la.get("columnFree"):
                level_anchor_free.setdefault(la["name"], {"cells": set(), "levels": []})
                level_anchor_free[la["name"]]["cells"] |= got
                level_anchor_free[la["name"]]["levels"].append(lid)
        # L3: 防災センター（1F・南テナント帯）
        if li == 0:
            brow = mall_min - 1
            bcells = {(i, brow) for (i, j) in plate if j == brow and 0.31 <= frac(i, j) <= 0.36}
            claim(bcells - set(assigned), "防災センター", "防災センター", "program")
            # L3: 機械室・電気室（北バックヤード帯、水系と分離）
            plant = {(i, j) for (i, j) in plate if j in (mall_max + 3, mall_max + 4)
                     and 0.55 <= frac(i, j) <= 0.60}
            elec = {(i, j) for (i, j) in plate if j in (mall_max + 3, mall_max + 4)
                    and 0.63 <= frac(i, j) <= 0.68}
            claim(plant - set(assigned), "バックヤード", "機械室", "program")
            claim(elec - set(assigned), "バックヤード", "電気室", "program")
        # アンカーは占有として最後に確定（分解は下でまとめて）
        for c in anchor_cells:
            if c not in assigned:
                assigned[c] = ("物販", ann["anchorName"], "guide")
        # 残り：バンドフィル（推定）
        for (i, j) in sorted(plate):
            if (i, j) in assigned:
                continue
            if j > mall_max:
                use = "テナント" if j in n_tenant_rows else "バックヤード"
                nm = "テナント" if use == "テナント" else "バックヤード・サービス"
            elif j < mall_min:
                in_fc = (li + 1) in fc.get("levels", []) and j in fc["shopRows"] \
                    and fc["fracRange"][0] <= frac(i, j) <= fc["fracRange"][1]
                if in_fc:
                    use, nm = "飲食", "フードコート店舗"
                elif j <= mall_min - 3:
                    # モールから離れた南側の深い帯は、駐車場に面する大型店として埋める
                    use, nm = "大型店", "大型テナント"
                else:
                    use, nm = "テナント", "テナント"
            else:
                use, nm = "モール", "モール"
            assigned[(i, j)] = (use, nm, "inferred")
        # セル群→部屋（use,name,source ごとに矩形分解）
        groups = {}
        for cell, key in assigned.items():
            groups.setdefault(key, set()).add(cell)
        counters = {}
        def add_room(use, name, source, i0, j0, w, h):
            counters[name] = counters.get(name, 0) + 1
            n = counters[name]
            suf = f"{name}-{n}" if n > 1 else name
            mid = i0 + w / 2
            zid = f"{ln}-W" if mid < nx / 3 else f"{ln}-C" if mid < 2 * nx / 3 else f"{ln}-E"
            r = room(f"room:{ln}-{suf}", lid, name if n == 1 else f"{name}{n}", use,
                     i0, i0 + w, j0, j0 + h, zid if use != "モール" else None,
                     4800 if use in ("モール", "吹抜け", "物販") else (ceil_seed or 3600))
            r["source"] = source
            fl.append(r); rooms.append(r)
        for (use, name, source), cells in sorted(groups.items(), key=lambda kv: kv[0][1]):
            maxw = 8 if use in ("物販", "フードコート") else 10 if use == "モール" else \
                   6 if use == "バックヤード" else 3
            if name in big_room_names:
                rects = _decompose(cells, 12)  # 階別アンカー（シネマ等）は大きな一室として保つ
            elif use == "大型店":
                rects = _decompose_banded(cells, 8, 2)  # 深い帯でも縦ストリップにしない
            else:
                rects = _decompose(cells, maxw)
            for (i0, j0, w, h) in rects:
                if use in ("テナント", "飲食"):
                    for (a0, b0, w_, h_) in split_ratio(i0, j0, w, h):
                        add_room(use, name, source, a0, b0, w_, h_)
                elif use == "物販":
                    for (a0, b0, w_, h_) in split_area_grid(i0, j0, w, h, X, Y):
                        add_room(use, name, source, a0, b0, w_, h_)
                else:
                    add_room(use, name, source, i0, j0, w, h)
        # 工区
        for suf, b0, b1 in (("W", 0, nx // 3), ("C", nx // 3, 2 * nx // 3), ("E", 2 * nx // 3, nx)):
            ranges = []
            for j in range(ny):
                run = None
                for i in range(b0, b1 + 1):
                    inside = i < b1 and (i, j) in plate
                    if inside and run is None:
                        run = i
                    if not inside and run is not None:
                        ranges.append({"xFrom": f"X{run+1}", "xTo": f"X{i+1}",
                                       "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
                        run = None
            if ranges:
                zones.append({"id": f"{ln}-{suf}", "level": lid, "cellRanges": ranges})
        # 面積区画
        def room_area(r):
            c = r["cells"]
            return (X[c["xTo"]] - X[c["xFrom"]]) * (Y[c["yTo"]] - Y[c["yFrom"]]) / 1e6
        grp, cur, cur_area = [], [], 0.0
        for r in sorted(fl, key=lambda r: X[r["cells"]["xFrom"]]):
            a = room_area(r)
            if cur and cur_area + a > 2900:
                grp.append(cur); cur, cur_area = [], 0.0
            cur.append(r["id"]); cur_area += a
        if cur:
            grp.append(cur)
        for gi, g in enumerate(grp):
            compartments.append({"id": f"fc:{ln}-{gi}", "kind": "面積区画", "level": lid, "rooms": g})
        walls += build_walls(fl, lid, nx, ny, commercial_decide, f"S2-{ln}")
    b.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
              "zones": zones, "compartments": compartments})
    slabs = []
    for li in range(floors):
        lid = f"L{li+1}"
        ops = [s["id"] for s in shafts if lid in s["levelRange"]] if li > 0 else []
        slabs.append({"id": f"slab:{lid}", "level": lid,
                      "kind": "土間コンクリート" if li == 0 else "デッキ合成スラブ",
                      "cellRanges": conv["footprint"], "thickness": 150, "openings": ops,
                      **({"onGround": True} if li == 0 else {})})
    b["slabs"] = slabs
    _roof_use = spec_val("roofUse")
    b["roof"] = {"id": "roof:main", "topLevel": f"L{floors}",
                 "kind": "陸屋根（屋上駐車場）" if _roof_use == "駐車場" else "陸屋根（シート防水）",
                 "cellRanges": conv["footprint"], "parapetHeight": 600,
                 "note": ("屋上用途はシード仕様（駐車場）" if _roof_use == "駐車場"
                          else "屋根仕様はシード不明のため生成器既定（シート防水）")}
    b["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cellRanges": conv["footprint"], "depth": 1500}]
    total_w = X[f"X{nx+1}"]
    site_ann = ann.get("site", {})
    def site_val(k):
        v = site_ann.get(k, {})
        return v.get("value") if isinstance(v, dict) else v
    b["site"] = {"polygon": [[-15000, -12000], [380000, -12000], [380000, 140000], [-15000, 140000]],
                 "buildingPlacement": {"origin": [0, 0], "rotationDeg": round(conv.get("main_axis_deg", 0), 1)},
                 "roads": site_val("roads") or [],
                 "gates": [{"edge": g["edge"], "atMm": round(g["frac"] * total_w),
                            "name": g["name"], "width": 6000} for g in ann.get("gates", [])],
                 "neighbors": site_val("neighbors") or []}
    mall1 = next((r["id"] for r in rooms if r["level"] == "L1" and r["use"] == "モール"), None)
    if mall1:
        b["coverings"] = [{"id": "cov:mall-floor", "target": mall1, "part": "床", "name": "磁器質タイル"}]
    b["reinforcement"] = [{"id": "re:slab", "target": "slab:L2" if floors > 1 else "slab:L1",
                           "kind": "スラブ配筋", "spec": "D13@200 ダブル"},
                          {"id": "re:footing", "target": "foundation:each-column", "kind": "基礎配筋",
                           "spec": "主筋D19・あばら筋D13@150"}]
    # L4：構造推論（柱例外・耐震要素・基礎仮定・施工属性）
    free_zones = []
    if void_cells:
        free_zones.append({"name": "吹抜け（サンコート）", "levels": levels_all, "cells": void_cells,
                           "treatment": "大梁（吹抜け上部）",
                           "basis": "アトリウムは内部の柱を抜き、縁の柱と大梁で受ける【実務】"})
    for nm, info in level_anchor_free.items():
        free_zones.append({"name": nm, "levels": info["levels"], "cells": info["cells"],
                           "treatment": "トラス／大梁（無柱大空間）",
                           "basis": "大空間（シネマ等）は柱を抜き、大梁・トラスで受ける【実務】"})
    _fnd = spec_val("foundationType")
    attach_structure(b, system=structure_system, plate=plate, levels_all=levels_all, fh_list=fh,
                     core_cells_list=[sv_cells, core_cells],
                     free_zones=free_zones,
                     ground_prior=ann.get("groundPrior", "unknown"), use="商業",
                     system_basis=(f"シード指定：{spec['structureSystem']['basis']}" if sys_seed else None),
                     ground_override=({"foundation": _fnd, "basis": spec["foundationType"]["basis"]}
                                      if _fnd else None),
                     frame_method=spec_val("frameMethod"))
    # 前提の明示（assumptions）：このモデルの決定が「シードの事実／推論／生成器既定／未生成（不足）」の
    # どれで決まったかを、項目ごとに根拠とプロセス付きで記録する。推論すること自体は正で、
    # 事実と混ざらないことが要件（ユーザー指示 2026-11-10）
    def _asm(item, adopted, source, basis, process):
        return {"item": item, "adopted": adopted, "source": source, "basis": basis, "process": process}
    st = b["structure"]
    b["assumptions"] = [
        _asm("structureSystem", structure_system, "seed" if sys_seed else "inference",
             st["systemBasis"], "L4推論 §7.2 step1（用途×階数×スパン）" if not sys_seed else "シード指定"),
        _asm("frameMethod", spec_val("frameMethod") or "在来（仮定）",
             "seed" if spec_val("frameMethod") else "inference",
             spec.get("frameMethod", {}).get("basis", ""), "L4推論（在来を既定とする）"),
        _asm("foundationType", st["groundAssumption"]["foundation"], "seed" if _fnd else "inference",
             "／".join(st["groundAssumption"]["basis"]), "L4推論 §7.2 step7（地域prior）"),
        _asm("exteriorWall", "外壁（種別未特定）", "default",
             spec.get("exteriorWall", {}).get("basis", ""), "生成器既定（壁種別は外壁／間仕切のみ、仕様種別は持たない）"),
        _asm("roofUse", _roof_use or "未特定", "seed" if _roof_use else "default",
             spec.get("roofUse", {}).get("basis", ""), "シード仕様／生成器既定"),
        _asm("roofSpec", b["roof"]["kind"], "default",
             spec.get("roofSpec", {}).get("basis", ""), "生成器既定（roofUse=駐車場の場合のみ種別を切り替える）"),
        _asm("ceilingHeightMm", ceil_seed or "一般室3600／モール・物販4800（生成器既定）",
             "seed" if ceil_seed else "default",
             spec.get("ceilingHeightMm", {}).get("basis", ""), "シード仕様／生成器既定"),
        _asm("sprinkler", bool(b["building"].get("sprinklerFull")), "seed",
             spec.get("sprinkler", {}).get("basis", ""), "シード仕様（歩行距離の上限40mの前提にもなる）"),
        _asm("parking", spec_val("parking") or "未特定", "seed" if spec_val("parking") else "default",
             spec.get("parking", {}).get("basis", ""), "シード仕様（モデル内では seedSpec として保持）"),
        _asm("floorHeight", fh[0], "seed", ann.get("floorHeightBasis", "注釈値（原典未記録）"),
             "シード注釈（floors／floorHeight）"),
        _asm("siteNeighbors", "シード値あり" if site_val("neighbors") else "未シード（空）",
             "seed" if site_val("neighbors") else "gap",
             site_ann.get("neighbors", {}).get("basis", ""), "シード注釈 site.neighbors"),
        _asm("sitePolygon", "仮置き矩形（380m×140m）", "default",
             site_ann.get("polygon", {}).get("basis", "敷地形状は未取得"), "生成器既定（実敷地形状ではない）"),
        _asm("equipmentRuns", "未生成", "gap", "シード生成では EquipmentRun（設備横引きルート）を生成していない",
             "既知の不足（パラメトリック生成には1本のみ）"),
    ]
    # 特記仕様書1頁相当ブロックの各項目も前提として記録する（値あり＝seed／null＝gap「未収集」）
    for _blk in ("outline", "zoning", "systems"):
        for _k, _v in (b["building"].get(_blk) or {}).items():
            _val = _v.get("value") if isinstance(_v, dict) else _v
            b["assumptions"].append(_asm(
                f"{_blk}.{_k}", _val if _val is not None else "未収集",
                "seed" if _val is not None else "gap",
                _v.get("basis", "") if isinstance(_v, dict) else "",
                "特記仕様書1頁相当（シード段階で網羅する項目）"))
    fix_doors(b)
    return b


def fix_doors(b):
    """V8（出入口）の後処理修復：戸を持たない室に、境界壁へ片開き戸を足す。
    同一店舗の矩形分解で生じた内部フラグメント（周囲が自店フラグメントと窓だけ）が主対象。
    検証器の V8 と同じ判定（戸種別の開口が室の範囲と重なること）で不足を検出する。"""
    DOORS = {"片開き戸", "両開き戸", "引戸", "シャッター"}
    X = {a["name"]: a["offset"] for a in b["grid"]["axesX"]}
    Y = {a["name"]: a["offset"] for a in b["grid"]["axesY"]}

    def wspan(w):
        ln = w["line"]
        if ln["axis"].startswith("Y"):
            return X[ln["from"]], X[ln["to"]]
        return Y[ln["from"]], Y[ln["to"]]

    def boundary(r):
        c = r["cells"]
        xr = (X[c["xFrom"]], X[c["xTo"]])
        yr = (Y[c["yFrom"]], Y[c["yTo"]])
        out = []
        for w in b["walls"]:
            if w["level"] != r["level"]:
                continue
            ln = w["line"]
            s0, s1 = wspan(w)
            if ln["axis"].startswith("Y") and ln["axis"] in (c["yFrom"], c["yTo"]):
                if s0 < xr[1] and xr[0] < s1:
                    out.append((w, s0, s1, xr))
            elif not ln["axis"].startswith("Y") and ln["axis"] in (c["xFrom"], c["xTo"]):
                if s0 < yr[1] and yr[0] < s1:
                    out.append((w, s0, s1, yr))
        return out

    def has_door(r):
        for (w, s0, s1, rng) in boundary(r):
            for o in w["openings"]:
                if o["kind"] in DOORS:
                    o0 = s0 + o["offsetFromStart"]
                    if o0 < rng[1] and rng[0] < o0 + o["width"]:
                        return True
        return False

    # セル→室の対応（候補壁の「向こう側」が誰かで優先順位を付けるため）
    cell_room = {}
    for r0 in b["rooms"]:
        c0 = r0["cells"]
        for i in range(int(c0["xFrom"][1:]) - 1, int(c0["xTo"][1:]) - 1):
            for j in range(int(c0["yFrom"][1:]) - 1, int(c0["yTo"][1:]) - 1):
                cell_room[(r0["level"], i, j)] = r0

    Xn = [a["name"] for a in b["grid"]["axesX"]]
    Yn = [a["name"] for a in b["grid"]["axesY"]]

    def neighbor_score(r, w, s0, s1, rng):
        # 壁の向こう側のセルを1つ特定して採点：同名の室 > 共用部系 > 屋外 > 他室
        ln = w["line"]
        c = r["cells"]
        if ln["axis"].startswith("Y"):
            i = Xn.index(ln["from"])
            n = int(ln["axis"][1:])
            across = (i, n - 2) if ln["axis"] == c["yFrom"] else (i, n - 1)
        else:
            j = Yn.index(ln["from"])
            n = int(ln["axis"][1:])
            across = (n - 2, j) if ln["axis"] == c["xFrom"] else (n - 1, j)
        nb = cell_room.get((r["level"], across[0], across[1]))
        if nb is None:
            return 1
        if nb["name"] == r["name"]:
            return 3
        if nb["use"] in ("モール", "コアホール", "WC", "共用部", "吹抜け"):
            return 2
        return 0

    for r in b["rooms"]:
        if r["use"] in ("モール", "吹抜け") or has_door(r):
            continue
        bw = boundary(r)

        def try_place(w, s0, s1, rng):
            # 室の範囲と重なる区間について、既存開口の隙間に片開き戸900を置けるか
            lo, hi = max(s0, rng[0]), min(s1, rng[1])
            if hi - lo < 1100:
                return False
            occ = sorted((s0 + o["offsetFromStart"], s0 + o["offsetFromStart"] + o["width"])
                         for o in w["openings"])
            gaps, curp = [], lo
            for (a, b_) in occ:
                if a > curp:
                    gaps.append((curp, a))
                curp = max(curp, b_)
            if hi > curp:
                gaps.append((curp, hi))
            gaps = [(a, b_) for (a, b_) in gaps if b_ - a >= 1100]
            if not gaps:
                return False
            a, b_ = max(gaps, key=lambda g: g[1] - g[0])
            w["openings"].append({"id": f"op:{w['id']}-fix{len(w['openings'])+1}", "kind": "片開き戸",
                                  "offsetFromStart": (a + b_ - 900) // 2 - s0,
                                  "width": 900, "height": 2100, "sillHeight": 0})
            return True

        # 候補1：境界壁の空き区間に戸を足す（向こう側の素性が良い順）
        done = False
        cands = sorted(bw, key=lambda t: -neighbor_score(r, t[0], t[1], t[2], t[3]))
        for (w, s0, s1, rng) in cands:
            if try_place(w, s0, s1, rng):
                done = True
                break
        if done:
            continue
        # 候補2：室に面するサッシを縮めて空きを作り、戸を並べる
        for (w, s0, s1, rng) in bw:
            tgt = None
            for o in w["openings"]:
                o0 = s0 + o["offsetFromStart"]
                if o["kind"] == "サッシ" and o0 < rng[1] and rng[0] < o0 + o["width"] and o["width"] > 1800:
                    tgt = o
                    break
            if tgt is not None:
                _orig_w = tgt["width"]
                tgt["width"] = 1800
                if try_place(w, s0, s1, rng):
                    break
                tgt["width"] = _orig_w  # 置けなければ戻す
    return b


def mansion_decide(useA, useB, horiz, axis):
    pair = {useA, useB}
    if useA is None or useB is None:
        inner = useB if useA is None else useA
        if inner == "住戸":
            return ("外壁", ("サッシ", 3600), False)
        if inner == "エントランス":
            return ("外壁", ("両開き戸", 1800), False)
        if inner == "コア":
            return ("外壁", ("片開き戸", 1000), False)
        if inner == "共用廊下":
            return ("外壁", ("片開き戸", 1000), False)
        return ("外壁", None, False)
    if pair == {"住戸", "住戸"} or pair == {"住戸", "コア"}:
        return ("戸境", None, False)
    if pair == {"住戸", "共用廊下"}:
        return ("間仕切", ("片開き戸", 900), False)
    if pair == {"コア", "共用廊下"}:
        return ("間仕切", ("片開き戸", 1000), False)
    if pair == {"エントランス", "共用廊下"}:
        return ("間仕切", ("両開き戸", 1600), False)
    if pair in ({"管理室", "共用廊下"}, {"集会室", "共用廊下"}, {"防災センター", "共用廊下"}):
        return ("間仕切", ("片開き戸", 1000), False)
    if pair in ({"管理室", "エントランス"}, {"防災センター", "エントランス"}, {"防災センター", "管理室"}):
        return ("間仕切", ("片開き戸", 900), False)
    return ("間仕切", ("片開き戸", 900), False)


def fix_daylight(b):
    """住戸の採光（法28条：採光開口 ≧ 床面積の1/7、住戸単位の近似）を満たすよう、
    外壁サッシを拡幅する。生成時の decide は固定幅（3600）しか返せないため後処理で担保する。
    拡幅は住戸と重なる区間について両側マージン300まで。開口が複数ある壁には触らない。"""
    X = {a["name"]: a["offset"] for a in b["grid"]["axesX"]}
    Y = {a["name"]: a["offset"] for a in b["grid"]["axesY"]}
    for r in b["rooms"]:
        if r["use"] != "住戸":
            continue
        c = r["cells"]
        rx0, rx1 = X[c["xFrom"]], X[c["xTo"]]
        ry0, ry1 = Y[c["yFrom"]], Y[c["yTo"]]
        area = (rx1 - rx0) * (ry1 - ry0) / 1e6
        need = area / 7 * 1.02
        segs, cur = [], 0.0
        for w in b["walls"]:
            if w["level"] != r["level"] or w["kind"] != "外壁":
                continue
            ln = w["line"]
            if ln["axis"].startswith("Y"):
                if ln["axis"] not in (c["yFrom"], c["yTo"]):
                    continue
                ws = X[ln["from"]]
                lo, hi = max(ws, rx0), min(X[ln["to"]], rx1)
            else:
                if ln["axis"] not in (c["xFrom"], c["xTo"]):
                    continue
                ws = Y[ln["from"]]
                lo, hi = max(ws, ry0), min(Y[ln["to"]], ry1)
            if hi <= lo:
                continue
            for o in w["openings"]:
                if o["kind"] not in ("サッシ", "固定窓"):
                    continue
                o0 = ws + o["offsetFromStart"]
                ov = min(o0 + o["width"], hi) - max(o0, lo)
                if ov > 0:
                    segs.append((o, ws, lo, hi))
                    cur += ov * o["height"] / 1e6
        for (o, ws, lo, hi) in segs:
            if cur >= need:
                break
            cap_w = (hi - lo) - 600
            if cap_w <= o["width"]:
                continue
            o0 = ws + o["offsetFromStart"]
            old_ov = min(o0 + o["width"], hi) - max(o0, lo)
            new_w = min(cap_w, o["width"] + int((need - cur) * 1e6 / o["height"]) + 1)
            center = (max(o0, lo) + min(o0 + o["width"], hi)) / 2
            off = int(center - new_w / 2) - ws
            off = max(lo - ws + 300, min(off, hi - ws - 300 - new_w))
            o["offsetFromStart"], o["width"] = off, new_w
            n0 = ws + off
            cur += (min(n0 + new_w, hi) - max(n0, lo) - old_ov) * o["height"] / 1e6
    return b


def gen_seeded_mansion(conv, ann=None, bid="bldg:gen-seeded-mansion"):
    """シード版マンション：実在棟の外形（変換結果）に片廊下／中廊下型の住戸割当てを行う。
    浅いプレート（行数<=3）は片廊下型、深いプレート（行数>=4）は中廊下型とする。"""
    ann = ann or {}
    grid = conv["grid"]
    spans_x = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesX"]],
                                        [a["offset"] for a in grid["axesX"]][1:])]
    spans_y = [b_ - a_ for a_, b_ in zip([a["offset"] for a in grid["axesY"]],
                                        [a["offset"] for a in grid["axesY"]][1:])]
    nx, ny = len(spans_x), len(spans_y)
    X = {a["name"]: a["offset"] for a in grid["axesX"]}
    Y = {a["name"]: a["offset"] for a in grid["axesY"]}
    plate = set()
    for r in conv["footprint"]:
        for i in range(int(r["xFrom"][1:]) - 1, int(r["xTo"][1:]) - 1):
            for j in range(int(r["yFrom"][1:]) - 1, int(r["yTo"][1:]) - 1):
                plate.add((i, j))
    props = conv.get("source_properties", {})
    floors = ann.get("floors") or (int(props["building:levels"]) if props.get("building:levels") else 5)
    floors_src = ("annotation" if ann.get("floors") else
                  "OSM building:levels" if props.get("building:levels") else "生成器既定（5階仮定）")
    fh1 = ann.get("floorHeight", 3150)
    fh = [fh1] * floors
    levels_all = [f"L{i+1}" for i in range(floors)]
    total_h = fh1 * floors
    tall = total_h > 31000
    b, full = base_parts(bid, ann.get("buildingName", "生成：シードマンション"), "マンション", "RC",
                         spans_x, spans_y, fh)
    for li in range(floors):
        b["levels"][li]["footprint"] = conv["footprint"]
    # 廊下行（スパイン）：最もセルの多い行を背骨とする。雁行・段型でも廊下が建物を貫く
    from collections import Counter as _Ctr
    _rowcount = _Ctr(j for (i, j) in plate)
    _maxc = max(_rowcount.values())
    _cand_rows = [j for j in sorted(_rowcount) if _rowcount[j] >= 0.9 * _maxc]
    corr_row = _cand_rows[len(_cand_rows) // 2]
    # コア列：約24m間隔（歩行距離50mの担保）。コアは「廊下行を含む連続行ラン」のある列に置き、
    # 段型の端部ではプレート内にある行だけをコア室とする
    step = max(2, round(24000 / spans_x[0]))
    def col_run(i):
        if (i, corr_row) not in plate:
            return None
        lo = corr_row
        while (i, lo - 1) in plate:
            lo -= 1
        hi = corr_row
        while (i, hi + 1) in plate:
            hi += 1
        return (lo, hi + 1)
    cand = [i for i in range(nx) if (r := col_run(i)) and r[1] - r[0] >= 2]
    core_cols = []
    last = None
    for i in cand:
        if last is None or i - last >= step:
            core_cols.append(i)
            last = i
    if cand and core_cols and cand[-1] - core_cols[-1] >= 2 and cand[-1] not in core_cols:
        core_cols.append(cand[-1])
    if not core_cols:
        core_cols = [nx // 2]
    core_run = {i: (col_run(i) or (0, ny)) for i in core_cols}
    mid_core = core_cols[len(core_cols) // 2]
    # 住戸列（コア列以外）→ 南側ユニット（廊下より南の行群）／北側ユニット
    def unit_sides(i):
        # 列ごとに、廊下行に接する連続行ランを住戸とする（段型・雁行の列ごとの差を吸収）。
        # 住戸の奥行は外周側から最大12m：雁行の重なり等でランが深い列では、廊下との間の行を
        # 住戸に含めず共用部フィル（廊下の延長）に回す。奥行18m級の片面採光住戸は実在しない
        sides = []
        if (i, corr_row - 1) in plate:
            lo = corr_row - 1
            while (i, lo - 1) in plate:
                lo -= 1
            b = corr_row
            while b > lo + 1 and Y[f"Y{b+1}"] - Y[f"Y{lo+1}"] > 12000:
                b -= 1
            sides.append(("S", lo, b))
        if (i, corr_row + 1) in plate:
            hi = corr_row + 1
            while (i, hi + 1) in plate:
                hi += 1
            a = corr_row + 1
            while a < hi and Y[f"Y{hi+2}"] - Y[f"Y{a+1}"] > 12000:
                a += 1
            sides.append(("N", a, hi + 1))
        return sides
    units_per_floor = sum(len(unit_sides(i)) for i in range(nx) if i not in core_cols)
    total_units = units_per_floor * floors
    # コア・シャフト
    cores, shafts, compartments = [], [], []
    for ci, cc in enumerate(core_cols):
        cid = f"core:M{ci}"
        r0, r1 = core_run[cc]
        cores.append({"id": cid, "levelRange": levels_all,
                      "rect": {"xFrom": f"X{cc+1}", "xTo": f"X{cc+2}",
                               "yFrom": f"Y{r0+1}", "yTo": f"Y{r1+1}"}})
        x0 = X[f"X{cc+1}"]
        y0 = Y[f"Y{r0+1}"]
        shafts.append({"id": f"shaft:M{ci}-stair", "coreId": cid, "kind": "階段",
                       "levelRange": levels_all,
                       "footprint": {"x": x0 + 200, "y": y0 + 200, "w": 2600, "d": 5000},
                       "stair": {"riser": 175, "steps": fh1 // 175, "going": 240}})
        compartments.append({"id": f"fc:shaft-M{ci}-stair", "kind": "竪穴区画",
                             "shafts": [f"shaft:M{ci}-stair"]})
        if floors >= 6 or cc == mid_core:
            ev = {"id": f"shaft:M{ci}-ev", "coreId": cid, "kind": "EV", "levelRange": levels_all,
                  "footprint": {"x": x0 + 3000, "y": y0 + 200, "w": 2300, "d": 2300}}
            if tall and cc == mid_core:
                ev["emergency"] = True
            shafts.append(ev)
            compartments.append({"id": f"fc:shaft-M{ci}-ev", "kind": "竪穴区画",
                                 "shafts": [f"shaft:M{ci}-ev"]})
    # 1Fの共用部（入口に近い南側ユニットを置換）
    specials = {}
    _south = [i for i in range(nx) if i not in core_cols and unit_sides(i)
              and unit_sides(i)[0][0] == "S"]
    _south.sort(key=lambda i: abs(i - mid_core))
    # 割当順は「小さい棟でも最低限そろう」順：入口まわり→ゴミ→集会/防災→設備
    _plan = [("ENT", "エントランス", "エントランス"), ("MGR", "管理室", "管理室"),
             ("GOMI", "ゴミ保管庫", "ゴミ保管庫")]
    if total_units >= 40:
        _plan.append(("MEET", "集会室", "集会室"))
    if tall:
        _plan.append(("BOUSAI", "防災センター", "防災センター"))
    # 試験準拠の設備セット（令和3年 設計製図試験「集合住宅」要求室表。§2.9／INTERIOR §11）
    _plan += [("ELEC", "電気室", "電気室"), ("TANK", "受水槽室", "受水槽室"),
              ("PUMP", "消火ポンプ室", "消火ポンプ室")]
    for (suf, nm, use), i in zip(_plan, _south):
        specials[(i, "S")] = (suf, nm, use)
    # 南側の列が足りなければ、残りを北側の1F住戸列へ（中廊下型の深いプレート用）
    _placed = min(len(_plan), len(_south))
    if _placed < len(_plan):
        _north = [i for i in range(nx) if i not in core_cols and unit_sides(i)
                  and any(s == "N" for (s, _a, _b) in unit_sides(i))]
        _north.sort(key=lambda i: abs(i - mid_core))
        for (suf, nm, use), i in zip(_plan[_placed:], _north):
            if (i, "N") not in specials and (i, "S") not in specials:
                specials[(i, "N")] = (suf, nm, use)
    # 住戸PS（縦連続の単一オブジェクト。1Fが共用部になる位置は2Fから）
    ps_ids = []
    for i in range(nx):
        if i in core_cols:
            continue
        for (side, j0, j1) in unit_sides(i):
            cid = f"core:U{i+1}{side}"
            rng = levels_all[1:] if (i, side) in specials else levels_all
            cores.append({"id": cid, "levelRange": rng,
                          "rect": {"xFrom": f"X{i+1}", "xTo": f"X{i+2}",
                                   "yFrom": f"Y{j0+1}", "yTo": f"Y{j1+1}"}})
            sid = f"shaft:PS-U{i+1}{side}"
            py = Y[f"Y{j1+1}"] - 1900 if side == "S" else Y[f"Y{j0+1}"] + 200
            shafts.append({"id": sid, "coreId": cid, "kind": "PS", "levelRange": rng,
                           "footprint": {"x": X[f"X{i+2}"] - 1100, "y": py, "w": 900, "d": 1700}})
            ps_ids.append(sid)
    rooms, walls, zones = [], [], []
    unit_no = []
    for li in range(floors):
        lid, ln = f"L{li+1}", f"{li+1}F"
        fl = []
        def R(suf, name, use, xi0, xi1, yi0, yi1, zone=True, ceil=2700):
            zid = f"{ln}-W" if xi0 < nx // 3 else f"{ln}-C" if xi0 < 2 * nx // 3 else f"{ln}-E"
            r = room(f"room:{ln}-{suf}", lid, name, use, xi0, xi1, yi0, yi1,
                     zid if zone else None, ceil)
            r["source"] = "program" if use != "住戸" else "inferred"
            fl.append(r)
            rooms.append(r)
            return r
        seq = 0
        for i in range(nx):
            if i in core_cols:
                R(f"CORE{i+1}", "階段室・EVホール", "コア", i, i + 1, core_run[i][0], core_run[i][1])
                continue
            for (side, j0, j1) in unit_sides(i):
                if li == 0 and (i, side) in specials:
                    suf, nm, use = specials[(i, side)]
                    R(suf, nm, use, i, i + 1, j0, j1)
                    continue
                seq += 1
                R(f"U{seq}", f"住戸{seq}", "住戸", i, i + 1, j0, j1)
                unit_no.append((li, i, side, seq))
        # 廊下（コア列を除く全列）
        run = None
        for i in range(nx + 1):
            on = i < nx and i not in core_cols and (i, corr_row) in plate
            if on and run is None:
                run = i
            if not on and run is not None:
                R(f"CORR{run}", "共用廊下", "共用廊下", run, i, corr_row, corr_row + 1, zone=False)
                run = None
        # 残余セル（段型の端部など、住戸として割れなかったセル）を共用部で埋める
        covered = set()
        for r in fl:
            cc = r["cells"]
            for ii in range(int(cc["xFrom"][1:]) - 1, int(cc["xTo"][1:]) - 1):
                for jj in range(int(cc["yFrom"][1:]) - 1, int(cc["yTo"][1:]) - 1):
                    covered.add((ii, jj))
        leftover = plate - covered
        for ki, (i0, j0, w, h) in enumerate(_decompose(leftover, 6)):
            R(f"FILL{ki}", "共用部", "共用廊下", i0, i0 + w, j0, j0 + h, zone=False)
        walls += build_walls(fl, lid, nx, ny, mansion_decide, f"SM-{ln}")
        for suf, b0, b1 in (("W", 0, nx // 3), ("C", nx // 3, 2 * nx // 3), ("E", 2 * nx // 3, nx)):
            ranges = []
            for j in range(ny):
                run = None
                for i in range(b0, b1 + 1):
                    inside = i < b1 and (i, j) in plate
                    if inside and run is None:
                        run = i
                    if not inside and run is not None:
                        ranges.append({"xFrom": f"X{run+1}", "xTo": f"X{i+1}",
                                       "yFrom": f"Y{j+1}", "yTo": f"Y{j+2}"})
                        run = None
            if ranges:
                zones.append({"id": f"{ln}-{suf}", "level": lid, "cellRanges": ranges})
        compartments.append({"id": f"fc:{ln}", "kind": "面積区画", "level": lid,
                             "rooms": [r["id"] for r in fl]})
    if ps_ids:
        compartments.append({"id": "fc:shaft-PS", "kind": "竪穴区画", "shafts": ps_ids})
    b.update({"cores": cores, "shafts": shafts, "rooms": rooms, "walls": walls,
              "zones": zones, "compartments": compartments})
    slabs = []
    for li in range(floors):
        lid = f"L{li+1}"
        ops = [s["id"] for s in shafts if lid in s["levelRange"]] if li > 0 else []
        slabs.append({"id": f"slab:{lid}", "level": lid,
                      "kind": "土間コンクリート" if li == 0 else "RCスラブ",
                      "cellRanges": conv["footprint"], "thickness": 200, "openings": ops,
                      **({"onGround": True} if li == 0 else {})})
    b["slabs"] = slabs
    b["roof"] = {"id": "roof:main", "topLevel": f"L{floors}", "kind": "陸屋根（シート防水）",
                 "cellRanges": conv["footprint"], "parapetHeight": 600}
    b["earthworks"] = [{"id": "ew:main", "kind": "根切り", "cellRanges": conv["footprint"], "depth": 1500}]
    total_w = X[f"X{nx+1}"]
    b["site"] = {"polygon": [[-12000, -10000], [total_w + 12000, -10000],
                             [total_w + 12000, 30000], [-12000, 30000]],
                 "buildingPlacement": {"origin": [0, 0], "rotationDeg": round(conv.get("main_axis_deg", 0), 1)},
                 "roads": [{"edge": "south", "name": "前面道路", "width": 6000}],
                 "gates": [{"edge": "south", "name": "敷地出入口", "atMm": total_w // 2, "width": 4000}],
                 "neighbors": [{"edge": "north", "type": "住宅"}, {"edge": "south", "type": "道路"}]}
    b["genericElements"] = [
        {"id": f"ge:balcony-{li+1}F-{seq}", "name": "バルコニー",
         "attachTo": f"room:{li+1}F-U{seq}", "note": "奥行1800・手すり1100・隔板あり"}
        for (li, i, side, seq) in unit_no]
    b["reinforcement"] = [{"id": "re:slab", "target": "slab:L2" if floors > 1 else "slab:L1",
                           "kind": "スラブ配筋", "spec": "D13@200 ダブル"},
                          {"id": "re:footing", "target": "foundation:each-column", "kind": "基礎配筋",
                           "spec": "主筋D22・あばら筋D13@150"}]
    system = "壁式RC" if floors <= 5 else "RC"
    attach_structure(b, system=system, plate=plate, levels_all=levels_all, fh_list=fh,
                     core_cells_list=[{(cc, core_run[cc][0])} for cc in core_cols], use="マンション")
    # 前提の明示（seeded2 と同形式）：階数・構造・住戸割当ての出所をモデルに残す
    b["assumptions"] = [
        {"item": "floors", "adopted": floors,
         "source": "seed" if floors_src != "生成器既定（5階仮定）" else "default",
         "basis": f"階数の出所：{floors_src}", "process": "シード変換／生成器既定"},
        {"item": "structureSystem", "adopted": system, "source": "inference",
         "basis": b["structure"]["systemBasis"], "process": "L4推論 §7.2 step1（階数帯：〜5F=壁式RC／6F〜=RCラーメン）"},
        {"item": "unitLayout", "adopted": "生成器の型（廊下スパイン＋列ごとの住戸ラン）", "source": "default",
         "basis": "住戸タイプ配分（2LDK/3LDK等）はシードに無い", "process": "生成器の型（USE_RULES §2）"},
        {"item": "floorHeight", "adopted": fh1, "source": "default" if not ann.get("floorHeight") else "seed",
         "basis": "注釈指定" if ann.get("floorHeight") else "生成器既定3150mm", "process": "シード注釈／生成器既定"},
        {"item": "siteNeighbors", "adopted": "生成器の仮置き（北=住宅／南=道路）", "source": "default",
         "basis": "実敷地の周辺・接道は未シード", "process": "生成器既定（実情報ではない）"},
        {"item": "roomProgram", "adopted": "1F共用・管理・設備は試験準拠セット（エントランス／管理室／集会室／防災センター／ゴミ保管庫／電気室／受水槽室／消火ポンプ室）",
         "source": "inference",
         "basis": "令和3年 設計製図試験「集合住宅」の要求室表（公式）＋USE_RULES §2.6/§2.9。試験は25戸級のため、存在と配置の型のみ準拠し面積はセル粒度に従う",
         "process": "プログラム準拠（INTERIOR_MODEL_V2 §11）"},
        {"item": "unitTypeMix", "adopted": "生成器の型（住戸タイプ配分なし）", "source": "gap",
         "basis": "試験の住戸面積の階段（賃貸：1K約25／1LDK約50／2LDK約75㎡）は未適用。住戸面積はセル割当で決まる",
         "process": "既知の不足（§2.9）"},
        {"item": "bicycleParking", "adopted": "未生成", "source": "gap",
         "basis": "試験は屋内25台（25戸）。大規模では屋外・別棟が普通のため室としては生成していない",
         "process": "既知の不足（§2.9）"},
    ]
    fix_daylight(b)
    return b


def annotate_cores_and_openings(b):
    """コアの内容物と、壁開口の役割（入口／コア／荷捌き）を付ける後処理（全生成器共通）。

    本編3Dが階段コアと出入口を描くために使う（2026-11-10、メイン側依頼）。
    - Core: shafts（内包するシャフトID）／hasStair／stairLevels（階段のある階）／hasElevator
    - Wall.openings: role（"entrance"＝建物出入口、"core"＝コアに面する出入口、"loading"＝荷捌き用）
      と、role="core" のとき servesCore（コアID）。判定できない開口には付けない（＝普通の戸・窓）。
    entrance の判定：外壁の戸のうち、内側に隣接する室が共用動線（モール／コアホール／共用廊下／
    エントランス等）のもの。外壁の戸でも店舗に直接面するものは shopfront として付けない。
    """
    shafts_by_core = {}
    for s in b.get("shafts", []):
        if s.get("coreId"):
            shafts_by_core.setdefault(s["coreId"], []).append(s)
    for c in b.get("cores", []):
        ss = shafts_by_core.get(c["id"], [])
        c["shafts"] = [s["id"] for s in ss]
        stairs = [s for s in ss if s["kind"] == "階段"]
        c["hasStair"] = bool(stairs)
        lv = []
        for s in stairs:
            for l in s.get("levelRange", []):
                if l not in lv:
                    lv.append(l)
        c["stairLevels"] = sorted(lv, key=lambda l: int(l[1:]))
        c["hasElevator"] = any(s["kind"] == "EV" for s in ss)
    # セル→室マップ（階ごと）と、コアのセル集合
    xi = {a["name"]: i for i, a in enumerate(b["grid"]["axesX"])}
    yi = {a["name"]: i for i, a in enumerate(b["grid"]["axesY"])}
    xoff = [a["offset"] for a in b["grid"]["axesX"]]
    yoff = [a["offset"] for a in b["grid"]["axesY"]]

    def cell_set(ranges):
        out = set()
        for r in ranges if isinstance(ranges, list) else [ranges]:
            for i in range(xi[r["xFrom"]], xi[r["xTo"]]):
                for j in range(yi[r["yFrom"]], yi[r["yTo"]]):
                    out.add((i, j))
        return out

    room_at = {}
    for r in b.get("rooms", []):
        for cell in cell_set(r["cells"]):
            room_at.setdefault(r["level"], {})[cell] = r
    core_cells = {c["id"]: cell_set(c["rect"]) for c in b.get("cores", [])}
    core_by_id = {c["id"]: c for c in b.get("cores", [])}
    CIRC_USES = {"モール", "コアホール", "共用廊下", "共用部", "階段室・EVホール"}
    import bisect as _bs
    for w in b.get("walls", []):
        line = w.get("line") or {}
        if "from" not in line or "to" not in line:
            continue
        lvl = w["level"]
        for o in w.get("openings", []):
            mid = o["offsetFromStart"] + o["width"] // 2
            if line["axis"].startswith("Y"):
                j_line = yi[line["axis"]]
                pos = xoff[xi[line["from"]]] + mid
                i = _bs.bisect_right(xoff, pos) - 1
                adj = [room_at.get(lvl, {}).get((i, j_line - 1)),
                       room_at.get(lvl, {}).get((i, j_line))]
                adj_cells = [(i, j_line - 1), (i, j_line)]
            else:
                i_line = xi[line["axis"]]
                pos = yoff[yi[line["from"]]] + mid
                j = _bs.bisect_right(yoff, pos) - 1
                adj = [room_at.get(lvl, {}).get((i_line - 1, j)),
                       room_at.get(lvl, {}).get((i_line, j))]
                adj_cells = [(i_line - 1, j), (i_line, j)]
            adj = [r for r in adj if r]
            # コアに面する出入口（隣接室がコアに属する室＝コアホール等で、そのセルがコア矩形の中）
            served = None
            for cell in adj_cells:
                r = room_at.get(lvl, {}).get(cell)
                if r is None:
                    continue
                for cid, ccells in core_cells.items():
                    if lvl not in core_by_id[cid].get("levelRange", []):
                        continue
                    if cell in ccells and (r["use"] in ("コアホール", "階段室・EVホール")
                                           or cell_set(r["cells"]) <= ccells):
                        served = cid
                        break
                if served:
                    break
            if served:
                o["role"] = "core"
                o["servesCore"] = served
            elif w["kind"] == "外壁" and o["kind"] in ("片開き戸", "両開き戸"):
                if any(r["use"] in CIRC_USES or "エントランス" in r["name"] for r in adj):
                    o["role"] = "entrance"
                elif any(r["use"] in ("大型店", "物販", "テナント", "飲食") for r in adj):
                    o["role"] = "shopfront"
            elif w["kind"] == "外壁" and o["kind"] == "シャッター":
                if any("荷捌き" in r["name"] or "納品所" in r["name"] for r in adj):
                    o["role"] = "loading"
    return b


if __name__ == "__main__":
    use = sys.argv[1] if len(sys.argv) > 1 else "commercial"
    out = sys.argv[2] if len(sys.argv) > 2 else f"generated_{use}.json"
    if use == "game":
        doc = gen_game_mall()
    elif use == "commercial":
        shape = sys.argv[3] if len(sys.argv) > 3 else "rectangle"
        doc = gen_commercial(shape=shape)
    elif use == "seeded":
        # 使い方: seeded <out.json> <conversion.json>（footprint_to_plate.py の出力）
        doc = gen_seeded(sys.argv[3])
    elif use == "seeded2":
        # 使い方: seeded2 <out.json> <conversion.json> <annotation.json>
        doc = gen_seeded2(sys.argv[3], sys.argv[4])
    elif use == "mansion":
        doc = gen_mansion()
    elif use == "seeded_mansion":
        # 使い方: seeded_mansion <out.json> <conversion.json> [annotation.json]
        _ann = json.load(open(sys.argv[4], encoding="utf-8")) if len(sys.argv) > 4 else None
        doc = gen_seeded_mansion(json.load(open(sys.argv[3], encoding="utf-8")), _ann)
    elif use == "seeded_station":
        # 使い方: seeded_station <out.json> <conversion.json> [annotation.json] [相対式|島式]
        _ann = json.load(open(sys.argv[4], encoding="utf-8")) if len(sys.argv) > 4 and sys.argv[4].endswith(".json") else None
        _form = sys.argv[5] if len(sys.argv) > 5 else "相対式"
        doc = gen_seeded_station(json.load(open(sys.argv[3], encoding="utf-8")), _ann, _form)
    elif use == "station":
        # 使い方: station <out.json> [相対式|島式] [n_spans]
        doc = gen_station(sys.argv[3] if len(sys.argv) > 3 else "相対式",
                          int(sys.argv[4]) if len(sys.argv) > 4 else 12)
    else:
        sys.exit(f"未対応の用途: {use}")
    for _b in doc.get("buildings", [doc]):
        annotate_cores_and_openings(_b)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    if "buildings" in doc:
        print(f"wrote {out}: buildings={len(doc['buildings'])} " +
              " ".join(f"{b['building']['id']}:rooms={len(b['rooms'])}" for b in doc["buildings"]))
    else:
        print(f"wrote {out}: rooms={len(doc['rooms'])} walls={len(doc['walls'])} shafts={len(doc['shafts'])}")
