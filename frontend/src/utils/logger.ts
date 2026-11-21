/**
 * Structured logger for the Vue frontend, powered by consola.
 *
 * Mirrors structlog patterns from the Python backend:
 * - Event-based logging with structured context
 * - Module-scoped loggers via createLogger('ModuleName')
 * - Consistent key=value format
 *
 * A line at or above the console's level prints there: info in a production
 * build, debug in dev. Every line, whatever its level, goes out as an
 * OpenTelemetry log record wherever `utils/telemetry.ts` exports.
 *
 * Usage:
 *   const logger = createLogger('CountdownsStore')
 *   logger.info('fetch_completed', { count: 5, duration_ms: 123 })
 */

import { SeverityNumber, type LogRecord } from '@opentelemetry/api'
import { createConsola, LogLevels } from 'consola'
import type { ConsolaReporter, LogObject } from 'consola'
import { logContext, telemetryLogger } from './telemetry'

const isDev = import.meta.env.DEV

// --- Formatting utilities (exported for testing) ---

export function formatValue(value: unknown): string {
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

export function levelName(level: number): string {
  // consola levels: error=0, warn=1, info=3, debug=4 (lower = more severe)
  if (level <= LogLevels.error) return 'error'
  if (level <= LogLevels.warn) return 'warning'
  if (level <= LogLevels.info) return 'info'
  return 'debug'
}

const CONSOLE_METHOD: Record<string, 'error' | 'warn' | 'info' | 'debug'> = {
  error: 'error',
  warning: 'warn',
  info: 'info',
  debug: 'debug',
}

/** One logger call, parsed once, so the console line and the OpenTelemetry record agree. */
export interface LogCall {
  level: string
  event: string
  module: string
  fields: Record<string, unknown>
  date: Date
}

/** The first argument is the event name; every object argument after it adds fields, skipping null and undefined. */
export function parseLogCall(logObj: LogObject): LogCall {
  const args = logObj.args || []
  const named = typeof args[0] === 'string'
  const fields: Record<string, unknown> = {}
  for (const arg of named ? args.slice(1) : args) {
    if (arg && typeof arg === 'object' && !Array.isArray(arg)) {
      for (const [key, value] of Object.entries(arg as Record<string, unknown>)) {
        if (value !== undefined && value !== null) fields[key] = value
      }
    }
  }
  return {
    level: levelName(logObj.level),
    event: named ? (args[0] as string) : logObj.message || 'log',
    module: logObj.tag || 'app',
    fields,
    date: logObj.date,
  }
}

/** The console line for a LogObject, in structlog's key=value shape. */
export function formatLogLine(logObj: LogObject): { line: string; level: string } {
  const { level, event, module, fields, date } = parseLogCall(logObj)
  const contextParts = [`module=${module}`, ...Object.entries(fields).map(([key, value]) => `${key}=${formatValue(value)}`)]
  const line = `${date.toISOString()} [${level.padEnd(7)}] ${event.padEnd(30)} ${contextParts.join(' ')}`
  return { line, level }
}

const SEVERITY: Record<string, SeverityNumber> = {
  error: SeverityNumber.ERROR,
  warning: SeverityNumber.WARN,
  info: SeverityNumber.INFO,
  debug: SeverityNumber.DEBUG,
}

/** The OpenTelemetry log record for a LogObject: the event as its body, the module and fields as attributes. */
export function logRecordOf(logObj: LogObject): LogRecord {
  const { level, event, module, fields, date } = parseLogCall(logObj)
  return {
    timestamp: date,
    severityNumber: SEVERITY[level],
    severityText: level,
    body: event,
    attributes: { module, ...fields } as LogRecord['attributes'],
  }
}

// The console's threshold; the root instance passes every level so telemetry sees debug in every build.
let consoleLevel: number = isDev ? LogLevels.debug : LogLevels.info

/**
 * Structured key=value reporter for console output.
 * Format mirrors structlog's ConsoleRenderer:
 *   2026-03-13T03:10:00.000Z [info   ] fetch_completed  module=Store count=5
 */
const structuredReporter: ConsolaReporter = {
  log(logObj: LogObject) {
    if (logObj.level > consoleLevel) return
    const { line, level } = formatLogLine(logObj)

    console[CONSOLE_METHOD[level] || 'info'](line)
  },
}

// Every level goes out; the Collector decides what it keeps.
const telemetryReporter: ConsolaReporter = {
  log(logObj: LogObject) {
    telemetryLogger.emit({ ...logRecordOf(logObj), context: logContext() })
  },
}

// --- Root consola instance ---

const rootConsola = createConsola({
  level: LogLevels.debug,
  reporters: [structuredReporter, telemetryReporter],
})

// --- Public API ---

export interface Logger {
  debug: (event: string, context?: Record<string, unknown>) => void
  info: (event: string, context?: Record<string, unknown>) => void
  warning: (event: string, context?: Record<string, unknown>) => void
  error: (event: string, context?: Record<string, unknown>) => void
}

/**
 * Create a module-scoped logger, equivalent to structlog.get_logger() in Python.
 *
 * Usage:
 *   const logger = createLogger('CountdownsStore')
 *   logger.info('fetch_completed', { count: 5, duration_ms: 123 })
 *
 * Console output:
 *   2026-03-13T03:10:00.000Z [info   ] fetch_completed                module=CountdownsStore count=5 duration_ms=123
 */
export function createLogger(module: string): Logger {
  const scoped = rootConsola.withTag(module)

  return {
    debug: (event: string, context?: Record<string, unknown>) => (context ? scoped.debug(event, context) : scoped.debug(event)),
    info: (event: string, context?: Record<string, unknown>) => (context ? scoped.info(event, context) : scoped.info(event)),
    warning: (event: string, context?: Record<string, unknown>) => (context ? scoped.warn(event, context) : scoped.warn(event)),
    error: (event: string, context?: Record<string, unknown>) => (context ? scoped.error(event, context) : scoped.error(event)),
  }
}

/**
 * Set the minimum level the browser console prints, at runtime. Telemetry is unaffected.
 * Useful for enabling debug logging via browser console:
 *   window.__setLogLevel && window.__setLogLevel('debug')
 */
export function setLogLevel(level: 'debug' | 'info' | 'warning' | 'error'): void {
  const mapping: Record<string, number> = {
    debug: LogLevels.debug,
    info: LogLevels.info,
    warning: LogLevels.warn,
    error: LogLevels.error,
  }
  consoleLevel = mapping[level] ?? LogLevels.info
}

// Expose setLogLevel globally in dev for debugging
if (isDev && typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).__setLogLevel = setLogLevel
}
