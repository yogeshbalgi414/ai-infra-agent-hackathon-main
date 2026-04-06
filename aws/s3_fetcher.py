"""
aws/s3_fetcher.py — S3 bucket inventory and public access status fetching.
Owner: Person 1
Status: IMPLEMENTED (Epic 11)

S3 is a global service — list_buckets returns all buckets regardless of region.
The region parameter is used only for boto3 client creation.
"""

import logging

from aws.client import get_client

logger = logging.getLogger(__name__)


def fetch_s3_buckets(region: str) -> list:
    """
    Fetch all S3 buckets in the account and check public access block status.

    S3 is global — all buckets are returned regardless of the region parameter.
    get_public_access_block is called per bucket to determine public access status.

    Returns list of dicts with:
        name:                  str — bucket name
        created_at:            str — ISO format creation date
        public_access_blocked: bool | None
            True  — all four public access block settings are enabled
            False — at least one setting is disabled (bucket may be public)
            None  — could not determine (API error other than NoSuchPublicAccessBlockConfiguration)
    """
    s3 = get_client("s3", region)
    buckets = []

    try:
        response = s3.list_buckets()
    except Exception as exc:
        logger.warning("Failed to list S3 buckets: %s", exc)
        return []

    for b in response.get("Buckets", []):
        name = b["Name"]
        created_at = b["CreationDate"].isoformat() if b.get("CreationDate") else None

        public_access_blocked = _get_public_access_blocked(s3, name)

        buckets.append({
            "name": name,
            "created_at": created_at,
            "public_access_blocked": public_access_blocked,
        })

    logger.info("Fetched %d S3 buckets", len(buckets))
    return buckets


def _get_public_access_blocked(s3_client, bucket_name: str) -> bool | None:
    """
    Check whether all four public access block settings are enabled for a bucket.

    Returns:
        True  — all four settings enabled (bucket is not publicly accessible)
        False — no block config exists OR at least one setting is disabled
        None  — unexpected API error (status unknown)
    """
    try:
        response = s3_client.get_public_access_block(Bucket=bucket_name)
        config = response.get("PublicAccessBlockConfiguration", {})
        return all([
            config.get("BlockPublicAcls", False),
            config.get("IgnorePublicAcls", False),
            config.get("BlockPublicPolicy", False),
            config.get("RestrictPublicBuckets", False),
        ])
    except s3_client.exceptions.NoSuchPublicAccessBlockConfiguration:
        # No block config at all — public access is NOT blocked
        return False
    except Exception as exc:
        logger.warning("Could not get public access block for bucket %s: %s", bucket_name, exc)
        return None
