"""
Resource Registry (CMDB) - Reference Implementation
Manages the lifecycle of provisioned infrastructure resources including
registration, dependency tracking, health monitoring, and decommissioning.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum


class ResourceStatus(Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    DECOMMISSIONING = "decommissioning"
    TERMINATED = "terminated"


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class ComplianceStatus(Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    UNKNOWN = "unknown"


class DependencyType(Enum):
    NETWORK = "network"
    DATA = "data"
    SERVICE = "service"
    AUTH = "auth"
    STORAGE = "storage"


# Valid state transitions for the resource lifecycle
VALID_TRANSITIONS = {
    ResourceStatus.PROVISIONING: [ResourceStatus.ACTIVE, ResourceStatus.TERMINATED],
    ResourceStatus.ACTIVE: [
        ResourceStatus.DEGRADED,
        ResourceStatus.MAINTENANCE,
        ResourceStatus.DECOMMISSIONING,
    ],
    ResourceStatus.DEGRADED: [ResourceStatus.ACTIVE, ResourceStatus.MAINTENANCE],
    ResourceStatus.MAINTENANCE: [ResourceStatus.ACTIVE],
    ResourceStatus.DECOMMISSIONING: [ResourceStatus.TERMINATED],
    ResourceStatus.TERMINATED: [],  # terminal state
}


@dataclass
class Resource:
    id: str
    org_id: str
    request_id: str
    cloud_resource_id: str          # AWS ARN or Azure resource ID
    resource_type: str
    name: str
    region: str
    environment: str
    team: str
    project: str
    status: ResourceStatus = ResourceStatus.PROVISIONING
    configuration: dict = field(default_factory=dict)
    desired_configuration: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
    monthly_cost: float = 0.0
    health_status: HealthStatus = HealthStatus.UNKNOWN
    compliance_status: ComplianceStatus = ComplianceStatus.UNKNOWN
    created_at: datetime = field(default_factory=datetime.utcnow)
    provisioned_at: Optional[datetime] = None
    decommissioned_at: Optional[datetime] = None


@dataclass
class Dependency:
    resource_id: str
    depends_on_id: str
    dependency_type: DependencyType
    is_critical: bool = True
    description: Optional[str] = None


class ResourceRegistry:
    """
    Central registry for all managed infrastructure resources.
    Tracks lifecycle state, dependencies, health, and compliance.

    In production, this writes to PostgreSQL with the resources
    and resource_dependencies tables. This reference implementation
    demonstrates the state machine, dependency graph, and cascade
    impact analysis logic.
    """

    def __init__(self):
        self.resources: dict[str, Resource] = {}
        self.dependencies: list[Dependency] = []

    def register(
        self,
        org_id: str,
        request_id: str,
        cloud_resource_id: str,
        resource_type: str,
        name: str,
        region: str,
        environment: str,
        team: str,
        project: str,
        configuration: dict,
        tags: dict,
        monthly_cost: float = 0.0,
    ) -> Resource:
        """
        Register a newly provisioned resource in the CMDB.
        Called by the Temporal provisioning workflow after terraform apply.
        """
        resource_id = f"res-{len(self.resources) + 1:04d}"

        resource = Resource(
            id=resource_id,
            org_id=org_id,
            request_id=request_id,
            cloud_resource_id=cloud_resource_id,
            resource_type=resource_type,
            name=name,
            region=region,
            environment=environment,
            team=team,
            project=project,
            configuration=configuration,
            desired_configuration=configuration.copy(),
            tags=tags,
            monthly_cost=monthly_cost,
        )

        self.resources[resource_id] = resource
        return resource

    def transition(self, resource_id: str, new_status: ResourceStatus) -> Resource:
        """
        Transition a resource to a new lifecycle state.
        Enforces the state machine: only valid transitions are allowed.
        """
        resource = self.resources.get(resource_id)
        if not resource:
            raise ValueError(f"Resource {resource_id} not found")

        valid_next = VALID_TRANSITIONS.get(resource.status, [])
        if new_status not in valid_next:
            raise ValueError(
                f"Invalid transition: {resource.status.value} -> {new_status.value}. "
                f"Valid transitions: {[s.value for s in valid_next]}"
            )

        resource.status = new_status

        if new_status == ResourceStatus.ACTIVE:
            resource.provisioned_at = datetime.utcnow()
        elif new_status == ResourceStatus.TERMINATED:
            resource.decommissioned_at = datetime.utcnow()

        return resource

    def add_dependency(
        self,
        resource_id: str,
        depends_on_id: str,
        dependency_type: DependencyType,
        is_critical: bool = True,
        description: Optional[str] = None,
    ) -> Dependency:
        """Register a dependency between two resources."""
        # Validate both resources exist
        if resource_id not in self.resources:
            raise ValueError(f"Resource {resource_id} not found")
        if depends_on_id not in self.resources:
            raise ValueError(f"Resource {depends_on_id} not found")

        # Prevent self-dependency
        if resource_id == depends_on_id:
            raise ValueError("Resource cannot depend on itself")

        dep = Dependency(
            resource_id=resource_id,
            depends_on_id=depends_on_id,
            dependency_type=dependency_type,
            is_critical=is_critical,
            description=description,
        )
        self.dependencies.append(dep)
        return dep

    def get_cascade_impact(
        self, failing_resource_id: str, max_depth: int = 5
    ) -> list[dict]:
        """
        Find all resources that would be affected if a resource fails.
        Traverses the dependency graph to identify cascade impact.

        Used by the incident response service to understand blast radius
        when a root cause resource is identified.
        """
        if failing_resource_id not in self.resources:
            raise ValueError(f"Resource {failing_resource_id} not found")

        affected = []
        visited = set()

        def traverse(resource_id: str, depth: int):
            if depth > max_depth or resource_id in visited:
                return
            visited.add(resource_id)

            # Find resources that depend on this one
            dependents = [
                d for d in self.dependencies
                if d.depends_on_id == resource_id
            ]

            for dep in dependents:
                resource = self.resources.get(dep.resource_id)
                if resource:
                    affected.append({
                        "resource_id": resource.id,
                        "name": resource.name,
                        "resource_type": resource.resource_type,
                        "environment": resource.environment,
                        "dependency_type": dep.dependency_type.value,
                        "is_critical": dep.is_critical,
                        "depth": depth,
                        "impact": "primary" if depth == 1 else "cascading",
                    })
                    traverse(dep.resource_id, depth + 1)

        traverse(failing_resource_id, 1)

        # Sort: critical dependencies first, then by depth
        affected.sort(key=lambda x: (not x["is_critical"], x["depth"]))
        return affected

    def detect_drift(self, resource_id: str) -> Optional[dict]:
        """
        Compare current configuration against desired configuration.
        Returns drift details if any differences are found.
        """
        resource = self.resources.get(resource_id)
        if not resource:
            raise ValueError(f"Resource {resource_id} not found")

        diffs = {}
        for key, desired_value in resource.desired_configuration.items():
            current_value = resource.configuration.get(key)
            if current_value != desired_value:
                diffs[key] = {
                    "current": current_value,
                    "desired": desired_value,
                }

        if diffs:
            return {
                "resource_id": resource_id,
                "resource_name": resource.name,
                "drift_count": len(diffs),
                "diffs": diffs,
            }
        return None

    def get_team_summary(self, team: str) -> dict:
        """Dashboard data: resource count, cost, health by team."""
        team_resources = [
            r for r in self.resources.values()
            if r.team == team and r.status == ResourceStatus.ACTIVE
        ]

        return {
            "team": team,
            "total_resources": len(team_resources),
            "by_environment": {
                env: len([r for r in team_resources if r.environment == env])
                for env in ["dev", "staging", "production"]
            },
            "monthly_cost": sum(r.monthly_cost for r in team_resources),
            "healthy": len([r for r in team_resources if r.health_status == HealthStatus.HEALTHY]),
            "degraded": len([r for r in team_resources if r.health_status == HealthStatus.DEGRADED]),
            "non_compliant": len([
                r for r in team_resources
                if r.compliance_status == ComplianceStatus.NON_COMPLIANT
            ]),
        }


def registry_example():
    """
    Example: register resources, add dependencies, analyze cascade impact.
    Simulates a typical provisioning workflow outcome.
    """
    registry = ResourceRegistry()

    # Register resources from a provisioning request
    db = registry.register(
        org_id="org-123", request_id="req-001",
        cloud_resource_id="arn:aws:rds:us-east-1:123456789012:db:payment-db-prod",
        resource_type="rds_instance", name="payment-db-prod",
        region="us-east-1", environment="production",
        team="payments", project="payment-gateway-v2",
        configuration={"instance_class": "db.r5.large", "multi_az": True, "encrypted": True},
        tags={"project": "payment-gateway-v2", "team": "payments"},
        monthly_cost=680.0,
    )

    api = registry.register(
        org_id="org-123", request_id="req-001",
        cloud_resource_id="arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123",
        resource_type="ec2_instance", name="payment-api-prod",
        region="us-east-1", environment="production",
        team="payments", project="payment-gateway-v2",
        configuration={"instance_type": "c5.xlarge", "security_groups": ["sg-web-prod"]},
        tags={"project": "payment-gateway-v2", "team": "payments"},
        monthly_cost=125.0,
    )

    checkout = registry.register(
        org_id="org-123", request_id="req-002",
        cloud_resource_id="arn:aws:ec2:us-east-1:123456789012:instance/i-0def456",
        resource_type="ec2_instance", name="checkout-service-prod",
        region="us-east-1", environment="production",
        team="frontend", project="checkout",
        configuration={"instance_type": "t3.xlarge"},
        tags={"project": "checkout", "team": "frontend"},
        monthly_cost=95.0,
    )

    # Activate resources
    registry.transition(db.id, ResourceStatus.ACTIVE)
    registry.transition(api.id, ResourceStatus.ACTIVE)
    registry.transition(checkout.id, ResourceStatus.ACTIVE)

    # Register dependencies
    registry.add_dependency(
        api.id, db.id, DependencyType.DATA, is_critical=True,
        description="Payment API reads/writes to payment database",
    )
    registry.add_dependency(
        checkout.id, api.id, DependencyType.SERVICE, is_critical=True,
        description="Checkout service calls Payment API for processing",
    )

    # Simulate: database goes down. What's the cascade impact?
    print("Cascade impact if payment-db-prod fails:")
    impact = registry.get_cascade_impact(db.id)
    for affected in impact:
        print(
            f"  [{affected['impact'].upper()}] {affected['name']} "
            f"({affected['dependency_type']}, "
            f"{'critical' if affected['is_critical'] else 'non-critical'}, "
            f"depth={affected['depth']})"
        )

    # Simulate configuration drift
    api.configuration["security_groups"] = ["sg-web-prod", "sg-open-ssh"]
    drift = registry.detect_drift(api.id)
    if drift:
        print(f"\nDrift detected on {drift['resource_name']}:")
        for key, diff in drift["diffs"].items():
            print(f"  {key}: current={diff['current']}, desired={diff['desired']}")


if __name__ == "__main__":
    registry_example()
