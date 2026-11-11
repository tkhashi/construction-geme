#!/usr/bin/env python3
"""複数棟の近接グルーピング：GeoJSON の建物群を棟間距離でクラスタリングし、
団地のような複合（Complex）として扱えるようにする。

使い方:
  python3 group_buildings.py <geojson> [threshold_m] [--complex <out.json>]

--complex を付けると、最大グループについて各棟を変換＋シード版マンション生成し、
Complex ファイル（複数建物＋リンク）を書き出す。"""
import json, sys
sys.path.insert(0, "../hidden_files/source_extracts/footprint_samples")
from footprint_to_plate import project, convert  # noqa: E402
from shapely.geometry import shape  # noqa: E402
import generate_building  # noqa: E402


def group_features(feats, threshold_m):
    polys = []
    for f in feats:
        g = shape(f["geometry"])
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        polys.append(project(g))
    parent = list(range(len(feats)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            if polys[i].distance(polys[j]) <= threshold_m:
                pi, pj = find(i), find(j)
                if pi != pj:
                    parent[pi] = pj
    groups = {}
    for i in range(len(feats)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True), polys


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0]
    threshold = float(args[1]) if len(args) > 1 else 30.0
    complex_out = None
    if "--complex" in sys.argv:
        complex_out = sys.argv[sys.argv.index("--complex") + 1]
    fc = json.load(open(path, encoding="utf-8"))
    feats = fc["features"]
    groups, polys = group_features(feats, threshold)
    print(f"buildings={len(feats)} threshold={threshold}m groups={len(groups)}")
    for gi, g in enumerate(groups):
        names = [feats[i].get("properties", {}).get("name") or f"#{i}" for i in g]
        print(f"  group {gi}: {len(g)} buildings: {names[:6]}{'...' if len(names) > 6 else ''}")
    if complex_out:
        g = list(groups[0])
        max_b = 8
        if "--max-buildings" in sys.argv:
            max_b = int(sys.argv[sys.argv.index("--max-buildings") + 1])
        if len(g) > max_b:
            g = sorted(g, key=lambda i: -polys[i].area)[:max_b]
            print(f"  complex build capped to the {max_b} largest buildings of the group")
        buildings = []
        for k, i in enumerate(g):
            conv = convert(feats[i], f"{path}#{i}")
            if conv["plate"]["cells"] < 15:
                print(f"  skip #{i}: plate too small ({conv['plate']['cells']} cells)")
                continue
            props = feats[i].get("properties", {})
            ann = {"buildingName": props.get("name") or f"団地棟{k+1}"}
            buildings.append(generate_building.annotate_cores_and_openings(
                generate_building.gen_seeded_mansion(conv, ann, bid=f"bldg:danchi-{k+1}")))
            print(f"  built bldg:danchi-{k+1} from feature #{i} "
                  f"(cells={conv['plate']['cells']}, rooms={len(buildings[-1]['rooms'])})")
        xs = [p.bounds[0] for p in polys] + [p.bounds[2] for p in polys]
        ys = [p.bounds[1] for p in polys] + [p.bounds[3] for p in polys]
        doc = {"complex": {"id": "complex:danchi", "name": "生成：団地（近接グルーピング）",
                           "links": [{"id": f"link:{k}", "from": buildings[k]["building"]["id"],
                                      "to": buildings[k + 1]["building"]["id"], "kind": "団地内通路"}
                                     for k in range(len(buildings) - 1)]},
               "site": {"polygon": [[min(xs) - 20000, min(ys) - 20000], [max(xs) + 20000, min(ys) - 20000],
                                    [max(xs) + 20000, max(ys) + 20000], [min(xs) - 20000, max(ys) + 20000]],
                        "buildingPlacement": {"origin": [0, 0], "rotationDeg": 0},
                        "roads": [{"edge": "south", "name": "前面道路", "width": 8000}],
                        "gates": [], "neighbors": [{"edge": "south", "type": "道路"}]},
               "buildings": buildings}
        with open(complex_out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        print("wrote", complex_out, "buildings:", len(buildings))


if __name__ == "__main__":
    main()
