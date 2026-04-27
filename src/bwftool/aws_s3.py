import base64
import hashlib
import os
import math

import boto3
from typing_extensions import Literal

s3_client = boto3.client("s3", region_name=None)  # TODO region is None by default in the original AI slop


def upload_singlepart(bucket, key, path, checksum_b64, storage_class):
    if checksum_b64:
        return s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=open(path, "rb"),
            StorageClass=storage_class,
            ChecksumAlgorithm="SHA256",
            ChecksumSHA256=checksum_b64,
        )
    else:
        return s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=open(path, "rb"),
            StorageClass=storage_class,
        )


def upload_multipart(bucket, key, path, storage_class, part_size, concurrency):
    file_size = os.path.getsize(path)
    part_count = math.ceil(file_size / part_size)

    out = s3_client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        StorageClass=storage_class,
        ChecksumAlgorithm="SHA256",
    )
    upload_id = out["UploadId"]

    parts = []
    part_meta = []

    try:
        with open(path, "rb") as f:
            for part_number in range(1, part_count + 1):
                chunk = f.read(part_size)
                if not chunk:
                    break

                checksum_b64 = base64.b64encode(hashlib.sha256(chunk).digest()).decode("ascii")

                resp = s3_client.upload_part(
                    Bucket=bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=chunk,
                    ChecksumSHA256=checksum_b64,
                )

                parts.append({
                    "ETag": resp["ETag"],
                    "PartNumber": part_number,
                    "ChecksumSHA256": checksum_b64,
                })
                part_meta.append({
                    "part_number": part_number,
                    "size": len(chunk),
                    "checksum_sha256_b64": checksum_b64,
                })

        completed = s3_client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": [{"ETag": p["ETag"], "PartNumber": p["PartNumber"],
                                        "ChecksumSHA256": p["ChecksumSHA256"]} for p in parts]},
        )

        head = s3_client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")

        return {
            "upload_id": upload_id,
            "parts": part_meta,
            "complete": completed,
            "head": head,
        }

    except Exception:
        s3_client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        raise


def verify_uploaded(bucket, key, expected_checksum_b64):
    head = s3_client.head_object(
        Bucket=bucket,
        Key=key,
        ChecksumMode="ENABLED",
    )
    actual = head.get("ChecksumSHA256")
    if actual and actual != expected_checksum_b64:
        return head, None
    return head, True


def upload_s3(bucket, path, key, expected_checksum_hex,
              storage_class: Literal["STANDARD", "INTELLIGENT_TIERING", "STANDARD_IA", "ONEZONE_IA",
              "GLACIER_IR", "GLACIER", "DEEP_ARCHIVE"], threshold, part_size, concurrency):
    if expected_checksum_hex:
        expected_checksum_b64 = base64.b64encode(bytes.fromhex(expected_checksum_hex)).decode()
    else:
        expected_checksum_b64 = None

    size = os.path.getsize(path)
    if size < threshold:
        resp = upload_singlepart(bucket, key, path, expected_checksum_b64, storage_class)
        if expected_checksum_b64:
            head, status = verify_uploaded(bucket, key, expected_checksum_b64)
            if status is None:
                s3_client.delete_object(Bucket=bucket, Key=key)
        else:
            head = None
            status = True
    else:
        resp = upload_multipart(bucket, key, path, storage_class, part_size, concurrency)
        head = None
        status = True

    return resp, head, status
