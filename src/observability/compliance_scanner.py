"""
Compliance Scanner - Reference Implementation
Continuously evaluates infrastructure resources against compliance
policies (NIST 800-53, FedRAMP, SOC 2) and detects configuration drift.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum


class ScanResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class ComplianceControl:
    framework: str                 # "nist_800_53", "fedramp_moderate", "soc2"
    control_id: str                # "AC-2", "SC-7", "CC6.1"
    control_name: str
    description: str
    resource_types: list[str]      # which resource types this applies to
    severity: str                  # "critical", "high", "medium", "low"
    check_function: str            # function name for evaluation
    auto_remediate: bool = False


@dataclass
class ScanFinding:
    resource_id: str
    resource_name: str
    resource_type: str
    framework: str
    control_id: str
    control_name: str
    result: ScanResult
    severity: str
    current_value: Optional[str] = None
    expected_value: Optional[str] = None
    finding: Optional[str] = None
    is_drift: bool = False
    remediated_automatically: bool = False


@dataclass
class ScanReport:
    org_id: str
    scan_id: str
    scanned_at: datetime
    total_resources: int
    total_controls: int
    findings: list[ScanFinding]
    pass_count: int = 0
    fail_count: int = 0

    @property
    def compliance_rate(self) -> float:
        total = self.pass_count + self.fail_count
        if total == 0:
            return 0.0
        return self.pass_count / total

    def by_framework(self) -> dict:
        """Group findings by framework."""
        frameworks = {}
        for finding in self.findings:
            fw = finding.framework
            if fw not in frameworks:
                frameworks[fw] = {"pass": 0, "fail": 0, "controls": set()}
            frameworks[fw]["controls"].add(finding.control_id)
            if finding.result == ScanResult.PASS:
                frameworks[fw]["pass"] += 1
            elif finding.result == ScanResult.FAIL:
                frameworks[fw]["fail"] += 1
        return frameworks


# Compliance controls applicable to infrastructure resources
CONTROLS = [
    ComplianceControl(
        "nist_800_53", "AC-2", "Account Management",
        "Manage system accounts, group memberships, and access authorizations",
        ["ec2_instance", "rds_instance", "ecs_service"],
        "high", "check_iam_role",
    ),
    ComplianceControl(
        "nist_800_53", "AC-6", "Least Privilege",
        "Employ principle of least privilege",
        ["ec2_instance", "ecs_service", "lambda_function"],
        "high", "check_least_privilege",
    ),
    ComplianceControl(
        "nist_800_53", "SC-7", "Boundary Protection",
        "Monitor and control communications at external boundaries",
        ["security_group", "ec2_instance"],
        "critical", "check_network_boundary",
        auto_remediate=True,       # auto-close open security groups
    ),
    ComplianceControl(
        "nist_800_53", "SC-28", "Protection of Information at Rest",
        "Protect confidentiality of information at rest",
        ["rds_instance", "ebs_volume", "s3_bucket"],
        "critical", "check_encryption_at_rest",
    ),
    ComplianceControl(
        "nist_800_53", "AU-2", "Audit Events",
        "Identify events that require auditing",
        ["ec2_instance", "rds_instance", "ecs_service", "s3_bucket"],
        "high", "check_monitoring_enabled",
    ),
    ComplianceControl(
        "nist_800_53", "CM-2", "Baseline Configuration",
        "Develop and maintain baseline configurations",
        ["ec2_instance", "ecs_service"],
        "medium", "check_hardening_applied",
    ),
    ComplianceControl(
        "soc2", "CC6.1", "Logical and Physical Access Controls",
        "Restrict logical access to information assets",
        ["ec2_instance", "rds_instance", "s3_bucket"],
        "high", "check_access_controls",
    ),
    ComplianceControl(
        "soc2", "CC6.6", "Security Event Monitoring",
        "Detect and respond to security events",
        ["ec2_instance", "rds_instance", "ecs_service"],
        "high", "check_monitoring_enabled",
    ),
    ComplianceControl(
        "soc2", "CC7.2", "Change Management",
        "Manage changes to infrastructure and software",
        ["ec2_instance", "rds_instance"],
        "medium", "check_change_tracking",
    ),
]


@dataclass
class ResourceConfig:
    """Simplified resource configuration for scanning."""
    id: str
    name: str
    resource_type: str
    environment: str
    configuration: dict
    desired_configuration: dict
    tags: dict


class ComplianceScanner:
    """
    Scans infrastructure resources against compliance policies and
    detects configuration drift.

    Scan frequency:
    - Production: every hour
    - Staging: every 24 hours
    - Dev: weekly

    In production, policy evaluation uses OPA with Rego policies.
    This reference implementation demonstrates the scanning logic,
    drift detection, and report generation.
    """

    def __init__(self, controls: list[ComplianceControl] = None):
        self.controls = controls or CONTROLS

    def scan(
        self, org_id: str, resources: list[ResourceConfig],
    ) -> ScanReport:
        """
        Run full compliance scan across all resources and applicable controls.
        """
        findings = []

        for resource in resources:
            # Find applicable controls
            applicable = [
                c for c in self.controls
                if resource.resource_type in c.resource_types
            ]

            for control in applicable:
                finding = self._evaluate_control(resource, control)
                findings.append(finding)

            # Drift detection (separate from compliance controls)
            drift_findings = self._check_drift(resource)
            findings.extend(drift_findings)

        pass_count = len([f for f in findings if f.result == ScanResult.PASS])
        fail_count = len([f for f in findings if f.result == ScanResult.FAIL])

        return ScanReport(
            org_id=org_id,
            scan_id=f"scan-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            scanned_at=datetime.utcnow(),
            total_resources=len(resources),
            total_controls=len(set(c.control_id for c in self.controls)),
            findings=findings,
            pass_count=pass_count,
            fail_count=fail_count,
        )

    def _evaluate_control(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        """Evaluate a single control against a resource."""
        check_functions = {
            "check_iam_role": self._check_iam_role,
            "check_least_privilege": self._check_least_privilege,
            "check_network_boundary": self._check_network_boundary,
            "check_encryption_at_rest": self._check_encryption_at_rest,
            "check_monitoring_enabled": self._check_monitoring_enabled,
            "check_hardening_applied": self._check_hardening_applied,
            "check_access_controls": self._check_access_controls,
            "check_change_tracking": self._check_change_tracking,
        }

        check_fn = check_functions.get(control.check_function)
        if not check_fn:
            return ScanFinding(
                resource_id=resource.id, resource_name=resource.name,
                resource_type=resource.resource_type,
                framework=control.framework, control_id=control.control_id,
                control_name=control.control_name,
                result=ScanResult.ERROR, severity=control.severity,
                finding=f"Unknown check function: {control.check_function}",
            )

        return check_fn(resource, control)

    def _check_iam_role(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        iam_role = resource.configuration.get("iam_role")
        result = ScanResult.PASS if iam_role else ScanResult.FAIL
        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity=control.severity,
            current_value=iam_role or "none",
            expected_value="IAM role assigned",
            finding=None if result == ScanResult.PASS else
                    f"Resource {resource.name} has no IAM role assigned",
        )

    def _check_least_privilege(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        iam_role = resource.configuration.get("iam_role", "")
        overprivileged = any(
            term in iam_role.lower()
            for term in ["admin", "root", "poweruser", "fullaccess"]
        )
        is_prod = resource.environment == "production"
        result = ScanResult.FAIL if overprivileged else ScanResult.PASS

        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity="critical" if is_prod and overprivileged else control.severity,
            current_value=iam_role,
            expected_value="Scoped IAM role (no admin/root/poweruser)",
            finding=None if result == ScanResult.PASS else
                    f"Overprivileged IAM role '{iam_role}' on {resource.environment} resource",
        )

    def _check_network_boundary(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        security_groups = resource.configuration.get("security_groups", [])
        open_ingress = []

        for sg in security_groups:
            if isinstance(sg, dict):
                rules = sg.get("ingress_rules", [])
                for rule in rules:
                    if rule.get("cidr") == "0.0.0.0/0" and rule.get("port") != 443:
                        open_ingress.append(
                            f"port {rule.get('port')} open to 0.0.0.0/0"
                        )

        result = ScanResult.FAIL if open_ingress else ScanResult.PASS

        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity=control.severity,
            current_value="; ".join(open_ingress) if open_ingress else "no open ingress",
            expected_value="No unrestricted ingress except HTTPS (443)",
            finding=None if result == ScanResult.PASS else
                    f"Unrestricted ingress detected: {'; '.join(open_ingress)}",
        )

    def _check_encryption_at_rest(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        encrypted = resource.configuration.get("encrypted", False)
        result = ScanResult.PASS if encrypted else ScanResult.FAIL
        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity=control.severity,
            current_value=str(encrypted),
            expected_value="true",
            finding=None if result == ScanResult.PASS else
                    f"Encryption at rest not enabled on {resource.name}",
        )

    def _check_monitoring_enabled(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        monitoring = resource.configuration.get("monitoring", {})
        has_agent = monitoring.get("datadog_agent") is not None
        result = ScanResult.PASS if has_agent else ScanResult.FAIL
        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity=control.severity,
            current_value="agent installed" if has_agent else "no agent",
            expected_value="Datadog agent installed and reporting",
            finding=None if result == ScanResult.PASS else
                    f"Monitoring agent not installed on {resource.name}",
        )

    def _check_hardening_applied(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        hardened = resource.configuration.get("cis_hardened", False)
        result = ScanResult.PASS if hardened else ScanResult.FAIL
        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity=control.severity,
            current_value=str(hardened),
            expected_value="CIS benchmark hardening applied",
            finding=None if result == ScanResult.PASS else
                    f"CIS hardening not applied to {resource.name}",
        )

    def _check_access_controls(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        # SOC 2 CC6.1: check both IAM and network controls
        has_iam = bool(resource.configuration.get("iam_role"))
        has_sg = bool(resource.configuration.get("security_groups"))
        result = ScanResult.PASS if (has_iam and has_sg) else ScanResult.FAIL
        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity=control.severity,
            finding=None if result == ScanResult.PASS else
                    f"Missing access controls: IAM={'set' if has_iam else 'missing'}, "
                    f"SG={'set' if has_sg else 'missing'}",
        )

    def _check_change_tracking(
        self, resource: ResourceConfig, control: ComplianceControl,
    ) -> ScanFinding:
        managed_by = resource.tags.get("managed_by")
        result = ScanResult.PASS if managed_by == "infrastructure-automation-platform" else ScanResult.FAIL
        return ScanFinding(
            resource_id=resource.id, resource_name=resource.name,
            resource_type=resource.resource_type,
            framework=control.framework, control_id=control.control_id,
            control_name=control.control_name,
            result=result, severity=control.severity,
            current_value=managed_by or "unmanaged",
            expected_value="infrastructure-automation-platform",
            finding=None if result == ScanResult.PASS else
                    f"Resource {resource.name} not managed through platform (shadow IT)",
        )

    def _check_drift(self, resource: ResourceConfig) -> list[ScanFinding]:
        """Compare current configuration against desired (Terraform) state."""
        findings = []
        for key, desired in resource.desired_configuration.items():
            current = resource.configuration.get(key)
            if current != desired:
                findings.append(ScanFinding(
                    resource_id=resource.id, resource_name=resource.name,
                    resource_type=resource.resource_type,
                    framework="drift_detection", control_id="DRIFT-001",
                    control_name="Configuration Drift",
                    result=ScanResult.FAIL, severity="high",
                    current_value=str(current),
                    expected_value=str(desired),
                    finding=f"Configuration drift on {resource.name}: "
                            f"{key} is '{current}' but should be '{desired}'",
                    is_drift=True,
                ))
        return findings


def scanner_example():
    """Example: scan production resources for compliance and drift."""
    scanner = ComplianceScanner()

    resources = [
        ResourceConfig(
            id="res-001", name="payment-api-prod", resource_type="ec2_instance",
            environment="production",
            configuration={
                "iam_role": "arn:aws:iam::123456789012:role/payment-api-role",
                "security_groups": [{"name": "sg-web-prod", "ingress_rules": [
                    {"cidr": "10.0.0.0/16", "port": 8080},
                    {"cidr": "10.0.0.0/16", "port": 443},
                ]}],
                "encrypted": True,
                "monitoring": {"datadog_agent": "7.45.0"},
                "cis_hardened": True,
            },
            desired_configuration={
                "iam_role": "arn:aws:iam::123456789012:role/payment-api-role",
                "cis_hardened": True,
            },
            tags={"managed_by": "infrastructure-automation-platform"},
        ),
        ResourceConfig(
            id="res-002", name="payment-db-prod", resource_type="rds_instance",
            environment="production",
            configuration={
                "iam_role": "arn:aws:iam::123456789012:role/rds-role",
                "encrypted": True,
                "monitoring": {"datadog_agent": "7.45.0"},
                "multi_az": True,
            },
            desired_configuration={
                "iam_role": "arn:aws:iam::123456789012:role/rds-role",
                "encrypted": True,
                "multi_az": True,
            },
            tags={"managed_by": "infrastructure-automation-platform"},
        ),
        ResourceConfig(
            id="res-003", name="rogue-instance", resource_type="ec2_instance",
            environment="production",
            configuration={
                "iam_role": "arn:aws:iam::123456789012:role/admin-role",
                "security_groups": [{"name": "sg-open", "ingress_rules": [
                    {"cidr": "0.0.0.0/0", "port": 22},
                ]}],
                "encrypted": False,
                "monitoring": {},
                "cis_hardened": False,
            },
            desired_configuration={
                "encrypted": True,
                "cis_hardened": True,
            },
            tags={"managed_by": "manual"},
        ),
    ]

    report = scanner.scan("org-123", resources)

    print(f"Compliance Scan Report")
    print(f"Resources scanned: {report.total_resources}")
    print(f"Overall compliance: {report.compliance_rate:.1%}")
    print(f"Findings: {report.pass_count} pass, {report.fail_count} fail")

    # Show by framework
    print("\nBy framework:")
    for fw, stats in report.by_framework().items():
        total = stats["pass"] + stats["fail"]
        pct = stats["pass"] / total * 100 if total else 0
        print(f"  {fw}: {pct:.0f}% ({stats['pass']}/{total} controls passing)")

    # Show failures
    failures = [f for f in report.findings if f.result == ScanResult.FAIL]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            drift_tag = " [DRIFT]" if f.is_drift else ""
            print(f"  [{f.severity.upper()}] {f.resource_name} - "
                  f"{f.control_id}{drift_tag}: {f.finding}")


if __name__ == "__main__":
    scanner_example()
