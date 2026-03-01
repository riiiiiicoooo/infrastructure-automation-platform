"""
Progressive Rollout Engine - Reference Implementation
Manages canary deployments with KPI monitoring at each stage
and automated rollback when health thresholds are breached.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum


class RolloutStage(Enum):
    SIMULATION = "simulation"
    CANARY_1PCT = "1_pct"
    CANARY_10PCT = "10_pct"
    CANARY_50PCT = "50_pct"
    FULL_100PCT = "100_pct"
    COMPLETE = "complete"
    ROLLED_BACK = "rolled_back"


class StageVerdict(Enum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"
    MANUAL_HOLD = "manual_hold"


@dataclass
class KPIThreshold:
    """Defines a monitored KPI with pass/rollback thresholds."""
    name: str
    metric_query: str              # Datadog/Prometheus query
    pass_threshold: float          # value must stay below this to pass
    rollback_threshold: float      # breach this for rollback_window -> rollback
    rollback_window_seconds: int   # how long breach must persist
    unit: str = ""

    def evaluate(self, current_value: float) -> str:
        if current_value <= self.pass_threshold:
            return "healthy"
        elif current_value <= self.rollback_threshold:
            return "warning"
        else:
            return "breached"


@dataclass
class KPISnapshot:
    kpi_name: str
    value: float
    status: str                    # "healthy", "warning", "breached"
    threshold_pass: float
    threshold_rollback: float
    captured_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class StageResult:
    stage: RolloutStage
    verdict: StageVerdict
    started_at: datetime
    completed_at: Optional[datetime]
    observation_seconds: int
    kpi_snapshots: list[KPISnapshot] = field(default_factory=list)
    rollback_trigger: Optional[str] = None
    approved_by: Optional[str] = None


@dataclass
class RolloutPlan:
    deployment_id: str
    stages: list[dict]             # ordered stage configs
    current_stage_index: int = 0
    results: list[StageResult] = field(default_factory=list)
    status: str = "in_progress"    # in_progress, completed, rolled_back


# Default rollout stages with observation windows
DEFAULT_STAGES = [
    {
        "stage": RolloutStage.CANARY_1PCT,
        "traffic_pct": 1,
        "observation_seconds": 900,    # 15 minutes
        "requires_approval": False,
    },
    {
        "stage": RolloutStage.CANARY_10PCT,
        "traffic_pct": 10,
        "observation_seconds": 1800,   # 30 minutes
        "requires_approval": False,
    },
    {
        "stage": RolloutStage.CANARY_50PCT,
        "traffic_pct": 50,
        "observation_seconds": 1800,   # 30 minutes
        "requires_approval": True,     # manual gate
    },
    {
        "stage": RolloutStage.FULL_100PCT,
        "traffic_pct": 100,
        "observation_seconds": 900,    # 15 minutes final soak
        "requires_approval": False,
    },
]

# Default KPI thresholds
DEFAULT_KPIS = [
    KPIThreshold(
        name="error_rate",
        metric_query="sum:http.errors{service:$SERVICE} / sum:http.requests{service:$SERVICE}",
        pass_threshold=0.01,           # < 1% to pass
        rollback_threshold=0.02,       # > 2% for 5 min -> rollback
        rollback_window_seconds=300,
        unit="%",
    ),
    KPIThreshold(
        name="p99_latency_ms",
        metric_query="p99:http.request.duration{service:$SERVICE}",
        pass_threshold=500,
        rollback_threshold=1000,       # > 1000ms for 5 min -> rollback
        rollback_window_seconds=300,
        unit="ms",
    ),
    KPIThreshold(
        name="cpu_utilization",
        metric_query="avg:system.cpu.user{service:$SERVICE}",
        pass_threshold=0.70,           # < 70% to pass
        rollback_threshold=0.90,       # > 90% for 10 min -> rollback
        rollback_window_seconds=600,
        unit="%",
    ),
    KPIThreshold(
        name="memory_utilization",
        metric_query="avg:system.mem.pct_usable{service:$SERVICE}",
        pass_threshold=0.80,
        rollback_threshold=0.95,       # > 95% for 5 min -> rollback
        rollback_window_seconds=300,
        unit="%",
    ),
    KPIThreshold(
        name="health_check_pass_rate",
        metric_query="avg:http.health.pass_rate{service:$SERVICE}",
        pass_threshold=1.00,           # must be 100%
        rollback_threshold=0.98,       # < 98% for 3 checks -> rollback
        rollback_window_seconds=180,
        unit="%",
    ),
]


class ProgressiveRolloutEngine:
    """
    Manages progressive deployment across canary stages with KPI
    monitoring and automated rollback.

    In production, this is a Temporal workflow that:
    1. Shifts traffic percentage via load balancer weight adjustment
    2. Monitors KPIs via Datadog/TimescaleDB queries
    3. Pauses with a Temporal signal for manual approval gates
    4. Triggers rollback by reverting load balancer weights

    This reference implementation demonstrates the stage progression,
    KPI evaluation, and rollback decision logic.
    """

    def __init__(
        self,
        stages: list[dict] = None,
        kpis: list[KPIThreshold] = None,
    ):
        self.stages = stages or DEFAULT_STAGES
        self.kpis = kpis or DEFAULT_KPIS

    def create_rollout(self, deployment_id: str) -> RolloutPlan:
        """Create a new rollout plan for a deployment."""
        return RolloutPlan(
            deployment_id=deployment_id,
            stages=self.stages,
        )

    def execute_stage(
        self,
        plan: RolloutPlan,
        kpi_values: dict,
        approver: Optional[str] = None,
    ) -> StageResult:
        """
        Execute the current stage of the rollout.

        kpi_values: dict of KPI name -> current value (from monitoring system)
        approver: user ID if this is a manual approval gate
        """
        if plan.current_stage_index >= len(plan.stages):
            raise ValueError("All stages completed")

        stage_config = plan.stages[plan.current_stage_index]
        stage = stage_config["stage"]
        started_at = datetime.utcnow()

        # Check if manual approval is needed
        if stage_config.get("requires_approval") and not approver:
            return StageResult(
                stage=stage,
                verdict=StageVerdict.MANUAL_HOLD,
                started_at=started_at,
                completed_at=None,
                observation_seconds=0,
            )

        # Evaluate KPIs
        snapshots = []
        breach_detected = False
        rollback_trigger = None

        for kpi in self.kpis:
            value = kpi_values.get(kpi.name, 0)
            status = kpi.evaluate(value)
            snapshots.append(KPISnapshot(
                kpi_name=kpi.name,
                value=value,
                status=status,
                threshold_pass=kpi.pass_threshold,
                threshold_rollback=kpi.rollback_threshold,
            ))
            if status == "breached":
                breach_detected = True
                rollback_trigger = (
                    f"{kpi.name}={value}{kpi.unit} exceeds rollback threshold "
                    f"{kpi.rollback_threshold}{kpi.unit}"
                )

        completed_at = datetime.utcnow()

        if breach_detected:
            verdict = StageVerdict.FAIL
        else:
            verdict = StageVerdict.PASS
            plan.current_stage_index += 1

        result = StageResult(
            stage=stage,
            verdict=verdict,
            started_at=started_at,
            completed_at=completed_at,
            observation_seconds=stage_config["observation_seconds"],
            kpi_snapshots=snapshots,
            rollback_trigger=rollback_trigger,
            approved_by=approver,
        )
        plan.results.append(result)

        if verdict == StageVerdict.FAIL:
            plan.status = "rolled_back"
        elif plan.current_stage_index >= len(plan.stages):
            plan.status = "completed"

        return result

    def rollback(self, plan: RolloutPlan, reason: str) -> dict:
        """
        Execute rollback: revert traffic to previous known-good state.

        In production, this:
        1. Sets load balancer weight to 0% for new version
        2. Verifies health checks pass on old version
        3. Removes new version containers/instances
        4. Notifies deployer with rollback reason
        """
        plan.status = "rolled_back"

        return {
            "deployment_id": plan.deployment_id,
            "action": "rollback",
            "reason": reason,
            "rolled_back_from": plan.stages[plan.current_stage_index]["stage"].value,
            "stages_completed": plan.current_stage_index,
            "notification": {
                "channel": "slack",
                "message": (
                    f"Deployment {plan.deployment_id} rolled back at "
                    f"{plan.stages[plan.current_stage_index]['stage'].value} stage. "
                    f"Reason: {reason}"
                ),
            },
        }

    def get_rollout_summary(self, plan: RolloutPlan) -> dict:
        """Generate a summary of the rollout for the deployment dashboard."""
        return {
            "deployment_id": plan.deployment_id,
            "status": plan.status,
            "stages_completed": plan.current_stage_index,
            "total_stages": len(plan.stages),
            "current_stage": (
                plan.stages[plan.current_stage_index]["stage"].value
                if plan.current_stage_index < len(plan.stages)
                else "complete"
            ),
            "results": [
                {
                    "stage": r.stage.value,
                    "verdict": r.verdict.value,
                    "kpis": {
                        s.kpi_name: {"value": s.value, "status": s.status}
                        for s in r.kpi_snapshots
                    },
                    "rollback_trigger": r.rollback_trigger,
                }
                for r in plan.results
            ],
        }


def rollout_example():
    """Example: simulate a progressive rollout with KPI monitoring."""
    engine = ProgressiveRolloutEngine()
    plan = engine.create_rollout("deploy-042")

    # Stage 1: 1% canary - healthy KPIs
    print("Stage 1: 1% canary")
    result = engine.execute_stage(plan, {
        "error_rate": 0.003,
        "p99_latency_ms": 145,
        "cpu_utilization": 0.42,
        "memory_utilization": 0.61,
        "health_check_pass_rate": 1.00,
    })
    print(f"  Verdict: {result.verdict.value}")
    for snap in result.kpi_snapshots:
        print(f"    {snap.kpi_name}: {snap.value} [{snap.status}]")

    # Stage 2: 10% canary - still healthy
    print("\nStage 2: 10% canary")
    result = engine.execute_stage(plan, {
        "error_rate": 0.005,
        "p99_latency_ms": 168,
        "cpu_utilization": 0.51,
        "memory_utilization": 0.68,
        "health_check_pass_rate": 1.00,
    })
    print(f"  Verdict: {result.verdict.value}")

    # Stage 3: 50% - requires manual approval
    print("\nStage 3: 50% (approval gate)")
    result = engine.execute_stage(plan, {})
    print(f"  Verdict: {result.verdict.value} (waiting for approver)")

    # Approver reviews terraform plan diff and approves
    result = engine.execute_stage(plan, {
        "error_rate": 0.008,
        "p99_latency_ms": 195,
        "cpu_utilization": 0.58,
        "memory_utilization": 0.72,
        "health_check_pass_rate": 1.00,
    }, approver="user-789")
    print(f"  Approved by: {result.approved_by}")
    print(f"  Verdict: {result.verdict.value}")

    # Stage 4: 100% - healthy
    print("\nStage 4: 100% rollout")
    result = engine.execute_stage(plan, {
        "error_rate": 0.006,
        "p99_latency_ms": 172,
        "cpu_utilization": 0.55,
        "memory_utilization": 0.70,
        "health_check_pass_rate": 1.00,
    })
    print(f"  Verdict: {result.verdict.value}")

    summary = engine.get_rollout_summary(plan)
    print(f"\nRollout status: {summary['status']}")
    print(f"Stages completed: {summary['stages_completed']}/{summary['total_stages']}")


if __name__ == "__main__":
    rollout_example()
