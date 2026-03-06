# Infrastructure Automation Platform -- Improvements & Technology Roadmap

**Last Updated:** March 2026
**Scope:** Architecture improvements, new technology adoption, and prioritized roadmap

---

## 1. Product Overview

The Infrastructure Automation Platform is an enterprise-grade system that automates the full infrastructure lifecycle for organizations operating in regulated sectors (government, defense, financial services, manufacturing). It addresses five critical pain points:

- **Self-service provisioning** -- Replaces 3-4 day manual provisioning with a 7-step automated pipeline: request validation, OPA policy evaluation, approval gate, Terraform plan/apply, Ansible hardening, CMDB registration, and post-provisioning compliance scan. Orchestrated via Temporal durable workflows.
- **Simulation & digital twins** -- Creates containerized replicas of production topology (via Docker Compose) to run integration, performance, chaos, and regression tests before any change reaches production.
- **Progressive rollout** -- Canary deployments with staged traffic shifting (1% -> 10% -> 50% -> 100%), KPI monitoring against Datadog/Prometheus thresholds, and automated rollback on breach.
- **Intelligent incident response** -- Ingests alerts from Datadog, CloudWatch, Prometheus, and PagerDuty; deduplicates and correlates them via dependency-graph analysis; classifies incidents using a random-forest/spaCy ensemble; routes to the correct on-call team; and executes auto-remediation playbooks with safety gates.
- **Continuous compliance** -- Scans resources against NIST 800-53, FedRAMP, and SOC 2 controls; detects configuration drift by comparing live state to Terraform desired state; generates audit-ready reports.

Target metrics include deployment time under 8 hours, configuration error rate below 3%, MTTR under 15 minutes, and auto-resolution rate above 60%.

---

## 2. Current Architecture

### 2.1 Tech Stack

| Layer | Technology | Version/Notes |
|---|---|---|
| API | FastAPI + Uvicorn | Python 3.11, Pydantic v2 |
| Database | Supabase (PostgreSQL) + TimescaleDB | Hypertables for metrics, RLS for multi-tenancy |
| Cache | Redis 7 | AOF persistence, used for caching and job queues |
| Orchestration | Temporal (workflows), Trigger.dev (long-running jobs), n8n (workflow automation) | Three separate orchestration systems |
| IaC | Terraform ~1.6 + Ansible | Internal module registry, HCL generation |
| Policy | OPA/Rego | Four policy files: tags, storage, encryption, instance restrictions |
| ML/NLP | scikit-learn (random forest) + spaCy | Ensemble incident classifier (rf_v3.2_spacy_v2.1) |
| Monitoring | Datadog + Prometheus + CloudWatch + Grafana | Alert ingestion from multiple sources |
| Dashboards | Grafana | Three dashboards: infrastructure overview, incident response, simulation |
| Email | React Email (TSX templates) + SendGrid | Provisioning complete, incident escalation |
| Secrets | HashiCorp Vault | Dynamic STS credentials with 1h TTL |
| CI/CD | Makefile-driven | format, lint, test, coverage, docker, simulate |
| Cloud | AWS (primary), Azure (secondary) | GCP credentials in .env but no implementation |

### 2.2 Key Components

| Component | File | Responsibility |
|---|---|---|
| Provisioning Workflow | `src/provisioning/workflow.py` | 7-step Temporal workflow with approval gates |
| Policy Engine | `src/provisioning/policy_engine.py` | NIST 800-53 controls, budget enforcement, naming standards |
| Template Generator | `src/provisioning/template_generator.py` | Composable Terraform HCL from module registry |
| Resource Registry (CMDB) | `src/provisioning/resource_registry.py` | Lifecycle state machine, dependency graph, drift detection |
| Digital Twin | `src/simulation/digital_twin.py` | Docker Compose topology generation from CMDB state |
| Progressive Rollout | `src/simulation/progressive_rollout.py` | Canary stages with KPI evaluation and rollback |
| Synthetic Workload | `src/simulation/synthetic_workload.py` | Locust-based load patterns (steady, ramp, peak, spike, sine) |
| Alert Correlator | `src/incident_response/alert_correlator.py` | Time-window grouping, dependency-graph root cause analysis |
| Incident Classifier | `src/incident_response/incident_classifier.py` | RF + spaCy ensemble, severity rules, routing table |
| Remediation Engine | `src/incident_response/remediation_engine.py` | Playbook execution with preconditions, post-checks, rollback |
| Compliance Scanner | `src/observability/compliance_scanner.py` | NIST/SOC2 control evaluation, drift detection |
| Anomaly Detector | `src/detection/anomaly_detector.py` | Seasonal baselines, z-score/IQR detection, persistence |
| Terraform Apply Job | `trigger-jobs/terraform_apply.ts` | Trigger.dev long-running job with checkpointing |
| Incident Remediation Job | `trigger-jobs/incident_remediation.ts` | Trigger.dev job with human-in-the-loop approval |

### 2.3 Database Schema

The schema (`supabase/migrations/001_initial_schema.sql`) contains 15+ tables across five domains: infrastructure resources, provisioning requests/approvals, policy evaluation, incident management, and simulation/digital twin. Uses TimescaleDB hypertables for metrics with continuous aggregates at 1-hour and 1-day granularity. Row-Level Security is enabled on core tables.

---

## 3. Recommended Improvements

### 3.1 Consolidate Orchestration Layer

**Problem:** The platform uses three different orchestration systems -- Temporal (provisioning workflows), Trigger.dev (Terraform apply, incident remediation), and n8n (pipeline automation). This creates operational complexity, inconsistent observability, and fragmented error handling.

**Current code references:**
- `src/provisioning/workflow.py` -- references Temporal signals and retry policies
- `trigger-jobs/terraform_apply.ts` -- uses Trigger.dev `io.runTask()` with manual checkpointing
- `trigger-jobs/incident_remediation.ts` -- uses Trigger.dev `io.waitForHumanApproval()`
- `n8n/provisioning_pipeline.json` and `n8n/incident_response.json` -- n8n workflow definitions

**Recommendation:** Standardize on Temporal as the single workflow orchestration layer. Temporal already handles the most complex workflow (provisioning) and natively supports signals (approval gates), retries, timeouts, and durable execution. Replace Trigger.dev jobs with Temporal activities and replace n8n workflows with Temporal workflow definitions.

**Specific changes:**
- Convert `trigger-jobs/terraform_apply.ts` to a Temporal activity in Python, eliminating the TypeScript/Python language boundary and the manual checkpoint file system (`fs.writeFileSync(checkpointFile, ...)`)
- Convert `trigger-jobs/incident_remediation.ts` to a Temporal workflow that uses `workflow.wait_condition()` for human approval instead of Trigger.dev's `io.waitForHumanApproval()`
- Remove n8n dependency entirely; its workflow definitions are simple enough to be Temporal workflows
- Benefit: single observability plane, consistent retry semantics, no cross-language debugging

### 3.2 Replace Reference Implementations with Production Code

**Problem:** Many modules are documented as "reference implementations" with simulated data and placeholder functions. For example:

- `src/provisioning/resource_registry.py` line 102-104: `ResourceRegistry.__init__` stores resources in a Python dict instead of PostgreSQL
- `src/detection/anomaly_detector.py` line 82-85: baselines stored in in-memory dict instead of TimescaleDB
- `src/incident_response/remediation_engine.py` line 377-394: `_execute_step` returns simulated `StepResult.PASS` without actually running commands
- `src/provisioning/workflow.py` line 509-511: `_wait_for_approval_signal` is a `pass` stub

**Recommendation:** Implement actual database-backed persistence and external service calls:

- `ResourceRegistry` should use `asyncpg` pool (already injected in `workflow.py` line 112 as `db_pool`) to read/write the `resources` and `resource_dependencies` tables
- `AnomalyDetector.baselines` should read from the `anomaly_baselines` table via a repository pattern
- `RemediationEngine._execute_step` should dispatch commands via SSH (using `asyncssh`) or Kubernetes API calls, with real timeout and error handling
- `_wait_for_approval_signal` should use Temporal's `workflow.wait_condition` API

### 3.3 Add GCP Support

**Problem:** The `.env.example` includes GCP credentials (`GCP_PROJECT_ID`, `GCP_CREDENTIALS_JSON`) and the database schema has a `provider` column with a CHECK constraint for `('aws', 'azure', 'gcp')`, but there is no GCP implementation. The Vault credential acquisition in `workflow.py` line 467-478 only handles AWS and Azure, raising `ValueError` for anything else.

**Recommendation:**
- Add `gcp` branch in `_acquire_credentials()` using Vault's GCP secrets engine
- Create Terraform templates for GCP resources (Compute Engine, Cloud SQL, GKE) in `terraform/templates/`
- Add GCP resource type mappings in `digital_twin.py` `_generate_compose_topology()`
- Update `template_generator.py` `MODULE_REGISTRY` with GCP module entries

### 3.4 Improve ML Incident Classifier

**Problem:** The current classifier uses a simulated random forest (`_classify_structured` in `incident_classifier.py` lines 264-292) and keyword matching for text classification (`_classify_text` lines 294-315) instead of trained models. The ensemble weighting is hardcoded at 60/40 (line 221-229) without calibration.

**Recommendation:**
- Train a real scikit-learn RandomForestClassifier on historical incident data (the schema already has `ml_features` in the `incidents` table)
- Replace keyword matching with a trained spaCy `TextCategorizer` pipeline using the `en_core_web_md` model (already in `requirements.txt` and `Makefile install` target)
- Implement model versioning and A/B testing: store model artifacts in S3 with version tags, load by `MODEL_VERSION` string
- Add a model retraining pipeline triggered by new incident data exceeding a threshold (e.g., 500 new labeled incidents)
- Calibrate ensemble weights using cross-validation on a held-out set instead of hardcoded 60/40

### 3.5 Add Structured Logging and Distributed Tracing

**Problem:** The codebase references OpenTelemetry in `.env.example` (`OTEL_ENABLED`, `OTEL_JAEGER_ENDPOINT`) and `python-json-logger` in `requirements.txt`, but there is no actual instrumentation in the source code. Temporal workflows, API endpoints, and background jobs have no trace context propagation.

**Recommendation:**
- Add OpenTelemetry SDK instrumentation to the FastAPI app using `opentelemetry-instrumentation-fastapi` (auto-instrumentation)
- Propagate trace IDs through Temporal workflows using Temporal's `interceptor` API for OpenTelemetry
- Add structured JSON logging with correlation IDs to every component, using `python-json-logger`
- Replace Jaeger with Grafana Tempo (already running Grafana) for trace storage, or use the OTLP exporter to send to Datadog APM
- Add span attributes for provisioning request IDs, incident IDs, and resource IDs for cross-component correlation

### 3.6 Harden Security

**Problem:** Several security concerns in the current codebase:

- `docker-compose.yml` line 26: database credentials are hardcoded (`postgres:postgres`)
- `docker-compose.yml` line 97: Grafana admin password is `admin`
- `src/simulation/digital_twin.py` line 205: test database password is hardcoded as `twin-test-only`
- `trigger-jobs/terraform_apply.ts` line 48: Terraform working directory is `/tmp` with no isolation
- Raw SQL queries in `workflow.py` lines 417-449 use parameterized queries (good), but there is no input validation on `request.parameters` dict before it reaches the policy engine

**Recommendation:**
- Use Docker secrets or environment variable injection from Vault for all credentials in `docker-compose.yml`
- Add Pydantic model validation for all `parameters` dicts before they reach the policy engine or template generator
- Use ephemeral containers or Firecracker microVMs for Terraform execution instead of `/tmp` directories
- Add RBAC checks at the API layer before workflow dispatch (the schema has RLS but the Python code does not enforce roles)

### 3.7 Add Comprehensive Test Suite

**Problem:** The `Makefile` references `pytest tests/` but there is no `tests/` directory in the repository. Each module has example functions (e.g., `evaluate_request_example()`, `simulation_example()`, `correlation_example()`) that serve as informal tests but are not actual pytest test cases.

**Recommendation:**
- Create `tests/` directory with unit tests for each module:
  - `tests/test_policy_engine.py` -- test all NIST controls, budget checks, approval routing
  - `tests/test_template_generator.py` -- test module selection, HCL generation, cost estimation
  - `tests/test_resource_registry.py` -- test state machine transitions, cascade impact, drift detection
  - `tests/test_alert_correlator.py` -- test deduplication, time-window grouping, root cause scoring
  - `tests/test_incident_classifier.py` -- test classification, severity determination, routing
  - `tests/test_remediation_engine.py` -- test playbook matching, execution flow, rate limiting
  - `tests/test_anomaly_detector.py` -- test z-score, IQR, persistence, baseline updates
- Use `hypothesis` (already in `requirements.txt`) for property-based testing of the policy engine
- Add integration tests using `testcontainers-python` for PostgreSQL and Redis
- Target 80%+ code coverage

### 3.8 Add API Layer

**Problem:** The `docker-compose.yml` references a FastAPI backend, and the ARCHITECTURE doc describes a full REST API, but there are no actual API route definitions in the `src/` directory. The Trigger.dev jobs in `trigger-jobs/` make `fetch()` calls to `http://api:3000/` endpoints that do not exist.

**Recommendation:**
- Create `src/api/` package with FastAPI routers:
  - `src/api/provisioning.py` -- POST/GET/DELETE for provisioning requests
  - `src/api/incidents.py` -- POST alert ingestion, GET/PATCH incident lifecycle
  - `src/api/compliance.py` -- GET scan results, POST trigger scan
  - `src/api/resources.py` -- GET CMDB queries, dependency graphs
  - `src/api/deployments.py` -- POST rollout, GET rollout status
- Add Pydantic request/response models for type safety and auto-generated OpenAPI docs
- Implement JWT/SAML authentication middleware
- Add rate limiting per tenant using Redis

---

## 4. New Technologies & Trends

### 4.1 OpenTofu -- Open-Source Terraform Fork

**What:** OpenTofu is the Linux Foundation's open-source fork of Terraform, created after HashiCorp changed Terraform's license to BSL in August 2023. OpenTofu 1.8+ introduced state encryption, provider-defined functions, and early variable/local evaluation.

**Why it matters for this project:** The platform currently pins `terraform >= 1.5.0` in generated HCL (`template_generator.py` line 254) and `TERRAFORM_VERSION=1.6.0` in `.env.example`. As HashiCorp tightens BSL restrictions, OpenTofu provides a license-safe drop-in replacement with additional features like state encryption (critical for NIST SC-28 compliance without relying solely on S3 server-side encryption).

**How to integrate:**
- Replace the `terraform` binary in `trigger-jobs/terraform_apply.ts` with `tofu` (CLI-compatible)
- Enable state encryption in OpenTofu configuration to add defense-in-depth for `terraform.tfstate` files stored in S3
- Update `template_generator.py` line 254 from `required_version = ">= 1.5.0"` to `required_version = ">= 1.8.0"` (OpenTofu versioning)

**Reference:** [https://opentofu.org/](https://opentofu.org/)

### 4.2 Pulumi + CDKTF -- IaC in General-Purpose Languages

**What:** Pulumi allows writing infrastructure code in Python, TypeScript, Go, and other languages instead of HCL. CDKTF (Cloud Development Kit for Terraform) provides a similar approach but generates Terraform JSON under the hood. Pulumi 3.x introduced Pulumi ESC (Environments, Secrets, and Configuration) for centralized secret management, and Pulumi AI for natural-language infrastructure generation.

**Why it matters:** The `template_generator.py` manually builds HCL strings with Python string concatenation (lines 247-293). This is fragile -- it does not handle escaping, complex nested structures, or conditional blocks well. Pulumi or CDKTF would let the template generator produce type-safe infrastructure definitions in Python directly, with IDE autocompletion, unit testing, and refactoring support.

**How to integrate:**
- Replace `_render_hcl()` in `template_generator.py` with Pulumi Python SDK calls or CDKTF Python constructs
- The existing `MODULE_REGISTRY` pattern maps cleanly to Pulumi ComponentResources or CDKTF constructs
- Keep Terraform state backend for compatibility; Pulumi can use its own state or Terraform state via `pulumi import`

**Reference:** [https://www.pulumi.com/](https://www.pulumi.com/), [https://developer.hashicorp.com/terraform/cdktf](https://developer.hashicorp.com/terraform/cdktf)

### 4.3 Backstage -- Internal Developer Portal

**What:** Backstage (CNCF Incubating) is Spotify's open-source platform for building internal developer portals. It provides a service catalog, software templates, TechDocs, and a plugin ecosystem. Backstage 1.x has stabilized its plugin API and added Backstage Search, Kubernetes integration, and cost insights plugins.

**Why it matters:** The platform currently uses ServiceNow for request intake (`.env.example` line 88-92) and Grafana for dashboards. Backstage could unify the developer experience: service catalog (replaces CMDB queries), software templates (replaces the provisioning request form), and TechDocs (embeds architecture and compliance documentation). This directly serves the "Priya" developer persona from the PRD who needs self-service without learning Terraform.

**How to integrate:**
- Deploy Backstage as the frontend portal, replacing ServiceNow for provisioning requests
- Create Backstage software templates that call the FastAPI provisioning API
- Use the Backstage Kubernetes plugin to show real-time resource health
- Integrate the Grafana plugin to embed existing dashboards

**Reference:** [https://backstage.io/](https://backstage.io/)

### 4.4 Cedar -- AWS Policy Language Alternative to Rego

**What:** Cedar is Amazon's open-source policy language, designed to be more readable and performant than Rego for authorization and access control decisions. It supports static analysis (policies can be verified for correctness before deployment) and is used in production by AWS Verified Access and Amazon Verified Permissions. Cedar 3.x added entity slicing for performance and schema-based policy validation.

**Why it matters:** The current Rego policies in `policies/` are functional but Rego has a steep learning curve. The `policy_engine.py` reference implementation (line 105-113) acknowledges that the Python code must mirror what the Rego policies encode. Cedar's type-safe schema validation could catch policy errors at authoring time rather than runtime, and its simpler syntax would lower the barrier for security officers (the "Security/Compliance Officer" persona from the PRD) to write and review policies.

**How to integrate:**
- Evaluate Cedar for the simpler policy domains (mandatory tags, naming conventions) while keeping OPA/Rego for complex NIST control evaluation
- Use the `cedarpy` Python SDK to evaluate Cedar policies from the FastAPI backend
- Implement Cedar schema definitions that match the `ProvisioningRequest` dataclass structure

**Reference:** [https://www.cedarpolicy.com/](https://www.cedarpolicy.com/)

### 4.5 Kyverno -- Kubernetes-Native Policy Engine

**What:** Kyverno (CNCF Graduated, 2024) is a Kubernetes-native policy engine that uses YAML instead of Rego for policy definitions. It supports validation, mutation, and generation of Kubernetes resources. Kyverno 1.12+ added policy exceptions, background scanning, and ValidatingAdmissionPolicy integration.

**Why it matters:** While OPA is used for Terraform-level policy evaluation, if the platform provisions Kubernetes namespaces (there is a `terraform/templates/kubernetes_namespace.tf` template), Kyverno can enforce runtime policies on the Kubernetes cluster itself -- preventing privilege escalation, requiring resource limits, enforcing image signing, and blocking public LoadBalancer services.

**How to integrate:**
- Deploy Kyverno ClusterPolicies to enforce the same compliance controls (NIST SC-7, AC-6) at the Kubernetes admission layer
- The policies in `policies/mandatory_tags.rego` can be mirrored as Kyverno policies that enforce labels on Kubernetes resources
- Use Kyverno Policy Reporter to feed compliance scan data back into the platform's `compliance_scans` table

**Reference:** [https://kyverno.io/](https://kyverno.io/)

### 4.6 Grafana Alloy (formerly Grafana Agent) -- Unified Telemetry Pipeline

**What:** Grafana Alloy (successor to Grafana Agent) is an OpenTelemetry Collector distribution that collects metrics, logs, and traces, and ships them to any OTLP-compatible backend. It replaced Grafana Agent in 2024 and provides a single binary for all telemetry collection.

**Why it matters:** The platform currently relies on Datadog, Prometheus, CloudWatch, and Grafana for observability, with the `alert_correlator.py` ingesting alerts from all four sources. Grafana Alloy can unify telemetry collection, reducing the number of agents on each managed host and simplifying the alert ingestion pipeline.

**How to integrate:**
- Replace the per-resource Datadog agent installation (referenced in `template_generator.py` line 87: `datadog_agent_version: "7.45.0"`) with Grafana Alloy
- Configure Alloy to export metrics to both Prometheus/Mimir and Datadog (dual-write) during migration
- Use Alloy's built-in service discovery to auto-register new resources, eliminating the manual monitoring setup in `workflow.py` line 198

**Reference:** [https://grafana.com/oss/alloy/](https://grafana.com/oss/alloy/)

### 4.7 Crossplane -- Kubernetes-Based Infrastructure Control Plane

**What:** Crossplane (CNCF Graduated, 2024) extends Kubernetes with Custom Resource Definitions (CRDs) to manage cloud infrastructure declaratively using the Kubernetes API. It supports AWS, Azure, and GCP through provider plugins.

**Why it matters:** The current architecture generates Terraform HCL and shells out to the Terraform CLI. Crossplane would allow the platform to define infrastructure as Kubernetes resources, leveraging Kubernetes reconciliation loops for drift detection (replacing the manual drift check in `resource_registry.py` lines 249-274) and self-healing. This aligns with the GitOps trend where infrastructure state is managed through Kubernetes controllers.

**How to integrate:**
- Create Crossplane Compositions that mirror the existing Terraform modules in `MODULE_REGISTRY`
- Use Crossplane's built-in drift detection (controller reconciliation) to replace `ComplianceScanner._check_drift()`
- Keep Terraform as an option for organizations that prefer it; Crossplane and Terraform can coexist

**Reference:** [https://www.crossplane.io/](https://www.crossplane.io/)

### 4.8 LLM-Powered Incident Analysis

**What:** Large Language Models (GPT-4o, Claude, Gemini) are being integrated into AIOps platforms for incident summarization, root cause analysis, and runbook generation. Tools like Datadog Bits AI, PagerDuty AIOps, and open-source projects integrate LLMs for natural-language incident investigation.

**Why it matters:** The current incident classifier uses a random forest + keyword ensemble (`incident_classifier.py`). While good for structured classification, it cannot explain its reasoning, summarize incident context in natural language, or suggest novel remediation steps. An LLM layer could:
- Generate human-readable incident summaries for the on-call engineer
- Suggest remediation steps beyond the hardcoded `PLAYBOOK_AVAILABILITY` map
- Analyze log snippets and stack traces embedded in alert messages
- Power a conversational interface for incident investigation

**How to integrate:**
- Add an LLM-powered incident summarizer that runs after the classifier, consuming alert messages, CMDB context, and dependency graph data
- Use retrieval-augmented generation (RAG) with historical incident resolutions stored in the `incidents` table
- Keep the random forest classifier for routing decisions (fast, deterministic) and use the LLM for human-facing explanations (slower, richer)
- Use `litellm` (Python library) to abstract across LLM providers

**Reference:** [https://github.com/BerriAI/litellm](https://github.com/BerriAI/litellm)

### 4.9 eBPF-Based Observability (Cilium, Pixie, Coroot)

**What:** eBPF (Extended Berkeley Packet Filter) enables kernel-level observability without application instrumentation. Tools like Cilium (CNCF Graduated) for networking/security, Pixie (CNCF Sandbox, now part of New Relic) for auto-instrumented observability, and Coroot for eBPF-based infrastructure monitoring provide deep visibility with zero application changes.

**Why it matters:** The anomaly detector (`anomaly_detector.py`) relies on metrics pushed by agents (Datadog, CloudWatch). eBPF-based tools can capture network flows, syscall latency, and DNS resolution without agent configuration, providing richer signals for anomaly detection. Cilium's Hubble can also enforce network policies, directly implementing NIST SC-7 (Boundary Protection) at the kernel level.

**How to integrate:**
- Deploy Cilium as the CNI plugin on managed Kubernetes clusters, gaining L3/L4/L7 network visibility
- Feed Hubble flow data into the `metrics` hypertable for anomaly detection
- Use Cilium Network Policies to enforce the same boundary protection rules currently checked by `compliance_scanner.py` `_check_network_boundary()`

**Reference:** [https://cilium.io/](https://cilium.io/), [https://coroot.com/](https://coroot.com/)

### 4.10 Dagger -- Programmable CI/CD Engine

**What:** Dagger is a programmable CI/CD engine that runs pipelines in containers. Dagger 0.13+ provides SDKs for Python, Go, TypeScript, and more. Pipelines are defined as code, are fully containerized (eliminating "works on my machine" CI issues), and can be run locally or in any CI system.

**Why it matters:** The platform uses a Makefile for CI/CD (`make ci: lint test coverage`) and Docker Compose for local development. Dagger would allow defining the build, test, and deploy pipeline as Python code that runs identically locally and in CI, with built-in caching and parallelism.

**How to integrate:**
- Replace `Makefile` CI targets with Dagger Python SDK pipelines
- Use Dagger for Terraform validation, OPA policy testing, and Python linting/testing in containerized environments
- Benefit: developers can run the full CI pipeline locally with `dagger run` before pushing

**Reference:** [https://dagger.io/](https://dagger.io/)

### 4.11 Temporal Cloud or Restate -- Managed Durable Execution

**What:** Temporal Cloud is the managed version of Temporal, eliminating the operational burden of running Temporal clusters. Restate is an alternative durable execution framework that provides similar workflow durability with a simpler programming model (no separate worker processes) and built-in virtual objects.

**Why it matters:** The platform's Temporal workflows are central to provisioning and incident response. Self-hosting Temporal adds operational complexity. Temporal Cloud provides managed hosting with multi-region support, while Restate offers an interesting alternative with lower operational overhead.

**How to integrate:**
- Migrate to Temporal Cloud for production deployments, keeping self-hosted for development
- Alternatively, evaluate Restate's virtual objects for simpler workflows (e.g., approval gates, incident state machines) while keeping Temporal for complex orchestrations

**Reference:** [https://temporal.io/cloud](https://temporal.io/cloud), [https://restate.dev/](https://restate.dev/)

### 4.12 Infracost -- Cloud Cost Estimation

**What:** Infracost provides real-time cloud cost estimates for Terraform plans. It integrates into CI/CD to show cost diffs on pull requests. Infracost 0.10+ supports 1,100+ AWS, Azure, and GCP resource types.

**Why it matters:** The current cost estimation in `template_generator.py` lines 339-350 uses a hardcoded `cost_map` with static per-resource prices. Infracost provides accurate, up-to-date pricing directly from cloud provider APIs, including data transfer, storage tiers, and reserved instance discounts.

**How to integrate:**
- Replace `_estimate_cost()` in `template_generator.py` with Infracost CLI integration
- Run `infracost diff` as part of the Terraform plan step in `workflow.py`
- Display accurate cost delta in the approval request sent to approvers

**Reference:** [https://www.infracost.io/](https://www.infracost.io/)

---

## 5. Priority Roadmap

### P0 -- Critical (Must-Have, Next Sprint)

| # | Improvement | Effort | Impact | Reference |
|---|---|---|---|---|
| 1 | **Add API layer** -- Create FastAPI routers for provisioning, incidents, compliance, and resources. Without this, Trigger.dev jobs and the frontend cannot communicate with the platform. | 2 weeks | Unblocks all integration | Section 3.8 |
| 2 | **Add test suite** -- Create pytest tests for all core modules. Current test coverage is 0%. | 1 week | Quality, CI pipeline | Section 3.7 |
| 3 | **Harden credentials** -- Remove hardcoded passwords from `docker-compose.yml` and `digital_twin.py`. Use Docker secrets or Vault injection. | 2 days | Security | Section 3.6 |
| 4 | **Implement workflow stubs** -- Replace `pass` stubs in `workflow.py` (`_wait_for_approval_signal`, `_run_compliance_scan`, `_configure_monitoring`) with real implementations. | 1 week | Core functionality | Section 3.2 |

### P1 -- High Priority (Next Month)

| # | Improvement | Effort | Impact | Reference |
|---|---|---|---|---|
| 5 | **Consolidate orchestration** -- Migrate Trigger.dev jobs and n8n workflows to Temporal. Eliminate the three-system complexity. | 2 weeks | Operational simplicity | Section 3.1 |
| 6 | **Add OpenTelemetry instrumentation** -- Instrument FastAPI, Temporal workflows, and background jobs with traces, metrics, and structured logs. | 1 week | Observability | Section 3.5 |
| 7 | **Integrate Infracost** -- Replace hardcoded cost estimation with Infracost for accurate Terraform plan cost analysis. | 3 days | Cost accuracy | Section 4.12 |
| 8 | **Train real ML models** -- Train RandomForestClassifier and spaCy TextCategorizer on historical incident data. Implement model versioning. | 2 weeks | Incident response quality | Section 3.4 |
| 9 | **Add GCP provider support** -- Implement GCP credential acquisition, Terraform templates, and resource type mappings. | 1 week | Multi-cloud | Section 3.3 |

### P2 -- Medium Priority (Next Quarter)

| # | Improvement | Effort | Impact | Reference |
|---|---|---|---|---|
| 10 | **Evaluate OpenTofu migration** -- Test OpenTofu as drop-in replacement. Enable state encryption for SC-28 compliance. | 1 week | License safety, compliance | Section 4.1 |
| 11 | **Deploy Backstage portal** -- Stand up Backstage as the developer-facing frontend with software templates for provisioning and embedded Grafana dashboards. | 3 weeks | Developer experience | Section 4.3 |
| 12 | **Add Kyverno for Kubernetes** -- Deploy Kyverno cluster policies for runtime enforcement on managed Kubernetes clusters. | 1 week | Runtime compliance | Section 4.5 |
| 13 | **LLM incident summarizer** -- Add LLM-powered incident summaries and remediation suggestions using RAG over historical data. | 2 weeks | Incident response | Section 4.8 |
| 14 | **Replace Datadog agent with Grafana Alloy** -- Unify telemetry collection with a single agent, reducing per-host overhead. | 2 weeks | Operational simplicity | Section 4.6 |
| 15 | **Implement Pulumi/CDKTF for template generation** -- Replace HCL string building with type-safe Python IaC definitions. | 3 weeks | Developer experience, safety | Section 4.2 |

### P3 -- Long-Term (Next 6 Months)

| # | Improvement | Effort | Impact | Reference |
|---|---|---|---|---|
| 16 | **Evaluate Crossplane** -- Prototype Crossplane Compositions for drift detection and self-healing infrastructure. | 4 weeks | GitOps, drift remediation | Section 4.7 |
| 17 | **eBPF observability** -- Deploy Cilium for kernel-level network visibility and Hubble for flow metrics. | 4 weeks | Deep observability | Section 4.9 |
| 18 | **Migrate CI to Dagger** -- Replace Makefile-based CI with Dagger Python SDK pipelines for reproducible, containerized builds. | 2 weeks | CI reliability | Section 4.10 |
| 19 | **Evaluate Cedar policies** -- Prototype Cedar for simpler policy domains (tagging, naming) while keeping OPA for complex NIST controls. | 2 weeks | Policy authoring UX | Section 4.4 |
| 20 | **Migrate to Temporal Cloud** -- Move Temporal to managed hosting for production, reducing operational burden. | 1 week | Operational simplicity | Section 4.11 |

---

## Appendix: Version Reference

| Technology | Current Version in Project | Latest Stable (as of early 2025) |
|---|---|---|
| Python | 3.11 | 3.13 |
| FastAPI | >= 0.115.0 | 0.115.x |
| Terraform | 1.6.0 | 1.9.x / OpenTofu 1.8.x |
| PostgreSQL | 15 | 17 |
| TimescaleDB | latest-pg15 | 2.17.x (pg16 support) |
| Redis | 7 | 7.4.x |
| Grafana | latest | 11.x |
| scikit-learn | >= 1.3.2 | 1.5.x |
| spaCy | >= 3.7.2 | 3.8.x |
| Pydantic | >= 2.10.0 | 2.10.x |
| Docker Compose | 3.8 spec | Compose v2 (no version field) |
| OPA | (not pinned) | 1.0.x (Rego v1) |
| Temporal | (not pinned) | 1.25.x |
| Datadog Agent | 7.45.0 | 7.60.x |

---

*This document was generated from analysis of all source files in the repository including provisioning workflows, policy engine, template generator, resource registry, simulation/digital twin, progressive rollout, synthetic workload generator, alert correlator, incident classifier, remediation engine, compliance scanner, anomaly detector, Trigger.dev jobs, Terraform templates, OPA Rego policies, database migrations, Docker Compose configuration, and project documentation.*
