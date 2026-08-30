import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import start_http_server, Counter, Histogram
import structlog

logger = structlog.get_logger()

resource = Resource.create({"service.name": "controlplane-api"})

tracer_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(tracer_provider)

# A TracerProvider with no exporter attached generates spans that go
# nowhere — they're created, recorded, and dropped. ConsoleSpanExporter is
# the zero-infrastructure default so `init_observability(app)` produces
# visible traces without requiring an OTLP collector to be running.
# Set OTEL_EXPORTER_OTLP_ENDPOINT to switch to a real collector instead
# (requires the optional opentelemetry-exporter-otlp-proto-grpc package —
# see requirements-optional.txt).
_otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
if _otlp_endpoint:
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint)))
        logger.info("otel_otlp_exporter_configured", endpoint=_otlp_endpoint)
    except ImportError:
        logger.warning("otel_otlp_exporter_not_installed",
                        detail="pip install opentelemetry-exporter-otlp-proto-grpc — falling back to console exporter")
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
else:
    tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

REQUEST_COUNT = Counter("controlplane_requests_total", "Total requests", ["method", "endpoint"])
REQUEST_LATENCY = Histogram("controlplane_request_latency_seconds", "Request latency", ["endpoint"])
MODEL_COST = Counter("controlplane_model_cost_usd", "Estimated cost", ["model"])

_prometheus_started = False


def init_observability(app):
    """Activate OTel FastAPI instrumentation + expose Prometheus metrics.
    Idempotent and non-fatal: a second call (e.g. an app factory invoked
    twice in the same process) or a port already bound (e.g. under a
    multi-worker/reload launcher) never crashes startup — it logs and
    continues, since observability failing to attach shouldn't take the API
    down with it."""
    global _prometheus_started
    FastAPIInstrumentor.instrument_app(app)

    if _prometheus_started:
        return
    port = int(os.getenv("PROMETHEUS_PORT", "9090"))
    try:
        start_http_server(port)
        _prometheus_started = True
        logger.info("prometheus_metrics_server_started", port=port)
    except OSError as e:
        logger.warning("prometheus_metrics_server_start_failed", port=port, error=str(e))
