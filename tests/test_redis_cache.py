"""
tests/test_redis_cache.py — Unit tests for Redis scan cache.
All tests mock the Redis client — no running Redis required.
"""

import pytest
from unittest.mock import MagicMock, patch
from cache.redis_cache import get_scan_cache, write_scan_cache, _cache_key


class TestCacheKey:
    def test_key_includes_region(self):
        assert "us-east-1" in _cache_key("us-east-1")

    def test_key_format(self):
        assert _cache_key("eu-west-1") == "scan:eu-west-1"

    def test_different_regions_different_keys(self):
        assert _cache_key("us-east-1") != _cache_key("eu-west-1")


class TestGetScanCache:
    def _mock_client(self, return_value):
        mock = MagicMock()
        mock.get.return_value = return_value
        return mock

    def test_returns_none_when_redis_unavailable(self):
        with patch("cache.redis_cache._get_client", return_value=None):
            result = get_scan_cache("session-1", "us-east-1")
        assert result is None

    def test_returns_none_on_cache_miss(self):
        with patch("cache.redis_cache._get_client", return_value=self._mock_client(None)):
            result = get_scan_cache("session-1", "us-east-1")
        assert result is None

    def test_returns_parsed_dict_on_hit(self):
        import json
        data = {"ec2": {"instances": []}, "rds": {"instances": []}}
        with patch("cache.redis_cache._get_client",
                   return_value=self._mock_client(json.dumps(data))):
            result = get_scan_cache("session-1", "us-east-1")
        assert result == data

    def test_returns_none_on_redis_error(self):
        mock = MagicMock()
        mock.get.side_effect = Exception("connection refused")
        with patch("cache.redis_cache._get_client", return_value=mock):
            result = get_scan_cache("session-1", "us-east-1")
        assert result is None

    def test_session_id_not_used_in_key(self):
        """Same region, different session_ids → same cache key."""
        import json
        data = {"ec2": {}}
        mock = self._mock_client(json.dumps(data))
        with patch("cache.redis_cache._get_client", return_value=mock):
            r1 = get_scan_cache("session-aaa", "us-east-1")
            r2 = get_scan_cache("session-bbb", "us-east-1")
        assert r1 == r2


class TestWriteScanCache:
    def test_noop_when_redis_unavailable(self):
        with patch("cache.redis_cache._get_client", return_value=None):
            write_scan_cache("session-1", "us-east-1", {"ec2": {}})  # should not raise

    def test_calls_setex_with_ttl(self):
        import json
        mock = MagicMock()
        data = {"ec2": {"instances": []}}
        with patch("cache.redis_cache._get_client", return_value=mock):
            write_scan_cache("session-1", "us-east-1", data, ttl_minutes=10)
        mock.setex.assert_called_once_with(
            "scan:us-east-1", 600, json.dumps(data)
        )

    def test_calls_delete_when_data_is_none(self):
        mock = MagicMock()
        with patch("cache.redis_cache._get_client", return_value=mock):
            write_scan_cache("session-1", "us-east-1", None)
        mock.delete.assert_called_once_with("scan:us-east-1")

    def test_noop_on_redis_error(self):
        mock = MagicMock()
        mock.setex.side_effect = Exception("write failed")
        with patch("cache.redis_cache._get_client", return_value=mock):
            write_scan_cache("session-1", "us-east-1", {"ec2": {}})  # should not raise

    def test_ttl_in_seconds(self):
        mock = MagicMock()
        with patch("cache.redis_cache._get_client", return_value=mock):
            write_scan_cache("session-1", "us-east-1", {"ec2": {}}, ttl_minutes=5)
        call_args = mock.setex.call_args[0]
        assert call_args[1] == 300  # 5 minutes × 60 seconds
