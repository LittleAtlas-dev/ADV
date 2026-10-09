#!/usr/bin/env python3
"""Pinterest pin generation.

One pin per run: Gemini writes the copy, Higgsfield renders a 2:3 photo with no text
on it, and the title is drawn on top here with Pillow - image models misspell
text, and a template service would need its own 2:3 template.

Each pin is committed to the landing page's RSS feeds, which Pinterest
auto-publishes (see pin_feed.py); Telegram only hears about failures.
Without LANDING_REPO_TOKEN (or on a dry run) the pin goes to Telegram instead,
to be posted by hand.

Little Atlas content introduces symbolic child profiles and creative keepsakes.
Never present the product as diagnosis or a reliable prediction of the future.
"""

import html
import io
import os
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import pin_feed
from pinterest_services import TIMEOUT, alert, env, gemini, higgsfield_generate
from human_text import HUMAN_RULES, retry_note, tells, tidy
from pinterest_text import copyable

PIN_W, PIN_H = 1000, 1500
FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "Outfit.ttf"

# Claims rejected even if the model ignores the product brief.
FORBIDDEN = [
    "face slimmer", "face yoga", "gua sha", "mewing", "google play",
    "guaranteed", "scientifically proven", "diagnose", "diagnosis",
    "predict your child's future", "predicts your child's future",
    "predict your child’s future", "predicts your child’s future",
    "destined to", "will become", "accurate prediction",
]

IMAGE_SUFFIX = (
    " Vertical 2:3 composition. Leave the top third calm and uncluttered for a title. "
    "Premium editorial still life or delicate symbolic illustration, warm ivory, "
    "muted gold, sage and midnight blue, soft light, refined paper textures. "
    "No text, letters, numbers, logos, watermarks, app screenshots or readable documents. "
    "Do not depict real customer data, identifiable children or before-and-after portraits."
)

PIN_TYPES = {
    "strengths": {
        "board": "Little Atlas Child Strengths",
        "brief": "Three gentle observation prompts for parents noticing a child's curiosity, creativity or persistence. Frame these as everyday observations, never a fixed personality label.",
        "scene": "A small compass, wooden building blocks and an open blank notebook arranged like a quiet discovery table, no people.",
    },
    "parenting": {
        "board": "Little Atlas Mindful Parenting",
        "brief": "Three small ways to make room for a child's own interests, such as offering choices, listening and exploring together. Avoid clinical advice and claims about developmental outcomes.",
        "scene": "Two ceramic cups, colored pencils and a simple handmade paper boat on a warm family table, no people.",
    },
    "mandala": {
        "board": "Little Atlas Personal Mandalas",
        "brief": "Introduce the personal mandala in Free Atlas as symbolic artwork and a conversation starter about a child's unique qualities. Never claim healing, measurable energy or scientific assessment.",
        "scene": "An original intricate circular botanical mandala in muted gold and sage on ivory paper, centered in the lower two thirds, no text.",
    },
    "keepsake": {
        "board": "Little Atlas Family Keepsakes",
        "brief": "An idea for a meaningful digital family keepsake. Explain that Premium Atlas includes artistic age cards and an expanded PDF; age imagery is imaginative, not a forecast of appearance or destiny. Do not invent prices, discounts or delivery times.",
        "scene": "A premium memory box with blank art cards, pressed flowers and a small brass star on a linen surface, no portraits or text.",
    },
    "free_atlas": {
        "board": "Little Atlas Free Atlas",
        "brief": "Introduce Free Atlas: a symbolic child profile with personality type, strengths, parent prompts and a personal mandala, based on birth details. Invite parents to explore the free profile without calling it diagnosis or a factual prediction.",
        "scene": "A blank decorative portrait-format card with an abstract compass rose, a small constellation and a delicate mandala on cream paper, no readable UI.",
    },
}

TYPE_ORDER = list(PIN_TYPES)


def copy_prompt(pin_type: str) -> str:
    t = PIN_TYPES[pin_type]
    return f"""Write a Pinterest pin for Little Atlas, a web product for parents.
PRODUCT FACTS:
- Free Atlas is a symbolic child profile based on birth details, with personality type, strengths, parent prompts and a personal mandala.
- Premium Atlas adds artistic age cards and an expanded PDF. Age images are imaginative artwork.
- This is a creative, reflective experience, not psychological assessment, medical advice, scientific evidence or a reliable prediction of appearance, career or destiny.
- Never invent testimonials, personal experience, expert endorsements, prices, discounts, app-store availability or results. Never imply Premium is free.

Pin topic: {t['brief']}

RULES:
- English, warm and clear, addressing parents of any gender.
- Use natural search phrases about child strengths, mindful parenting, personal mandalas and family keepsakes, selected for this topic.
- Give one concrete idea or explain one real product feature. Avoid assigning a child a fixed future or pressuring parents.
- Never use: {', '.join(FORBIDDEN)}.
- No hashtags, emojis or URLs in the copy.
- Mention Little Atlas naturally. Invite readers to explore or save the idea, without fabricated urgency.

{HUMAN_RULES}

Return ONLY valid JSON:
1. "overlay_title": 3-7 words, key phrase first, max 60 characters.
2. "overlay_subtitle": 2-5 words, or an empty string.
3. "pin_title": search-friendly title, max 90 characters, no colon.
4. "description": 250-420 characters: concrete idea or feature, then a short truthful Little Atlas invitation. For age cards explicitly say imaginative artwork, not a prediction.
5. "alt_text": plain image description for screen readers, max 150 characters.
6. "scene_detail": one visual variation of this scene: {t['scene']} Describe objects, lighting and palette only. No text, real child photos or fabricated screenshots.
"""


# Everything a person reads; scene_detail only goes to the image model.
READ_FIELDS = ("overlay_title", "overlay_subtitle", "pin_title", "description", "alt_text")
DESCRIPTION_MAX = 480  # pin_feed cuts at 500 - past that the app line is lost


def copy_problems(copy: dict) -> list[str]:
    blob = " ".join(str(copy.get(k, "")) for k in READ_FIELDS).lower()
    bad = [w for w in FORBIDDEN if w in blob] + tells(blob)
    if "little atlas" not in str(copy.get("description", "")).lower():
        bad.append("(the description must name Little Atlas)")
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
    label = "Little Atlas  ·  A world of possibilities"
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
    return pin_feed.landing_link(env("SITE_URL").rstrip("/"), pin_type)


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
    for key in ("GEMINI_API_KEY", "HF_API_KEY", "SITE_URL"):
        env(key)
    if os.environ.get("DRY_RUN", "").lower() != "true":
        required = ("LANDING_REPO", "SITE_URL", "PIN_COMMIT_NAME", "PIN_COMMIT_EMAIL") if os.environ.get("LANDING_REPO_TOKEN", "").strip() else ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        for key in required:
            env(key)
    forced = os.environ.get("PIN_TYPE", "auto").strip().lower()
    if forced not in {"", "auto", *PIN_TYPES}:
        raise ValueError(f"Unknown PIN_TYPE: {forced}")
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
        image_url = higgsfield_generate(scene + IMAGE_SUFFIX, aspect_ratio="2:3", what="Pin")
        downloaded = requests.get(image_url, timeout=TIMEOUT)
        downloaded.raise_for_status()
        photo = Image.open(io.BytesIO(downloaded.content))

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
