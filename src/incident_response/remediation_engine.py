"""
Remediation Engine - Reference Implementation
Executes automated remediation playbooks for classified incidents
with safety checks, rollback capability, and decision support
for human-triaged incidents.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum


class PlaybookStepType(Enum):
    PRECONDITION = "precondition_check"
    ACTION = "action"
    POST_CHECK = "post_check"
    ROLLBACK = "rollback"


class StepResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class RemediationOutcome(Enum):
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"
    ROLLED_BACK = "rolled_back"


@dataclass
class PlaybookStep:
    step_type: PlaybookStepType
    name: str
    command: str                        # shell command or API call
    timeout_seconds: int = 30
    expected_result: Optional[str] = None


@dataclass
class StepExecution:
    step_type: str
    name: str
    result: StepResult
    duration_ms: int
    output: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Playbook:
    id: str
    name: str
    description: str
    trigger_type: str                   # incident classification type
    trigger_subtypes: list[str]
    confidence_min: float               # minimum classification confidence
    severity_allowed: list[str]         # which severities this playbook handles
    preconditions: list[PlaybookStep]
    actions: list[PlaybookStep]
    post_checks: list[PlaybookStep]
    rollback_actions: list[PlaybookStep]
    exclude_resources: list[str] = field(default_factory=list)
    max_executions_per_hour: int = 3    # safety limit
    git_sha: Optional[str] = None


@dataclass
class RemediationResult:
    incident_id: str
    playbook_id: str
    playbook_name: str
    outcome: RemediationOutcome
    steps_executed: list[StepExecution]
    total_duration_seconds: int
    started_at: datetime
    completed_at: datetime
    escalation_reason: Optional[str] = None


# Playbook definitions (in production, these are YAML files in Git)
PLAYBOOKS = {
    "service_restart": Playbook(
        id="pb-001",
        name="Service Restart",
        description="Gracefully restart a crashed or unhealthy service",
        trigger_type="service_health",
        trigger_subtypes=["process_crash", "health_check_failure"],
        confidence_min=0.95,
        severity_allowed=["p2", "p3"],
        preconditions=[
            PlaybookStep(
                PlaybookStepType.PRECONDITION, "service_exists",
                "systemctl status {service_name}", 10,
                "service found",
            ),
            PlaybookStep(
                PlaybookStepType.PRECONDITION, "restart_count_below_threshold",
                "check_restart_count {service_name} --max 3 --window 1h", 10,
                "below threshold",
            ),
        ],
        actions=[
            PlaybookStep(
                PlaybookStepType.ACTION, "restart_service",
                "systemctl restart {service_name} --timeout 30", 45,
            ),
        ],
        post_checks=[
            PlaybookStep(
                PlaybookStepType.POST_CHECK, "health_check_passing",
                "curl -sf http://localhost:{port}/health", 30,
                "200 OK",
            ),
            PlaybookStep(
                PlaybookStepType.POST_CHECK, "error_rate_below_threshold",
                "check_error_rate {service_name} --threshold 0.02 --window 5m", 310,
                "below threshold",
            ),
        ],
        rollback_actions=[
            PlaybookStep(
                PlaybookStepType.ROLLBACK, "escalate_to_human",
                "pagerduty_escalate {service_name} --reason 'restart failed post-check'", 10,
            ),
        ],
        exclude_resources=["payment-gateway-prod"],
    ),
    "connection_pool_reset": Playbook(
        id="pb-002",
        name="Connection Pool Reset",
        description="Reset exhausted database connection pool",
        trigger_type="database",
        trigger_subtypes=["connection_pool_exhaustion"],
        confidence_min=0.95,
        severity_allowed=["p1", "p2"],
        preconditions=[
            PlaybookStep(
                PlaybookStepType.PRECONDITION, "db_instance_reachable",
                "pg_isready -h {db_host} -p 5432", 10,
                "accepting connections",
            ),
            PlaybookStep(
                PlaybookStepType.PRECONDITION, "connection_count_above_threshold",
                "check_pg_connections {db_host} --min-pct 90", 10,
                "above 90%",
            ),
        ],
        actions=[
            PlaybookStep(
                PlaybookStepType.ACTION, "terminate_idle_connections",
                "pg_terminate_idle {db_host} --idle-seconds 300", 15,
            ),
            PlaybookStep(
                PlaybookStepType.ACTION, "restart_connection_pooler",
                "systemctl restart pgbouncer", 30,
            ),
        ],
        post_checks=[
            PlaybookStep(
                PlaybookStepType.POST_CHECK, "connection_count_normalized",
                "check_pg_connections {db_host} --max-pct 70", 60,
                "below 70%",
            ),
            PlaybookStep(
                PlaybookStepType.POST_CHECK, "application_health",
                "check_dependent_services {db_host} --health", 120,
                "all healthy",
            ),
        ],
        rollback_actions=[
            PlaybookStep(
                PlaybookStepType.ROLLBACK, "escalate_to_dba",
                "pagerduty_escalate {db_host} --team database-reliability "
                "--reason 'connection pool reset failed'", 10,
            ),
        ],
    ),
    "log_rotation": Playbook(
        id="pb-003",
        name="Emergency Log Rotation",
        description="Free disk space by rotating and compressing logs",
        trigger_type="storage",
        trigger_subtypes=["disk_full"],
        confidence_min=0.95,
        severity_allowed=["p2", "p3"],
        preconditions=[
            PlaybookStep(
                PlaybookStepType.PRECONDITION, "disk_usage_above_threshold",
                "check_disk_usage {host} --min-pct 85", 10,
                "above 85%",
            ),
        ],
        actions=[
            PlaybookStep(
                PlaybookStepType.ACTION, "rotate_logs",
                "logrotate --force /etc/logrotate.d/{service_name}", 30,
            ),
            PlaybookStep(
                PlaybookStepType.ACTION, "compress_old_logs",
                "find /var/log/{service_name} -name '*.log.*' -mtime +1 "
                "-exec gzip {} \\;", 60,
            ),
            PlaybookStep(
                PlaybookStepType.ACTION, "clean_tmp",
                "find /tmp -type f -mtime +7 -delete", 30,
            ),
        ],
        post_checks=[
            PlaybookStep(
                PlaybookStepType.POST_CHECK, "disk_usage_reduced",
                "check_disk_usage {host} --max-pct 80", 10,
                "below 80%",
            ),
        ],
        rollback_actions=[
            PlaybookStep(
                PlaybookStepType.ROLLBACK, "alert_team",
                "slack_notify #platform-incidents 'Log rotation insufficient on {host}. "
                "Manual cleanup required.'", 10,
            ),
        ],
    ),
}


class RemediationEngine:
    """
    Executes remediation playbooks against classified incidents.

    Safety model:
    1. Only executes if classification confidence >= playbook threshold
    2. Preconditions must all pass before any action runs
    3. Post-checks validate the fix worked
    4. If post-checks fail, rollback actions execute
    5. Execution rate-limited per playbook per hour

    In production, steps execute via SSH/API calls orchestrated by
    a Temporal workflow. This reference implementation demonstrates
    the execution logic, safety checks, and decision framework.
    """

    def __init__(self, playbooks: dict = None):
        self.playbooks = playbooks or PLAYBOOKS
        self.execution_history: list[RemediationResult] = []

    def find_playbook(
        self,
        incident_type: str,
        subtype: str,
        severity: str,
        confidence: float,
        resource_name: str,
    ) -> Optional[Playbook]:
        """
        Find a matching playbook for the incident classification.
        Returns None if no playbook matches or if safety checks fail.
        """
        for playbook in self.playbooks.values():
            if playbook.trigger_type != incident_type:
                continue
            if subtype not in playbook.trigger_subtypes:
                continue
            if severity not in playbook.severity_allowed:
                continue
            if confidence < playbook.confidence_min:
                continue
            if resource_name in playbook.exclude_resources:
                continue

            # Rate limit check
            if self._exceeds_rate_limit(playbook):
                continue

            return playbook

        return None

    def execute(
        self,
        incident_id: str,
        playbook: Playbook,
        context: dict,
    ) -> RemediationResult:
        """
        Execute a playbook against an incident.

        context: variables to substitute into commands
        (e.g., {"service_name": "payment-api", "port": "8080"})
        """
        started_at = datetime.utcnow()
        steps_executed = []
        outcome = RemediationOutcome.RESOLVED

        # Phase 1: Precondition checks
        for step in playbook.preconditions:
            result = self._execute_step(step, context)
            steps_executed.append(result)

            if result.result == StepResult.FAIL:
                outcome = RemediationOutcome.ESCALATED
                escalation_reason = (
                    f"Precondition '{step.name}' failed: {result.error}"
                )
                return self._build_result(
                    incident_id, playbook, outcome, steps_executed,
                    started_at, escalation_reason,
                )

        # Phase 2: Execute remediation actions
        for step in playbook.actions:
            result = self._execute_step(step, context)
            steps_executed.append(result)

            if result.result == StepResult.FAIL:
                # Action failed, attempt rollback
                outcome = RemediationOutcome.ROLLED_BACK
                steps_executed.extend(
                    self._execute_rollback(playbook, context)
                )
                return self._build_result(
                    incident_id, playbook, outcome, steps_executed,
                    started_at, f"Action '{step.name}' failed: {result.error}",
                )

        # Phase 3: Post-check validation
        for step in playbook.post_checks:
            result = self._execute_step(step, context)
            steps_executed.append(result)

            if result.result == StepResult.FAIL:
                # Fix didn't work, rollback + escalate
                outcome = RemediationOutcome.ESCALATED
                steps_executed.extend(
                    self._execute_rollback(playbook, context)
                )
                return self._build_result(
                    incident_id, playbook, outcome, steps_executed,
                    started_at,
                    f"Post-check '{step.name}' failed after remediation: {result.error}",
                )

        return self._build_result(
            incident_id, playbook, outcome, steps_executed, started_at,
        )

    def build_decision_support(
        self,
        incident_type: str,
        subtype: str,
        resource_name: str,
        affected_resources: list[dict],
    ) -> dict:
        """
        For incidents that don't qualify for auto-remediation,
        build a decision support package for the on-call engineer.
        """
        # Find similar past incidents
        similar = self._find_similar_incidents(incident_type, subtype)

        # Suggested steps based on incident type
        suggested_steps = self._get_suggested_steps(incident_type, subtype)

        return {
            "summary": f"{incident_type}/{subtype} on {resource_name}",
            "why_not_auto": self._explain_no_auto(incident_type, subtype, resource_name),
            "affected_resources": affected_resources,
            "similar_past_incidents": similar,
            "suggested_steps": suggested_steps,
            "useful_commands": self._get_diagnostic_commands(incident_type, resource_name),
            "escalation_contacts": self._get_escalation_contacts(incident_type),
        }

    def _execute_step(self, step: PlaybookStep, context: dict) -> StepExecution:
        """
        Execute a single playbook step.
        In production, this runs the command via SSH or API call.
        """
        # Substitute context variables into command
        command = step.command
        for key, value in context.items():
            command = command.replace(f"{{{key}}}", str(value))

        # Simulated execution
        return StepExecution(
            step_type=step.step_type.value,
            name=step.name,
            result=StepResult.PASS,
            duration_ms=int(step.timeout_seconds * 100),  # simulated
            output=step.expected_result or "completed",
        )

    def _execute_rollback(
        self, playbook: Playbook, context: dict
    ) -> list[StepExecution]:
        """Execute all rollback actions for a playbook."""
        results = []
        for step in playbook.rollback_actions:
            result = self._execute_step(step, context)
            results.append(result)
        return results

    def _build_result(
        self,
        incident_id: str,
        playbook: Playbook,
        outcome: RemediationOutcome,
        steps: list[StepExecution],
        started_at: datetime,
        escalation_reason: Optional[str] = None,
    ) -> RemediationResult:
        completed_at = datetime.utcnow()
        total_ms = sum(s.duration_ms for s in steps)

        result = RemediationResult(
            incident_id=incident_id,
            playbook_id=playbook.id,
            playbook_name=playbook.name,
            outcome=outcome,
            steps_executed=steps,
            total_duration_seconds=total_ms // 1000,
            started_at=started_at,
            completed_at=completed_at,
            escalation_reason=escalation_reason,
        )
        self.execution_history.append(result)
        return result

    def _exceeds_rate_limit(self, playbook: Playbook) -> bool:
        """Check if playbook has been executed too many times recently."""
        recent = [
            r for r in self.execution_history
            if r.playbook_id == playbook.id
            and (datetime.utcnow() - r.started_at).total_seconds() < 3600
        ]
        return len(recent) >= playbook.max_executions_per_hour

    def _find_similar_incidents(self, incident_type: str, subtype: str) -> list[dict]:
        """Find past incidents with same classification."""
        return [
            {
                "incident_id": r.incident_id,
                "playbook": r.playbook_name,
                "outcome": r.outcome.value,
                "duration_seconds": r.total_duration_seconds,
            }
            for r in self.execution_history
            if r.playbook_name and incident_type in r.playbook_name.lower()
        ]

    def _explain_no_auto(
        self, incident_type: str, subtype: str, resource_name: str
    ) -> str:
        """Explain why auto-remediation was not triggered."""
        reasons = []
        for playbook in self.playbooks.values():
            if playbook.trigger_type == incident_type:
                if subtype not in playbook.trigger_subtypes:
                    reasons.append(f"No playbook covers subtype '{subtype}'")
                if resource_name in playbook.exclude_resources:
                    reasons.append(f"Resource '{resource_name}' is excluded from auto-remediation")
        if not reasons:
            reasons.append("No matching playbook found for this incident classification")
        return "; ".join(reasons)

    def _get_suggested_steps(self, incident_type: str, subtype: str) -> list[str]:
        """Suggested investigation steps for the on-call engineer."""
        steps_map = {
            "database": [
                "Check RDS console for CPU/memory/connection metrics",
                "Review slow query log for the last 30 minutes",
                "Check replication lag if multi-AZ",
                "Verify connection pool settings in application config",
            ],
            "service_health": [
                "Check container/instance logs for crash stacktrace",
                "Review memory usage trend over last hour",
                "Check if recent deployment correlates with issue start time",
                "Verify health check endpoint responds locally",
            ],
            "network": [
                "Check VPC flow logs for rejected connections",
                "Verify security group rules haven't changed",
                "Test DNS resolution from affected instances",
                "Check SSL certificate expiration dates",
            ],
        }
        return steps_map.get(incident_type, ["Review monitoring dashboards for the affected resource"])

    def _get_diagnostic_commands(self, incident_type: str, resource_name: str) -> list[str]:
        """Pre-built diagnostic commands for the on-call engineer."""
        return [
            f"aws rds describe-db-instances --db-instance-identifier {resource_name}",
            f"kubectl logs -l app={resource_name} --tail=100",
            f"curl -v http://{resource_name}:8080/health",
        ]

    def _get_escalation_contacts(self, incident_type: str) -> dict:
        """Escalation path for the incident type."""
        contacts = {
            "database": {"primary": "DBA on-call", "secondary": "Database team lead"},
            "service_health": {"primary": "Platform on-call", "secondary": "Service owner"},
            "network": {"primary": "Network on-call", "secondary": "Infrastructure lead"},
            "security": {"primary": "Security on-call", "secondary": "CISO"},
        }
        return contacts.get(incident_type, {"primary": "Platform on-call"})


def remediation_example():
    """Example: execute service restart playbook for a process crash."""
    engine = RemediationEngine()

    # Find matching playbook
    playbook = engine.find_playbook(
        incident_type="service_health",
        subtype="process_crash",
        severity="p2",
        confidence=0.96,
        resource_name="payment-api-prod",
    )

    if playbook:
        print(f"Found playbook: {playbook.name}")
        result = engine.execute(
            incident_id="inc-a1",
            playbook=playbook,
            context={
                "service_name": "payment-api",
                "port": "8080",
                "host": "payment-api-prod",
            },
        )

        print(f"Outcome: {result.outcome.value}")
        print(f"Duration: {result.total_duration_seconds}s")
        for step in result.steps_executed:
            icon = "+" if step.result == StepResult.PASS else "x"
            print(f"  [{icon}] {step.step_type}: {step.name} ({step.duration_ms}ms)")
    else:
        print("No matching playbook found")

    # Example: decision support for non-auto incident
    print("\nDecision support for human-triaged incident:")
    support = engine.build_decision_support(
        incident_type="database",
        subtype="replication_lag",
        resource_name="payment-db-prod",
        affected_resources=[
            {"name": "payment-db-prod", "impact": "root_cause"},
            {"name": "payment-api-prod", "impact": "cascading"},
        ],
    )
    print(f"  Summary: {support['summary']}")
    print(f"  Why not auto: {support['why_not_auto']}")
    print("  Suggested steps:")
    for step in support["suggested_steps"]:
        print(f"    - {step}")


if __name__ == "__main__":
    remediation_example()
