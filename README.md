# 民生新聞（原型）
靜態網站：index.html / style.css / app.js，資料在 data/news.json。
- 預覽：`python3 -m http.server 8000` 後開啟 http://localhost:8000/ （國際分頁：#intl）
- 過期規則：一般消息自首次發布起 48 小時移入 `archive.html`（不刪除）；更正紀錄見 `corrections.html`（資料 `data/corrections.json`）。
- 更新流程：見 AUTOMATION.md（`python3 update.py fetch` → 編輯 data/news.json → `python3 update.py validate` → `python3 update.py finalize`）。
