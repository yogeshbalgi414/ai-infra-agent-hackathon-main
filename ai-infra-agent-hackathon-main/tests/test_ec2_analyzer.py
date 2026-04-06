"""
tests/test_ec2_analyzer.py — Unit tests for EC2 analysis.
Owner: Person 1
Epic: 2
"""

import pytest
from analysis.ec2_analyzer import (
    classify_instance,
    recommend_downsize,
    ec2_confidence_statement,
    INSTANCE_SIZE_ORDER,
)
from analysis.cost_estimator import estimate_ec2_monthly_cost, estimate_ec2_savings


# ---------------------------------------------------------------------------
# Fixtures — base instance shapes
# ---------------------------------------------------------------------------

def _running_instance(cpu, net_in=None, net_out=None, disk=None,
                      data_days=7, instance_type="m5.xlarge",
                      purchasing_type="on-demand"):
    return {
        "id": "i-test001",
        "name": "test-instance",
        "type": instance_type,
        "state": "running",
        "purchasing_type": purchasing_type,
        "days_in_current_state": 10,
        "cpu_avg_7d": cpu,
        "network_in_avg_7d": net_in,
        "network_out_avg_7d": net_out,
        "disk_read_ops_avg_7d": disk,
        "data_available_days": data_days,
    }


def _stopped_instance(days_stopped, instance_type="t3.micro"):
    return {
        "id": "i-stopped01",
        "name": "stopped-instance",
        "type": instance_type,
        "state": "stopped",
        "purchasing_type": "on-demand",
        "days_in_current_state": days_stopped,
        "cpu_avg_7d": None,
        "network_in_avg_7d": None,
        "network_out_avg_7d": None,
        "disk_read_ops_avg_7d": None,
        "data_available_days": 0,
    }


# ---------------------------------------------------------------------------
# Task 2.9 — classify_instance() — all 6 branches
# ---------------------------------------------------------------------------

class TestClassifyInstanceIdle:
    def test_cpu_below_5_is_idle(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=200, disk=0.1)
        result = classify_instance(inst)
        assert result["classification"] == "idle"

    def test_cpu_exactly_0_is_idle(self):
        inst = _running_instance(cpu=0.0, net_in=0, net_out=0, disk=0.0)
        result = classify_instance(inst)
        assert result["classification"] == "idle"

    def test_cpu_4_99_is_idle(self):
        inst = _running_instance(cpu=4.99)
        result = classify_instance(inst)
        assert result["classification"] == "idle"


class TestClassifyInstanceOverprovisioned:
    def test_cpu_5_to_20_large_instance_is_overprovisioned(self):
        inst = _running_instance(cpu=8.0, instance_type="m5.xlarge")
        result = classify_instance(inst)
        assert result["classification"] == "overprovisioned"

    def test_cpu_5_to_20_t3_small_is_healthy(self):
        """t3.small is the minimum — should not be flagged as overprovisioned."""
        inst = _running_instance(cpu=10.0, instance_type="t3.small")
        result = classify_instance(inst)
        assert result["classification"] == "healthy"

    def test_cpu_5_to_20_t3_micro_is_healthy(self):
        inst = _running_instance(cpu=15.0, instance_type="t3.micro")
        result = classify_instance(inst)
        assert result["classification"] == "healthy"

    def test_overprovisioned_has_recommended_type(self):
        inst = _running_instance(cpu=8.0, instance_type="m5.xlarge")
        result = classify_instance(inst)
        assert result["recommended_type"] is not None

    def test_overprovisioned_on_demand_has_savings(self):
        inst = _running_instance(cpu=8.0, instance_type="m5.xlarge", purchasing_type="on-demand")
        result = classify_instance(inst)
        assert result["savings_usd"] is not None
        assert result["savings_usd"] > 0

    def test_overprovisioned_reserved_no_savings(self):
        inst = _running_instance(cpu=8.0, instance_type="m5.xlarge", purchasing_type="reserved")
        result = classify_instance(inst)
        # Reserved instances should not show savings_usd
        assert result["savings_usd"] is None


class TestClassifyInstanceHealthy:
    def test_cpu_20_to_80_is_healthy(self):
        inst = _running_instance(cpu=50.0)
        result = classify_instance(inst)
        assert result["classification"] == "healthy"

    def test_cpu_exactly_20_is_healthy(self):
        inst = _running_instance(cpu=20.0)
        result = classify_instance(inst)
        assert result["classification"] == "healthy"


class TestClassifyInstanceUnderprovisioned:
    def test_cpu_above_80_is_underprovisioned(self):
        inst = _running_instance(cpu=85.0)
        result = classify_instance(inst)
        assert result["classification"] == "underprovisioned"

    def test_cpu_100_is_underprovisioned(self):
        inst = _running_instance(cpu=100.0)
        result = classify_instance(inst)
        assert result["classification"] == "underprovisioned"

    def test_underprovisioned_confidence_is_high(self):
        inst = _running_instance(cpu=90.0)
        result = classify_instance(inst)
        assert result["confidence"] == "high"


class TestClassifyInstanceStopped:
    def test_stopped_more_than_7_days_is_stopped(self):
        inst = _stopped_instance(days_stopped=10)
        result = classify_instance(inst)
        assert result["classification"] == "stopped"

    def test_stopped_exactly_8_days_is_stopped(self):
        inst = _stopped_instance(days_stopped=8)
        result = classify_instance(inst)
        assert result["classification"] == "stopped"

    def test_stopped_3_days_is_flagged(self):
        """Any stopped instance is classified as stopped regardless of days (Bug 3 fix)."""
        inst = _stopped_instance(days_stopped=3)
        result = classify_instance(inst)
        assert result["classification"] == "stopped"

    def test_stopped_7_days_is_flagged(self):
        """Any stopped instance is classified as stopped regardless of days (Bug 3 fix)."""
        inst = _stopped_instance(days_stopped=7)
        result = classify_instance(inst)
        assert result["classification"] == "stopped"


class TestClassifyInstanceInsufficientData:
    def test_fewer_than_3_days_data_is_insufficient(self):
        inst = _running_instance(cpu=2.0, data_days=2)
        result = classify_instance(inst)
        assert result["classification"] == "insufficient_data"

    def test_zero_days_data_is_insufficient(self):
        inst = _running_instance(cpu=2.0, data_days=0)
        result = classify_instance(inst)
        assert result["classification"] == "insufficient_data"

    def test_null_cpu_with_enough_days_is_insufficient(self):
        inst = _running_instance(cpu=None, data_days=7)
        result = classify_instance(inst)
        assert result["classification"] == "insufficient_data"

    def test_insufficient_data_confidence_is_none(self):
        inst = _running_instance(cpu=2.0, data_days=1)
        result = classify_instance(inst)
        assert result["confidence"] is None


# ---------------------------------------------------------------------------
# Task 2.10 — Confidence scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring:
    def test_all_three_signals_near_zero_is_high(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=200, disk=0.1)
        result = classify_instance(inst)
        assert result["confidence"] == "high"

    def test_two_signals_near_zero_is_high(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=200, disk=None)
        result = classify_instance(inst)
        assert result["confidence"] == "high"

    def test_one_signal_near_zero_is_medium(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=None, disk=None)
        result = classify_instance(inst)
        assert result["confidence"] == "medium"

    def test_no_secondary_signals_is_low(self):
        inst = _running_instance(cpu=2.0, net_in=None, net_out=None, disk=None)
        result = classify_instance(inst)
        assert result["confidence"] == "low"

    def test_high_network_reduces_confidence(self):
        """High network traffic means instance is not truly idle — lower confidence."""
        inst = _running_instance(cpu=2.0, net_in=50000, net_out=50000, disk=0.1)
        result = classify_instance(inst)
        # Only disk signal is near zero → medium
        assert result["confidence"] == "medium"

    def test_all_signals_high_is_low_confidence(self):
        inst = _running_instance(cpu=2.0, net_in=50000, net_out=50000, disk=5.0)
        result = classify_instance(inst)
        assert result["confidence"] == "low"


# ---------------------------------------------------------------------------
# recommend_downsize()
# ---------------------------------------------------------------------------

class TestRecommendDownsize:
    def test_m5_xlarge_downsizes_to_m5_large(self):
        assert recommend_downsize("m5.xlarge") == "m5.large"

    def test_t3_large_downsizes_to_t3_medium(self):
        assert recommend_downsize("t3.large") == "t3.medium"

    def test_t3_nano_returns_none(self):
        assert recommend_downsize("t3.nano") is None

    def test_unknown_type_returns_none(self):
        assert recommend_downsize("c5.xlarge") is None

    def test_t3_micro_downsizes_to_t3_nano(self):
        assert recommend_downsize("t3.micro") == "t3.nano"


# ---------------------------------------------------------------------------
# Purchasing type notes
# ---------------------------------------------------------------------------

class TestPurchasingTypeNotes:
    def test_reserved_idle_has_purchasing_note(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=200, disk=0.1,
                                  purchasing_type="reserved")
        result = classify_instance(inst)
        assert result["purchasing_note"] is not None
        assert "Reserved" in result["purchasing_note"] or "commitment" in result["purchasing_note"].lower()

    def test_spot_idle_has_purchasing_note(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=200, disk=0.1,
                                  purchasing_type="spot")
        result = classify_instance(inst)
        assert result["purchasing_note"] is not None
        assert "Spot" in result["purchasing_note"] or "spot" in result["purchasing_note"].lower()

    def test_on_demand_idle_no_purchasing_note(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=200, disk=0.1,
                                  purchasing_type="on-demand")
        result = classify_instance(inst)
        assert result["purchasing_note"] is None


# ---------------------------------------------------------------------------
# Task 2.11 — Cost estimator
# ---------------------------------------------------------------------------

class TestEstimateEC2MonthlyCost:
    def test_t3_large_cost(self):
        # 0.0832 * 730 = 60.74
        assert estimate_ec2_monthly_cost("t3.large") == pytest.approx(60.74, abs=0.01)

    def test_m5_xlarge_cost(self):
        # 0.192 * 730 = 140.16
        assert estimate_ec2_monthly_cost("m5.xlarge") == pytest.approx(140.16, abs=0.01)

    def test_unknown_type_returns_zero(self):
        assert estimate_ec2_monthly_cost("c5.4xlarge") == 0.0

    def test_t3_nano_cost(self):
        # 0.0052 * 730 = 3.80
        assert estimate_ec2_monthly_cost("t3.nano") == pytest.approx(3.80, abs=0.01)


class TestEstimateEC2Savings:
    def test_m5_xlarge_to_m5_large_savings(self):
        # 140.16 - 70.08 = 70.08
        savings = estimate_ec2_savings("m5.xlarge", "m5.large")
        assert savings == pytest.approx(70.08, abs=0.01)

    def test_same_type_zero_savings(self):
        assert estimate_ec2_savings("t3.large", "t3.large") == 0.0

    def test_unknown_current_type_returns_zero(self):
        assert estimate_ec2_savings("c5.xlarge", "t3.medium") == pytest.approx(
            0.0 - estimate_ec2_monthly_cost("t3.medium"), abs=0.01
        )


# ---------------------------------------------------------------------------
# ec2_confidence_statement()
# ---------------------------------------------------------------------------

class TestConfidenceStatement:
    def test_high_confidence_statement(self):
        inst = _running_instance(cpu=2.0, net_in=500, net_out=200, disk=0.1)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert "High confidence" in stmt

    def test_low_confidence_statement(self):
        inst = _running_instance(cpu=2.0, net_in=None, net_out=None, disk=None)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert "Low confidence" in stmt

    def test_insufficient_data_statement_includes_days(self):
        inst = _running_instance(cpu=2.0, data_days=1)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert "1" in stmt
        assert "day" in stmt.lower()
