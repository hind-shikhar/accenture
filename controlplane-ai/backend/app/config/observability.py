from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import start_http_server

# Initialize basic OpenTelemetry
resource = Resource.create({"service.name": "controlplane-api"})

# Tracing
trace.set_tracer_provider(TracerProvider(resource=resource))

# Metrics
# For a real implementation, you'd configure the OpenTelemetry Prometheus exporter
# For this MVP, we will just use the standard prometheus_client to expose /metrics manually

from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter("controlplane_requests_total", "Total requests", ["method", "endpoint"])
REQUEST_LATENCY = Histogram("controlplane_request_latency_seconds", "Request latency", ["endpoint"])
MODEL_COST = Counter("controlplane_model_cost_usd", "Estimated cost", ["model"])

def init_observability(app):
    FastAPIInstrumentor.instrument_app(app)
    # Expose prometheus metrics on a different port or same
    # We will just expose them via a fast api endpoint or start a thread
    start_http_server(9090)
