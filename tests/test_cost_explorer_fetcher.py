"""
tests/test_cost_explorer_fetcher.py — Unit tests for Cost Explorer fetcher.
"""

import pytest
from datetime import date
from unittest.mock import patch, MagicMock
from aws.cost_explorer_fetcher import fetch_actual_cost, _month_boundaries


def _make_ce_response(groups):
    """Build a minimal Cost Explorer get_cost_and_usage response."""
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-03-01", "End": "2026-04-01"},
                "Groups": [
                    {
                        "Keys": [svc],
                        "Metrics": {"UnblendedCost": {"Amount": str(cost), "Unit": "USD"}},
                    }
                    for svc, cost in groups
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# _month_boundaries unit tests — no AWS calls
# ---------------------------------------------------------------------------

class TestMonthBoundaries:
    def test_months_back_1_start_is_first_of_prev_month(self):
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            start, end = _month_boundaries(1)
        assert start == date(2026, 3, 1)
        assert end == date(2026, 4, 1)

    def test_months_back_2_february_28_days(self):
        # From April, going back 2 = February 2026 (28 days)
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            start, end = _month_boundaries(2)
        assert start == date(2026, 2, 1)
        assert end == date(2026, 3, 1)

    def test_months_back_1_january_rolls_to_december(self):
        # From January, going back 1 = December of previous year
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            start, end = _month_boundaries(1)
        assert start == date(2025, 12, 1)
        assert end == date(2026, 1, 1)

    def test_months_back_0_start_is_first_of_current_month(self):
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            start, end = _month_boundaries(0)
        assert start == date(2026, 4, 1)
        assert end == date(2026, 4, 15)

    def test_start_always_before_end(self):
        for mb in range(6):
            start, end = _month_boundaries(mb)
            assert start < end, f"months_back={mb}: start={start} not < end={end}"

    def test_months_back_1_march_has_31_days(self):
        # From April, going back 1 = March (31 days)
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            start, end = _month_boundaries(1)
        days = (end - start).days
        assert days == 31

    def test_months_back_2_february_has_28_days(self):
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            start, end = _month_boundaries(2)
        days = (end - start).days
        assert days == 28

    def test_period_label_full_month(self):
        # months_back=1 from April → "March 2026"
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            with patch("aws.client.get_client", return_value=MagicMock(
                get_cost_and_usage=MagicMock(return_value=_make_ce_response([]))
            )):
                result = fetch_actual_cost("us-east-1", months_back=1)
        assert result["period_label"] == "March 2026"

    def test_period_label_mtd(self):
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            with patch("aws.client.get_client", return_value=MagicMock(
                get_cost_and_usage=MagicMock(return_value=_make_ce_response([]))
            )):
                result = fetch_actual_cost("us-east-1", months_back=0)
        assert "month to date" in result["period_label"]
        assert "April 2026" in result["period_label"]


# ---------------------------------------------------------------------------
# fetch_actual_cost integration tests — mocked CE client
# ---------------------------------------------------------------------------

class TestFetchActualCost:
    def _mock_ce(self, groups):
        mock_client = MagicMock()
        mock_client.get_cost_and_usage.return_value = _make_ce_response(groups)
        return mock_client

    def test_returns_dict_on_success(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([
            ("Amazon Elastic Compute Cloud - Compute", 50.0),
        ])):
            result = fetch_actual_cost("us-east-1")
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([
            ("Amazon Elastic Compute Cloud - Compute", 50.0),
        ])):
            result = fetch_actual_cost("us-east-1")
        for key in ("period_start", "period_end", "period_label", "period_display",
                    "total_usd", "by_service", "currency", "note"):
            assert key in result

    def test_total_usd_sums_services(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([
            ("Amazon Elastic Compute Cloud - Compute", 50.0),
            ("Amazon Relational Database Service", 30.0),
        ])):
            result = fetch_actual_cost("us-east-1")
        assert result["total_usd"] == 80.0

    def test_zero_cost_services_excluded(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([
            ("Amazon Elastic Compute Cloud - Compute", 50.0),
            ("Amazon CloudWatch", 0.0),
        ])):
            result = fetch_actual_cost("us-east-1")
        services = [s["service"] for s in result["by_service"]]
        assert len(result["by_service"]) == 1
        assert all("CloudWatch" not in s for s in services)

    def test_by_service_sorted_descending(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([
            ("Amazon Relational Database Service", 10.0),
            ("Amazon Elastic Compute Cloud - Compute", 50.0),
            ("Amazon Simple Storage Service", 5.0),
        ])):
            result = fetch_actual_cost("us-east-1")
        costs = [s["cost_usd"] for s in result["by_service"]]
        assert costs == sorted(costs, reverse=True)

    def test_service_labels_mapped(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([
            ("Amazon Elastic Compute Cloud - Compute", 50.0),
        ])):
            result = fetch_actual_cost("us-east-1")
        assert result["by_service"][0]["service"] == "EC2 Compute"

    def test_unknown_service_uses_raw_name(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([
            ("Some Unknown Service", 5.0),
        ])):
            result = fetch_actual_cost("us-east-1")
        assert result["by_service"][0]["service"] == "Some Unknown Service"

    def test_currency_is_usd(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([])):
            result = fetch_actual_cost("us-east-1")
        assert result["currency"] == "USD"

    def test_note_mentions_reserved_instances(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([])):
            result = fetch_actual_cost("us-east-1")
        assert "Reserved Instance" in result["note"]

    def test_returns_none_on_api_failure(self):
        mock_client = MagicMock()
        mock_client.get_cost_and_usage.side_effect = Exception("AccessDenied")
        with patch("aws.client.get_client", return_value=mock_client):
            result = fetch_actual_cost("us-east-1")
        assert result is None

    def test_returns_none_when_get_client_fails(self):
        with patch("aws.client.get_client", side_effect=Exception("no creds")):
            result = fetch_actual_cost("us-east-1")
        assert result is None

    def test_empty_response_returns_zero_total(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([])):
            result = fetch_actual_cost("us-east-1")
        assert result["total_usd"] == 0.0
        assert result["by_service"] == []

    def test_period_start_before_end(self):
        with patch("aws.client.get_client", return_value=self._mock_ce([])):
            result = fetch_actual_cost("us-east-1", months_back=1)
        start = date.fromisoformat(result["period_start"])
        end = date.fromisoformat(result["period_end"])
        assert start < end

    def test_period_display_shows_inclusive_end(self):
        # months_back=1 from April → March 01 – March 31
        with patch("aws.cost_explorer_fetcher.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            with patch("aws.client.get_client", return_value=MagicMock(
                get_cost_and_usage=MagicMock(return_value=_make_ce_response([]))
            )):
                result = fetch_actual_cost("us-east-1", months_back=1)
        assert "March 01, 2026" in result["period_display"]
        assert "March 31, 2026" in result["period_display"]
        # Must NOT show April
        assert "April" not in result["period_display"]
