#!/usr/bin/env python3
"""Update pipeline for 民生新聞.

  python3 update.py fetch      # run fetch.py + cwa.py, list NEW candidate items -> data/new_candidates.json
  python3 update.py validate   # check data/news.json against the editorial schema
  python3 update.py finalize   # validate, prune old items, stamp `updated`, screenshots, zip

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
TPE = timezone(timedelta(hours=8))
STATUSES = {"快訊・初步資訊", "完整版"}
REQUIRED = ["id", "tab", "category", "status", "title", "summary", "who", "what", "when", "published", "sources"]

def load():
    return json.load(open(NEWS, encoding="utf-8"))

def save(d):
    tmp = NEWS + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, NEWS)

def norm(u):
    return re.sub(r"[?#].*$", "", u or "").rstrip("/")

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

def validate(d):
    errs = []
    cats = set(d.get("categories", []))
    ids = set()
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
        for s in i.get("sources", []):
            if not re.match(r"^https?://", s.get("url", "")): errs.append(f"{tag}: bad source url")
        for k in ("published", "updated"):
            if i.get(k):
                try: datetime.fromisoformat(i[k])
                except ValueError: errs.append(f"{tag}: bad {k}")
    return errs

def cmd_validate(a):
    errs = validate(load())
    print("\n".join(errs) if errs else "OK")
    return 1 if errs else 0

def cmd_finalize(a):
    d = load()
    errs = validate(d)
    if errs:
        print("Validation failed:\n" + "\n".join(errs)); return 1
    now = datetime.now(TPE)
    cutoff = now - timedelta(hours=a.keep_hours)
    keep, dropped = [], []
    for i in d["items"]:
        last = datetime.fromisoformat(i.get("updated") or i["published"])
        (keep if last >= cutoff else dropped).append(i)
    d["items"] = keep
    d["updated"] = now.replace(microsecond=0).isoformat()
    save(d)
    print(f"kept {len(keep)}, dropped {len(dropped)} (older than {a.keep_hours}h); updated={d['updated']}")
    for i in dropped: print("  dropped:", i["id"], i["title"])
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
    sp.add_parser("validate")
    fn = sp.add_parser("finalize")
    fn.add_argument("--keep-hours", type=float, default=72)
    fn.add_argument("--no-screens", action="store_true")
    fn.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    sys.exit({"fetch": cmd_fetch, "validate": cmd_validate, "finalize": cmd_finalize}[a.cmd](a) or 0)

if __name__ == "__main__":
    main()
