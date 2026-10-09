"""Shared API helpers for Pinterest generation and optional Telegram alerts."""

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

KIE_CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"

KIE_RECORD_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

POLL_ATTEMPTS = 60

POLL_INTERVAL = 15

KIE_TASK_ATTEMPTS = 3

KIE_RETRY_DELAY = 20

KIE_TOTAL_BUDGET = 20 * 60

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

def kie_extract_url(data: dict[str, Any]) -> str:
    """Pull the first result URL out of a recordInfo payload."""
    result = data.get("resultJson")
    if not result:
        return ""
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError):
        return ""
    urls = parsed.get("resultUrls")
    return urls[0] if isinstance(urls, list) and urls else ""

def _kie_create(prompt: str, aspect_ratio: str, kie_key: str) -> str:
    """Start one Kie task and return its id."""
    created = requests.post(
        KIE_CREATE_URL,
        headers={
            "Authorization": f"Bearer {kie_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "nano-banana-2-lite",
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": "2K",
                "output_format": "jpg",
            },
        },
        timeout=TIMEOUT,
    )
    created.raise_for_status()
    task_id = created.json().get("data", {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"Kie returned no taskId: {created.text}")
    return task_id

def _kie_poll(task_id: str, kie_key: str, deadline: float) -> tuple[str, str]:
    """Poll one task until it has an image, fails, or runs out of time."""
    image_url, state = "", "unknown"
    for attempt in range(1, POLL_ATTEMPTS + 1):
        if time.monotonic() >= deadline:
            print("  time budget spent, abandoning this task")
            break
        time.sleep(POLL_INTERVAL)
        poll = requests.get(
            KIE_RECORD_URL,
            headers={"Authorization": f"Bearer {kie_key}"},
            params={"taskId": task_id},
            timeout=TIMEOUT,
        )
        poll.raise_for_status()
        data = poll.json().get("data") or {}
        state = data.get("state", "unknown")
        image_url = kie_extract_url(data)
        print(f"  attempt {attempt}/{POLL_ATTEMPTS}: state={state}")
        if image_url or state == "fail":
            break
    return image_url, state

def kie_generate(prompt: str, *, aspect_ratio: str, what: str) -> str:
    """Render one image on Kie and return its URL, polling until it is ready.

    A failed task, a 5xx or an unreachable Kie is retried with a brand new
    task. A 4xx is not: the request itself is wrong (an aspect ratio the model
    refuses, say), retrying cannot help, and generate_pin.py relies on it
    propagating so it can fall back to another ratio.

    Alerts Telegram and raises once every attempt is used up.
    """
    kie_key = env("KIE_API_KEY")
    state, task_id, reason = "unknown", "", "unknown"
    deadline = time.monotonic() + KIE_TOTAL_BUDGET
    tries = 0

    for attempt in range(1, KIE_TASK_ATTEMPTS + 1):
        if time.monotonic() >= deadline:
            reason = "time budget spent"
            print(f"Kie: {reason}, giving up after {tries} tries")
            break
        tries = attempt
        try:
            task_id = _kie_create(prompt, aspect_ratio, kie_key)
            print(
                f"Kie task {task_id} created "
                f"(try {attempt}/{KIE_TASK_ATTEMPTS}), polling..."
            )
            image_url, state = _kie_poll(task_id, kie_key, deadline)
            if image_url:
                return image_url
            reason = f"state={state}"
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status < 500:
                raise
            reason = f"HTTP {status}"
        except requests.RequestException as exc:
            reason = f"{type(exc).__name__}: {exc}"
        except RuntimeError as exc:  # malformed create response
            reason = str(exc)

        if attempt < KIE_TASK_ATTEMPTS:
            print(f"Kie try {attempt} failed ({reason}), retrying in {KIE_RETRY_DELAY}s")
            time.sleep(KIE_RETRY_DELAY)
        else:
            print(f"Kie try {attempt} failed ({reason}), giving up")

    alert(
        f"\U0001f6a8 {what} generation failed after {tries} tries.\n"
        f"Last: {reason}\nTask: {task_id}"
    )
    raise RuntimeError(
        f"Kie produced no image after {tries} tries "
        f"(last {reason}, task {task_id})"
    )
