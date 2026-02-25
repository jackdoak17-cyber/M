from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import boto3


@dataclass(frozen=True)
class R2Settings:
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    public_base_url: str
    endpoint_url: str
    region_name: str = "auto"


@dataclass(frozen=True)
class UploadedObject:
    key: str
    url: str
    content_type: str
    size_bytes: int


class R2Storage:
    def __init__(self, settings: R2Settings) -> None:
        self.settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            region_name=settings.region_name,
        )

    def public_url_for_key(self, key: str) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}/{key.lstrip('/')}"

    def upload_file(
        self,
        local_path: Path,
        key: str,
        *,
        content_type: str,
        cache_control: str = "public, max-age=86400",
    ) -> UploadedObject:
        local_path = Path(local_path)
        extra_args = {
            "ContentType": content_type,
            "CacheControl": cache_control,
        }
        self._client.upload_file(
            str(local_path),
            self.settings.bucket_name,
            key,
            ExtraArgs=extra_args,
        )
        return UploadedObject(
            key=key,
            url=self.public_url_for_key(key),
            content_type=content_type,
            size_bytes=local_path.stat().st_size,
        )

    def upload_files(
        self,
        files: Iterable[tuple[Path, str, str]],
        *,
        cache_control: str = "public, max-age=86400",
    ) -> list[UploadedObject]:
        uploaded: list[UploadedObject] = []
        for local_path, key, content_type in files:
            uploaded.append(
                self.upload_file(
                    local_path,
                    key,
                    content_type=content_type,
                    cache_control=cache_control,
                )
            )
        return uploaded

    def delete_keys(self, keys: Iterable[str]) -> int:
        key_items = [{"Key": key} for key in keys if key]
        if not key_items:
            return 0
        deleted = 0
        # S3 delete_objects max 1000 keys per request
        for i in range(0, len(key_items), 1000):
            chunk = key_items[i : i + 1000]
            resp = self._client.delete_objects(
                Bucket=self.settings.bucket_name,
                Delete={"Objects": chunk, "Quiet": False},
            )
            if "Deleted" in resp:
                deleted += len(resp.get("Deleted") or [])
            else:
                # Some S3-compatible providers may omit Deleted; treat non-error items as deleted.
                deleted += max(0, len(chunk) - len(resp.get("Errors") or []))
        return deleted

    def key_from_public_url(self, url: str) -> str:
        parsed = urlparse(url)
        base = urlparse(self.settings.public_base_url)
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
            raise ValueError(f"URL does not match configured public base URL: {url}")
        return parsed.path.lstrip("/")
