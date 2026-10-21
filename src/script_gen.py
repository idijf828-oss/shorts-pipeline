"""2-qadam: Gemini API — retention-first geografiya skripti.

Yangi format (35-40s, 95-110 so'z, 7 sahna):
  1 = HOOK (0-3s): aniq obraz/savol. "Did you know" va umumiy kirish TAQIQ.
  2-6 = FAKTLAR: punchy (≤12 so'z/jumla), eng qiziqisi oxirida.
  7 = LOOP: oxirgi gap ataylab tugallanmaydi — hook bilan halqa yopadi.
Outro / like-subscribe CTA YO'Q (CTA pinned comment'da).

Har sahna JSON'da: voice, on_screen (≤4 so'z), visual_query (ro'yxat),
must_contain (klip tanlash filtri), fallback (map_zoom:Joy), duration_s.
"""
import datetime
import json
import re
import time

from src.net import session

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# 2026-10 holati: gemini-2.5-*/gemini-2.0-flash O'CHIRILGAN (404 qaytaradi).
# Faqat hozirgi TIRIK modellar (barchasi bepul tier'da mavjud):
MODELS = [
    "gemini-3.5-flash-lite",   # tez, arzon (asosiy tanlov)
    "gemini-3.1-flash-lite",   # arzon zaxira
    "gemini-3.8-flash",        # kuchliroq zaxira
    "gemini-3.6-flash",        # oxirgi zaxira
]

SYSTEM = """You are a professional documentary scriptwriter and fact researcher for a
US YouTube Shorts channel about geography, borders and countries (ages 13-40).
Use ONLY well-known, verifiable facts (atlas / encyclopedia level) — never
invent statistics, borders or records. Tone: cinematic, confident, conversational
American English. You write for RETENTION: concrete images, zero filler."""


def _call(key, model, prompt, cfg, timeout=90):
    s = session()
    for attempt in range(3):
        try:
            r = s.post(
                API.format(model=model),
                params={"key": key},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                        "temperature": cfg["gemini"].get("temperature", 0.8),
                    },
                },
                timeout=timeout,
            )
            if r.status_code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
            data = r.json()
            cands = data.get("candidates") or []
            if not cands or not (cands[0].get("content") or {}).get("parts"):
                reason = ((cands[0].get("finishReason") if cands else None)
                          or data.get("promptFeedback", {}).get("blockReason", "?"))
                raise RuntimeError(f"Gemini javob bo'sh (finishReason={reason})")
            txt = "".join(p.get("text", "") for p in cands[0]["content"]["parts"])
            return txt
        except RuntimeError:
            raise
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Gemini bilan bog'lanib bo'lmadi: {e}")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("Gemini javob bermadi")


def _build_prompt(cfg, trends, history_kws, avoid_title=""):
    ch = cfg["channel"]
    sm = trends.get("summary", {})
    top_titles = "\n".join(
        f"- {t['title']} ({t['views']:,} views)" for t in sm.get("top_titles", [])[:8]
    )
    hist = ", ".join(history_kws[-25:]) if history_kws else "(hech narsa — birinchi video)"
    avoid = (f"\nAVOID this exact topic too (already generated today): {avoid_title}\n"
             if avoid_title else "")
    # Kun mavzusi: deterministik (har kuni boshqa mavzu, takrorlanmasin)
    topics = ch["topics"]
    yday = datetime.datetime.now(datetime.UTC).timetuple().tm_yday
    topic = topics[yday % len(topics)]
    return f"""Channel niche: {ch['niche']} — geography & country facts.
TODAY'S ASSIGNED TOPIC: "{topic}".
Audience: USA, English, ages 13-40.

WHAT IS TRENDING IN THIS NICHE (US, last {cfg['sources']['days_back']} days):
{top_titles}
Most-used words: {', '.join(sm.get('top_words', [])[:10])}

ALREADY-USED TOPICS (do NOT repeat):
{hist}
{avoid}
WRITE A 7-SCENE SHORTS SCRIPT about "{topic}" (fact-checked).

FORMAT (retention-first, built for watch-to-the-end and replays):
- Scene 1 (HOOK, 0-3 s, ~10-11 words): ONE concrete image or question that
  opens a loop. FORBIDDEN: "Did you know", "Top 5", "Welcome back",
  any generic channel intro. Start mid-action.
- Scenes 2-6 (FACTS, ~12-15 words each): escalate interest scene by scene;
  the single strongest fact is scene 6 ("But number one?" style payoff
  is allowed). Punchy sentences, max 12 words each.
- Scene 7 (LOOP, ~10-13 words): closing line is deliberately UNFINISHED and
  circles back to the hook (e.g. "...one step through the next door...")
  so a replay closes the loop. NO outro, NO "like and subscribe",
  NO "comment below" anywhere in the narration.

Rules:
- Total narration 95-110 words (35-40 seconds spoken).
- voice: plain spoken English, one or two short sentences per scene.
- on_screen: 2-4 words, ALL CAPS, plain letters/numbers only, NO emojis.
- visual_query: 2-3 DIFFERENT stock-footage searches (2-4 words each),
  concrete REAL footage (streets, doors, maps, aerials, buildings).
  No 3D renders, no green screen, no people close-ups, no logos.
- must_contain: 2-4 lowercase words; a clip is accepted only if its
  title/tags contain at least one of them (e.g. ["street","town","door"]).
- fallback: "map_zoom:<Place>" used if no clip matches.
- duration_s: planned seconds (hook ~3, facts ~5-6, loop ~3).

Title style (pick ONE approach, under 70 chars, max 1 emoji):
"This Door Is in Two Countries", "The Island That Changes Country Every 6 Months",
"A Library Where You Stand in Two Countries" — a concrete image + a curiosity gap.

Description template (follow EXACTLY):
Line 1 = the hook sentence.
Then 2 short fact sentences.
Then: "Which {topic} should I cover next? Comment below 👇"
Then: "New geography fact every day."
Plain text, NO hashtags inside (they are added automatically).

Return ONLY this JSON, nothing else:
{{"title": "...", "keywords": ["3-6 keywords"], "tags": ["12-15 lowercase tags"],
 "hashtags": ["shorts","geography","<topic tag>"],
 "description": "...", "pinned_comment": "Which {topic} should I cover next? 👇",
 "scenes": [
  {{"id": 1, "type": "hook", "voice": "...", "on_screen": "...",
    "visual_query": ["...", "..."], "must_contain": ["..."],
    "fallback": "map_zoom:...", "duration_s": 3}},
  {{"id": 2, "type": "fact", "voice": "...", "on_screen": "...",
    "visual_query": ["...", "..."], "must_contain": ["..."],
    "fallback": "map_zoom:...", "duration_s": 6}},
  ... scenes 3, 4, 5, 6 (type "fact") ...
  {{"id": 7, "type": "loop", "voice": "...", "on_screen": "...",
    "visual_query": ["..."], "must_contain": ["..."],
    "fallback": "map_zoom:...", "duration_s": 3}}
 ]}}"""


def _as_list(v):
    if isinstance(v, str):
        return [v]
    return list(v or [])


def _parse(raw):
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    # JSON'dan oldin/keyin ortiqcha matn bo'lsa, { ... } blokini kesib olish
    a, b = txt.find("{"), txt.rfind("}")
    if a != -1 and b > a and (a > 0 or b < len(txt) - 1):
        txt = txt[a:b + 1]
    data = json.loads(txt)
    scenes = data.get("scenes", [])
    if len(scenes) != 7:
        raise ValueError(f"7 sahna kerak (hook+5 fakt+loop), {len(scenes)} ta keldi")
    types = [str(sc.get("type", "")).lower() for sc in scenes]
    if types[0] != "hook" or types[-1] != "loop":
        raise ValueError("1-sahna 'hook', oxirgisi 'loop' bo'lishi kerak")
    for sc in scenes:
        if not sc.get("voice"):
            raise ValueError("bo'sh voice")
        sc.setdefault("on_screen", "")
        vq = _as_list(sc.get("visual_query") or sc.get("pexels_query"))
        sc["visual_query"] = [str(q).strip() for q in vq if str(q).strip()][:4] \
            or ["aerial landscape"]
        mc = _as_list(sc.get("must_contain"))
        sc["must_contain"] = [str(m).strip().lower() for m in mc if str(m).strip()][:5]
        sc.setdefault("fallback", "")
        try:
            sc["duration_s"] = float(sc.get("duration_s") or 0)
        except (TypeError, ValueError):
            sc["duration_s"] = 0.0
    data["title"] = str(data.get("title", "Geography Facts That Break Your Brain"))[:100]
    data["keywords"] = [str(k) for k in data.get("keywords", [])][:8]
    data["description"] = str(data.get("description", "")).strip()[:4500]
    data["tags"] = [str(t).strip().lower() for t in data.get("tags", [])
                    if str(t).strip()][:20]
    data["hashtags"] = [re.sub(r"^#", "", str(h).strip()).lower()
                        for h in _as_list(data.get("hashtags"))
                        if str(h).strip()][:4]
    data["pinned_comment"] = str(data.get("pinned_comment", "")).strip()[:200]
    return data


def write_script(cfg, trends, history_kws, avoid_title=""):
    key = cfg["secrets"]["gemini_api_key"]
    primary = cfg["gemini"].get("model", MODELS[0])
    models = [primary] + [m for m in MODELS if m != primary]
    prompt = _build_prompt(cfg, trends, history_kws, avoid_title)
    last_err = None
    for model in models:
        for attempt in range(2):
            try:
                raw = _call(key, model, prompt, cfg)
                return _parse(raw)
            except Exception as e:
                last_err = e
                print(f"[script] {model} urinish {attempt + 1}: {e}")
                # model topilmadi/o'chirilgan -> qayta urinmasdan keyingisiga
                if "not found" in str(e).lower() or "not_found" in str(e).lower():
                    break
                time.sleep(2)
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
