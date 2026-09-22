"""Resume file storage behind one small interface.

Two backends:

* :class:`S3Storage` — any S3-compatible service (AWS S3, Cloudflare R2,
  Supabase Storage, MinIO) via boto3. Objects are private; the API is the
  only reader.
* :class:`LocalStorage` — files under ``services/api/uploads/`` for local
  development and tests, so no cloud credentials are needed to run the app.

Both store and return an opaque ``file_url`` (``s3://bucket/key`` or
``local://key``) that only this module knows how to resolve. The URL is never
handed to browsers; downloads go through the API so ownership is enforced.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final, Protocol
from urllib.parse import urlparse

from app.core.config import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


class StorageError(RuntimeError):
    """The backend refused or failed an operation."""


class Storage(Protocol):
    """Minimal object-store contract used by the resumes router."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        """Store ``data`` under ``key`` and return its ``file_url``."""

    async def get(self, file_url: str) -> bytes:
        """Return the bytes behind a ``file_url`` produced by :meth:`put`."""

    async def delete(self, file_url: str) -> None:
        """Remove the object; missing objects are not an error."""


def validate_key(key: str) -> str:
    """Reject keys that could escape the bucket prefix or the local upload dir."""
    if not _KEY_RE.match(key) or ".." in key or key.startswith("/"):
        msg = f"invalid storage key {key!r}"
        raise StorageError(msg)
    return key


# --------------------------------------------------------------------------- #
# Local disk
# --------------------------------------------------------------------------- #


class LocalStorage:
    """Files under ``root`` (default ``services/api/uploads``); ``file_url`` is ``local://<key>``."""

    scheme: Final[str] = "local"

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / validate_key(key)).resolve()
        if self._root not in path.parents:
            msg = f"key {key!r} resolves outside the upload directory"
            raise StorageError(msg)
        return path

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return f"{self.scheme}://{key}"

    async def get(self, file_url: str) -> bytes:
        path = self._path(_key_from_url(file_url, self.scheme))
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            msg = f"no stored file for {file_url}"
            raise StorageError(msg) from exc

    async def delete(self, file_url: str) -> None:
        path = self._path(_key_from_url(file_url, self.scheme))
        await asyncio.to_thread(path.unlink, True)


# --------------------------------------------------------------------------- #
# S3-compatible
# --------------------------------------------------------------------------- #


class S3Storage:
    """Objects in ``bucket`` on any S3-compatible endpoint; ``file_url`` is ``s3://<bucket>/<key>``."""

    scheme: Final[str] = "s3"

    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls) -> S3Storage:
        """Build a client from ``STORAGE_*`` settings (endpoint optional for AWS itself)."""
        import boto3  # local import: boto3 is only needed when this backend is selected

        client = boto3.client(
            "s3",
            endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
            region_name=settings.STORAGE_REGION,
            aws_access_key_id=settings.STORAGE_ACCESS_KEY or None,
            aws_secret_access_key=settings.STORAGE_SECRET_KEY or None,
        )
        return cls(client, settings.STORAGE_BUCKET)

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        validate_key(key)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                # Never public; ServerSideEncryption is honoured by AWS and ignored elsewhere.
                ServerSideEncryption="AES256",
            )
        except Exception as exc:  # botocore raises many ClientError subclasses
            msg = f"upload to s3://{self._bucket}/{key} failed: {exc}"
            raise StorageError(msg) from exc
        return f"{self.scheme}://{self._bucket}/{key}"

    async def get(self, file_url: str) -> bytes:
        bucket, key = _bucket_and_key(file_url)
        try:
            response = await asyncio.to_thread(self._client.get_object, Bucket=bucket, Key=key)
            return await asyncio.to_thread(response["Body"].read)
        except Exception as exc:
            msg = f"download of {file_url} failed: {exc}"
            raise StorageError(msg) from exc

    async def delete(self, file_url: str) -> None:
        bucket, key = _bucket_and_key(file_url)
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=bucket, Key=key)
        except Exception as exc:
            msg = f"delete of {file_url} failed: {exc}"
            raise StorageError(msg) from exc


def _key_from_url(file_url: str, scheme: str) -> str:
    parsed = urlparse(file_url)
    if parsed.scheme != scheme:
        msg = f"{file_url!r} is not a {scheme}:// URL"
        raise StorageError(msg)
    key = f"{parsed.netloc}{parsed.path}"
    return validate_key(key)


def _bucket_and_key(file_url: str) -> tuple[str, str]:
    parsed = urlparse(file_url)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        msg = f"{file_url!r} is not an s3://bucket/key URL"
        raise StorageError(msg)
    return parsed.netloc, validate_key(str(PurePosixPath(parsed.path.lstrip("/"))))


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

_storage: Storage | None = None


def get_storage() -> Storage:
    """Process-wide storage backend chosen by ``settings.STORAGE_BACKEND``."""
    global _storage  # — single lazily-built client per process
    if _storage is None:
        if settings.STORAGE_BACKEND == "s3":
            _storage = S3Storage.from_settings()
        else:
            _storage = LocalStorage(settings.STORAGE_LOCAL_DIR)
        logger.info("resume storage backend: %s", type(_storage).__name__)
    return _storage


def reset_storage() -> None:
    """Forget the cached backend (tests swap settings between cases)."""
    global _storage
    _storage = None
