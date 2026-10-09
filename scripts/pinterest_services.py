"""Pinterest API helpers: Gemini copy, Higgsfield images, Telegram alerts."""

import json

import os

import re

import sys

import time

from typing import Any

import requests

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/gemini-2.5-flash:generateContent"
)

GEMINI_ATTEMPTS = 5

GEMINI_BACKOFF = [5, 10, 20, 40]

TIMEOUT = 60

def env(name: str, *, required: bool = True) -> str:
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def gemini(prompt: str) -> dict[str, Any]:
    """Call Gemini and parse the JSON object it returns.

    Retries transient failures - 429, any 5xx, or no response at all - with
    backoff. A 4xx other than 429 is a real problem (bad key, bad request) and
    is raised immediately rather than hammered.

    An answer that is not valid JSON is asked for again right away: longer
    answers (the TikTok carousels) now and then come back with a stray quote
    inside a string, and a fresh sample is almost always clean.
    """
    last: Exception | None = None
    for attempt in range(1, GEMINI_ATTEMPTS + 1):
        try:
            return _gemini_json(prompt)
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            last = exc
            print(f"Gemini attempt {attempt}/{GEMINI_ATTEMPTS}: unusable answer ({exc})")
    raise RuntimeError(f"Gemini gave no valid JSON after {GEMINI_ATTEMPTS} attempts: {last}")

def _gemini_json(prompt: str) -> dict[str, Any]:
    """One answer from Gemini, parsed; network retries happen in here."""
    last: Exception | None = None
    for attempt in range(1, GEMINI_ATTEMPTS + 1):
        try:
            resp = requests.post(
                GEMINI_URL,
                headers={
                    "x-goog-api-key": env("GEMINI_API_KEY"),
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 1.0,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            last = exc
            print(f"Gemini attempt {attempt}/{GEMINI_ATTEMPTS}: {exc}")
        else:
            if resp.status_code == 429 or resp.status_code >= 500:
                last = requests.HTTPError(
                    f"{resp.status_code} {resp.reason}", response=resp
                )
                print(f"Gemini attempt {attempt}/{GEMINI_ATTEMPTS}: HTTP {resp.status_code}")
            else:
                resp.raise_for_status()
                break
        if attempt < GEMINI_ATTEMPTS:
            time.sleep(GEMINI_BACKOFF[min(attempt - 1, len(GEMINI_BACKOFF) - 1)])
    else:
        raise RuntimeError(f"Gemini unavailable after {GEMINI_ATTEMPTS} attempts: {last}")

    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    # responseMimeType usually prevents code fences, but the n8n nodes stripped
    # them defensively and so do we.
    return json.loads(re.sub(r"```json|```", "", raw).strip())

def telegram(method: str, payload: dict[str, Any]) -> None:
    if os.environ.get("DRY_RUN", "").lower() == "true":
        print(f"[dry-run] telegram.{method}: {json.dumps(payload, ensure_ascii=False)}")
        return
    token = env("TELEGRAM_BOT_TOKEN")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=TIMEOUT
    )
    if not resp.ok:
        print(
            f"Telegram {method} failed: {resp.status_code} {resp.text}", file=sys.stderr
        )
    resp.raise_for_status()

def alert(text: str) -> None:
    """Best-effort failure notice - never masks the original error."""
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        print(text, file=sys.stderr)
        return
    try:
        telegram("sendMessage", {"chat_id": env("TELEGRAM_CHAT_ID"), "text": text})
    except Exception as exc:  # noqa: BLE001
        print(f"Could not send the failure alert: {exc}", file=sys.stderr)

HIGGSFIELD_BASE_URL = "https://api.higgsfield.ai"
HIGGSFIELD_MODEL = "higgsfield-ai/soul/standard"
HIGGSFIELD_POLL_SECONDS = 10
HIGGSFIELD_TOTAL_BUDGET = 20 * 60


def higgsfield_generate(prompt: str, *, aspect_ratio: str, what: str) -> str:
    """Submit once, then poll the official API for a generated image.

    An ambiguous POST failure is never retried: it may already have created a
    billable request. Poll timeouts do not imply server-side cancellation.
    """
    headers = {"Authorization": f"Key {env('HF_API_KEY')}",
               "Content-Type": "application/json"}
    created = requests.post(
        f"{HIGGSFIELD_BASE_URL}/{HIGGSFIELD_MODEL}",
        headers=headers,
        json={"prompt": prompt, "aspect_ratio": aspect_ratio,
              "resolution": "1080p", "batch_size": 1},
        timeout=TIMEOUT,
    )
    if not created.ok:
        raise RuntimeError(f"Higgsfield submission failed: HTTP {created.status_code}")
    request_id = created.json().get("request_id")
    if not request_id:
        raise RuntimeError("Higgsfield response has no request_id; check request history before retrying")
    print(f"{what}: Higgsfield request {request_id}")
    # Build our own URL so credentials are never forwarded to a response URL.
    from urllib.parse import quote
    status_url = f"{HIGGSFIELD_BASE_URL}/requests/{quote(str(request_id), safe='')}/status"
    deadline = time.monotonic() + HIGGSFIELD_TOTAL_BUDGET
    while time.monotonic() < deadline:
        try:
            response = requests.get(status_url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(HIGGSFIELD_POLL_SECONDS)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(HIGGSFIELD_POLL_SECONDS)
            continue
        if not response.ok:
            raise RuntimeError(f"Higgsfield status failed: HTTP {response.status_code}; request {request_id}")
        result = response.json()
        status = result.get("status")
        print(f"Higgsfield request {request_id}: {status}")
        if status == "completed":
            images = result.get("images") or []
            url = images[0].get("url") if images else None
            if not isinstance(url, str) or not url.startswith("https://"):
                raise RuntimeError(f"Higgsfield completed without an HTTPS image URL; request {request_id}")
            return url
        if status in {"failed", "nsfw", "canceled", "cancelled"}:
            raise RuntimeError(f"Higgsfield generation {status}; request {request_id}")
        time.sleep(HIGGSFIELD_POLL_SECONDS)
    raise TimeoutError(f"Higgsfield polling timed out; request {request_id} may still be running. Check API history before retrying.")
