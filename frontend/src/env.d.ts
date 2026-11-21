/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  /** A Collector's OTLP/HTTP base URL. Unset, no span or log record leaves the browser. */
  readonly VITE_OTEL_ENDPOINT?: string
  /** Sent as `Authorization: Bearer <token>` to the Collector, where it checks one. */
  readonly VITE_OTEL_INGEST_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
