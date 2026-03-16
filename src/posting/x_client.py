from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, List

import requests
from requests import RequestException, Response
from requests_oauthlib import OAuth1

from .settings import get_posting_settings


@dataclass(frozen=True)
class TweetResult:
    tweet_ids: List[str]


def _oauth() -> OAuth1:
    settings = get_posting_settings()
    if not (settings.x_consumer_key and settings.x_consumer_secret and settings.x_access_token and settings.x_access_token_secret):
        raise RuntimeError("Missing X API credentials")
    return OAuth1(
        settings.x_consumer_key,
        settings.x_consumer_secret,
        settings.x_access_token,
        settings.x_access_token_secret,
    )


def _split_text(text: str, max_len: int = 4000) -> List[str]:
    lines = text.splitlines() if text else []
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current_len
        if current:
            chunks.append("\n".join(current).rstrip())
            current.clear()
            current_len = 0

    for line in lines:
        if len(line) > max_len:
            flush()
            start = 0
            while start < len(line):
                chunks.append(line[start : start + max_len])
                start += max_len
            continue
        if not current:
            current.append(line)
            current_len = len(line)
            continue
        projected = current_len + 1 + len(line)
        if projected > max_len:
            flush()
            current.append(line)
            current_len = len(line)
        else:
            current.append(line)
            current_len = projected
    flush()

    if not chunks:
        return [""]
    return chunks


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _response_snippet(response: Response, limit: int = 220) -> str:
    snippet = response.text[:limit].replace("\n", " ").strip()
    return snippet or "<empty response body>"


def _is_cloudflare_challenge(response: Response) -> bool:
    text = response.text.lower()
    return response.status_code == 403 and ("just a moment" in text or "cloudflare" in text)


def _post_thread_v1(chunks: List[str], auth: OAuth1, reason: str | None = None) -> TweetResult:
    if reason:
        print(f"Falling back to X v1.1 statuses/update ({reason})")
    url = "https://api.twitter.com/1.1/statuses/update.json"
    tweet_ids: List[str] = []
    reply_to: str | None = None

    for chunk in chunks:
        payload: dict[str, Any] = {"status": chunk}
        if reply_to:
            payload["in_reply_to_status_id"] = reply_to
            payload["auto_populate_reply_metadata"] = "true"
        response = requests.post(url, data=payload, auth=auth, timeout=30)
        response.raise_for_status()
        data = response.json()
        tweet_id = data.get("id_str") or (str(data.get("id")) if data.get("id") else None)
        if not tweet_id:
            raise RuntimeError(f"Unexpected X v1.1 response: {data}")
        tweet_ids.append(tweet_id)
        reply_to = tweet_id

    return TweetResult(tweet_ids=tweet_ids)


def _is_v2_fallback_status(response: Response) -> bool:
    # v2 occasionally returns 5xx or enrollment/auth-gating responses even when
    # user-context v1.1 posting is still healthy.
    return response.status_code in {429, 500, 502, 503, 504} or _is_cloudflare_challenge(response)


def _is_retryable_v2_status(response: Response) -> bool:
    return response.status_code in {429, 500, 502, 503, 504} or _is_cloudflare_challenge(response)


def post_thread(text: str) -> TweetResult:
    v2_url = "https://api.twitter.com/2/tweets"
    auth = _oauth()
    chunks = _split_text(text)
    enable_v1_fallback = _env_bool("X_ENABLE_V1_FALLBACK", default=False)
    max_retries = 4
    base_backoff_seconds = 3
    tweet_ids: List[str] = []
    reply_to: str | None = None

    for idx, chunk in enumerate(chunks):
        payload: dict[str, Any] = {"text": chunk}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}
        response: Response | None = None
        network_error: RequestException | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(v2_url, json=payload, auth=auth, timeout=30)
                network_error = None
            except RequestException as exc:
                network_error = exc
                if attempt < max_retries:
                    time.sleep(base_backoff_seconds * attempt)
                    continue
                response = None
                break

            if response.ok:
                break

            if _is_retryable_v2_status(response) and attempt < max_retries:
                time.sleep(base_backoff_seconds * attempt)
                continue
            break

        if response is None:
            if idx == 0 and enable_v1_fallback:
                return _post_thread_v1(chunks, auth, reason=str(network_error))
            raise RuntimeError(f"X v2 post failed after retries (network error): {network_error}")

        if not response.ok:
            if idx == 0 and enable_v1_fallback and _is_v2_fallback_status(response):
                return _post_thread_v1(
                    chunks,
                    auth,
                    reason=f"v2 status {response.status_code}: {_response_snippet(response)}",
                )
            raise RuntimeError(f"X v2 post failed (status {response.status_code}): {_response_snippet(response)}")

        data = response.json()
        tweet_id = data.get("data", {}).get("id")
        if not tweet_id:
            raise RuntimeError(f"Unexpected X response: {data}")
        tweet_ids.append(tweet_id)
        reply_to = tweet_id

    return TweetResult(tweet_ids=tweet_ids)
