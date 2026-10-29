(function(){
  const {fmt, esc, first, bindToggles, validEnd, validLabel} = NN;
  let data = null;

  const isBreaking = i => String(i.status||"").startsWith("快訊");

  function card(i, featured){
    return NN.cardHtml(i, {featured: !!featured});
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

  const newest = i => { const t = new Date(i.updated || first(i)).getTime(); return isNaN(t) ? 0 : t; };

  // Calendar day (YYYY-MM-DD) in Taiwan time, computed explicitly in Asia/Taipei; null for invalid input.
  const dayFmt = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Taipei", year:"numeric", month:"2-digit", day:"2-digit"});
  function taipeiDay(v){
    const d = v instanceof Date ? v : new Date(v);
    return (v == null || isNaN(d)) ? null : dayFmt.format(d);
  }
  // 今日新聞 = first_published falls on today's calendar date in Taiwan (not 24h based).
  // Items with an unfinished `ongoing` disaster stay in 今日 until ongoing.ended is set.
  // Missing / invalid first_published => 其他新聞 (never throws).
  function sectionOf(i, now){
    if(i.ongoing && !i.ongoing.ended) return "today";
    const day = taipeiDay(first(i));
    return day && day === taipeiDay(now == null ? new Date() : now) ? "today" : "other";
  }
  NN.sectionOf = sectionOf; NN.taipeiDay = taipeiDay;

  // 快訊 (pinned first) before the rest, each newest first
  const ordered = list => list.slice().sort((a,b) =>
    (isBreaking(b) - isBreaking(a)) || (isBreaking(a) && ((!!b.pinned - !!a.pinned))) || (newest(b)-newest(a)));

  function listSection(id, title, list, emptyText, note, featureFirst){
    return `
      <section class="day-sec" id="${id}" aria-label="${title}">
        <h2>${title}<span class="count">${list.length} 則</span>${note ? `<span class="note">${note}</span>` : ""}</h2>
        ${list.length ? list.map((i, n) => card(i, featureFirst && n === 0)).join("") : `<p class="day-empty">${emptyText}</p>`}
      </section>`;
  }

  // --- 分類篩選 (client-side only; categories are derived from the items' own `category` field) ---
  let filter = "all";   // "all" or a category string; resets on tab switch, never persisted
  // 進行中 (ongoing, not ended) disaster items are exempt from the filter so a live warning is never hidden.
  const exempt = i => !!(i.ongoing && !i.ongoing.ended);
  function categoriesOf(items){
    const present = [...new Set(items.map(i => i.category).filter(Boolean))];
    const order = (data && data.categories) || [];   // keep the editorial order when known; unknown (new) ones follow
    const rank = c => { const n = order.indexOf(c); return n < 0 ? order.length : n; };
    return present.map((c, n) => [c, n]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(x => x[0]);
  }
  function filterBar(items, cats){
    const btn = (value, label, n) =>
      `<button type="button" class="filter-btn" data-filter="${esc(value)}" aria-pressed="${filter === value}">${esc(label)}<span class="n">${n}</span></button>`;
    return `<div class="filter-bar" role="group" aria-label="依分類篩選">
        ${btn("all", "全部", items.length)}${cats.map(c => btn(c, c, items.filter(i => i.category === c).length)).join("")}
      </div>`;
  }

  let renderedDay = null, shownTab = null;
  function render(tab, keepScroll){
    document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab===tab));
    const items = data.items.filter(i => i.tab===tab);
    const now = new Date();
    renderedDay = taipeiDay(now); shownTab = tab;
    const cats = categoriesOf(items);
    if(filter !== "all" && !cats.includes(filter)) filter = "all";   // category vanished (e.g. archived) -> back to 全部
    const filtering = filter !== "all";
    const pass = i => !filtering || i.category === filter || exempt(i);
    const allToday = items.filter(i => sectionOf(i, now) === "today");
    const allOther = items.filter(i => sectionOf(i, now) === "other");
    const today = ordered(allToday.filter(pass));
    const other = ordered(allOther.filter(pass));
    document.getElementById("updated").textContent = data.updated
      ? `最後更新：${fmt(data.updated)}（台灣時間）　共 ${items.length} 則` : `共 ${items.length} 則`;
    document.getElementById("cat-index").innerHTML =
      `<a href="#today-${tab}" class="to-breaking">今日新聞 ${today.length}</a>` +
      (allOther.length ? `<a href="#other-${tab}">其他新聞 ${other.length}</a>` : "");
    const el = document.getElementById("content");
    if(!items.length){ el.innerHTML = `<p class="empty">目前沒有符合收錄標準的消息。</p>`; return; }
    const shown = today.length + other.length, kept = [...today, ...other].filter(i => exempt(i) && i.category !== filter).length;
    const bar = cats.length > 1   // a single category would make the row a no-op, so hide it
      ? filterBar(items, cats) +
        `<p class="filter-status" role="status" aria-live="polite">${filtering
          ? `目前顯示「${esc(filter)}」${shown - kept} 則${kept ? `，另有 ${kept} 則進行中的事件不受篩選影響` : ""}` : ""}</p>` : "";
    const emptyFiltered = "這個分類目前沒有新聞";
    el.innerHTML = validBlock(items) + bar +
      listSection(`today-${tab}`, "今日新聞", today, filtering && allToday.length ? emptyFiltered : "今天還沒有新的重大民生新聞", "台灣時間今日首次發布；進行中的事件會保留於此", true) +
      (allOther.length ? listSection(`other-${tab}`, "其他新聞", other, emptyFiltered, "") : "");
    bindToggles(el); NN.bindCards(el);
    // 相關報導 links to another card on this page: expand + scroll (works even when the hash is already set)
    el.querySelectorAll("a.rel-link[data-local='1']").forEach(a => a.addEventListener("click", e => {
      e.preventDefault();
      const id = a.dataset.rel;
      history.replaceState(null, "", "#" + encodeURIComponent(id));
      goTo(id);
    }));
    el.querySelectorAll(".filter-btn").forEach(b => b.addEventListener("click", () => {
      filter = b.dataset.filter;
      render(tab, true);
      const again = [...el.querySelectorAll(".filter-btn")].find(x => x.dataset.filter === filter);
      if(again) again.focus({preventScroll:true});   // re-rendering replaces the button; keep keyboard focus on it
    }));
    // links to an item (本週有效 titles) must still work when the filter has hidden that item
    el.querySelectorAll(".vn-title").forEach(a => a.addEventListener("click", e => {
      e.preventDefault();
      const id = decodeURIComponent(a.getAttribute("href").slice(1));
      history.replaceState(null, "", "#" + encodeURIComponent(id));
      goTo(id);
    }));
    if(keepScroll) return;
    const id = location.hash.length > 1 && decodeURIComponent(location.hash.slice(1));
    if(id) goTo(id);
  }

  // Jump to an item: leave the filter if it hides the item, auto-expand the card (deep links), then scroll to it.
  function goTo(id){
    let t = document.getElementById(id);
    if(!t || !t.classList.contains("card")){
      const it = data && data.items.find(x => x.id === id);
      if(!it) return;
      filter = "all"; render(it.tab, true);
      t = document.getElementById(id);
    }
    if(!t || !t.classList.contains("card")) return;
    NN.setExpanded(t, true);
    t.scrollIntoView();
  }
  window.addEventListener("hashchange", () => {
    if(!data) return;
    const id = decodeURIComponent(location.hash.slice(1));
    if(id && id !== "tw" && id !== "intl" && !/^(today|other)-/.test(id)) goTo(id);
    else if(id === "tw" || id === "intl"){ if(id !== shownTab) { filter = "all"; render(id); } }
  });

  // a page left open across Taiwan midnight moves yesterday's items to 其他新聞
  setInterval(() => { if(data && renderedDay && taipeiDay(new Date()) !== renderedDay) render(current(), true); }, 30000);

  // the tab for the URL hash; a deep link to an item (#item-id) opens the tab that holds it
  function current(){
    const id = decodeURIComponent(location.hash.slice(1));
    const it = id && data && data.items.find(x => x.id === id);
    return it ? it.tab : (location.hash.startsWith("#intl") ? "intl" : "tw");
  }

  document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => {
    history.replaceState(null, "", b.dataset.tab==="intl" ? "#intl" : "#tw");
    filter = "all";
    render(b.dataset.tab); window.scrollTo(0,0);
  }));

  // related links: also load archive.json (optional; links to archived items fall back to the given title if it is unavailable)
  Promise.all([
    fetch("data/news.json", {cache:"no-store"}).then(r => r.json()),
    fetch("data/archive.json", {cache:"no-store"}).then(r => r.json()).catch(() => ({items: []}))
  ]).then(([j, arch]) => { data = j; NN.setRelatedIndex(j.items, arch.items); render(current()); })
    .catch(() => { document.getElementById("content").innerHTML = '<p class="empty">無法載入資料。請以本機伺服器開啟（例如 python3 -m http.server）。</p>'; });
})();
