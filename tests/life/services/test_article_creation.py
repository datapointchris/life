from life import schemas
from life.services.article_creation import body_fingerprint


def test_a_body_fingerprints_the_same_under_every_release():
    """A stored fingerprint cannot be taken again, so a change that moves this digest turns every replay of a saved key into a 409.

    A field joining the fingerprint, or a listed field's new default, belongs under a new version prefix.
    """
    body = schemas.ArticleCreate.model_validate(
        {
            'title': 'A saved post',
            'url': 'https://example.com/saved-post?utm_source=feed',
            'save_date': '2026-11-20T10:04:05-05:00',
            'source_key': 'post/abc',
        }
    )
    assert body_fingerprint(body) == 'v1:d3822f8524c29a9c0bde3b4fc0328529b40c2ffa29a2330f87ba881b45ee8891'
