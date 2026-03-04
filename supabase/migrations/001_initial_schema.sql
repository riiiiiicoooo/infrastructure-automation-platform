-- Infrastructure Automation Platform - Initial Schema
-- This schema supports provisioning workflows, incident response, policy evaluation, and observability

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "timescaledb";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- =====================================================================
-- INFRASTRUCTURE RESOURCES
-- =====================================================================

CREATE TABLE environments (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name text NOT NULL,
  project_id uuid NOT NULL,
  owner_id uuid NOT NULL,
  environment_type text NOT NULL CHECK (environment_type IN ('dev', 'staging', 'production')),

  -- Status tracking
  status text NOT NULL CHECK (status IN ('requested', 'provisioning', 'active', 'degraded', 'decommissioning', 'terminated')) DEFAULT 'requested',
  provisioned_at timestamp with time zone,
  decommissioned_at timestamp with time zone,

  -- Cost tracking (monthly estimate)
  monthly_cost_estimate float NOT NULL DEFAULT 0.0,
  actual_monthly_cost float DEFAULT 0.0,
  budget_limit float,

  -- TTL for temporary environments
  expires_at timestamp with time zone,
  auto_terminate boolean DEFAULT true,

  -- Metadata
  tags jsonb DEFAULT '{}'::jsonb,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),

  UNIQUE(project_id, name)
);

CREATE TABLE resources (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  environment_id uuid NOT NULL REFERENCES environments(id) ON DELETE CASCADE,

  -- Resource identification
  resource_type text NOT NULL,
  provider text NOT NULL CHECK (provider IN ('aws', 'azure', 'gcp')),
  provider_id text NOT NULL,

  -- Status and health
  status text NOT NULL CHECK (status IN ('creating', 'active', 'error', 'terminating')) DEFAULT 'active',
  health_status text CHECK (health_status IN ('healthy', 'degraded', 'unhealthy')),
  health_check_timestamp timestamp with time zone,

  -- Cost tracking
  hourly_cost float DEFAULT 0.0,
  monthly_cost_estimate float DEFAULT 0.0,

  -- Configuration snapshot
  configuration jsonb NOT NULL,
  tags jsonb DEFAULT '{}'::jsonb,

  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),

  UNIQUE(environment_id, provider, provider_id)
);

-- =====================================================================
-- PROVISIONING REQUESTS & APPROVALS
-- =====================================================================

CREATE TABLE provisioning_requests (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  environment_id uuid NOT NULL REFERENCES environments(id) ON DELETE CASCADE,

  -- Request metadata
  status text NOT NULL CHECK (status IN ('draft', 'submitted', 'validating', 'approved', 'rejected', 'executing', 'completed', 'failed', 'rolled_back')) DEFAULT 'draft',
  requester_id uuid NOT NULL,

  -- Request details
  infrastructure_spec jsonb NOT NULL,  -- Terraform variables
  estimated_cost float,
  estimated_duration_minutes integer,

  -- Policy evaluation
  policy_check_passed boolean,
  policy_violations jsonb DEFAULT '[]'::jsonb,

  -- Terraform state
  terraform_plan_id text,
  terraform_apply_id text,
  terraform_state_snapshot jsonb,

  -- Approval workflow
  approval_required boolean DEFAULT true,
  approver_id uuid,
  approval_timestamp timestamp with time zone,
  approval_comments text,

  -- Execution tracking
  execution_started_at timestamp with time zone,
  execution_completed_at timestamp with time zone,
  execution_error text,
  rollback_executed boolean DEFAULT false,

  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE approval_workflows (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  provisioning_request_id uuid NOT NULL REFERENCES provisioning_requests(id) ON DELETE CASCADE,

  -- Workflow stage
  stage text NOT NULL CHECK (stage IN ('budget_review', 'security_review', 'compliance_review', 'final_approval')),
  stage_status text NOT NULL CHECK (stage_status IN ('pending', 'approved', 'rejected', 'escalated')),

  -- Assignee and action
  assigned_to uuid NOT NULL,
  action_taken_by uuid,
  action_taken_at timestamp with time zone,
  decision text,

  -- Audit trail
  reason text,
  metadata jsonb DEFAULT '{}'::jsonb,

  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- =====================================================================
-- POLICY EVALUATION
-- =====================================================================

CREATE TABLE policy_definitions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),

  -- Policy metadata
  name text NOT NULL UNIQUE,
  description text,
  policy_type text NOT NULL CHECK (policy_type IN ('compliance', 'security', 'cost', 'performance')),

  -- OPA Rego policy
  rego_source text NOT NULL,
  version text NOT NULL DEFAULT '1.0',

  -- Control mapping (e.g., NIST 800-53, CIS, SOC 2)
  control_framework text,  -- 'NIST_800_53', 'CIS_AWS', 'SOC2'
  control_id text,

  -- Policy state
  enabled boolean DEFAULT true,
  enforced boolean DEFAULT true,  -- false = audit-only

  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE policy_evaluations (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  policy_id uuid NOT NULL REFERENCES policy_definitions(id) ON DELETE SET NULL,
  provisioning_request_id uuid REFERENCES provisioning_requests(id) ON DELETE CASCADE,

  -- Evaluation result
  passed boolean NOT NULL,
  violations jsonb DEFAULT '[]'::jsonb,

  -- Detailed findings
  evaluated_resource_ids jsonb DEFAULT '[]'::jsonb,
  evaluation_timestamp timestamp with time zone DEFAULT now(),

  -- Remediation
  remediation_required boolean,
  remediation_steps jsonb,

  created_at timestamp with time zone DEFAULT now()
);

-- =====================================================================
-- INCIDENT MANAGEMENT
-- =====================================================================

CREATE TABLE incidents (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),

  -- Identification
  incident_key text UNIQUE NOT NULL,
  title text NOT NULL,
  description text,

  -- Classification (ML-powered)
  incident_type text CHECK (incident_type IN ('performance', 'availability', 'security', 'cost', 'configuration', 'deployment', 'unknown')),
  severity text NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')) DEFAULT 'medium',
  confidence_score float CHECK (confidence_score >= 0 AND confidence_score <= 1),

  -- Affected resources
  affected_environments uuid[],
  affected_resource_ids uuid[],

  -- Status
  status text NOT NULL CHECK (status IN ('open', 'investigating', 'in_progress', 'resolved', 'closed', 'escalated')) DEFAULT 'open',
  opened_at timestamp with time zone DEFAULT now(),
  resolved_at timestamp with time zone,
  closed_at timestamp with time zone,

  -- Assignment
  assigned_to uuid,
  assigned_at timestamp with time zone,

  -- Resolution
  root_cause text,
  resolution_notes text,

  -- ML classification metadata
  ml_features jsonb,
  model_version text,

  -- Runbook linkage
  runbook_id uuid,
  auto_remediation_executed boolean DEFAULT false,

  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE incident_alerts (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,

  -- Alert correlation
  alert_source text NOT NULL,  -- 'grafana', 'pagerduty', 'datadog', etc
  alert_id text NOT NULL,
  correlated_alerts uuid[],

  -- Alert details
  alert_message text,
  alert_metric text,
  threshold_value float,
  observed_value float,

  -- Timing
  alert_fired_at timestamp with time zone NOT NULL,
  alert_resolved_at timestamp with time zone,

  created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE incident_escalations (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,

  escalation_level integer NOT NULL DEFAULT 1,
  escalated_to uuid NOT NULL,
  escalation_reason text,

  escalated_at timestamp with time zone DEFAULT now(),
  resolved_at timestamp with time zone
);

-- =====================================================================
-- RUNBOOKS & AUTO-REMEDIATION
-- =====================================================================

CREATE TABLE runbooks (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),

  -- Metadata
  name text NOT NULL UNIQUE,
  description text,
  incident_type text NOT NULL,

  -- Applicability
  severity_levels text[],
  affects_resource_types text[],

  -- Execution config
  steps jsonb NOT NULL,  -- Array of remediation steps
  rollback_steps jsonb,  -- Rollback procedures

  -- Safety constraints
  requires_approval boolean DEFAULT false,
  approval_threshold text CHECK (approval_threshold IN ('critical', 'high')),
  max_parallel_executions integer DEFAULT 10,
  requires_human_confirmation boolean DEFAULT false,

  -- Observability
  success_metrics jsonb,  -- Metric names to check after remediation
  verification_timeout_seconds integer DEFAULT 300,

  -- Version control
  version text DEFAULT '1.0',
  created_by uuid,

  enabled boolean DEFAULT true,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE runbook_executions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  runbook_id uuid NOT NULL REFERENCES runbooks(id) ON DELETE SET NULL,
  incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,

  -- Execution metadata
  execution_status text NOT NULL CHECK (execution_status IN ('pending', 'running', 'paused', 'completed', 'failed', 'rolled_back')) DEFAULT 'pending',

  -- Step tracking
  current_step_index integer DEFAULT 0,
  completed_steps jsonb,
  failed_step_index integer,
  failed_step_error text,

  -- Results
  success boolean,
  verified boolean DEFAULT false,
  verification_results jsonb,

  -- Timing
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  duration_seconds integer,

  -- Human-in-the-loop
  paused_for_approval boolean DEFAULT false,
  approval_requested_at timestamp with time zone,
  approval_granted_at timestamp with time zone,
  approved_by uuid,

  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- =====================================================================
-- SIMULATION & DIGITAL TWIN
-- =====================================================================

CREATE TABLE simulation_runs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  provisioning_request_id uuid REFERENCES provisioning_requests(id) ON DELETE SET NULL,

  -- Simulation metadata
  simulation_type text NOT NULL CHECK (simulation_type IN ('dry_run', 'chaos', 'load_test', 'canary_validation')),
  status text NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')) DEFAULT 'pending',

  -- Environment snapshot
  infrastructure_snapshot jsonb NOT NULL,
  baseline_metrics jsonb,

  -- Workload configuration
  synthetic_workload_config jsonb,
  duration_seconds integer,

  -- Results
  test_results jsonb,
  validation_passed boolean,
  issues_found jsonb DEFAULT '[]'::jsonb,

  -- Performance metrics
  cpu_peak_percent float,
  memory_peak_percent float,
  network_latency_ms float,
  error_rate_percent float,

  -- Container/resource tracking
  container_image_hash text,
  resource_cleanup_timestamp timestamp with time zone,

  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE canary_deployments (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  provisioning_request_id uuid NOT NULL REFERENCES provisioning_requests(id) ON DELETE CASCADE,

  -- Deployment stages
  status text NOT NULL CHECK (status IN ('planning', 'canary_1pct', 'canary_10pct', 'canary_50pct', 'full_rollout', 'completed', 'rolled_back')) DEFAULT 'planning',

  -- Traffic split
  current_canary_percentage integer DEFAULT 1,

  -- KPI monitoring
  success_metrics jsonb,
  kpi_baseline jsonb,
  kpi_current jsonb,
  anomaly_detected boolean DEFAULT false,

  -- Approval gates
  approval_required_at_50pct boolean DEFAULT true,
  approval_granted boolean,
  approved_by uuid,

  -- Timing
  started_at timestamp with time zone,
  stage_start_timestamp timestamp with time zone,
  completed_at timestamp with time zone,

  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- =====================================================================
-- METRICS & OBSERVABILITY
-- =====================================================================

CREATE TABLE metrics (
  time timestamptz NOT NULL,
  metric_name text NOT NULL,
  resource_id uuid,
  environment_id uuid,
  value float NOT NULL,

  -- Dimensional tagging
  dimensions jsonb,

  PRIMARY KEY (metric_name, time, resource_id)
) PARTITION BY RANGE (time);

-- Create partitions for metrics (monthly)
SELECT create_hypertable('metrics', 'time', if_not_exists => TRUE);

CREATE INDEX ON metrics (metric_name, environment_id, time DESC);
CREATE INDEX ON metrics (resource_id, time DESC);

CREATE TABLE anomaly_baselines (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  metric_name text NOT NULL,
  resource_id uuid,
  environment_id uuid,

  -- Baseline statistics
  mean_value float,
  stddev_value float,
  p95_value float,
  p99_value float,

  -- Adaptive baseline
  last_updated timestamp with time zone DEFAULT now(),
  calculation_window_days integer DEFAULT 30,

  UNIQUE(metric_name, resource_id)
);

CREATE TABLE compliance_scans (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  environment_id uuid REFERENCES environments(id) ON DELETE CASCADE,

  -- Scan metadata
  scan_type text NOT NULL CHECK (scan_type IN ('policy', 'config_drift', 'security', 'cost')),
  status text NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),

  -- Results
  total_checks integer,
  passed_checks integer,
  failed_checks integer,
  compliance_percentage float,

  violations jsonb DEFAULT '[]'::jsonb,
  drift_detected jsonb DEFAULT '[]'::jsonb,

  -- Evidence
  scan_report jsonb,
  remediation_instructions jsonb,

  started_at timestamp with time zone DEFAULT now(),
  completed_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now()
);

-- =====================================================================
-- AUDIT & COMPLIANCE
-- =====================================================================

CREATE TABLE audit_log (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),

  -- What happened
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,

  -- Who did it
  actor_id uuid NOT NULL,
  actor_type text,  -- 'user', 'service', 'system'

  -- Context
  project_id uuid,
  environment_id uuid,

  -- Changes
  before_state jsonb,
  after_state jsonb,

  -- Metadata
  metadata jsonb DEFAULT '{}'::jsonb,
  timestamp timestamp with time zone DEFAULT now(),

  -- Compliance
  is_sensitive_operation boolean DEFAULT false
);

CREATE INDEX ON audit_log (timestamp DESC);
CREATE INDEX ON audit_log (actor_id, timestamp DESC);
CREATE INDEX ON audit_log (entity_type, entity_id);

-- =====================================================================
-- ROLE-LEVEL SECURITY (RLS)
-- =====================================================================

ALTER TABLE environments ENABLE ROW LEVEL SECURITY;
ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE provisioning_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE runbook_executions ENABLE ROW LEVEL SECURITY;

-- Policy: Platform team sees all
CREATE POLICY "platform_team_all_access"
  ON environments
  USING (auth.jwt() ->> 'role' = 'platform_admin');

-- Policy: Developers see their own environments
CREATE POLICY "developers_own_environments"
  ON environments
  USING (owner_id = auth.uid() OR auth.jwt() ->> 'role' = 'platform_admin');

-- Policy: Security team sees policy violations
CREATE POLICY "security_team_violations"
  ON policy_evaluations
  USING (
    auth.jwt() ->> 'role' = 'security'
    OR auth.jwt() ->> 'role' = 'platform_admin'
  );

-- =====================================================================
-- FUNCTIONS & TRIGGERS
-- =====================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_environments_updated_at BEFORE UPDATE ON environments
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_provisioning_requests_updated_at BEFORE UPDATE ON provisioning_requests
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_incidents_updated_at BEFORE UPDATE ON incidents
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Audit log function
CREATE OR REPLACE FUNCTION audit_log_function()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO audit_log (action, entity_type, entity_id, actor_id, after_state)
  VALUES (TG_ARGV[0], TG_TABLE_NAME, NEW.id, auth.uid(), row_to_json(NEW));
  RETURN NEW;
END;
$$ language 'plpgsql';

-- =====================================================================
-- CONTINUOUS AGGREGATES (for metrics)
-- =====================================================================

-- Hour-level metrics aggregation
CREATE MATERIALIZED VIEW metrics_1hour WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', time) AS hour,
  metric_name,
  resource_id,
  environment_id,
  AVG(value) AS avg_value,
  MAX(value) AS max_value,
  MIN(value) AS min_value,
  STDDEV(value) AS stddev_value
FROM metrics
GROUP BY hour, metric_name, resource_id, environment_id
WITH DATA;

-- Day-level metrics aggregation
CREATE MATERIALIZED VIEW metrics_1day WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', time) AS day,
  metric_name,
  resource_id,
  environment_id,
  AVG(value) AS avg_value,
  MAX(value) AS max_value,
  MIN(value) AS min_value
FROM metrics
GROUP BY day, metric_name, resource_id, environment_id
WITH DATA;

-- =====================================================================
-- INDEXES FOR PERFORMANCE
-- =====================================================================

CREATE INDEX idx_resources_status ON resources(status);
CREATE INDEX idx_resources_provider ON resources(provider);
CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_severity ON incidents(severity);
CREATE INDEX idx_incidents_type ON incidents(incident_type);
CREATE INDEX idx_provisioning_status ON provisioning_requests(status);
CREATE INDEX idx_provisioning_requester ON provisioning_requests(requester_id);
CREATE INDEX idx_policy_evals_passed ON policy_evaluations(passed);
CREATE INDEX idx_simulation_runs_type ON simulation_runs(simulation_type);
CREATE INDEX idx_metrics_name_resource ON metrics(metric_name, resource_id);

-- GIN index for jsonb queries
CREATE INDEX idx_resources_config_gin ON resources USING GIN (configuration);
CREATE INDEX idx_incidents_features_gin ON incidents USING GIN (ml_features);
CREATE INDEX idx_audit_metadata_gin ON audit_log USING GIN (metadata);

COMMIT;
