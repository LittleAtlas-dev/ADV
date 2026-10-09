"""Format Pinterest previews for Telegram."""
import html

def copyable(fields: list[tuple[str, str]]) -> str:
    """Telegram HTML: each field as a label plus a <pre> block, which Telegram
    copies with one tap. Empty fields are left out."""
    return "\n\n".join(
        f"<b>{html.escape(label)}</b>\n<pre>{html.escape(value.strip())}</pre>"
        for label, value in fields if value.strip()
    )
