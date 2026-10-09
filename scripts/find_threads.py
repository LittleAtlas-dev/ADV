# Disabled: this repository runs Pinterest only.
# #!/usr/bin/env python3
# """Find fresh Reddit threads where people ask about face yoga, puffiness,
# double chin and the like, draft a helpful reply with Gemini and send each one
# to Telegram. Posting stays manual: copy the draft, tap the button, paste,
# send. Nothing here ever posts to Reddit or X.
#
# Why not post automatically: both sites ban accounts that auto-comment, and
# Reddit also blacklists the domain being promoted. A human sending a few good
# replies a day is what keeps the account alive.
#
# Ban-safety rules baked in:
# - Drafts never contain links. New accounts with links are auto-removed by
#   AutoModerator in most subreddits; if someone asks, link by hand.
# - Most drafts are plain help with no mention of the app at all. The app is
#   only mentioned when the post asks for an app or tool, never in subreddits
#   known to forbid self-promotion, at most MAX_MENTIONS_PER_DAY times a day,
#   and always with "I made it" disclosure.
# - At most MAX_PER_RUN / MAX_PER_DAY suggestions, and one per subreddit per
#   SUB_COOLDOWN_HOURS, so the account never looks like it is working a list.
#
# Reddit: self-service API keys are gone (approval only), so by default this
# reads the public search RSS feed. If REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET
# are set (after Reddit approves an app), it uses OAuth instead, which also
# returns comment counts and locked/archived flags.
#
# X: its API charges for every post read and scraping it needs a logged-in
# account, so X is not read at all. Once a day a message with X search buttons
# (sorted by Latest) goes out instead; the fresh tweets open in the X app, and
# the reply bot in the landing repo drafts an app-mentioning reply from a link.
# The Reddit rules above stay strict: Reddit bans promo, X mostly does not.
#
# State (already-seen ids, cooldowns, daily counters) lives in a JSON file that
# the workflow carries between runs in the Actions cache.
# """
#
# import html
# import json
# import os
# import sys
# import time
# import xml.etree.ElementTree as ET
# from datetime import datetime, timezone
# from pathlib import Path
# from typing import Any
# from urllib.parse import quote, urlencode
#
# import requests
#
# from generate_ad import TIMEOUT, alert, env, gemini
# from human_text import HUMAN_RULES, retry_note, tells, tidy
#
# STATE_PATH = Path(os.environ.get("THREADS_STATE", "state/threads.json"))
#
# # Reddit search syntax: OR between quoted phrases. Few queries on purpose -
# # unauthenticated RSS gets 429 after a handful of requests.
# REDDIT_QUERIES = [
#     '"face yoga" OR "gua sha" OR "facial massage" OR "face exercises" OR "facial exercises"',
#     '"puffy face" OR "double chin" OR "jawline exercises" OR "face bloating" OR "puffy in the morning"',
# ]
# # X search pages (not the API) - each becomes a button in Telegram. The first
# # finds people looking for an app, where naming ours is the answer itself.
# X_SEARCHES = [
#     ("Ищут приложение", '(app OR apps) ("face yoga" OR jawline OR "double chin" '
#                         'OR "puffy face" OR "face exercises" OR "gua sha")'),
#     ("Face yoga", '"face yoga"'),
#     ("Puffy face", '("puffy face" OR "face is puffy" OR "puffy in the morning")'),
#     ("Double chin", '"double chin" (how OR help OR tips OR exercise)'),
#     ("Jawline / gua sha", '("jawline exercises" OR ("gua sha" routine))'),
# ]
# # No replies, no link posts (usually ads), English only.
# X_FILTERS = "-filter:replies -filter:links lang:en"
#
# # Plain help is fine here, but these subreddits remove anything that looks
# # like promotion. The app is never mentioned in them. Edit freely.
# NO_PROMO_SUBS = {
#     "skincareaddiction", "asianbeauty", "30plusskincare", "makeupaddiction",
#     "beauty", "femalefashionadvice", "loseit", "fitness", "xxfitness",
#     "askdocs", "medical", "dermatology", "tretinoin", "skincare_addiction",
# }
# # Never suggested at all: medical, eating disorders and body image, minors,
# # or off-audience. Pitching a face app there is harmful, not just a ban risk.
# SKIP_SUBS = {
#     "askdocs", "medical", "teenagers", "nsfw", "truerateme", "rateme",
#     "amiugly", "looksmaxxing", "mewing", "orthotropics",
#     "bodydysmorphia", "bdd", "bulimia", "anorexia", "anorexianervosa",
#     "eatingdisorders", "edanonymous", "fuckeatingdisorders", "bingeeatingdisorder",
#     "arfid", "selfesteem", "depression", "mentalhealth", "anxiety", "offmychest",
# }
#
# MAX_AGE_HOURS = 24          # older threads get little traffic
# MAX_COMMENTS = 40           # deeper than this, a new comment is buried
# MIN_SCORE = 7               # Gemini relevance 0-10
# MAX_PER_RUN = 3
# MAX_PER_DAY = 8
# MAX_MENTIONS_PER_DAY = 2
# SUB_COOLDOWN_HOURS = 24
# SEEN_KEEP_DAYS = 7
#
# BROWSER_UA = (
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#     "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
# )
# ATOM = {"a": "http://www.w3.org/2005/Atom"}
#
#
# # --------------------------------------------------------------------------
# # State
# # --------------------------------------------------------------------------
#
# def load_state() -> dict[str, Any]:
#     try:
#         state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
#     except (OSError, ValueError):
#         state = {}
#     state.setdefault("seen", {})
#     state.setdefault("subs", {})
#     state.setdefault("sent", [])
#     return state
#
#
# def save_state(state: dict[str, Any]) -> None:
#     now = time.time()
#     state["seen"] = {k: t for k, t in state["seen"].items()
#                      if now - t < SEEN_KEEP_DAYS * 86400}
#     state["sent"] = [s for s in state["sent"] if now - s["t"] < 86400]
#     STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
#     STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")
#
#
# # --------------------------------------------------------------------------
# # Reddit
# # --------------------------------------------------------------------------
#
# def reddit_oauth_token() -> str | None:
#     cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
#     secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
#     if not (cid and secret):
#         return None
#     resp = requests.post(
#         "https://www.reddit.com/api/v1/access_token",
#         auth=(cid, secret),
#         data={"grant_type": "client_credentials"},
#         headers={"User-Agent": reddit_ua()},
#         timeout=TIMEOUT,
#     )
#     resp.raise_for_status()
#     return resp.json()["access_token"]
#
#
# def reddit_ua() -> str:
#     user = os.environ.get("REDDIT_USERNAME", "").strip() or "faceslimmer"
#     return f"python:faceslimmer-thread-finder:v1.0 (by /u/{user})"
#
#
# def fetch(url: str, headers: dict[str, str]) -> requests.Response | None:
#     """GET with one polite retry on 429. None if still refused."""
#     for attempt in (1, 2):
#         resp = requests.get(url, headers=headers, timeout=TIMEOUT)
#         if resp.status_code == 429 and attempt == 1:
#             time.sleep(30)
#             continue
#         if not resp.ok:
#             print(f"GET {url[:90]}... -> HTTP {resp.status_code}")
#             return None
#         return resp
#     return None
#
#
# def reddit_via_oauth(token: str, query: str) -> list[dict[str, Any]]:
#     url = "https://oauth.reddit.com/search?" + urlencode(
#         {"q": query, "sort": "new", "t": "day", "limit": 50, "type": "link"}
#     )
#     resp = fetch(url, {"Authorization": f"Bearer {token}", "User-Agent": reddit_ua()})
#     if resp is None:
#         return []
#     posts = []
#     for child in resp.json()["data"]["children"]:
#         d = child["data"]
#         if d.get("locked") or d.get("archived") or d.get("over_18"):
#             continue
#         posts.append({
#             "id": d["name"],
#             "source": "reddit",
#             "sub": d["subreddit"],
#             "title": d["title"],
#             "body": d.get("selftext", ""),
#             "url": "https://www.reddit.com" + d["permalink"],
#             "created": d["created_utc"],
#             "comments": d.get("num_comments"),
#         })
#     return posts
#
#
# def reddit_via_rss(query: str) -> list[dict[str, Any]]:
#     url = "https://www.reddit.com/search.rss?" + urlencode(
#         {"q": query, "sort": "new", "t": "day", "limit": 50, "type": "link"}
#     )
#     resp = fetch(url, {"User-Agent": BROWSER_UA})
#     if resp is None:
#         return []
#     posts = []
#     for e in ET.fromstring(resp.content).findall("a:entry", ATOM):
#         cat = e.find("a:category", ATOM)
#         link = e.find("a:link", ATOM)
#         published = e.findtext("a:published", "", ATOM) or e.findtext("a:updated", "", ATOM)
#         # The content is the post rendered as HTML plus a "submitted by" footer.
#         body = html.unescape(e.findtext("a:content", "", ATOM))
#         body = html.unescape(_strip_tags(body)).split("submitted by")[0]
#         posts.append({
#             "id": e.findtext("a:id", "", ATOM),
#             "source": "reddit",
#             "sub": cat.get("term", "") if cat is not None else "",
#             "title": e.findtext("a:title", "", ATOM),
#             "body": body.strip(),
#             "url": link.get("href", "") if link is not None else "",
#             "created": datetime.fromisoformat(published).timestamp() if published else 0,
#             "comments": None,
#         })
#     return posts
#
#
# def _strip_tags(text: str) -> str:
#     out, inside = [], False
#     for ch in text:
#         if ch == "<":
#             inside = True
#         elif ch == ">":
#             inside = False
#             out.append(" ")
#         elif not inside:
#             out.append(ch)
#     return " ".join("".join(out).split())
#
#
# def reddit_posts() -> tuple[list[dict[str, Any]], bool]:
#     """All posts from all queries, and whether any request succeeded."""
#     token = reddit_oauth_token()
#     posts, ok = [], False
#     for i, query in enumerate(REDDIT_QUERIES):
#         if i:
#             time.sleep(5)
#         batch = reddit_via_oauth(token, query) if token else reddit_via_rss(query)
#         ok = ok or bool(batch)
#         posts += batch
#     print(f"Reddit ({'oauth' if token else 'rss'}): {len(posts)} posts")
#     return posts, ok
#
#
# # --------------------------------------------------------------------------
# # X (free: search links, once a day)
# # --------------------------------------------------------------------------
#
# def send_x_links(state: dict[str, Any]) -> None:
#     """Once a UTC day, a message with one button per X search, sorted by
#     Latest. Tapping opens the X app on fresh tweets; replying stays manual."""
#     today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
#     if state.get("x_day") == today:
#         return
#     buttons = [
#         [{"text": label, "url": "https://x.com/search?" + urlencode(
#             {"q": f"{q} {X_FILTERS}", "f": "live"}, quote_via=quote)}]
#         for label, q in X_SEARCHES
#     ]
#     text = ("\U0001f426 X: свежие твиты по теме. Выбери 3-5 и пришли ссылку на "
#             "каждый боту - он напишет ответ с советом и упоминанием Face Slimmer "
#             "и даст кнопку, которая откроет X с готовым текстом.")
#     if os.environ.get("DRY_RUN", "").lower() == "true":
#         print(f"[dry-run] {text}\n" + "\n".join(b[0]["url"] for b in buttons))
#         return
#     telegram_send(text, buttons)
#     state["x_day"] = today
#
#
# # --------------------------------------------------------------------------
# # Filtering and drafting
# # --------------------------------------------------------------------------
#
# def prefilter(posts: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
#     now = time.time()
#     out, ids = [], set()
#     for p in posts:
#         sub = p["sub"].lower()
#         if (not p["id"] or p["id"] in ids or p["id"] in state["seen"]
#                 or sub in SKIP_SUBS
#                 or now - p["created"] > MAX_AGE_HOURS * 3600
#                 or (p["comments"] or 0) > MAX_COMMENTS
#                 or now - state["subs"].get(sub, 0) < SUB_COOLDOWN_HOURS * 3600):
#             continue
#         ids.add(p["id"])
#         out.append(p)
#     return out
#
#
# def draft_prompt(posts: list[dict[str, Any]]) -> str:
#     items = []
#     for p in posts:
#         where = f"r/{p['sub']}"
#         promo = "no" if p["sub"].lower() in NO_PROMO_SUBS else "yes"
#         items.append(
#             f'--- id: {p["id"]}\nwhere: {where}\napp_mention_allowed: {promo}\n'
#             f'title: {p["title"]}\ntext: {p["body"][:900]}'
#         )
#     return f"""You help the solo developer of 'Face Slimmer', a free Android app with daily 5-minute face yoga, facial massage and jawline routines, habit tracking (water, sleep, salt) and an AI preview of the face. The developer answers people online by hand; you pick the threads worth answering and draft the reply.
#
# For each post decide whether a genuinely useful reply is possible and draft it.
#
# Mark relevant=false (and leave reply empty) when:
# - the post is not really about face puffiness, face yoga, facial massage, jawline or double chin;
# - it is a medical issue (sudden or one-sided swelling, allergy, pain, infection, dental problem, medication) - that needs a doctor, not tips;
# - the author seems to be under 18;
# - it touches an eating disorder, body dysmorphia, self-harm, bullying or low self-esteem - never pitch anything to someone in that state;
# - it is a sales post, a spam post, or a meme.
#
# Reply rules:
# - Same language as the post. Sound like a regular redditor who knows the topic, not a brand: no greeting, no sign-off, start straight with the answer or a short relatable line.
# - Answer the actual question first with concrete, honest tips (e.g. cold water or ice, gua sha toward the ears, less salt and alcohol in the evening, sleep, water, posture, specific face yoga moves with reps). Pick the 2-3 tips that fit this post, not a checklist of everything.
# - Be honest: spot fat reduction does not exist, exercises tone muscles and help puffiness and posture. Never promise weight or fat loss or fast results.
# - 40-120 words. Plain paragraphs; a short numbered list only if the steps really are a sequence.
# - No links, no hashtags, no emojis, no "Great question!".
# - mention_app=true ONLY if app_mention_allowed is yes AND the post asks for an app, a tool, a routine to follow or a way to stay consistent. Then end with ONE short, casual sentence naming the app and saying you made it, worded differently every time. The idea, not a template: "I made a free app for this routine, Face Slimmer, but the steps above work fine without it." Otherwise do not mention any app.
#
# {HUMAN_RULES}
#
# "why": one short sentence in Russian explaining why this thread is worth answering.
# "score": 0-10, how likely a helpful reply gets seen and appreciated (fresh, a direct question, few answers so far = high).
#
# Return ONLY JSON: {{"results": [{{"id": "...", "relevant": true, "score": 8, "why": "...", "mention_app": false, "reply": "..."}}]}}
#
# Posts:
# {chr(10).join(items)}
# """
#
#
# def draft(posts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
#     """Drafts by post id. A reply that still sounds like AI gets one rewrite;
#     if the rewrite does too, the thread is dropped rather than sent."""
#     by_id: dict[str, dict[str, Any]] = {}
#     for i in range(0, len(posts), 15):
#         chunk = posts[i:i + 15]
#         for r in gemini(draft_prompt(chunk)).get("results", []):
#             by_id[str(r.get("id"))] = r
#
#     def flagged() -> dict[str, list[str]]:
#         out = {}
#         for pid, r in by_id.items():
#             r["reply"] = tidy(r.get("reply", ""))
#             if r.get("relevant") and tells(r["reply"]):
#                 out[pid] = tells(r["reply"])
#         return out
#
#     bad = flagged()
#     if bad:
#         print(f"Rewriting {len(bad)} AI-sounding drafts: {bad}")
#         redo = [p for p in posts if p["id"] in bad]
#         words = sorted({w for ws in bad.values() for w in ws})
#         for r in gemini(draft_prompt(redo) + retry_note(words)).get("results", []):
#             if str(r.get("id")) in bad:
#                 by_id[str(r.get("id"))] = r
#         for pid in flagged():
#             by_id[pid]["relevant"] = False
#     return by_id
#
#
# def pick(posts, drafts, state):
#     """Best-scored drafts that fit the daily caps, one per subreddit."""
#     sent_today = state["sent"]
#     left = min(MAX_PER_RUN, MAX_PER_DAY - len(sent_today))
#     mentions_left = MAX_MENTIONS_PER_DAY - sum(1 for s in sent_today if s["mention"])
#     chosen, subs = [], set()
#     ranked = sorted(
#         (p for p in posts if p["id"] in drafts),
#         key=lambda p: -int(drafts[p["id"]].get("score") or 0),
#     )
#     for p in ranked:
#         d = drafts[p["id"]]
#         # Trust the text, not the flag: Gemini sometimes names the app anyway.
#         mention = bool(d.get("mention_app")) or "face slimmer" in str(d.get("reply", "")).lower()
#         if (len(chosen) >= left or not d.get("relevant") or not d.get("reply")
#                 or int(d.get("score") or 0) < MIN_SCORE or p["sub"].lower() in subs):
#             continue
#         if mention and (mentions_left <= 0 or p["sub"].lower() in NO_PROMO_SUBS):
#             continue  # its reply names the app; skip rather than send it
#         subs.add(p["sub"].lower())
#         mentions_left -= mention
#         chosen.append((p, d, mention))
#     return chosen
#
#
# # --------------------------------------------------------------------------
# # Telegram
# # --------------------------------------------------------------------------
#
# def telegram_send(text: str, keyboard: list[list[dict[str, str]]]) -> None:
#     chat = os.environ.get("THREADS_CHAT_ID", "").strip() or env("TELEGRAM_CHAT_ID")
#     resp = requests.post(
#         f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage",
#         json={
#             "chat_id": chat,
#             "text": text[:4096],
#             "parse_mode": "HTML",
#             "disable_web_page_preview": True,
#             "reply_markup": {"inline_keyboard": keyboard},
#         },
#         timeout=TIMEOUT,
#     )
#     if not resp.ok:
#         print(f"Telegram failed: {resp.status_code} {resp.text}", file=sys.stderr)
#     resp.raise_for_status()
#
#
# def send(p: dict[str, Any], d: dict[str, Any], mention: bool) -> None:
#     age_h = max(0, int((time.time() - p["created"]) // 3600))
#     reply = str(d["reply"]).strip()
#     comments = f" · \U0001f4ac {p['comments']}" if p["comments"] is not None else ""
#     head = f"\U0001f7e0 r/{p['sub']} · {age_h} ч назад{comments}"
#     button = {"text": "Открыть тред", "url": p["url"]}
#
#     kind = ("\U0001f4f1 упоминает приложение (без ссылки)" if mention
#             else "\U0001f4ac просто помощь, без рекламы")
#     title = p["title"] or p["body"][:200]
#     text = (
#         f"{html.escape(head)}\n<b>{html.escape(title)}</b>\n"
#         f"<i>{html.escape(str(d.get('why', '')))}</i>\n{kind}\n\n"
#         f"<pre>{html.escape(reply)}</pre>"
#     )
#     if os.environ.get("DRY_RUN", "").lower() == "true":
#         print(f"[dry-run]\n{head}\n{title}\n{kind}\n{reply}\n{button['url']}\n")
#         return
#     telegram_send(text, [[button]])
#
#
# def main() -> None:
#     state = load_state()
#     try:
#         send_x_links(state)
#         reddit, reddit_ok = reddit_posts()
#         posts = prefilter(reddit, state)
#         print(f"{len(posts)} candidates after filters")
#
#         if not reddit_ok:
#             # Warn once a day, not every run.
#             if time.time() - state.get("reddit_alert", 0) > 86400:
#                 state["reddit_alert"] = time.time()
#                 alert("⚠️ Thread finder: Reddit refused every request "
#                       "(403/429). The RSS feed may be blocked for GitHub's IPs - "
#                       "see README, 'Thread finder'.")
#
#         if posts and MAX_PER_DAY - len(state["sent"]) > 0:
#             drafts = draft(posts)
#             for p, d, mention in pick(posts, drafts, state):
#                 send(p, d, mention)
#                 state["subs"][p["sub"].lower()] = time.time()
#                 state["sent"].append({"t": time.time(), "mention": mention})
#                 print(f"Sent {p['url']}")
#             # Everything Gemini looked at is done - never judge it twice.
#             for p in posts:
#                 state["seen"][p["id"]] = time.time()
#     except Exception as exc:  # noqa: BLE001
#         alert(f"\U0001f6a8 Thread finder failed:\n{type(exc).__name__}: {exc}"[:3500])
#         raise
#     finally:
#         # A dry run must not use up the day's quota or hide threads.
#         if os.environ.get("DRY_RUN", "").lower() != "true":
#             save_state(state)
#
#
# if __name__ == "__main__":
#     main()
