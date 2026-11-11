#!/usr/bin/env python3
"""工事計画 → 本編ゲーム形式への変換器（統合手前）。

DP-1 の換算（実働日 → ゲーム日）を表示・進行層として実装する。
計画 JSON は書き換えず、ゲーム形式の別ファイルを出す。検証付き。

使い方：python3 plan_to_game.py <計画JSON> [durationScale=7]
"""
import json, math, sys
from pathlib import Path

HERE = Path(__file__).parent

def main():
    plan_path = Path(sys.argv[1])
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0
    plan = json.loads(plan_path.read_text())
    tasks = {t["id"]: t for t in plan["tasks"]}

    def gstart(t):
        return int(t["es"] // scale) + 1
    def gend(t):
        return max(gstart(t), math.ceil(t["ef"] / scale))

    insp_by_task = {}
    for ins in plan["inspections"]:
        for tid in ins["chain"]:
            insp_by_task[tid] = ins["id"]
    out_tasks = []
    for t in plan["tasks"]:
        out_tasks.append({
            "id": t["id"], "name": t["name"], "phase": t["phase"], "zone": t["zone"], "trade": t["trade"],
            "gameStart": gstart(t), "gameEnd": gend(t),
            "realWorkingDays": t["days"], "cost": t["cost"],
            "gate": t["gate"], "inspectionId": insp_by_task.get(t["id"]),
            "deps": [{"to": d["to"], "type": d["type"]} for d in t["deps"]],
        })
    game_tasks = {t["id"]: t for t in out_tasks}

    # 検証
    errors = []
    for ins in plan["inspections"]:
        if len(ins["chain"]) != 3:
            errors.append(f"検査チェーンが3段でない: {ins['id']}")
        if ins["gateFor"] and ins["gateFor"] not in tasks:
            errors.append(f"ゲート先が存在しない: {ins['id']} → {ins['gateFor']}")
    for t in out_tasks:
        for d in t["deps"]:
            p = game_tasks[d["to"]]
            if t["gameStart"] < p["gameStart"] or t["gameEnd"] < p["gameEnd"]:
                errors.append(f"依存の単調性が崩れた: {p['id']} → {t['id']}")
    total_game = max(t["gameEnd"] for t in out_tasks)
    expect = math.ceil(plan["schedules"]["totalWorkingDays"] / scale)
    if total_game != expect:
        errors.append(f"最終ゲーム日 {total_game} ≠ 期待 {expect}")

    out = {
        "meta": {"converter": "plan_to_game.py v0.1", "sourcePlan": plan_path.name,
                 "building": plan["meta"]["building"], "durationScale": scale,
                 "difficulty": plan["meta"]["difficulty"], "seed": plan["meta"]["seed"],
                 "note": "計画は実日数で保持し、換算はこの層でのみ行う（DP-1）"},
        "premises": plan["premises"],
        "tasks": out_tasks,
        "inspections": plan["inspections"],
        "milestones": [{"task": m["task"], "gameDay": gend(tasks[m["task"]])} for m in plan["schedules"]["milestones"]],
        "totalGameDays": total_game,
        "validation": {"ok": not errors, "errors": errors},
    }
    stem = plan_path.stem.replace("generated_construction_plan_", "")
    out_path = HERE / "integration" / f"generated_game_schedule_{stem}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"建物: {plan['meta']['building']}  scale={scale:g} → 全 {total_game} ゲーム日 / タスク {len(out_tasks)}件")
    print(f"検証: {'PASS' if not errors else 'FAIL ' + str(errors[:3])}")
    print(f"出力: {out_path}")

if __name__ == "__main__":
    main()
