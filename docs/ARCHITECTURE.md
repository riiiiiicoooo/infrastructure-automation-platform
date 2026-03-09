# System Architecture: Infrastructure Automation Platform

**Last Updated:** February 2025
**Status:** Production (v2.0)

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        USER LAYER                                       │
│                                                                         │
│  ServiceNow Portal          Datadog Dashboards          CLI / API       │
│  (request intake,           (health, cost,              (Terraform,     │
│   approvals)                 compliance, incidents)      Ansible, REST)  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ HTTPS / WebSocket / gRPC
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    API LAYER (FastAPI)                                   │
│                                                                         │
│  /api/v1/provisioning  - Submit request, check status, decommission    │
│  /api/v1/deployments   - Submit change, trigger simulation, rollout    │
│  /api/v1/incidents     - Alert ingestion, status, resolution history   │
│  /api/v1/compliance    - Scan results, policy status, reports          │
│  /api/v1/resources     - CMDB queries, dependency graphs              │
│  /api/v1/audit         - Immutable log queries                        │
│                                                                         │
│  Middleware: auth (JWT/SAML), tenant-scoped rate limiting, request    │
│  logging, tenant context injection                                    │
│                                                                         │
│  Rate Limiting (per tenant, Redis-backed):                             │
│  ├── Provisioning: 10 requests/min (prevents queue flooding)          │
│  ├── Deployments: 5 requests/min                                      │
│  ├── Incident API: 1000 requests/min (high-throughput alert ingestion)│
│  ├── Compliance: 20 requests/min                                      │
│  └── Priority queue: incident remediation always takes precedence     │
│       over provisioning jobs in the Temporal task queue                │
└──────┬──────────────┬──────────────┬──────────────┬─────────────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐
│ PROVISIONING │ │  SIMULATION  │ │  INCIDENT    │ │  OBSERVABILITY       │
│  SERVICE     │ │  SERVICE     │ │  RESPONSE    │ │  SERVICE             │
│              │ │              │ │  SERVICE     │ │                      │
│ Temporal     │ │ Docker API   │ │ scikit-learn │ │ TimescaleDB          │
│ Terraform    │ │ Synthetic    │ │ spaCy NLP    │ │ Datadog API          │
│ Ansible      │ │   workloads  │ │ PagerDuty    │ │ OPA / Rego           │
│ OPA          │ │ KPI monitor  │ │ Slack        │ │ Datadog APM          │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────────┬───────────┘
       │                │               │                      │
       ▼                ▼               ▼                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                      │
│                                                                         │
│  PostgreSQL 15                       Redis 7                            │
│  ├── Resources, environments         ├── Session cache                  │
│  ├── Deployments, rollout state      ├── Real-time metrics buffer       │
│  ├── Incidents, playbooks            ├── Provisioning job queue         │
│  ├── Compliance policies + results   └── Rate limiting                  │
│  ├── Audit log (append-only)                                            │
│  └── CMDB (resources + dependencies) S3 / Azure Blob                   │
│                                      ├── Terraform state (remote)       │
│  TimescaleDB                         ├── Simulation snapshots           │
│  ├── Infrastructure metrics          ├── Compliance reports             │
│  └── Anomaly detection baselines     └── Audit archives (cold storage) │
│                                                                         │
│  HashiCorp Vault                                                        │
│  ├── Cloud provider credentials                                         │
│  ├── Database connection strings                                        │
│  └── API keys (Datadog, PagerDuty, Slack)                              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Service Architecture

The platform is organized into four core services. Each runs as an independent process but shares the same PostgreSQL database with schema-level isolation. Temporal handles workflow orchestration across services.

**Backpressure and priority queuing:**

Temporal task queues are separated by service: `provisioning-queue`, `simulation-queue`, `incident-queue`, `compliance-queue`. The incident queue is configured with higher priority workers and dedicated capacity. If a developer's rogue script floods the provisioning API with 200 environment requests, tenant-scoped rate limiting in the API layer (Redis-backed, configurable per endpoint) throttles the inbound rate. Requests that pass rate limiting enter the provisioning queue, which has a configurable concurrency limit per tenant (default: 5 parallel workflows). This prevents one tenant from consuming all Temporal worker capacity and starving incident remediation, which always runs on its own dedicated worker pool.

### 2.1 Provisioning Service

Handles request intake, policy validation, IaC generation, execution, and post-provisioning configuration.

```
Request submitted (ServiceNow or API)
      │
      ▼
┌─────────────────────┐
│  Request Validation  │
│  - Schema check      │
│  - Required fields   │
│  - Template exists   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Policy Engine (OPA) │
│                      │
│  Evaluate Rego       │
│  policies:           │
│  - NIST 800-53       │
│  - Budget quota      │
│  - Network rules     │
│  - Resource limits   │
│  - Naming standards  │
│                      │
│  < 100ms evaluation  │
└──────────┬──────────┘
           │
     ┌─────┴──────┐
     ▼            ▼
┌─────────┐  ┌──────────┐
│ DENY    │  │ ALLOW    │
│         │  │          │
│ Return  │  │ Check    │
│ reason  │  │ approval │
│ + which │  │ required?│
│ policy  │  │          │
│ failed  │  └────┬─────┘
└─────────┘       │
            ┌─────┴──────┐
            ▼            ▼
     ┌──────────┐  ┌──────────┐
     │ Auto-    │  │ Needs    │
     │ approved │  │ approval │
     │ (under   │  │ (>$500/mo│
     │ threshold│  │  or prod │
     │  + dev/  │  │  access) │
     │  staging)│  │          │
     └────┬─────┘  │ Pause    │
          │        │ workflow, │
          │        │ notify   │
          │        │ approver │
          │        │          │
          │        │ Approver │
          │        │ sees:    │
          │        │ - Diff   │
          │        │   view of│
          │        │   tf plan│
          │        │   output │
          │        │ - Cost   │
          │        │   delta  │
          │        │ - Policy │
          │        │   results│
          │        │          │
          │        │ Resume   │
          │        │ on signal│
          │        └────┬─────┘
          │             │
          └──────┬──────┘
                 ▼
┌─────────────────────────────┐
│  Temporal Workflow:          │
│  provision_environment       │
│                              │
│  Step 1: Generate Terraform  │
│    - Select base template    │
│    - Inject parameters       │
│    - Apply security groups   │
│    - Add tagging standards   │
│                              │
│  Step 2: Dry-run             │
│    - terraform plan          │
│    - Validate output         │
│    - Estimate cost           │
│                              │
│  Step 3: Execute             │
│    - terraform apply         │
│    - Capture resource IDs    │
│    - Store state remotely    │
│                              │
│  Step 4: Configure           │
│    - Ansible hardening       │
│    - CIS benchmark checks    │
│    - Install agents          │
│    - Configure SSH/access    │
│                              │
│  Step 5: Register            │
│    - CMDB entry              │
│    - Dependency mapping      │
│    - Monitoring setup        │
│    - Alert rules             │
│                              │
│  Step 6: Validate            │
│    - Compliance scan         │
│    - Health checks           │
│    - Connectivity tests      │
│                              │
│  Step 7: Notify              │
│    - Connection details      │
│    - Compliance status       │
│    - Estimated monthly cost  │
└─────────────────────────────┘
```

**Why Temporal over Airflow or Step Functions:**

| Criteria | Temporal | Airflow | AWS Step Functions |
|---|---|---|---|
| Long-running workflows | Native. Workflows can run for hours/days (provisioning + approval waits) | Designed for batch DAGs, not long-running processes | 1-year max execution, JSONPath state management gets unwieldy |
| Human-in-the-loop | Signal/query primitives. Workflow pauses, resumes on external signal. | No native support. Requires external polling. | Callback tasks work but require additional infrastructure |
| Failure recovery | Durable execution. Workflow resumes at exact failed step after platform restart. | Task retry, but DAG-level recovery is manual | Retry per state, but debugging failed executions is painful |
| Dynamic branching | Workflows are code. Conditional logic is just if/else in Python/Go. | DAGs are static. Dynamic task generation is a workaround. | Choice states work for simple branching, complex logic is hard to express |
| Cloud lock-in | Self-hosted or Temporal Cloud. Runs anywhere. | Self-hosted. | AWS only. |

**Approval experience for approvers:**

When a provisioning workflow pauses for approval, the approver does not dig through logs to figure out what they are signing off on. The portal renders a structured diff view showing exactly what Terraform will create, modify, or destroy, pulled directly from the `terraform plan` output:

- Resources being created (green), modified (yellow), or destroyed (red)
- Estimated cost delta (monthly increase/decrease from current baseline)
- Policy evaluation results (which controls passed, which required the approval gate)
- Requester details and project context

The approver clicks approve or deny with a required comment. The Temporal workflow receives the signal and resumes or terminates accordingly. The approval decision, comment, and timestamp are written to the audit log.

**Terraform template generation approach:**

Templates are not generated from scratch for each request. The system maintains a library of approved base modules (versioned in Git) and composes them based on request parameters:

```
Base modules (internal Terraform registry):
├── modules/compute/        # EC2, auto-scaling groups
├── modules/networking/     # VPC, subnets, security groups, NACLs
├── modules/storage/        # EBS, S3, RDS
├── modules/security/       # IAM roles, KMS keys, WAF rules
├── modules/monitoring/     # Datadog agent, CloudWatch alarms
└── modules/compliance/     # Config rules, GuardDuty, CloudTrail

Request: {type: "staging", compute: "t3.large", storage: "100GB", rds: true}
  -> Compose: modules/compute + modules/networking + modules/storage + modules/monitoring
  -> Inject parameters: instance_type = "t3.large", volume_size = 100, rds_enabled = true
  -> Apply overrides: security group for staging (internal-only HTTP/HTTPS)
  -> Tag all resources: {project, team, environment, cost_center, provisioned_by}
  -> Output: complete .tf file ready for plan/apply
```

### 2.2 Simulation Service

Handles digital twin creation, test execution, and progressive deployment with automated rollback.

```
Infrastructure change submitted (Terraform plan, Ansible playbook, config update)
           │
           ▼
┌──────────────────────────┐
│  Digital Twin Spin-up     │
│                           │
│  Docker Compose           │
│  - Mirror target topology │
│  - Network simulation     │
│  - Mock external services │
│  - Synthetic data loaded  │
│                           │
│  Spin-up time: < 10 min   │
│  Cost: ~$200/run          │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  Apply Change to Twin     │
│                           │
│  Execute the same         │
│  Terraform/Ansible that   │
│  would run in production  │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  Automated Test Suite     │
│                           │
│  ┌────────────────────┐   │
│  │ Integration Tests  │   │
│  │ End-to-end flows   │   │
│  │ pytest + requests   │   │
│  └────────────────────┘   │
│  ┌────────────────────┐   │
│  │ Performance Tests  │   │
│  │ Simulated peak     │   │
│  │ Locust load gen    │   │
│  └────────────────────┘   │
│  ┌────────────────────┐   │
│  │ Chaos Tests        │   │
│  │ Network partition   │   │
│  │ Process kill        │   │
│  │ Disk fill           │   │
│  │ Latency injection   │   │
│  └────────────────────┘   │
│  ┌────────────────────┐   │
│  │ Regression Tests   │   │
│  │ Existing endpoints │   │
│  │ Data integrity     │   │
│  └────────────────────┘   │
└──────────┬───────────────┘
           │
     ┌─────┴──────┐
     ▼            ▼
┌─────────┐  ┌──────────────────────────┐
│ FAIL    │  │ PASS                      │
│         │  │                           │
│ Report  │  │ Progressive Rollout:      │
│ failures│  │                           │
│ Block   │  │  1% ─ observe 15 min     │
│ deploy  │  │    └─ KPIs OK? ──┐       │
│         │  │                   ▼       │
│         │  │ 10% ─ observe 30 min     │
│         │  │    └─ KPIs OK? ──┐       │
│         │  │                   ▼       │
│         │  │ 50% ─ MANUAL APPROVAL    │
│         │  │    └─ KPIs OK? ──┐       │
│         │  │                   ▼       │
│         │  │ 100% ─ complete          │
│         │  │                           │
│         │  │ At ANY stage:             │
│         │  │ KPI degradation triggers  │
│         │  │ automatic rollback to     │
│         │  │ previous known-good state │
└─────────┘  └──────────────────────────┘
```

**KPI monitoring during rollout:**

The rollout engine monitors these metrics at each stage with configurable thresholds:

| Metric | Default Threshold | Rollback Trigger |
|---|---|---|
| Error rate | < 1% | > 2% sustained for 5 minutes |
| p99 latency | < 500ms | > 1000ms sustained for 5 minutes |
| CPU utilization | < 70% | > 90% sustained for 10 minutes |
| Memory utilization | < 80% | > 95% sustained for 5 minutes |
| Health check pass rate | 100% | < 98% for 3 consecutive checks |
| Active connections | Within 2 std dev of baseline | > 3 std dev for 5 minutes |

**Why containerized twins over persistent staging environments:**

A persistent staging environment that mirrors production costs 60-80% of the production budget ($35K-$45K/month) and drifts from production configuration over time. Containerized twins spin up on demand from production configuration snapshots, run the test suite, and tear down. Cost per simulation run is approximately $200 in compute time. For an organization running 50 simulation cycles per month, that is $10K/month vs $45K/month for persistent staging, and the twin is guaranteed to match production topology because it is generated from the same source configuration.

### 2.3 Incident Response Service

Handles alert ingestion, ML-based correlation and classification, automated remediation, and decision support.

```
Alert arrives (Datadog, Splunk, CloudWatch, Prometheus, PagerDuty webhook)
           │
           ▼
┌──────────────────────────┐
│  Alert Ingestion          │
│                           │
│  Normalize to schema:     │
│  {source, timestamp,      │
│   severity_raw, message,  │
│   affected_resource,      │
│   metadata}               │
│                           │
│  Dedup check:             │
│  Same resource + message  │
│  within 5-minute window   │
│  = suppress duplicate     │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│  ML Correlation Engine                        │
│                                               │
│  1. Time-window grouping (5-min sliding)      │
│     Group alerts arriving within 5 min        │
│     that share affected resources             │
│                                               │
│  2. Dependency graph traversal                │
│     Load resource dependency graph from CMDB  │
│     If Alert A affects Service X, and         │
│     Service X depends on Database Y, and      │
│     Alert B affects Database Y, then          │
│     B is likely root cause, A is symptom      │
│                                               │
│  3. Root cause scoring                        │
│     Random forest model trained on:           │
│     - Alert source                            │
│     - Resource type                           │
│     - Dependency depth                        │
│     - Historical resolution patterns          │
│     - Time of day / day of week               │
│                                               │
│  Output: Correlated incident with             │
│  root cause identification                    │
│  (500 raw alerts -> 87 incidents/month)       │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│  NLP Incident Classifier                      │
│                                               │
│  spaCy pipeline processing alert text:        │
│  1. Tokenize + extract entities               │
│     (service names, error codes, metrics)     │
│  2. Classify incident type:                   │
│     service_health | storage | network |      │
│     database | security | deployment | cost   │
│  3. Predict severity: P1 / P2 / P3           │
│  4. Route to team based on classification     │
│                                               │
│  Confidence threshold: 0.95                   │
│  Below threshold: route to human triage       │
│                                               │
│  Accuracy: 92% (validated monthly against     │
│  human-classified incidents)                  │
└──────────┬───────────────────────────────────┘
           │
     ┌─────┴──────┐
     ▼            ▼
┌──────────┐  ┌──────────────────────────────┐
│ HAS      │  │ NO PLAYBOOK MATCH            │
│ PLAYBOOK │  │                               │
│          │  │ Route to on-call engineer:    │
│ Execute: │  │ - Pre-filled incident context │
│ 1. Safety│  │ - Dependency graph visual     │
│    check │  │ - Similar past incidents      │
│ 2. Run   │  │ - Recommended resolution      │
│    action│  │   steps from knowledge base   │
│ 3. Health│  │ - PagerDuty escalation        │
│    check │  │ - Slack channel created       │
│ 4. Log   │  │                               │
│          │  │ Resolution logged and fed     │
│ Verify   │  │ back to ML model for next     │
│ resolved │  │ retraining cycle              │
└──────────┘  └──────────────────────────────┘
```

**Remediation playbook architecture:**

Playbooks are defined as YAML files version-controlled in Git. Each playbook has preconditions (when to trigger), actions (what to do), safety checks (validation before and after), and rollback (undo if the fix doesn't work).

```yaml
# Example: playbooks/service_restart.yaml
name: service_restart
description: Restart a crashed or unresponsive service
trigger:
  incident_type: service_health
  subtypes: [process_crash, health_check_failure]
  confidence_min: 0.95

preconditions:
  - check: service_exists
    params: {service_name: "{{affected_resource}}"}
  - check: restart_count_below_threshold
    params: {service_name: "{{affected_resource}}", max_restarts: 3, window_hours: 1}

actions:
  - type: restart_service
    params: {service_name: "{{affected_resource}}", graceful: true, timeout_seconds: 30}

post_checks:
  - check: health_check_passing
    params: {service_name: "{{affected_resource}}", retry_count: 3, retry_interval: 10}
  - check: error_rate_below_threshold
    params: {service_name: "{{affected_resource}}", threshold: 0.02, window_minutes: 5}

rollback:
  - type: escalate_to_human
    params: {reason: "Service restart did not resolve health check failure"}

metadata:
  auto_resolution_rate: 0.84
  avg_execution_time_seconds: 45
  last_updated: "2025-01-15"
```

**Why random forest + NLP over deep learning:**

The incident classification model needs to run inference at alert ingestion speed (< 30 seconds from alert arrival to classification). Deep learning models (transformers, LSTMs) require GPU infrastructure that adds cost and operational complexity. With ~500 incidents/month of training data after 6 months, a transformer model would be prone to overfitting. Random forest operates on structured alert metadata (source, severity, resource type, time features) while spaCy handles text classification on the unstructured message field. The ensemble achieves 92% accuracy, which clears the 90% threshold we set as the minimum viable accuracy. Model retraining runs monthly on the rolling 6-month window of resolved incidents. If accuracy drops below 88% (monitored via classification accuracy dashboard), the system falls back to rule-based routing while the data science team investigates.

### 2.4 Observability Service

Handles metrics collection, anomaly detection, compliance scanning, and reporting.

```
┌───────────────────────────────────────────────────────┐
│  METRICS PIPELINE                                      │
│                                                        │
│  Datadog Agent (per host)                              │
│  ├── System: CPU, memory, disk, network                │
│  ├── Application: request rate, error rate, latency    │
│  ├── Custom: queue depth, connection pool, cache hit   │
│  └── Traces: distributed request tracing               │
│           │                                            │
│           ▼                                            │
│  TimescaleDB (time-series storage)                     │
│  ├── Hypertable: 1-second granularity, 7-day hot       │
│  ├── Continuous aggregates: 1-min, 5-min, 1-hr rollups │
│  ├── Compression: 90%+ for data older than 24 hours    │
│  └── Retention: 90 days detailed, 2 years aggregated   │
│           │                                            │
│           ▼                                            │
│  Anomaly Detection Engine                              │
│  ├── Z-score: flag metrics > 3 std dev from baseline   │
│  ├── IQR: flag metrics outside 1.5x interquartile range│
│  ├── Adaptive baselines: exponential moving average     │
│  │   with seasonal adjustment (time-of-day, day-of-week│
│  └── Alert generated if anomaly persists > 3 data points│
│           │                                            │
│           ▼                                            │
│  Datadog Dashboards (APM + Infrastructure)            │
│  ├── Infrastructure Health (real-time)                  │
│  ├── Cost Tracking (daily refresh)                      │
│  ├── Deployment Velocity (DORA metrics)                 │
│  ├── Incident Trends (MTTR, volume, auto-resolution)   │
│  ├── Automatic Service Maps (dependency discovery)      │
│  └── Compliance Posture (scan results, drift count)     │
└───────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────┐
│  COMPLIANCE PIPELINE                                   │
│                                                        │
│  Scheduled scan (hourly for production, daily others)  │
│           │                                            │
│           ▼                                            │
│  Resource Discovery                                    │
│  ├── Query cloud provider APIs for current state       │
│  ├── Compare against CMDB registered resources         │
│  └── Flag unregistered resources (shadow IT detection)  │
│           │                                            │
│           ▼                                            │
│  OPA Policy Evaluation                                 │
│  ├── Load current Rego policies from Git               │
│  ├── Evaluate each resource against applicable policies│
│  ├── Policies organized by framework:                  │
│  │   ├── nist_800_53/                                  │
│  │   ├── fedramp_moderate/                             │
│  │   ├── soc2/                                         │
│  │   └── organization_custom/                          │
│  └── Output: pass/fail per control per resource        │
│           │                                            │
│           ▼                                            │
│  Drift Detection                                       │
│  ├── Compare current resource config vs. Terraform state│
│  ├── Flag any delta as configuration drift              │
│  └── Auto-remediate if drift policy says "enforce"      │
│       (e.g., someone manually opened a security group   │
│        that should be restricted)                       │
│           │                                            │
│           ▼                                            │
│  Report Generation                                     │
│  ├── On-demand compliance report (PDF/Excel)           │
│  ├── Scheduled weekly summary to compliance officer    │
│  └── Audit-ready export with evidence per control      │
└───────────────────────────────────────────────────────┘
```

**Why OPA over hardcoded rules or commercial GRC tools:**

Hardcoded compliance rules (if/else in application code) require engineering deployments for every policy update. When NIST publishes new guidelines or the organization updates internal policies, the compliance team has to file a ticket with engineering, wait for a sprint, and hope the implementation matches their intent. OPA decouples policy from application code. Compliance engineers write Rego policies (declarative, testable, version-controlled) that evaluate in < 100ms. Policies are reviewed via pull request, tested with `opa test`, and deployed independently of application releases.

Commercial GRC tools (ServiceNow GRC, Archer, LogicGate) are designed for manual audit workflows: checklists, evidence collection, attestation forms. They don't integrate into automated provisioning pipelines or evaluate policies against live infrastructure state in real time. They answer "did someone check a box" not "is this resource actually compliant right now."

---

## 3. Data Architecture

### 3.1 Core Schema

```sql
-- Organizations / tenants
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    cloud_provider TEXT CHECK (cloud_provider IN ('aws', 'azure', 'gcp')),
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Environment templates
CREATE TABLE environment_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    name TEXT NOT NULL,                          -- 'development', 'staging', 'production'
    description TEXT,
    terraform_modules JSONB NOT NULL,            -- list of module refs + default params
    ansible_playbooks JSONB NOT NULL,            -- post-provisioning config
    policy_requirements JSONB NOT NULL,          -- required OPA policy bundles
    estimated_monthly_cost DECIMAL(10,2),
    requires_approval BOOLEAN DEFAULT false,
    approval_level TEXT,                         -- 'team_lead', 'director', 'vp'
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Provisioning requests
CREATE TABLE provisioning_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    template_id UUID REFERENCES environment_templates(id) NOT NULL,
    requested_by UUID NOT NULL,
    project_name TEXT NOT NULL,
    team TEXT NOT NULL,
    parameters JSONB NOT NULL,                   -- user-specified overrides
    estimated_cost DECIMAL(10,2),
    status TEXT CHECK (status IN (
        'submitted', 'validating', 'pending_approval', 'approved',
        'provisioning', 'configuring', 'validating_compliance',
        'active', 'decommissioning', 'decommissioned', 'failed', 'rejected'
    )) DEFAULT 'submitted',
    policy_result JSONB,                         -- OPA evaluation output
    approved_by UUID,
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT,
    terraform_plan_output TEXT,
    temporal_workflow_id TEXT,                    -- reference to Temporal execution
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Managed resources (CMDB)
CREATE TABLE resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    request_id UUID REFERENCES provisioning_requests(id),
    cloud_resource_id TEXT NOT NULL,              -- AWS ARN, Azure resource ID
    resource_type TEXT NOT NULL,                  -- 'ec2_instance', 'rds_instance', 'security_group'
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    environment TEXT NOT NULL,                    -- 'dev', 'staging', 'production'
    status TEXT CHECK (status IN (
        'provisioning', 'active', 'degraded', 'maintenance', 'decommissioning', 'terminated'
    )) DEFAULT 'provisioning',
    configuration JSONB NOT NULL,                -- current config snapshot
    tags JSONB NOT NULL,                         -- project, team, cost_center, etc.
    monthly_cost DECIMAL(10,2),
    last_compliance_scan TIMESTAMPTZ,
    compliance_status TEXT CHECK (compliance_status IN ('compliant', 'non_compliant', 'unknown')),
    created_at TIMESTAMPTZ DEFAULT now(),
    decommissioned_at TIMESTAMPTZ
);

-- Resource dependencies
CREATE TABLE resource_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id UUID REFERENCES resources(id) NOT NULL,
    depends_on_id UUID REFERENCES resources(id) NOT NULL,
    dependency_type TEXT NOT NULL,                -- 'network', 'data', 'service', 'auth'
    UNIQUE(resource_id, depends_on_id)
);

-- Deployments and rollout state
CREATE TABLE deployments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    initiated_by UUID NOT NULL,
    change_type TEXT NOT NULL,                    -- 'terraform', 'ansible', 'config_update'
    change_description TEXT NOT NULL,
    target_resources JSONB NOT NULL,              -- list of resource IDs affected
    status TEXT CHECK (status IN (
        'submitted', 'simulating', 'simulation_passed', 'simulation_failed',
        'rolling_out', 'paused_for_approval', 'completed', 'rolled_back', 'failed'
    )) DEFAULT 'submitted',
    current_stage TEXT,                           -- '1_pct', '10_pct', '50_pct', '100_pct'
    simulation_results JSONB,                    -- test pass/fail summary
    rollout_kpis JSONB,                          -- metrics at each stage
    rollback_state JSONB,                        -- snapshot for automated rollback
    approved_by UUID,
    temporal_workflow_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Incidents
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    correlated_alert_ids JSONB NOT NULL,          -- raw alert IDs grouped into this incident
    classification TEXT NOT NULL,                 -- 'service_health', 'storage', 'network', etc.
    severity TEXT CHECK (severity IN ('p1', 'p2', 'p3')) NOT NULL,
    status TEXT CHECK (status IN (
        'detected', 'classified', 'remediating', 'resolved', 'escalated'
    )) DEFAULT 'detected',
    root_cause_resource_id UUID REFERENCES resources(id),
    classification_confidence FLOAT NOT NULL,
    playbook_used TEXT,                           -- null if human-resolved
    resolution_type TEXT CHECK (resolution_type IN ('auto', 'human', 'escalated')),
    resolution_summary TEXT,
    mttr_seconds INTEGER,                        -- time from detection to resolution
    assigned_to UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- Compliance scan results
CREATE TABLE compliance_scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    resource_id UUID REFERENCES resources(id) NOT NULL,
    framework TEXT NOT NULL,                      -- 'nist_800_53', 'fedramp_moderate', 'soc2'
    control_id TEXT NOT NULL,                     -- 'AC-2', 'SC-7', etc.
    status TEXT CHECK (status IN ('pass', 'fail', 'not_applicable')),
    details JSONB,                               -- specific findings
    policy_version TEXT NOT NULL,                 -- Git SHA of Rego policy
    scanned_at TIMESTAMPTZ DEFAULT now()
);

-- Immutable audit log
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    actor_id UUID NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID,
    details JSONB NOT NULL,
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Append-only: no UPDATE or DELETE allowed
REVOKE UPDATE, DELETE ON audit_log FROM app_user;
```

### 3.2 Indexes

```sql
-- CMDB lookups
CREATE INDEX idx_resources_org ON resources (org_id);
CREATE INDEX idx_resources_type ON resources (resource_type);
CREATE INDEX idx_resources_env ON resources (environment);
CREATE INDEX idx_resources_status ON resources (status);
CREATE INDEX idx_resources_compliance ON resources (compliance_status);
CREATE INDEX idx_resources_cloud_id ON resources (cloud_resource_id);

-- Dependency graph traversal
CREATE INDEX idx_deps_resource ON resource_dependencies (resource_id);
CREATE INDEX idx_deps_depends_on ON resource_dependencies (depends_on_id);

-- Provisioning request tracking
CREATE INDEX idx_requests_org_status ON provisioning_requests (org_id, status);
CREATE INDEX idx_requests_requested_by ON provisioning_requests (requested_by, created_at DESC);

-- Incident queries
CREATE INDEX idx_incidents_org_status ON incidents (org_id, status);
CREATE INDEX idx_incidents_severity ON incidents (severity, created_at DESC);
CREATE INDEX idx_incidents_root_cause ON incidents (root_cause_resource_id);

-- Compliance queries
CREATE INDEX idx_compliance_resource ON compliance_scans (resource_id, scanned_at DESC);
CREATE INDEX idx_compliance_framework ON compliance_scans (framework, control_id, status);
CREATE INDEX idx_compliance_failures ON compliance_scans (status) WHERE status = 'fail';

-- Audit log queries
CREATE INDEX idx_audit_resource ON audit_log (resource_type, resource_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_log (actor_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_log (action, created_at DESC);
```

### 3.3 Entity Relationship Diagram

```
┌────────────────┐       ┌──────────────────────┐
│ organizations  │──1:N──│ environment_templates │
└───────┬────────┘       └──────────────────────┘
        │
       1:N
        │
   ┌────┴────────────────────────────────────┐
   │                                          │
   ▼                                          ▼
┌──────────────────────┐       ┌─────────────────┐
│ provisioning_requests│──1:N──│   resources      │──N:M──┌───────────────────────┐
└──────────────────────┘       └───────┬─────────┘       │ resource_dependencies │
                                       │                  └───────────────────────┘
                                      1:N
                                       │
                    ┌──────────────────┼─────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
             ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐
             │  incidents   │  │ compliance   │  │  audit_log       │
             └─────────────┘  │ scans        │  │  (append-only)   │
                              └──────────────┘  └──────────────────┘

deployments ──N:M── resources (via target_resources JSONB)
```

### 3.4 State Machines

**Provisioning Request Lifecycle:**

```
submitted -> validating -> pending_approval -> approved -> provisioning
                │                                            │
                ▼                                            ▼
             rejected                                   configuring
                                                            │
                                                            ▼
                                                   validating_compliance
                                                            │
                                                      ┌─────┴─────┐
                                                      ▼           ▼
                                                   active       failed
                                                      │
                                                      ▼
                                              decommissioning
                                                      │
                                                      ▼
                                              decommissioned
```

**Deployment Lifecycle:**

```
submitted -> simulating -> simulation_passed -> rolling_out -> completed
                │                                   │
                ▼                                   ▼
        simulation_failed                   paused_for_approval
                                                   │
                                             ┌─────┴─────┐
                                             ▼           ▼
                                         rolling_out  rolled_back
                                             │
                                             ▼
                                         rolled_back (on KPI degradation)
```

**Incident Lifecycle:**

```
detected -> classified -> remediating -> resolved
                │               │
                ▼               ▼
           escalated       escalated
           (low confidence) (fix failed)
```

---

## 4. Infrastructure

### 4.1 Deployment Architecture

```
┌─────────────────────────────────────────────────┐
│               Kubernetes (EKS / AKS)             │
│                                                   │
│  Namespace: platform                              │
│  ├── FastAPI (3 replicas, HPA on CPU/request)     │
│  ├── Temporal server (self-hosted)                │
│  ├── Temporal workers (4 replicas)                │
│  │   ├── provisioning-worker                      │
│  │   ├── simulation-worker                        │
│  │   ├── incident-worker                          │
│  │   └── compliance-worker                        │
│  ├── Redis (StatefulSet, 1 primary + 1 replica)   │
│                                                   │
│  Namespace: monitoring                            │
│  ├── Datadog agent (DaemonSet)                    │
│  ├── Prometheus (for custom metrics)              │
│  └── AlertManager                                 │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│              Managed Services                     │
│                                                   │
│  PostgreSQL 15 (RDS / Azure Database)             │
│  ├── Primary + read replica                       │
│  ├── Multi-AZ for production                      │
│  └── Automated backups, 30-day retention          │
│                                                   │
│  TimescaleDB (dedicated instance)                 │
│  ├── Time-series metrics storage                  │
│  └── Continuous aggregates for dashboards         │
│                                                   │
│  S3 / Azure Blob                                  │
│  ├── Terraform state (versioned, encrypted)       │
│  ├── Simulation snapshots                         │
│  └── Compliance reports + audit archives          │
│                                                   │
│  HashiCorp Vault (self-hosted on K8s)             │
│  ├── Cloud provider credentials                   │
│  ├── Database connection strings                  │
│  └── Third-party API keys                         │
└─────────────────────────────────────────────────┘
```

### 4.2 Network Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  VPC (10.0.0.0/16)                                                │
│                                                                    │
│  ┌──────────────────────┐  ┌──────────────────────┐               │
│  │ Public Subnet         │  │ Private Subnet        │              │
│  │ (10.0.1.0/24)        │  │ (10.0.2.0/24)        │              │
│  │                       │  │                       │              │
│  │ ALB (API gateway)    │  │ K8s worker nodes      │              │
│  │ NAT Gateway          │  │ Temporal server       │              │
│  │                       │  │ Redis                 │              │
│  └──────────────────────┘  └──────────────────────┘               │
│                                                                    │
│  ┌──────────────────────┐  ┌──────────────────────┐               │
│  │ Data Subnet          │  │ Management Subnet     │              │
│  │ (10.0.3.0/24)        │  │ (10.0.4.0/24)        │              │
│  │                       │  │                       │              │
│  │ PostgreSQL (RDS)     │  │ Vault                 │              │
│  │ TimescaleDB          │  │ Bastion host          │              │
│  │ No public access     │  │ VPN endpoint          │              │
│  └──────────────────────┘  └──────────────────────┘               │
│                                                                    │
│  Security Groups:                                                  │
│  ├── sg-api: 443 from ALB only                                    │
│  ├── sg-workers: all traffic from sg-api only                     │
│  ├── sg-data: 5432 from sg-workers only                           │
│  ├── sg-vault: 8200 from sg-workers + sg-mgmt only               │
│  └── sg-mgmt: 22 from VPN CIDR only                              │
└──────────────────────────────────────────────────────────────────┘
```

### 4.3 Local Development

```yaml
# docker-compose.yml
services:
  api:
    build: ./src/api
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/infra_platform
      - REDIS_URL=redis://redis:6379
      - TEMPORAL_HOST=temporal:7233
      - VAULT_ADDR=http://vault:8200
    depends_on: [db, redis, temporal]

  temporal:
    image: temporalio/auto-setup:1.22
    ports: ["7233:7233"]
    environment:
      - DB=postgresql
      - DB_PORT=5432
      - POSTGRES_USER=postgres
      - POSTGRES_PWD=postgres
      - POSTGRES_SEEDS=db
    depends_on: [db]

  temporal-ui:
    image: temporalio/ui:2.22
    ports: ["8080:8080"]
    environment:
      - TEMPORAL_ADDRESS=temporal:7233

  worker:
    build: ./src/api
    command: python -m workers.main
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/infra_platform
      - REDIS_URL=redis://redis:6379
      - TEMPORAL_HOST=temporal:7233
    depends_on: [db, redis, temporal]

  db:
    image: postgres:15-alpine
    ports: ["5432:5432"]
    environment:
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=infra_platform
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql

  timescaledb:
    image: timescale/timescaledb:latest-pg15
    ports: ["5433:5432"]
    environment:
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=metrics

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  vault:
    image: hashicorp/vault:1.15
    ports: ["8200:8200"]
    environment:
      - VAULT_DEV_ROOT_TOKEN_ID=dev-token
    cap_add: [IPC_LOCK]

  grafana:
    image: grafana/grafana:10.2.0
    ports: ["3000:3000"]
    volumes:
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./grafana/datasources:/etc/grafana/provisioning/datasources

volumes:
  pgdata:
```

---

## 5. Security Architecture

### 5.1 Authentication and Authorization

```
User request
      │
      ▼
┌──────────────────┐
│  Identity Provider│
│  (Okta / Azure AD)│
│                   │
│  SAML 2.0 / OIDC │
│  MFA required     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  API Gateway      │
│                   │
│  JWT validation   │
│  Extract: user_id,│
│  org_id, roles    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  RBAC Middleware   │
│                   │
│  Roles:           │
│  - admin          │
│  - platform_eng   │
│  - developer      │
│  - compliance     │
│  - viewer         │
│                   │
│  Permissions:     │
│  ┌───────────────────────────────────────────────────┐
│  │ Action              │ admin │ plat │ dev │ comp  │
│  │ provision_prod      │  ✓    │  ✓   │  ✗  │  ✗   │
│  │ provision_dev       │  ✓    │  ✓   │  ✓  │  ✗   │
│  │ approve_requests    │  ✓    │  ✓   │  ✗  │  ✗   │
│  │ trigger_deployment  │  ✓    │  ✓   │  ✗  │  ✗   │
│  │ view_incidents      │  ✓    │  ✓   │  ✓  │  ✓   │
│  │ manage_playbooks    │  ✓    │  ✓   │  ✗  │  ✗   │
│  │ manage_policies     │  ✓    │  ✗   │  ✗  │  ✓   │
│  │ view_compliance     │  ✓    │  ✓   │  ✓  │  ✓   │
│  │ export_audit        │  ✓    │  ✗   │  ✗  │  ✓   │
│  └───────────────────────────────────────────────────┘
└──────────────────┘
```

### 5.2 Secrets Management

All credentials flow through HashiCorp Vault Dynamic Secrets. No long-lived IAM keys anywhere in the system. No secrets in environment variables, config files, or source code.

```
Temporal workflow starts provisioning step
      │
      ▼
┌──────────────────┐
│  Vault Auth       │
│  (K8s service     │
│   account token)  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Vault AWS        │
│  Secrets Engine   │
│  (Dynamic)        │
│                   │
│  Generates scoped │
│  STS session token│
│  per workflow run  │
│  (1 hour TTL)     │
│                   │
│  IAM policy bound │
│  to requested     │
│  resource types   │
│  only (least      │
│  privilege)       │
│                   │
│  Auto-revoke on   │
│  workflow complete │
│  or TTL expiry,   │
│  whichever comes  │
│  first            │
└────────┬─────────┘
         │
         ▼
  Terraform/Ansible execute with scoped session token
  Token cannot outlive the provisioning workflow
  Vault lease tracked in audit log for compliance
```

Every Temporal workflow run gets its own short-lived credential. If a workflow fails mid-execution and never resumes, the token expires in 1 hour regardless. No credential cleanup scripts needed. Vault's lease revocation handles it automatically.

### 5.3 Encryption

| Layer | Method | Details |
|---|---|---|
| Data in transit | TLS 1.3 | All internal and external communication. Certificate rotation via cert-manager. |
| Data at rest | AES-256 | RDS encryption enabled. S3 server-side encryption (SSE-S3). EBS volume encryption. |
| Terraform state | AES-256 + versioning | S3 bucket with SSE, versioning enabled, and access restricted to platform service account only. |
| Secrets | Vault transit engine | Application-level encryption for sensitive fields in database (API keys, connection strings). |
| Audit logs | Immutable + encrypted | Write-once storage. Separate encryption key managed by compliance team. |

---

## 6. Failure Modes and Recovery

| Failure | Detection | Recovery | RTO |
|---|---|---|---|
| Platform API goes down | Health check failure, ALB stops routing | K8s restarts pods, HPA scales up. In-flight requests retry via client backoff. | < 2 minutes |
| Temporal server crash | Temporal health check | Temporal restarts. Workflows resume from last checkpoint. No data loss. | < 5 minutes |
| Provisioning fails mid-execution | Terraform error, Ansible timeout | Temporal retries failed step. If retry exhausted, mark as failed + alert. Manual intervention with state inspection. | N/A (workflow pauses) |
| Database failure | Connection refused, replication lag alert | Failover to read replica (automated by RDS). Write traffic paused until promotion complete. | < 5 minutes |
| Vault unavailable | Health check failure | New provisioning blocked (can't get credentials). Existing environments unaffected. Vault auto-unseals on restart. | < 10 minutes |
| ML model returns low confidence | Confidence < 0.88 threshold | Fall back to rule-based routing for incident classification. Alert data science team. | Immediate (graceful degradation) |
| Cloud provider API outage | Provisioning timeout, API errors | Queue requests. Retry with exponential backoff. Notify requestors of delay. | Depends on provider |
