# Data Model: Infrastructure Automation Platform

**Last Updated:** February 2025
**Primary Database:** PostgreSQL 15 (RDS / Azure Database)
**Time-Series Database:** TimescaleDB (dedicated instance)
**Secrets:** HashiCorp Vault
**Cache/Queue:** Redis 7

---

## 1. Entity Relationship Diagram

```
┌────────────────┐
│ organizations  │
│────────────────│
│ id (PK)        │
│ name           │
│ cloud_provider │
│ settings       │
└───────┬────────┘
        │
        │ 1:N
        │
   ┌────┴─────────────────────────────────────────────────────────┐
   │                    │                    │                     │
   ▼                    ▼                    ▼                     ▼
┌────────────────┐ ┌────────────────┐ ┌──────────────┐  ┌──────────────┐
│ environment_   │ │ provisioning_  │ │   users      │  │ compliance_  │
│ templates      │ │ requests       │ │──────────────│  │ policies     │
│────────────────│ │────────────────│ │ id (PK)      │  │──────────────│
│ id (PK)        │ │ id (PK)        │ │ org_id (FK)  │  │ id (PK)      │
│ org_id (FK)    │ │ org_id (FK)    │ │ email        │  │ org_id (FK)  │
│ name           │ │ template_id(FK)│ │ role         │  │ framework    │
│ terraform_     │ │ requested_by   │ │ full_name    │  │ rego_policy  │
│   modules      │ │ parameters     │ └──────────────┘  │ version      │
│ ansible_       │ │ status         │                    └──────────────┘
│   playbooks    │ │ policy_result  │
│ estimated_cost │ │ temporal_wf_id │
└────────────────┘ └───────┬────────┘
                           │
                           │ 1:N
                           ▼
                    ┌────────────────┐
                    │  resources     │  (CMDB)
                    │────────────────│
                    │ id (PK)        │
                    │ org_id (FK)    │
                    │ request_id(FK) │
                    │ cloud_id       │
                    │ resource_type  │
                    │ environment    │
                    │ status         │
                    │ configuration  │
                    │ compliance_    │
                    │   status       │
                    │ monthly_cost   │
                    └───────┬────────┘
                            │
               ┌────────────┼─────────────┬──────────────────┐
               │            │             │                  │
              1:N         N:M            1:N                1:N
               │            │             │                  │
               ▼            ▼             ▼                  ▼
       ┌──────────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐
       │  incidents   │ │ resource_│ │ compliance_  │ │  deployments │
       │──────────────│ │ deps     │ │ scans        │ │──────────────│
       │ id (PK)      │ │──────────│ │──────────────│ │ id (PK)      │
       │ org_id (FK)  │ │ resource │ │ resource_id  │ │ org_id (FK)  │
       │ root_cause_  │ │ depends_ │ │ framework    │ │ change_type  │
       │   resource   │ │   on     │ │ control_id   │ │ status       │
       │ classification│ │ dep_type │ │ status       │ │ current_stage│
       │ severity     │ └──────────┘ │ policy_ver   │ │ simulation_  │
       │ playbook_used│              └──────────────┘ │   results    │
       │ resolution   │                               │ rollout_kpis │
       └──────────────┘                               └──────────────┘

                    ┌──────────────┐
                    │  audit_log   │  (append-only, immutable)
                    │──────────────│
                    │ id (PK)      │
                    │ org_id (FK)  │
                    │ actor_id     │
                    │ action       │
                    │ resource_type│
                    │ resource_id  │
                    │ details      │
                    └──────────────┘

                    ┌──────────────┐
                    │  playbooks   │  (remediation definitions)
                    │──────────────│
                    │ id (PK)      │
                    │ org_id (FK)  │
                    │ name         │
                    │ trigger_rules│
                    │ actions      │
                    │ safety_checks│
                    └──────────────┘
```

---

## 2. Full Schema Definition

### 2.1 Organizations

```sql
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,                    -- URL-friendly identifier
    cloud_provider TEXT NOT NULL CHECK (cloud_provider IN ('aws', 'azure', 'gcp')),
    settings JSONB DEFAULT '{}'::jsonb,
    vault_path TEXT NOT NULL,                     -- path in Vault for org secrets
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Example settings JSONB:
-- {
--   "default_approval_threshold_monthly": 500,
--   "max_environments_per_team": 20,
--   "auto_decommission_unused_days": 30,
--   "compliance_frameworks": ["nist_800_53", "soc2"],
--   "rate_limits": {
--     "provisioning_per_min": 10,
--     "deployments_per_min": 5
--   },
--   "notification_channels": {
--     "slack_webhook": "https://hooks.slack.com/...",
--     "pagerduty_service_key": "vault:pagerduty/org_123"
--   }
-- }
```

### 2.2 Users

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN (
        'admin', 'platform_eng', 'developer', 'compliance', 'viewer'
    )),
    team TEXT,                                    -- engineering team name
    is_active BOOLEAN DEFAULT true,
    sso_subject TEXT,                             -- IdP subject identifier
    last_login_at TIMESTAMPTZ,
    preferences JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 2.3 Environment Templates

```sql
CREATE TABLE environment_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    name TEXT NOT NULL,                            -- 'development', 'staging', 'production'
    description TEXT,
    terraform_modules JSONB NOT NULL,              -- module references + default parameters
    ansible_playbooks JSONB NOT NULL,              -- post-provisioning configuration
    policy_requirements JSONB NOT NULL,            -- required OPA policy bundles
    estimated_monthly_cost DECIMAL(10,2),
    requires_approval BOOLEAN DEFAULT false,
    approval_level TEXT CHECK (approval_level IN ('team_lead', 'director', 'vp')),
    max_instances INTEGER,                         -- cap on how many can be provisioned
    auto_decommission_days INTEGER,                -- null = no auto-decommission
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Example terraform_modules JSONB:
-- [
--   {
--     "source": "registry.internal/modules/compute",
--     "version": "2.1.0",
--     "defaults": {
--       "instance_type": "t3.large",
--       "ami_id": "ami-0abcdef1234567890",
--       "volume_size_gb": 100
--     }
--   },
--   {
--     "source": "registry.internal/modules/networking",
--     "version": "1.8.0",
--     "defaults": {
--       "subnet_type": "private",
--       "allowed_ingress": ["443", "8080"]
--     }
--   },
--   {
--     "source": "registry.internal/modules/monitoring",
--     "version": "1.3.0",
--     "defaults": {
--       "datadog_agent": true,
--       "alert_channel": "#platform-alerts"
--     }
--   }
-- ]

-- Example ansible_playbooks JSONB:
-- [
--   {"name": "cis_hardening", "version": "3.0.1"},
--   {"name": "datadog_agent", "version": "2.1.0"},
--   {"name": "ssh_config", "version": "1.0.0", "params": {"allow_from": "vpn_cidr"}}
-- ]
```

### 2.4 Provisioning Requests

```sql
CREATE TABLE provisioning_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    template_id UUID REFERENCES environment_templates(id) NOT NULL,
    requested_by UUID REFERENCES users(id) NOT NULL,
    project_name TEXT NOT NULL,
    team TEXT NOT NULL,
    cost_center TEXT,
    parameters JSONB NOT NULL,                     -- user-specified overrides to template defaults
    estimated_monthly_cost DECIMAL(10,2),
    status TEXT NOT NULL CHECK (status IN (
        'submitted',                -- initial request received
        'validating',               -- policy engine evaluating
        'pending_approval',         -- paused, waiting for approver
        'approved',                 -- approval received, queued for execution
        'provisioning',             -- Terraform apply running
        'configuring',              -- Ansible hardening running
        'validating_compliance',    -- post-provisioning compliance scan
        'active',                   -- environment ready for use
        'decommissioning',          -- teardown in progress
        'decommissioned',           -- fully cleaned up
        'failed',                   -- error during provisioning
        'rejected'                  -- approver denied request
    )) DEFAULT 'submitted',
    policy_result JSONB,                           -- OPA evaluation output
    terraform_plan_output TEXT,                     -- full plan output for approval diff view
    terraform_plan_summary JSONB,                  -- structured summary: resources to create/modify/destroy
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    approval_comment TEXT,
    rejection_reason TEXT,
    temporal_workflow_id TEXT,                      -- Temporal execution reference
    failure_reason TEXT,                            -- error details if failed
    failure_step TEXT,                              -- which workflow step failed
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Example parameters JSONB (user overrides):
-- {
--   "instance_type": "c5.xlarge",
--   "volume_size_gb": 500,
--   "rds_enabled": true,
--   "rds_instance_class": "db.r5.large",
--   "multi_az": true,
--   "tags": {
--     "project": "payment-gateway-v2",
--     "team": "platform",
--     "cost_center": "ENG-2024-Q1"
--   }
-- }

-- Example policy_result JSONB:
-- {
--   "decision": "allow",
--   "policies_evaluated": 14,
--   "policies_passed": 14,
--   "policies_failed": 0,
--   "details": [
--     {"policy": "nist_ac_2", "result": "pass", "message": "Access control requirements met"},
--     {"policy": "budget_check", "result": "pass", "message": "Within team budget ($420/mo of $5000/mo remaining)"},
--     {"policy": "naming_standard", "result": "pass", "message": "Project name follows convention"}
--   ],
--   "requires_approval": true,
--   "approval_reason": "production_access"
-- }

-- Example terraform_plan_summary JSONB:
-- {
--   "resources_to_create": 12,
--   "resources_to_modify": 0,
--   "resources_to_destroy": 0,
--   "cost_delta_monthly": 420.00,
--   "resources": [
--     {"type": "aws_instance", "name": "web-server", "action": "create"},
--     {"type": "aws_security_group", "name": "web-sg", "action": "create"},
--     {"type": "aws_db_instance", "name": "app-db", "action": "create"}
--   ]
-- }
```

### 2.5 Resources (CMDB)

```sql
CREATE TABLE resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    request_id UUID REFERENCES provisioning_requests(id),
    cloud_resource_id TEXT NOT NULL,                -- AWS ARN or Azure resource ID
    resource_type TEXT NOT NULL,                    -- 'ec2_instance', 'rds_instance', 'security_group', etc.
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    availability_zone TEXT,
    environment TEXT NOT NULL CHECK (environment IN ('dev', 'staging', 'production')),
    team TEXT NOT NULL,
    project TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'provisioning', 'active', 'degraded', 'maintenance', 'decommissioning', 'terminated'
    )) DEFAULT 'provisioning',
    configuration JSONB NOT NULL,                  -- current config snapshot
    desired_configuration JSONB,                   -- expected config (for drift detection)
    tags JSONB NOT NULL,
    monthly_cost DECIMAL(10,2),
    last_compliance_scan TIMESTAMPTZ,
    compliance_status TEXT CHECK (compliance_status IN ('compliant', 'non_compliant', 'unknown'))
        DEFAULT 'unknown',
    last_health_check TIMESTAMPTZ,
    health_status TEXT CHECK (health_status IN ('healthy', 'degraded', 'unreachable', 'unknown'))
        DEFAULT 'unknown',
    provisioned_at TIMESTAMPTZ,
    decommissioned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Example configuration JSONB (EC2):
-- {
--   "instance_type": "c5.xlarge",
--   "ami_id": "ami-0abcdef1234567890",
--   "vpc_id": "vpc-12345",
--   "subnet_id": "subnet-67890",
--   "security_groups": ["sg-web-prod", "sg-monitoring"],
--   "iam_role": "arn:aws:iam::123456789012:role/web-server-role",
--   "root_volume_gb": 100,
--   "monitoring": {
--     "datadog_agent": "7.45.0",
--     "cloudwatch_detailed": true
--   },
--   "ssh_key": "platform-prod-2025"
-- }

-- Example desired_configuration JSONB (for drift detection):
-- Same structure as configuration. If current != desired, drift is flagged.
```

### 2.6 Resource Dependencies

```sql
CREATE TABLE resource_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id UUID REFERENCES resources(id) ON DELETE CASCADE NOT NULL,
    depends_on_id UUID REFERENCES resources(id) ON DELETE CASCADE NOT NULL,
    dependency_type TEXT NOT NULL CHECK (dependency_type IN (
        'network',     -- resource communicates over network with dependency
        'data',        -- resource reads/writes data to dependency
        'service',     -- resource calls API of dependency
        'auth',        -- resource authenticates via dependency
        'storage'      -- resource stores data in dependency
    )),
    description TEXT,                              -- human-readable dependency note
    is_critical BOOLEAN DEFAULT true,              -- if dependency fails, does this resource fail?
    UNIQUE(resource_id, depends_on_id)
);
```

### 2.7 Deployments

```sql
CREATE TABLE deployments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    initiated_by UUID REFERENCES users(id) NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('terraform', 'ansible', 'config_update')),
    change_description TEXT NOT NULL,
    change_diff TEXT,                              -- git diff of the change
    target_resources JSONB NOT NULL,               -- list of resource IDs affected
    status TEXT NOT NULL CHECK (status IN (
        'submitted',
        'simulating',              -- digital twin running tests
        'simulation_passed',
        'simulation_failed',
        'rolling_out',             -- progressive deployment in progress
        'paused_for_approval',     -- waiting for manual gate at 50%
        'completed',
        'rolled_back',
        'failed'
    )) DEFAULT 'submitted',
    current_stage TEXT CHECK (current_stage IN (
        'simulation', '1_pct', '10_pct', '50_pct', '100_pct', 'complete'
    )),
    simulation_results JSONB,                      -- test suite pass/fail details
    rollout_kpis JSONB,                            -- metrics captured at each stage
    rollback_state JSONB,                          -- snapshot for automated rollback
    approved_by UUID REFERENCES users(id),         -- who approved the 50% gate
    approval_comment TEXT,
    temporal_workflow_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Example simulation_results JSONB:
-- {
--   "duration_seconds": 342,
--   "suites": {
--     "integration": {"total": 24, "passed": 24, "failed": 0},
--     "performance": {"total": 8, "passed": 7, "failed": 1, "failures": [
--       {"test": "peak_load_500rps", "expected": "<200ms p99", "actual": "312ms p99"}
--     ]},
--     "chaos": {"total": 6, "passed": 6, "failed": 0},
--     "regression": {"total": 42, "passed": 42, "failed": 0}
--   },
--   "verdict": "fail",
--   "blocking_failures": ["performance.peak_load_500rps"]
-- }

-- Example rollout_kpis JSONB:
-- {
--   "1_pct": {
--     "started_at": "2025-02-15T10:00:00Z",
--     "completed_at": "2025-02-15T10:15:00Z",
--     "error_rate": 0.003,
--     "p99_latency_ms": 145,
--     "cpu_avg": 0.42,
--     "health_checks_passing": true,
--     "verdict": "pass"
--   },
--   "10_pct": {
--     "started_at": "2025-02-15T10:15:00Z",
--     "completed_at": "2025-02-15T10:45:00Z",
--     "error_rate": 0.005,
--     "p99_latency_ms": 168,
--     "cpu_avg": 0.51,
--     "health_checks_passing": true,
--     "verdict": "pass"
--   }
-- }
```

### 2.8 Incidents

```sql
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    correlated_alert_ids JSONB NOT NULL,            -- raw alert IDs grouped into this incident
    alert_count INTEGER NOT NULL,                   -- how many raw alerts were correlated
    classification TEXT NOT NULL CHECK (classification IN (
        'service_health', 'storage', 'network', 'database',
        'security', 'deployment', 'cost'
    )),
    subtype TEXT,                                   -- 'process_crash', 'disk_full', 'ssl_expiry', etc.
    severity TEXT NOT NULL CHECK (severity IN ('p1', 'p2', 'p3')),
    title TEXT NOT NULL,                            -- auto-generated summary
    description TEXT,                               -- detailed incident context
    status TEXT NOT NULL CHECK (status IN (
        'detected',        -- alert received and correlated
        'classified',      -- ML model assigned type + severity
        'remediating',     -- auto-remediation or human working
        'resolved',        -- fixed, verified by health check
        'escalated'        -- routed to human or higher tier
    )) DEFAULT 'detected',
    root_cause_resource_id UUID REFERENCES resources(id),
    affected_resources JSONB,                      -- all resources impacted (cascading)
    classification_confidence FLOAT NOT NULL CHECK (
        classification_confidence >= 0 AND classification_confidence <= 1
    ),
    model_version TEXT NOT NULL,                   -- 'rf_v3.2_spacy_v2.1'
    playbook_id UUID REFERENCES playbooks(id),
    playbook_execution_log JSONB,                  -- step-by-step execution record
    resolution_type TEXT CHECK (resolution_type IN ('auto', 'human', 'escalated')),
    resolution_summary TEXT,
    mttr_seconds INTEGER,                          -- detection to resolution
    assigned_to UUID REFERENCES users(id),
    pagerduty_incident_id TEXT,                    -- external reference
    slack_channel_id TEXT,                          -- incident channel if created
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- Example playbook_execution_log JSONB:
-- {
--   "playbook": "service_restart",
--   "started_at": "2025-02-15T14:22:03Z",
--   "steps": [
--     {"step": "precondition_check", "name": "service_exists", "result": "pass", "duration_ms": 120},
--     {"step": "precondition_check", "name": "restart_count_below_threshold", "result": "pass", "duration_ms": 85},
--     {"step": "action", "name": "restart_service", "result": "success", "duration_ms": 4200},
--     {"step": "post_check", "name": "health_check_passing", "result": "pass", "duration_ms": 31000},
--     {"step": "post_check", "name": "error_rate_below_threshold", "result": "pass", "duration_ms": 300500}
--   ],
--   "completed_at": "2025-02-15T14:27:39Z",
--   "total_duration_seconds": 336,
--   "verdict": "resolved"
-- }

-- Example affected_resources JSONB:
-- [
--   {"resource_id": "uuid-1", "name": "payment-api", "impact": "primary", "status": "down"},
--   {"resource_id": "uuid-2", "name": "checkout-service", "impact": "cascading", "status": "degraded"},
--   {"resource_id": "uuid-3", "name": "order-processor", "impact": "cascading", "status": "degraded"}
-- ]
```

### 2.9 Raw Alerts

```sql
CREATE TABLE raw_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    incident_id UUID REFERENCES incidents(id),      -- null until correlated
    source TEXT NOT NULL CHECK (source IN (
        'datadog', 'splunk', 'cloudwatch', 'prometheus', 'pagerduty', 'custom'
    )),
    external_alert_id TEXT,                         -- ID from source system
    severity_raw TEXT,                              -- original severity from source
    message TEXT NOT NULL,
    affected_resource_id UUID REFERENCES resources(id),
    affected_resource_name TEXT,                    -- fallback if resource not in CMDB
    metadata JSONB,                                -- source-specific fields
    is_duplicate BOOLEAN DEFAULT false,
    received_at TIMESTAMPTZ DEFAULT now()
);
```

### 2.10 Remediation Playbooks

```sql
CREATE TABLE playbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    trigger_rules JSONB NOT NULL,                  -- incident classification + subtype + confidence threshold
    preconditions JSONB NOT NULL,                   -- checks before executing
    actions JSONB NOT NULL,                         -- ordered list of remediation steps
    post_checks JSONB NOT NULL,                     -- validation after execution
    rollback_actions JSONB NOT NULL,                -- undo if post-checks fail
    is_active BOOLEAN DEFAULT true,
    auto_resolution_rate FLOAT,                    -- historical success rate
    avg_execution_seconds INTEGER,                  -- historical average
    version INTEGER DEFAULT 1,
    git_sha TEXT,                                   -- source control reference
    last_updated_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Example trigger_rules JSONB:
-- {
--   "incident_type": "service_health",
--   "subtypes": ["process_crash", "health_check_failure"],
--   "confidence_min": 0.95,
--   "severity": ["p2", "p3"],
--   "exclude_resources": ["payment-gateway-prod"]
-- }
```

### 2.11 Compliance Policies

```sql
CREATE TABLE compliance_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    framework TEXT NOT NULL,                        -- 'nist_800_53', 'fedramp_moderate', 'soc2', 'custom'
    control_id TEXT NOT NULL,                       -- 'AC-2', 'SC-7', 'CC6.1'
    control_name TEXT NOT NULL,                     -- human-readable name
    rego_policy TEXT NOT NULL,                      -- OPA Rego source code
    resource_types TEXT[] NOT NULL,                 -- which resource types this applies to
    severity TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    remediation_guidance TEXT,                      -- what to do if check fails
    auto_remediate BOOLEAN DEFAULT false,           -- should drift trigger auto-fix?
    is_active BOOLEAN DEFAULT true,
    version INTEGER DEFAULT 1,
    git_sha TEXT,
    approved_by UUID REFERENCES users(id),          -- compliance officer sign-off
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(org_id, framework, control_id, version)
);
```

### 2.12 Compliance Scans

```sql
CREATE TABLE compliance_scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    resource_id UUID REFERENCES resources(id) NOT NULL,
    policy_id UUID REFERENCES compliance_policies(id) NOT NULL,
    framework TEXT NOT NULL,
    control_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pass', 'fail', 'error', 'not_applicable')),
    details JSONB,                                 -- specific findings
    current_value TEXT,                             -- what the resource has
    expected_value TEXT,                            -- what the policy requires
    is_drift BOOLEAN DEFAULT false,                -- detected via drift check vs. scheduled scan
    remediated_automatically BOOLEAN DEFAULT false,
    policy_version INTEGER NOT NULL,
    scanned_at TIMESTAMPTZ DEFAULT now()
);

-- Example details JSONB:
-- {
--   "finding": "Security group sg-web-prod allows ingress on port 22 from 0.0.0.0/0",
--   "control": "SC-7: Boundary Protection",
--   "expected": "SSH access restricted to VPN CIDR (10.0.4.0/24)",
--   "actual": "SSH access open to 0.0.0.0/0",
--   "risk": "Unrestricted SSH access exposes the instance to brute-force attacks"
-- }
```

### 2.13 Audit Log

```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organizations(id) NOT NULL,
    actor_id UUID NOT NULL,                        -- user or system service account
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'system', 'temporal_workflow')),
    action TEXT NOT NULL,                           -- 'provisioning_request.created', 'deployment.rolled_back', etc.
    resource_type TEXT NOT NULL,                    -- 'provisioning_request', 'resource', 'incident', 'compliance_scan'
    resource_id UUID,
    details JSONB NOT NULL,                         -- action-specific payload
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- CRITICAL: append-only, no updates or deletes
REVOKE UPDATE, DELETE ON audit_log FROM app_user;
REVOKE UPDATE, DELETE ON audit_log FROM app_service;

-- Example actions:
-- 'provisioning_request.submitted'
-- 'provisioning_request.approved'
-- 'provisioning_request.rejected'
-- 'resource.provisioned'
-- 'resource.decommissioned'
-- 'deployment.simulation_started'
-- 'deployment.rolled_back'
-- 'incident.detected'
-- 'incident.auto_remediated'
-- 'compliance_scan.drift_detected'
-- 'compliance_scan.auto_remediated'
-- 'policy.updated'
-- 'playbook.executed'
```

---

## 3. TimescaleDB Schema (Metrics)

Separate TimescaleDB instance for high-cardinality time-series data. PostgreSQL is not suited for the write volume and query patterns of infrastructure metrics.

```sql
-- Hypertable for infrastructure metrics
CREATE TABLE metrics (
    time TIMESTAMPTZ NOT NULL,
    resource_id UUID NOT NULL,
    metric_name TEXT NOT NULL,              -- 'cpu_utilization', 'memory_pct', 'disk_io_read_bytes'
    value DOUBLE PRECISION NOT NULL,
    tags JSONB                              -- {'environment': 'prod', 'team': 'platform'}
);

SELECT create_hypertable('metrics', 'time');

-- Continuous aggregates for dashboard queries
CREATE MATERIALIZED VIEW metrics_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    resource_id,
    metric_name,
    avg(value) AS avg_value,
    min(value) AS min_value,
    max(value) AS max_value,
    count(*) AS sample_count
FROM metrics
GROUP BY bucket, resource_id, metric_name;

CREATE MATERIALIZED VIEW metrics_1hr
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    resource_id,
    metric_name,
    avg(value) AS avg_value,
    min(value) AS min_value,
    max(value) AS max_value,
    percentile_agg(value) AS pct_agg       -- for p50, p95, p99 queries
FROM metrics
GROUP BY bucket, resource_id, metric_name;

-- Compression policy: compress chunks older than 24 hours (90%+ compression ratio)
ALTER TABLE metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'resource_id, metric_name',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('metrics', INTERVAL '24 hours');

-- Retention policy: drop raw data after 90 days, keep aggregates for 2 years
SELECT add_retention_policy('metrics', INTERVAL '90 days');

-- Anomaly baselines table
CREATE TABLE anomaly_baselines (
    resource_id UUID NOT NULL,
    metric_name TEXT NOT NULL,
    hour_of_day INTEGER NOT NULL,           -- 0-23, for time-of-day seasonality
    day_of_week INTEGER NOT NULL,           -- 0-6, for day-of-week seasonality
    mean DOUBLE PRECISION NOT NULL,
    stddev DOUBLE PRECISION NOT NULL,
    iqr_lower DOUBLE PRECISION NOT NULL,
    iqr_upper DOUBLE PRECISION NOT NULL,
    sample_count INTEGER NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (resource_id, metric_name, hour_of_day, day_of_week)
);
```

---

## 4. Indexes

### 4.1 Primary Indexes

```sql
-- CMDB lookups
CREATE INDEX idx_resources_org ON resources (org_id);
CREATE INDEX idx_resources_type ON resources (resource_type);
CREATE INDEX idx_resources_env ON resources (environment);
CREATE INDEX idx_resources_team ON resources (team);
CREATE INDEX idx_resources_cloud_id ON resources (cloud_resource_id);

-- Dependency graph traversal
CREATE INDEX idx_deps_resource ON resource_dependencies (resource_id);
CREATE INDEX idx_deps_depends_on ON resource_dependencies (depends_on_id);

-- Provisioning tracking
CREATE INDEX idx_requests_org_status ON provisioning_requests (org_id, status);
CREATE INDEX idx_requests_requested_by ON provisioning_requests (requested_by, created_at DESC);
CREATE INDEX idx_requests_team ON provisioning_requests (team, created_at DESC);

-- Incident queries
CREATE INDEX idx_incidents_org_status ON incidents (org_id, status);
CREATE INDEX idx_incidents_severity ON incidents (severity, created_at DESC);
CREATE INDEX idx_incidents_root_cause ON incidents (root_cause_resource_id);
CREATE INDEX idx_incidents_classification ON incidents (classification, created_at DESC);

-- Deployment tracking
CREATE INDEX idx_deployments_org_status ON deployments (org_id, status);
CREATE INDEX idx_deployments_initiated_by ON deployments (initiated_by, created_at DESC);

-- Compliance
CREATE INDEX idx_scans_resource ON compliance_scans (resource_id, scanned_at DESC);
CREATE INDEX idx_scans_framework ON compliance_scans (framework, control_id, status);

-- Alerts
CREATE INDEX idx_alerts_org ON raw_alerts (org_id, received_at DESC);
CREATE INDEX idx_alerts_incident ON raw_alerts (incident_id);
CREATE INDEX idx_alerts_resource ON raw_alerts (affected_resource_id, received_at DESC);

-- Audit
CREATE INDEX idx_audit_resource ON audit_log (resource_type, resource_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_log (actor_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_log (action, created_at DESC);
```

### 4.2 Partial Indexes (hot paths)

```sql
-- Only active resources (skip terminated)
CREATE INDEX idx_resources_active ON resources (org_id, environment)
    WHERE status = 'active';

-- Only non-compliant resources (compliance dashboard)
CREATE INDEX idx_resources_noncompliant ON resources (org_id)
    WHERE compliance_status = 'non_compliant';

-- Only open incidents (ops dashboard)
CREATE INDEX idx_incidents_open ON incidents (org_id, severity)
    WHERE status NOT IN ('resolved');

-- Only pending provisioning requests (approval queue)
CREATE INDEX idx_requests_pending ON provisioning_requests (org_id)
    WHERE status = 'pending_approval';

-- Only failed compliance scans (compliance dashboard)
CREATE INDEX idx_scans_failures ON compliance_scans (org_id, framework)
    WHERE status = 'fail';

-- Only active deployments (rollout dashboard)
CREATE INDEX idx_deployments_active ON deployments (org_id)
    WHERE status IN ('simulating', 'rolling_out', 'paused_for_approval');

-- Uncorrelated alerts (correlation engine inbox)
CREATE INDEX idx_alerts_uncorrelated ON raw_alerts (org_id, received_at DESC)
    WHERE incident_id IS NULL AND is_duplicate = false;
```

### 4.3 JSONB Indexes

```sql
-- Search resources by tag
CREATE INDEX idx_resources_tags ON resources USING gin (tags);

-- Search incidents by affected resources
CREATE INDEX idx_incidents_affected ON incidents USING gin (affected_resources);

-- Search deployments by target resources
CREATE INDEX idx_deployments_targets ON deployments USING gin (target_resources);
```

---

## 5. Row-Level Security

Every table with org data has RLS enabled. The API layer sets session variables on each database connection.

```sql
-- Enable RLS
ALTER TABLE provisioning_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE resource_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE playbooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Organization isolation: users only see their org's data
CREATE POLICY org_isolation ON resources
    FOR ALL
    USING (org_id = current_setting('app.current_org')::UUID);

CREATE POLICY org_isolation ON provisioning_requests
    FOR ALL
    USING (org_id = current_setting('app.current_org')::UUID);

CREATE POLICY org_isolation ON incidents
    FOR ALL
    USING (org_id = current_setting('app.current_org')::UUID);

-- Role-based access within org
-- Developers: see their own requests + resources tagged to their team
-- Platform engineers: see all resources and deployments
-- Compliance: see all compliance scans and policies, read-only on infrastructure
-- Admins: full access within org

CREATE POLICY developer_requests ON provisioning_requests
    FOR SELECT
    USING (
        current_setting('app.user_role') IN ('platform_eng', 'admin')
        OR requested_by = current_setting('app.user_id')::UUID
    );

CREATE POLICY developer_resources ON resources
    FOR SELECT
    USING (
        current_setting('app.user_role') IN ('platform_eng', 'admin')
        OR team = current_setting('app.user_team')
    );

-- Audit log: read-only for compliance and admins, write by system only
CREATE POLICY audit_read ON audit_log
    FOR SELECT
    USING (
        org_id = current_setting('app.current_org')::UUID
        AND current_setting('app.user_role') IN ('compliance', 'admin')
    );

-- Compliance policies: compliance officers can modify, others read-only
CREATE POLICY policy_write ON compliance_policies
    FOR ALL
    USING (
        org_id = current_setting('app.current_org')::UUID
        AND current_setting('app.user_role') IN ('compliance', 'admin')
    );
```

**API middleware sets session variables on every request:**

```python
async def set_rls_context(db_conn, user):
    await db_conn.execute(f"SET app.current_org = '{user.org_id}'")
    await db_conn.execute(f"SET app.user_id = '{user.id}'")
    await db_conn.execute(f"SET app.user_role = '{user.role}'")
    await db_conn.execute(f"SET app.user_team = '{user.team}'")
```

---

## 6. Common Query Patterns

### 6.1 Infrastructure health dashboard

```sql
SELECT
    r.environment,
    COUNT(*) AS total_resources,
    COUNT(*) FILTER (WHERE r.health_status = 'healthy') AS healthy,
    COUNT(*) FILTER (WHERE r.health_status = 'degraded') AS degraded,
    COUNT(*) FILTER (WHERE r.health_status = 'unreachable') AS unreachable,
    COUNT(*) FILTER (WHERE r.compliance_status = 'non_compliant') AS non_compliant,
    SUM(r.monthly_cost) AS total_monthly_cost
FROM resources r
WHERE r.org_id = $1
    AND r.status = 'active'
GROUP BY r.environment
ORDER BY
    CASE r.environment
        WHEN 'production' THEN 1
        WHEN 'staging' THEN 2
        WHEN 'dev' THEN 3
    END;
```

### 6.2 Incident trends (MTTR by week)

```sql
SELECT
    date_trunc('week', i.created_at) AS week,
    COUNT(*) AS incident_count,
    COUNT(*) FILTER (WHERE i.resolution_type = 'auto') AS auto_resolved,
    COUNT(*) FILTER (WHERE i.resolution_type = 'human') AS human_resolved,
    ROUND(AVG(i.mttr_seconds) / 60.0, 1) AS avg_mttr_minutes,
    ROUND(
        COUNT(*) FILTER (WHERE i.resolution_type = 'auto')::numeric /
        NULLIF(COUNT(*), 0) * 100, 1
    ) AS auto_resolution_pct
FROM incidents i
WHERE i.org_id = $1
    AND i.status = 'resolved'
    AND i.created_at >= now() - INTERVAL '12 weeks'
GROUP BY week
ORDER BY week DESC;
```

### 6.3 Dependency graph for root cause analysis

```sql
-- Find all resources that depend on a failing resource (cascade impact)
WITH RECURSIVE dependency_chain AS (
    -- Start from the failing resource
    SELECT
        rd.resource_id AS affected_id,
        rd.depends_on_id AS root_id,
        rd.dependency_type,
        rd.is_critical,
        1 AS depth
    FROM resource_dependencies rd
    WHERE rd.depends_on_id = $1  -- $1 = failing resource ID

    UNION ALL

    -- Walk up the dependency tree
    SELECT
        rd.resource_id AS affected_id,
        dc.root_id,
        rd.dependency_type,
        rd.is_critical,
        dc.depth + 1
    FROM resource_dependencies rd
    JOIN dependency_chain dc ON rd.depends_on_id = dc.affected_id
    WHERE dc.depth < 5  -- max traversal depth to prevent cycles
)
SELECT
    r.id,
    r.name,
    r.resource_type,
    r.environment,
    r.status,
    dc.dependency_type,
    dc.is_critical,
    dc.depth
FROM dependency_chain dc
JOIN resources r ON r.id = dc.affected_id
ORDER BY dc.is_critical DESC, dc.depth ASC;
```

### 6.4 Compliance posture by framework

```sql
SELECT
    cs.framework,
    COUNT(DISTINCT cs.control_id) AS total_controls,
    COUNT(DISTINCT cs.control_id) FILTER (WHERE cs.status = 'pass') AS passing,
    COUNT(DISTINCT cs.control_id) FILTER (WHERE cs.status = 'fail') AS failing,
    ROUND(
        COUNT(DISTINCT cs.control_id) FILTER (WHERE cs.status = 'pass')::numeric /
        NULLIF(COUNT(DISTINCT cs.control_id), 0) * 100, 1
    ) AS compliance_pct,
    COUNT(*) FILTER (WHERE cs.is_drift = true AND cs.status = 'fail') AS drift_violations
FROM compliance_scans cs
JOIN (
    -- Get latest scan per resource per control
    SELECT DISTINCT ON (resource_id, framework, control_id)
        id
    FROM compliance_scans
    WHERE org_id = $1
    ORDER BY resource_id, framework, control_id, scanned_at DESC
) latest ON latest.id = cs.id
GROUP BY cs.framework
ORDER BY compliance_pct ASC;
```

### 6.5 Cost breakdown by team and environment

```sql
SELECT
    r.team,
    r.environment,
    COUNT(*) AS resource_count,
    SUM(r.monthly_cost) AS monthly_cost,
    ROUND(
        SUM(r.monthly_cost) /
        NULLIF(SUM(SUM(r.monthly_cost)) OVER (), 0) * 100, 1
    ) AS pct_of_total
FROM resources r
WHERE r.org_id = $1
    AND r.status = 'active'
GROUP BY r.team, r.environment
ORDER BY monthly_cost DESC;
```

### 6.6 Anomaly detection query (TimescaleDB)

```sql
-- Find metrics currently exceeding anomaly thresholds
SELECT
    m.resource_id,
    r.name AS resource_name,
    m.metric_name,
    m.avg_value AS current_value,
    ab.mean AS baseline_mean,
    ab.stddev AS baseline_stddev,
    (m.avg_value - ab.mean) / NULLIF(ab.stddev, 0) AS z_score
FROM metrics_1min m
JOIN resources r ON r.id = m.resource_id
JOIN anomaly_baselines ab ON
    ab.resource_id = m.resource_id
    AND ab.metric_name = m.metric_name
    AND ab.hour_of_day = EXTRACT(HOUR FROM now())::integer
    AND ab.day_of_week = EXTRACT(DOW FROM now())::integer
WHERE m.bucket >= now() - INTERVAL '5 minutes'
    AND ABS((m.avg_value - ab.mean) / NULLIF(ab.stddev, 0)) > 3  -- z-score > 3
ORDER BY z_score DESC;
```

---

## 7. Data Lifecycle

### 7.1 State Machines

**Provisioning Request:**

```
                    ┌──────────┐
                    │ submitted│
                    └────┬─────┘
                         │
                         ▼
                    ┌──────────┐
                    │validating│
                    └────┬─────┘
                         │
                   ┌─────┴──────┐
                   ▼            ▼
            ┌──────────┐  ┌──────────────┐
            │ rejected │  │pending_      │
            └──────────┘  │approval      │
                          └──────┬───────┘
                                 │
                           ┌─────┴─────┐
                           ▼           ▼
                     ┌──────────┐ ┌──────────┐
                     │ rejected │ │ approved │
                     └──────────┘ └────┬─────┘
                                       │
                                       ▼
                                 ┌──────────────┐
                                 │ provisioning │
                                 └──────┬───────┘
                                        │
                                  ┌─────┴─────┐
                                  ▼           ▼
                           ┌──────────┐ ┌──────────────┐
                           │  failed  │ │ configuring  │
                           └──────────┘ └──────┬───────┘
                                               │
                                               ▼
                                    ┌──────────────────────┐
                                    │validating_compliance │
                                    └──────────┬───────────┘
                                               │
                                         ┌─────┴─────┐
                                         ▼           ▼
                                  ┌──────────┐  ┌────────┐
                                  │  failed  │  │ active │
                                  └──────────┘  └───┬────┘
                                                    │
                                                    ▼
                                           ┌──────────────────┐
                                           │ decommissioning  │
                                           └────────┬─────────┘
                                                    │
                                                    ▼
                                           ┌──────────────────┐
                                           │ decommissioned   │
                                           └──────────────────┘
```

**Resource Health:**

```
                    ┌──────────────┐
                    │ provisioning │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────┐     health check fails
                    │  active  │ ─────────────────────────> ┌──────────┐
                    └────┬─────┘                            │ degraded │
                         │          health check recovers   └────┬─────┘
                         │ <────────────────────────────────────┘
                         │
                         │ maintenance window
                         ▼
                    ┌─────────────┐
                    │ maintenance │
                    └──────┬──────┘
                           │ maintenance complete
                           ▼
                    ┌──────────┐
                    │  active  │
                    └──────────┘
```

### 7.2 Retention Policy

| Data Type | Hot Storage | Cold Storage | Total Retention | Reason |
|---|---|---|---|---|
| Active resources | PostgreSQL | N/A | Until decommissioned | Operational data |
| Terminated resources | PostgreSQL (90 days) | S3 archive | 7 years | Audit trail |
| Incidents (resolved) | PostgreSQL (1 year) | S3 archive | 7 years | Trend analysis + compliance |
| Raw alerts | PostgreSQL (30 days) | None | 30 days | Only needed for correlation window |
| Metrics (raw) | TimescaleDB (90 days) | None (aggregates retained) | 90 days raw | High volume, aggregates sufficient |
| Metrics (1-min aggregates) | TimescaleDB | N/A | 1 year | Dashboard queries |
| Metrics (1-hr aggregates) | TimescaleDB | N/A | 2 years | Long-term trend analysis |
| Compliance scans | PostgreSQL (1 year) | S3 archive | 7 years | Audit evidence |
| Audit logs | PostgreSQL (1 year) | S3 Glacier | 7 years | Regulatory requirement |
| Terraform state | S3 (versioned) | N/A | Indefinite | Infrastructure recovery |
| Simulation snapshots | S3 | None | 30 days | Debugging only |

### 7.3 Deletion Cascade

```
Resource decommissioned:
  ├── Resource record: status = 'terminated', soft delete
  ├── Dependencies: hard delete (relationship no longer valid)
  ├── Compliance scans: retained (audit evidence)
  ├── Incidents: retained (root_cause_resource_id preserved)
  └── Audit log: NEVER deleted

Organization offboarded:
  ├── All resources: soft delete
  ├── All requests: soft delete
  ├── All deployments: soft delete
  ├── All incidents: soft delete
  ├── Compliance data: archived to S3, purged from PostgreSQL after export confirmed
  ├── Metrics: dropped from TimescaleDB
  ├── Vault secrets: revoked and purged
  └── Audit log: archived to S3 Glacier, NEVER purged
```

---

## 8. Migration Strategy

### 8.1 Migration Files

```
migrations/
├── 001_create_organizations.sql
├── 002_create_users.sql
├── 003_create_environment_templates.sql
├── 004_create_provisioning_requests.sql
├── 005_create_resources.sql
├── 006_create_resource_dependencies.sql
├── 007_create_deployments.sql
├── 008_create_playbooks.sql
├── 009_create_incidents.sql
├── 010_create_raw_alerts.sql
├── 011_create_compliance_policies.sql
├── 012_create_compliance_scans.sql
├── 013_create_audit_log.sql
├── 014_enable_rls.sql
├── 015_create_indexes.sql
├── 016_create_partial_indexes.sql
├── 017_seed_environment_templates.sql
├── 018_seed_compliance_policies.sql
└── 019_timescaledb_setup.sql
```

### 8.2 Backfill Procedures

When adding new compliance controls or updating scan logic:

```sql
-- Backfill compliance scans for new policy
-- Run as background job during low-traffic window
INSERT INTO compliance_scans (
    org_id, resource_id, policy_id, framework, control_id,
    status, details, policy_version, scanned_at
)
SELECT
    r.org_id,
    r.id,
    $1,                    -- new policy ID
    $2,                    -- framework
    $3,                    -- control_id
    evaluate_policy(r.configuration, $4),  -- app-level OPA evaluation
    NULL,                  -- details populated by evaluation function
    1,                     -- policy version
    now()
FROM resources r
WHERE r.status = 'active'
    AND r.resource_type = ANY($5)          -- applicable resource types
ORDER BY r.environment DESC                -- production first
LIMIT 500;                                 -- batch processing
```

When retraining incident classification model:

```sql
-- Export training data for ML pipeline
COPY (
    SELECT
        i.classification,
        i.subtype,
        i.severity,
        i.title,
        i.description,
        i.resolution_type,
        i.mttr_seconds,
        i.classification_confidence,
        json_agg(json_build_object(
            'source', ra.source,
            'message', ra.message,
            'severity_raw', ra.severity_raw
        )) AS raw_alerts
    FROM incidents i
    JOIN raw_alerts ra ON ra.incident_id = i.id
    WHERE i.status = 'resolved'
        AND i.resolved_at >= now() - INTERVAL '6 months'
    GROUP BY i.id
) TO '/tmp/incident_training_data.csv' WITH CSV HEADER;
```
