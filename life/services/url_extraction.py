"""Turn a URL into its page's title and text.

`read_article_page` reads a page's title and text, and `read_article_title` its
title alone. Both refuse a page that is not the article: one the site
redirected to its homepage or a section index, or a bot challenge standing in
for the page. `read_article_page` also refuses a page with too little text to
be about anything. Each refusal is its own exception, so the import worker
records why and a caller can branch on which.

A YouTube video is read through ypl, never from YouTube. Its text is its
details and its transcript, each under its own label.
"""

import io
import re
from dataclasses import dataclass
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlsplit

import structlog
import trafilatura
from bs4 import BeautifulSoup
from bs4 import Tag
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from life.config import get_settings
from life.services.outbound_http import FetchedPage
from life.services.outbound_http import get_page
from life.services.ypl_client import VideoDetails
from life.services.ypl_client import YplClient
from life.services.ypl_client import YplRefused
from life.services.ypl_client import ypl_client

logger = structlog.get_logger()

# Below this, what extraction found is not writing: a cookie notice, a login
# prompt, a post whose content is an image, a JavaScript app shell. A summary
# of any of those describes the page chrome and reads as if it were the article.
MIN_READABLE_WORDS = 40

# Titles a site serves in place of the page when it has decided the request is a
# bot. Each separator-delimited segment of the document <title> is compared
# lowercased and exact — Reddit's is "Reddit - Prove your humanity", where the
# phrase is the part a suffix strip would discard — so an article merely
# mentioning one of the phrases is not caught.
BOT_CHALLENGE_TITLES = frozenset(
    {
        'just a moment...',  # Cloudflare's interstitial
        'attention required!',  # Cloudflare's block page
        'prove your humanity',  # Reddit
        'access denied',  # Akamai, served by Stanford Online among others
    }
)

TITLE_SUFFIX_SEPARATORS = (' | ', ' - ', ' — ', ' · ')

YOUTUBE_HOSTS = frozenset({'youtube.com', 'youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com'})
VIDEO_PATH_PREFIXES = frozenset({'shorts', 'live', 'embed'})
VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')


class PageUnreadable(Exception):
    """The site answered, but what it sent is not the page that was saved."""

    def __init__(self, url: str, message: str):
        super().__init__(message)
        self.url = url


class NotAVideoUrl(PageUnreadable):
    """A YouTube URL that names no video, such as a channel or a search. Only a video is read, through ypl."""

    def __init__(self, url: str):
        super().__init__(url, f'{url} names no YouTube video, and only a video can be read')


class VideoNotFound(PageUnreadable):
    """YouTube returns no public or unlisted video for the id: it is private, deleted, or never existed."""

    def __init__(self, url: str, video_id: str):
        super().__init__(url, f'{url} names video {video_id}, which YouTube does not return')
        self.video_id = video_id


class PageRedirectedAway(PageUnreadable):
    """The site redirected the page to its homepage or to a section above it."""

    def __init__(self, url: str, final_url: str):
        super().__init__(url, f'{url} now redirects to {final_url}, not to the page that was saved')
        self.final_url = final_url


class PageIsBotChallenge(PageUnreadable):
    """The site served a bot check in place of the page."""

    def __init__(self, url: str, title: str):
        super().__init__(url, f'{url} served a bot check ("{title}") in place of the page')
        self.title = title


class PageIsUnreadablePdf(PageUnreadable):
    """The link is a PDF that could not be parsed: damaged, encrypted or not really a PDF."""

    def __init__(self, url: str, reason: str):
        super().__init__(url, f'{url} is a PDF that could not be read: {reason}')
        self.reason = reason


class PageHasNoText(PageUnreadable):
    """Extraction found too little text to summarize."""

    def __init__(self, url: str, word_count: int):
        super().__init__(url, f'{url} has {word_count} words of readable text, below the {MIN_READABLE_WORDS} a summary needs')
        self.word_count = word_count


@dataclass(frozen=True)
class YouTubeVideo:
    """A video's details, and its transcript where ypl could give one."""

    details: VideoDetails
    transcript: str | None


@dataclass(frozen=True)
class ArticlePage:
    """What a summary is written from. `url` is where the page was finally served."""

    url: str
    title: str
    text: str


def url_host(url: str) -> str:
    """The URL's lowercased host, reading a URL saved without its scheme as if it had one."""
    return (urlsplit(url if '//' in url else f'//{url}').hostname or '').lower()


def is_youtube_url(url: str) -> bool:
    host = url_host(url)
    return host in YOUTUBE_HOSTS or host.endswith('.youtube.com')


def extract_video_id(url: str) -> str:
    """The video id a YouTube URL names, or `NotAVideoUrl` for one that names none.

    Reads youtu.be/ID, youtube.com/watch?v=ID, and the /shorts/, /live/ and
    /embed/ paths.
    """
    parts = urlsplit(url if '//' in url else f'//{url}')
    segments = [segment for segment in parts.path.split('/') if segment]
    if url_host(url) == 'youtu.be':
        candidate = segments[0] if segments else ''
    elif len(segments) >= 2 and segments[0] in VIDEO_PATH_PREFIXES:
        candidate = segments[1]
    else:
        candidate = parse_qs(parts.query).get('v', [''])[0]
    if not VIDEO_ID.fullmatch(candidate):
        raise NotAVideoUrl(url)
    return candidate


def read_youtube_details(url: str, client: YplClient | None = None) -> VideoDetails:
    """The video's title, description, channel and duration, read through ypl."""
    video_id = extract_video_id(url)
    details = (client or ypl_client(get_settings())).video_details(video_id)
    if details is None:
        raise VideoNotFound(url, video_id)
    return details


def read_youtube_video(url: str) -> YouTubeVideo:
    """The video's details and transcript, read through ypl.

    The details are required, because they hold the title. The transcript is
    not. When ypl refuses it, the video is read without one, and the log names
    ypl's code and its `Retry-After`. ypl answers 404 for a video with no
    captions, and 503 while its door is busy or paused.
    """
    client = ypl_client(get_settings())
    details = read_youtube_details(url, client)
    try:
        transcript = client.transcript(details.video_id).text
    except YplRefused as e:
        logger.warning(
            'youtube_transcript_left_out',
            url=url,
            video_id=details.video_id,
            status=e.status_code,
            code=e.code,
            retry_after=e.retry_after,
            error=e.message,
        )
        transcript = None
    return YouTubeVideo(details=details, transcript=transcript)


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ''
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


def youtube_video_text(video: YouTubeVideo) -> str:
    """What a model reads for a video: each detail and the transcript under its own label.

    The description is the uploader's own text and often carries what the video
    leaves unsaid, such as a recipe's quantities. A missing transcript leaves its
    label empty.
    """
    details = video.details
    return (
        f'<title>{details.title}</title>\n'
        f'<channel>{details.channel_title}</channel>\n'
        f'<duration>{format_duration(details.duration_seconds)}</duration>\n'
        f'<description>{details.description}</description>\n'
        f'<transcript>{video.transcript or ""}</transcript>\n'
    )


def strip_site_suffix(title: str) -> str:
    """Drop a trailing site name: "Article Title | Site Name" becomes "Article Title".

    Splits on the last separator, and only when what follows is four words or
    fewer, so a title using a separator inside itself survives.
    """
    for separator in TITLE_SUFFIX_SEPARATORS:
        if separator in title:
            head, tail = title.rsplit(separator, 1)
            if len(tail.split()) <= 4:
                title = head
            break
    return title.strip()


def get_page_title(soup: BeautifulSoup) -> str | None:
    """The page's own title: og:title, then the document <title>, then the first <h1>.

    The document <title> is read from <head> only. An inline SVG carries its own
    <title> for accessibility, and a site that draws its logo that way puts
    "Site Logo" first in the document.
    """
    og_title = soup.find('meta', attrs={'property': 'og:title'})
    head_title = soup.head.find('title') if isinstance(soup.head, Tag) else None
    first_heading = soup.find('h1')
    candidates = (
        og_title.get('content') if isinstance(og_title, Tag) else None,
        head_title.get_text() if isinstance(head_title, Tag) else None,
        first_heading.get_text() if isinstance(first_heading, Tag) else None,
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return strip_site_suffix(' '.join(candidate.split()))
    return None


def bot_challenge_title(soup: BeautifulSoup) -> str | None:
    """The document <title> when it is a bot check standing in for the page, else None."""
    head_title = soup.head.find('title') if isinstance(soup.head, Tag) else None
    if not isinstance(head_title, Tag):
        return None
    title = ' '.join(head_title.get_text().split())
    segments = re.split('|'.join(re.escape(separator) for separator in TITLE_SUFFIX_SEPARATORS), title)
    if any(segment.strip().lower() in BOT_CHALLENGE_TITLES for segment in segments):
        return title
    return None


def extract_main_text(content: bytes, url: str) -> str:
    """The page's main text, without navigation, share rows, sidebars or related-post cards.

    Recall is favored, because a summary written from a little too much text is
    still about the article and one written from too little is not. Tables are
    kept for recipes and reference pages; a site's own comment section is not
    the article and is left out.
    """
    text = trafilatura.extract(content, url=url, favor_recall=True, include_tables=True, include_comments=False)
    return text or ''


def is_pdf(content: bytes) -> bool:
    """Whether a response body is a PDF, by its signature rather than a content type servers often get wrong."""
    return content.startswith(b'%PDF-')


def title_from_file_name(url: str) -> str | None:
    """A title made from the last path segment: `A_Good_Tech_Resume.pdf` becomes "A Good Tech Resume"."""
    name = unquote(urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1])
    stem = re.sub(r'\.pdf$', '', name, flags=re.IGNORECASE)
    words = re.sub(r'[_\-]+', ' ', stem).split()
    return ' '.join(words) or None


def read_pdf(content: bytes, url: str) -> tuple[str | None, str]:
    """A PDF's title and its text, one paragraph per page.

    Whitespace inside a page is collapsed, because text laid out in a PDF often
    extracts one word per line and the line breaks carry nothing.
    """
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [' '.join((page.extract_text() or '').split()) for page in reader.pages]
        metadata_title = reader.metadata.title if reader.metadata is not None else None
    except PyPdfError as e:
        raise PageIsUnreadablePdf(url, str(e)) from e
    title = metadata_title.strip() if isinstance(metadata_title, str) and metadata_title.strip() else title_from_file_name(url)
    return title, '\n\n'.join(page for page in pages if page)


def redirected_away(requested_url: str, final_url: str) -> bool:
    """Whether a redirect replaced the page with the site's homepage or a section above it.

    A moved article lands on another path and is still the article. Landing on
    `/`, or on a path the requested one sits under, is the site saying the page
    is gone and sending the reader somewhere general instead.
    """
    requested_path = urlsplit(requested_url).path.rstrip('/')
    final_path = urlsplit(final_url).path.rstrip('/')
    if not requested_path or final_path == requested_path:
        return False
    return final_path == '' or requested_path.startswith(final_path + '/')


def fetch_article(url: str) -> tuple[FetchedPage, BeautifulSoup | None]:
    """Fetch a saved page, refusing a redirect away from it and a bot check in its place.

    The soup is None for a PDF, which has no document to parse.
    """
    page = get_page(url).raise_for_status()
    if redirected_away(page.requested_url, page.url):
        raise PageRedirectedAway(url, page.url)
    if is_pdf(page.content):
        return page, None
    soup = BeautifulSoup(page.content, 'html.parser')
    if (challenge := bot_challenge_title(soup)) is not None:
        raise PageIsBotChallenge(url, challenge)
    return page, soup


def read_article_title(url: str) -> str:
    """Read a saved page's title, with no transcript and no word count."""
    if is_youtube_url(url):
        return read_youtube_details(url).title or url
    page, soup = fetch_article(url)
    title = read_pdf(page.content, page.url)[0] if soup is None else get_page_title(soup)
    return title or page.url


def read_video_page(url: str) -> ArticlePage:
    """A video's title, and its details and transcript as the text to summarize.

    The words counted are the description's and the transcript's, so a video
    read without a transcript is still summarized from a description long
    enough to be about something.
    """
    video = read_youtube_video(url)
    word_count = len(video.details.description.split()) + len((video.transcript or '').split())
    if word_count < MIN_READABLE_WORDS:
        raise PageHasNoText(url, word_count)
    return ArticlePage(url=url, title=video.details.title or url, text=youtube_video_text(video))


def read_article_page(url: str) -> ArticlePage:
    """Fetch a saved page and return its title and the text to summarize.

    A YouTube video's text is its details and transcript, read through ypl, and
    a PDF's is its pages. Everything else is extracted from the page. Every kind
    is refused when it has too little text.
    """
    if is_youtube_url(url):
        return read_video_page(url)
    page, soup = fetch_article(url)
    if soup is None:
        title, text = read_pdf(page.content, page.url)
    else:
        title = get_page_title(soup)
        text = extract_main_text(page.content, page.url)

    word_count = len(text.split())
    if word_count < MIN_READABLE_WORDS:
        raise PageHasNoText(url, word_count)
    return ArticlePage(url=page.url, title=title or page.url, text=text)
