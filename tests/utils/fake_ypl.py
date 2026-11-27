"""A stand-in for ypl and the identity provider in front of it, built from the shapes ypl publishes.

ypl's wire test writes `ypl_wire/transcript.json`, copied here unchanged. The
videos read answers a list of ypl's `liveVideo`, whose fields its
`api/handlers/data_api.go` declares. A refusal is ypl's
`{"error", "message", "code"}` body.
"""

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs

import httpx2

from life.services.ypl_client import SCOPES
from life.services.ypl_client import YplClient

ISSUER = 'https://auth.example.test'
TOKEN_ENDPOINT = f'{ISSUER}/api/oidc/token'
API_URL = 'http://ypl.example.test'
CLIENT_ID = 'ypl-svc-life'
CLIENT_SECRET = 'fake-client-secret'

TRANSCRIPT_WIRE = json.loads((Path(__file__).parent / 'ypl_wire' / 'transcript.json').read_text())
TRANSCRIPT_PATH = re.compile(r'/api/v1/youtube/videos/([^/]+)/transcript')


@dataclass
class FakeVideo:
    """`transcript` None answers 404 `no_captions`, as ypl does for a video with no track."""

    video_id: str
    title: str
    description: str
    channel_title: str
    duration_seconds: int | None
    transcript: str | None


def refusal(status: int, code: str, message: str, retry_after: int | None = None) -> httpx2.Response:
    headers = {'Retry-After': str(retry_after)} if retry_after is not None else {}
    body = {'error': httpx2.codes.get_reason_phrase(status), 'message': message, 'code': code}
    return httpx2.Response(status, json=body, headers=headers)


class FakeYpl:
    def __init__(self) -> None:
        self.videos: dict[str, FakeVideo] = {}
        # (status, code, Retry-After) every transcript read answers, as ypl's door does while busy or paused.
        self.transcript_refusal: tuple[int, str, int | None] | None = None
        self.tokens_issued: list[str] = []
        self.tokens_revoked: set[str] = set()
        self.reads: list[httpx2.Request] = []

    def add(self, video: FakeVideo) -> FakeVideo:
        self.videos[video.video_id] = video
        return video

    def client(self) -> YplClient:
        return YplClient(API_URL, ISSUER, CLIENT_ID, CLIENT_SECRET, transport=httpx2.MockTransport(self.handle))

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = f'{request.url.scheme}://{request.url.host}{request.url.path}'
        if url == f'{ISSUER}/.well-known/openid-configuration':
            return httpx2.Response(200, json={'issuer': ISSUER, 'token_endpoint': TOKEN_ENDPOINT})
        if url == TOKEN_ENDPOINT:
            return self.grant(request)
        if not url.startswith(API_URL):
            return httpx2.Response(404)
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        if token not in self.tokens_issued or token in self.tokens_revoked:
            return refusal(401, 'unauthorized', 'the access token is not valid')
        self.reads.append(request)
        path = request.url.path
        if path == '/api/v1/youtube/videos':
            ids = request.url.params.get('ids', '').split(',')
            return httpx2.Response(200, json=[self.live_video(self.videos[i]) for i in ids if i in self.videos])
        if match := TRANSCRIPT_PATH.fullmatch(path):
            return self.transcript(match.group(1), request.url.params.get('lang', 'en'))
        return refusal(404, 'route_not_found', f'no route {path}')

    def grant(self, request: httpx2.Request) -> httpx2.Response:
        expected = base64.b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()
        form = parse_qs(request.content.decode())
        if request.headers.get('Authorization') != f'Basic {expected}':
            return httpx2.Response(401, json={'error': 'invalid_client'})
        if form.get('grant_type') != ['client_credentials'] or form.get('scope') != [' '.join(SCOPES)]:
            return httpx2.Response(400, json={'error': 'invalid_request'})
        token = f'token-{len(self.tokens_issued) + 1}'
        self.tokens_issued.append(token)
        return httpx2.Response(200, json={'access_token': token, 'token_type': 'bearer', 'expires_in': 3599, 'scope': ' '.join(SCOPES)})

    def transcript(self, video_id: str, language: str) -> httpx2.Response:
        if self.transcript_refusal is not None:
            status, code, retry_after = self.transcript_refusal
            return refusal(status, code, 'the read waited its turn at the door and did not get it', retry_after)
        video = self.videos.get(video_id)
        if video is None or video.transcript is None:
            return refusal(404, 'no_captions', f'video {video_id} has no captions in {language}')
        return httpx2.Response(200, json=TRANSCRIPT_WIRE | {'video_id': video_id, 'language': language, 'text': video.transcript})

    @staticmethod
    def live_video(video: FakeVideo) -> dict:
        return {
            'id': video.video_id,
            'title': video.title,
            'description': video.description,
            'channel_id': 'UCfakechannel000000000',
            'channel_title': video.channel_title,
            'published_at': '2026-01-01T00:00:00Z',
            'privacy': 'public',
            'duration_seconds': video.duration_seconds,
            'live_broadcast_content': 'none',
            'view_count': 0,
            'like_count': 0,
            'comment_count': 0,
        }
