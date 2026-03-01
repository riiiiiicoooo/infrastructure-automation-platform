"""
Incident Classifier - Reference Implementation
Classifies correlated incidents by type and severity using structured
feature extraction and NLP text analysis. Routes to the appropriate
on-call team based on classification.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class IncidentType(Enum):
    SERVICE_HEALTH = "service_health"
    STORAGE = "storage"
    NETWORK = "network"
    DATABASE = "database"
    SECURITY = "security"
    DEPLOYMENT = "deployment"
    COST = "cost"


class Severity(Enum):
    P1 = "p1"      # customer-facing outage
    P2 = "p2"      # degraded performance or partial outage
    P3 = "p3"      # non-urgent, no customer impact


@dataclass
class ClassificationResult:
    incident_type: IncidentType
    subtype: str                       # "process_crash", "disk_full", etc.
    severity: Severity
    confidence: float
    model_version: str
    routing: dict                       # team, channel, escalation
    features_used: dict                 # for explainability
    auto_remediation_eligible: bool     # confidence >= 0.95 and playbook exists


@dataclass
class IncidentFeatures:
    """Structured features extracted from an incident for classification."""
    alert_source: str
    resource_type: str
    resource_environment: str
    alert_count: int
    affected_resource_count: int
    has_dependency_cascade: bool
    hour_of_day: int
    day_of_week: int
    message_text: str                  # raw text for NLP classification
    historical_similar_count: int      # past incidents with same resource


# Keyword patterns for NLP text classification
# In production, this is a trained spaCy pipeline
TEXT_PATTERNS = {
    IncidentType.DATABASE: [
        "rds", "database", "connection pool", "query timeout", "replication lag",
        "deadlock", "connection refused", "postgres", "mysql", "connection count",
        "storage full", "backup failed", "failover",
    ],
    IncidentType.SERVICE_HEALTH: [
        "health check", "503", "502", "process crash", "oom", "out of memory",
        "restart", "unresponsive", "timeout", "container", "pod",
    ],
    IncidentType.NETWORK: [
        "network", "dns", "ssl", "certificate", "connection reset",
        "packet loss", "latency spike", "vpc", "security group", "firewall",
    ],
    IncidentType.STORAGE: [
        "disk", "volume", "s3", "storage", "iops", "throughput",
        "disk full", "ebs", "mount", "filesystem",
    ],
    IncidentType.SECURITY: [
        "unauthorized", "brute force", "anomalous", "guardduty",
        "iam", "permission denied", "suspicious", "vulnerability",
    ],
    IncidentType.DEPLOYMENT: [
        "deployment", "rollback", "canary", "rollout", "config change",
        "version mismatch", "terraform", "ansible",
    ],
    IncidentType.COST: [
        "budget", "cost spike", "billing", "reserved instance",
        "spot termination", "quota exceeded",
    ],
}

# Severity rules based on resource environment and cascade impact
SEVERITY_RULES = [
    # P1: production + cascading + critical resource types
    {
        "severity": Severity.P1,
        "conditions": {
            "resource_environment": "production",
            "has_dependency_cascade": True,
            "affected_resource_count_min": 2,
        },
    },
    # P1: production database down
    {
        "severity": Severity.P1,
        "conditions": {
            "resource_environment": "production",
            "resource_type_in": ["rds_instance", "aurora_cluster"],
        },
    },
    # P2: production single resource, no cascade
    {
        "severity": Severity.P2,
        "conditions": {
            "resource_environment": "production",
            "has_dependency_cascade": False,
        },
    },
    # P2: staging with cascade
    {
        "severity": Severity.P2,
        "conditions": {
            "resource_environment": "staging",
            "has_dependency_cascade": True,
        },
    },
    # P3: everything else (staging single, dev)
    {
        "severity": Severity.P3,
        "conditions": {},
    },
]

# Team routing based on incident type
ROUTING_TABLE = {
    IncidentType.DATABASE: {
        "team": "database-reliability",
        "slack_channel": "#db-incidents",
        "pagerduty_service": "database-oncall",
        "escalation_minutes": 15,
    },
    IncidentType.SERVICE_HEALTH: {
        "team": "platform-engineering",
        "slack_channel": "#platform-incidents",
        "pagerduty_service": "platform-oncall",
        "escalation_minutes": 10,
    },
    IncidentType.NETWORK: {
        "team": "network-engineering",
        "slack_channel": "#network-incidents",
        "pagerduty_service": "network-oncall",
        "escalation_minutes": 10,
    },
    IncidentType.STORAGE: {
        "team": "platform-engineering",
        "slack_channel": "#platform-incidents",
        "pagerduty_service": "platform-oncall",
        "escalation_minutes": 15,
    },
    IncidentType.SECURITY: {
        "team": "security-operations",
        "slack_channel": "#security-incidents",
        "pagerduty_service": "security-oncall",
        "escalation_minutes": 5,
    },
    IncidentType.DEPLOYMENT: {
        "team": "platform-engineering",
        "slack_channel": "#deploy-incidents",
        "pagerduty_service": "platform-oncall",
        "escalation_minutes": 15,
    },
    IncidentType.COST: {
        "team": "finops",
        "slack_channel": "#cost-alerts",
        "pagerduty_service": None,
        "escalation_minutes": 60,
    },
}

# Playbook availability by incident type + subtype
PLAYBOOK_AVAILABILITY = {
    ("service_health", "process_crash"): "service_restart",
    ("service_health", "health_check_failure"): "service_restart",
    ("service_health", "oom_kill"): "memory_limit_increase",
    ("database", "connection_pool_exhaustion"): "connection_pool_reset",
    ("database", "replication_lag"): "replica_promotion_check",
    ("storage", "disk_full"): "log_rotation",
    ("network", "ssl_expiry"): "certificate_renewal",
    ("deployment", "config_regression"): "deployment_rollback",
}


class IncidentClassifier:
    """
    Classifies incidents by type and severity, then routes to the
    appropriate team.

    In production, this is a two-model ensemble:
    - Random forest on structured features (resource type, environment,
      alert count, cascade, time-of-day)
    - spaCy text classifier on alert message content

    The ensemble combines both predictions with weighted voting.
    This reference implementation demonstrates the classification logic,
    severity determination, and routing decisions.
    """

    CONFIDENCE_THRESHOLD = 0.95    # minimum for auto-remediation
    MODEL_VERSION = "rf_v3.2_spacy_v2.1"

    def classify(self, features: IncidentFeatures) -> ClassificationResult:
        """
        Classify an incident using structured features + text analysis.
        """
        # Structured feature classification (simulates random forest)
        structured_type, structured_conf = self._classify_structured(features)

        # Text classification (simulates spaCy pipeline)
        text_type, text_conf = self._classify_text(features.message_text)

        # Ensemble: weighted combination
        # Structured features get 60% weight, text gets 40%
        if structured_type == text_type:
            final_type = structured_type
            final_conf = 0.6 * structured_conf + 0.4 * text_conf
        elif structured_conf > text_conf:
            final_type = structured_type
            final_conf = structured_conf * 0.7    # penalize for disagreement
        else:
            final_type = text_type
            final_conf = text_conf * 0.7

        # Determine subtype from text analysis
        subtype = self._extract_subtype(features.message_text, final_type)

        # Determine severity
        severity = self._determine_severity(features)

        # Check playbook availability for auto-remediation eligibility
        playbook_key = (final_type.value, subtype)
        has_playbook = playbook_key in PLAYBOOK_AVAILABILITY
        auto_eligible = final_conf >= self.CONFIDENCE_THRESHOLD and has_playbook

        # Get routing
        routing = ROUTING_TABLE.get(final_type, ROUTING_TABLE[IncidentType.SERVICE_HEALTH])
        if has_playbook:
            routing = {**routing, "playbook": PLAYBOOK_AVAILABILITY[playbook_key]}

        return ClassificationResult(
            incident_type=final_type,
            subtype=subtype,
            severity=severity,
            confidence=round(final_conf, 3),
            model_version=self.MODEL_VERSION,
            routing=routing,
            features_used={
                "structured_prediction": structured_type.value,
                "structured_confidence": round(structured_conf, 3),
                "text_prediction": text_type.value,
                "text_confidence": round(text_conf, 3),
                "ensemble_method": "weighted_vote",
            },
            auto_remediation_eligible=auto_eligible,
        )

    def _classify_structured(
        self, features: IncidentFeatures
    ) -> tuple[IncidentType, float]:
        """
        Classify based on structured features.
        Simulates random forest prediction.
        """
        # Resource type is the strongest structured signal
        type_map = {
            "rds_instance": (IncidentType.DATABASE, 0.92),
            "aurora_cluster": (IncidentType.DATABASE, 0.94),
            "elasticache": (IncidentType.DATABASE, 0.85),
            "ec2_instance": (IncidentType.SERVICE_HEALTH, 0.75),
            "ecs_service": (IncidentType.SERVICE_HEALTH, 0.80),
            "alb": (IncidentType.NETWORK, 0.78),
            "security_group": (IncidentType.NETWORK, 0.82),
            "ebs_volume": (IncidentType.STORAGE, 0.88),
            "s3_bucket": (IncidentType.STORAGE, 0.85),
        }

        result = type_map.get(features.resource_type)
        if result:
            incident_type, base_conf = result
            # Boost confidence if cascade matches expected pattern
            if features.has_dependency_cascade and incident_type == IncidentType.DATABASE:
                base_conf = min(base_conf + 0.05, 0.99)
            return incident_type, base_conf

        return IncidentType.SERVICE_HEALTH, 0.60

    def _classify_text(self, message: str) -> tuple[IncidentType, float]:
        """
        Classify based on alert message text.
        Simulates spaCy text classification pipeline.
        """
        message_lower = message.lower()
        scores = {}

        for incident_type, keywords in TEXT_PATTERNS.items():
            matches = sum(1 for kw in keywords if kw in message_lower)
            total = len(keywords)
            scores[incident_type] = matches / total if total > 0 else 0

        if not scores or max(scores.values()) == 0:
            return IncidentType.SERVICE_HEALTH, 0.50

        best_type = max(scores, key=scores.get)
        # Scale raw match ratio to confidence range [0.5, 0.95]
        raw_score = scores[best_type]
        confidence = 0.50 + (raw_score * 0.45)

        return best_type, min(confidence, 0.95)

    def _extract_subtype(self, message: str, incident_type: IncidentType) -> str:
        """Extract incident subtype from message text."""
        message_lower = message.lower()

        subtype_patterns = {
            IncidentType.SERVICE_HEALTH: {
                "process_crash": ["crash", "exit code", "killed", "segfault"],
                "health_check_failure": ["health check", "unhealthy", "503"],
                "oom_kill": ["oom", "out of memory", "memory limit"],
                "high_cpu": ["cpu", "throttl"],
            },
            IncidentType.DATABASE: {
                "connection_pool_exhaustion": ["connection pool", "connection count", "max_connections"],
                "replication_lag": ["replication", "replica lag", "sync"],
                "query_timeout": ["query timeout", "slow query", "deadlock"],
                "storage_full": ["storage full", "disk space", "tablespace"],
            },
            IncidentType.STORAGE: {
                "disk_full": ["disk full", "no space", "filesystem full"],
                "iops_throttle": ["iops", "throughput", "throttl"],
            },
            IncidentType.NETWORK: {
                "ssl_expiry": ["ssl", "certificate", "tls", "cert expir"],
                "dns_failure": ["dns", "resolution", "nxdomain"],
                "connectivity": ["connection reset", "refused", "packet loss"],
            },
            IncidentType.DEPLOYMENT: {
                "config_regression": ["config", "regression", "mismatch"],
                "rollback_needed": ["rollback", "canary fail", "error spike"],
            },
        }

        type_patterns = subtype_patterns.get(incident_type, {})
        for subtype, keywords in type_patterns.items():
            if any(kw in message_lower for kw in keywords):
                return subtype

        return "unclassified"

    def _determine_severity(self, features: IncidentFeatures) -> Severity:
        """Determine incident severity from structured features."""
        for rule in SEVERITY_RULES:
            conditions = rule["conditions"]
            if not conditions:
                return rule["severity"]

            match = True
            if "resource_environment" in conditions:
                if features.resource_environment != conditions["resource_environment"]:
                    match = False
            if "has_dependency_cascade" in conditions:
                if features.has_dependency_cascade != conditions["has_dependency_cascade"]:
                    match = False
            if "affected_resource_count_min" in conditions:
                if features.affected_resource_count < conditions["affected_resource_count_min"]:
                    match = False
            if "resource_type_in" in conditions:
                if features.resource_type not in conditions["resource_type_in"]:
                    match = False

            if match:
                return rule["severity"]

        return Severity.P3


def classification_example():
    """Example: classify a production database incident with cascading failures."""
    classifier = IncidentClassifier()

    features = IncidentFeatures(
        alert_source="cloudwatch",
        resource_type="rds_instance",
        resource_environment="production",
        alert_count=5,
        affected_resource_count=3,
        has_dependency_cascade=True,
        hour_of_day=14,
        day_of_week=2,        # Wednesday
        message_text="RDS connection count exceeded threshold. Connection pool exhausted on payment-db-prod.",
        historical_similar_count=4,
    )

    result = classifier.classify(features)

    print(f"Classification: {result.incident_type.value} / {result.subtype}")
    print(f"Severity: {result.severity.value}")
    print(f"Confidence: {result.confidence:.1%}")
    print(f"Model: {result.model_version}")
    print(f"Auto-remediation eligible: {result.auto_remediation_eligible}")
    print()
    print(f"Routing:")
    print(f"  Team: {result.routing['team']}")
    print(f"  Slack: {result.routing['slack_channel']}")
    print(f"  PagerDuty: {result.routing['pagerduty_service']}")
    if "playbook" in result.routing:
        print(f"  Playbook: {result.routing['playbook']}")
    print()
    print("Feature analysis:")
    for key, value in result.features_used.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    classification_example()
