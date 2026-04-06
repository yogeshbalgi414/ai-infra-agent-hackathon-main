"""
aws/security_fetcher.py — Raw Security Group data fetching.
Owner: Person 2
Status: IMPLEMENTED (Epic 4)
"""

import logging

from aws.client import get_client

logger = logging.getLogger(__name__)


def fetch_security_groups(region: str) -> list:
    """
    Fetch all Security Groups attached to running EC2 instances in the region.

    Steps:
      1. Fetch all running EC2 instances via describe_instances (state=running)
      2. Collect all Security Group IDs attached to those instances, tracking
         which instance each SG is attached to
      3. Fetch full SG details via describe_security_groups
      4. Return list of (security_group, attached_instance_id) pairs

    Port extraction rules:
      - FromPort == ToPort → single port
      - FromPort != ToPort → port range; each sensitive port in range is checked
        by the analyzer, so we store FromPort as the representative port
      - IpProtocol == '-1' → all traffic; port stored as None

    Returns list of dicts:
        {
            'group_id': str,
            'group_name': str,
            'attached_instance_id': str,
            'inbound_rules': [
                {
                    'port': int | None,
                    'port_range_end': int | None,
                    'protocol': str,
                    'source_cidr': str | None,
                    'source_sg': str | None,
                }
            ]
        }
    """
    ec2 = get_client("ec2", region)

    # Step 1: Fetch running instances and collect SG IDs → instance mapping
    paginator = ec2.get_paginator("describe_instances")
    sg_to_instance: dict[str, str] = {}  # group_id → first attached instance_id

    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    ):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                instance_id = inst["InstanceId"]
                for sg in inst.get("SecurityGroups", []):
                    group_id = sg["GroupId"]
                    # Track each (group_id, instance_id) pair — one entry per attachment
                    # Use a list to preserve all instance associations
                    if group_id not in sg_to_instance:
                        sg_to_instance[group_id] = []
                    sg_to_instance[group_id].append(instance_id)

    if not sg_to_instance:
        logger.info("No running instances with Security Groups found in region %s", region)
        return []

    # Step 2: Fetch full SG details
    sg_ids = list(sg_to_instance.keys())
    response = ec2.describe_security_groups(GroupIds=sg_ids)

    results = []
    for sg in response.get("SecurityGroups", []):
        group_id = sg["GroupId"]
        group_name = sg.get("GroupName", group_id)
        inbound_rules = _extract_inbound_rules(sg.get("IpPermissions", []))

        # Emit one entry per attached instance (findings are traceable to instances)
        for instance_id in sg_to_instance.get(group_id, []):
            results.append({
                "group_id": group_id,
                "group_name": group_name,
                "attached_instance_id": instance_id,
                "inbound_rules": inbound_rules,
            })

    logger.info(
        "Fetched %d Security Group/instance pairs from region %s", len(results), region
    )
    return results


def _extract_inbound_rules(ip_permissions: list) -> list:
    """
    Convert boto3 IpPermissions into a flat list of rule dicts.

    Each IpPermission entry may have multiple IP ranges (CIDRs) and/or
    security group sources — we emit one rule dict per source.
    """
    rules = []
    for perm in ip_permissions:
        protocol = perm.get("IpProtocol", "-1")

        # All-traffic rule
        if protocol == "-1":
            port = None
            port_range_end = None
        else:
            port = perm.get("FromPort")
            port_range_end = perm.get("ToPort")
            # Normalise: if FromPort == ToPort it's a single port
            if port is not None and port_range_end is not None and port == port_range_end:
                port_range_end = None

        # IPv4 CIDR ranges
        for ip_range in perm.get("IpRanges", []):
            cidr = ip_range.get("CidrIp")
            if cidr:
                rules.append({
                    "port": port,
                    "port_range_end": port_range_end,
                    "protocol": protocol,
                    "source_cidr": cidr,
                    "source_sg": None,
                })

        # IPv6 CIDR ranges
        for ip_range in perm.get("Ipv6Ranges", []):
            cidr = ip_range.get("CidrIpv6")
            if cidr:
                rules.append({
                    "port": port,
                    "port_range_end": port_range_end,
                    "protocol": protocol,
                    "source_cidr": cidr,
                    "source_sg": None,
                })

        # Security Group sources
        for sg_pair in perm.get("UserIdGroupPairs", []):
            sg_id = sg_pair.get("GroupId")
            if sg_id:
                rules.append({
                    "port": port,
                    "port_range_end": port_range_end,
                    "protocol": protocol,
                    "source_cidr": None,
                    "source_sg": sg_id,
                })

    return rules
