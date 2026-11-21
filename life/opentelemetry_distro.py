"""The distro and configurator `opentelemetry-instrument` loads for this app.

The API and the scheduler start under `opentelemetry-instrument`, which finds
these two through this package's entry points. A process whose environment
names an OTLP endpoint exports its traces there over HTTP. One that names none
keeps the SDK disabled and instruments no library, so an install that sets no
`OTEL_*` variable runs as it would with no tracing at all.

Every `OTEL_*` default here is a `setdefault`, so the environment overrides it.
"""

import os

from opentelemetry.environment_variables import OTEL_LOGS_EXPORTER
from opentelemetry.environment_variables import OTEL_METRICS_EXPORTER
from opentelemetry.environment_variables import OTEL_TRACES_EXPORTER
from opentelemetry.instrumentation.distro import BaseDistro
from opentelemetry.instrumentation.environment_variables import OTEL_PYTHON_DISABLED_INSTRUMENTATIONS
from opentelemetry.processor.baggage import ALLOW_ALL_BAGGAGE_KEYS
from opentelemetry.processor.baggage import BaggageSpanProcessor
from opentelemetry.sdk._configuration import _OTelSDKConfigurator
from opentelemetry.sdk.environment_variables import OTEL_EXPORTER_OTLP_ENDPOINT
from opentelemetry.sdk.environment_variables import OTEL_EXPORTER_OTLP_PROTOCOL
from opentelemetry.sdk.environment_variables import OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
from opentelemetry.sdk.environment_variables import OTEL_SDK_DISABLED
from opentelemetry.sdk.trace import SpanProcessor

# The container healthcheck calls it every thirty seconds, and its span would
# name neither a caller nor any work. A pattern is searched for in the full URL.
UNTRACED_URLS = '/health$'


def endpoint_named() -> bool:
    return bool(os.environ.get(OTEL_EXPORTER_OTLP_ENDPOINT) or os.environ.get(OTEL_EXPORTER_OTLP_TRACES_ENDPOINT))


def sdk_disabled() -> bool:
    return os.environ.get(OTEL_SDK_DISABLED, '').strip().lower() == 'true'


def span_processors() -> list[SpanProcessor]:
    """What every span passes through ahead of its export.

    Each baggage member the caller sent is copied onto each span, so a caller's
    own context, such as the flow it runs in, reaches these spans while this
    app's code names none of it.
    """
    return [BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS)]


class Distro(BaseDistro):
    """Set the defaults the configurator and the instrumentations then read."""

    def _configure(self, **kwargs):
        if not endpoint_named():
            os.environ[OTEL_SDK_DISABLED] = 'true'
        if sdk_disabled():
            os.environ[OTEL_PYTHON_DISABLED_INSTRUMENTATIONS] = '*'
            return
        os.environ.setdefault(OTEL_TRACES_EXPORTER, 'otlp')
        # Logs already leave through stderr, and nothing reads metrics from here yet.
        os.environ.setdefault(OTEL_METRICS_EXPORTER, 'none')
        os.environ.setdefault(OTEL_LOGS_EXPORTER, 'none')
        os.environ.setdefault(OTEL_EXPORTER_OTLP_PROTOCOL, 'http/protobuf')
        os.environ.setdefault('OTEL_PYTHON_FASTAPI_EXCLUDED_URLS', UNTRACED_URLS)


class Configurator(_OTelSDKConfigurator):
    """Install the tracer provider, with the baggage processor ahead of the exporter."""

    def _configure(self, **kwargs):
        if sdk_disabled():
            return
        super()._configure(span_processors=span_processors(), **kwargs)
