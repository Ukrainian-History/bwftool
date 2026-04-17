import base64
import hashlib
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig
from typing_extensions import Literal

s3_client = boto3.client("s3", region_name=None)  # TODO region is None by default in the original AI slop


def to_key(path: str, root: str | None, prefix: str) -> str:
    p = Path(path)
    if root:
        rel = p.relative_to(Path(root))
        key = rel.as_posix()
    else:
        key = p.name
    return f"{prefix}{key}" if prefix else key


def upload_singlepart(bucket, key, path, checksum_b64, storage_class):
    return s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=path,
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


def upload_s3(bucket, path, key, expected_checksum_hex,
              storage_class: Literal["STANDARD", "INTELLIGENT_TIERING", "STANDARD_IA", "ONEZONE_IA",
              "GLACIER_IR", "GLACIER", "DEEP_ARCHIVE"], threshold, chunk, concurrency):
    expected_checksum_b64 = base64.b64encode(bytes.fromhex(expected_checksum_hex)).decode()

    size = os.path.getsize(path)
    if size < threshold:
        resp = upload_singlepart(bucket, key, path, expected_checksum_b64, storage_class)
    else:
        resp = upload_multipart(bucket, key, path, storage_class, threshold, chunk, concurrency)
    head = verify_uploaded(bucket, key, expected_checksum_b64)
    return resp, head
