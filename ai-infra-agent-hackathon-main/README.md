# AI Infrastructure Advisor

AI-powered AWS infrastructure advisor that analyzes cloud resources, detects inefficiencies, surfaces security misconfigurations, and delivers cost optimization recommendations through a natural language conversational interface.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [IAM Permissions Required](#iam-permissions-required)
- [Local Development Setup](#local-development-setup)
- [Production Deployment](#production-deployment)
- [Database Setup (PostgreSQL)](#database-setup-postgresql)
- [Redis Setup (Scan Cache)](#redis-setup-scan-cache)
- [Running Tests](#running-tests)
- [LocalStack Demo (No Real AWS)](#localstack-demo-no-real-aws)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Streamlit UI (ui/app.py)            │
│         Chat interface + Dashboard cards             │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│           LangChain Agent (agent/agent.py)           │
│   Azure OpenAI (primary) / Groq (fallback)           │
│   Tools: EC2 · RDS · Security · Cost · Resources     │
└──────┬──────────┬──────────┬──────────┬─────────────┘
       │          │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌───▼────┐ ┌───▼──────────┐
  │  AWS   │ │  AWS   │ │  AWS   │ │  AWS Cost    │
  │  EC2   │ │  RDS   │ │  SGs   │ │  Explorer    │
  └────┬───┘ └───┬────┘ └───┬────┘ └──────────────┘
       │         │          │
  ┌────▼─────────▼──────────▼────────────────────────┐
  │           Redis (cache/redis_cache.py)            │
  │   Scan results · TTL 10 min · Region-scoped keys  │
  └───────────────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│           PostgreSQL (db/)                           │
│   Chat sessions · Message history                    │
└─────────────────────────────────────────────────────┘
```

**LLM priority:** Azure OpenAI (`AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT`) → Groq (`GROQ_API_KEY`) → error

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.14 has pydantic.v1 incompatibility with langchain-core 0.2.x |
| Redis | 7+ | Required for scan result caching — `brew install redis` |
| PostgreSQL | 14+ | Optional — app runs without it (no chat history persistence) |
| Docker | Any | Only needed for LocalStack demo |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | ✅ | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | ✅ | AWS secret key |
| `AWS_SESSION_TOKEN` | Only for STS temp creds | Session token (leave blank for long-term keys) |
| `AWS_REGION` | ✅ | Default region e.g. `us-east-1` |
| `AWS_ENDPOINT_URL` | LocalStack only | Set to `http://localhost:4566` for local dev, leave blank for real AWS |
| `AZURE_OPENAI_API_KEY` | ✅ (or Groq) | Azure OpenAI API key — primary LLM |
| `AZURE_OPENAI_ENDPOINT` | ✅ (or Groq) | Azure OpenAI endpoint URL e.g. `https://your-resource.openai.azure.com/` |
| `GROQ_API_KEY` | Fallback only | Used when Azure keys are not set |
| `CHAT_DB_URL` | Optional | PostgreSQL connection string — app works without it |
| `REDIS_URL` | Optional | Redis connection string — defaults to `redis://localhost:6379` |

**Minimum for real AWS + Azure OpenAI:**
```dotenv
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=us-east-1
AZURE_OPENAI_API_KEY=your_azure_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
REDIS_URL=redis://localhost:6379
CHAT_DB_URL=postgresql://user:pass@host:5432/ai_advisor
```

---

## IAM Permissions Required

The AWS credentials must have the following permissions. Attach this policy to the IAM user or role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2ReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeReservedInstances",
        "ec2:DescribeAddresses",
        "ec2:DescribeVolumes",
        "ec2:DescribeVpcs"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RDSReadOnly",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBInstances"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchReadOnly",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3ReadOnly",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets",
        "s3:GetBucketPublicAccessBlock"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaReadOnly",
      "Effect": "Allow",
      "Action": [
        "lambda:ListFunctions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CostExplorer",
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "STSIdentity",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PricingReadOnly",
      "Effect": "Allow",
      "Action": [
        "pricing:GetProducts"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Note:** All actions are read-only. The agent never creates, modifies, or deletes any AWS resources.

---

## Local Development Setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd ai-infra-agent-hackathon

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your values

# 5. Run the app
streamlit run ui/app.py
```

Open http://localhost:8501, enter your AWS region, and click **Start Session**.

---

## Production Deployment

### Option A — Streamlit Community Cloud

1. Push the repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app
3. Set **Main file path** to `ui/app.py`
4. Add all environment variables from `.env` in the **Secrets** section (TOML format):

```toml
AWS_ACCESS_KEY_ID = "your_key"
AWS_SECRET_ACCESS_KEY = "your_secret"
AWS_REGION = "us-east-1"
AZURE_OPENAI_API_KEY = "your_azure_key"
AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
CHAT_DB_URL = "postgresql://user:pass@host:5432/ai_advisor"
REDIS_URL = "redis://:password@your-redis-host:6379"
```

5. Click **Deploy**

> **Important:** Do NOT set `AWS_ENDPOINT_URL` in production — leave it blank so the app connects to real AWS.

---

### Option B — Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "ui/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

Build and run:

```bash
docker build -t ai-infra-advisor .

docker run -d \
  -p 8501:8501 \
  --env-file .env \
  --name ai-infra-advisor \
  ai-infra-advisor
```

---

### Option C — EC2 / VM

```bash
# On the server
git clone <repo-url>
cd ai-infra-agent-hackathon
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env

# Run with nohup to keep alive after SSH disconnect
nohup streamlit run ui/app.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true \
  > streamlit.log 2>&1 &

echo "Running at http://$(curl -s ifconfig.me):8501"
```

For production, use a process manager like `systemd` or `supervisor` instead of `nohup`.

---

## Database Setup (PostgreSQL)

Chat history persistence requires PostgreSQL. The app runs without it (in-memory only, no history across sessions).

### Local setup (macOS)

```bash
brew install postgresql
brew services start postgresql
createdb ai_advisor
```

### Production setup

```bash
psql -U postgres
CREATE DATABASE ai_advisor;
CREATE USER ai_advisor_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE ai_advisor TO ai_advisor_user;
\q
```

Set `CHAT_DB_URL` in `.env`:
```dotenv
CHAT_DB_URL=postgresql://ai_advisor_user:your_password@localhost:5432/ai_advisor
```

Tables are created automatically on first startup — no migration scripts needed.

> **Existing DB migration:** If you had the app running before the Redis caching update, drop the now-unused columns:
> ```sql
> ALTER TABLE chat_sessions
>   DROP COLUMN IF EXISTS scan_cache,
>   DROP COLUMN IF EXISTS scan_cache_at,
>   DROP COLUMN IF EXISTS scan_region;
> ```

---

## Redis Setup (Scan Cache)

Redis caches AWS scan results (EC2, RDS, Security Groups) with a 10-minute TTL. The app works without Redis — tools will re-fetch from AWS on every call.

### Local setup (macOS)

```bash
brew install redis
brew services start redis
```

### Production setup

Use a managed Redis service (AWS ElastiCache, Redis Cloud, Upstash) and set:
```dotenv
REDIS_URL=redis://:your_password@your-redis-host:6379
```

### Verify cache is working

```bash
# After running a scan in the app:
redis-cli KEYS scan:*          # shows cached regions
redis-cli TTL scan:us-east-1   # shows remaining TTL in seconds
```

### Cache invalidation

Say `refresh` or `rescan` in the chat, or click the **Refresh Data** button in the sidebar — this deletes the Redis key and forces a fresh AWS fetch.

---

## Running Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

Expected: **507 tests passing**, 0 failing. Tests do not require LocalStack, real AWS credentials, Redis, or a running database.

---

## LocalStack Demo (No Real AWS)

For local development without a real AWS account:

### 1. Start LocalStack

```bash
docker run --rm -d \
  -p 4566:4566 \
  -e SERVICES=ec2,rds,cloudwatch,sts \
  --name localstack \
  localstack/localstack

# Wait until ready
curl http://localhost:4566/_localstack/health
```

### 2. Configure `.env` for LocalStack

```dotenv
AWS_ACCESS_KEY_ID=fake
AWS_SECRET_ACCESS_KEY=fake
AWS_REGION=us-east-1
AWS_ENDPOINT_URL=http://localhost:4566
AZURE_OPENAI_API_KEY=your_azure_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
```

### 3. Seed demo resources

```bash
python localstack/setup_demo.py
```

Creates the full demo scenario:
- EC2: `idle-worker` (t3.large, 2% CPU), `overprovisioned-api` (m5.xlarge, 8% CPU), `stopped-legacy` (t3.micro, stopped)
- RDS: `prod-db` (db.r5.large, idle), `dev-db` (db.m5.large, unnecessary Multi-AZ)
- Security Groups: SSH open to `0.0.0.0/0`, MySQL open to `0.0.0.0/0`
- 7 days of CloudWatch metrics for all running instances

### 4. Run the app

```bash
streamlit run ui/app.py
```

Expected scan output: 2 critical security findings, ~$470/month savings opportunity, 1 best practice violation.

> **Note:** Cost Explorer (`get_actual_cost` tool) does not work with LocalStack — it always calls real AWS. The estimated cost tools work fully with LocalStack.

---

## Project Structure

```
ai-infra-agent-hackathon/
├── agent/
│   ├── agent.py          — LangChain AgentExecutor, tool registration, LLM selection
│   ├── prompts.py        — System prompt, proactive scan prompt
│   ├── memory.py         — ConversationBufferMemory factory
│   └── tools/
│       ├── ec2_tools.py       — EC2 analysis LangChain tool
│       ├── rds_tools.py       — RDS analysis LangChain tool
│       ├── security_tools.py  — Security Group analysis LangChain tool
│       └── resource_tools.py  — S3/Lambda/VPC/EBS/EIP overview tool
├── analysis/
│   ├── ec2_analyzer.py        — EC2 classification + confidence scoring
│   ├── rds_analyzer.py        — RDS classification + confidence scoring
│   ├── security_analyzer.py   — Security Group finding generation
│   ├── resource_analyzer.py   — S3/Lambda/other resource findings
│   ├── cost_estimator.py      — On-demand cost estimation + savings calculation
│   └── confidence.py          — Public confidence scoring API
├── aws/
│   ├── client.py              — boto3 client factory (LocalStack-aware)
│   ├── ec2_fetcher.py         — EC2 instance + CloudWatch metric fetching
│   ├── rds_fetcher.py         — RDS instance + CloudWatch metric fetching
│   ├── security_fetcher.py    — Security Group fetching
│   ├── s3_fetcher.py          — S3 bucket + public access status
│   ├── lambda_fetcher.py      — Lambda function + invocation metrics
│   ├── resource_fetcher.py    — VPC/EIP/EBS fetching
│   ├── pricing_fetcher.py     — AWS Pricing API (dynamic pricing)
│   ├── cost_explorer_fetcher.py — AWS Cost Explorer (real billing data)
│   └── connectivity_check.py  — STS connectivity validation
├── cache/
│   └── redis_cache.py         — Redis scan result cache (TTL 10 min, region-scoped)
├── db/
│   ├── database.py            — PostgreSQL connection + schema init
│   └── session_manager.py     — Chat session + message CRUD
├── ui/
│   ├── app.py                 — Streamlit chat interface + dashboard
│   ├── region_validator.py    — AWS region format validation
│   └── styles.css             — Custom UI styles
├── localstack/
│   └── setup_demo.py          — Demo resource seeding script
├── tests/                     — 494 unit tests (no AWS/DB required)
├── .env.example               — Environment variable template
├── requirements.txt           — Pinned Python dependencies
└── README.md                  — This file
```

---

## Troubleshooting

### `Error code: 400 — 'max_tokens' is not supported`
Your Azure deployment uses a newer model that requires `max_completion_tokens`. Ensure `agent/agent.py` uses `max_completion_tokens` in the `AzureChatOpenAI` constructor. Current code already handles this.

### `Failed to create agent: EnvironmentError: No LLM API key found`
Set either `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` (preferred) or `GROQ_API_KEY` in your `.env`.

### `Database unavailable — chat history will not be saved`
PostgreSQL is not running or `CHAT_DB_URL` is wrong. The app works fully without it — this is just a warning. To fix: start PostgreSQL and verify the connection string.

### `Redis unavailable — cache disabled`
Redis is not running. The app works without it — tools will re-fetch from AWS on every call (slower but functional). To fix: `brew services start redis` (macOS) or start your Redis server.

### `Proactive scan failed: Unable to locate credentials`
AWS credentials are missing or expired. Check `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` (if using temporary credentials).

### `Cost Explorer fetch failed`
The IAM role/user is missing `ce:GetCostAndUsage` permission. Add it to the IAM policy. The app continues to work — estimated costs still show, only real billing data is unavailable.

### Tests failing after `pip install`
Dependency conflict — likely `langchain-core` was upgraded to 1.x. Run:
```bash
pip uninstall langchain-classic -y
pip install "langchain-community==0.3.0" "langchain-core>=0.3.27,<0.4.0" "langsmith>=0.1.17,<0.2.0"
pip check
```
