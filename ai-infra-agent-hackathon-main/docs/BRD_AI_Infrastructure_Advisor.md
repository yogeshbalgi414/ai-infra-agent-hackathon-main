# Business Requirements Document
## AI Infrastructure Advisor Agent — MVP
**Version:** 1.0  
**Status:** Draft  
**Team:** Hackathon Team (4 members)  
**Scope:** EC2 Instances, RDS Instances, Security Group Analysis, Cost Optimization  

---

## 1. Executive Summary

Cloud infrastructure accumulates waste silently. Teams provision resources for peak load, forget about them, and keep paying. Security misconfigurations get introduced and go unnoticed for months. The AI Infrastructure Advisor Agent gives any engineering team a conversational interface to interrogate their AWS environment — identifying idle resources, surfacing security risks, and delivering prioritized, actionable recommendations in plain English.

---

## 2. Problem Statement

Engineering teams managing AWS face three persistent problems:

**Cost Blindness**
Resources provisioned for a spike or a one-off project remain running indefinitely. Nobody has a clear view of which resources are idle or overprovisioned without manually checking CloudWatch dashboards across every service.

**Security Drift**
Security group rules get added for debugging or testing and never get removed. Open ports accumulate over time. Nobody audits them systematically until something goes wrong.

**Recommendation Gap**
Even when engineers identify a problem, they don't always know the right fix. What should this instance be downsized to? What is the actual monthly saving? What is the risk of changing it? These questions go unanswered.

---

## 3. Goals

- Detect idle and overprovisioned EC2 instances using real CloudWatch metrics
- Detect idle and overprovisioned RDS instances using real CloudWatch metrics
- Identify critical security misconfigurations in EC2 Security Groups
- Assign confidence scores to every recommendation based on how many signals support it
- Quantify cost savings in dollars for every recommendation
- Prioritize security findings above cost recommendations
- Enable natural language conversation so users can ask follow-up questions
- Proactively surface insights when the user opens the agent, without waiting for a question
- Maintain conversation context so the agent builds on previous answers
- Handle missing or insufficient CloudWatch data gracefully without crashing

---

## 4. Users

**Primary User — Cloud Engineer / DevOps Engineer**
Has AWS access, understands infrastructure, wants fast answers without manually checking multiple dashboards. Values technical accuracy and specific recommendations.

**Secondary User — Engineering Manager / Tech Lead**
Wants cost visibility and security posture overview without deep AWS knowledge. Needs plain English summaries and dollar figures they can act on.

---

## 5. Functional Requirements

---

### 5.1 EC2 Analysis

**FR-EC2-01: Instance Inventory**
The agent shall fetch all EC2 instances in the configured AWS account and selected region, capturing instance ID, instance type, instance state, purchasing type, name tag, and launch time.

**FR-EC2-02: CloudWatch Metrics Fetch**
The agent shall fetch the following CloudWatch metrics for each running EC2 instance over the past 7 days:
- CPUUtilization (average)
- NetworkIn (average)
- NetworkOut (average)
- DiskReadOps (average)

**FR-EC2-03: Idle Instance Detection**
The agent shall flag any running EC2 instance as idle when average CPU utilization is below 5% over 7 days. Confidence scoring shall apply based on supporting network and disk signals.

**FR-EC2-04: Overprovisioned Instance Detection**
The agent shall flag any running EC2 instance as overprovisioned when average CPU utilization is between 5% and 20% over 7 days and the instance type is larger than t3.small. The agent shall recommend a specific smaller instance type as replacement.

**FR-EC2-05: Underprovisioned Instance Detection**
The agent shall flag any running EC2 instance with average CPU utilization consistently above 80% over 7 days as potentially underprovisioned, and recommend review.

**FR-EC2-06: Stopped Instance Detection**
The agent shall flag EC2 instances that have been in a stopped state for more than 7 days. Stopped instances continue to incur EBS storage costs and may be candidates for termination.

**FR-EC2-07: Purchasing Type Awareness**
The agent shall check the purchasing type of each instance before making cost recommendations:
- On-Demand → standard cost saving recommendations apply
- Reserved → agent shall note the instance is already committed and stopping it does not reduce cost
- Spot → agent shall flag for manual verification before recommending any action, as spot instances may be intentional for batch workloads

**FR-EC2-08: Right-Sizing Recommendation**
For every overprovisioned on-demand instance, the agent shall recommend a specific target instance type and calculate estimated monthly savings in dollars based on AWS on-demand pricing.

**EC2 Utilization Thresholds:**
| CPU Average (7 days) | Classification | Recommended Action |
|---|---|---|
| Below 5% | Idle | Stop or terminate |
| 5% to 20% | Overprovisioned | Downsize instance type |
| 20% to 80% | Healthy | No action needed |
| Above 80% | Underprovisioned | Review and consider upgrading |

---

### 5.2 RDS Analysis

**FR-RDS-01: Instance Inventory**
The agent shall fetch all RDS instances in the configured AWS account and selected region, capturing instance identifier, instance class, database engine, status, Multi-AZ configuration, and name tags.

**FR-RDS-02: CloudWatch Metrics Fetch**
The agent shall fetch the following CloudWatch metrics for each RDS instance over the past 7 days:
- CPUUtilization (average)
- DatabaseConnections (average)
- ReadIOPS (average)
- WriteIOPS (average)
- FreeStorageSpace (minimum)
- FreeableMemory (average)

**FR-RDS-03: Idle Database Detection**
The agent shall flag any RDS instance as idle when average CPU is below 5% AND average database connections are below 5 over 7 days. Confidence scoring shall apply based on supporting IOPS signals.

**FR-RDS-04: Overprovisioned Database Detection**
The agent shall flag RDS instances with average CPU consistently below 20% and recommend a smaller instance class with estimated monthly savings.

**FR-RDS-05: Unnecessary Multi-AZ Detection**
The agent shall flag RDS instances with Multi-AZ enabled where the instance name or tags suggest a non-production environment (containing keywords: dev, test, staging, sandbox, qa). Multi-AZ roughly doubles RDS cost and is unnecessary for non-production workloads.

**FR-RDS-06: Low Storage Warning**
The agent shall flag any RDS instance where FreeStorageSpace drops below 20% of total allocated storage as a critical operational warning requiring immediate attention.

**FR-RDS-07: Low Memory Warning**
The agent shall flag any RDS instance where FreeableMemory is consistently low relative to total instance memory as a potential performance issue, recommending instance class upgrade.

**FR-RDS-08: Backup Configuration Check**
The agent shall flag any RDS instance with automated backups disabled as a best practice violation and recommend enabling with a minimum 7-day retention window.

**RDS Utilization Thresholds:**
| Condition | Classification | Recommended Action |
|---|---|---|
| CPU < 5% AND Connections < 5 | Idle | Snapshot and delete |
| CPU < 20% | Overprovisioned | Downsize instance class |
| Multi-AZ on non-prod | Unnecessary cost | Disable Multi-AZ |
| FreeStorage < 20% | Critical warning | Increase allocated storage |
| Backups disabled | Best practice violation | Enable automated backups |

---

### 5.3 Security Analysis

**FR-SEC-01: Security Group Inventory**
The agent shall fetch all Security Groups associated with running EC2 instances in the selected region.

**FR-SEC-02: Open SSH Detection**
The agent shall flag any Security Group that allows inbound traffic on port 22 (SSH) from source 0.0.0.0/0 or ::/0 as a critical security risk.

**FR-SEC-03: Open RDP Detection**
The agent shall flag any Security Group that allows inbound traffic on port 3389 (RDP) from source 0.0.0.0/0 or ::/0 as a critical security risk.

**FR-SEC-04: Open Database Port Detection**
The agent shall flag any Security Group allowing inbound traffic from 0.0.0.0/0 on the following ports as critical:
- 3306 (MySQL)
- 5432 (PostgreSQL)
- 1433 (MSSQL)
- 27017 (MongoDB)

**FR-SEC-05: Broad CIDR Detection**
The agent shall flag any Security Group rule using a CIDR range broader than /16 on sensitive ports (below 1024) as a high severity finding.

**FR-SEC-06: Severity Classification**
Every security finding shall be classified by severity:
| Severity | Condition |
|---|---|
| Critical | Port 22, 3389, or database ports open to 0.0.0.0/0 |
| High | Any port below 1024 open to 0.0.0.0/0 |
| Medium | Sensitive ports open to unusually broad CIDR ranges |

**FR-SEC-07: Remediation Recommendation**
For every security finding the agent shall provide a specific recommended fix. Example: "Restrict port 22 to your office IP range instead of 0.0.0.0/0."

---

### 5.4 Confidence Scoring

**FR-CONF-01: Multi-Signal Confidence**
Every idle or overprovisioned recommendation shall include a confidence score based on how many independent metrics support the finding.

**EC2 Confidence Logic:**
| Signals Present | Confidence |
|---|---|
| CPU low + Network near zero + Disk near zero | High |
| CPU low + one other signal | Medium |
| CPU low only | Low |

**RDS Confidence Logic:**
| Signals Present | Confidence |
|---|---|
| CPU low + Connections near zero + IOPS near zero | High |
| CPU low + one other signal | Medium |
| CPU low only | Low |

**FR-CONF-02: Confidence in Response**
The agent shall communicate confidence level in plain English within every recommendation. Example: "High confidence this instance is unused — CPU, network traffic, and disk activity have all been near zero for 7 days."

---

### 5.5 Cost Analysis

**FR-COST-01: Per-Resource Cost Estimation**
The agent shall estimate monthly cost for every EC2 and RDS instance based on AWS on-demand pricing for the instance type and selected region.

**FR-COST-02: Total Waste Calculation**
The agent shall calculate total estimated monthly waste from idle and overprovisioned resources combined across EC2 and RDS.

**FR-COST-03: Savings Prioritization**
Within cost recommendations, the agent shall rank by potential monthly savings highest first so users know where to focus.

**FR-COST-04: Cost Summary**
On request the agent shall produce a cost summary covering:
- Total current estimated monthly spend (EC2 + RDS combined)
- Total identified monthly waste
- Potential savings if all recommendations are applied
- Top 3 highest impact cost actions

---

### 5.6 Conversational Agent

**FR-AGENT-01: Proactive Initial Scan**
When a user opens the agent, it shall automatically trigger a full scan of the selected region and present a summary of findings without waiting for the user to ask. The summary shall cover security findings first, then cost waste, then best practice violations.

**FR-AGENT-02: Natural Language Querying**
After the initial scan the agent shall remain fully conversational, responding to follow-up questions in natural language.

Example queries the agent must handle:
```
"Show me all unused resources"
"What is costing me the most money?"
"Are there any security risks?"
"Which EC2 instances can I safely downsize?"
"What would I save if I acted on all your recommendations?"
"Tell me more about the second instance you mentioned"
"Is the database in this region safe to delete?"
"Which of these is highest priority?"
```

**FR-AGENT-03: Conversation Memory**
The agent shall maintain full conversation history within a session. Follow-up questions shall be answered in context of what was already discussed without the user needing to repeat themselves.

**FR-AGENT-04: Selective Tool Calling**
The agent shall only call the AWS APIs relevant to the current question. A security question shall not trigger cost API calls. A question about a specific instance shall not re-fetch all instances.

**FR-AGENT-05: Priority Order**
The agent shall always surface and address findings in this order:
1. Critical and high security findings
2. Cost waste from idle resources
3. Cost waste from overprovisioned resources
4. Best practice violations

**FR-AGENT-06: Safe Recommendations Only**
The agent shall never instruct the user to delete or terminate a resource directly. All output is advisory. Destructive actions require explicit human decision and execution outside the agent.

**FR-AGENT-07: Clarification Handling**
When a user query is ambiguous the agent shall ask one focused clarifying question before proceeding rather than making assumptions.

**FR-AGENT-08: Graceful Degradation**
When CloudWatch data is missing, insufficient, or covers fewer than 3 days, the agent shall inform the user clearly and provide whatever partial analysis is possible rather than failing silently or crashing. Example: "This instance only has 2 days of CloudWatch data available. Showing available metrics but recommend manual review before acting."

---

## 6. Non-Functional Requirements

**NFR-01: Response Time**
The agent shall respond to any query within 15 seconds under normal conditions.

**NFR-02: Token Efficiency**
The agent shall not fetch all AWS data upfront on every query. It shall fetch only the data relevant to the current question to avoid exceeding LLM context limits and to keep response times acceptable.

**NFR-03: Read Only AWS Access**
The agent shall operate exclusively with read-only AWS IAM permissions. It shall have no ability to modify, create, or delete any AWS resource under any circumstance.

**NFR-04: Credentials Security**
AWS credentials shall be loaded from environment variables only. No credentials shall be hardcoded anywhere in source code.

**NFR-05: Region Selectability**
The agent shall support user-selectable AWS regions. The user shall specify which region to analyze at the start of a session. Only one region is analyzed per session.

---

## 7. Technical Architecture

```
┌─────────────────────────────────────────────────┐
│                  Chat UI                         │
│         (User types, agent responds)             │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│              LangChain Agent                     │
│   - Proactive initial scan on session open       │
│   - Maintains full chat history                  │
│   - Decides which tools to call per query        │
│   - Applies priority order to findings           │
│   - Formats confidence-scored responses          │
└──┬──────────────┬──────────────┬────────────────┘
   │              │              │
┌──▼──┐      ┌───▼───┐     ┌────▼────┐
│ EC2 │      │  RDS  │     │Security │
│Tools│      │ Tools │     │  Tools  │
└──┬──┘      └───┬───┘     └────┬────┘
   │              │              │
┌──▼──────────────▼──────────────▼────┐
│              boto3 Layer             │
│         AWS SDK for Python           │
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│              AWS APIs                 │
│  EC2 | RDS | CloudWatch | EC2 (SG)   │
└───────────────────────────────────────┘
```

---

## 8. Team Module Split

| Person | Module | Responsibilities |
|---|---|---|
| Senior | AWS Setup + Integration | AWS account, IAM read-only role, mock data, architecture, final wiring |
| Person 1 | EC2 Tools | boto3 EC2 fetcher, CloudWatch CPU/network/disk metrics, right-sizing logic, cost estimation |
| Person 2 | RDS Tools + Security Tools | boto3 RDS fetcher, RDS CloudWatch metrics, Multi-AZ check, Security Group fetcher, open port detection, severity scoring |
| Person 3 | LangChain Agent + UI | Agent setup, tool registration, chat memory, system prompt, proactive scan trigger, chat interface |

---

## 9. Interface Contracts

Agreed data shapes between modules. All persons code against these from Day 1 using mock data.

**EC2 Tool Output:**
```json
{
  "instances": [
    {
      "id": "string",
      "name": "string",
      "type": "string",
      "state": "running | stopped",
      "purchasing_type": "on-demand | reserved | spot",
      "cpu_avg_7d": "float",
      "network_in_avg_7d": "float",
      "network_out_avg_7d": "float",
      "disk_read_ops_avg_7d": "float",
      "monthly_cost_usd": "float",
      "days_in_current_state": "integer",
      "confidence": "high | medium | low",
      "classification": "idle | overprovisioned | healthy | underprovisioned",
      "data_available_days": "integer"
    }
  ]
}
```

**RDS Tool Output:**
```json
{
  "instances": [
    {
      "id": "string",
      "name": "string",
      "class": "string",
      "engine": "string",
      "status": "string",
      "multi_az": "boolean",
      "backups_enabled": "boolean",
      "cpu_avg_7d": "float",
      "connections_avg_7d": "float",
      "read_iops_avg_7d": "float",
      "write_iops_avg_7d": "float",
      "free_storage_pct": "float",
      "freeable_memory_mb": "float",
      "monthly_cost_usd": "float",
      "confidence": "high | medium | low",
      "classification": "idle | overprovisioned | healthy",
      "data_available_days": "integer"
    }
  ]
}
```

**Security Tool Output:**
```json
{
  "findings": [
    {
      "security_group_id": "string",
      "attached_instance_id": "string",
      "port": "integer",
      "protocol": "string",
      "source_cidr": "string",
      "severity": "critical | high | medium",
      "description": "string",
      "recommendation": "string"
    }
  ]
}
```

---

## 10. Demo Scenario

The demo AWS account shall have the following resources deliberately configured to showcase all agent capabilities:

**EC2 Instances:**
| Instance | Config | Expected Finding |
|---|---|---|
| t3.large | Running, 2% CPU, near-zero network, 7 days | Idle — High Confidence, $60/month waste |
| m5.xlarge | Running, 8% CPU, on-demand | Overprovisioned, downsize to t3.medium, save $110/month |
| t3.micro | Stopped for 10 days | Stopped instance, storage cost accumulating |

**RDS Instances:**
| Instance | Config | Expected Finding |
|---|---|---|
| db.r5.large | 1% CPU, 1 connection, 7 days | Idle — High Confidence, $180/month waste |
| db.m5.large | Multi-AZ enabled, tagged "dev" | Unnecessary Multi-AZ, save $120/month |

**Security Groups:**
| Rule | Expected Finding |
|---|---|
| Port 22 open to 0.0.0.0/0 | Critical — SSH exposed to internet |
| Port 3306 open to 0.0.0.0/0 | Critical — MySQL exposed to internet |

**Demo Conversation Flow:**
```
Agent opens → proactive scan summary:
  "I found 2 critical security risks, 3 idle or 
   overprovisioned resources, and $470/month in 
   potential savings. Here is what needs attention..."

Judge: "What are the security risks?"
Agent: Details both critical findings with specific remediation steps

Judge: "What is costing me the most?"
Agent: Ranks resources by waste, idle RDS at $180/month is top

Judge: "How confident are you about the idle database?"
Agent: Explains high confidence — CPU, connections, and IOPS all near zero for 7 days

Judge: "What would I save if I fixed everything?"
Agent: $470/month, $5,640/year

Judge: "Tell me more about the stopped EC2 instance"
Agent: Remembers context, gives full details on the specific instance
```

---

## 11. Out of Scope — MVP

| Feature | Reason Deferred |
|---|---|
| S3 bucket analysis | Out of MVP scope, version 2 |
| IAM user and role auditing | Out of MVP scope, version 2 |
| Lambda function analysis | Out of MVP scope, version 2 |
| Multi-region simultaneous analysis | Token management complexity, version 2 |
| Automated remediation | Safety risk, agent is advisory only |
| Fix Plan output | Deferred to keep MVP focused |
| Multi-user authentication | Unnecessary for hackathon demo |
| Scheduled automated scans | Out of MVP scope |
| Historical trend analysis | Out of MVP scope |
