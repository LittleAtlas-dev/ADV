#!/usr/bin/env python3
"""Pinterest pin generation.

One pin per run: Gemini writes the copy, Kie renders a 2:3 photo with no text
on it, and the title is drawn on top here with Pillow - image models misspell
text, and a template service would need its own 2:3 template.

Each pin is committed to the landing page's RSS feeds, which Pinterest
auto-publishes (see pin_feed.py); Telegram only hears about failures.
Without LANDING_REPO_TOKEN (or on a dry run) the pin goes to Telegram instead,
to be posted by hand.

Pinterest cuts reach for weight-loss content and bans it in ads, so the copy
is about face yoga, massage, habits and posture - never "burn fat" or
before/after. The generated text is checked for those words and regenerated
if they slip in.
"""

import html
import io
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import pin_feed
from pinterest_services import TIMEOUT, alert, env, gemini, kie_generate
from human_text import HUMAN_RULES, retry_note, tells, tidy
from pinterest_text import copyable

PIN_W, PIN_H = 1000, 1500
FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "Outfit.ttf"

PLAY_URL = "https://play.google.com/store/apps/details?id=com.faceslimmer.app"

# Words that get a pin down-ranked on Pinterest or contradict what the app can
# honestly promise. Checked case-insensitively against everything Gemini writes.
FORBIDDEN = [
    "lose weight", "weight loss", "burn fat", "fat burning", "face fat",
    "slim down", "slimming", "before and after", "before/after", "guaranteed",
    "in 7 days", "in 30 days", "overnight", "fat face", "chubby",
]

# Suffix shared by every image prompt: format, empty space for the title, and
# no text from the model.
IMAGE_SUFFIX = (
    " Vertical 2:3 composition. The top third of the image is calm, uncluttered "
    "background with no objects or faces, leaving room for a title. Photorealistic, "
    "high detail, soft natural light. No text, no letters, no numbers, no logos, "
    "no watermark."
)

PIN_TYPES = {
    "exercise": {
        "board": "Face Yoga Exercises",
        "brief": "A step-by-step face yoga or jawline exercise (3 moves or fewer) "
                 "someone can do in 5 minutes. Name each move and give reps or seconds.",
        "scene": "A calm young woman in her twenties doing a face yoga exercise with "
                 "her fingertips on the face or jaw, eyes relaxed, shot from the "
                 "chest up, clean minimal home interior.",
    },
    "depuff": {
        "board": "Morning Depuff Routine",
        "brief": "A quick morning routine against a puffy face: cold water or ice, "
                 "gua sha toward the ears, water, less salt the evening before.",
        "scene": "A flat lay from above of a morning skincare and depuff setup: gua "
                 "sha stone, ice, a glass of water, a towel, a plant, on a soft "
                 "light surface, objects in the lower two thirds only.",
    },
    "habits": {
        "board": "Healthy Face Habits",
        "brief": "A checklist of 4-5 daily habits that make the face look less puffy: "
                 "water, sleep, salt, sugar and alcohol, posture.",
        "scene": "A minimal wellness still life (water carafe, tea, a small clock, a "
                 "plant) on a soft neutral background, objects on one side only.",
    },
    "myth": {
        "board": "Face Yoga Exercises",
        "brief": "An honest myth-vs-fact about face exercises: they do not burn fat "
                 "in one spot; they can tone muscles, reduce puffiness and improve "
                 "posture. Plain and honest, no preaching.",
        "scene": "A studio portrait of a young woman in her twenties in side profile "
                 "with good upright posture and a defined jawline, against a smooth "
                 "deep purple gradient background with soft cyan rim light.",
    },
    "mewing": {
        "board": "Mewing & Posture",
        "brief": "How to mew correctly: tongue flat on the roof of the mouth, lips "
                 "closed, teeth lightly together, nasal breathing, good neck posture. "
                 "Mention honestly that it does not reshape adult bones but posture "
                 "makes the jawline look sharper.",
        "scene": "A clean minimal 3D illustration of a human head in side profile "
                 "with a straight neck, soft purple and cyan gradient colours, dark "
                 "navy background, no labels.",
    },
}

TYPE_ORDER = ["exercise", "depuff", "habits", "myth", "mewing"]


def copy_prompt(pin_type: str) -> str:
    t = PIN_TYPES[pin_type]
    return f"""You write Pinterest pins for women for 'Face Slimmer', a free Android app with daily 5-minute face yoga, facial massage and jawline routines, habit tracking and an AI face preview.

Pin topic: {t['brief']}

STRICT RULES:
- English. Reads like a real woman sharing what works for her, not a wellness magazine and not an ad.
- Pinterest is a search engine: use the words people actually type ("face yoga for jawline", "puffy face in the morning", "gua sha routine"), naturally, not stuffed.
- Never promise weight or fat loss. Never use these words: {', '.join(FORBIDDEN)}.
- No hashtags, no emojis.
- Make it different from a generic version: pick a fresh angle, a specific move or a specific moment of the day.

{HUMAN_RULES}

Return ONLY valid JSON with fields:
1. "overlay_title": the text drawn on the image, 3-7 words, title case, the key phrase first, a number when it fits (e.g. "3 Face Yoga Moves for a Sharper Jawline").
2. "overlay_subtitle": 2-5 words shown under the title (e.g. "5 minutes a day"), or "" if not needed.
3. "pin_title": Pinterest title, max 90 characters, starts with the search phrase. No "Phrase: Catchy Subtitle" pattern and no colon.
4. "description": 250-420 characters. The first sentence contains the search phrase and a concrete problem (only the first ~60 characters show in the feed). Then the steps, short and specific. Then one short sentence that the full 5-minute routine is in the free Face Slimmer app. End with a short, natural nudge to save it (e.g. "Saving this for tomorrow morning"), worded differently each time.
5. "alt_text": plain description of the image for screen readers, max 150 characters.
6. "scene_detail": one sentence that varies this scene: {t['scene']} Describe a specific person, setting or arrangement, lighting and colour palette. Do not mention text or titles.
"""


# Everything a person reads; scene_detail only goes to the image model.
READ_FIELDS = ("overlay_title", "overlay_subtitle", "pin_title", "description", "alt_text")
DESCRIPTION_MAX = 480  # pin_feed cuts at 500 - past that the app line is lost


def copy_problems(copy: dict) -> list[str]:
    blob = " ".join(str(copy.get(k, "")) for k in READ_FIELDS).lower()
    bad = [w for w in FORBIDDEN if w in blob] + tells(blob)
    if "face slimmer" not in str(copy.get("description", "")).lower():
        bad.append("(the description must name Face Slimmer)")
    if len(str(copy.get("description", ""))) > DESCRIPTION_MAX:
        bad.append(f"(the description must be under {DESCRIPTION_MAX} characters)")
    return bad


def write_copy(pin_type: str) -> dict:
    prompt = copy_prompt(pin_type)
    for attempt in range(1, 4):
        copy = gemini(prompt)
        for k in READ_FIELDS:
            copy[k] = tidy(copy.get(k, ""))
        bad = copy_problems(copy)
        if not bad:
            return copy
        print(f"Copy attempt {attempt} rejected {bad}, retrying")
        prompt = copy_prompt(pin_type) + retry_note(bad)
    raise RuntimeError(f"Gemini kept writing unusable copy: {bad}")


def font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), size)
    f.set_variation_by_axes([weight])
    return f


def wrap_to_width(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    """Greedy word wrap by rendered width."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=f) <= max_w:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def compose(photo: Image.Image, title: str, subtitle: str) -> bytes:
    """Crop the photo to 2:3, darken the top, draw title, subtitle and brand."""
    photo = photo.convert("RGB")
    w, h = photo.size
    target = PIN_W / PIN_H
    if w / h > target:
        new_w = int(h * target)
        photo = photo.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    else:
        new_h = int(w / target)
        photo = photo.crop((0, 0, w, new_h))
    pin = photo.resize((PIN_W, PIN_H), Image.LANCZOS)

    # Dark gradient over the top ~45% so white text reads on any photo.
    shade = Image.new("L", (1, PIN_H))
    for y in range(PIN_H):
        shade.putpixel((0, y), int(max(0.0, 1 - y / (PIN_H * 0.5)) ** 1.2 * 215))
    shade = shade.resize((PIN_W, PIN_H))
    pin = Image.composite(Image.new("RGB", pin.size, (14, 4, 30)), pin, shade)

    # Text goes on its own layer so it can cast a soft shadow - the gradient
    # alone is not enough when the model puts something light up top anyway.
    text_layer = Image.new("RGBA", pin.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    margin = 70

    # Title: shrink until it fits in 4 lines.
    size = 92
    while True:
        tf = font(size, 800)
        lines = wrap_to_width(draw, title, tf, PIN_W - 2 * margin)
        if len(lines) <= 4 or size <= 56:
            break
        size -= 6
    y = 90
    line_h = int(size * 1.08)
    for line in lines:
        tw = draw.textlength(line, font=tf)
        draw.text(((PIN_W - tw) / 2, y), line, font=tf, fill="white")
        y += line_h

    if subtitle:
        sf = font(44, 500)
        y += 14
        tw = draw.textlength(subtitle, font=sf)
        draw.text(((PIN_W - tw) / 2, y), subtitle, font=sf, fill=(0, 240, 255))

    shadow = Image.new("RGBA", pin.size, (0, 0, 0, 0))
    shadow.putalpha(text_layer.getchannel("A").filter(ImageFilter.GaussianBlur(10)))
    pin = pin.convert("RGBA")
    pin = Image.alpha_composite(pin, shadow)
    pin = Image.alpha_composite(pin, text_layer).convert("RGB")
    draw = ImageDraw.Draw(pin)

    # Brand pill at the bottom.
    bf = font(30, 700)
    label = "Face Slimmer  ·  free on Google Play"
    tw = draw.textlength(label, font=bf)
    pw, ph = tw + 56, 62
    x0, y0 = (PIN_W - pw) / 2, PIN_H - ph - 48
    pill = Image.new("RGBA", pin.size, (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle(
        (x0, y0, x0 + pw, y0 + ph), radius=ph // 2, fill=(14, 4, 30, 200)
    )
    pin = Image.alpha_composite(pin.convert("RGBA"), pill).convert("RGB")
    draw = ImageDraw.Draw(pin)
    draw.text((x0 + 28, y0 + 13), label, font=bf, fill="white")

    out = io.BytesIO()
    pin.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    return out.getvalue()


def pin_link(pin_type: str) -> str:
    referrer = f"utm_source=pinterest&utm_medium=social&utm_campaign={pin_type}"
    return f"{PLAY_URL}&referrer={quote(referrer, safe='')}"


def send_preview(image: bytes, pin_type: str, copy: dict, link: str, status: str) -> None:
    """Photo plus the full pin text to the Telegram queue."""
    if os.environ.get("DRY_RUN", "").lower() == "true":
        Path("pin_preview.jpg").write_bytes(image)
        print("[dry-run] saved pin_preview.jpg")
        print(copy)
        return
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    api = f"https://api.telegram.org/bot{token}"

    resp = requests.post(
        f"{api}/sendPhoto",
        data={"chat_id": chat, "caption": f"\U0001f4cc Pinterest pin ({pin_type})\n{status}"},
        files={"photo": ("pin.jpg", image, "image/jpeg")},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()

    text = f"Board: {html.escape(PIN_TYPES[pin_type]['board'])}\n\n" + copyable([
        ("Title", str(copy.get("pin_title", ""))),
        ("Description", str(copy.get("description", ""))),
        ("Alt text", str(copy.get("alt_text", ""))),
        ("Link", link),
    ])
    resp = requests.post(
        f"{api}/sendMessage",
        json={"chat_id": chat, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def main() -> None:
    # Validate configuration before spending generation credits.
    for key in ("GEMINI_API_KEY", "KIE_API_KEY"):
        env(key)
    if os.environ.get("DRY_RUN", "").lower() != "true":
        required = ("LANDING_REPO", "SITE_URL", "PIN_COMMIT_NAME", "PIN_COMMIT_EMAIL") if os.environ.get("LANDING_REPO_TOKEN", "").strip() else ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        for key in required:
            env(key)
    forced = os.environ.get("PIN_TYPE", "auto").strip().lower()
    if forced in PIN_TYPES:
        pin_type = forced
    else:
        day = int(time.time() // 86400)
        pin_type = TYPE_ORDER[day % len(TYPE_ORDER)]
    print(f"Pin type: {pin_type}")

    try:
        copy = write_copy(pin_type)
        print(f"Copy: {copy.get('overlay_title')!r}")

        scene = str(copy.get("scene_detail") or PIN_TYPES[pin_type]["scene"])
        try:
            image_url = kie_generate(scene + IMAGE_SUFFIX, aspect_ratio="2:3", what="Pin")
        except requests.HTTPError as exc:
            # Not every Kie model takes 2:3. 9:16 is known to work, and
            # compose() crops any ratio to 2:3.
            print(f"2:3 rejected ({exc}), retrying at 9:16")
            image_url = kie_generate(scene + IMAGE_SUFFIX, aspect_ratio="9:16", what="Pin")
        photo = Image.open(
            io.BytesIO(requests.get(image_url, timeout=TIMEOUT).content)
        )

        pin = compose(
            photo,
            str(copy.get("overlay_title", "")),
            str(copy.get("overlay_subtitle", "")),
        )
        board = PIN_TYPES[pin_type]["board"]
        dry = os.environ.get("DRY_RUN", "").lower() == "true"
        if os.environ.get("LANDING_REPO_TOKEN", "").strip() and not dry:
            # Pinterest posts it from the feed; nothing for the owner to do,
            # so no Telegram copy. Failures still alert below.
            feed = pin_feed.publish(pin, pin_type, board, copy)
            print(f"Queued in the RSS feed, Pinterest will post it: {feed}")
        else:
            status = "Not published - post it by hand."
            send_preview(pin, pin_type, copy, pin_link(pin_type), status)
            print(status)
    except Exception as exc:  # noqa: BLE001
        alert(f"\U0001f6a8 Pinterest pin ({pin_type}) failed:\n{type(exc).__name__}: {exc}"[:3500])
        raise


if __name__ == "__main__":
    main()

