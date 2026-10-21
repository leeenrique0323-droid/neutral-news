#!/usr/bin/env python3
"""Fetch RSS feeds and output candidate livelihood (民生) news items as JSON.

Usage: python3 fetch.py [-o candidates.json] [--hours 36]
Fetches each feed once (modest, with a polite User-Agent and delay).
Output candidates are for an editor to curate; summaries are written by hand
(or a later pipeline) into data/news.json.
"""
import argparse, json, re, sys, time, urllib.request, email.utils
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

UA = "NeutralNewsPrototype/0.1 (+local prototype; modest polling)"
FEEDS = [
    # (source name, tab, url)
    ("公視新聞", "tw", "https://news.pts.org.tw/xml/newsfeed.xml"),
    ("中央社 政治", "tw", "https://feeds.feedburner.com/rsscna/politics"),
    ("中央社 財經", "tw", "https://feeds.feedburner.com/rsscna/finance"),
    ("中央社 生活", "tw", "https://feeds.feedburner.com/rsscna/lifehealth"),
    ("中央社 社會", "tw", "https://feeds.feedburner.com/rsscna/social"),
    ("中央社 地方", "tw", "https://feeds.feedburner.com/rsscna/local"),
    ("中央社 產經證券", "tw", "https://feeds.feedburner.com/rsscna/technology"),
    ("行政院 本院新聞", "tw", "https://www.ey.gov.tw/RSS_Content.aspx?ModuleType=3"),
    ("行政院 部會新聞", "tw", "https://www.ey.gov.tw/RSS_Content.aspx?ModuleType=4"),
    ("中央社 國際", "intl", "https://feeds.feedburner.com/rsscna/intworld"),
    ("BBC World", "intl", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Business", "intl", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    # NHK cat0 RSS returned only stale (Aug 2026) items on 2026-10-21; kept for completeness
    ("NHK", "intl", "https://www3.nhk.or.jp/rss/news/cat0.xml"),
]

# keyword -> category (zh-TW). Simple first-pass filter; editor decides.
CATEGORIES = {
    "物價與薪資": ["物價", "CPI", "通膨", "薪資", "基本工資", "油價", "漲價", "調漲", "降價", "失業", "inflation", "wage", "price"],
    "稅務與補助": ["稅", "補助", "津貼", "普發", "退稅", "補貼", "tax", "subsid"],
    "健保與醫療": ["健保", "醫療", "疫苗", "流感", "醫院", "藥", "長照", "疫情", "health", "vaccine"],
    "房價與租屋": ["房價", "租屋", "房貸", "社宅", "社會住宅", "打房", "信用管制", "租金", "housing", "mortgage"],
    "能源與水電": ["電價", "水價", "台電", "停電", "供電", "缺水", "限水", "天然氣", "核", "能源", "energy", "electricity"],
    "交通": ["高鐵", "台鐵", "捷運", "公車", "國道", "機場", "航班", "票價", "交通", "TPASS", "train", "airline"],
    "教育": ["教育", "學費", "學生", "學校", "大學", "教育部", "school", "tuition"],
    "天災與公共安全": ["颱風", "地震", "豪雨", "大雨", "淹水", "海嘯", "停班停課", "氣象署", "土石流", "typhoon", "earthquake", "flood"],
    "勞動與產業": ["罷工", "勞資", "工會", "裁員", "工安", "勞檢", "職災", "勞動部", "strike", "layoff"],
    "新法規": ["三讀", "修法", "新制", "上路", "草案", "法案", "立法院", "施行", "law", "bill"],
}
EXCLUDE = ["車禍", "判刑", "起訴", "藝人", "緋聞", "殺", "命案", "詐騙集團", "竊", "毒品", "棒球", "籃球", "MLB", "NBA"]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()

def text(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
    return ""

def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
        # CNA feeds omit the timezone; their times are Taipei time (UTC+8)
        return d if d.tzinfo else d.replace(tzinfo=timezone(timedelta(hours=8)))
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def parse(raw):
    root = ET.fromstring(raw)
    atom = "{http://www.w3.org/2005/Atom}"
    items = root.findall(".//item") or root.findall(f".//{atom}entry")
    out = []
    for it in items:
        link = text(it, "link")
        if not link:
            l = it.find(f"{atom}link")
            link = l.get("href") if l is not None else ""
        out.append({
            "title": text(it, "title", f"{atom}title"),
            "link": link,
            "summary": re.sub(r"<[^>]+>", "", text(it, "description", f"{atom}summary"))[:300],
            "published": text(it, "pubDate", f"{atom}updated", f"{atom}published", "{http://purl.org/dc/elements/1.1/}date"),
        })
    return out

def classify(title, summary):
    blob = f"{title} {summary}"
    if any(k in blob for k in EXCLUDE):
        return []
    return [c for c, kws in CATEGORIES.items() if any(k.lower() in blob.lower() for k in kws)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="candidates.json")
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--all", action="store_true", help="keep items without category match")
    a = ap.parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    cands, status = [], []
    for name, tab, url in FEEDS:
        try:
            items = parse(fetch(url))
            status.append({"feed": name, "url": url, "ok": True, "items": len(items)})
        except Exception as e:
            status.append({"feed": name, "url": url, "ok": False, "error": str(e)[:200]})
            print(f"[FAIL] {name}: {e}", file=sys.stderr)
            continue
        for it in items:
            d = parse_date(it["published"])
            if d and d.tzinfo and d < cutoff:
                continue
            cats = classify(it["title"], it["summary"])
            if cats or a.all:
                cands.append({**it, "source": name, "tab": tab, "categories": cats})
        print(f"[OK] {name}: {len(items)} items", file=sys.stderr)
        time.sleep(1.5)  # be polite
    json.dump({"generated": datetime.now(timezone.utc).isoformat(), "feeds": status, "candidates": cands},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{len(cands)} candidates -> {a.out}", file=sys.stderr)

if __name__ == "__main__":
    main()
