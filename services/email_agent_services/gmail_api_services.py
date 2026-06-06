import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config.gmail_oauth_config import GOOGLE_TOKEN_URL
from config.settings import settings
from logging_config import get_logger

logger = get_logger()

GMAIL_MESSAGES_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_THREADS_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/threads"
SYNC_BATCH_SIZE = 20

async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    payload = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=payload)

    if response.status_code != 200:
        logger.error(f"Google refresh token failed: {response.status_code} {response.text}")
        return {
            "success": False,
            "message": "Failed to refresh Gmail access token.",
            "details": response.text,
        }

    return {"success": True, "data": response.json()}


def _gmail_after_date(cutoff: datetime) -> str:
    """Format datetime for Gmail search query after:YYYY/MM/DD."""
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return cutoff.astimezone(timezone.utc).strftime("%Y/%m/%d")


def _build_sync_thread_query(cutoff: datetime) -> str:
    """Gmail search query for inbox sync — Primary tab only (excludes Promotions, Social, etc.)."""
    return f"after:{_gmail_after_date(cutoff)} category:primary"


def _header_map(headers: List[Dict[str, str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for header in headers or []:
        name = header.get("name")
        value = header.get("value", "")
        if name:
            result[name] = value
    return result


def _split_recipients(value: str) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _decode_body_data(data: str) -> str:
    if not data:
        return ""
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_bodies(payload: Dict[str, Any]) -> Tuple[str, str]:
    """Extract plain text and HTML bodies from a Gmail full-format payload."""
    body_text = ""
    body_html = ""

    def walk(part: Dict[str, Any]) -> None:
        nonlocal body_text, body_html
        mime_type = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        data = body.get("data", "")

        if mime_type == "text/plain" and data and not body_text:
            body_text = _decode_body_data(data)
        elif mime_type == "text/html" and data and not body_html:
            body_html = _decode_body_data(data)

        for child in part.get("parts", []) or []:
            walk(child)

    if payload:
        walk(payload)

    return body_text, body_html


def _count_attachments(payload: Dict[str, Any]) -> int:
    count = 0

    def walk(part: Dict[str, Any]) -> None:
        nonlocal count
        body = part.get("body", {}) or {}
        filename = part.get("filename", "")
        if body.get("attachmentId") or filename:
            count += 1
        for child in part.get("parts", []) or []:
            walk(child)

    if payload:
        walk(payload)

    return count


def _parse_received_at(header_date: str, internal_date_ms: Optional[str]) -> datetime:
    if internal_date_ms:
        try:
            return datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            pass

    if header_date:
        try:
            parsed = parsedate_to_datetime(header_date)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass

    return datetime.now(timezone.utc)


def parse_gmail_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a Gmail API full-format message into storable metadata and bodies."""
    payload = message.get("payload", {}) or {}
    headers = _header_map(payload.get("headers", []))
    label_ids = message.get("labelIds", []) or []
    body_text, body_html = _extract_bodies(payload)
    attachment_count = _count_attachments(payload)

    return {
        "gmail_message_id": message.get("id", ""),
        "thread_id": message.get("threadId", ""),
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "to": _split_recipients(headers.get("To", "")),
        "cc": _split_recipients(headers.get("Cc", "")),
        "bcc": _split_recipients(headers.get("Bcc", "")),
        "reply_to": headers.get("Reply-To", ""),
        "message_id_header": headers.get("Message-ID", ""),
        "snippet": message.get("snippet", ""),
        "body_text": body_text,
        "body_html": body_html,
        "received_at": _parse_received_at(headers.get("Date", ""), message.get("internalDate")),
        "label_ids": label_ids,
        "is_unread": "UNREAD" in label_ids,
        "direction": "outbound" if "SENT" in label_ids else "inbound",
        "metadata": {
            "history_id": message.get("historyId"),
            "size_estimate": message.get("sizeEstimate"),
            "date_header": headers.get("Date", ""),
            "root_mime_type": payload.get("mimeType", ""),
            "has_attachments": attachment_count > 0,
            "attachment_count": attachment_count,
        },
    }


async def list_thread_ids(
    access_token: str,
    cutoff: datetime,
    max_results: int = SYNC_BATCH_SIZE,
) -> Dict[str, Any]:
    """List Primary-tab Gmail thread IDs with activity after the cutoff date."""
    query = _build_sync_thread_query(cutoff)
    params = {
        "q": query,
        "maxResults": max_results,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            GMAIL_THREADS_LIST_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )

    if response.status_code != 200:
        logger.error(f"Gmail list threads failed: {response.status_code} {response.text}")
        return {
            "success": False,
            "message": "Failed to list Gmail threads.",
            "details": response.text,
        }

    data = response.json()
    threads = data.get("threads", []) or []
    return {
        "success": True,
        "data": {
            "thread_ids": [item.get("id") for item in threads if item.get("id")],
            "result_size_estimate": data.get("resultSizeEstimate", 0),
        },
    }


async def get_gmail_thread(access_token: str, thread_id: str) -> Dict[str, Any]:
    """Fetch a Gmail thread with all messages in full format."""
    params = {"format": "full"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"{GMAIL_THREADS_LIST_URL}/{thread_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )

    if response.status_code != 200:
        logger.error(f"Gmail get thread failed: {response.status_code} {response.text}")
        return {
            "success": False,
            "message": f"Failed to fetch Gmail thread {thread_id}.",
            "details": response.text,
        }

    return {"success": True, "data": response.json()}


async def get_gmail_message(access_token: str, message_id: str) -> Dict[str, Any]:
    """Fetch a single Gmail message with full payload (headers + body parts)."""
    params = {
        "format": "full",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GMAIL_MESSAGES_LIST_URL}/{message_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )

    if response.status_code != 200:
        logger.error(f"Gmail get message failed: {response.status_code} {response.text}")
        return {
            "success": False,
            "message": f"Failed to fetch Gmail message {message_id}.",
            "details": response.text,
        }

    return {"success": True, "data": response.json()}


def is_message_after_cutoff(message: Dict[str, Any], cutoff: datetime) -> bool:
    """Filter messages more precisely than Gmail's after: date query."""
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)

    internal_date_ms = message.get("internalDate")
    if internal_date_ms:
        try:
            received_at = datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=timezone.utc)
            return received_at > cutoff
        except (TypeError, ValueError):
            return True

    return True
