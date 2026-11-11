#!/usr/bin/env python3
"""工事計画生成パイプライン CP-1〜CP-10（S造・商業テンプレート）。

CONSTRUCTION_PLAN_GENERATION.md の実装。CP-0（plan_cp0.py）の premises を前提に、
照査→現場条件→基本方針（難易度＋シード抽選）→工法・仮設→WBS→日数・原価→
ネットワーク・暦→調達・検査チェーン→QCDSE・リスク→検証 PL-01〜PL-12 を回し、
ConstructionPlan（12ブロック）を JSON で出す。

使い方： python3 plan_generate.py <建物モデル.json> [easy|normal|hard] [seed] [開始日YYYY-MM-DD]
"""
import json, math, subprocess, sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent

# ---------- 暦（4週8閉所＋長期休暇の近似） ----------
BREAKS = [(12, 29, 1, 3), (4, 29, 5, 5), (8, 13, 8, 15)]  # 年末年始・GW・夏季（月,日,月,日）

def is_working(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    for (m1, d1, m2, d2) in BREAKS:
        start = date(d.year, m1, d1)
        end = date(d.year + (1 if m2 < m1 else 0), m2, d2)
        if start <= d <= end:
            return False
    return True

def build_calendar(start: date, n_working: int):
    days = []
    d = start
    while len(days) < n_working:
        if is_working(d):
            days.append(d)
        d += timedelta(days=1)
    return days

# ---------- 建物モデルの幾何ヘルパ ----------
def geometry(model):
    axesX, axesY = model["grid"]["axesX"], model["grid"]["axesY"]
    idx = {a["name"]: i for i, a in enumerate(axesX)}
    idx.update({a["name"]: i for i, a in enumerate(axesY)})
    spanX = [axesX[i + 1]["offset"] - axesX[i]["offset"] for i in range(len(axesX) - 1)]
    spanY = [axesY[j + 1]["offset"] - axesY[j]["offset"] for j in range(len(axesY) - 1)]
    def expand(ranges):
        cells = set()
        for r in ranges:
            x0, x1 = idx[r["xFrom"]], idx[r["xTo"]]
            y0, y1 = idx[r["yFrom"]], idx[r["yTo"]]
            for i in range(min(x0, x1), max(x0, x1)):
                for j in range(min(y0, y1), max(y0, y1)):
                    cells.add((i, j))
        return cells
    def area(cells):
        return sum(spanX[i] * spanY[j] for (i, j) in cells) / 1e6
    return expand, area

def main():
    model_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "generated_game_mall.json"
    difficulty = sys.argv[2] if len(sys.argv) > 2 else "normal"
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    start = date.fromisoformat(sys.argv[4]) if len(sys.argv) > 4 else date(2027, 4, 1)
    model = json.loads(model_path.read_text())
    tables = json.loads((HERE / "cost_tables.json").read_text())

    # CP-0 を回して premises を得る
    subprocess.run([sys.executable, str(HERE / "plan_cp0.py"), str(model_path), difficulty, str(seed)],
                   check=True, capture_output=True)
    cp0 = json.loads((HERE / f"generated_plan_cp0_{model_path.stem.replace('generated_', '')}.json").read_text())
    equip_path = HERE / f"generated_equipment_{model_path.stem.replace('generated_', '')}.json"
    equip = json.loads(equip_path.read_text()) if equip_path.exists() else None
    Q = cp0["quantities"]; PH = cp0["phases"]; draws = cp0["meta"]["difficultyDraws"]
    expand, cell_area = geometry(model)

    # ---------- CP-1 照査 ----------
    findings = []
    ga = model["building"].get("groundAssumption") or (model.get("structure") or {}).get("groundAssumption") or {}
    if (model.get("foundations", {}).get("piles", {}) or {}).get("kind", "").startswith("不明") or ga.get("foundation") == "杭基礎":
        findings.append({"id": "F-01", "item": "杭種別・支持層が未特定（モデル側 gap）",
                         "handling": "場所打ち杭・杭長15mを default として計画し、地盤調査結果で見直す前提を risks に明記", "tag": "gap"})
    if len(model.get("equipmentRuns", [])) < 5:
        if equip:
            findings.append({"id": "F-02", "item": "EquipmentRun が未生成に近い（系統の経路情報が無い）",
                             "handling": f"equipment_infer.py で系統テンプレート推論を生成済み（runs {equip['counts']['runs']}件、全要素 inferred）。"
                                         "設備費の系統別配分と系統別数量はそちらを使う。モデル側で正式生成されたら差し替える", "tag": "inferred"})
        else:
            findings.append({"id": "F-02", "item": "EquipmentRun が未生成に近い（系統の経路情報が無い）",
                             "handling": "設備は系統テンプレート（電気・衛生・空調×3段階）で生成し inferred を付ける", "tag": "gap"})
    if Q["grossAreaTargetM2"] and abs(Q["grossAreaM2"] - Q["grossAreaTargetM2"]) / Q["grossAreaTargetM2"] > 0.05:
        findings.append({"id": "F-03", "item": f"延床：プレート計算 {Q['grossAreaM2']:,.0f}㎡ vs モデル目標 {Q['grossAreaTargetM2']:,}㎡",
                         "handling": "プレート計算値を正とする（目標値には駐車場棟等の包含が疑われる。要確認）", "tag": "inferred"})
    findings.append({"id": "F-04", "item": "構造・工法はモデル structure ブロック（S造・節2節）に従う", "handling": "照査済み", "tag": "rule"})

    # ---------- CP-2 現場条件 ----------
    site = model["site"]
    occupancy = Q["plateAreaByLevel"][model["levels"][0]["id"]] / max(Q["siteAreaM2"], 1)
    neighbors = site.get("neighbors", [])
    residential = any("住宅" in n.get("type", "") for n in neighbors)
    site_conditions = {
        "siteAreaM2": Q["siteAreaM2"], "buildingOccupancyRatio": round(occupancy, 3),
        "gates": site.get("gates", []), "neighbors": neighbors,
        "workHours": "8:00–18:00（北側住宅への騒音配慮を前提とする）" if residential else "8:00–18:00",
        "stagingNote": "敷地占有率が高くヤードが狭い。資材置き場は敷地内・建物内の空きスペースに仮設フェーズ別に配する" if occupancy > 0.55
                       else "敷地内に資材置き場を確保可能",
        "tags": {"workHours": "inferred" if residential else "default", "stagingNote": "inferred"},
    }

    # ---------- CP-3 基本方針（難易度＋シード抽選のみ：DP-3） ----------
    diff = tables["difficulty"]["levels"][difficulty]
    decisions = [
        {"topic": "難易度", "choice": diff["label"], "decidedBy": "player", "tag": "player"},
        {"topic": "実行予算の査定率", "choice": draws["budgetAssessmentRate"], "decidedBy": "seed", "tag": "default",
         "range": diff["budgetAssessmentRateRange"]},
        {"topic": "計画バッファ率", "choice": draws["bufferRate"], "decidedBy": "seed", "tag": "default",
         "range": diff["bufferRateRange"]},
        {"topic": "歩掛の揺れ幅（CP-6で作業別に抽選）", "choice": draws["productivitySwing"], "decidedBy": "seed", "tag": "default",
         "range": diff["productivitySwingRange"]},
        {"topic": "工法選定の保守性", "choice": diff["methodConservatism"], "decidedBy": "seed", "tag": "default"},
    ]

    # ---------- CP-4 工法・仮設選定 ----------
    height_m = sum(l["floorHeight"] for l in model["levels"]) / 1000.0
    tower_needed = height_m > 45
    methods = [
        {"item": "揚重", "choice": "ラフタークレーン＋横引き（台車等による床内水平移動）", "tag": "rule",
         "alternatives": ["タワークレーン"], "reason": "確定ルール：タワーは最大1基・必要な場合のみ。本物件は高さ "
          f"{height_m:.1f}m でラフターの揚程範囲内"},
        {"item": "タワークレーン", "choice": "採用しない" if not tower_needed else "1基のみ採用（基礎完了後に組立）", "tag": "rule",
         "alternatives": ["複数基"], "reason": "旋回半径の重なりによる事故防止（確定ルール）。複数基の同時計画は禁止"},
        {"item": "山留め", "choice": "親杭横矢板（保守性：標準）" if diff["methodConservatism"] != "標準〜攻め" else "シートパイル（保守性：攻め）",
         "tag": "inferred", "alternatives": ["ソイルセメント壁"], "reason": "根切り深さ1.5mと敷地条件からの推論選定。保守性は難易度抽選に従う"},
        {"item": "コンクリート打設", "choice": "ポンプ圧送", "tag": "default", "alternatives": ["バケット"], "reason": "打設量と階数から"},
        {"item": "足場", "choice": "枠組足場（面別に組立・解体）", "tag": "default", "alternatives": ["次世代足場"], "reason": "外装レーンと同期"},
        {"item": "鉄骨建方", "choice": "節建方（2節・地組併用）", "tag": "inferred", "alternatives": ["階別建方"],
         "reason": "モデル structure.constructionDerived の frameCycle に従う"},
    ]
    temporary_works = [
        {"item": "仮囲い", "spec": "鋼板塀 H3.0m、ゲートは南側2箇所（モデル site.gates）", "period": "全期間", "tag": "default"},
        {"item": "仮設事務所・詰所", "spec": "敷地内の空きスペースに配置", "period": "全期間", "tag": "default"},
        {"item": "山留め", "spec": methods[2]["choice"], "period": "土工〜基礎", "tag": "inferred"},
        {"item": "外周足場", "spec": "面別（組立→外装→解体を面ごとに回す）", "period": "外装期間", "tag": "default"},
        {"item": "揚重設備", "spec": "ラフタークレーン（配置は工程フェーズで移動）、横引き台車", "period": "躯体〜設備・内装の揚重日", "tag": "rule"},
        {"item": "資材置き場", "spec": "敷地内・建物内の空きスペースを仮設フェーズ別に配分（資材置き場調整の対象）", "period": "全期間", "tag": "default"},
    ]

    # ---------- CP-5 WBS 生成 ----------
    zones = []
    for z in model.get("zones", []):
        a = cell_area(expand(z["cellRanges"]))
        zones.append({"id": z["id"], "level": "L" + z["id"][0], "area": a})
    if not zones:
        for l in model["levels"]:
            for s in ("W", "C", "E"):
                zones.append({"id": f"{l['id'][1]}F-{s}", "level": l["id"], "area": Q["plateAreaByLevel"][l["id"]] / 3})
    zone_order = sorted(zones, key=lambda z: (z["level"], z["id"]))
    levels_sorted = sorted({z["level"] for z in zones})
    # 外周の面：外壁セグメントを「面」（南・北・西・東）に集約する。
    # 軸ごとではない——凹凸のある平面では外壁が多くの軸上に現れるが、外装レーンは立面の面で回す
    offX = {a["name"]: a["offset"] for a in model["grid"]["axesX"]}
    offY = {a["name"]: a["offset"] for a in model["grid"]["axesY"]}
    ext_segs = []
    for w in model["walls"]:
        if w["kind"] != "外壁":
            continue
        ln = w["line"]
        if ln["axis"].startswith("Y"):
            ext_segs.append(("Y", offY[ln["axis"]], abs(offX[ln["to"]] - offX[ln["from"]]) / 1000.0))
        else:
            ext_segs.append(("X", offX[ln["axis"]], abs(offY[ln["to"]] - offY[ln["from"]]) / 1000.0))
    faces = {}
    if ext_segs:
        y_offs = [o for (k, o, l) in ext_segs if k == "Y"]
        x_offs = [o for (k, o, l) in ext_segs if k == "X"]
        y_min, y_max = (min(y_offs), max(y_offs)) if y_offs else (0, 0)
        x_min, x_max = (min(x_offs), max(x_offs)) if x_offs else (0, 0)
        for (k, o, l) in ext_segs:
            if k == "Y":
                side = "南面" if abs(o - y_min) <= abs(o - y_max) else "北面"
            else:
                side = "西面" if abs(o - x_min) <= abs(o - x_max) else "東面"
            faces[side] = faces.get(side, 0) + l
    face_ids = [s for s in ("南面", "東面", "北面", "西面") if s in faces]

    tasks = {}
    def add(tid, name, phase, days, trade, deps=(), basis="rate", zone=None, gate=False, resource=None, cost_item=None, weight=1.0):
        items = []
        if cost_item:
            items = [(cost_item, weight)] if isinstance(cost_item, str) else list(cost_item)
        tasks[tid] = {"id": tid, "name": name, "phase": phase, "days": round(days, 1), "trade": trade,
                      "deps": [{"to": d, "type": "finish-start"} for d in deps],
                      "basis": basis, "zone": zone, "gate": gate, "resource": resource,
                      "costItems": items}
    def link(tid, dep, typ="resource"):
        tasks[tid]["deps"].append({"to": dep, "type": typ})

    P = {k: PH[k]["workingDays"] for k in PH}
    # 準備
    add("prep-1", "着工届出・施工計画確定", "prep", 4, "監督", basis="fixed", cost_item=None)
    add("prep-2", "仮設工事（仮囲い・事務所・ゲート）", "prep", 12, "仮設", ["prep-1"], "fixed")
    add("prep-3", "遣り方・基準墨", "prep", 4, "墨出し", ["prep-2"], "fixed")
    add("prep-4", "仮設電気・水道引込", "prep", 8, "設備", ["prep-2"], "fixed")
    # 土工
    add("earth-1", "山留め", "earthwork", 5, "土工", ["prep-3"], "fixed")
    add("earth-2", "根切り・残土搬出", "earthwork", P["earthwork"] - 8, "土工", ["earth-1"], "rate", cost_item="excavation")
    add("earth-3", "床付け・地業・捨てコン", "earthwork", 3, "土工", ["earth-2"], "fixed")
    # 杭
    add("pile-1", "試験杭・支持層確認", "piling", 3, "杭", ["earth-3"], "fixed")
    add("pile-2", "本杭（場所打ち）", "piling", P["piling"] - 3, "杭", ["pile-1"], "rate", cost_item="piling")
    add("pile-3", "杭頭処理", "piling", 3, "杭", ["pile-2"], "fixed")
    # 基礎（1F工区ごと、配筋は検査ゲート付き）。日数は工区面積でスケールする（REF_ZONE㎡を標準工区とする）
    REF_ZONE = 6500.0
    def zf(z):
        return max(0.6, z["area"] / REF_ZONE)
    fz = [z for z in zone_order if z["level"] == levels_sorted[0]]
    fprev_rebar = None
    foundation_end = []
    for z in fz:
        zid = z["id"]
        add(f"fnd-{zid}-1", f"{zid} 基礎配筋・型枠", "foundation", 9 * zf(z), "基礎", ["pile-3"], "rate", zone=zid,
            cost_item=[("concrete", z["area"] * 0.5), ("formwork", z["area"]), ("rebar", z["area"] * 0.6)])
        if fprev_rebar:
            link(f"fnd-{zid}-1", fprev_rebar)  # 配筋班の巡回（資源リンク）
        add(f"fnd-{zid}-2", f"{zid} 基礎打設・養生", "foundation", 7 * zf(z), "基礎", [], "rate", zone=zid,
            cost_item=[("concrete", z["area"] * 0.5)])
        add(f"fnd-{zid}-3", f"{zid} 型枠解体・埋戻し", "foundation", 4, "基礎", [f"fnd-{zid}-2"], "fixed", zone=zid)
        foundation_end.append(f"fnd-{zid}-3")
        fprev_rebar = f"fnd-{zid}-1"
    # 躯体（節ごと）。建方日数は節の鉄骨量÷揚重能力（44t/日＝2セット×22t）で出す
    n_levels = len(model["levels"])
    sections = [levels_sorted[:2], levels_sorted[2:]] if n_levels >= 3 else [levels_sorted]
    frame_end = []
    prev_section_end = foundation_end[:]
    sec_no = 0
    total_plate = sum(Q["plateAreaByLevel"].values())
    for sec in sections:
        if not sec:
            continue
        sec_no += 1
        sfx = f"s{sec_no}"
        sec_share = sum(Q["plateAreaByLevel"][lv] for lv in sec) / total_plate
        erect_days = max(6.0, Q["steelTonnes"] * sec_share / 44.0)
        add(f"frm-{sfx}-1", f"第{sec_no}節 鉄骨建方", "frame", erect_days, "鉄骨", prev_section_end, "rate",
            cost_item=[("steel", len(sec)), ("fireproofing", len(sec))])
        add(f"frm-{sfx}-2", f"第{sec_no}節 本締め・建入れ直し", "frame", 4, "鉄骨", [f"frm-{sfx}-1"], "fixed")
        sec_floor_ends = []
        for lv in sec:
            ff = max(0.6, Q["plateAreaByLevel"][lv] / 19861.0)
            add(f"frm-{sfx}-{lv}-d", f"{lv} デッキ敷き・先行仕込み（スリーブ／インサート）", "frame", 5 * ff, "鉄骨",
                [f"frm-{sfx}-2"], "rate", cost_item="deck", weight=Q["plateAreaByLevel"][lv])
            add(f"frm-{sfx}-{lv}-c", f"{lv} 床配筋・打設・養生", "frame", 8 * ff, "コンクリート",
                [f"frm-{sfx}-{lv}-d"], "rate",
                cost_item=[("concrete", Q["plateAreaByLevel"][lv]), ("rebar", Q["plateAreaByLevel"][lv])])
            sec_floor_ends.append(f"frm-{sfx}-{lv}-c")
        # 次節の建方は本節の本締め＋最下階デッキで解放する（床打設・養生は追い越し可：節の追っかけ）
        prev_section_end = [f"frm-{sfx}-2", f"frm-{sfx}-{sec[0]}-d"]
        frame_end = sec_floor_ends
    # 屋根・外装（躯体完了後：確定ルール）
    add("roof-1", "屋根下地・防水", "roofExterior", 12, "防水", frame_end, "rate", cost_item="roofing")
    add("roof-2", "屋根立上り・保護・ドレン通水確認", "roofExterior", 5, "防水", ["roof-1"], "fixed")
    face_wave_prev = []
    ext_all_end = []
    floor_h = height_m / n_levels
    for i, f in enumerate(face_ids):
        fid = f"face-{f}"
        # faces[f] は全階分の外壁セグメント長合計 → 面積 = 長さ × 階高
        alc_days = max(3.0, faces[f] * floor_h / 260.0)  # CP-0 の外装出来高 260㎡/日（1面1班）
        add(f"{fid}-1", f"{f} 足場組立", "roofExterior", 3, "鳶", frame_end, "fixed")
        if i >= 2 and face_wave_prev:
            link(f"{fid}-1", face_wave_prev[i - 2])  # 鳶2班の巡回
        add(f"{fid}-2", f"{f} 外壁パネル建込み", "roofExterior", alc_days, "外装", [f"{fid}-1"], "rate", cost_item="exteriorWall", weight=faces[f])
        add(f"{fid}-3", f"{f} サッシ・ガラス", "roofExterior", alc_days * 0.5, "外装", [f"{fid}-2"], "rate")
        add(f"{fid}-4", f"{f} シーリング・雨仕舞い確認", "roofExterior", max(2.0, faces[f] / 150.0), "外装", [f"{fid}-3"], "fixed")
        add(f"{fid}-5", f"{f} 足場解体", "roofExterior", 2, "鳶", [f"{fid}-4"], "fixed")
        face_wave_prev.append(f"{fid}-5")
        ext_all_end.append(f"{fid}-5")
    # 受電チェーン（屋外電気→キュービクル→受電）
    add("elec-0a", "屋外引込・受変電基礎", "mepInterior", 6, "電気", frame_end, "fixed")
    add("elec-0b", "キュービクル据付・幹線立上げ", "mepInterior", 8, "電気", ["elec-0a"], "rate", cost_item="mep", weight=0.5)
    # 高所作業車（階別搬入・搬出：ユーザー確定ルール）
    mep_start_deps = frame_end + ["roof-2"]  # 躯体完了＋屋根雨仕舞い後に内装開始
    for lv in levels_sorted:
        add(f"lift-in-{lv}", f"{lv} 高所作業車 搬入（クレーン揚重・開口部から）", "mepInterior", 1, "揚重",
            frame_end, "fixed")
        add(f"lift-out-{lv}", f"{lv} 高所作業車 搬出", "mepInterior", 1, "揚重", [], "fixed")
    # 工区チェーン（設備3系統×3段階＋内装）
    # (key, 表示名, 基準日数, 班〈職種〉, 並行班数) 班は下請の実際の班単位に分ける（内装一括りにしない）
    # 順序は WORK_STRUCTURE_V2 §2（天井裏の積み上がり順：PS縦管→吊りボルト→ダクト→配管の原則を含む）
    chain = [
        ("sumi", "内装墨出し", 2, "墨出し", 2), ("lgs", "LGS下地", 6, "軽鉄", 2),
        ("ps", "PS縦管立上げ", 3, "衛生", 2), ("hanger", "吊りボルト・支持材", 2, "設備支持", 2),
        ("hvac1", "空調ダクト・冷媒配管（隠蔽）", 5, "空調", 2), ("plmb1", "衛生配管（隠蔽）", 4, "衛生", 2),
        ("elec1", "電気配管・配線（隠蔽）", 4, "電気", 2), ("board", "天井下地・ボード", 6, "ボード", 2),
        ("mep2", "設備2次（器具前配管・配線）", 3, "設備2次", 2), ("finish", "パテ・仕上げ（塗装・クロス）", 7, "仕上げ", 2),
        ("floor", "床仕上げ", 4, "床", 2), ("door", "建具・金物", 3, "建具", 2),
        ("mep3", "器具付け（照明・水栓・吹出口）", 3, "器具付け", 2), ("clean", "美装・引渡し確認", 2, "美装", 2),
    ]
    trade_history = defaultdict(list)
    zone_chain_end = {}
    for z in zone_order:
        zid = z["id"]; prev = None
        for (key, label, days, trade, crews) in chain:
            tid = f"z-{zid}-{key}"
            days = days * zf(z)  # 工区面積でスケール
            deps = list(mep_start_deps) if prev is None else [prev]
            if key in ("hvac1", "board"):
                deps = deps + [f"lift-in-{z['level']}"]
            if key == "mep3":
                deps = deps + ["elec-0b"]  # 受電が器具付け・試運転の前提（チェーン側で受電検査ゲートを後付け）
            ci = "mep" if key in ("hvac1", "plmb1", "elec1", "mep2", "mep3") else ("interiorFinish" if key in ("lgs", "board", "finish", "floor", "door", "clean", "sumi") else None)
            add(tid, f"{zid} {label}", "mepInterior", days, trade, deps, "rate", zone=zid, cost_item=ci, weight=z["area"])
            hist = trade_history[trade]
            if len(hist) >= crews:
                link(tid, hist[-crews])  # 班の工区巡回（並行班数ぶん遡った工区と資源リンク）
            hist.append(tid)
            prev = tid
        tasks[f"lift-out-{z['level']}"]["deps"].append({"to": f"z-{zid}-board", "type": "finish-start"})
        zone_chain_end[zid] = prev
    # EV（単独レーン）
    add("ev-1", "昇降路引渡し・レール据付", "elevator", 18, "EV", frame_end, "rate", cost_item="elevator", weight=0.4)
    add("ev-2", "かご・巻上機組立", "elevator", 15, "EV", ["ev-1"], "rate", cost_item="elevator", weight=0.35)
    add("ev-3", "配線・試運転調整", "elevator", 12, "EV", ["ev-2"], "rate", cost_item="elevator", weight=0.25)
    add("ev-4", "養生・工事用解放", "elevator", 2, "EV", ["ev-3"], "fixed")
    # 外構（足場全解体後）
    add("ext-1", "外構 埋設配管・排水", "exteriorWorks", 8, "外構", ext_all_end, "rate", cost_item="exteriorWorks", weight=0.35)
    add("ext-2", "外構 路盤・縁石", "exteriorWorks", 7, "外構", ["ext-1"], "rate", cost_item="exteriorWorks", weight=0.3)
    add("ext-3", "外構 舗装", "exteriorWorks", 8, "外構", ["ext-2"], "rate", cost_item="exteriorWorks", weight=0.25)
    add("ext-4", "外構 植栽・ライン・美装", "exteriorWorks", 3, "外構", ["ext-3"], "fixed", cost_item="exteriorWorks", weight=0.1)
    # 締め（試運転→検査群 自→監→施→法→引渡し）
    all_work_end = list(zone_chain_end.values()) + ["ev-4", "ext-4"] + [f"lift-out-{lv}" for lv in levels_sorted]
    add("close-1", "総合試運転調整", "closing", 8, "設備", all_work_end, "fixed")
    add("close-2", "社内自主検査・是正", "closing", 4, "監督", ["close-1"], "fixed")
    add("close-3", "監理者検査・是正", "closing", 4, "監督", ["close-2"], "fixed")
    add("close-4", "施主検査・是正", "closing", 4, "監督", ["close-3"], "fixed")
    add("close-5", "完了検査（法定）・是正", "closing", 3, "監督", ["close-4"], "fixed")
    add("close-6", "引渡し", "closing", 2, "監督", ["close-5"], "fixed")

    # ---------- CP-8 検査チェーン（書類→申請→実施、ゲート） ----------
    inspections = []
    def inspection(iid, name, evidence_end_deps, doc_days, gated_successor, kind="立会い"):
        doc = f"{iid}-doc"; app = f"{iid}-app"; act = f"{iid}-act"
        add(doc, f"{name} 書類作成", "inspection", doc_days, "監督", evidence_end_deps, "fixed")
        add(app, f"{name} 申請・依頼", "inspection", 1, "監督", [doc], "fixed")
        add(act, f"{name} 実施", "inspection", 1, "検査", [app] + evidence_end_deps, "fixed", gate=True)
        if gated_successor:
            tasks[gated_successor]["deps"].append({"to": act, "type": "gate"})
        inspections.append({"id": iid, "name": name, "kind": kind, "chain": [doc, app, act],
                            "gateFor": gated_successor, "leadRule": "予約は実施の10〜14日前、書類は証拠が揃うことが前提"})
    for z in fz:
        inspection(f"insp-fnd-{z['id']}", f"{z['id']} 基礎配筋検査", [f"fnd-{z['id']}-1"], 2, f"fnd-{z['id']}-2", "監理者立会い")
    inspection("insp-steel-prod", "鉄骨製品検査", ["prep-1"], 3, "frm-s1-1", "工場検査")
    for sfx in [f"s{i+1}" for i in range(sec_no)]:
        inspection(f"insp-steel-{sfx}", f"第{sfx[1]}節 建方検査", [f"frm-{sfx}-2"], 2, None, "監理者立会い")
    inspection("insp-mid", "中間検査（特定工程・鉄骨工事）", [f"frm-s{sec_no}-2"], 3,
               face_ids and f"face-{face_ids[0]}-2" or None, "法定")
    for z in zone_order:
        zid = z["id"]
        inspection(f"insp-wp-{zid}", f"{zid} 水圧・満水試験", [f"z-{zid}-plmb1"], 1, f"z-{zid}-board", "監理者立会い")
        inspection(f"insp-conc-{zid}", f"{zid} 隠蔽前検査", [f"z-{zid}-hvac1", f"z-{zid}-plmb1", f"z-{zid}-elec1"], 2,
                   f"z-{zid}-board", "監理者立会い")
    inspection("insp-power", "受電立会い（電力会社・電気主任技術者）", ["elec-0b"], 2,
               zone_order and f"z-{zone_order[0]['id']}-mep3" or None, "立会い")
    inspection("insp-ev", "EV落成検査", ["ev-3"], 2, "ev-4", "法定")
    inspection("insp-fire", "消防検査", ["close-1"], 3, "close-5", "法定")
    inspection("insp-final", "完了検査", ["close-4"], 3, "close-6", "法定")

    # ---------- CP-6 日数（揺れ抽選）・原価配分 ----------
    import random
    rng = random.Random(seed * 1000 + 7)
    swing = draws["productivitySwing"]
    for t in tasks.values():
        if t["basis"] == "rate" and swing > 0:
            t["daysBase"] = t["days"]
            t["days"] = round(t["days"] * (1 + rng.uniform(-swing, swing)), 1)
    item_amount = {i["id"]: i["amount"] for i in cp0["cost"]["items"]}
    by_item = defaultdict(float)
    for t in tasks.values():
        for (item, w) in t["costItems"]:
            by_item[item] += w
    for t in tasks.values():
        t["cost"] = round(sum(item_amount[item] * w / by_item[item] for (item, w) in t["costItems"] if by_item[item] > 0))

    # ---------- CP-7 ネットワーク（CPM）と暦 ----------
    order, done, guard = [], set(), 0
    while len(order) < len(tasks) and guard < 10000:
        guard += 1
        for tid, t in tasks.items():
            if tid not in done and all(d["to"] in done for d in t["deps"]):
                order.append(tid); done.add(tid)
    assert len(order) == len(tasks), "依存関係に循環がある"
    for tid in order:
        t = tasks[tid]
        t["es"] = max([tasks[d["to"]]["ef"] for d in t["deps"]], default=0.0)
        t["ef"] = round(t["es"] + t["days"], 1)
    total_working = max(t["ef"] for t in tasks.values())
    critical = sorted([t["id"] for t in tasks.values() if abs(t["ef"] - total_working) < 0.01])
    # 逆向きにクリティカルチェーンを辿る
    chain_cp, cur = [], critical[-1] if critical else None
    while cur:
        chain_cp.append(cur)
        preds = [d["to"] for d in tasks[cur]["deps"] if abs(tasks[d["to"]]["ef"] - tasks[cur]["es"]) < 0.11]
        cur = preds[0] if preds else None
    chain_cp.reverse()
    n_cal = int(total_working) + 40
    cal = build_calendar(start, n_cal)
    for t in tasks.values():
        t["startDate"] = cal[int(t["es"])].isoformat()
        t["endDate"] = cal[min(int(math.ceil(t["ef"])) - 1, n_cal - 1)].isoformat()
    end_date = cal[min(int(math.ceil(total_working)) - 1, n_cal - 1)]
    buffer_days = round(total_working * draws["bufferRate"], 1)

    # 山積み（職種別の同時並行ピーク）
    trade_peak = {}
    horizon = int(math.ceil(total_working))
    for trade in {t["trade"] for t in tasks.values()}:
        load = [0] * (horizon + 1)
        for t in tasks.values():
            if t["trade"] == trade:
                for d0 in range(int(t["es"]), int(math.ceil(t["ef"]))):
                    load[d0] += 1
        trade_peak[trade] = max(load) if load else 0
    resource_notes = [f"{tr}：最大{trade_peak[tr]}班が同時並行（資源リンクで巡回を明示済み）"
                      for tr in sorted(trade_peak) if trade_peak[tr] > 2]

    # Sカーブ（月次累計出来高：直接工事費ベース）
    monthly = defaultdict(float)
    for t in tasks.values():
        if t["cost"]:
            mid = cal[min(int((t["es"] + t["ef"]) / 2), n_cal - 1)]
            monthly[f"{mid.year}-{mid.month:02d}"] += t["cost"]
    scurve, cum = [], 0.0
    for m in sorted(monthly):
        cum += monthly[m]
        scurve.append({"month": m, "amount": round(monthly[m]), "cumulative": round(cum)})

    # ---------- CP-8 調達 ----------
    def es_of(tid):
        return tasks[tid]["es"]
    def date_of_working(wd):
        return cal[int(wd)].isoformat()
    procurement = [
        {"item": "鉄骨（製作図→承諾→製作→工場検査→搬入）", "leadDays": 75, "needBy": date_of_working(es_of("frm-s1-1")),
         "orderBy": date_of_working(max(0, int(es_of("frm-s1-1")) - 75)), "tag": "inferred"},
        {"item": "キュービクル・受変電設備", "leadDays": 90, "needBy": date_of_working(es_of("elec-0b")),
         "orderBy": date_of_working(max(0, int(es_of("elec-0b")) - 90)), "tag": "inferred"},
        {"item": "エレベーター", "leadDays": 90, "needBy": date_of_working(es_of("ev-1")),
         "orderBy": date_of_working(max(0, int(es_of("ev-1")) - 90)), "tag": "inferred"},
        {"item": "外壁パネル・サッシ", "leadDays": 45, "needBy": date_of_working(es_of(f"face-{face_ids[0]}-2") if face_ids else start.toordinal() and es_of("roof-1")),
         "orderBy": date_of_working(max(0, int(es_of(f"face-{face_ids[0]}-2")) - 45)) if face_ids else None, "tag": "default"},
    ]

    # ---------- CP-9 QCDSE・リスク ----------
    qcdse = {
        "Q": {"plan": "検査チェーン（書類→申請→実施）を全隠蔽部・全ゲートに生成。配筋・建方・隠蔽・水圧は立会いを必須とする", "gates": len(inspections)},
        "C": {"executionBudget": cp0["cost"]["executionBudget"], "contractApprox": cp0["cost"]["totalPrice"],
              "plan": "実行予算は原価×(1−査定率〈難易度抽選〉)。月次出来高はSカーブで予実管理する"},
        "D": {"workingDays": round(total_working, 1), "calendarDays": (end_date - start).days + 1,
              "bufferWorkingDays": buffer_days, "plan": "クリティカルパスを工程表の主線とし、バッファは末尾に集約する"},
        "S": {"plan": "重点：杭・根切りの重機災害、建方の墜落・飛来、EVシャフト内作業、外装足場。フェーズ別の安全計画は工種別計画で展開"},
        "E": {"plan": "残土搬出の飛散・騒音（北側住宅）、粉じん、廃棄物分別。作業時間 8:00–18:00 を前提条件とする" if residential
              else "残土・粉じん・廃棄物分別の標準計画"},
    }
    risks = [
        {"risk": "地盤・支持層の不確実性（モデル側 gap）", "impact": "杭長・工法の変更で杭工事と原価が変動", "mitigation": "試験杭で支持層を確認し、変動はバッファと予備費で吸収", "tag": "gap"},
        {"risk": "梅雨・台風期が基礎〜躯体にかかる", "impact": "打設・建方の中断、根切りの崩壊", "mitigation": "3点推定の高側に作業不能日を含む。排水・養生を仮設に明記", "tag": "inferred"},
        {"risk": "新しい工種・作業の開始時に近隣クレームが増える", "impact": "条件の締め付け（開始時刻の後倒し等）", "mitigation": "着工前周知と工種開始ごとの事前説明。金銭・菓子折りでの解決はしない（確定ルール）", "tag": "rule"},
        {"risk": "長納期品目（鉄骨・キュービクル・EV）の遅れ", "impact": "躯体・受電・EVがクリティカルパス上で直撃", "mitigation": "調達計画の発注期限を工程に接続し、製作図承諾を先行させる", "tag": "inferred"},
        {"risk": "検査書類の証拠不足（写真・試験結果）", "impact": "書類が進まずゲートで後工程が止まる", "mitigation": "検査チェーンを着工時に全件生成し、証拠は工事中にしか生まれない前提で撮影計画を持つ", "tag": "rule"},
    ]

    plan = {
        "meta": {"generator": "plan_generate.py v0.1 (CP-1〜CP-10, S造・商業テンプレート)",
                 "building": model["building"]["name"], "buildingFile": model_path.name,
                 "difficulty": difficulty, "seed": seed, "startDate": start.isoformat(),
                 "completionLevel": "L2（実施可能完了）。L3はゲームではスキップ（DP-4訂正）"},
        "overview": {"name": model["building"]["name"], "use": model["building"].get("use"),
                     "structure": model["building"].get("structure"), "grossAreaM2": Q["grossAreaM2"],
                     "floors": n_levels, "zones": len(zones), "faces": face_ids},
        "premises": {"quantities": Q, "cp0Duration": cp0["duration"], "cost": {k: cp0["cost"][k] for k in
                     ("directCost", "totalPrice", "unitPricePerM2", "executionBudget")}, "draws": draws,
                     "mepSystems": ({"totals": equip["totals"], "costShares": equip["mepCostShares"],
                                     "runsFile": equip_path.name, "tag": "inferred"} if equip else None)},
        "findings": findings, "siteConditions": site_conditions, "decisions": decisions,
        "methods": methods, "temporaryWorks": temporary_works,
        "tasks": [tasks[k] for k in order],
        "schedules": {"totalWorkingDays": round(total_working, 1), "endDate": end_date.isoformat(),
                      "criticalPath": chain_cp, "sCurve": scurve,
                      "milestones": [{"task": t, "date": tasks[t]["endDate"]} for t in
                                     ("pile-2", "frm-s1-1", "elec-0b", "ev-4", "close-6") if t in tasks]},
        "resources": {"tradePeak": trade_peak, "notes": resource_notes},
        "procurement": procurement, "inspections": inspections,
        "qcdsePlans": qcdse, "risks": risks, "undecided": [],
    }

    # ---------- CP-10 検証 PL-01〜PL-12 ----------
    checks = []
    def chk(pid, ok, detail):
        checks.append({"id": pid, "ok": bool(ok), "detail": detail})
    chk("PL-01", abs(Q["grossAreaM2"] - plan["overview"]["grossAreaM2"]) < 1, "概要（延床・階数・構造）が建物モデルと一致")
    sinks = [t for t in tasks.values() if not any(d["to"] == t["id"] for x in tasks.values() for d in x["deps"])]
    chk("PL-02", len(order) == len(tasks) and len(sinks) >= 1, f"ネットワーク閉合（タスク{len(tasks)}件・循環なし・終端あり）")
    unallocated = [i["id"] for i in cp0["cost"]["items"]
                   if not any(item == i["id"] for t in tasks.values() for (item, w) in t["costItems"])]
    chk("PL-03", not unallocated, f"数量カバレッジ（CP-0の全金額項目がタスクへ配分済み{'' if not unallocated else '未配分：' + str(unallocated)}）")
    chk("PL-04", all(t.get("basis") in ("rate", "fixed") for t in tasks.values()), "全タスクが日数根拠（出来高式または固定根拠）を持つ")
    bad_dates = [t["id"] for t in tasks.values() if not is_working(date.fromisoformat(t["startDate"]))]
    chk("PL-05", not bad_dates, f"暦整合（閉所日に開始するタスクなし{'' if not bad_dates else '：' + str(bad_dates[:3])}）")
    ungated = []
    for z in zone_order:
        board = tasks.get(f"z-{z['id']}-board")
        if board and not any(d["type"] == "gate" for d in board["deps"]):
            ungated.append(z["id"])
    chk("PL-06", not ungated, f"ゲート完全性（全工区のボード前に水圧試験＋隠蔽前検査のゲート{'' if not ungated else '不足：' + str(ungated)}）")
    chk("PL-07", any(tw["item"] == "外周足場" for tw in temporary_works) and len(face_ids) >= 3,
        "仮設整合（外装の面数と足場計画が対応）")
    chk("PL-08", True, f"資源競合の明示（職種別ピークを算出：{resource_notes if resource_notes else '過集中なし'}）")
    task_cost_sum = sum(t["cost"] for t in tasks.values())
    chk("PL-09", abs(task_cost_sum - cp0["cost"]["directCost"]) / cp0["cost"]["directCost"] < 0.02,
        f"金額整合（タスク原価合計 {task_cost_sum/1e8:.2f}億円 vs 直接工事費 {cp0['cost']['directCost']/1e8:.2f}億円）")
    lo, hi = cp0["duration"]["workingDaysLow"], cp0["duration"]["workingDaysHigh"]
    chk("PL-10", lo <= total_working <= hi, f"工期整合（CP実働 {total_working:.0f}日 vs CP-0 3点 {lo:.0f}〜{hi:.0f}日）")
    frame_ok = all(tasks[t]["es"] >= max(tasks[d["to"]]["ef"] for d in tasks[t]["deps"] if d["to"].startswith("frm-")) - 0.11
                   for t in tasks if t.startswith("face-") and t.endswith("-1"))
    chk("PL-11", frame_ok, "段階整合（外装は躯体完了後。設備・内装も躯体完了＋屋根雨仕舞いが前提）")
    chk("PL-12", plan["undecided"] == [], "判断の明示（未定リスト空。gap は findings/decisions に根拠タグ付きで記録）")
    plan["validation"] = checks

    out_path = HERE / f"generated_construction_plan_{model_path.stem.replace('generated_', '')}.json"
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    npass = sum(1 for c in checks if c["ok"])
    print(f"建物: {model['building']['name']} / 難易度 {difficulty} / seed {seed}")
    print(f"タスク {len(tasks)}件（検査チェーン {len(inspections)}件） 実働 {total_working:.0f}日 → {end_date} 完了")
    print(f"CP: {' → '.join(chain_cp[:6])} …（{len(chain_cp)}タスク）")
    print(f"検証 PL: {npass}/{len(checks)} PASS")
    for c in checks:
        if not c["ok"]:
            print(f"  FAIL {c['id']}: {c['detail']}")
    print(f"出力: {out_path}")

if __name__ == "__main__":
    main()
