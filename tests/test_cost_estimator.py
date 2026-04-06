"""
tests/test_cost_estimator.py — Unit tests for cost estimation and summary.
Owner: Person 1
Epic: 6

Tests cover:
  - estimate_ec2_monthly_cost()    — known types, unknown type
  - estimate_ec2_savings()         — downsize savings
  - estimate_rds_monthly_cost()    — single-AZ, Multi-AZ, unknown type
  - build_cost_summary()           — mixed idle/overprovisioned, sorting, top 3, empty input
  - rds_analyzer savings_usd       — overprovisioned RDS instances get savings_usd
"""

import pytest
from analysis.cost_estimator import (
    estimate_ec2_monthly_cost,
    estimate_ec2_savings,
    estimate_rds_monthly_cost,
    build_cost_summary,
    EC2_HOURLY_PRICES,
    RDS_HOURLY_PRICES,
    HOURS_PER_MONTH,
)
from analysis.rds_analyzer import classify_rds_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ec2_instance(id_, name, classification, monthly_cost, savings_usd=None):
    inst = {
        "id": id_,
        "name": name,
        "classification": classification,
        "monthly_cost_usd": monthly_cost,
    }
    if savings_usd is not None:
        inst["savings_usd"] = savings_usd
    return inst


def make_rds_instance(id_, name, classification, monthly_cost, savings_usd=None):
    inst = {
        "id": id_,
        "name": name,
        "classification": classification,
        "monthly_cost_usd": monthly_cost,
    }
    if savings_usd is not None:
        inst["savings_usd"] = savings_usd
    return inst


def make_rds_raw(cpu=50.0, connections=20.0, read_iops=10.0, write_iops=10.0,
                 data_days=7, instance_class="db.m5.xlarge", multi_az=False,
                 name="db-test"):
    return {
        "id": "db-test",
        "name": name,
        "class": instance_class,
        "engine": "mysql",
        "status": "available",
        "multi_az": multi_az,
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


# ---------------------------------------------------------------------------
# estimate_ec2_monthly_cost()
# ---------------------------------------------------------------------------

class TestEstimateEC2MonthlyCost:
    def test_known_type_m5_xlarge(self):
        expected = round(EC2_HOURLY_PRICES["m5.xlarge"] * HOURS_PER_MONTH, 2)
        assert estimate_ec2_monthly_cost("m5.xlarge") == expected

    def test_known_type_t3_micro(self):
        expected = round(EC2_HOURLY_PRICES["t3.micro"] * HOURS_PER_MONTH, 2)
        assert estimate_ec2_monthly_cost("t3.micro") == expected

    def test_known_type_r5_large(self):
        expected = round(EC2_HOURLY_PRICES["r5.large"] * HOURS_PER_MONTH, 2)
        assert estimate_ec2_monthly_cost("r5.large") == expected

    def test_unknown_type_returns_zero(self):
        assert estimate_ec2_monthly_cost("x99.superlarge") == 0.0

    def test_unknown_type_does_not_crash(self):
        result = estimate_ec2_monthly_cost("nonexistent.type")
        assert isinstance(result, float)

    def test_returns_float(self):
        assert isinstance(estimate_ec2_monthly_cost("m5.large"), float)

    def test_all_known_types_positive(self):
        for itype in EC2_HOURLY_PRICES:
            assert estimate_ec2_monthly_cost(itype) > 0


# ---------------------------------------------------------------------------
# estimate_ec2_savings()
# ---------------------------------------------------------------------------

class TestEstimateEC2Savings:
    def test_downsize_m5_xlarge_to_m5_large(self):
        expected = round(
            estimate_ec2_monthly_cost("m5.xlarge") - estimate_ec2_monthly_cost("m5.large"), 2
        )
        assert estimate_ec2_savings("m5.xlarge", "m5.large") == expected

    def test_savings_positive_when_downsizing(self):
        assert estimate_ec2_savings("m5.2xlarge", "m5.xlarge") > 0

    def test_savings_zero_when_same_type(self):
        assert estimate_ec2_savings("m5.large", "m5.large") == 0.0

    def test_unknown_current_type_returns_zero(self):
        # unknown current type → 0.0 cost, so savings = 0.0 - target_cost (negative)
        result = estimate_ec2_savings("unknown.type", "m5.large")
        assert result == round(0.0 - estimate_ec2_monthly_cost("m5.large"), 2)

    def test_unknown_target_type_returns_zero(self):
        # current cost - 0.0 = current cost (not negative)
        result = estimate_ec2_savings("m5.large", "unknown.type")
        assert result == estimate_ec2_monthly_cost("m5.large")


# ---------------------------------------------------------------------------
# estimate_rds_monthly_cost() — US-6.1
# ---------------------------------------------------------------------------

class TestEstimateRDSMonthlyCost:
    def test_single_az_db_t3_medium(self):
        expected = round(RDS_HOURLY_PRICES["db.t3.medium"] * HOURS_PER_MONTH, 2)
        assert estimate_rds_monthly_cost("db.t3.medium") == expected

    def test_single_az_db_r5_large(self):
        expected = round(RDS_HOURLY_PRICES["db.r5.large"] * HOURS_PER_MONTH, 2)
        assert estimate_rds_monthly_cost("db.r5.large", multi_az=False) == expected

    def test_multi_az_doubles_price(self):
        single = estimate_rds_monthly_cost("db.r5.large", multi_az=False)
        multi = estimate_rds_monthly_cost("db.r5.large", multi_az=True)
        assert multi == round(single * 2, 2)

    def test_multi_az_db_m5_xlarge(self):
        expected = round(RDS_HOURLY_PRICES["db.m5.xlarge"] * HOURS_PER_MONTH * 2, 2)
        assert estimate_rds_monthly_cost("db.m5.xlarge", multi_az=True) == expected

    def test_unknown_class_returns_zero(self):
        assert estimate_rds_monthly_cost("db.x99.huge") == 0.0

    def test_unknown_class_multi_az_returns_zero(self):
        assert estimate_rds_monthly_cost("db.unknown", multi_az=True) == 0.0

    def test_unknown_class_does_not_crash(self):
        result = estimate_rds_monthly_cost("db.nonexistent")
        assert isinstance(result, float)

    def test_returns_float(self):
        assert isinstance(estimate_rds_monthly_cost("db.t3.micro"), float)

    def test_all_known_classes_positive(self):
        for cls in RDS_HOURLY_PRICES:
            assert estimate_rds_monthly_cost(cls) > 0

    def test_multi_az_always_greater_than_single(self):
        for cls in RDS_HOURLY_PRICES:
            assert estimate_rds_monthly_cost(cls, multi_az=True) > estimate_rds_monthly_cost(cls, multi_az=False)


# ---------------------------------------------------------------------------
# build_cost_summary() — US-6.2, US-6.3, US-6.4
# ---------------------------------------------------------------------------

class TestBuildCostSummaryEmpty:
    def test_empty_inputs_returns_zero_spend(self):
        result = build_cost_summary({"instances": []}, {"instances": []})
        assert result["total_monthly_spend_usd"] == 0.0

    def test_empty_inputs_returns_zero_waste(self):
        result = build_cost_summary({"instances": []}, {"instances": []})
        assert result["total_monthly_waste_usd"] == 0.0

    def test_empty_inputs_returns_zero_annual_savings(self):
        result = build_cost_summary({"instances": []}, {"instances": []})
        assert result["potential_annual_savings_usd"] == 0.0

    def test_empty_inputs_top_3_is_empty_list(self):
        result = build_cost_summary({"instances": []}, {"instances": []})
        assert result["top_3_actions"] == []

    def test_missing_instances_key_handled(self):
        result = build_cost_summary({}, {})
        assert result["total_monthly_spend_usd"] == 0.0


class TestBuildCostSummaryTotalSpend:
    def test_total_spend_sums_all_instances(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "web", "healthy", 140.16),
            make_ec2_instance("i-2", "api", "idle", 70.08),
        ]}
        rds = {"instances": [
            make_rds_instance("db-1", "prod-db", "healthy", 175.20),
        ]}
        result = build_cost_summary(ec2, rds)
        assert result["total_monthly_spend_usd"] == round(140.16 + 70.08 + 175.20, 2)

    def test_total_spend_includes_healthy_instances(self):
        ec2 = {"instances": [make_ec2_instance("i-1", "web", "healthy", 100.0)]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["total_monthly_spend_usd"] == 100.0


class TestBuildCostSummaryWaste:
    def test_idle_instance_contributes_full_cost_to_waste(self):
        ec2 = {"instances": [make_ec2_instance("i-1", "idle-box", "idle", 140.16)]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["total_monthly_waste_usd"] == 140.16

    def test_overprovisioned_instance_contributes_savings_to_waste(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "big-box", "overprovisioned", 280.32, savings_usd=140.16)
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["total_monthly_waste_usd"] == 140.16

    def test_overprovisioned_with_zero_savings_not_in_waste(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "box", "overprovisioned", 100.0, savings_usd=0.0)
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["total_monthly_waste_usd"] == 0.0
        assert result["top_3_actions"] == []

    def test_healthy_instance_not_in_waste(self):
        ec2 = {"instances": [make_ec2_instance("i-1", "web", "healthy", 140.16)]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["total_monthly_waste_usd"] == 0.0

    def test_mixed_idle_and_overprovisioned(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "idle-box", "idle", 140.16),
            make_ec2_instance("i-2", "big-box", "overprovisioned", 280.32, savings_usd=70.08),
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["total_monthly_waste_usd"] == round(140.16 + 70.08, 2)

    def test_rds_idle_contributes_to_waste(self):
        rds = {"instances": [make_rds_instance("db-1", "idle-db", "idle", 175.20)]}
        result = build_cost_summary({"instances": []}, rds)
        assert result["total_monthly_waste_usd"] == 175.20

    def test_rds_overprovisioned_contributes_savings_to_waste(self):
        rds = {"instances": [
            make_rds_instance("db-1", "big-db", "overprovisioned", 249.12, savings_usd=124.56)
        ]}
        result = build_cost_summary({"instances": []}, rds)
        assert result["total_monthly_waste_usd"] == 124.56


class TestBuildCostSummaryAnnualSavings:
    def test_annual_savings_is_12x_monthly_waste(self):
        ec2 = {"instances": [make_ec2_instance("i-1", "idle", "idle", 100.0)]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["potential_annual_savings_usd"] == round(100.0 * 12, 2)

    def test_annual_savings_zero_when_no_waste(self):
        ec2 = {"instances": [make_ec2_instance("i-1", "web", "healthy", 100.0)]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["potential_annual_savings_usd"] == 0.0


class TestBuildCostSummarySorting:
    def test_top_3_sorted_by_waste_descending(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "small", "idle", 50.0),
            make_ec2_instance("i-2", "large", "idle", 200.0),
            make_ec2_instance("i-3", "medium", "idle", 100.0),
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        wastes = [a["waste_usd"] for a in result["top_3_actions"]]
        assert wastes == sorted(wastes, reverse=True)

    def test_top_3_limited_to_three_items(self):
        ec2 = {"instances": [
            make_ec2_instance(f"i-{i}", f"box-{i}", "idle", float(i * 10))
            for i in range(1, 7)
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        assert len(result["top_3_actions"]) == 3

    def test_top_3_contains_highest_waste_items(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "box-1", "idle", 10.0),
            make_ec2_instance("i-2", "box-2", "idle", 300.0),
            make_ec2_instance("i-3", "box-3", "idle", 200.0),
            make_ec2_instance("i-4", "box-4", "idle", 100.0),
            make_ec2_instance("i-5", "box-5", "idle", 50.0),
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        ids = [a["id"] for a in result["top_3_actions"]]
        assert "i-2" in ids
        assert "i-3" in ids
        assert "i-4" in ids
        assert "i-1" not in ids

    def test_fewer_than_3_waste_items_returns_all(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "box-1", "idle", 100.0),
            make_ec2_instance("i-2", "box-2", "idle", 200.0),
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        assert len(result["top_3_actions"]) == 2


class TestBuildCostSummaryOutputShape:
    def test_output_has_all_required_keys(self):
        result = build_cost_summary({"instances": []}, {"instances": []})
        assert "total_monthly_spend_usd" in result
        assert "total_monthly_waste_usd" in result
        assert "potential_annual_savings_usd" in result
        assert "top_3_actions" in result

    def test_top_3_action_has_required_fields(self):
        ec2 = {"instances": [make_ec2_instance("i-1", "idle-box", "idle", 100.0)]}
        result = build_cost_summary(ec2, {"instances": []})
        action = result["top_3_actions"][0]
        assert "id" in action
        assert "name" in action
        assert "waste_usd" in action
        assert "reason" in action

    def test_idle_action_reason_is_idle(self):
        ec2 = {"instances": [make_ec2_instance("i-1", "idle-box", "idle", 100.0)]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["top_3_actions"][0]["reason"] == "idle"

    def test_overprovisioned_action_reason_is_overprovisioned(self):
        ec2 = {"instances": [
            make_ec2_instance("i-1", "big-box", "overprovisioned", 200.0, savings_usd=50.0)
        ]}
        result = build_cost_summary(ec2, {"instances": []})
        assert result["top_3_actions"][0]["reason"] == "overprovisioned"


# ---------------------------------------------------------------------------
# RDS savings_usd field — task 6.5
# ---------------------------------------------------------------------------

class TestRDSSavingsUSD:
    def test_overprovisioned_rds_has_savings_usd(self):
        inst = make_rds_raw(cpu=10.0, connections=50.0, instance_class="db.m5.xlarge")
        result = classify_rds_instance(inst)
        assert result["classification"] == "overprovisioned"
        assert result["savings_usd"] is not None
        assert result["savings_usd"] > 0

    def test_overprovisioned_rds_has_recommended_class(self):
        inst = make_rds_raw(cpu=10.0, connections=50.0, instance_class="db.m5.xlarge")
        result = classify_rds_instance(inst)
        assert result["recommended_class"] == "db.m5.large"

    def test_overprovisioned_rds_savings_matches_cost_diff(self):
        inst = make_rds_raw(cpu=10.0, connections=50.0, instance_class="db.m5.xlarge")
        result = classify_rds_instance(inst)
        from analysis.cost_estimator import estimate_rds_monthly_cost
        expected = round(
            estimate_rds_monthly_cost("db.m5.xlarge") - estimate_rds_monthly_cost("db.m5.large"), 2
        )
        assert result["savings_usd"] == expected

    def test_overprovisioned_rds_multi_az_savings_accounts_for_multiplier(self):
        inst = make_rds_raw(cpu=10.0, connections=50.0, instance_class="db.m5.xlarge", multi_az=True)
        result = classify_rds_instance(inst)
        from analysis.cost_estimator import estimate_rds_monthly_cost
        expected = round(
            estimate_rds_monthly_cost("db.m5.xlarge", multi_az=True)
            - estimate_rds_monthly_cost("db.m5.large", multi_az=True), 2
        )
        assert result["savings_usd"] == expected

    def test_idle_rds_has_no_savings_usd(self):
        inst = make_rds_raw(cpu=2.0, connections=1.0)
        result = classify_rds_instance(inst)
        assert result["classification"] == "idle"
        assert result["savings_usd"] is None

    def test_healthy_rds_has_no_savings_usd(self):
        inst = make_rds_raw(cpu=60.0, connections=100.0)
        result = classify_rds_instance(inst)
        assert result["classification"] == "healthy"
        assert result["savings_usd"] is None

    def test_minimum_class_overprovisioned_has_no_savings(self):
        # db.t3.micro is the smallest — no downsize possible
        inst = make_rds_raw(cpu=10.0, connections=50.0, instance_class="db.t3.micro")
        result = classify_rds_instance(inst)
        assert result["classification"] == "overprovisioned"
        assert result["savings_usd"] is None
        assert result["recommended_class"] is None
