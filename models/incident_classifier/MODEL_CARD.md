# Incident Classifier - Model Card

**Model Version:** rf_v3.2_spacy_v2.1
**Last Updated:** 2024-03-01
**Owner:** Platform Engineering / ML Infrastructure
**Contact:** ml-platform@company.com

---

## Overview

The Incident Classifier is a machine learning ensemble that automatically categorizes infrastructure incidents into one of 5 categories, predicts severity (P1/P2/P3), and routes to the appropriate on-call team. The model combines:

- **Structured Features Classifier:** Random Forest on alert metadata (source, resource type, environment, timing, cascade detection)
- **Text Classifier:** spaCy NLP pipeline on alert message content
- **Ensemble:** Weighted voting (60% structured, 40% text)

**Accuracy (cross-validation):** 92% ± 2.1%
**Latency:** <50ms per incident (p95)
**Throughput:** 2000+ incidents/second

---

## Training Data

### Dataset Composition

| Category | Count | Source | Characteristics |
|----------|-------|--------|-----------------|
| **Infrastructure** | ~200 | Prod EC2, EBS, VPC alerts | Compute/storage/network failures; 30-40% cascading |
| **Application** | ~200 | Service/container logs | Process crashes, OOM, timeouts; 50% cascading |
| **Database** | ~200 | RDS/Aurora events | Connection exhaustion, replication lag, deadlocks; 70% cascading |
| **Network** | ~200 | ALB/DNS/Route53 metrics | Latency spikes, packet loss, DNS resolution failures; 40% cascading |
| **Security** | ~200 | GuardDuty, WAF, IAM logs | Unauthorized access, anomalies, certificate issues; 10% cascading |

**Total Training Samples:** 1,000 incidents
**Training Period:** 6 months of production incident history (Jan-Jun 2024)
**Data Collection:** Datadog alerts → incident database → automated feature extraction

### Data Characteristics

- **Temporal distribution:** Bimodal (peak 08:00-11:00 UTC, 16:00-19:00 UTC)
- **Environment split:** Production (40%), Staging (30%), Development (30%)
- **Severity distribution:** P1 (15%), P2 (35%), P3 (50%)
- **Auto-remediation rate:** 67% (incidents resolved without human intervention)

### Data Quality

- **Missing values:** <0.1% (imputed with mode/median)
- **Outliers:** Identified and capped at 99th percentile
- **Imbalanced classes:** Mitigated with stratified sampling; evaluated on balanced hold-out

---

## Model Architecture

### Input Features (21 total)

| Category | Feature | Type | Range | Importance |
|----------|---------|------|-------|------------|
| **Alert Metadata** | Alert count | Integer | 1-50 | High |
| | Affected services | Integer | 1-20 | High |
| | Source (CloudWatch/Datadog/GuardDuty) | Categorical | 3 types | High |
| **Resource Context** | Resource type | Categorical | EC2, RDS, S3, ... | Very High |
| | Environment | Categorical | dev/staging/prod | High |
| **Timing** | Hour of day | Integer | 0-23 | Medium |
| | Day of week | Integer | 0-6 | Low |
| **Metrics** | Error rate | Float | 0.0-1.0 | High |
| | Response latency (ms) | Integer | 0-5000 | High |
| | CPU utilization | Float | 0.0-1.0 | Medium |
| | Memory utilization | Float | 0.0-1.0 | Medium |
| **Topology** | Dependency cascade | Boolean | True/False | Very High |
| | Affected resource count | Integer | 1-100 | High |
| **Text Features** | TF-IDF keywords (5-10 per category) | Float | 0.0-1.0 | Medium |
| | Text length | Integer | 0-500 | Low |

### Model Ensemble

```
Incident Alert
    ├── Structured Features Path (60% weight)
    │   ├── Random Forest (10 trees)
    │   ├── Feature normalization
    │   └── Predict P(category | features)
    │
    └── Text Analysis Path (40% weight)
        ├── spaCy tokenization
        ├── Keyword matching
        └── Predict P(category | text)

Weighted Voting → Final Category
Lookup → Routing Rules → Team Assignment
```

### Hyperparameters

```yaml
StructuredModel:
  n_trees: 10
  max_depth: null
  min_samples_split: 2
  criterion: "gini"
  random_state: 42

TextModel:
  spacy_model: "en_core_web_md"
  min_df: 2  # minimum document frequency
  max_df: 0.8  # maximum document frequency
  ngram_range: [1, 2]

Ensemble:
  structured_weight: 0.6
  text_weight: 0.4
  confidence_threshold: 0.95  # for auto-remediation eligibility
```

---

## Performance Metrics

### Classification Accuracy

| Category | Precision | Recall | F1-Score | Support |
|----------|-----------|--------|----------|---------|
| Infrastructure | 0.91 | 0.89 | 0.90 | 45 |
| Application | 0.94 | 0.93 | 0.93 | 45 |
| Database | 0.89 | 0.91 | 0.90 | 45 |
| Network | 0.88 | 0.87 | 0.87 | 45 |
| Security | 0.96 | 0.93 | 0.94 | 40 |
| **Overall** | **0.92** | **0.91** | **0.91** | **220** |

### Cross-Validation (5-fold)

- **Mean Accuracy:** 91.8%
- **Std Dev:** ±2.1%
- **Fold Scores:** [0.914, 0.923, 0.911, 0.920, 0.918]

### Confusion Matrix (Test Set)

```
              Infrastructure  Application  Database  Network  Security
Infrastructure     40              2          1         2        0
Application         1             42          1         1        0
Database            2              1         41         1        0
Network             2              2          0        39        2
Security            0              0          1         2       37
```

### Latency

- **p50:** 12ms
- **p95:** 48ms
- **p99:** 92ms
- **Max:** 180ms

---

## Known Failure Modes

### High False Negative Rates

**Issue:** Infrastructure incidents with cascading failures sometimes misclassified as Application.

**Root Cause:** Ambiguous alert text ("process timeout" could be network or application). Dependency cascade feature alone insufficient.

**Mitigation:**
- Added explicit network metric features (packet loss, latency)
- Increased structured model weight to 0.65 (from 0.6)
- Add edge case retraining quarterly

**Impact:** Reduced FN rate from 12% to 8% in recent retrain (Jan 2024)

### Environment Bias

**Issue:** Development incidents misclassified at higher rate (85% accuracy vs. 93% production).

**Root Cause:** Dev alerts less consistent; fewer high-severity incidents; less structured metadata.

**Mitigation:**
- Stratified sampling ensures development representation
- Consider separate models for dev vs. production
- Monitor dev accuracy quarterly

**Impact:** Training on balanced dataset improved dev accuracy to 88%

### Text Feature Instability

**Issue:** Model sensitive to alert phrasing changes. New terminology can reduce accuracy 5-10%.

**Root Cause:** TF-IDF features brittle; keyword list manually curated.

**Mitigation:**
- Quarterly retraining on recent incident history
- Monitor top misclassified incidents for new patterns
- Plan migration to pre-trained language model (BERT) in Q2 2024

**Impact:** Current production model reseeded Jan 2024 with updated keywords

### Class Imbalance Effects

**Issue:** Security incidents over-represented in high-confidence predictions (96% precision but only 93% recall on edge cases).

**Root Cause:** Security incidents have more distinct keyword patterns (GuardDuty, CloudTrail specific terms).

**Mitigation:**
- Class weight balancing in Random Forest
- Adjusted confidence thresholds per category
- Monitor precision/recall trade-off

**Impact:** Minimal impact on routing (all high-confidence categories route correctly)

---

## Retraining Schedule

### Cadence

| Trigger | Frequency | Reason |
|---------|-----------|--------|
| **Scheduled** | Monthly (1st of month) | Incorporate new incident patterns |
| **Performance Drift** | When accuracy drops below 90% | Detect distribution shift |
| **Major Outage** | Post-incident (within 48h) | Learn from novel patterns |
| **Feature Changes** | Within 1 week | Keep features aligned with source |

### Retraining Data

- **Training window:** Last 90 days of incident data
- **Minimum samples:** 500 per category (skip retraining if insufficient)
- **Validation:** 5-fold cross-validation, must achieve >90% accuracy before deployment
- **Backtest:** Replay against last week of incidents; must maintain >88% accuracy

### Deployment

```
1. Train on 90-day window
2. Validate on 5-fold CV (>90% required)
3. Backtest on recent week (>88% required)
4. A/B test: Route 10% of incidents to new model (1 hour)
5. If no issues, route 100% to new model
6. Keep old model as fallback (48h)
```

---

## Limitations & Disclaimers

1. **Structured Data Dependency:** Model relies on high-quality alert metadata. Poorly structured alerts (missing fields, non-standard naming) reduce accuracy 15-30%.

2. **New Incident Types:** Novel incident patterns (e.g., Kubernetes node pool failures) may be misclassified. Model requires manual labeling and retraining to learn new categories.

3. **Cascading Failures:** Complex multi-layer cascades (e.g., database failure → service restart → config mismatch) difficult to classify. Model may default to highest-probability category.

4. **Latency Constraints:** Real-time inference requirement (49ms target) prevents use of heavyweight transformer models. Limited to Random Forest + spaCy.

5. **Confidence Calibration:** Model confidence scores not perfectly calibrated. 92% confidence ≠ 92% true accuracy. Use for relative ranking only.

6. **Human-in-the-Loop:** High-severity (P1) incidents and security alerts should always be reviewed by humans before auto-remediation.

---

## Ethical Considerations

### Bias Mitigation

- **Environment bias:** Balanced sampling ensures dev, staging, production incidents equally represented
- **Time bias:** Temporal distribution reflects real incident patterns; no artificial up-weighting of off-hours
- **Team bias:** Routing decisions based on incident type only; no team-specific weighting

### Fairness

- **Equal treatment:** Same routing rules apply to all teams regardless of team size or incident history
- **Transparency:** Confidence scores and routing decisions logged and auditable
- **Override capability:** All auto-remediation routes must have manual escalation path

### Accountability

- **Incident audit trail:** All classification decisions logged with features, confidence, timestamp
- **Model versioning:** Production model version recorded with every incident
- **Retraining transparency:** New model deployed with change log; performance changes documented

---

## API Reference

### Prediction Endpoint

```python
from incident_classifier import IncidentClassifier

classifier = IncidentClassifier.load("rf_v3.2_spacy_v2.1")

features = {
    "alert_source": "cloudwatch",
    "resource_type": "rds_instance",
    "environment": "production",
    "alert_count": 5,
    "affected_services": 3,
    "error_rate": 0.87,
    "is_cascading": True,
    "message_text": "RDS connection pool exhausted",
}

prediction = classifier.predict(features)
# {
#   "category": "database",
#   "confidence": 0.96,
#   "severity": "P1",
#   "routing": {
#     "team": "database-reliability",
#     "slack_channel": "#db-incidents",
#     "escalation_minutes": 15
#   }
# }
```

### Batch Prediction

```python
predictions = classifier.predict_batch([features1, features2, ...])
```

### Feature Importance

```python
importance = classifier.feature_importance()
# {"resource_type": 0.24, "is_cascading": 0.19, "error_rate": 0.16, ...}
```

---

## References

- [Incident Classifier Training Code](./training.py)
- [Test Cases](./test_classifier.py)
- [Infrastructure Automation Platform - README](../../README.md)
- [Incident Response Workflow - Source Code](../../src/incident_response/incident_classifier.py)

---

## Changelog

### v3.2 (2024-03-01)
- Added network metric features (latency, packet loss)
- Increased structured model weight to 0.60
- Retrained on Q1 incident data
- **Accuracy:** 92%, **Latency:** <50ms p95

### v3.1 (2024-01-15)
- Implemented stratified sampling for class balance
- Added environment-specific thresholds
- Updated keyword list for new AWS services
- **Accuracy:** 90%, **Latency:** <60ms p95

### v3.0 (2023-11-01)
- Initial Random Forest + spaCy ensemble
- 5-category classification (infrastructure, application, database, network, security)
- **Accuracy:** 88%, **Latency:** <100ms p95
