"""Publish pins to Pinterest through RSS feeds on the landing page.

Pinterest's auto-publish reads an RSS feed from a claimed website and turns
each new item into a pin on one board. So every pin is committed to the
landing repo - the image plus an updated feed for its board - and Vercel
serves them at /pins/. One feed per board, because Pinterest maps each feed
to exactly one board.

Everything lands in a single commit through the Git Data API, so each pin
costs one Vercel deploy. The commit is authored with the owner's GitHub
noreply address: Vercel's Hobby plan refuses to deploy commits whose author
it cannot match to the account.
"""

import base64
import json
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

import requests

from pinterest_services import TIMEOUT, env

PINS_DIR = "public/pins"
INDEX_PATH = f"{PINS_DIR}/pins.json"
# Enough history for Pinterest to catch up after a missed day or two; older
# items and their images are pruned so the repo does not grow forever.
KEEP_ITEMS = 60

def commit_author() -> dict:
    return {"name": env("PIN_COMMIT_NAME"), "email": env("PIN_COMMIT_EMAIL")}


def board_slug(board: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", board.lower()).strip("-")


def feed_url(site: str, board: str) -> str:
    return f"{site}/pins/{board_slug(board)}.xml"


class _Repo:
    def __init__(self) -> None:
        self.base = f"https://api.github.com/repos/{env('LANDING_REPO')}"
        self.headers = {
            "Authorization": f"Bearer {env('LANDING_REPO_TOKEN')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def call(self, method: str, path: str, **kw) -> requests.Response:
        resp = requests.request(
            method, f"{self.base}{path}", headers=self.headers, timeout=TIMEOUT, **kw
        )
        if not resp.ok and resp.status_code != 404:
            print(f"GitHub {method} {path}: {resp.status_code} {resp.text[:300]}")
            resp.raise_for_status()
        return resp

    def blob(self, data: bytes) -> str:
        resp = self.call(
            "POST",
            "/git/blobs",
            json={"content": base64.b64encode(data).decode(), "encoding": "base64"},
        )
        return resp.json()["sha"]


def landing_link(site: str, pin_type: str) -> str:
    """Keep every pin destination on the Pinterest-claimed Little Atlas site."""
    return f"{site}/?utm_source=pinterest&utm_medium=social&utm_campaign={pin_type}"


def render_feed(site: str, board: str, items: list[dict]) -> str:
    entries = []
    for it in items:
        image = f"{site}/pins/{it['file']}"
        # Rebuilt from the id rather than read from the index, so pins stored
        # with an older link (the first ones pointed at Play) are fixed too.
        link = landing_link(site, it["id"].rsplit("-", 1)[1])
        entries.append(
            "    <item>\n"
            f"      <title>{escape(it['title'])}</title>\n"
            f"      <link>{escape(link)}</link>\n"
            f"      <description>{escape(it['description'])}</description>\n"
            f"      <guid isPermaLink=\"false\">{escape(it['id'])}</guid>\n"
            f"      <pubDate>{it['pub_date']}</pubDate>\n"
            f"      <enclosure url=\"{escape(image)}\" type=\"image/jpeg\" length=\"{it['size']}\"/>\n"
            f"      <media:content url=\"{escape(image)}\" medium=\"image\" type=\"image/jpeg\" width=\"1000\" height=\"1500\">\n"
            f"        <media:description>{escape(it['alt'])}</media:description>\n"
            "      </media:content>\n"
            "    </item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">\n'
        "  <channel>\n"
        f"    <title>Little Atlas – {escape(board)}</title>\n"
        f"    <link>{site}/</link>\n"
        f"    <description>{escape(board)}: symbolic child profiles, creative mandalas and family keepsakes from Little Atlas.</description>\n"
        "    <language>en</language>\n"
        + "\n".join(entries)
        + "\n  </channel>\n</rss>\n"
    )


def publish(image: bytes, pin_type: str, board: str, copy: dict) -> str:
    """Commit the pin to the landing repo. Returns the board's feed URL."""
    site = env("SITE_URL").rstrip("/")
    commit_author()  # Validate deployment identity before creating any blobs.
    repo = _Repo()

    ref = repo.call("GET", "/git/ref/heads/main").json()
    head = ref["object"]["sha"]
    base_tree = repo.call("GET", f"/git/commits/{head}").json()["tree"]["sha"]

    existing = repo.call("GET", f"/contents/{INDEX_PATH}", params={"ref": head})
    items: list[dict] = (
        json.loads(base64.b64decode(existing.json()["content"]))
        if existing.status_code == 200
        else []
    )

    now = datetime.now(timezone.utc)
    pin_id = f"{now:%Y%m%d-%H%M%S}-{pin_type}"
    item = {
        "id": pin_id,
        "file": f"{pin_id}.jpg",
        "board": board,
        "title": str(copy.get("pin_title", ""))[:100],
        "description": str(copy.get("description", ""))[:500],
        "alt": str(copy.get("alt_text", ""))[:500],
        "link": landing_link(site, pin_type),
        "pub_date": format_datetime(now),
        "size": len(image),
    }
    items.insert(0, item)
    kept, dropped = items[:KEEP_ITEMS], items[KEEP_ITEMS:]

    tree = [
        {"path": f"{PINS_DIR}/{item['file']}", "mode": "100644", "type": "blob",
         "sha": repo.blob(image)},
        {"path": INDEX_PATH, "mode": "100644", "type": "blob",
         "sha": repo.blob(json.dumps(kept, ensure_ascii=False, indent=1).encode())},
    ]
    for board_name in sorted({it["board"] for it in items}):
        board_items = [it for it in kept if it["board"] == board_name]
        tree.append({
            "path": f"{PINS_DIR}/{board_slug(board_name)}.xml",
            "mode": "100644", "type": "blob",
            "sha": repo.blob(render_feed(site, board_name, board_items).encode()),
        })
    for old in dropped:
        tree.append({"path": f"{PINS_DIR}/{old['file']}", "mode": "100644",
                     "type": "blob", "sha": None})

    new_tree = repo.call("POST", "/git/trees", json={"base_tree": base_tree, "tree": tree}).json()["sha"]
    author = {**commit_author(), "date": now.isoformat()}
    commit = repo.call("POST", "/git/commits", json={
        "message": f"Add Pinterest pin: {item['title']}",
        "tree": new_tree,
        "parents": [head],
        "author": author,
        "committer": author,
    }).json()["sha"]
    repo.call("PATCH", "/git/refs/heads/main", json={"sha": commit})
    print(f"Committed pin {pin_id} to the landing repo ({commit[:7]})")
    return feed_url(site, board)
