"""Funding-label lookup shared by fetch.py and update.py (single source of truth: data/source_funding.json).

funding_for(source_name) -> {"label": key, "tag": 短標籤, "outlet": id, "name": ..., "detail": ..., "basis": url, "explicit": bool}
`explicit` is False when no outlet matches (the label then falls back to 「未標示」). Longest matching prefix wins; the prefix
must be followed by the end of the string or a non-alphanumeric ASCII character (so "Dawn" matches "Dawn Business" but not "Dawnx").
"""
import json, os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "source_funding.json")
_cache = None

def load():
    global _cache
    if _cache is None:
        _cache = json.load(open(_PATH, encoding="utf-8"))
    return _cache

def _prefix_ok(name, p):
    if not name.startswith(p):
        return False
    rest = name[len(p):]
    return rest == "" or not (rest[0].isascii() and rest[0].isalnum())

def funding_for(name):
    d = load()
    best, blen = None, -1
    for o in d["outlets"]:
        for p in o["match"]:
            if len(p) > blen and _prefix_ok(name or "", p):
                best, blen = o, len(p)
    if best is None:
        lab = d["labels"]["unlabeled"]
        return {"label": "unlabeled", "tag": lab["tag"], "outlet": None, "name": name, "detail": "", "basis": "", "explicit": False}
    return {"label": best["label"], "tag": d["labels"][best["label"]]["tag"], "outlet": best["id"], "name": best["name"],
            "detail": best["detail"], "basis": best["basis"], "explicit": True}
