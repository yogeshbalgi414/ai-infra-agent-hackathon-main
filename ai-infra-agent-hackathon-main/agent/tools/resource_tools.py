"""
agent/tools/resource_tools.py — Resource overview LangChain tool.
Owner: Person 1
Status: IMPLEMENTED (Epic 11)

Output contract:
{
  "overview": {
    "s3":     {"total_buckets": int, "public_buckets": int, "findings": [str]},
    "lambda": {"total_functions": int, "unused_functions": int, "findings": [str]},
    "other":  {"vpcs": int, "unattached_elastic_ips": int, "unattached_ebs_volumes": int, "findings": [str]}
  }
}
"""

import logging

from langchain_core.tools import tool

from aws.s3_fetcher import fetch_s3_buckets
from aws.lambda_fetcher import fetch_lambda_functions
from aws.resource_fetcher import fetch_other_resources
from analysis.resource_analyzer import analyze_resources

logger = logging.getLogger(__name__)

_EMPTY_OVERVIEW = {
    "overview": {
        "s3":     {"total_buckets": 0, "public_buckets": 0, "findings": []},
        "lambda": {"total_functions": 0, "unused_functions": 0, "findings": []},
        "other":  {"vpcs": 0, "unattached_elastic_ips": 0, "unattached_ebs_volumes": 0, "findings": []},
    }
}


@tool
def get_resource_overview(region: str) -> dict:
    """
    Fetch a resource overview for the given AWS region.
    Returns S3 bucket counts and public access findings, Lambda function counts
    and unused function findings, plus VPC, Elastic IP, and EBS volume counts.
    Use this tool when the user asks about S3, Lambda, VPCs, Elastic IPs,
    EBS volumes, or wants a general resource count summary.
    """
    try:
        # Each fetcher is wrapped independently — one failure doesn't block others
        try:
            s3_buckets = fetch_s3_buckets(region)
        except Exception as exc:
            logger.error("S3 fetch failed: %s", exc)
            s3_buckets = []

        try:
            lambda_functions = fetch_lambda_functions(region)
        except Exception as exc:
            logger.error("Lambda fetch failed: %s", exc)
            lambda_functions = []

        try:
            other_resources = fetch_other_resources(region)
        except Exception as exc:
            logger.error("Other resources fetch failed: %s", exc)
            other_resources = {
                "vpcs": 0,
                "unattached_elastic_ips": 0,
                "unattached_ebs_volumes": 0,
                "unattached_eip_details": [],
                "unattached_ebs_details": [],
            }

        result = analyze_resources(s3_buckets, lambda_functions, other_resources)
        logger.info(
            "Resource overview complete for %s: %d S3 buckets, %d Lambda functions",
            region, len(s3_buckets), len(lambda_functions),
        )
        return result

    except Exception as exc:
        logger.error("get_resource_overview failed for region %s: %s", region, exc)
        return {"error": str(exc), **_EMPTY_OVERVIEW}
