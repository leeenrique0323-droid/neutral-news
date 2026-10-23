#!/usr/bin/env python3
"""Update pipeline for 民生新聞.

  python3 update.py fetch      # run fetch.py + cwa.py, list NEW candidate items -> data/new_candidates.json
  python3 update.py archive    # move expired items from data/news.json to data/archive.json (never deletes)
  python3 update.py validate   # check data/news.json against the editorial schema (fails on expired items)
  python3 update.py finalize   # archive expired, validate, stamp `updated`, screenshots, zip

Writing/curating summaries into data/news.json is an editorial step between
`fetch` and `finalize` (see AUTOMATION.md). This script never invents content.
"""
import argparse, json, os, re, subprocess, sys, zipfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
NEWS = os.path.join(ROOT, "data", "news.json")
CANDS = os.path.join(ROOT, "candidates.json")
NEWC = os.path.join(ROOT, "data", "new_candidates.json")
CWA = os.path.join(ROOT, "cwa_alerts.json")
ARCHIVE = os.path.join(ROOT, "data", "archive.json")
TPE = timezone(timedelta(hours=8))
STATUSES = {"快訊・初步資訊", "完整版"}
REQUIRED = ["id", "tab", "category", "status", "title", "summary", "who", "what", "when", "published",
            "first_published", "sources"]

# --- expiry / length rules (keep in sync with AUTOMATION.md) ---
KEEP_HOURS = 72            # normal items: archived 72h after first_published (never changes on update)
WRAPUP_HOURS = 24          # ongoing stories: upper bound for the post-event wrap-up after `ongoing.ended`
ONGOING_MAX_HOURS = 168    # safety cap: even an "ongoing" item is archived 7 days after first_published
ONGOING_CATEGORY = "天災與公共安全"
SUMMARY_MAX = 300          # normal summary (characters)
SUMMARY_MAX_SECTIONED = 200  # items with `sections`: short status block
SUMMARY_MAX_LINES = 4      # newline-separated lines
FACT_MAX = 200             # who / what / when (characters)
SECTION_MAX = 8            # sections per item
BULLETS_MIN, BULLETS_MAX = 2, 5
BULLET_MAX = 260           # characters per bullet

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

def expiry(i, hours=KEEP_HOURS):
    """Return the datetime after which the item must be archived, or None if it is
    currently allowed to stay open-ended (active ongoing story, subject to the hard cap).
    Always based on first_published (never on `updated`)."""
    first = dt(i["first_published"])
    normal = first + timedelta(hours=hours)
    og = i.get("ongoing")
    if not og:
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
            i["archive_reason"] = reason or ("過期：逾首次發布後%d小時" % hours if not i.get("ongoing")
                                             else "過期：進行中事件已結束並完成總結（或達上限）")
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

def cmd_fetch(a):
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
    print(f"{len(new)} new candidates -> {NEWC}")
    for f in bad:
        print(f"[FEED FAIL] {f['feed']}: {f.get('error')}")
    for x in new:
        print(f"- [{x['tab']}] {','.join(x['categories'])} | {x['title']} | {x['link']}")

def validate(d, now=None, hours=KEEP_HOURS, check_git=True):
    errs = []
    cats = set(d.get("categories", []))
    ids = set()
    prev = git_first_published() if check_git else {}
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
        # --- expiry (based on first_published only) ---
        if now is not None and not (bad_dt & {"first_published"}) and i.get("first_published"):
            try:
                if is_expired(i, now, hours):
                    errs.append(f"{tag}: EXPIRED (past {expiry(i, hours).isoformat()}); run `python3 update.py archive`")
            except (ValueError, TypeError):
                pass
    return errs

def now_tpe(a=None):
    n = getattr(a, "now", None)
    return datetime.fromisoformat(n) if n else datetime.now(TPE)

def cmd_validate(a):
    errs = validate(load(), now_tpe(a), a.keep_hours)
    print("\n".join(errs) if errs else "OK")
    return 1 if errs else 0

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
    for name in ("validate", "archive"):
        p = sp.add_parser(name)
        p.add_argument("--keep-hours", type=float, default=KEEP_HOURS)
        p.add_argument("--now", help="ISO time override (testing)")
    fn = sp.add_parser("finalize")
    fn.add_argument("--keep-hours", type=float, default=KEEP_HOURS)
    fn.add_argument("--now", help="ISO time override (testing)")
    fn.add_argument("--no-screens", action="store_true")
    fn.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    sys.exit({"fetch": cmd_fetch, "validate": cmd_validate, "archive": cmd_archive, "finalize": cmd_finalize}[a.cmd](a) or 0)

if __name__ == "__main__":
    main()
