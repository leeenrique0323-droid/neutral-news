(function(){
  const {esc, fmtDate} = NN;
  const el = document.getElementById("content");
  fetch("data/corrections.json", {cache:"no-store"}).then(r => r.json()).then(d => {
    const es = (d.entries||[]).slice().sort((a,b) => String(b.date).localeCompare(String(a.date)));
    document.getElementById("updated").textContent = `共 ${es.length} 則更正` + (d.started ? `　紀錄自 ${d.started} 起` : "");
    const note = d.note ? `<p class="archive-note">${esc(d.note)}</p>` : "";
    if(!es.length){ el.innerHTML = note + `<p class="empty">目前沒有更正紀錄。</p>`; return; }
    el.innerHTML = note + es.map(e => {
      const link = e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.item_title)}</a>` : esc(e.item_title);
      return `<article class="item correction">
        <p class="arch-meta">${esc(e.date)}${e.item_id ? `・${esc(e.item_id)}` : ""}</p>
        <h3>${link}</h3>
        <dl class="facts">
          <dt>原本錯誤</dt><dd>${esc(e.what_was_wrong)}</dd>
          <dt>更正內容</dt><dd>${esc(e.correction)}</dd>
        </dl></article>`;
    }).join("");
  }).catch(() => { el.innerHTML = '<p class="empty">無法載入資料。</p>'; });
})();
