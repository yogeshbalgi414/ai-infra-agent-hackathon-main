"""
analysis/ec2_analyzer.py — EC2 classification, confidence scoring, right-sizing.
Owner: Person 1
Status: IMPLEMENTED (Epic 2)
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (from BRD)
# ---------------------------------------------------------------------------

CPU_IDLE_THRESHOLD = 5.0          # below this → idle
CPU_OVERPROV_THRESHOLD = 20.0     # 5–20% → overprovisioned
CPU_UNDERPROV_THRESHOLD = 80.0    # above this → underprovisioned
STOPPED_DAYS_THRESHOLD = 7        # stopped longer than this → flagged
INSUFFICIENT_DATA_DAYS = 3        # fewer days than this → insufficient_data

NETWORK_NEAR_ZERO_BYTES = 1000.0  # bytes/s
DISK_NEAR_ZERO_OPS = 1.0          # ops/s

# ---------------------------------------------------------------------------
# Instance size ordering for right-sizing
# Ordered smallest → largest within each family, then across families.
# ---------------------------------------------------------------------------

INSTANCE_SIZE_ORDER = [
    "t3.nano", "t3.micro", "t3.small", "t3.medium",
    "t3.large", "t3.xlarge", "t3.2xlarge",
    "m5.large", "m5.xlarge", "m5.2xlarge", "m5.4xlarge",
    "r5.large", "r5.xlarge", "r5.2xlarge",
]

# t3.small is the minimum size for overprovisioned detection per spec
MINIMUM_OVERPROV_SIZE = "t3.small"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_instance(instance: dict, region: str = None) -> dict:
    """
    Classify an EC2 instance based on utilization metrics.

    Adds to the instance dict:
      - classification: idle | overprovisioned | healthy | underprovisioned
                        | stopped | insufficient_data
      - confidence:     high | medium | low | None
      - recommended_type: str | None  (only for overprovisioned on-demand)
      - savings_usd:    float | None  (only for overprovisioned on-demand)
      - purchasing_note: str | None   (reserved/spot advisory)

    Returns the enriched dict (does not mutate the original).
    """
    inst = dict(instance)
    state = inst.get("state", "")
    data_days = inst.get("data_available_days", 0)
    cpu = inst.get("cpu_avg_7d")
    purchasing_type = inst.get("purchasing_type", "on-demand")

    # Defaults
    inst.setdefault("recommended_type", None)
    inst.setdefault("savings_usd", None)
    inst.setdefault("purchasing_note", None)

    # --- Stopped instance check (before metrics check) ---
    if state == "stopped":
        inst["classification"] = "stopped"
        inst["confidence"] = None
        return inst

    # --- Insufficient data ---
    if data_days < INSUFFICIENT_DATA_DAYS:
        inst["classification"] = "insufficient_data"
        inst["confidence"] = None
        return inst

    if cpu is None:
        inst["classification"] = "insufficient_data"
        inst["confidence"] = None
        return inst

    # --- Idle ---
    if cpu < CPU_IDLE_THRESHOLD:
        inst["classification"] = "idle"
        inst["confidence"] = _score_confidence(inst)
        inst["purchasing_note"] = _purchasing_note(purchasing_type, "idle")
        return inst

    # --- Overprovisioned ---
    if CPU_IDLE_THRESHOLD <= cpu < CPU_OVERPROV_THRESHOLD:
        if _is_larger_than_t3_small(inst.get("type", "")):
            inst["classification"] = "overprovisioned"
            inst["confidence"] = "medium"
            inst["purchasing_note"] = _purchasing_note(purchasing_type, "overprovisioned")
            if purchasing_type == "on-demand":
                target = recommend_downsize(inst.get("type", ""))
                if target:
                    from analysis.cost_estimator import estimate_ec2_savings
                    inst["recommended_type"] = target
                    inst["savings_usd"] = estimate_ec2_savings(inst["type"], target, region=region)
            return inst
        # CPU in overprovisioned range but already at/below t3.small → healthy
        inst["classification"] = "healthy"
        inst["confidence"] = None
        return inst

    # --- Underprovisioned ---
    if cpu > CPU_UNDERPROV_THRESHOLD:
        inst["classification"] = "underprovisioned"
        inst["confidence"] = "high"
        return inst

    # --- Healthy ---
    inst["classification"] = "healthy"
    inst["confidence"] = None
    return inst


def recommend_downsize(instance_type: str) -> str | None:
    """
    Return the next smaller instance type in INSTANCE_SIZE_ORDER,
    or None if already at the minimum or type is unknown.
    """
    if instance_type not in INSTANCE_SIZE_ORDER:
        return None
    idx = INSTANCE_SIZE_ORDER.index(instance_type)
    if idx == 0:
        return None
    return INSTANCE_SIZE_ORDER[idx - 1]


def ec2_confidence_statement(instance: dict) -> str:
    """
    Generate a plain-English confidence statement for the given instance.
    Used by the LangChain tool to populate the confidence_statement field.
    """
    classification = instance.get("classification")
    confidence = instance.get("confidence")
    data_days = instance.get("data_available_days", 0)

    if classification == "insufficient_data":
        return (
            f"Only {data_days} day(s) of CloudWatch data available. "
            "Recommend manual review before taking any action."
        )

    if classification == "stopped":
        days = instance.get("days_in_current_state", 0)
        return (
            f"Instance has been stopped for {days} day(s). "
            "No utilization data available for stopped instances."
        )

    if classification == "underprovisioned":
        cpu = instance.get("cpu_avg_7d")
        cpu_str = f"{cpu:.1f}%" if cpu is not None else "unknown"
        return (
            f"High confidence — CPU utilization averaged {cpu_str} over 7 days, "
            "consistently above the 80% threshold."
        )

    if classification == "healthy":
        cpu = instance.get("cpu_avg_7d")
        if cpu is not None:
            return (
                f"Instance is healthy — CPU averaged {cpu:.1f}% over 7 days, "
                "within normal operating range."
            )
        return "Instance is healthy — no utilization concerns detected."

    # idle / overprovisioned — scored confidence
    signals = []
    if instance.get("cpu_avg_7d") is not None and instance["cpu_avg_7d"] < CPU_IDLE_THRESHOLD:
        signals.append("CPU utilization")
    if instance.get("network_in_avg_7d") is not None and instance["network_in_avg_7d"] < NETWORK_NEAR_ZERO_BYTES:
        signals.append("inbound network traffic")
    if instance.get("network_out_avg_7d") is not None and instance["network_out_avg_7d"] < NETWORK_NEAR_ZERO_BYTES:
        signals.append("outbound network traffic")
    if instance.get("disk_read_ops_avg_7d") is not None and instance["disk_read_ops_avg_7d"] < DISK_NEAR_ZERO_OPS:
        signals.append("disk activity")

    signal_str = ", ".join(signals) if signals else "CPU utilization"

    if confidence == "high":
        return f"High confidence — {signal_str} have all been near zero for 7 days."
    if confidence == "medium":
        return f"Medium confidence — {signal_str} near zero, but not all signals are available."
    return (
        "Low confidence — only CPU data is available. "
        "Recommend checking network and disk metrics manually before acting."
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _score_confidence(instance: dict) -> str:
    """Score idle confidence based on secondary signals (network + disk)."""
    signals = 0
    net_in = instance.get("network_in_avg_7d")
    net_out = instance.get("network_out_avg_7d")
    disk = instance.get("disk_read_ops_avg_7d")

    if net_in is not None and net_in < NETWORK_NEAR_ZERO_BYTES:
        signals += 1
    if net_out is not None and net_out < NETWORK_NEAR_ZERO_BYTES:
        signals += 1
    if disk is not None and disk < DISK_NEAR_ZERO_OPS:
        signals += 1

    if signals >= 2:
        return "high"
    if signals == 1:
        return "medium"
    return "low"


def _is_larger_than_t3_small(instance_type: str) -> bool:
    """Return True if instance_type is larger than t3.small in INSTANCE_SIZE_ORDER."""
    if instance_type not in INSTANCE_SIZE_ORDER:
        # Unknown type — assume it could be large, flag it
        return True
    min_idx = INSTANCE_SIZE_ORDER.index(MINIMUM_OVERPROV_SIZE)
    return INSTANCE_SIZE_ORDER.index(instance_type) > min_idx


def _purchasing_note(purchasing_type: str, classification: str) -> str | None:
    """Return advisory note for reserved/spot instances."""
    if purchasing_type == "reserved":
        return (
            "This instance is on a Reserved Instance commitment. "
            "Stopping it does not reduce cost — the reservation fee continues."
        )
    if purchasing_type == "spot":
        return (
            "This is a Spot Instance. Verify it is not part of an intentional "
            "batch workload before taking any action."
        )
    return None
