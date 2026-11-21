import datetime as dt
import time
import uuid
from collections import deque

import structlog
from fastapi import Request
from opentelemetry import propagate
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()


def request_trace_id(request: Request) -> str | None:
    """The trace the request runs in: this server's span where it has one, else the caller's traceparent."""
    for span in (trace.get_current_span(), trace.get_current_span(propagate.extract(request.headers))):
        span_context = span.get_span_context()
        if span_context.is_valid:
            return trace.format_trace_id(span_context.trace_id)
    return None


# Module-level ring buffer for recent error responses (4xx/5xx).
# Accessible from admin endpoints to provide "what just happened?" visibility.
# Resets on process restart; per-worker in multi-worker setups.
recent_errors: deque[dict] = deque(maxlen=200)


class ResponseLoggerMiddleware(BaseHTTPMiddleware):
    """Logs all requests and responses from the API with request tracing."""

    async def dispatch(self, request: Request, call_next):
        """Process request with timing, logging, and request ID tracking.

        The request ID is the trace ID wherever the request has one, so a log
        line, a response and a span all name the request alike. An ID the client
        minted that differs is logged beside it as `client_request_id`.
        """
        structlog.contextvars.clear_contextvars()
        client_request_id = request.headers.get('X-Request-ID')
        request_id = request_trace_id(request) or client_request_id or str(uuid.uuid4())[:8]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        if client_request_id and client_request_id != request_id:
            structlog.contextvars.bind_contextvars(client_request_id=client_request_id)

        start_time = time.time()
        response = await call_next(request)
        process_time = round((time.time() - start_time) * 1000, 2)

        response.headers['X-Request-ID'] = request_id
        if trace.get_current_span().get_span_context().is_valid:
            TraceContextTextMapPropagator().inject(response.headers)

        if request.method == 'GET' and request.url.path == '/health':
            structlog.contextvars.clear_contextvars()
            return response

        log_data = {
            'method': request.method,
            'path': request.url.path,
            'status': response.status_code,
            'duration_ms': process_time,
        }

        if response.status_code >= 500:
            logger.error('request_completed', **log_data)
        elif response.status_code >= 400:
            logger.warning('request_completed', **log_data)
        else:
            logger.info('request_completed', **log_data)

        if response.status_code >= 400:
            recent_errors.append(
                {
                    'timestamp': dt.datetime.now(dt.UTC).isoformat(),
                    'method': request.method,
                    'path': request.url.path,
                    'status': response.status_code,
                    'duration_ms': process_time,
                    'request_id': request_id,
                }
            )

        structlog.contextvars.clear_contextvars()
        return response
