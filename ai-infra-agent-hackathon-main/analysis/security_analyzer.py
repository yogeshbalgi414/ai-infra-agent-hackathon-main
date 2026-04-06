"""
analysis/security_analyzer.py — Security finding severity classification.
Owner: Person 2
Status: IMPLEMENTED (Epic 4)
"""

import ipaddress
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CRITICAL_PORTS = {
    22: "SSH",
    3389: "RDP",
    3306: "MySQL",
    5432: "PostgreSQL",
    1433: "MSSQL",
    27017: "MongoDB",
}

OPEN_CIDRS = {"0.0.0.0/0", "::/0"}

SENSITIVE_PORT_THRESHOLD = 1024  # ports below this are considered sensitive
BROAD_CIDR_PREFIX = 16           # prefix length strictly less than this is "broad"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_security_groups(groups: list) -> dict:
    """
    Analyze Security Group rules and return findings with severity classification.

    Severity rules (evaluated in order per rule):
      critical — known dangerous port (CRITICAL_PORTS) open to 0.0.0.0/0 or ::/0
      high     — any port below 1024 open to 0.0.0.0/0 or ::/0
      medium   — sensitive port (below 1024) open to a broad CIDR (prefix < /16)
                 that is NOT a fully-open CIDR

    Port range handling:
      - port is None (all-traffic, protocol -1) → treated as all ports open;
        checked against CRITICAL_PORTS and the < 1024 rule
      - port_range_end is set → it's a range; we check if any CRITICAL_PORT
        falls within [port, port_range_end] and whether the range covers < 1024

    Returns: {"findings": [...]}
    """
    findings = []

    for group in groups:
        for rule in group.get("inbound_rules", []):
            cidr = rule.get("source_cidr")
            if cidr is None:
                # SG-to-SG rule — no CIDR to evaluate
                continue

            port = rule.get("port")
            port_range_end = rule.get("port_range_end")
            protocol = rule.get("protocol", "-1")

            # Determine which ports this rule covers
            ports_to_check = _resolve_ports(port, port_range_end, protocol)

            seen_ports = set()
            for check_port in ports_to_check:
                if check_port in seen_ports:
                    continue
                finding = _evaluate_port_cidr(group, rule, check_port, cidr)
                if finding:
                    findings.append(finding)
                    seen_ports.add(check_port)

    return {"findings": findings}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_ports(port, port_range_end, protocol: str) -> list:
    """
    Return the list of representative ports to check for a rule.

    - protocol == '-1' (all traffic) → check all CRITICAL_PORTS + sentinel 0
      to trigger the < 1024 check
    - single port (port_range_end is None) → [port]
    - port range → all CRITICAL_PORTS within range + port itself (for < 1024 check)
    """
    if protocol == "-1" or port is None:
        # All traffic — check every critical port and a representative low port
        return list(CRITICAL_PORTS.keys()) + [80]

    if port_range_end is None:
        # Single port
        return [port]

    # Port range: collect critical ports within range, plus the start port
    ports = [p for p in CRITICAL_PORTS if port <= p <= port_range_end]
    # Also include the start port to trigger the generic < 1024 check
    if port not in ports:
        ports.append(port)
    return ports


def _evaluate_port_cidr(group: dict, rule: dict, port: int, cidr: str):
    """
    Evaluate a single (port, cidr) combination and return a finding dict or None.
    """
    is_open = cidr in OPEN_CIDRS

    # Critical: known dangerous port open to the entire internet
    if is_open and port in CRITICAL_PORTS:
        service = CRITICAL_PORTS[port]
        return _make_finding(
            group, rule, port, cidr, "critical",
            f"{service} port {port} is open to the entire internet (0.0.0.0/0).",
            f"Restrict port {port} to your office IP range or a specific trusted CIDR "
            f"instead of 0.0.0.0/0.",
        )

    # High: any port below 1024 open to the entire internet
    if is_open and port < SENSITIVE_PORT_THRESHOLD:
        return _make_finding(
            group, rule, port, cidr, "high",
            f"Port {port} (below 1024) is open to the entire internet.",
            f"Restrict port {port} to a specific trusted CIDR range.",
        )

    # Medium: sensitive port open to a broad CIDR (not fully public)
    if not is_open and port < SENSITIVE_PORT_THRESHOLD and _is_broad_cidr(cidr):
        return _make_finding(
            group, rule, port, cidr, "medium",
            f"Port {port} is open to a broad CIDR range ({cidr}).",
            f"Restrict port {port} to a narrower CIDR range (/{BROAD_CIDR_PREFIX} or smaller).",
        )

    return None


def _is_broad_cidr(cidr: str) -> bool:
    """
    Return True if the CIDR prefix length is strictly less than /16.
    IPv4 and IPv6 are both supported.
    Returns False for invalid CIDR strings.
    """
    try:
        network = ipaddress.ip_network(cidr, strict=False)
        return network.prefixlen < BROAD_CIDR_PREFIX
    except ValueError:
        return False


def _make_finding(group: dict, rule: dict, port: int, cidr: str,
                  severity: str, description: str, recommendation: str) -> dict:
    """Build a finding dict matching the tool output contract."""
    return {
        "security_group_id": group["group_id"],
        "attached_instance_id": group["attached_instance_id"],
        "port": port,
        "protocol": rule.get("protocol"),
        "source_cidr": cidr,
        "severity": severity,
        "description": description,
        "recommendation": recommendation,
    }
