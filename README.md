# Shorts Pipeline — "Mind-blowing geography & country facts"

To'liq avtomatik YouTube Shorts kanali (geografiya va davlatlar faktlari,
ingliz tilida, professional ovoz bilan). **Barchasi bepul.**

## Ishlash tartibi
GitHub Actions (har kuni UTC 09:00) → trend tahlili (YouTube API) →
Gemini bilan fakt tekshirilgan skript (retention: curiosity gap + like CTA)
→ professional ovoz (en-US-ChristopherNeural, gTTS fallback) →
sintez SFX (riser/whoosh/ding/impact) → Pexels/Pixabay B-roll kliplar
(fallback: rasm kartasi) → ffmpeg montaj (1080x1920, 40-50s, ambient fon
musiqasi + ducking) → Telegram'da inson tasdig'i → YouTube'ga upload
(professional title/description/tags/hashtags, Education kategoriyasi)
→ history.json commit.

## Sozlash
1. Barcha kalitlarni GitHub Secrets'ga qo'shing (qarang wiki/qo'llanma):
   YT_API_KEY, GEMINI_API_KEY, PEXELS_API_KEY yoki PIXABAY_API_KEY,
   TG_BOT_TOKEN, TG_CHAT_ID, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
2. `.github/workflows/daily.yml` → Actions → "Daily Shorts Pipeline" → Run workflow.

## Muhim eslatmalar (2026-10 holati)
- edge-tts 2026-10 dan 403 beradi (Microsoft endpoint o'zgardi) —
  kod avtomatik gTTS'ga o'tadi.
- Pexels yangi API kalitlarini vaqtincha to'xtatgan — Pixabay kaliti
  ishlatishingiz mumkin (ikkisi ham qo'llab-quvvatlanadi).
- YouTube API auditdan o'tmagan loyiha upload'larni private'ga majbur
  qiladi — config'da privacy_status: "private" qoldiring, video'ni
  Studio'dan qo'lda public qiling. Audit formasi:
  https://support.google.com/youtube/contact/yt_api_form
- Tarix (qo'llanilgan mavzular) statsiz bo'lgani uchun workflow
  oxirida history.json repo'ga qayta commit qilinadi.
