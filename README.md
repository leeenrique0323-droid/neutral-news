# 民生新聞（原型）
靜態網站：index.html / style.css / app.js，資料在 data/news.json。
- 預覽：`python3 -m http.server 8000` 後開啟 http://localhost:8000/ （國際分頁：#intl）
- 過期規則：一般消息自首次發布起 48 小時移入 `archive.html`（不刪除；有 `valid_until` 的項目留到有效期限過後，上限 14 天）；更正紀錄見 `corrections.html`（資料 `data/corrections.json`）。
- 更新流程：見 AUTOMATION.md（`python3 update.py fetch` → 編輯 data/news.json → `python3 update.py validate` → `python3 update.py finalize`）。
- 首頁分區：「本週有效」下方分為「今日新聞」（`first_published` 為台灣時間今日）與「其他新聞」，由前端依日曆日推導、隔天自動移動；進行中（`ongoing` 未解除）的事件留在今日新聞。詳見 AUTOMATION.md。
- 分類篩選：首頁「本週有效」下方的按鈕列（全部＋各分類與則數）會同時篩選今日新聞與其他新聞；按鈕由各項目的 `category` 欄位自動產生，新增分類（例如「政治」）不需改前端。進行中事件不受篩選影響。詳見 AUTOMATION.md。
- 相關報導：項目可帶選填 `related`（`[{id, title?}]`），卡片展開後顯示連結；指向 news.json 的項目同頁跳轉，指向 archive.json 的項目連到 `archive.html#id`（過往新聞頁會展開並標示）。`validate` 檢查 id 存在。詳見 AUTOMATION.md。
- 國際新聞目標約占全站三分之一，fetch.py 涵蓋多國公開 RSS；規則見 AUTOMATION.md「國際新聞：比例與收錄範圍」。
- 資金來源標示：來源名稱旁的小標籤（公共出資／商業＋公共／商業／信託／捐助／政府機關／未標示），由單一對照表 `data/source_funding.json` 推導（`funding.py`、`common.js`），只依各媒體自己公開的資金說明，無法確認者標「未標示」；`validate` 會檢查 fetch.py 每個來源都有對照。詳見 AUTOMATION.md「資金來源標示」。
- 國際新聞的「對台灣的影響」：只寫有出處的事實（例如「據經濟部資料，…」），不做預測（不用「恐將」「可能衝擊」）；間接推論一律寫成「可能間接影響。理由：…」並註明出處，不得捏造數字；修改已刊登內容須記入更正紀錄。詳見 AUTOMATION.md §8。
