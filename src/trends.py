"""1-qadam: YouTube (Data API v3) orqali niche'da US trendini tahlil qilish.

Quota (2026 yil holatiga ko'ra):
  - search.list   -> o'z bucket'i: 100 chaqiruv/kun
  - videos.list   -> umumiy bucket: 1 unit
  Kunlik sarf: ~4 search + 1 videos.list = juda oz.
Natija 6 soatgacha trends_cache.json'da cachelanadi (retry'lar quota'ni
yo'qotmaydi).
"""
import datetime
import json
import os
import re
import time

from src.config import ROOT
from src.net import session

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

STOP = set("""the a an and or of to in on at for with my your our we i you it its
is are was were do does did this that what when where who how can could should
would be been being as by from about into over under out up down off again more
most some such only same so than too very just not no yes but if because until
while during before after above below between get got go goes going make makes
made like know think thing things moment moments way something anything""".split())


def _iso_days_ago(days):
    dt = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(url, params, key):
    params = dict(params, key=key)
    r = session().get(url, params=params, timeout=30)
    if r.status_code == 403 and "quotaExceeded" in r.text:
        raise RuntimeError(
            "YouTube quota tugadi (quotaExceeded). Ertaga yoki boshqa GCP loyihasi."
        )
    if r.status_code != 200:
        raise RuntimeError(f"YouTube API {r.status_code}: {r.text[:300]}")
    return r.json()


def _analyze(items):
    titles = [i["title"] for i in items]
    top = sorted(items, key=lambda x: -x["views"])[:10]
    words, tags = {}, {}
    for t in titles:
        for w in re.findall(r"[a-z']{3,}", t.lower()):
            if w not in STOP:
                words[w] = words.get(w, 0) + 1
        for h in re.findall(r"#(\w+)", t.lower()):
            tags[h] = tags.get(h, 0) + 1
    formats = []
    for marker in ("POV", "Top 5", "Top 10", "Storytime", "Day in my life",
                   "Wait for it", "Nobody:", "When you", "Part "):
        if any(marker.lower() in t.lower() for t in titles):
            formats.append(marker)
    return {
        "top_titles": [{"title": i["title"], "views": i["views"]} for i in top],
        "avg_views_top10": round(sum(i["views"] for i in top) / max(1, len(top))),
        "top_words": [w for w, _ in sorted(words.items(), key=lambda kv: -kv[1])[:15]],
        "hashtags": [h for h, _ in sorted(tags.items(), key=lambda kv: -kv[1])[:10]],
        "avg_title_len": round(sum(len(t) for t in titles) / max(1, len(titles))),
        "formats_seen": formats,
    }


def fetch_trending(cfg):
    """Niche bo'yicha oxirgi 30 kunda trend bo'lgan Shorts'larni qaytaradi."""
    cache_path = cfg["_paths"]["trends_cache"]
    # ---- cache: 6 soat ichida takror qidiruv qilmaymiz (quota tejash) ----
    if os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < 6 * 3600:
            with open(cache_path, encoding="utf-8") as f:
                print("[trends] cache'dan olindi (6 soatdan yosh)")
                return json.load(f)

    s = session()
    key = cfg["secrets"]["yt_api_key"]
    src = cfg["sources"]
    queries = [f"funny {t} moments" for t in cfg["channel"]["topics"]][:3]
    queries.append(cfg["channel"]["niche"])

    def _search_all(with_category):
        """Barcha so'rovlarni yuboradi. videoCategoryId search.list'da
        ko'pincha BO'SH natija qaytaradi (YouTube'ning ma'lum xususiyati),
        shuning uchun bo'sh bo'lsa filtrsiz qayta urinamiz."""
        got, seen = [], set()
        for q in queries:
            params = {
                "part": "snippet",
                "q": q,
                "type": "video",
                "videoDuration": "short",
                "regionCode": src["youtube_region"],
                "order": "viewCount",
                "publishedAfter": _iso_days_ago(src["days_back"]),
                "maxResults": 25,
                "fields": "items(id/videoId,snippet/title,snippet/channelTitle,snippet/publishedAt)",
            }
            if with_category:
                params["videoCategoryId"] = src["youtube_category"]
            try:
                data = _get(SEARCH_URL, params, key)
            except Exception as e:
                print(f"[trends] so'rov xatosi ({q!r}): {e}")
                continue
            for it in data.get("items", []):
                vid = it["id"].get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    got.append({
                        "id": vid,
                        "title": it["snippet"]["title"],
                        "channel": it["snippet"].get("channelTitle", ""),
                        "published": it["snippet"].get("publishedAt", ""),
                        "views": 0,
                        "duration": "",
                    })
            time.sleep(0.4)
        return got

    items = _search_all(True)
    if not items:
        print("[trends] category filtri bilan natija bo'sh - filtrsiz qayta urinish")
        items = _search_all(False)

    items = items[: cfg["sources"]["max_trend_items"]]
    if not items:
        raise RuntimeError("YouTube'dan hech narsa topilmadi — kalit/region/so'rovni tekshiring")

    # ---- views va davomiylik (videos.list: 1 unit) ----
    stats = {}
    for i in range(0, len(items), 40):
        batch = ",".join(x["id"] for x in items[i:i + 40])
        try:
            data = _get(VIDEOS_URL, {"part": "statistics,contentDetails", "id": batch}, key)
        except Exception as e:
            print(f"[trends] statistika xatosi: {e}")
            continue
        for v in data.get("items", []):
            stats[v["id"]] = {
                "views": int(v.get("statistics", {}).get("viewCount", 0) or 0),
                "duration": v.get("contentDetails", {}).get("duration", ""),
            }
    for it in items:
        it.update(stats.get(it["id"], {"views": 0, "duration": ""}))

    out = {
        "fetched_at": _iso_days_ago(0),
        "queries": queries,
        "items": items,
        "summary": _analyze(items),
    }
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return out
