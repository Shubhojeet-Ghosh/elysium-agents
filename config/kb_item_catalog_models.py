"""Structured LLM output for kb_item_catalog summary (embedded for routing)."""

from pydantic import BaseModel, Field


class KbCatalogSummary(BaseModel):
    summary: str = Field(
        ...,
        description="2-3 dense sentences describing what this knowledge item covers.",
    )
