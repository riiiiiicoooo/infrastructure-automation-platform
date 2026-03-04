"""
OpenTelemetry Instrumentation for Infrastructure Automation Platform

Configures automatic instrumentation of:
- FastAPI endpoints
- HTTP client requests (to cloud providers)
- SQL queries (to state management DB)
- Custom spans for terraform operations, policy evaluation, incidents

Exports traces and metrics to Grafana Cloud via OTLP.
"""

import os
from typing import Optional, Dict, Any

# OpenTelemetry SDK imports
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

# Auto-instrumentation
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

# Utilities
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.propagators import set_default_propagator
from opentelemetry.propagators.jaeger_composite import JaegerComposite

import logging

logger = logging.getLogger(__name__)


def setup_tracing(
    service_name: str = "infrastructure-automation-platform",
    otlp_endpoint: Optional[str] = None,
) -> TracerProvider:
    """
    Configure OpenTelemetry tracing with OTLP exporter.
    
    Args:
        service_name: Identifier for this service
        otlp_endpoint: OTLP collector endpoint (default: localhost:4317)
    
    Returns:
        Configured TracerProvider for manual span creation
    """
    
    # Create resource with service metadata
    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "portfolio-ops",
        "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        "service.instance.id": os.getenv("HOSTNAME", "unknown"),
    })
    
    # Configure OTLP exporter
    otlp_endpoint = otlp_endpoint or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
    )
    
    # gRPC exporter for traces
    trace_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    
    # Create TracerProvider with batch processor
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    
    # Set as global provider
    trace.set_tracer_provider(trace_provider)
    
    # Configure propagation (W3C Trace Context + Jaeger baggage)
    set_default_propagator(JaegerComposite())
    
    logger.info(f"Tracing configured for {service_name}, exporting to {otlp_endpoint}")
    
    return trace_provider


def setup_metrics(
    service_name: str = "infrastructure-automation-platform",
    otlp_endpoint: Optional[str] = None,
) -> MeterProvider:
    """
    Configure OpenTelemetry metrics with custom instruments.
    
    Metrics include:
    - terraform_plan_duration_seconds: Histogram of terraform plan execution time
    - terraform_apply_duration_seconds: Histogram of terraform apply duration
    - active_deployments: Gauge of currently active infrastructure changes
    - policy_violations_total: Counter of compliance violations detected
    - incident_classification_latency_ms: Histogram of classification latency
    - state_changes_total: Counter of infrastructure state changes by type
    
    Args:
        service_name: Identifier for this service
        otlp_endpoint: OTLP collector endpoint
    
    Returns:
        Configured MeterProvider for manual metric creation
    """
    
    otlp_endpoint = otlp_endpoint or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
    )
    
    # Create resource
    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "portfolio-ops",
        "environment": os.getenv("ENVIRONMENT", "development"),
    })
    
    # OTLP exporter for metrics
    metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
    metric_reader = PeriodicExportingMetricReader(metric_exporter, interval_millis=30000)
    
    # Create MeterProvider
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    
    # Set as global provider
    metrics.set_meter_provider(meter_provider)
    
    # Get meter for creating instruments
    meter = meter_provider.get_meter(__name__)
    
    # Custom histograms for operation durations (in seconds)
    provisioning_duration = meter.create_histogram(
        name="provisioning_duration_seconds",
        description="Time spent provisioning infrastructure via terraform/ansible",
        unit="s",
    )
    
    terraform_plan_duration = meter.create_histogram(
        name="terraform_plan_duration_seconds",
        description="Duration of terraform plan execution",
        unit="s",
    )
    
    terraform_apply_duration = meter.create_histogram(
        name="terraform_apply_duration_seconds",
        description="Duration of terraform apply execution",
        unit="s",
    )
    
    incident_classification_latency = meter.create_histogram(
        name="incident_classification_latency_ms",
        description="Time to classify and categorize infrastructure incidents",
        unit="ms",
    )
    
    policy_eval_latency = meter.create_histogram(
        name="policy_evaluation_latency_ms",
        description="Time to evaluate compliance policies",
        unit="ms",
    )
    
    # Custom gauges for current state (dimensionless)
    active_deployments = meter.create_gauge(
        name="active_deployments",
        description="Number of currently active infrastructure deployments",
        unit="1",
    )
    
    active_incidents = meter.create_gauge(
        name="active_incidents",
        description="Count of active infrastructure incidents being investigated",
        unit="1",
    )
    
    # Custom counters for aggregate events
    policy_violations = meter.create_counter(
        name="policy_violations_total",
        description="Total number of compliance policy violations detected",
        unit="1",
    )
    
    state_changes = meter.create_counter(
        name="state_changes_total",
        description="Total infrastructure state changes executed",
        unit="1",
    )
    
    provision_failures = meter.create_counter(
        name="provision_failures_total",
        description="Total provisioning failures",
        unit="1",
    )
    
    logger.info(f"Metrics configured for {service_name}, exporting to {otlp_endpoint}")
    
    # Return meter for use in application code
    return meter_provider


class InfrastructureSpans:
    """
    Helper class for creating consistent custom spans for infrastructure operations.
    """
    
    def __init__(self):
        self.tracer = trace.get_tracer(__name__)
    
    def terraform_plan_span(self, workspace: str, plan_file: str):
        """Create span for terraform plan operation."""
        return self.tracer.start_as_current_span(
            name="terraform.plan",
            attributes={
                "terraform.workspace": workspace,
                "terraform.plan_file": plan_file,
                "operation.type": "terraform",
            },
        )
    
    def terraform_apply_span(self, workspace: str, plan_file: str, auto_approve: bool = False):
        """Create span for terraform apply operation."""
        return self.tracer.start_as_current_span(
            name="terraform.apply",
            attributes={
                "terraform.workspace": workspace,
                "terraform.plan_file": plan_file,
                "terraform.auto_approve": auto_approve,
                "operation.type": "terraform",
            },
        )
    
    def policy_evaluation_span(self, policy_id: str, resource_count: int):
        """Create span for policy compliance evaluation."""
        return self.tracer.start_as_current_span(
            name="policy.evaluate",
            attributes={
                "policy.id": policy_id,
                "policy.resource_count": resource_count,
                "operation.type": "policy",
            },
        )
    
    def incident_classification_span(self, incident_id: str, severity: str):
        """Create span for incident classification."""
        return self.tracer.start_as_current_span(
            name="incident.classify",
            attributes={
                "incident.id": incident_id,
                "incident.severity": severity,
                "operation.type": "incident",
            },
        )


def instrument_fastapi(app):
    """
    Instrument FastAPI application with OpenTelemetry.
    
    Automatically captures:
    - HTTP request/response metrics and traces
    - Endpoint latency
    - Error rates
    """
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=".*healthz,.*ready",  # Exclude health checks
        meter_provider=metrics.get_meter_provider(),
        tracer_provider=trace.get_tracer_provider(),
    )
    logger.info("FastAPI instrumented with OpenTelemetry")


def instrument_http_requests():
    """
    Instrument HTTP requests made by the application.
    
    Captures all requests made via requests library or urllib3:
    - Request/response headers and body size
    - Latency per HTTP method
    - Error rates by status code
    """
    RequestsInstrumentor().instrument(
        tracer_provider=trace.get_tracer_provider(),
    )
    logger.info("HTTP requests instrumented")


def instrument_database(engine):
    """
    Instrument SQLAlchemy database connections.
    
    Captures:
    - Query execution time
    - Query patterns and table access
    - Connection pool metrics
    """
    SQLAlchemyInstrumentor().instrument(
        engine=engine,
        service=os.getenv("SERVICE_NAME", "infrastructure-automation"),
        tracer_provider=trace.get_tracer_provider(),
    )
    logger.info("Database instrumented")


def initialize_telemetry(service_name: str = "infrastructure-automation-platform"):
    """
    Complete telemetry initialization for infrastructure automation.
    
    Sets up:
    - Tracing with OTLP exporter
    - Metrics collection
    - Auto-instrumentation of HTTP, FastAPI, and database
    - Custom spans for infrastructure operations
    
    Call this early in application startup.
    """
    
    logger.info(f"Initializing OpenTelemetry for {service_name}")
    
    # Configure tracing and metrics
    trace_provider = setup_tracing(service_name)
    meter_provider = setup_metrics(service_name)
    
    # Auto-instrument common libraries
    instrument_http_requests()
    
    logger.info(f"OpenTelemetry telemetry initialized for {service_name}")
    
    # Return providers for explicit instrument calls (FastAPI app, database engine)
    return trace_provider, meter_provider


# Convenience function for getting custom span helper
def get_infrastructure_spans() -> InfrastructureSpans:
    """Get helper for creating infrastructure-specific spans."""
    return InfrastructureSpans()
