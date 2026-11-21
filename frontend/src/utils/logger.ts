/**
 * Structured logger for the Vue frontend, powered by consola.
 *
 * Mirrors structlog patterns from the Python backend:
 * - Event-based logging with structured context
 * - Module-scoped loggers via createLogger('ModuleName')
 * - Consistent key=value format
 *
 * Every line prints to the browser console, and goes out as an OpenTelemetry
 * log record wherever `utils/telemetry.ts` exports.
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

/**
 * Build a structured log line from a LogObject.
 * Exported for testing — this is the core formatting logic.
 */
export function formatLogLine(logObj: LogObject): { line: string; level: string } {
  const level = levelName(logObj.level)
  const timestamp = new Date().toISOString()
  const tag = logObj.tag || 'app'

  // First arg is the event name, rest are context objects
  const args = logObj.args || []
  const event = typeof args[0] === 'string' ? args[0] : logObj.message || 'log'
  const contextParts: string[] = [`module=${tag}`]

  // Merge all object arguments as structured context
  for (let i = typeof args[0] === 'string' ? 1 : 0; i < args.length; i++) {
    const arg = args[i]
    if (arg && typeof arg === 'object' && !Array.isArray(arg)) {
      for (const [key, value] of Object.entries(arg as Record<string, unknown>)) {
        if (value !== undefined && value !== null) {
          contextParts.push(`${key}=${formatValue(value)}`)
        }
      }
    }
  }

  const line = `${timestamp} [${level.padEnd(7)}] ${(event as string).padEnd(30)} ${contextParts.join(' ')}`
  return { line, level }
}

const SEVERITY: Record<string, SeverityNumber> = {
  error: SeverityNumber.ERROR,
  warning: SeverityNumber.WARN,
  info: SeverityNumber.INFO,
  debug: SeverityNumber.DEBUG,
}

/** The OpenTelemetry log record for a LogObject: the event as its body, the module and context as attributes. */
export function logRecordOf(logObj: LogObject): LogRecord {
  const level = levelName(logObj.level)
  const args = logObj.args || []
  const event = typeof args[0] === 'string' ? args[0] : logObj.message || 'log'
  const attributes: Record<string, unknown> = { module: logObj.tag || 'app' }

  for (let i = typeof args[0] === 'string' ? 1 : 0; i < args.length; i++) {
    const arg = args[i]
    if (arg && typeof arg === 'object' && !Array.isArray(arg)) {
      for (const [key, value] of Object.entries(arg as Record<string, unknown>)) {
        if (value !== undefined && value !== null) attributes[key] = value
      }
    }
  }

  return {
    timestamp: logObj.date,
    severityNumber: SEVERITY[level],
    severityText: level,
    body: event as string,
    attributes: attributes as LogRecord['attributes'],
  }
}

/**
 * Structured key=value reporter for console output.
 * Format mirrors structlog's ConsoleRenderer:
 *   2026-03-13T03:10:00.000Z [info   ] fetch_completed  module=Store count=5
 */
const structuredReporter: ConsolaReporter = {
  log(logObj: LogObject) {
    const { line, level } = formatLogLine(logObj)

    console[CONSOLE_METHOD[level] || 'info'](line)
  },
}

const telemetryReporter: ConsolaReporter = {
  log(logObj: LogObject) {
    telemetryLogger.emit({ ...logRecordOf(logObj), context: logContext() })
  },
}

// --- Root consola instance ---

const rootConsola = createConsola({
  level: isDev ? LogLevels.debug : LogLevels.info,
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
 * Set the minimum log level at runtime.
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
  rootConsola.level = mapping[level] ?? LogLevels.info
}

// Expose setLogLevel globally in dev for debugging
if (isDev && typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).__setLogLevel = setLogLevel
}
