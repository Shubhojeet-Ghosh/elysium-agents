from pydantic import BaseModel, Field


class PreviewLoadThreadContextRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    thread_id: str = Field(..., min_length=1, max_length=256)
    trigger_message_id: str = Field(
        default="",
        max_length=256,
        description=(
            "Mongo message _id or gmail_message_id for the inbound message that triggered the run. "
            "If omitted, uses the latest inbound message with processing_status=pending."
        ),
    )
    persist_run_log: bool = Field(
        default=True,
        description="When true, creates an email-flow-runs record with the node log output.",
    )
    message_limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max messages to load from the thread (oldest-first window ending at latest).",
    )


class GetFlowRunRequest(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=128)


class ListThreadFlowRunsRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    thread_id: str = Field(..., min_length=1, max_length=256)
    limit: int = Field(default=20, ge=1, le=100)


class ReprocessAgentThreadRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    thread_id: str = Field(..., min_length=1, max_length=256)
    trigger_message_id: str = Field(
        default="",
        max_length=256,
        description=(
            "Optional Mongo message _id or gmail_message_id. "
            "If omitted, uses latest inbound (or latest pending when force_reprocess is false)."
        ),
    )
    force_reprocess: bool = Field(
        default=True,
        description="When true, re-runs even if the thread was already processed (recommended for testing).",
    )
    message_limit: int = Field(default=10, ge=1, le=100)
