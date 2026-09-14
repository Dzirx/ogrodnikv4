"""Pliki w MinIO. Przepisane z pierwszej wersji - dzialalo."""

import boto3

from app.config import settings


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


def ensure_bucket() -> None:
    client = _client()
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if settings.minio_bucket not in existing:
        client.create_bucket(Bucket=settings.minio_bucket)


def upload_bytes(key: str, data: bytes) -> None:
    ensure_bucket()
    _client().put_object(Bucket=settings.minio_bucket, Key=key, Body=data)


def download_bytes(key: str) -> bytes:
    return _client().get_object(Bucket=settings.minio_bucket, Key=key)["Body"].read()
