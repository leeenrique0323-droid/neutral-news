(function(){
  const {esc, corrKind, corrTag} = NN;
  const el = document.getElementById("content");
  const bar = document.getElementById("corr-filter");
  const TYPES = ["事實更正", "用語調整"];
  let entries = [], filter = "all";   // filter: "all" | a type; never persisted

  function card(e){
    const link = e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.item_title)}</a>` : esc(e.item_title);
    return `<article class="item correction ${corrKind(e.type)}">
        <p class="arch-meta">${corrTag(e.type)}<span>${esc(e.date)}${e.item_id ? `・${esc(e.item_id)}` : ""}</span></p>
        <h3>${link}</h3>
        <dl class="facts">
          <dt>原本錯誤</dt><dd>${esc(e.what_was_wrong)}</dd>
          <dt>更正內容</dt><dd>${esc(e.correction)}</dd>
        </dl></article>`;
  }
  function render(){
    const shown = entries.filter(e => filter === "all" || e.type === filter);
    const n = t => entries.filter(e => e.type === t).length;
    const btn = (v, label, count, cls) =>
      `<button type="button" class="filter-btn ${cls||""}" data-filter="${esc(v)}" aria-pressed="${filter === v}">${esc(label)}<span class="n">${count}</span></button>`;
    bar.innerHTML = `<div class="filter-bar" role="group" aria-label="依更正類型篩選">${btn("all", "全部", entries.length)}${btn("事實更正", "事實更正", n("事實更正"), "fact")}${btn("用語調整", "用語調整", n("用語調整"))}</div>`;
    bar.querySelectorAll(".filter-btn").forEach(b => b.addEventListener("click", () => { filter = b.dataset.filter; render(); }));
    el.innerHTML = (shown.length ? shown.map(card).join("") : `<p class="empty">這個類型目前沒有更正紀錄。</p>`);
  }
  fetch("data/corrections.json", {cache:"no-store"}).then(r => r.json()).then(d => {
    // newest date first; within a day 事實更正 before 用語調整
    entries = (d.entries||[]).slice().sort((a,b) => String(b.date).localeCompare(String(a.date)) || TYPES.indexOf(a.type) - TYPES.indexOf(b.type));
    document.getElementById("updated").textContent = `共 ${entries.length} 則更正` + (d.started ? `　紀錄自 ${d.started} 起` : "");
    document.getElementById("corr-note").innerHTML = d.note ? `<p class="archive-note">${esc(d.note)}</p>` : "";
    if(!entries.length){ bar.innerHTML = ""; el.innerHTML = `<p class="empty">目前沒有更正紀錄。</p>`; return; }
    render();
  }).catch(() => { el.innerHTML = '<p class="empty">無法載入資料。</p>'; });
})();
