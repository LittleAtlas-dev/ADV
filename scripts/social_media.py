# Disabled: this repository runs Pinterest only.
# """Fit a finished ad into the vertical 9:16 frame TikTok and YouTube use, and
# post it to the Telegram queue as a photo. Its texts come as tap-to-copy blocks.
#
# Images that are not 9:16 (the dialogue meme is square) are fitted whole over
# a blurred, darkened copy of themselves instead of being cropped, so no text
# in them is cut off.
# """
#
# import html
# import io
# import os
# from pathlib import Path
#
# import requests
# from PIL import Image, ImageEnhance, ImageFilter
#
# from generate_ad import TIMEOUT, env
#
# W, H = 1080, 1920
# TELEGRAM_CAPTION_MAX = 1024
#
#
# def to_vertical(image_bytes: bytes) -> bytes:
#     img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
#     iw, ih = img.size
#
#     # Cover-scaled background.
#     scale = max(W / iw, H / ih)
#     bg = img.resize((round(iw * scale), round(ih * scale)), Image.LANCZOS)
#     left, top = (bg.width - W) // 2, (bg.height - H) // 2
#     bg = bg.crop((left, top, left + W, top + H))
#
#     if abs(iw / ih - W / H) < 0.02:
#         # Already 9:16 (the Kie banner): just scale it.
#         out = bg
#     else:
#         bg = bg.filter(ImageFilter.GaussianBlur(40))
#         bg = ImageEnhance.Brightness(bg).enhance(0.55)
#         scale = min(W / iw, H / ih)
#         fg = img.resize((round(iw * scale), round(ih * scale)), Image.LANCZOS)
#         bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
#         out = bg
#
#     buf = io.BytesIO()
#     out.save(buf, "JPEG", quality=92, optimize=True, progressive=True)
#     return buf.getvalue()
#
#
# def copyable(fields: list[tuple[str, str]]) -> str:
#     """Telegram HTML: each field as a label plus a <pre> block, which Telegram
#     copies with one tap. Empty fields are left out."""
#     return "\n\n".join(
#         f"<b>{html.escape(label)}</b>\n<pre>{html.escape(value.strip())}</pre>"
#         for label, value in fields if value.strip()
#     )
#
#
# def send(image_url: str, fields: list[tuple[str, str]], label: str) -> None:
#     """Download the ad, fit it to 9:16 and post it to Telegram as a photo, with
#     every text (title, caption, tags) in its own tap-to-copy block."""
#     raw = requests.get(image_url, timeout=TIMEOUT)
#     raw.raise_for_status()
#     jpeg = to_vertical(raw.content)
#
#     if os.environ.get("DRY_RUN", "").lower() == "true":
#         Path(f"{label}.jpg").write_bytes(jpeg)
#         print(f"[dry-run] saved {label}.jpg")
#         print(copyable(fields))
#         return
#
#     api = f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}"
#     chat = env("TELEGRAM_CHAT_ID")
#     text = copyable(fields)
#     # The caption limit counts visible characters, not the HTML tags.
#     visible = sum(len(k) + len(v) + 4 for k, v in fields)
#     fits = visible <= TELEGRAM_CAPTION_MAX
#
#     data = {"chat_id": chat}
#     if fits:
#         data |= {"caption": text, "parse_mode": "HTML"}
#     resp = requests.post(
#         f"{api}/sendPhoto",
#         data=data,
#         files={"photo": (f"{label}.jpg", jpeg, "image/jpeg")},
#         timeout=TIMEOUT,
#     )
#     resp.raise_for_status()
#     if not fits:
#         resp = requests.post(
#             f"{api}/sendMessage",
#             json={"chat_id": chat, "text": text[:4096], "parse_mode": "HTML"},
#             timeout=TIMEOUT,
#         )
#         resp.raise_for_status()
