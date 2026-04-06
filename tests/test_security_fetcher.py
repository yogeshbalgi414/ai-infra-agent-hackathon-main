"""
tests/test_security_fetcher.py — Unit tests for aws/security_fetcher.py.
Owner: Person 2
Status: IMPLEMENTED (Epic 4)
"""

import pytest
from unittest.mock import MagicMock, patch

from aws.security_fetcher import fetch_security_groups, _extract_inbound_rules


# ---------------------------------------------------------------------------
# Helpers — mock boto3 responses
# ---------------------------------------------------------------------------

def _make_instance(instance_id, sg_ids):
    """Build a minimal boto3 instance dict with the given Security Group IDs."""
    return {
        "InstanceId": instance_id,
        "SecurityGroups": [{"GroupId": sg_id, "GroupName": sg_id} for sg_id in sg_ids],
    }


def _make_sg(group_id, group_name, ip_permissions=None):
    """Build a minimal boto3 Security Group dict."""
    return {
        "GroupId": group_id,
        "GroupName": group_name,
        "IpPermissions": ip_permissions or [],
    }


def _make_paginator(instances):
    """Wrap instances in the boto3 describe_instances page structure."""
    page = {
        "Reservations": [
            {"Instances": [inst]} for inst in instances
        ]
    }
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [page]
    return mock_paginator


def _run_fetch(instances, security_groups, region="us-east-1"):
    """
    Helper: mock get_client, paginator, and describe_security_groups,
    then call fetch_security_groups and return the result list.
    """
    mock_ec2 = MagicMock()
    mock_ec2.get_paginator.return_value = _make_paginator(instances)
    mock_ec2.describe_security_groups.return_value = {
        "SecurityGroups": security_groups
    }

    with patch("aws.security_fetcher.get_client", return_value=mock_ec2):
        return fetch_security_groups(region)


# ---------------------------------------------------------------------------
# Basic fetching
# ---------------------------------------------------------------------------

class TestFetchSecurityGroupsBasic:
    def test_returns_list(self):
        result = _run_fetch([], [])
        assert isinstance(result, list)

    def test_no_instances_returns_empty(self):
        result = _run_fetch([], [])
        assert result == []

    def test_single_instance_single_sg(self):
        instances = [_make_instance("i-001", ["sg-001"])]
        sgs = [_make_sg("sg-001", "my-sg")]
        result = _run_fetch(instances, sgs)
        assert len(result) == 1
        assert result[0]["group_id"] == "sg-001"
        assert result[0]["attached_instance_id"] == "i-001"

    def test_result_has_all_required_fields(self):
        instances = [_make_instance("i-001", ["sg-001"])]
        sgs = [_make_sg("sg-001", "my-sg")]
        result = _run_fetch(instances, sgs)
        r = result[0]
        for field in ("group_id", "group_name", "attached_instance_id", "inbound_rules"):
            assert field in r, f"Missing field: {field}"

    def test_group_name_is_populated(self):
        instances = [_make_instance("i-001", ["sg-001"])]
        sgs = [_make_sg("sg-001", "web-servers")]
        result = _run_fetch(instances, sgs)
        assert result[0]["group_name"] == "web-servers"

    def test_inbound_rules_is_list(self):
        instances = [_make_instance("i-001", ["sg-001"])]
        sgs = [_make_sg("sg-001", "my-sg")]
        result = _run_fetch(instances, sgs)
        assert isinstance(result[0]["inbound_rules"], list)


# ---------------------------------------------------------------------------
# Multiple instances and SGs
# ---------------------------------------------------------------------------

class TestMultipleInstancesAndSGs:
    def test_instance_with_multiple_sgs(self):
        instances = [_make_instance("i-001", ["sg-001", "sg-002"])]
        sgs = [
            _make_sg("sg-001", "sg-one"),
            _make_sg("sg-002", "sg-two"),
        ]
        result = _run_fetch(instances, sgs)
        # One entry per SG per instance
        assert len(result) == 2
        group_ids = {r["group_id"] for r in result}
        assert "sg-001" in group_ids
        assert "sg-002" in group_ids

    def test_sg_attached_to_multiple_instances_returns_one_per_instance(self):
        """US-4.1: SG attached to multiple instances → one entry per instance."""
        instances = [
            _make_instance("i-001", ["sg-shared"]),
            _make_instance("i-002", ["sg-shared"]),
        ]
        sgs = [_make_sg("sg-shared", "shared-sg")]
        result = _run_fetch(instances, sgs)
        assert len(result) == 2
        instance_ids = {r["attached_instance_id"] for r in result}
        assert "i-001" in instance_ids
        assert "i-002" in instance_ids

    def test_multiple_instances_multiple_sgs(self):
        instances = [
            _make_instance("i-001", ["sg-001"]),
            _make_instance("i-002", ["sg-002"]),
        ]
        sgs = [
            _make_sg("sg-001", "sg-one"),
            _make_sg("sg-002", "sg-two"),
        ]
        result = _run_fetch(instances, sgs)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Paginator filter — only running instances
# ---------------------------------------------------------------------------

class TestRunningInstanceFilter:
    def test_paginator_filters_for_running_state(self):
        mock_ec2 = MagicMock()
        mock_ec2.get_paginator.return_value = _make_paginator([])
        mock_ec2.describe_security_groups.return_value = {"SecurityGroups": []}

        with patch("aws.security_fetcher.get_client", return_value=mock_ec2):
            fetch_security_groups("us-east-1")

        paginate_call = mock_ec2.get_paginator.return_value.paginate.call_args
        kwargs = paginate_call[1] if paginate_call[1] else {}
        args = paginate_call[0] if paginate_call[0] else ()
        # Check that Filters with running state was passed
        filters = kwargs.get("Filters", [])
        state_filter = next(
            (f for f in filters if f.get("Name") == "instance-state-name"), None
        )
        assert state_filter is not None
        assert "running" in state_filter["Values"]


# ---------------------------------------------------------------------------
# _extract_inbound_rules() — port extraction
# ---------------------------------------------------------------------------

class TestExtractInboundRules:
    def test_single_port_tcp(self):
        perms = [{
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            "Ipv6Ranges": [],
            "UserIdGroupPairs": [],
        }]
        rules = _extract_inbound_rules(perms)
        assert len(rules) == 1
        assert rules[0]["port"] == 22
        assert rules[0]["port_range_end"] is None
        assert rules[0]["source_cidr"] == "0.0.0.0/0"
        assert rules[0]["protocol"] == "tcp"

    def test_port_range(self):
        perms = [{
            "IpProtocol": "tcp",
            "FromPort": 8000,
            "ToPort": 8080,
            "IpRanges": [{"CidrIp": "10.0.0.0/8"}],
            "Ipv6Ranges": [],
            "UserIdGroupPairs": [],
        }]
        rules = _extract_inbound_rules(perms)
        assert len(rules) == 1
        assert rules[0]["port"] == 8000
        assert rules[0]["port_range_end"] == 8080

    def test_all_traffic_protocol_minus_1(self):
        perms = [{
            "IpProtocol": "-1",
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            "Ipv6Ranges": [],
            "UserIdGroupPairs": [],
        }]
        rules = _extract_inbound_rules(perms)
        assert len(rules) == 1
        assert rules[0]["port"] is None
        assert rules[0]["protocol"] == "-1"

    def test_ipv6_cidr_extracted(self):
        perms = [{
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [],
            "Ipv6Ranges": [{"CidrIpv6": "::/0"}],
            "UserIdGroupPairs": [],
        }]
        rules = _extract_inbound_rules(perms)
        assert len(rules) == 1
        assert rules[0]["source_cidr"] == "::/0"

    def test_sg_source_extracted(self):
        perms = [{
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "IpRanges": [],
            "Ipv6Ranges": [],
            "UserIdGroupPairs": [{"GroupId": "sg-other"}],
        }]
        rules = _extract_inbound_rules(perms)
        assert len(rules) == 1
        assert rules[0]["source_sg"] == "sg-other"
        assert rules[0]["source_cidr"] is None

    def test_multiple_cidrs_in_one_permission(self):
        perms = [{
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "IpRanges": [
                {"CidrIp": "10.0.0.0/8"},
                {"CidrIp": "192.168.0.0/16"},
            ],
            "Ipv6Ranges": [],
            "UserIdGroupPairs": [],
        }]
        rules = _extract_inbound_rules(perms)
        assert len(rules) == 2
        cidrs = {r["source_cidr"] for r in rules}
        assert "10.0.0.0/8" in cidrs
        assert "192.168.0.0/16" in cidrs

    def test_empty_permissions_returns_empty_list(self):
        rules = _extract_inbound_rules([])
        assert rules == []

    def test_rule_fields_present(self):
        perms = [{
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            "Ipv6Ranges": [],
            "UserIdGroupPairs": [],
        }]
        rules = _extract_inbound_rules(perms)
        for field in ("port", "port_range_end", "protocol", "source_cidr", "source_sg"):
            assert field in rules[0], f"Missing field: {field}"
