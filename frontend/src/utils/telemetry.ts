// The tracer always runs so every request sends a traceparent; spans and logs leave only where VITE_OTEL_ENDPOINT is set.

import { ROOT_CONTEXT, SpanKind, SpanStatusCode, context, isSpanContextValid, logs, propagation, trace } from '@opentelemetry/api'
import type { Context, Span } from '@opentelemetry/api'
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
import { START_LOCATION, type Router } from 'vue-router'

export const SERVICE_NAME = 'life-vue'

// Incubating semantic conventions, written out because the package's incubating entry may rename them.
const ATTR_SESSION_ID = 'session.id'
const ATTR_URL_TEMPLATE = 'url.template'
const ATTR_BROWSER_LANGUAGE = 'browser.language'

// A navigation span closes this long after its last request answers; a later request starts its own trace.
const NAVIGATION_IDLE_MS = 1000
const NAVIGATION_LIMIT_MS = 30_000

const SESSION_STORAGE_KEY = 'life.telemetry.session-id'

const tracer = trace.getTracer(SERVICE_NAME)
export const telemetryLogger = logs.getLogger(SERVICE_NAME)

interface OpenNavigation {
  span: Span
  context: Context
  requestsInFlight: number
  routeResolved: boolean
  idleTimer?: ReturnType<typeof setTimeout>
  limitTimer: ReturnType<typeof setTimeout>
}

let openNavigation: OpenNavigation | undefined
let latestNavigationContext: Context = ROOT_CONTEXT

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
  trace.setGlobalTracerProvider(
    new TracerProvider({
      resource,
      spanProcessors: base ? [new BatchSpanProcessor({ exporter: new OTLPTraceExporter({ url: `${base}/v1/traces`, headers }) })] : [],
    })
  )
  if (base) {
    logs.setGlobalLoggerProvider(
      new LoggerProvider({
        resource,
        processors: [new BatchLogRecordProcessor({ exporter: new OTLPLogExporter({ url: `${base}/v1/logs`, headers }) })],
      })
    )
  }

  const pageLoad = beginNavigation('page_load', performance.timeOrigin)
  if (base) {
    parentDocumentLoadOn(pageLoad.context)
    registerInstrumentations({ instrumentations: [new DocumentLoadInstrumentation()] })
  }
}

/** Open a navigation span on each route change, and name it for the route it reached. */
export function traceNavigations(router: Router): void {
  router.beforeEach((_to, from) => {
    // The page load's own span covers the first navigation and any redirect inside it.
    if (from !== START_LOCATION) beginNavigation('route_change')
  })
  router.afterEach((to, from, failure) => {
    const navigation = openNavigation
    if (!navigation) return
    const route = to.matched[to.matched.length - 1]?.path ?? to.path
    navigation.span.updateName(`navigation ${route}`)
    navigation.span.setAttributes({
      [ATTR_URL_PATH]: to.path,
      'navigation.route': route,
      'navigation.from': from === START_LOCATION ? '' : from.fullPath,
    })
    if (failure) navigation.span.setAttribute('navigation.failure', failure.message)
    navigation.routeResolved = true
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

/** Start the client span for one API request, under the navigation that is still settling, if any. */
export function startApiRequest(method: string, url: string, path: string): ApiRequestTrace {
  const navigation = openNavigation
  const parent = navigation?.context ?? ROOT_CONTEXT
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
    parent
  )
  const spanContext = trace.setSpan(parent, span)
  const headers: Record<string, string> = {}
  propagation.inject(spanContext, headers)
  if (navigation) {
    navigation.requestsInFlight += 1
    clearTimeout(navigation.idleTimer)
  }

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
      if (navigation) {
        navigation.requestsInFlight -= 1
        scheduleIdleEnd(navigation)
      }
    },
  }
}

/** The context a log record is written in: the active span's, else the latest navigation's. */
export function logContext(): Context {
  const active = context.active()
  return trace.getSpan(active) ? active : latestNavigationContext
}

/** A path with each numeric segment replaced, so `/tasks/12/complete` reads `/tasks/{id}/complete`. */
export function urlTemplate(path: string): string {
  return (path.split('?')[0] ?? '').replace(/\/\d+(?=\/|$)/g, '/{id}')
}

function beginNavigation(type: 'page_load' | 'route_change', startTime?: number): OpenNavigation {
  if (openNavigation) endNavigation(openNavigation)
  const span = tracer.startSpan('navigation', { root: true, startTime, attributes: { 'navigation.type': type } })
  const navigation: OpenNavigation = {
    span,
    context: trace.setSpan(ROOT_CONTEXT, span),
    requestsInFlight: 0,
    routeResolved: false,
    limitTimer: setTimeout(() => endNavigation(navigation), NAVIGATION_LIMIT_MS),
  }
  openNavigation = navigation
  latestNavigationContext = navigation.context
  return navigation
}

function scheduleIdleEnd(navigation: OpenNavigation): void {
  clearTimeout(navigation.idleTimer)
  if (openNavigation !== navigation || !navigation.routeResolved || navigation.requestsInFlight > 0) return
  navigation.idleTimer = setTimeout(() => endNavigation(navigation), NAVIGATION_IDLE_MS)
}

function endNavigation(navigation: OpenNavigation): void {
  clearTimeout(navigation.idleTimer)
  clearTimeout(navigation.limitTimer)
  if (openNavigation === navigation) openNavigation = undefined
  navigation.span.end()
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
