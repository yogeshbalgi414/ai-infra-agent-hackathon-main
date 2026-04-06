"""
tests/test_pricing_fetcher.py — Unit tests for aws/pricing_fetcher.py.
Issue: 42 — Replace Hardcoded EC2/RDS Pricing with Dynamic AWS Pricing API Fetching

Tests cover:
  - fetch_ec2_price()         — correct extraction from mock API response, caching, fallback
  - fetch_rds_price()         — correct extraction from mock API response, caching, fallback
  - _extract_on_demand_price() — parsing on-demand price from PriceList entries
  - get_client("pricing")     — called with correct service and region via factory
  - estimate_ec2_monthly_cost() — uses dynamic price when API available
  - estimate_rds_monthly_cost() — uses dynamic price, correct Multi-AZ pricing
"""

import json
import pytest
from unittest.mock import patch, MagicMock

import aws.pricing_fetcher as pricing_fetcher
from aws.pricing_fetcher import (
    fetch_ec2_price,
    fetch_rds_price,
    _extract_on_demand_price,
    clear_cache,
    PRICING_REGION,
)


# ---------------------------------------------------------------------------
# Helpers — build mock PriceList items
# ---------------------------------------------------------------------------

def _make_price_list_item(usd_price: str) -> str:
    """Build a minimal PriceList JSON string as returned by the AWS Pricing API."""
    item = {
        "product": {"attributes": {}},
        "terms": {
            "OnDemand": {
                "TERMKEY.OFFERKEY": {
                    "priceDimensions": {
                        "TERMKEY.OFFERKEY.DIMKEY": {
                            "unit": "Hrs",
                            "pricePerUnit": {"USD": usd_price},
                        }
                    }
                }
            }
        },
    }
    return json.dumps(item)


def _make_get_products_response(usd_price: str) -> dict:
    return {"PriceList": [_make_price_list_item(usd_price)]}


def _make_empty_get_products_response() -> dict:
    return {"PriceList": []}


# ---------------------------------------------------------------------------
# Setup / Teardown
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_pricing_cache():
    """Clear the in-memory pricing cache before each test."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# _extract_on_demand_price()
# ---------------------------------------------------------------------------

class TestExtractOnDemandPrice:
    def test_extracts_price_from_valid_response(self):
        response = _make_get_products_response("0.1920000000")
        assert _extract_on_demand_price(response) == pytest.approx(0.192, rel=1e-6)

    def test_returns_none_for_empty_price_list(self):
        assert _extract_on_demand_price({"PriceList": []}) is None

    def test_returns_none_for_zero_price(self):
        response = _make_get_products_response("0.0000000000")
        assert _extract_on_demand_price(response) is None

    def test_returns_none_when_price_list_key_missing(self):
        assert _extract_on_demand_price({}) is None

    def test_parses_string_price_list_items(self):
        """PriceList items may arrive as JSON strings — ensure they are parsed."""
        response = _make_get_products_response("0.0960000000")
        result = _extract_on_demand_price(response)
        assert result == pytest.approx(0.096, rel=1e-6)

    def test_parses_dict_price_list_items(self):
        """PriceList items may arrive as dicts (not strings) — both must be handled."""
        item = json.loads(_make_price_list_item("0.0520000000"))
        response = {"PriceList": [item]}
        result = _extract_on_demand_price(response)
        assert result == pytest.approx(0.052, rel=1e-6)


# ---------------------------------------------------------------------------
# fetch_ec2_price()
# ---------------------------------------------------------------------------

class TestFetchEC2Price:
    def test_returns_hourly_price_on_success(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.1920000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            result = fetch_ec2_price("m5.xlarge", "us-east-1")
        assert result == pytest.approx(0.192, rel=1e-6)

    def test_uses_pricing_region_for_client(self):
        """get_client must always be called with the global pricing region (us-east-1)."""
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.0960000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client) as mock_get_client:
            fetch_ec2_price("m5.large", "ap-southeast-1")
        mock_get_client.assert_called_once_with("pricing", PRICING_REGION)

    def test_passes_instance_type_filter(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.0416000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            fetch_ec2_price("t3.medium", "us-east-1")
        call_kwargs = mock_client.get_products.call_args[1]
        filters = {f["Field"]: f["Value"] for f in call_kwargs["Filters"]}
        assert filters["instanceType"] == "t3.medium"

    def test_translates_region_to_full_name(self):
        """Region code must be translated to the full AWS region name in the filter."""
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.0416000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            fetch_ec2_price("t3.medium", "us-east-1")
        call_kwargs = mock_client.get_products.call_args[1]
        filters = {f["Field"]: f["Value"] for f in call_kwargs["Filters"]}
        assert filters["location"] == "US East (N. Virginia)"

    def test_returns_none_when_api_raises_exception(self):
        mock_client = MagicMock()
        mock_client.get_products.side_effect = Exception("AccessDenied")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            result = fetch_ec2_price("m5.large", "us-east-1")
        assert result is None

    def test_returns_none_when_get_client_raises(self):
        with patch("aws.pricing_fetcher.get_client", side_effect=Exception("Network error")):
            result = fetch_ec2_price("m5.large", "us-east-1")
        assert result is None

    def test_returns_none_for_empty_price_list(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_empty_get_products_response()
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            result = fetch_ec2_price("x99.huge", "us-east-1")
        assert result is None

    def test_caches_result_on_second_call(self):
        """Second call for the same key must not invoke the API again."""
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.0960000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            first = fetch_ec2_price("m5.large", "us-east-1")
            second = fetch_ec2_price("m5.large", "us-east-1")
        assert first == second
        assert mock_client.get_products.call_count == 1

    def test_cache_is_keyed_by_instance_type_region_and_os(self):
        """Different keys must trigger separate API calls."""
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.0960000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            fetch_ec2_price("m5.large", "us-east-1", "Linux")
            fetch_ec2_price("m5.large", "us-west-2", "Linux")
        assert mock_client.get_products.call_count == 2

    def test_default_os_is_linux(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.0960000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            fetch_ec2_price("m5.large", "us-east-1")
        call_kwargs = mock_client.get_products.call_args[1]
        filters = {f["Field"]: f["Value"] for f in call_kwargs["Filters"]}
        assert filters["operatingSystem"] == "Linux"

    def test_logs_warning_on_api_failure(self, caplog):
        import logging
        mock_client = MagicMock()
        mock_client.get_products.side_effect = Exception("Timeout")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="aws.pricing_fetcher"):
                fetch_ec2_price("m5.large", "us-east-1")
        assert any("m5.large" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# fetch_rds_price()
# ---------------------------------------------------------------------------

class TestFetchRDSPrice:
    def test_returns_hourly_price_on_success(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.1710000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            result = fetch_rds_price("db.m5.large", "us-east-1")
        assert result == pytest.approx(0.171, rel=1e-6)

    def test_uses_pricing_region_for_client(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.1710000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client) as mock_get_client:
            fetch_rds_price("db.m5.large", "eu-west-1")
        mock_get_client.assert_called_once_with("pricing", PRICING_REGION)

    def test_passes_instance_class_filter(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.0680000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            fetch_rds_price("db.t3.medium", "us-east-1")
        call_kwargs = mock_client.get_products.call_args[1]
        filters = {f["Field"]: f["Value"] for f in call_kwargs["Filters"]}
        assert filters["instanceType"] == "db.t3.medium"

    def test_requests_single_az_deployment(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.1710000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            fetch_rds_price("db.m5.large", "us-east-1")
        call_kwargs = mock_client.get_products.call_args[1]
        filters = {f["Field"]: f["Value"] for f in call_kwargs["Filters"]}
        assert filters["deploymentOption"] == "Single-AZ"

    def test_returns_none_when_api_raises(self):
        mock_client = MagicMock()
        mock_client.get_products.side_effect = Exception("AccessDenied")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            result = fetch_rds_price("db.m5.large", "us-east-1")
        assert result is None

    def test_caches_result_on_second_call(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.1710000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            first = fetch_rds_price("db.m5.large", "us-east-1")
            second = fetch_rds_price("db.m5.large", "us-east-1")
        assert first == second
        assert mock_client.get_products.call_count == 1

    def test_default_engine_is_mysql(self):
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_get_products_response("0.1710000000")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            fetch_rds_price("db.m5.large", "us-east-1")
        call_kwargs = mock_client.get_products.call_args[1]
        filters = {f["Field"]: f["Value"] for f in call_kwargs["Filters"]}
        assert filters["databaseEngine"] == "MySQL"

    def test_logs_warning_on_api_failure(self, caplog):
        import logging
        mock_client = MagicMock()
        mock_client.get_products.side_effect = Exception("Timeout")
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="aws.pricing_fetcher"):
                fetch_rds_price("db.m5.large", "us-east-1")
        assert any("db.m5.large" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Dynamic pricing integration with cost_estimator
# ---------------------------------------------------------------------------

class TestEstimateEC2MonthlyCostDynamic:
    def test_uses_dynamic_price_when_api_available(self):
        """estimate_ec2_monthly_cost() should use the dynamic price when API succeeds."""
        dynamic_hourly = 0.200
        with patch("aws.pricing_fetcher.get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_products.return_value = _make_get_products_response(str(dynamic_hourly))
            mock_get_client.return_value = mock_client

            from analysis.cost_estimator import estimate_ec2_monthly_cost, HOURS_PER_MONTH
            result = estimate_ec2_monthly_cost("m5.xlarge", region="us-east-1")

        assert result == round(dynamic_hourly * HOURS_PER_MONTH, 2)

    def test_falls_back_to_hardcoded_when_api_fails(self):
        """estimate_ec2_monthly_cost() must fall back to EC2_HOURLY_PRICES on API failure."""
        with patch("aws.pricing_fetcher.get_client", side_effect=Exception("No network")):
            from analysis.cost_estimator import (
                estimate_ec2_monthly_cost,
                EC2_HOURLY_PRICES,
                HOURS_PER_MONTH,
            )
            result = estimate_ec2_monthly_cost("m5.xlarge", region="us-east-1")

        expected = round(EC2_HOURLY_PRICES["m5.xlarge"] * HOURS_PER_MONTH, 2)
        assert result == expected

    def test_falls_back_for_unknown_type_when_api_returns_none(self):
        """Unknown instance type with empty API result still returns 0.0."""
        with patch("aws.pricing_fetcher.fetch_ec2_price", return_value=None):
            from analysis.cost_estimator import estimate_ec2_monthly_cost
            result = estimate_ec2_monthly_cost("x99.superlarge", region="us-east-1")
        assert result == 0.0

    def test_default_region_does_not_crash(self):
        """Calling without region argument must not raise."""
        with patch("aws.pricing_fetcher.fetch_ec2_price", return_value=None):
            from analysis.cost_estimator import estimate_ec2_monthly_cost
            result = estimate_ec2_monthly_cost("m5.large")
        assert isinstance(result, float)


class TestEstimateRDSMonthlyCostDynamic:
    def test_uses_dynamic_price_single_az(self):
        """estimate_rds_monthly_cost() should use dynamic single-AZ price when API succeeds."""
        dynamic_hourly = 0.200
        with patch("aws.pricing_fetcher.get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_products.return_value = _make_get_products_response(str(dynamic_hourly))
            mock_get_client.return_value = mock_client

            from analysis.cost_estimator import estimate_rds_monthly_cost, HOURS_PER_MONTH
            result = estimate_rds_monthly_cost("db.m5.large", region="us-east-1")

        assert result == round(dynamic_hourly * HOURS_PER_MONTH, 2)

    def test_multi_az_doubles_dynamic_price(self):
        """Multi-AZ must apply 2x multiplier to the dynamic single-AZ price."""
        dynamic_hourly = 0.171
        with patch("aws.pricing_fetcher.get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_products.return_value = _make_get_products_response(str(dynamic_hourly))
            mock_get_client.return_value = mock_client

            from analysis.cost_estimator import estimate_rds_monthly_cost, HOURS_PER_MONTH
            single = estimate_rds_monthly_cost("db.m5.large", multi_az=False, region="us-east-1")
            # Clear cache so multi-AZ call is fresh
            clear_cache()
            mock_client.get_products.return_value = _make_get_products_response(str(dynamic_hourly))
            multi = estimate_rds_monthly_cost("db.m5.large", multi_az=True, region="us-east-1")

        assert multi == round(single * 2, 2)

    def test_falls_back_to_hardcoded_when_api_fails(self):
        """estimate_rds_monthly_cost() must fall back to RDS_HOURLY_PRICES on API failure."""
        with patch("aws.pricing_fetcher.fetch_rds_price", return_value=None):
            from analysis.cost_estimator import (
                estimate_rds_monthly_cost,
                RDS_HOURLY_PRICES,
                HOURS_PER_MONTH,
            )
            result = estimate_rds_monthly_cost("db.m5.large", region="us-east-1")

        expected = round(RDS_HOURLY_PRICES["db.m5.large"] * HOURS_PER_MONTH, 2)
        assert result == expected

    def test_falls_back_multi_az_when_api_fails(self):
        """Multi-AZ fallback must still apply 2x multiplier to hardcoded price."""
        with patch("aws.pricing_fetcher.fetch_rds_price", return_value=None):
            from analysis.cost_estimator import (
                estimate_rds_monthly_cost,
                RDS_HOURLY_PRICES,
                HOURS_PER_MONTH,
            )
            result = estimate_rds_monthly_cost("db.r5.large", multi_az=True, region="us-east-1")

        expected = round(RDS_HOURLY_PRICES["db.r5.large"] * HOURS_PER_MONTH * 2, 2)
        assert result == expected

    def test_default_region_does_not_crash(self):
        with patch("aws.pricing_fetcher.fetch_rds_price", return_value=None):
            from analysis.cost_estimator import estimate_rds_monthly_cost
            result = estimate_rds_monthly_cost("db.m5.large")
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Integration: get_client("pricing") via the existing client factory
# ---------------------------------------------------------------------------

class TestPricingClientFactory:
    def test_get_client_called_with_pricing_service(self):
        """Verify fetch_ec2_price calls get_client with 'pricing' service."""
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_empty_get_products_response()
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client) as mock_factory:
            fetch_ec2_price("m5.large", "us-east-1")
        args = mock_factory.call_args[0]
        assert args[0] == "pricing"

    def test_get_client_called_with_us_east_1_for_rds(self):
        """Verify fetch_rds_price always uses us-east-1 for the pricing client."""
        mock_client = MagicMock()
        mock_client.get_products.return_value = _make_empty_get_products_response()
        with patch("aws.pricing_fetcher.get_client", return_value=mock_client) as mock_factory:
            fetch_rds_price("db.m5.large", "eu-central-1")
        args = mock_factory.call_args[0]
        assert args[1] == "us-east-1"
