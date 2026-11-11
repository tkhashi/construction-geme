#!/usr/bin/env python3
"""CP-0 試作：建物モデルから数量→工期（3点推定）→金額を推論する。

CONSTRUCTION_PLAN_GENERATION.md の CP-0／CP-6 の最小実装（S造・商業のみ）。
入力：generated_*.json（建物モデル）＋ cost_tables.json（DP-2 テーブル）
出力：generated_plan_cp0_<name>.json ＋ 標準出力サマリ
全ての値は cost_tables.json のゲーム用既定に基づく。公表歩掛・公表単価ではない。
"""
import json, math, random, sys
from pathlib import Path

HERE = Path(__file__).parent

def expand_cells(ranges, idx):
    """ranges（軸名）→ セル集合 {(i,j)}。idx は軸名→順序"""
    cells = set()
    for r in ranges:
        x0, x1 = idx[r["xFrom"]], idx[r["xTo"]]
        y0, y1 = idx[r["yFrom"]], idx[r["yTo"]]
        for i in range(min(x0, x1), max(x0, x1)):
            for j in range(min(y0, y1), max(y0, y1)):
                cells.add((i, j))
    return cells

def main():
    model_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "generated_game_mall.json"
    difficulty_name = sys.argv[2] if len(sys.argv) > 2 else "normal"
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    model = json.loads(model_path.read_text())
    tables = json.loads((HERE / "cost_tables.json").read_text())
    qc = tables["quantityCoefficients"]
    prod = tables["productivity"]
    prices = tables["unitPrices"]

    axesX = model["grid"]["axesX"]; axesY = model["grid"]["axesY"]
    idxX = {a["name"]: i for i, a in enumerate(axesX)}
    idxY = {a["name"]: i for i, a in enumerate(axesY)}
    idx = {**idxX, **idxY}
    offX = {a["name"]: a["offset"] for a in axesX}
    offY = {a["name"]: a["offset"] for a in axesY}
    spanX = [axesX[i + 1]["offset"] - axesX[i]["offset"] for i in range(len(axesX) - 1)]
    spanY = [axesY[j + 1]["offset"] - axesY[j]["offset"] for j in range(len(axesY) - 1)]

    def cells_area(cells):
        return sum(spanX[i] * spanY[j] for (i, j) in cells) / 1e6

    def plate_cells(level):
        fp = level.get("footprint")
        if not fp:
            fp = [{"xFrom": axesX[0]["name"], "xTo": axesX[-1]["name"],
                   "yFrom": axesY[0]["name"], "yTo": axesY[-1]["name"]}]
        return expand_cells(fp, idx)

    levels = model["levels"]
    plate = {l["id"]: plate_cells(l) for l in levels}
    plate_area = {lid: cells_area(c) for lid, c in plate.items()}
    gross_area = sum(plate_area.values())

    # 柱位置：構造軸の交点のみ（SPAN_STANDARD：柱・大梁は構造軸だけ。補助軸に柱は立たない）
    struct_i = {idxX[n] for n in model["grid"].get("structuralAxesX", [a["name"] for a in axesX])}
    struct_j = {idxY[n] for n in model["grid"].get("structuralAxesY", [a["name"] for a in axesY])}
    exceptions = {(e["at"], lv) for e in model["grid"].get("columnExceptions", []) for lv in e["levels"]}
    def column_points(lid):
        pts = set()
        for (i, j) in plate[lid]:
            pts |= {(i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)}
        out = set()
        for (i, j) in pts:
            if i not in struct_i or j not in struct_j:
                continue
            at = f"{axesX[i]['name']}-{axesY[j]['name']}"
            if (at, lid) not in exceptions:
                out.add((i, j))
        return out
    cols = {l["id"]: column_points(l["id"]) for l in levels}
    first_level = levels[0]["id"]
    column_count_1f = len(cols[first_level])

    # 梁総長：大梁＝構造軸上の線、小梁＝補助軸上の線（分けて数える）
    def beam_length(lid, structural_only):
        cells = plate[lid]; total_mm = 0
        xs = sorted({i for (i, j) in cells} | {i + 1 for (i, j) in cells})
        ys = sorted({j for (i, j) in cells} | {j + 1 for (i, j) in cells})
        for j in ys:  # Y=j の線に沿う X 区間
            if (j in struct_j) != structural_only:
                continue
            for i in range(len(axesX) - 1):
                if (i, j - 1) in cells or (i, j) in cells:
                    total_mm += spanX[i]
        for i in xs:  # X=i の線に沿う Y 区間
            if (i in struct_i) != structural_only:
                continue
            for j in range(len(axesY) - 1):
                if (i - 1, j) in cells or (i, j) in cells:
                    total_mm += spanY[j]
        return total_mm / 1000.0
    beam_len = {l["id"]: beam_length(l["id"], True) for l in levels}
    beam_len_secondary = {l["id"]: beam_length(l["id"], False) for l in levels}
    grade_beam_len = beam_len[first_level]  # 地中梁は1Fプレートの構造軸線で近似

    # スラブ
    slab_area = {}; slab_concrete = 0.0; deck_area = 0.0
    for s in model["slabs"]:
        cells = expand_cells(s["cellRanges"], idx)
        a = cells_area(cells); slab_area[s["id"]] = a
        slab_concrete += a * s["thickness"] / 1000.0
        if not s.get("onGround"):
            deck_area += a

    # 基礎
    foot = model["foundations"]["footings"]
    footing_concrete = column_count_1f * (foot["size"]["w"] / 1000) * (foot["size"]["d"] / 1000) * (foot["thickness"] / 1000)
    grade_concrete = grade_beam_len * qc["gradeBeamSectionM2"]["value"]
    foundation_concrete = footing_concrete + grade_concrete

    # 数量
    total_height_m = sum(l["floorHeight"] for l in levels) / 1000.0
    column_steel_t = sum(len(cols[l["id"]]) * (l["floorHeight"] / 1000.0) for l in levels) * qc["columnSteelKgPerM"]["value"] / 1000.0
    girder_len = sum(beam_len[lid] for lid in [l["id"] for l in levels[1:]]) + beam_len[levels[-1]["id"]]  # 上階床梁＋屋根梁
    secondary_len = sum(beam_len_secondary[lid] for lid in [l["id"] for l in levels[1:]]) + beam_len_secondary[levels[-1]["id"]]
    girder_steel_t = (girder_len * qc["girderSteelKgPerM"]["value"]
                      + secondary_len * qc["secondaryBeamSteelKgPerM"]["value"]) / 1000.0
    steel_t = (column_steel_t + girder_steel_t) * (1 + qc["steelBraceEtcRatio"]["value"])

    earth = model["earthworks"][0]
    excavation = plate_area[first_level] * (earth["depth"] / 1000.0) * qc["earthworkWorkingSpaceRatio"]["value"]

    pile_count = column_count_1f
    pile_len_total = pile_count * qc["pileLengthM"]["value"]

    concrete_total = slab_concrete + foundation_concrete
    rebar_t = (sum(slab_area.values()) * qc["slabRebarKgPerM2"]["value"] + foundation_concrete * qc["foundationRebarKgPerM3"]["value"]) / 1000.0
    formwork = foundation_concrete * qc["formworkFoundationM2PerM3"]["value"]

    # 外壁面積：外壁セグメント長 × 階高
    exterior_wall = 0.0
    fh = {l["id"]: l["floorHeight"] / 1000.0 for l in levels}
    for w in model["walls"]:
        if w["kind"] != "外壁":
            continue
        line = w["line"]
        if "axis" in line and line["axis"].startswith("Y"):
            length = abs(offX[line["to"]] - offX[line["from"]]) / 1000.0
        elif "axis" in line:
            length = abs(offY[line["to"]] - offY[line["from"]]) / 1000.0
        else:
            continue
        exterior_wall += length * fh[w["level"]]

    roof_cells = expand_cells(model["roof"]["cellRanges"], idx)
    roof_area = cells_area(roof_cells)

    site = model["site"]["polygon"]
    xs = [p[0] for p in site]; ys = [p[1] for p in site]
    site_area = (max(xs) - min(xs)) * (max(ys) - min(ys)) / 1e6
    exterior_works_area = max(site_area - plate_area[first_level], 0)

    elevator_count = sum(1 for s in model["shafts"] if s["kind"] == "EV")

    quantities = {
        "grossAreaM2": round(gross_area, 1),
        "grossAreaTargetM2": model["building"].get("grossAreaTarget"),
        "plateAreaByLevel": {k: round(v, 1) for k, v in plate_area.items()},
        "columnCount1F": column_count_1f,
        "pileCount": pile_count,
        "pileLengthTotalM": round(pile_len_total, 1),
        "excavationM3": round(excavation, 1),
        "foundationConcreteM3": round(foundation_concrete, 1),
        "concreteTotalM3": round(concrete_total, 1),
        "slabConcreteM3": round(slab_concrete, 1),
        "formworkM2": round(formwork, 1),
        "rebarTonnes": round(rebar_t, 1),
        "steelTonnes": round(steel_t, 1),
        "columnSteelTonnes": round(column_steel_t, 1),
        "girderSteelTonnes": round(girder_steel_t, 1),
        "deckSlabM2": round(deck_area, 1),
        "exteriorWallM2": round(exterior_wall, 1),
        "roofM2": round(roof_area, 1),
        "exteriorWorksM2": round(exterior_works_area, 1),
        "siteAreaM2": round(site_area, 1),
        "elevatorCount": elevator_count,
    }

    # ---- 工期（CP-0）：フェーズ日数→ネットワーク（直列＋並行）→暦変換 ----
    rng = random.Random(seed)
    diff = tables["difficulty"]["levels"][difficulty_name]
    swing_hi = rng.uniform(*diff["productivitySwingRange"])
    draws = {
        "difficulty": difficulty_name,
        "seed": seed,
        "budgetAssessmentRate": round(rng.uniform(*diff["budgetAssessmentRateRange"]), 4),
        "bufferRate": round(rng.uniform(*diff["bufferRateRange"]), 4),
        "productivitySwing": round(swing_hi, 4),
    }
    qmap = {k: quantities[k] for k in quantities}
    phase_days = {}
    for ph in prod["phases"]:
        if ph["type"] == "fixed":
            phase_days[ph["id"]] = {"name": ph["name"], "workingDays": ph["workingDays"], "basis": ph["basis"]}
        else:
            raw = qmap[ph["quantity"]] / (ph["dailyOutput"] * ph["sets"]) + ph.get("plusDays", 0)
            phase_days[ph["id"]] = {"name": ph["name"], "workingDays": round(raw, 1), "basis": ph["basis"]}
    order = ["prep", "earthwork", "piling", "foundation", "frame", "roofExterior", "mepInterior", "closing"]
    cp_days = sum(phase_days[p]["workingDays"] for p in order)
    # 並行フェーズは CP を伸ばす場合のみ加算
    for pid, base in (("elevator", "mepInterior"), ("exteriorWorks", "mepInterior")):
        over = phase_days[pid]["workingDays"] - phase_days[base]["workingDays"]
        phase_days[pid]["cpAddition"] = round(max(0.0, over), 1)
        cp_days += max(0.0, over)
    tp = prod["threePoint"]
    rate_phases = [p for p in order if p not in ("prep", "closing")]
    fixed_days = phase_days["prep"]["workingDays"] + phase_days["closing"]["workingDays"]
    rate_days = cp_days - fixed_days
    wd = prod["calendar"]["workingDaysPer28CalendarDays"]
    def to_calendar(working):
        cal = working * 28.0 / wd
        cal += (cal / 365.0) * 11  # 長期休暇（年末年始5・夏季3・GW3）の近似
        return round(cal)
    duration = {
        "workingDaysBase": round(cp_days, 1),
        "workingDaysLow": round(fixed_days + rate_days * tp["lowFactor"], 1),
        "workingDaysHigh": round(fixed_days + rate_days * tp["highFactor"], 1),
        "calendarDaysBase": to_calendar(cp_days),
        "calendarDaysLow": to_calendar(fixed_days + rate_days * tp["lowFactor"]),
        "calendarDaysHigh": to_calendar(fixed_days + rate_days * tp["highFactor"]),
        "bufferWorkingDays": round(cp_days * draws["bufferRate"], 1),
        "note": "暦変換は4週8閉所（28暦日=20実働日）＋長期休暇近似。3点推定は実働日数側の係数（cost_tables.threePoint）",
    }

    # ---- 金額 ----
    items = []
    direct = 0.0
    for it in prices["items"]:
        amt = qmap[it["quantity"]] * it["price"]
        direct += amt
        items.append({"id": it["id"], "name": it["name"], "quantity": qmap[it["quantity"]],
                      "unit": it["unit"], "unitPrice": it["price"], "amount": round(amt)})
    rates = prices["commonRates"]
    common_temp = direct * rates["commonTemporaryRateOnDirect"]["value"]
    net = direct + common_temp
    site_mgmt = net * rates["siteManagementRateOnNet"]["value"]
    cost_price = net + site_mgmt
    general = cost_price * rates["generalManagementRateOnCost"]["value"]
    total_price = cost_price + general
    execution_budget = cost_price * (1 - draws["budgetAssessmentRate"])
    cost = {
        "items": items,
        "directCost": round(direct),
        "commonTemporary": round(common_temp),
        "netConstructionCost": round(net),
        "siteManagement": round(site_mgmt),
        "constructionCostPrice": round(cost_price),
        "generalManagement": round(general),
        "totalPrice": round(total_price),
        "unitPricePerM2": round(total_price / gross_area),
        "executionBudget": round(execution_budget),
        "budgetAssessmentRateDrawn": draws["budgetAssessmentRate"],
        "note": "実行予算 = 工事原価 × (1 - 査定率〈難易度レンジからシード抽選〉)。請負金額の近似は totalPrice",
    }

    out = {
        "meta": {"generator": "plan_cp0.py v0.1 (CP-0 prototype)", "building": model["building"]["name"],
                 "buildingFile": model_path.name, "tables": "cost_tables.json",
                 "difficultyDraws": draws},
        "quantities": quantities,
        "phases": phase_days,
        "duration": duration,
        "cost": cost,
    }
    out_path = HERE / f"generated_plan_cp0_{model_path.stem.replace('generated_', '')}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"建物: {model['building']['name']}  延床(計算) {gross_area:,.0f}㎡ / 目標 {model['building'].get('grossAreaTarget')}㎡")
    print(f"数量: 柱(1F) {column_count_1f}本 / 杭 {pile_count}本 / 鉄骨 {steel_t:,.0f}t / コンクリート {concrete_total:,.0f}㎥ / 鉄筋 {rebar_t:,.0f}t / 掘削 {excavation:,.0f}㎥")
    print(f"工期: 実働 {cp_days:,.0f}日 → 暦 {duration['calendarDaysBase']}日（低 {duration['calendarDaysLow']} / 高 {duration['calendarDaysHigh']}、バッファ実働 {duration['bufferWorkingDays']}日）")
    print(f"金額: 直接 {direct/1e8:.2f}億円 → 工事価格 {total_price/1e8:.2f}億円（{cost['unitPricePerM2']:,}円/㎡） 実行予算 {execution_budget/1e8:.2f}億円")
    print(f"出力: {out_path}")

if __name__ == "__main__":
    main()
