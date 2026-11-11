# 新しい建物を生成するデータフロー（現状）

最終更新：2026-11-10。入口は2系統（実在建物のシード生成／架空建物のパラメトリック生成）＋複合化。定義の正は BUILDING_MODEL_SCHEMA、ルールの正は USE_RULES、内側の決め方は INTERIOR_MODEL_V2。

## A. 実在建物（シード生成）— 主経路

| # | 工程 | 入力 → 出力 | 担い手 |
|---|---|---|---|
| 0 | ソース取得 | PLATEAU（Flateau GeoParquet、PDL 1.0）を第一選択、OSM（Overpass）を補完 → 建物の外形ポリゴン＋属性（地上階数タグ等）。全て無料（有料APIは使わない） | 調査 |
| 1 | 変換 | `footprint_samples/footprint_to_plate.py`：ポリゴン → 主軸推定 → 主軸へ回転 → グリッドセル化（スパン候補を総当たりしポリゴンとの IoU が最大のものを選択、孤立セル・非最大断片を除去）→ conversion JSON（`source_properties`／`original_polygon`〔面積・矩形度〕／`orientation`〔実方位〕／`grid`〔スパン・軸〕／`footprint`〔セル範囲〕／`plate`〔セル数・IoU〕） | 自動 |
| 2 | 注釈（annotation） | conversion ＋ フロアガイド／駅構内図／施設概要／全体像調査 → `model/seed_annotations_<建物>.json`。中身は L2/L3 の事実シード：`floors`／`floorHeight`（＋`floorHeightBasis`）、`anchorSide/Size`／`quasiAnchors`／`levelAnchors`、`mallRows`／`coreFracs`／`foodCourt`／`courtFracRange`、`gates`、`serviceFace`、`groundPrior`、`spec` {value, basis}（構造種別・工法・基礎・外装・屋根用途/仕様・天井高・スプリンクラー・駐車場）、`site` {value, basis}（周辺・道路・敷地面積・ポリゴン）、特記仕様書1頁相当の `outline`（工事概要）／`zoning`（法規条件）／`systems`（設備概要）{value, basis}。**分からない項目は value=null**（生成器の推論で補われるか、未収集としてモデルの assumptions に推論／gap と出る） | 調査（人手が要る唯一の工程。マンション・駅は注釈なしでも生成可） |
| 3 | 生成 | `model/generate_building.py`：商業 `gen_seeded2`／マンション `gen_seeded_mansion`／駅 `gen_seeded_station`。手順は下記 → `model/generated_*.json` | 自動 |
| 4 | 検証 | `model/validate_building_model.py`：不変条件 V1〜V24＋V-L3（裏側配置）＋用途別 V-U（歩行距離・採光など）。**全PASS が受け入れ条件**（既知の例外は旧 seeded v1 の V-U商5 のみ）。落ちたらモデルを直接編集せず、生成器か注釈を直して再生成する | 自動 |
| 5 | 消費 | `model/render_plan.py` → 平面図 SVG／本編ゲーム（生成モデルを直接読む。対応付けは JSON 内 `gameIntegration` が正。3D 試作の compact3d は凍結・廃止予定）／`group_buildings.py`（下記 C） | 自動 |

工程3（生成）の内部手順：
1. `base_parts`：グリッド（軸・スパン）、レベル（階）、敷地の仮置きポリゴンを置く
2. 室配置：claim の優先順位（サービス／コア ＞ アンカー ＞ モール・準アンカー・階別アンカー ＞ フードコート／フィル）でプレートに室を割り当てる。各室に根拠タグ `source`（guide／program／inferred）を付与
3. コア・シャフト（EV／階段／PS／DS／EPS／吹抜け。縦連続は単一オブジェクト）
4. 壁：`build_walls` が同一線上の連続セグメントを統合し開口（サッシ／戸／シャッター等）を載せる。`fix_doors` が出入口チェック（V8）に合わせて戸を補う。マンションは `fix_daylight` が採光（V-Uマ6）に合わせてサッシを拡幅
5. スラブ・屋根・土工・基礎：屋根の種別と注記はシードの `roofUse` で切り替わる（例：駐車場 → 陸屋根（屋上駐車場））
6. L4 構造推論 `attach_structure`：構造軸の選定（商業は 9m モジュール、SPAN_STANDARD）→ 柱は構造交点のみ、柱例外（大空間）、耐震要素、大梁せい（最大構造スパンから）、地盤仮定（地域 prior またはシード指定）→ 杭基礎なら foundations.piles に規則を明記、施工属性（クレーン可否等）。**シード spec の値がある項目は推論より優先**
7. 仕様と前提の付与：`building.seedSpec`（注釈 spec の写し）と `assumptions`（項目ごとに {item, adopted, source: seed／inference／default／gap, basis, process}）を付ける。検証 V24 が seedSpec 全項目に対応する assumptions があることを担保

## B. 架空建物（パラメトリック生成）

パラメータ（用途・形状・階数・グリッド寸法）を生成コマンドの引数で与える → `gen_commercial`（rectangle／stepped／L／setback）／`gen_mansion`／`gen_station`（相対式／島式）／`gen_game_mall`（本編の物件）→ 以降は A と同じ（検証 → 消費）。建物自体が架空の設計なので注釈・spec・assumptions は付かない（パラメータはコードと DOCUMENTS が明示の場所）。

## C. 複合化（団地）

`model/group_buildings.py`：GeoJSON の全棟 → 棟間距離の閾値で union-find グルーピング → 面積上位 N 棟（既定 8）を `gen_seeded_mansion` で生成 → Complex JSON（棟間リンク＋共有の site）。

## 検証実績：PLATEAU経由の新規生成（2026-11-10）

新規物件「モラージュ柏」（千葉県柏市）をこのフローで生成し、全チェック PASS を確認した。柏市の GeoParquet（Flateau V2、169,223棟）から用途コード402・面積で主棟（building_id 12217-bldg-72906、外形23,516㎡）を選定 → 変換は 48×28セル・6mスパン・IoU 0.946 → 軽量注釈（外形と施設概要は事実、内部配置は推定と明示。階数はフロアガイドの2階を採用し、PLATEAU属性の4階は駐車場階等を含むとみて不採用＝要確認として注釈に記録）→ 249室で生成。歩行距離（V-U商5）はモール行の位置調整で解消した。環境注意：Flateau V2 の GeoParquet 2.0 は新しい pyarrow が要る（システムの numpy 1.26 と競合するため venv で読んだ）。成果物は conversion_plateau_mallage_kashiwa.json／seed_annotations_mallage_kashiwa.json／generated_commercial_seeded2_mallage.json。

検証実績2（2026-11-10）：高層マンションも同じ柏市データから生成し、全チェック PASS。用途コード412（共同住宅）の最大階数15階・高さ42.7m・外形1,703㎡の棟（building_id 12217-bldg-170397、柏市柏436-2、建物名は未同定）を選定 → 変換は 11×8セル・IoU 0.859 → 注釈は階数と階高のみ（階数は PLATEAU 属性、階高は計測高さからの逆算を階段整合の取れる 2800mm に丸めた）→ 15階・255室・112戸で生成。高さ31m超のため防災センターと非常用EVが入り、1Fには試験標準セット（ゴミ保管庫・電気室・受水槽室・消火ポンプ室）＋集会室が揃った。注意：柏市の PLATEAU データセットは最大15階までで、柏の葉の25階超タワー群は含まれていなかった（整備範囲・年度の限界）。超高層で試すなら対象都市のデータセットにタワーが含まれるか先に確認が要る。成果物は conversion_plateau_kashiwa_tower.json／seed_annotations_kashiwa_tower.json／generated_mansion_seeded_kashiwa_tower.json。

## 現在の限界（フロー上の）

- ソースデータに階ごとのセットバックが無い（外形は全階同一プレートが前提。階別アンカー等で部分的に表現）
- 敷地ポリゴンは実形状が未取得で仮置き矩形（siteAreaM2 の事実とは一致しない。assumptions に明示）
- シード生成で EquipmentRun（設備横引きルート）は未生成（gap として assumptions に明示）
- 駅のシードは注釈の形式が未整備（改札行の位置・駅ビル階数は生成器の仮定。INTERIOR_MODEL_V2 §10）
