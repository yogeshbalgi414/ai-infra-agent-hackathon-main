"""
tests/test_ec2_fetcher.py — Unit tests for aws/ec2_fetcher.py purchasing type logic.
Owner: Person 1
Epic: 2 (revised — reserved instance detection fix)

Tests focus on the purchasing_type derivation since that is the logic that changed.
CloudWatch metric fetching is covered by integration tests against LocalStack.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from aws.ec2_fetcher import _fetch_reserved_instance_keys, fetch_ec2_instances


# ---------------------------------------------------------------------------
# Helpers — mock boto3 responses
# ---------------------------------------------------------------------------

def _make_ec2_instance(instance_id, instance_type, az, lifecycle=None, tags=None):
    """Build a minimal boto3 instance dict."""
    inst = {
        "InstanceId": instance_id,
        "InstanceType": instance_type,
        "State": {"Name": "running"},
        "Placement": {"AvailabilityZone": az},
        "Tags": tags or [{"Key": "Name", "Value": instance_id}],
        "LaunchTime": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "StateTransitionReason": "",
    }
    if lifecycle:
        inst["InstanceLifecycle"] = lifecycle
    return inst


def _make_reserved_instance(instance_type, az, state="active"):
    return {
        "InstanceType": instance_type,
        "AvailabilityZone": az,
        "State": state,
    }


def _make_paginator_response(instances):
    """Wrap instances in the boto3 describe_instances page structure."""
    page = {
        "Reservations": [
            {"Instances": [inst]} for inst in instances
        ]
    }
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [page]
    return mock_paginator


# ---------------------------------------------------------------------------
# _fetch_reserved_instance_keys()
# ---------------------------------------------------------------------------

class TestFetchReservedInstanceKeys:
    def test_returns_set_of_type_az_tuples(self):
        mock_ec2 = MagicMock()
        mock_ec2.describe_reserved_instances.return_value = {
            "ReservedInstances": [
                _make_reserved_instance("m5.xlarge", "us-east-1a"),
                _make_reserved_instance("t3.large", "us-east-1b"),
            ]
        }
        keys = _fetch_reserved_instance_keys(mock_ec2)
        assert ("m5.xlarge", "us-east-1a") in keys
        assert ("t3.large", "us-east-1b") in keys

    def test_only_active_reservations_are_fetched(self):
        """The filter for state=active is passed to describe_reserved_instances."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_reserved_instances.return_value = {"ReservedInstances": []}
        _fetch_reserved_instance_keys(mock_ec2)
        call_kwargs = mock_ec2.describe_reserved_instances.call_args[1]
        filters = call_kwargs.get("Filters", [])
        state_filter = next((f for f in filters if f["Name"] == "state"), None)
        assert state_filter is not None
        assert "active" in state_filter["Values"]

    def test_returns_empty_set_when_no_reservations(self):
        mock_ec2 = MagicMock()
        mock_ec2.describe_reserved_instances.return_value = {"ReservedInstances": []}
        keys = _fetch_reserved_instance_keys(mock_ec2)
        assert keys == set()

    def test_returns_empty_set_on_api_exception(self):
        """If describe_reserved_instances fails, return empty set — do not crash."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_reserved_instances.side_effect = Exception("AccessDenied")
        keys = _fetch_reserved_instance_keys(mock_ec2)
        assert keys == set()

    def test_skips_entries_with_missing_type_or_az(self):
        mock_ec2 = MagicMock()
        mock_ec2.describe_reserved_instances.return_value = {
            "ReservedInstances": [
                {"InstanceType": "m5.xlarge", "AvailabilityZone": ""},  # empty AZ
                {"InstanceType": "", "AvailabilityZone": "us-east-1a"},  # empty type
                {"InstanceType": "t3.large", "AvailabilityZone": "us-east-1b"},  # valid
            ]
        }
        keys = _fetch_reserved_instance_keys(mock_ec2)
        assert len(keys) == 1
        assert ("t3.large", "us-east-1b") in keys


# ---------------------------------------------------------------------------
# fetch_ec2_instances() — purchasing_type derivation
# ---------------------------------------------------------------------------

class TestFetchEC2InstancesPurchasingType:
    def _run_fetch(self, instances, reserved_instances=None):
        """
        Helper: mock get_client, describe_reserved_instances, and paginator,
        then call fetch_ec2_instances and return the result list.
        """
        reserved_instances = reserved_instances or []

        mock_ec2_client = MagicMock()
        mock_ec2_client.describe_reserved_instances.return_value = {
            "ReservedInstances": reserved_instances
        }
        mock_ec2_client.get_paginator.return_value = _make_paginator_response(instances)

        with patch("aws.ec2_fetcher.get_client", return_value=mock_ec2_client):
            from aws.ec2_fetcher import fetch_ec2_instances
            return fetch_ec2_instances("us-east-1")

    def test_spot_instance_detected_via_lifecycle_field(self):
        inst = _make_ec2_instance("i-spot01", "t3.large", "us-east-1a", lifecycle="spot")
        results = self._run_fetch([inst])
        assert results[0]["purchasing_type"] == "spot"

    def test_spot_takes_priority_over_reserved_match(self):
        """Even if a spot instance matches a reservation by type+AZ, spot wins."""
        inst = _make_ec2_instance("i-spot01", "m5.xlarge", "us-east-1a", lifecycle="spot")
        reserved = [_make_reserved_instance("m5.xlarge", "us-east-1a")]
        results = self._run_fetch([inst], reserved_instances=reserved)
        assert results[0]["purchasing_type"] == "spot"

    def test_reserved_detected_via_type_and_az_match(self):
        inst = _make_ec2_instance("i-res01", "m5.xlarge", "us-east-1a")
        reserved = [_make_reserved_instance("m5.xlarge", "us-east-1a")]
        results = self._run_fetch([inst], reserved_instances=reserved)
        assert results[0]["purchasing_type"] == "reserved"

    def test_no_match_defaults_to_on_demand(self):
        inst = _make_ec2_instance("i-od01", "t3.large", "us-east-1b")
        # Reserved exists but for a different AZ
        reserved = [_make_reserved_instance("t3.large", "us-east-1a")]
        results = self._run_fetch([inst], reserved_instances=reserved)
        assert results[0]["purchasing_type"] == "on-demand"

    def test_type_mismatch_defaults_to_on_demand(self):
        inst = _make_ec2_instance("i-od02", "t3.medium", "us-east-1a")
        # Reserved exists but for a different instance type
        reserved = [_make_reserved_instance("t3.large", "us-east-1a")]
        results = self._run_fetch([inst], reserved_instances=reserved)
        assert results[0]["purchasing_type"] == "on-demand"

    def test_no_reservations_all_on_demand(self):
        instances = [
            _make_ec2_instance("i-01", "t3.large", "us-east-1a"),
            _make_ec2_instance("i-02", "m5.xlarge", "us-east-1b"),
        ]
        results = self._run_fetch(instances, reserved_instances=[])
        assert all(r["purchasing_type"] == "on-demand" for r in results)

    def test_reserved_api_failure_falls_back_to_on_demand(self):
        """If describe_reserved_instances raises, all instances default to on-demand."""
        inst = _make_ec2_instance("i-01", "m5.xlarge", "us-east-1a")

        mock_ec2_client = MagicMock()
        mock_ec2_client.describe_reserved_instances.side_effect = Exception("AccessDenied")
        mock_ec2_client.get_paginator.return_value = _make_paginator_response([inst])

        with patch("aws.ec2_fetcher.get_client", return_value=mock_ec2_client):
            from aws.ec2_fetcher import fetch_ec2_instances
            results = fetch_ec2_instances("us-east-1")

        assert results[0]["purchasing_type"] == "on-demand"

    def test_multiple_reservations_all_matched(self):
        instances = [
            _make_ec2_instance("i-01", "m5.xlarge", "us-east-1a"),
            _make_ec2_instance("i-02", "t3.large", "us-east-1b"),
            _make_ec2_instance("i-03", "r5.xlarge", "us-east-1c"),  # no reservation
        ]
        reserved = [
            _make_reserved_instance("m5.xlarge", "us-east-1a"),
            _make_reserved_instance("t3.large", "us-east-1b"),
        ]
        results = self._run_fetch(instances, reserved_instances=reserved)
        by_id = {r["id"]: r for r in results}
        assert by_id["i-01"]["purchasing_type"] == "reserved"
        assert by_id["i-02"]["purchasing_type"] == "reserved"
        assert by_id["i-03"]["purchasing_type"] == "on-demand"


# ---------------------------------------------------------------------------
# fetch_ec2_instances() — other fields
# ---------------------------------------------------------------------------

class TestFetchEC2InstancesFields:
    def _run_fetch(self, instances):
        mock_ec2_client = MagicMock()
        mock_ec2_client.describe_reserved_instances.return_value = {"ReservedInstances": []}
        mock_ec2_client.get_paginator.return_value = _make_paginator_response(instances)
        with patch("aws.ec2_fetcher.get_client", return_value=mock_ec2_client):
            from aws.ec2_fetcher import fetch_ec2_instances
            return fetch_ec2_instances("us-east-1")

    def test_name_tag_used_when_present(self):
        inst = _make_ec2_instance("i-01", "t3.large", "us-east-1a",
                                   tags=[{"Key": "Name", "Value": "my-server"}])
        results = self._run_fetch([inst])
        assert results[0]["name"] == "my-server"

    def test_instance_id_used_as_name_fallback(self):
        inst = _make_ec2_instance("i-01", "t3.large", "us-east-1a", tags=[])
        results = self._run_fetch([inst])
        assert results[0]["name"] == "i-01"

    def test_all_required_fields_present(self):
        inst = _make_ec2_instance("i-01", "t3.large", "us-east-1a")
        results = self._run_fetch([inst])
        r = results[0]
        for field in ("id", "name", "type", "state", "purchasing_type",
                      "launch_time", "days_in_current_state"):
            assert field in r, f"Missing field: {field}"
