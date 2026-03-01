"""
Policy Engine - Reference Implementation
Evaluates provisioning requests against OPA/Rego policies for NIST 800-53
compliance, budget enforcement, and approval routing.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import json


class PolicyDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"


class ApprovalLevel(Enum):
    NONE = "none"
    TEAM_LEAD = "team_lead"
    DIRECTOR = "director"
    VP = "vp"


@dataclass
class PolicyResult:
    policy_id: str
    name: str
    result: str            # "pass" or "fail"
    message: str
    framework: Optional[str] = None    # "nist_800_53", "soc2", etc.
    control_id: Optional[str] = None   # "AC-2", "SC-7", etc.


@dataclass
class PolicyEvaluation:
    decision: PolicyDecision
    policies_evaluated: int
    policies_passed: int
    policies_failed: int
    results: list[PolicyResult]
    requires_approval: bool
    approval_level: ApprovalLevel
    approval_reason: Optional[str] = None
    estimated_monthly_cost: Optional[float] = None


@dataclass
class ProvisioningRequest:
    org_id: str
    requested_by: str
    template_name: str
    environment: str       # "dev", "staging", "production"
    project_name: str
    team: str
    parameters: dict
    cost_center: Optional[str] = None


# NIST 800-53 control definitions relevant to infrastructure provisioning
NIST_CONTROLS = {
    "AC-2": {
        "name": "Account Management",
        "description": "Manage system accounts, group memberships, and access authorizations",
        "check": "iam_role_defined",
    },
    "AC-6": {
        "name": "Least Privilege",
        "description": "Employ principle of least privilege for access to resources",
        "check": "least_privilege",
    },
    "SC-7": {
        "name": "Boundary Protection",
        "description": "Monitor and control communications at external boundaries",
        "check": "network_boundary",
    },
    "SC-8": {
        "name": "Transmission Confidentiality",
        "description": "Protect confidentiality of transmitted information",
        "check": "encryption_in_transit",
    },
    "SC-28": {
        "name": "Protection of Information at Rest",
        "description": "Protect confidentiality of information at rest",
        "check": "encryption_at_rest",
    },
    "AU-2": {
        "name": "Audit Events",
        "description": "Identify events that require auditing",
        "check": "monitoring_enabled",
    },
    "CM-2": {
        "name": "Baseline Configuration",
        "description": "Develop and maintain baseline configurations for systems",
        "check": "hardening_applied",
    },
    "CM-7": {
        "name": "Least Functionality",
        "description": "Configure systems to provide only essential capabilities",
        "check": "minimal_ports",
    },
}


class PolicyEngine:
    """
    Evaluates provisioning requests against compliance policies,
    budget constraints, and organizational rules.

    In production, this calls OPA via REST API with Rego policies.
    This reference implementation shows the evaluation logic and
    decision framework that the Rego policies encode.
    """

    def __init__(self, org_settings: dict):
        self.org_settings = org_settings
        self.budget_limits = org_settings.get("budget_limits", {})
        self.approval_threshold = org_settings.get(
            "default_approval_threshold_monthly", 500
        )
        self.max_environments_per_team = org_settings.get(
            "max_environments_per_team", 20
        )

    def evaluate(self, request: ProvisioningRequest) -> PolicyEvaluation:
        """
        Run all policy checks against a provisioning request.
        Returns a PolicyEvaluation with the overall decision,
        individual results, and approval requirements.
        """
        results = []

        # NIST 800-53 security controls
        results.extend(self._evaluate_nist_controls(request))

        # Budget and quota enforcement
        results.extend(self._evaluate_budget_policies(request))

        # Organizational rules (naming, tagging, etc.)
        results.extend(self._evaluate_org_policies(request))

        # Calculate totals
        passed = [r for r in results if r.result == "pass"]
        failed = [r for r in results if r.result == "fail"]

        # Any failure means deny
        decision = PolicyDecision.ALLOW if not failed else PolicyDecision.DENY

        # Determine approval requirements (even if allowed, may need approval)
        requires_approval, approval_level, approval_reason = (
            self._determine_approval(request)
        )

        return PolicyEvaluation(
            decision=decision,
            policies_evaluated=len(results),
            policies_passed=len(passed),
            policies_failed=len(failed),
            results=results,
            requires_approval=requires_approval,
            approval_level=approval_level,
            approval_reason=approval_reason,
            estimated_monthly_cost=self._estimate_cost(request),
        )

    def _evaluate_nist_controls(
        self, request: ProvisioningRequest
    ) -> list[PolicyResult]:
        """Evaluate NIST 800-53 security controls."""
        results = []

        # AC-2: Account Management - IAM role must be defined
        iam_role = request.parameters.get("iam_role")
        results.append(PolicyResult(
            policy_id="nist_ac_2",
            name="Account Management (AC-2)",
            result="pass" if iam_role else "fail",
            message=(
                f"IAM role defined: {iam_role}"
                if iam_role
                else "No IAM role specified. Every resource must have an explicit IAM role."
            ),
            framework="nist_800_53",
            control_id="AC-2",
        ))

        # AC-6: Least Privilege - no admin/root access in dev/staging
        iam_role = request.parameters.get("iam_role", "")
        is_overprivileged = any(
            term in iam_role.lower()
            for term in ["admin", "root", "poweruser", "fullaccess"]
        )
        if request.environment in ("dev", "staging") and is_overprivileged:
            results.append(PolicyResult(
                policy_id="nist_ac_6",
                name="Least Privilege (AC-6)",
                result="fail",
                message=f"IAM role '{iam_role}' is overprivileged for {request.environment}. "
                        "Use a scoped role with minimum required permissions.",
                framework="nist_800_53",
                control_id="AC-6",
            ))
        else:
            results.append(PolicyResult(
                policy_id="nist_ac_6",
                name="Least Privilege (AC-6)",
                result="pass",
                message="IAM role meets least privilege requirements",
                framework="nist_800_53",
                control_id="AC-6",
            ))

        # SC-7: Boundary Protection - no public ingress in production
        security_groups = request.parameters.get("security_groups", [])
        has_public_ingress = any(
            sg.get("ingress_cidr") == "0.0.0.0/0"
            for sg in security_groups
            if isinstance(sg, dict)
        )
        if request.environment == "production" and has_public_ingress:
            results.append(PolicyResult(
                policy_id="nist_sc_7",
                name="Boundary Protection (SC-7)",
                result="fail",
                message="Production resources cannot have 0.0.0.0/0 ingress. "
                        "Restrict to VPN CIDR or load balancer security group.",
                framework="nist_800_53",
                control_id="SC-7",
            ))
        else:
            results.append(PolicyResult(
                policy_id="nist_sc_7",
                name="Boundary Protection (SC-7)",
                result="pass",
                message="Network boundary controls meet requirements",
                framework="nist_800_53",
                control_id="SC-7",
            ))

        # SC-28: Encryption at rest - must be enabled
        encryption = request.parameters.get("encryption_at_rest", True)
        results.append(PolicyResult(
            policy_id="nist_sc_28",
            name="Protection of Information at Rest (SC-28)",
            result="pass" if encryption else "fail",
            message=(
                "Encryption at rest enabled"
                if encryption
                else "Encryption at rest must be enabled for all storage volumes"
            ),
            framework="nist_800_53",
            control_id="SC-28",
        ))

        # AU-2: Monitoring must be enabled
        monitoring = request.parameters.get("monitoring_enabled", True)
        results.append(PolicyResult(
            policy_id="nist_au_2",
            name="Audit Events (AU-2)",
            result="pass" if monitoring else "fail",
            message=(
                "Monitoring and audit logging enabled"
                if monitoring
                else "Monitoring must be enabled. Datadog agent is required on all resources."
            ),
            framework="nist_800_53",
            control_id="AU-2",
        ))

        return results

    def _evaluate_budget_policies(
        self, request: ProvisioningRequest
    ) -> list[PolicyResult]:
        """Evaluate budget and quota constraints."""
        results = []

        # Team environment quota
        current_count = self._get_team_environment_count(request.team)
        within_quota = current_count < self.max_environments_per_team
        results.append(PolicyResult(
            policy_id="quota_team_environments",
            name="Team Environment Quota",
            result="pass" if within_quota else "fail",
            message=(
                f"Team '{request.team}' has {current_count}/{self.max_environments_per_team} environments"
                if within_quota
                else f"Team '{request.team}' has reached the maximum of "
                     f"{self.max_environments_per_team} environments. "
                     "Decommission unused environments or request a quota increase."
            ),
        ))

        # Budget check
        estimated_cost = self._estimate_cost(request)
        team_budget = self.budget_limits.get(request.team, {})
        remaining = team_budget.get("remaining_monthly", float("inf"))
        within_budget = estimated_cost <= remaining

        results.append(PolicyResult(
            policy_id="budget_check",
            name="Budget Enforcement",
            result="pass" if within_budget else "fail",
            message=(
                f"Estimated cost ${estimated_cost:.2f}/month within team budget "
                f"(${remaining:.2f} remaining)"
                if within_budget
                else f"Estimated cost ${estimated_cost:.2f}/month exceeds remaining "
                     f"team budget of ${remaining:.2f}/month"
            ),
        ))

        return results

    def _evaluate_org_policies(
        self, request: ProvisioningRequest
    ) -> list[PolicyResult]:
        """Evaluate organizational naming and tagging standards."""
        results = []

        # Naming convention: lowercase alphanumeric with hyphens
        import re
        name_valid = bool(re.match(r"^[a-z0-9][a-z0-9\-]{2,62}$", request.project_name))
        results.append(PolicyResult(
            policy_id="naming_standard",
            name="Naming Convention",
            result="pass" if name_valid else "fail",
            message=(
                "Project name follows naming convention"
                if name_valid
                else f"Project name '{request.project_name}' does not follow convention. "
                     "Must be lowercase alphanumeric with hyphens, 3-63 characters."
            ),
        ))

        # Required tags
        tags = request.parameters.get("tags", {})
        required_tags = ["project", "team", "cost_center", "environment"]
        # Environment tag is set by the system, so we add it
        tags_with_env = {**tags, "environment": request.environment}
        missing = [t for t in required_tags if t not in tags_with_env]

        results.append(PolicyResult(
            policy_id="required_tags",
            name="Resource Tagging",
            result="pass" if not missing else "fail",
            message=(
                "All required tags present"
                if not missing
                else f"Missing required tags: {', '.join(missing)}. "
                     "All resources must be tagged with project, team, cost_center, and environment."
            ),
        ))

        return results

    def _determine_approval(
        self, request: ProvisioningRequest
    ) -> tuple[bool, ApprovalLevel, Optional[str]]:
        """
        Determine if the request requires manual approval and at what level.

        Approval triggers:
        - Production environment: VP approval
        - Estimated cost > threshold: Director approval
        - Elevated IAM permissions: Director approval
        - Dev/staging under threshold: auto-approved
        """
        estimated_cost = self._estimate_cost(request)

        if request.environment == "production":
            return True, ApprovalLevel.VP, "production_access"

        if estimated_cost > self.approval_threshold:
            return True, ApprovalLevel.DIRECTOR, (
                f"estimated_cost_${estimated_cost:.0f}_exceeds_${self.approval_threshold}_threshold"
            )

        iam_role = request.parameters.get("iam_role", "")
        elevated_terms = ["write", "delete", "modify", "admin"]
        if any(term in iam_role.lower() for term in elevated_terms):
            return True, ApprovalLevel.DIRECTOR, "elevated_iam_permissions"

        return False, ApprovalLevel.NONE, None

    def _estimate_cost(self, request: ProvisioningRequest) -> float:
        """Estimate monthly cost based on request parameters."""
        # Simplified cost model for reference implementation
        base_costs = {
            "dev": 85.0,
            "staging": 420.0,
            "production": 2800.0,
        }
        base = base_costs.get(request.environment, 100.0)

        # Adjust for parameter overrides
        instance_type = request.parameters.get("instance_type", "")
        if "xlarge" in instance_type:
            base *= 1.5
        elif "2xlarge" in instance_type:
            base *= 2.5

        if request.parameters.get("rds_enabled"):
            base += 350.0
        if request.parameters.get("multi_az"):
            base *= 1.6

        return round(base, 2)

    def _get_team_environment_count(self, team: str) -> int:
        """
        Get current environment count for a team.
        In production, this queries the resources table.
        """
        # Simulated for reference implementation
        team_counts = {
            "platform": 12,
            "payments": 8,
            "data": 6,
            "frontend": 4,
        }
        return team_counts.get(team, 0)


def evaluate_request_example():
    """
    Example: evaluate a staging provisioning request against all policies.
    Demonstrates the full policy evaluation flow.
    """
    org_settings = {
        "default_approval_threshold_monthly": 500,
        "max_environments_per_team": 20,
        "budget_limits": {
            "platform": {"remaining_monthly": 5000.0},
            "payments": {"remaining_monthly": 3000.0},
        },
    }

    engine = PolicyEngine(org_settings)

    request = ProvisioningRequest(
        org_id="org-123",
        requested_by="user-456",
        template_name="staging",
        environment="staging",
        project_name="payment-gateway-v2",
        team="payments",
        parameters={
            "instance_type": "t3.large",
            "rds_enabled": True,
            "multi_az": False,
            "iam_role": "arn:aws:iam::123456789012:role/staging-app-role",
            "monitoring_enabled": True,
            "encryption_at_rest": True,
            "security_groups": [
                {"name": "web-sg", "ingress_cidr": "10.0.0.0/16", "port": 443},
            ],
            "tags": {
                "project": "payment-gateway-v2",
                "team": "payments",
                "cost_center": "ENG-2024-Q1",
            },
        },
    )

    evaluation = engine.evaluate(request)

    print(f"Decision: {evaluation.decision.value}")
    print(f"Policies: {evaluation.policies_passed}/{evaluation.policies_evaluated} passed")
    print(f"Estimated cost: ${evaluation.estimated_monthly_cost:.2f}/month")
    print(f"Requires approval: {evaluation.requires_approval}")
    if evaluation.requires_approval:
        print(f"Approval level: {evaluation.approval_level.value}")
        print(f"Reason: {evaluation.approval_reason}")
    print()

    for result in evaluation.results:
        status = "PASS" if result.result == "pass" else "FAIL"
        control = f" [{result.control_id}]" if result.control_id else ""
        print(f"  [{status}]{control} {result.name}: {result.message}")


if __name__ == "__main__":
    evaluate_request_example()
