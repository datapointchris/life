import { test, expect, type Route } from '@playwright/test'

// The OTLP posts the SPA sends to the endpoint the test stack names, answered here with page.route.
// How a log line becomes a record is covered by src/utils/__tests__/logger.test.ts.

const isDevEnv = process.env.E2E_ENV === 'dev'
const OTLP = isDevEnv ? 'https://otel.docker.localhost' : 'https://otel.test.localhost:8443'
const API = isDevEnv ? 'https://api.docker.localhost/api/v1/' : 'https://api.test.localhost:8443/api/v1/'
const SPAN_KIND_CLIENT = 3

interface OtlpAttribute {
  key: string
  value: { stringValue?: string }
}
interface OtlpResource {
  attributes: OtlpAttribute[]
}
interface OtlpSpan {
  traceId: string
  spanId: string
  parentSpanId?: string
  name: string
  kind: number
}
interface OtlpLogRecord {
  traceId?: string
  spanId?: string
  body?: { stringValue?: string }
}
interface OtlpTraces {
  resourceSpans: { resource: OtlpResource; scopeSpans: { spans: OtlpSpan[] }[] }[]
}
interface OtlpLogs {
  resourceLogs: { resource: OtlpResource; scopeLogs: { logRecords: OtlpLogRecord[] }[] }[]
}

const serviceName = (resource: OtlpResource) => resource.attributes.find((attribute) => attribute.key === 'service.name')?.value.stringValue

async function accept(route: Route) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    headers: { 'Access-Control-Allow-Origin': '*' },
    body: '{}',
  })
}

test('a page load posts one root span, a client span under it per API call, and log records in its trace', async ({ page }) => {
  test.setTimeout(45_000)
  const traces: OtlpTraces[] = []
  const logs: OtlpLogs[] = []
  await page.route(`${OTLP}/v1/traces`, async (route) => {
    traces.push(route.request().postDataJSON())
    await accept(route)
  })
  await page.route(`${OTLP}/v1/logs`, async (route) => {
    logs.push(route.request().postDataJSON())
    await accept(route)
  })
  const requestIds: string[] = []
  page.on('response', (response) => {
    if (response.url().startsWith(API) && response.request().method() !== 'OPTIONS') {
      requestIds.push(response.headers()['x-request-id'] ?? '')
    }
  })

  await page.goto('/countdowns')
  await expect(page.locator('.grid')).toBeVisible({ timeout: 10_000 })

  const spans = () => traces.flatMap((batch) => batch.resourceSpans.flatMap((r) => r.scopeSpans.flatMap((s) => s.spans)))
  const records = () => logs.flatMap((batch) => batch.resourceLogs.flatMap((r) => r.scopeLogs.flatMap((s) => s.logRecords)))

  // The root span ends a second after the page's last API answer, and the next batch posts it.
  await expect.poll(() => spans().filter((span) => !span.parentSpanId).length, { timeout: 15_000 }).toBe(1)
  const root = spans().find((span) => !span.parentSpanId)!
  expect(root.name).toBe('navigation /countdowns')
  expect(traces.flatMap((batch) => batch.resourceSpans.map((r) => serviceName(r.resource)))).toContain('life-vue')

  const documentLoad = spans().find((span) => span.name === 'documentLoad')
  expect(documentLoad?.parentSpanId).toBe(root.spanId)

  const clientSpans = spans().filter((span) => span.kind === SPAN_KIND_CLIENT)
  expect(requestIds.length).toBeGreaterThan(0)
  expect(clientSpans).toHaveLength(requestIds.length)
  for (const span of clientSpans) {
    expect(span.traceId).toBe(root.traceId)
    expect(span.parentSpanId).toBe(root.spanId)
  }
  expect(requestIds).toEqual(requestIds.map(() => root.traceId))

  const completed = () => records().filter((record) => record.body?.stringValue === 'request_completed')
  await expect.poll(() => completed().length, { timeout: 15_000 }).toBe(clientSpans.length)
  for (const span of clientSpans) {
    expect(completed().filter((record) => record.spanId === span.spanId)).toHaveLength(1)
  }
  expect(records().every((record) => record.traceId === root.traceId)).toBe(true)
})
