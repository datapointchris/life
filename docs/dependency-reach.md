# What a Dependency Can Reach

These dependencies see more than the code that calls them, so what each one reaches is written down here rather than inferred from the import. Add a dependency here when it receives user content, makes outbound requests, or holds a handle on the host.

## claude-agent-sdk

`claude-agent-sdk` receives user content, not metadata, and is the only model provider the app talks to. `life/ai/assistants/anthropic.py` wraps it; the callers are `api/endpoints/articles.py`, `api/endpoints/recipes.py` and `services/url_ingest.py`. Each call runs the Claude Code CLI bundled in the package, authenticated by the subscription OAuth token in `AI_ANTHROPIC_OAUTH_TOKEN`, so usage draws on the Claude plan and never on API credits. `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` outrank that token inside Claude Code, so `options()` blanks both on every call. What crosses the boundary is the full text of each page sent to the summary or insights endpoint, a recipe being imported, and the contents of any URL ingested. Saving an article sends nothing.

The CLI inherits the API process's whole environment, which is the decrypted `.env`: the database and Redis passwords, the internal service key, the Slack webhook and the default users' passwords, beside the OAuth token. That is accepted. The model has no tool that reads the environment, and every library in the API process already holds the same values, so a compromised CLI binary reaches what a compromised Python dependency would. The CLI's nonessential traffic, analytics included, is switched off on every call. It loads no CLAUDE.md, settings, skills or MCP servers, and the only tool any call has is `WebSearch`, on recipe discovery, capped at five calls.

## docker

`docker` is a *runtime* dependency, and `api/endpoints/admin.py` builds a client with `docker.from_env()` to report container status on the admin page. That gives the API process a handle on the host daemon, which is the widest reach in the list: a daemon socket is root-equivalent on the host. It is narrow in use — status reads only — and the endpoint is behind `get_admin_user`.

## testcontainers

`testcontainers` is a *test* dependency, used only by `PrivateServices` in `tests/environment.py`. It reaches the Docker daemon through the same socket the `docker` client uses, so a pytest process holds the root-equivalent handle a developer's own shell already has. Each session starts three containers: the Postgres and Redis images production runs, read from `docker-compose.yml`, and the `testcontainers/ryuk` reaper. Ryuk mounts the daemon socket read-write, so it can remove the session's containers when the session dies. It is unprivileged unless `TESTCONTAINERS_RYUK_PRIVILEGED` says otherwise. Nothing from the app's `.env` reaches any of the three: the database runs with fixed test credentials, and Redis without a password.

## OpenTelemetry

The API and the scheduler start under `opentelemetry-instrument`, which patches FastAPI, SQLAlchemy and Redis before the app imports them. `life/opentelemetry_distro.py` is the distro it loads. Where `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, it disables the SDK and patches nothing, so no span is made and nothing leaves.

Where an endpoint is set, each process posts its spans there over OTLP/HTTP. A span carries:

- the request's method, route and full path, path parameters included
- each SQL statement's text, without its bound values
- each Redis command's name, with every argument replaced by `?`
- the full URL of every page `get_page` fetches, and the URL it was redirected to
- every member of the baggage the caller sent, copied onto each span in that request
- the process that made it: its pid, its command line and the container's hostname

So the collector the endpoint names sees which saved links a user fetched, though not the pages' text, and not a column's value.

The SPA carries the browser SDK, started by `frontend/src/utils/telemetry.ts`. Where the build set `VITE_OTEL_ENDPOINT`, the browser posts its spans and log records there over OTLP/HTTP, with `VITE_OTEL_INGEST_TOKEN` as a bearer token. Where it was unset, nothing leaves the browser. A browser span or record carries:

- each API request's method and full URL, query string included
- the route each navigation reached and the path it left
- every field a `createLogger` call logs, at every level, debug included
- the URL and timing of every resource the page loaded
- the browser's user agent and language, and a random id per tab

The token ships inside the bundle every visitor downloads, so it is no secret. It keeps drive-by posts off the endpoint.

## curl_cffi

`curl_cffi` makes every third-party page request, from `services/outbound_http.py`. It reaches whatever URL a user saved, as any HTTP client would, and carries nothing but the request.

## trafilatura and pypdf

`trafilatura` and `pypdf` parse page and PDF bytes already fetched, in `services/url_extraction.py`. Neither makes a request: `trafilatura`'s own download helpers are never called.

## yt-dlp and youtube-transcript-api

`yt-dlp` fetches YouTube metadata on the app's behalf from `services/url_extraction.py`, alongside `youtube-transcript-api`. Both make outbound requests to a third party with whatever URL a user saved. `yt-dlp` releases weekly to track site changes, so it carries a lower bound only.
