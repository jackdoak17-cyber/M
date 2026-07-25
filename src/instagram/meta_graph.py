from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any

import requests


DEFAULT_TIMEOUT_SEC = 30
FACEBOOK_GRAPH_BASE_URL = "https://graph.facebook.com"


@dataclass(frozen=True)
class MetaGraphSettings:
    instagram_account_id: str
    access_token: str
    api_version: str = "v25.0"
    graph_base_url: str = FACEBOOK_GRAPH_BASE_URL


@dataclass(frozen=True)
class CarouselPublishResult:
    item_container_ids: list[str]
    carousel_container_id: str
    media_id: str


class MetaGraphApiError(RuntimeError):
    """Provider error with safe, actionable context and no credential content."""

    def __init__(self, *, status_code: int, message: str, code: int | None, subcode: int | None) -> None:
        self.status_code = status_code
        self.code = code
        self.subcode = subcode
        identifier = f" code={code}" if code is not None else ""
        if subcode is not None:
            identifier += f" subcode={subcode}"
        super().__init__(f"Meta Graph API request failed ({status_code}{identifier}): {message}")


class InstagramGraphClient:
    """Minimal Meta Graph API client for carousel publishing."""

    def __init__(self, settings: MetaGraphSettings) -> None:
        self.settings = settings
        self._base = f"{settings.graph_base_url.rstrip('/')}/{settings.api_version}"

    def _raise_for_error(self, response: requests.Response) -> None:
        if response.ok:
            return
        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            raw_message = str(error.get("error_user_msg") or error.get("message") or "Meta rejected the request.")
            code = error.get("code") if isinstance(error.get("code"), int) else None
            subcode = error.get("error_subcode") if isinstance(error.get("error_subcode"), int) else None
        else:
            raw_message = "Meta rejected the request without a structured error."
            code = None
            subcode = None
        safe_message = raw_message.replace(self.settings.access_token, "[redacted]")[:800]
        raise MetaGraphApiError(
            status_code=response.status_code,
            message=safe_message,
            code=code,
            subcode=subcode,
        )

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        payload["access_token"] = self.settings.access_token
        response = requests.post(f"{self._base}/{path.lstrip('/')}", data=payload, timeout=DEFAULT_TIMEOUT_SEC)
        self._raise_for_error(response)
        return response.json()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = dict(params)
        payload["access_token"] = self.settings.access_token
        response = requests.get(f"{self._base}/{path.lstrip('/')}", params=payload, timeout=DEFAULT_TIMEOUT_SEC)
        self._raise_for_error(response)
        return response.json()

    def create_image_container(
        self,
        image_url: str,
        *,
        is_carousel_item: bool = True,
        caption: str | None = None,
    ) -> str:
        data = {
            "image_url": image_url,
        }
        if is_carousel_item:
            data["is_carousel_item"] = "true"
        elif caption:
            data["caption"] = caption
        result = self._post(f"{self.settings.instagram_account_id}/media", data)
        container_id = result.get("id")
        if not container_id:
            raise RuntimeError(f"Meta API did not return container id: {result}")
        return str(container_id)

    def create_carousel_container(self, children: list[str], caption: str) -> str:
        if not children:
            raise ValueError("children must not be empty")
        result = self._post(
            f"{self.settings.instagram_account_id}/media",
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
            },
        )
        container_id = result.get("id")
        if not container_id:
            raise RuntimeError(f"Meta API did not return carousel container id: {result}")
        return str(container_id)

    def publish_container(self, creation_id: str) -> str:
        result = self._post(
            f"{self.settings.instagram_account_id}/media_publish",
            {"creation_id": creation_id},
        )
        media_id = result.get("id")
        if not media_id:
            raise RuntimeError(f"Meta API did not return published media id: {result}")
        return str(media_id)

    def get_container_status(self, creation_id: str) -> dict[str, Any]:
        return self._get(creation_id, {"fields": "status_code,status"})

    def get_media(self, media_id: str, *, fields: str = "id,permalink") -> dict[str, Any]:
        return self._get(media_id, {"fields": fields})

    def wait_for_container_ready(
        self,
        creation_id: str,
        *,
        max_attempts: int = 10,
        delay_seconds: float = 2.0,
    ) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for _ in range(max_attempts):
            last = self.get_container_status(creation_id)
            status = str(last.get("status_code") or last.get("status") or "").upper()
            if status in {"FINISHED", "PUBLISHED"}:
                return last
            if status in {"ERROR", "EXPIRED"}:
                raise RuntimeError(f"Meta media container failed: {last}")
            sleep(delay_seconds)
        raise TimeoutError(f"Timed out waiting for Meta container {creation_id}: last={last}")

    def create_and_publish_carousel(self, image_urls: list[str], caption: str) -> CarouselPublishResult:
        if len(image_urls) < 2:
            raise ValueError("Instagram carousel requires at least 2 images")
        item_container_ids = [self.create_image_container(url, is_carousel_item=True) for url in image_urls]
        for cid in item_container_ids:
            self.wait_for_container_ready(cid)
        carousel_container_id = self.create_carousel_container(item_container_ids, caption)
        self.wait_for_container_ready(carousel_container_id)
        media_id = self.publish_container(carousel_container_id)
        return CarouselPublishResult(
            item_container_ids=item_container_ids,
            carousel_container_id=carousel_container_id,
            media_id=media_id,
        )
