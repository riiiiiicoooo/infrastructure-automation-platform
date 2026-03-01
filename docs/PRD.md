# Product Requirements Document: Infrastructure Automation Platform

**Product:** Infrastructure Automation Platform
**Author:** Jacob George, Principal Product Manager
**Last Updated:** February 2025
**Status:** Production (v2.0)
**Stakeholders:** Platform engineering, operations, security/compliance, infrastructure leadership, development teams

---

## 1. Overview

### 1.1 Problem Statement

Enterprise infrastructure teams managing cloud environments across government, defense, financial services, and manufacturing sectors are bottlenecked by manual processes at every stage of the infrastructure lifecycle. The current state has five critical problems:

1. **Provisioning is slow and gatekept.** Operations teams manually provision cloud infrastructure through console clicks and ad-hoc scripts. A single environment deployment takes 3-4 days. Only 3 people on the team know how to do it, creating a hard bottleneck. Monthly provisioning capacity is capped at 12 environments regardless of demand.

2. **Configuration errors are endemic.** Manual provisioning produces an 18% configuration error rate. Misconfigured security groups, missing monitoring agents, incorrect network rules, and forgotten CMDB entries create security gaps and operational blind spots. Each error takes an average of 4 hours to diagnose and remediate after discovery.

3. **Deployments go to production untested.** There is no simulation environment to validate infrastructure changes before they hit production. Engineers are reluctant to deploy because a bad change can halt production lines ($50K/hour in manufacturing), take down payment processing, or violate compliance controls. Deployment velocity has stalled at 2 per month because the risk is too high.

4. **Incident response is reactive.** Operations teams triage 500+ alerts per month across cloud infrastructure, application services, and network components. Every incident requires manual investigation. Mean time to resolution is 45 minutes. The team cannot distinguish root causes from cascading symptoms, so they chase the wrong alerts while the real issue persists.

5. **Compliance is verified after the fact.** Security and regulatory requirements (NIST 800-53, FedRAMP, SOC 2) are checked manually after deployment. Audit preparation consumes weeks of engineering time. Non-compliant resources sit in production until someone notices, creating exposure windows.

### 1.2 Product Vision

Build a platform that treats infrastructure as a product: self-service provisioning with automated compliance enforcement, simulation-validated deployments, and intelligent incident response. The platform should enable any qualified engineer to safely provision and manage infrastructure without depending on a specialized operations team, while giving leadership visibility into cost, compliance, and operational health.

### 1.3 Success Criteria

| Metric | Target | Measurement Method |
|---|---|---|
| Environment deployment time | < 8 hours (from 3-4 days) | Time from request submission to active environment |
| Configuration error rate | < 3% (from 18%) | Errors caught in post-provisioning validation scan |
| Self-service adoption | 40+ engineers (from 3) | Unique users completing provisioning requests per quarter |
| Issues caught pre-production | > 90% | Issues identified in simulation / total issues |
| Production incidents from deployments | < 3/month (from 12) | Incidents tagged to deployment changes |
| Mean time to resolution (MTTR) | < 15 minutes (from 45) | Alert triggered to incident resolved |
| Auto-resolution rate | > 60% | Incidents resolved without human intervention |
| Compliance scan coverage | 100% continuous (from quarterly manual) | Resources validated against policy framework |

---

## 2. Users and Personas

### 2.1 Primary Personas

**Platform Engineer (Marcus)**
- Role: Senior Platform Engineer, manages cloud infrastructure for the organization
- Context: Handles 30-50 provisioning requests per month, maintains Terraform modules, triages production incidents
- Pain points: Buried in manual provisioning requests that prevent him from doing architecture work. On-call rotation is exhausting because alert volume is unmanageable. Spends 40% of time on compliance documentation.
- Goals: Automate the repetitive work so he can focus on platform improvements. Reduce on-call burden. Get ahead of compliance instead of scrambling before audits.
- Technical comfort: High. Writes Terraform, Ansible, Python daily. Comfortable with APIs and CLI tools.
- Key workflow: Review provisioning request -> validate configuration -> provision infrastructure -> configure monitoring -> register in CMDB -> generate compliance docs

**Application Developer (Priya)**
- Role: Senior Software Engineer, builds and deploys application services
- Context: Needs new environments for feature development, testing, staging, and production releases. Currently submits tickets to the ops team and waits 3-4 days.
- Pain points: Can't get infrastructure when she needs it. Deployment process is opaque. Has no visibility into whether her environment meets compliance requirements until someone tells her it doesn't.
- Goals: Self-service infrastructure provisioning that takes hours, not days. Confidence that what she deploys is safe and compliant. Clear visibility into environment status and costs.
- Technical comfort: Moderate for infrastructure. Comfortable with code and APIs but doesn't write Terraform or Ansible. Needs a UI or simplified CLI.
- Key workflow: Submit infrastructure request -> specify requirements (compute, storage, network, security level) -> wait for provisioning -> deploy application code -> monitor

**Infrastructure Director (Kevin)**
- Role: VP of Infrastructure, owns budget and operational accountability for all environments
- Context: Manages a $4M+ annual cloud budget across 200+ environments. Reports to CTO on operational metrics, cost efficiency, and compliance posture. Gets called when major incidents happen.
- Pain points: No real-time visibility into infrastructure costs until the monthly bill arrives. Compliance audit preparation takes his team offline for weeks. Can't answer basic questions like "how many environments do we have" or "are we compliant" without manual investigation.
- Goals: Dashboard showing cost, compliance, and operational health in real time. Predictable infrastructure spend. Confidence that regulatory requirements are continuously met, not just at audit time.
- Technical comfort: Low. Reviews dashboards and reports. Does not interact with infrastructure tooling directly.
- Key workflow: Review cost and compliance dashboards -> approve high-cost provisioning requests -> review incident trends -> present operational metrics to leadership

### 2.2 Secondary Personas

**Security/Compliance Officer** - Defines compliance policies (NIST 800-53, FedRAMP controls), reviews audit reports, validates that automated enforcement matches policy intent
**Release Manager** - Coordinates deployment schedules, approves production rollouts, manages change advisory board (CAB) processes
**Finance/Procurement** - Tracks cloud spend against budget, reviews cost allocation by team and project

---

## 3. User Flows

### 3.1 Core Flow: Self-Service Provisioning

```
Developer                        Platform                         Platform Engineer
   |                               |                                    |
   |-- Submit request via portal   |                                    |
   |   (compute, storage, network, |                                    |
   |    security level, project)   |                                    |
   |                               |-- Validate against policies        |
   |                               |   (NIST controls, budget, quotas)  |
   |                               |                                    |
   |                               |   [If policy violation]            |
   |<- Rejection with explanation  |                                    |
   |                               |                                    |
   |                               |   [If high-cost or elevated access]|
   |                               |-- Route for approval ------------->|
   |                               |                     Approve/deny ->|
   |                               |                                    |
   |                               |   [If approved or auto-approved]   |
   |                               |-- Generate Terraform templates     |
   |                               |-- Execute dry-run validation       |
   |                               |-- Provision infrastructure         |
   |                               |-- Apply security hardening         |
   |                               |-- Configure monitoring + alerting  |
   |                               |-- Register in CMDB                 |
   |                               |-- Generate compliance report       |
   |                               |                                    |
   |<- Notification: ready         |                                    |
   |   (connection details,        |                                    |
   |    compliance status,         |                                    |
   |    estimated monthly cost)    |                                    |
```

### 3.2 Deployment Flow: Simulation and Progressive Rollout

```
Engineer submits infrastructure change (Terraform plan, Ansible playbook, config update)
  -> Platform spins up digital twin environment (containerized mirror of target)
  -> Runs automated test suite:
     - Integration tests (end-to-end workflows)
     - Performance tests (simulated peak load)
     - Chaos tests (injected failures)
     - Regression tests (existing functionality intact)
  -> Results dashboard shows pass/fail with details
  -> [If all pass] Engineer triggers canary deployment (1% of targets)
  -> Platform monitors KPIs: latency, error rate, throughput, resource utilization
  -> [If KPIs healthy after observation window] Expand to 10%
  -> [If KPIs healthy] Expand to 50% (requires manual approval)
  -> [If KPIs healthy] Expand to 100%
  -> [If KPIs degrade at any stage] Automatic rollback to previous state
```

### 3.3 Incident Response Flow

```
Monitoring detects anomaly (Datadog, Splunk, CloudWatch, Prometheus)
  -> Alert ingested by platform
  -> ML correlation engine groups related alerts (dedup + root cause mapping)
  -> NLP classifier categorizes incident type and predicts severity (P1/P2/P3)
  -> Automatic routing to appropriate team based on classification
  -> [If known pattern with playbook] Execute automated remediation
     - Service restart, log rotation, cache clear, traffic reroute
     - Validate fix via health checks
     - Close incident with auto-generated post-mortem
  -> [If unknown pattern or high severity] Route to on-call engineer
     - Pre-filled context: dependency graph, similar past incidents, recommended steps
     - Real-time collaboration via Slack/PagerDuty integration
     - Engineer resolves and documents resolution
     - Resolution feeds back into ML model for future classification
```

---

## 4. Functional Requirements

### 4.1 Provisioning Engine

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| PRV-01 | Self-service request portal with configurable templates per environment type (dev, staging, production) | P0 | ServiceNow integration for organizations using it |
| PRV-02 | Policy validation against security frameworks (NIST 800-53, FedRAMP, SOC 2) before provisioning | P0 | OPA/Rego policy engine |
| PRV-03 | Budget and quota enforcement per team/project | P0 | Prevent runaway cloud spend |
| PRV-04 | Dynamic Terraform template generation from approved patterns | P0 | Templates version-controlled in Git |
| PRV-05 | Dry-run validation before execution (terraform plan equivalent) | P0 | Show exactly what will be created before committing |
| PRV-06 | Automated security hardening via Ansible post-provisioning | P0 | CIS benchmarks, patching, agent installation |
| PRV-07 | Automatic CMDB registration with resource metadata and dependencies | P0 | Every resource tracked from creation |
| PRV-08 | Monitoring and alerting auto-configuration (Datadog agents, dashboards, alert rules) | P0 | No manual monitoring setup |
| PRV-09 | Compliance documentation auto-generation per provisioned environment | P1 | Audit-ready from day one |
| PRV-10 | Approval routing for high-cost or elevated-access requests | P0 | Configurable thresholds |
| PRV-11 | Environment decommissioning workflow with cleanup validation | P1 | Prevent orphaned resources |
| PRV-12 | Cost estimation displayed before request submission | P1 | Users see projected monthly cost |

### 4.2 Simulation and Testing

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| SIM-01 | Containerized digital twin environment mirroring production topology | P0 | Docker-based, spun up on demand |
| SIM-02 | Synthetic workload generation matching production traffic patterns | P0 | CPU, memory, network, disk I/O profiles |
| SIM-03 | Automated integration test execution on every change | P0 | Validates end-to-end workflows |
| SIM-04 | Performance test suite simulating peak load scenarios | P0 | Catch capacity issues before production |
| SIM-05 | Chaos engineering: inject network partitions, process crashes, disk failures | P1 | Test resilience under failure conditions |
| SIM-06 | Regression test suite ensuring existing functionality is preserved | P0 | No change should break something else |
| SIM-07 | Test results dashboard with pass/fail, duration, and failure details | P0 | Clear go/no-go signal |
| SIM-08 | Progressive rollout engine with configurable stages (1% -> 10% -> 50% -> 100%) | P0 | Each stage has observation window |
| SIM-09 | Automated rollback triggered by KPI degradation | P0 | Configurable thresholds per metric |
| SIM-10 | Manual approval gates at configurable expansion thresholds | P0 | Human checkpoint for production safety |

### 4.3 Incident Response

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| INC-01 | Multi-source alert ingestion (Datadog, Splunk, CloudWatch, Prometheus, PagerDuty) | P0 | Unified alert pipeline |
| INC-02 | ML-based alert correlation and deduplication within time windows | P0 | Reduce noise from 500 to <100 meaningful incidents |
| INC-03 | Root cause identification via dependency graph traversal | P0 | Distinguish cause from cascading symptoms |
| INC-04 | NLP-based incident classification (type, severity, team routing) | P0 | 92% accuracy target |
| INC-05 | Automated remediation playbooks for common failure patterns | P0 | Service restart, log rotation, cache clear, traffic reroute |
| INC-06 | Safety checks before automated remediation execution | P0 | Validate the fix won't make things worse |
| INC-07 | Decision support for human-triaged incidents (similar past incidents, recommended steps) | P1 | Pre-filled context for on-call engineers |
| INC-08 | ChatOps integration (Slack/Teams) for real-time incident collaboration | P1 | Notifications, status updates, commands |
| INC-09 | Auto-generated post-mortem reports for resolved incidents | P1 | Timeline, root cause, resolution, prevention recommendations |
| INC-10 | Feedback loop: resolved incidents improve future classification models | P0 | Model retraining monthly on new data |

### 4.4 Observability and Compliance

| ID | Requirement | Priority | Notes |
|---|---|---|---|
| OBS-01 | Infrastructure health dashboard (uptime, latency, error rates, resource utilization) | P0 | Grafana-based, real-time |
| OBS-02 | Cost dashboard with breakdown by team, project, environment, and resource type | P0 | Updated daily at minimum |
| OBS-03 | Anomaly detection on time-series metrics with adaptive baselines | P0 | MTTD target: < 15 minutes |
| OBS-04 | Continuous compliance scanning against policy frameworks | P0 | Every resource validated, not just spot checks |
| OBS-05 | Configuration drift detection and alerting | P1 | Flag resources that deviate from approved state |
| OBS-06 | Audit log with immutable record of all provisioning, changes, and incidents | P0 | Retention: 7 years minimum |
| OBS-07 | Compliance report generation (on-demand and scheduled) | P0 | Exportable for auditors |
| OBS-08 | Deployment velocity tracking (frequency, lead time, failure rate, MTTR) | P1 | DORA metrics |

---

## 5. Non-Functional Requirements

| Category | Requirement | Target |
|---|---|---|
| **Performance** | Provisioning request to active environment | < 6 hours for standard templates |
| **Performance** | Dry-run validation response | < 5 minutes |
| **Performance** | Simulation environment spin-up | < 10 minutes |
| **Performance** | Alert ingestion to classification | < 30 seconds |
| **Performance** | Automated remediation execution | < 3 minutes from trigger to resolution |
| **Performance** | Dashboard page load | < 3 seconds |
| **Availability** | Platform uptime | 99.9% (incident response must be always-on) |
| **Scalability** | Environments under management | 500+ simultaneously |
| **Scalability** | Alerts processed per hour | 10,000+ |
| **Scalability** | Concurrent provisioning requests | 20+ in parallel |
| **Security** | Authentication | SSO (SAML 2.0, OIDC) + MFA |
| **Security** | Secrets management | HashiCorp Vault integration |
| **Security** | Network isolation | VPC peering, no public endpoints for provisioned infrastructure |
| **Compliance** | Audit log retention | 7 years (immutable) |
| **Compliance** | FedRAMP Moderate readiness | Required within 12 months for government clients |

---

## 6. Technical Constraints

### 6.1 Orchestration Constraints

- Provisioning workflows must be durable. If the platform crashes mid-provisioning, it must resume where it left off, not restart. This rules out stateless job runners.
- Workflows must support human-in-the-loop approval signals without polling. The system must be able to pause execution and resume when an approver acts.
- Each provisioning step must be independently retryable without side effects (idempotent operations).

### 6.2 Infrastructure-as-Code Constraints

- All Terraform state must be stored remotely with locking (S3 + DynamoDB or equivalent). No local state files.
- Terraform modules must be versioned and pulled from an internal registry. Engineers cannot use arbitrary community modules without security review.
- Ansible playbooks must be tested with Molecule before promotion to production.
- All infrastructure changes must be traceable to a specific request, approver, and policy validation result.

### 6.3 ML/AI Constraints

- Incident classification models must be explainable. On-call engineers need to understand why the model classified an incident a certain way, not just receive a label.
- Automated remediation requires confidence threshold of > 95% on incident classification before executing. Below that, route to human.
- Model retraining runs monthly on resolved incident data. No real-time model updates to avoid instability.
- All model inputs and outputs logged for audit trail.

### 6.4 Compliance Constraints

- Policy engine must evaluate in < 100ms per request. Provisioning latency budget does not allow slow policy checks.
- Compliance policies must be version-controlled and auditable. Every policy change must have an author, timestamp, and approval.
- Resources that fail compliance scanning must be quarantined automatically (network isolation) until remediated.
- Encryption required for all data at rest (AES-256) and in transit (TLS 1.3).

---

## 7. Out of Scope (v1)

- Application deployment pipelines (CI/CD for application code, not infrastructure)
- Multi-cloud provisioning in a single request (AWS or Azure per request, not both simultaneously)
- Custom ML model training UI (data science team manages model retraining pipeline offline)
- Mobile application for incident response
- Cost optimization recommendations (v1 tracks costs, v2 recommends savings)
- Network automation for physical hardware (software-defined only in v1)
- Self-healing infrastructure beyond defined playbooks (no autonomous remediation without playbook match)

---

## 8. Phased Rollout

### Phase 0: Foundation (Weeks 1-8)

**Goal:** Prove that automated provisioning is faster and more accurate than manual process

- Self-service request portal with 3 standard environment templates (dev, staging, production)
- Policy validation against core security controls
- Terraform template generation and execution for AWS
- Basic Ansible hardening (security groups, monitoring agent, SSH config)
- CMDB registration
- Provisioning dashboard showing request status and history
- Audit logging for all provisioning actions

**Exit criteria:** 10 environments provisioned through the platform with 0 configuration errors. Average deployment time under 8 hours.

### Phase 1: Safe Deployments (Weeks 9-16)

**Goal:** Enable engineers to deploy infrastructure changes with confidence

- Containerized digital twin simulation environment
- Automated test suite (integration, performance, regression)
- Progressive rollout engine (1% -> 10% -> 50% -> 100%)
- Automated rollback on KPI degradation
- Deployment dashboard with real-time rollout status
- Manual approval gates at configurable thresholds
- Deployment history and audit trail

**Exit criteria:** 94%+ of issues caught in simulation. Production incidents from deployments drop below 3/month.

### Phase 2: Intelligent Operations (Weeks 17-24)

**Goal:** Reduce incident burden on operations teams through automation

- Multi-source alert ingestion pipeline
- ML alert correlation and deduplication
- NLP incident classification and severity prediction
- Automated remediation playbooks for top 10 incident types
- Decision support for human-triaged incidents
- Slack/PagerDuty integration for incident workflow
- Incident dashboard with trends, MTTR, and auto-resolution metrics
- Post-mortem report generation

**Exit criteria:** Alert noise reduced by 80%+. Auto-resolution rate above 60%. MTTR under 15 minutes.

### Phase 3: Continuous Compliance and Optimization (Weeks 25+)

**Goal:** Proactive compliance and cost management across all managed infrastructure

- Continuous compliance scanning against NIST/FedRAMP/SOC 2 controls
- Configuration drift detection and automated remediation
- Cost dashboards with team/project/environment breakdown
- Anomaly detection with adaptive baselines
- On-demand and scheduled compliance report generation
- Chaos engineering framework (scheduled failure injection)
- Self-service environment templates (teams create their own approved patterns)
- Cost optimization recommendations (idle resource detection, rightsizing)

---

## 9. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Automated provisioning creates misconfigured resources at scale | Medium | Critical | Dry-run validation before execution. Post-provisioning compliance scan. Quarantine resources that fail validation. |
| Automated remediation makes an incident worse | Medium | Critical | 95% confidence threshold before auto-execution. Safety checks validate fix before applying. Rollback capability on every remediation action. |
| Engineers bypass platform and provision manually | High | Medium | Compliance scanner detects unregistered resources. Policy enforcement blocks resources not provisioned through platform. Reporting to leadership on out-of-band provisioning. |
| ML models degrade over time as infrastructure patterns change | Medium | Medium | Monthly retraining on resolved incidents. Model accuracy monitoring dashboard. Alert when classification accuracy drops below 88%. |
| Simulation environment doesn't accurately mirror production | Medium | High | Automated configuration sync between simulation and production. Chaos tests validate failure modes match reality. Quarterly simulation accuracy review. |
| Terraform state corruption | Low | Critical | Remote state with locking. State backup before every operation. Import/recovery tooling tested quarterly. |
| Resistance from ops team who see automation as threat to their roles | Medium | Medium | Position as "automate the boring work so you can do architecture." Involve ops engineers in policy and playbook authoring. Publicly credit ops expertise embedded in automation. |

---

## 10. Dependencies

| Dependency | Owner | Risk Level | Notes |
|---|---|---|---|
| AWS / Azure cloud APIs | External | Low | Core infrastructure provider. Multi-cloud support mitigates single provider risk. |
| Terraform Cloud / Enterprise | External | Medium | State management and module registry. Self-hosted option available as fallback. |
| ServiceNow | External | Medium | Request intake and approval workflows. REST API integration. |
| Datadog | External | Medium | Metrics collection, alerting, dashboards. Agent deployment automated by platform. |
| Splunk | External | Low | Security log aggregation and SIEM. Already deployed in most target environments. |
| PagerDuty | External | Low | On-call routing and escalation. |
| HashiCorp Vault | External | Medium | Secrets management for provisioning credentials. |
| OPA (Open Policy Agent) | Open Source | Low | Policy engine. Self-hosted, no external dependency. |
| Active Directory / Okta | Customer | High | SSO and identity provider. Configuration varies by customer. |

---

## Appendix A: Supported Environment Templates (v1)

### Development Environment
- 1 EC2 instance (t3.medium) or equivalent
- 50GB EBS storage
- VPC with private subnet
- Security group: SSH from VPN only
- Datadog agent installed
- CMDB entry auto-created
- Auto-decommission after 30 days if unused
- Estimated cost: $85/month

### Staging Environment
- 2 EC2 instances (t3.large) with load balancer
- 100GB EBS storage + 50GB S3
- VPC with public and private subnets
- RDS instance (db.t3.medium)
- Security group: HTTP/HTTPS from internal only
- Full monitoring suite (Datadog + alerting)
- CMDB entry with dependency mapping
- Estimated cost: $420/month

### Production Environment
- Auto-scaling group (2-8 instances, c5.xlarge)
- 500GB EBS storage + 200GB S3
- Multi-AZ RDS (db.r5.large) with read replica
- VPC with public, private, and data subnets
- WAF and DDoS protection
- Full monitoring + PagerDuty integration
- Compliance scan on provisioning + continuous
- Requires VP-level approval
- Estimated cost: $2,800/month (baseline)

---

## Appendix B: Incident Classification Taxonomy

| Category | Subtypes | Auto-remediation Available |
|---|---|---|
| **Service Health** | Process crash, memory exhaustion, CPU spike, health check failure | Yes: restart, scale-up |
| **Storage** | Disk full, log rotation failure, backup failure | Yes: log rotation, cleanup, expand volume |
| **Network** | Connectivity loss, DNS failure, SSL certificate expiry, latency spike | Partial: DNS flush, cert renewal |
| **Database** | Connection pool exhaustion, replication lag, lock contention, slow queries | Partial: connection reset, kill long queries |
| **Security** | Unauthorized access attempt, compliance drift, vulnerability detected | No: route to security team |
| **Deployment** | Failed deployment, configuration drift, canary failure | Yes: automated rollback |
| **Cost** | Budget threshold exceeded, idle resource detected | No: notification only |

---

## Appendix C: Glossary

| Term | Definition |
|---|---|
| **IaC (Infrastructure as Code)** | Managing infrastructure through declarative configuration files rather than manual processes |
| **CMDB** | Configuration Management Database. Central inventory of all infrastructure resources and their relationships |
| **Digital Twin** | Containerized simulation environment that mirrors production topology for testing changes |
| **Progressive Rollout** | Deploying changes incrementally (1% -> 10% -> 50% -> 100%) with automated monitoring at each stage |
| **OPA (Open Policy Agent)** | Open-source policy engine that evaluates access and configuration policies written in Rego |
| **NIST 800-53** | Security and privacy controls framework published by the National Institute of Standards and Technology |
| **FedRAMP** | Federal Risk and Authorization Management Program. Standardized approach to security assessment for cloud products used by federal agencies |
| **MTTR** | Mean Time to Resolution. Average time from incident detection to resolution |
| **MTTD** | Mean Time to Detection. Average time from issue occurring to detection by monitoring |
| **DORA Metrics** | DevOps Research and Assessment metrics: deployment frequency, lead time, failure rate, MTTR |
| **Canary Deployment** | Deploying changes to a small subset of infrastructure first to detect issues before full rollout |
| **Chaos Engineering** | Deliberately injecting failures into systems to test resilience and uncover weaknesses |
| **Rego** | Policy language used by OPA. Declarative, designed for evaluating structured data against rules |
