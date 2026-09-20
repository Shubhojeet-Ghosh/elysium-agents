from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DASHBOARD_RANGE_TODAY = "today"
DASHBOARD_RANGE_LAST_7_DAYS = "last_7_days"
DASHBOARD_RANGE_LAST_30_DAYS = "last_30_days"
DASHBOARD_RANGE_LAST_365_DAYS = "last_365_days"

DASHBOARD_GRANULARITY_DAY = "day"
DASHBOARD_GRANULARITY_MONTH = "month"

DashboardDateRange = Literal[
    "today",
    "last_7_days",
    "last_30_days",
    "last_365_days",
]

DashboardGranularity = Literal["day", "month"]

# last_365_days is 12 UTC calendar months (including the current month), not 365 days.
DASHBOARD_RANGE_SPECS: dict[str, dict[str, str | int]] = {
    DASHBOARD_RANGE_TODAY: {
        "granularity": DASHBOARD_GRANULARITY_DAY,
        "bucket_count": 1,
    },
    DASHBOARD_RANGE_LAST_7_DAYS: {
        "granularity": DASHBOARD_GRANULARITY_DAY,
        "bucket_count": 7,
    },
    DASHBOARD_RANGE_LAST_30_DAYS: {
        "granularity": DASHBOARD_GRANULARITY_DAY,
        "bucket_count": 30,
    },
    DASHBOARD_RANGE_LAST_365_DAYS: {
        "granularity": DASHBOARD_GRANULARITY_MONTH,
        "bucket_count": 12,
    },
}


class ChatSessionCountsRequest(BaseModel):
    """New-session and visitor-message counts for the authenticated team."""

    model_config = ConfigDict(extra="forbid")

    range: DashboardDateRange = Field(
        ...,
        description=(
            "UTC window including today / the current month: today, last_7_days, "
            "last_30_days (daily bars), or last_365_days (12 monthly bars)."
        ),
    )
    agent_id: str | None = Field(
        default=None,
        min_length=1,
        description="When set, count sessions for this agent only. Otherwise all team agents.",
    )
