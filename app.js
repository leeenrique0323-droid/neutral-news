(function(){
  const {fmt, esc, first, itemBody, bindToggles, validEnd, validLabel} = NN;
  let data = null;

  const isBreaking = i => i.status.startsWith("快訊");

  function card(i, showCat){
    return `
        <article class="item ${i.sections ? "has-sections" : ""}" id="${esc(i.id)}">
          <div class="badges">
            <span class="badge ${isBreaking(i) ? "prelim" : ""}">${esc(i.status)}</span>
            ${i.valid_until && validLabel(i) ? `<span class="badge valid">${esc(validLabel(i))}</span>` : ""}
            ${i.ongoing && !i.ongoing.ended ? `<span class="badge live">進行中</span>` : ""}
            ${showCat ? `<span class="cat-label">${esc(i.category)}</span>` : ""}
            <span>發布 ${fmt(first(i))}${i.updated ? `　更新 ${fmt(i.updated)}` : ""}</span>
          </div>
          ${itemBody(i)}
        </article>`;
  }

  // 本週有效: items flagged `evergreen` (policy / subsidy / deadline / price freeze) whose valid_until is still ahead
  function validBlock(items){
    const now = Date.now();
    const list = items.filter(i => i.evergreen && validEnd(i) && validEnd(i).getTime() > now)
      .sort((a,b) => validEnd(a) - validEnd(b));
    const oneLine = s => (String(s||"").split("\n")[0].match(/^.*?[。！？]/) || [String(s||"")])[0];
    return `
      <section class="valid-now" id="valid-now" aria-label="本週有效">
        <h2>本週有效<span class="note">政策、補助、期限與價格凍結等有效期間內的資訊</span></h2>
        ${list.length ? `<ul>${list.map(i => `
          <li><a class="vn-title" href="#${esc(i.id)}">${esc(i.title)}</a>
            <span class="vn-until">${esc(validLabel(i))}</span>
            <span class="vn-sum">${esc(oneLine(i.summary))}</span></li>`).join("")}</ul>`
        : `<p class="vn-empty">目前沒有本週有效的民生資訊</p>`}
      </section>`;
  }

  const newest = i => new Date(i.updated || first(i)).getTime();

  function render(tab){
    document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab===tab));
    const items = data.items.filter(i => i.tab===tab);
    // pinned items first, then newest
    const breaking = items.filter(isBreaking).sort((a,b) => (!!b.pinned - !!a.pinned) || (newest(b)-newest(a)));
    const rest = items.filter(i => !isBreaking(i));
    const cats = data.categories.filter(c => rest.some(i => i.category===c));
    document.getElementById("updated").textContent = data.updated
      ? `最後更新：${fmt(data.updated)}（台灣時間）　共 ${items.length} 則` : `共 ${items.length} 則`;
    document.getElementById("cat-index").innerHTML =
      (breaking.length ? `<a href="#breaking-${tab}" class="to-breaking">快訊</a>` : "") +
      cats.map((c,n) => `<a href="#cat-${tab}-${n}">${esc(c)}</a>`).join("");
    const el = document.getElementById("content");
    if(!items.length){ el.innerHTML = `<p class="empty">目前沒有符合收錄標準的消息。</p>`; return; }
    el.innerHTML = validBlock(items) +
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
    bindToggles(el);
    const target = location.hash.length > 1 && document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if(target) target.scrollIntoView();
  }

  function current(){ return location.hash.startsWith("#intl") ? "intl" : "tw"; }

  document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => {
    history.replaceState(null, "", b.dataset.tab==="intl" ? "#intl" : "#tw");
    render(b.dataset.tab); window.scrollTo(0,0);
  }));

  fetch("data/news.json", {cache:"no-store"}).then(r => r.json()).then(j => { data = j; render(current()); })
    .catch(() => { document.getElementById("content").innerHTML = '<p class="empty">無法載入資料。請以本機伺服器開啟（例如 python3 -m http.server）。</p>'; });
})();
