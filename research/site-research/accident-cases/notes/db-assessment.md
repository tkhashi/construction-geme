# DB所見メモ (2026-11-09 閲覧)

## 経済産業省系
- 事故事例データベース https://www.meti.go.jp/policy/safety_security/industrial_safety/sangyo/hipregas/jikoboushi/database.html (verified live via index fetch)
  - 実体は「高圧ガス保安法事故」専用。令和6年度版取扱説明書 https://www.meti.go.jp/policy/safety_security/industrial_safety/sangyo/hipregas/jikoboushi/incident_db_2025_help.pdf の目次・検索項目は高圧ガス保安法事故タブのみ、項目は物質名/噴出・漏えい部位/設備区分/着火源等。製作は高圧ガス保安協会(経産省委託)、Excelマクロ形式 incident_db_2025.xlsm。
  - → 建設現場の墜落・足場・クレーン転倒・土砂崩壊等の労働災害事例は構造的にほぼ含まれない。接点は溶接用ガス/LPガス漏えい・爆発程度。
- 産業保安トップ https://www.meti.go.jp/policy/safety_security/industrial_safety/index.html : 事故速報は都市ガス/LPガスの一酸化炭素中毒・漏えい爆発が主。
- 電気事故 https://www.meti.go.jp/policy/safety_security/industrial_safety/sangyo/electric/detail/setsubi_jiko.html : 電気保安統計(電気事業者・自家用電気工作物設置者の詳報ベース)と各産業保安監督部の概要。NITE電気設備事故情報公開システム/詳報公表システム https://www.nite.go.jp/gcet/tso/kohyo.html は2020年度以降の電気工作物事故を一元化。設備事故寄りで、作業者の行動・KY等の叙述は薄い。キュービクル感電の背景理解には有用。
- NITE製品安全 SAFE-Lite https://www.nite.go.jp/jiko/jikojohou/safe-lite.html : 1996年度以降の消費生活用製品事故。消費者製品対象で建設現場労働災害ではない。
- 鉱山災害事例 (関東産業保安監督部等) は鉱山専用。

## 補完源
- 厚生労働省 職場のあんぜんサイト 労働災害事例 https://anzeninfo.mhlw.go.jp/jirei/sai_search.html : 死亡・重大災害を発生状況/原因/対策+イラストで紹介。事例集ページは全2644件と記載(検索結果より)。本調査の主源。個別事例は sai_XXXXXX.html 形式。2026-11-09に多数を verified live で開覧。
- 国土交通省 建設工事事故データベース(SAS) https://www.mlit.go.jp/report/press/kanbo08_hh_001048.html (2024-02-02発表, verified): R1-R4に地方整備局・都道府県・政令市で発生した公共工事事故約1,600件をExcel公開 https://www.mlit.go.jp/tec/content/001721757.xlsx 。母体はH5構築・約18,000件蓄積(H5-R3, NILIM資料)だが公開分は公共工事=土木偏重で、民間の建築(モール新築)の個別叙述は乏しい。本調査ではDB所見と公衆災害の裏付けに使用し、個別事例の主源にはしなかった。
