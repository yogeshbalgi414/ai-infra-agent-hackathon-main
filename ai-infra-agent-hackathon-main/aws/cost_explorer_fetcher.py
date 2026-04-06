"""
aws/cost_explorer_fetcher.py — Real billing data via AWS Cost Explorer API.
Status: IMPLEMENTED

Fetches actual spend from ce:GetCostAndUsage — reflects Reserved Instance
discounts, Spot pricing, Savings Plans, and partial-month usage.
This is your real AWS bill, not a theoretical on-demand estimate.

Cost Explorer is a global service — always uses us-east-1 endpoint.
Requires ce:GetCostAndUsage IAM permission.
Returns None on any failure — callers must handle gracefully.

Period logic uses calendar month boundaries, not rolling day windows:
  - month=0 (default) → 1st of current month to today (month-to-date)
  - month=1           → full previous calendar month (e.g. all of March)
  - month=2           → two months ago (e.g. all of February — 28 days)
This ensures February always gets 28/29 days and March always gets 31 days.
"""

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# Cost Explorer is global — always us-east-1
_CE_REGION = "us-east-1"

# Service name mappings for cleaner output
_SERVICE_LABELS = {
    "Amazon Elastic Compute Cloud - Compute": "EC2 Compute",
    "EC2 - Other":                            "EC2 Other (EBS/data transfer)",
    "Amazon Relational Database Service":     "RDS",
    "Amazon Simple Storage Service":          "S3",
    "AWS Lambda":                             "Lambda",
    "Amazon CloudWatch":                      "CloudWatch",
    "Amazon Elastic Load Balancing":          "Load Balancing",
    "Amazon CloudFront":                      "CloudFront",
    "Amazon Route 53":                        "Route 53",
    "Amazon DynamoDB":                        "DynamoDB",
    "Amazon ElastiCache":                     "ElastiCache",
    "Amazon Elastic Container Service":       "ECS",
    "Amazon Elastic Kubernetes Service":      "EKS",
    "Amazon SageMaker":                       "SageMaker",
    "Amazon Simple Notification Service":     "SNS",
    "Amazon Simple Queue Service":            "SQS",
    "Amazon API Gateway":                     "API Gateway",
    "AWS Secrets Manager":                    "Secrets Manager",
    "AWS Key Management Service":             "KMS",
    "Amazon VPC":                             "VPC",
}


def _month_boundaries(months_back: int = 0):
    """
    Return (start, end) date objects for a calendar month period.

    months_back=0 → 1st of current month to today (month-to-date)
    months_back=1 → full previous calendar month
    months_back=2 → two months ago, etc.

    Examples (today = 2026-04-01):
        months_back=0 → (2026-04-01, 2026-04-01)  ← MTD, same day edge handled
        months_back=1 → (2026-03-01, 2026-04-01)  ← all of March (31 days)
        months_back=2 → (2026-02-01, 2026-03-01)  ← all of February (28 days)
        months_back=3 → (2026-01-01, 2026-02-01)  ← all of January (31 days)
    """
    today = date.today()

    # Start from the 1st of the target month
    year = today.year
    month = today.month - months_back

    # Roll back across year boundaries
    while month <= 0:
        month += 12
        year -= 1

    start = date(year, month, 1)

    if months_back == 0:
        # Month-to-date: end is today
        end = today
    else:
        # Full previous month: end is the 1st of the following month
        end_month = month + 1
        end_year = year
        if end_month > 12:
            end_month = 1
            end_year += 1
        end = date(end_year, end_month, 1)

    # Cost Explorer requires start < end
    if start >= end:
        # Edge case: today is the 1st of the month, MTD has zero days
        # Return yesterday as start so we get at least 1 day
        from datetime import timedelta
        start = end - timedelta(days=1)

    return start, end


def fetch_actual_cost(region: str, months_back: int = 0) -> Optional[dict]:
    """
    Fetch real billing data from AWS Cost Explorer for a calendar month period.

    Args:
        region:      AWS region (context only — CE is global)
        months_back: 0 = current month to date (default)
                     1 = full previous calendar month
                     2 = two months ago, etc.

    Returns:
        {
            "period_start": str,       # ISO date — 1st of the month
            "period_end":   str,       # ISO date — exclusive end
            "period_label": str,       # human-readable e.g. "March 2026"
            "total_usd":    float,
            "by_service":   [{"service": str, "cost_usd": float}],
            "currency":     "USD",
            "note":         str
        }
        or None if the API call fails.
    """
    try:
        from aws.client import get_client
        ce = get_client("ce", _CE_REGION)

        start, end = _month_boundaries(months_back)

        # Build a human-readable label
        if months_back == 0:
            period_label = f"{start.strftime('%B %Y')} (month to date)"
        else:
            period_label = start.strftime("%B %Y")

        # Human-readable display range — end is exclusive so show end-1 day
        from datetime import timedelta
        display_end = end - timedelta(days=1)
        display_range = (
            f"{start.strftime('%B %d, %Y')} – {display_end.strftime('%B %d, %Y')}"
        )

        response = ce.get_cost_and_usage(
            TimePeriod={
                "Start": start.isoformat(),
                "End": end.isoformat(),
            },
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        by_service = []
        total = 0.0

        for period in response.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                svc_raw = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if cost > 0:
                    svc_label = _SERVICE_LABELS.get(svc_raw, svc_raw)
                    by_service.append({"service": svc_label, "cost_usd": round(cost, 4)})
                    total += cost

        by_service.sort(key=lambda x: x["cost_usd"], reverse=True)

        logger.info(
            "Cost Explorer: $%.2f for %s (region context: %s)",
            total, period_label, region,
        )

        return {
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "period_label": period_label,
            "period_display": display_range,
            "total_usd": round(total, 2),
            "by_service": by_service,
            "currency": "USD",
            "note": (
                "This is your actual AWS bill for the period — it reflects "
                "Reserved Instance discounts, Spot pricing, Savings Plans, "
                "and partial-month usage. It covers your entire AWS account, "
                "not just the selected region."
            ),
        }

    except Exception as exc:
        logger.warning("Cost Explorer fetch failed: %s — returning None", exc)
        return None
