"""Tarix: qo'llanilgan mavzular + ishlatilgan klip id'lari.
GitHub Actions statsiz -> history.json commit orqali repo'ga qaytadi
(qarang .github/workflows/daily.yml)."""
import datetime
import difflib
import json
import os

from src.config import ROOT


def _path():
    return os.path.join(ROOT, "history.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save(entries):
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def keywords(entries):
    out = []
    for e in entries:
        out.append(e.get("title", ""))
        out.extend(e.get("keywords", []))
    return out


def clip_ids(entries=None):
    """Hamma ishlatilgan klip id'lari (takrorlanmaslik uchun)."""
    out = set()
    for e in (entries if entries is not None else load()):
        for c in e.get("clips", []):
            out.add(c)
    return out


def too_similar(new_title, new_keywords, entries, title_thresh=0.55,
                kw_overlap=3):
    """Yangi mavzu oldingi videolardan juda o'xshashmi?

    v9: OXIRGI 5 videoda BITTA umumiy kalit so'z ham takrorlanmaydi
    (bir davlat ketma-ket chiqmasin). Eski videolar bilan 3 ta
    overlap / 0.55 title o'xshashligi cheki."""
    new_kw = set(k.lower() for k in new_keywords)
    n = len(entries)
    for idx, e in enumerate(entries):
        old = e.get("title", "")
        if old and difflib.SequenceMatcher(None, new_title.lower(),
                                           old.lower()).ratio() > title_thresh:
            return True
        shared = new_kw & set(k.lower() for k in e.get("keywords", []))
        if len(shared) >= kw_overlap:
            return True
        if idx >= n - 5 and any(len(s) >= 4 for s in shared):
            return True
    return False


def add(title, keywords_list, video_id="", clips=None, ending_mode=None):
    entries = load()
    entry = {
        "date": datetime.datetime.now(datetime.UTC).isoformat(),
        "title": title,
        "keywords": keywords_list,
        "video_id": video_id,
        "clips": sorted(set(clips or []))[:60],
    }
    # v13.2 (user 3-tuzatish): loop/cta A/B — har videoga yoziladi
    if ending_mode:
        entry["ending_mode"] = str(ending_mode)
    entries.append(entry)
    save(entries)
