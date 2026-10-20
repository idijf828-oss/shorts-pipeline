"""6-qadam: Telegram bot orqali inson tasdig'i.

Video + inline tugmalar (YUKLASH / BEKOR QILISH).
GitHub Actions statsiz -> job o'zi polling qiladi
(getUpdates), 6 soatlik job limit ichida.
"""
import json
import os
import time

from src.net import session

API = "https://api.telegram.org/bot{token}/{method}"


def _post(token, method, **params):
    r = session().post(API.format(token=token, method=method),
                       data=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {method} {r.status_code}: {r.text[:300]}")
    return r.json()


def send_message(cfg, text):
    try:
        _post(cfg["secrets"]["tg_bot_token"], "sendMessage",
              chat_id=cfg["secrets"]["tg_chat_id"], text=text,
              parse_mode="HTML")
    except Exception as e:
        print(f"[tg] xabar yuborib bo'lmadi: {e}")


def caption(cfg, trends, script, duration_s):
    sm = trends.get("summary", {})
    top = sm.get("top_titles", [])[:3]
    kws = ", ".join(script.get("keywords", [])[:5])
    lines = [
        f"🎬 <b>{script['title']}</b>",
        f"⏱ {duration_s:.0f}s | 7 sahna"
        + (f" | {kws}" if kws else ""),
        "📊 US trend (30 kun):",
    ]
    for t in top:
        lines.append(f"• {t['title'][:80]} — {t['views']:,} views")
    lines += ["", "Tasdiqlaysizmi?"]
    return "\n".join(lines)


def send_video_and_wait(cfg, video_path, text, timeout_min):
    """Video yuboradi va tasdiq callback'ini kutadi.
    True = yuklash, False = bekor/timeout."""
    tok = cfg["secrets"]["tg_bot_token"]
    chat = cfg["secrets"]["tg_chat_id"]
    kb = {"inline_keyboard": [[
        {"text": "✅ YouTube'ga yuklash", "callback_data": "approve"},
        {"text": "❌ Bekor qilish", "callback_data": "reject"},
    ]]}
    with open(video_path, "rb") as f:
        r = session().post(
            API.format(token=tok, method="sendVideo"),
            data={"chat_id": chat, "caption": text,
                  "parse_mode": "HTML"},
            params={"reply_markup": json.dumps(kb)},
            files={"video": (os.path.basename(video_path), f, "video/mp4")},
            timeout=180,
        )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram sendVideo {r.status_code}: {r.text[:300]}")
    msg_id = r.json()["result"]["message_id"]
    print(f"[tg] video yuborildi (msg {msg_id}); tasdiq kutilyapti...")

    offset = None
    deadline = time.time() + timeout_min * 60
    s = session()
    while time.time() < deadline:
        try:
            u = s.get(API.format(token=tok, method="getUpdates"),
                      params={"offset": offset, "timeout": 30}, timeout=45)
            for upd in u.json().get("result", []):
                offset = upd["update_id"] + 1
                cb = upd.get("callback_query")
                if not cb:
                    continue
                if str(cb.get("message", {}).get("message_id")) != str(msg_id):
                    continue
                _post(tok, "answerCallbackQuery",
                      callback_query_id=cb["id"])
                data = cb.get("data")
                print(f"[tg] foydalanuvchi: {data}")
                return data == "approve"
        except Exception as e:
            print(f"[tg] polling xatosi: {e}")
        time.sleep(4)
    print("[tg] vaqt tugadi -> xavfsizlik uchun BEKOR")
    return False
