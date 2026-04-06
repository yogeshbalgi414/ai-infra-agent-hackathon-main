"""
analysis/rds_analyzer.py — RDS classification, confidence scoring, findings.
Owner: Person 2
Status: IMPLEMENTED (Epic 3)
"""

import logging

logger = logging.getLogger(__name__)

# Keywords that indicate a non-production RDS instance
NON_PROD_KEYWORDS = ["dev", "test", "staging", "sandbox", "qa"]

# RDS instance class ordering (smallest → largest) for right-sizing
RDS_INSTANCE_SIZE_ORDER = [
    "db.t3.micro", "db.t3.small", "db.t3.medium", "db.t3.large",
    "db.m5.large", "db.m5.xlarge",
    "db.r5.large", "db.r5.xlarge",
]

# Thresholds
IDLE_CPU_THRESHOLD = 5.0          # %
IDLE_CONNECTIONS_THRESHOLD = 5    # count
OVERPROV_CPU_THRESHOLD = 20.0     # %
INSUFFICIENT_DATA_DAYS = 3        # minimum days required
LOW_STORAGE_THRESHOLD = 20.0      # %
IOPS_IDLE_THRESHOLD = 1.0         # ops/s


def classify_rds_instance(instance: dict, region: str = None) -> dict:
    """
    Classify an RDS instance based on utilization metrics.

    Classification rules (evaluated in order):
        insufficient_data — data_available_days < 3
        idle              — cpu < 5% AND connections < 5 (dual-signal)
        overprovisioned   — cpu < 20%
        healthy           — everything else

    Additional findings (independent of classification):
        low_storage          — free_storage_pct < 20%  (severity: critical)
        backups_disabled     — backups_enabled == False (severity: medium)
        unnecessary_multi_az — multi_az AND name contains non-prod keyword (severity: medium)

    Returns the input dict enriched with:
        classification: str
        confidence: 'high' | 'medium' | 'low' | None
        findings: list[dict]
    """
    cpu = instance.get("cpu_avg_7d")
    connections = instance.get("connections_avg_7d")
    data_days = instance.get("data_available_days", 0)
    findings = []

    # --- Classification ---
    recommended_class = None
    savings_usd = None

    if data_days < INSUFFICIENT_DATA_DAYS:
        classification = "insufficient_data"
        confidence = None
    elif (
        cpu is not None and cpu < IDLE_CPU_THRESHOLD
        and connections is not None and connections < IDLE_CONNECTIONS_THRESHOLD
    ):
        classification = "idle"
        confidence = _score_rds_confidence(instance)
    elif cpu is not None and cpu < OVERPROV_CPU_THRESHOLD:
        classification = "overprovisioned"
        confidence = "medium"
        target = recommend_rds_downsize(instance.get("class", ""))
        if target:
            from analysis.cost_estimator import estimate_rds_monthly_cost
            multi_az = instance.get("multi_az", False)
            current_cost = estimate_rds_monthly_cost(instance.get("class", ""), multi_az, region=region)
            target_cost = estimate_rds_monthly_cost(target, multi_az, region=region)
            recommended_class = target
            savings_usd = round(current_cost - target_cost, 2)
    else:
        classification = "healthy"
        confidence = None

    # --- Additional findings ---
    free_storage_pct = instance.get("free_storage_pct")
    if free_storage_pct is not None and free_storage_pct < LOW_STORAGE_THRESHOLD:
        findings.append({"type": "low_storage", "severity": "critical"})

    if not instance.get("backups_enabled", True):
        findings.append({"type": "backups_disabled", "severity": "medium"})

    name_lower = instance.get("name", "").lower()
    if instance.get("multi_az") and any(kw in name_lower for kw in NON_PROD_KEYWORDS):
        findings.append({"type": "unnecessary_multi_az", "severity": "medium"})

    return {
        **instance,
        "classification": classification,
        "confidence": confidence,
        "recommended_class": recommended_class,
        "savings_usd": savings_usd,
        "findings": findings,
    }


def _score_rds_confidence(instance: dict) -> str:
    """
    Score confidence for idle RDS instances using IOPS as secondary signals.

    Signals:
        read_iops_avg_7d  < 1.0  → +1
        write_iops_avg_7d < 1.0  → +1

    Returns:
        'high'   — both IOPS signals near zero (2 signals)
        'medium' — one IOPS signal near zero (1 signal)
        'low'    — no IOPS data or neither near zero (0 signals)
    """
    signals = 0
    read_iops = instance.get("read_iops_avg_7d")
    write_iops = instance.get("write_iops_avg_7d")

    if read_iops is not None and read_iops < IOPS_IDLE_THRESHOLD:
        signals += 1
    if write_iops is not None and write_iops < IOPS_IDLE_THRESHOLD:
        signals += 1

    if signals >= 2:
        return "high"
    if signals == 1:
        return "medium"
    return "low"


def rds_confidence_statement(instance: dict) -> str:
    """
    Return a plain-English explanation of the confidence level for an RDS instance.
    Used by the LangChain tool to enrich agent responses.
    """
    classification = instance.get("classification")
    confidence = instance.get("confidence")
    data_days = instance.get("data_available_days", 0)

    if classification == "insufficient_data":
        return (
            f"Only {data_days} day(s) of CloudWatch data available — "
            "need at least 3 days for a reliable assessment."
        )

    if classification == "healthy":
        return "CPU utilization is above 20% — instance appears to be in active use."

    if classification == "overprovisioned":
        cpu = instance.get("cpu_avg_7d")
        cpu_str = f"{cpu:.1f}%" if cpu is not None else "unknown"
        return (
            f"Average CPU over 7 days is {cpu_str} (below 20%). "
            "Medium confidence — CPU alone suggests overprovisioning but connection data is not below idle threshold."
        )

    if classification == "idle":
        read_iops = instance.get("read_iops_avg_7d")
        write_iops = instance.get("write_iops_avg_7d")

        if confidence == "high":
            return (
                "High confidence idle: CPU < 5%, connections < 5, "
                "read IOPS < 1, and write IOPS < 1 over 7 days."
            )
        if confidence == "medium":
            iops_detail = ""
            if read_iops is not None and read_iops < IOPS_IDLE_THRESHOLD:
                iops_detail = "Read IOPS near zero but write IOPS data unavailable or elevated."
            elif write_iops is not None and write_iops < IOPS_IDLE_THRESHOLD:
                iops_detail = "Write IOPS near zero but read IOPS data unavailable or elevated."
            else:
                iops_detail = "One IOPS signal near zero."
            return (
                f"Medium confidence idle: CPU < 5% and connections < 5. {iops_detail}"
            )
        # low confidence
        return (
            "Low confidence idle: CPU < 5% and connections < 5, "
            "but IOPS data is unavailable or elevated — manual verification recommended."
        )

    return "No confidence assessment available."


def recommend_rds_downsize(instance_class: str) -> str | None:
    """
    Return the next smaller RDS instance class in RDS_INSTANCE_SIZE_ORDER,
    or None if already at the minimum or class is unknown.
    """
    if instance_class not in RDS_INSTANCE_SIZE_ORDER:
        return None
    idx = RDS_INSTANCE_SIZE_ORDER.index(instance_class)
    if idx == 0:
        return None
    return RDS_INSTANCE_SIZE_ORDER[idx - 1]
