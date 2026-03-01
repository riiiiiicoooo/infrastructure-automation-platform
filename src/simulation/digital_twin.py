"""
Digital Twin - Reference Implementation
Manages containerized simulation environments that mirror production topology
for pre-deployment validation.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum
import json


class TwinStatus(Enum):
    CREATING = "creating"
    READY = "ready"
    RUNNING_TESTS = "running_tests"
    COMPLETED = "completed"
    FAILED = "failed"
    TORN_DOWN = "torn_down"


class TestResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass
class TestCase:
    name: str
    suite: str             # "integration", "performance", "chaos", "regression"
    result: TestResult
    duration_ms: int
    expected: Optional[str] = None
    actual: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class TestSuite:
    name: str
    total: int
    passed: int
    failed: int
    skipped: int
    duration_ms: int
    tests: list[TestCase] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total


@dataclass
class SimulationResult:
    twin_id: str
    deployment_id: str
    status: str
    duration_seconds: int
    suites: list[TestSuite]
    verdict: str               # "pass" or "fail"
    blocking_failures: list[str]
    cost_estimate: float

    @property
    def total_tests(self) -> int:
        return sum(s.total for s in self.suites)

    @property
    def total_passed(self) -> int:
        return sum(s.passed for s in self.suites)


@dataclass
class TwinEnvironment:
    id: str
    deployment_id: str
    source_environment: str      # "production" or "staging"
    topology: dict               # Docker Compose equivalent structure
    status: TwinStatus = TwinStatus.CREATING
    created_at: datetime = field(default_factory=datetime.utcnow)
    ready_at: Optional[datetime] = None
    torn_down_at: Optional[datetime] = None


class DigitalTwinManager:
    """
    Manages ephemeral simulation environments for pre-deployment testing.

    Each twin is a containerized replica of the target environment's
    topology, generated from the current Terraform state. Twins are
    created on demand, run the test suite, and are torn down after.

    In production, this orchestrates Docker Compose via the Docker API.
    This reference implementation demonstrates the topology generation,
    test orchestration, and result evaluation logic.
    """

    def __init__(self):
        self.twins: dict[str, TwinEnvironment] = {}

    def create_twin(
        self,
        deployment_id: str,
        source_environment: str,
        resource_topology: list[dict],
    ) -> TwinEnvironment:
        """
        Create a containerized twin from the target environment's topology.

        resource_topology is the list of resources from the CMDB with
        their configurations and dependencies.
        """
        twin_id = f"twin-{deployment_id}"

        topology = self._generate_compose_topology(resource_topology)

        twin = TwinEnvironment(
            id=twin_id,
            deployment_id=deployment_id,
            source_environment=source_environment,
            topology=topology,
        )

        self.twins[twin_id] = twin

        # In production: docker-compose up -d with the generated topology
        # Spin-up time target: < 10 minutes
        twin.status = TwinStatus.READY
        twin.ready_at = datetime.utcnow()

        return twin

    def _generate_compose_topology(self, resources: list[dict]) -> dict:
        """
        Generate Docker Compose service definitions from production resources.
        Maps cloud resources to container equivalents.
        """
        services = {}

        resource_to_container = {
            "ec2_instance": self._map_compute,
            "rds_instance": self._map_database,
            "elasticache": self._map_cache,
            "s3_bucket": self._map_storage,
            "alb": self._map_loadbalancer,
        }

        for resource in resources:
            resource_type = resource.get("resource_type", "")
            mapper = resource_to_container.get(resource_type)
            if mapper:
                service_name, service_config = mapper(resource)
                services[service_name] = service_config

        return {
            "version": "3.8",
            "services": services,
            "networks": {
                "twin-net": {"driver": "bridge"},
            },
        }

    def _map_compute(self, resource: dict) -> tuple[str, dict]:
        """Map EC2 instance to a container."""
        name = resource.get("name", "app")
        config = resource.get("configuration", {})

        # Estimate container resources from instance type
        instance_type = config.get("instance_type", "t3.medium")
        cpu_map = {"t3.medium": "1.0", "t3.large": "2.0", "c5.xlarge": "4.0"}
        mem_map = {"t3.medium": "2g", "t3.large": "4g", "c5.xlarge": "8g"}

        return name, {
            "image": f"twin-{name}:latest",
            "deploy": {
                "resources": {
                    "limits": {
                        "cpus": cpu_map.get(instance_type, "1.0"),
                        "memory": mem_map.get(instance_type, "2g"),
                    },
                },
            },
            "networks": ["twin-net"],
            "healthcheck": {
                "test": ["CMD", "curl", "-f", "http://localhost:8080/health"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 3,
            },
        }

    def _map_database(self, resource: dict) -> tuple[str, dict]:
        """Map RDS instance to PostgreSQL container."""
        name = resource.get("name", "db")
        config = resource.get("configuration", {})

        return name, {
            "image": "postgres:15-alpine",
            "environment": {
                "POSTGRES_DB": name.replace("-", "_"),
                "POSTGRES_USER": "app",
                "POSTGRES_PASSWORD": "twin-test-only",
            },
            "networks": ["twin-net"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U app"],
                "interval": "5s",
                "timeout": "3s",
                "retries": 5,
            },
        }

    def _map_cache(self, resource: dict) -> tuple[str, dict]:
        """Map ElastiCache to Redis container."""
        return resource.get("name", "cache"), {
            "image": "redis:7-alpine",
            "networks": ["twin-net"],
        }

    def _map_storage(self, resource: dict) -> tuple[str, dict]:
        """Map S3 bucket to MinIO container."""
        return resource.get("name", "storage"), {
            "image": "minio/minio:latest",
            "command": "server /data",
            "environment": {
                "MINIO_ROOT_USER": "minioadmin",
                "MINIO_ROOT_PASSWORD": "minioadmin",
            },
            "networks": ["twin-net"],
        }

    def _map_loadbalancer(self, resource: dict) -> tuple[str, dict]:
        """Map ALB to nginx container."""
        return resource.get("name", "lb"), {
            "image": "nginx:alpine",
            "networks": ["twin-net"],
        }

    def run_test_suite(self, twin_id: str, change_diff: dict) -> SimulationResult:
        """
        Execute the full test suite against a twin environment.
        Returns structured results with pass/fail per suite.
        """
        twin = self.twins.get(twin_id)
        if not twin:
            raise ValueError(f"Twin {twin_id} not found")

        twin.status = TwinStatus.RUNNING_TESTS
        suites = []

        # Integration tests
        suites.append(self._run_integration_tests(twin))

        # Performance tests
        suites.append(self._run_performance_tests(twin))

        # Chaos tests
        suites.append(self._run_chaos_tests(twin))

        # Regression tests
        suites.append(self._run_regression_tests(twin))

        # Evaluate verdict
        blocking_failures = []
        for suite in suites:
            for test in suite.tests:
                if test.result == TestResult.FAIL:
                    blocking_failures.append(f"{suite.name}.{test.name}")

        verdict = "pass" if not blocking_failures else "fail"
        twin.status = TwinStatus.COMPLETED

        total_duration = sum(s.duration_ms for s in suites) // 1000

        return SimulationResult(
            twin_id=twin_id,
            deployment_id=twin.deployment_id,
            status="completed",
            duration_seconds=total_duration,
            suites=suites,
            verdict=verdict,
            blocking_failures=blocking_failures,
            cost_estimate=self._calculate_simulation_cost(total_duration),
        )

    def _run_integration_tests(self, twin: TwinEnvironment) -> TestSuite:
        """End-to-end workflow validation."""
        tests = [
            TestCase("api_health_check", "integration", TestResult.PASS, 1200),
            TestCase("database_connectivity", "integration", TestResult.PASS, 3400),
            TestCase("cache_read_write", "integration", TestResult.PASS, 890),
            TestCase("storage_upload_download", "integration", TestResult.PASS, 2100),
            TestCase("auth_flow_complete", "integration", TestResult.PASS, 4500),
            TestCase("webhook_delivery", "integration", TestResult.PASS, 1800),
        ]
        passed = len([t for t in tests if t.result == TestResult.PASS])
        return TestSuite(
            name="integration", total=len(tests), passed=passed,
            failed=len(tests) - passed, skipped=0,
            duration_ms=sum(t.duration_ms for t in tests), tests=tests,
        )

    def _run_performance_tests(self, twin: TwinEnvironment) -> TestSuite:
        """Simulated peak load testing."""
        tests = [
            TestCase(
                "baseline_100rps", "performance", TestResult.PASS, 60000,
                expected="<100ms p99", actual="72ms p99",
            ),
            TestCase(
                "peak_load_500rps", "performance", TestResult.PASS, 120000,
                expected="<200ms p99", actual="145ms p99",
            ),
            TestCase(
                "sustained_load_10min", "performance", TestResult.PASS, 600000,
                expected="<150ms p99, no errors", actual="128ms p99, 0 errors",
            ),
            TestCase(
                "connection_pool_saturation", "performance", TestResult.PASS, 30000,
                expected="graceful queuing", actual="queued 12 connections, 0 dropped",
            ),
        ]
        passed = len([t for t in tests if t.result == TestResult.PASS])
        return TestSuite(
            name="performance", total=len(tests), passed=passed,
            failed=len(tests) - passed, skipped=0,
            duration_ms=sum(t.duration_ms for t in tests), tests=tests,
        )

    def _run_chaos_tests(self, twin: TwinEnvironment) -> TestSuite:
        """Failure injection and resilience validation."""
        tests = [
            TestCase(
                "network_partition_db", "chaos", TestResult.PASS, 45000,
                expected="circuit breaker opens, requests queued",
                actual="circuit opened in 2.1s, 0 requests dropped",
            ),
            TestCase(
                "process_kill_api", "chaos", TestResult.PASS, 30000,
                expected="restart within 10s, no data loss",
                actual="restarted in 4.2s, 0 in-flight requests lost",
            ),
            TestCase(
                "disk_fill_90pct", "chaos", TestResult.PASS, 20000,
                expected="log rotation triggered, alert fired",
                actual="rotation at 85%, alert fired at 80%",
            ),
            TestCase(
                "latency_injection_500ms", "chaos", TestResult.PASS, 60000,
                expected="timeout handling, no cascading failures",
                actual="upstream timeout at 3s, retry succeeded",
            ),
        ]
        passed = len([t for t in tests if t.result == TestResult.PASS])
        return TestSuite(
            name="chaos", total=len(tests), passed=passed,
            failed=len(tests) - passed, skipped=0,
            duration_ms=sum(t.duration_ms for t in tests), tests=tests,
        )

    def _run_regression_tests(self, twin: TwinEnvironment) -> TestSuite:
        """Existing functionality preservation."""
        tests = [
            TestCase("existing_api_endpoints", "regression", TestResult.PASS, 8000),
            TestCase("database_schema_compat", "regression", TestResult.PASS, 3000),
            TestCase("config_file_parsing", "regression", TestResult.PASS, 1200),
            TestCase("monitoring_agent_reporting", "regression", TestResult.PASS, 15000),
            TestCase("log_format_unchanged", "regression", TestResult.PASS, 2000),
        ]
        passed = len([t for t in tests if t.result == TestResult.PASS])
        return TestSuite(
            name="regression", total=len(tests), passed=passed,
            failed=len(tests) - passed, skipped=0,
            duration_ms=sum(t.duration_ms for t in tests), tests=tests,
        )

    def _calculate_simulation_cost(self, duration_seconds: int) -> float:
        """Estimate compute cost for this simulation run."""
        # 16 vCPU, 32GB RAM instance at $0.544/hour (c5.4xlarge on-demand)
        hourly_rate = 0.544
        hours = duration_seconds / 3600
        return round(hourly_rate * hours, 2)

    def teardown(self, twin_id: str):
        """Tear down a twin environment after testing completes."""
        twin = self.twins.get(twin_id)
        if twin:
            twin.status = TwinStatus.TORN_DOWN
            twin.torn_down_at = datetime.utcnow()


def simulation_example():
    """Example: create twin, run tests, evaluate results."""
    manager = DigitalTwinManager()

    # Production topology from CMDB
    topology = [
        {"name": "payment-api", "resource_type": "ec2_instance",
         "configuration": {"instance_type": "c5.xlarge"}},
        {"name": "payment-db", "resource_type": "rds_instance",
         "configuration": {"instance_class": "db.r5.large"}},
        {"name": "payment-cache", "resource_type": "elasticache",
         "configuration": {}},
        {"name": "payment-lb", "resource_type": "alb",
         "configuration": {}},
    ]

    # Create twin
    twin = manager.create_twin(
        deployment_id="deploy-042",
        source_environment="production",
        resource_topology=topology,
    )
    print(f"Twin {twin.id} created with {len(twin.topology['services'])} services")

    # Run tests
    result = manager.run_test_suite(twin.id, change_diff={})

    print(f"\nSimulation verdict: {result.verdict.upper()}")
    print(f"Duration: {result.duration_seconds}s")
    print(f"Cost: ${result.cost_estimate}")
    print(f"Tests: {result.total_passed}/{result.total_tests} passed")

    for suite in result.suites:
        status = "PASS" if suite.failed == 0 else "FAIL"
        print(f"\n  [{status}] {suite.name}: {suite.passed}/{suite.total} passed")
        for test in suite.tests:
            icon = "+" if test.result == TestResult.PASS else "x"
            print(f"    [{icon}] {test.name} ({test.duration_ms}ms)")

    if result.blocking_failures:
        print(f"\nBlocking failures: {result.blocking_failures}")

    # Teardown
    manager.teardown(twin.id)


if __name__ == "__main__":
    simulation_example()
