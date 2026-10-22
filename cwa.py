#!/usr/bin/env python3
"""Official 中央氣象署 (CWA) warnings and earthquake reports for the update runs.

Usage: python3 cwa.py [-o cwa_alerts.json] [--eq-hours 72]

Keyless sources (the same public files the www.cwa.gov.tw pages load via XHR):
  - RSS  警報、特報        https://www.cwa.gov.tw/rss/Data/cwa_warning.xml
  - JS   警特報內容        https://www.cwa.gov.tw/Data/js/warn/Warning_Content.js
  - JS   颱風消息(位置)    https://www.cwa.gov.tw/Data/js/typhoon/TY_NEWS-Data.js
  - HTML 地震列表片段      https://www.cwa.gov.tw/V8/C/E/MOD/EQ_ROW.html
Optional (only when env CWA_API_KEY is set): CWA open data API
  W-C0034-005 熱帶氣旋路徑, W-C0033-002 天氣特報內容, E-A0015-001 顯著有感地震報告.
Every item carries a public www.cwa.gov.tw page URL to use as the source link.
Each source is fetched once per run (1.5 s apart). A failing source is reported
in `sources` and never aborts the run.
"""
import argparse, json, os, re, sys, time, html, urllib.request, urllib.parse, ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

UA = "NeutralNewsPrototype/0.1 (+local prototype; modest polling)"
TPE = timezone(timedelta(hours=8))
BASE = "https://www.cwa.gov.tw"
RSS_URL = BASE + "/rss/Data/cwa_warning.xml"
WARN_JS = BASE + "/Data/js/warn/Warning_Content.js"
TY_JS = BASE + "/Data/js/typhoon/TY_NEWS-Data.js"
EQ_ROW = BASE + "/V8/C/E/MOD/EQ_ROW.html"
API = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"

# public page for each warning code (links readers can open)
PAGES = {
    "TY_WARN": BASE + "/V8/C/P/Typhoon/TY_WARN.html",
    "W21": BASE + "/V8/C/P/Typhoon/TY_WARN.html",
    "TY_NEWS": BASE + "/V8/C/P/Typhoon/TY_NEWS.html",
    "LargeSurf": BASE + "/V8/C/P/Warning/LargeSurf.html",
    "EQ": BASE + "/V8/C/E/index.html",
}
def page(code):
    return PAGES.get(code) or f"{BASE}/V8/C/P/Warning/{code}.html"

NAMES = {"W21": "颱風警報", "W25": "陸上強風特報", "W26": "豪(大)雨特報", "W27": "濃霧特報",
         "W28": "低溫特報", "W29": "高溫資訊", "W33": "大雷雨即時訊息", "LargeSurf": "巨浪告警",
         "TY_WARN": "颱風警報", "TY_NEWS": "颱風消息"}
# Overnight (23:00-06:00) runs act only on items flagged urgent.
URGENT_WORDS = ["颱風警報", "豪雨", "大豪雨", "超大豪雨", "海嘯", "紅色燈號", "巨浪告警"]

_ctx = ssl.create_default_context()
# www.cwa.gov.tw's certificate lacks a Subject Key Identifier, which Python 3.13's
# VERIFY_X509_STRICT rejects. Keep full chain/hostname verification, drop only the strict flag.
_ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)

def get(url, data_time=True, headers=None):
    if data_time:  # same cache-buster the CWA pages use
        url += ("&" if "?" in url else "?") + "T=" + datetime.now(TPE).strftime("%Y%m%d%H%M")
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=25, context=_ctx) as r:
        return r.read().decode("utf-8", "replace")

# ---------- minimal JS literal parser (objects, arrays, strings, numbers, bools) ----------
class JS:
    def __init__(self, s): self.s, self.i = s, 0
    def ws(self):
        s = self.s
        while self.i < len(s):
            if s[self.i].isspace(): self.i += 1
            elif s.startswith("//", self.i): self.i = s.find("\n", self.i) % (len(s) + 1) or len(s)
            elif s.startswith("/*", self.i): self.i = s.find("*/", self.i) + 2
            else: break
    def val(self):
        self.ws(); c = self.s[self.i]
        if c == "{": return self.obj()
        if c == "[": return self.arr()
        if c in "'\"": return self.str()
        if self.s.startswith("new Array()", self.i): self.i += 11; return []
        m = re.compile(r"-?\d+(\.\d+)?|true|false|null").match(self.s, self.i)
        if not m: raise ValueError(f"bad JS at {self.i}: {self.s[self.i:self.i+30]!r}")
        self.i = m.end(); t = m.group(0)
        return {"true": True, "false": False, "null": None}.get(t, float(t) if "." in t else int(t) if t[0] != "t" else t)
    def str(self):
        q = self.s[self.i]; self.i += 1; out = []
        esc = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}
        while self.s[self.i] != q:
            c = self.s[self.i]
            if c == "\\":
                self.i += 1; c = self.s[self.i]
                if c == "u": out.append(chr(int(self.s[self.i+1:self.i+5], 16))); self.i += 4
                else: out.append(esc.get(c, c))
            else: out.append(c)
            self.i += 1
        self.i += 1
        return "".join(out)
    def key(self):
        self.ws()
        if self.s[self.i] in "'\"": return self.str()
        m = re.compile(r"[\w$-]+").match(self.s, self.i); self.i = m.end(); return m.group(0)
    def obj(self):
        self.i += 1; d = {}
        while True:
            self.ws()
            if self.s[self.i] == "}": self.i += 1; return d
            k = self.key(); self.ws(); self.i += 1  # ':'
            d[k] = self.val(); self.ws()
            if self.s[self.i] == ",": self.i += 1
    def arr(self):
        self.i += 1; a = []
        while True:
            self.ws()
            if self.s[self.i] == "]": self.i += 1; return a
            a.append(self.val()); self.ws()
            if self.s[self.i] == ",": self.i += 1

def js_vars(src):
    """Return {name: value} for top-level `var name = <literal>;` statements that parse."""
    out = {}
    for m in re.finditer(r"^var\s+(\w+)\s*=\s*", src, re.M):
        p = JS(src); p.i = m.end()
        try: out[m.group(1)] = p.val()
        except Exception: pass
    return out

def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    return re.sub(r"[ \t]+", " ", s).strip()

def tw_time(s):
    """'2026/10/22 08:30' -> ISO +08:00"""
    try: return datetime.strptime(s.strip(), "%Y/%m/%d %H:%M").replace(tzinfo=TPE).isoformat()
    except Exception: return None

def md_time(s):
    """'10/22 07:23' (current year assumed) -> ISO +08:00; unchanged if unparsable"""
    now = datetime.now(TPE)
    try:
        t = datetime.strptime(f"{now.year}/{s.strip()}", "%Y/%m/%d %H:%M").replace(tzinfo=TPE)
        return (t.replace(year=now.year - 1) if t > now + timedelta(days=1) else t).isoformat()
    except Exception: return s or None

def is_urgent(text):
    return any(w in text for w in URGENT_WORDS)

# ---------- keyless sources ----------
def from_rss(xml):
    out = []
    for it in ET.fromstring(xml).iter("item"):
        t = (it.findtext("title") or "").strip()
        d = clean(it.findtext("description")).replace("\\n", "\n").strip()
        pub = it.findtext("pubDate")
        try:
            from email.utils import parsedate_to_datetime
            pub = parsedate_to_datetime(pub).astimezone(TPE).isoformat()
        except Exception: pass
        out.append({"title": t, "description": d, "published": pub, "url": (it.findtext("link") or "").strip()})
    return out

def from_warning_js(src):
    v = js_vars(src)
    alerts = []
    wc = v.get("WarnContent", {}) or {}
    for code, langs in wc.items():
        if code == "W21" and "TY_WARN" in wc:
            continue  # W21 duplicates TY_WARN text
        c = (langs or {}).get("C") or {}
        body = c.get("content_web") or c.get("content") or ""
        alerts.append({
            "code": code, "type": c.get("title") or NAMES.get(code, code),
            "issued": tw_time(c.get("issued", "")), "valid_to": tw_time(c.get("validto", "")),
            "summary": clean(re.sub(r"^發布時間：[^\n]*\n+", "", c.get("content") or "")),
            "detail": clean(body)[:1500], "url": page("TY_WARN" if code == "W21" else code),
        })
    for x in v.get("WarnContent_LargeSurf", []) or []:
        areas = "；".join(f"{a.get('County','')}{('（'+a['Town']+'）') if a.get('Town') else ''}" for a in x.get("WarnArea", []))
        alerts.append({"code": "LargeSurf", "type": "巨浪告警", "issued": md_time(x.get("Issued", "")), "valid_to": None,
                       "summary": clean(x.get("Description")), "detail": f"{clean(x.get('Instruction'))} 告警區域：{areas}",
                       "url": page("LargeSurf")})
    for name, code in (("WarnContent_W33", "W33"), ("WarnContent_W32", "W32"), ("WarnContent_TyWind", "TyWind")):
        for x in v.get(name, []) or []:
            txt = clean(json.dumps(x, ensure_ascii=False)) if not isinstance(x, str) else clean(x)
            if isinstance(x, dict):
                txt = clean(x.get("Description") or x.get("content") or txt)
            alerts.append({"code": code, "type": NAMES.get(code, code), "issued": (md_time(x.get("Issued", "")) if isinstance(x, dict) else None),
                           "valid_to": None, "summary": txt[:400], "detail": "", "url": page(code if code == "W33" else "TY_WARN")})
    return alerts, v.get("WarnContent_TyWarn", []) or []

def from_typhoon_js(src):
    v = js_vars(src)
    names = v.get("TYPHOON", {}) or {}
    tys = []
    # TY_LIST_1['C'] = '...' + '...';  (HTML panels, one per storm)
    m = re.search(r"TY_LIST_1\['C'\]\s*=\s*(.*?);\s*\n", src, re.S)
    panels = "".join(re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))) if m else ""
    for pid, info in names.items():
        nm = info.get("Name", {})
        block = panels.split(f'id="{pid}"', 1)[1] if f'id="{pid}"' in panels else ""
        block = block.split('class="panel panel-default"', 1)[0]
        head = re.search(r'<span class="fa-red">([^<]+)</span><span class="fa-blue">([^<]+)</span><br>編號第 *(\d+) *號', block)
        body = re.search(r'<div class="panel-body">(.*?)</div>', block, re.S)
        tys.append({"id": pid, "name_zh": nm.get("C"), "name_en": nm.get("E"),
                    "intensity": head.group(1) if head else None, "number": head.group(3) if head else None,
                    "status": clean(body.group(1)) if body else "",
                    "as_of": (v.get("TY_TIME") or {}).get("C"), "url": page("TY_NEWS")})
    return tys

def from_eq_rows(src, hours):
    now = datetime.now(TPE); out = []
    for row in re.findall(r'<tr id="eq-\d+".*?</tr>', src, re.S):
        g = lambda p: (re.search(p, row, re.S) or [None, None])[1]
        num = g(r'data-num="(\d+)"'); href = g(r'<a href="(/V8/C/E/EQ/[^"]+)"')
        when = g(r'<div class="eq-detail">\s*<span>([^<]+)</span>')
        try:
            t = datetime.strptime(f"{now.year}/{when}", "%Y/%m/%d %H:%M").replace(tzinfo=TPE)
            if t > now + timedelta(days=1): t = t.replace(year=now.year - 1)
        except Exception: t = None
        if t and t < now - timedelta(hours=hours): continue
        mag = g(r"<span>地震規模</span>([\d.]+)"); inten = g(r'headers="maximum"[^>]*>([^<]+)<')
        loc = clean(g(r"<span>地點</span>(.*?)</li>") or "")
        numbered = bool(num and num != "000")
        lvl = int(re.match(r"\d+", inten).group(0)) if inten and re.match(r"\d+", inten) else 0
        out.append({"time": t.isoformat() if t else when, "number": num if numbered else None,
                    "kind": "顯著有感地震（編號）" if numbered else "小區域有感地震",
                    "magnitude": float(mag) if mag else None, "max_intensity": inten,
                    "depth": clean(g(r"<span>深度</span>([^<]+)") or ""), "location": loc,
                    "urgent": bool(numbered and (lvl >= 4 or (mag and float(mag) >= 6.0))),
                    "url": BASE + href if href else page("EQ")})
    return out

# ---------- optional keyed API ----------
def api(dataset, key, **params):
    # key goes in the Authorization header (not the URL) so it never lands in logs
    q = urllib.parse.urlencode({"format": "JSON", **params})
    return json.loads(get(f"{API}{dataset}?{q}", data_time=False, headers={"Authorization": key}))

def from_api(key, status):
    extra = {}
    for ds, params in (("W-C0034-005", {}), ("W-C0033-002", {}), ("E-A0015-001", {"limit": 5})):
        try:
            extra[ds] = api(ds, key, **params).get("records")
            status.append({"source": f"opendata {ds}", "ok": True})
        except Exception as e:
            status.append({"source": f"opendata {ds}", "ok": False, "error": str(e)[:200]})
        time.sleep(1.5)
    return extra

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cwa_alerts.json"))
    ap.add_argument("--eq-hours", type=float, default=72, help="earthquake look-back window")
    a = ap.parse_args()
    status, rss, alerts, tys, eqs, active_ty = [], [], [], [], [], []
    steps = [("CWA RSS 警報特報", RSS_URL), ("CWA Warning_Content.js", WARN_JS),
             ("CWA TY_NEWS-Data.js", TY_JS), ("CWA EQ_ROW 地震列表", EQ_ROW)]
    for i, (name, url) in enumerate(steps):
        try:
            src = get(url)
            if i == 0: rss = from_rss(src)
            elif i == 1: alerts, active_ty = from_warning_js(src)
            elif i == 2: tys = from_typhoon_js(src)
            else: eqs = from_eq_rows(src, a.eq_hours)
            status.append({"source": name, "url": url, "ok": True})
            print(f"[OK] {name}", file=sys.stderr)
        except Exception as e:
            status.append({"source": name, "url": url, "ok": False, "error": str(e)[:200]})
            print(f"[FAIL] {name}: {e}", file=sys.stderr)
        time.sleep(1.5)
    # RSS link (with ?T=issue time) is the most specific public URL for that issuance
    for al in alerts:
        for r in rss:
            if al["type"] in r["title"] or (al["code"] in ("TY_WARN",) and "颱風警報" in r["title"]):
                al["url"] = r["url"]; al["rss_title"] = r["title"]
        al["urgent"] = is_urgent(al["type"] + al["summary"])
    for t in tys:
        t["warning_active"] = t["id"] in active_ty or any(x["code"] == "TY_WARN" for x in alerts)
    key = os.environ.get("CWA_API_KEY", "").strip()
    extra = from_api(key, status) if key else None
    if not key:
        status.append({"source": "opendata API", "ok": None, "note": "CWA_API_KEY not set; skipped (optional)"})
    out = {"generated": datetime.now(TPE).replace(microsecond=0).isoformat(), "sources": status,
           "active_alerts": alerts, "rss_items": rss, "typhoons": tys, "earthquakes": eqs,
           "urgent": any(x.get("urgent") for x in alerts + eqs)}
    if extra is not None: out["opendata"] = extra
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print_summary(out)
    print(f"-> {a.out}", file=sys.stderr)

def print_summary(o):
    print(f"== 中央氣象署 官方警特報（{o['generated']}）==")
    for s in o["sources"]:
        if s["ok"] is False: print(f"[CWA FAIL] {s['source']}: {s.get('error')}")
    warn_ok = any(s["ok"] for s in o["sources"] if s["source"] in ("CWA RSS 警報特報", "CWA Warning_Content.js"))
    if not warn_ok: print("！無法取得 CWA 警特報資料，請手動開啟 https://www.cwa.gov.tw/V8/C/P/Warning/FIFOWS.html 確認。")
    elif not o["active_alerts"] and not o["rss_items"]: print("目前無生效中的警特報。")
    for x in o["active_alerts"]:
        flag = "【緊急】" if x.get("urgent") else ""
        vt = f"，有效至 {x['valid_to']}" if x.get("valid_to") else ""
        print(f"- {flag}{x['type']}（發布 {x.get('issued')}{vt}）{x['summary'][:160]} | {x['url']}")
    for t in o["typhoons"]:
        print(f"- 颱風 {t['intensity'] or ''}{t['name_zh']}（第{t['number']}號，{t['name_en']}）"
              f"{'警報中' if t['warning_active'] else '無警報'}；{t['as_of']}：{t['status'][:160]} | {t['url']}")
    if not any(s["ok"] for s in o["sources"] if s["source"] == "CWA EQ_ROW 地震列表"):
        print("！無法取得 CWA 地震列表，請手動開啟 https://www.cwa.gov.tw/V8/C/E/index.html 確認。"); big = []
    big = [e for e in o["earthquakes"] if e["number"]]
    print(f"- 近期地震：{len(o['earthquakes'])} 筆（編號顯著有感 {len(big)} 筆）")
    for e in o["earthquakes"]:
        if e["number"] or e["urgent"]:
            print(f"  {'【緊急】' if e['urgent'] else ''}第{e['number']}號 {e['time']} M{e['magnitude']} 最大震度{e['max_intensity']} {e['location']} | {e['url']}")
    print("整體：" + ("有緊急項目（夜間時段亦須處理）" if o["urgent"] else "無緊急項目"))

if __name__ == "__main__":
    main()
