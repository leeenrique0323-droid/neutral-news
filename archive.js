(function(){
  const {fmt, fmtDate, esc, first, itemBody, bindToggles} = NN;
  fetch("data/archive.json", {cache:"no-store"}).then(r => r.json()).then(a => {
    const items = (a.items||[]).slice().sort((x,y) => new Date(first(y)) - new Date(first(x)));
    document.getElementById("updated").textContent = `共 ${items.length} 則` + (a.updated ? `　最後整理：${fmt(a.updated)}` : "");
    const el = document.getElementById("content");
    if(!items.length){ el.innerHTML = `<p class="empty">目前沒有過往新聞。</p>`; return; }
    const groups = {};
    items.forEach(i => (groups[fmtDate(first(i))] = groups[fmtDate(first(i))] || []).push(i));
    el.innerHTML = Object.keys(groups).sort().reverse().map(day => `
      <section class="cat">
        <h2>${esc(day)}</h2>
        ${groups[day].map(i => `
        <details class="arch-item">
          <summary>
            <span class="arch-title">${esc(i.title)}</span>
            <span class="arch-meta">${NN.chip(i.category)}<span>${i.tab==="intl" ? "國際" : "台灣"}・發布 ${fmt(first(i))}${i.valid_until && NN.validLabel(i) ? `・${esc(NN.validLabel(i))}` : ""}${i.archived ? `・移入 ${fmtDate(i.archived)}` : ""}</span></span>
          </summary>
          <article class="item">${itemBody(i, {openFirst:false})}</article>
        </details>`).join("")}
      </section>`).join("");
    bindToggles(el);
  }).catch(() => { document.getElementById("content").innerHTML = '<p class="empty">無法載入資料。</p>'; });
})();
