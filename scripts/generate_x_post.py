# Disabled: this repository runs Pinterest only.
# #!/usr/bin/env python3
# """Posts for the app's own X account.
#
# Once a day Gemini writes POSTS_PER_DAY short posts about Face Slimmer, each in
# a different format (tip, build in public, feature, ...). Each goes to Telegram
# with a button that opens X with the text already filled in: tap, check, Post.
# Spread them over the day - morning, afternoon, evening.
#
# Nothing is posted automatically: X's API bills per request, and new accounts
# posting through it get limited quickly. One tap per post costs nothing.
#
# Links: X shows posts with an external link to far fewer people, so the posts
# carry none. The first post of the day also comes with a tap-to-copy reply
# holding the link, to post as the first reply under your own post.
#
# Recent posts live in the Actions cache (state/x_posts.json) and are shown to
# Gemini so it does not repeat itself.
# """
#
# import html
# import json
# import os
# import time
# from pathlib import Path
# from urllib.parse import quote
#
# from generate_ad import alert, env, gemini, telegram
# from human_text import HUMAN_RULES, retry_note, tells, tidy
#
# STATE_PATH = Path(os.environ.get("X_POSTS_STATE", "state/x_posts.json"))
#
# POSTS_PER_DAY = 3
# X_MAX = 270        # X allows 280; emojis count double, so keep a margin
# KEEP_RECENT = 30
#
# APP_FACTS = (
#     "'Face Slimmer' is a free Android app by a solo developer: a daily "
#     "5-minute routine of face yoga, facial massage and jawline exercises, "
#     "streaks and reminders, habit tracking of water, sleep and salt (what "
#     "actually drives a puffy face) and an AI preview of the face."
# )
#
# # Posts are the developer's own voice, so the honesty rules of the Pinterest
# # copy apply: no fat-loss promises, no invented proof.
# FORBIDDEN = [
#     "lose weight", "weight loss", "burn fat", "fat burning", "fat loss",
#     "guaranteed", "overnight", "in 7 days", "in 30 days", "chubby",
#     "download now", "link in bio",
# ]
#
# FORMATS = {
#     "tip": "One concrete, honest tip for a puffy morning face or a sharper "
#            "jawline: a named face yoga move with reps or seconds, cold water or "
#            "ice, gua sha toward the ears, less salt in the evening, posture. "
#            "End with one short line that the app turns this into a 5-minute "
#            "daily routine.",
#     "build": "Build in public: the solo developer talks about building Face "
#              "Slimmer - a decision, a feature in progress, a mistake, something "
#              "users asked for. First person, honest, a little personal.",
#     "feature": "Spotlight ONE feature and the problem it solves: the daily "
#                "5-minute routine, streaks and reminders, water/sleep/salt "
#                "tracking, or the AI face preview.",
#     "myth": "Bust one common myth (spot fat reduction, 'results in 7 days', "
#             "mewing fixes everything, more reps is better) and say what "
#             "actually helps, tied to how the app approaches it.",
#     "question": "A question that invites replies from women into face yoga, "
#                 "skincare or depuffing (e.g. what they do on a puffy morning), "
#                 "plus one line saying you are building an app for this.",
#     "routine": "'My 5-minute morning face routine' as a short list of 3-4 steps "
#                "with seconds or reps, then one line that it is the routine "
#                "inside the app.",
# }
# ORDER = ["tip", "build", "feature", "myth", "question", "routine"]
# WHEN = ["утром", "днём", "вечером"]
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
# def todays_formats() -> list[str]:
#     forced = os.environ.get("X_FORMAT", "auto").strip()
#     if forced in FORMATS:
#         return [forced]
#     # Three a day, all six every two days.
#     start = int(time.time() // 86400) * POSTS_PER_DAY
#     return [ORDER[(start + i) % len(ORDER)] for i in range(POSTS_PER_DAY)]
#
#
# def post_prompt(formats: list[str], recent: list[str]) -> str:
#     briefs = "\n".join(f'- "{f}": {FORMATS[f]}' for f in formats)
#     avoid = "\n".join(f"- {r}" for r in recent[-15:]) or "- (none yet)"
#     return f"""You write posts for the X (Twitter) account of the solo developer of an app. {APP_FACTS}
#
# Audience: women 20-35 into face yoga, skincare, gua sha, depuffing and glow-ups.
#
# Write one post for each of these formats:
# {briefs}
#
# RULES:
# - English. The developer posting from their own account, not a brand account. Casual X style: lowercase starts are fine, line breaks between thoughts.
# - The first line is the hook and decides everything: a specific claim, a surprising fact, or a relatable moment ("woke up with a puffy face before a date"). Never a generic opener.
# - Each post at most 250 characters including spaces and line breaks.
# - Name "Face Slimmer" exactly once in every post and say it is free (Android) where it fits. The app is the point of the post, but the post must still be useful or interesting without it.
# - No links, no hashtags, no "download now", no "link in bio", no call-to-action slogans. At most 1 emoji, usually none.
# - Honest: spot fat reduction does not exist; exercises tone muscles and help puffiness and posture. Never promise weight or fat loss or fast results.
# - Never invent numbers, download counts, ratings, reviews, testimonials or users' results.
# - Do not repeat the ideas or openings of these recent posts:
# {avoid}
#
# {HUMAN_RULES}
#
# Return ONLY JSON: {{"posts": [{{"format": "tip", "text": "..."}}]}}
# """
#
#
# def problem(text: str) -> str:
#     """Everything wrong with a post, comma-separated; "" when it is fine."""
#     low = text.lower()
#     if not text:
#         return "empty"
#     bad = [w for w in FORBIDDEN if w in low] + tells(text)
#     if len(text) > X_MAX:
#         bad.append(f"over {X_MAX} characters")
#     if "http" in low or "www." in low or ".com" in low:
#         bad.append("a link")
#     if "face slimmer" not in low:
#         bad.append("not naming Face Slimmer")
#     if "#" in text:
#         bad.append("a hashtag")
#     return ", ".join(bad)
#
#
# def write_posts(formats: list[str], recent: list[str]) -> dict[str, str]:
#     """One valid post per format; formats still invalid after 3 tries are dropped."""
#     posts: dict[str, str] = {}
#     issues: list[str] = []
#     for attempt in range(1, 4):
#         missing = [f for f in formats if f not in posts]
#         if not missing:
#             break
#         prompt = post_prompt(missing, recent) + (retry_note(issues) if issues else "")
#         issues = []
#         for p in gemini(prompt).get("posts", []):
#             fmt, text = str(p.get("format", "")), tidy(p.get("text", ""))
#             if fmt not in missing or fmt in posts:
#                 continue
#             issue = problem(text)
#             if issue:
#                 print(f"Attempt {attempt}: {fmt} rejected ({issue}): {text!r}")
#                 issues.append(issue)
#                 continue
#             posts[fmt] = text
#     return posts
#
#
# def link_reply() -> str:
#     site = env("SITE_URL").rstrip("/")
#     return f"Free on Android: {site}/?utm_source=x&utm_medium=social"
#
#
# def send(i: int, n: int, fmt: str, text: str) -> None:
#     when = f" · выложи {WHEN[i]}" if n == len(WHEN) else ""
#     head = f"\U0001f426 Пост для X {i + 1}/{n} · {fmt}{when}"
#     body = f"{html.escape(head)}\n\n<pre>{html.escape(text)}</pre>"
#     if i == 0:
#         body += (
#             "\n\n<b>Первым ответом под этим постом (ссылка)</b>\n"
#             f"<pre>{html.escape(link_reply())}</pre>"
#         )
#     telegram("sendMessage", {
#         "chat_id": env("TELEGRAM_CHAT_ID"),
#         "text": body,
#         "parse_mode": "HTML",
#         "disable_web_page_preview": True,
#         "reply_markup": {"inline_keyboard": [[{
#             "text": "Опубликовать в X (текст уже вставлен)",
#             "url": "https://x.com/intent/post?text=" + quote(text, safe=""),
#         }]]},
#     })
#
#
# def main() -> None:
#     recent = load_recent()
#     formats = todays_formats()
#     print(f"Formats: {formats}")
#     try:
#         posts = write_posts(formats, recent)
#         if not posts:
#             raise RuntimeError("Gemini produced no usable post")
#         ordered = [(f, posts[f]) for f in formats if f in posts]
#         for i, (fmt, text) in enumerate(ordered):
#             send(i, len(ordered), fmt, text)
#             recent.append(text)
#             print(f"Sent {fmt}: {text!r}")
#     except Exception as exc:  # noqa: BLE001
#         alert(f"\U0001f6a8 X posts failed:\n{type(exc).__name__}: {exc}"[:3500])
#         raise
#     # A dry run must not make real runs avoid posts nobody saw.
#     if os.environ.get("DRY_RUN", "").lower() != "true":
#         save_recent(recent)
#
#
# if __name__ == "__main__":
#     main()
