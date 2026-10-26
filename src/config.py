"""Config + secrets yuklagich. Sirlar faqat environment o'zgaruvchilardan (GitHub Secrets)."""
import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path=None):
    path = path or os.path.join(ROOT, "config.yaml")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    sec = {
        "yt_api_key": os.environ.get("YT_API_KEY", ""),
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "pexels_api_key": os.environ.get("PEXELS_API_KEY", ""),
        "pixabay_api_key": os.environ.get("PIXABAY_API_KEY", ""),
        "tg_bot_token": os.environ.get("TG_BOT_TOKEN", ""),
        "tg_chat_id": os.environ.get("TG_CHAT_ID", ""),
        "yt_client_id": os.environ.get("YT_CLIENT_ID", ""),
        "yt_client_secret": os.environ.get("YT_CLIENT_SECRET", ""),
        "yt_refresh_token": os.environ.get("YT_REFRESH_TOKEN", ""),
    }

    missing = [
        k for k in ("yt_api_key", "gemini_api_key", "tg_bot_token", "tg_chat_id",
                    "yt_client_id", "yt_client_secret", "yt_refresh_token")
        if not sec[k]
    ]
    if missing:
        raise RuntimeError(
            "Yetishmayotgan GitHub Secrets: " + ", ".join(missing)
            + " — repo Settings > Secrets and variables > Actions da qo'shing"
        )
    if not sec["pexels_api_key"] and not sec["pixabay_api_key"]:
        raise RuntimeError("PEXELS_API_KEY yoki PIXABAY_API_KEY kerak (ikkisidan biri)")

    cfg["secrets"] = sec
    cfg["_paths"] = {
        "history": os.path.join(ROOT, "history.json"),
        "trends_cache": os.path.join(ROOT, "trends_cache.json"),
        "work": os.path.join(ROOT, "work"),
        "output": os.path.join(ROOT, "output"),
    }
    return cfg
