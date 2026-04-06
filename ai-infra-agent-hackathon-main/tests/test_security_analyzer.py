"""
tests/test_security_analyzer.py — Unit tests for Security Group analysis.
Owner: Person 2
Status: IMPLEMENTED (Epic 4)
"""

import pytest
from analysis.security_analyzer import (
    analyze_security_groups,
    _is_broad_cidr,
    CRITICAL_PORTS,
    OPEN_CIDRS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_group(group_id="sg-001", instance_id="i-001", rules=None):
    """Return a minimal Security Group dict."""
    return {
        "group_id": group_id,
        "group_name": "test-sg",
        "attached_instance_id": instance_id,
        "inbound_rules": rules or [],
    }


def make_rule(port, cidr, protocol="tcp", port_range_end=None, source_sg=None):
    """Return a minimal inbound rule dict."""
    return {
        "port": port,
        "port_range_end": port_range_end,
        "protocol": protocol,
        "source_cidr": cidr,
        "source_sg": source_sg,
    }


def get_findings(groups):
    return analyze_security_groups(groups)["findings"]


# ---------------------------------------------------------------------------
# US-4.2 — Open SSH Detection
# ---------------------------------------------------------------------------

class TestOpenSSHDetection:
    def test_ssh_open_to_internet_ipv4_is_critical(self):
        group = make_group(rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"
        assert findings[0]["port"] == 22

    def test_ssh_open_to_internet_ipv6_is_critical(self):
        group = make_group(rules=[make_rule(22, "::/0")])
        findings = get_findings([group])
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"

    def test_ssh_restricted_to_specific_cidr_no_finding(self):
        group = make_group(rules=[make_rule(22, "10.0.0.0/8")])
        # 10.0.0.0/8 is broad but not open internet — medium, not critical
        # But wait: /8 < /16 so it IS broad → medium finding
        findings = get_findings([group])
        # Should be medium (broad CIDR), not critical
        assert all(f["severity"] != "critical" for f in findings)

    def test_ssh_restricted_to_narrow_cidr_no_finding(self):
        group = make_group(rules=[make_rule(22, "10.0.1.0/24")])
        findings = get_findings([group])
        assert findings == []

    def test_ssh_finding_description_mentions_ssh(self):
        group = make_group(rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "SSH" in findings[0]["description"]

    def test_ssh_finding_recommendation_mentions_port_22(self):
        group = make_group(rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "22" in findings[0]["recommendation"]

    def test_ssh_finding_has_correct_sg_and_instance(self):
        group = make_group(group_id="sg-abc", instance_id="i-xyz",
                           rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        assert findings[0]["security_group_id"] == "sg-abc"
        assert findings[0]["attached_instance_id"] == "i-xyz"


# ---------------------------------------------------------------------------
# US-4.3 — Open RDP Detection
# ---------------------------------------------------------------------------

class TestOpenRDPDetection:
    def test_rdp_open_to_internet_is_critical(self):
        group = make_group(rules=[make_rule(3389, "0.0.0.0/0")])
        findings = get_findings([group])
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"
        assert findings[0]["port"] == 3389

    def test_rdp_restricted_to_specific_cidr_no_critical(self):
        group = make_group(rules=[make_rule(3389, "192.168.1.0/24")])
        findings = get_findings([group])
        assert all(f["severity"] != "critical" for f in findings)

    def test_rdp_finding_description_mentions_rdp(self):
        group = make_group(rules=[make_rule(3389, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "RDP" in findings[0]["description"]


# ---------------------------------------------------------------------------
# US-4.4 — Open Database Port Detection
# ---------------------------------------------------------------------------

class TestOpenDatabasePortDetection:
    @pytest.mark.parametrize("port,service", [
        (3306, "MySQL"),
        (5432, "PostgreSQL"),
        (1433, "MSSQL"),
        (27017, "MongoDB"),
    ])
    def test_db_port_open_to_internet_is_critical(self, port, service):
        group = make_group(rules=[make_rule(port, "0.0.0.0/0")])
        findings = get_findings([group])
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"
        assert findings[0]["port"] == port

    def test_mysql_finding_description_mentions_mysql(self):
        group = make_group(rules=[make_rule(3306, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "MySQL" in findings[0]["description"]

    def test_postgres_finding_description_mentions_postgres(self):
        group = make_group(rules=[make_rule(5432, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "PostgreSQL" in findings[0]["description"]

    def test_db_port_restricted_to_narrow_cidr_no_finding(self):
        group = make_group(rules=[make_rule(3306, "10.0.1.0/24")])
        findings = get_findings([group])
        assert findings == []


# ---------------------------------------------------------------------------
# US-4.5 — Broad CIDR Detection
# ---------------------------------------------------------------------------

class TestBroadCIDRDetection:
    def test_port_443_with_slash_8_is_medium(self):
        group = make_group(rules=[make_rule(443, "10.0.0.0/8")])
        findings = get_findings([group])
        assert len(findings) == 1
        assert findings[0]["severity"] == "medium"

    def test_port_443_with_slash_16_no_finding(self):
        group = make_group(rules=[make_rule(443, "10.0.0.0/16")])
        findings = get_findings([group])
        assert findings == []

    def test_port_443_with_slash_24_no_finding(self):
        group = make_group(rules=[make_rule(443, "10.0.1.0/24")])
        findings = get_findings([group])
        assert findings == []

    def test_port_above_1024_with_broad_cidr_no_finding(self):
        # Port 8080 is above 1024 — broad CIDR check only applies to sensitive ports
        group = make_group(rules=[make_rule(8080, "10.0.0.0/8")])
        findings = get_findings([group])
        assert findings == []

    def test_port_1023_with_broad_cidr_is_medium(self):
        # 1023 is below 1024 — should trigger medium
        group = make_group(rules=[make_rule(1023, "10.0.0.0/8")])
        findings = get_findings([group])
        assert len(findings) == 1
        assert findings[0]["severity"] == "medium"

    def test_port_1024_with_broad_cidr_no_finding(self):
        # 1024 is NOT below 1024
        group = make_group(rules=[make_rule(1024, "10.0.0.0/8")])
        findings = get_findings([group])
        assert findings == []

    def test_broad_cidr_finding_mentions_cidr_in_description(self):
        group = make_group(rules=[make_rule(443, "10.0.0.0/8")])
        findings = get_findings([group])
        assert "10.0.0.0/8" in findings[0]["description"]

    def test_broad_cidr_recommendation_mentions_slash_16(self):
        group = make_group(rules=[make_rule(443, "10.0.0.0/8")])
        findings = get_findings([group])
        assert "/16" in findings[0]["recommendation"]


# ---------------------------------------------------------------------------
# Priority: critical takes precedence over high/medium for same port
# ---------------------------------------------------------------------------

class TestSeverityPriority:
    def test_critical_port_open_to_internet_is_critical_not_high(self):
        # Port 22 is both a critical port AND below 1024 — should be critical
        group = make_group(rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        assert findings[0]["severity"] == "critical"

    def test_port_80_open_to_internet_is_high_not_critical(self):
        # Port 80 is not in CRITICAL_PORTS but is below 1024
        group = make_group(rules=[make_rule(80, "0.0.0.0/0")])
        findings = get_findings([group])
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"

    def test_port_443_open_to_internet_is_high(self):
        group = make_group(rules=[make_rule(443, "0.0.0.0/0")])
        findings = get_findings([group])
        assert findings[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# SG-to-SG rules (no CIDR) — should produce no findings
# ---------------------------------------------------------------------------

class TestSGSourceRules:
    def test_sg_source_rule_produces_no_finding(self):
        rule = {
            "port": 22,
            "port_range_end": None,
            "protocol": "tcp",
            "source_cidr": None,
            "source_sg": "sg-other",
        }
        group = make_group(rules=[rule])
        findings = get_findings([group])
        assert findings == []


# ---------------------------------------------------------------------------
# All-traffic rules (protocol -1)
# ---------------------------------------------------------------------------

class TestAllTrafficRules:
    def test_all_traffic_open_to_internet_raises_critical_for_ssh(self):
        rule = make_rule(None, "0.0.0.0/0", protocol="-1")
        group = make_group(rules=[rule])
        findings = get_findings([group])
        # Should find at least one critical finding (SSH, RDP, etc.)
        severities = {f["severity"] for f in findings}
        assert "critical" in severities

    def test_all_traffic_open_to_internet_includes_known_ports(self):
        rule = make_rule(None, "0.0.0.0/0", protocol="-1")
        group = make_group(rules=[rule])
        findings = get_findings([group])
        found_ports = {f["port"] for f in findings}
        # All critical ports should be flagged
        for port in CRITICAL_PORTS:
            assert port in found_ports


# ---------------------------------------------------------------------------
# Port range rules
# ---------------------------------------------------------------------------

class TestPortRangeRules:
    def test_range_containing_ssh_port_is_critical(self):
        # Range 20-25 contains port 22
        rule = make_rule(20, "0.0.0.0/0", port_range_end=25)
        group = make_group(rules=[rule])
        findings = get_findings([group])
        critical = [f for f in findings if f["severity"] == "critical"]
        assert len(critical) >= 1
        assert any(f["port"] == 22 for f in critical)

    def test_range_not_containing_critical_port_is_high(self):
        # Range 8000-8100 — all above 1024, no critical ports
        rule = make_rule(8000, "0.0.0.0/0", port_range_end=8100)
        group = make_group(rules=[rule])
        findings = get_findings([group])
        # No critical or high (all above 1024)
        assert findings == []

    def test_range_covering_low_ports_is_high(self):
        # Range 80-90 — below 1024, not critical ports
        rule = make_rule(80, "0.0.0.0/0", port_range_end=90)
        group = make_group(rules=[rule])
        findings = get_findings([group])
        assert len(findings) >= 1
        assert findings[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# Multiple groups and rules
# ---------------------------------------------------------------------------

class TestMultipleGroupsAndRules:
    def test_multiple_groups_each_produce_findings(self):
        groups = [
            make_group(group_id="sg-001", instance_id="i-001",
                       rules=[make_rule(22, "0.0.0.0/0")]),
            make_group(group_id="sg-002", instance_id="i-002",
                       rules=[make_rule(3389, "0.0.0.0/0")]),
        ]
        findings = get_findings(groups)
        sg_ids = {f["security_group_id"] for f in findings}
        assert "sg-001" in sg_ids
        assert "sg-002" in sg_ids

    def test_clean_group_produces_no_findings(self):
        group = make_group(rules=[make_rule(443, "10.0.1.0/24")])
        findings = get_findings([group])
        assert findings == []

    def test_empty_groups_list_returns_empty_findings(self):
        result = analyze_security_groups([])
        assert result == {"findings": []}

    def test_group_with_no_rules_produces_no_findings(self):
        group = make_group(rules=[])
        findings = get_findings([group])
        assert findings == []


# ---------------------------------------------------------------------------
# Output contract validation
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_result_has_findings_key(self):
        result = analyze_security_groups([])
        assert "findings" in result

    def test_finding_has_all_required_fields(self):
        group = make_group(rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        required = {
            "security_group_id", "attached_instance_id", "port",
            "protocol", "source_cidr", "severity", "description", "recommendation",
        }
        for field in required:
            assert field in findings[0], f"Missing field: {field}"

    def test_severity_values_are_valid(self):
        groups = [
            make_group(group_id="sg-1", rules=[make_rule(22, "0.0.0.0/0")]),
            make_group(group_id="sg-2", rules=[make_rule(80, "0.0.0.0/0")]),
            make_group(group_id="sg-3", rules=[make_rule(443, "10.0.0.0/8")]),
        ]
        findings = get_findings(groups)
        valid_severities = {"critical", "high", "medium"}
        for f in findings:
            assert f["severity"] in valid_severities

    def test_recommendation_is_specific_not_generic(self):
        group = make_group(rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        rec = findings[0]["recommendation"]
        # Should mention the specific port, not just a generic message
        assert "22" in rec or "SSH" in rec.upper() or "office" in rec.lower()


# ---------------------------------------------------------------------------
# US-4.6 — Remediation recommendations are specific
# ---------------------------------------------------------------------------

class TestRemediationRecommendations:
    def test_ssh_recommendation_mentions_restrict(self):
        group = make_group(rules=[make_rule(22, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "Restrict" in findings[0]["recommendation"] or "restrict" in findings[0]["recommendation"]

    def test_rdp_recommendation_mentions_port_3389(self):
        group = make_group(rules=[make_rule(3389, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "3389" in findings[0]["recommendation"]

    def test_mysql_recommendation_mentions_port_3306(self):
        group = make_group(rules=[make_rule(3306, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "3306" in findings[0]["recommendation"]

    def test_high_severity_recommendation_mentions_trusted_cidr(self):
        group = make_group(rules=[make_rule(80, "0.0.0.0/0")])
        findings = get_findings([group])
        assert "trusted" in findings[0]["recommendation"].lower() or "CIDR" in findings[0]["recommendation"]


# ---------------------------------------------------------------------------
# Task 4.11 — _is_broad_cidr() edge cases
# ---------------------------------------------------------------------------

class TestIsBroadCidr:
    def test_slash_8_is_broad(self):
        assert _is_broad_cidr("10.0.0.0/8") is True

    def test_slash_15_is_broad(self):
        assert _is_broad_cidr("10.0.0.0/15") is True

    def test_slash_16_is_not_broad(self):
        assert _is_broad_cidr("10.0.0.0/16") is False

    def test_slash_24_is_not_broad(self):
        assert _is_broad_cidr("192.168.1.0/24") is False

    def test_slash_32_is_not_broad(self):
        assert _is_broad_cidr("192.168.1.1/32") is False

    def test_open_cidr_0_0_0_0_slash_0_is_broad(self):
        # 0.0.0.0/0 has prefix 0 < 16 → broad
        assert _is_broad_cidr("0.0.0.0/0") is True

    def test_ipv6_slash_8_is_broad(self):
        assert _is_broad_cidr("2001::/8") is True

    def test_ipv6_slash_16_is_not_broad(self):
        assert _is_broad_cidr("2001:db8::/16") is False

    def test_ipv6_slash_128_is_not_broad(self):
        assert _is_broad_cidr("::1/128") is False

    def test_invalid_cidr_returns_false(self):
        assert _is_broad_cidr("not-a-cidr") is False

    def test_empty_string_returns_false(self):
        assert _is_broad_cidr("") is False
