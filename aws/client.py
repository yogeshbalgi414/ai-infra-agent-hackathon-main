"""
aws/client.py — boto3 client factory with LocalStack endpoint injection.
Owner: Senior
Status: IMPLEMENTED (Epic 1)

All modules must use get_client() to create boto3 clients.
Never call boto3.client() directly anywhere else in the codebase.
"""

import os
import boto3
import logging

logger = logging.getLogger(__name__)


def get_client(service: str, region: str):
    """
    Create and return a boto3 client for the given service and region.

    If AWS_ENDPOINT_URL is set in the environment, the client will use that
    endpoint (LocalStack for local development). Otherwise it connects to
    real AWS.

    Args:
        service: AWS service name, e.g. 'ec2', 'rds', 'cloudwatch', 'sts'
        region:  AWS region string, e.g. 'us-east-1'

    Returns:
        boto3 client instance

    Raises:
        ValueError: if service or region is empty
    """
    if not service:
        raise ValueError("service must be a non-empty string")
    if not region:
        raise ValueError("region must be a non-empty string")

    kwargs = {"region_name": region}

    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        logger.debug("Using LocalStack endpoint: %s for service: %s", endpoint, service)
    else:
        logger.debug("Using real AWS for service: %s in region: %s", service, region)

    return boto3.client(service, **kwargs)
