#!/usr/bin/env python3
"""設備系統の推論生成（EquipmentRun 相当）。

建物モデルに EquipmentRun が無い／乏しい場合に、systems の有無と Shaft 配置
（PS=配管、DS=ダクト）から系統テンプレートで経路を推論生成する。
CONSTRUCTION_PLAN_GENERATION.md §5.4 の決定（全要素 inferred、モデル側で
正式生成されたら差し替える）に基づく。

出力：generated_equipment_<name>.json（runs と系統別数量・金額配分比）
使い方：python3 equipment_infer.py <建物モデル.json>
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).parent
SERVE_RADIUS_M = 48.0          # シャフトが担う水平距離の上限（ゲーム既定）
DUCT_AREA_PER_M = 1.8          # ダクト長1mあたりのダクト面積（㎡、ゲーム既定）
COST_WEIGHT = {"電気": 0.8, "衛生": 0.6, "空調": 1.0}  # mあたり金額の重み（ゲーム既定）

def main():
    model_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "generated_game_mall.json"
    model = json.loads(model_path.read_text())
    axesX = {a["name"]: a["offset"] for a in model["grid"]["axesX"]}
    axesY = {a["name"]: a["offset"] for a in model["grid"]["axesY"]}

    def room_centroid(r):
        c = r["cells"]
        x = (axesX[c["xFrom"]] + axesX[c["xTo"]]) / 2 / 1000.0
        y = (axesY[c["yFrom"]] + axesY[c["yTo"]]) / 2 / 1000.0
        return x, y

    levels = [l["id"] for l in model["levels"]]
    floor_h = {l["id"]: l["floorHeight"] / 1000.0 for l in model["levels"]}
    total_h = sum(floor_h.values())
    rooms = model["rooms"]
    wc_by_level = {lv: [r for r in rooms if r["level"] == lv and r["use"] == "WC"] for lv in levels}
    all_by_level = {lv: [r for r in rooms if r["level"] == lv and r["use"] not in ("吹抜け",)] for lv in levels}

    runs = []
    totals = {"電気": 0.0, "衛生": 0.0, "空調": 0.0}
    def add_run(system, kind, shaft, level, to_desc, length_m, note=""):
        runs.append({"system": system, "kind": kind, "fromShaft": shaft["id"], "level": level,
                     "to": to_desc, "lengthM": round(length_m, 1), "tag": "inferred", "note": note})
        totals[system] += length_m

    ps_shafts = [s for s in model["shafts"] if s["kind"] == "PS"]
    ds_shafts = [s for s in model["shafts"] if s["kind"] == "DS"]
    def nearest(shafts, lv, x, y):
        best, bd = None, 1e18
        for s in shafts:
            if lv not in s["levelRange"]:
                continue
            d = abs(x - s["footprint"]["x"] / 1000.0) + abs(y - s["footprint"]["y"] / 1000.0)
            if d < bd:
                best, bd = s, d
        return best, bd
    for s in ps_shafts:
        add_run("衛生", "給排水・通気 立管", s, "all", "立管（全層）", total_h)
        add_run("電気", "幹線 立管", s, "all", "立管（EPS兼用として推論）", total_h, "電気シャフトはPSと兼用と推論")
    for s in ds_shafts:
        add_run("空調", "ダクト 立管", s, "all", "立管（全層）", total_h)
    # 横引きは各部屋を最寄りシャフトに一意に割り当てる（二重計上防止）
    for lv in levels:
        for r in wc_by_level.get(lv, []):
            rx, ry = room_centroid(r)
            s, d = nearest(ps_shafts, lv, rx, ry)
            if s and d <= SERVE_RADIUS_M:
                add_run("衛生", "給排水 横引き", s, lv, r["id"], d)
        for r in all_by_level.get(lv, []):
            rx, ry = room_centroid(r)
            s, d = nearest(ds_shafts, lv, rx, ry)
            if s and d <= SERVE_RADIUS_M:
                add_run("空調", "ダクト 横引き", s, lv, r["id"], d)
        # 電気は階ごとの分電盤群への代表配線（最寄りPSから階重心へ）
        served = all_by_level.get(lv, [])
        if served and ps_shafts:
            cx = sum(room_centroid(r)[0] for r in served) / len(served)
            cy = sum(room_centroid(r)[1] for r in served) / len(served)
            s, d = nearest(ps_shafts, lv, cx, cy)
            if s:
                add_run("電気", "幹線・分電盤 横引き（代表）", s, lv, f"{lv} 分電盤群", min(d, SERVE_RADIUS_M))

    # 金額配分比は延長から出さない：系統ごとにネットワーク形態（ダクトは全室へ分岐、
    # 電気は代表幹線で表現）が違い、延長の単純比較は金額比にならないため。
    # 配分比は大型商業のゲーム既定とし、延長は空間・数量の参考値として別に持つ
    DEFAULT_SHARES = {"電気": 0.30, "衛生": 0.22, "空調": 0.48}
    shares = dict(DEFAULT_SHARES)
    out = {
        "meta": {"generator": "equipment_infer.py v0.1", "building": model["building"]["name"],
                 "buildingFile": model_path.name, "tag": "inferred",
                 "note": "モデル側 EquipmentRun の正式生成までの推論代替。経路はシャフト配置と部屋重心からのマンハッタン距離で近似"},
        "runs": runs,
        "totals": {"pipeAndCableLengthM": {k: round(v, 1) for k, v in totals.items()},
                   "ductAreaM2": round(totals["空調"] * DUCT_AREA_PER_M, 1)},
        "mepCostShares": shares,
        "counts": {"runs": len(runs), "psShafts": len(ps_shafts), "dsShafts": len(ds_shafts)},
    }
    out_path = HERE / f"generated_equipment_{model_path.stem.replace('generated_', '')}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"建物: {model['building']['name']}  runs {len(runs)}件（PS {len(ps_shafts)} / DS {len(ds_shafts)}）")
    print(f"系統別延長: 電気 {totals['電気']:,.0f}m / 衛生 {totals['衛生']:,.0f}m / 空調 {totals['空調']:,.0f}m（ダクト面積 {out['totals']['ductAreaM2']:,.0f}㎡）")
    print(f"設備費の配分比（推論）: {shares}")
    print(f"出力: {out_path}")

if __name__ == "__main__":
    main()
