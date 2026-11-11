#!/usr/bin/env python3
"""Official 中央氣象署 (CWA) warnings and earthquake reports for the update runs.

Usage: python3 cwa.py [-o cwa_alerts.json] [--eq-hours 72]

Primary keyless sources (the same public files the www.cwa.gov.tw pages load):
  - RSS  警報、特報        https://www.cwa.gov.tw/rss/Data/cwa_warning.xml
  - JS   警特報內容        https://www.cwa.gov.tw/Data/js/warn/Warning_Content.js
  - JS   颱風消息(位置)    https://www.cwa.gov.tw/Data/js/typhoon/TY_NEWS-Data.js
  - HTML 地震列表片段      https://www.cwa.gov.tw/V8/C/E/MOD/EQ_ROW.html
Some networks get a HiNetCDN 404 (X-Cache: RULE) for www.cwa.gov.tw even though
the files still exist. When a keyless source fails, fall back to official CWA
open data (opendata.cwa.gov.tw): W-C0033-002 特報內容, W-C0034-005 熱帶氣旋路徑,
E-A0015-001 顯著有感地震, E-A0016-001 小區域有感地震. Auth is env CWA_API_KEY,
or the authorization published on official data.gov.tw dataset API URLs
(dataset 9244 / 138041). Earthquakes have a further keyless fallback:
https://scweb.cwa.gov.tw/ (中央氣象署地震測報中心).
Every item carries a public CWA page URL to use as the source link.
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
SCWEB = "https://scweb.cwa.gov.tw"
# Authorization published as the official API URL on data.gov.tw CWA datasets
# (https://data.gov.tw/dataset/9244, https://data.gov.tw/dataset/138041).
# Prefer env CWA_API_KEY when set. Never log this value.
DATAGOV_PUBLISHED_AUTH = "rdec-key-123-45678-011121314"

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

def as_list(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

def od_time(s):
    """'2026-11-11 16:16:00' or ISO -> ISO +08:00"""
    if not s: return None
    s = str(s).strip()
    for raw in (s, s.replace("T", " ")):
        base = raw.replace("+08:00", "").replace("Z", "")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(base, fmt).replace(tzinfo=TPE).isoformat()
            except ValueError:
                pass
    return s

def opendata_key():
    return os.environ.get("CWA_API_KEY", "").strip() or DATAGOV_PUBLISHED_AUTH

def typoon_intensity(ms):
    try: v = float(ms)
    except (TypeError, ValueError): return None
    if v >= 51: return "強烈颱風"
    if v >= 32.7: return "中度颱風"
    if v >= 17.2: return "輕度颱風"
    return "熱帶性低氣壓"

PHEN_CODE = {
    "陸上強風": "W25", "強風": "W25",
    "豪雨": "W26", "大雨": "W26", "豪(大)雨": "W26", "豪大雨": "W26",
    "濃霧": "W27", "低溫": "W28", "高溫": "W29",
    "颱風": "TY_WARN", "大雷雨": "W33", "巨浪": "LargeSurf",
}

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

# ---------- official open data API (and scweb earthquake fallback) ----------
def api(dataset, key, **params):
    # key goes in the Authorization header (not the URL) so it never lands in logs
    q = urllib.parse.urlencode({"format": "JSON", **params})
    return json.loads(get(f"{API}{dataset}?{q}", data_time=False, headers={"Authorization": key}))

def from_api(key, status, datasets=None):
    extra = {}
    if datasets is None:
        datasets = (("W-C0033-002", {}), ("W-C0034-005", {}),
                    ("E-A0015-001", {"limit": 15}), ("E-A0016-001", {"limit": 15}))
    for ds, params in datasets:
        try:
            extra[ds] = api(ds, key, **params).get("records")
            status.append({"source": f"opendata {ds}", "ok": True})
        except Exception as e:
            extra[ds] = None
            status.append({"source": f"opendata {ds}", "ok": False, "error": str(e)[:200]})
        time.sleep(1.5)
    return extra

def from_opendata_warnings(records):
    out = []
    if not records: return out
    for rec in as_list(records.get("record") if isinstance(records, dict) else records):
        if not isinstance(rec, dict): continue
        info = rec.get("datasetInfo") or {}
        title = info.get("datasetDescription") or ""
        vt = info.get("validTime") or {}
        contents = rec.get("contents") or {}
        content = contents.get("content") or {}
        if isinstance(content, list):
            content = next((c for c in content if (c or {}).get("contentLanguage") == "zh-TW"), content[0] if content else {})
        body = clean((content or {}).get("contentText") or "")
        phenomena, areas, code = [], [], None
        hazards = ((rec.get("hazardConditions") or {}).get("hazards") or {})
        if isinstance(hazards, dict): hazards = hazards.get("hazard")
        for h in as_list(hazards):
            inf = (h or {}).get("info") or {}
            ph = inf.get("phenomena") or ""
            if ph: phenomena.append(ph)
            if code is None:
                code = PHEN_CODE.get(ph) or PHEN_CODE.get(title.replace("特報", "").replace("警報", "").replace("資訊", ""))
            locs = ((inf.get("affectedAreas") or {}).get("location"))
            for loc in as_list(locs):
                name = (loc or {}).get("locationName")
                if name: areas.append(name)
        if code is None:
            for k, v in PHEN_CODE.items():
                if k in title:
                    code = v; break
        code = code or "W26"
        typ = title or (phenomena[0] + "特報" if phenomena else code)
        typ = typ if typ else NAMES.get(code, code)
        out.append({
            "code": code, "type": typ,
            "issued": od_time(info.get("issueTime") or info.get("update")),
            "valid_to": od_time(vt.get("endTime")),
            "summary": body[:400], "detail": body[:1500],
            "areas": areas,
            "url": page("TY_WARN" if code in ("W21", "TY_WARN") else code),
        })
    return out

def from_opendata_typhoons(records):
    out = []
    if not records: return out
    tcs = records.get("TropicalCyclones") if isinstance(records, dict) else None
    if isinstance(tcs, dict): tcs = tcs.get("TropicalCyclone")
    for tc in as_list(tcs):
        if not isinstance(tc, dict): continue
        fixes = as_list((tc.get("AnalysisData") or {}).get("Fix"))
        last = fixes[-1] if fixes else {}
        pred = ""
        for p in as_list(last.get("MovingPrediction")):
            if isinstance(p, dict) and p.get("lang") in ("zh-hant", "zh-TW", "zh"):
                pred = p.get("value") or ""; break
        lon, lat = last.get("CoordinateLongitude"), last.get("CoordinateLatitude")
        wind, press = last.get("MaxWindSpeed"), last.get("Pressure")
        bits = []
        if last.get("DateTime"): bits.append(str(last["DateTime"]).replace("T", " ").replace("+08:00", ""))
        if lon and lat: bits.append(f"中心位於東經{lon}度、北緯{lat}度")
        if press: bits.append(f"中心氣壓{press}百帕")
        if wind: bits.append(f"最大風速{wind}公尺/秒")
        if pred: bits.append(pred)
        num = str(tc.get("CwaTyNo") or tc.get("CwaTdNo") or "").lstrip("0") or None
        out.append({
            "id": tc.get("TyphoonName") or tc.get("CwaTyphoonName") or num,
            "name_zh": tc.get("CwaTyphoonName"), "name_en": tc.get("TyphoonName"),
            "intensity": typoon_intensity(wind), "number": num,
            "status": "，".join(bits), "as_of": last.get("DateTime"),
            "url": page("TY_NEWS"),
        })
    return out

def _eq_item(eq, hours, now):
    info = eq.get("EarthquakeInfo") or {}
    origin = info.get("OriginTime")
    t = None
    if origin:
        try:
            t = datetime.fromisoformat(origin)
            if t.tzinfo is None: t = t.replace(tzinfo=TPE)
        except ValueError:
            t = None
    if t and t < now - timedelta(hours=hours): return None
    no = eq.get("EarthquakeNo")
    numbered = bool(no) and str(no) not in ("0", "000", "115000")
    # unnumbered reports often use 115000 or omit a real serial
    if str(no).endswith("000") and not numbered:
        numbered = False
        no = None
    mag = ((info or {}).get("EarthquakeMagnitude") or {}).get("MagnitudeValue")
    inten = None
    for area in as_list(((eq.get("Intensity") or {}).get("ShakingArea"))):
        ai = (area or {}).get("AreaIntensity")
        if ai and (inten is None or ai > inten):
            inten = ai
    loc = ((info.get("Epicenter") or {}).get("Location") or "").strip()
    depth = info.get("FocalDepth")
    depth_s = f"{depth}公里" if depth is not None and depth != "" else ""
    url = eq.get("Web") or page("EQ")
    lvl = 0
    if inten:
        m = re.match(r"(\d+)", str(inten))
        if m: lvl = int(m.group(1))
    try: mag_f = float(mag) if mag is not None else None
    except (TypeError, ValueError): mag_f = None
    return {"time": t.isoformat() if t else origin, "number": str(no) if numbered else None,
            "kind": "顯著有感地震（編號）" if numbered else "小區域有感地震",
            "magnitude": mag_f, "max_intensity": inten,
            "depth": depth_s, "location": clean(loc),
            "urgent": bool(numbered and (lvl >= 4 or (mag_f is not None and mag_f >= 6.0))),
            "url": url}

def from_opendata_earthquakes(records_list, hours):
    now = datetime.now(TPE); out, seen = [], set()
    for records in records_list:
        if not records: continue
        eqs = records.get("Earthquake") if isinstance(records, dict) else records
        for eq in as_list(eqs):
            if not isinstance(eq, dict): continue
            item = _eq_item(eq, hours, now)
            if not item: continue
            key = (item.get("time"), item.get("magnitude"), item.get("location"))
            if key in seen: continue
            seen.add(key); out.append(item)
    out.sort(key=lambda e: e.get("time") or "", reverse=True)
    return out

def from_scweb_home(src, hours):
    """Parse the official 地震測報中心 homepage table (keyless)."""
    now = datetime.now(TPE); out = []
    for row in re.findall(r'<tr class="btnInfo".*?</tr>', src, re.S):
        href = (re.search(r'href="(/zh-tw/earthquake/details/[^"]+)"', row) or [None, None])[1]
        tds = [clean(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        # [icon or number, intensity, time, magnitude, depth, location]
        if len(tds) < 6: continue
        num_m = re.search(r"\b(\d{2,3})\b", tds[0])
        num = num_m.group(1) if num_m else None
        inten = tds[1].replace(" ", "") or None
        when = tds[2]
        try:
            t = datetime.strptime(f"{now.year}/{when}", "%Y/%m/%d %H:%M").replace(tzinfo=TPE)
            if t > now + timedelta(days=1): t = t.replace(year=now.year - 1)
        except Exception:
            t = None
        if t and t < now - timedelta(hours=hours): continue
        mag = tds[3]; depth = tds[4]; loc = tds[5]
        numbered = bool(num)
        lvl = int(re.match(r"\d+", inten).group(0)) if inten and re.match(r"\d+", inten) else 0
        try: mag_f = float(mag) if mag else None
        except ValueError: mag_f = None
        out.append({"time": t.isoformat() if t else when, "number": f"115{num}" if numbered else None,
                    "kind": "顯著有感地震（編號）" if numbered else "小區域有感地震",
                    "magnitude": mag_f, "max_intensity": inten,
                    "depth": f"{depth}公里" if depth and "公里" not in depth else depth,
                    "location": loc,
                    "urgent": bool(numbered and (lvl >= 4 or (mag_f is not None and mag_f >= 6.0))),
                    "url": (SCWEB + href) if href else SCWEB + "/"})
    return out

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
        al["urgent"] = is_urgent(al["type"] + (al.get("summary") or ""))
    for t in tys:
        t["warning_active"] = t["id"] in active_ty or any(x["code"] == "TY_WARN" for x in alerts)
    # Fall back to official open data when www.cwa.gov.tw keyless sources fail
    # (some networks see a HiNetCDN 404 even though the public files still exist).
    need_warn = not any(s.get("ok") for s in status if s["source"] in ("CWA RSS 警報特報", "CWA Warning_Content.js"))
    need_ty = not any(s.get("ok") for s in status if s["source"] == "CWA TY_NEWS-Data.js")
    need_eq = not any(s.get("ok") for s in status if s["source"] == "CWA EQ_ROW 地震列表")
    extra = None
    if need_warn or need_ty or need_eq:
        key = opendata_key()
        extra = from_api(key, status)
        if need_warn and extra.get("W-C0033-002") is not None:
            alerts = from_opendata_warnings(extra["W-C0033-002"])
            for al in alerts:
                al["urgent"] = is_urgent(al["type"] + (al.get("summary") or ""))
        if need_ty and extra.get("W-C0034-005") is not None:
            tys = from_opendata_typhoons(extra["W-C0034-005"])
        if need_eq:
            eqs = from_opendata_earthquakes(
                [extra.get("E-A0015-001"), extra.get("E-A0016-001")], a.eq_hours)
    else:
        key = os.environ.get("CWA_API_KEY", "").strip()
        if key:
            extra = from_api(key, status)
        else:
            status.append({"source": "opendata API", "ok": None, "note": "keyless sources ok; CWA_API_KEY not set, skipped"})
    for t in tys:
        t["warning_active"] = t.get("warning_active") or any(x["code"] in ("TY_WARN", "W21") for x in alerts)
    if need_eq and not eqs:
        try:
            src = get(SCWEB + "/", data_time=False)
            eqs = from_scweb_home(src, a.eq_hours)
            status.append({"source": "CWA 地震測報中心 scweb", "url": SCWEB + "/", "ok": True})
            print("[OK] CWA 地震測報中心 scweb", file=sys.stderr)
        except Exception as e:
            status.append({"source": "CWA 地震測報中心 scweb", "url": SCWEB + "/", "ok": False, "error": str(e)[:200]})
            print(f"[FAIL] CWA 地震測報中心 scweb: {e}", file=sys.stderr)
    out = {"generated": datetime.now(TPE).replace(microsecond=0).isoformat(), "sources": status,
           "active_alerts": alerts, "rss_items": rss, "typhoons": tys, "earthquakes": eqs,
           "urgent": any(x.get("urgent") for x in alerts + eqs)}
    if extra is not None:
        # raw records can be large (station lists); keep only presence + dataset keys
        out["opendata"] = {k: ("ok" if v is not None else None) for k, v in extra.items()}
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print_summary(out)
    print(f"-> {a.out}", file=sys.stderr)

def print_summary(o):
    print(f"== 中央氣象署 官方警特報（{o['generated']}）==")
    for s in o["sources"]:
        if s["ok"] is False: print(f"[CWA FAIL] {s['source']}: {s.get('error')}")
    warn_ok = any(s.get("ok") for s in o["sources"] if s["source"] in (
        "CWA RSS 警報特報", "CWA Warning_Content.js", "opendata W-C0033-002"))
    if not warn_ok: print("！無法取得 CWA 警特報資料，請手動開啟 https://www.cwa.gov.tw/V8/C/P/Warning/FIFOWS.html 確認。")
    elif not o["active_alerts"] and not o["rss_items"]: print("目前無生效中的警特報。")
    for x in o["active_alerts"]:
        flag = "【緊急】" if x.get("urgent") else ""
        vt = f"，有效至 {x['valid_to']}" if x.get("valid_to") else ""
        print(f"- {flag}{x['type']}（發布 {x.get('issued')}{vt}）{x['summary'][:160]} | {x['url']}")
    for t in o["typhoons"]:
        print(f"- 颱風 {t['intensity'] or ''}{t['name_zh']}（第{t['number']}號，{t['name_en']}）"
              f"{'警報中' if t['warning_active'] else '無警報'}；{t['as_of']}：{t['status'][:160]} | {t['url']}")
    if not any(s.get("ok") for s in o["sources"] if s["source"] in (
            "CWA EQ_ROW 地震列表", "opendata E-A0015-001", "opendata E-A0016-001", "CWA 地震測報中心 scweb")):
        print("！無法取得 CWA 地震列表，請手動開啟 https://scweb.cwa.gov.tw/ 確認。"); big = []
    big = [e for e in o["earthquakes"] if e["number"]]
    print(f"- 近期地震：{len(o['earthquakes'])} 筆（編號顯著有感 {len(big)} 筆）")
    for e in o["earthquakes"]:
        if e["number"] or e["urgent"]:
            print(f"  {'【緊急】' if e['urgent'] else ''}第{e['number']}號 {e['time']} M{e['magnitude']} 最大震度{e['max_intensity']} {e['location']} | {e['url']}")
    print("整體：" + ("有緊急項目（夜間時段亦須處理）" if o["urgent"] else "無緊急項目"))

if __name__ == "__main__":
    main()
