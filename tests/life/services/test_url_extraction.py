from unittest.mock import patch

import pytest

from life.services.outbound_http import FetchedPage
from life.services.url_extraction import NotAVideoUrl
from life.services.url_extraction import extract_video_id
from life.services.url_extraction import is_youtube_url
from life.services.url_extraction import read_article_title

VIDEO_ID = 'Wr1tt3nVid0'


def test_a_page_too_short_to_summarize_still_gives_the_title_it_is_saved_under():
    """A save keeps only the title, so it is not refused for text it would throw away."""
    url = 'https://example.com/short-note'
    html = b'<html><head><title>A short note | Example</title></head><body><p>Too few words to summarize.</p></body></html>'
    with patch('life.services.url_extraction.get_page', return_value=FetchedPage(url, url, 200, html)):
        assert read_article_title(url) == 'A short note'


@pytest.mark.parametrize(
    'url',
    [
        f'https://www.youtube.com/watch?v={VIDEO_ID}',
        f'https://youtu.be/{VIDEO_ID}',
        f'https://www.youtube.com/shorts/{VIDEO_ID}',
        f'https://www.youtube.com/live/{VIDEO_ID}',
        f'https://www.youtube.com/embed/{VIDEO_ID}',
        f'https://m.youtube.com/watch?v={VIDEO_ID}&t=30s',
        f'https://youtu.be/{VIDEO_ID}?si=abc123',
        f'youtube.com/watch?v={VIDEO_ID}',
    ],
)
def test_extract_video_id_handles_supported_url_formats(url: str):
    assert is_youtube_url(url)
    assert extract_video_id(url) == VIDEO_ID


@pytest.mark.parametrize('url', ['https://www.youtube.com/@somechannel', 'https://www.youtube.com/watch?v=../status'])
def test_a_youtube_url_naming_no_video_is_refused_before_any_read(url: str):
    with pytest.raises(NotAVideoUrl):
        extract_video_id(url)


def test_a_url_that_only_mentions_youtube_is_read_as_a_page():
    assert not is_youtube_url('https://example.com/post?ref=youtube.com')
