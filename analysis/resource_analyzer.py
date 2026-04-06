"""
analysis/resource_analyzer.py — Resource overview analysis and findings generation.
Owner: Person 1
Status: IMPLEMENTED (Epic 11)

Generates findings for:
  - S3 buckets with public access block disabled (critical)
  - Lambda functions with zero invocations in 7 days (unused)
  - Unattached Elastic IPs (cost waste)
  - Unattached EBS volumes (cost waste)
"""

import logging

logger = logging.getLogger(__name__)


def analyze_resources(
    s3_buckets: list,
    lambda_functions: list,
    other_resources: dict,
) -> dict:
    """
    Generate findings from S3, Lambda, and other resource data.

    Returns contract-compliant dict:
    {
        "overview": {
            "s3": {
                "total_buckets": int,
                "public_buckets": int,
                "findings": [str]
            },
            "lambda": {
                "total_functions": int,
                "unused_functions": int,
                "findings": [str]
            },
            "other": {
                "vpcs": int,
                "unattached_elastic_ips": int,
                "unattached_ebs_volumes": int,
                "findings": [str]
            }
        }
    }
    """
    s3_section = _analyze_s3(s3_buckets)
    lambda_section = _analyze_lambda(lambda_functions)
    other_section = _analyze_other(other_resources)

    return {
        "overview": {
            "s3": s3_section,
            "lambda": lambda_section,
            "other": other_section,
        }
    }


def _analyze_s3(buckets: list) -> dict:
    findings = []
    public_count = 0

    for b in buckets:
        blocked = b.get("public_access_blocked")
        if blocked is False:
            public_count += 1
            findings.append(
                f"Bucket '{b['name']}' has public access block disabled — "
                "it may be publicly accessible. Enable all four public access block settings."
            )

    return {
        "total_buckets": len(buckets),
        "public_buckets": public_count,
        "findings": findings,
    }


def _analyze_lambda(functions: list) -> dict:
    findings = []
    unused_count = 0

    for fn in functions:
        inv = fn.get("invocations_7d")
        if inv is not None and inv == 0:
            unused_count += 1
            findings.append(
                f"Lambda function '{fn['name']}' (runtime: {fn.get('runtime', 'unknown')}) "
                "has zero invocations in the past 7 days — consider removing it to reduce costs."
            )

    return {
        "total_functions": len(functions),
        "unused_functions": unused_count,
        "findings": findings,
    }


def _analyze_other(other: dict) -> dict:
    findings = []

    for eip in other.get("unattached_eip_details", []):
        findings.append(
            f"Elastic IP {eip.get('public_ip', '')} "
            f"(allocation: {eip.get('allocation_id', '')}) is unattached — "
            "you are being charged ~$0.005/hour. Release it if not needed."
        )

    for vol in other.get("unattached_ebs_details", []):
        findings.append(
            f"EBS volume {vol.get('volume_id', '')} ({vol.get('size_gb', 0)} GB) "
            "is unattached (status: available) — "
            "you are being charged for unused storage. Delete it if not needed."
        )

    return {
        "vpcs": other.get("vpcs", 0),
        "unattached_elastic_ips": other.get("unattached_elastic_ips", 0),
        "unattached_ebs_volumes": other.get("unattached_ebs_volumes", 0),
        "findings": findings,
    }
