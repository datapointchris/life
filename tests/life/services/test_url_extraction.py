from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from life.services.outbound_http import FetchedPage
from life.services.url_extraction import YouTubeMetadata
from life.services.url_extraction import extract_video_id
from life.services.url_extraction import get_youtube_video_metadata
from life.services.url_extraction import read_article_title


def test_a_page_too_short_to_summarize_still_gives_the_title_it_is_saved_under():
    """A save keeps only the title, so it is not refused for text it would throw away."""
    url = 'https://example.com/short-note'
    html = b'<html><head><title>A short note | Example</title></head><body><p>Too few words to summarize.</p></body></html>'
    with patch('life.services.url_extraction.get_page', return_value=FetchedPage(url, url, 200, html)):
        assert read_article_title(url) == 'A short note'


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        ('https://www.youtube.com/watch?v=qEb96qFi2Tc', 'qEb96qFi2Tc'),
        ('https://youtu.be/qEb96qFi2Tc', 'qEb96qFi2Tc'),
        ('https://www.youtube.com/shorts/qEb96qFi2Tc', 'qEb96qFi2Tc'),
        ('https://www.youtube.com/live/qEb96qFi2Tc', 'qEb96qFi2Tc'),
        ('https://www.youtube.com/watch?v=qEb96qFi2Tc&t=30s', 'qEb96qFi2Tc'),
        ('https://youtu.be/qEb96qFi2Tc?si=abc123', 'qEb96qFi2Tc'),
    ],
)
def test_extract_video_id_handles_supported_url_formats(url: str, expected: str):
    assert extract_video_id(url) == expected


def test_extract_video_id_raises_on_unsupported_url():
    with pytest.raises(ValueError, match='Cannot extract video ID'):
        extract_video_id('https://example.com/not-a-youtube-url')


def test_get_youtube_video_metadata_returns_structured_info_on_success():
    fake_info = {
        'title': 'Why everyone needs Chimichurri in their lives',
        'description': 'A 3:1 vinaigrette framework applied to herbs...',
        'uploader': 'KWOOWK',
        'duration': 612,
    }
    with patch('life.services.url_extraction.yt_dlp.YoutubeDL') as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = fake_info
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        result = get_youtube_video_metadata('https://www.youtube.com/watch?v=qEb96qFi2Tc')

    assert result == YouTubeMetadata(
        title='Why everyone needs Chimichurri in their lives',
        description='A 3:1 vinaigrette framework applied to herbs...',
        uploader='KWOOWK',
        duration_seconds=612,
    )


def test_get_youtube_video_metadata_falls_back_to_channel_when_uploader_missing():
    fake_info = {'title': 't', 'description': 'd', 'channel': 'Some Channel', 'duration': 100}
    with patch('life.services.url_extraction.yt_dlp.YoutubeDL') as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = fake_info
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        result = get_youtube_video_metadata('https://www.youtube.com/watch?v=x')

    assert result.uploader == 'Some Channel'


def test_get_youtube_video_metadata_returns_empty_on_yt_dlp_exception():
    """yt-dlp breaks often — a failure must not propagate. Callers fall back to transcript-only."""
    with patch('life.services.url_extraction.yt_dlp.YoutubeDL') as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.side_effect = RuntimeError('yt-dlp site change broke extraction')

        result = get_youtube_video_metadata('https://www.youtube.com/watch?v=x')

    assert result == YouTubeMetadata(title=None, description=None, uploader=None, duration_seconds=None)


def test_get_youtube_video_metadata_returns_empty_on_none_info():
    with patch('life.services.url_extraction.yt_dlp.YoutubeDL') as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        result = get_youtube_video_metadata('https://www.youtube.com/watch?v=x')

    assert result == YouTubeMetadata(title=None, description=None, uploader=None, duration_seconds=None)
