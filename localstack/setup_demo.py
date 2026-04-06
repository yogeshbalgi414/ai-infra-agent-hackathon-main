"""
localstack/setup_demo.py — Seeds LocalStack with demo resources from the BRD.
Owner: Senior
Status: IMPLEMENTED (Epic 10)

Run with:
    AWS_ENDPOINT_URL=http://localhost:4566 python localstack/setup_demo.py

Requires LocalStack running at http://localhost:4566.
Set AWS_ENDPOINT_URL in your .env or shell before running.

Demo resources created:
  EC2:  idle-worker (t3.large, running, 2% CPU)
        overprovisioned-api (m5.xlarge, running, 8% CPU)
        stopped-legacy (t3.micro, stopped 10 days)
  RDS:  prod-db (db.r5.large, single-AZ, 1% CPU — idle)
        dev-db (db.m5.large, Multi-AZ, 15% CPU — unnecessary Multi-AZ)
  SGs:  sg-open-ssh  (port 22 → 0.0.0.0/0)
        sg-open-mysql (port 3306 → 0.0.0.0/0)
  CW:   7 days of hourly metrics for all running instances
"""

import os
import sys
import time
import random
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

# Add project root to path so aws.client is importable when run directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aws.client import get_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security Group helpers
# ---------------------------------------------------------------------------

def create_sg_open_ssh(ec2_client) -> str:
    """
    Create a Security Group with port 22 (SSH) open to 0.0.0.0/0.
    Returns the new Security Group ID.
    """
    resp = ec2_client.create_security_group(
        GroupName="sg-open-ssh",
        Description="Demo SG: SSH open to internet (intentional misconfiguration)",
    )
    sg_id = resp["GroupId"]
    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[{
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "All IPv4"}],
        }],
    )
    logger.info("Created sg-open-ssh: %s", sg_id)
    return sg_id


def create_sg_open_mysql(ec2_client) -> str:
    """
    Create a Security Group with port 3306 (MySQL) open to 0.0.0.0/0.
    Returns the new Security Group ID.
    """
    resp = ec2_client.create_security_group(
        GroupName="sg-open-mysql",
        Description="Demo SG: MySQL open to internet (intentional misconfiguration)",
    )
    sg_id = resp["GroupId"]
    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[{
            "IpProtocol": "tcp",
            "FromPort": 3306,
            "ToPort": 3306,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "All IPv4"}],
        }],
    )
    logger.info("Created sg-open-mysql: %s", sg_id)
    return sg_id


# ---------------------------------------------------------------------------
# EC2 helpers
# ---------------------------------------------------------------------------

def create_ec2_instance(ec2_client, name: str, instance_type: str, sg_id: str) -> str:
    """
    Create a running EC2 instance with the given Name tag and security group.
    Returns the instance ID.
    """
    resp = ec2_client.run_instances(
        ImageId="ami-00000000",          # LocalStack accepts any AMI ID
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        SecurityGroupIds=[sg_id],
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": name}],
        }],
    )
    instance_id = resp["Instances"][0]["InstanceId"]
    logger.info("Created EC2 instance %s (%s): %s", name, instance_type, instance_id)
    return instance_id


def create_and_stop_ec2(ec2_client, name: str, instance_type: str) -> str:
    """
    Create an EC2 instance and immediately stop it (simulates stopped-for-10-days).
    Returns the instance ID.
    """
    # Use a default SG — LocalStack creates one automatically
    resp = ec2_client.run_instances(
        ImageId="ami-00000000",
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": name}],
        }],
    )
    instance_id = resp["Instances"][0]["InstanceId"]
    ec2_client.stop_instances(InstanceIds=[instance_id])
    logger.info("Created and stopped EC2 instance %s (%s): %s", name, instance_type, instance_id)
    return instance_id


# ---------------------------------------------------------------------------
# RDS helpers
# ---------------------------------------------------------------------------

def create_rds_instance(
    rds_client,
    name: str,
    instance_class: str,
    multi_az: bool = False,
    tags: list | None = None,
) -> bool:
    """
    Create an RDS MySQL instance with the given configuration.
    Returns True on success, False if RDS is unavailable (e.g. LocalStack community edition).
    """
    if tags is None:
        tags = [{"Key": "Name", "Value": name}]

    try:
        rds_client.create_db_instance(
            DBInstanceIdentifier=name,
            DBInstanceClass=instance_class,
            Engine="mysql",
            MasterUsername="admin",
            MasterUserPassword="password123",
            AllocatedStorage=20,
            MultiAZ=multi_az,
            BackupRetentionPeriod=7,
            Tags=tags,
        )
        logger.info("Created RDS instance %s (%s, multi_az=%s)", name, instance_class, multi_az)
        return True
    except Exception as exc:
        logger.warning(
            "Could not create RDS instance %s: %s\n"
            "  → RDS requires LocalStack Pro. Skipping RDS setup.",
            name, exc,
        )
        return False


# ---------------------------------------------------------------------------
# CloudWatch metric seeding
# ---------------------------------------------------------------------------

def seed_cloudwatch_metric(
    cw_client,
    namespace: str,
    metric_name: str,
    dimensions: list,
    base_value: float,
    unit: str,
    jitter: float = 0.5,
) -> None:
    """
    Seed 7 days of hourly datapoints around base_value using put_metric_data.
    PutMetricData accepts max 20 items per call — batched automatically.
    """
    now = datetime.now(timezone.utc)
    metric_data = []
    for hours_ago in range(168, 0, -1):   # 7 days × 24 hours = 168 datapoints
        timestamp = now - timedelta(hours=hours_ago)
        value = max(0.0, base_value + random.uniform(-jitter, jitter))
        metric_data.append({
            "MetricName": metric_name,
            "Dimensions": dimensions,
            "Timestamp": timestamp,
            "Value": value,
            "Unit": unit,
        })

    # Batch into groups of 20 (AWS API limit)
    for i in range(0, len(metric_data), 20):
        cw_client.put_metric_data(
            Namespace=namespace,
            MetricData=metric_data[i:i + 20],
        )


def seed_ec2_metrics(cw_client, idle_id: str, overprovisioned_id: str) -> None:
    """
    Seed CloudWatch metrics for idle-worker and overprovisioned-api EC2 instances.

    idle-worker:        CPU 2%, NetworkIn ~500 B/s, NetworkOut ~200 B/s, DiskReadOps ~0.1
    overprovisioned-api: CPU 8%, NetworkIn ~50000 B/s
    """
    # idle-worker metrics
    idle_dims = [{"Name": "InstanceId", "Value": idle_id}]
    seed_cloudwatch_metric(cw_client, "AWS/EC2", "CPUUtilization",  idle_dims, 2.0,   "Percent", jitter=0.3)
    seed_cloudwatch_metric(cw_client, "AWS/EC2", "NetworkIn",       idle_dims, 500.0, "Bytes",   jitter=50.0)
    seed_cloudwatch_metric(cw_client, "AWS/EC2", "NetworkOut",      idle_dims, 200.0, "Bytes",   jitter=30.0)
    seed_cloudwatch_metric(cw_client, "AWS/EC2", "DiskReadOps",     idle_dims, 0.1,   "Count",   jitter=0.05)
    logger.info("Seeded CloudWatch metrics for idle-worker (%s)", idle_id)

    # overprovisioned-api metrics
    over_dims = [{"Name": "InstanceId", "Value": overprovisioned_id}]
    seed_cloudwatch_metric(cw_client, "AWS/EC2", "CPUUtilization",  over_dims, 8.0,     "Percent", jitter=1.0)
    seed_cloudwatch_metric(cw_client, "AWS/EC2", "NetworkIn",       over_dims, 50000.0, "Bytes",   jitter=5000.0)
    seed_cloudwatch_metric(cw_client, "AWS/EC2", "NetworkOut",      over_dims, 20000.0, "Bytes",   jitter=2000.0)
    logger.info("Seeded CloudWatch metrics for overprovisioned-api (%s)", overprovisioned_id)


def seed_rds_metrics(cw_client, prod_db_id: str, dev_db_id: str) -> None:
    """
    Seed CloudWatch metrics for prod-db and dev-db RDS instances.

    prod-db: CPU 1%, connections 1, ReadIOPS ~0.2, WriteIOPS ~0.1
    dev-db:  CPU 15%
    """
    # prod-db metrics (idle, high confidence)
    prod_dims = [{"Name": "DBInstanceIdentifier", "Value": prod_db_id}]
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "CPUUtilization",      prod_dims, 1.0,  "Percent", jitter=0.2)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "DatabaseConnections",  prod_dims, 1.0,  "Count",   jitter=0.3)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "ReadIOPS",             prod_dims, 0.2,  "Count",   jitter=0.1)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "WriteIOPS",            prod_dims, 0.1,  "Count",   jitter=0.05)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "FreeStorageSpace",     prod_dims, 15e9, "Bytes",   jitter=1e8)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "FreeableMemory",       prod_dims, 4e9,  "Bytes",   jitter=1e8)
    logger.info("Seeded CloudWatch metrics for prod-db (%s)", prod_db_id)

    # dev-db metrics (overprovisioned — unnecessary Multi-AZ)
    dev_dims = [{"Name": "DBInstanceIdentifier", "Value": dev_db_id}]
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "CPUUtilization",      dev_dims, 15.0, "Percent", jitter=2.0)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "DatabaseConnections",  dev_dims, 10.0, "Count",   jitter=2.0)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "FreeStorageSpace",     dev_dims, 10e9, "Bytes",   jitter=1e8)
    seed_cloudwatch_metric(cw_client, "AWS/RDS", "FreeableMemory",       dev_dims, 2e9,  "Bytes",   jitter=1e8)
    logger.info("Seeded CloudWatch metrics for dev-db (%s)", dev_db_id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if not endpoint:
        logger.warning(
            "AWS_ENDPOINT_URL is not set. "
            "This script is intended for LocalStack. "
            "Set AWS_ENDPOINT_URL=http://localhost:4566 to target LocalStack."
        )

    ec2 = get_client("ec2", region)
    rds = get_client("rds", region)
    cw  = get_client("cloudwatch", region)

    print("=== AI Infra Agent — LocalStack Demo Setup ===")

    print("\n[1/4] Creating Security Groups...")
    sg_ssh_id   = create_sg_open_ssh(ec2)
    sg_mysql_id = create_sg_open_mysql(ec2)

    print("\n[2/4] Creating EC2 instances...")
    idle_id  = create_ec2_instance(ec2, "idle-worker",        "t3.large",  sg_ssh_id)
    over_id  = create_ec2_instance(ec2, "overprovisioned-api","m5.xlarge", sg_mysql_id)
    _stop_id = create_and_stop_ec2(ec2, "stopped-legacy",     "t3.micro")

    print("\n[3/4] Creating RDS instances...")
    rds_ok = create_rds_instance(rds, "prod-db", "db.r5.large", multi_az=False)
    if rds_ok:
        create_rds_instance(
            rds, "dev-db", "db.m5.large", multi_az=True,
            tags=[{"Key": "Name", "Value": "dev-db"}],
        )

    print("\n[4/4] Seeding CloudWatch metrics (7 days × 24 hours per instance)...")
    seed_ec2_metrics(cw, idle_id, over_id)
    if rds_ok:
        seed_rds_metrics(cw, "prod-db", "dev-db")

    print("\n✅ Demo environment ready.")
    print(f"   Region:   {region}")
    print(f"   Endpoint: {endpoint or 'real AWS (no LocalStack endpoint set)'}")
    print("\nExpected proactive scan findings:")
    print("  🔴 2 critical security findings (SSH + MySQL open to internet)")
    if rds_ok:
        print("  💰 ~$470/month waste (idle prod-db + overprovisioned-api + idle-worker)")
        print("  ⚠️  1 best practice violation (unnecessary Multi-AZ on dev-db)")
    else:
        print("  💰 EC2 cost waste visible (RDS skipped — requires LocalStack Pro)")
        print("  ℹ️  RDS findings unavailable: upgrade to LocalStack Pro for full demo")
    print("\nRun the agent with:")
    print("  streamlit run ui/app.py")


if __name__ == "__main__":
    main()
