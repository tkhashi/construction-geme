#!/usr/bin/env python3
"""計画の後処理：フロート計算・山崩し提案・ローリング詳細化（3ヶ月／1ヶ月工程）。

入力は plan_generate.py の出力（generated_construction_plan_*.json）。
元の計画は書き換えず、提案と詳細化を別ファイルに出す。

- 山崩し：職種ごとの同時並行数が上限（班数）を超える日を検出し、フロートの
  範囲内で開始を後ろ倒しする提案を作る。提案を適用しても総工期が伸びない
  ことを再計算で確認したものだけを「適用可能」とする。
- 3ヶ月工程：着工から90暦日の窓。週別の山積みと窓内タスク、検査の申請期限。
  作成主体は所長＋課長（確定した役割分担）。
- 1ヶ月工程：着工から30暦日の日別リストと担当者のTODO（書類・申請・発注期限）。
  作成は担当者、チェックは課長（確定した役割分担）。

使い方：python3 plan_postprocess.py <計画JSON>
"""
import json, math, sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
CREW_CAPS = {"監督": 8, "検査": 3, "基礎": 3, "鉄骨": 2, "鳶": 2, "外装": 2, "土工": 2, "杭": 2}
DEFAULT_CAP = 2

def cap_of(trade):
    return CREW_CAPS.get(trade, DEFAULT_CAP)

def forward(tasks, delays):
    """delays: {taskId: 追加の開始遅延（実働日）} を入れて CPM を再計算する"""
    order, done = [], set()
    while len(order) < len(tasks):
        progressed = False
        for tid, t in tasks.items():
            if tid not in done and all(d["to"] in done for d in t["deps"]):
                order.append(tid); done.add(tid); progressed = True
        if not progressed:
            raise ValueError("循環")
    es, ef = {}, {}
    for tid in order:
        t = tasks[tid]
        es[tid] = max([ef[d["to"]] for d in t["deps"]], default=0.0) + delays.get(tid, 0.0)
        ef[tid] = es[tid] + t["days"]
    return es, ef, max(ef.values())

def main():
    plan_path = Path(sys.argv[1])
    plan = json.loads(plan_path.read_text())
    tasks = {t["id"]: t for t in plan["tasks"]}
    total = plan["schedules"]["totalWorkingDays"]
    horizon = int(math.ceil(total)) + 2

    # ---- フロート（後方パス） ----
    succ = defaultdict(list)
    for t in tasks.values():
        for d in t["deps"]:
            succ[d["to"]].append(t["id"])
    lf, ls = {}, {}
    for tid in reversed([t["id"] for t in plan["tasks"]]):
        lf[tid] = min([ls[s] for s in succ[tid]], default=total)
        ls[tid] = lf[tid] - tasks[tid]["days"]
    for t in tasks.values():
        t["float"] = round(ls[t["id"]] - t["es"], 1)

    # ---- 山崩し ----
    def loads(es, ef):
        per = defaultdict(lambda: [0] * horizon)
        for tid, t in tasks.items():
            for d0 in range(int(es[tid]), min(int(math.ceil(ef[tid])), horizon)):
                per[t["trade"]][d0] += 1
        return per
    es0 = {t["id"]: t["es"] for t in tasks.values()}
    ef0 = {t["id"]: t["ef"] for t in tasks.values()}
    per0 = loads(es0, ef0)
    overloads = []
    for trade, arr in per0.items():
        over_days = [i for i, v in enumerate(arr) if v > cap_of(trade)]
        if over_days:
            overloads.append({"trade": trade, "cap": cap_of(trade), "peak": max(arr),
                              "overDays": len(over_days), "firstOverDay": over_days[0]})
    proposals = []
    delays = {}
    es_c, ef_c, total_c = es0, ef0, total
    for ov in sorted(overloads, key=lambda o: -o["overDays"]):
        trade = ov["trade"]
        cands = [t for t in tasks.values() if t["trade"] == trade and t["float"] >= 1]
        cands.sort(key=lambda t: -t["float"])
        for t in cands:
            arr = loads(es_c, ef_c)[trade]
            if max(arr) <= cap_of(trade):
                break
            shift = min(t["float"], 10.0)
            trial = dict(delays); trial[t["id"]] = trial.get(t["id"], 0.0) + shift
            es_t, ef_t, total_t = forward(tasks, trial)
            arr_t = loads(es_t, ef_t)[trade]
            if total_t <= total + 0.11 and max(arr_t) < max(arr):
                delays = trial; es_c, ef_c, total_c = es_t, ef_t, total_t
                proposals.append({"task": t["id"], "name": t["name"], "trade": trade,
                                    "shiftWorkingDays": shift, "floatUsed": t["float"],
                                    "effect": f"{trade}のピーク {max(arr)}→{max(arr_t)}班",
                                    "cpImpact": round(total_t - total, 1)})
    per1 = loads(es_c, ef_c)
    leveling = {
        "caps": {"default": DEFAULT_CAP, "byTrade": CREW_CAPS},
        "overloadsBefore": overloads,
        "proposals": proposals,
        "peaksAfter": {tr: max(arr) for tr, arr in per1.items() if max(arr) > 0},
        "totalWorkingDaysAfter": round(total_c, 1),
        "note": "提案はフロート範囲内の後ろ倒しのみ。適用しても総工期が伸びないことを再計算で確認済み。"
                "フロートで解消できない過集中（クリティカルなタスクの重なり）は peaksAfter に残り、増班か工順変更の判断事項になる",
    }

    # ---- ローリング詳細化 ----
    start = date.fromisoformat(plan["meta"]["startDate"])
    def in_window(t, days):
        s = date.fromisoformat(t["startDate"]); e = date.fromisoformat(t["endDate"])
        return s < start + timedelta(days=days) and e >= start
    def app_deadlines(window_days):
        out = []
        for ins in plan["inspections"]:
            doc, app, act = (tasks[i] for i in ins["chain"])
            if in_window(act, window_days) or in_window(app, window_days):
                out.append({"inspection": ins["name"], "applyBy": app["startDate"],
                            "implementOn": act["startDate"], "gateFor": ins["gateFor"]})
        return sorted(out, key=lambda x: x["applyBy"])
    w3 = [t for t in plan["tasks"] if in_window(t, 90)]
    weekly = defaultdict(lambda: defaultdict(int))
    for t in w3:
        s = date.fromisoformat(t["startDate"])
        week = (s - start).days // 7 + 1
        weekly[week][t["trade"]] += 1
    three_month = {
        "window": {"from": start.isoformat(), "to": (start + timedelta(days=90)).isoformat()},
        "createdBy": "所長＋課長（確定した役割分担）", "taskCount": len(w3),
        "tasks": [{"id": t["id"], "name": t["name"], "start": t["startDate"], "end": t["endDate"],
                   "trade": t["trade"], "float": t.get("float")} for t in w3],
        "weeklyLoad": {str(k): dict(v) for k, v in sorted(weekly.items())},
        "applicationDeadlines": app_deadlines(90),
        "procurementDeadlines": [{"item": p["item"], "orderBy": p["orderBy"]} for p in plan["procurement"]
                                 if date.fromisoformat(p["orderBy"]) < start + timedelta(days=90)],
    }
    w1 = [t for t in plan["tasks"] if in_window(t, 30)]
    daily = defaultdict(list)
    for t in w1:
        daily[t["startDate"]].append({"id": t["id"], "name": t["name"], "type": "開始"})
        daily[t["endDate"]].append({"id": t["id"], "name": t["name"], "type": "終了"})
    todos = []
    for t in w1:
        if "書類作成" in t["name"]:
            todos.append({"date": t["startDate"], "todo": f"{t['name']}（証拠の収集状況を確認してから着手）", "owner": "担当者"})
        if "申請・依頼" in t["name"]:
            todos.append({"date": t["startDate"], "todo": f"{t['name']}（期限厳守）", "owner": "担当者"})
    for p in plan["procurement"]:
        if date.fromisoformat(p["orderBy"]) < start + timedelta(days=30):
            todos.append({"date": p["orderBy"], "todo": f"発注期限：{p['item']}", "owner": "担当者（手配）"})
    one_month = {
        "window": {"from": start.isoformat(), "to": (start + timedelta(days=30)).isoformat()},
        "createdBy": "担当者", "checkedBy": "課長（確定した役割分担。課長繁忙度がチェック速度を決める）",
        "taskCount": len(w1), "daily": {k: v for k, v in sorted(daily.items())},
        "todos": sorted(todos, key=lambda x: x["date"]),
        "applicationDeadlines": app_deadlines(30),
    }

    out = {"meta": {"generator": "plan_postprocess.py v0.1", "sourcePlan": plan_path.name,
                    "building": plan["meta"]["building"]},
           "leveling": leveling, "threeMonthSchedule": three_month, "oneMonthSchedule": one_month}
    stem = plan_path.stem.replace("generated_construction_plan_", "")
    out_path = HERE / f"generated_plan_detail_{stem}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"建物: {plan['meta']['building']}")
    print(f"山崩し: 過集中 {len(overloads)}職種 → 提案 {len(proposals)}件（適用後も総工期 {total_c:.0f}日）")
    for ov in overloads:
        print(f"  {ov['trade']}: ピーク{ov['peak']}班（上限{ov['cap']}）が{ov['overDays']}日")
    print(f"3ヶ月工程: タスク {len(w3)}件・申請期限 {len(three_month['applicationDeadlines'])}件 / 1ヶ月工程: タスク {len(w1)}件・TODO {len(todos)}件")
    print(f"出力: {out_path}")

if __name__ == "__main__":
    main()
