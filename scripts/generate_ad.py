# Disabled: this repository runs Pinterest only.
# #!/usr/bin/env python3
# """Daily ad generation - a direct port of the n8n workflow
# "Ad generation ROTATION (AI + Template)".
#
# Alternates day by day between two formats, same as the Format Alternator node:
#   format 1 - an AI subway "review" banner rendered by Kie (nano-banana-2-lite)
#   format 2 - a "two faces" dialogue meme rendered by APITemplate
#
# Both post the finished image plus caption to the Telegram queue.
#
# Every secret comes from the environment; nothing is hardcoded. See README.md
# for the list of GitHub Secrets to set.
# """
#
# import json
# import os
# import re
# import sys
# import time
# from typing import Any
#
# import requests
#
# GEMINI_URL = (
#     "https://generativelanguage.googleapis.com/v1beta/models"
#     "/gemini-2.5-flash:generateContent"
# )
# KIE_CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
# KIE_RECORD_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
# APITEMPLATE_URL = "https://rest.apitemplate.io/v2/create-image"
#
# # The n8n version polled twice, 40s apart, then gave up. 2K images regularly
# # take longer than 80s, which is how a job that would have succeeded still
# # reports "Banner generation failed". A real sleep loop costs nothing here.
# # Kie has been seen taking 571s on a task that then succeeded - after the old
# # 20 x 15s = 300s budget had already given up on it, so the image was paid for
# # and thrown away. 60 x 15s covers fifteen minutes.
# POLL_ATTEMPTS = 60
# POLL_INTERVAL = 15
# # A Kie task that comes back state=fail is usually a transient model
# # hiccup, so start a fresh task instead of giving up on the whole run.
# KIE_TASK_ATTEMPTS = 3
# KIE_RETRY_DELAY = 20
# # Hard ceiling for all attempts together. Three full polls would take 45
# # minutes and the workflow (timeout-minutes: 30) would be killed before the
# # Telegram alert ever went out.
# KIE_TOTAL_BUDGET = 20 * 60
#
# # Gemini answers 503 Service Unavailable now and then under load. Two daily
# # runs in a row died on it before the first retry was even attempted.
# GEMINI_ATTEMPTS = 5
# GEMINI_BACKOFF = [5, 10, 20, 40]
#
# BUBBLE_MAX = 135
#
# # The ads target women only: the face yoga / gua sha / depuffing vocabulary
# # converts, and mixing in the looksmaxxing crowd's words (#mog, #sigma) made
# # posts read as written for nobody.
# TAGS_CORE = (
#     "jawline, glowup, jawline exercise, facial fitness, double chin, "
#     "self improvement, transformation, fyp, viral"
# )
# TAGS_FEM = (
#     "face yoga, facial massage, gua sha, face sculpting, snatched jawline, "
#     "cheekbones, depuffing, puffy face, buccal fat, beauty, skincare, self care, "
#     "glow up girl, faceyoga"
# )
#
#
# def tag_rules() -> str:
#     return f'''Core tags: {TAGS_CORE}.
# Audience tags (women): {TAGS_FEM}.
# - "tags": about 17 comma-separated keywords, no # symbol. Take at least 6 from each list; the rest may be close variants. Always include: jawline, glowup, face yoga.
# - Hashtags in "caption": 4-6, all taken from the two lists above, written as one word each.'''
#
#
# TIMEOUT = 60
#
#
# def env(name: str, *, required: bool = True) -> str:
#     value = os.environ.get(name, "").strip()
#     if required and not value:
#         sys.exit(f"Missing required environment variable: {name}")
#     return value
#
#
# def gemini(prompt: str) -> dict[str, Any]:
#     """Call Gemini and parse the JSON object it returns.
#
#     Retries transient failures - 429, any 5xx, or no response at all - with
#     backoff. A 4xx other than 429 is a real problem (bad key, bad request) and
#     is raised immediately rather than hammered.
#
#     An answer that is not valid JSON is asked for again right away: longer
#     answers (the TikTok carousels) now and then come back with a stray quote
#     inside a string, and a fresh sample is almost always clean.
#     """
#     last: Exception | None = None
#     for attempt in range(1, GEMINI_ATTEMPTS + 1):
#         try:
#             return _gemini_json(prompt)
#         except (json.JSONDecodeError, KeyError, IndexError) as exc:
#             last = exc
#             print(f"Gemini attempt {attempt}/{GEMINI_ATTEMPTS}: unusable answer ({exc})")
#     raise RuntimeError(f"Gemini gave no valid JSON after {GEMINI_ATTEMPTS} attempts: {last}")
#
#
# def _gemini_json(prompt: str) -> dict[str, Any]:
#     """One answer from Gemini, parsed; network retries happen in here."""
#     last: Exception | None = None
#     for attempt in range(1, GEMINI_ATTEMPTS + 1):
#         try:
#             resp = requests.post(
#                 GEMINI_URL,
#                 headers={
#                     "x-goog-api-key": env("GEMINI_API_KEY"),
#                     "Content-Type": "application/json",
#                 },
#                 json={
#                     "contents": [{"parts": [{"text": prompt}]}],
#                     "generationConfig": {
#                         "temperature": 1.0,
#                         "responseMimeType": "application/json",
#                     },
#                 },
#                 timeout=TIMEOUT,
#             )
#         except requests.RequestException as exc:
#             last = exc
#             print(f"Gemini attempt {attempt}/{GEMINI_ATTEMPTS}: {exc}")
#         else:
#             if resp.status_code == 429 or resp.status_code >= 500:
#                 last = requests.HTTPError(
#                     f"{resp.status_code} {resp.reason}", response=resp
#                 )
#                 print(f"Gemini attempt {attempt}/{GEMINI_ATTEMPTS}: HTTP {resp.status_code}")
#             else:
#                 resp.raise_for_status()
#                 break
#         if attempt < GEMINI_ATTEMPTS:
#             time.sleep(GEMINI_BACKOFF[min(attempt - 1, len(GEMINI_BACKOFF) - 1)])
#     else:
#         raise RuntimeError(f"Gemini unavailable after {GEMINI_ATTEMPTS} attempts: {last}")
#
#     raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
#     # responseMimeType usually prevents code fences, but the n8n nodes stripped
#     # them defensively and so do we.
#     return json.loads(re.sub(r"```json|```", "", raw).strip())
#
#
# def telegram(method: str, payload: dict[str, Any]) -> None:
#     if os.environ.get("DRY_RUN", "").lower() == "true":
#         print(f"[dry-run] telegram.{method}: {json.dumps(payload, ensure_ascii=False)}")
#         return
#     token = env("TELEGRAM_BOT_TOKEN")
#     resp = requests.post(
#         f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=TIMEOUT
#     )
#     if not resp.ok:
#         print(
#             f"Telegram {method} failed: {resp.status_code} {resp.text}", file=sys.stderr
#         )
#     resp.raise_for_status()
#
#
# def ad_fields(idea: dict[str, Any]) -> list[tuple[str, str]]:
#     """The texts posted with an ad, each copied separately in Telegram."""
#     return [
#         ("YouTube title", str(idea.get("title", ""))),
#         ("TikTok / YouTube description", str(idea.get("caption", ""))),
#         ("YouTube tags", str(idea.get("tags", ""))),
#     ]
#
#
# def alert(text: str) -> None:
#     """Best-effort failure notice - never masks the original error."""
#     try:
#         telegram("sendMessage", {"chat_id": env("TELEGRAM_CHAT_ID"), "text": text})
#     except Exception as exc:  # noqa: BLE001
#         print(f"Could not send the failure alert: {exc}", file=sys.stderr)
#
#
# # --------------------------------------------------------------------------
# # Format 1 - AI subway banner
# # --------------------------------------------------------------------------
#
# def banner_prompt() -> str:
#     # The review itself stays unisex - no he/she, a name that fits anyone -
#     # while the caption and tags speak to women.
#     who = "someone in their twenties; do not reveal their gender"
#     signature = "'- Alex, 24' or '- Sam, 26' (any gender-neutral first name)"
#     payoff = "compliments, confidence and loving their photos again"
#     return f"""You are a marketer for the app 'Face Slimmer' (an AI app that removes face fat and puffiness and sharpens the cheekbones and jawline). Write content for a subway-style 'review' promo banner.
#
# STRICT RULES:
# - English only. Sounds like a real person, no absurd or surreal jokes.
# - A POSITIVE 5-star review.
# - The reviewer is {who}. Write in their voice, with no gendered words.
# - Idea: the person removed face fat, looks better, and because of that got {payoff}.
# - The review is SHORT - maximum 8 words.
#
# Return ONLY valid JSON, no explanations, with fields:
# 1. "review_text": short 5-star review (max 8 words).
# 2. "reviewer_name": author signature, e.g. {signature}.
# 3. "ui_metrics": a metrics string, e.g. 'Jawline definition: +45%, Puffiness: -80%'.
# 4. "caption": a TikTok caption/description with hashtags (see tag rules below).
# 5. "title": a short catchy video title for YouTube (max 70 chars, no hashtags).
# 6. "tags": see tag rules below.
#
# """ + tag_rules()
#
#
# def kie_image_prompt(review_text: str, reviewer_name: str) -> str:
#     return (
#         "Realistic close-up photo of a black rectangular advertisement banner "
#         "mounted inside a modern subway train car, dark near-black background. "
#         f"In the center, large bold white English text reads exactly: «{review_text}». "
#         "Directly under it, a horizontal row of exactly FIVE golden five-pointed "
#         "stars, all fully filled and glowing. Below the stars, smaller white "
#         f"English text reads exactly: «{reviewer_name}». Near the top, small white "
#         "text that says Face Slimmer - text only, no app icon, no logo, no "
#         "emblem. Two elegant white laurel wreaths frame the review on the "
#         "left and right. Clean modern western advertising design, all text "
#         "spelled perfectly in English, sharp typography, cinematic realistic "
#         "lighting, shot on iPhone, highly detailed, vertical 9:16. No logos or "
#         "icons anywhere."
#     )
#
#
# def kie_extract_url(data: dict[str, Any]) -> str:
#     """Pull the first result URL out of a recordInfo payload."""
#     result = data.get("resultJson")
#     if not result:
#         return ""
#     try:
#         parsed = json.loads(result) if isinstance(result, str) else result
#     except (TypeError, ValueError):
#         return ""
#     urls = parsed.get("resultUrls")
#     return urls[0] if isinstance(urls, list) and urls else ""
#
#
# def _kie_create(prompt: str, aspect_ratio: str, kie_key: str) -> str:
#     """Start one Kie task and return its id."""
#     created = requests.post(
#         KIE_CREATE_URL,
#         headers={
#             "Authorization": f"Bearer {kie_key}",
#             "Content-Type": "application/json",
#         },
#         json={
#             "model": "nano-banana-2-lite",
#             "input": {
#                 "prompt": prompt,
#                 "aspect_ratio": aspect_ratio,
#                 "resolution": "2K",
#                 "output_format": "jpg",
#             },
#         },
#         timeout=TIMEOUT,
#     )
#     created.raise_for_status()
#     task_id = created.json().get("data", {}).get("taskId")
#     if not task_id:
#         raise RuntimeError(f"Kie returned no taskId: {created.text}")
#     return task_id
#
#
# def _kie_poll(task_id: str, kie_key: str, deadline: float) -> tuple[str, str]:
#     """Poll one task until it has an image, fails, or runs out of time."""
#     image_url, state = "", "unknown"
#     for attempt in range(1, POLL_ATTEMPTS + 1):
#         if time.monotonic() >= deadline:
#             print("  time budget spent, abandoning this task")
#             break
#         time.sleep(POLL_INTERVAL)
#         poll = requests.get(
#             KIE_RECORD_URL,
#             headers={"Authorization": f"Bearer {kie_key}"},
#             params={"taskId": task_id},
#             timeout=TIMEOUT,
#         )
#         poll.raise_for_status()
#         data = poll.json().get("data") or {}
#         state = data.get("state", "unknown")
#         image_url = kie_extract_url(data)
#         print(f"  attempt {attempt}/{POLL_ATTEMPTS}: state={state}")
#         if image_url or state == "fail":
#             break
#     return image_url, state
#
#
# def kie_generate(prompt: str, *, aspect_ratio: str, what: str) -> str:
#     """Render one image on Kie and return its URL, polling until it is ready.
#
#     A failed task, a 5xx or an unreachable Kie is retried with a brand new
#     task. A 4xx is not: the request itself is wrong (an aspect ratio the model
#     refuses, say), retrying cannot help, and generate_pin.py relies on it
#     propagating so it can fall back to another ratio.
#
#     Alerts Telegram and raises once every attempt is used up.
#     """
#     kie_key = env("KIE_API_KEY")
#     state, task_id, reason = "unknown", "", "unknown"
#     deadline = time.monotonic() + KIE_TOTAL_BUDGET
#     tries = 0
#
#     for attempt in range(1, KIE_TASK_ATTEMPTS + 1):
#         if time.monotonic() >= deadline:
#             reason = "time budget spent"
#             print(f"Kie: {reason}, giving up after {tries} tries")
#             break
#         tries = attempt
#         try:
#             task_id = _kie_create(prompt, aspect_ratio, kie_key)
#             print(
#                 f"Kie task {task_id} created "
#                 f"(try {attempt}/{KIE_TASK_ATTEMPTS}), polling..."
#             )
#             image_url, state = _kie_poll(task_id, kie_key, deadline)
#             if image_url:
#                 return image_url
#             reason = f"state={state}"
#         except requests.HTTPError as exc:
#             status = exc.response.status_code if exc.response is not None else 0
#             if status < 500:
#                 raise
#             reason = f"HTTP {status}"
#         except requests.RequestException as exc:
#             reason = f"{type(exc).__name__}: {exc}"
#         except RuntimeError as exc:  # malformed create response
#             reason = str(exc)
#
#         if attempt < KIE_TASK_ATTEMPTS:
#             print(f"Kie try {attempt} failed ({reason}), retrying in {KIE_RETRY_DELAY}s")
#             time.sleep(KIE_RETRY_DELAY)
#         else:
#             print(f"Kie try {attempt} failed ({reason}), giving up")
#
#     alert(
#         f"\U0001f6a8 {what} generation failed after {tries} tries.\n"
#         f"Last: {reason}\nTask: {task_id}"
#     )
#     raise RuntimeError(
#         f"Kie produced no image after {tries} tries "
#         f"(last {reason}, task {task_id})"
#     )
#
#
# def run_banner() -> None:
#     idea = gemini(banner_prompt())
#     print(f"Idea: {idea.get('review_text')!r} / {idea.get('reviewer_name')!r}")
#
#     image_url = kie_generate(
#         kie_image_prompt(idea.get("review_text", ""), idea.get("reviewer_name", "")),
#         aspect_ratio="9:16",
#         what="Banner",
#     )
#
#     import social_media  # imports this module; deferred to avoid a cycle
#     social_media.send(image_url, ad_fields(idea), "banner")
#     print(f"Posted banner: {image_url}")
#
#
# # --------------------------------------------------------------------------
# # Format 2 - dialogue meme
# # --------------------------------------------------------------------------
#
# def dialogue_prompt() -> str:
#     speakers = "two young women"
#     examples = "I actually love my selfies now / everyone asks what I changed / I stopped hiding my chin / I feel so much more confident"
#     return f"""You are a marketer for the app 'Face Slimmer' (removes face fat and puffiness, sharpens the cheekbones and jawline). Write a short viral 2-line dialogue for a 'two faces' meme image (one chubby/puffy face vs one sharp, attractive face).
#
# RULES:
# - English only, natural and relatable, no absurd or surreal jokes.
# - The two speakers are {speakers}. Write in their voice.
# - Line 1 (the person with the fuller/puffier face): envy/desire, wants a sharp defined face like the other person.
# - Line 2 (the person with the attractive face): recommends 'Face Slimmer', says they got the result with its workouts, and ends with a BENEFIT that is DIFFERENT EVERY TIME (e.g. {examples}).
# - CRITICAL: each line MUST be at most 135 characters INCLUDING spaces so it fits inside a speech bubble. Keep them punchy.
#
# Return ONLY valid JSON, no explanations, with fields:
# 1. "bubble_fat": line 1 (max 135 characters).
# 2. "bubble_fit": line 2 (max 135 characters).
# 3. "caption": a catchy TikTok caption/description with hashtags (see tag rules below).
# 4. "title": a short catchy YouTube video title (max 70 chars, no hashtags).
# 5. "tags": see tag rules below.
#
# """ + tag_rules()
#
#
# def cap(text: Any) -> str:
#     text = str(text or "").strip()
#     return text if len(text) <= BUBBLE_MAX else text[: BUBBLE_MAX - 1].rstrip() + "…"
#
#
# def run_dialogue() -> None:
#     idea = gemini(dialogue_prompt())
#     bubble_fat, bubble_fit = cap(idea.get("bubble_fat")), cap(idea.get("bubble_fit"))
#     print(f"Bubbles: {bubble_fat!r} / {bubble_fit!r}")
#
#     rendered = requests.post(
#         APITEMPLATE_URL,
#         headers={
#             "X-API-KEY": env("APITEMPLATE_API_KEY"),
#             "Content-Type": "application/json",
#         },
#         params={"template_id": env("APITEMPLATE_TEMPLATE_ID")},
#         json={
#             "overrides": [
#                 {"name": "bubble_fat", "text": bubble_fat},
#                 {"name": "bubble_fit", "text": bubble_fit},
#             ]
#         },
#         timeout=TIMEOUT,
#     )
#     rendered.raise_for_status()
#     download_url = rendered.json().get("download_url")
#     if not download_url:
#         alert(f"\U0001f6a8 Dialogue render failed.\n{rendered.text[:300]}")
#         raise RuntimeError(f"APITemplate returned no download_url: {rendered.text}")
#
#     import social_media  # imports this module; deferred to avoid a cycle
#     social_media.send(download_url, ad_fields(idea), "dialogue")
#     print(f"Posted dialogue: {download_url}")
#
#
# def main() -> None:
#     day = int(time.time() // 86400)
#
#     forced = os.environ.get("FORCE_FORMAT", "auto").strip()
#     if forced in ("1", "2"):
#         fmt = int(forced)
#     else:
#         # Same rule as the n8n Format Alternator: even UTC day -> 1, odd -> 2.
#         fmt = (day % 2) + 1
#     label = "banner" if fmt == 1 else "dialogue"
#
#     print(f"Format {fmt} ({label})")
#
#     try:
#         if fmt == 1:
#             run_banner()
#         else:
#             run_dialogue()
#     except Exception as exc:  # noqa: BLE001
#         # Best effort, then re-raise so the Actions run still goes red.
#         alert(f"\U0001f6a8 Daily ad ({label}) failed:\n{type(exc).__name__}: {exc}"[:3500])
#         raise
#
#
# if __name__ == "__main__":
#     main()
