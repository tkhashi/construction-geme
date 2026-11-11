#!/usr/bin/env python3
"""建物モデル JSON → 平面図 SVG レンダラー（試作）。
使い方: python3 render_plan.py <model.json> <level_id> [building_id] [out.svg]
モデル由来の情報だけを描く：通り芯・寸法チェーン・柱・壁（開口で切る）・室名＋派生面積・シャフト。"""
import json, sys

COLORS = {
    "テナント": "#FFF3CD", "飲食": "#FFE0B2", "モール": "#D6EAF8", "吹抜け": "#FADBD8",
    "コアホール": "#D5D8DC", "WC": "#D1F2EB", "バックヤード": "#D5F5E3", "防災センター": "#F5B7B1",
    "住戸": "#FFF9C4", "共用廊下": "#ECEFF1", "集会室": "#E1BEE7", "管理室": "#C5CAE9",
    "エントランス": "#B2DFDB", "コンコース": "#D6EAF8", "待合室": "#FEF9E7", "駅事務室": "#F9E79F",
    "機械室": "#D5D8DC", "コア": "#D5D8DC",
}
DOORS = {"片開き戸", "両開き戸", "引戸", "シャッター"}

def load(path, building_id=None):
    data = json.load(open(path, encoding="utf-8"))
    if "buildings" in data:
        for b in data["buildings"]:
            if building_id is None or b["building"]["id"] == building_id:
                return b, data.get("site", {})
        raise SystemExit(f"building not found: {building_id}")
    return data, data.get("site", {})

def render(m, level_id, site=None):
    X = {a["name"]: a["offset"] for a in m["grid"]["axesX"]}
    Y = {a["name"]: a["offset"] for a in m["grid"]["axesY"]}
    Xn = [a["name"] for a in m["grid"]["axesX"]]
    Yn = [a["name"] for a in m["grid"]["axesY"]]
    W, D = X[Xn[-1]], Y[Yn[-1]]
    MX, MY = 9000, 9000  # 余白（寸法チェーン・通り符号用）
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-MX} {-MY} {W + 2 * MX} {D + 2 * MY}" '
             f'width="{(W + 2 * MX) / 40:.0f}" height="{(D + 2 * MY) / 40:.0f}" font-family="sans-serif">',
             '<rect x="-9000" y="-9000" width="100%" height="100%" fill="white"/>',
             '<defs><pattern id="hatch" width="900" height="900" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             '<rect width="900" height="900" fill="#EAEDED"/><line x1="0" y1="0" x2="0" y2="900" stroke="#95A5A6" stroke-width="160"/></pattern></defs>']
    def Yf(y):  # SVG は y 下向き：北を上にするため反転
        return D - y
    # 室
    for r in m["rooms"]:
        if r["level"] != level_id:
            continue
        c = r["cells"]
        x0, x1 = X[c["xFrom"]], X[c["xTo"]]
        y0, y1 = Yf(Y[c["yTo"]]), Yf(Y[c["yFrom"]])
        area = (x1 - x0) * (Y[c["yTo"]] - Y[c["yFrom"]]) / 1e6
        col = COLORS.get(r["use"], "#F2F3F4")
        dash = ' stroke-dasharray="700 400"' if r["use"] == "吹抜け" else ""
        parts.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{col}" stroke="#BDC3C7" stroke-width="60"{dash}/>')
        fs = 620 if (x1 - x0) >= 6000 and (y1 - y0) >= 4000 else 480
        parts.append(f'<text x="{(x0 + x1) / 2}" y="{(y0 + y1) / 2 - 60}" font-size="{fs}" text-anchor="middle" fill="#1B2631">{r["name"]}</text>')
        parts.append(f'<text x="{(x0 + x1) / 2}" y="{(y0 + y1) / 2 + fs}" font-size="{int(fs * 0.8)}" text-anchor="middle" fill="#5D6D7E">{area:.0f}㎡</text>')
    # シャフト（この階を通るもの）
    for s in m.get("shafts", []):
        if level_id not in s["levelRange"]:
            continue
        f = s["footprint"]
        y0 = Yf(f["y"] + f["d"])
        parts.append(f'<rect x="{f["x"]}" y="{y0}" width="{f["w"]}" height="{f["d"]}" fill="url(#hatch)" stroke="#616A6B" stroke-width="70"/>')
        if f["w"] >= 1800 and f["d"] >= 1400:
            parts.append(f'<text x="{f["x"] + f["w"] / 2}" y="{y0 + f["d"] / 2 + 220}" font-size="560" text-anchor="middle" fill="#1B2631">{s["kind"]}</text>')
    # 壁と開口
    def wall_span(w):
        ln = w["line"]
        if ln["axis"].startswith("Y"):
            return X[ln["from"]], X[ln["to"]] - X[ln["from"]]
        return Y[ln["from"]], Y[ln["to"]] - Y[ln["from"]]
    for w in m["walls"]:
        if w["level"] != level_id:
            continue
        ln = w["line"]
        start, length = wall_span(w)
        horiz = ln["axis"].startswith("Y")
        fixed = Y[ln["axis"]] if horiz else X[ln["axis"]]
        lw = 210 if w["kind"] in ("外壁", "シャフト壁", "戸境") else 110
        segs = [(0, length)]
        for o in w["openings"]:
            a, b = o["offsetFromStart"], o["offsetFromStart"] + o["width"]
            nxt = []
            for s0, s1 in segs:
                if b <= s0 or a >= s1:
                    nxt.append((s0, s1))
                else:
                    if a > s0:
                        nxt.append((s0, a))
                    if b < s1:
                        nxt.append((b, s1))
            segs = nxt
        def pt(t):
            return (start + t, Yf(fixed)) if horiz else (fixed, Yf(start + t))
        for s0, s1 in segs:
            (ax, ay), (bx, by) = pt(s0), pt(s1)
            parts.append(f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="#1B2631" stroke-width="{lw}"/>')
        for o in w["openings"]:
            a = o["offsetFromStart"]
            ax, ay = pt(a)
            if o["kind"] in DOORS:
                leaf = o["width"]
                if horiz:
                    parts.append(f'<line x1="{ax}" y1="{ay}" x2="{ax}" y2="{ay - leaf}" stroke="#1B2631" stroke-width="60"/>')
                    parts.append(f'<path d="M {ax} {ay - leaf} A {leaf} {leaf} 0 0 1 {ax + leaf} {ay}" fill="none" stroke="#808B96" stroke-width="45"/>')
                else:
                    parts.append(f'<line x1="{ax}" y1="{ay}" x2="{ax + leaf}" y2="{ay}" stroke="#1B2631" stroke-width="60"/>')
                    parts.append(f'<path d="M {ax + leaf} {ay} A {leaf} {leaf} 0 0 1 {ax} {ay - leaf}" fill="none" stroke="#808B96" stroke-width="45"/>')
    # 柱（この階のプレートに接する交点だけ：プレート外には柱は立たない。
    # 構造軸/補助軸の分離があるモデルでは構造軸の交点のみ、柱例外の位置は描かない）
    plate_cells = set()
    for r in m["rooms"]:
        if r["level"] != level_id:
            continue
        c = r["cells"]
        for i in range(Xn.index(c["xFrom"]), Xn.index(c["xTo"])):
            for j in range(Yn.index(c["yFrom"]), Yn.index(c["yTo"])):
                plate_cells.add((i, j))
    sax_r = set(m["grid"].get("structuralAxesX") or Xn)
    say_r = set(m["grid"].get("structuralAxesY") or Yn)
    exc_r = {e["at"] for e in m["grid"].get("columnExceptions", []) if level_id in e.get("levels", [])}
    for ii, xn in enumerate(Xn):
        for jj, yn in enumerate(Yn):
            if xn not in sax_r or yn not in say_r or f"{xn}-{yn}" in exc_r:
                continue
            if any((ii + di, jj + dj) in plate_cells for di in (-1, 0) for dj in (-1, 0)):
                parts.append(f'<rect x="{X[xn] - 350}" y="{Yf(Y[yn]) - 350}" width="700" height="700" fill="#1B2631"/>')
    # 通り芯・符号・寸法チェーン
    for xn in Xn:
        parts.append(f'<line x1="{X[xn]}" y1="{-4500}" x2="{X[xn]}" y2="{D + 2500}" stroke="#A93226" stroke-width="35" stroke-dasharray="1600 300 260 300"/>')
        parts.append(f'<circle cx="{X[xn]}" cy="{-5800}" r="1050" fill="white" stroke="#1B2631" stroke-width="60"/>')
        parts.append(f'<text x="{X[xn]}" y="{-5450}" font-size="950" text-anchor="middle" fill="#1B2631">{xn}</text>')
    for yn in Yn:
        parts.append(f'<line x1="{-4500}" y1="{Yf(Y[yn])}" x2="{W + 2500}" y2="{Yf(Y[yn])}" stroke="#A93226" stroke-width="35" stroke-dasharray="1600 300 260 300"/>')
        parts.append(f'<circle cx="{-5800}" cy="{Yf(Y[yn])}" r="1050" fill="white" stroke="#1B2631" stroke-width="60"/>')
        parts.append(f'<text x="{-5800}" y="{Yf(Y[yn]) + 350}" font-size="950" text-anchor="middle" fill="#1B2631">{yn}</text>')
    for i in range(len(Xn) - 1):
        a, b = X[Xn[i]], X[Xn[i + 1]]
        parts.append(f'<text x="{(a + b) / 2}" y="{-1600}" font-size="800" text-anchor="middle" fill="#1B2631">{b - a:,}</text>')
    for j in range(len(Yn) - 1):
        a, b = Y[Yn[j]], Y[Yn[j + 1]]
        parts.append(f'<text x="{-1600}" y="{Yf((a + b) / 2) + 280}" font-size="800" text-anchor="end" fill="#1B2631">{b - a:,}</text>')
    lvl_name = next(l["name"] for l in m["levels"] if l["id"] == level_id)
    parts.append(f'<text x="{W / 2}" y="{D + 6200}" font-size="1100" text-anchor="middle" fill="#1B2631">{m["building"]["name"]}　{lvl_name} 平面図</text>')
    parts.append('</svg>')
    return "\n".join(parts)

if __name__ == "__main__":
    path, level_id = sys.argv[1], sys.argv[2]
    building_id = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    out = sys.argv[4] if len(sys.argv) > 4 else f"plan_{level_id}.svg"
    m, site = load(path, building_id)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(m, level_id, site))
    print(f"wrote {out}")
