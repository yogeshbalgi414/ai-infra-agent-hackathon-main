"""
aws/rds_fetcher.py — Raw RDS and CloudWatch data fetching.
Owner: Person 2
Status: IMPLEMENTED (Epic 3)
"""

import logging
from datetime import datetime, timedelta, timezone

from aws.client import get_client

logger = logging.getLogger(__name__)

METRICS_WINDOW_DAYS = 7
METRICS_PERIOD_SECONDS = 3600  # 1-hour granularity


def fetch_rds_instances(region: str) -> list:
    """
    Fetch all RDS instances in the given region using describe_db_instances paginator.

    Returns list of dicts with:
        id, name, class, engine, status, multi_az, backups_enabled, allocated_storage_gb
    """
    rds = get_client("rds", region)
    paginator = rds.get_paginator("describe_db_instances")
    instances = []

    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]

            # Name tag — fallback to DBInstanceIdentifier
            tags = {t["Key"]: t["Value"] for t in db.get("TagList", [])}
            name = tags.get("Name", db_id)

            instances.append({
                "id": db_id,
                "name": name,
                "class": db.get("DBInstanceClass", "unknown"),
                "engine": db.get("Engine", "unknown"),
                "status": db.get("DBInstanceStatus", "unknown"),
                "multi_az": db.get("MultiAZ", False),
                "backups_enabled": db.get("BackupRetentionPeriod", 0) > 0,
                "allocated_storage_gb": db.get("AllocatedStorage", 0),
            })

    logger.info("Fetched %d RDS instances from region %s", len(instances), region)
    return instances


def fetch_rds_metrics(db_id: str, region: str, allocated_storage_gb: int = 0) -> dict:
    """
    Fetch 6 CloudWatch metrics for a single RDS instance over the past 7 days
    at 1-hour granularity.

    Metrics fetched (Namespace: AWS/RDS):
        CPUUtilization      → Average → cpu_avg_7d
        DatabaseConnections → Average → connections_avg_7d
        ReadIOPS            → Average → read_iops_avg_7d
        WriteIOPS           → Average → write_iops_avg_7d
        FreeStorageSpace    → Minimum → free_storage_pct  (converted from bytes)
        FreeableMemory      → Average → freeable_memory_mb (converted from bytes)

    free_storage_pct = (FreeStorageSpace_min / (allocated_storage_gb * 1e9)) * 100
    freeable_memory_mb = raw_bytes / 1e6

    Returns None (not 0) for any metric with no datapoints.
    data_available_days = count of distinct calendar days with at least one datapoint
    across all metrics combined.
    """
    cw = get_client("cloudwatch", region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=METRICS_WINDOW_DAYS)

    # (metric_name, stat, output_field, unit)
    metrics_to_fetch = [
        ("CPUUtilization",      "Average", "cpu_avg_7d",          None),
        ("DatabaseConnections", "Average", "connections_avg_7d",  None),
        ("ReadIOPS",            "Average", "read_iops_avg_7d",    None),
        ("WriteIOPS",           "Average", "write_iops_avg_7d",   None),
        ("FreeStorageSpace",    "Minimum", "_free_storage_bytes", None),
        ("FreeableMemory",      "Average", "_freeable_memory_bytes", None),
    ]

    raw = {}
    all_dates = set()

    for metric_name, stat, field_name, _ in metrics_to_fetch:
        try:
            response = cw.get_metric_statistics(
                Namespace="AWS/RDS",
                MetricName=metric_name,
                Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
                StartTime=start,
                EndTime=end,
                Period=METRICS_PERIOD_SECONDS,
                Statistics=[stat],
            )
            datapoints = response.get("Datapoints", [])

            if datapoints:
                value = sum(d[stat] for d in datapoints) / len(datapoints)
                raw[field_name] = value
                for dp in datapoints:
                    ts = dp["Timestamp"]
                    if hasattr(ts, "date"):
                        all_dates.add(ts.date())
            else:
                raw[field_name] = None

        except Exception as exc:
            logger.warning("Failed to fetch %s for %s: %s", metric_name, db_id, exc)
            raw[field_name] = None

    # Convert raw bytes to derived fields
    free_storage_bytes = raw.pop("_free_storage_bytes", None)
    freeable_memory_bytes = raw.pop("_freeable_memory_bytes", None)

    if free_storage_bytes is not None and allocated_storage_gb and allocated_storage_gb > 0:
        free_storage_pct = (free_storage_bytes / (allocated_storage_gb * 1e9)) * 100
        raw["free_storage_pct"] = round(free_storage_pct, 2)
    else:
        raw["free_storage_pct"] = None

    if freeable_memory_bytes is not None:
        raw["freeable_memory_mb"] = round(freeable_memory_bytes / 1e6, 2)
    else:
        raw["freeable_memory_mb"] = None

    # Round numeric metrics
    for field in ("cpu_avg_7d", "connections_avg_7d", "read_iops_avg_7d", "write_iops_avg_7d"):
        if raw.get(field) is not None:
            raw[field] = round(raw[field], 4)

    raw["data_available_days"] = len(all_dates)
    return raw
