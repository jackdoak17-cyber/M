from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.instagram.r2_storage import UploadedObject
from src.posting.test_instagram_connection import (
    PUBLISH_CONFIRMATION,
    _test_card_html,
    publish_test_card,
)


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded_keys: list[str] = []
        self.deleted_keys: list[str] = []

    def upload_file(
        self,
        local_path: Path,
        key: str,
        *,
        content_type: str,
        cache_control: str,
    ) -> UploadedObject:
        assert local_path.read_bytes() == b"png"
        assert content_type == "image/png"
        assert cache_control == "public, max-age=3600"
        self.uploaded_keys.append(key)
        return UploadedObject(
            key=key,
            url=f"https://media.example/{key}",
            content_type=content_type,
            size_bytes=3,
        )

    def delete_keys(self, keys: list[str]) -> int:
        self.deleted_keys.extend(keys)
        return len(keys)


class FakeInstagramClient:
    def __init__(self) -> None:
        self.image_url: str | None = None
        self.is_carousel_item: bool | None = None
        self.waited_for: str | None = None
        self.published_container: str | None = None

    def create_image_container(self, image_url: str, *, is_carousel_item: bool = True) -> str:
        self.image_url = image_url
        self.is_carousel_item = is_carousel_item
        return "container-123"

    def wait_for_container_ready(self, creation_id: str) -> dict[str, str]:
        self.waited_for = creation_id
        return {"status_code": "FINISHED"}

    def publish_container(self, creation_id: str) -> str:
        self.published_container = creation_id
        return "media-456"

    def get_media(self, media_id: str, *, fields: str = "id,permalink") -> dict[str, str]:
        assert media_id == "media-456"
        assert fields == "id,permalink"
        return {
            "id": media_id,
            "permalink": "https://www.instagram.com/p/test/",
        }


def test_publish_requires_exact_confirmation_before_upload(tmp_path: Path) -> None:
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"png")
    storage = FakeStorage()
    client = FakeInstagramClient()

    with pytest.raises(RuntimeError, match="PUBLISH_TEST"):
        publish_test_card(
            confirmation="yes",
            run_label="operations-1",
            image_path=image_path,
            storage=storage,  # type: ignore[arg-type]
            client=client,  # type: ignore[arg-type]
            generated_at=datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
        )

    assert storage.uploaded_keys == []
    assert client.image_url is None


def test_publish_returns_confirmed_media_and_cleans_up_r2(tmp_path: Path) -> None:
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"png")
    storage = FakeStorage()
    client = FakeInstagramClient()
    probed_urls: list[str] = []

    result = publish_test_card(
        confirmation=PUBLISH_CONFIRMATION,
        run_label="operations-42",
        image_path=image_path,
        storage=storage,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        generated_at=datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
        public_image_probe=probed_urls.append,
    )

    expected_key = "instagram/connection-tests/2026-07-25/operations-42/connection-test.png"
    assert storage.uploaded_keys == [expected_key]
    assert storage.deleted_keys == [expected_key]
    assert probed_urls == [f"https://media.example/{expected_key}"]
    assert client.is_carousel_item is False
    assert client.waited_for == "container-123"
    assert client.published_container == "container-123"
    assert result.status == "published"
    assert result.media_id == "media-456"
    assert result.permalink == "https://www.instagram.com/p/test/"


def test_card_escapes_dynamic_run_label() -> None:
    rendered = _test_card_html(
        run_label="<script>alert(1)</script>",
        generated_at=datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
    )

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
