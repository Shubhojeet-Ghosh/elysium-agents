from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


def _round_canvas_coordinate(value: Any) -> int:
    """React Flow uses floats for drag positions; persist as integers."""
    if isinstance(value, bool):
        raise ValueError("Coordinate must be a number.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    raise ValueError("Coordinate must be a number.")


class FlowNodePositionModel(BaseModel):
    x: int
    y: int

    @field_validator("x", "y", mode="before")
    @classmethod
    def coerce_coordinate(cls, value: Any) -> int:
        return _round_canvas_coordinate(value)


class FlowNodeDimensionsModel(BaseModel):
    width: int = Field(default=280, ge=1)
    height: int = Field(default=72, ge=1)

    @field_validator("width", "height", mode="before")
    @classmethod
    def coerce_dimension(cls, value: Any) -> int:
        return _round_canvas_coordinate(value)


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


class ListTeamEmailFlowsRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)


class GetFlowForAgentRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)


class GetFlowRequest(BaseModel):
    flow_id: str = Field(..., min_length=1, max_length=128)


class FlowNodeEdgeModel(BaseModel):
    to: str = Field(..., min_length=1, max_length=128)


class FlowNodeModel(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=128)
    type: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=256)
    position: FlowNodePositionModel
    dimensions: FlowNodeDimensionsModel | None = None
    config: Dict[str, Any] = Field(default_factory=dict)
    edges: List[FlowNodeEdgeModel] = Field(default_factory=list)


class CreateEmailFlowRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=2000)


class UpdateEmailFlowRequest(BaseModel):
    flow_id: str = Field(..., min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    nodes: List[FlowNodeModel] = Field(..., min_length=1)
