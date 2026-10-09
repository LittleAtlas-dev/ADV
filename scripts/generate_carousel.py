# Disabled: this repository runs Pinterest only.
# #!/usr/bin/env python3
# """TikTok carousel packs: image prompts plus the post texts, sent to Telegram.
#
# Once a day Gemini plans one photo-mode carousel of SLIDES_MIN-SLIDES_MAX
# slides. Each slide comes as a ready image prompt that already contains the
# exact words to put on the image and the background behind them, so it can be
# pasted as is into an image model that renders text well (Nano Banana, GPT
# image, Ideogram). Then the post title and the description with hashtags.
# Generating the images and posting stay manual.
#
# The carousels are meant for everyone: no recurring person, no gendered
# wording, and backgrounds built from objects, textures and gender-neutral line
# art instead of faces. Useful content first - tips, reasons, myths, routines -
# with one soft mention of the app on the last slide.
#
# Six formats rotate by UTC day, and one visual style per carousel keeps its
# slides looking like a set. Recent hooks live in the Actions cache
# (state/carousels.json) so Gemini does not repeat itself.
# """
#
# import html
# import json
# import os
# import time
# from pathlib import Path
#
# from generate_ad import alert, env, gemini, telegram
# from human_text import HUMAN_RULES, retry_note, tells, tidy
#
# STATE_PATH = Path(os.environ.get("CAROUSEL_STATE", "state/carousels.json"))
#
# SLIDES_MIN, SLIDES_MAX = 5, 6
# HEADLINE_MAX_WORDS = 7
# BODY_MAX_WORDS = 16      # image models misspell long text; keep slides short
# TITLE_MAX = 90           # TikTok photo post title
# KEEP_RECENT = 30
#
# # Same honesty line as the pins and X posts.
# FORBIDDEN = [
#     "lose weight", "weight loss", "burn fat", "fat burning", "fat loss",
#     "face fat", "slim down", "slimming", "before and after", "guaranteed",
#     # "overnight" alone is fine here ("salt holds water overnight"); the
#     # promise is what is banned.
#     "overnight results", "results overnight", "in 7 days", "in 30 days",
#     "chubby", "fat face",
# ]
#
# FORMATS = {
#     "moves": "3-4 face yoga or jawline moves, one per slide: name the move, "
#              "how to do it, reps or seconds.",
#     "reasons": "Reasons the face looks puffy in the morning (salt, alcohol, "
#                "short sleep, sleeping face-down, too little water), one per "
#                "slide with a quick fix.",
#     "myths": "Face yoga and jawline myths vs facts, one per slide. Honest: no "
#              "spot fat reduction; exercises tone muscles, help puffiness and "
#              "posture.",
#     "routine": "A 5-minute morning depuff routine, one step per slide, in "
#                "order, with seconds.",
#     "habits": "Daily habits for a less puffy, more defined face (water, salt, "
#               "sleep, posture, screen time), one per slide.",
#     "mistakes": "Everyday mistakes that make the jawline look softer (phone "
#                 "neck, slouching, mouth breathing, sleeping face-down), one "
#                 "per slide with the fix.",
# }
# ORDER = ["moves", "reasons", "myths", "routine", "habits", "mistakes"]
#
# # One per carousel, repeated in every slide prompt so the set matches.
# STYLES = [
#     "Deep purple to navy gradient background with a soft cyan glow; bold white "
#     "sans-serif headline, light lavender body text; brand-like, modern.",
#     "Warm beige and cream minimal spa aesthetic with soft daylight shadows; "
#     "dark brown bold serif headline, charcoal body text; calm and clean.",
#     "Clean white and pale mint background, clinical and fresh; bold black "
#     "sans-serif headline, dark gray body text; lots of white space.",
#     "Dark charcoal marble texture with subtle gold accents; bold cream "
#     "sans-serif headline, light gray body text; premium and moody.",
# ]
#
# SLIDE_SUFFIX = (
#     "Vertical 9:16, 1080x1920. Text placed in the upper or middle third, "
#     "centered, large and easy to read on a phone, high contrast with the "
#     "background, every word spelled exactly as given, no other text, no "
#     "watermark, no logo. No real people, no faces, no hands with visible "
#     "skin details."
# )
#
#
# def load_recent() -> list[str]:
#     try:
#         return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("recent", [])
#     except (OSError, ValueError):
#         return []
#
#
# def save_recent(recent: list[str]) -> None:
#     STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
#     STATE_PATH.write_text(
#         json.dumps({"recent": recent[-KEEP_RECENT:]}, indent=1), encoding="utf-8"
#     )
#
#
# def todays_plan() -> tuple[str, str]:
#     forced = os.environ.get("CAROUSEL_FORMAT", "auto").strip()
#     day = int(time.time() // 86400)
#     fmt = forced if forced in FORMATS else ORDER[day % len(ORDER)]
#     return fmt, STYLES[day % len(STYLES)]
#
#
# def carousel_prompt(fmt: str, style: str, recent: list[str]) -> str:
#     avoid = "\n".join(f"- {r}" for r in recent[-15:]) or "- (none yet)"
#     return f"""You plan a TikTok photo-mode carousel for a face yoga and depuffing account. The account belongs to the developer of 'Face Slimmer', a free Android app with a daily 5-minute face yoga, massage and jawline routine and water/sleep/salt tracking.
#
# Audience: everyone interested in face yoga, a puffy face, jawline, gua sha or skincare. Keep it neutral: no gendered words (no girls, ladies, guys, bro), no specific person.
#
# Carousel topic: {FORMATS[fmt]}
#
# Structure, {SLIDES_MIN}-{SLIDES_MAX} slides in total:
# - Slide 1: the hook. A specific promise or a surprising fact that makes people swipe (e.g. "Why your face is puffy every morning"). Never generic.
# - Middle slides: one idea per slide, concrete (seconds, reps, times of day).
# - Last slide: "Save this for tomorrow morning" style nudge, plus one short line that the full 5-minute routine is in Face Slimmer, free on Android. No links.
#
# For every slide write:
# - "headline": at most {HEADLINE_MAX_WORDS} words.
# - "body": at most {BODY_MAX_WORDS} words, or "" if the headline says it all.
# - "background": one sentence describing the image behind the text, fitting this slide's idea. Use objects, textures, nature, water, ice, gua sha stones, plants, simple gender-neutral line-art or 3D face outlines. Never a photo of a real person, never a man or a woman.
#
# Visual style for all slides: {style}
#
# Post texts:
# - "title": at most {TITLE_MAX} characters, starts with the search phrase people type (e.g. "face yoga for jawline").
# - "description": 2-3 short sentences using natural search keywords, then a question that invites comments. No hashtags inside it.
# - "hashtags": 5-7 hashtags, niche and neutral (e.g. #faceyoga #jawline #puffyface #depuff #guasha #skincaretips #selfcare), no gendered ones.
#
# Honesty: never promise weight or fat loss or fast results. Never use: {", ".join(FORBIDDEN)}.
#
# Do not repeat the ideas or hooks of these recent carousels:
# {avoid}
#
# {HUMAN_RULES}
#
# Return ONLY JSON: {{"slides": [{{"headline": "...", "body": "...", "background": "..."}}], "title": "...", "description": "...", "hashtags": ["#faceyoga"]}}
# """
#
#
# def problems(c: dict) -> list[str]:
#     bad: list[str] = []
#     slides = c.get("slides") or []
#     if not SLIDES_MIN <= len(slides) <= SLIDES_MAX:
#         bad.append(f"{SLIDES_MIN}-{SLIDES_MAX} slides, not {len(slides)}")
#     words = " ".join(
#         f"{s.get('headline', '')} {s.get('body', '')}" for s in slides
#     ) + f" {c.get('title', '')} {c.get('description', '')}"
#     low = words.lower()
#     bad += [w for w in FORBIDDEN if w in low] + tells(words)
#     for i, s in enumerate(slides, 1):
#         if len(str(s.get("headline", "")).split()) > HEADLINE_MAX_WORDS:
#             bad.append(f"slide {i} headline over {HEADLINE_MAX_WORDS} words")
#         if len(str(s.get("body", "")).split()) > BODY_MAX_WORDS:
#             bad.append(f"slide {i} body over {BODY_MAX_WORDS} words")
#     if len(str(c.get("title", ""))) > TITLE_MAX:
#         bad.append(f"title over {TITLE_MAX} characters")
#     if "face slimmer" not in low:
#         bad.append("last slide must name Face Slimmer")
#     return bad
#
#
# def write_carousel(fmt: str, style: str, recent: list[str]) -> dict:
#     prompt = carousel_prompt(fmt, style, recent)
#     bad: list[str] = []
#     for attempt in range(1, 4):
#         c = gemini(prompt)
#         for s in c.get("slides") or []:
#             s["headline"] = tidy(s.get("headline", ""))
#             s["body"] = tidy(s.get("body", ""))
#         c["title"] = tidy(c.get("title", ""))
#         c["description"] = tidy(c.get("description", ""))
#         bad = problems(c)
#         if not bad:
#             return c
#         print(f"Attempt {attempt} rejected: {bad}")
#         prompt = carousel_prompt(fmt, style, recent) + retry_note(bad)
#     raise RuntimeError(f"Gemini kept writing an unusable carousel: {bad}")
#
#
# def slide_prompt(slide: dict, style: str) -> str:
#     """One self-contained image prompt: background, exact text, style, format."""
#     text = f'Large headline text: "{slide["headline"]}".'
#     if slide.get("body"):
#         text += f' Below it, smaller text: "{slide["body"]}".'
#     return f"{slide['background']} {text} Style: {style} {SLIDE_SUFFIX}"
#
#
# def hashtags(c: dict) -> str:
#     tags = []
#     for t in c.get("hashtags") or []:
#         t = "#" + str(t).strip().lstrip("#").replace(" ", "")
#         if len(t) > 1 and t.lower() not in (x.lower() for x in tags):
#             tags.append(t)
#     return " ".join(tags[:7])
#
#
# def pre(label: str, value: str) -> str:
#     return f"<b>{html.escape(label)}</b>\n<pre>{html.escape(value.strip())}</pre>"
#
#
# def send(fmt: str, c: dict, style: str) -> None:
#     slides = c["slides"]
#     blocks = [
#         pre(f"Слайд {i}" + (" — крючок" if i == 1 else " — финал" if i == len(slides) else ""),
#             slide_prompt(s, style))
#         for i, s in enumerate(slides, 1)
#     ]
#     blocks += [
#         pre("Название", c["title"]),
#         pre("Описание + теги", f"{c['description']}\n\n{hashtags(c)}"),
#     ]
#     head = (f"\U0001f3a0 TikTok карусель · {fmt} · {len(slides)} слайдов\n"
#             "Промпт каждого слайда копируется нажатием. Звук добавь при публикации.")
#
#     # Telegram caps a message at 4096 characters: pack the blocks greedily.
#     messages, current = [], html.escape(head)
#     for block in blocks:
#         if len(current) + 2 + len(block) > 4000:
#             messages.append(current)
#             current = block
#         else:
#             current += "\n\n" + block
#     messages.append(current)
#
#     for text in messages:
#         telegram("sendMessage", {
#             "chat_id": env("TELEGRAM_CHAT_ID"),
#             "text": text,
#             "parse_mode": "HTML",
#             "disable_web_page_preview": True,
#         })
#
#
# def main() -> None:
#     recent = load_recent()
#     fmt, style = todays_plan()
#     print(f"Format: {fmt}")
#     try:
#         c = write_carousel(fmt, style, recent)
#         send(fmt, c, style)
#         recent.append(c["slides"][0]["headline"])
#         print(f"Sent: {c['title']!r}")
#     except Exception as exc:  # noqa: BLE001
#         alert(f"\U0001f6a8 TikTok carousel failed:\n{type(exc).__name__}: {exc}"[:3500])
#         raise
#     # A dry run must not make real runs avoid hooks nobody saw.
#     if os.environ.get("DRY_RUN", "").lower() != "true":
#         save_recent(recent)
#
#
# if __name__ == "__main__":
#     main()
