"""
Orchestrate inline KB item creation + agent attachment on build/update agent.

Team items are created or finalized first; attachments are synced via kb_attachment_service.
Indexing is scheduled separately via BackgroundTasks.

If an inline item already exists in the team library (by URL, file name, or alias),
the existing kb_id is attached without re-indexing.
"""

from typing import Any

from config.kb_item_constants import (
    MAX_URLS_PER_CREATE,
    SOURCE_TYPE_CUSTOM_TEXT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_QA_PAIR,
    SOURCE_TYPE_URL,
)
from logging_config import get_logger
from services.elysium_atlas_services.kb_item.kb_attachment_service import sync_kb_attachments_for_agent
from services.elysium_atlas_services.kb_item.kb_item_services import (
    create_custom_text_for_team,
    create_qa_pair_for_team,
    create_url_items_for_team,
    delete_draft_file_item,
    finalize_file_item,
    find_custom_text_kb_id_for_team,
    find_file_kb_id_for_team,
    find_qa_pair_kb_id_for_team,
    find_url_kb_id_for_team,
    get_file_item,
)

logger = get_logger()

_INDEX_SCHEDULE_KEY = "_kb_items_to_index"


def _normalize_kb_attachments(raw: Any) -> list[dict[str, str]] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None

    normalized: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        kb_id = str(entry.get("kb_id", "")).strip()
        source_type = str(entry.get("source_type", "")).strip()
        if kb_id and source_type:
            normalized.append({"kb_id": kb_id, "source_type": source_type})
    return normalized


def request_has_kb_payload(request_data: dict[str, Any]) -> bool:
    """Return True when the request includes KB attachment or inline create fields."""
    if _normalize_kb_attachments(request_data.get("kb_attachments")) is not None:
        return True
    for field in ("new_urls", "new_files", "new_custom_texts", "new_qa_pairs"):
        value = request_data.get(field)
        if isinstance(value, list) and len(value) > 0:
            return True
    return False


def pop_kb_index_jobs(request_data: dict[str, Any]) -> list[tuple[str, str]]:
    """Pop (kb_id, source_type) pairs scheduled for indexing during KB orchestration."""
    jobs = request_data.pop(_INDEX_SCHEDULE_KEY, [])
    if not isinstance(jobs, list):
        return []
    return [(str(kb_id), str(source_type)) for kb_id, source_type in jobs if kb_id and source_type]


def _schedule_index(request_data: dict[str, Any], kb_id: str, source_type: str) -> None:
    jobs: list[tuple[str, str]] = request_data.setdefault(_INDEX_SCHEDULE_KEY, [])
    jobs.append((kb_id, source_type))


def _append_attachment(
    attachments: list[dict[str, str]],
    request_data: dict[str, Any],
    kb_id: str,
    source_type: str,
    *,
    should_index: bool,
) -> None:
    attachments.append({"kb_id": kb_id, "source_type": source_type})
    if should_index:
        _schedule_index(request_data, kb_id, source_type)


async def _create_inline_urls(
    request_data: dict[str, Any],
    team_id: str,
    user_id: str,
) -> tuple[list[dict[str, str]], str | None]:
    raw_urls = request_data.get("new_urls")
    if not isinstance(raw_urls, list) or not raw_urls:
        return [], None

    urls = [str(u).strip() for u in raw_urls if u and str(u).strip()]
    if not urls:
        return [], None
    if len(urls) > MAX_URLS_PER_CREATE:
        return [], f"new_urls exceeds maximum of {MAX_URLS_PER_CREATE} URLs per request."

    attachments: list[dict[str, str]] = []
    seen_kb_ids: set[str] = set()

    for raw_url in urls:
        existing_kb_id = await find_url_kb_id_for_team(team_id, raw_url)
        if existing_kb_id:
            if existing_kb_id not in seen_kb_ids:
                _append_attachment(
                    attachments,
                    request_data,
                    existing_kb_id,
                    SOURCE_TYPE_URL,
                    should_index=False,
                )
                seen_kb_ids.add(existing_kb_id)
            continue

        created, error = await create_url_items_for_team(team_id, user_id, [raw_url])
        if error or not created:
            return [], error or "Failed to create URL items."

        kb_id = created[0]["kb_id"]
        if kb_id not in seen_kb_ids:
            _append_attachment(
                attachments,
                request_data,
                kb_id,
                SOURCE_TYPE_URL,
                should_index=True,
            )
            seen_kb_ids.add(kb_id)

    return attachments, None


async def _finalize_inline_files(
    request_data: dict[str, Any],
    team_id: str,
) -> tuple[list[dict[str, str]], str | None]:
    raw_files = request_data.get("new_files")
    if not isinstance(raw_files, list) or not raw_files:
        return [], None

    attachments: list[dict[str, str]] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            return [], "Each new_files entry must be an object with kb_id and file_key."
        kb_id = str(entry.get("kb_id", "")).strip()
        file_key = str(entry.get("file_key", "")).strip()
        if not kb_id or not file_key:
            return [], "Each new_files entry requires kb_id and file_key."

        draft = await get_file_item(kb_id)
        if not draft or draft.get("team_id") != team_id:
            return [], f"File item not found: {kb_id}."

        file_name = str(draft.get("file_name") or file_key.rsplit("/", 1)[-1]).strip()
        existing_kb_id = await find_file_kb_id_for_team(team_id, file_name)
        if existing_kb_id and existing_kb_id != kb_id:
            await delete_draft_file_item(team_id, kb_id)
            _append_attachment(
                attachments,
                request_data,
                existing_kb_id,
                SOURCE_TYPE_FILE,
                should_index=False,
            )
            continue

        finalized, error = await finalize_file_item(team_id, kb_id, file_key)
        if error or not finalized:
            return [], error or f"Failed to finalize file item {kb_id}."

        _append_attachment(
            attachments,
            request_data,
            kb_id,
            SOURCE_TYPE_FILE,
            should_index=True,
        )

    return attachments, None


async def _create_inline_custom_texts(
    request_data: dict[str, Any],
    team_id: str,
    user_id: str,
) -> tuple[list[dict[str, str]], str | None]:
    raw_texts = request_data.get("new_custom_texts")
    if not isinstance(raw_texts, list) or not raw_texts:
        return [], None

    attachments: list[dict[str, str]] = []
    for entry in raw_texts:
        if not isinstance(entry, dict):
            return [], "Each new_custom_texts entry must be an object."
        alias = str(entry.get("custom_text_alias", "")).strip()
        content = str(entry.get("custom_text", "")).strip()
        if not alias or not content:
            return [], "Each new_custom_texts entry requires custom_text_alias and custom_text."

        existing_kb_id = await find_custom_text_kb_id_for_team(team_id, alias)
        if existing_kb_id:
            _append_attachment(
                attachments,
                request_data,
                existing_kb_id,
                SOURCE_TYPE_CUSTOM_TEXT,
                should_index=False,
            )
            continue

        created, error = await create_custom_text_for_team(team_id, user_id, alias, content)
        if error or not created:
            return [], error or "Failed to create custom text item."

        _append_attachment(
            attachments,
            request_data,
            created["kb_id"],
            SOURCE_TYPE_CUSTOM_TEXT,
            should_index=True,
        )

    return attachments, None


async def _create_inline_qa_pairs(
    request_data: dict[str, Any],
    team_id: str,
    user_id: str,
) -> tuple[list[dict[str, str]], str | None]:
    raw_pairs = request_data.get("new_qa_pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        return [], None

    attachments: list[dict[str, str]] = []
    for entry in raw_pairs:
        if not isinstance(entry, dict):
            return [], "Each new_qa_pairs entry must be an object."
        alias = str(entry.get("qna_alias", "")).strip()
        question = str(entry.get("question", "")).strip()
        answer = str(entry.get("answer", "")).strip()
        if not alias or not question or not answer:
            return [], "Each new_qa_pairs entry requires qna_alias, question, and answer."

        existing_kb_id = await find_qa_pair_kb_id_for_team(team_id, alias)
        if existing_kb_id:
            _append_attachment(
                attachments,
                request_data,
                existing_kb_id,
                SOURCE_TYPE_QA_PAIR,
                should_index=False,
            )
            continue

        created, error = await create_qa_pair_for_team(team_id, user_id, alias, question, answer)
        if error or not created:
            return [], error or "Failed to create Q&A item."

        _append_attachment(
            attachments,
            request_data,
            created["kb_id"],
            SOURCE_TYPE_QA_PAIR,
            should_index=True,
        )

    return attachments, None


async def apply_agent_kb_changes(
    agent_id: str,
    team_id: str,
    user_id: str,
    request_data: dict[str, Any],
    *,
    is_build: bool,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Create inline team KB items, sync attachments, and schedule indexing jobs on request_data.

    kb_attachments:
      - build-agent: full desired set (omit = no attachments unless inline items add some)
      - update-agent: full desired set when key is present; omit key = keep existing + append inline
    """
    if not request_has_kb_payload(request_data):
        return None, None

    explicit_attachments = _normalize_kb_attachments(request_data.get("kb_attachments"))
    replace = is_build or "kb_attachments" in request_data

    inline_attachments: list[dict[str, str]] = []
    inline_steps: list[tuple[Any, tuple[Any, ...]]] = [
        (_create_inline_urls, (request_data, team_id, user_id)),
        (_finalize_inline_files, (request_data, team_id)),
        (_create_inline_custom_texts, (request_data, team_id, user_id)),
        (_create_inline_qa_pairs, (request_data, team_id, user_id)),
    ]
    for step, args in inline_steps:
        created, error = await step(*args)
        if error:
            return None, error
        inline_attachments.extend(created)

    if replace:
        desired = list(explicit_attachments or [])
        existing_kb_ids = {item["kb_id"] for item in desired}
        for item in inline_attachments:
            if item["kb_id"] not in existing_kb_ids:
                desired.append(item)
                existing_kb_ids.add(item["kb_id"])
    else:
        desired = inline_attachments

    success, error = await sync_kb_attachments_for_agent(
        agent_id,
        team_id,
        desired,
        user_id,
        replace=replace,
    )
    if not success:
        return None, error

    attachments = await _fetch_attachments(agent_id)
    return attachments, None


async def _fetch_attachments(agent_id: str) -> list[dict[str, Any]]:
    from services.elysium_atlas_services.kb_item.kb_attachment_service import list_kb_attachments_for_agent

    return await list_kb_attachments_for_agent(agent_id)
