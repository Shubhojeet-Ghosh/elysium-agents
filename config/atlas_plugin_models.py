from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.atlas_plugin_config import ATLAS_PLUGIN_CODE_MAX_CHARS


class CreatePluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_code: str = Field(..., min_length=1, max_length=ATLAS_PLUGIN_CODE_MAX_CHARS)

    @field_validator("python_code")
    @classmethod
    def strip_python_code(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("python_code cannot be empty.")
        return stripped


class UpdatePluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(..., min_length=1)
    python_code: str | None = Field(default=None, min_length=1, max_length=ATLAS_PLUGIN_CODE_MAX_CHARS)
    is_active: bool | None = None

    @field_validator("python_code")
    @classmethod
    def strip_python_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("python_code cannot be empty.")
        return stripped

    @model_validator(mode="after")
    def require_update_fields(self) -> "UpdatePluginRequest":
        if self.python_code is None and self.is_active is None:
            raise ValueError("Provide python_code and/or is_active to update.")
        return self


class GetPluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(..., min_length=1)


class DeletePluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(..., min_length=1)


class ListPluginsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)
    include_inactive: bool = False


class SetPluginSecretsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(..., min_length=1)
    secrets: dict[str, str | None] = Field(..., min_length=1)

    @field_validator("secrets")
    @classmethod
    def validate_secret_keys(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        if not value:
            raise ValueError("secrets must include at least one key.")
        for key in value:
            if not key or not key.strip():
                raise ValueError("Secret keys cannot be empty.")
        return value


class TestPluginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(..., min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
