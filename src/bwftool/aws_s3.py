import base64
import hashlib
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig

s3_client = boto3.client("s3", region_name=region)


def to_key(path: str, root: str | None, prefix: str) -> str:
    p = Path(path)
    if root:
        rel = p.relative_to(Path(root))
        key = rel.as_posix()
    else:
        key = p.name
    return f"{prefix}{key}" if prefix else key


def upload_singlepart(bucket, key, path, checksum_b64, storage_class):
    with open(path, "rb") as body:
        return s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            StorageClass=storage_class,
            ChecksumAlgorithm="SHA256",
            ChecksumSHA256=checksum_b64,
        )


def upload_multipart(bucket, key, path, storage_class, threshold, chunk, concurrency):
    config = TransferConfig(
        multipart_threshold=threshold,
        multipart_chunksize=chunk,
        max_concurrency=concurrency,
        use_threads=True,
    )
    return s3_client.upload_file(
        Filename=path,
        Bucket=bucket,
        Key=key,
        ExtraArgs={
            "StorageClass": storage_class,
            "ChecksumAlgorithm": "SHA256",
        },
        Config=config,
    )


def verify_uploaded(bucket, key, expected_checksum_b64):
    head = s3_client.head_object(
        Bucket=bucket,
        Key=key,
        ChecksumMode="ENABLED",
    )
    actual = head.get("ChecksumSHA256")
    if actual and actual != expected_checksum_b64:
        raise ValueError(f"Checksum mismatch for s3://{bucket}/{key}")
    return head


def upload_s3(bucket, path, key, expected_checksum_b64, storage_class,
              threshold, chunk, concurrency):
    size = os.path.getsize(path)
    if size < threshold:
        resp = upload_singlepart(bucket, key, path, expected_checksum_b64, storage_class)
    else:
        resp = upload_multipart(bucket, key, path, storage_class, threshold, chunk, concurrency)
    head = verify_uploaded(bucket, key, expected_checksum_b64)
    return resp, head
