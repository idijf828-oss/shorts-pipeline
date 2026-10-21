"""7-qadam: YouTube'ga yuklash (faqat inson tasdig'idan keyin).

OAuth2: refresh token (OAuth Playground orqali olinadi).
Quota: videos.insert = 1 unit / o'z bucket'i (100 ta/kun) —
2026-yilgi yangi granular quota tizimi.

ESLATMA: API loyihasi auditdan o'tmagan bo'lsa, YouTube
video'ni private'ga majbur qiladi (privacyStatus bilan
emas). Shu sababli config'da privacy_status: "private"
deb qoldiring, audit o'tgunacha Studio'dan qo'lda
public qiling.
"""
import time

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def upload(cfg, video_path, title, description, tags):
    sec = cfg["secrets"]
    creds = Credentials(
        token=None,
        refresh_token=sec["yt_refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=sec["yt_client_id"],
        client_secret=sec["yt_client_secret"],
        scopes=SCOPES,
    )
    yt = build("youtube", "v3", credentials=creds,
               cache_discovery=False, static_discovery=True)

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
            print(f"[yt] yuklandi: https://youtu.be/{vid} "
                  f"(privacy: {body['status']['privacyStatus']})")
            return vid
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
