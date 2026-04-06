"""
tests/test_rds_analyzer.py — Unit tests for RDS analysis.
Owner: Person 2
Status: IMPLEMENTED (Epic 3)
"""

import pytest
from analysis.rds_analyzer import (
    classify_rds_instance,
    _score_rds_confidence,
    rds_confidence_statement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_instance(**overrides):
    """Return a minimal valid RDS instance dict with sensible defaults."""
    base = {
        "id": "db-test-001",
        "name": "db-test-001",
        "class": "db.t3.medium",
        "engine": "mysql",
        "status": "available",
        "multi_az": False,
        "backups_enabled": True,
        "allocated_storage_gb": 100,
        "cpu_avg_7d": 50.0,
        "connections_avg_7d": 20.0,
        "read_iops_avg_7d": 10.0,
        "write_iops_avg_7d": 10.0,
        "free_storage_pct": 50.0,
        "freeable_memory_mb": 1024.0,
        "data_available_days": 7,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Classification: insufficient_data
# ---------------------------------------------------------------------------

class TestInsufficientData:
    def test_zero_days(self):
        inst = make_instance(data_available_days=0)
        result = classify_rds_instance(inst)
        assert result["classification"] == "insufficient_data"
        assert result["confidence"] is None

    def test_one_day(self):
        inst = make_instance(data_available_days=1)
        result = classify_rds_instance(inst)
        assert result["classification"] == "insufficient_data"

    def test_two_days(self):
        inst = make_instance(data_available_days=2)
        result = classify_rds_instance(inst)
        assert result["classification"] == "insufficient_data"

    def test_exactly_three_days_is_not_insufficient(self):
        # 3 days is the threshold — should proceed to classification
        inst = make_instance(data_available_days=3, cpu_avg_7d=50.0, connections_avg_7d=20.0)
        result = classify_rds_instance(inst)
        assert result["classification"] != "insufficient_data"


# ---------------------------------------------------------------------------
# Classification: idle (dual-signal)
# ---------------------------------------------------------------------------

class TestIdleClassification:
    def test_idle_both_signals_present(self):
        inst = make_instance(cpu_avg_7d=2.0, connections_avg_7d=1.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "idle"

    def test_idle_cpu_exactly_at_threshold_is_not_idle(self):
        # cpu == 5.0 is NOT < 5.0, so not idle
        inst = make_instance(cpu_avg_7d=5.0, connections_avg_7d=1.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] != "idle"

    def test_idle_connections_exactly_at_threshold_is_not_idle(self):
        # connections == 5 is NOT < 5, so not idle
        inst = make_instance(cpu_avg_7d=2.0, connections_avg_7d=5.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] != "idle"

    def test_not_idle_when_only_cpu_low(self):
        # connections not low — not idle
        inst = make_instance(cpu_avg_7d=2.0, connections_avg_7d=10.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] != "idle"

    def test_not_idle_when_only_connections_low(self):
        # cpu not low — not idle
        inst = make_instance(cpu_avg_7d=30.0, connections_avg_7d=1.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] != "idle"

    def test_idle_with_none_cpu_is_not_idle(self):
        inst = make_instance(cpu_avg_7d=None, connections_avg_7d=1.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] != "idle"

    def test_idle_with_none_connections_is_not_idle(self):
        inst = make_instance(cpu_avg_7d=2.0, connections_avg_7d=None, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] != "idle"

    def test_idle_zero_cpu_zero_connections(self):
        inst = make_instance(cpu_avg_7d=0.0, connections_avg_7d=0.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "idle"


# ---------------------------------------------------------------------------
# Classification: overprovisioned
# ---------------------------------------------------------------------------

class TestOverprovisionedClassification:
    def test_overprovisioned_cpu_below_20(self):
        inst = make_instance(cpu_avg_7d=10.0, connections_avg_7d=20.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "overprovisioned"
        assert result["confidence"] == "medium"

    def test_overprovisioned_cpu_just_below_20(self):
        inst = make_instance(cpu_avg_7d=19.9, connections_avg_7d=20.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "overprovisioned"

    def test_not_overprovisioned_at_exactly_20(self):
        # cpu == 20.0 is NOT < 20.0
        inst = make_instance(cpu_avg_7d=20.0, connections_avg_7d=20.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "healthy"

    def test_overprovisioned_confidence_is_medium(self):
        inst = make_instance(cpu_avg_7d=15.0, connections_avg_7d=50.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["confidence"] == "medium"


# ---------------------------------------------------------------------------
# Classification: healthy
# ---------------------------------------------------------------------------

class TestHealthyClassification:
    def test_healthy_high_cpu(self):
        inst = make_instance(cpu_avg_7d=60.0, connections_avg_7d=100.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "healthy"
        assert result["confidence"] is None

    def test_healthy_exactly_20_cpu(self):
        inst = make_instance(cpu_avg_7d=20.0, connections_avg_7d=100.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "healthy"

    def test_healthy_none_cpu_with_enough_data(self):
        # cpu is None but data_days >= 3 and connections not low → healthy
        inst = make_instance(cpu_avg_7d=None, connections_avg_7d=100.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "healthy"


# ---------------------------------------------------------------------------
# Findings: low_storage
# ---------------------------------------------------------------------------

class TestLowStorageFinding:
    def test_low_storage_below_threshold(self):
        inst = make_instance(free_storage_pct=10.0, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "low_storage" in finding_types

    def test_low_storage_severity_is_critical(self):
        inst = make_instance(free_storage_pct=5.0, data_available_days=7)
        result = classify_rds_instance(inst)
        low_storage = next(f for f in result["findings"] if f["type"] == "low_storage")
        assert low_storage["severity"] == "critical"

    def test_no_low_storage_at_exactly_20(self):
        inst = make_instance(free_storage_pct=20.0, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "low_storage" not in finding_types

    def test_no_low_storage_above_threshold(self):
        inst = make_instance(free_storage_pct=50.0, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "low_storage" not in finding_types

    def test_no_low_storage_when_none(self):
        inst = make_instance(free_storage_pct=None, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "low_storage" not in finding_types

    def test_low_storage_present_even_for_insufficient_data(self):
        # Findings are independent of classification
        inst = make_instance(free_storage_pct=5.0, data_available_days=0)
        result = classify_rds_instance(inst)
        assert result["classification"] == "insufficient_data"
        finding_types = [f["type"] for f in result["findings"]]
        assert "low_storage" in finding_types


# ---------------------------------------------------------------------------
# Findings: backups_disabled
# ---------------------------------------------------------------------------

class TestBackupsDisabledFinding:
    def test_backups_disabled_finding(self):
        inst = make_instance(backups_enabled=False, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "backups_disabled" in finding_types

    def test_backups_disabled_severity_is_medium(self):
        inst = make_instance(backups_enabled=False, data_available_days=7)
        result = classify_rds_instance(inst)
        finding = next(f for f in result["findings"] if f["type"] == "backups_disabled")
        assert finding["severity"] == "medium"

    def test_no_backups_finding_when_enabled(self):
        inst = make_instance(backups_enabled=True, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "backups_disabled" not in finding_types


# ---------------------------------------------------------------------------
# Findings: unnecessary_multi_az
# ---------------------------------------------------------------------------

class TestUnnecessaryMultiAzFinding:
    @pytest.mark.parametrize("name", [
        "my-dev-db", "test-database", "staging-rds", "sandbox-01", "qa-mysql"
    ])
    def test_multi_az_non_prod_keywords(self, name):
        inst = make_instance(name=name, multi_az=True, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "unnecessary_multi_az" in finding_types

    def test_multi_az_non_prod_severity_is_medium(self):
        inst = make_instance(name="dev-db", multi_az=True, data_available_days=7)
        result = classify_rds_instance(inst)
        finding = next(f for f in result["findings"] if f["type"] == "unnecessary_multi_az")
        assert finding["severity"] == "medium"

    def test_no_multi_az_finding_when_single_az(self):
        inst = make_instance(name="dev-db", multi_az=False, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "unnecessary_multi_az" not in finding_types

    def test_no_multi_az_finding_for_prod_name(self):
        inst = make_instance(name="production-db", multi_az=True, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "unnecessary_multi_az" not in finding_types

    def test_keyword_match_is_case_insensitive(self):
        inst = make_instance(name="DEV-DATABASE", multi_az=True, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "unnecessary_multi_az" in finding_types

    def test_keyword_partial_match(self):
        # 'developer' contains 'dev' — should match
        inst = make_instance(name="developer-db", multi_az=True, data_available_days=7)
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "unnecessary_multi_az" in finding_types


# ---------------------------------------------------------------------------
# Multiple findings at once
# ---------------------------------------------------------------------------

class TestMultipleFindings:
    def test_all_three_findings_simultaneously(self):
        inst = make_instance(
            name="dev-db",
            multi_az=True,
            backups_enabled=False,
            free_storage_pct=5.0,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        finding_types = [f["type"] for f in result["findings"]]
        assert "low_storage" in finding_types
        assert "backups_disabled" in finding_types
        assert "unnecessary_multi_az" in finding_types

    def test_no_findings_for_clean_instance(self):
        inst = make_instance(
            name="prod-db",
            multi_az=True,
            backups_enabled=True,
            free_storage_pct=60.0,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# Output contract: enriched dict preserves original fields
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_original_fields_preserved(self):
        inst = make_instance()
        result = classify_rds_instance(inst)
        for key in inst:
            assert key in result

    def test_classification_field_present(self):
        result = classify_rds_instance(make_instance())
        assert "classification" in result

    def test_confidence_field_present(self):
        result = classify_rds_instance(make_instance())
        assert "confidence" in result

    def test_findings_field_is_list(self):
        result = classify_rds_instance(make_instance())
        assert isinstance(result["findings"], list)


# ---------------------------------------------------------------------------
# Confidence scoring: _score_rds_confidence
# ---------------------------------------------------------------------------

class TestRdsConfidenceScoring:
    def test_high_confidence_both_iops_near_zero(self):
        inst = make_instance(read_iops_avg_7d=0.0, write_iops_avg_7d=0.0)
        assert _score_rds_confidence(inst) == "high"

    def test_high_confidence_both_iops_below_threshold(self):
        inst = make_instance(read_iops_avg_7d=0.5, write_iops_avg_7d=0.9)
        assert _score_rds_confidence(inst) == "high"

    def test_medium_confidence_only_read_iops_low(self):
        inst = make_instance(read_iops_avg_7d=0.5, write_iops_avg_7d=5.0)
        assert _score_rds_confidence(inst) == "medium"

    def test_medium_confidence_only_write_iops_low(self):
        inst = make_instance(read_iops_avg_7d=5.0, write_iops_avg_7d=0.5)
        assert _score_rds_confidence(inst) == "medium"

    def test_low_confidence_both_iops_elevated(self):
        inst = make_instance(read_iops_avg_7d=5.0, write_iops_avg_7d=5.0)
        assert _score_rds_confidence(inst) == "low"

    def test_low_confidence_both_iops_none(self):
        inst = make_instance(read_iops_avg_7d=None, write_iops_avg_7d=None)
        assert _score_rds_confidence(inst) == "low"

    def test_medium_confidence_read_iops_none_write_low(self):
        inst = make_instance(read_iops_avg_7d=None, write_iops_avg_7d=0.5)
        assert _score_rds_confidence(inst) == "medium"

    def test_medium_confidence_read_low_write_none(self):
        inst = make_instance(read_iops_avg_7d=0.5, write_iops_avg_7d=None)
        assert _score_rds_confidence(inst) == "medium"

    def test_iops_exactly_at_threshold_not_counted(self):
        # 1.0 is NOT < 1.0
        inst = make_instance(read_iops_avg_7d=1.0, write_iops_avg_7d=1.0)
        assert _score_rds_confidence(inst) == "low"

    def test_iops_just_below_threshold_counted(self):
        inst = make_instance(read_iops_avg_7d=0.99, write_iops_avg_7d=0.99)
        assert _score_rds_confidence(inst) == "high"


# ---------------------------------------------------------------------------
# Confidence scoring via classify_rds_instance (integration)
# ---------------------------------------------------------------------------

class TestConfidenceScoringIntegration:
    def test_idle_high_confidence_via_classify(self):
        inst = make_instance(
            cpu_avg_7d=2.0, connections_avg_7d=1.0,
            read_iops_avg_7d=0.5, write_iops_avg_7d=0.5,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        assert result["classification"] == "idle"
        assert result["confidence"] == "high"

    def test_idle_medium_confidence_via_classify(self):
        inst = make_instance(
            cpu_avg_7d=2.0, connections_avg_7d=1.0,
            read_iops_avg_7d=0.5, write_iops_avg_7d=5.0,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        assert result["classification"] == "idle"
        assert result["confidence"] == "medium"

    def test_idle_low_confidence_via_classify(self):
        inst = make_instance(
            cpu_avg_7d=2.0, connections_avg_7d=1.0,
            read_iops_avg_7d=None, write_iops_avg_7d=None,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        assert result["classification"] == "idle"
        assert result["confidence"] == "low"

    def test_overprovisioned_always_medium_confidence(self):
        inst = make_instance(
            cpu_avg_7d=15.0, connections_avg_7d=50.0,
            read_iops_avg_7d=0.0, write_iops_avg_7d=0.0,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        assert result["classification"] == "overprovisioned"
        assert result["confidence"] == "medium"

    def test_healthy_has_no_confidence(self):
        inst = make_instance(cpu_avg_7d=60.0, connections_avg_7d=100.0, data_available_days=7)
        result = classify_rds_instance(inst)
        assert result["classification"] == "healthy"
        assert result["confidence"] is None

    def test_insufficient_data_has_no_confidence(self):
        inst = make_instance(data_available_days=1)
        result = classify_rds_instance(inst)
        assert result["classification"] == "insufficient_data"
        assert result["confidence"] is None


# ---------------------------------------------------------------------------
# rds_confidence_statement
# ---------------------------------------------------------------------------

class TestRdsConfidenceStatement:
    def test_insufficient_data_statement(self):
        inst = make_instance(data_available_days=1)
        result = classify_rds_instance(inst)
        stmt = rds_confidence_statement(result)
        assert "1 day" in stmt or "day(s)" in stmt

    def test_healthy_statement(self):
        inst = make_instance(cpu_avg_7d=60.0, connections_avg_7d=100.0, data_available_days=7)
        result = classify_rds_instance(inst)
        stmt = rds_confidence_statement(result)
        assert "20%" in stmt or "active" in stmt

    def test_overprovisioned_statement_contains_cpu(self):
        inst = make_instance(cpu_avg_7d=15.0, connections_avg_7d=50.0, data_available_days=7)
        result = classify_rds_instance(inst)
        stmt = rds_confidence_statement(result)
        assert "15.0%" in stmt

    def test_idle_high_confidence_statement(self):
        inst = make_instance(
            cpu_avg_7d=2.0, connections_avg_7d=1.0,
            read_iops_avg_7d=0.5, write_iops_avg_7d=0.5,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        stmt = rds_confidence_statement(result)
        assert "High confidence" in stmt

    def test_idle_low_confidence_statement(self):
        inst = make_instance(
            cpu_avg_7d=2.0, connections_avg_7d=1.0,
            read_iops_avg_7d=None, write_iops_avg_7d=None,
            data_available_days=7,
        )
        result = classify_rds_instance(inst)
        stmt = rds_confidence_statement(result)
        assert "Low confidence" in stmt or "manual" in stmt
