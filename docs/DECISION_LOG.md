# Decision Log: Infrastructure Automation Platform

**Last Updated:** February 2025

This document records key technical and product decisions made during the development of the Infrastructure Automation Platform. Each entry captures the context, options considered, decision made, and the reasoning behind it.

---

## DEC-001: Temporal vs. Airflow vs. Step Functions for Workflow Orchestration

**Date:** March 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Platform Engineering Lead

**Context:**
Provisioning workflows are long-running (hours to days when approvals are involved), must survive platform restarts, require human-in-the-loop approval gates, and need per-step retry with idempotency. We needed an orchestration engine that could handle all of this without custom state management.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Temporal** | Durable execution (survives crashes), native signal/query for human-in-the-loop, workflows are code (Python/Go), self-hosted or cloud, per-step retry and timeout built in | Newer technology, smaller community than Airflow, operational overhead of running Temporal server |
| **B: Apache Airflow** | Large community, well-understood, good for batch DAGs | Designed for scheduled batch jobs, not long-running interactive workflows. No native human-in-the-loop. DAGs are static, not code-driven. |
| **C: AWS Step Functions** | Managed service, integrates with AWS natively | AWS lock-in, JSONPath state management gets painful for complex logic, 1-year max execution, callback tasks require additional infrastructure |
| **D: Custom state machine (PostgreSQL + Celery)** | Full control, no new infrastructure dependency | We would be building our own Temporal. State management, retry logic, crash recovery, and approval signals all become our maintenance burden. |

**Decision:** Option A, Temporal.

**Reasoning:**
- The approval gate was the deciding factor. When a provisioning request needs VP approval, the workflow must pause indefinitely and resume exactly where it left off when the approver acts. Temporal's signal primitive does this natively. Airflow has no equivalent without external polling. Step Functions require a callback task with SQS or API Gateway plumbing.
- Durable execution means if the platform crashes during step 3 of a 7-step provisioning workflow, Temporal replays the workflow history and resumes at step 3. We do not re-provision resources that were already created. With Celery, we would need to build checkpoint logic in every task.
- Workflows are Python code. Branching, retries, timeouts, and error handling are just if/else, try/except, and decorators. Airflow DAGs and Step Functions state machines both require declarative definitions that get unwieldy for our branching logic (policy validation can result in auto-approve, route-to-approval, or reject, each with different downstream paths).
- Self-hosted option means we run Temporal on the same Kubernetes cluster as the rest of the platform. No cloud lock-in, no egress to external services for workflow orchestration.

**Consequences:**
- Need to run and maintain Temporal server (adds ~2GB memory, 1 vCPU to cluster)
- Team needs to learn Temporal SDK patterns (activity functions, workflow definitions, signal handling)
- Temporal UI available for workflow debugging and visibility
- All workflow state is in Temporal's database, not our application database (requires separate backup strategy)

**Revisit trigger:** If Temporal operational burden becomes significant, evaluate Temporal Cloud (managed service).

---

## DEC-002: OPA/Rego for Policy Engine vs. Hardcoded Rules vs. Commercial GRC

**Date:** April 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Security/Compliance Officer

**Context:**
Every provisioning request and every managed resource needs to be evaluated against security and compliance policies (NIST 800-53, FedRAMP, SOC 2, plus organization-specific rules). Policies change when frameworks are updated, when new controls are added, and when organizational risk appetite shifts. We needed a policy evaluation approach that could keep up without engineering deployments for every change.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Hardcoded rules (Python if/else)** | Fast to build initially, no new technology | Every policy change requires code change, PR review, deployment. Compliance team can't update policies independently. Testing is manual. |
| **B: OPA with Rego policies** | Declarative policies, version-controlled, testable with `opa test`, < 100ms evaluation, decoupled from application code | New language (Rego) for compliance team to learn, self-hosted OPA server |
| **C: Commercial GRC (ServiceNow GRC, Archer)** | Built for compliance workflows, audit evidence collection, attestation | Designed for manual audit processes, not real-time evaluation. Can't evaluate policy against live infrastructure state. Expensive licensing. |
| **D: AWS Config Rules / Azure Policy** | Native cloud integration, managed service | Cloud-provider-specific. Rules are limited to what the provider supports. Can't enforce organization-specific policies. |

**Decision:** Option B, OPA with Rego policies stored in Git.

**Reasoning:**
- The compliance officer needs to update policies without filing an engineering ticket. With OPA, she writes a Rego policy, tests it with `opa test`, submits a pull request, and after review the policy is live. With hardcoded rules, she describes the policy in a Jira ticket, an engineer translates it to Python, and two weeks later it's deployed. That lag creates compliance exposure windows.
- Rego policies are testable. We write unit tests for each policy (given this resource configuration, expect pass/fail). This is impossible with commercial GRC tools that are checklist-based.
- Evaluation speed matters. OPA evaluates policies in < 100ms. This is critical because policy evaluation happens in the provisioning request path. A slow policy engine adds latency to every provisioning request.
- Policies are version-controlled with Git SHA tracking. Every compliance scan records which policy version was used. Auditors can trace exactly which version of which policy was in effect for any historical scan.
- Cloud-native rules (AWS Config, Azure Policy) only cover their own provider and only the checks they offer. We need to enforce custom policies like naming conventions, cost thresholds, and team-specific access rules.

**Consequences:**
- Compliance team needs to learn Rego (invested 2 days of training, plus example policies as templates)
- OPA server runs as a sidecar on the API pod (minimal resource overhead)
- All policy changes go through Git PR review (compliance officer + platform engineer must both approve)
- Policy test suite runs in CI before any policy is deployable

---

## DEC-003: Containerized Digital Twins vs. Persistent Staging Environment

**Date:** May 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Platform Engineering Lead

**Context:**
Engineers refused to deploy infrastructure changes without testing, but the existing testing approach was either "test in production and hope" or "maintain a permanent staging environment that costs $45K/month and constantly drifts from production." We needed a simulation approach that was accurate, affordable, and always up to date.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Persistent staging environment** | Always available, familiar to engineers | $45K/month, drifts from production over time, shared by all teams (conflicts and queuing), configuration updates are manual |
| **B: Containerized digital twins (ephemeral)** | Generated from production config (always accurate), spun up on demand, torn down after test, $200/run | Not 100% identical to production (containerized simulation vs. real cloud resources), spin-up takes 10 minutes |
| **C: Production canary only (no pre-production testing)** | No simulation infrastructure needed | All testing happens in production. Higher risk of customer-impacting failures. Rollback is the only safety net. |
| **D: LocalStack / cloud emulation** | Cheap, fast | Emulation fidelity is low for complex services (RDS, ALB, IAM policies). False confidence in tests that pass locally but fail in real cloud. |

**Decision:** Option B, Containerized digital twins with Docker Compose mirroring production topology.

**Reasoning:**
- Cost was the clearest differentiator. At 50 simulation runs per month, ephemeral twins cost $10K/month. The persistent staging environment costs $45K/month. Same accuracy (actually better, because twins are generated from current production config while staging drifts).
- Staging environment drift was the real problem with Option A. We tracked 23 configuration differences between staging and production over a 3-month period. 4 of those differences caused tests to pass in staging but fail in production. The twin is generated from the same Terraform state that defines production, so it matches by construction.
- Spin-up time of 10 minutes is acceptable. Engineers submit a deployment, the simulation runs, and they get results in 15-20 minutes total. This fits naturally into their workflow because they're not sitting and waiting; they move on to other work and get a notification when results are ready.
- The twin doesn't need to be 100% identical to production for every dimension. It needs to be accurate enough to catch the categories of issues we care about: integration failures, performance regressions, chaos resilience, and configuration regressions. Benchmarking showed 96.2% simulation accuracy vs. 95.8% for the persistent staging environment.

**Consequences:**
- Need Docker Compose templates that mirror production topology (maintained automatically from Terraform state)
- Simulation workers need beefy machines (16 vCPU, 32GB RAM) to run the full twin
- Spin-up time means simulation is asynchronous, not instant. Engineers submit and wait for notification.
- Some cloud-specific behaviors (IAM policy evaluation, VPC networking nuances) are mocked, not real. Acknowledged as an acceptable gap.

**Revisit trigger:** If simulation accuracy drops below 93% or if engineers report false confidence from simulations that miss real issues.

---

## DEC-004: Random Forest + spaCy vs. Deep Learning for Incident Classification

**Date:** June 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Data Science Lead

**Context:**
The incident response service needs to classify incoming alerts by type (service_health, storage, network, database, security, deployment, cost) and predict severity (P1/P2/P3) in under 30 seconds. The classification drives automated remediation routing, so accuracy and speed both matter.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Random forest (structured features) + spaCy (text classification)** | Fast inference (< 1 second), works well with moderate data volume (500 incidents/month), explainable (feature importance), no GPU required | May plateau on accuracy as patterns get more complex, two-model architecture to maintain |
| **B: Fine-tuned transformer (BERT/RoBERTa)** | State-of-the-art text classification accuracy, single model for all features | Requires GPU for inference (cost + complexity), prone to overfitting with 500 incidents/month training data, harder to explain predictions to on-call engineers |
| **C: LLM classification (Claude/GPT-4 per incident)** | Highest potential accuracy, zero training data needed, can handle novel incident types | Latency (3-10 seconds per API call), cost ($0.01-0.05 per classification at 500/month), external API dependency on critical incident path |
| **D: Rule-based (regex + keyword matching)** | Simple, fast, no ML infrastructure | Brittle, doesn't generalize to novel alert patterns, maintenance burden grows linearly with new alert types |

**Decision:** Option A, Random forest on structured alert metadata + spaCy text classification on alert messages.

**Reasoning:**
- Training data volume was the primary concern. After 6 months we had ~3,000 labeled incidents. That is plenty for random forest and spaCy but insufficient for a fine-tuned transformer to generalize without overfitting. We benchmarked: random forest achieved 92% accuracy, spaCy achieved 89%, and the ensemble (RF on structured features, spaCy on text, weighted combination) achieved 92%. A fine-tuned BERT achieved 88% accuracy, worse because of overfitting on the small dataset.
- No GPU infrastructure means no additional operational complexity. Random forest and spaCy run on CPU, on the same worker nodes that run everything else. A transformer would require a dedicated GPU instance ($500+/month) or GPU-equipped workers.
- Explainability matters for trust. When the model classifies an incident as "database, P2" and routes it to the database team, the on-call engineer needs to understand why. Random forest provides feature importance (e.g., "alert source: CloudWatch RDS, resource type: rds_instance, historical pattern: connection_pool_exhaustion"). Transformers provide attention weights that are harder to interpret.
- LLM classification (Option C) was tempting but puts an external API call on the critical incident response path. If Claude or GPT-4 is down or slow during our own production incident, the incident response system itself is degraded. Unacceptable for a system that must be always-on.

**Consequences:**
- Monthly model retraining pipeline using the rolling 6-month window of resolved incidents
- Model accuracy dashboard monitoring classification accuracy against human-validated sample
- If accuracy drops below 88%, automatic fallback to rule-based routing while data science investigates
- Ensemble approach means two models to maintain (RF and spaCy), but both are lightweight

**Revisit trigger:** If training data exceeds 10,000 labeled incidents (at that volume, a transformer may outperform the ensemble).

---

## DEC-005: Vault Dynamic Secrets vs. Long-Lived IAM Keys

**Date:** June 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Security Lead

**Context:**
The provisioning service needs cloud provider credentials to execute Terraform and Ansible against AWS/Azure. We needed to decide how to manage these credentials securely.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Long-lived IAM access keys in environment variables** | Simple, fast to set up | Keys never rotate unless manually done, if leaked they grant persistent access, keys shared across all workflows |
| **B: Long-lived IAM keys in Vault (static secrets)** | Centralized secret management, audit trail, access control | Keys still long-lived, just stored in a better place. If compromised, attacker has persistent access until manual rotation. |
| **C: Vault Dynamic Secrets (AWS STS)** | Short-lived credentials (1-hour TTL) per workflow run, scoped to requested resource types, auto-revoke on workflow completion or TTL expiry | Vault dependency on critical provisioning path, slightly higher latency for credential issuance |
| **D: AWS IAM roles for service accounts (IRSA)** | No credentials to manage, native Kubernetes integration | Only works for AWS, doesn't solve Azure/GCP, same role shared across all provisioning workflows (no per-workflow scoping) |

**Decision:** Option C, Vault Dynamic Secrets with per-workflow STS session tokens.

**Reasoning:**
- The blast radius question was decisive. With long-lived keys, a compromised credential grants access to everything those keys can do, indefinitely. With dynamic secrets, a compromised token is scoped to the specific resource types requested by that workflow and expires in 1 hour. The worst case is dramatically smaller.
- Per-workflow credential scoping means a workflow provisioning a dev environment gets a token that can only create the resource types in the dev template. It cannot touch production resources even if the token is intercepted. With shared long-lived keys, every workflow uses the same powerful credentials.
- Auto-revocation eliminates credential cleanup. If a workflow fails mid-execution and is never retried, the token expires automatically. No orphaned credentials accumulating. No rotation scripts to maintain.
- Vault is already in our stack for other secret management. The marginal cost of using its AWS secrets engine is near zero. The AWS secrets engine generates STS tokens via AssumeRole, which is an AWS-native pattern.
- IRSA (Option D) would be ideal for AWS-only, but we need multi-cloud support. A Vault-based approach works identically for AWS (STS), Azure (service principal tokens), and GCP (OAuth tokens).

**Consequences:**
- Vault is on the critical path for provisioning. If Vault is down, no provisioning can happen. Mitigated by Vault HA deployment with auto-unseal.
- Credential issuance adds ~500ms latency per workflow step that needs cloud access. Acceptable.
- Every Temporal workflow includes a Vault lease ID in its state. On workflow completion (success or failure), the lease is explicitly revoked.
- Audit trail: every credential issuance logged in Vault audit log with workflow ID, resource scope, and TTL.

---

## DEC-006: TimescaleDB for Metrics vs. Prometheus Long-Term Storage vs. Datadog Only

**Date:** July 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Platform Engineering Lead

**Context:**
The observability service ingests infrastructure metrics at 1-second granularity across 200+ resources, each producing 15-20 metric types. That is approximately 50,000 data points per second at steady state. We needed to store this data for anomaly detection baselines (requires 90+ days of history), dashboard queries (real-time to 2-year lookback), and trend analysis.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Datadog only (SaaS)** | Already deployed for collection, built-in dashboards and alerting, no infrastructure to manage | Retention costs scale with metric volume ($0.05/metric/month), limited to Datadog query language, data lock-in, custom anomaly detection requires Datadog ML (limited) |
| **B: Prometheus + Thanos** | Industry standard for Kubernetes metrics, Thanos adds long-term storage on S3 | Not designed for high-cardinality metrics at our scale, PromQL is powerful but limited for complex anomaly detection, operational complexity of running Thanos |
| **C: TimescaleDB** | SQL interface (team already knows PostgreSQL), continuous aggregates for rollups, 90%+ compression, hypertables handle time-series natively, runs on same PostgreSQL infrastructure | Another database to manage, less community tooling than Prometheus for Kubernetes-native metrics |
| **D: InfluxDB** | Purpose-built for time series, good write performance | Flux query language is a barrier, clustering requires Enterprise license ($$$), fewer SQL integrations |

**Decision:** Option C, TimescaleDB as metrics storage with Datadog retained for collection and alerting.

**Reasoning:**
- The anomaly detection queries drove the decision. Our anomaly detection engine calculates z-scores and IQR against seasonal baselines (time-of-day, day-of-week). This requires JOINs between current metrics and baseline tables, grouped aggregations, and percentile calculations. SQL handles this naturally. Doing the same in PromQL or Datadog's query language requires workarounds.
- Continuous aggregates solve the hot/cold data problem automatically. 1-second raw data is expensive to query across 90 days. TimescaleDB materializes 1-minute and 1-hour rollups automatically. Dashboard queries hit the rollups (fast), anomaly detection hits raw data for the recent window and rollups for baselines (efficient).
- Compression at 90%+ means 90 days of raw data at 50K points/second is manageable storage-wise (~200GB compressed vs. ~2TB uncompressed).
- The team already knows PostgreSQL. TimescaleDB is a PostgreSQL extension, so all existing tooling, connection libraries, and knowledge transfer directly.
- We keep Datadog for what it does best: agent-based collection, real-time alerting, distributed tracing, and pre-built integration dashboards. Datadog feeds data into TimescaleDB via the Datadog API, giving us the best of both worlds.

**Consequences:**
- Dedicated TimescaleDB instance to manage (separate from main PostgreSQL)
- Data pipeline: Datadog agents collect metrics, platform service writes to TimescaleDB via insert API
- Grafana connects to TimescaleDB for custom dashboards (alongside Datadog dashboards for standard views)
- Retention policies managed by TimescaleDB: 90 days raw, 1 year 1-minute aggregates, 2 years 1-hour aggregates

---

## DEC-007: Tenant-Scoped Rate Limiting with Priority Queues

**Date:** August 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Platform Engineering Lead

**Context:**
During a load test, a developer's script submitted 200 provisioning requests in 3 minutes. This flooded the Temporal provisioning queue, consumed all worker capacity, and blocked an incident remediation workflow from executing for 8 minutes. We needed to prevent one tenant or one user from monopolizing platform resources.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Global rate limit (X requests/minute total)** | Simple to implement | Doesn't differentiate between tenants. One noisy tenant blocks everyone. |
| **B: Per-tenant rate limiting at API layer** | Fair resource allocation, prevents one tenant from starving others | Doesn't solve priority between provisioning and incident response |
| **C: Per-tenant rate limiting + separated Temporal task queues with priority** | Fair allocation AND incident response is never blocked by provisioning load | More complex queue configuration, need to manage multiple worker pools |
| **D: Just add more workers** | No rate limiting needed if capacity is always sufficient | Expensive, doesn't solve a genuine burst from a bad script, incident response still competes with provisioning on shared queue |

**Decision:** Option C, Per-tenant rate limiting at the API layer combined with separated Temporal task queues.

**Reasoning:**
- The 8-minute incident response delay was the wake-up call. Incident remediation must execute within seconds, regardless of what else is happening on the platform. Sharing a queue with provisioning means provisioning volume directly impacts incident response latency. Unacceptable.
- Per-tenant rate limiting is implemented in Redis with sliding window counters. Each endpoint has a per-tenant limit: provisioning at 10/minute, deployments at 5/minute, incident ingestion at 1000/minute. The limits are configurable per organization in the settings JSONB.
- Temporal task queues are separated by service: `provisioning-queue`, `simulation-queue`, `incident-queue`, `compliance-queue`. Each has dedicated workers. Incident workers are provisioned at 2x the calculated need so there is always spare capacity.
- Per-tenant concurrency limits on provisioning (default: 5 parallel workflows) prevent one tenant from consuming all provisioning worker capacity even within their rate limit.

**Consequences:**
- Four Temporal worker deployments instead of one (slightly more Kubernetes resource usage)
- Rate limit configuration per tenant stored in organization settings (adjustable by admin)
- Redis dependency for rate limiting (already in stack for caching)
- Monitoring: alert if incident queue depth > 0 for more than 30 seconds (means workers are backed up)

---

## DEC-008: Terraform Plan Diff View for Approvers

**Date:** September 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Infrastructure Director

**Context:**
When a provisioning request requires approval, the approver received an email saying "Provisioning request #1234 requires your approval" with a link to the ServiceNow portal. The portal showed the request parameters but not what Terraform would actually create. Approvers were signing off on requests without understanding the infrastructure impact, or worse, rejecting requests because they couldn't verify what would happen.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: Show raw `terraform plan` output** | Complete information, no interpretation needed | Terraform plan output is verbose and hard to read for non-engineers. A production environment plan can be 500+ lines. |
| **B: Structured diff view with cost delta** | Human-readable summary of create/modify/destroy, color-coded, estimated cost impact | Requires parsing and structuring plan output, might miss nuance in raw output |
| **C: No change (approve based on request parameters only)** | Simplest | Approvers don't know what they're approving. Governance theater. |

**Decision:** Option B, Structured diff view with full plan available on expand.

**Reasoning:**
- The Infrastructure Director (primary approver) said directly: "I'm not going to read 500 lines of Terraform output. Show me what's being created, what it costs, and whether it passed policy checks. If I need details, let me drill into the raw plan."
- The structured summary shows: resources being created (green), modified (yellow), destroyed (red), estimated monthly cost delta, and policy evaluation results. This is generated by parsing `terraform plan -json` output and extracting the resource changes.
- Raw plan output is available behind an "expand details" toggle for the rare cases where the approver wants to see exact configuration values.
- Policy evaluation results are shown inline so the approver knows which controls passed and why approval was required (e.g., "production access" or "estimated cost exceeds $500/month").

**Consequences:**
- Need to parse `terraform plan -json` output and generate structured summary (stored as `terraform_plan_summary` JSONB in provisioning_requests table)
- Portal renders diff view with color coding (green/yellow/red) and cost delta
- Full raw plan output stored in `terraform_plan_output` text field for audit trail and drill-down
- Approval decisions recorded with comment, timestamp, and approver identity

---

## DEC-009: Playbooks as YAML in Git vs. Database-Stored Playbooks

**Date:** October 2024
**Status:** Accepted
**Decider:** Jacob George (PM), Platform Engineering Lead

**Context:**
Remediation playbooks define what the incident response system does automatically when it classifies an incident. We needed to decide where playbooks live and how they're updated.

**Options Considered:**

| Option | Pros | Cons |
|---|---|---|
| **A: YAML files in Git** | Version-controlled, PR review process, testable in CI, audit trail via git log, engineers can review diffs | Deployment required to update playbooks, not editable by non-engineers without Git knowledge |
| **B: Database-stored with admin UI** | Non-engineers can create/edit playbooks via UI, changes are instant | No version control (need to build our own), no PR review process, no CI testing, harder to audit history |
| **C: Both (Git as source of truth, synced to database)** | Best of both worlds: Git review process + database for runtime | Sync complexity, potential for divergence between Git and database |

**Decision:** Option C, YAML in Git as source of truth, synced to database on merge.

**Reasoning:**
- Playbooks are code. A bad playbook can restart the wrong service or escalate the wrong team. They need the same review rigor as application code: PR review, CI testing, and approval before deployment.
- But at runtime, the incident response service needs fast access to playbook definitions. Reading YAML files from disk on every incident is fragile (file not found, stale cache). Syncing to the database on merge means the runtime reads from a fast, reliable source.
- The sync process is a CI pipeline step: on merge to main, a script reads all playbook YAML files, validates them, and upserts into the playbooks table. The `git_sha` column records which commit each playbook came from.
- Non-engineers (ops managers who want to tweak a threshold) can edit the YAML in a GitHub web editor and submit a PR. The platform engineer reviews the YAML changes, CI validates the playbook structure, and on merge it syncs automatically.

**Consequences:**
- CI pipeline validates playbook YAML schema on every PR (prevents malformed playbooks)
- Database playbooks table has a `git_sha` column linking each record to the source commit
- If sync fails, the previous version remains in the database (safe default)
- Playbook execution logs reference both playbook ID and git_sha for full traceability

---

## DEC-010: Tiered Approval Gates Over Full Self-Service Provisioning

**Date:** February 2025
**Status:** Accepted (supersedes earlier approach)
**Decider:** Jacob George (PM), Security/Compliance Officer, Engineering Lead

**Context:** The original vision was full self-service — any engineer could provision any environment type through the platform without approval. This was the key selling point to engineering leadership: "No more waiting 3-4 days for infrastructure."

**What Happened:** Security review at Week 6 blocked the launch. The security team identified three risks: (1) Engineers could provision production-grade environments for testing, running up costs ($2,100/environment), (2) No guardrails on environment configurations that included elevated IAM permissions, (3) No audit trail connecting provisioning to approved project work. The CISO's feedback: "Self-service is great, but 'anyone can create anything' is not self-service — it's chaos."

**Decision:** Implemented three-tier approval model. Tier 1 (dev/sandbox): fully self-service, auto-approved, cost-capped at $500/month. Tier 2 (staging/integration): requires team lead approval, auto-approved if within project budget. Tier 3 (production/elevated access): requires director approval + security review, SLA of 4 hours.

**Rationale:** 85% of requests are Tier 1 (truly self-service). Tier 2 adds minimal friction (team lead approval is typically <30 minutes). Tier 3 represents only 5% of requests and these genuinely need oversight. Net result: median provisioning time went from 3-4 days to 6 hours (weighted across tiers), not the <1 hour we originally promised but acceptable.

**Consequences:** Had to rebuild the provisioning workflow to include approval routing (1.5 weeks). Required policy definitions per tier (worked with security to co-author). Needed to add budget tracking per project. But the security team became advocates for the platform instead of blockers. The CISO now demos it to other departments.

**Lesson:** Getting security as a co-designer rather than a gate reviewer turned a blocker into a champion. The tiered model was a better product because it addressed real risks we'd overlooked.
