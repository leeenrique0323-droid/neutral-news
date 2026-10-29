/* Shared helpers for index.html and archive.html (no build step). */
window.NN = (function(){
  const p = n => String(n).padStart(2,"0");
  // display in Taiwan time (UTC+8)
  const tp = iso => { const t = new Date(new Date(iso).getTime() + 8*3600*1000); return t; };
  const fmt = iso => {
    if(!iso) return "";
    const t = tp(iso);
    return `${t.getUTCFullYear()}/${p(t.getUTCMonth()+1)}/${p(t.getUTCDate())} ${p(t.getUTCHours())}:${p(t.getUTCMinutes())}`;
  };
  const fmtDate = iso => { const t = tp(iso); return `${t.getUTCFullYear()}/${p(t.getUTCMonth()+1)}/${p(t.getUTCDate())}`; };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const first = i => i.first_published || i.published;

  // `valid_until` ("YYYY-MM-DD" = valid through the end of that day, or an ISO datetime; Taiwan time)
  const validEnd = i => {
    const v = i.valid_until; if(!v) return null;
    const t = /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(v + "T23:59:59.999+08:00")
      : new Date(/(Z|[+-]\d{2}:?\d{2})$/.test(v) ? v : v + "+08:00");
    return isNaN(t) ? null : t;
  };
  const validLabel = i => { const e = validEnd(i); if(!e) return "";
    const t = tp(new Date(e.getTime() - 1)); return `有效至 ${p(t.getUTCMonth()+1)}/${p(t.getUTCDate())}`; };

  // ---------- 資金來源標示 (data/source_funding.json is the single mapping; same matching rule as funding.py) ----------
  let fund = null;
  const fundingReady = fetch("data/source_funding.json", {cache:"no-store"}).then(r => r.json()).then(j => { fund = j; return j; }).catch(() => null);
  const prefixOk = (name, p) => name.startsWith(p) && (name.length === p.length || !/^[A-Za-z0-9]/.test(name.slice(p.length)));
  function fundingFor(name){
    if(!fund) return null;
    name = String(name || ""); let best = null, blen = -1;
    (fund.outlets || []).forEach(o => (o.match || []).forEach(p => { if(p.length > blen && prefixOk(name, p)){ best = o; blen = p.length; } }));
    const key = best ? best.label : "unlabeled", lab = (fund.labels || {})[key];
    if(!lab) return null;
    return {key, tag: lab.tag, desc: lab.desc, detail: best ? best.detail : "", basis: best ? best.basis : ""};
  }
  // 更正類型 (corrections.json / item.corrected `type`): 事實更正 = prominent amber tag, 用語調整 = quiet outlined tag
  function corrKind(t){ return t === "事實更正" ? "fact" : t === "用語調整" ? "wording" : ""; }
  function corrTag(t){ const k = corrKind(t); return k ? `<span class="ctag ${k}">${esc(t)}</span>` : ""; }
  // small neutral tag; hover/long-press text = label meaning + this outlet's documented basis
  function fundTag(name){
    const f = fundingFor(name); if(!f) return "";
    const tip = `資金來源：${f.tag}。${f.detail || f.desc}（說明見頁尾「資金來源標示」；此標示不代表報導品質或立場）`;
    return `<span class="fund fund-${esc(f.key)}" title="${esc(tip)}">${esc(f.tag)}</span>`;
  }
  // footer legend (element #fund-legend): every label + meaning, link to the mapping file
  function renderFundLegend(){
    const el = document.getElementById("fund-legend"); if(!el || !fund) return;
    el.innerHTML = `<h2>資金來源標示</h2>
      <p class="small">來源名稱旁的小標籤，只說明該媒體<strong>自己公開的資金來源</strong>（依其官網或官方文件），不代表報導品質或立場；無法確認者標「未標示」。</p>
      <ul class="fund-list">${Object.keys(fund.labels).map(k => `<li><span class="fund fund-${esc(k)}">${esc(fund.labels[k].tag)}</span>${esc(fund.labels[k].desc)}</li>`).join("")}</ul>
      <p class="small">各媒體的分類依據與出處：<a href="data/source_funding.json">source_funding.json</a>（檢查日 ${esc(fund.checked || "")}）。</p>`;
  }
  fundingReady.then(renderFundLegend);

  const sourceList = i => `<ul>${i.sources.map(s =>
    `<li>${esc(s.name)}${fundTag(s.name)}：<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("")}</ul>`;

  function refs(links, byUrl){
    const ss = links.map(u => byUrl[u]).filter(Boolean);
    const cnt = {}; ss.forEach(x => cnt[x.name] = (cnt[x.name]||0)+1);
    const seen = {};
    return ss.map(x => {
      seen[x.name] = (seen[x.name]||0)+1;
      const label = cnt[x.name] > 1 ? `${x.name}${seen[x.name]}` : x.name;
      return `<a href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(x.title)}">${esc(label)}</a>`;
    }).join("");
  }

  // Generic: any item may carry `sections: [{id,title,bullets:[{text,links:[url]}]}]`.
  function sectionsHtml(i, openFirst){
    if(!i.sections || !i.sections.length) return "";
    const byUrl = {}; (i.sources||[]).forEach(s => byUrl[s.url] = s);
    return `<div class="sections">
      <div class="sec-tools"><button type="button" class="sec-toggle" data-open="0">全部展開</button></div>
      ${i.sections.map((s,n) => `
      <details class="sec" ${openFirst && n===0 ? "open" : ""}>
        <summary><span class="sec-title">${esc(s.title)}</span><span class="sec-count">${s.bullets.length} 項</span></summary>
        <ul class="bullets">${s.bullets.map(b => `
          <li>${esc(b.text)}<span class="refs">${refs(b.links||[], byUrl)}</span></li>`).join("")}
        </ul>
      </details>`).join("")}
    </div>`;
  }


  // ---------- related stories (`related: [{id, title?}]`) ----------
  // Targets live in news.json (same page: #id) or archive.json (archive.html#id). Call NN.setRelatedIndex() once data is loaded.
  let relIndex = {news: {}, archive: {}};
  function setRelatedIndex(newsItems, archiveItems){
    const m = (l, o) => { (l || []).forEach(x => { if(x && x.id) o[x.id] = x; }); return o; };
    relIndex = {news: m(newsItems, {}), archive: m(archiveItems, {})};
  }
  // `page` = the page being rendered ("index" or "archive"): decides whether a link stays on the page.
  function relatedHtml(i, page){
    const rel = Array.isArray(i.related) ? i.related : [];
    const links = rel.filter(r => r && r.id).map(r => {
      const inNews = relIndex.news[r.id], inArch = relIndex.archive[r.id];
      const target = inNews || inArch;
      const title = (target && target.title) || r.title || r.id;
      const here = (inNews && page === "index") || (!inNews && page === "archive");
      const base = inNews ? (page === "index" ? "" : "./") : (page === "archive" ? "" : "archive.html");
      const href = base + "#" + encodeURIComponent(r.id);
      const tag = inNews ? "" : (inArch ? `<span class="rel-tag">過往新聞</span>` : "");
      return `<li><a class="rel-link" href="${esc(href)}" data-rel="${esc(r.id)}" data-local="${here ? "1" : ""}">${esc(title)}</a>${tag}</li>`;
    });
    return links.length ? `<div class="related"><strong>相關報導</strong><ul>${links.join("")}</ul></div>` : "";
  }

  function bindToggles(root){
    root.querySelectorAll(".sec-toggle").forEach(btn => btn.addEventListener("click", () => {
      const open = btn.dataset.open !== "1";
      btn.dataset.open = open ? "1" : "0";
      btn.textContent = open ? "全部收合" : "全部展開";
      btn.closest(".sections").querySelectorAll("details.sec").forEach(d => d.open = open);
    }));
  }

  function itemBody(i, opts){
    opts = opts || {};
    const sectioned = !!(i.sections && i.sections.length);
    return `
          <h3>${esc(i.title)}</h3>
          ${i.corrected ? `<p class="corrected-note ${corrKind(i.corrected.type)}"><strong>已更正</strong>${corrTag(i.corrected.type)}（${esc(i.corrected.date)}）${esc(i.corrected.note)}　<a href="corrections.html">更正紀錄</a></p>` : ""}
          <p class="summary ${sectioned ? "lines" : ""}">${esc(i.summary)}</p>
          <dl class="facts">
            <dt>影響誰</dt><dd>${esc(i.who)}</dd>
            <dt>影響什麼</dt><dd>${esc(i.what)}</dd>
            <dt>何時開始</dt><dd>${esc(i.when)}</dd>
          </dl>
          ${i.taiwanImpact ? `<p class="tw-impact"><strong>對台灣的影響</strong>${esc(i.taiwanImpact)}</p>` : ""}
          ${relatedHtml(i, opts.page || "archive")}
          ${sectionsHtml(i, opts.openFirst !== false)}
          ${sectioned
            ? `<details class="sources all-sources"><summary>全部來源（${i.sources.length}）</summary>${sourceList(i)}</details>`
            : `<div class="sources">原始報導與資料來源${sourceList(i)}</div>`}`;
  }

  // ---------- v2: category chips (stable colour per category) ----------
  // Known categories keep a fixed slot (independent of what is on the page today); any new category
  // (e.g. 政治) falls back to a stable hash of its name into the same palette. Chips always carry the text label.
  const CHIP_KNOWN = ["物價與薪資","稅務與補助","健保與醫療","房價與租屋","能源與水電","交通","教育","天災與公共安全","勞動與產業","新法規"];
  const CHIP_SLOTS = 10;
  function chipIndex(cat){
    const k = CHIP_KNOWN.indexOf(cat);
    if(k >= 0) return k;
    let h = 5381; const s = String(cat || "");
    for(let n = 0; n < s.length; n++) h = ((h * 33) ^ s.charCodeAt(n)) >>> 0;
    return h % CHIP_SLOTS;
  }
  const chip = cat => cat ? `<span class="chip c${chipIndex(cat)}">${esc(cat)}</span>` : "";

  // ---------- v2: teaser (first 1-2 sentences) shown while a card is collapsed ----------
  function splitSummary(summary){
    const text = String(summary || "").trim();
    if(!text) return ["", ""];
    const lines = text.split("\n").map(x => x.trim()).filter(Boolean);
    if(lines.length > 1) return [lines[0], lines.slice(1).join("\n")];   // sectioned items: first line = latest status
    const sents = text.match(/[^。！？]*[。！？]/g) || [text];
    let n = 1, head = sents[0];
    if(head.length < 45 && sents.length > 1){ head += sents[1]; n = 2; }
    const rest = sents.slice(n).join("") + text.slice(sents.join("").length);
    return [head, rest.trim()];
  }

  // collapsed card: one link per publisher (first article), at most 4 publishers; the full list is in the expanded body
  function sourceLinks(i){
    const groups = [];
    (i.sources || []).forEach(x => {
      const g = groups.find(y => y.name === x.name);
      if(g) g.n++; else groups.push({name: x.name, url: x.url, title: x.title, n: 1});
    });
    const shown = groups.slice(0, 4).map(g =>
      `<span class="src-item"><a href="${esc(g.url)}" target="_blank" rel="noopener" title="${esc(g.title)}">${esc(g.name)}${g.n > 1 ? `<span class="n">×${g.n}</span>` : ""}</a>${fundTag(g.name)}</span>`).join("");
    const more = groups.length > 4 ? `<span class="src-more">等 ${(i.sources || []).length} 則</span>` : "";
    return shown + more;
  }

  // Collapsible news card. Collapsed: badges, chip, title, 已更正 note, teaser, sources.
  // Expanded (button, aria-expanded): rest of summary, 影響誰/什麼/何時, 對台灣的影響, sections, full source list.
  function cardHtml(i, o){
    o = o || {};
    const breaking = String(i.status || "").startsWith("快訊");
    const live = !!(i.ongoing && !i.ongoing.ended);
    const sectioned = !!(i.sections && i.sections.length);
    const [head, rest] = splitSummary(i.summary);
    const pid = "body-" + i.id;
    const cls = ["item", "card", o.featured ? "featured" : "", breaking ? "breaking" : "", live ? "live" : "", sectioned ? "has-sections" : ""].filter(Boolean).join(" ");
    return `
        <article class="${cls}" id="${esc(i.id)}">
          <div class="badges">
            <span class="badge ${breaking ? "prelim" : "full"}">${esc(i.status)}</span>
            ${live ? `<span class="badge live">進行中</span>` : ""}
            ${i.valid_until && validLabel(i) ? `<span class="badge valid">${esc(validLabel(i))}</span>` : ""}
            ${o.showCat === false ? "" : chip(i.category)}
          </div>
          <h3>${esc(i.title)}</h3>
          ${i.corrected ? `<p class="corrected-note ${corrKind(i.corrected.type)}"><strong>已更正</strong>${corrTag(i.corrected.type)}（${esc(i.corrected.date)}）${esc(i.corrected.note)}　<a href="corrections.html">更正紀錄</a></p>` : ""}
          <p class="summary teaser">${esc(head)}</p>
          <div class="card-meta">
            <span class="when-line">發布 ${fmt(first(i))}${i.updated ? `　更新 ${fmt(i.updated)}` : ""}</span>
            <span class="src-line"><span class="src-label">來源</span>${sourceLinks(i)}</span>
          </div>
          <div class="card-body" id="${esc(pid)}" hidden>
            ${rest ? `<p class="summary rest ${sectioned ? "lines" : ""}">${esc(rest)}</p>` : ""}
            <dl class="facts">
              <dt>影響誰</dt><dd>${esc(i.who)}</dd>
              <dt>影響什麼</dt><dd>${esc(i.what)}</dd>
              <dt>何時開始</dt><dd>${esc(i.when)}</dd>
            </dl>
            ${i.taiwanImpact ? `<p class="tw-impact"><strong>對台灣的影響</strong>${esc(i.taiwanImpact)}</p>` : ""}
            ${relatedHtml(i, "index")}
            ${sectionsHtml(i, true)}
            <details class="sources all-sources"><summary>原始報導與資料來源（${(i.sources || []).length}）</summary>${sourceList(i)}</details>
          </div>
          <button type="button" class="card-toggle" aria-expanded="false" aria-controls="${esc(pid)}"><span class="lbl">展開全文</span><span class="ico" aria-hidden="true"></span></button>
        </article>`;
  }

  function setExpanded(card, open){
    const btn = card.querySelector(".card-toggle"), body = card.querySelector(".card-body");
    if(!btn || !body) return;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.querySelector(".lbl").textContent = open ? "收合" : "展開全文";
    body.hidden = !open;
    card.classList.toggle("expanded", open);
  }
  function bindCards(root){
    root.querySelectorAll(".card-toggle").forEach(btn => btn.addEventListener("click", () => {
      setExpanded(btn.closest(".card"), btn.getAttribute("aria-expanded") !== "true");
    }));
  }

  // banner date (Taiwan time) e.g. 2026年10月27日 星期二
  function bannerDate(){
    const el = document.getElementById("today-date"); if(!el) return;
    const t = tp(new Date()); const wd = "日一二三四五六"[t.getUTCDay()];
    el.textContent = `${t.getUTCFullYear()}年${t.getUTCMonth()+1}月${t.getUTCDate()}日 星期${wd}`;
  }
  document.addEventListener("DOMContentLoaded", bannerDate);

  return {fmt, fmtDate, esc, first, validEnd, validLabel, sectionsHtml, bindToggles, itemBody, tp,
          chip, chipIndex, cardHtml, corrKind, corrTag, fundingReady, fundingFor, fundTag, setRelatedIndex, relatedHtml, bindCards, setExpanded, splitSummary};
})();
