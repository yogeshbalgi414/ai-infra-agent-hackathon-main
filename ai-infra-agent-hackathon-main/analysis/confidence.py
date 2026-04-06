"""
analysis/confidence.py — Confidence scoring engine public API.
Owner: Person 1
Status: IMPLEMENTED (Epic 5)

This module is the canonical entry point for confidence scoring and plain-English
statement generation. The underlying scoring logic lives in ec2_analyzer.py and
rds_analyzer.py (where it is co-located with classification). This module re-exports
the public functions so callers can import from a single place.

Usage:
    from analysis.confidence import ec2_confidence_statement, rds_confidence_statement
"""

from analysis.ec2_analyzer import (
    ec2_confidence_statement,
    _score_confidence as score_ec2_confidence,
)
from analysis.rds_analyzer import (
    rds_confidence_statement,
    _score_rds_confidence as score_rds_confidence,
)

__all__ = [
    "ec2_confidence_statement",
    "rds_confidence_statement",
    "score_ec2_confidence",
    "score_rds_confidence",
]
