(function(){
  const fmt = iso => {
    if(!iso) return "";
    const d = new Date(iso);
    const p = n => String(n).padStart(2,"0");
    // display in Taiwan time (UTC+8)
    const t = new Date(d.getTime() + 8*3600*1000);
    return `${t.getUTCFullYear()}/${p(t.getUTCMonth()+1)}/${p(t.getUTCDate())} ${p(t.getUTCHours())}:${p(t.getUTCMinutes())}`;
  };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  let data = null;

  const isBreaking = i => i.status.startsWith("快訊");

  function card(i, showCat){
    return `
        <article class="item">
          <div class="badges">
            <span class="badge ${isBreaking(i) ? "prelim" : ""}">${esc(i.status)}</span>
            ${showCat ? `<span class="cat-label">${esc(i.category)}</span>` : ""}
            <span>發布 ${fmt(i.published)}${i.updated ? `　更新 ${fmt(i.updated)}` : ""}</span>
          </div>
          <h3>${esc(i.title)}</h3>
          <p class="summary">${esc(i.summary)}</p>
          <dl class="facts">
            <dt>影響誰</dt><dd>${esc(i.who)}</dd>
            <dt>影響什麼</dt><dd>${esc(i.what)}</dd>
            <dt>何時開始</dt><dd>${esc(i.when)}</dd>
          </dl>
          ${i.taiwanImpact ? `<p class="tw-impact"><strong>對台灣的影響</strong>${esc(i.taiwanImpact)}</p>` : ""}
          <div class="sources">原始報導與資料來源
            <ul>${i.sources.map(s => `<li>${esc(s.name)}：<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("")}</ul>
          </div>
        </article>`;
  }

  const newest = i => new Date(i.updated || i.published).getTime();

  function render(tab){
    document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab===tab));
    const items = data.items.filter(i => i.tab===tab);
    const breaking = items.filter(isBreaking).sort((a,b) => newest(b)-newest(a));
    const rest = items.filter(i => !isBreaking(i));
    const cats = data.categories.filter(c => rest.some(i => i.category===c));
    document.getElementById("updated").textContent = data.updated
      ? `最後更新：${fmt(data.updated)}（台灣時間）　共 ${items.length} 則` : `共 ${items.length} 則`;
    document.getElementById("cat-index").innerHTML =
      (breaking.length ? `<a href="#breaking-${tab}" class="to-breaking">快訊</a>` : "") +
      cats.map((c,n) => `<a href="#cat-${tab}-${n}">${esc(c)}</a>`).join("");
    const el = document.getElementById("content");
    if(!items.length){ el.innerHTML = `<p class="empty">目前沒有符合收錄標準的消息。</p>`; return; }
    el.innerHTML =
      (breaking.length ? `
      <section class="breaking" id="breaking-${tab}" aria-label="快訊">
        <h2>快訊<span class="note">事件發展中，內容可能更新</span></h2>
        ${breaking.map(i => card(i, true)).join("")}
      </section>` : "") +
      cats.map((c,n) => `
      <section class="cat" id="cat-${tab}-${n}">
        <h2>${esc(c)}</h2>
        ${rest.filter(i => i.category===c).sort((a,b) => newest(b)-newest(a)).map(i => card(i, false)).join("")}
      </section>`).join("");
  }

  function current(){ return location.hash.startsWith("#intl") ? "intl" : "tw"; }

  document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => {
    history.replaceState(null, "", b.dataset.tab==="intl" ? "#intl" : "#tw");
    render(b.dataset.tab); window.scrollTo(0,0);
  }));

  fetch("data/news.json", {cache:"no-store"}).then(r => r.json()).then(j => { data = j; render(current()); })
    .catch(() => { document.getElementById("content").innerHTML = '<p class="empty">無法載入資料。請以本機伺服器開啟（例如 python3 -m http.server）。</p>'; });
})();
