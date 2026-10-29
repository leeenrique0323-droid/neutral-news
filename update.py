#!/usr/bin/env python3
"""Update pipeline for 民生新聞.

  python3 update.py fetch      # run fetch.py + cwa.py, list NEW candidate items -> data/new_candidates.json
                               # (a repeat call within 10 min reuses the file; --force to refetch)
  python3 update.py archive    # move expired items from data/news.json to data/archive.json (never deletes)
  python3 update.py validate   # check data/news.json against the editorial schema (fails on expired items)
  python3 update.py finalize   # archive expired, validate, stamp `updated`, screenshots, zip
  python3 update.py log [-n N] # print the last N (default 10) entries of data/fetch_log.jsonl
  python3 update.py feedhealth # per-feed success rate + consecutive failures from the fetch log (>=3 in a row listed first)
  python3 update.py copycheck [--new | --ids a,b]  # flag 20+ identical characters (FAIL) and >40% overlap in 12+ char runs (WARN) vs. source pages (needs network; see copycheck.py)

Writing/curating summaries into data/news.json is an editorial step between
`fetch` and `finalize` (see AUTOMATION.md). This script never invents content.
"""
import argparse, difflib, json, os, re, subprocess, sys, time, unicodedata, zipfile
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
NEWS = os.path.join(ROOT, "data", "news.json")
CANDS = os.path.join(ROOT, "candidates.json")
NEWC = os.path.join(ROOT, "data", "new_candidates.json")
CWA = os.path.join(ROOT, "cwa_alerts.json")
CORRECTIONS = os.path.join(ROOT, "data", "corrections.json")
ARCHIVE = os.path.join(ROOT, "data", "archive.json")
FETCH_LOG = os.path.join(ROOT, "data", "fetch_log.jsonl")
TPE = timezone(timedelta(hours=8))
STATUSES = {"快訊・初步資訊", "完整版"}
CORRECTION_TYPES = ("事實更正", "用語調整")   # corrections.json `type` (required); see AUTOMATION.md「更正類型」
REQUIRED = ["id", "tab", "category", "status", "title", "summary", "who", "what", "when", "published",
            "first_published", "sources"]

# --- expiry / length rules (keep in sync with AUTOMATION.md) ---
KEEP_HOURS = 48            # normal items: archived 48h after first_published (never changes on update)
WRAPUP_HOURS = 24          # ongoing stories: upper bound for the post-event wrap-up after `ongoing.ended`
ONGOING_MAX_HOURS = 168    # safety cap: even an "ongoing" item is archived 7 days after first_published
VALID_MAX_DAYS = 14        # items with `valid_until`: hard cap after first_published (nothing lingers forever)
ONGOING_CATEGORY = "天災與公共安全"
SUMMARY_MAX = 250          # normal summary (characters; 2026-10-29: was 300)
SUMMARY_MAX_SECTIONED = 200  # items with `sections`: short status block
SUMMARY_MAX_LINES = 4      # newline-separated lines
FACT_MAX = 200             # who / what / when (characters)
SECTION_MAX = 8            # sections per item
BULLETS_MIN, BULLETS_MAX = 2, 5
BULLET_MAX = 260           # characters per bullet

# --- fetch / duplicate rules (keep in sync with AUTOMATION.md) ---
FETCH_LOG_MAX = 500        # data/fetch_log.jsonl keeps only the last this-many lines
FETCH_REUSE_MINUTES = 10   # `fetch` reuses data/new_candidates.json younger than this unless --force
TITLE_SIM_MAX = 0.85       # validate: normalized-title similarity above this (with identical numbers) = duplicate
SHARED_URL_HOSTS = ("cwa.gov.tw",)  # official hub pages legitimately cited as primary source by several items

def load():
    return json.load(open(NEWS, encoding="utf-8"))

def save(d):
    tmp = NEWS + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, NEWS)

def norm(u):
    return re.sub(r"[?#].*$", "", u or "").rstrip("/")

def dt(x):
    return datetime.fromisoformat(x)

def valid_until_end(v):
    """`valid_until` (Taiwan time) -> the first instant it no longer applies.
    A plain date (YYYY-MM-DD) is valid through the END of that day; a datetime without
    an offset is read as Taiwan time. Raises ValueError for anything else."""
    if not isinstance(v, str): raise ValueError("valid_until must be a string")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=TPE) + timedelta(days=1)
    x = datetime.fromisoformat(v)
    return x if x.tzinfo else x.replace(tzinfo=TPE)

def expiry(i, hours=KEEP_HOURS):
    """Return the datetime after which the item must be archived, or None if it is
    currently allowed to stay open-ended (active ongoing story, subject to the hard cap).
    Always based on first_published (never on `updated`).
    Items with `valid_until` stay until it has passed (hard cap: VALID_MAX_DAYS after
    first_published); ongoing disaster items keep their own rules."""
    first = dt(i["first_published"])
    normal = first + timedelta(hours=hours)
    og = i.get("ongoing")
    if not og:
        if i.get("valid_until"):
            return min(valid_until_end(i["valid_until"]), first + timedelta(days=VALID_MAX_DAYS))
        return normal
    cap = first + timedelta(hours=ONGOING_MAX_HOURS)
    if not og.get("ended"):
        return cap                       # warning/event still active: stay (until the hard cap)
    ended = dt(og["ended"])
    after = ended if og.get("wrapup_done") else ended + timedelta(hours=WRAPUP_HOURS)
    return min(max(normal, after), cap)

def is_expired(i, now, hours=KEEP_HOURS):
    return now >= expiry(i, hours)

def git_first_published():
    """first_published values as committed at HEAD (immutability check). {} if unavailable."""
    try:
        r = subprocess.run(["git", "-C", ROOT, "show", "HEAD:data/news.json"], capture_output=True, text=True, timeout=20)
        if r.returncode != 0: return {}
        return {x["id"]: x.get("first_published") for x in json.loads(r.stdout)["items"]}
    except Exception:
        return {}

def load_archive():
    if os.path.exists(ARCHIVE):
        return json.load(open(ARCHIVE, encoding="utf-8"))
    return {"updated": None, "items": []}

def archive_expired(d, now, hours=KEEP_HOURS, reason=None, write=True):
    """Remove expired items from d["items"]; with write=True also append them to
    data/archive.json (items are archived, never deleted). Returns the moved items
    (each already carrying `archived` / `archive_reason`)."""
    keep, moved = [], []
    for i in d["items"]:
        if is_expired(i, now, hours):
            i = dict(i)
            i["archived"] = now.replace(microsecond=0).isoformat()
            i["archive_reason"] = reason or (
                "過期：進行中事件已結束並完成總結（或達上限）" if i.get("ongoing")
                else "過期：已過有效期限（或達%d天上限）" % VALID_MAX_DAYS if i.get("valid_until")
                else "過期：逾首次發布後%d小時" % hours)
            moved.append(i)
        else:
            keep.append(i)
    d["items"] = keep
    if moved and write:
        write_archive(moved, now)
    return moved

def write_archive(moved, now):
    a = load_archive()
    byid = {x["id"]: x for x in a["items"]}
    for i in moved:
        byid[i["id"]] = i
    a["items"] = sorted(byid.values(), key=lambda x: x["first_published"], reverse=True)
    a["updated"] = now.replace(microsecond=0).isoformat()
    tmp = ARCHIVE + ".tmp"
    json.dump(a, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, ARCHIVE)

def log_fetch(mode, new, feeds, cwa):
    """Append one JSON line per fetch (real or reused) to data/fetch_log.jsonl; keep the last FETCH_LOG_MAX lines.
    Never fatal: logging problems must not break a scheduled run."""
    try:
        cwa_items = []
        if cwa:
            for k in ("active_alerts", "typhoons", "earthquakes"):
                cwa_items += [x for x in cwa.get(k) or [] if isinstance(x, dict)]
        rec = {"ts": datetime.now(TPE).replace(microsecond=0).isoformat(), "mode": mode,
               "feeds_ok": [f["feed"] for f in feeds if f.get("ok")],
               "feeds_failed": [f["feed"] for f in feeds if not f.get("ok")],
               "feed_errors": {f["feed"]: str(f.get("error") or "")[:80] for f in feeds if not f.get("ok")},   # short reason per failed feed (HTTP 403, 0 items, timeout...)
               "candidates": len(new),
               "cwa_urgent": (sum(1 for x in cwa_items if x.get("urgent")) if cwa else None)}
        lines = []
        if os.path.exists(FETCH_LOG):
            lines = [l for l in open(FETCH_LOG, encoding="utf-8").read().splitlines() if l.strip()]
        lines.append(json.dumps(rec, ensure_ascii=False))
        tmp = FETCH_LOG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines[-FETCH_LOG_MAX:]) + "\n")
        os.replace(tmp, FETCH_LOG)
    except Exception as e:
        print(f"[fetch log] could not write {FETCH_LOG}: {e}")

def cmd_log(a):
    if not os.path.exists(FETCH_LOG):
        print("no fetch log yet"); return 0
    rows = [l for l in open(FETCH_LOG, encoding="utf-8").read().splitlines() if l.strip()]
    for l in rows[-a.n:] if a.n > 0 else []:
        try: r = json.loads(l)
        except ValueError: print(l); continue
        failed = ",".join(r.get("feeds_failed") or []) or "-"
        urgent = r.get("cwa_urgent")
        print(f"{r.get('ts')} {r.get('mode'):7} feeds ok {len(r.get('feeds_ok') or [])} failed {len(r.get('feeds_failed') or [])} ({failed})"
              f" | candidates {r.get('candidates')} | CWA urgent {'n/a' if urgent is None else urgent}")
    print(f"({min(a.n, len(rows)) if a.n > 0 else 0} of {len(rows)} entries; file: {FETCH_LOG})")
    return 0

FEED_FAIL_STREAK = 3       # feedhealth: this many consecutive failed (or 0-item) runs = "broken"
FEED_RECENT_RUNS = 20      # feedhealth: window for the "recent" success rate

def feed_health(rows, feed_names, window=FEED_RECENT_RUNS):
    """rows: parsed fetch-log records, oldest first. Only real fetches count ('fresh'/'forced'; 'reused'
    repeats the previous result without network, so it would double-count). A feed counts as failed when it is
    in `feeds_failed` (HTTP/parse error, timeout, or 0 items). Runs that do not mention a feed (logged before
    it was added) are skipped. Returns one dict per feed in feed_names order."""
    real = [r for r in rows if r.get("mode") in ("fresh", "forced")]
    out = []
    for name in feed_names:
        hist = []   # (ts, ok, error)
        for r in real:
            if name in (r.get("feeds_failed") or []):
                hist.append((r.get("ts"), False, (r.get("feed_errors") or {}).get(name, "")))
            elif name in (r.get("feeds_ok") or []):
                hist.append((r.get("ts"), True, ""))
        streak = 0
        for ts, ok, _ in reversed(hist):
            if ok: break
            streak += 1
        recent = hist[-window:]
        last_ok = next((ts for ts, ok, _ in reversed(hist) if ok), None)
        last_err = next((e for ts, ok, e in reversed(hist) if not ok and e), "")
        out.append({"feed": name, "runs": len(hist), "ok": sum(1 for h in hist if h[1]),
                    "recent_runs": len(recent), "recent_ok": sum(1 for h in recent if h[1]),
                    "streak": streak, "last_ok": last_ok, "last_error": last_err if streak else ""})
    return out

def cmd_feedhealth(a):
    path = a.log_file or FETCH_LOG
    if not os.path.exists(path):
        print("尚無抓取紀錄（data/fetch_log.jsonl）；先執行 `python3 update.py fetch`。"); return 0
    rows = []
    for l in open(path, encoding="utf-8").read().splitlines():
        try: rows.append(json.loads(l))
        except ValueError: pass
    import fetch as _fetch
    names = [n for n, _tab, _url in _fetch.FEEDS]
    real = [r for r in rows if r.get("mode") in ("fresh", "forced")]
    h = feed_health(rows, names, a.recent)
    def rate(ok, n): return f"{100 * ok / n:.0f}%" if n else "—"
    def line(x):
        s = f"{x['feed']}：近 {x['recent_runs']} 次成功率 {rate(x['recent_ok'], x['recent_runs'])}（{x['recent_ok']}/{x['recent_runs']}），全部 {rate(x['ok'], x['runs'])}（{x['ok']}/{x['runs']}）"
        if x["streak"]:
            s += f"，連續失敗 {x['streak']} 次"
            if x["last_error"]: s += f"（最近原因：{x['last_error']}）"
            s += f"，上次成功：{x['last_ok'] or '從未成功'}"
        return "  " + s
    print(f"來源健康檢查：{len(names)} 個來源，{len(real)} 次實際抓取（略過 reused）"
          + (f"，紀錄期間 {real[0].get('ts')} ～ {real[-1].get('ts')}" if real else ""))
    if not real:
        print("沒有實際抓取的紀錄可分析。"); return 0
    broken = sorted([x for x in h if x["streak"] >= a.threshold], key=lambda x: -x["streak"])
    watch = sorted([x for x in h if 0 < x["streak"] < a.threshold], key=lambda x: -x["streak"])
    shaky = [x for x in h if x["streak"] == 0 and x["runs"] and x["ok"] < x["runs"]]
    unseen = [x for x in h if x["runs"] == 0]
    print(f"\n【連續失敗 ≥ {a.threshold} 次（或 0 筆資料）】{len(broken)} 個")
    print("\n".join(line(x) for x in broken) if broken else "  無")
    print(f"\n【觀察中：連續失敗 1–{a.threshold - 1} 次】{len(watch)} 個（單次失敗，例如偶發 403，可能只是暫時性，持續出現才算壞掉）")
    if watch: print("\n".join(line(x) for x in watch))
    if shaky or a.all:
        print(f"\n【目前正常、但曾失敗】{len(shaky)} 個")
        print("\n".join(line(x) for x in sorted(shaky, key=lambda x: x['recent_ok'] / max(x['recent_runs'], 1))) if shaky else "  無")
    if unseen: print(f"\n【紀錄中尚無資料】{len(unseen)} 個：" + "、".join(x["feed"] for x in unseen))
    ok_all = [x for x in h if x["runs"] and x["ok"] == x["runs"]]
    print(f"\n全部抓取皆成功：{len(ok_all)} 個" + ("" if not a.all else "\n" + "\n".join(line(x) for x in ok_all)))
    print("（說明：失敗＝HTTP/解析錯誤、逾時或 0 筆資料；紀錄最多約 500 次執行。更換壞掉的來源前請先用 curl 驗證替代來源，見 AUTOMATION.md「來源健康檢查」。）")
    return 0

def print_new_list(new):
    for x in new:
        tag = "國際" if x["tab"] == "intl" else "台灣"
        print(f"- [{x['tab']}] {tag} | {x.get('source', '?')} [資金:{x.get('funding', '?')}] | {','.join(x['categories'])} | {x['title']} | {x['link']}")

def mix_line():
    """Informational only: current 國際 share in news.json vs. the editorial target (about one third). Never fatal."""
    try:
        items = load()["items"]
        n_intl = sum(1 for i in items if i.get("tab") == "intl")
        need = max(0, -(-(len(items) - 3 * n_intl) // 2))   # extra 國際 items m so that (k+m)/(t+m) = 1/3 -> m = (t-3k)/2
        return (f"[mix] 國際 {n_intl}/{len(items)} items on site now ({(100 * n_intl / len(items)) if items else 0:.0f}%), target about 1/3"
                + (f" - about {need} below the 1/3 goal (goal only: same selection rules and daily caps, do not pad or prefer 國際 candidates)" if n_intl * 3 < len(items) else " - target met"))
    except Exception as e:
        return f"[mix] unavailable ({e})"

def fetch_summary_line(tag, new, feeds, cwa, extra=""):
    bad = [f for f in feeds if not f["ok"]]
    urgent = "n/a" if cwa is None else ("YES" if cwa.get("urgent") else "no")
    return (f"[fetch {tag}] {len(new)} new candidates | feed failures: {len(bad)} | CWA urgent: {urgent}"
            f" | file: {NEWC}{extra}")

def cmd_fetch(a):
    # Duplicate-fetch guard: AUTOMATION.md says fetch once per run. A second call within
    # FETCH_REUSE_MINUTES re-uses the previous result (no network) unless --force is given.
    if not a.force and os.path.exists(NEWC):
        age_min = (time.time() - os.path.getmtime(NEWC)) / 60
        if 0 <= age_min < FETCH_REUSE_MINUTES:
            try:
                prev = json.load(open(NEWC, encoding="utf-8"))
                used = {norm(s["url"]) for i in load()["items"] for s in i["sources"]}
                new = [x for x in prev["new"] if norm(x["link"]) not in used]   # drop ones added to news.json since
                print(f"[fetch REUSED] already fetched this run ({age_min:.1f} min ago, < {FETCH_REUSE_MINUTES} min); "
                      f"reusing {NEWC} - no network requests made. Use `update.py fetch --force` to fetch again.")
                print(fetch_summary_line("REUSED", new, prev["feeds"], prev.get("cwa"), f" | generated: {prev['generated']}"))
                print(mix_line())
                for f in prev["feeds"]:
                    if not f["ok"]: print(f"[FEED FAIL] {f['feed']}: {f.get('error')}")
                if os.path.exists(CWA):
                    print("\n" + "=" * 60)
                    try:
                        import cwa as _cwa
                        _cwa.print_summary(json.load(open(CWA, encoding="utf-8")))
                    except Exception as e:
                        print(f"(CWA summary unavailable from cache: {e}; see {NEWC} `cwa` field)")
                    print("=" * 60 + "\n")
                print(f"{len(new)} new candidates -> {NEWC}")
                print_new_list(new)
                log_fetch("reused", new, prev["feeds"], prev.get("cwa"))
                return 0
            except (OSError, ValueError, KeyError) as e:
                print(f"[fetch] cached {NEWC} unreadable ({e}); fetching fresh")
    subprocess.run([sys.executable, os.path.join(ROOT, "fetch.py"), "-o", CANDS, "--hours", str(a.hours)], check=True)
    c = json.load(open(CANDS, encoding="utf-8"))
    used = {norm(s["url"]) for i in load()["items"] for s in i["sources"]}
    seen, new = set(), []
    for x in c["candidates"]:
        k = norm(x["link"])
        if k in used or k in seen:
            continue
        seen.add(k); new.append(x)
    # Official CWA warnings/earthquakes (keyless; optional CWA_API_KEY). Never fatal.
    print("\n" + "=" * 60, flush=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "cwa.py"), "-o", CWA])
    cwa = None
    if r.returncode == 0 and os.path.exists(CWA):
        cwa = json.load(open(CWA, encoding="utf-8"))
    else:
        print("[FEED FAIL] CWA: cwa.py failed; check https://www.cwa.gov.tw/V8/C/P/Warning/FIFOWS.html manually")
    print("=" * 60 + "\n")
    json.dump({"generated": c["generated"], "feeds": c["feeds"], "new": new,
               "cwa": ({k: cwa[k] for k in ("generated", "urgent", "active_alerts", "typhoons", "earthquakes")} if cwa else None)},
              open(NEWC, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    bad = [f for f in c["feeds"] if not f["ok"]]
    log_fetch("forced" if a.force else "fresh", new, c["feeds"], cwa)
    print(fetch_summary_line("FRESH", new, c["feeds"], cwa))
    print(mix_line())
    print(f"{len(new)} new candidates -> {NEWC}")
    for f in bad:
        print(f"[FEED FAIL] {f['feed']}: {f.get('error')}")
    print_new_list(new)

def validate(d, now=None, hours=KEEP_HOURS, check_git=True, check_archive=True):
    errs = []
    cats = set(d.get("categories", []))
    ids = set()
    prev = git_first_published() if check_git else {}
    known_ids = {x.get("id") for x in d["items"]} | {x.get("id") for x in (load_archive()["items"] if check_archive else [])}
    for i in d["items"]:
        tag = i.get("id", "?")
        for k in REQUIRED:
            if not i.get(k):
                errs.append(f"{tag}: missing {k}")
        if i.get("id") in ids: errs.append(f"{tag}: duplicate id")
        ids.add(i.get("id"))
        if i.get("tab") not in ("tw", "intl"): errs.append(f"{tag}: bad tab")
        if i.get("category") not in cats: errs.append(f"{tag}: category not in list")
        if i.get("status") not in STATUSES: errs.append(f"{tag}: bad status")
        if i.get("tab") == "intl" and not i.get("taiwanImpact"): errs.append(f"{tag}: intl item needs taiwanImpact")
        urls = set()
        for s in i.get("sources", []):
            if not re.match(r"^https?://", s.get("url", "")): errs.append(f"{tag}: bad source url")
            urls.add(s.get("url"))
        bad_dt = set()
        for k in ("published", "first_published", "updated"):
            if i.get(k):
                try: datetime.fromisoformat(i[k])
                except ValueError: errs.append(f"{tag}: bad {k}"); bad_dt.add(k)
        if i.get("published") and i.get("first_published") and i["published"] != i["first_published"]:
            errs.append(f"{tag}: published must equal first_published (first_published never changes)")
        if i.get("id") in prev and prev[i["id"]] and i.get("first_published") != prev[i["id"]]:
            errs.append(f"{tag}: first_published changed from committed value {prev[i['id']]} (must never change)")
        # --- length limits ---
        summ = i.get("summary") or ""
        has_sections = bool(i.get("sections"))
        smax = SUMMARY_MAX_SECTIONED if has_sections else SUMMARY_MAX
        if len(summ) > smax:
            errs.append(f"{tag}: summary {len(summ)} chars > {smax} (rewrite, don't append; move detail into sections)")
        if len([x for x in summ.split("\n") if x.strip()]) > SUMMARY_MAX_LINES:
            errs.append(f"{tag}: summary has more than {SUMMARY_MAX_LINES} lines")
        for k in ("who", "what", "when"):
            if len(i.get(k) or "") > FACT_MAX:
                errs.append(f"{tag}: {k} {len(i[k])} chars > {FACT_MAX}")
        # --- sections ---
        secs = i.get("sections")
        if secs is not None:
            if not isinstance(secs, list) or not secs: errs.append(f"{tag}: sections must be a non-empty list")
            else:
                if len(secs) > SECTION_MAX: errs.append(f"{tag}: more than {SECTION_MAX} sections")
                sids = set()
                for s in secs:
                    sid = s.get("id") or "?"
                    if not s.get("id") or not s.get("title"): errs.append(f"{tag}: section needs id and title")
                    if sid in sids: errs.append(f"{tag}: duplicate section id {sid}")
                    sids.add(sid)
                    if len(s.get("title") or "") > 12: errs.append(f"{tag}/{sid}: section title too long (>12)")
                    bl = s.get("bullets") or []
                    if not (BULLETS_MIN <= len(bl) <= BULLETS_MAX):
                        errs.append(f"{tag}/{sid}: needs {BULLETS_MIN}-{BULLETS_MAX} bullets (has {len(bl)})")
                    for b in bl:
                        if not b.get("text"): errs.append(f"{tag}/{sid}: empty bullet")
                        if len(b.get("text") or "") > BULLET_MAX: errs.append(f"{tag}/{sid}: bullet > {BULLET_MAX} chars: {b['text'][:20]}…")
                        if not b.get("links"): errs.append(f"{tag}/{sid}: bullet without source link: {(b.get('text') or '')[:20]}…")
                        for l in b.get("links", []):
                            if l not in urls: errs.append(f"{tag}/{sid}: bullet link not in item sources: {l}")
        # --- ongoing ---
        og = i.get("ongoing")
        if og is not None:
            if i.get("category") != ONGOING_CATEGORY: errs.append(f"{tag}: ongoing only allowed for {ONGOING_CATEGORY}")
            if not og.get("reason"): errs.append(f"{tag}: ongoing.reason required")
            if og.get("ended"):
                try: datetime.fromisoformat(og["ended"])
                except ValueError: errs.append(f"{tag}: bad ongoing.ended")
            elif og.get("wrapup_done"): errs.append(f"{tag}: wrapup_done requires ongoing.ended")
        # --- valid_until / evergreen ---
        vu = i.get("valid_until")
        if vu is not None:
            try:
                end = valid_until_end(vu)
                if "first_published" not in bad_dt and i.get("first_published"):
                    fp = dt(i["first_published"])
                    if end <= fp: errs.append(f"{tag}: valid_until {vu} is before first_published")
                    if end > fp + timedelta(days=VALID_MAX_DAYS):
                        errs.append(f"{tag}: valid_until {vu} is more than {VALID_MAX_DAYS} days after first_published (hard cap; use a date within {VALID_MAX_DAYS} days or leave valid_until off)")
            except (ValueError, TypeError):
                errs.append(f"{tag}: bad valid_until {vu!r} (use YYYY-MM-DD or ISO datetime, Taiwan time)")
        if i.get("evergreen") is not None:
            if not isinstance(i["evergreen"], bool): errs.append(f"{tag}: evergreen must be true/false")
            elif i["evergreen"] and not vu: errs.append(f"{tag}: evergreen requires valid_until (it is listed in 本週有效 only while valid_until is in the future)")
        # --- related (follow-up stories): [{id, title?}], ids must exist in news.json or archive.json ---
        rel = i.get("related")
        if rel is not None:
            if not isinstance(rel, list) or not rel: errs.append(f"{tag}: related must be a non-empty list of {{id, title?}}")
            else:
                seen_rel = set()
                for r in rel:
                    if not (isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"].strip()):
                        errs.append(f"{tag}: each related entry must be an object with a string id"); continue
                    if r.get("title") is not None and not isinstance(r["title"], str): errs.append(f"{tag}: related title must be a string")
                    rid = r["id"]
                    if rid == i.get("id"): errs.append(f"{tag}: related points to itself")
                    elif rid in seen_rel: errs.append(f"{tag}: related lists {rid} twice")
                    elif rid not in known_ids: errs.append(f"{tag}: related id {rid!r} not found in news.json or archive.json")
                    seen_rel.add(rid)
        # --- expiry (based on first_published only) ---
        if now is not None and not (bad_dt & {"first_published"}) and i.get("first_published"):
            try:
                if is_expired(i, now, hours):
                    errs.append(f"{tag}: EXPIRED (past {expiry(i, hours).isoformat()}); run `python3 update.py archive`")
            except (ValueError, TypeError):
                pass
    corr = load_corrections()
    errs += corrections_errors(corr, d["items"])
    errs += duplicate_errors(d["items"], load_archive()["items"] if check_archive else [])
    errs += funding_errors()
    return errs

# --- funding labels (資金來源標示): single mapping data/source_funding.json, see funding.py ---
def funding_errors():
    """Mapping integrity + every FEEDS source in fetch.py must match an explicit outlet entry (no silent 未標示 fallback)."""
    import funding
    errs = []
    try:
        m = funding.load()
    except (OSError, ValueError) as e:
        return [f"source_funding.json: unreadable ({e})"]
    labels = m.get("labels") or {}
    if "unlabeled" not in labels: errs.append("source_funding.json: labels must include `unlabeled` (未標示)")
    for k, v in labels.items():
        if not (isinstance(v, dict) and v.get("tag") and v.get("desc")): errs.append(f"source_funding.json: label {k!r} needs tag and desc")
    ids = set()
    for o in m.get("outlets") or []:
        t = f"source_funding.json outlet {o.get('id', '?')!r}"
        if o.get("id") in ids: errs.append(f"{t}: duplicate id")
        ids.add(o.get("id"))
        if o.get("label") not in labels: errs.append(f"{t}: unknown label {o.get('label')!r}")
        if not (isinstance(o.get("match"), list) and o["match"] and all(isinstance(x, str) and x for x in o["match"])): errs.append(f"{t}: `match` must be a non-empty list of strings")
        if not o.get("detail"): errs.append(f"{t}: missing detail")
        if not re.match(r"^https?://", o.get("basis") or ""): errs.append(f"{t}: basis must be an http(s) URL")
    try:
        import fetch as _fetch
        for name, tab, url in _fetch.FEEDS:
            if not funding.funding_for(name)["explicit"]:
                errs.append(f"fetch.py feed {name!r}: no entry in data/source_funding.json (add an outlet; use label `unlabeled` if its funding is not documented)")
    except Exception as e:
        errs.append(f"funding check could not import fetch.py: {e}")
    return errs

def funding_warnings(items):
    """Non-fatal: item source names that match no outlet entry (they show as 未標示 on the site)."""
    import funding
    seen = {}
    for i in items:
        for s in i.get("sources", []):
            if not funding.funding_for(s.get("name", ""))["explicit"]: seen.setdefault(s.get("name", ""), i.get("id"))
    return [f"[funding] source {n!r} (e.g. in {iid}) has no entry in data/source_funding.json -> shown as 未標示; add it to `outlets`" for n, iid in seen.items()]

def norm_primary_url(i):
    """Normalized primary (first) source URL: no scheme/www/query/fragment/trailing slash, lowercase host."""
    srcs = i.get("sources") or []
    u = (srcs[0].get("url") if srcs else "") or ""
    p = urlsplit(u.strip())
    if not p.netloc: return ""
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + p.path.rstrip("/")

def norm_title(t):
    t = unicodedata.normalize("NFKC", t or "").lower()
    return re.sub(r"[\W_]+", "", t)

def title_numbers(t):
    return sorted(re.findall(r"\d+(?:\.\d+)?", unicodedata.normalize("NFKC", (t or "").replace(",", ""))))

def duplicate_pair(a, b):
    """Reason string if items a and b look like the same story, else None.
    Only the primary source URL and the title are compared (not the whole source list).
    - Same primary URL -> duplicate, except hub pages on SHARED_URL_HOSTS (e.g. CWA typhoon page).
    - Titles with similarity > TITLE_SIM_MAX -> duplicate, unless their numbers differ
      (e.g. daily oil price / daily series items: different date or figure = different item)."""
    ua, ub = norm_primary_url(a), norm_primary_url(b)
    if ua and ua == ub and not any(ua.split("/")[0].endswith(h) for h in SHARED_URL_HOSTS):
        return f"same primary source URL {ua}"
    ta, tb = norm_title(a.get("title")), norm_title(b.get("title"))
    if ta and tb and title_numbers(a.get("title")) == title_numbers(b.get("title")):
        r = difflib.SequenceMatcher(None, ta, tb).ratio()
        if r > TITLE_SIM_MAX:
            return f"near-identical titles (similarity {r:.2f} > {TITLE_SIM_MAX})"
    return None

def duplicate_errors(items, archived=()):
    """Compare news items with each other and with archived items. Same id = same item, skipped."""
    errs = []
    for n, a in enumerate(items):
        for b in items[n + 1:]:
            if a.get("id") == b.get("id"): continue      # reported by the duplicate-id check
            why = duplicate_pair(a, b)
            if why: errs.append(f"DUPLICATE: {a.get('id')} and {b.get('id')}: {why}; keep one story per item (update the existing item instead)")
        for b in archived:
            if a.get("id") == b.get("id"): continue
            why = duplicate_pair(a, b)
            if why: errs.append(f"DUPLICATE: {a.get('id')} (news.json) and {b.get('id')} (archive.json): {why}; update/reuse the existing story or add a new item only for a genuinely new development")
    return errs

def load_corrections():
    if os.path.exists(CORRECTIONS):
        try: return json.load(open(CORRECTIONS, encoding="utf-8"))
        except ValueError as e: return {"_error": str(e)}
    return None

def corrections_errors(c, items):
    """Schema check for data/corrections.json (更正紀錄) and consistency with items' `corrected` marker.
    File: {"started": "YYYY-MM-DD", "note": "...", "entries": [{date, type, item_title, item_id and/or url, what_was_wrong, correction}]}
    `type` is required: 事實更正 (a fact/number/date/attribution/link was wrong) or 用語調整 (wording/tone only). Items' `corrected` = {date, type, note}."""
    errs = []
    if c is None: return ["corrections.json: missing (data/corrections.json must exist, entries may be empty)"]
    if "_error" in c: return [f"corrections.json: invalid JSON ({c['_error']})"]
    if not isinstance(c.get("entries"), list): return ["corrections.json: `entries` must be a list"]
    if not c.get("started"): errs.append("corrections.json: missing `started` date")
    ids = set()
    types = {}   # item_id -> set of entry types
    for n, e in enumerate(c["entries"], 1):
        tag = f"corrections.json entry #{n}"
        if not isinstance(e, dict): errs.append(f"{tag}: must be an object"); continue
        for k in ("date", "item_title", "what_was_wrong", "correction"):
            if not (isinstance(e.get(k), str) and e[k].strip()): errs.append(f"{tag}: missing {k}")
        if not (e.get("item_id") or e.get("url")): errs.append(f"{tag}: needs item_id and/or url")
        if e.get("url") and not re.match(r"^https?://", e["url"]): errs.append(f"{tag}: bad url")
        try:
            dd = datetime.strptime(e.get("date") or "", "%Y-%m-%d").date()
            if dd > datetime.now(TPE).date(): errs.append(f"{tag}: date is in the future")
        except ValueError: errs.append(f"{tag}: date must be YYYY-MM-DD")
        if e.get("type") not in CORRECTION_TYPES:
            errs.append(f"{tag}: `type` is required and must be one of {' / '.join(CORRECTION_TYPES)} (got {e.get('type')!r}); when in doubt use 事實更正")
        if e.get("item_id"):
            ids.add(e["item_id"])
            types.setdefault(e["item_id"], set()).add(e.get("type"))
    cur = {i.get("id"): i for i in items}
    for iid in ids & set(cur):
        if not cur[iid].get("corrected"):
            errs.append(f"{iid}: has an entry in corrections.json but the item lacks the visible `corrected` note")
    for i in items:
        cr = i.get("corrected")
        if cr is None: continue
        if not (isinstance(cr, dict) and cr.get("date") and cr.get("note")):
            errs.append(f"{i.get('id')}: `corrected` must be {{date, type, note}}")
        elif i.get("id") not in ids:
            errs.append(f"{i.get('id')}: marked `corrected` but no entry with this item_id in corrections.json (never silently edit)")
        if isinstance(cr, dict):
            if cr.get("type") not in CORRECTION_TYPES:
                errs.append(f"{i.get('id')}: `corrected.type` is required and must be one of {' / '.join(CORRECTION_TYPES)} (got {cr.get('type')!r})")
            elif "事實更正" in types.get(i.get("id"), ()) and cr["type"] != "事實更正":
                errs.append(f"{i.get('id')}: corrections.json has a 事實更正 entry for this item, so `corrected.type` must be 事實更正 (never use 用語調整 to hide a factual fix)")
    return errs

def now_tpe(a=None):
    n = getattr(a, "now", None)
    return datetime.fromisoformat(n) if n else datetime.now(TPE)

def cmd_validate(a):
    d = load()
    errs = validate(d, now_tpe(a), a.keep_hours)
    for w in funding_warnings(d["items"] + load_archive()["items"]): print(w)
    print("\n".join(errs) if errs else "OK")
    return 1 if errs else 0

def cmd_copycheck(a):
    import copycheck
    items = load()["items"] + (load_archive()["items"] if a.archive else [])
    ids = [x.strip() for x in (a.ids or "").split(",") if x.strip()]
    return copycheck.run(items, ids=ids or None, new=a.new, minlen=a.min, refresh=a.refresh)

def cmd_archive(a):
    d = load()
    now = now_tpe(a)
    moved = archive_expired(d, now, a.keep_hours)
    if moved: save(d)
    print(f"archived {len(moved)} expired item(s) -> {ARCHIVE}")
    for i in moved: print("  archived:", i["id"], i["first_published"], i["title"])
    return 0

def cmd_finalize(a):
    d = load()
    now = now_tpe(a)
    moved = archive_expired(d, now, a.keep_hours, write=False)   # expiry uses first_published, never `updated`
    errs = validate(d, now, a.keep_hours)
    if errs:
        print("Validation failed (nothing written):\n" + "\n".join(errs)); return 1
    if moved: write_archive(moved, now)
    d["updated"] = now.replace(microsecond=0).isoformat()
    save(d)
    print(f"kept {len(d['items'])}, archived {len(moved)} (expired: >{a.keep_hours}h after first_published, or ongoing story finished); updated={d['updated']}")
    for i in moved: print("  archived:", i["id"], i["title"])
    if not a.no_screens:
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "screenshot.py")], check=True)
    if not a.no_zip:
        out = os.path.join(os.path.dirname(ROOT), "neutral-news.zip")
        base = os.path.basename(ROOT)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for r, dirs, files in os.walk(ROOT):
                dirs[:] = [x for x in dirs if x not in ("raw", "__pycache__")]
                for f in files:
                    if f.endswith(".tmp"): continue
                    p = os.path.join(r, f)
                    z.write(p, os.path.join(base, os.path.relpath(p, ROOT)))
        print("zip ->", out)
    return 0

def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("fetch"); f.add_argument("--hours", type=float, default=36)
    f.add_argument("--force", action="store_true", help=f"fetch again even if data/new_candidates.json is < {FETCH_REUSE_MINUTES} min old")
    for name in ("validate", "archive"):
        p = sp.add_parser(name)
        p.add_argument("--keep-hours", type=float, default=KEEP_HOURS)
        p.add_argument("--now", help="ISO time override (testing)")
    lg = sp.add_parser("log"); lg.add_argument("-n", type=int, default=10, help="number of entries (default 10)")
    fh = sp.add_parser("feedhealth")
    fh.add_argument("--threshold", type=int, default=FEED_FAIL_STREAK, help=f"consecutive failed runs counted as broken (default {FEED_FAIL_STREAK})")
    fh.add_argument("--recent", type=int, default=FEED_RECENT_RUNS, help=f"runs in the 'recent' success rate (default {FEED_RECENT_RUNS})")
    fh.add_argument("--all", action="store_true", help="also list feeds that never failed")
    fh.add_argument("--log-file", help="read this log instead of data/fetch_log.jsonl (testing)")
    cc = sp.add_parser("copycheck", help="compare our text with source pages (network; never part of validate)")
    cc.add_argument("--ids", help="comma-separated item ids to check")
    cc.add_argument("--new", action="store_true", help="only items new or changed vs. git HEAD")
    cc.add_argument("--min", type=int, default=20, help="minimum identical run length (default 20)")
    cc.add_argument("--refresh", action="store_true", help="ignore the page cache (raw/copycheck/)")
    cc.add_argument("--archive", action="store_true", help="also check data/archive.json items")
    fn = sp.add_parser("finalize")
    fn.add_argument("--keep-hours", type=float, default=KEEP_HOURS)
    fn.add_argument("--now", help="ISO time override (testing)")
    fn.add_argument("--no-screens", action="store_true")
    fn.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    sys.exit({"fetch": cmd_fetch, "validate": cmd_validate, "archive": cmd_archive, "finalize": cmd_finalize, "log": cmd_log, "feedhealth": cmd_feedhealth, "copycheck": cmd_copycheck}[a.cmd](a) or 0)

if __name__ == "__main__":
    main()
