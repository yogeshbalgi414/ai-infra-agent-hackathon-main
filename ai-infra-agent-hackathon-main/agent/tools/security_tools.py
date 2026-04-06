"""
agent/tools/security_tools.py — Security Group analysis LangChain tools.
Owner: Person 2
Status: IMPLEMENTED (Epic 4)

Output contract:
{
  "findings": [
    {
      "security_group_id": str,
      "attached_instance_id": str,
      "port": int,
      "protocol": str,
      "source_cidr": str,
      "severity": "critical | high | medium",
      "description": str,
      "recommendation": str
    }
  ]
}
"""

import logging

from langchain_core.tools import tool

from aws.security_fetcher import fetch_security_groups
from analysis.security_analyzer import analyze_security_groups as _analyze

logger = logging.getLogger(__name__)


@tool
def analyze_security_groups(region: str) -> dict:
    """
    Fetch and analyze all Security Groups attached to running EC2 instances in the given region.
    Returns security findings with severity classification and specific remediation recommendations.
    Security findings are always higher priority than cost recommendations.

    Use this tool when the user asks about security risks, open ports, firewall rules,
    Security Groups, SSH exposure, RDP exposure, or database port exposure.
    """
    try:
        groups = fetch_security_groups(region)
        result = _analyze(groups)
        logger.info(
            "Security analysis complete: %d findings in %s",
            len(result.get("findings", [])),
            region,
        )
        return result
    except Exception as exc:
        logger.error("Security analysis failed for region %s: %s", region, exc)
        return {"error": str(exc), "findings": []}
