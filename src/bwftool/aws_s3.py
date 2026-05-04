import base64
import hashlib
import os
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger
import boto3
from typing_extensions import Literal

# logger.add(sys.stderr, level="TRACE")

s3_client = boto3.client("s3")


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
    logger.trace(f"doing multipart upload of {path}")
    file_size = os.path.getsize(path)
    part_count = math.ceil(file_size / part_size)

    out = s3_client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        StorageClass=storage_class,
        ChecksumAlgorithm="SHA256",
    )
    upload_id = out["UploadId"]

    def upload_part(part_number):
        logger.info(f"start upload of part {part_number}")
        offset = (part_number - 1) * part_size
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read(part_size)

        checksum_b64 = base64.b64encode(hashlib.sha256(chunk).digest()).decode("ascii")

        resp = s3_client.upload_part(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=chunk,
            ChecksumSHA256=checksum_b64,
        )

        logger.trace(f"finish upload of part {part_number} with {resp}")

        return {
            "PartNumber": part_number,
            "ETag": resp["ETag"],
            "ChecksumSHA256": checksum_b64,
            "Size": len(chunk),
        }

    parts = []
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(upload_part, part_number) for part_number in range(1, part_count + 1)]
            for future in as_completed(futures):
                parts.append(future.result())

        logger.trace("part uploads finished")
        parts.sort(key=lambda p: p["PartNumber"])

        complete_resp = s3_client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": [{"ETag": p["ETag"], "PartNumber": p["PartNumber"],
                                        "ChecksumSHA256": p["ChecksumSHA256"]} for p in parts]},
        )

        logger.trace("multipart upload completed")

        head_resp = s3_client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")

        return {
            "upload_id": upload_id,
            "parts": parts,
            "complete": complete_resp,
            "head": head_resp,
        }

    except Exception:  # TODO need to make this less generic
        logger.exception(f"failed to upload {path}")
        s3_client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        return None


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
        resp = upload_singlepart(bucket, key, path, None, storage_class)
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
        if resp is None:
            status = False
        else:
            status = True

    return resp, head, status
