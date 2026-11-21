import { describe, it, expect } from 'vitest'
import { formatLogLine, logRecordOf, formatValue, levelName } from '../logger'
import { SeverityNumber } from '@opentelemetry/api'
import { LogLevels } from 'consola'
import type { LogObject } from 'consola'

// Helper to build a LogObject matching consola's internal structure
function makeLogObj(overrides: Partial<LogObject> = {}): LogObject {
  return {
    level: LogLevels.info,
    type: 'info',
    tag: 'TestModule',
    args: ['test_event'],
    date: new Date(),
    ...overrides,
  } as LogObject
}

describe('formatValue', () => {
  it('returns strings as-is', () => {
    expect(formatValue('hello')).toBe('hello')
  })

  it('JSON-stringifies non-string values', () => {
    expect(formatValue(42)).toBe('42')
    expect(formatValue(true)).toBe('true')
    expect(formatValue(['a', 'b'])).toBe('["a","b"]')
    expect(formatValue({ key: 'val' })).toBe('{"key":"val"}')
  })
})

describe('levelName', () => {
  it('maps consola log levels to structlog-style names', () => {
    expect(levelName(LogLevels.error)).toBe('error')
    expect(levelName(LogLevels.warn)).toBe('warning')
    expect(levelName(LogLevels.info)).toBe('info')
    expect(levelName(LogLevels.debug)).toBe('debug')
    expect(levelName(LogLevels.verbose)).toBe('debug')
  })
})

describe('formatLogLine (structured reporter)', () => {
  it('includes timestamp, level, event, and module', () => {
    const { line } = formatLogLine(makeLogObj())

    expect(line).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/)
    expect(line).toContain('[info   ]')
    expect(line).toContain('test_event')
    expect(line).toContain('module=TestModule')
  })

  it('includes structured context as key=value pairs', () => {
    const logObj = makeLogObj({
      args: ['request_completed', { method: 'GET', status: 200, duration_ms: 42 }],
    })

    const { line } = formatLogLine(logObj)

    expect(line).toContain('request_completed')
    expect(line).toContain('method=GET')
    expect(line).toContain('status=200')
    expect(line).toContain('duration_ms=42')
  })

  it('maps levels correctly', () => {
    expect(formatLogLine(makeLogObj({ level: LogLevels.debug })).level).toBe('debug')
    expect(formatLogLine(makeLogObj({ level: LogLevels.info })).level).toBe('info')
    expect(formatLogLine(makeLogObj({ level: LogLevels.warn })).level).toBe('warning')
    expect(formatLogLine(makeLogObj({ level: LogLevels.error })).level).toBe('error')
  })

  it('JSON-stringifies complex context values', () => {
    const logObj = makeLogObj({
      args: ['test_event', { tags: ['a', 'b'] }],
    })

    const { line } = formatLogLine(logObj)
    expect(line).toContain('tags=["a","b"]')
  })

  it('omits null and undefined context values', () => {
    const logObj = makeLogObj({
      args: ['test_event', { present: 'yes', absent: undefined, empty: null }],
    })

    const { line } = formatLogLine(logObj)
    expect(line).toContain('present=yes')
    expect(line).not.toContain('absent')
    expect(line).not.toContain('empty')
  })

  it('works without context (event name only)', () => {
    const logObj = makeLogObj({ args: ['simple_event'] })

    const { line } = formatLogLine(logObj)
    expect(line).toContain('simple_event')
    expect(line).toContain('module=TestModule')
  })

  it('defaults to "app" when no tag is set', () => {
    const logObj = makeLogObj({ tag: '' })

    const { line } = formatLogLine(logObj)
    expect(line).toContain('module=app')
  })
})

describe('logRecordOf (OpenTelemetry reporter)', () => {
  it('carries the event as its body and the module and context as attributes', () => {
    const logObj = makeLogObj({
      level: LogLevels.warn,
      args: ['request_failed', { status: 503, tags: ['a'], absent: undefined }],
    })

    expect(logRecordOf(logObj)).toEqual({
      timestamp: logObj.date,
      severityNumber: SeverityNumber.WARN,
      severityText: 'warning',
      body: 'request_failed',
      attributes: { module: 'TestModule', status: 503, tags: ['a'] },
    })
  })
})
