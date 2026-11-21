// The tracer always runs so every request sends a traceparent; spans and logs leave only where VITE_OTEL_ENDPOINT is set.

import { ROOT_CONTEXT, SpanKind, SpanStatusCode, context, isSpanContextValid, logs, propagation, trace } from '@opentelemetry/api'
import type { Attributes, Context, Span } from '@opentelemetry/api'
import { W3CTraceContextPropagator } from '@opentelemetry/core'
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-http'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { registerInstrumentations } from '@opentelemetry/instrumentation'
import { DocumentLoadInstrumentation } from '@opentelemetry/instrumentation-document-load'
import { defaultResource, resourceFromAttributes } from '@opentelemetry/resources'
import { BatchLogRecordProcessor, LoggerProvider } from '@opentelemetry/sdk-logs'
import { BatchSpanProcessor, StackContextManager, TracerProvider } from '@opentelemetry/sdk-trace'
import {
  ATTR_DEPLOYMENT_ENVIRONMENT_NAME,
  ATTR_ERROR_TYPE,
  ATTR_HTTP_REQUEST_METHOD,
  ATTR_HTTP_RESPONSE_STATUS_CODE,
  ATTR_SERVER_ADDRESS,
  ATTR_SERVICE_NAME,
  ATTR_URL_FULL,
  ATTR_URL_PATH,
  ATTR_USER_AGENT_ORIGINAL,
} from '@opentelemetry/semantic-conventions'
import { START_LOCATION, type RouteLocationNormalized, type Router } from 'vue-router'

export const SERVICE_NAME = 'life-vue'

// Incubating semantic conventions, written out because the package's incubating entry may rename them.
const ATTR_SESSION_ID = 'session.id'
const ATTR_URL_TEMPLATE = 'url.template'
const ATTR_BROWSER_LANGUAGE = 'browser.language'

// A root span closes this long after its last request answers; a later request opens a root of its own.
const ROOT_IDLE_MS = 1000
const ROOT_LIMIT_MS = 30_000

const SESSION_STORAGE_KEY = 'life.telemetry.session-id'

const tracer = trace.getTracer(SERVICE_NAME)
export const telemetryLogger = logs.getLogger(SERVICE_NAME)

// A navigation roots the requests its page makes; an activity roots requests made after the page settled, such as a click's.
interface OpenRoot {
  kind: 'navigation' | 'activity'
  span: Span
  context: Context
  requestsInFlight: number
  settled: boolean
  idleTimer?: ReturnType<typeof setTimeout>
  limitTimer: ReturnType<typeof setTimeout>
}

let openRoot: OpenRoot | undefined
let latestRootContext: Context = ROOT_CONTEXT
let currentRoute = ''

export interface TelemetryOptions {
  endpoint?: string
  ingestToken?: string
  environment: string
}

function optionsFromBuild(): TelemetryOptions {
  return {
    endpoint: import.meta.env.VITE_OTEL_ENDPOINT || undefined,
    ingestToken: import.meta.env.VITE_OTEL_INGEST_TOKEN || undefined,
    environment: import.meta.env.MODE,
  }
}

export function startTelemetry(options: TelemetryOptions = optionsFromBuild()): void {
  const resource = defaultResource().merge(
    resourceFromAttributes({
      [ATTR_SERVICE_NAME]: SERVICE_NAME,
      [ATTR_DEPLOYMENT_ENVIRONMENT_NAME]: options.environment,
      [ATTR_SESSION_ID]: tabSessionId(),
      [ATTR_BROWSER_LANGUAGE]: navigator.language,
      [ATTR_USER_AGENT_ORIGINAL]: navigator.userAgent,
    })
  )
  const base = options.endpoint?.replace(/\/+$/, '')
  const headers: Record<string, string> = options.ingestToken ? { Authorization: `Bearer ${options.ingestToken}` } : {}

  context.setGlobalContextManager(new StackContextManager().enable())
  propagation.setGlobalPropagator(new W3CTraceContextPropagator())
  const tracerProvider = new TracerProvider({
    resource,
    spanProcessors: base ? [new BatchSpanProcessor({ exporter: new OTLPTraceExporter({ url: `${base}/v1/traces`, headers }) })] : [],
  })
  trace.setGlobalTracerProvider(tracerProvider)
  const loggerProvider = base
    ? new LoggerProvider({
        resource,
        processors: [new BatchLogRecordProcessor({ exporter: new OTLPLogExporter({ url: `${base}/v1/logs`, headers }) })],
      })
    : undefined
  if (loggerProvider) logs.setGlobalLoggerProvider(loggerProvider)

  const pageLoad = beginRoot('navigation', 'navigation', { 'navigation.type': 'page_load' }, performance.timeOrigin)
  if (base) {
    parentDocumentLoadOn(pageLoad.context)
    registerInstrumentations({ instrumentations: [new DocumentLoadInstrumentation()] })
  }

  // Each batch processor's own hide listener runs first; this one ends the open root and flushes that span too.
  const endAndFlush = () => {
    if (openRoot) endRoot(openRoot)
    void tracerProvider.forceFlush()
    void loggerProvider?.forceFlush()
  }
  window.addEventListener('pagehide', endAndFlush)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') endAndFlush()
  })
}

/** Open a navigation span on each route change, and name it for the route it reached. */
export function traceNavigations(router: Router): void {
  router.beforeEach((_to, from) => {
    // The page load's own span covers the first navigation and any redirect inside it.
    if (from !== START_LOCATION) beginRoot('navigation', 'navigation', { 'navigation.type': 'route_change' })
  })
  router.afterEach((to, from, failure) => {
    currentRoute = routeOf(to)
    const navigation = openRoot
    if (navigation?.kind !== 'navigation') return
    navigation.span.updateName(`navigation ${currentRoute}`)
    navigation.span.setAttributes({
      [ATTR_URL_PATH]: to.path,
      'navigation.route': currentRoute,
      'navigation.from': from === START_LOCATION ? '' : from.fullPath,
    })
    if (failure) navigation.span.setAttribute('navigation.failure', failure.message)
    navigation.settled = true
    scheduleIdleEnd(navigation)
  })
}

export interface ApiRequestTrace {
  /** The request's trace id, which the API answers in `X-Request-ID`; undefined where no tracer runs. */
  readonly traceId: string | undefined
  /** The propagation headers the request carries. */
  readonly headers: Record<string, string>
  /** Run `fn` with the request's span active, so a log record written in it names the request. */
  inContext<T>(fn: () => T): T
  end(outcome: { status?: number; errorType?: string }): void
}

/** Start the client span for one API request, under the open root, or under a new activity root where none is open. */
export function startApiRequest(method: string, url: string, path: string): ApiRequestTrace {
  const root = openRoot ?? beginActivity()
  const template = urlTemplate(path)
  const span = tracer.startSpan(
    `${method} ${template}`,
    {
      kind: SpanKind.CLIENT,
      attributes: {
        [ATTR_HTTP_REQUEST_METHOD]: method,
        [ATTR_URL_FULL]: url,
        [ATTR_URL_TEMPLATE]: template,
        [ATTR_SERVER_ADDRESS]: hostOf(url),
      },
    },
    root.context
  )
  const spanContext = trace.setSpan(root.context, span)
  const headers: Record<string, string> = {}
  propagation.inject(spanContext, headers)
  root.requestsInFlight += 1
  clearTimeout(root.idleTimer)

  return {
    traceId: isSpanContextValid(span.spanContext()) ? span.spanContext().traceId : undefined,
    headers,
    inContext: (fn) => context.with(spanContext, fn),
    end({ status, errorType }) {
      if (status !== undefined) span.setAttribute(ATTR_HTTP_RESPONSE_STATUS_CODE, status)
      if (errorType) {
        span.setAttribute(ATTR_ERROR_TYPE, errorType)
        span.setStatus({ code: SpanStatusCode.ERROR })
      }
      span.end()
      root.requestsInFlight -= 1
      scheduleIdleEnd(root)
    },
  }
}

/** The context a log record is written in: the active span's, else the latest root's, so a store's line after an await joins its request's trace. */
export function logContext(): Context {
  const active = context.active()
  return trace.getSpan(active) ? active : latestRootContext
}

/** A path with each numeric segment replaced, so `/tasks/12/complete` reads `/tasks/{id}/complete`. */
export function urlTemplate(path: string): string {
  return (path.split('?')[0] ?? '').replace(/\/\d+(?=\/|$)/g, '/{id}')
}

function beginActivity(): OpenRoot {
  const route = currentRoute || window.location.pathname
  return beginRoot('activity', `activity ${route}`, { [ATTR_URL_PATH]: window.location.pathname, 'activity.route': route })
}

function beginRoot(kind: OpenRoot['kind'], name: string, attributes: Attributes, startTime?: number): OpenRoot {
  if (openRoot) endRoot(openRoot)
  const span = tracer.startSpan(name, { root: true, startTime, attributes })
  const root: OpenRoot = {
    kind,
    span,
    context: trace.setSpan(ROOT_CONTEXT, span),
    requestsInFlight: 0,
    settled: kind === 'activity',
    limitTimer: setTimeout(() => endRoot(root), ROOT_LIMIT_MS),
  }
  openRoot = root
  latestRootContext = root.context
  return root
}

function scheduleIdleEnd(root: OpenRoot): void {
  clearTimeout(root.idleTimer)
  if (openRoot !== root || !root.settled || root.requestsInFlight > 0) return
  root.idleTimer = setTimeout(() => endRoot(root), ROOT_IDLE_MS)
}

function endRoot(root: OpenRoot): void {
  clearTimeout(root.idleTimer)
  clearTimeout(root.limitTimer)
  if (openRoot === root) openRoot = undefined
  root.span.end()
}

function routeOf(to: RouteLocationNormalized): string {
  return to.matched[to.matched.length - 1]?.path ?? to.path
}

// The document-load instrumentation parents its span on a traceparent meta tag, which puts it in the page load's trace.
function parentDocumentLoadOn(parent: Context): void {
  const carrier: Record<string, string> = {}
  propagation.inject(parent, carrier)
  if (!carrier.traceparent) return
  const meta = document.createElement('meta')
  meta.name = 'traceparent'
  meta.content = carrier.traceparent
  document.head.append(meta)
}

// One id per browser tab, kept across reloads, so a tab's traces group without a login.
function tabSessionId(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (existing) return existing
    const created = crypto.randomUUID()
    sessionStorage.setItem(SESSION_STORAGE_KEY, created)
    return created
  } catch {
    return crypto.randomUUID()
  }
}

function hostOf(url: string): string {
  try {
    return new URL(url, window.location.href).hostname
  } catch {
    return ''
  }
}
