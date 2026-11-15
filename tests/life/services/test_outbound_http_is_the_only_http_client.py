"""Outbound HTTP leaves the app through `get_page` in services/outbound_http.py.

Sites behind bot protection refuse a plain HTTP client whatever user agent it
claims, so a page fetched any other way fails on exactly the sites users save
most. A new module importing an HTTP client would pass every other test while
fetching around that door. This test reads the package source, so a module added
later is covered without editing it.
"""

import ast

from life.util import find_project_root

SOURCE_ROOT = find_project_root() / 'life'

HTTP_CLIENTS = frozenset(
    {
        'aiohttp',
        'curl_cffi',
        'http.client',
        'httpx',
        'httpx2',
        'pycurl',
        'requests',
        'urllib.request',
        'urllib3',
    }
)

# Each module allowed an HTTP client, and why.
ALLOWED = {
    'services/outbound_http.py': 'the door itself',
    'api/oidc_auth.py': 'OIDC discovery talks to the identity provider, not a third-party page',
    'api/smoke_tests.py': 'drives the app in-process through ASGITransport, so nothing leaves it',
}


def is_http_client(module: str) -> bool:
    return any(module == client or module.startswith(client + '.') for client in HTTP_CLIENTS)


def imported_modules(node: ast.Import | ast.ImportFrom) -> list[str]:
    """The dotted names an import statement can bind, so `from urllib import request` counts."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.module and node.level == 0:
        return [node.module, *(f'{node.module}.{alias.name}' for alias in node.names)]
    return []


def test_only_outbound_http_imports_an_http_client():
    offenders: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob('*.py')):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        if relative in ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import | ast.ImportFrom):
                offenders.extend(f'{relative}:{node.lineno}: {module}' for module in imported_modules(node) if is_http_client(module))
    assert not offenders, offenders
