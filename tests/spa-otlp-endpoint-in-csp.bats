#!/usr/bin/env bats
#
# The release workflow builds the production SPA to post its traces and logs to
# otel_endpoint, and the browser refuses that post unless the production CSP's
# connect-src names the endpoint's origin. A refused post only shows in a
# visitor's console, and the e2e suite runs under the test stack's own CSP, so
# this is the one place the two production files are read together.

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd -P)"
  cd "$REPO_ROOT" || return 1
}

@test "the production CSP lets the SPA post to the endpoint its release build names" {
  endpoint=$(yq '.jobs.images.strategy.matrix.include[] | select(.image == "life-vue") | .otel_endpoint' .github/workflows/release.yml)
  [[ "$endpoint" == https://* ]]
  origin=$(printf '%s' "$endpoint" | sed -E 's#^(https://[^/]+).*#\1#')

  csp=$(yq '.http.middlewares.security-headers-prod.headers.customResponseHeaders."Content-Security-Policy"' deploy-containers/traefik/dynamic/prod/middlewares.yml)
  connect_src=$(printf '%s' "$csp" | tr ';' '\n' | sed -n 's/^ *connect-src //p')
  [ -n "$connect_src" ]

  [[ " $connect_src " == *" $origin "* ]] || {
    echo "connect-src '$connect_src' does not name $origin"
    return 1
  }
}
