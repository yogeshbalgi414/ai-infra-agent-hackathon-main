"""
aws/pricing_fetcher.py — Dynamic EC2 and RDS on-demand price fetching via AWS Pricing API.
Owner: Issue 42
Status: IMPLEMENTED

All boto3 clients are created via get_client() from aws/client.py.
The AWS Pricing API is a global service only available through us-east-1,
but can retrieve pricing for any region.

Results are cached in-memory per session to avoid redundant API calls.
Returns None on any failure — callers must implement fallback to hardcoded values.
"""

import json
import logging
from typing import Optional

from aws.client import get_client

logger = logging.getLogger(__name__)

# The AWS Pricing API is only accessible in us-east-1
PRICING_REGION = "us-east-1"

# Mapping from AWS region code to the human-readable name used in Pricing API filters
REGION_NAMES = {
    "us-east-1":      "US East (N. Virginia)",
    "us-east-2":      "US East (Ohio)",
    "us-west-1":      "US West (N. California)",
    "us-west-2":      "US West (Oregon)",
    "ca-central-1":   "Canada (Central)",
    "eu-west-1":      "Europe (Ireland)",
    "eu-west-2":      "Europe (London)",
    "eu-west-3":      "Europe (Paris)",
    "eu-central-1":   "Europe (Frankfurt)",
    "eu-north-1":     "Europe (Stockholm)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-south-1":     "Asia Pacific (Mumbai)",
    "sa-east-1":      "South America (Sao Paulo)",
}

# In-memory caches — keyed by (instance_type, region, os) and (instance_class, region, engine)
_ec2_price_cache: dict = {}
_rds_price_cache: dict = {}


def fetch_ec2_price(
    instance_type: str,
    region: str,
    operating_system: str = "Linux",
) -> Optional[float]:
    """
    Fetch the on-demand hourly price (USD) for an EC2 instance type in the given region.

    Uses the AWS Pricing API via get_client("pricing", PRICING_REGION).
    Results are cached in-memory by (instance_type, region, operating_system).

    Args:
        instance_type:    EC2 instance type, e.g. "m5.xlarge"
        region:           AWS region code, e.g. "us-east-1"
        operating_system: OS string for the filter, default "Linux"

    Returns:
        Hourly on-demand price as a float, or None if the API call fails or
        no matching price is found.
    """
    cache_key = (instance_type, region, operating_system)
    if cache_key in _ec2_price_cache:
        return _ec2_price_cache[cache_key]

    try:
        region_name = REGION_NAMES.get(region, region)
        client = get_client("pricing", PRICING_REGION)
        response = client.get_products(
            ServiceCode="AmazonEC2",
            FormatVersion="aws_v1",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType",    "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "location",        "Value": region_name},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
                {"Type": "TERM_MATCH", "Field": "tenancy",         "Value": "Shared"},
                {"Type": "TERM_MATCH", "Field": "capacityStatus",  "Value": "Used"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw",  "Value": "NA"},
            ],
        )
        price = _extract_on_demand_price(response)
        if price is not None:
            _ec2_price_cache[cache_key] = price
        return price

    except Exception as exc:
        logger.warning(
            "Failed to fetch EC2 price for %s in %s: %s — will use hardcoded fallback",
            instance_type, region, exc,
        )
        return None


def fetch_rds_price(
    instance_class: str,
    region: str,
    database_engine: str = "MySQL",
) -> Optional[float]:
    """
    Fetch the on-demand hourly price (USD) for an RDS instance class in the given region.

    Fetches Single-AZ pricing. Multi-AZ callers should apply a 2x multiplier.
    Uses the AWS Pricing API via get_client("pricing", PRICING_REGION).
    Results are cached in-memory by (instance_class, region, database_engine).

    Args:
        instance_class:  RDS instance class, e.g. "db.m5.large"
        region:          AWS region code, e.g. "us-east-1"
        database_engine: Engine string for the filter, default "MySQL"

    Returns:
        Hourly on-demand Single-AZ price as a float, or None if the API call fails or
        no matching price is found.
    """
    cache_key = (instance_class, region, database_engine)
    if cache_key in _rds_price_cache:
        return _rds_price_cache[cache_key]

    try:
        region_name = REGION_NAMES.get(region, region)
        client = get_client("pricing", PRICING_REGION)
        response = client.get_products(
            ServiceCode="AmazonRDS",
            FormatVersion="aws_v1",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType",     "Value": instance_class},
                {"Type": "TERM_MATCH", "Field": "location",         "Value": region_name},
                {"Type": "TERM_MATCH", "Field": "databaseEngine",   "Value": database_engine},
                {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": "Single-AZ"},
            ],
        )
        price = _extract_on_demand_price(response)
        if price is not None:
            _rds_price_cache[cache_key] = price
        return price

    except Exception as exc:
        logger.warning(
            "Failed to fetch RDS price for %s in %s: %s — will use hardcoded fallback",
            instance_class, region, exc,
        )
        return None


def _extract_on_demand_price(response: dict) -> Optional[float]:
    """
    Extract the on-demand hourly USD price from a Pricing API get_products response.

    The PriceList items may be JSON strings or already-parsed dicts.
    Returns the first positive USD price found, or None if none is found.
    """
    price_list = response.get("PriceList", [])
    if not price_list:
        return None

    for item_raw in price_list:
        item = json.loads(item_raw) if isinstance(item_raw, str) else item_raw
        on_demand = item.get("terms", {}).get("OnDemand", {})
        for term in on_demand.values():
            for dim in term.get("priceDimensions", {}).values():
                usd_str = dim.get("pricePerUnit", {}).get("USD", "0")
                try:
                    price = float(usd_str)
                    if price > 0:
                        return price
                except (ValueError, TypeError):
                    continue

    return None


def clear_cache() -> None:
    """Clear the in-memory pricing cache. Primarily used in tests."""
    _ec2_price_cache.clear()
    _rds_price_cache.clear()
