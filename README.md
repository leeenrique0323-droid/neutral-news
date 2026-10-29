# 民生新聞（原型）
靜態網站：index.html / style.css / app.js，資料在 data/news.json。
- 預覽：`python3 -m http.server 8000` 後開啟 http://localhost:8000/ （國際分頁：#intl）
- 過期規則：一般消息自首次發布起 48 小時移入 `archive.html`（不刪除；有 `valid_until` 的項目留到有效期限過後，上限 14 天）；更正紀錄見 `corrections.html`（資料 `data/corrections.json`）。
- 更新流程：見 AUTOMATION.md（`python3 update.py fetch` → 編輯 data/news.json → `python3 update.py validate` → `python3 update.py finalize`）。
- 首頁分區：「本週有效」下方分為「今日新聞」（`first_published` 為台灣時間今日）與「其他新聞」，由前端依日曆日推導、隔天自動移動；進行中（`ongoing` 未解除）的事件留在今日新聞。詳見 AUTOMATION.md。
- 分類篩選：首頁「本週有效」下方的按鈕列（全部＋各分類與則數）會同時篩選今日新聞與其他新聞；按鈕由各項目的 `category` 欄位自動產生，新增分類（例如「政治」）不需改前端。進行中事件不受篩選影響。詳見 AUTOMATION.md。
- 相關報導：項目可帶選填 `related`（`[{id, title?}]`），卡片展開後顯示連結；指向 news.json 的項目同頁跳轉，指向 archive.json 的項目連到 `archive.html#id`（過往新聞頁會展開並標示）。`validate` 檢查 id 存在。詳見 AUTOMATION.md。
- 國際新聞目標約占全站三分之一，fetch.py 涵蓋多國公開 RSS；規則見 AUTOMATION.md「國際新聞：比例與收錄範圍」。
