# Replace Hardcoded EC2/RDS Pricing with Dynamic AWS Pricing API Fetching

**Issue #42** - In_Progress

**Author:** 
**Created:** 2026-03-27T05:47:02.092295
**URL:** https://microforge.dev.andinolabs.ai/pulse-testing/api/v1/teams/7d671209-b067-4e92-becd-724187db4776/projects/4/stories/42

---

## Overview
EC2 and RDS instance costs in **analysis/cost_estimator.py** are currently hardcoded as static dictionaries locked to `us-east-1` on-demand pricing. This story replaces those hardcoded values with dynamic pricing fetched from the AWS Pricing API via boto3, enabling accurate, region-aware cost estimates. A graceful fallback to the existing hardcoded values must be preserved for resilience.

## Technical Context
- Hardcoded pricing dictionaries for EC2 (lines 18–33) and RDS (lines 40–49) live in **analysis/cost_estimator.py**
- All boto3 clients must be instantiated via the existing `get_client()` factory in **aws/client.py** — never via direct `boto3.client()` calls
- The AWS Pricing API (`pricing` service) is a global service available only through the `us-east-1` endpoint, but can retrieve pricing for any region
- Functions directly affected: **estimate_ec2_monthly_cost()**, **estimate_rds_monthly_cost()**, and **build_cost_summary()** in **analysis/cost_estimator.py**
- Downstream callers include **agent/tools/ec2_tools.py**, **agent/tools/rds_tools.py**, and **agent/agent.py**
- LocalStack support must be considered — the Pricing API may not be available in LocalStack environments

## Acceptance Criteria
- A new **aws/pricing_fetcher.py** module fetches EC2 and RDS on-demand prices using the AWS Pricing API via the existing `get_client()` factory in **aws/client.py**
- Pricing is fetched dynamically per **instance_type**, **region**, and **operating_system** for EC2, and per **instance_class** and **database_engine** for RDS
- Fetched prices are cached in-memory (per session) to avoid redundant API calls on repeated lookups
- If the Pricing API call fails (e.g., permission error, network issue, LocalStack unavailability), the system gracefully falls back to the existing hardcoded values in **cost_estimator.py** and logs a warning
- **estimate_ec2_monthly_cost()** and **estimate_rds_monthly_cost()** in **cost_estimator.py** use dynamic pricing by default when the API is reachable
- Multi-AZ RDS pricing is correctly derived from the dynamic single-AZ price using the existing 2x multiplier, or fetched directly if the API provides it
- Pricing supports the currently active AWS region, not just `us-east-1`

## Testing Criteria
- Unit tests mock the Pricing API response and assert correct price extraction in **aws/pricing_fetcher.py**
- Unit tests verify graceful fallback to hardcoded values when the Pricing API raises an exception
- Unit tests confirm **estimate_ec2_monthly_cost()** returns the dynamically fetched value when the API is available
- Unit tests confirm **estimate_rds_monthly_cost()** returns the correct Multi-AZ price using dynamic pricing
- Integration tests (or mock-compatible tests) verify the `get_client("pricing")` call succeeds through the existing client factory in **aws/client.py**
- All existing tests in **test_cost_estimator.py** continue to pass with no regressions