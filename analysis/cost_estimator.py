"""
analysis/cost_estimator.py — Monthly cost estimation and savings calculation.
Owner: Person 1 (EC2), Person 2 (RDS)
Status: IMPLEMENTED (Epic 2 — EC2; Epic 3 — RDS; Issue 42 — dynamic pricing)

Pricing source: AWS Pricing API (dynamic, fetched via aws/pricing_fetcher.py).
Falls back to hardcoded us-east-1 on-demand prices when the API is unavailable.
Multiply hourly rate × 730 hours for monthly estimate.
"""

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EC2 on-demand hourly pricing (us-east-1, Linux)
# ---------------------------------------------------------------------------

EC2_HOURLY_PRICES = {
    "t3.nano":    0.0052,
    "t3.micro":   0.0104,
    "t3.small":   0.0208,
    "t3.medium":  0.0416,
    "t3.large":   0.0832,
    "t3.xlarge":  0.1664,
    "t3.2xlarge": 0.3328,
    "m5.large":   0.096,
    "m5.xlarge":  0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "r5.large":   0.126,
    "r5.xlarge":  0.252,
    "r5.2xlarge": 0.504,
}

# ---------------------------------------------------------------------------
# RDS on-demand hourly pricing (us-east-1, single-AZ)
# Multi-AZ doubles the price — pass multi_az=True to estimate_rds_monthly_cost
# ---------------------------------------------------------------------------

RDS_HOURLY_PRICES = {
    "db.t3.micro":  0.017,
    "db.t3.small":  0.034,
    "db.t3.medium": 0.068,
    "db.t3.large":  0.136,
    "db.m5.large":  0.171,
    "db.m5.xlarge": 0.342,
    "db.r5.large":  0.24,
    "db.r5.xlarge": 0.48,
}

HOURS_PER_MONTH = 730

_DEFAULT_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# EC2 cost functions
# ---------------------------------------------------------------------------

def estimate_ec2_monthly_cost(instance_type: str, region: str = None) -> float:
    """
    Return estimated monthly on-demand cost in USD for the given EC2 instance type.

    Attempts to fetch the price dynamically from the AWS Pricing API.
    Falls back to the hardcoded EC2_HOURLY_PRICES dictionary when the API is
    unavailable or returns no result.

    Returns 0.0 for unknown types and logs a warning — does not crash.
    """
    active_region = region or _DEFAULT_REGION

    try:
        from aws.pricing_fetcher import fetch_ec2_price
        hourly = fetch_ec2_price(instance_type, active_region)
    except Exception as exc:
        logger.warning("pricing_fetcher unavailable for EC2 %s: %s — using hardcoded", instance_type, exc)
        hourly = None

    if hourly is None:
        hourly = EC2_HOURLY_PRICES.get(instance_type)
        if hourly is None:
            logger.warning("Unknown EC2 instance type for pricing: %s — returning 0.0", instance_type)
            return 0.0

    return round(hourly * HOURS_PER_MONTH, 2)


def estimate_ec2_savings(current_type: str, target_type: str, region: str = None) -> float:
    """
    Return estimated monthly savings in USD from downsizing current_type to target_type.
    Returns 0.0 if either type is unknown.
    """
    return round(
        estimate_ec2_monthly_cost(current_type, region=region)
        - estimate_ec2_monthly_cost(target_type, region=region), 2
    )


# ---------------------------------------------------------------------------
# RDS cost functions (added in Epic 3)
# ---------------------------------------------------------------------------

def estimate_rds_monthly_cost(instance_class: str, multi_az: bool = False, region: str = None) -> float:
    """
    Return estimated monthly on-demand cost in USD for the given RDS instance class.
    Doubles the price when multi_az=True (2x multiplier applied to single-AZ price).

    Attempts to fetch the price dynamically from the AWS Pricing API.
    Falls back to the hardcoded RDS_HOURLY_PRICES dictionary when the API is
    unavailable or returns no result.

    Returns 0.0 for unknown classes and logs a warning — does not crash.
    """
    active_region = region or _DEFAULT_REGION

    try:
        from aws.pricing_fetcher import fetch_rds_price
        hourly = fetch_rds_price(instance_class, active_region)
    except Exception as exc:
        logger.warning("pricing_fetcher unavailable for RDS %s: %s — using hardcoded", instance_class, exc)
        hourly = None

    if hourly is None:
        hourly = RDS_HOURLY_PRICES.get(instance_class)
        if hourly is None:
            logger.warning("Unknown RDS instance class for pricing: %s — returning 0.0", instance_class)
            return 0.0

    multiplier = 2.0 if multi_az else 1.0
    return round(hourly * HOURS_PER_MONTH * multiplier, 2)


# ---------------------------------------------------------------------------
# Cost summary aggregation (added in Epic 6)
# ---------------------------------------------------------------------------

def build_cost_summary(ec2_results: dict, rds_results: dict) -> dict:
    """
    Aggregate cost data from EC2 and RDS tool outputs.

    Returns:
        {
            'total_monthly_spend_usd': float,
            'total_monthly_waste_usd': float,
            'potential_annual_savings_usd': float,
            'top_3_actions': [{'id', 'name', 'waste_usd', 'reason'}]
        }
    """
    ec2_results = ec2_results or {}
    rds_results = rds_results or {}
    all_instances = (
        list(ec2_results.get("instances") or []) + list(rds_results.get("instances") or [])
    )

    total_spend = sum(i.get("monthly_cost_usd", 0.0) for i in all_instances)

    waste_items = []
    for inst in all_instances:
        cls = inst.get("classification")
        if cls == "idle":
            waste_items.append({
                "id": inst.get("id", ""),
                "name": inst.get("name", ""),
                "waste_usd": inst.get("monthly_cost_usd", 0.0),
                "reason": "idle",
            })
        elif cls == "overprovisioned":
            savings = inst.get("savings_usd") or 0.0
            if savings > 0:
                waste_items.append({
                    "id": inst.get("id", ""),
                    "name": inst.get("name", ""),
                    "waste_usd": savings,
                    "reason": "overprovisioned",
                })

    waste_items.sort(key=lambda x: x["waste_usd"], reverse=True)
    total_waste = sum(w["waste_usd"] for w in waste_items)

    return {
        "total_monthly_spend_usd": round(total_spend, 2),
        "total_monthly_waste_usd": round(total_waste, 2),
        "potential_annual_savings_usd": round(total_waste * 12, 2),
        "top_3_actions": waste_items[:3],
    }
