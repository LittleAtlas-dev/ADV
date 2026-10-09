"""Keep generated copy from reading like an AI wrote it.

People on Reddit, X and Pinterest spot AI text by a handful of tells: em
dashes, markdown asterisks, curly quotes, and a stock vocabulary ("embrace",
"elevate", "rejuvenate", "game changer"). A post that reads like that gets
scrolled past on X, downvoted on Reddit and called out as a bot.

HUMAN_RULES goes into every prompt. tidy() fixes the mechanical tells, and
tells() lists the word-level ones so the caller can ask Gemini for a rewrite.
The landing repo's api/telegram.js keeps a copy of the same list - change
both together.
"""

import re

# Lowercase; matched as whole words/phrases.
BANNED = [
    "delve", "dive in", "dive into", "game changer", "game-changer", "elevate",
    "unlock", "unleash", "journey", "embrace", "empower", "transform your",
    "transformative", "seamless", "effortless", "effortlessly", "holistic",
    "nourish", "rejuvenate", "revitalize", "radiant", "vibrant", "ritual",
    "boost your", "level up", "next level", "say goodbye", "in today's",
    "whether you", "here's the thing", "the secret", "secret weapon",
    "pro tip", "the best part", "a testament", "navigate", "realm", "tapestry",
    "crucial", "essential", "moreover", "furthermore", "additionally",
    "ultimately", "incorporate", "incorporating", "be mindful",
    "noticeable difference", "great question", "hope this helps",
    "it's important to", "remember to", "don't forget to", "detox",
    "enhance", "enhancement", "achieve", "effectively", "discover",
    "refreshed glow", "natural glow", "look and feel your best", "ready to",
    "imagine", "unlock your", "self-care routine",
]
_BANNED_RE = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(b) for b in BANNED) + r")(?![a-z])"
)

HUMAN_RULES = f"""HOW TO SOUND HUMAN (most important - nobody should be able to tell AI wrote this):
- Write like one real person typing on their phone, not a copywriter or a brand. Plain everyday words, contractions (I'm, don't, it's), short sentences. A fragment now and then is fine.
- Specific beats polished: a named move, seconds or reps, a time of day, a small concrete detail.
- No em dashes or en dashes. Use a comma, a period or " - " instead.
- No markdown (no *asterisks*, no **bold**), no curly quotes, no emoji chains.
- Never use these words or phrases: {", ".join(BANNED)}.
- No "it's not X, it's Y" contrasts, no stacks of three adjectives, no opening rhetorical question, no summary or motivational line at the end, no "Great question".
- Vary how sentences start. Do not start with "So,", "Honestly,", "Let's" or "As someone who".
- Never invent personal results or stories ("I lost my double chin in 2 weeks"). Share what helps, not fake proof."""

_DASH_RE = re.compile(r"\s*[—–]\s*")


def tidy(text: str) -> str:
    """Fix the mechanical tells: dashes, curly quotes, ellipsis, markdown."""
    text = _DASH_RE.sub(" - ", str(text))
    text = (text.replace("‘", "'").replace("’", "'")
                .replace("“", '"').replace("”", '"')
                .replace("…", "..."))
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(\S[^*]*?)\*(?!\w)", r"\1", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def tells(text: str) -> list[str]:
    """Banned phrases still in the text (run tidy() first)."""
    return sorted({m.group(1) for m in _BANNED_RE.finditer(str(text).lower())})


def retry_note(bad: list[str]) -> str:
    """Appended to a prompt after a draft came back with tells."""
    return ("\n\nYOUR LAST DRAFT WAS REJECTED because of: "
            + ", ".join(f'"{b}"' for b in bad)
            + ". Rewrite it from scratch in plain everyday words, without them.")
