"""
Alert Correlator - Reference Implementation
Ingests raw alerts from multiple monitoring sources, deduplicates them,
groups related alerts using time-window and dependency-graph analysis,
and identifies probable root causes.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict


@dataclass
class RawAlert:
    id: str
    source: str                    # "datadog", "cloudwatch", "prometheus", etc.
    severity_raw: str              # original severity from source
    message: str
    affected_resource_id: str
    affected_resource_name: str
    metadata: dict = field(default_factory=dict)
    received_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CorrelatedIncident:
    id: str
    alert_ids: list[str]
    alert_count: int
    root_cause_resource_id: str
    root_cause_resource_name: str
    affected_resources: list[dict]
    root_cause_score: float        # confidence that this is the actual root cause
    title: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DependencyEdge:
    resource_id: str
    depends_on_id: str
    dependency_type: str           # "network", "data", "service", "auth"
    is_critical: bool


class AlertCorrelator:
    """
    Correlates raw monitoring alerts into actionable incidents.

    Pipeline:
    1. Normalize alerts from different sources to common schema
    2. Deduplicate: same resource + similar message within 5-min window
    3. Time-window grouping: alerts within sliding 5-min window
    4. Dependency graph traversal: identify root cause vs. cascading symptoms
    5. Score root cause candidates using dependency depth + alert timing

    In production, the dependency graph comes from the CMDB (resource_dependencies
    table). The random forest model (trained on historical incident data) scores
    root cause candidates. This reference implementation demonstrates the
    correlation logic and scoring heuristics.
    """

    def __init__(
        self,
        dependency_graph: list[DependencyEdge],
        correlation_window_seconds: int = 300,
    ):
        self.dependency_graph = dependency_graph
        self.correlation_window = timedelta(seconds=correlation_window_seconds)
        self.alert_buffer: list[RawAlert] = []
        self.seen_signatures: dict[str, datetime] = {}

    def ingest(self, alert: RawAlert) -> Optional[str]:
        """
        Ingest a raw alert. Returns alert ID if accepted, None if deduplicated.

        Deduplication: same resource + same message within the correlation window
        suppresses the duplicate.
        """
        alert = self._normalize(alert)
        signature = f"{alert.affected_resource_id}:{alert.message[:100]}"

        last_seen = self.seen_signatures.get(signature)
        if last_seen and (alert.received_at - last_seen) < self.correlation_window:
            return None  # duplicate suppressed

        self.seen_signatures[signature] = alert.received_at
        self.alert_buffer.append(alert)
        return alert.id

    def _normalize(self, alert: RawAlert) -> RawAlert:
        """
        Normalize alert fields from different monitoring sources.
        Different sources use different severity scales and field names.
        """
        severity_map = {
            # Datadog
            "critical": "critical", "error": "high", "warning": "medium", "info": "low",
            # CloudWatch
            "ALARM": "high", "INSUFFICIENT_DATA": "medium", "OK": "low",
            # Prometheus
            "firing": "high", "resolved": "low",
            # PagerDuty
            "P1": "critical", "P2": "high", "P3": "medium",
        }
        alert.severity_raw = severity_map.get(alert.severity_raw, alert.severity_raw)
        return alert

    def correlate(self) -> list[CorrelatedIncident]:
        """
        Process buffered alerts into correlated incidents.

        Steps:
        1. Group alerts by time window
        2. Within each group, identify resource clusters using dependency graph
        3. For each cluster, identify the root cause resource
        4. Score root cause confidence
        """
        if not self.alert_buffer:
            return []

        # Step 1: group by time window
        time_groups = self._group_by_time_window()

        # Step 2-4: for each group, find root causes
        incidents = []
        for group in time_groups:
            resource_clusters = self._cluster_by_dependency(group)
            for cluster in resource_clusters:
                incident = self._identify_root_cause(cluster)
                incidents.append(incident)

        # Clear processed alerts
        self.alert_buffer = []

        return incidents

    def _group_by_time_window(self) -> list[list[RawAlert]]:
        """Group alerts into 5-minute sliding windows."""
        if not self.alert_buffer:
            return []

        # Sort by time
        sorted_alerts = sorted(self.alert_buffer, key=lambda a: a.received_at)
        groups = []
        current_group = [sorted_alerts[0]]

        for alert in sorted_alerts[1:]:
            if alert.received_at - current_group[0].received_at <= self.correlation_window:
                current_group.append(alert)
            else:
                groups.append(current_group)
                current_group = [alert]

        groups.append(current_group)
        return groups

    def _cluster_by_dependency(
        self, alerts: list[RawAlert]
    ) -> list[list[RawAlert]]:
        """
        Within a time group, cluster alerts that share dependency relationships.
        If Alert A affects Service X and Alert B affects Database Y,
        and Service X depends on Database Y, they belong to the same cluster.
        """
        # Build adjacency map from dependency graph
        connected_to = defaultdict(set)
        for edge in self.dependency_graph:
            connected_to[edge.resource_id].add(edge.depends_on_id)
            connected_to[edge.depends_on_id].add(edge.resource_id)

        # Group alerts whose affected resources are connected
        assigned = set()
        clusters = []

        for i, alert in enumerate(alerts):
            if i in assigned:
                continue

            cluster = [alert]
            assigned.add(i)

            # Find other alerts in this group whose resources are connected
            for j, other in enumerate(alerts):
                if j in assigned:
                    continue
                if self._are_connected(
                    alert.affected_resource_id,
                    other.affected_resource_id,
                    connected_to,
                ):
                    cluster.append(other)
                    assigned.add(j)

            clusters.append(cluster)

        return clusters

    def _are_connected(
        self, resource_a: str, resource_b: str, adjacency: dict, max_hops: int = 3
    ) -> bool:
        """BFS to check if two resources are connected within max_hops."""
        if resource_a == resource_b:
            return True

        visited = {resource_a}
        frontier = {resource_a}

        for _ in range(max_hops):
            next_frontier = set()
            for node in frontier:
                neighbors = adjacency.get(node, set())
                for neighbor in neighbors:
                    if neighbor == resource_b:
                        return True
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier

        return False

    def _identify_root_cause(self, cluster: list[RawAlert]) -> CorrelatedIncident:
        """
        From a cluster of related alerts, identify the most likely root cause.

        Scoring heuristics (to be replaced by random forest in production):
        - Deepest in dependency chain: if A depends on B depends on C,
          and alerts fire on all three, C is most likely the root cause
        - Earliest alert: the first alert in the cluster is more likely root cause
        - Resource type: databases and network resources are more often root causes
          than application servers
        """
        # Build dependency depth map
        depth_map = {}
        for edge in self.dependency_graph:
            depth_map[edge.depends_on_id] = depth_map.get(edge.depends_on_id, 0)
            # Resources that are depended upon get higher depth (more fundamental)
            depth_map[edge.depends_on_id] = max(
                depth_map[edge.depends_on_id],
                depth_map.get(edge.resource_id, 0) + 1,
            )

        # Resource type weight (infrastructure > application)
        type_weights = {
            "rds_instance": 3.0,
            "elasticache": 2.5,
            "network": 2.5,
            "security_group": 2.0,
            "ec2_instance": 1.0,
            "alb": 1.5,
        }

        # Score each alert's resource as potential root cause
        scored = []
        sorted_cluster = sorted(cluster, key=lambda a: a.received_at)

        for i, alert in enumerate(sorted_cluster):
            resource_id = alert.affected_resource_id
            resource_type = alert.metadata.get("resource_type", "unknown")

            # Dependency depth score (deeper = more likely root cause)
            depth_score = depth_map.get(resource_id, 0) * 2.0

            # Timing score (earlier alerts = more likely root cause)
            timing_score = (len(sorted_cluster) - i) / len(sorted_cluster)

            # Resource type score
            type_score = type_weights.get(resource_type, 1.0)

            total_score = depth_score + timing_score + type_score
            scored.append((alert, total_score))

        # Highest score is root cause
        scored.sort(key=lambda x: x[1], reverse=True)
        root_alert, root_score = scored[0]
        max_possible = 10.0  # rough upper bound for normalization
        confidence = min(root_score / max_possible, 0.99)

        # Build affected resources list
        affected = []
        for alert, score in scored:
            is_root = alert.id == root_alert.id
            affected.append({
                "resource_id": alert.affected_resource_id,
                "name": alert.affected_resource_name,
                "impact": "root_cause" if is_root else "cascading",
                "alert_message": alert.message,
            })

        # Generate incident title
        title = (
            f"{root_alert.affected_resource_name}: {root_alert.message[:80]}"
        )

        return CorrelatedIncident(
            id=f"inc-{root_alert.id}",
            alert_ids=[a.id for a in cluster],
            alert_count=len(cluster),
            root_cause_resource_id=root_alert.affected_resource_id,
            root_cause_resource_name=root_alert.affected_resource_name,
            affected_resources=affected,
            root_cause_score=round(confidence, 3),
            title=title,
        )


def correlation_example():
    """
    Example: 5 raw alerts from a database outage cascade.
    The correlator identifies the database as root cause and the
    API + checkout service as cascading failures.
    """
    # Dependency graph from CMDB
    graph = [
        DependencyEdge("api-prod", "db-prod", "data", True),
        DependencyEdge("checkout-prod", "api-prod", "service", True),
        DependencyEdge("api-prod", "cache-prod", "data", False),
    ]

    correlator = AlertCorrelator(graph)

    now = datetime.utcnow()

    # Simulate cascade: database connection failures trigger API errors,
    # which trigger checkout failures
    alerts = [
        RawAlert("a1", "cloudwatch", "ALARM", "RDS connection count exceeded threshold",
                 "db-prod", "payment-db-prod",
                 {"resource_type": "rds_instance"}, now),
        RawAlert("a2", "datadog", "error", "Connection pool exhausted",
                 "api-prod", "payment-api-prod",
                 {"resource_type": "ec2_instance"}, now + timedelta(seconds=15)),
        RawAlert("a3", "datadog", "error", "HTTP 503 rate spike",
                 "api-prod", "payment-api-prod",
                 {"resource_type": "ec2_instance"}, now + timedelta(seconds=20)),
        RawAlert("a4", "datadog", "error", "Upstream timeout: payment-api",
                 "checkout-prod", "checkout-service-prod",
                 {"resource_type": "ec2_instance"}, now + timedelta(seconds=45)),
        RawAlert("a5", "prometheus", "firing", "Redis connection errors",
                 "cache-prod", "payment-cache-prod",
                 {"resource_type": "elasticache"}, now + timedelta(seconds=30)),
    ]

    # Ingest
    for alert in alerts:
        result = correlator.ingest(alert)
        status = "accepted" if result else "deduplicated"
        print(f"  [{status}] {alert.source}: {alert.message[:60]}")

    # Correlate
    incidents = correlator.correlate()

    print(f"\nRaw alerts: {len(alerts)}")
    print(f"Correlated incidents: {len(incidents)}")

    for inc in incidents:
        print(f"\n  Incident: {inc.title}")
        print(f"  Root cause: {inc.root_cause_resource_name} "
              f"(confidence: {inc.root_cause_score:.1%})")
        print(f"  Alerts correlated: {inc.alert_count}")
        for affected in inc.affected_resources:
            print(f"    [{affected['impact'].upper()}] {affected['name']}: "
                  f"{affected['alert_message'][:50]}")


if __name__ == "__main__":
    correlation_example()
