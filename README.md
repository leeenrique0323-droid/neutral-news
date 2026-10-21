# 民生新聞（原型）
靜態網站：index.html / style.css / app.js，資料在 data/news.json。
- 預覽：`python3 -m http.server 8000` 後開啟 http://localhost:8000/ （國際分頁：#intl）
- 更新流程：見 AUTOMATION.md（`python3 update.py fetch` → 編輯 data/news.json → `python3 update.py validate` → `python3 update.py finalize`）。
