"""LLM summaries for kb_item_catalog (summary only; metadata stays empty for now)."""

from config.kb_item_catalog_models import KbCatalogSummary
from config.kb_item_constants import (
    KB_ITEM_CATALOG_SUMMARY_ENABLED,
    SOURCE_TYPE_CUSTOM_TEXT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_QA_PAIR,
    SOURCE_TYPE_URL,
)
from services.open_ai_services import openai_structured_output

_SUMMARY_MODEL = "gpt-4.1-nano"
_MAX_INPUT_CHARS = 120_000

_SYSTEM_PROMPTS: dict[str, str] = {
    SOURCE_TYPE_URL: (
        "You are an expert at summarizing web page content for a team knowledge library.\n\n"
        "The user message includes the page URL and plain text extracted from that page "
        "(navigation noise may be included). Describe what that page is actually about.\n\n"
        "Rules:\n"
        "- Base the summary ONLY on information present in the provided content. Do not invent facts.\n"
        "- Do not write about search, routing, embeddings, AI, or how the summary will be stored.\n"
        "- Write exactly 2-3 dense sentences covering the main topic, key facts, products, services, "
        "people, or policies someone might ask about.\n"
        "- Prefer concrete nouns and specifics from the page over vague marketing language.\n"
        "- If the text is thin or unclear, summarize only what is explicitly stated."
    ),
    SOURCE_TYPE_FILE: (
        "You are an expert at summarizing uploaded documents for a team knowledge library.\n\n"
        "The user message includes the file name and text extracted from that document. "
        "Summarize what the document covers and what questions it could answer.\n\n"
        "Rules:\n"
        "- Base the summary ONLY on the provided content. Do not invent details.\n"
        "- Do not mention search systems, routing, or embeddings.\n"
        "- Write exactly 2-3 dense sentences highlighting the document's subject, scope, and key details.\n"
        "- If the text is thin, state only what is clearly present."
    ),
    SOURCE_TYPE_CUSTOM_TEXT: (
        "You are an expert at summarizing custom knowledge snippets for a team knowledge library.\n\n"
        "The user message is a custom text entry written by the team. Summarize its purpose and main points.\n\n"
        "Rules:\n"
        "- Base the summary ONLY on the provided text. Do not add assumptions.\n"
        "- Do not mention search systems, routing, or embeddings.\n"
        "- Write exactly 2-3 dense sentences capturing what this snippet explains or defines."
    ),
    SOURCE_TYPE_QA_PAIR: (
        "You are an expert at summarizing question-and-answer knowledge for a team knowledge library.\n\n"
        "The user message contains one question and its answer. Summarize what topic it addresses "
        "and the gist of the answer.\n\n"
        "Rules:\n"
        "- Base the summary ONLY on the provided question and answer.\n"
        "- Do not mention search systems, routing, or embeddings.\n"
        "- Write exactly 2-3 dense sentences so someone searching later can tell when this Q&A is relevant."
    ),
}


def _truncate(text: str) -> str:
    if len(text) <= _MAX_INPUT_CHARS:
        return text
    return text[:_MAX_INPUT_CHARS]


def _build_user_message(
    source_type: str,
    *,
    text_content: str,
    url: str | None = None,
    file_name: str | None = None,
    question: str | None = None,
    answer: str | None = None,
) -> str:
    if source_type == SOURCE_TYPE_URL:
        if not url:
            raise ValueError("url is required for URL summary generation")
        return f"URL:\n{url}\n\nPage content:\n\n{_truncate(text_content)}"

    if source_type == SOURCE_TYPE_FILE:
        if not file_name:
            raise ValueError("file_name is required for file summary generation")
        return f"File name:\n{file_name}\n\nDocument content:\n\n{_truncate(text_content)}"

    if source_type == SOURCE_TYPE_CUSTOM_TEXT:
        return _truncate(text_content)

    if source_type == SOURCE_TYPE_QA_PAIR:
        if not question or not answer:
            raise ValueError("question and answer are required for Q&A summary generation")
        return f"Question:\n{question}\n\nAnswer:\n{answer}"

    raise ValueError(f"Unsupported source_type for summary: {source_type}")


async def generate_kb_item_catalog_summary(
    source_type: str,
    text_content: str,
    *,
    url: str | None = None,
    file_name: str | None = None,
    question: str | None = None,
    answer: str | None = None,
) -> str:
    """
    Returns summary text for kb_item_catalog. Caller stores metadata as {}.

    URL summaries require url + scraped text_content.
    File summaries require file_name + extracted text_content.
    Custom text uses text_content only.
    Q&A summaries require question + answer (text_content ignored).
    """
    if source_type not in (
        SOURCE_TYPE_URL,
        SOURCE_TYPE_FILE,
        SOURCE_TYPE_CUSTOM_TEXT,
        SOURCE_TYPE_QA_PAIR,
    ):
        raise ValueError(f"Unsupported source_type for summary: {source_type}")

    body = _build_user_message(
        source_type,
        text_content=text_content,
        url=url,
        file_name=file_name,
        question=question,
        answer=answer,
    )
    entry = await openai_structured_output(
        model=_SUMMARY_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPTS[source_type]},
            {"role": "user", "content": body},
        ],
        response_format=KbCatalogSummary,
    )
    return entry["summary"]


async def resolve_kb_item_catalog_summary(
    source_type: str,
    text_content: str,
    *,
    url: str | None = None,
    file_name: str | None = None,
    question: str | None = None,
    answer: str | None = None,
) -> str | None:
    """
    Returns LLM summary when KB_ITEM_CATALOG_SUMMARY_ENABLED is True, else None.
    Toggle in config/kb_item_constants.py.
    """
    if not KB_ITEM_CATALOG_SUMMARY_ENABLED:
        return None
    return await generate_kb_item_catalog_summary(
        source_type,
        text_content,
        url=url,
        file_name=file_name,
        question=question,
        answer=answer,
    )
