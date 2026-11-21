"""Traces from the API and the scheduler, each under the trace of whatever called it.

The in-process tests hand each instrumentation a provider of their own, so no
other test's spans reach it. The launcher tests run `opentelemetry-instrument`
itself, the way production starts.
"""

import json
import os
import subprocess  # nosec B404
import sys
import threading
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import redis
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from life.api import API_PREFIX
from life.api import article_import_worker
from life.api.main import create_api
from life.config import get_settings
from life.database.session import get_db_engine
from life.database.session import get_sqlalchemy_session
from life.opentelemetry_distro import span_processors
from life.scheduler import jobs
from tests.utils.database import get_test_runner_settings
from tests.utils.database import get_test_session
from tests.utils.database import test_settings

USER_EMAIL = 'testloginregular@testuser.com'
# The header strategy looks the user up in SQL, and the route reads its batch from Redis.
SIGNED_IN = {'Remote-User': 'testloginregular', 'Remote-Email': USER_EMAIL}
BATCH_STATUS_ROUTE = f'{API_PREFIX}/articles/bulk-import/{{batch_id}}'
CALLER_TRACE_ID = '4bf92f3577b34da6a3ce929d0e0e4736'
CALLER_SPAN_ID = '00f067aa0ba902b7'
FLOW_ID = 'flow-under-test'


@pytest.fixture(scope='module')
def span_exporter():
    return InMemorySpanExporter()


@pytest.fixture(scope='module')
def tracer_provider(span_exporter):
    provider = TracerProvider()
    for processor in span_processors():
        provider.add_span_processor(processor)
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    yield provider
    provider.shutdown()


@pytest.fixture
def finished_spans(tracer_provider, span_exporter):
    span_exporter.clear()
    return span_exporter.get_finished_spans


@pytest.fixture(scope='module')
def traced_api(tracer_provider):
    api = create_api(settings=test_settings)
    api.dependency_overrides[get_sqlalchemy_session] = get_test_session
    api.dependency_overrides[get_settings] = get_test_runner_settings
    redis_client = redis.Redis(host=test_settings.redis.host, port=test_settings.redis.port, db=test_settings.redis.db)
    api.state.redis_client = redis_client
    FastAPIInstrumentor.instrument_app(api, tracer_provider=tracer_provider)
    SQLAlchemyInstrumentor().instrument(engine=get_db_engine(test_settings), tracer_provider=tracer_provider)
    RedisInstrumentor().instrument(tracer_provider=tracer_provider)
    yield TestClient(api)
    RedisInstrumentor().uninstrument()
    SQLAlchemyInstrumentor().uninstrument()
    FastAPIInstrumentor.uninstrument_app(api)
    redis_client.close()


def route_span(spans):
    (span,) = [s for s in spans if s.kind == SpanKind.SERVER and s.attributes.get('http.route') == BATCH_STATUS_ROUTE]
    return span


def scope_names(spans) -> set[str]:
    return {span.instrumentation_scope.name for span in spans}


def test_one_request_is_one_trace_holding_its_route_sql_and_redis_spans(traced_api, finished_spans, caplog):
    response = traced_api.get(BATCH_STATUS_ROUTE.format(batch_id='no-such-batch'), headers=SIGNED_IN)

    spans = finished_spans()
    route = route_span(spans)
    trace_id = trace.format_trace_id(route.context.trace_id)
    assert {span.context.trace_id for span in spans} == {route.context.trace_id}
    assert {'opentelemetry.instrumentation.sqlalchemy', 'opentelemetry.instrumentation.redis'} <= scope_names(spans)
    assert response.headers['X-Request-ID'] == trace_id
    assert response.headers['traceparent'].startswith(f'00-{trace_id}-')
    (completed,) = [r.msg for r in caplog.records if isinstance(r.msg, dict) and r.msg.get('event') == 'request_completed']
    assert completed['trace_id'] == trace_id


def test_a_request_under_a_callers_traceparent_is_its_child_and_carries_its_baggage(traced_api, finished_spans):
    caller = {'traceparent': f'00-{CALLER_TRACE_ID}-{CALLER_SPAN_ID}-01', 'baggage': f'caller.flow.id={FLOW_ID}'}
    response = traced_api.get(BATCH_STATUS_ROUTE.format(batch_id='no-such-batch'), headers=SIGNED_IN | caller)

    spans = finished_spans()
    route = route_span(spans)
    assert trace.format_trace_id(route.context.trace_id) == CALLER_TRACE_ID
    assert route.parent.is_remote
    assert trace.format_span_id(route.parent.span_id) == CALLER_SPAN_ID
    assert {span.attributes.get('caller.flow.id') for span in spans} == {FLOW_ID}
    assert response.headers['X-Request-ID'] == CALLER_TRACE_ID


def test_a_job_run_is_a_span_named_for_the_job_holding_its_run_id(tracer_provider, finished_spans, monkeypatch, caplog):
    monkeypatch.setattr(jobs, 'tracer', tracer_provider.get_tracer(jobs.__name__))

    @jobs.job_logger
    def traced_job(settings):
        jobs.logger.info('traced_job_ran')

    traced_job(test_settings)

    (span,) = [s for s in finished_spans() if s.name == 'traced_job']
    (ran,) = [r.msg for r in caplog.records if isinstance(r.msg, dict) and r.msg.get('event') == 'traced_job_ran']
    assert span.attributes['job.run_id'] == ran['job_run_id']
    assert ran['trace_id'] == trace.format_trace_id(span.context.trace_id)


def test_a_queued_import_runs_under_the_request_that_queued_it_and_polling_makes_no_span(
    traced_api, tracer_provider, span_exporter, finished_spans, monkeypatch
):
    monkeypatch.setattr(article_import_worker, 'tracer', tracer_provider.get_tracer(article_import_worker.__name__))
    redis_client = traced_api.app.state.redis_client
    redis_client.delete(article_import_worker.QUEUE_KEY, article_import_worker.PAUSE_KEY)
    caller = {'traceparent': f'00-{CALLER_TRACE_ID}-{CALLER_SPAN_ID}-01', 'baggage': f'caller.flow.id={FLOW_ID}'}
    traced_api.post(f'{API_PREFIX}/articles/bulk-import', json={'urls': ['https://example.com/traced']}, headers=SIGNED_IN | caller)
    (queued_by,) = [s for s in finished_spans() if s.kind == SpanKind.SERVER]
    worker = article_import_worker.ArticleImportWorker(redis_client, test_settings)

    span_exporter.clear()
    _, popped = worker._poll()
    assert finished_spans() == ()
    with patch.object(article_import_worker, 'summarize_and_create_article', return_value=MagicMock(title='Traced')):
        worker._process_item(json.loads(popped[1]))

    (imported,) = [s for s in finished_spans() if s.name == 'article_import']
    assert imported.parent.span_id == queued_by.context.span_id
    assert trace.format_trace_id(imported.context.trace_id) == CALLER_TRACE_ID
    assert imported.attributes['caller.flow.id'] == FLOW_ID
    for key in redis_client.keys('article_import:*'):
        redis_client.delete(key)


PROBE = """
from opentelemetry import baggage, context, trace
context.attach(baggage.set_baggage('caller.flow.id', 'flow-under-test'))
with trace.get_tracer('probe').start_as_current_span('probe'):
    pass
provider = trace.get_tracer_provider()
print(type(provider).__name__)
provider.force_flush() if hasattr(provider, 'force_flush') else None
"""


def run_under_launcher(**otel_env: str) -> str:
    """Run the probe as production starts the app, with only the `OTEL_*` variables given."""
    inherited = {k: v for k, v in os.environ.items() if not k.startswith('OTEL_') and k not in {'TRACEPARENT', 'TRACESTATE', 'BAGGAGE'}}
    launcher = Path(sys.executable).with_name('opentelemetry-instrument')
    result = subprocess.run(  # nosec B603
        [str(launcher), sys.executable, '-c', PROBE], env=inherited | otel_env, capture_output=True, text=True, timeout=60, check=True
    )
    return result.stdout.strip()


def test_with_no_endpoint_named_no_tracer_provider_is_installed():
    assert run_under_launcher() == 'ProxyTracerProvider'


def test_with_an_endpoint_named_spans_leave_over_otlp_http_carrying_the_baggage():
    received: list[tuple[str, str, bytes]] = []

    class ReceivedExports(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.headers['Content-Type'], self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    collector = HTTPServer(('127.0.0.1', 0), ReceivedExports)
    threading.Thread(target=collector.serve_forever, daemon=True).start()
    try:
        assert run_under_launcher(OTEL_EXPORTER_OTLP_ENDPOINT=f'http://127.0.0.1:{collector.server_port}') == 'TracerProvider'
    finally:
        collector.shutdown()

    ((path, content_type, body),) = received
    assert (path, content_type) == ('/v1/traces', 'application/x-protobuf')
    request = ExportTraceServiceRequest.FromString(body)
    (span,) = [span for resource in request.resource_spans for scope in resource.scope_spans for span in scope.spans]
    assert {a.key: a.value.string_value for a in span.attributes} == {'caller.flow.id': FLOW_ID}
