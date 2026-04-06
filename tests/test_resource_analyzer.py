"""
tests/test_resource_analyzer.py — Unit tests for resource overview analysis.
Owner: Person 1
Status: IMPLEMENTED (Epic 11)
"""

import pytest
from analysis.resource_analyzer import analyze_resources, _analyze_s3, _analyze_lambda, _analyze_other


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bucket(name="my-bucket", public_access_blocked=True):
    return {"name": name, "created_at": "2024-01-01T00:00:00+00:00", "public_access_blocked": public_access_blocked}


def make_function(name="my-fn", runtime="python3.11", invocations_7d=100.0):
    return {"name": name, "runtime": runtime, "last_modified": "2024-01-01", "invocations_7d": invocations_7d}


def make_other(vpcs=1, eips=None, ebs=None):
    eips = eips or []
    ebs = ebs or []
    return {
        "vpcs": vpcs,
        "unattached_elastic_ips": len(eips),
        "unattached_ebs_volumes": len(ebs),
        "unattached_eip_details": eips,
        "unattached_ebs_details": ebs,
    }


# ---------------------------------------------------------------------------
# S3 analysis
# ---------------------------------------------------------------------------

class TestS3Analysis:
    def test_public_bucket_raises_finding(self):
        buckets = [make_bucket("public-bucket", public_access_blocked=False)]
        result = _analyze_s3(buckets)
        assert result["public_buckets"] == 1
        assert len(result["findings"]) == 1
        assert "public-bucket" in result["findings"][0]

    def test_blocked_bucket_no_finding(self):
        buckets = [make_bucket("safe-bucket", public_access_blocked=True)]
        result = _analyze_s3(buckets)
        assert result["public_buckets"] == 0
        assert result["findings"] == []

    def test_unknown_status_bucket_no_finding(self):
        # public_access_blocked=None means unknown — should not flag
        buckets = [make_bucket("unknown-bucket", public_access_blocked=None)]
        result = _analyze_s3(buckets)
        assert result["public_buckets"] == 0
        assert result["findings"] == []

    def test_total_bucket_count_correct(self):
        buckets = [
            make_bucket("b1", True),
            make_bucket("b2", False),
            make_bucket("b3", True),
        ]
        result = _analyze_s3(buckets)
        assert result["total_buckets"] == 3
        assert result["public_buckets"] == 1

    def test_empty_buckets_returns_zeros(self):
        result = _analyze_s3([])
        assert result["total_buckets"] == 0
        assert result["public_buckets"] == 0
        assert result["findings"] == []

    def test_multiple_public_buckets_multiple_findings(self):
        buckets = [make_bucket(f"bucket-{i}", False) for i in range(3)]
        result = _analyze_s3(buckets)
        assert result["public_buckets"] == 3
        assert len(result["findings"]) == 3

    def test_finding_mentions_public_access_block(self):
        buckets = [make_bucket("exposed", False)]
        result = _analyze_s3(buckets)
        assert "public access block" in result["findings"][0].lower()


# ---------------------------------------------------------------------------
# Lambda analysis
# ---------------------------------------------------------------------------

class TestLambdaAnalysis:
    def test_zero_invocations_raises_finding(self):
        functions = [make_function("idle-fn", invocations_7d=0.0)]
        result = _analyze_lambda(functions)
        assert result["unused_functions"] == 1
        assert len(result["findings"]) == 1
        assert "idle-fn" in result["findings"][0]

    def test_active_function_no_finding(self):
        functions = [make_function("active-fn", invocations_7d=500.0)]
        result = _analyze_lambda(functions)
        assert result["unused_functions"] == 0
        assert result["findings"] == []

    def test_null_invocations_not_flagged(self):
        # None means no CloudWatch data — insufficient data, should not flag
        functions = [make_function("unknown-fn", invocations_7d=None)]
        result = _analyze_lambda(functions)
        assert result["unused_functions"] == 0
        assert result["findings"] == []

    def test_total_function_count_correct(self):
        functions = [
            make_function("fn1", invocations_7d=0.0),
            make_function("fn2", invocations_7d=100.0),
            make_function("fn3", invocations_7d=None),
        ]
        result = _analyze_lambda(functions)
        assert result["total_functions"] == 3
        assert result["unused_functions"] == 1

    def test_empty_functions_returns_zeros(self):
        result = _analyze_lambda([])
        assert result["total_functions"] == 0
        assert result["unused_functions"] == 0
        assert result["findings"] == []

    def test_finding_mentions_runtime(self):
        functions = [make_function("fn", runtime="python3.11", invocations_7d=0.0)]
        result = _analyze_lambda(functions)
        assert "python3.11" in result["findings"][0]

    def test_finding_mentions_zero_invocations(self):
        functions = [make_function("fn", invocations_7d=0.0)]
        result = _analyze_lambda(functions)
        assert "zero invocations" in result["findings"][0].lower() or "0" in result["findings"][0]


# ---------------------------------------------------------------------------
# Other resources analysis
# ---------------------------------------------------------------------------

class TestOtherResourcesAnalysis:
    def test_unattached_eip_raises_finding(self):
        other = make_other(eips=[{"allocation_id": "eipalloc-123", "public_ip": "1.2.3.4"}])
        result = _analyze_other(other)
        assert result["unattached_elastic_ips"] == 1
        assert len(result["findings"]) == 1
        assert "1.2.3.4" in result["findings"][0]

    def test_unattached_ebs_raises_finding(self):
        other = make_other(ebs=[{"volume_id": "vol-abc", "size_gb": 100}])
        result = _analyze_other(other)
        assert result["unattached_ebs_volumes"] == 1
        assert len(result["findings"]) == 1
        assert "vol-abc" in result["findings"][0]

    def test_no_unattached_resources_no_findings(self):
        other = make_other()
        result = _analyze_other(other)
        assert result["findings"] == []
        assert result["unattached_elastic_ips"] == 0
        assert result["unattached_ebs_volumes"] == 0

    def test_vpc_count_correct(self):
        other = make_other(vpcs=3)
        result = _analyze_other(other)
        assert result["vpcs"] == 3

    def test_eip_finding_mentions_cost(self):
        other = make_other(eips=[{"allocation_id": "eipalloc-1", "public_ip": "5.6.7.8"}])
        result = _analyze_other(other)
        assert "charged" in result["findings"][0].lower() or "cost" in result["findings"][0].lower()

    def test_ebs_finding_mentions_size(self):
        other = make_other(ebs=[{"volume_id": "vol-xyz", "size_gb": 50}])
        result = _analyze_other(other)
        assert "50" in result["findings"][0]

    def test_multiple_eips_multiple_findings(self):
        eips = [
            {"allocation_id": f"eipalloc-{i}", "public_ip": f"1.2.3.{i}"}
            for i in range(3)
        ]
        other = make_other(eips=eips)
        result = _analyze_other(other)
        assert len(result["findings"]) == 3

    def test_empty_other_returns_zeros(self):
        result = _analyze_other({})
        assert result["vpcs"] == 0
        assert result["unattached_elastic_ips"] == 0
        assert result["unattached_ebs_volumes"] == 0
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# analyze_resources integration
# ---------------------------------------------------------------------------

class TestAnalyzeResourcesIntegration:
    def test_full_output_contract_shape(self):
        result = analyze_resources([], [], make_other())
        assert "overview" in result
        overview = result["overview"]
        assert "s3" in overview
        assert "lambda" in overview
        assert "other" in overview

    def test_s3_section_has_required_keys(self):
        result = analyze_resources([], [], make_other())
        s3 = result["overview"]["s3"]
        assert "total_buckets" in s3
        assert "public_buckets" in s3
        assert "findings" in s3

    def test_lambda_section_has_required_keys(self):
        result = analyze_resources([], [], make_other())
        lmb = result["overview"]["lambda"]
        assert "total_functions" in lmb
        assert "unused_functions" in lmb
        assert "findings" in lmb

    def test_other_section_has_required_keys(self):
        result = analyze_resources([], [], make_other())
        other = result["overview"]["other"]
        assert "vpcs" in other
        assert "unattached_elastic_ips" in other
        assert "unattached_ebs_volumes" in other
        assert "findings" in other

    def test_findings_are_lists_of_strings(self):
        buckets = [make_bucket("pub", False)]
        functions = [make_function("idle", invocations_7d=0.0)]
        other = make_other(eips=[{"allocation_id": "e1", "public_ip": "1.1.1.1"}])
        result = analyze_resources(buckets, functions, other)
        for section in result["overview"].values():
            assert isinstance(section["findings"], list)
            for f in section["findings"]:
                assert isinstance(f, str)

    def test_counts_are_integers(self):
        result = analyze_resources(
            [make_bucket("b", False)],
            [make_function("f", invocations_7d=0.0)],
            make_other(vpcs=2),
        )
        assert isinstance(result["overview"]["s3"]["total_buckets"], int)
        assert isinstance(result["overview"]["lambda"]["total_functions"], int)
        assert isinstance(result["overview"]["other"]["vpcs"], int)

    def test_all_empty_inputs_returns_zeros(self):
        result = analyze_resources([], [], make_other(vpcs=0))
        assert result["overview"]["s3"]["total_buckets"] == 0
        assert result["overview"]["lambda"]["total_functions"] == 0
        assert result["overview"]["other"]["vpcs"] == 0
        assert result["overview"]["s3"]["findings"] == []
        assert result["overview"]["lambda"]["findings"] == []
        assert result["overview"]["other"]["findings"] == []
