"""
Synthetic Workload Generator - Reference Implementation
Generates realistic traffic patterns for digital twin environments
to validate performance, capacity, and failure handling under load.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import math
import random


class WorkloadPattern(Enum):
    STEADY = "steady"              # constant RPS
    RAMP_UP = "ramp_up"           # gradual increase to peak
    PEAK_HOUR = "peak_hour"       # simulate business hours spike
    SPIKE = "spike"               # sudden burst
    SINE_WAVE = "sine_wave"       # oscillating load


@dataclass
class RequestProfile:
    """Defines a type of request to generate."""
    name: str
    method: str                    # GET, POST, PUT, DELETE
    path: str
    weight: float                  # relative frequency (0.0-1.0)
    payload_size_bytes: int = 0
    expected_latency_ms: int = 100
    timeout_ms: int = 5000


@dataclass
class WorkloadConfig:
    pattern: WorkloadPattern
    base_rps: float                # requests per second at baseline
    peak_rps: float                # max requests per second
    duration_seconds: int
    ramp_duration_seconds: int = 60
    request_profiles: list[RequestProfile] = field(default_factory=list)
    concurrent_users: int = 50
    think_time_ms: int = 500       # delay between user requests


@dataclass
class WorkloadSnapshot:
    """Point-in-time workload state."""
    timestamp_offset_seconds: int
    target_rps: float
    concurrent_users: int
    request_distribution: dict     # profile_name -> count


@dataclass
class WorkloadPlan:
    """Complete execution plan for a synthetic workload run."""
    config: WorkloadConfig
    snapshots: list[WorkloadSnapshot]
    total_requests: int
    estimated_data_transfer_mb: float


# Production traffic profiles derived from real traffic analysis
PRODUCTION_PROFILES = {
    "web_api": [
        RequestProfile("health_check", "GET", "/health", 0.05, 0, 10),
        RequestProfile("list_resources", "GET", "/api/v1/resources", 0.25, 0, 150),
        RequestProfile("get_resource", "GET", "/api/v1/resources/{id}", 0.30, 0, 80),
        RequestProfile("create_resource", "POST", "/api/v1/resources", 0.15, 2048, 300),
        RequestProfile("update_resource", "PUT", "/api/v1/resources/{id}", 0.10, 1024, 200),
        RequestProfile("search", "GET", "/api/v1/search?q={query}", 0.10, 0, 250),
        RequestProfile("dashboard_data", "GET", "/api/v1/dashboard", 0.05, 0, 500),
    ],
    "incident_api": [
        RequestProfile("ingest_alert", "POST", "/api/v1/alerts", 0.60, 512, 50),
        RequestProfile("get_incident", "GET", "/api/v1/incidents/{id}", 0.15, 0, 100),
        RequestProfile("list_incidents", "GET", "/api/v1/incidents", 0.10, 0, 200),
        RequestProfile("update_status", "PUT", "/api/v1/incidents/{id}/status", 0.10, 256, 150),
        RequestProfile("get_playbook", "GET", "/api/v1/playbooks/{id}", 0.05, 0, 50),
    ],
}


class SyntheticWorkloadGenerator:
    """
    Generates time-series workload plans that model real production
    traffic patterns. The plans are executed by Locust workers inside
    the digital twin environment.

    In production, this feeds configuration to Locust load generators.
    This reference implementation demonstrates the workload modeling,
    pattern generation, and request distribution logic.
    """

    def generate_plan(self, config: WorkloadConfig) -> WorkloadPlan:
        """
        Generate a complete workload execution plan.
        Returns a time-series of snapshots defining exact load at each second.
        """
        snapshots = []
        total_requests = 0
        total_bytes = 0

        pattern_fn = self._get_pattern_function(config.pattern)

        for t in range(config.duration_seconds):
            target_rps = pattern_fn(t, config)

            # Distribute requests across profiles by weight
            distribution = {}
            for profile in config.request_profiles:
                count = round(target_rps * profile.weight)
                distribution[profile.name] = count
                total_requests += count
                total_bytes += count * profile.payload_size_bytes

            # Scale concurrent users proportionally to RPS
            rps_ratio = target_rps / max(config.peak_rps, 1)
            active_users = max(1, round(config.concurrent_users * rps_ratio))

            snapshots.append(WorkloadSnapshot(
                timestamp_offset_seconds=t,
                target_rps=round(target_rps, 1),
                concurrent_users=active_users,
                request_distribution=distribution,
            ))

        return WorkloadPlan(
            config=config,
            snapshots=snapshots,
            total_requests=total_requests,
            estimated_data_transfer_mb=round(total_bytes / (1024 * 1024), 2),
        )

    def _get_pattern_function(self, pattern: WorkloadPattern):
        """Return the RPS calculation function for a given pattern."""
        return {
            WorkloadPattern.STEADY: self._steady,
            WorkloadPattern.RAMP_UP: self._ramp_up,
            WorkloadPattern.PEAK_HOUR: self._peak_hour,
            WorkloadPattern.SPIKE: self._spike,
            WorkloadPattern.SINE_WAVE: self._sine_wave,
        }[pattern]

    def _steady(self, t: int, config: WorkloadConfig) -> float:
        """Constant load at base RPS."""
        return config.base_rps

    def _ramp_up(self, t: int, config: WorkloadConfig) -> float:
        """Linear ramp from base to peak over ramp_duration, then hold."""
        if t < config.ramp_duration_seconds:
            progress = t / config.ramp_duration_seconds
            return config.base_rps + (config.peak_rps - config.base_rps) * progress
        return config.peak_rps

    def _peak_hour(self, t: int, config: WorkloadConfig) -> float:
        """
        Simulate business hours traffic pattern:
        - Low baseline for first 20% of duration (early morning)
        - Ramp to peak over next 15% (morning ramp)
        - Hold peak for 30% (business hours)
        - Gradual decline for 20% (afternoon)
        - Return to baseline for last 15% (evening)
        """
        d = config.duration_seconds
        phase = t / d

        if phase < 0.20:
            return config.base_rps
        elif phase < 0.35:
            progress = (phase - 0.20) / 0.15
            return config.base_rps + (config.peak_rps - config.base_rps) * progress
        elif phase < 0.65:
            return config.peak_rps
        elif phase < 0.85:
            progress = (phase - 0.65) / 0.20
            return config.peak_rps - (config.peak_rps - config.base_rps) * progress
        else:
            return config.base_rps

    def _spike(self, t: int, config: WorkloadConfig) -> float:
        """
        Sudden traffic spike at 40% of duration, lasting 10% of duration.
        Tests auto-scaling and circuit breaker behavior.
        """
        d = config.duration_seconds
        phase = t / d

        if 0.40 <= phase <= 0.50:
            return config.peak_rps
        return config.base_rps

    def _sine_wave(self, t: int, config: WorkloadConfig) -> float:
        """Oscillating load between base and peak. Tests adaptive behavior."""
        amplitude = (config.peak_rps - config.base_rps) / 2
        midpoint = config.base_rps + amplitude
        return midpoint + amplitude * math.sin(2 * math.pi * t / config.duration_seconds)

    def generate_locust_config(self, plan: WorkloadPlan) -> str:
        """
        Generate a Locust load test configuration file from the workload plan.
        This is what actually executes inside the digital twin.
        """
        profiles = plan.config.request_profiles

        lines = []
        lines.append('"""Auto-generated Locust load test from workload plan."""')
        lines.append("from locust import HttpUser, task, between, constant_throughput")
        lines.append("")
        lines.append("")
        lines.append("class SimulatedUser(HttpUser):")
        lines.append(f"    wait_time = between(0.1, {plan.config.think_time_ms / 1000})")
        lines.append("")

        for profile in profiles:
            weight = max(1, round(profile.weight * 100))
            lines.append(f"    @task({weight})")
            lines.append(f"    def {profile.name}(self):")
            if profile.method == "GET":
                lines.append(f'        self.client.get("{profile.path}", '
                           f'timeout={profile.timeout_ms / 1000})')
            elif profile.method == "POST":
                lines.append(f'        self.client.post("{profile.path}", '
                           f'json={{"test": True}}, timeout={profile.timeout_ms / 1000})')
            elif profile.method == "PUT":
                lines.append(f'        self.client.put("{profile.path}", '
                           f'json={{"test": True}}, timeout={profile.timeout_ms / 1000})')
            lines.append("")

        return "\n".join(lines)


def workload_example():
    """Example: generate a peak-hour workload plan for a web API."""
    generator = SyntheticWorkloadGenerator()

    config = WorkloadConfig(
        pattern=WorkloadPattern.PEAK_HOUR,
        base_rps=50,
        peak_rps=500,
        duration_seconds=600,      # 10-minute simulation
        concurrent_users=100,
        think_time_ms=200,
        request_profiles=PRODUCTION_PROFILES["web_api"],
    )

    plan = generator.generate_plan(config)

    print(f"Workload plan: {config.pattern.value}")
    print(f"Duration: {config.duration_seconds}s")
    print(f"Total requests: {plan.total_requests:,}")
    print(f"Data transfer: {plan.estimated_data_transfer_mb} MB")
    print()

    # Show RPS at key moments
    key_points = [0, 60, 150, 210, 300, 420, 510, 570]
    print("RPS over time:")
    for t in key_points:
        if t < len(plan.snapshots):
            snap = plan.snapshots[t]
            bar = "#" * int(snap.target_rps / 10)
            print(f"  t={t:>3}s: {snap.target_rps:>6.1f} RPS, "
                  f"{snap.concurrent_users:>3} users  {bar}")


if __name__ == "__main__":
    workload_example()
