"""
tests/test_confidence.py — Unit tests for the confidence scoring engine.
Owner: Person 1
Epic: 5

Tests cover:
  - ec2_confidence_statement() — high / medium / low / insufficient_data
  - rds_confidence_statement() — high / medium / low / insufficient_data / healthy / overprovisioned
  - score_ec2_confidence()     — signal counting
  - score_rds_confidence()     — IOPS signal counting
"""

import pytest
from analysis.confidence import (
    ec2_confidence_statement,
    rds_confidence_statement,
    score_ec2_confidence,
    score_rds_confidence,
)
from analysis.ec2_analyzer import classify_instance
from analysis.rds_analyzer import classify_rds_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ec2(cpu, net_in=None, net_out=None, disk=None,
             data_days=7, state="running", classification=None, confidence=None):
    inst = {
        "id": "i-test",
        "name": "test",
        "type": "m5.xlarge",
        "state": state,
        "purchasing_type": "on-demand",
        "days_in_current_state": 10,
        "cpu_avg_7d": cpu,
        "network_in_avg_7d": net_in,
        "network_out_avg_7d": net_out,
        "disk_read_ops_avg_7d": disk,
        "data_available_days": data_days,
    }
    if classification is not None:
        inst["classification"] = classification
    if confidence is not None:
        inst["confidence"] = confidence
    return inst


def make_rds(cpu=50.0, connections=20.0, read_iops=10.0, write_iops=10.0,
             data_days=7, classification=None, confidence=None):
    inst = {
        "id": "db-test",
        "name": "db-test",
        "class": "db.t3.medium",
        "engine": "mysql",
        "status": "available",
        "multi_az": False,
        "backups_enabled": True,
        "allocated_storage_gb": 100,
        "cpu_avg_7d": cpu,
        "connections_avg_7d": connections,
        "read_iops_avg_7d": read_iops,
        "write_iops_avg_7d": write_iops,
        "free_storage_pct": 50.0,
        "freeable_memory_mb": 1024.0,
        "data_available_days": data_days,
    }
    if classification is not None:
        inst["classification"] = classification
    if confidence is not None:
        inst["confidence"] = confidence
    return inst


# ---------------------------------------------------------------------------
# score_ec2_confidence() — signal counting
# ---------------------------------------------------------------------------

class TestScoreEC2Confidence:
    def test_all_three_signals_near_zero_is_high(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=200, disk=0.1)
        assert score_ec2_confidence(inst) == "high"

    def test_two_signals_near_zero_is_high(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=200, disk=None)
        assert score_ec2_confidence(inst) == "high"

    def test_one_signal_near_zero_is_medium(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=None, disk=None)
        assert score_ec2_confidence(inst) == "medium"

    def test_no_secondary_signals_is_low(self):
        inst = make_ec2(cpu=2.0, net_in=None, net_out=None, disk=None)
        assert score_ec2_confidence(inst) == "low"

    def test_elevated_network_does_not_count(self):
        inst = make_ec2(cpu=2.0, net_in=50000, net_out=50000, disk=0.1)
        # Only disk near zero → medium
        assert score_ec2_confidence(inst) == "medium"

    def test_all_signals_elevated_is_low(self):
        inst = make_ec2(cpu=2.0, net_in=50000, net_out=50000, disk=5.0)
        assert score_ec2_confidence(inst) == "low"

    def test_network_exactly_at_threshold_not_counted(self):
        # 1000.0 is NOT < 1000.0
        inst = make_ec2(cpu=2.0, net_in=1000.0, net_out=1000.0, disk=None)
        assert score_ec2_confidence(inst) == "low"

    def test_network_just_below_threshold_counted(self):
        inst = make_ec2(cpu=2.0, net_in=999.9, net_out=999.9, disk=None)
        assert score_ec2_confidence(inst) == "high"

    def test_disk_exactly_at_threshold_not_counted(self):
        # 1.0 is NOT < 1.0
        inst = make_ec2(cpu=2.0, net_in=None, net_out=None, disk=1.0)
        assert score_ec2_confidence(inst) == "low"

    def test_disk_just_below_threshold_counted(self):
        inst = make_ec2(cpu=2.0, net_in=None, net_out=None, disk=0.99)
        assert score_ec2_confidence(inst) == "medium"


# ---------------------------------------------------------------------------
# score_rds_confidence() — IOPS signal counting
# ---------------------------------------------------------------------------

class TestScoreRDSConfidence:
    def test_both_iops_near_zero_is_high(self):
        inst = make_rds(read_iops=0.5, write_iops=0.5)
        assert score_rds_confidence(inst) == "high"

    def test_only_read_iops_near_zero_is_medium(self):
        inst = make_rds(read_iops=0.5, write_iops=5.0)
        assert score_rds_confidence(inst) == "medium"

    def test_only_write_iops_near_zero_is_medium(self):
        inst = make_rds(read_iops=5.0, write_iops=0.5)
        assert score_rds_confidence(inst) == "medium"

    def test_both_iops_elevated_is_low(self):
        inst = make_rds(read_iops=5.0, write_iops=5.0)
        assert score_rds_confidence(inst) == "low"

    def test_both_iops_none_is_low(self):
        inst = make_rds(read_iops=None, write_iops=None)
        assert score_rds_confidence(inst) == "low"

    def test_read_iops_none_write_near_zero_is_medium(self):
        inst = make_rds(read_iops=None, write_iops=0.5)
        assert score_rds_confidence(inst) == "medium"

    def test_iops_exactly_at_threshold_not_counted(self):
        inst = make_rds(read_iops=1.0, write_iops=1.0)
        assert score_rds_confidence(inst) == "low"

    def test_iops_just_below_threshold_counted(self):
        inst = make_rds(read_iops=0.99, write_iops=0.99)
        assert score_rds_confidence(inst) == "high"


# ---------------------------------------------------------------------------
# ec2_confidence_statement() — US-5.1, US-5.3, US-5.4
# ---------------------------------------------------------------------------

class TestEC2ConfidenceStatementHighConfidence:
    def test_high_confidence_starts_with_high(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=200, disk=0.1,
                        classification="idle", confidence="high")
        stmt = ec2_confidence_statement(inst)
        assert stmt.startswith("High confidence")

    def test_high_confidence_mentions_seven_days(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=200, disk=0.1,
                        classification="idle", confidence="high")
        stmt = ec2_confidence_statement(inst)
        assert "7 days" in stmt

    def test_high_confidence_via_classify(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=200, disk=0.1)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert "High confidence" in stmt

    def test_high_confidence_lists_signals(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=200, disk=0.1,
                        classification="idle", confidence="high")
        stmt = ec2_confidence_statement(inst)
        # At least one signal should be named
        assert any(s in stmt for s in ["CPU", "network", "disk"])


class TestEC2ConfidenceStatementMediumConfidence:
    def test_medium_confidence_starts_with_medium(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=None, disk=None,
                        classification="idle", confidence="medium")
        stmt = ec2_confidence_statement(inst)
        assert stmt.startswith("Medium confidence")

    def test_medium_confidence_mentions_not_all_signals(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=None, disk=None,
                        classification="idle", confidence="medium")
        stmt = ec2_confidence_statement(inst)
        assert "not all" in stmt.lower() or "available" in stmt.lower()

    def test_medium_confidence_via_classify(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=None, disk=None)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert "Medium confidence" in stmt


class TestEC2ConfidenceStatementLowConfidence:
    def test_low_confidence_mentions_low(self):
        inst = make_ec2(cpu=2.0, net_in=None, net_out=None, disk=None,
                        classification="idle", confidence="low")
        stmt = ec2_confidence_statement(inst)
        assert "Low confidence" in stmt

    def test_low_confidence_recommends_manual_review(self):
        inst = make_ec2(cpu=2.0, net_in=None, net_out=None, disk=None,
                        classification="idle", confidence="low")
        stmt = ec2_confidence_statement(inst)
        assert "manual" in stmt.lower() or "recommend" in stmt.lower()

    def test_low_confidence_via_classify(self):
        inst = make_ec2(cpu=2.0, net_in=None, net_out=None, disk=None)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert "Low confidence" in stmt


class TestEC2ConfidenceStatementInsufficientData:
    def test_insufficient_data_mentions_days(self):
        inst = make_ec2(cpu=2.0, data_days=1, classification="insufficient_data", confidence=None)
        stmt = ec2_confidence_statement(inst)
        assert "1" in stmt
        assert "day" in stmt.lower()

    def test_insufficient_data_recommends_manual_review(self):
        inst = make_ec2(cpu=2.0, data_days=2, classification="insufficient_data", confidence=None)
        stmt = ec2_confidence_statement(inst)
        assert "manual" in stmt.lower() or "review" in stmt.lower()

    def test_insufficient_data_zero_days(self):
        inst = make_ec2(cpu=None, data_days=0, classification="insufficient_data", confidence=None)
        stmt = ec2_confidence_statement(inst)
        assert "0" in stmt

    def test_insufficient_data_via_classify(self):
        inst = make_ec2(cpu=2.0, data_days=1)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert "1" in stmt and "day" in stmt.lower()


# ---------------------------------------------------------------------------
# rds_confidence_statement() — US-5.2, US-5.3, US-5.4
# ---------------------------------------------------------------------------

class TestRDSConfidenceStatementHighConfidence:
    def test_high_confidence_starts_with_high(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=0.5, write_iops=0.5,
                        classification="idle", confidence="high")
        stmt = rds_confidence_statement(inst)
        assert "High confidence" in stmt

    def test_high_confidence_via_classify(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=0.5, write_iops=0.5)
        classified = classify_rds_instance(inst)
        stmt = rds_confidence_statement(classified)
        assert "High confidence" in stmt

    def test_high_confidence_mentions_iops(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=0.5, write_iops=0.5,
                        classification="idle", confidence="high")
        stmt = rds_confidence_statement(inst)
        assert "IOPS" in stmt or "iops" in stmt.lower()


class TestRDSConfidenceStatementMediumConfidence:
    def test_medium_confidence_via_classify_one_iops(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=0.5, write_iops=5.0)
        classified = classify_rds_instance(inst)
        stmt = rds_confidence_statement(classified)
        assert "Medium confidence" in stmt or "medium" in stmt.lower()

    def test_medium_confidence_mentions_iops_detail(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=0.5, write_iops=5.0,
                        classification="idle", confidence="medium")
        stmt = rds_confidence_statement(inst)
        assert "IOPS" in stmt or "iops" in stmt.lower()


class TestRDSConfidenceStatementLowConfidence:
    def test_low_confidence_via_classify_no_iops(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=None, write_iops=None)
        classified = classify_rds_instance(inst)
        stmt = rds_confidence_statement(classified)
        assert "Low confidence" in stmt or "low" in stmt.lower() or "manual" in stmt.lower()

    def test_low_confidence_recommends_verification(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=None, write_iops=None,
                        classification="idle", confidence="low")
        stmt = rds_confidence_statement(inst)
        assert "manual" in stmt.lower() or "verification" in stmt.lower() or "recommend" in stmt.lower()


class TestRDSConfidenceStatementInsufficientData:
    def test_insufficient_data_mentions_days(self):
        inst = make_rds(data_days=1, classification="insufficient_data", confidence=None)
        stmt = rds_confidence_statement(inst)
        assert "1" in stmt
        assert "day" in stmt.lower()

    def test_insufficient_data_zero_days(self):
        inst = make_rds(data_days=0, classification="insufficient_data", confidence=None)
        stmt = rds_confidence_statement(inst)
        assert "0" in stmt

    def test_insufficient_data_via_classify(self):
        inst = make_rds(data_days=1)
        classified = classify_rds_instance(inst)
        stmt = rds_confidence_statement(classified)
        assert "1" in stmt and "day" in stmt.lower()

    def test_insufficient_data_recommends_review(self):
        inst = make_rds(data_days=2, classification="insufficient_data", confidence=None)
        stmt = rds_confidence_statement(inst)
        assert "review" in stmt.lower() or "assessment" in stmt.lower() or "reliable" in stmt.lower()


class TestRDSConfidenceStatementHealthy:
    def test_healthy_statement_mentions_active(self):
        inst = make_rds(cpu=60.0, connections=100.0, classification="healthy", confidence=None)
        stmt = rds_confidence_statement(inst)
        assert "active" in stmt.lower() or "20%" in stmt

    def test_healthy_via_classify(self):
        inst = make_rds(cpu=60.0, connections=100.0)
        classified = classify_rds_instance(inst)
        stmt = rds_confidence_statement(classified)
        assert len(stmt) > 0


class TestRDSConfidenceStatementOverprovisioned:
    def test_overprovisioned_mentions_cpu(self):
        inst = make_rds(cpu=15.0, connections=50.0, classification="overprovisioned", confidence="medium")
        stmt = rds_confidence_statement(inst)
        assert "15.0%" in stmt or "CPU" in stmt or "cpu" in stmt.lower()

    def test_overprovisioned_via_classify(self):
        inst = make_rds(cpu=15.0, connections=50.0)
        classified = classify_rds_instance(inst)
        stmt = rds_confidence_statement(classified)
        assert "15.0%" in stmt


# ---------------------------------------------------------------------------
# Integration: confidence_statement field in tool output shape
# ---------------------------------------------------------------------------

class TestConfidenceStatementIntegration:
    def test_ec2_classify_then_statement_is_string(self):
        inst = make_ec2(cpu=2.0, net_in=500, net_out=200, disk=0.1)
        classified = classify_instance(inst)
        stmt = ec2_confidence_statement(classified)
        assert isinstance(stmt, str)
        assert len(stmt) > 0

    def test_rds_classify_then_statement_is_string(self):
        inst = make_rds(cpu=2.0, connections=1.0, read_iops=0.5, write_iops=0.5)
        classified = classify_rds_instance(inst)
        stmt = rds_confidence_statement(classified)
        assert isinstance(stmt, str)
        assert len(stmt) > 0

    def test_ec2_all_classifications_produce_non_empty_statement(self):
        cases = [
            make_ec2(cpu=2.0, net_in=500, net_out=200, disk=0.1),          # idle high
            make_ec2(cpu=2.0, net_in=None, net_out=None, disk=None),        # idle low
            make_ec2(cpu=10.0),                                              # overprovisioned
            make_ec2(cpu=50.0),                                              # healthy
            make_ec2(cpu=90.0),                                              # underprovisioned
            make_ec2(cpu=2.0, data_days=1),                                  # insufficient_data
        ]
        for inst in cases:
            classified = classify_instance(inst)
            stmt = ec2_confidence_statement(classified)
            assert isinstance(stmt, str) and len(stmt) > 0, \
                f"Empty statement for classification: {classified.get('classification')}"

    def test_rds_all_classifications_produce_non_empty_statement(self):
        cases = [
            make_rds(cpu=2.0, connections=1.0, read_iops=0.5, write_iops=0.5),  # idle high
            make_rds(cpu=2.0, connections=1.0, read_iops=None, write_iops=None), # idle low
            make_rds(cpu=15.0, connections=50.0),                                # overprovisioned
            make_rds(cpu=60.0, connections=100.0),                               # healthy
            make_rds(data_days=1),                                               # insufficient_data
        ]
        for inst in cases:
            classified = classify_rds_instance(inst)
            stmt = rds_confidence_statement(classified)
            assert isinstance(stmt, str) and len(stmt) > 0, \
                f"Empty statement for classification: {classified.get('classification')}"
