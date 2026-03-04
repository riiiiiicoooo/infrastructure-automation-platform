# Infrastructure Automation Platform - OpenTelemetry Observability

This directory contains OpenTelemetry configuration and instrumentation for comprehensive observability of the Infrastructure Automation Platform, including traces, metrics, and logs.

## Overview

The observability stack captures telemetry for:
- **Terraform Operations**: Plan and apply durations, resource changes, state changes
- **Policy Evaluation**: Compliance check latency, violations detected
- **Incident Classification**: Classification accuracy and latency
- **HTTP Requests**: API latency, error rates by endpoint
- **Database Operations**: Query performance, connection pool metrics

## Files

- **otel_config.yaml**: OpenTelemetry Collector configuration (receivers, processors, exporters)
- **instrumentation.py**: Python SDK setup and custom span helpers
- **docker-compose.otel.yml**: Docker Compose overlay for observability stack
- **README.md**: This file

## Quick Start

### 1. Start Observability Stack

```bash
docker-compose -f docker-compose.yml -f docker-compose.otel.yml up
```

This starts:
- OpenTelemetry Collector (OTLP receivers on 4317/4318)
- Jaeger UI (trace visualization on 16686)
- Prometheus (metrics on 9090)
- Grafana (dashboards on 3000)

### 2. Initialize Telemetry in Application

```python
from observability.instrumentation import initialize_telemetry, instrument_fastapi

# Early in application startup (before creating routes)
initialize_telemetry(service_name="infrastructure-automation-platform")

# After creating FastAPI app
instrument_fastapi(app)
```

### 3. Create Custom Spans

```python
from observability.instrumentation import get_infrastructure_spans

spans = get_infrastructure_spans()

# In terraform provisioning code:
with spans.terraform_plan_span(workspace="prod", plan_file="main.tfplan") as span:
    # Your terraform plan code
    plan_result = terraform_cli.plan(workspace="prod")
    span.set_attribute("resource.count", len(plan_result.resources))

# In policy evaluation code:
with spans.policy_evaluation_span(policy_id="compliance-001", resource_count=42):
    # Your policy evaluation code
    violations = policy_engine.evaluate(resources)
```

### 4. Create Custom Metrics

```python
from opentelemetry import metrics

meter = metrics.get_meter(__name__)

# Counters are cumulative
provision_failures = meter.create_counter("provision_failures_total")

# Histograms record distribution
terraform_apply_duration = meter.create_histogram("terraform_apply_duration_seconds")

# In your code:
try:
    duration = terraform_cli.apply(plan_file)
    terraform_apply_duration.record(duration, {"workspace": "prod", "status": "success"})
except Exception as e:
    provision_failures.add(1, {"error_type": type(e).__name__})
```

## Exports

### Grafana Cloud (Production)

Set environment variables for Grafana Cloud export:

```bash
export GRAFANA_OTLP_TOKEN="your-grafana-otlp-token"
export GRAFANA_PROMETHEUS_TOKEN="your-grafana-prometheus-token"
```

Collector will export:
- Traces to Grafana Tempo
- Metrics to Grafana Cloud Prometheus

### Local Exporters (Development)

By default, the collector also exports to console/logging for debugging.

## Dashboards

### Pre-built Dashboards

Located in `grafana-dashboards/`:
- **infrastructure-terraform.json**: Terraform plan/apply metrics
- **infrastructure-policies.json**: Policy compliance dashboard
- **infrastructure-incidents.json**: Incident classification metrics

Import into Grafana at: Settings → Dashboards → Import

### Jaeger Distributed Tracing

View traces at: http://localhost:16686

Search by:
- Service: `infrastructure-automation-platform`
- Operation name: `terraform.plan`, `policy.evaluate`, `incident.classify`
- Tag filters: `operation.type=terraform`, `incident.severity=critical`

## Metrics Reference

### Histograms (Latency/Duration)

- **provisioning_duration_seconds**: End-to-end provisioning time
- **terraform_plan_duration_seconds**: `terraform plan` execution time
- **terraform_apply_duration_seconds**: `terraform apply` execution time
- **policy_evaluation_latency_ms**: Policy compliance evaluation time
- **incident_classification_latency_ms**: Incident classification latency

### Gauges (Current State)

- **active_deployments**: Number of in-progress deployments
- **active_incidents**: Count of open infrastructure incidents

### Counters (Cumulative)

- **policy_violations_total**: Total compliance violations detected
- **state_changes_total**: Total infrastructure state changes by type
- **provision_failures_total**: Total provisioning failures by error type

## Attributes on Spans

All spans include:
- `service.name`: infrastructure-automation-platform
- `deployment.environment`: prod/dev
- `operation.type`: terraform/policy/incident
- Operation-specific attributes (workspace, policy_id, incident.severity)

## Troubleshooting

### Metrics Not Appearing

1. Check collector is healthy: `curl http://localhost:13133/healthz`
2. Check application sends metrics: Look for "record" calls in code
3. Check Prometheus scrape config: http://localhost:9090/targets

### Traces Not Appearing in Jaeger

1. Verify OTLP exporter is configured in otel_config.yaml
2. Check collector logs: `docker logs infrastructure-otel-collector`
3. Verify application creates spans: `get_infrastructure_spans()`

### High Memory Usage

The memory_limiter processor may be dropping telemetry. Increase limits in otel_config.yaml:
```yaml
memory_limiter:
  limit_mib: 1024  # Increase from 512
  spike_limit_mib: 256  # Increase from 128
```

## References

- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/instrumentation/python/)
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Prometheus Metrics](https://prometheus.io/docs/concepts/data_model/)
