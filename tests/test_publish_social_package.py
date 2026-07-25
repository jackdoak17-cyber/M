from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.posting.publish_social_package import publish_package, validate_package


POST_ID = "00000000-0000-0000-0000-000000000001"


def package(**overrides):
    value = {
        "id": POST_ID,
        "account_key": "oddssearch-main",
        "status": "publishing",
        "channels": ["x", "instagram"],
        "instagram_caption": "Reviewed caption",
        "instagram_image_urls": [
            "https://media.example/slide-1.png",
            "https://media.example/slide-2.png",
        ],
        "warnings": [],
        "posted_instagram_id": None,
    }
    value.update(overrides)
    return value


class FakeClient:
    def __init__(self):
        self.single = []
        self.carousels = []

    def create_and_publish_carousel(self, urls, caption):
        self.carousels.append((urls, caption))
        return SimpleNamespace(media_id="media-carousel")

    def create_image_container(self, url, *, is_carousel_item, caption=None):
        self.single.append((url, is_carousel_item, caption))
        return "container-single"

    def wait_for_container_ready(self, container_id):
        return {"status": "FINISHED", "id": container_id}

    def publish_container(self, container_id):
        return "media-single"

    def get_media(self, media_id, *, fields):
        return {"id": media_id, "permalink": "https://instagram.example/post"}


def test_rejects_mock_local_and_unapproved_packages():
    with pytest.raises(RuntimeError, match="warning blocks"):
        validate_package(
            package(warnings=[{"message": "Mock detected fixture-day package."}]),
            post_id=POST_ID,
            account_key="oddssearch-main",
        )
    with pytest.raises(RuntimeError, match="warning blocks"):
        validate_package(
            package(data_snapshot={"is_mock": True}),
            post_id=POST_ID,
            account_key="oddssearch-main",
        )
    with pytest.raises(RuntimeError, match="durable HTTPS"):
        validate_package(
            package(instagram_image_urls=["http://localhost/slide.png"]),
            post_id=POST_ID,
            account_key="oddssearch-main",
        )
    with pytest.raises(RuntimeError, match="publishing state"):
        validate_package(
            package(status="approved"),
            post_id=POST_ID,
            account_key="oddssearch-main",
        )


def test_publishes_a_reviewed_carousel():
    client = FakeClient()
    result = publish_package(
        package(),
        post_id=POST_ID,
        account_key="oddssearch-main",
        client=client,
    )

    assert result.media_id == "media-carousel"
    assert result.image_count == 2
    assert len(client.carousels) == 1
    assert client.single == []


def test_publishes_a_reviewed_single_image():
    client = FakeClient()
    result = publish_package(
        package(instagram_image_urls=["https://media.example/slide.png"]),
        post_id=POST_ID,
        account_key="oddssearch-main",
        client=client,
    )

    assert result.media_id == "media-single"
    assert client.single == [
        ("https://media.example/slide.png", False, "Reviewed caption")
    ]
