# Metrics Framework: Infrastructure Automation Platform

**Last Updated:** February 2025

---

## 1. North Star Metric

**Infrastructure changes deployed successfully per week**

This metric captures the full value proposition: teams can ship infrastructure changes faster because provisioning is self-service, deployments are simulation-validated, and incidents are auto-resolved. It combines velocity (throughput) with safety (only successful deployments count) and is directly tied to the business outcome leadership cares about, which is faster, safer delivery of infrastructure changes.

**Baseline (manual process):** 2 deployments per month (~0.5/week)
**Target (with platform):** 14+ deployments per week
**Current:** 14.2 deployments per week (averaged across last 8 weeks)

A deployment counts as "successful" only if it completes rollout without rollback, passes post-deployment health checks, and produces zero P1/P2 incidents within 24 hours.

---

## 2. Input Metrics

These are the levers we can pull to improve the North Star.

### 2.1 Provisioning Speed and Quality

| Metric | Definition | Target | Current | Measurement |
|---|---|---|---|---|
| Environment deployment time | Request submission to active environment | < 8 hours | 5.8 hours (p50) | Temporal workflow timestamps |
| Configuration error rate | Errors caught in post-provisioning compliance scan | < 3% | 1.4% | Compliance scan results / total provisioned resources |
| Self-service adoption | Unique engineers completing provisioning requests per quarter | 40+ | 47 | Platform user activity |
| Template coverage | Percentage of provisioning requests satisfied by existing templates | > 90% | 88% | Requests using templates vs. custom requests |
| Policy validation pass rate | Percentage of requests that pass OPA validation on first submission | > 85% | 82% | OPA evaluation logs |

### 2.2 Deployment Safety

| Metric | Definition | Target | Current | Measurement |
|---|---|---|---|---|
| Issues caught pre-production | Issues identified in simulation / total issues found | > 90% | 94% | Simulation failures + production incidents per deployment |
| Simulation accuracy | Percentage of simulation verdicts confirmed by production behavior | > 95% | 96.2% | False positive + false negative tracking |
| Production incidents from deployments | Incidents tagged to a deployment change within 24 hours | < 3/month | 2.1/month | Incident-deployment correlation |
| Rollback rate | Percentage of deployments that trigger automated rollback | < 5% | 3.8% | Deployment status tracking |
| Time to rollback | Detection of KPI degradation to completed rollback | < 5 minutes | 3.2 minutes (p50) | Temporal workflow timestamps |

### 2.3 Incident Response

| Metric | Definition | Target | Current | Measurement |
|---|---|---|---|---|
| Mean time to detection (MTTD) | Issue occurring to first alert | < 5 minutes | 3.8 minutes | Anomaly detection latency |
| Mean time to resolution (MTTR) | Alert triggered to incident resolved | < 15 minutes | 12.4 minutes | Incident timestamps |
| Auto-resolution rate | Incidents resolved without human intervention | > 60% | 63% | Incident resolution_type field |
| Alert noise reduction | Raw alerts correlated into meaningful incidents | > 80% reduction | 83% | Raw alerts / correlated incidents per month |
| Classification accuracy | ML model classification matches human-validated label | > 90% | 92% | Monthly validation against 50 human-classified incidents |
| Playbook success rate | Automated remediation resolves the incident | > 80% | 84% | Playbook execution outcomes |

### 2.4 Compliance and Observability

| Metric | Definition | Target | Current | Measurement |
|---|---|---|---|---|
| Compliance scan coverage | Percentage of active resources scanned continuously | 100% | 100% | Resource count vs. scan count |
| Compliance pass rate | Resources passing all applicable controls | > 95% | 96.8% | Compliance scan results |
| Configuration drift detection time | Time from drift occurring to platform detection | < 1 hour | 42 minutes | Drift detection timestamps |
| Drift auto-remediation rate | Drifted resources auto-corrected without human action | > 70% | 74% | Drift scan outcomes |
| Audit log completeness | Percentage of platform actions with corresponding audit entry | 100% | 100% | Daily automated reconciliation |

---

## 3. Guardrail Metrics

These metrics should NOT degrade as we optimize for the North Star. If they move in the wrong direction, we pause and investigate.

| Metric | Acceptable Range | Alert Threshold | Why It Matters |
|---|---|---|---|
| Automated remediation making incidents worse | 0% | > 0% | Safety checks must prevent bad remediations. Any occurrence triggers immediate playbook review. |
| Unregistered resources (shadow IT) | 0 | > 5 | Resources provisioned outside the platform bypass policy validation and compliance scanning |
| Cross-org data exposure | 0% | > 0% | RLS failure. Zero tolerance. Automated tests run daily. |
| Platform uptime | > 99.9% | < 99.5% | Incident response must be always-on. Platform downtime during production incidents is unacceptable. |
| Vault credential leak | 0% | > 0% | Dynamic secrets should never appear in logs, config files, or error messages. Zero tolerance. |
| Cost overrun (unplanned) | < 5% over estimate | > 15% | Cost estimation must be accurate. Large overruns erode trust in self-service provisioning. |
| Terraform state corruption | 0 incidents | > 0 | State corruption blocks all operations on affected resources. Recovery is expensive. |

---

## 4. Business Impact Metrics

### 4.1 Operational Efficiency

| Metric | Before Platform | After Platform | Improvement |
|---|---|---|---|
| Environment deployment time | 3-4 days | 6 hours (p50) | 85% reduction |
| Environments provisioned per month | 12 (capacity limited) | 55+ (self-service) | 4.5x throughput |
| Configuration error rate | 18% | 1.4% | 92% reduction |
| Engineers who can provision infrastructure | 3 (ops specialists) | 47 (self-service) | 15x access |
| Audit preparation time per quarter | 3-4 weeks | 2 hours (report generation) | 98% reduction |

### 4.2 Incident Response

| Metric | Before Platform | After Platform | Improvement |
|---|---|---|---|
| Monthly alert volume (human-triaged) | 500+ | 87 (after correlation) | 83% noise reduction |
| MTTR | 45 minutes | 12.4 minutes | 73% faster |
| Production incidents from deployments | 12/month | 2.1/month | 82% reduction |
| On-call engineer burden (hours/week) | 20+ hours | 6 hours | 70% reduction |
| Incidents requiring human intervention | 100% | 37% | 63% auto-resolved |

### 4.3 Financial Impact

| Metric | Before Platform | After Platform | Improvement |
|---|---|---|---|
| Annual downtime cost (at $50K/hour) | $2.1M (42 hours unplanned) | $375K (7.5 hours) | $1.7M annual savings |
| Prevented downtime (pre-production detection) | $0 (no simulation) | $2.4M (estimated) | Issues caught before production |
| Compliance audit labor cost | $180K/year (manual preparation) | $12K/year (automated reports) | $168K annual savings |
| Cloud waste (untracked resources) | ~15% of spend ($600K/year on $4M budget) | < 2% ($80K/year) | $520K annual savings |
| Total annual platform value | N/A | $12M+ | Combined savings + prevented downtime + efficiency gains |

### 4.4 DORA Metrics

| Metric | Before Platform | After Platform | Industry Elite |
|---|---|---|---|
| Deployment frequency | 2/month | 14/week | On demand |
| Lead time for changes | 3-4 weeks | < 1 day | < 1 hour |
| Change failure rate | 30%+ | 3.8% | < 5% |
| MTTR | 45 minutes | 12.4 minutes | < 1 hour |

---

## 5. Metric Relationships

```
                    ┌─────────────────────────────────┐
                    │          NORTH STAR              │
                    │  Infrastructure changes deployed │
                    │  successfully per week           │
                    └───────────────┬─────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
┌──────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ Provisioning     │  │ Deployment          │  │ Incident            │
│ Speed + Quality  │  │ Safety              │  │ Response            │
│                  │  │                     │  │                     │
│ Deploy time      │  │ Pre-prod catch rate │  │ MTTR                │
│ Config errors    │  │ Simulation accuracy │  │ Auto-resolution     │
│ Self-service     │  │ Rollback rate       │  │ Classification acc  │
│ adoption         │  │ Prod incidents      │  │ Alert noise         │
│ Template coverage│  │                     │  │ reduction           │
└────────┬─────────┘  └──────────┬──────────┘  └──────────┬──────────┘
         │                       │                         │
         └───────────────────────┼─────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │       GUARDRAILS        │
                    │                         │
                    │ Bad remediation = 0%    │
                    │ Shadow IT = 0           │
                    │ Cross-org exposure = 0% │
                    │ Platform uptime > 99.9% │
                    │ Credential leak = 0%    │
                    │ State corruption = 0    │
                    └─────────────────────────┘
```

**How they connect:**

Provisioning speed drives the North Star by removing the bottleneck that capped deployment frequency at 2/month. When any engineer can provision an environment in hours instead of waiting 4 days for the ops team, the queue clears and throughput increases.

Deployment safety drives the North Star by reducing the fear that previously throttled deployment velocity. When engineers know that simulation catches 94% of issues and rollback is automatic, they deploy more often instead of batching changes into large, risky releases.

Incident response protects the North Star by keeping the overall system healthy. If MTTR is high and incidents pile up, the ops team shifts into firefighting mode and stops approving provisioning requests and deployment rollouts. Low MTTR and high auto-resolution keep the ops team available for platform work.

---

## 6. Measurement Cadence

| Frequency | Metrics Reviewed | Forum |
|---|---|---|
| **Real-time** | Platform uptime, alert volume, active incidents, deployment rollout status, credential health | Grafana dashboards + PagerDuty alerts |
| **Daily** | Provisioning queue depth, deployment count, MTTR, auto-resolution rate, compliance scan failures | Team standup dashboard |
| **Weekly** | Deployment frequency, change failure rate, configuration error rate, self-service adoption, cost tracking | Platform team review |
| **Monthly** | Classification accuracy validation, playbook success rates, compliance posture trends, DORA metrics, business impact | Product + leadership review |
| **Quarterly** | Full business impact analysis, DORA benchmarking against industry, model retraining assessment, template coverage review | Executive review |

---

## 7. Experiments and Learning

### Completed Experiments

| Experiment | Hypothesis | Result | Decision |
|---|---|---|---|
| Canary window: 15 min vs. 30 min at 1% | Reducing observation window from 30 to 15 minutes will increase deployment velocity without missing issues | 15-minute window caught 97% of issues that 30-minute window caught. 2 issues per quarter missed were P3 severity only. Deployment cycle time improved 20%. | Adopted 15-minute window for 1% stage. Kept 30 minutes for 10% stage. |
| ML classification confidence threshold: 0.90 vs. 0.95 | Raising threshold from 0.90 to 0.95 will reduce false auto-remediations | False auto-remediation dropped from 2.1% to 0.3%. But auto-resolution rate dropped from 71% to 63%. | Adopted 0.95. The safety improvement justifies the lower auto-resolution rate. |
| Containerized twin vs. persistent staging | Ephemeral simulation environments spun up per deployment will match persistent staging accuracy at lower cost | Simulation accuracy was 96.2% (twin) vs. 95.8% (persistent staging). Cost was $10K/month vs. $45K/month. | Adopted containerized twins. Cost savings of $35K/month with equivalent accuracy. |
| Alert correlation window: 3 min vs. 5 min | Widening the correlation window from 3 to 5 minutes will group more related alerts | Correlated incidents per month dropped from 112 to 87 (22% reduction). 3 incidents were over-grouped (merged two unrelated issues). | Adopted 5-minute window with dependency graph validation to prevent over-grouping. |

### Active Experiments

| Experiment | Hypothesis | Status | Expected Completion |
|---|---|---|---|
| LLM-generated post-mortems | Using Claude to generate post-mortem drafts from incident data will reduce post-mortem writing time by 70% | Running on 30% of resolved incidents | March 2025 |
| Predictive scaling based on deployment schedule | Pre-scaling infrastructure before scheduled deployments will reduce capacity-related incidents | Testing on staging environments | March 2025 |
| OPA policy testing in simulation | Running compliance policy evaluation inside the digital twin before production will catch policy-infrastructure conflicts earlier | Design phase | April 2025 |
