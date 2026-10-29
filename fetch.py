#!/usr/bin/env python3
"""Fetch RSS feeds and output candidate livelihood (民生) news items as JSON.

Usage: python3 fetch.py [-o candidates.json] [--hours 36]
Fetches each feed once (modest, with a polite User-Agent and delay).
Output candidates are for an editor to curate; summaries are written by hand
(or a later pipeline) into data/news.json.
"""
import argparse, json, re, sys, time, urllib.request, email.utils
from funding import funding_for   # 資金來源標示：單一對照表 data/source_funding.json
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
    # NHK cat0 RSS returned only stale (Aug 2026) items on 2026-10-21 (re-checked 2026-10-29: cat0/1/3/4/5/6 and
    # nhkworld all.json all still stale); kept for completeness
    ("NHK", "intl", "https://www3.nhk.or.jp/rss/news/cat0.xml"),
    # --- more 國際 sources (added 2026-10-29; each verified to fetch + parse + carry fresh dates, no key needed).
    # Mixed regions/viewpoints on purpose: UK, US/EU public media, Germany, France, Middle East, Singapore, Hong Kong,
    # Japan, Korea, Philippines, Thailand, Australia. All feed `tab="intl"`; the editor still decides what is used.
    ("BBC Technology", "intl", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("BBC Science", "intl", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("DW World", "intl", "https://rss.dw.com/rdf/rss-en-world"),
    ("DW Business", "intl", "https://rss.dw.com/rdf/rss-en-bus"),
    ("DW Asia", "intl", "https://rss.dw.com/rdf/rss-en-asia"),
    ("Al Jazeera English", "intl", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Guardian World", "intl", "https://www.theguardian.com/world/rss"),
    ("Guardian Business", "intl", "https://www.theguardian.com/uk/business/rss"),
    ("France 24", "intl", "https://www.france24.com/en/rss"),
    ("CNA Singapore World", "intl", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6311"),
    ("CNA Singapore Asia", "intl", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511"),
    ("CNA Singapore Business", "intl", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936"),
    ("Straits Times Asia", "intl", "https://www.straitstimes.com/news/asia/rss.xml"),
    ("Straits Times Business", "intl", "https://www.straitstimes.com/news/business/rss.xml"),
    ("Japan Times", "intl", "https://www.japantimes.co.jp/news/feed/"),
    ("Korea Herald World", "intl", "https://www.koreaherald.com/rss/kh_World"),
    ("Yonhap English", "intl", "https://en.yna.co.kr/RSS/news.xml"),
    ("SCMP Asia", "intl", "https://www.scmp.com/rss/3/feed"),
    ("SCMP Economy", "intl", "https://www.scmp.com/rss/92/feed"),
    ("Korea Herald Business", "intl", "https://www.koreaherald.com/rss/kh_Business"),
    ("Rappler", "intl", "https://www.rappler.com/feed/"),
    ("Bangkok Post", "intl", "https://www.bangkokpost.com/rss/data/topstories.xml"),
    ("ABC Australia", "intl", "https://www.abc.net.au/news/feed/2942460/rss.xml"),
    # --- source diversity round 2 (added 2026-10-29): Middle East, South Asia, Latin America, Africa. English-only, keyless;
    # each verified 2026-10-29 with curl (HTTP 200, parseable, newest item < 10 h old, articles readable without sign-in/paywall).
    # Rejected after testing (do not re-add without re-checking): Times of Israel (articles 403 / bot challenge), Al-Monitor (paywall),
    # Buenos Aires Times (metered paywall), Mexico News Daily (leaky paywall + bot check), Daily Maverick (sign-in wall after N free
    # articles; /feed/ 403), Nation Africa (premium content, some 403). See AUTOMATION.md for the full list.
    ("Anadolu Agency World", "intl", "https://www.aa.com.tr/en/rss/default?cat=world"),
    ("Daily News Egypt", "intl", "https://www.dailynewsegypt.com/feed/"),
    ("Asharq Al-Awsat", "intl", "https://english.aawsat.com/feed"),
    ("Tehran Times", "intl", "https://www.tehrantimes.com/rss"),
    ("Dawn", "intl", "https://www.dawn.com/feeds/home"),
    ("Dawn Business", "intl", "https://www.dawn.com/feeds/business"),
    ("Times of India World", "intl", "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms"),
    ("Times of India Business", "intl", "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms"),
    ("Daily Star Bangladesh", "intl", "https://www.thedailystar.net/news/rss.xml"),
    ("Daily Star Bangladesh Business", "intl", "https://www.thedailystar.net/business/rss.xml"),
    ("Express Tribune", "intl", "https://tribune.com.pk/feed/home"),
    ("EconomyNext", "intl", "https://economynext.com/feed/"),
    ("MercoPress", "intl", "https://en.mercopress.com/rss"),
    ("Rio Times", "intl", "https://www.riotimesonline.com/feed/"),
    ("Colombia One", "intl", "https://colombiaone.com/feed/"),
    ("Africanews", "intl", "https://www.africanews.com/feed/rss"),   # item links are http:// (500 there); parse() upgrades them to https
    ("Premium Times", "intl", "https://www.premiumtimesng.com/feed"),
    ("Punch Nigeria", "intl", "https://punchng.com/feed/"),
    ("SABC News", "intl", "https://www.sabcnews.com/sabcnews/feed/"),
    ("The Citizen South Africa", "intl", "https://www.citizen.co.za/feed/"),
    ("Graphic Online Ghana", "intl", "https://www.graphic.com.gh/news.feed?type=rss"),
]
TAB_TAG = {"tw": "台灣", "intl": "國際"}   # tag shown in the candidate list
INTL_MAX_PER_FEED = 12   # keep the newest N matching items per 國際 feed so the broad English feeds cannot flood the list

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
# 國際 hints (English feeds): whole-word / phrase regexes -> existing category. Only a hint; the editor decides whether an
# item has a real (direct or indirect) Taiwan livelihood link. Used only for feeds with tab="intl".
INTL_CATEGORIES = {
    "物價與薪資": [r"inflation", r"consumer prices?", r"central banks?", r"interest rates?", r"rate (cut|hike)s?", r"\bFed\b", r"Federal Reserve",
                 r"currency", r"\byen\b", r"South Korean won", r"dollar", r"\beuro\b", r"wheat", r"\brice\b", r"grain", r"coffee", r"cocoa", r"food prices?",
                 r"commodit", r"minimum wage", r"recession", r"\bGDP\b", r"unemployment"],
    "稅務與補助": [r"tariffs?", r"\btax(es)?\b", r"subsid", r"customs dut", r"sanctions"],
    "健保與醫療": [r"outbreak", r"epidemic", r"pandemic", r"virus", r"vaccine", r"\bWHO\b", r"\bFDA\b", r"drug approval", r"bird flu", r"avian", r"Ebola", r"measles", r"cholera", r"dengue", r"mpox", r"health (ministry|authorit)"],
    "房價與租屋": [r"housing market", r"property market", r"home prices?", r"mortgage"],
    "能源與水電": [r"\boil\b", r"crude", r"Brent", r"\bOPEC", r"natural gas", r"\bLNG\b", r"electricity", r"power (cuts?|outage|grid)", r"energy", r"Strait of Hormuz", r"nuclear"],
    "交通": [r"airline", r"airport", r"aviation", r"\bflights?\b", r"Boeing", r"Airbus", r"shipping", r"container", r"port strike", r"high-speed (train|rail)", r"visa[- ]free", r"travel (ban|advisory|rules?)", r"cruise"],
    "天災與公共安全": [r"earthquake", r"tsunami", r"typhoon", r"hurricane", r"cyclone", r"flood", r"wildfire", r"heat ?wave", r"drought", r"volcano", r"landslide", r"extreme weather", r"train crash", r"plane crash", r"climate"],
    "勞動與產業": [r"semiconductor", r"\bchips?\b", r"\bTSMC\b", r"Nvidia", r"\bAI\b", r"artificial intelligence", r"supply chain", r"export controls?", r"\bstrikes?\b", r"layoffs?", r"job cuts", r"trade (deal|war|talks|curbs)", r"rare earth", r"\bEV\b", r"electric vehicles?", r"Samsung", r"Apple", r"Foxconn", r"Taiwan"],
    "新法規": [r"new (law|rules?|regulation)s?", r"regulat", r"export ban", r"import ban", r"takes effect", r"comes into (force|effect)"],
}
EXCLUDE_INTL = [r"\bmurder", r"stabbing", r"celebrit", r"\bactress\b", r"\bactor\b", r"\bsinger\b", r"\bfootball\b", r"\bsoccer\b", r"\bcricket\b", r"\bNFL\b", r"\bNBA\b", r"\bMLB\b",
                r"Premier League", r"\bgolf\b", r"\btennis\b", r"\brugby\b", r"royal family", r"\bhoroscope", r"\bK-pop\b"]
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
    rdf = "{http://purl.org/rss/1.0/}"   # RSS 1.0 / RDF feeds (DW, Nikkei Asia) use namespaced <item>
    items = root.findall(".//item") or root.findall(f".//{atom}entry") or root.findall(f".//{rdf}item")
    out = []
    for it in items:
        link = text(it, "link", f"{rdf}link")
        if not link:
            l = it.find(f"{atom}link")
            link = l.get("href") if l is not None else ""
        if link.startswith("http://www.africanews.com/"):
            link = "https://" + link[len("http://"):]   # their feed emits http:// links, which answer 500; https works
        out.append({
            "title": text(it, "title", f"{atom}title", f"{rdf}title"),
            "link": link,
            "summary": re.sub(r"<[^>]+>", "", text(it, "description", f"{atom}summary", f"{rdf}description"))[:300],
            "published": text(it, "pubDate", f"{atom}updated", f"{atom}published", "{http://purl.org/dc/elements/1.1/}date"),
        })
    return out

def intl_match(pattern, text):
    """Pattern written all-lowercase -> case-insensitive; any capital letter (Fed, WHO, Brent, AI) -> case-sensitive,
    so acronyms such as WHO/AI do not match ordinary words."""
    return re.search(pattern, text, 0 if pattern != pattern.lower() else re.I) is not None

def classify(title, summary, tab="tw"):
    blob = f"{title} {summary}"
    if any(k in blob for k in EXCLUDE):
        return []
    if tab == "intl":
        # Chinese keywords (中央社 國際, NHK...) still apply; English feeds use whole-word regexes instead of loose substrings
        if any(intl_match(p, title) for p in EXCLUDE_INTL):
            return []
        out = []
        for c, kws in CATEGORIES.items():
            zh = [k for k in kws if not k.isascii()]
            if any(k in blob for k in zh) or any(intl_match(p, blob) for p in INTL_CATEGORIES.get(c, [])):
                out.append(c)
        return out
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
            if not items:
                raise ValueError("feed parsed but contains 0 items (format changed or empty)")
            status.append({"feed": name, "url": url, "ok": True, "items": len(items), "tab": tab, "tag": TAB_TAG.get(tab, tab),
                           "funding": funding_for(name)["label"]})
        except Exception as e:
            status.append({"feed": name, "url": url, "ok": False, "error": str(e)[:200]})
            print(f"[FAIL] {name}: {e}", file=sys.stderr)
            continue
        kept = 0
        for it in items:
            d = parse_date(it["published"])
            if d and d.tzinfo and d < cutoff:
                continue
            cats = classify(it["title"], it["summary"], tab)
            if cats or a.all:
                if tab == "intl" and kept >= INTL_MAX_PER_FEED and not a.all:
                    continue   # feeds are newest-first; cap how many items one broad 國際 feed contributes
                kept += 1
                cands.append({**it, "source": name, "tab": tab, "tag": TAB_TAG.get(tab, tab), "categories": cats,
                              "funding": funding_for(name)["label"]})
        print(f"[OK] {name}: {len(items)} items", file=sys.stderr)
        time.sleep(1.5)  # be polite
    json.dump({"generated": datetime.now(timezone.utc).isoformat(), "feeds": status, "candidates": cands},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{len(cands)} candidates -> {a.out}", file=sys.stderr)

if __name__ == "__main__":
    main()
