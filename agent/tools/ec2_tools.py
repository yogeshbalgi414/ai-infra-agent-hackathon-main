"""
agent/tools/ec2_tools.py — EC2 analysis LangChain tool.
Owner: Person 1
Status: IMPLEMENTED (Epic 2)

Output contract (matches structure.md):
{
  "instances": [
    {
      "id": str, "name": str, "type": str,
      "state": "running | stopped",
      "purchasing_type": "on-demand | reserved | spot",
      "cpu_avg_7d": float | None,
      "network_in_avg_7d": float | None,
      "network_out_avg_7d": float | None,
      "disk_read_ops_avg_7d": float | None,
      "monthly_cost_usd": float,
      "days_in_current_state": int,
      "confidence": "high | medium | low" | None,
      "classification": "idle | overprovisioned | healthy | underprovisioned | stopped | insufficient_data",
      "data_available_days": int,
      "recommended_type": str | None,
      "savings_usd": float | None,
      "purchasing_note": str | None,
      "confidence_statement": str
    }
  ]
}
"""

import logging
from langchain_core.tools import tool

from aws.ec2_fetcher import fetch_ec2_instances, fetch_ec2_metrics
from analysis.ec2_analyzer import classify_instance, ec2_confidence_statement
from analysis.cost_estimator import estimate_ec2_monthly_cost

logger = logging.getLogger(__name__)


@tool
def analyze_ec2_instances(region: str) -> dict:
    """
    Fetch and analyze all EC2 instances in the given AWS region.
    Returns classification, confidence score, cost estimates, and right-sizing
    recommendations for each instance.

    Use this tool when the user asks about EC2 instances, idle resources,
    overprovisioned compute, stopped instances, or EC2 cost waste.
    """
    try:
        raw_instances = fetch_ec2_instances(region)
        results = []

        for inst in raw_instances:
            # Fetch CloudWatch metrics (running instances only — stopped have no metrics)
            if inst.get("state") == "running":
                metrics = fetch_ec2_metrics(inst["id"], region)
            else:
                metrics = {
                    "cpu_avg_7d": None,
                    "network_in_avg_7d": None,
                    "network_out_avg_7d": None,
                    "disk_read_ops_avg_7d": None,
                    "data_available_days": 0,
                }

            enriched = {**inst, **metrics}
            classified = classify_instance(enriched, region=region)

            # Add monthly cost and confidence statement
            classified["monthly_cost_usd"] = estimate_ec2_monthly_cost(inst["type"], region=region)
            classified["confidence_statement"] = ec2_confidence_statement(classified)

            results.append(classified)

        logger.info("EC2 analysis complete: %d instances in %s", len(results), region)
        return {"instances": results}

    except Exception as exc:
        logger.error("EC2 analysis failed for region %s: %s", region, exc)
        return {"error": str(exc), "instances": []}
