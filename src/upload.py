"""7-qadam: YouTube'ga yuklash (faqat inson tasdig'idan keyin).

OAuth2: refresh token (OAuth Playground orqali olinadi).
Quota: videos.insert = 1 unit / o'z bucket'i (100 ta/kun) —
2026-yilgi yangi granular quota tizimi.

v13.3 (user, 2026-10-26): privacy_status "public" bo'lsa, yuklangan
videoni tekshirib, private qolib ketsa videos.update bilan public
qilishga uriniladi. Cheklovlar: (a) API audit insert'ni private'ga
majbur qilishi mumkin; (b) videos.update uchun youtube.force-ssl
scope kerak — tokenda faqat youtube.upload bo'lsa 403. Bo'lsa ochiq
yoziladi (Studio'dan qo'lda public qilinadi).
"""
import time

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _client(cfg):
    sec = cfg["secrets"]
    creds = Credentials(
        token=None,
        refresh_token=sec["yt_refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=sec["yt_client_id"],
        client_secret=sec["yt_client_secret"],
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds,
                 cache_discovery=False, static_discovery=True)


def make_public(yt, vid):
    """videoni public qilishga urinish. -> (ok, sabab)."""
    try:
        st = yt.videos().list(part="status", id=vid).execute()
        items = st.get("items") or []
        if not items:
            return False, "video topilmadi"
        cur = (items[0].get("status") or {}).get("privacyStatus", "")
        if cur == "public":
            return True, "allakim public"
        yt.videos().update(
            part="status",
            body={"id": vid, "status": {"privacyStatus": "public"}},
        ).execute()
        st2 = yt.videos().list(part="status", id=vid).execute()
        it2 = (st2.get("items") or [{}])[0]
        now = (it2.get("status") or {}).get("privacyStatus", "")
        if now == "public":
            return True, f"{cur} -> public"
        return False, f"update'dan keyin ham {now}"
    except HttpError as e:
        if e.resp.status == 403:
            return False, ("403 — videos.update uchun youtube.force-ssl "
                           "scope kerak (tokenda faqat youtube.upload). "
                           "Studio'dan qo'lda public qiling")
        return False, f"HTTP {e.resp.status}: {str(e)[:120]}"
    except Exception as e:
        return False, str(e)[:120]


def publish_pending(cfg, video_ids):
    """Eski private videolarni public qilish (user so'rovi, 2026-10-26).

    history'dagi videolar (barchasi tasdiqlangan) ichida hali private
    turganlarni public qiladi. -> [(vid, ok, sabab), ...] private'lar."""
    ids = [v for v in (video_ids or []) if v]
    if not ids:
        return []
    yt = _client(cfg)
    out = []
    try:
        st = yt.videos().list(part="status", id=",".join(ids)).execute()
        for it in st.get("items", []):
            vid = it.get("id")
            if (it.get("status") or {}).get("privacyStatus") == "public":
                continue
            ok, why = make_public(yt, vid)
            print(f"[yt] publish_pending {vid}: "
                  f"{'OK' if ok else 'MUAMMO'} ({why})")
            out.append((vid, ok, why))
    except Exception as e:
        print(f"[yt] publish_pending ro'yxat olinmadi: {str(e)[:160]}")
    return out


def upload(cfg, video_path, title, description, tags):
    yt = _client(cfg)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": cfg["sources"]["youtube_category"],
            "defaultLanguage": cfg["channel"]["language"],
            "defaultAudioLanguage": cfg["channel"]["language"],
        },
        "status": {
            "privacyStatus": cfg["behavior"]["privacy_status"],
            "selfDeclaredMadeForKids": False,
        },
    }

    last_err = None
    for attempt in range(3):
        try:
            media = MediaFileUpload(video_path, chunksize=-1,
                                    resumable=True, mimetype="video/mp4")
            req = yt.videos().insert(part="snippet,status",
                                     body=body, media_body=media)
            resp = None
            while resp is None:
                _, resp = req.next_chunk()
            vid = resp["id"]
            # v13.3: private qolib ketsa (audit) — public qilib ko'ramiz
            want = str((cfg.get("behavior") or {})
                       .get("privacy_status") or "private").lower()
            public_ok, why = True, want
            if want == "public":
                public_ok, why = make_public(yt, vid)
                if not public_ok:
                    print(f"[yt] PUBLIC BO'LMADI ({why})")
            print(f"[yt] yuklandi: https://youtu.be/{vid} "
                  f"(privacy: {want}"
                  + (f" | {why}" if want == "public" else "") + ")")
            return vid, public_ok
        except RefreshError as e:
            # Refresh token eskirgan/noto'g'ri — qayta urinish foydasiz
            raise RuntimeError(
                "YT_REFRESH_TOKEN eskirgan yoki noto'g'ri. OAuth tokenlari "
                "verifikatsiyadan o'tmagan loyihada ~7 kunda tugaydi. "
                "Google OAuth Playground'dan yangi refresh_token oling va "
                "GitHub Secrets > YT_REFRESH_TOKEN'ni yangilang. Xato: "
                + str(e)[:200]
            )
        except HttpError as e:
            last_err = e
            print(f"[yt] urinish {attempt + 1} (HTTP {e.resp.status}): {e}")
            # 401/403 — huquq muammosi, qayta urinish foydasiz
            if e.resp.status in (401, 403):
                break
            time.sleep(8 * (attempt + 1))
        except Exception as e:
            last_err = e
            print(f"[yt] urinish {attempt + 1}: {e}")
            time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"YouTube'ga yuklab bo'lmadi: {last_err}")
