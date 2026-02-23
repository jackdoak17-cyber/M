from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

import requests
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


def post_thread(text: str) -> TweetResult:
    url = "https://api.twitter.com/2/tweets"
    auth = _oauth()
    chunks = _split_text(text)
    tweet_ids: List[str] = []
    reply_to: str | None = None

    for chunk in chunks:
        payload: dict[str, Any] = {"text": chunk}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}
        response = requests.post(url, json=payload, auth=auth, timeout=30)
        response.raise_for_status()
        data = response.json()
        tweet_id = data.get("data", {}).get("id")
        if not tweet_id:
            raise RuntimeError(f"Unexpected X response: {data}")
        tweet_ids.append(tweet_id)
        reply_to = tweet_id

    return TweetResult(tweet_ids=tweet_ids)
