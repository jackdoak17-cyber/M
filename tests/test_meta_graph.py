from __future__ import annotations

import pytest

from src.instagram.meta_graph import InstagramGraphClient, MetaGraphApiError, MetaGraphSettings


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


def test_uses_facebook_graph_for_facebook_login_page_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_post(url, *, data, timeout):
        observed.update(url=url, data=data, timeout=timeout)
        return FakeResponse(200, {"id": "container-1"})

    monkeypatch.setattr("src.instagram.meta_graph.requests.post", fake_post)
    client = InstagramGraphClient(
        MetaGraphSettings(instagram_account_id="ig-1", access_token="token-value")
    )

    assert client.create_image_container("https://media.example/card.png") == "container-1"
    assert observed["url"] == "https://graph.facebook.com/v25.0/ig-1/media"
    assert observed["data"] == {
        "image_url": "https://media.example/card.png",
        "is_carousel_item": "true",
        "access_token": "token-value",
    }


def test_surfaces_meta_error_code_without_leaking_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url, *, data, timeout):
        return FakeResponse(
            400,
            {"error": {"message": "Bad media for token-value", "code": 100, "error_subcode": 33}},
        )

    monkeypatch.setattr("src.instagram.meta_graph.requests.post", fake_post)
    client = InstagramGraphClient(
        MetaGraphSettings(instagram_account_id="ig-1", access_token="token-value")
    )

    with pytest.raises(MetaGraphApiError, match=r"400 code=100 subcode=33") as error:
        client.create_image_container("https://media.example/card.png")

    assert "token-value" not in str(error.value)
    assert "[redacted]" in str(error.value)
