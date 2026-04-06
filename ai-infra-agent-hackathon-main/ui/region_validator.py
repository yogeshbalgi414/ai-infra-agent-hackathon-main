"""
ui/region_validator.py — AWS region validation helper.
Owner: Person 3
Status: IMPLEMENTED (Epic 8)

Extracted as a pure-Python module so it can be unit-tested
without a running Streamlit server.
"""

import re

VALID_REGION_PATTERN = r'^[a-z]{2}-[a-z]+-\d+$'


def is_valid_region(region: str) -> bool:
    """
    Return True if region matches the AWS region format.
    Valid examples: us-east-1, eu-west-2, ap-southeast-1, ca-central-1.
    """
    if not region or not isinstance(region, str):
        return False
    return bool(re.match(VALID_REGION_PATTERN, region.strip()))
