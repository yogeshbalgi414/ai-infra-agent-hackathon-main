"""
aws/ec2_fetcher.py — Raw EC2 and CloudWatch data fetching.
Owner: Person 1
Status: IMPLEMENTED (Epic 2, revised post-Epic-2 review)
"""

import logging
from datetime import datetime, timedelta, timezone

from aws.client import get_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

METRICS_WINDOW_DAYS = 7
METRICS_PERIOD_SECONDS = 3600  # 1-hour granularity
INSUFFICIENT_DATA_THRESHOLD = 3  # days


# ---------------------------------------------------------------------------
# Reserved instance cross-reference
# ---------------------------------------------------------------------------

def _fetch_reserved_instance_keys(ec2_client) -> set:
    """
    Call describe_reserved_instances() and return a set of
    (instance_type, availability_zone) tuples for all active reservations.

    This set is used to cross-reference running instances and determine
    whether they are covered by a reservation.

    Only 'active' state reservations are included.
    """
    reserved_keys = set()
    try:
        response = ec2_client.describe_reserved_instances(
            Filters=[{"Name": "state", "Values": ["active"]}]
        )
        for ri in response.get("ReservedInstances", []):
            instance_type = ri.get("InstanceType", "")
            az = ri.get("AvailabilityZone", "")
            if instance_type and az:
                reserved_keys.add((instance_type, az))
    except Exception as exc:
        # Non-fatal — if this call fails, fall back to on-demand for all instances
        logger.warning("Could not fetch reserved instances: %s — defaulting all to on-demand", exc)
    return reserved_keys


# ---------------------------------------------------------------------------
# Instance inventory
# ---------------------------------------------------------------------------

def fetch_ec2_instances(region: str) -> list:
    """
    Fetch all EC2 instances in the given region using a paginator.

    Purchasing type derivation (in priority order):
      1. InstanceLifecycle == 'spot'  → 'spot'
      2. Cross-reference with describe_reserved_instances() by
         (instance_type, availability_zone) match → 'reserved'
      3. Default → 'on-demand'

    days_in_current_state is derived from StateTransitionReason when available,
    otherwise falls back to days since LaunchTime.

    Returns list of dicts matching the raw instance shape consumed by ec2_analyzer.
    """
    ec2 = get_client("ec2", region)

    # Fetch active reserved instance keys once for the whole region
    reserved_keys = _fetch_reserved_instance_keys(ec2)

    paginator = ec2.get_paginator("describe_instances")
    instances = []
    now = datetime.now(timezone.utc)

    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}]
    ):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                instance_id = inst["InstanceId"]

                # Name tag — fallback to instance ID
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                name = tags.get("Name", instance_id)

                # State
                state = inst.get("State", {}).get("Name", "unknown")

                # Instance type and AZ for reserved cross-reference
                instance_type = inst.get("InstanceType", "unknown")
                az = inst.get("Placement", {}).get("AvailabilityZone", "")

                # Purchasing type — spot check first (InstanceLifecycle field),
                # then reserved cross-reference, then default on-demand
                lifecycle = inst.get("InstanceLifecycle", "")
                if lifecycle == "spot":
                    purchasing_type = "spot"
                elif (instance_type, az) in reserved_keys:
                    purchasing_type = "reserved"
                else:
                    purchasing_type = "on-demand"

                # Launch time
                launch_time = inst.get("LaunchTime")
                launch_time_iso = launch_time.isoformat() if launch_time else None

                # days_in_current_state
                days_in_state = _parse_days_in_state(
                    inst.get("StateTransitionReason", ""), launch_time, now
                )

                instances.append({
                    "id": instance_id,
                    "name": name,
                    "type": instance_type,
                    "state": state,
                    "purchasing_type": purchasing_type,
                    "launch_time": launch_time_iso,
                    "days_in_current_state": days_in_state,
                })

    logger.info("Fetched %d EC2 instances from region %s", len(instances), region)
    return instances


def _parse_days_in_state(reason: str, launch_time, now: datetime) -> int:
    """
    Parse StateTransitionReason to extract days since last state change.
    Format example: "User initiated (2024-01-15 10:30:00 GMT)"
    Falls back to days since launch_time if parsing fails.
    """
    import re
    match = re.search(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} GMT)\)", reason)
    if match:
        try:
            ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S GMT")
            ts = ts.replace(tzinfo=timezone.utc)
            return max(0, (now - ts).days)
        except ValueError:
            pass

    if launch_time:
        if launch_time.tzinfo is None:
            launch_time = launch_time.replace(tzinfo=timezone.utc)
        return max(0, (now - launch_time).days)

    return 0


# ---------------------------------------------------------------------------
# CloudWatch metrics
# ---------------------------------------------------------------------------

def fetch_ec2_metrics(instance_id: str, region: str) -> dict:
    """
    Fetch 4 CloudWatch metrics for a single EC2 instance over the past 7 days
    at 1-hour granularity.

    Returns:
        {
            'cpu_avg_7d': float | None,
            'network_in_avg_7d': float | None,
            'network_out_avg_7d': float | None,
            'disk_read_ops_avg_7d': float | None,
            'data_available_days': int
        }

    Returns None (not 0) for any metric with no datapoints.
    data_available_days = count of distinct calendar days with at least one datapoint
    across all metrics combined.
    """
    cw = get_client("cloudwatch", region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=METRICS_WINDOW_DAYS)

    metrics_to_fetch = [
        ("CPUUtilization", "cpu_avg_7d", "Percent"),
        ("NetworkIn", "network_in_avg_7d", "Bytes"),
        ("NetworkOut", "network_out_avg_7d", "Bytes"),
        ("DiskReadOps", "disk_read_ops_avg_7d", "Count"),
    ]

    result = {}
    all_dates = set()

    for metric_name, field_name, _ in metrics_to_fetch:
        try:
            response = cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName=metric_name,
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start,
                EndTime=end,
                Period=METRICS_PERIOD_SECONDS,
                Statistics=["Average"],
            )
            datapoints = response.get("Datapoints", [])

            if datapoints:
                avg = sum(d["Average"] for d in datapoints) / len(datapoints)
                result[field_name] = round(avg, 4)
                for dp in datapoints:
                    ts = dp["Timestamp"]
                    if hasattr(ts, "date"):
                        all_dates.add(ts.date())
            else:
                result[field_name] = None

        except Exception as exc:
            logger.warning(
                "Failed to fetch %s for %s: %s", metric_name, instance_id, exc
            )
            result[field_name] = None

    result["data_available_days"] = len(all_dates)
    return result
