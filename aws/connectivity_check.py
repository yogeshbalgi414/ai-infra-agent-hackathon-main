"""
aws/connectivity_check.py — Verifies AWS/LocalStack connectivity.
Owner: Senior
Status: IMPLEMENTED (Epic 1)

Run directly: python -m aws.connectivity_check
"""

import os
import logging
from aws.client import get_client

logger = logging.getLogger(__name__)


def check_connectivity(region: str = None) -> dict:
    """
    Verify AWS connectivity by calling STS GetCallerIdentity.

    Args:
        region: AWS region to use. Defaults to AWS_REGION env var, then 'us-east-1'.

    Returns:
        On success: {
            'status': 'ok',
            'account_id': str,
            'arn': str,
            'user_id': str,
            'endpoint': str   # 'real AWS' or the LocalStack URL
        }
        On failure: {
            'status': 'error',
            'message': str
        }
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")

    # Check for required env vars and give specific messages
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        return {
            "status": "error",
            "message": "AWS_ACCESS_KEY_ID environment variable is not set.",
        }
    if not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return {
            "status": "error",
            "message": "AWS_SECRET_ACCESS_KEY environment variable is not set.",
        }

    try:
        sts = get_client("sts", region)
        identity = sts.get_caller_identity()
        endpoint = os.environ.get("AWS_ENDPOINT_URL", "real AWS")
        return {
            "status": "ok",
            "account_id": identity["Account"],
            "arn": identity["Arn"],
            "user_id": identity["UserId"],
            "endpoint": endpoint,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def main():
    """CLI entry point — prints connectivity result."""
    # Load .env if present (development convenience)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    result = check_connectivity()
    if result["status"] == "ok":
        endpoint = result["endpoint"]
        print(f"[OK] Connected to {endpoint}")
        print(f"     Account ID : {result['account_id']}")
        print(f"     ARN        : {result['arn']}")
    else:
        print(f"[ERROR] {result['message']}")


if __name__ == "__main__":
    main()
