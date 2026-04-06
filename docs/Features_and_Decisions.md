# Features and Business Decisions
## AI Infrastructure Advisor Agent — MVP
**Version:** 1.0  
**Purpose:** Reference document for team debate, alignment, and decision tracking

---

## Part 1 — Features We Are Building

### EC2 Analysis

| Feature | Description | Decision Rationale |
|---|---|---|
| Instance Inventory | Fetch all EC2 instances with state, type, purchasing type, and launch time | Foundation for all other EC2 analysis |
| CPU Utilization (7 days) | Fetch average CPU over past 7 days from CloudWatch | Primary signal for idle and overprovisioned detection |
| Network In/Out Metrics | Fetch average network traffic over 7 days from CloudWatch | Secondary signal — near-zero traffic strengthens idle confidence |
| Disk Read Ops | Fetch average disk read activity over 7 days from CloudWatch | Secondary signal — near-zero disk activity strengthens idle confidence |
| Idle Detection | Flag instances with CPU below 5% over 7 days | 5% threshold is industry standard for flagging genuinely unused compute |
| Overprovisioned Detection | Flag instances with CPU between 5-20% that are larger than t3.small | Consistent low CPU on a large instance = wrong size for the workload |
| Underprovisioned Flag | Flag instances with CPU consistently above 80% | Prevents agent from only focusing on savings — reliability matters too |
| Stopped Instance Detection | Flag instances stopped for more than 7 days | Stopped instances still incur EBS storage costs, often forgotten |
| Purchasing Type Awareness | Check if instance is on-demand, reserved, or spot before recommending | Reserved = already paid, stopping saves nothing. Spot = may be intentional |
| Right-Sizing Recommendation | Recommend specific target instance type with monthly savings in dollars | Specific recommendations are actionable, vague ones are not |

---

### RDS Analysis

| Feature | Description | Decision Rationale |
|---|---|---|
| Instance Inventory | Fetch all RDS instances with class, engine, status, Multi-AZ config | Foundation for all RDS analysis |
| CPU + Connection Metrics | Fetch average CPU and connection count over 7 days | Two signals together give much stronger idle confidence than CPU alone |
| IOPS Metrics | Fetch read and write IOPS over 7 days | Zero IOPS combined with zero connections = very confident idle database |
| Free Storage Warning | Flag when free storage drops below 20% of allocated | Running out of database storage is a production emergency, critical to surface |
| Freeable Memory Check | Flag when available memory is consistently low | Low memory causes database performance degradation, often missed |
| Idle Detection | Flag when CPU below 5% AND connections below 5 over 7 days | Requiring both signals prevents false positives on databases with bursty patterns |
| Overprovisioned Detection | Flag CPU consistently below 20% with right-sizing recommendation | Same logic as EC2 — consistent low utilization on large class = wrong size |
| Unnecessary Multi-AZ | Flag Multi-AZ on instances tagged dev, test, staging, sandbox, qa | Multi-AZ doubles cost and is designed for production failover, not dev environments |
| Backup Configuration Check | Flag instances with automated backups disabled | Disabled backups is a data loss risk, not just a best practice |

---

### Security Analysis

| Feature | Description | Decision Rationale |
|---|---|---|
| Security Group Inventory | Fetch all security groups attached to running EC2 instances | Cannot detect misconfigurations without fetching the rules |
| Open SSH Detection | Flag port 22 open to 0.0.0.0/0 as critical | SSH open to the entire internet is one of the most common attack vectors |
| Open RDP Detection | Flag port 3389 open to 0.0.0.0/0 as critical | RDP brute force is extremely common, should never be internet-facing |
| Open Database Port Detection | Flag MySQL, PostgreSQL, MSSQL, MongoDB ports open to 0.0.0.0/0 | Databases exposed to the internet are a direct data breach risk |
| Broad CIDR Detection | Flag sensitive ports open to ranges broader than /16 | Even non-public ranges can be dangerously broad |
| Severity Classification | Classify every finding as critical, high, or medium | Helps users understand what to fix first without needing security expertise |
| Specific Remediation | Provide exact recommended fix per finding | "Restrict to your office IP" is actionable. "Fix this" is not |

---

### Confidence Scoring

| Feature | Description | Decision Rationale |
|---|---|---|
| Multi-Signal Confidence | Score each recommendation as high, medium, or low based on how many metrics support it | Single metric recommendations can be wrong. Multiple signals converging = trustworthy |
| Plain English Confidence Statement | Agent communicates confidence level in natural language within every recommendation | Judges and users should understand why the agent is confident, not just that it is |

---

### Cost Analysis

| Feature | Description | Decision Rationale |
|---|---|---|
| Per-Resource Cost Estimation | Estimate monthly cost per EC2 and RDS instance using on-demand pricing | Without dollar figures, recommendations are abstract. Dollar figures drive decisions |
| Total Waste Calculation | Sum total monthly waste across all idle and overprovisioned resources | Gives the single most impactful number for the demo |
| Savings Ranking | Rank cost recommendations by potential monthly savings, highest first | Users should fix the biggest waste first |
| Cost Summary | On request, produce total spend, total waste, potential savings, and top 3 actions | Gives managers a fast executive overview without going through every finding |

---

### Conversational Agent

| Feature | Description | Decision Rationale |
|---|---|---|
| Proactive Initial Scan | On session open, agent automatically scans and summarizes findings | Judges should see value immediately without needing to type a question first |
| Natural Language Querying | Agent responds to any AWS infrastructure question in plain English | Core value proposition — no need to know boto3 or AWS console |
| Conversation Memory | Agent remembers everything discussed in the current session | Follow-up questions should not require the user to repeat context |
| Selective Tool Calling | Agent only fetches data relevant to the current question | Fetching everything every time wastes tokens and slows responses |
| Priority Ordering | Security findings always surfaced before cost recommendations | A $10 saving is irrelevant if the database is exposed to the internet |
| Advisory Only | Agent never instructs destructive actions, all output is recommendations | Safety requirement — a wrong recommendation that deletes production data is unacceptable |
| Clarification Handling | Agent asks one clarifying question when a query is ambiguous | Better to ask once than to give a confident but wrong answer |
| Graceful Degradation | Agent handles missing or insufficient CloudWatch data without crashing | Real AWS accounts frequently have monitoring gaps, agent must handle this |
| Region Selectability | User selects which AWS region to analyze at session start | Different teams use different regions, single hardcoded region is too limiting |

---

## Part 2 — Features We Are NOT Building (MVP)

| Feature | Description | Why Not Now |
|---|---|---|
| S3 Bucket Analysis | Analyze storage buckets for public access, unused buckets, and cost waste | Out of MVP scope to keep the project focused and deliverable in hackathon timeline |
| IAM Auditing | Analyze user permissions, overpermissioned roles, unused users | IAM analysis is complex and requires deeper security domain knowledge, deferred to version 2 |
| Lambda Analysis | Analyze serverless functions for unused or inefficient configurations | Out of MVP scope, version 2 |
| Multi-Region Simultaneous Analysis | Analyze multiple AWS regions in one session at the same time | Multiplies token usage significantly, adds complexity to response aggregation. Single region is sufficient for demo |
| Automated Remediation | Agent automatically applies fixes such as stopping instances or closing ports | Unacceptable safety risk for MVP. A wrong automated action could take down production infrastructure |
| Fix Plan Output | Structured prioritized action plan listing every fix in order | Good feature but deferred — the core analysis and conversational features take priority |
| Multi-User Authentication | Multiple users logging in with separate AWS accounts | Unnecessary for hackathon demo. One account, one demo is sufficient |
| Scheduled Automated Scans | Agent runs on a schedule and sends alerts without being asked | Requires background job infrastructure, out of scope for hackathon |
| Historical Trend Analysis | Compare resource utilization this week vs last month | Requires storing historical data over time, out of scope for MVP |
| EBS Volume Analysis | Detect unattached or unused EBS storage volumes | Useful but out of scope for MVP, can be added as a quick win in version 2 |
| Cost Anomaly Detection | Flag sudden unexpected spikes in AWS spending | Requires historical baseline data, out of scope for MVP |

---

## Part 3 — Key Business Decisions Made

| Decision | What Was Decided | Why |
|---|---|---|
| Metrics window | 7 days of CloudWatch data | Long enough to smooth out daily spikes, short enough to reflect current state |
| Idle CPU threshold | Below 5% average | Industry standard for flagging genuinely unused compute resources |
| Overprovisioned threshold | 5% to 20% average CPU | Consistent low utilization on a sized-up instance = clear right-sizing opportunity |
| Underprovisioned threshold | Above 80% average CPU | Prevents the agent from only optimizing cost while ignoring reliability |
| RDS idle requires two signals | CPU below 5% AND connections below 5 | Databases can have low CPU but still be actively serving queries, two signals reduce false positives |
| Security prioritized above cost | Security findings shown first always | A security breach is more damaging than any cost inefficiency |
| Purchasing type awareness | Reserved and spot instances get different recommendations than on-demand | Recommending to stop a reserved instance wastes the upfront commitment already paid |
| Proactive agent behavior | Agent scans immediately on open without waiting for user input | Stronger demo experience, immediate value is visible to judges |
| Read only IAM only | Agent has no write permissions to AWS | Safety requirement, agent must never be able to cause infrastructure changes |
| Single region per session | One region analyzed per session | Keeps token usage manageable and response times acceptable |
| Confidence scoring included | Every recommendation includes a confidence level | Recommendations without confidence levels feel like guesses. Scored recommendations feel trustworthy |
| No fix plan for MVP | Fix Plan output deferred | Too many features risk delivering none of them well. Core analysis and conversation come first |
| Credentials via environment variables | No hardcoded credentials anywhere | Security requirement, hardcoded credentials in source code is a critical vulnerability |
| Claude API for LLM | Using Claude API for the agent, Kiro free tier for development | Kiro credits are for building the project. The agent needs a separate funded API for demo and testing |

---

## Part 4 — Open Questions (To Be Debated)

| Question | Options | Status |
|---|---|---|
| What happens if CloudWatch enhanced monitoring is not enabled on an instance? | Show basic metrics only / Flag it as a finding / Skip the instance | Not decided |
| How do we handle instances with no name tag? | Use instance ID as display name / Flag untagged resources as a best practice violation | Not decided |
| Should the agent ask for region at startup or should we hardcode one demo region? | Ask user at startup / Hardcode for demo simplicity | Not decided |
| What pricing source do we use for cost estimates? | Hardcode common instance prices in code / Call AWS Pricing API | Not decided |
| Should the initial proactive scan show a brief summary or full detail? | Brief summary with offer to go deeper / Full detailed report immediately | Not decided |
