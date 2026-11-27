"""Read a YouTube video's details and transcript through ypl.

ypl is the one reader of YouTube. Its door paces every read, so this app sends
YouTube nothing of its own. The client signs in to ypl as a service, with the
client-credentials grant against the identity provider that issues this app's
own tokens. It keeps the token until shortly before it expires.

ypl answers a read it cannot make now with 503 and a `Retry-After`. When
YouTube refuses a read, ypl answers with a code of its own, such as 404
`no_captions`. Each refusal arrives here as `YplRefused`, carrying the status,
the code and the wait.
"""

import functools
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote
from urllib.parse import urlsplit

import httpx2
from opentelemetry import propagate
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opentelemetry.trace import StatusCode

from life.config import Settings

tracer = trace.get_tracer(__name__)

USER_AGENT = 'life-api'
DISCOVERY_PATH = '/.well-known/openid-configuration'
SCOPES = ('ypl.videos.read', 'ypl.transcripts.read')

# A token is dropped this long before it expires, so a read never leaves holding one that lapses in flight.
TOKEN_EXPIRY_MARGIN_SECONDS = 30
# Used when the identity provider names no lifetime, short enough that a wrong guess costs one sign-in.
TOKEN_LIFETIME_UNSTATED_SECONDS = 300

SIGN_IN_TIMEOUT_SECONDS = 15.0
# A details read is one Data API call, which waits up to 20 seconds for the call ahead of it.
DETAILS_TIMEOUT_SECONDS = 60.0
# A transcript read waits up to two minutes for its turn at ypl's door, then reads YouTube at the door's pace.
TRANSCRIPT_TIMEOUT_SECONDS = 180.0


class YplError(Exception):
    """A read through ypl did not answer what was asked."""


class YplNotConfigured(YplError):
    def __init__(self, missing: str):
        super().__init__(f'YouTube videos are read through ypl, and {missing} is not set')
        self.missing = missing


class YplUnreachable(YplError):
    """No answer came back: DNS, the connection or the timeout failed, on ypl or the identity provider."""

    def __init__(self, url: str, reason: str):
        super().__init__(f'could not reach {url}: {reason}')
        self.url = url
        self.reason = reason


class YplSignInRefused(YplError):
    """The identity provider refused this app's client credentials."""

    def __init__(self, status_code: int, error: str):
        super().__init__(f'the identity provider refused the ypl sign-in with {status_code} {error}')
        self.status_code = status_code
        self.error = error


class YplRefused(YplError):
    """ypl answered with a status that is not success. `code` is ypl's own name for the refusal."""

    def __init__(self, status_code: int, code: str, message: str, retry_after: int | None):
        wait = f'; ask again in {retry_after}s' if retry_after is not None else ''
        super().__init__(f'ypl answered {status_code} {code or "with no code"}: {message}{wait}')
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class VideoDetails:
    video_id: str
    title: str
    description: str
    channel_title: str
    duration_seconds: int | None


@dataclass(frozen=True)
class Transcript:
    """`kind` is `manual` or `automatic`, and `text` is every segment joined on one line."""

    video_id: str
    language: str
    kind: str
    text: str


def retry_after_seconds(response: httpx2.Response) -> int | None:
    """The `Retry-After` header as whole seconds. ypl sends seconds, so an HTTP date reads as none."""
    value = response.headers.get('Retry-After', '').strip()
    return int(value) if value.isdigit() else None


def refusal(response: httpx2.Response) -> YplRefused:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    message = body.get('message') or response.text[:200] or response.reason_phrase
    return YplRefused(response.status_code, body.get('code') or '', message, retry_after_seconds(response))


class YplClient:
    """Reads through one ypl server as one service client. Safe to share across threads."""

    def __init__(self, api_url: str, issuer: str, client_id: str, client_secret: str, transport: httpx2.BaseTransport | None = None):
        self.api_url = api_url.rstrip('/')
        self.issuer = issuer.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = httpx2.Client(transport=transport, headers={'User-Agent': USER_AGENT}, follow_redirects=False)
        self.token_lock = threading.Lock()
        self.token: str | None = None
        self.token_good_until = 0.0
        self.token_endpoint: str | None = None

    def video_details(self, video_id: str) -> VideoDetails | None:
        """The video's details as YouTube reports them now, or None when YouTube returns no such video."""
        response = self.request_ypl('/api/v1/youtube/videos', {'ids': video_id}, DETAILS_TIMEOUT_SECONDS)
        for video in response.json():
            if video.get('id') == video_id:
                return VideoDetails(
                    video_id=video_id,
                    title=video.get('title') or '',
                    description=video.get('description') or '',
                    channel_title=video.get('channel_title') or '',
                    duration_seconds=video.get('duration_seconds'),
                )
        return None

    def transcript(self, video_id: str, language: str = 'en') -> Transcript:
        """The video's captions in `language` as one line. A video with none raises `YplRefused` with `no_captions`."""
        response = self.request_ypl(
            f'/api/v1/youtube/videos/{quote(video_id, safe="")}/transcript', {'lang': language}, TRANSCRIPT_TIMEOUT_SECONDS
        )
        body = response.json()
        return Transcript(
            video_id=video_id, language=body.get('language') or language, kind=body.get('kind') or '', text=body.get('text') or ''
        )

    def request_ypl(self, path: str, params: dict[str, str], timeout: float) -> httpx2.Response:
        """GET a ypl route as this client, signing in again once when ypl refuses the token it holds."""
        url = self.api_url + path
        attributes = {'http.request.method': 'GET', 'url.full': url, 'server.address': urlsplit(url).hostname or ''}
        # A client span by hand, because no OpenTelemetry instrumentation covers httpx2.
        with tracer.start_as_current_span('GET', kind=SpanKind.CLIENT, attributes=attributes) as span:
            response = self.send_signed_in(url, params, timeout)
            if response.status_code == httpx2.codes.UNAUTHORIZED:
                self.forget_token()
                response = self.send_signed_in(url, params, timeout)
            span.set_attribute('http.response.status_code', response.status_code)
            if response.is_success:
                return response
            refused = refusal(response)
            span.set_attributes({'error.type': str(response.status_code), 'life.ypl.code': refused.code})
            if refused.retry_after is not None:
                span.set_attribute('life.ypl.retry_after', refused.retry_after)
            span.set_status(StatusCode.ERROR)
            raise refused

    def send_signed_in(self, url: str, params: dict[str, str], timeout: float) -> httpx2.Response:
        headers = {'Authorization': f'Bearer {self.access_token()}'}
        propagate.inject(headers)
        try:
            return self.http.get(url, params=params, headers=headers, timeout=timeout)
        except httpx2.HTTPError as e:
            raise YplUnreachable(url, str(e) or type(e).__name__) from e

    def access_token(self) -> str:
        with self.token_lock:
            if self.token is None or time.monotonic() >= self.token_good_until:
                self.token, self.token_good_until = self.sign_in()
            return self.token

    def forget_token(self) -> None:
        with self.token_lock:
            self.token = None

    def sign_in(self) -> tuple[str, float]:
        """A token from the client-credentials grant, and the monotonic time to stop using it.

        RFC 6749 § 2.3.1 form-encodes each half of the Basic credentials.
        """
        endpoint = self.token_endpoint or self.discover_token_endpoint()
        auth = httpx2.BasicAuth(quote(self.client_id, safe=''), quote(self.client_secret, safe=''))
        data = {'grant_type': 'client_credentials', 'scope': ' '.join(SCOPES)}
        try:
            response = self.http.post(endpoint, data=data, auth=auth, timeout=SIGN_IN_TIMEOUT_SECONDS)
        except httpx2.HTTPError as e:
            raise YplUnreachable(endpoint, str(e) or type(e).__name__) from e
        if not response.is_success:
            try:
                error = response.json().get('error') or ''
            except ValueError:
                error = ''
            raise YplSignInRefused(response.status_code, error)
        body = response.json()
        lifetime = body.get('expires_in') or TOKEN_LIFETIME_UNSTATED_SECONDS
        return body['access_token'], time.monotonic() + max(lifetime - TOKEN_EXPIRY_MARGIN_SECONDS, 0)

    def discover_token_endpoint(self) -> str:
        url = self.issuer + DISCOVERY_PATH
        try:
            response = self.http.get(url, timeout=SIGN_IN_TIMEOUT_SECONDS)
            response.raise_for_status()
        except httpx2.HTTPError as e:
            raise YplUnreachable(url, str(e) or type(e).__name__) from e
        endpoint = response.json().get('token_endpoint')
        if not endpoint:
            raise YplUnreachable(url, 'the discovery document names no token_endpoint')
        self.token_endpoint = endpoint
        return endpoint


@functools.cache
def client_for(api_url: str, issuer: str, client_id: str, client_secret: str) -> YplClient:
    """The process-wide client for one configuration, so every thread shares its token."""
    return YplClient(api_url, issuer, client_id, client_secret)


def ypl_client(settings: Settings) -> YplClient:
    if settings.ypl.api_url is None:
        raise YplNotConfigured('YPL_API_URL')
    if settings.ypl.client_secret is None:
        raise YplNotConfigured('YPL_CLIENT_SECRET')
    return client_for(settings.ypl.api_url, settings.oidc.issuer, settings.ypl.client_id, settings.ypl.client_secret)
