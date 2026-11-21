# Logging Configuration

## Overview

The life application uses **structlog**, rendered through the stdlib root logger. All logs go to stderr, including records from stdlib loggers such as alembic's, and Docker handles persistence via its logging driver. This is the industry-standard approach for containerized applications.

**Configuration**: `life/logger.py`

```python
LOG_FORMAT = os.environ.get('LOG_FORMAT', 'console')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG')
LOG_COLORS = os.environ.get('LOG_COLORS', 'auto')
```

## Environment Variables

### LOG_FORMAT

Controls the output format for log messages.

| Value | Description |
| --- | --- |
| `console` | Human-readable colored output |
| `json` | Structured JSON output |

`json` is the default for dev, test, and production and is required by the
CLI viewer (`ops/log_viewer.py`) and by Loki's pipeline. The dev and test
compose files set `LOG_FORMAT=${LOG_FORMAT:-json}` so the viewer always
receives structured input. Override per-service by exporting
`LOG_FORMAT=console` for raw colored output without the viewer.

**Console format example:**

```text
2026-01-13T15:30:45Z [info     ] user_login_success    filename=auth.py func_name=login lineno=45 request_id=abc12345 user_id=123
```

**JSON format example:**

```json
{"timestamp": "2026-01-13T15:30:45Z", "level": "info", "event": "user_login_success", "filename": "auth.py", "func_name": "login", "lineno": 45, "request_id": "abc12345", "user_id": 123}
```

### LOG_LEVEL

Controls which log messages are output.

| Value | Description |
| --- | --- |
| `DEBUG` (default) | All messages including detailed diagnostics |
| `INFO` | Normal operations (user login, task created, job completed) |
| `WARNING` | Recoverable issues (invalid input, retry attempts) |
| `ERROR` | Failures requiring attention (API errors, DB errors) |
| `CRITICAL` | System-level failures (can't connect to DB) |

### LOG_COLORS

Controls whether colored output is used in console format.

| Value | Description |
| --- | --- |
| `auto` (default) | Use TTY detection (colors if terminal, no colors if piped) |
| `true` | Force colors on (useful in Docker where TTY detection fails) |
| `false` | Force colors off |

## Request Tracing

Every request's log lines carry a `request_id`. Every line written inside a span also carries `trace_id` and `span_id`, added by `add_trace_context` in `life/logger.py`, so a line leads to its trace and a trace to its lines.

### Request ID Flow

The request ID is the trace ID wherever the request runs in a trace. `life/api/middleware.py` picks the first of these that exists:

1. the trace ID of the span the API is recording for the request
2. the trace ID of the caller's W3C `traceparent` header, when the API records no span
3. the caller's `X-Request-ID` header
4. eight fresh hex characters

The response echoes the result as `X-Request-ID`. Where the API recorded a span, it also returns `traceparent`, naming that span. The Vue client sends a `traceparent` on every request, so the API's `request_id` is the browser's trace ID. A caller's own `X-Request-ID` that differs from the trace ID is logged beside it as `client_request_id`.

```text
caller (CLI, job, SPA)                 FastAPI process
──────────────────────                 ───────────────
traceparent: 00-<trace>-<span>-01
baggage: <member>=<value>
X-Request-ID: abc12345 (optional)
          │
          └──── HTTP request ────────► server span, child of <span> in <trace>
                                       every baggage member copied onto each span
                                       bind_contextvars(request_id=<trace>,
                                                        client_request_id=abc12345)
◀── X-Request-ID: <trace>, traceparent: 00-<trace>-<server span>-01
```

### Traces

The API and the scheduler start under `opentelemetry-instrument`, which loads the distro in `life/opentelemetry_distro.py`. Where `OTEL_EXPORTER_OTLP_ENDPOINT` names a collector, each process exports its spans there over OTLP/HTTP: the request's route, its SQL and Redis calls, and each page `get_page` fetches. Where none is named, nothing is instrumented and nothing is exported. `/health` is never traced.

A bulk article import stores the enqueuing request's `traceparent` and `baggage` on each queued item. The worker imports each item in an `article_import` span under that request, so the import shows in the caller's trace. Its poll of the empty queue every few seconds makes no span.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | The collector's OTLP/HTTP base URL. Unset turns tracing off. |
| `OTEL_SERVICE_NAME` | `unknown_service` | The spans' `service.name`. Production sets `life-api` and `life-scheduler`. |
| `OTEL_RESOURCE_ATTRIBUTES` | unset | Extra resource attributes. Production adds the environment and the deploy color. |

Every other `OTEL_*` variable the SDK reads still applies, and overrides the distro's defaults.

Each span's resource also names the process that made it: `process.pid`, its command line, `host.name` (the container) and a `service.instance.id` drawn fresh per process. uvicorn's workers share one service name, so these are what tell one worker's spans from another's.

#### The browser's traces

The SPA traces itself as `life-vue`, from `frontend/src/utils/telemetry.ts`. Its tracer always runs, so every API request carries a `traceparent`. Spans and log records leave the browser only where the build set `VITE_OTEL_ENDPOINT`, the base URL a Collector serves OTLP/HTTP at. `VITE_OTEL_INGEST_TOKEN`, where set, goes with each post as `Authorization: Bearer <token>`. The release workflow builds the production image with both.

Each navigation is a root span named for the route it reached, and the first one starts when the browser began loading the page. The axios client in `frontend/src/api/client.ts` opens a client span for each API request under the navigation that is still settling, and the API continues that trace:

```text
navigation /countdowns                  (navigation.type=page_load)
├── documentLoad                        load timings, from the document-load instrumentation
│   ├── documentFetch
│   └── resourceFetch × each script, stylesheet and font
├── GET /users/me                       client span; the API answers X-Request-ID = this trace
│   └── life-api server span → SQL
└── GET /countdowns
    └── life-api server span → SQL
```

A navigation's span ends a second after its last request answers, and after thirty seconds at most. A request made later, such as a click's, starts a trace of its own. A log record carries the trace of the request it describes, else of the latest navigation.

#### The dev stack's Collector

The dev stack runs an OpenTelemetry Collector of its own, the `otel-collector` service, configured by `deploy-containers/otel-collector/dev.yaml`. The dev api and scheduler send to it at `http://otel-collector:4318`, as `life-api` and `life-scheduler`. The browser reaches it through Traefik at `https://otel.docker.localhost`, which the dev `vue` service passes as `VITE_OTEL_ENDPOINT`. Its receiver answers CORS for the dev app's origins, so the browser needs no token.

The Collector stamps every record `deployment.environment.name=development`, so dev records sit beside production's in one store and one filter separates them.

`LIFE_OTEL_FORWARD_ENDPOINT` decides where the records go. Set it in the shell or in `.env` to an OTLP/HTTP base URL, and the Collector forwards there. Left unset, the debug exporter prints each span in the Collector's own log:

```bash
./ops/lifeops dev logs otel-collector
```

A change to the variable takes effect on the next `lifeops dev restart`.

### Scheduler Job Correlation

Scheduler jobs are not request-scoped, so they get their own correlation token.
The `@job_logger` decorator in `life/scheduler/jobs.py` opens a span named for
the job, holding a per-invocation `job_run_id` (8-hex) as `job.run_id`. It binds
the same id into structlog contextvars for the lifetime of the job, and
persists it on the `SchedulerJobRun` row written at the end. Every log line a
job emits carries the `job_run_id` and the span's `trace_id`, so a single
execution is queryable in Loki via `{job_run_id="..."}`, and joins back to the
DB record and the trace by the same ids.

## Viewing Logs

### Development

Use the CLI to view colored logs that persist across container restarts:

```bash
# All services
./ops/lifeops dev logs

# Specific service
./ops/lifeops dev logs api
./ops/lifeops dev logs scheduler
./ops/lifeops dev logs vue
```

The logs command uses a watch loop that automatically reconnects when containers restart, and supports filter flags described in [CLI Usage](cli-traefik-usage.md).

### Testing

```bash
# View test environment logs
./ops/lifeops testing logs

# Specific service
./ops/lifeops testing logs api
```

### Production

```bash
# View production logs
./ops/lifeops prod logs

# Specific service
./ops/lifeops prod logs api
```

### Direct Docker Commands

```bash
# Follow logs for a specific container
docker logs -f life-dev-api

# View recent logs
docker logs --tail 100 life-dev-api
```

## Log Persistence

Docker handles log persistence via its logging driver. By default, Docker uses the `json-file` driver which stores logs on disk. These logs persist across container restarts.

### Accessing Docker Log Files

```bash
# Find log file location
docker inspect life-dev-api --format='{{.LogPath}}'

# View raw log file (requires sudo)
sudo cat /var/lib/docker/containers/<container-id>/<container-id>-json.log
```

### Log Rotation

Docker manages log rotation. Configure in Docker daemon settings if needed:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

## Structlog Configuration

**Configuration**: `configure_structlog` in `life/logger.py`

The structlog configuration includes:

1. **Context variable merging**: Includes request_id and other bound context
2. **Trace context**: `trace_id` and `span_id` of the current span, on structlog and stdlib lines alike
3. **Log level filtering**: Based on LOG_LEVEL environment variable
4. **Timestamp**: ISO 8601 format (UTC)
5. **Call site tracking**: Automatic filename, function name, and line number
6. **Stack info rendering**: For exception tracebacks
7. **Format rendering**: Console or JSON based on LOG_FORMAT

### Processor Chain

```python
processors = [
    structlog.contextvars.merge_contextvars,      # Include request_id, etc.
    add_trace_context,                            # Add trace_id, span_id inside a span
    structlog.processors.add_log_level,           # Add level field
    structlog.processors.TimeStamper(...),        # Add timestamp
    CallsiteParameterAdder({...}),                # Add filename, func, line
    structlog.processors.StackInfoRenderer(),     # Render stack traces
    structlog.processors.format_exc_info,         # Format exceptions
    # Final renderer: ConsoleRenderer or JSONRenderer
]
```

## Third-Party Logger Suppression

Noisy third-party loggers are raised to a quieter level. The loggers and their
levels are the `third_party_levels` mapping in `configure_stdlib_logging`, in
`life/logger.py`, and that mapping is the list.

`httpx2` and `httpcore2` cover the app's own requests. `claude_agent_sdk` is
raised to `WARNING`, because it logs the path of the Claude Code CLI it starts
at `INFO` on every model call.

## Usage Pattern

Every module uses the same simple pattern:

```python
import structlog

logger = structlog.get_logger()

# Log with structured data
logger.info('user_login_success', user_id=user.id, email=user.email)
logger.error('database_error', error=str(e), operation='create_user')
```

### Event Naming Convention

Use snake_case event names that describe what happened:

| Good | Bad |
| --- | --- |
| `user_login_success` | `logged in user` |
| `task_created` | `Created new task` |
| `api_request_failed` | `HTTP error` |
| `job_started` | `Starting job...` |

## Migration from Standard Logging

The project migrated from Python's standard logging module to structlog. Key differences:

| Standard Logging | Structlog |
| --- | --- |
| `logger = logging.getLogger(__name__)` | `logger = structlog.get_logger()` |
| `logger.info(f'User {user_id} logged in')` | `logger.info('user_login', user_id=user_id)` |
| String interpolation | Keyword arguments |
| `__name__` for logger identification | CallsiteParameterAdder for location |

## Vue Frontend Logging

The Vue 3 frontend uses **consola** with two reporters: one prints structlog's key=value line to the browser console, and one sends each line as an OpenTelemetry log record.

**Configuration**: `frontend/src/utils/logger.ts`

### Vue Logger Usage

```typescript
import { createLogger } from '@/utils/logger'

const logger = createLogger('CountdownsStore')

// Log with structured data (matches structlog's keyword arguments)
logger.info('countdown_created', { id: data.id, name: data.name })
logger.error('countdown_create_failed', { detail: error.detail, status: error.status })
```

### Output

Every build prints the key=value line, matching structlog's console format:

```text
2026-03-13T15:30:45.123Z [info   ] countdown_created              module=CountdownsStore id=42 name="Summer Trip"
```

Where the build set `VITE_OTEL_ENDPOINT`, the same line also posts to it as a log record. The event is its body, `module` and each context field are its attributes, and its trace and span are the ones it was written in. A production build logs at `info` and above, and a dev build at `debug`.

### Vue Request Tracing

The Vue API client (`frontend/src/api/client.ts`) opens a client span for every request and sends its `traceparent`. Its `request_outgoing`, `request_completed` and `request_failed` lines carry that trace ID as `request_id`, the same value the server logs as `request_id` and answers in `X-Request-ID`. So one trace ID finds the browser's span and log records and the server's spans and lines.

### Log Level Control

In development, you can change the log level at runtime via the browser console:

```javascript
window.__setLogLevel('debug')  // Show all logs
window.__setLogLevel('error')  // Errors only
```

## Benefits

1. **Structured data**: All log data is structured, enabling filtering and analysis
2. **Request tracing**: Correlate logs across services with request_id
3. **Consistent format**: Same output format across all services (Python + Vue)
4. **Environment flexibility**: Switch between console and JSON with one variable
5. **No file management**: Docker handles persistence and rotation
6. **Industry standard**: Follows 12-factor app logging principles
