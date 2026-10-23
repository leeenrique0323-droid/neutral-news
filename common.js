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

  const sourceList = i => `<ul>${i.sources.map(s =>
    `<li>${esc(s.name)}：<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("")}</ul>`;

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
          <p class="summary ${sectioned ? "lines" : ""}">${esc(i.summary)}</p>
          <dl class="facts">
            <dt>影響誰</dt><dd>${esc(i.who)}</dd>
            <dt>影響什麼</dt><dd>${esc(i.what)}</dd>
            <dt>何時開始</dt><dd>${esc(i.when)}</dd>
          </dl>
          ${i.taiwanImpact ? `<p class="tw-impact"><strong>對台灣的影響</strong>${esc(i.taiwanImpact)}</p>` : ""}
          ${sectionsHtml(i, opts.openFirst !== false)}
          ${sectioned
            ? `<details class="sources all-sources"><summary>全部來源（${i.sources.length}）</summary>${sourceList(i)}</details>`
            : `<div class="sources">原始報導與資料來源${sourceList(i)}</div>`}`;
  }

  return {fmt, fmtDate, esc, first, sectionsHtml, bindToggles, itemBody, tp};
})();
