#!/usr/bin/env python3
"""VAQTINCHA o'lchov vositasi (2-bo'lim, 2026-10-26).

Pipeline'ga umuman ta'sir qilmaydi — faqat YouTube Data API +
Analytics API'dan 13 videoning ko'rsatkichlarini logga chiqaradi.
Ishdan keyin o'chiriladi.
Chiqim formatlari (parse uchun):
  SCOPE|<token scope>
  DATA|<id>|<views>|<likes>|<comments>|<dur_s>|<privacy>|<published>
  ANL|<id>|<views>|<avgdur>|<avgpct>|<impr>|<ctr>     (yoki ANLERR|<id>|<xato>)
  RET|<id>|<ratio>|<watch_ratio>                        (100 nuqta)
  RETDROP|<id>|<sec>|<drop_pct>|<from_pct>|<to_pct>
"""
import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


def http_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:300]
        except Exception:
            body = "?"
        return {"_error": e.code, "_body": body}, e.code
    except Exception as e:
        return {"_error": str(e)}, 0


def dur_s(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", iso or "")
    if not m:
        return 0.0
    h, mi, se = (float(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def main():
    hist = json.load(open("history.json", encoding="utf-8"))
    vids = [{"id": e["video_id"], "date": e["date"]} for e in hist]
    print("videolar:", len(vids))
    today = datetime.date.today().isoformat()

    # --- A: Data API (statistics + duration + privacy) ---
    key = os.environ.get("YT_API_KEY", "")
    ids = ",".join(v["id"] for v in vids)
    url = ("https://www.googleapis.com/youtube/v3/videos"
           "?part=statistics,contentDetails,snippet,status&id="
           + ids + "&key=" + key)
    d, st = http_json(url)
    print("=== DATA_API status:", st)
    pub_map = {}
    if "items" in d:
        for it in d["items"]:
            s = it.get("statistics", {})
            vid = it["id"]
            pub = it.get("snippet", {}).get("publishedAt", "")[:10]
            pub_map[vid] = pub
            print("DATA|%s|%s|%s|%s|%.1f|%s|%s" % (
                vid, s.get("viewCount", 0), s.get("likeCount", 0),
                s.get("commentCount", 0),
                dur_s(it.get("contentDetails", {}).get("duration", "")),
                it.get("status", {}).get("privacyStatus", "?"), pub))
    else:
        print("DATAERR|" + json.dumps(d)[:300])

    # --- B: OAuth refresh + scope tekshiruvi ---
    cid = os.environ.get("YT_CLIENT_ID", "")
    csec = os.environ.get("YT_CLIENT_SECRET", "")
    rt = os.environ.get("YT_REFRESH_TOKEN", "")
    tok = None
    if cid and csec and rt:
        form = urllib.parse.urlencode({
            "client_id": cid, "client_secret": csec,
            "refresh_token": rt, "grant_type": "refresh_token"}).encode()
        d2, st2 = http_json(
            "https://oauth2.googleapis.com/token", data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        print("=== OAUTH status:", st2)
        if "access_token" in d2:
            tok = d2["access_token"]
            print("SCOPE|" + d2.get("scope", "?"))
        else:
            print("OAUTHERR|" + json.dumps(d2)[:400])
    else:
        print("OAUTHERR|secrets yo'q")

    if not tok:
        return

    hdr = {"Authorization": "Bearer " + tok}

    # --- C: Analytics API — har video uchun asosiy ko'rsatkichlar ---
    for v in vids:
        vid = v["id"]
        pub = pub_map.get(vid, v["date"][:10])
        start = min(pub, today)
        base = ("https://youtubeanalytics.googleapis.com/v2/reports"
                "?ids=channel%3D%3DMINE&filters=video%3D%3D" + vid)
        m_all = ("views,averageViewDuration,averageViewPercentage,"
                 "impressions,clickThroughRate")
        d3, st3 = http_json(base + "&metrics=" + urllib.parse.quote(m_all)
                            + "&startDate=" + start + "&endDate=" + today,
                            headers=hdr)
        if "rows" in d3 and d3["rows"]:
            r = d3["rows"][0]
            print("ANL|%s|%s|%s|%s|%s|%s" % (vid, r[0], r[1], r[2],
                                             r[3] if len(r) > 3 else "",
                                             r[4] if len(r) > 4 else ""))
        elif d3.get("_error"):
            # impressions/ctr mavjud bo'lmasa — qisqa to'plam bilan qayta
            m_min = "views,averageViewDuration,averageViewPercentage"
            d4, st4 = http_json(
                base + "&metrics=" + urllib.parse.quote(m_min)
                + "&startDate=" + start + "&endDate=" + today, headers=hdr)
            if "rows" in d4 and d4["rows"]:
                r = d4["rows"][0]
                print("ANL|%s|%s|%s|%s||" % (vid, r[0], r[1], r[2]))
            else:
                print("ANLERR|%s|%s|%s" % (vid, st3, json.dumps(d4)[:200]))
        else:
            print("ANLEMPTY|%s|%s" % (vid, json.dumps(d3)[:200]))

    # --- D: retention egri chizig'i (eski 2 + yangi 3) ---
    want = ["oeBE3Mvz8zE", "cdf6wSj9KDA", "Lb9G1JmOUOM",
            "GgIQmbaDQvc", "rQB-4m1_FfA"]
    durs = {}
    for v in vids:
        # uzunlikni Data API'dan olmoqdamiz — lekin bu yerda faqat ID bor;
        # dur ni DATA qatoridan ololmaymiz, shuning uchun retentionni
        # nisbiy nuqtalarda chiqaramiz, sekundni tashqarida hisoblaymiz.
        pass
    for vid in want:
        pub = pub_map.get(vid, "2026-10-21")
        url = ("https://youtubeanalytics.googleapis.com/v2/reports"
               "?ids=channel%3D%3DMINE&filters=video%3D%3D" + vid
               + "&metrics=audienceWatchRatio"
               + "&dimensions=elapsedVideoTimeRatio"
               + "&startDate=" + min(pub, today) + "&endDate=" + today)
        d5, st5 = http_json(url, headers=hdr)
        if "rows" in d5 and d5["rows"]:
            rows = d5["rows"]
            for pt in rows:
                print("RET|%s|%.2f|%.4f" % (vid, pt[0], pt[1]))
            worst, wi = None, 1
            for i in range(1, len(rows)):
                drop = rows[i - 1][1] - rows[i][1]
                if worst is None or drop > worst:
                    worst, wi = drop, i
            if worst is not None and worst > 0:
                print("RETDROP|%s|ratio=%.2f|drop=%.1f%%|from=%.1f%%|to=%.1f%%"
                      % (vid, rows[wi][0], worst * 100, rows[wi - 1][1] * 100,
                         rows[wi][1] * 100))
        else:
            print("RETERR|%s|%s" % (vid, json.dumps(d5)[:200]))


if __name__ == "__main__":
    main()
