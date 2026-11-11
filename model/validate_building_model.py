#!/usr/bin/env python3
"""建物モデルの検証器 v0.4 — BUILDING_MODEL_SCHEMA.md の不変条件
V1,V2,V5,V6,V7,V8,V9,V11〜V21 と、用途別追加検証 V-U の即判定分を検査する。
プレート（Level.footprint のセル集合）対応：非矩形プランも検証できる。
使い方: python3 validate_building_model.py [building_model.json]
複合ファイル（最上位に buildings を持つ形）にも対応する。
生成器の受け入れ条件：このスクリプトの全チェックが PASS すること。"""
import json, sys
from collections import Counter

fails = []

def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — " + detail) if detail else ""))
    if not ok:
        fails.append(name)

def area_of(r, X, Y):
    c = r["cells"]
    return (X[c["xTo"]] - X[c["xFrom"]]) * (Y[c["yTo"]] - Y[c["yFrom"]]) / 1e6

def validate_building(m, tag="", extra_ids=()):
    pre = f"[{tag}] " if tag else ""
    X = {a["name"]: a["offset"] for a in m["grid"]["axesX"]}
    Y = {a["name"]: a["offset"] for a in m["grid"]["axesY"]}
    Xn = [a["name"] for a in m["grid"]["axesX"]]
    Yn = [a["name"] for a in m["grid"]["axesY"]]
    levels = {l["id"]: l for l in m["levels"]}
    shafts_by_id = {s["id"]: s for s in m.get("shafts", [])}
    cores_by_id = {c["id"]: c for c in m.get("cores", [])}

    # プレート（階ごとのセル集合）と範囲ユーティリティ（v0.4）
    def ranges_of(o):
        if o.get("cellRanges"):
            return o["cellRanges"]
        r = o.get("cells") or o.get("cellRange")
        return [r] if r else []
    def cell_set(ranges):
        s = set()
        for r in ranges:
            for i in range(Xn.index(r["xFrom"]), Xn.index(r["xTo"])):
                for j in range(Yn.index(r["yFrom"]), Yn.index(r["yTo"])):
                    s.add((i, j))
        return s
    all_cells = {(i, j) for i in range(len(Xn) - 1) for j in range(len(Yn) - 1)}
    plate = {lid: (cell_set(lv["footprint"]) if lv.get("footprint") else set(all_cells))
             for lid, lv in levels.items()}
    cell_area = {(i, j): (X[Xn[i + 1]] - X[Xn[i]]) * (Y[Yn[j + 1]] - Y[Yn[j]]) / 1e6
                 for i in range(len(Xn) - 1) for j in range(len(Yn) - 1)}

    # V1 寸法チェーン
    for axes, label in ((m["grid"]["axesX"], "X"), (m["grid"]["axesY"], "Y")):
        offs = [a["offset"] for a in axes]
        spans = [b - a for a, b in zip(offs, offs[1:])]
        check(f"{pre}V1 寸法チェーン({label})", offs[0] == 0 and sum(spans) == offs[-1] and all(s > 0 for s in spans),
              f"spans={spans} total={offs[-1]}")

    # V2 シャフト縦連続（自 Core の矩形内に収まる）
    for s in m.get("shafts", []):
        core = cores_by_id.get(s.get("coreId"))
        if core is None:
            check(f"{pre}V2 シャフト縦連続 {s['id']}", False, "coreId が解決できない")
            continue
        cr = (X[core["rect"]["xFrom"]], X[core["rect"]["xTo"]], Y[core["rect"]["yFrom"]], Y[core["rect"]["yTo"]])
        f = s["footprint"]
        inside = cr[0] <= f["x"] and f["x"] + f["w"] <= cr[1] and cr[2] <= f["y"] and f["y"] + f["d"] <= cr[3]
        rng_ok = all(l in levels for l in s["levelRange"]) and len(s["levelRange"]) >= 1
        check(f"{pre}V2 シャフト縦連続 {s['id']}", inside and rng_ok,
              f"footprint=({f['x']},{f['y']},{f['w']}x{f['d']}) levels={s['levelRange']}")

    def wall_span(w):
        ln = w["line"]
        if ln["axis"].startswith("Y"):
            return X[ln["from"]], X[ln["to"]] - X[ln["from"]]
        return Y[ln["from"]], Y[ln["to"]] - Y[ln["from"]]

    # V5 開口の収容
    for w in m["walls"]:
        start, length = wall_span(w)
        ivs = sorted((o["offsetFromStart"], o["offsetFromStart"] + o["width"]) for o in w["openings"])
        ok = all(a >= 0 and b <= length for a, b in ivs) and all(ivs[i][1] <= ivs[i + 1][0] for i in range(len(ivs) - 1))
        check(f"{pre}V5 開口収容 {w['id']}", ok, f"len={length} openings={len(ivs)}")

    # V6 面積整合（プレート面積に対して）
    for lid in levels:
        tot = sum(area_of(r, X, Y) for r in m["rooms"] if r["level"] == lid)
        plate_area = sum(cell_area[c] for c in plate[lid])
        check(f"{pre}V6 面積整合 {lid}", abs(tot - plate_area) / plate_area <= 0.01,
              f"rooms={tot:.1f}㎡ plate={plate_area:.1f}㎡")

    # V7 工区分割（プレートの全セルを重なりなく覆う）
    for lid in levels:
        cnt = Counter()
        for z in (z for z in m["zones"] if z["level"] == lid):
            for c in cell_set(ranges_of(z)):
                cnt[c] += 1
        check(f"{pre}V7 工区分割 {lid}", set(cnt) == plate[lid] and all(v == 1 for v in cnt.values()),
              f"cells covered={len(cnt)}/{len(plate[lid])}")

    # V21 形状整合（全 Room がプレート内）
    for lid in levels:
        bad = [r["id"] for r in m["rooms"] if r["level"] == lid and not cell_set([r["cells"]]) <= plate[lid]]
        check(f"{pre}V21 形状整合 {lid}", not bad, f"outside={bad}")

    # V8 出入口
    DOORS = {"片開き戸", "両開き戸", "引戸", "シャッター"}
    EXEMPT = {"モール", "吹抜け"}
    def room_has_door(r):
        c = r["cells"]
        xr = (X[c["xFrom"]], X[c["xTo"]]); yr = (Y[c["yFrom"]], Y[c["yTo"]])
        for w in m["walls"]:
            if w["level"] != r["level"]:
                continue
            ln = w["line"]; start, length = wall_span(w)
            horiz = ln["axis"].startswith("Y")
            if horiz and ln["axis"] in (c["yFrom"], c["yTo"]):
                if not (X[ln["from"]] < xr[1] and xr[0] < X[ln["to"]]):
                    continue
                rng = xr
            elif not horiz and ln["axis"] in (c["xFrom"], c["xTo"]):
                if not (Y[ln["from"]] < yr[1] and yr[0] < Y[ln["to"]]):
                    continue
                rng = yr
            else:
                continue
            for o in w["openings"]:
                if o["kind"] in DOORS:
                    a, b = start + o["offsetFromStart"], start + o["offsetFromStart"] + o["width"]
                    if a < rng[1] and rng[0] < b:
                        return True
        return False

    for r in m["rooms"]:
        if r["use"] in EXEMPT:
            continue
        check(f"{pre}V8 出入口 {r['id']}", room_has_door(r), r["name"])

    # V9 階段整合
    for s in m.get("shafts", []):
        if s["kind"] != "階段":
            continue
        st = s["stair"]
        fh = levels[s["levelRange"][0]]["floorHeight"]
        check(f"{pre}V9 階段整合 {s['id']}", st["riser"] * st["steps"] == fh and st["riser"] <= 220 and st["going"] >= 210,
              f"{st['riser']}x{st['steps']}={st['riser']*st['steps']} floorHeight={fh} going={st['going']}")

    # V11 基礎（柱は構造軸の交点のみ：SPAN_STANDARD の構造軸/補助軸分離に対応。
    # structuralAxes が無いモデルでは全交点が構造軸とみなす）
    fnd = m.get("foundations", {})
    sax11 = m["grid"].get("structuralAxesX") or Xn
    say11 = m["grid"].get("structuralAxesY") or Yn
    exc11 = {}
    for e in m["grid"].get("columnExceptions", []):
        exc11[e["at"]] = set(e.get("levels", []))
    first_lid11 = m["levels"][0]["id"]
    n_cols = 0
    for xn_ in sax11:
        for yn_ in say11:
            pi, pj = Xn.index(xn_), Yn.index(yn_)
            adj = [(pi - 1, pj - 1), (pi, pj - 1), (pi - 1, pj), (pi, pj)]
            if not any(c in plate[first_lid11] for c in adj):
                continue
            if first_lid11 in exc11.get(f"{xn_}-{yn_}", ()):
                continue
            n_cols += 1
    check(f"{pre}V11 基礎の対応", fnd.get("footings", {}).get("rule") in ("each-column", "each-structural-column") and n_cols > 0,
          f"columns(1F・構造軸交点)={n_cols} footings=各柱で同数")
    ew_cells = set()
    for e in m.get("earthworks", []):
        ew_cells |= cell_set(ranges_of(e))
    first_lid = m["levels"][0]["id"]
    check(f"{pre}V11 地業の範囲", plate[first_lid] <= ew_cells, "根切りが1階プレートを覆う")

    # V12 スラブ完全性
    for lid in levels:
        sl = [s for s in m.get("slabs", []) if s["level"] == lid]
        ok = len(sl) == 1 and cell_set(ranges_of(sl[0])) == plate[lid] and all(
            o in shafts_by_id and lid in shafts_by_id[o]["levelRange"] for o in sl[0]["openings"])
        check(f"{pre}V12 スラブ完全性 {lid}", ok, f"openings={sl[0]['openings'] if sl else 'なし'}")

    # V13 屋根
    roof = m.get("roof", {})
    top = m["levels"][-1]["id"]
    check(f"{pre}V13 屋根", roof.get("topLevel") == top and cell_set(ranges_of(roof)) == plate[top],
          f"topLevel={roof.get('topLevel')} kind={roof.get('kind')}")

    # V14 防火区画
    for lid in levels:
        want = sorted(r["id"] for r in m["rooms"] if r["level"] == lid)
        got = [rid for c in m.get("compartments", []) if c["kind"] == "面積区画" and c.get("level") == lid for rid in c["rooms"]]
        check(f"{pre}V14 面積区画 {lid}", sorted(got) == want and len(got) == len(set(got)),
              f"rooms={len(got)}/{len(want)}")
    shaft_cov = Counter(sid for c in m.get("compartments", []) if c["kind"] == "竪穴区画" for sid in c.get("shafts", []))
    check(f"{pre}V14 竪穴区画", all(shaft_cov[s["id"]] == 1 for s in m.get("shafts", [])),
          f"shafts={dict(shaft_cov)}")

    # V15 カーテンウォール排他
    for cw in m.get("curtainWalls", []):
        ln = cw["line"]
        cs, cl = (Y[ln["from"]], Y[ln["to"]] - Y[ln["from"]]) if ln["axis"].startswith("X") else (X[ln["from"]], X[ln["to"]] - X[ln["from"]])
        conflict = []
        for w in m["walls"]:
            if w["level"] == cw["level"] and w["line"]["axis"] == ln["axis"]:
                ws, wl = wall_span(w)
                if ws < cs + cl and cs < ws + wl:
                    conflict.append(w["id"])
        check(f"{pre}V15 CW排他 {cw['id']}", not conflict, f"conflicts={conflict}")

    # V16 付随要素の参照整合
    registry = ({w["id"] for w in m["walls"]} | {r["id"] for r in m["rooms"]} | {s["id"] for s in m.get("slabs", [])}
                | set(shafts_by_id) | {roof.get("id")} | {"foundation:each-column"} | set(extra_ids))
    for c in m.get("coverings", []):
        check(f"{pre}V16 仕上げ参照 {c['id']}", c["target"] in registry, c["target"])
    for r in m.get("reinforcement", []):
        check(f"{pre}V16 配筋参照 {r['id']}", r["target"] in registry, r["target"])
    for g in m.get("genericElements", []):
        check(f"{pre}V16 汎用要素参照 {g['id']}", g["attachTo"] in registry, g["attachTo"])

    # V19 改札ゾーン分割（駅舎のみ）
    if m.get("fareZones"):
        all_rooms = sorted(r["id"] for r in m["rooms"])
        zoned = [rid for z in m["fareZones"] for rid in z["rooms"]]
        check(f"{pre}V19 改札ゾーン分割", sorted(zoned) == all_rooms and len(zoned) == len(set(zoned)),
              f"rooms={len(zoned)}/{len(all_rooms)}")
        kinds = {z["id"]: z["kind"] for z in m["fareZones"]}
        gates_ok = any({kinds.get(g["fromZone"]), kinds.get(g["toZone"])} == {"改札内", "改札外"}
                       for g in m.get("fareGates", []))
        check(f"{pre}V19 改札の存在", gates_ok, f"gates={len(m.get('fareGates', []))}")

    # ---- 用途別追加検証 V-U の即判定分 ----
    use = m.get("building", {}).get("use", "")
    if use.startswith("商業"):
        limit = 3000 if m.get("building", {}).get("sprinklerFull") else 1500
        for c in m.get("compartments", []):
            if c["kind"] != "面積区画":
                continue
            tot = sum(area_of(r, X, Y) for r in m["rooms"] if r["id"] in c["rooms"])
            check(f"{pre}V-U商2 区画面積 {c['id']}", tot <= limit, f"{tot:.0f}㎡ <= {limit}㎡")
        retail = [r for r in m["rooms"] if r["use"] in ("テナント", "飲食")]
        for r in retail:
            w = X[r["cells"]["xTo"]] - X[r["cells"]["xFrom"]]
            d = Y[r["cells"]["yTo"]] - Y[r["cells"]["yFrom"]]
            check(f"{pre}V-U商3 区画形状 {r['id']}", max(w, d) / min(w, d) <= 3, f"{w}x{d}")
        if retail:
            areas = [area_of(r, X, Y) for r in retail]
            check(f"{pre}V-U商4 最大店舗比率", max(areas) <= 0.8 * sum(areas),
                  f"max={max(areas):.0f} total={sum(areas):.0f}")
    if use.startswith("マンション"):
        for w in m["walls"]:
            if w["kind"] == "戸境":
                check(f"{pre}V-Uマ3 界壁の開口ゼロ {w['id']}", len(w["openings"]) == 0, "")
        top_h = max(l["elevation"] + l["floorHeight"] for l in m["levels"])
        if top_h > 31000:
            has_emg = any(s.get("emergency") for s in m.get("shafts", []))
            has_bousai = any(r["use"] == "防災センター" for r in m["rooms"])
            check(f"{pre}V-Uマ4 31m超の非常用EV・防災センター", has_emg and has_bousai,
                  f"height={top_h} emergencyEv={has_emg} 防災センター={has_bousai}")
        # V-Uマ6 採光（法28条：居室の採光開口 ≧ 床面積の1/7。住戸単位・開口面積ベースの近似で、
        # 採光補正係数と住戸内の室別判定は行わない）
        def daylight_ratio(r):
            c = r["cells"]
            rx0, rx1 = X[c["xFrom"]], X[c["xTo"]]
            ry0, ry1 = Y[c["yFrom"]], Y[c["yTo"]]
            area = (rx1 - rx0) * (ry1 - ry0) / 1e6
            win = 0.0
            for w in m["walls"]:
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
                        win += ov * o["height"] / 1e6
            return win / area if area else 0.0
        units6 = [r for r in m["rooms"] if r["use"] == "住戸"]
        if units6:
            ratios = [(daylight_ratio(r), r["id"]) for r in units6]
            bad6 = [(rid, round(v, 3)) for v, rid in sorted(ratios) if v < 1 / 7]
            check(f"{pre}V-Uマ6 採光1/7（住戸単位の近似）", not bad6,
                  f"units={len(units6)} 不足={bad6[:4]}")

    # ---- V22：L4構造推論の整合（structure ブロックがある場合） ----
    lids = [l["id"] for l in m["levels"]]
    st = m.get("structure")
    if st:
        exc = {}
        for e in m.get("grid", {}).get("columnExceptions", []):
            at = e["at"]
            pi = Xn.index(at.split("-")[0]); pj = Yn.index(at.split("-")[1])
            exc[(pi, pj)] = set(e.get("levels", []))
        zones22 = []
        for z in st.get("columnFreeZones", []):
            zones22.append((z, cell_set(z.get("cellRanges", []))))
        def zone_adj(pi, pj, lid):
            n = 0
            for (z, zc) in zones22:
                if lid not in z["levels"]:
                    continue
                adj = [(pi - 1, pj - 1), (pi, pj - 1), (pi - 1, pj), (pi, pj)]
                n = max(n, len([c for c in adj if c in zc]))
            return n
        bad = [(at, lv) for (pi, pj), lvs in exc.items() for lv in lvs if zone_adj(pi, pj, lv) < 2]
        check(f"{pre}V22a 柱例外が無柱区画内", not bad, f"bad={bad[:4]}")
        okadachi = []
        for (pi, pj), lvs in exc.items():
            for k, lid in enumerate(lids[:-1]):
                if lid in lvs and lids[k + 1] not in lvs:
                    covered = any(lids[k + 1] in z["levels"] and
                                  ("受替" in z.get("treatment", "") or "トランスファー" in z.get("treatment", ""))
                                  and zone_adj(pi, pj, lids[k + 1]) >= 2 for (z, zc) in zones22)
                    if not covered:
                        okadachi.append((f"X{pi+1}-Y{pj+1}", lid))
        check(f"{pre}V22b 岡立ち禁止（受替なしの柱再開）", not okadachi, f"bad={okadachi[:4]}")
        seis = st.get("seismicElements", [])
        nx_ = len([s for s in seis if s["direction"] == "X"])
        ny_ = len([s for s in seis if s["direction"] == "Y"])
        seis_ok = nx_ >= 2 and ny_ >= 2 and all(lids[0] in s["levelRange"] for s in seis) and \
            all(cell_set([s["cell"]]) <= plate[s["levelRange"][0]] for s in seis)
        check(f"{pre}V22c 耐震要素の配置", seis_ok, f"X={nx_} Y={ny_} elements={len(seis)}")
        ga = st.get("groundAssumption", {})
        sys_ok = (st.get("system") == m.get("building", {}).get("structure")) or \
                 (st.get("system") == "壁式RC" and m.get("building", {}).get("structure") == "RC")
        check(f"{pre}V22d 構造種別・基礎仮定の記録", sys_ok and bool(ga.get("basis")),
              f"system={st.get('system')} foundation={ga.get('foundation')}")

    # ---- V23：構造軸/補助軸の分離（SPAN_STANDARD、structuralAxes がある場合） ----
    sax23 = m["grid"].get("structuralAxesX")
    say23 = m["grid"].get("structuralAxesY")
    if sax23 or say23:
        ok23 = bool(sax23) and bool(say23)
        detail23 = ""
        if ok23:
            ix = [Xn.index(n) for n in sax23]
            iy = [Yn.index(n) for n in say23]
            spans23 = [X[sax23[k + 1]] - X[sax23[k]] for k in range(len(sax23) - 1)] + \
                      [Y[say23[k + 1]] - Y[say23[k]] for k in range(len(say23) - 1)]
            exc_bad = [e["at"] for e in m["grid"].get("columnExceptions", [])
                       if e["at"].split("-")[0] not in sax23 or e["at"].split("-")[1] not in say23]
            ok23 = (ix == sorted(ix) and iy == sorted(iy)
                    and sax23[0] == Xn[0] and sax23[-1] == Xn[-1]
                    and say23[0] == Yn[0] and say23[-1] == Yn[-1]
                    and all(4000 <= s <= 15000 for s in spans23)
                    and not exc_bad)
            detail23 = (f"構造軸 X{len(sax23)}/{len(Xn)} Y{len(say23)}/{len(Yn)} "
                        f"構造スパン max={max(spans23)}mm（シード量子化の許容込み） 例外の非構造軸={exc_bad[:3]}")
        check(f"{pre}V23 構造軸/補助軸の分離", ok23, detail23)

    # ---- V24：シード仕様（building.seedSpec）とモデルの整合 ----
    ss24 = m.get("building", {}).get("seedSpec")
    if ss24:
        def _sv24(k):
            v = ss24.get(k, {})
            return v.get("value") if isinstance(v, dict) else v
        ok24, det24 = True, []
        ssys24 = _sv24("structureSystem")
        if ssys24 is not None:
            want24 = "RC" if ssys24 == "壁式RC" else ssys24
            ok24 = ok24 and m["building"].get("structure") == want24
            det24.append(f"structureSystem={ssys24}")
        ssp24 = _sv24("sprinkler")
        if ssp24 is not None:
            ok24 = ok24 and bool(m["building"].get("sprinklerFull")) == bool(ssp24)
            det24.append(f"sprinkler={ssp24}")
        # 前提の明示：seedSpec の全項目について assumptions に対応する記録があること
        asm_items = {a.get("item") for a in m.get("assumptions", [])}
        missing24 = [k for k in ss24 if k not in asm_items]
        ok24 = ok24 and not missing24
        if missing24:
            det24.append(f"assumptions欠落={missing24}")
        check(f"{pre}V24 シード仕様の反映", ok24, " ".join(det24))
    # V25 特記仕様書1頁相当ブロック（outline/zoning/systems）の前提記録
    _blks25 = [bk for bk in ("outline", "zoning", "systems") if m["building"].get(bk)]
    if _blks25:
        asm25 = {a.get("item") for a in m.get("assumptions", [])}
        miss25 = [f"{bk}.{k}" for bk in _blks25 for k in m["building"][bk]
                  if f"{bk}.{k}" not in asm25]
        check(f"{pre}V25 特記1頁ブロックの前提記録", not miss25,
              f"blocks={_blks25} 欠落={miss25}" if miss25 else f"blocks={_blks25}")
    # V26 コア内容物と開口ロールの整合（annotate_cores_and_openings の出力がある場合）
    if any("shafts" in c for c in m.get("cores", [])):
        shaft_by_id26 = {s["id"]: s for s in m.get("shafts", [])}
        core_by_id26 = {c["id"]: c for c in m.get("cores", [])}
        bad26 = []
        for c in m.get("cores", []):
            ss = [shaft_by_id26.get(sid) for sid in c.get("shafts", [])]
            if any(s is None for s in ss):
                bad26.append(f"{c['id']}:存在しないシャフト参照")
                continue
            stairs = [s for s in ss if s["kind"] == "階段"]
            if c.get("hasStair") != bool(stairs):
                bad26.append(f"{c['id']}:hasStair不一致")
            want_lv = sorted({l for s in stairs for l in s.get("levelRange", [])},
                             key=lambda l: int(l[1:]))
            if c.get("stairLevels") != want_lv:
                bad26.append(f"{c['id']}:stairLevels不一致")
        for w in m.get("walls", []):
            for o in w.get("openings", []):
                role = o.get("role")
                if role is None:
                    continue
                if role not in ("entrance", "shopfront", "core", "loading"):
                    bad26.append(f"{o['id']}:未知のrole={role}")
                elif role == "core":
                    cc = core_by_id26.get(o.get("servesCore"))
                    if cc is None or w["level"] not in cc.get("levelRange", []):
                        bad26.append(f"{o['id']}:servesCore不一致")
                elif role in ("entrance", "shopfront", "loading") and w["kind"] != "外壁":
                    bad26.append(f"{o['id']}:role={role}なのに外壁でない")
        check(f"{pre}V26 コア内容物・開口ロール", not bad26, "; ".join(bad26[:4]))

    # ---- V-L3：裏側（L3）の配置チェック ----
    def room_cells(r):
        return cell_set([r["cells"]])
    def adjacent(a, b):
        return any((i + d[0], j + d[1]) in b for (i, j) in a for d in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    freight_cores = {s["coreId"] for s in m.get("shafts", []) if s.get("freight")}
    loading = [r for r in m["rooms"] if "荷捌き" in r["name"] or "納品所" in r["name"]]
    if loading and freight_cores:
        core_cells_l1 = set()
        for cid in freight_cores:
            core_cells_l1 |= cell_set([cores_by_id[cid]["rect"]])
        ok = any(r["level"] == lids[0] and adjacent(room_cells(r), core_cells_l1) for r in loading)
        check(f"{pre}V-L3-1 荷捌きと貨物EVコアの隣接", ok, f"loading={len(loading)}")
    elec = [r for r in m["rooms"] if r["name"].startswith("電気室")]
    water = [r for r in m["rooms"] if r["name"].startswith("ポンプ室")]
    if elec and water:
        ok = not any(r1["level"] == r2["level"] and adjacent(room_cells(r1), room_cells(r2))
                     for r1 in elec for r2 in water)
        check(f"{pre}V-L3-2 電気室と水系室の非隣接", ok, "")
    bousai = [r for r in m["rooms"] if r["use"] == "防災センター"]
    if bousai:
        check(f"{pre}V-L3-3 防災センターは1F", all(r["level"] == lids[0] for r in bousai),
              f"levels={[r['level'] for r in bousai]}")
    if loading:
        ok = any(any((i + d[0], j + d[1]) not in plate[r["level"]]
                     for (i, j) in room_cells(r) for d in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                 for r in loading if r["level"] == lids[0])
        check(f"{pre}V-L3-4 荷捌きが外周に面する", ok, "")

    # ---- V-U 歩行距離（近似：プレート全セルを通行可としてBFS） ----
    def shaft_cells(s):
        f = s["footprint"]
        out = set()
        for i in range(len(Xn) - 1):
            for j in range(Yn.__len__() - 1):
                if X[Xn[i]] < f["x"] + f["w"] and f["x"] < X[Xn[i + 1]] and \
                   Y[Yn[j]] < f["y"] + f["d"] and f["y"] < Y[Yn[j + 1]]:
                    out.add((i, j))
        return out
    stair_cells = {}
    for s in m.get("shafts", []):
        if s["kind"] == "階段":
            for lid in s["levelRange"]:
                stair_cells.setdefault(lid, set()).update(shaft_cells(s))
    from collections import deque
    def walk_check(level_rooms, limit_mm, label):
        for lid in {r["level"] for r in level_rooms}:
            if lid not in stair_cells:
                continue
            dist = {c: 0 for c in stair_cells[lid]}
            dq = deque(stair_cells[lid])
            while dq:
                c = dq.popleft()
                for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (c[0] + d[0], c[1] + d[1])
                    if n in plate[lid] and n not in dist:
                        step = (X[Xn[n[0] + 1]] - X[Xn[n[0]]]) if d[0] else (Y[Yn[n[1] + 1]] - Y[Yn[n[1]]])
                        dist[n] = dist[c] + step
                        dq.append(n)
                # 斜め移動：両脇の直交セルがプレート内にある場合のみ（開いた売場内の歩行を近似）
                for d in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                    n = (c[0] + d[0], c[1] + d[1])
                    if n in plate[lid] and n not in dist and \
                            (c[0] + d[0], c[1]) in plate[lid] and (c[0], c[1] + d[1]) in plate[lid]:
                        sx = X[Xn[n[0] + 1]] - X[Xn[n[0]]]
                        sy = Y[Yn[n[1] + 1]] - Y[Yn[n[1]]]
                        dist[n] = dist[c] + int(0.707 * (sx + sy))
                        dq.append(n)
            worst = []
            for r in level_rooms:
                if r["level"] != lid:
                    continue
                rc = room_cells(r)
                far = max((dist.get(c, 10 ** 9) for c in rc), default=0)
                if far > limit_mm:
                    worst.append((r["id"], far // 1000))
            check(f"{pre}{label} {lid}", not worst, f"超過={worst[:4]}（近似）")
    if use.startswith("商業"):
        # 令120条：物販30m。準不燃内装＋準耐火/不燃＋SP前提の建物は40mで設計される（USE_RULES §1）
        wlim = 40000 if m.get("building", {}).get("sprinklerFull") else 30000
        walk_check([r for r in m["rooms"] if r["use"] in ("物販", "テナント", "飲食")], wlim,
                   f"V-U商5 歩行距離{wlim // 1000}m")
    if use.startswith("マンション"):
        walk_check([r for r in m["rooms"] if r["use"] == "住戸"], 50000, "V-Uマ5 歩行距離50m")

def validate_site_station(site):
    """V17・V18：軌道とホーム（site は軌道・ホームを持つ dict）"""
    tracks = {t["id"]: t for t in site.get("tracks", [])}
    for p in site.get("platforms", []):
        refs_ok = all(t in tracks for t in p["trackIds"])
        eo = p["edgeOffset"]
        eo_ok = (1350 <= eo <= 1650) if all(tracks[t]["kind"] == "在来線" for t in p["trackIds"] if t in tracks) else eo >= 1400
        check(f"V17 軌道・ホーム整合 {p['id']}", refs_ok and eo_ok, f"tracks={p['trackIds']} edgeOffset={eo}")
        w = p["rect"]["w"] if p["rect"]["w"] else 0
        width = p["rect"]["d"]
        form_ok = (width >= 5000 if p["form"] == "島式" else width >= 2000)
        h_ok = p["height"] in (760, 920, 1100, 1250)
        check(f"V18 ホーム定数 {p['id']}", form_ok and h_ok, f"form={p['form']} width={width} height={p['height']}")

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "building_model_example.json"
    data = json.load(open(path, encoding="utf-8"))
    if "buildings" in data:
        site = data.get("site", {})
        validate_site_station(site)
        ids = {b["building"]["id"] for b in data["buildings"]}
        extra = {p["id"] for p in site.get("platforms", [])} | {t["id"] for t in site.get("tracks", [])}
        for b in data["buildings"]:
            validate_building(b, tag=b["building"]["id"], extra_ids=extra)
        for lk in data.get("complex", {}).get("links", []):
            check(f"V20 複合整合 {lk['id']}", lk["from"] in ids and lk["to"] in ids,
                  f"{lk['from']} -> {lk['to']} ({lk['kind']})")
    else:
        if data.get("site", {}).get("platforms"):
            validate_site_station(data["site"])
        validate_building(data)
    print()
    print("結果:", "全チェック PASS" if not fails else f"{len(fails)} 件 FAIL: {fails}")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
