"""
aws/resource_fetcher.py — VPC, Elastic IP, and EBS volume inventory fetching.
Owner: Person 1
Status: IMPLEMENTED (Epic 11)
"""

import logging

from aws.client import get_client

logger = logging.getLogger(__name__)


def fetch_other_resources(region: str) -> dict:
    """
    Fetch counts and details for VPCs, unattached Elastic IPs, and unattached EBS volumes.

    Each resource type is fetched independently — failure of one does not affect others.

    Returns dict with:
        vpcs:                     int  — total VPC count in region
        unattached_elastic_ips:   int  — count of EIPs not associated with any instance or ENI
        unattached_ebs_volumes:   int  — count of EBS volumes in 'available' state
        unattached_eip_details:   list[dict] — [{allocation_id, public_ip}]
        unattached_ebs_details:   list[dict] — [{volume_id, size_gb}]
    """
    ec2 = get_client("ec2", region)

    vpcs = _fetch_vpc_count(ec2)
    eip_details, eip_count = _fetch_unattached_eips(ec2)
    ebs_details, ebs_count = _fetch_unattached_ebs(ec2)

    return {
        "vpcs": vpcs,
        "unattached_elastic_ips": eip_count,
        "unattached_ebs_volumes": ebs_count,
        "unattached_eip_details": eip_details,
        "unattached_ebs_details": ebs_details,
    }


def _fetch_vpc_count(ec2_client) -> int:
    try:
        response = ec2_client.describe_vpcs()
        return len(response.get("Vpcs", []))
    except Exception as exc:
        logger.warning("Failed to fetch VPCs: %s", exc)
        return 0


def _fetch_unattached_eips(ec2_client) -> tuple:
    """
    Return (details_list, count) for EIPs not attached to any instance or network interface.
    """
    try:
        response = ec2_client.describe_addresses()
        unattached = [
            a for a in response.get("Addresses", [])
            if "InstanceId" not in a and "NetworkInterfaceId" not in a
        ]
        details = [
            {
                "allocation_id": a.get("AllocationId", ""),
                "public_ip": a.get("PublicIp", ""),
            }
            for a in unattached
        ]
        return details, len(details)
    except Exception as exc:
        logger.warning("Failed to fetch Elastic IPs: %s", exc)
        return [], 0


def _fetch_unattached_ebs(ec2_client) -> tuple:
    """
    Return (details_list, count) for EBS volumes in 'available' state (not attached).
    """
    try:
        response = ec2_client.describe_volumes(
            Filters=[{"Name": "status", "Values": ["available"]}]
        )
        volumes = response.get("Volumes", [])
        details = [
            {
                "volume_id": v["VolumeId"],
                "size_gb": v.get("Size", 0),
            }
            for v in volumes
        ]
        return details, len(details)
    except Exception as exc:
        logger.warning("Failed to fetch EBS volumes: %s", exc)
        return [], 0
