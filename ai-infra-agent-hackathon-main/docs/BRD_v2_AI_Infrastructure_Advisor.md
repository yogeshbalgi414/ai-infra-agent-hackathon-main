# Business Requirements Document — v2
## AI Infrastructure Advisor Agent
**Version:** 2.0
**Status:** In Progress
**Builds On:** v1.0 (Epics 1–10 complete)
**New Epics:** 11, 12, 13, 14
**Completed Epics (v2):** 12 (Hybrid Pricing Engine — done)

---

## 1. Executive Summary

Version 1 delivered a functional conversational agent capable of analyzing EC2
and RDS instances, detecting security misconfigurations, and providing cost
optimization recommendations. Version 2 focuses on three areas: expanding
resource visibility across all major AWS services, building a professional
dashboard UI with persistent chat history, and making cost estimates accurate
against real AWS pricing when connected to a live account.

---

## 2. What Changed From v1

| Area | v1 | v2 |
|---|---|---|
| Resources analyzed | EC2, RDS, Security Groups | EC2, RDS, Security Groups + S3, Lambda overview |
| UI | Basic Streamlit chat | Dashboard + sidebar + chat in one interface |
| Cost pricing | Hardcoded table only | Pricing API for real AWS, hardcoded for LocalStack |
| Chat persistence | In-memory, lost on refresh | PostgreSQL backed, survives crashes and restarts |
| Chat history | Not stored | Listed in sidebar, auto-named, deletable |
| Confidence display | Text only in responses | Star ratings on dashboard and inline in chat |
| Token usage | ~2000 per message | Optimized via caching and history trimming |
| Response formatting | Inconsistent | Enforced markdown with explicit format rules |

---

## 3. Goals

- Show resource counts and basic health status for S3, Lambda, and other
  available AWS services on the dashboard
- Flag public S3 buckets and unused Lambda functions as lightweight insights
- Fetch real AWS on-demand pricing when connected to a live AWS account
- Fall back to hardcoded pricing table when running on LocalStack
- Deliver a professional Streamlit UI with dashboard, sidebar, and chat
- Persist chat history across sessions using PostgreSQL
- Auto-name chat sessions and allow deletion from sidebar
- Display confidence ratings as stars (1-3) on dashboard and in chat
- Show hover tooltips explaining what star ratings mean

---

## 4. Functional Requirements

---

### Epic 11 — Resource Overview (S3, Lambda, Other Services)

**FR-E11-01: S3 Bucket Inventory**
The agent shall fetch all S3 buckets in the configured account and report:
- Total bucket count
- List of bucket names and creation dates
- Public access status per bucket (is public access block enabled?)
- Flag any bucket without public access block as a security finding

**FR-E11-02: Lambda Function Inventory**
The agent shall fetch all Lambda functions in the selected region and report:
- Total function count
- Function names, runtimes, and last modified dates
- Invocation count over the past 7 days via CloudWatch
- Flag any function with zero invocations in 7 days as potentially unused

**FR-E11-03: Other Resource Counts**
The agent shall fetch counts for any additional resource types available via
boto3 in the selected region. For MVP these are counts only with no analysis:
- VPCs
- Elastic IPs (unattached Elastic IPs are a cost item)
- EBS Volumes (unattached volumes flagged as waste)

**FR-E11-04: Resource Overview Output Shape**
All resource overview data shall conform to this contract:

```json
{
  "overview": {
    "s3": {
      "total_buckets": "integer",
      "public_buckets": "integer",
      "findings": ["string"]
    },
    "lambda": {
      "total_functions": "integer",
      "unused_functions": "integer",
      "findings": ["string"]
    },
    "other": {
      "vpcs": "integer",
      "unattached_elastic_ips": "integer",
      "unattached_ebs_volumes": "integer"
    }
  }
}
```

**FR-E11-05: Feeds Into Proactive Scan**
Resource overview data shall be included in the proactive scan summary shown
on dashboard load. Deep analysis (recommendations) remains EC2 and RDS only.

---

### Epic 12 — Hybrid Pricing Engine ✅ COMPLETE

**FR-E12-01: LocalStack Detection**
The pricing engine shall detect LocalStack by checking whether AWS_ENDPOINT_URL
is set in environment variables. This reuses the existing detection pattern
from aws/client.py.

```
AWS_ENDPOINT_URL set     → LocalStack mode → use hardcoded pricing table
AWS_ENDPOINT_URL not set → Real AWS mode   → call AWS Pricing API
```

**FR-E12-02: AWS Pricing API Integration**
When connected to real AWS, the pricing engine shall call the AWS Pricing API
to fetch current on-demand prices:

```python
pricing = boto3.client('pricing', region_name='us-east-1')
response = pricing.get_products(
    ServiceCode='AmazonEC2',
    Filters=[
        {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
        {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region_display_name},
        {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
        {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
        {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'},
        {'Type': 'TERM_MATCH', 'Field': 'capacitystatus', 'Value': 'Used'},
    ]
)
```

**FR-E12-03: Graceful Fallback**
If the Pricing API call fails for any reason (network error, unknown instance
type, rate limit), the engine shall silently fall back to the hardcoded table
and log a warning. The calling code shall never know the difference.

**FR-E12-04: Zero Signature Changes**
The get_monthly_cost() function signature must not change. All existing code
calling it requires zero updates. The hybrid logic is entirely internal.

**FR-E12-05: Pricing API Mocked in Tests**
All tests must mock the Pricing API call so LocalStack development and CI
are completely unaffected. Tests must cover:
- LocalStack path uses hardcoded table
- Real AWS path calls Pricing API
- Pricing API failure falls back to hardcoded table

**FR-E12-06: RDS Pricing**
Apply the same hybrid approach to RDS instance pricing using ServiceCode
'AmazonRDS' in the Pricing API call.

---

### Epic 13 — UI Overhaul (Streamlit)

**FR-E13-01: Overall Layout**
The interface shall be a single page Streamlit application with three zones:

```
┌─────────────────────────────────────────────────────────┐
│  Left Sidebar           │  Main Content Area             │
│                         │                                │
│  Region selector        │  ┌──────────────────────────┐ │
│                         │  │  Dashboard (upper half)   │ │
│  ── Chat Sessions ──    │  │  Resource cards           │ │
│  > Session 1            │  │  Proactive analysis       │ │
│    Session 2            │  │  Star confidence ratings  │ │
│    Session 3            │  └──────────────────────────┘ │
│  [+ New Session]        │                                │
│                         │  ┌──────────────────────────┐ │
│                         │  │  Chat Interface           │ │
│                         │  │  (lower half, scrollable) │ │
│                         │  └──────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**FR-E13-02: Left Sidebar — Configuration**
- Region selector dropdown at the top of the sidebar
- Supported regions list fetched from a hardcoded list of common AWS regions
- Selected region persisted in session state
- Changing region triggers a fresh proactive scan

**FR-E13-03: Left Sidebar — Chat Session History**
- List of all past chat sessions shown in sidebar
- Each session auto-named based on first user message or first finding
  (example: "EC2 analysis — us-east-1" or "Security audit 21 Mar")
- Active session highlighted
- Each session has a delete button (trash icon) shown on hover
- New Session button at bottom of session list
- Sessions stored in SQLite via Epic 14

**FR-E13-04: Dashboard — Resource Cards**
The dashboard shall show one card per AWS service with:
- Service name and icon
- Resource count
- Brief status (healthy / issues found)
- Star confidence rating for analysis quality

Services shown as cards:
```
EC2       RDS       S3        Lambda
VPCs      EBS       Elastic IPs
```

**FR-E13-05: Dashboard — Star Confidence Rating**
- 1 star (⭐) = Low confidence — insufficient data or single signal only
- 2 stars (⭐⭐) = Medium confidence — some signals support finding
- 3 stars (⭐⭐⭐) = High confidence — multiple signals converge

Display rules:
- Stars shown on each resource card on the dashboard
- Stars shown inline in chat responses when agent mentions confidence
- Hovering over stars opens a tooltip explaining the rating system:
  "Confidence is based on how many independent metrics support
   this finding. More signals = higher confidence."
- Overall confidence score shown at the top of the dashboard
  as a summary across all analyzed resources

**FR-E13-06: Dashboard — Proactive Analysis Summary**
- Shown immediately on page load without user input
- Covers all resource types from Epic 11 overview
- Structured as:
  ```
  SECURITY    → X critical findings
  COST WASTE  → $Y/month identified
  RESOURCES   → Z total resources across N services
  CONFIDENCE  → ⭐⭐⭐ overall
  ```
- Each line is clickable and scrolls to the chat with a pre-filled
  question about that category

**FR-E13-07: Chat Interface**
- Occupies lower half of main content, scrollable
- User input at the bottom
- Agent responses rendered with st.markdown() always
- Star ratings rendered inline when confidence is mentioned
- Responses never truncated
- Loading spinner shown while agent is processing
- "Refresh data" button that clears tool result cache and re-fetches

**FR-E13-08: Streamlit Rendering Rules**
- All agent responses rendered with st.markdown() not st.write()
- Resource IDs and technical values in code formatting
- Dollar amounts in bold
- Section headers use ## markdown
- Star ratings use ⭐ emoji directly in response text

---

### Epic 14 — Chat Persistence (PostgreSQL + Streamlit)

**FR-E14-01: PostgreSQL Database**
Chat history shall be stored in a PostgreSQL database. The database connection
string is configurable via environment variable with a sensible default.
Streamlit's built-in `st.connection` shall be used to manage the database
connection, leveraging connection pooling and automatic reconnect.

```bash
CHAT_DB_URL=postgresql://user:password@localhost:5432/chat_history
```

**FR-E14-02: PostgreSQL + Streamlit Integration**
Use Streamlit's `st.connection` with `psycopg2` for database access, and
LangChain's `PostgresChatMessageHistory` for message history management:

```python
import streamlit as st
from langchain_community.chat_message_histories import PostgresChatMessageHistory

conn = st.connection("postgresql", type="sql")

history = PostgresChatMessageHistory(
    session_id=session_id,
    connection_string=st.secrets["CHAT_DB_URL"]
)
```

Database credentials shall be stored in Streamlit secrets (`secrets.toml`)
and never hardcoded or committed to version control.

**FR-E14-03: Session Model**
Each chat session shall have:
- Unique session ID (UUID)
- Auto-generated display name
- Created timestamp
- Last updated timestamp
- Associated AWS region

**FR-E14-04: Auto Session Naming**
Session display name shall be generated automatically:
- If first user message is a question → use condensed version of the question
- If proactive scan runs first → use "Infrastructure scan — {region} — {date}"
- Maximum 40 characters, truncated with ellipsis if longer

**FR-E14-05: Session Operations**
- Load session → restore full chat history from SQLite
- Delete session → remove all messages for that session ID from SQLite
- New session → generate new UUID, start fresh history
- List sessions → return all sessions ordered by last updated descending

**FR-E14-06: Security**
- Database credentials stored in `.streamlit/secrets.toml`, never in code
- `secrets.toml` added to `.gitignore` and never committed to version control
- Session IDs are UUIDs, not sequential integers
- PostgreSQL user shall have minimal permissions: SELECT, INSERT, DELETE on
  chat tables only — no DDL privileges in production

**FR-E14-07: Graceful Degradation**
If the PostgreSQL connection fails for any reason (unreachable host, bad
credentials, connection timeout), the agent shall fall back to in-memory
history and display a visible warning banner in the Streamlit UI. The agent
must remain fully functional in degraded mode.

---

## 5. Non-Functional Requirements

**NFR-E2-01: Token Efficiency**
Average tokens per LLM call shall not exceed 800 input tokens for follow-up
messages in an ongoing conversation. Achieved via:
- Chat history trimmed to last 6 messages
- Tool results cached in session state for the duration of the session
- Re-fetching only when user explicitly requests refresh
- Applies to both Azure OpenAI (primary) and Groq (fallback)

**NFR-E2-02: Response Completeness**
LLM responses shall never be truncated mid-sentence. max_tokens set to 2048
minimum on all LLM calls.

**NFR-E2-03: Consistent Formatting**
All agent responses shall use markdown formatting enforced via system prompt
rules. Stars rendered as ⭐ emoji. Dollar amounts bolded. IDs in code format.

**NFR-E2-04: UI Performance**
Dashboard shall load and display proactive scan results within 20 seconds
of region selection on LocalStack. Real AWS times may vary based on account size.

---

## 6. Updated Tech Stack

No changes to core stack. Additions only:

```
PostgreSQL                          → chat persistence (replaces in-memory)
psycopg2                            → PostgreSQL driver
st.connection (Streamlit)           → connection pooling and secret management
LangChain PostgresChatMessageHistory → session management
AWS Pricing API                     → real-time cost data for live AWS accounts
boto3 S3, Lambda clients            → new resource overview fetchers
Azure OpenAI                        → primary LLM provider
Groq                                → fallback LLM (when Azure keys not set)
```

---

## 7. Updated Environment Variables

```bash
# AWS Credentials
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=            # required when using temporary STS credentials
AWS_DEFAULT_REGION=us-east-1
AWS_REGION=us-east-1

# LocalStack endpoint (comment out when using real AWS)
# AWS_ENDPOINT_URL=http://localhost:4566

# Azure OpenAI — primary LLM (required)
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=        # e.g. https://your-resource.openai.azure.com/

# Groq — fallback LLM (used when Azure keys are not set)
GROQ_API_KEY=

# New in v2 — stored in .streamlit/secrets.toml (not as env vars)
# [connections.postgresql]
# CHAT_DB_URL = "postgresql://user:password@host:5432/chat_history"
```

---

## 8. Epic Order and Dependencies

```
Epic 11 (Resource Overview)    → no dependencies, start immediately
Epic 12 (Hybrid Pricing)       → ✅ COMPLETE — no further action needed

Epic 14 (Chat Persistence)     → no dependencies, start immediately
                                  can run parallel to Epic 11

Epic 13 (UI Overhaul)          → depends on 11, 12, 14 being complete
                                  builds the UI that consumes all of the above
                                  implement last
```

---

## 9. Out of Scope — v2

| Feature | Reason Deferred |
|---|---|
| Deep analysis for S3 and Lambda | Overview and flagging sufficient for v2 |
| Multi-region simultaneous analysis | Token complexity, v3 |
| Automated remediation | Safety risk, advisory only always |
| User authentication | Not required for demo |
| Cloud cost anomaly detection | Requires historical baseline, v3 |
| IAM deep analysis | Complex domain, v3 |
| Mobile responsive UI | Streamlit limitation, v3 |

---

## 10. Demo Scenario Updates

Same demo AWS account as v1 with these additions:

```
S3 Buckets:
  - One bucket with public access block disabled  → security finding

Lambda Functions:
  - One function with zero invocations in 7 days  → unused, cost waste

EBS Volumes:
  - One unattached volume                          → cost waste flagged
```

Updated demo conversation:
```
Page loads → dashboard shows all resource cards with star ratings
             proactive summary: "2 critical security risks,
             $470/month waste, 8 total resources across 4 services ⭐⭐⭐"

Judge hovers over stars → tooltip explains confidence rating system

Judge: "Tell me about the security risks"
Agent: ⭐⭐⭐ Critical — SSH open to internet on i-xxxx
               Critical — S3 bucket publicly accessible

Judge: "What is the total I could save?"
Agent: $470/month, $5,640/year — broken down per resource

Judge clicks old session in sidebar → full previous conversation restored
Judge deletes old session → removed from sidebar instantly
```
