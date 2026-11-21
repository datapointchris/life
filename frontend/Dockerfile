# Build stage
FROM node:24-alpine AS builder

WORKDIR /app

# Install dependencies first (layer caching)
COPY frontend/package*.json ./
RUN npm ci

# Copy frontend source
COPY frontend/ .

# Only production builds this image, and its API sits under the page's own origin.
ARG VITE_API_URL=/api/v1

# Where the SPA sends its traces and log records, and the token it sends with them. Left unset,
# nothing leaves the browser. The token ships in the bundle, so it gates the endpoint without
# being secret, and an ARG keeps a new token from being masked by a cached build layer.
ARG VITE_OTEL_ENDPOINT
ARG VITE_OTEL_INGEST_TOKEN

RUN npm run build

# Production stage — Caddy serves static files with SPA routing
FROM caddy:2-alpine

# The app image's account, so neither image runs as root or as a person. The
# image's caddy binary carries cap_net_bind_service, so it still binds :80.
RUN addgroup -S -g 10300 ichrisbirch \
 && adduser -S -D -H -u 10300 -G ichrisbirch -s /sbin/nologin ichrisbirch \
 && chown -R ichrisbirch:ichrisbirch /data /config

COPY --from=builder /app/dist /srv
COPY frontend/Caddyfile /etc/caddy/Caddyfile

USER 10300:10300
EXPOSE 80
