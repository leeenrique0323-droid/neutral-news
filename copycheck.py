"""copycheck: flag wording copied too closely from an item's source pages (see AUTOMATION.md「摘要寫法與相似度檢查」).

  python3 update.py copycheck               # every item in data/news.json
  python3 update.py copycheck --new         # only items new or changed vs. git HEAD (fast; for scheduled runs)
  python3 update.py copycheck --ids a,b     # only these item ids
  options: --min N (run length, default 20) --refresh (ignore page cache) --archive (also data/archive.json)

For each item, every source page is fetched (cached under raw/copycheck/, browser User-Agent, timeout, no block
bypass: a 403/timeout/captcha page is reported as SKIPPED, never retried around) and the article text is compared
with our text fields (title, summary, who, what, when, taiwanImpact, section bullets). Both sides are normalized
(NFKC, whitespace and punctuation removed); any run of MIN_RUN+ consecutive identical characters is a hit unless it is
  - inside 「」/『』/“” quotes in our text (attributed quotes, programme names), or
  - mostly digits/dates/units/Latin letters or names: after removing digits, ASCII, date/unit characters and names
    (terms quoted in the source or our text, source/outlet names, and the item's `copycheck_names` list, optional),
    fewer than MIN_SUBSTANTIVE characters remain.
Media sources: hit = FAIL (exit 1). Government sources (data/source_funding.json label `government`, 政府機關): WARN only.
Network failures are SKIPPED (not failures). This command needs network; `validate` never calls it.
"""
import hashlib, html, json, os, re, subprocess, sys, time, unicodedata, urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "raw", "copycheck")      # raw/ is gitignored
CACHE_HOURS = 72
MIN_RUN = 20
MIN_SUBSTANTIVE = 10
TIMEOUT = 20
DELAY = 1.5   # seconds between network requests (same politeness as fetch.py)
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
FIELDS = ("title", "summary", "who", "what", "when", "taiwanImpact")
# characters that do not count as "substantive" wording (dates, units, counters)
UNIT_CHARS = set("年月日時分秒點元萬億千百十個件人次名位架班座台輛張度級號週周")
QUOTE_RE = re.compile(r"「[^「」]*」|『[^『』]*』|“[^“”]*”|\"[^\"]*\"")
BLOCK_MARKERS = ("Request Rejected", "Access Denied", "captcha", "Just a moment", "Attention Required")

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "header", "footer", "nav", "aside", "form", "svg", "button", "select"}
    KEEP = {"p", "h1", "h2", "h3", "td", "blockquote"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0; self.keep = 0; self.par = []; self.all = []; self.cur = []
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        elif tag in self.KEEP: self.keep += 1; self.cur = []
        elif tag == "br": self.all.append("\n")
    def handle_endtag(self, tag):
        if tag in self.SKIP: self.skip = max(0, self.skip - 1)
        elif tag in self.KEEP and self.keep:
            self.keep -= 1
            t = "".join(self.cur).strip()
            if t: self.par.append(t)
            self.cur = []
    def handle_data(self, data):
        if self.skip: return
        self.all.append(data)
        if self.keep: self.cur.append(data)

def extract_text(raw_html):
    p = _Text()
    try: p.feed(raw_html)
    except Exception: pass
    par = "\n".join(p.par)
    if len(par) >= 200: return par
    return re.sub(r"\s+", " ", "".join(p.all))

def _cache_path(url):
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")

_last_net = [0.0]
def get_page(url, refresh=False):
    """-> (html or None, status string). Cached; never bypasses blocks."""
    path = _cache_path(url)
    if not refresh and os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_HOURS * 3600:
        return open(path, encoding="utf-8", errors="replace").read(), "cache"
    wait = DELAY - (time.time() - _last_net[0])
    if wait > 0: time.sleep(wait)
    _last_net[0] = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception as e:
        # e.g. 403 / captcha / SSL / timeout: report and move on (no bypass, no retry tricks)
        r = subprocess.run(["curl", "-sS", "-L", "--max-time", str(TIMEOUT), "-A", UA, "-w", "\n%{http_code}", url],
                           capture_output=True, text=True) if "CERTIFICATE" in str(e).upper() else None
        if r is None or r.returncode != 0 or not r.stdout.rstrip().endswith("200"):
            return None, f"network error: {str(e)[:80]}"
        body = r.stdout.rstrip()[:-3]
    if len(body) < 2000 and any(m.lower() in body.lower() for m in BLOCK_MARKERS):
        return None, "blocked page (not bypassed)"
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh: fh.write(body)
    return body, "fetched"

def seed_cache(url, path):
    """Put an already-fetched page (e.g. from an audit) into the cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    dst = _cache_path(url)
    if not os.path.exists(dst):
        with open(path, encoding="utf-8", errors="replace") as s, open(dst, "w", encoding="utf-8") as d: d.write(s.read())

SEP = "\x00"
def _is_sep(ch):
    c = unicodedata.category(ch)
    return ch.isspace() or c.startswith("P") or c.startswith("S") or c in ("Cc", "Cf", "Zs")

def norm_keep_map(s, mask_quotes=False):
    """NFKC, quotes masked (-> SEP), whitespace/punctuation dropped. Returns normalized string."""
    s = unicodedata.normalize("NFKC", s or "")
    if mask_quotes: s = QUOTE_RE.sub(SEP, s)
    out = []
    for ch in s:
        if ch == SEP: out.append(SEP)
        elif not _is_sep(ch): out.append(ch.lower())
    return "".join(out)

def common_runs(a, b, minlen):
    """Maximal substrings of a (>= minlen, no SEP) that occur in b; greedy left to right."""
    res, i = [], 0
    while i <= len(a) - minlen:
        chunk = a[i:i + minlen]
        if SEP not in chunk and chunk in b:
            L = minlen
            while i + L < len(a) and a[i + L] != SEP and a[i:i + L + 1] in b: L += 1
            res.append(a[i:i + L]); i += L
        else:
            i += 1
    return res

def substantive(run, names):
    r = run
    for n in sorted(names, key=len, reverse=True):
        if len(n) >= 2: r = r.replace(n, SEP)
    return sum(1 for ch in r if ch != SEP and not ch.isascii() and not ch.isdigit() and ch not in UNIT_CHARS)

def name_terms(item, texts):
    names = set()
    for t in texts:
        for q in QUOTE_RE.findall(unicodedata.normalize("NFKC", t or "")):
            n = norm_keep_map(q[1:-1])
            if 2 <= len(n) <= 30: names.add(n)
    for s in item.get("sources") or []:
        names.add(norm_keep_map(s.get("name")))
    for n in item.get("copycheck_names") or []:
        names.add(norm_keep_map(n))
    return {n for n in names if n}

def our_texts(item):
    out = [(k, item[k]) for k in FIELDS if isinstance(item.get(k), str) and item[k]]
    for s in item.get("sections") or []:
        for n, b in enumerate(s.get("bullets") or [], 1):
            if b.get("text"): out.append((f"sections/{s.get('id')}#{n}", b["text"]))
    return out

def check_item(item, minlen=MIN_RUN, refresh=False, log=print):
    """-> list of (level, url, field, run) with level FAIL/WARN, and list of skipped (url, why)."""
    import funding
    hits, skipped = [], []
    fields = our_texts(item)
    for s in item.get("sources") or []:
        url = s.get("url") or ""
        gov = funding.funding_for(s.get("name", ""))["label"] == "government"
        page, status = get_page(url, refresh)
        if page is None:
            skipped.append((url, status)); continue
        body = extract_text(page)
        names = name_terms(item, [body] + [t for _, t in fields])
        b = norm_keep_map(body + "\n" + (s.get("title") or ""))
        for fld, text in fields:
            for run in common_runs(norm_keep_map(text, mask_quotes=True), b, minlen):
                if substantive(run, names) >= MIN_SUBSTANTIVE:
                    hits.append(("WARN" if gov else "FAIL", url, fld, run))
    return hits, skipped

def changed_ids(items, root=ROOT):
    """Items whose content differs from git HEAD (new ids included)."""
    try:
        r = subprocess.run(["git", "-C", root, "show", "HEAD:data/news.json"], capture_output=True, text=True, timeout=20)
        prev = {x["id"]: x for x in json.loads(r.stdout)["items"]} if r.returncode == 0 else {}
    except Exception:
        prev = {}
    keys = FIELDS + ("sections", "sources")
    return [i["id"] for i in items if i["id"] not in prev or any(i.get(k) != prev[i["id"]].get(k) for k in keys)]

def run(items, ids=None, new=False, minlen=MIN_RUN, refresh=False):
    sel = items
    if new:
        ch = set(changed_ids(items)); sel = [i for i in items if i["id"] in ch]
    if ids:
        want = set(ids); sel = [i for i in items if i["id"] in want]
        for m in want - {i["id"] for i in sel}: print(f"[copycheck] unknown id {m}")
    print(f"copycheck: {len(sel)} item(s), run >= {minlen} identical characters (media = FAIL, 政府機關 = WARN, network problems = SKIPPED)")
    fails = warns = skips = 0
    for it in sel:
        hits, skipped = check_item(it, minlen, refresh)
        f = [h for h in hits if h[0] == "FAIL"]; w = [h for h in hits if h[0] == "WARN"]
        fails += len(f); warns += len(w); skips += len(skipped)
        state = "FAIL" if f else ("WARN" if w else "ok")
        print(f"[{state}] {it['id']}" + (f"  ({len(skipped)} source(s) skipped)" if skipped else ""))
        for lvl, url, fld, r in hits:
            print(f"    {lvl} {fld}: {len(r)} chars identical to {url}: {r}")
        for url, why in skipped:
            print(f"    SKIPPED {url}: {why}")
    print(f"copycheck done: {fails} fail, {warns} warn, {skips} skipped source(s)"
          + (" -> rewrite flagged text in your own words (先列事實再用自己的話寫，不照原文句序), record a 用語調整 correction if already published" if fails else ""))
    return 1 if fails else 0
