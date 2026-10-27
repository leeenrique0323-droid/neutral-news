(function(){
  const {fmt, esc, first, itemBody, bindToggles, validEnd, validLabel} = NN;
  let data = null;

  const isBreaking = i => String(i.status||"").startsWith("快訊");

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

  function listSection(id, title, list, emptyText, note){
    return `
      <section class="day-sec" id="${id}" aria-label="${title}">
        <h2>${title}<span class="count">${list.length} 則</span>${note ? `<span class="note">${note}</span>` : ""}</h2>
        ${list.length ? list.map(i => card(i, true)).join("") : `<p class="day-empty">${emptyText}</p>`}
      </section>`;
  }

  let renderedDay = null;
  function render(tab, keepScroll){
    document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab===tab));
    const items = data.items.filter(i => i.tab===tab);
    const now = new Date();
    renderedDay = taipeiDay(now);
    const today = ordered(items.filter(i => sectionOf(i, now) === "today"));
    const other = ordered(items.filter(i => sectionOf(i, now) === "other"));
    document.getElementById("updated").textContent = data.updated
      ? `最後更新：${fmt(data.updated)}（台灣時間）　共 ${items.length} 則` : `共 ${items.length} 則`;
    document.getElementById("cat-index").innerHTML =
      `<a href="#today-${tab}" class="to-breaking">今日新聞 ${today.length}</a>` +
      (other.length ? `<a href="#other-${tab}">其他新聞 ${other.length}</a>` : "");
    const el = document.getElementById("content");
    if(!items.length){ el.innerHTML = `<p class="empty">目前沒有符合收錄標準的消息。</p>`; return; }
    el.innerHTML = validBlock(items) +
      listSection(`today-${tab}`, "今日新聞", today, "今天還沒有新的重大民生新聞", "台灣時間今日首次發布；進行中的事件會保留於此") +
      (other.length ? listSection(`other-${tab}`, "其他新聞", other, "", "") : "");
    bindToggles(el);
    if(keepScroll) return;
    const target = location.hash.length > 1 && document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if(target) target.scrollIntoView();
  }

  // a page left open across Taiwan midnight moves yesterday's items to 其他新聞
  setInterval(() => { if(data && renderedDay && taipeiDay(new Date()) !== renderedDay) render(current(), true); }, 30000);

  function current(){ return location.hash.startsWith("#intl") ? "intl" : "tw"; }

  document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => {
    history.replaceState(null, "", b.dataset.tab==="intl" ? "#intl" : "#tw");
    render(b.dataset.tab); window.scrollTo(0,0);
  }));

  fetch("data/news.json", {cache:"no-store"}).then(r => r.json()).then(j => { data = j; render(current()); })
    .catch(() => { document.getElementById("content").innerHTML = '<p class="empty">無法載入資料。請以本機伺服器開啟（例如 python3 -m http.server）。</p>'; });
})();
