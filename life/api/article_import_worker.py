"""Background worker for bulk article imports via Redis queue.

Queue item format (JSON string in Redis list):
    {"batch_id": "...", "url": "...", "notes": "...", "attempt": 1, "actor": "...", "request_id": "...",
     "trace_context": {"traceparent": "...", "baggage": "..."}}

    `trace_context` is the enqueuing request's W3C headers, so each item's import
    runs as a span under the request that queued it, carrying its caller's baggage.

Batch status (Redis hash at article_import:batch:{batch_id}):
    status, total, processed, succeeded, failed_count, errors (JSON), results (JSON),
    created_at, updated_at. It expires BATCH_TTL after the batch completes, so a
    batch still waiting — behind a backlog or a stopped worker — keeps its status
    for as long as the wait lasts.
"""

import datetime as dt
import json
import threading
import uuid
from typing import Any

import redis
import structlog
from opentelemetry import propagate
from opentelemetry import trace
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.trace import SpanKind

from life.config import Settings
from life.database.session import create_session
from life.models.record_change import bind_actor
from life.services.article_creation import ArticleAlreadyExists
from life.services.article_creation import save_article_from_url
from life.services.outbound_http import PageStatusError
from life.services.url_extraction import PageUnreadable
from life.services.ypl_client import YplError
from life.services.ypl_client import YplUnreachable
from life.util import clean_url

logger = structlog.get_logger()
tracer = trace.get_tracer(__name__)

QUEUE_KEY = 'article_import:queue'
BATCH_KEY_PREFIX = 'article_import:batch:'
BATCH_TTL = 86400  # 24 hours
MAX_ATTEMPTS = 2
QUEUE_WAIT_SECONDS = 5
# `blpop` leaves the socket silent for up to QUEUE_WAIT_SECONDS, so a read timeout at or below it
# raises TimeoutError on every poll of an empty queue.
QUEUE_READ_TIMEOUT_SECONDS = QUEUE_WAIT_SECONDS * 2


def worth_retrying(error: Exception) -> bool:
    """Whether asking again at once could give a different answer.

    A page that is not the article, a duplicate and a 4xx stay the same on a
    second request. ypl answering at all says when to ask again, or that the
    answer will not change, so its refusal is not retried at once. A dropped
    connection or a 5xx can pass, so those are retried, ypl's included.
    """
    if isinstance(error, PageUnreadable | ArticleAlreadyExists):
        return False
    if isinstance(error, YplError):
        return isinstance(error, YplUnreachable)
    return not (isinstance(error, PageStatusError) and error.status_code < 500)


def enqueue_bulk_import(redis_client: redis.Redis, urls: list[str], notes_map: dict[str, str] | None = None, *, actor: str) -> str:
    """Enqueue URLs for bulk import. Returns batch_id.

    Each item carries `actor` and the request's id, so the worker's writes are audited under them.
    """
    batch_id = str(uuid.uuid4())
    notes_map = notes_map or {}
    request_id = structlog.contextvars.get_contextvars().get('request_id')
    trace_context: dict[str, str] = {}
    propagate.inject(trace_context)

    pipeline = redis_client.pipeline()
    for url in urls:
        item = json.dumps(
            {
                'batch_id': batch_id,
                'url': clean_url(url.strip()),
                'notes': notes_map.get(url),
                'attempt': 1,
                'actor': actor,
                'request_id': request_id,
                'trace_context': trace_context,
            }
        )
        pipeline.rpush(QUEUE_KEY, item)

    batch_key = f'{BATCH_KEY_PREFIX}{batch_id}'
    now = dt.datetime.now(dt.UTC).isoformat()
    pipeline.hset(
        batch_key,
        mapping={
            'status': 'queued',
            'total': len(urls),
            'processed': 0,
            'succeeded': 0,
            'failed_count': 0,
            'errors': '[]',
            'results': '[]',
            'created_at': now,
            'updated_at': now,
        },
    )
    pipeline.execute()

    logger.info('bulk_import_enqueued', batch_id=batch_id, count=len(urls))
    return batch_id


def get_batch_status(redis_client: redis.Redis, batch_id: str) -> dict | None:
    """Get status of a bulk import batch."""
    batch_key = f'{BATCH_KEY_PREFIX}{batch_id}'
    data = redis_client.hgetall(batch_key)
    if not data:
        return None
    return {
        'batch_id': batch_id,
        'status': data['status'],
        'total': int(data['total']),
        'processed': int(data['processed']),
        'succeeded': int(data['succeeded']),
        'failed_count': int(data['failed_count']),
        'errors': json.loads(data['errors']),
        'results': json.loads(data['results']),
        'created_at': data['created_at'],
        'updated_at': data['updated_at'],
    }


class ArticleImportWorker:
    """Daemon thread that processes article import queue via BLPOP."""

    def __init__(self, redis_client: redis.Redis, settings: Settings):
        self.redis_client = redis_client
        self.settings = settings
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name='article-import-worker')
        self._thread.start()
        logger.info('article_import_worker_started')

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info('article_import_worker_stopped')

    def _run(self):
        while not self._stop_event.is_set():
            try:
                result = self._poll()
                if result is None:
                    continue
                _, item_json = result
                item = json.loads(item_json)
                self._process_item(item)
            except Exception:
                logger.exception('article_import_worker_error')
                if self._stop_event.wait(timeout=2):
                    break

    def _poll(self) -> Any:
        """The next item, once one arrives within QUEUE_WAIT_SECONDS.

        It makes no span. Every worker polls an empty queue every few seconds, and
        each poll's Redis commands would otherwise be a trace of their own.
        """
        with suppress_instrumentation():
            return self.redis_client.blpop(QUEUE_KEY, timeout=QUEUE_WAIT_SECONDS)

    def _process_item(self, item: dict):
        """Import one item inside a span under the request that queued it."""
        attributes = {
            'article_import.batch_id': item['batch_id'],
            'article_import.attempt': item.get('attempt', 1),
            'url.full': item['url'],
        }
        parent = propagate.extract(item.get('trace_context') or {})
        with tracer.start_as_current_span('article_import', context=parent, kind=SpanKind.CONSUMER, attributes=attributes):
            self._import_item(item)

    def _import_item(self, item: dict):
        batch_id = item['batch_id']
        url = item['url']
        attempt = item.get('attempt', 1)
        notes = item.get('notes')
        batch_key = f'{BATCH_KEY_PREFIX}{batch_id}'

        if self._batch_exists(batch_key):
            self.redis_client.hset(batch_key, mapping={'status': 'processing', 'updated_at': dt.datetime.now(dt.UTC).isoformat()})
        else:
            logger.warning('article_import_batch_missing', batch_id=batch_id, url=url)

        try:
            with structlog.contextvars.bound_contextvars(request_id=item.get('request_id')), create_session(self.settings) as session:
                if actor := item.get('actor'):
                    bind_actor(session, actor)
                article = save_article_from_url(url, notes, session)
                self._record_success(batch_key, url, article.title)
        except Exception as e:
            error_msg = str(e)
            logger.warning('article_import_item_failed', url=url, attempt=attempt, error=error_msg)

            if attempt < MAX_ATTEMPTS and worth_retrying(e):
                # Re-queue with incremented attempt
                retry_item = json.dumps(item | {'attempt': attempt + 1})
                self.redis_client.rpush(QUEUE_KEY, retry_item)
            else:
                self._record_failure(batch_key, url, error_msg)

    def _batch_exists(self, batch_key: str) -> bool:
        """Whether the batch's status hash is there to update.

        A write to a missing hash creates one with no `total`, which reads as a
        completed batch and fails every later status read, so the worker still
        imports the URL but leaves a missing batch's status alone.
        """
        return bool(self.redis_client.exists(batch_key))

    def _record_success(self, batch_key: str, url: str, title: str):
        if not self._batch_exists(batch_key):
            return
        pipeline = self.redis_client.pipeline()
        pipeline.hincrby(batch_key, 'processed', 1)
        pipeline.hincrby(batch_key, 'succeeded', 1)
        pipeline.hset(batch_key, 'updated_at', dt.datetime.now(dt.UTC).isoformat())
        pipeline.execute()

        # Append to results list
        results = json.loads(self.redis_client.hget(batch_key, 'results') or '[]')
        results.append({'url': url, 'title': title})
        self.redis_client.hset(batch_key, 'results', json.dumps(results))

        self._check_batch_complete(batch_key)

    def _record_failure(self, batch_key: str, url: str, error_msg: str):
        """Count a URL that will not be tried again into its batch's status.

        Nothing else keeps it. The batch expires with its errors, and a page that
        would not import is not worth holding onto past that.
        """
        if not self._batch_exists(batch_key):
            return
        pipeline = self.redis_client.pipeline()
        pipeline.hincrby(batch_key, 'processed', 1)
        pipeline.hincrby(batch_key, 'failed_count', 1)
        pipeline.hset(batch_key, 'updated_at', dt.datetime.now(dt.UTC).isoformat())
        pipeline.execute()

        # Append to errors list
        errors = json.loads(self.redis_client.hget(batch_key, 'errors') or '[]')
        errors.append({'url': url, 'error': error_msg})
        self.redis_client.hset(batch_key, 'errors', json.dumps(errors))

        self._check_batch_complete(batch_key)

    def _check_batch_complete(self, batch_key: str):
        data = self.redis_client.hgetall(batch_key)
        if int(data.get('processed', 0)) >= int(data.get('total', 0)):
            pipeline = self.redis_client.pipeline()
            pipeline.hset(batch_key, mapping={'status': 'completed', 'updated_at': dt.datetime.now(dt.UTC).isoformat()})
            pipeline.expire(batch_key, BATCH_TTL)
            pipeline.execute()
            logger.info('bulk_import_batch_completed', batch_key=batch_key)
