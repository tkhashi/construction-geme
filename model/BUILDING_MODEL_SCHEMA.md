# 建物モデル データ定義 v0.7（2026-11-10、コア内容物と開口ロールを追加。v0.6 は構造軸/補助軸の分離とシード仕様ブロック、v0.5 は L4 構造推論ブロックと構造・配置の検証を追加）

位置づけ：PLAN_GENERATION_STUDY.md の生成パイプライン（条件→建物モデル→描画）が生み出す「建物モデル」のデータ定義。生成・描画・自動検証・ゲーム側ロジックはすべてこのモデルを参照し、座標のベタ書きを排除する。既存の OBJECT_MODEL.md の Area／WorkTask／Photo は、このモデルの空間要素を参照する形に接続する（§7）。

## 1. 設計原則
1. **単位は mm・整数**。原点は通り芯 X1∩Y1、X＝東方向、Y＝北方向（平面座標）。高さは FL（仕上床）基準の標高 mm。
2. **すべての幾何はグリッドから導く**。要素は通り芯の名前＋オフセットで位置を表し、自由な絶対座標で置けるのは敷地ポリゴンとシャフト内部の機器だけに限る。「なぜそこにあるか」をデータが語れることが現実味の源泉。
3. **規則＋例外で持てる**。柱の全交点配置のような規則的なものは規則として保存し、例外（吹抜けで抜ける柱など）だけを列挙する。生成器は規則を展開して全要素を数えられること。
4. **派生値は保存しない**。面積・寸法チェーン・スパン合計・延床はモデルから計算で出す。保存するのは一次情報だけにし、矛盾の発生源を断つ。
5. **縦連続は「階をまたぐ1つのオブジェクト」**で表す。シャフトと柱は階ごとのコピーを作らず、対象階の範囲（levelRange）を持つ単一オブジェクトとする。縦に通っているかはデータ構造自体が保証する。
6. **IDは安定ID**（例 `col:X3-Y2`, `wall:1F-Y2-a`, `room:1F-T03`, `shaft:PS-1`）。生成の種が変わらない限り再生成しても同じIDになり、ゲーム側の参照（作業・写真・検査）が壊れない。

## 2. エンティティ定義

### Building（建物）
| フィールド | 内容 |
|---|---|
| id / name | 物件ID・名称 |
| use | 用途：商業／事務所／共同住宅／工場・倉庫／病院／学校 |
| structure | 構造：S／RC／SRC |
| floorHeightDefault | 基準階高 mm（階ごとの上書き可） |
| grossAreaTarget | 条件としての延床㎡（実延床は派生値。検証で突き合わせる） |
| seedSpec | （任意、v0.6）シード注釈の建物仕様ブロックをそのまま保持：{項目: {value, basis}}。項目は structureSystem／frameMethod／foundationType／exteriorWall／roofUse／roofSpec／ceilingHeightMm／sprinkler／parking。value が非 null の項目は生成器の推論より優先され（検証 V24）、null は「公開情報では不明」で生成器が推論で補ったことを意味する。仕様がシードで確定できる建物では推論と置き換わる |
| outline／zoning／systems | （任意、v0.6）特記仕様書1頁相当のシード（ユーザー指示 2026-11-10：シード段階で特記仕様書1ページ目の内容を網羅する）。いずれも {項目: {value, basis}} で、注釈にあればモデルへそのまま写る。outline＝工事概要（address／use／buildingAreaM2／totalFloorAreaM2／heightMm／openedYear／operator／architect／builder）、zoning＝法規条件（useDistrict／fireZone／buildingCoverageLimit／floorAreaRatioLimit／heightDistrict／shadowRegulation）、systems＝設備概要（powerReceiving／waterSupply／drainage／airConditioning／heatSource／elevators／fireAlarm）。value=null は「枠はあるが未収集」を意味し、assumptions に gap として記録される（検証 V25）。構造特記1頁の項目（基礎形式・部材・地盤）は structure ブロックと groundAssumption が、共通仕様（適用する標準仕様書等）は設計図書側の属性として対象外 |

### Site（敷地）
| フィールド | 内容 |
|---|---|
| polygon | 敷地境界の頂点列（敷地座標系 mm、時計回り） |
| buildingPlacement | 建物グリッド原点の敷地座標＋回転角（度）。建物の方位はここで決まる |
| roads | 接道：{境界辺の参照, 幅員, 名称} |
| gates | ゲート（仮設）：{境界上の位置, 幅}。配置ステップで先に決まる |
| neighbors | 隣地条件：{境界辺の参照, 種別（住宅／道路／田畑／商業…）} |

### Grid（基準グリッド）
| フィールド | 内容 |
|---|---|
| axesX | [{name:"X1", offset:0}, …] offsetは X1 からの累積 mm。名前は左（西）→右（東） |
| axesY | [{name:"Y1", offset:0}, …] offsetは Y1 からの累積 mm。名前は下（南）→上（北） |
| スパン | 隣接 offset の差＝派生値。寸法チェーンは axes から自動生成される |
| structuralAxesX / structuralAxesY | （任意、v0.6）構造軸の軸名リスト。グリッドの残りは部屋割り用の補助軸。柱・大梁・基礎は構造軸の交点にのみ置く（SPAN_STANDARD.md の構造軸/補助軸分離）。選定は端から約9mピッチ（実務レンジ8〜10m）に最も近い既存軸で、両端の軸を必ず含む。省略時は全軸が構造軸。分離がある場合 columnRule は "structural-intersections"、beamRule は "structural-grid-lines-…" になる |
| structuralModule | （任意、v0.6）{targetMm:9000, rangeMm:[8000,10000], basis} 構造軸選定の基準記録（正は SPAN_STANDARD.md） |

### Level（階）
| フィールド | 内容 |
|---|---|
| id / name | "L1"/"1F"（地下は "LB1"/"B1F"） |
| elevation | FL標高 mm |
| floorHeight | この階の階高 mm（階段の整合に使う） |
| footprint | （任意、v0.4）この階のプレート形状＝セル範囲のリスト（下記「プレートとセル集合」）。省略時はグリッド全体の矩形。階ごとに変えることでセットバックや段型が表せる |

### Column（柱）
| フィールド | 内容 |
|---|---|
| at | {x:"X3", y:"Y2"} 芯交点の参照 |
| levelRange | ["L1","L3"] 通っている階（1オブジェクトで複数階） |
| sizeByLevel | 階帯ごとの断面 {w,d} mm（下階ほど太い、を表せる） |
| 例外表現 | Gridに `columnRule: "all-intersections"`（構造軸分離がある建物では `"structural-intersections"`＝柱は構造軸交点のみ）を置き、抜ける柱は `columnExceptions` に {at:"X3-Y2", levels:["L2"], reason:"吹抜け"} と列挙（v0.5 で形式を確定）。例外は構造軸の交点にだけ付ける（v0.6） |

### Structure（構造推論ブロック）— v0.5 追加（L4：公開情報に無い躯体を推論で創造する）
建物直下の `structure` オブジェクト。実構造ではなく、構造計画の原則からの**推論**であり、各要素に根拠（basis）を併記する（INTERIOR_MODEL_V2 §7）。実測・設計情報が得られたら推論と置き換える。
| フィールド | 内容 |
|---|---|
| system | 推論した構造種別：S／RC／壁式RC／SRC（Building.structure と一致。壁式RC は RC の内訳） |
| systemBasis / moduleBasis | 種別選定・構造モジュール（駐車モジュール等）の根拠（強度タグ【基準】【指針】【実務】付き文字列） |
| columnSizeMm / girderDepthMm（+Basis） | 部材断面の初期値（柱は代表値、大梁せいはスパン比からの推定） |
| structuralSpanMaxMm | （v0.6）構造軸間の最大スパン mm。大梁せいの推定はこの値から行う（補助軸の細かいスパンではない） |
| seismicElements | [{id, kind: ブレース／耐震壁, direction: X／Y, levelRange, cell（配置セル）, basis}]。重心≒剛心で外周＋コアにバランス配置し L1 まで連続 |
| columnFreeZones | [{id, name, levels, cellRanges, treatment（大梁／トラス／受替）, basis}]。吹抜け・シネマ等の無柱区画。Grid.columnExceptions はここから導く |
| groundAssumption | {foundation, bearingLayer, liquefactionRisk, basis}。地盤は公開情報で確定できないため、地域 prior からの**仮定**として保持し、事実と混ぜない |
| constructionDerived | {frameCycle, crane, note}。節分割・クレーン種別（50m ルール）など施工属性の導出 |
| note | 推論である旨の宣言 |

### Assumptions（前提の明示）— v0.6 追加
建物直下の `assumptions` 配列（シード生成で出力）：[{item, adopted, source, basis, process}]。モデルの各決定が **seed（シードの事実）／inference（推論）／default（生成器既定）／gap（未生成＝既知の不足）** のどれで決まったかを項目ごとに記録する。推論や既定で決めること自体は正とし、事実と混ざらないことが要件（検証 V24：seedSpec がある場合、全仕様項目に対応する assumptions 記録が必須）。杭基礎と仮定した場合は foundations.piles にも規則として残す（null のままにしない）。

### Beam（梁）
| フィールド | 内容 |
|---|---|
| along | {axis:"X3", from:"Y1", to:"Y2"} または Y軸方向。芯上の隣接柱間 |
| level | かかる階（その階の床を支える梁＝上の Level を指す規則を統一） |
| size | {w,h} mm |

### Core（コア）
| フィールド | 内容 |
|---|---|
| rect | グリッド基準の矩形 {xFrom:"X1", xTo:"X2", yFrom:"Y3", yTo:"Y4"} |
| levelRange | 通る階 |
| 中身 | Shaft と階段・ホール（Roomとして）を内包する |
| shafts | （v0.7）内包する Shaft の ID 列挙。生成時に付けた事実（どのシャフトをこのコアに入れたか） |
| hasStair／stairLevels | （v0.7）階段シャフトの有無と、階段のある階の列挙。本編3Dが階段コアを階ごとに描くための主データ |
| hasElevator | （v0.7）EVシャフトの有無 |

### Shaft（シャフト／縦動線）— 縦連続の主役
| フィールド | 内容 |
|---|---|
| kind | EV／階段／PS／DS／EPS／吹抜け／ダクト |
| footprint | グリッド基準の矩形（芯参照）または mm 矩形（コア内配置用）。**全階で同一** |
| levelRange | 通る階。途中で止まる場合は止まる階と理由（例：EVの機械室）を持つ |
| openingsByLevel | 階ごとの開口（EV扉・点検口・階段出入口）：{level, wall参照, 位置} |
| 階段の追加情報 | riser（蹴上）・going（踏面）・steps。floorHeight ＝ riser × steps が恒等式として検証される |

### Wall（壁セグメント）— 開口を内包する
| フィールド | 内容 |
|---|---|
| level | 属する階 |
| line | {axis:"Y2", from:"X1", to:"X5"}（芯上）または {axis, offset:mm, side} で芯からずらした壁も表せる |
| thickness | 壁厚 mm |
| kind | 外壁／間仕切／耐力壁／シャフト壁 |
| openings | [{id, kind, offsetFromStart, width, height, sillHeight, fireRating, swing, role?, servesCore?}]。kind＝サッシ／片開き戸／両開き戸／引戸／シャッター／固定窓。swing は戸のみ {hinge:"start側", opens:"室外方向"}。role（v0.7、任意）＝開口の役割：**entrance**（建物の出入口：外壁の戸で内側が共用動線＝モール／コアホール／共用廊下／エントランスに面する）／**shopfront**（店舗の外向き出入口：外壁の戸で内側が大型店／物販／テナント／飲食）／**core**（コアに属する室＝コアホール等に面する出入口。servesCore にコアID）／**loading**（荷捌き・納品所に面する外壁シャッター）。判定できない開口には role を付けない（＝普通の戸・窓）。Shaft の openingsByLevel は未生成で、階段・EVの出入口はこの role="core" で表す |

### Room（室・区画）
| フィールド | 内容 |
|---|---|
| level / name / use | 階・室名・用途（テナント／モール／バックヤード／WC／機械室／コアホール／サービス通路…） |
| cells | グリッドセルの範囲 {xFrom,xTo,yFrom,yTo}（矩形の室）。非矩形は cells の集合で表す |
| zoneId | 所属する工区（§Zone）。モール等の共用部は null |
| ceilingHeight | 天井高 mm |
| area | **派生値**（cells の面積合計から計算。壁芯/内法の区別は集計規則として別途持つ） |

### Zone（工区）
| フィールド | 内容 |
|---|---|
| id / level | "1F-E" など |
| cellRange | {xFrom,xTo,yFrom,yTo}。**工区境は必ず芯の上** |
| 規則 | 同一階の工区は重ならず、コア・共用部を含む全セルを覆う（検証 V7） |

### EquipmentRun（設備横引き）— 軽量に持つ
| フィールド | 内容 |
|---|---|
| kind | 給水／排水／空調ダクト／電気配管 |
| fromShaft | 起点シャフトID |
| level / route | 経由する Room／セルの列。隠蔽・先行の判定（ゲーム側）に使う |

### Foundation（基礎）／Earthwork（地業）— v0.2 追加（IFC: IfcFooting／IfcPile／IfcEarthworksElement）
| フィールド | 内容 |
|---|---|
| footings | {rule:"each-column" 等の規則＋例外, size:{w,d}, thickness, topElevation}。柱位置ごとに基礎が対応する（検証 V11） |
| piles | 杭がある場合：{at:柱参照または位置, kind（場所打ち／既製）, diameter, length} の列挙または規則 |
| gradeBeams | 地中梁：グリッドライン沿い（規則表現可） |
| earthworks | [{kind（根切り／埋戻し／地業）, cells, depth}] 掘削範囲と深さ |

### Slab（床版）— v0.2 追加（IFC: IfcSlab）
| フィールド | 内容 |
|---|---|
| level | この床版が床になる階（その階の梁に支えられる） |
| kind | デッキ合成スラブ／RCスラブ／土間コンクリート（onGround:true） |
| cells | 張る範囲（通常は全セル） |
| thickness | 版厚 mm |
| openings | 貫通する Shaft のID列挙。シャフトは「床を抜く開口」としてここに現れる |

### Roof（屋根）— v0.2 追加（IFC: IfcRoof）
| フィールド | 内容 |
|---|---|
| topLevel | 直下の最上階 |
| kind | 陸屋根（防水種別）／折板／勾配屋根 |
| cells | 覆う範囲（通常は最上階の全セル） |
| parapetHeight | パラペット高さ mm |

### Compartment（防火区画）— v0.2 追加（IFC: IfcZone）。工区（Zone）とは別軸
| フィールド | 内容 |
|---|---|
| kind | 面積区画／竪穴区画／異種用途区画 |
| level | 面積区画の属する階（竪穴区画は階をまたぐ） |
| rooms | 面積区画：構成する Room のID列挙。同一階の面積区画は全 Room を重なりなく分割する（検証 V14） |
| shafts | 竪穴区画：構成する Shaft のID列挙（各シャフトは必ず1つの竪穴区画に属する） |

### Covering（仕上げ）— v0.2 追加（IFC: IfcCovering）
| フィールド | 内容 |
|---|---|
| target | 付く相手：Room／Wall／Slab のID |
| part | 床／壁／天井／外装 |
| name | 仕上げの名称（文字列。材料の層構成は B 群＝保留のため持たない） |
| area | 派生値（対象の面積から計算） |

### Reinforcement（配筋）— v0.2 追加（IFC: IfcReinforcingBar／Mesh）
| フィールド | 内容 |
|---|---|
| target | 配筋される部材：Slab／Beam／Footing 等のID（規則対象は "foundation:each-column" のような規則参照も可） |
| kind | スラブ配筋／梁主筋・あばら筋／基礎配筋 |
| spec | 配筋仕様の文字列（例 "D13@200 ダブル"）。部材として数える対象になる |

### CurtainWall（カーテンウォール）— v0.2 追加（IFC: IfcCurtainWall）
| フィールド | 内容 |
|---|---|
| level / line | Wall と同じ芯参照。外壁 Wall と同一区間に重ねて置けない（検証 V15） |
| mullionPitch | 方立の割付ピッチ mm（パネル数は派生値） |

### GenericElement（汎用要素）— v0.2 追加（IFC: IfcBuildingElementProxy）
| フィールド | 内容 |
|---|---|
| name | 庇／笠木／水切り／層間ふさぎ 等、型にない部材の名前 |
| attachTo | 付く相手（Wall／Roof／Shaft 等）のID |
| note | 位置などの補足。種別が育ったら専用エンティティへ昇格させる逃げ場 |

### v0.3 追加：駅舎対応（USE_RULES.md §3.0 の拡張4点を採用、2026-11-08）
駅は建物単体では生成できない（線路とホームが敷地側の固定条件になる）ため、次を追加する。いずれも駅以外の用途では現れない任意要素で、既存の例・検証には影響しない。

### Track（軌道）— Site の子要素
| フィールド | 内容 |
|---|---|
| id / name | 例 `track:1`／「1番線」 |
| kind | 在来線／新幹線（定数表の切替キー） |
| centerOffset | 軌道中心線の位置（敷地座標系、mm。線路は X 方向に平行を既定とし Y 座標で表す） |
| centerSpacing | 隣接軌道との中心間隔（在来線 3,600 級／新幹線 4,300 以上） |

### Platform（ホーム）— Site の子要素（専用エンティティにせずとも Slab＋汎用要素では位置の意味が持てないため新設）
| フィールド | 内容 |
|---|---|
| id | 例 `platform:A` |
| level | 対応する Level（高さの文脈） |
| trackIds | 接する軌道（島式は2本、相対式は1本） |
| form | 島式／相対式／単式 |
| rect | 敷地座標系の矩形 {x, y, w, d}（グリッドに従属しない唯一の例外。ホームは軌道から決まるため） |
| edgeOffset | 接する軌道中心からホーム縁端までの距離（mm。在来線 1,480 級） |
| height | ホーム高さ（電車専用 1,100／併用 920／客車 760／新幹線 1,250） |
| usableWidth | 使用幅（相対式＝幅そのもの、島式＝両側合算の目安として中央部の幅） |

### FareZone（改札ゾーン）／FareGate（改札）— Compartment と直交する軸
| フィールド | 内容 |
|---|---|
| FareZone.id / kind | 改札内／改札外。level と rooms（Room IDの列）を持つ。1つの駅舎 Building 内の全 Room を重なりなく覆う |
| FareGate.id / level | fromZone／toZone（FareZone ID）、passages（通路数）、widePassages（拡幅通路数、80cm以上） |

### Complex（複合）— ファイル全体の形
単体ファイル（現行の形）に加え、複合ファイルを持てるようにする：最上位に `complex`（id／name／links）と共有の `site`（軌道・ホームを含む）を置き、`buildings` に Building オブジェクトの列を並べる。Link は {id, from（Building ID）, to, kind（連絡通路／共有コンコース等）}。駅ビルは別 Building としてこれで結ぶ。

### プレートとセル集合（v0.4）— 非矩形プランの表現
建物の平面形状は「グリッド全体の矩形」ではなく、**グリッドセルの集合（プレート）**として表す。これにより L字・コの字・雁行（段型）・十字などの直交多角形と、階ごとのセットバックが、セル矩形の和集合だけで表現できる。斜め壁・曲面は対象外（§11）。
- `Level.footprint`：その階のプレートをセル範囲（Room と同じ {xFrom, xTo, yFrom, yTo} 形式）のリストで与える。省略時は全面。
- `cellRanges` の一般化：Zone／Slab／Roof／Earthwork の範囲指定は、単一矩形の `cells` に加えて複数矩形の `cellRanges`（リスト）を許す。検証・描画は和集合として扱う。
- 柱の規則 "each-column" の意味は「プレートに接する交点に柱がある」に一般化する（プレート外の交点には柱は立たない）。
- Room はプレートの内側にのみ置ける。プレート外は敷地（外構・駐車場・荷捌きヤード等）として描画側が扱う。

## 3. 関係の骨格
- Building は Grid・Level・Core・Room・Zone を所有する。Site は Building を配置する。
- Column／Beam は Grid の交点・芯を参照する（座標を持たない）。
- Wall は Grid の芯を参照し、Opening を内包する。Room はセルの集合であり、その境界は Wall と一致する（検証で担保）。
- Shaft は Core に内包され、Level をまたぐ。EquipmentRun は Shaft から生える。
- Zone は Level 内のセルを分割する。Room は1つの Zone に属する。
- Foundation は Column の位置に対応し、Earthwork はその範囲と深さを与える。Slab は Level の床となり、Shaft の貫通を開口として持つ。Roof は最上階を覆う。
- Compartment（防火区画）は Zone とは独立の軸で、面積区画は Room を、竪穴区画は Shaft をグルーピングする。
- Covering は Room／Wall／Slab に付き、Reinforcement は構造部材に付く。CurtainWall は外壁位置を Wall と排他的に占める。
- Track は Site に属し、Platform は Track に相対して置かれる（建物 Grid に従属しない）。FareZone は Compartment と直交する軸で Room を改札内／外に分け、FareGate がその境界になる。Complex の Link は Building 同士を結ぶ。

## 4. 不変条件（検証ルール）と生成ステップの対応
| # | ルール | 主な対象 | 生成ステップ |
|---|---|---|---|
| V1 | 寸法チェーン：Σスパン ＝ 全長（axes の末端 offset と一致） | Grid | 2 基準グリッド |
| V2 | シャフト縦連続：footprint が levelRange の全階で同一、Core 内に収まる | Shaft/Core | 4 コア |
| V3 | 壁の整合：Wall の line は芯または宣言済みオフセット上にあり、端点は芯か壁の接合点 | Wall | 5 外皮・6 平面計画 |
| V4 | 柱の完全性：交点に柱がある（例外は reason 付きのみ） | Column | 3 構造 |
| V5 | 開口の収容：開口は壁セグメント内に収まり、相互に重ならない | Wall.openings | 5・7 建具 |
| V6 | 面積整合：階の Room 面積合計＋シャフト等 ≒ その階のプレート面積（許容差内）。延床も同様 | Room | 6 平面計画 |
| V7 | 工区分割：同一階の Zone は重ならずプレートの全セルを覆う。工区境は芯上 | Zone | 6 平面計画 |
| V8 | 出入口：囲まれた Room（シャフト・モール等の例外用途を除く）は境界壁に戸を1つ以上持つ | Room/Wall | 7 建具 |
| V9 | 階段整合：riser × steps ＝ floorHeight、riser・going が用途別基準内 | Shaft(階段) | 4 コア |
| V10 | 参照整合：Room・EquipmentRun 等の参照先が実在し、その階に存在する | 全体 | 全部 |
| V11 | 基礎の対応：全ての柱位置に Footing（または杭＋Footing）があり、Earthwork が建物範囲を覆う | Foundation | 3 構造 |
| V12 | スラブ完全性：各階に Slab がありプレートの全セルを覆う。開口はその階を通る Shaft のみ | Slab | 3 構造 |
| V13 | 屋根：最上階に Roof が1つあり、その階のプレート全セルを覆う | Roof | 5 外皮 |
| V14 | 防火区画：面積区画が階の全 Room を重なりなく分割し、各 Shaft が竪穴区画に属する | Compartment | 6 平面計画 |
| V15 | カーテンウォール排他：同一階・同一芯・重なる区間に外壁 Wall と CurtainWall が併存しない | CurtainWall | 5 外皮 |
| V16 | 付随要素の参照整合：Covering／Reinforcement／GenericElement の target・attachTo が実在する | 付随要素 | 全部 |
| V17 | 軌道・ホーム整合：Platform の参照する Track が実在し、縁端距離（edgeOffset）が路線種別の範囲内（在来線 1,350〜1,650mm） | Track/Platform | 1 配置 |
| V18 | ホーム定数：形式ごとの幅・高さが路線種別の定数表を満たす（相対式幅 ≧2,000、島式幅 ≧5,000、高さは {760, 920, 1100, 1250} のいずれか） | Platform | 3 構造 |
| V19 | 改札ゾーン分割：FareZone が駅舎の全 Room を重なりなく覆い、改札内と改札外を結ぶ FareGate が存在する | FareZone/FareGate | 6 平面計画 |
| V20 | 複合整合：Complex の Link の両端が実在する Building を指す | Complex | 1 配置 |
| V21 | 形状整合：Level.footprint の範囲がグリッド内にあり、全ての Room がその階のプレート内に収まる | Level/Room | 2 基準グリッド |
| V22a | 柱例外が無柱区画内：Grid.columnExceptions の各（位置, 階）は Structure.columnFreeZones のいずれかに隣接（2セル以上）する | Structure/Grid | 3 構造 |
| V22b | 岡立ち禁止：ある階で例外（柱なし）の位置が直上の階で柱に戻る場合、その位置を覆う受替（トランスファー）区画が必要 | Structure | 3 構造 |
| V22c | 耐震要素の配置：Structure.seismicElements が X・Y 両方向に各2以上あり、全て levelRange に L1 を含み（下階まで連続）、セルがプレート内にある | Structure | 3 構造 |
| V22d | 構造種別・基礎仮定の記録：Structure.system が Building.structure と一致し（壁式RC は RC の内訳として可）、groundAssumption.basis が空でない | Structure | 3 構造 |
| V23 | 構造軸/補助軸の分離（SPAN_STANDARD）：Grid.structuralAxesX/Y がある場合、両方向とも実在の軸名で昇順・両端の軸を含み、構造スパンが 4,000〜15,000mm（シードグリッド量子化の許容込み）に収まり、columnExceptions が全て構造軸交点を指す。柱・基礎の本数は構造軸交点（1Fプレートに接し例外でないもの）で数える（V11 の数え方も同じ） | Grid | 2 基準グリッド／3 構造 |
| V24 | シード仕様の反映：Building.seedSpec がある場合、値が入っている structureSystem が Building.structure と一致し（壁式RC は RC として）、sprinkler が Building.sprinklerFull と一致する | Building | 1 配置 |
| V25 | 特記1頁ブロックの前提記録：outline／zoning／systems がある場合、全項目に対応する assumptions（item＝"<block>.<項目>"）が存在する | Building | 1 配置 |
| V26 | コア内容物・開口ロール：Core.shafts がある場合、参照先が実在し hasStair／stairLevels がシャフトと一致する。開口 role は既定の値のみで、role="core" は servesCore の実在と階の一致、entrance／shopfront／loading は外壁の開口であること | Core/Wall | 1 配置 |
| V-L3-1 | 荷捌きと貨物EVコアの隣接：1F の荷捌き／納品所 Room が貨物EV（freight）シャフトを持つ Core に隣接する | Room/Core | 6 平面計画 |
| V-L3-2 | 電気室と水系室の非隣接：電気室とポンプ室が同階で隣接しない | Room | 6 平面計画 |
| V-L3-3 | 防災センターは1F：防災センター Room が全て1Fにある | Room | 6 平面計画 |
| V-L3-4 | 荷捌きが外周に面する：1F の荷捌き Room がプレート境界に接するセルを持つ | Room | 6 平面計画 |
| V-U商5 | 歩行距離（近似）：物販・テナント・飲食 Room の全セルから最寄り階段シャフトまでの BFS 距離（プレート全セル通行可、条件付き斜め移動あり）が上限以下（SP・準耐火前提 40m、それ以外 30m） | Room/Shaft | 6 平面計画 |
| V-Uマ5 | 歩行距離（近似）：住戸について同上の距離が 50m 以下 | Room/Shaft | 6 平面計画 |
| V-Uマ6 | 採光（近似）：住戸の外壁サッシ・固定窓の開口面積（室の範囲と重なる部分）が床面積の 1/7 以上（法28条。住戸単位の近似で、採光補正係数と室別判定は行わない） | Room/Wall | 7 建具 |

検証を通らない生成物は破棄し、種を変えて再生成する（PLAN_GENERATION_STUDY §2 ステップ10）。

## 5. 描画への写像（モデル→ビュー）
- 平面図：Level を1枚とし、Wall（厚み付き）・Opening（壁を切って描く）・Column（交点）・Room（室名＋派生面積）・通り符号と寸法チェーン（Grid から自動生成）を描く。注記は全部モデル由来なので矛盾しない。
- アイソメ／3D：Column・Beam・Slab 相当（cells×level）と Wall の立面がそのまま部材になる。アイソメ側の「部材単位で積み上がる」表現（別チャット検討中）は、このモデルの部材IDと対応付けられる。
- 敷地一体図：Site.polygon・buildingPlacement から建物を敷地内に配置し、roads・gates・neighbors を描く。

## 6. 生成器が書く順序（再掲・対応づけ）
配置→Site/buildingPlacement／グリッド→Grid／構造→Column・Beam・Foundation・Earthwork・Slab・Reinforcement／コア→Core・Shaft／外皮→Wall(外壁)＋CurtainWall＋Opening(サッシ)＋Roof／平面計画→Room・Zone・Compartment(防火区画)・Covering／建具→Opening(戸)／設備→EquipmentRun／注記→描画時に派生／検証→V1〜V20＋用途別 V-U。駅舎では配置ステップで Site に Track／Platform を先に固定し、平面計画で FareZone／FareGate を割る。

## 7. ゲーム側との接続
- OBJECT_MODEL の **Area** は Room または GridCell に対応（巡回・占有の単位）。
- **工区**は Zone そのもの。作業（WorkTask）は Room／Zone／Shaft 等の空間参照を持つ。
- **Photo** の「測点・通り芯」は Grid の軸名で記録する。
- **置場スポット**は use が置場候補の Room／セル、または Site 内の空地ポリゴンとしてモデルに載せる（仮設計画の対象）。
- 検査・写真の対象部材（配筋・スリーブ等）は Column/Beam/Wall/Shaft の部材IDに紐づく。

## 8. 具体例と検証器
- 例1：`building_model_example.json` — 小規模商業施設（2階、X4スパン×Y3スパン、センターコアではない西コア型）で全エンティティを通した例（v0.2 で基礎・スラブ・屋根・防火区画・仕上げ・配筋・カーテンウォール・汎用要素を追加。1F東面はカーテンウォール）。
- 例2：`building_model_station_example.json` — v0.3 の複合ファイルの例（地上駅・相対式2面2線＋駅ビル、Track／Platform／FareZone・FareGate／Complex を使用）。組み立ては `build_station_example.py`。
- 検証器：`validate_building_model.py` — V1・V2・V5〜V21（複合ファイル・プレート形状対応）、V22（L4 構造推論の整合）、V-L3（裏側配置）、用途別追加検証 V-U の即判定分（商業：区画面積・区画形状・最大店舗比率・歩行距離／マンション：界壁の開口ゼロ・31m超の非常用EV等・歩行距離）を実行する。現行の合格状況（2026-11-09）：例1・例2・全生成モデル（商業4形状・シード商業2棟・マンション・シードマンション2棟・駅・団地複合6棟）が全PASS。既知の例外：シード生成 v1（generated_commercial_seeded.json、v2 に置換済み）は歩行距離 V-U商5 のみ未達（コアが北帯のみで間隔が広い）で、v1 の既知の限界として記録する。生成器はこの検証を通すことを受け入れ条件にする。
- 生成器（最小試作）：`generate_building.py` — USE_RULES をパラメータから実行する。商業施設（ダンベル型、9mグリッド×8スパン・3階。形状パラメータ：rectangle／stepped（雁行）／L（L字）／setback（階別セットバック）、生成物は形状ごとに 240〜275 チェック全PASS）とマンション（片廊下型、間口6m×9戸・8階、558チェック全PASS）に対応する。
- 描画（最小試作）：`render_plan.py` — モデル JSON から平面図 SVG（通り符号・寸法チェーン・柱・壁と開口・室名＋派生面積・シャフト）を描く。出力例：`plan_commercial_1F.svg`、`plan_mansion_3F.svg` 等。

## 10. IFC（ISO 16739）との対照 — 不足の棚卸し（2026-11-08）
前提：IFCは「交換のための完全なスキーマ」、本モデルは「生成のための最小モデル」。全てを取り込むのが正解ではなく、現実味（LOD300）とゲーム側の必要から優先度を付ける。逆にIFCにない我々の強みは「要素がグリッドをパラメトリックに参照すること」（IFCの要素は配置座標を持つだけで生成規則を持たない）で、これは生成器の土台として維持する。

### A. 要素そのものが欠けている（生成ステップ自体に影響・最優先）
| 不足 | IFC | なぜ要るか |
|---|---|---|
| 基礎・地業（杭・フーチング・地中梁・根切り） | IfcPile／IfcFooting／IfcEarthworksElement | 現行は地上の柱からしか始まらない。ゲームの工程に土工事・基礎があるのにモデルの受け皿がない |
| スラブ（床版） | IfcSlab | Levelはあるが床版の部材がない。デッキ・打設・床を抜くシャフト開口は全部スラブにぶら下がる |
| 屋根 | IfcRoof | 屋根防水・笠木の受け皿がない |
| 防火区画・竪穴区画 | IfcZone（空間のグルーピング） | 現行Zoneは「施工の工区」専用で、防火という別軸の区画がない。シャフト＝竪穴区画という意味づけ、消防検査に直結 |
| 仕上げ（カバーイング） | IfcCovering | 天井・床仕上げ・外装仕上げがRoomの属性でしかない。内装チェーン（ボード→仕上げ）の受け皿 |
| 配筋 | IfcReinforcingBar／Mesh | 躯体の主役級の部材で、アイソメ側では部材として数えているのにモデルにない |
| カーテンウォール | IfcCurtainWall（方立＋パネルの集約） | 吹抜け・アトリウム面の主役。現行の壁＋開口では表せない |
| 汎用要素（逃げ場） | IfcBuildingElementProxy | 庇・笠木・水切り・層間ふさぎ等「型にない部材」が置けない（現行は種別が閉じた列挙） |

### B. 表現の仕組みが欠けている（LOD300の芯）
| 不足 | IFC | なぜ要るか |
|---|---|---|
| 材料の層構成・断面プロファイル | IfcMaterialLayerSet／IfcMaterialProfileSet | 現行は壁厚ひとつと柱の{w,d}だけ。壁＝躯体＋断熱＋仕上げの層、柱梁＝形鋼プロファイルがあって初めて隠蔽/仕上げの区別と物量が生まれる |
| タイプ（型）と個の分離 | IfcTypeObject（IfcDoorType等） | 同じ扉型・サッシ型の使い回しがなく全属性を個々に持つ。生成ルール（用途→型の選定）と数量集計の前提 |
| 開口の分離（空ける／嵌る） | IfcOpeningElement＋IfcRelVoidsElement＋IfcRelFillsElement | 現行は壁への内包で簡略化。実害は「壁以外を貫通する開口＝スリーブ」が表せないこと（スラブ・梁の貫通は失敗モードの主役） |
| 空間境界 | IfcRelSpaceBoundary | 室と「それを囲む壁・開口」の対応をデータとして持たない。隣接・動線の解析が毎回派生計算になる |
| 接続関係（取合い） | IfcRelConnectsPathElements等 | 壁同士・梁と柱の接続と優先順位がない。施工図の取り合いチェックの土台 |
| 設備の系統とポート接続 | IfcDistributionSystem／IfcDistributionPort | 現行EquipmentRunは経路リストのみで接続グラフがない。水圧試験の系統、受電→試運転の依存は接続で表すべきもの |

### C. 土台・運用
| 不足 | IFC | なぜ要るか |
|---|---|---|
| 配置階層と地理参照 | IfcLocalPlacement／IfcMapConversion | 敷地→建物→階→部材の相対配置、真北と標高基準（T.P.）の区別がない。複数棟・方位の厳密さに効く |
| 形状表現の一般形 | 押出し＋プロファイル定義 | 現行は芯平行の矩形前提。斜め壁・段差スラブ等が表現不能（§9の未決定と対応） |
| プロパティ／数量セットの枠組み | IfcPropertySet／IfcElementQuantity（Pset_WallCommon等） | 属性をエンティティごとに場当たりで増やす方式は拡張に限界。防火等級など性能属性の置き場 |
| 分類コード | IfcClassificationReference | ゲームの工種・仕様と部材を結ぶコード表の受け皿がない |
| 版管理・変更履歴 | IfcOwnerHistory相当 | 設計変更フロー（ゲームの核）の土台として、モデルの版と差分を持つ仕組みがない |

### D. 意図的に取り込まない（IFCにあるが不要）
- 構造解析モデル（IfcStructuralAnalysisModel）：構造計算は範囲外。
- IFCの工程・資源（IfcTask／IfcWorkSchedule／IfcConstructionResource）：工程と人はゲーム側モデル（WORK_STRUCTURE_V2／OBJECT_MODEL）が正で、IFC側に寄せない。
- 形状表現の全分（BRep等）：LOD300の範囲（押出し＋プロファイル）で足りる。
- IFC形式のGlobalId：安定IDの考え方だけ借り、形式は独自でよい。

### 取り込み優先順位（案）
1. 第1弾（生成パイプラインのステップ自体が変わる）：基礎・地業／スラブ／屋根／防火区画 — 用途別ルールより先に定義へ追加する。
2. 第2弾（LOD300の見た目と物量）：材料層・プロファイル／タイプ分離／カバーイング／配筋／カーテンウォール／汎用要素。
3. 第3弾（関係と運用）：開口の分離（スリーブ対応）／空間境界／接続／設備系統／プロパティ枠組み／分類／版管理。

### ユーザー判断（2026-11-08）と反映状況
- **A群（要素の追加）＝対応**：v0.2 で §2 に Foundation／Earthwork／Slab／Roof／Compartment（防火区画）／Covering／Reinforcement／CurtainWall／GenericElement を追加し、不変条件 V11〜V16 と具体例・検証器まで反映済み。
- **B群（表現の仕組み）＝保留**：材料層・プロファイル／タイプ分離／開口の分離／空間境界／接続／設備系統は、必要になった時点で再検討する。保留中は Covering の材料を文字列で持つ等の簡易表現で代替する。
- **C群（土台・運用）＝不要**：配置階層・地理参照／形状表現の一般形／プロパティ・数量セット枠組み／分類コード／版管理は取り込まない。将来必要になればその時に判断する。

## 11. 未決定（次に詰める）
- （解消）駅舎・駅ビル対応の拡張4点は v0.3 で採用した（Track／Platform／FareZone・FareGate／Complex）。詳細は §2 の v0.3 追加と USE_RULES.md §3。
- 壁の仕様の深さ：LOD300として材料・仕上げ（ALC／サッシ種別等）を Wall にどこまで持たせるか。
- 非矩形の室・斜め壁の表現（一部解消 v0.4）：建物外形の非矩形（L字・雁行・セットバック等の直交多角形）はプレート＝セル集合で対応した。残りは斜め壁・曲面（現定義は芯平行が前提。敷地なりの斜めは buildingPlacement の回転で吸収する方針だが、建物内部の斜め壁・隅切りは未定義）。
- 梁・スラブを平面図の表現にどこまで出すか（ゲーム図面は意匠図ベースで構造は伏図を別に持つか）。
- Room の境界を cells だけでなく Wall のループでも表現するか（非矩形対応と引き換えに複雑化）。
