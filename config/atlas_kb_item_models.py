from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.kb_item_constants import (
    DEFAULT_KB_LIST_PAGE_SIZE,
    MAX_KB_LIST_PAGE_SIZE,
    MAX_URLS_PER_CREATE,
    KB_SOURCE_TYPES,
)


def _validate_alias(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("Alias must not be empty.")
    return stripped


class PaginationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=DEFAULT_KB_LIST_PAGE_SIZE, ge=1, le=MAX_KB_LIST_PAGE_SIZE)


class SearchKbItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["url", "file", "custom_text", "qa_pair"]
    search_query: str = Field(..., min_length=1, max_length=256)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=DEFAULT_KB_LIST_PAGE_SIZE, ge=1, le=MAX_KB_LIST_PAGE_SIZE)

    @field_validator("search_query")
    @classmethod
    def strip_search_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("search_query must not be empty.")
        return stripped


class KbIdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(..., min_length=1)


class ReindexItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(..., min_length=1)
    source_type: Literal["url", "file", "custom_text", "qa_pair"]


class CreateUrlsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(..., min_length=1, max_length=MAX_URLS_PER_CREATE)

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, values: list[str]) -> list[str]:
        normalized = [u.strip() for u in values if u and u.strip()]
        if not normalized:
            raise ValueError("urls must contain at least one non-empty URL.")
        return normalized


class UpdateUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip()


class CreateFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(..., min_length=1, max_length=512)


class PresignedFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(..., min_length=1, max_length=512)
    filetype: str = Field(default="application/octet-stream", min_length=1, max_length=128)


class GenerateKbPresignedUrlsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(..., min_length=1)
    files: list[PresignedFileInput] = Field(..., min_length=1, max_length=10)


class FinalizeFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(..., min_length=1)
    file_key: str = Field(..., min_length=1)


class CreateCustomTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    custom_text_alias: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=500_000)

    @field_validator("custom_text_alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        return _validate_alias(value)


class UpdateCustomTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(..., min_length=1)
    custom_text_alias: str | None = Field(default=None, min_length=1, max_length=64)
    content: str | None = Field(default=None, min_length=1, max_length=500_000)

    @field_validator("custom_text_alias")
    @classmethod
    def validate_alias(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_alias(value)


class CreateQaPairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qna_alias: str = Field(..., min_length=1, max_length=64)
    question: str = Field(..., min_length=1, max_length=10_000)
    answer: str = Field(..., min_length=1, max_length=50_000)

    @field_validator("qna_alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        return _validate_alias(value)


class UpdateQaPairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(..., min_length=1)
    qna_alias: str | None = Field(default=None, min_length=1, max_length=64)
    question: str | None = Field(default=None, min_length=1, max_length=10_000)
    answer: str | None = Field(default=None, min_length=1, max_length=50_000)

    @field_validator("qna_alias")
    @classmethod
    def validate_alias(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_alias(value)


def source_type_literal():
    return Literal[tuple(KB_SOURCE_TYPES)]  # type: ignore[misc]
