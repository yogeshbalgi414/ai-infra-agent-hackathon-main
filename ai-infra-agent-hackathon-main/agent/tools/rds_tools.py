"""
agent/tools/rds_tools.py — RDS analysis LangChain tools.
Owner: Person 2
Status: IMPLEMENTED (Epic 3)

Output contract:
{
  "instances": [
    {
      "id": str, "name": str, "class": str, "engine": str, "status": str,
      "multi_az": bool, "backups_enabled": bool,
      "cpu_avg_7d": float | None, "connections_avg_7d": float | None,
      "read_iops_avg_7d": float | None, "write_iops_avg_7d": float | None,
      "free_storage_pct": float | None, "freeable_memory_mb": float | None,
      "monthly_cost_usd": float,
      "confidence": "high | medium | low | null",
      "classification": "idle | overprovisioned | healthy | insufficient_data",
      "data_available_days": int,
      "findings": [{"type": str, "severity": str}],
      "confidence_statement": str
    }
  ]
}
"""

import logging

from langchain_core.tools import tool

from aws.rds_fetcher import fetch_rds_instances, fetch_rds_metrics
from analysis.rds_analyzer import classify_rds_instance, rds_confidence_statement
from analysis.cost_estimator import estimate_rds_monthly_cost

logger = logging.getLogger(__name__)


@tool
def analyze_rds_instances(region: str) -> dict:
    """
    Fetch and analyze all RDS instances in the given AWS region.
    Returns classification, confidence score, cost estimates, and additional findings per instance.
    """
    try:
        raw_instances = fetch_rds_instances(region)
        results = []

        for inst in raw_instances:
            db_id = inst["id"]
            allocated_gb = inst.get("allocated_storage_gb", 0)

            # Fetch CloudWatch metrics
            metrics = fetch_rds_metrics(db_id, region, allocated_storage_gb=allocated_gb)

            # Merge instance data + metrics
            combined = {**inst, **metrics}

            # Classify
            classified = classify_rds_instance(combined, region=region)

            # Cost estimate
            monthly_cost = estimate_rds_monthly_cost(
                classified.get("class", ""),
                multi_az=classified.get("multi_az", False),
                region=region,
            )
            classified["monthly_cost_usd"] = monthly_cost

            # Confidence statement (additive — not in base contract)
            classified["confidence_statement"] = rds_confidence_statement(classified)

            results.append(classified)

        logger.info("Analyzed %d RDS instances in region %s", len(results), region)
        return {"instances": results}

    except Exception as exc:
        logger.error("analyze_rds_instances failed for region %s: %s", region, exc)
        return {"error": str(exc), "instances": []}
