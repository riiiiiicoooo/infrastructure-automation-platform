# Architecture Decision Records

This document captures the key technical decisions made during the design and implementation of the Infrastructure Automation Platform. Each ADR explains the context, the decision, alternatives evaluated, and the trade-offs accepted.

---

## ADR-001: Temporal for Provisioning Workflow Orchestration

**Status:** Accepted
**Date:** 2024-02

**Context:** The provisioning workflow is a 7-step pipeline (policy evaluation, approval gate, Vault credential acquisition, Terraform plan/apply, Ansible hardening, CMDB registration, compliance scan) that can take minutes to hours to complete. Steps involve external systems (cloud APIs, HashiCorp Vault, OPA) that can fail transiently, and the approval gate requires the workflow to pause indefinitely until a human responds. The platform must guarantee that a crash mid-workflow does not re-provision resources or leave infrastructure in a partially-configured state.

**Decision:** Use Temporal as the durable workflow engine. Each provisioning step is modeled as a Temporal activity with its own timeout and retry policy (e.g., `TERRAFORM_APPLY_TIMEOUT = 2 hours`, `APPROVAL_WAIT_TIMEOUT = 7 days`). The approval gate uses Temporal signals -- the workflow blocks at `_wait_for_approval_signal()` and resumes when an approver sends an approve/reject signal through the API or portal. Vault credential leases are acquired before Terraform apply and revoked in a `finally` block to guarantee cleanup on both success and failure paths.

**Alternatives Considered:**
- **Apache Airflow:** Designed for batch-oriented DAG execution, not real-time interactive workflows. Airflow lacks native signal/query primitives for human-in-the-loop approval injection, which would require external polling mechanisms.
- **AWS Step Functions:** Provides durable execution but locks the platform into AWS. Multi-cloud provisioning (AWS + Azure) would require separate orchestration stacks or custom Lambda-based bridges.
- **Trigger.dev (used alongside):** Used for long-running job orchestration with checkpointing (see `trigger-jobs/terraform_apply.ts`), but Temporal provides the higher-level workflow coordination layer with stronger replay guarantees across the full 7-step pipeline.

**Consequences:**
- Workflows survive platform crashes and resume from the last completed activity, eliminating partial provisioning states.
- Signal-based approval gates allow indefinite workflow pauses without consuming compute resources.
- Adds operational complexity: requires running a Temporal cluster (or Temporal Cloud at ~$200/month) and maintaining worker processes.
- Activity-level retry policies (exponential backoff, 3 max attempts, 5-minute maximum interval) handle transient cloud API failures without re-running the full pipeline.

---

## ADR-002: Terraform + Ansible Split for Infrastructure-as-Code

**Status:** Accepted
**Date:** 2024-02

**Context:** The platform must provision cloud infrastructure (VPCs, EC2 instances, RDS databases, load balancers, S3 buckets) and then configure those resources with security hardening, monitoring agents, and SSH restrictions. A single tool needs to handle both declarative infrastructure state management and imperative post-provisioning configuration tasks like package installation ordering, service configuration, and CIS benchmark hardening.

**Decision:** Split IaC into two layers. Terraform handles declarative infrastructure provisioning through composable modules from an internal registry (`MODULE_REGISTRY` in `template_generator.py` with versioned modules for compute, networking, storage, database, monitoring, security, and load balancer). Ansible handles post-provisioning configuration through playbooks defined in templates (CIS hardening, Datadog agent installation, SSH configuration). The `TemplateGenerator` class composes Terraform HCL from module references with user parameter overrides, enforces mandatory tags (`project`, `team`, `cost_center`, `environment`, `managed_by`, `provisioned_at`), and configures S3 backend with DynamoDB state locking. Ansible inventory is auto-generated from Terraform apply output with Vault-managed Datadog API keys.

**Alternatives Considered:**
- **Terraform-only:** Terraform excels at declarative state but is weak at imperative configuration tasks where execution order matters (e.g., installing packages before configuring services). `local-exec` provisioners are brittle and not idempotent.
- **Pulumi:** Would require all operations engineers to learn TypeScript or Python SDK. Terraform's HCL has a lower learning curve for ops teams who already work with YAML-based configuration.
- **Ansible-only:** Ansible can provision cloud resources but lacks Terraform's state management, plan-before-apply workflow, and drift detection capabilities.

**Consequences:**
- Clear separation of concerns: Terraform owns "what infrastructure exists" and Ansible owns "how it is configured."
- The template + override pattern (base config per environment tier with only deltas specified) reduced configuration errors from 18% to 1.8% by eliminating copy-paste drift.
- Two tools means two sets of state to manage, two failure modes to handle in the workflow, and potential ordering issues between provisioning and configuration.
- Internal module registry with semantic versioning (`compute@2.1.0`, `networking@1.8.0`) ensures security-reviewed modules are used consistently across all provisioning requests.

---

## ADR-003: OPA Rego for Policy-as-Code Compliance Enforcement

**Status:** Accepted
**Date:** 2024-03

**Context:** The platform serves government, defense, and financial services clients with compliance requirements across NIST 800-53, FedRAMP, SOC 2, PCI DSS, and HIPAA. Compliance rules change as frameworks evolve and as organizational policies are updated. Hardcoding rules in application logic makes every policy change a code deployment. The policy evaluation must run at provisioning time (pre-deployment gate) and continuously post-deployment (drift/compliance scanning).

**Decision:** Use Open Policy Agent (OPA) with Rego policies stored in Git alongside infrastructure code. Four policy bundles are implemented: `mandatory_tags.rego` (tag validation with resource-type-specific rules), `encryption_required.rego` (encryption at rest for EBS, RDS, S3, DynamoDB, ElastiCache with KMS key enforcement for production), `no_public_storage.rego` (S3 ACL/policy validation, RDS public access prevention), and `instance_restrictions.rego` (environment-based instance type guardrails with cost thresholds). The `PolicyEngine` class evaluates requests against NIST controls (AC-2, AC-6, SC-7, SC-28, AU-2, CM-2, CM-7), budget constraints, and organizational rules. The `ComplianceScanner` runs post-provisioning scans with configurable frequency (hourly for production, daily for staging, weekly for dev).

**Alternatives Considered:**
- **Hardcoded rules in Python:** Would require code deployments for every policy update, which is unacceptable when compliance frameworks evolve. No separation between policy logic and application logic.
- **Commercial GRC tools (ServiceNow GRC, Archer):** Expensive, designed for manual audit workflows rather than automated inline enforcement, and unable to evaluate in the provisioning pipeline at <10ms latency.
- **AWS Config Rules:** Cloud-specific, would not work for multi-cloud enforcement, and limited to post-deployment detection rather than pre-deployment prevention.

**Consequences:**
- Policies are version-controlled, testable (see `policies/test/mandatory_tags_test.rego`), and reviewable through standard Git workflows.
- Each Rego policy maps violations to specific compliance frameworks (e.g., encryption violations map to NIST SC-28, PCI DSS 3.2.1, SOC 2 CC6.1, HIPAA 164.312, FedRAMP SC-28), enabling automated audit report generation.
- Policy evaluation at provisioning time prevents non-compliant resources from ever being created, shifting compliance left.
- Requires OPA expertise on the team; Rego's logic programming model has a steeper learning curve than imperative policy definitions.
- Tiered approval routing based on policy results: production environments require VP approval, cost exceeding threshold requires Director approval, elevated IAM permissions require Director approval, dev/staging under threshold is auto-approved.

---

## ADR-004: Containerized Digital Twin for Pre-Deployment Simulation

**Status:** Accepted
**Date:** 2024-03

**Context:** Infrastructure changes were validated only by reviewing Terraform plan output, which catches syntax errors but misses behavioral issues (e.g., a security group change that applies successfully but breaks a dependent service). A persistent staging environment was considered but costs 60-80% of production and drifts constantly from the production topology.

**Decision:** Build an ephemeral digital twin simulation layer. The `DigitalTwinManager` generates Docker Compose topologies from the CMDB resource graph, mapping cloud resources to container equivalents (EC2 to application containers with resource limits matching instance types, RDS to PostgreSQL containers, ElastiCache to Redis, S3 to MinIO, ALB to nginx). The `SyntheticWorkloadGenerator` produces realistic traffic plans using five patterns (steady, ramp-up, peak-hour business cycle, sudden spike, sine wave) with request profiles derived from real production traffic analysis. Four test suites run against each twin: integration (end-to-end workflow validation), performance (baseline 100 RPS through sustained 10-minute load), chaos (network partition, process kill, disk fill, latency injection), and regression (API compatibility, schema compatibility, config parsing, monitoring agent reporting).

**Alternatives Considered:**
- **Persistent staging environment:** $45K/month ongoing cost vs ~$200 per simulation run. Staging environments drift from production topology within days, giving false confidence.
- **Terraform plan-only validation:** Catches 30% of issues (syntax and configuration errors) but misses behavioral and performance problems. The simulation catches 94% of issues pre-production.
- **Production canary only (no simulation):** Risk of deploying untested changes to production, even at 1% traffic. Simulation provides a zero-risk validation layer before any production exposure.

**Consequences:**
- Simulation cost is ~$200/run (c5.4xlarge equivalent for test duration) versus $45K/month for persistent staging, representing a 99.5% cost reduction for validation infrastructure.
- Twins spin up on demand, run identical workloads against synthetic data, and tear down after validation, eliminating environment drift.
- The simulation was the most expensive module to build (6 weeks of the 10-week core build) but became the highest-impact feature.
- Container-based twins cannot perfectly replicate managed service behavior (e.g., RDS failover mechanics, ElastiCache cluster mode), creating a fidelity gap for certain failure scenarios.

---

## ADR-005: Progressive Rollout with Manual Approval Gate at 50%

**Status:** Accepted
**Date:** 2024-04

**Context:** Infrastructure changes need to reach production, but fully automated rollout is too risky (a 2% error rate across 500 servers is 10 misconfigured systems), while fully manual deployment is too slow and blocks the deployment velocity target of 12+ deployments per month.

**Decision:** Implement a 4-stage progressive rollout engine: 1% canary (15-minute observation, auto-advance), 10% canary (30-minute observation, auto-advance), 50% (30-minute observation, mandatory human approval gate via Temporal signal), 100% full rollout (15-minute final soak). Five KPIs are monitored at each stage with pass/rollback thresholds: error rate (<1% pass, >2% for 5 min triggers rollback), p99 latency (<500ms pass, >1000ms rollback), CPU utilization (<70% pass, >90% rollback), memory utilization (<80% pass, >95% rollback), and health check pass rate (100% pass, <98% rollback). Traffic shifting is implemented via load balancer weight adjustment, and rollback reverts weights to 0% for the new version with health verification on the old version.

**Alternatives Considered:**
- **Fully automated progressive rollout:** Removes the human judgment checkpoint at the critical 50% threshold where the blast radius becomes significant. A subtle performance degradation that passes automated thresholds could affect half the fleet.
- **Fully manual deployment:** Limits deployment velocity and introduces human scheduling bottlenecks. Prior process averaged 3-4 days per deployment.
- **Blue-green deployment only:** Provides instant rollback but requires double the infrastructure cost and doesn't allow gradual confidence building through staged traffic exposure.

**Consequences:**
- The 50% manual gate balances automation speed with human oversight at the point where blast radius becomes operationally significant.
- KPI-based automated rollback at early stages (1%, 10%) catches issues before they affect significant traffic, achieving 97% automated rollback success rate.
- The observation windows (15-30 minutes per stage) add 1.5-2 hours to total deployment time compared to immediate full rollout.
- Rollback is automated at all stages: load balancer weights revert, new version containers/instances are removed, and the deployer receives a Slack notification with the rollback reason.

---

## ADR-006: ML Ensemble for Incident Classification with Confidence-Gated Auto-Remediation

**Status:** Accepted
**Date:** 2024-04

**Context:** Operations teams process 500+ monitoring alerts per month from Datadog, CloudWatch, Prometheus, and PagerDuty. Alert fatigue is real, and manual triage takes 45 minutes average per incident. The team needs to distinguish signal from noise, correlate related alerts into incidents, and automatically remediate common patterns while routing complex issues to the appropriate on-call team.

**Decision:** Implement a three-stage incident response pipeline. Stage 1: The `AlertCorrelator` normalizes alerts from multiple sources to a common schema, deduplicates within a 5-minute sliding window, clusters related alerts using the CMDB dependency graph (BFS traversal within 3 hops), and identifies root causes using a scoring heuristic based on dependency depth, alert timing, and resource type weights (databases score 3.0x, cache 2.5x, application servers 1.0x). Stage 2: The `IncidentClassifier` uses a two-model ensemble -- structured features (resource type, environment, cascade depth) weighted at 60% and NLP text classification (keyword pattern matching against 7 incident types) weighted at 40% -- with a confidence penalty when models disagree. Severity is determined by environment + cascade rules (production + cascade + 2+ resources = P1). Stage 3: The `RemediationEngine` matches classified incidents to playbooks only when confidence >= 0.95 and a matching playbook exists. Playbooks have precondition checks, actions, post-check validation, and rollback steps. Execution is rate-limited to 3 per playbook per hour, and specific resources can be excluded from auto-remediation.

**Alternatives Considered:**
- **Deep learning for classification:** Requires GPU infrastructure and more training data than available at launch (6 months of incident history). Random forest trains on structured metadata and achieves 92% accuracy with monthly retraining on resolved incidents.
- **Rule-based triage only:** Cannot handle novel incident patterns or adapt to changing infrastructure topology. Works for known scenarios but misses emerging failure modes.
- **Fully automated remediation without confidence gating:** Too risky without high confidence. The 0.95 threshold ensures auto-remediation only triggers when the classification is highly reliable, and even then, P1 production incidents require human approval via the Trigger.dev human-in-the-loop workflow.

**Consequences:**
- Alert noise reduced from 500 to 87 meaningful incidents per month (83% reduction) through deduplication and correlation.
- Auto-remediation resolves 67% of incidents end-to-end with MTTR reduced from 45 minutes to 12 minutes.
- Decision support packages (similar past incidents, suggested steps, diagnostic commands, escalation contacts) are generated for incidents that do not qualify for auto-remediation.
- The confidence-gating approach means some correctly-classified incidents are not auto-remediated because the model confidence falls below 0.95, requiring human intervention for borderline cases.
- Monthly model retraining on resolved incidents creates a feedback loop that improves classification accuracy over time.
