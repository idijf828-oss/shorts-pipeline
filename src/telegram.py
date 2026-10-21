"""6-qadam: Telegram bot orqali inson tasdig'i.

Video + inline tugmalar (YUKLASH / BEKOR QILISH).
GitHub Actions statsiz -> job o'zi polling qiladi
(getUpdates), 6 soatlik job limit ichida.
"""
import html
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
              chat_id=cfg["secrets"]["tg_chat_id"], text=html.escape(str(text)),
              parse_mode="HTML")
    except Exception as e:
        print(f"[tg] xabar yuborib bo'lmadi: {e}")


def caption(cfg, trends, script, duration_s):
    sm = trends.get("summary", {})
    top = sm.get("top_titles", [])[:3]
    kws = ", ".join(script.get("keywords", [])[:5])
    n_facts = len(script.get("scenes", [])) - 2
    lines = [
        f"🎬 <b>{html.escape(script['title'])}</b>",
        f"⏱ {duration_s:.0f}s | {n_facts} fakt"
        + (f" | {html.escape(kws)}" if kws else ""),
    ]
    if top:
        lines.append("📊 US trend (30 kun):")
    for t in top:
        lines.append(f"• {html.escape(t['title'][:80])} — {t['views']:,} views")
    lines += ["", "Tasdiqlaysizmi?"]
    return "\n".join(lines)


def send_video_and_wait(cfg, video_path, text, timeout_min):
    """Video yuboradi va tasdiq callback'ini kutadi.
    True = yuklash, False = bekor/timeout."""
    tok = cfg["secrets"]["tg_bot_token"]
    chat = cfg["secrets"]["tg_chat_id"]
    # getUpdates webhook bilan bir vaqtda ishlay olmaydi (409 konflikt) —
    # webhook o'rnatilgan bo'lsa olib tashlaymiz (bot faqat polling ishlatadi)
    try:
        _post(tok, "deleteWebhook", drop_pending_updates=False)
    except Exception as e:
        print(f"[tg] deleteWebhook: {e}")
    kb = {"inline_keyboard": [[
        {"text": "✅ YouTube'ga yuklash", "callback_data": "approve"},
        {"text": "❌ Bekor qilish", "callback_data": "reject"},
    ]]}

    def _send_video(cap, parse_html=True):
        data = {"chat_id": chat, "caption": cap,
                "reply_markup": json.dumps(kb)}
        if parse_html:
            data["parse_mode"] = "HTML"
        with open(video_path, "rb") as f:
            return session().post(
                API.format(token=tok, method="sendVideo"),
                data=data,
                files={"video": (os.path.basename(video_path), f, "video/mp4")},
                timeout=180,
            )

    r = _send_video(text)
    # caption'da HTML buzilgan bo'lsa (noodatiy belgilar) — oddiy matn bilan qayta
    if r.status_code != 200 and "can't parse entities" in r.text:
        r = _send_video(html.unescape(text), parse_html=False)
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
                      params={"offset": offset, "timeout": 25,
                              "allowed_updates": json.dumps(["callback_query"])},
                      timeout=40)
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
