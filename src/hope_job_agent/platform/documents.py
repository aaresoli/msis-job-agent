"""Private S3-compatible resume storage."""

from __future__ import annotations

import io
from functools import lru_cache

from minio import Minio

from hope_job_agent.platform.settings import get_platform_settings


@lru_cache
def document_client() -> Minio:
    settings = get_platform_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
    )


def put_private_document(object_key: str, content: bytes, media_type: str) -> None:
    settings = get_platform_settings()
    client = document_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
    client.put_object(
        settings.minio_bucket,
        object_key,
        io.BytesIO(content),
        len(content),
        content_type=media_type,
    )


def delete_private_document(object_key: str) -> None:
    """Delete a private object; callers keep database metadata if this fails."""

    settings = get_platform_settings()
    document_client().remove_object(settings.minio_bucket, object_key)


def get_private_document(object_key: str) -> bytes:
    settings = get_platform_settings()
    response = document_client().get_object(settings.minio_bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
