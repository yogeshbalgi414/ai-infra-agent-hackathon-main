"""
tests/test_client.py — Unit tests for aws/client.py get_client() factory.
Owner: Senior
Epic: 1
"""

import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_get_client():
    """Import get_client fresh so env-var patches take effect."""
    import importlib
    import aws.client as mod
    importlib.reload(mod)
    return mod.get_client


# ---------------------------------------------------------------------------
# Test: LocalStack endpoint injection
# ---------------------------------------------------------------------------

class TestLocalStackEndpointInjection:
    def test_endpoint_url_passed_when_env_var_set(self):
        """When AWS_ENDPOINT_URL is set, the client must use that endpoint."""
        localstack_url = "http://localhost:4566"
        with patch.dict(os.environ, {"AWS_ENDPOINT_URL": localstack_url}):
            with patch("boto3.client") as mock_boto3_client:
                mock_boto3_client.return_value = MagicMock()
                from aws.client import get_client
                get_client("ec2", "us-east-1")
                mock_boto3_client.assert_called_once_with(
                    "ec2",
                    region_name="us-east-1",
                    endpoint_url=localstack_url,
                )

    def test_endpoint_url_used_for_any_service(self):
        """LocalStack endpoint injection works for rds, cloudwatch, sts, etc."""
        localstack_url = "http://localhost:4566"
        with patch.dict(os.environ, {"AWS_ENDPOINT_URL": localstack_url}):
            with patch("boto3.client") as mock_boto3_client:
                mock_boto3_client.return_value = MagicMock()
                from aws.client import get_client
                for service in ("rds", "cloudwatch", "sts"):
                    get_client(service, "eu-west-1")
                    call_kwargs = mock_boto3_client.call_args[1]
                    assert call_kwargs["endpoint_url"] == localstack_url


# ---------------------------------------------------------------------------
# Test: Real AWS (no endpoint)
# ---------------------------------------------------------------------------

class TestRealAWSNoEndpoint:
    def test_no_endpoint_url_when_env_var_absent(self):
        """When AWS_ENDPOINT_URL is not set, endpoint_url must NOT be passed."""
        env = {k: v for k, v in os.environ.items() if k != "AWS_ENDPOINT_URL"}
        with patch.dict(os.environ, env, clear=True):
            with patch("boto3.client") as mock_boto3_client:
                mock_boto3_client.return_value = MagicMock()
                from aws.client import get_client
                get_client("ec2", "us-east-1")
                call_kwargs = mock_boto3_client.call_args[1]
                assert "endpoint_url" not in call_kwargs

    def test_region_always_passed(self):
        """region_name must always be passed regardless of endpoint setting."""
        env = {k: v for k, v in os.environ.items() if k != "AWS_ENDPOINT_URL"}
        with patch.dict(os.environ, env, clear=True):
            with patch("boto3.client") as mock_boto3_client:
                mock_boto3_client.return_value = MagicMock()
                from aws.client import get_client
                get_client("rds", "ap-southeast-1")
                call_kwargs = mock_boto3_client.call_args[1]
                assert call_kwargs["region_name"] == "ap-southeast-1"


# ---------------------------------------------------------------------------
# Test: Invalid / empty inputs raise ValueError
# ---------------------------------------------------------------------------

class TestInvalidInputs:
    def test_empty_service_raises_value_error(self):
        from aws.client import get_client
        with pytest.raises(ValueError, match="service"):
            get_client("", "us-east-1")

    def test_none_service_raises_value_error(self):
        from aws.client import get_client
        with pytest.raises(ValueError, match="service"):
            get_client(None, "us-east-1")

    def test_empty_region_raises_value_error(self):
        from aws.client import get_client
        with pytest.raises(ValueError, match="region"):
            get_client("ec2", "")

    def test_none_region_raises_value_error(self):
        from aws.client import get_client
        with pytest.raises(ValueError, match="region"):
            get_client("ec2", None)


# ---------------------------------------------------------------------------
# Test: check_connectivity returns structured dict
# ---------------------------------------------------------------------------

class TestCheckConnectivity:
    def test_returns_ok_dict_on_success(self):
        """check_connectivity returns status=ok with account_id on success."""
        mock_identity = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/test",
            "UserId": "AIDATEST",
        }
        with patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_REGION": "us-east-1",
        }):
            with patch("aws.connectivity_check.get_client") as mock_get_client:
                mock_sts = MagicMock()
                mock_sts.get_caller_identity.return_value = mock_identity
                mock_get_client.return_value = mock_sts

                from aws.connectivity_check import check_connectivity
                result = check_connectivity()

        assert result["status"] == "ok"
        assert result["account_id"] == "123456789012"
        assert result["arn"] == "arn:aws:iam::123456789012:user/test"

    def test_returns_error_dict_on_missing_access_key(self):
        """check_connectivity returns status=error when AWS_ACCESS_KEY_ID missing."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")}
        with patch.dict(os.environ, env, clear=True):
            from aws.connectivity_check import check_connectivity
            result = check_connectivity()
        assert result["status"] == "error"
        assert "AWS_ACCESS_KEY_ID" in result["message"]

    def test_returns_error_dict_on_boto3_exception(self):
        """check_connectivity returns status=error when boto3 raises."""
        with patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
        }):
            with patch("aws.connectivity_check.get_client") as mock_get_client:
                mock_sts = MagicMock()
                mock_sts.get_caller_identity.side_effect = Exception("Connection refused")
                mock_get_client.return_value = mock_sts

                from aws.connectivity_check import check_connectivity
                result = check_connectivity()

        assert result["status"] == "error"
        assert "Connection refused" in result["message"]

    def test_endpoint_shown_in_ok_result(self):
        """When LocalStack is active, endpoint field shows the URL not 'real AWS'."""
        mock_identity = {
            "Account": "000000000000",
            "Arn": "arn:aws:iam::000000000000:root",
            "UserId": "LOCALSTACK",
        }
        with patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_ENDPOINT_URL": "http://localhost:4566",
        }):
            with patch("aws.connectivity_check.get_client") as mock_get_client:
                mock_sts = MagicMock()
                mock_sts.get_caller_identity.return_value = mock_identity
                mock_get_client.return_value = mock_sts

                from aws.connectivity_check import check_connectivity
                result = check_connectivity()

        assert result["status"] == "ok"
        assert result["endpoint"] == "http://localhost:4566"
