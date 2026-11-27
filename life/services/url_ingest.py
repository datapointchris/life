"""URL → classifier pipeline for the recipes/techniques import flow.

Used by `POST /recipes/import-from-url`. Orchestrates content extraction
(YouTube description + transcript, or article HTML text) and passes the
labeled content to a Claude classifier that returns a UrlImportCandidate.
"""

import structlog

from life import schemas
from life.ai.assistants.anthropic import AnthropicAssistant
from life.config import Settings
from life.services.url_extraction import is_youtube_url
from life.services.url_extraction import read_article_page
from life.services.url_extraction import read_youtube_video
from life.services.url_extraction import youtube_video_text

logger = structlog.get_logger()


def extract_content_for_classifier(url: str) -> str:
    """Build the labeled content block the classifier reads.

    YouTube: the details and the transcript, read through ypl, each in its own
    labeled section, so Claude can weigh the written recipe in the description
    against the spoken one. A transcript ypl refuses leaves its section empty.
    Unlike a summary, no word count applies, since a description alone can hold
    the recipe.

    Articles: the page text `read_article_page` returns, which refuses a redirect
    away from the page, a bot check and a page with no readable text.
    """
    if is_youtube_url(url):
        return youtube_video_text(read_youtube_video(url))

    return read_article_page(url).text


async def classify_url_content(url: str, hint: str, content: str, settings: Settings) -> schemas.UrlImportCandidate:
    """Run the classifier and return its UrlImportCandidate.

    A classifier that produces no usable candidate raises the assistant's
    `AssistantOutputError`, carrying its reason and raw output, and the API's
    handler for that error answers HTTP 424.
    """
    assistant = AnthropicAssistant(
        name='URL Import Classifier',
        system_prompt=settings.ai.prompts.url_import_classifier,
        settings=settings,
    )
    user_message = f'url: {url}\nhint: {hint}\n\n{content}'
    candidate = await assistant.generate_structured(user_message, schemas.UrlImportCandidate, max_tokens=8192)

    # Always pin source_url to the input URL — the classifier sometimes drops or
    # rewrites it, but the endpoint needs it for the duplicate check on re-ingest.
    if candidate.recipe is not None and candidate.recipe.source_url != url:
        candidate.recipe = candidate.recipe.model_copy(update={'source_url': url})
    if candidate.technique is not None and candidate.technique.source_url != url:
        candidate.technique = candidate.technique.model_copy(update={'source_url': url})

    return candidate
