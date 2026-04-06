"""
aws/lambda_fetcher.py — Lambda function inventory and CloudWatch invocation fetching.
Owner: Person 1
Status: IMPLEMENTED (Epic 11)
"""

import logging
from datetime import datetime, timedelta, timezone

from aws.client import get_client

logger = logging.getLogger(__name__)

METRICS_WINDOW_DAYS = 7
METRICS_PERIOD_SECONDS = 86400  # 1-day granularity for invocation counts


def fetch_lambda_functions(region: str) -> list:
    """
    Fetch all Lambda functions in the given region and their 7-day invocation counts.

    Uses list_functions paginator. Fetches CloudWatch Invocations (Sum) per function
    over the past 7 days at 1-day granularity.

    Returns list of dicts with:
        name:           str   — function name
        runtime:        str   — e.g. "python3.11", "nodejs18.x"
        last_modified:  str   — ISO format last modified date
        invocations_7d: float | None — total invocations over 7 days, None if no data
    """
    lmb = get_client("lambda", region)
    cw = get_client("cloudwatch", region)

    try:
        paginator = lmb.get_paginator("list_functions")
    except Exception as exc:
        logger.warning("Failed to list Lambda functions in %s: %s", region, exc)
        return []

    functions = []
    for page in paginator.paginate():
        for fn in page.get("Functions", []):
            name = fn["FunctionName"]
            invocations = _fetch_invocations(cw, name)
            functions.append({
                "name": name,
                "runtime": fn.get("Runtime", "unknown"),
                "last_modified": fn.get("LastModified", ""),
                "invocations_7d": invocations,
            })

    logger.info("Fetched %d Lambda functions from region %s", len(functions), region)
    return functions


def _fetch_invocations(cw_client, function_name: str) -> float | None:
    """
    Fetch total Lambda invocations over the past 7 days using CloudWatch Sum stat.

    Returns total sum across all daily datapoints, or None if no datapoints exist.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=METRICS_WINDOW_DAYS)

    try:
        response = cw_client.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName="Invocations",
            Dimensions=[{"Name": "FunctionName", "Value": function_name}],
            StartTime=start,
            EndTime=end,
            Period=METRICS_PERIOD_SECONDS,
            Statistics=["Sum"],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return None
        return round(sum(d["Sum"] for d in datapoints), 2)

    except Exception as exc:
        logger.warning("Failed to fetch invocations for %s: %s", function_name, exc)
        return None
