import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

ToolScalarType = Literal["string", "number", "integer", "boolean"]
ToolArrayItemType = Literal["string", "number", "integer", "boolean"]
ToolParameterType = Literal[
    "string", "number", "integer", "boolean", "enum", "array", "object"
]


def _validate_parameter_name(value: str) -> str:
    if not TOOL_NAME_PATTERN.match(value):
        raise ValueError(
            "Parameter name must start with a lowercase letter and contain only "
            "lowercase letters, numbers, and underscores."
        )
    return value


def _validate_enum_values(values: list[str]) -> list[str]:
    normalized = [item.strip() for item in values if item and item.strip()]
    if not normalized:
        raise ValueError("enum_values must contain at least one non-empty value.")
    if len(normalized) != len(set(normalized)):
        raise ValueError("enum_values must be unique.")
    return normalized


class ToolNestedParameterInput(BaseModel):
    """Parameter definition used inside an object-typed parameter (no nested objects)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    type: Literal["string", "number", "integer", "boolean", "enum", "array"]
    description: str = Field(..., min_length=1, max_length=1024)
    required: bool = False
    enum_values: list[str] | None = Field(default=None, max_length=50)
    items_type: ToolArrayItemType | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_parameter_name(value)

    @field_validator("enum_values")
    @classmethod
    def validate_enum_values_field(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return _validate_enum_values(value)

    @model_validator(mode="after")
    def validate_shape(self) -> "ToolNestedParameterInput":
        if self.type == "enum":
            if not self.enum_values:
                raise ValueError("enum_values is required when parameter type is enum.")
            if self.items_type is not None:
                raise ValueError("items_type is only allowed when parameter type is array.")
        elif self.type == "array":
            if self.items_type is None:
                raise ValueError("items_type is required when parameter type is array.")
            if self.enum_values is not None:
                raise ValueError("enum_values is only allowed when parameter type is enum.")
        else:
            if self.enum_values is not None:
                raise ValueError("enum_values is only allowed when parameter type is enum.")
            if self.items_type is not None:
                raise ValueError("items_type is only allowed when parameter type is array.")
        return self


class ToolParameterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    type: ToolParameterType
    description: str = Field(..., min_length=1, max_length=1024)
    required: bool = False
    enum_values: list[str] | None = Field(default=None, max_length=50)
    items_type: ToolArrayItemType | None = None
    properties: list[ToolNestedParameterInput] | None = Field(default=None, max_length=20)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_parameter_name(value)

    @field_validator("enum_values")
    @classmethod
    def validate_enum_values_field(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return _validate_enum_values(value)

    @model_validator(mode="after")
    def validate_shape(self) -> "ToolParameterInput":
        if self.type == "enum":
            if not self.enum_values:
                raise ValueError("enum_values is required when parameter type is enum.")
            if self.items_type is not None or self.properties is not None:
                raise ValueError("enum parameters cannot include items_type or properties.")
        elif self.type == "array":
            if self.items_type is None:
                raise ValueError("items_type is required when parameter type is array.")
            if self.enum_values is not None or self.properties is not None:
                raise ValueError("array parameters cannot include enum_values or properties.")
        elif self.type == "object":
            if not self.properties:
                raise ValueError("properties is required when parameter type is object.")
            names = [item.name for item in self.properties]
            if len(names) != len(set(names)):
                raise ValueError("Nested parameter names must be unique within an object parameter.")
            if self.enum_values is not None or self.items_type is not None:
                raise ValueError("object parameters cannot include enum_values or items_type.")
        else:
            if self.enum_values is not None or self.items_type is not None or self.properties is not None:
                raise ValueError(
                    f"{self.type} parameters cannot include enum_values, items_type, or properties."
                )
        return self


def build_parameter_property_schema(param: ToolParameterInput | ToolNestedParameterInput) -> dict[str, Any]:
    """Convert a parameter input model to an OpenAI JSON Schema property definition."""
    prop: dict[str, Any] = {"description": param.description}

    if param.type == "enum":
        prop["type"] = "string"
        prop["enum"] = param.enum_values
    elif param.type == "array":
        prop["type"] = "array"
        prop["items"] = {"type": param.items_type}
    elif param.type == "object":
        assert isinstance(param, ToolParameterInput)
        nested_properties: dict[str, Any] = {}
        nested_required: list[str] = []
        for nested in param.properties or []:
            nested_properties[nested.name] = build_parameter_property_schema(nested)
            if nested.required:
                nested_required.append(nested.name)
        prop["type"] = "object"
        prop["properties"] = nested_properties
        if nested_required:
            prop["required"] = nested_required
    else:
        prop["type"] = param.type

    return prop


def build_tool_parameters_schema(parameters: list[ToolParameterInput]) -> dict[str, Any]:
    """Build the root OpenAI function parameters object for a tool."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in parameters:
        properties[param.name] = build_parameter_property_schema(param)
        if param.required:
            required.append(param.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


class ToolAuthConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "api_key"] = "none"
    location: Literal["header", "query"] | None = None
    param_name: str | None = Field(default=None, max_length=128)
    token: str | None = Field(default=None, max_length=4096)
    token_prefix: Literal["Bearer", "none"] | None = "Bearer"

    @model_validator(mode="after")
    def validate_auth_fields(self) -> "ToolAuthConfigInput":
        if self.type == "none":
            return self

        if not self.location:
            raise ValueError("location is required when auth type is api_key.")
        if not self.param_name or not self.param_name.strip():
            raise ValueError("param_name is required when auth type is api_key.")
        if not self.token or not self.token.strip():
            raise ValueError("token is required when auth type is api_key.")

        if self.location == "query" and self.token_prefix not in (None, "none"):
            raise ValueError("token_prefix must be 'none' when auth location is query.")

        return self


class CreateToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=2048)
    api_url: str = Field(..., min_length=1, max_length=2048)
    http_method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    auth: ToolAuthConfigInput = Field(default_factory=lambda: ToolAuthConfigInput(type="none"))
    parameters: list[ToolParameterInput] = Field(default_factory=list, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        normalized = value.strip()
        if not TOOL_NAME_PATTERN.match(normalized):
            raise ValueError(
                "Tool name must start with a lowercase letter and contain only "
                "lowercase letters, numbers, and underscores."
            )
        return normalized

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name cannot be empty.")
        return normalized

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("api_url must start with http:// or https://.")
        return normalized

    @model_validator(mode="after")
    def validate_unique_parameter_names(self) -> "CreateToolRequest":
        names = [param.name for param in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("Parameter names must be unique within a tool.")
        return self


class UpdateToolAuthConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "api_key"] | None = None
    location: Literal["header", "query"] | None = None
    param_name: str | None = Field(default=None, max_length=128)
    token: str | None = Field(default=None, max_length=4096)
    token_prefix: Literal["Bearer", "none"] | None = None


class UpdateToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(..., min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=2048)
    api_url: str | None = Field(default=None, min_length=1, max_length=2048)
    http_method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    auth: UpdateToolAuthConfigInput | None = None
    parameters: list[ToolParameterInput] | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_tool_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not TOOL_NAME_PATTERN.match(normalized):
            raise ValueError(
                "Tool name must start with a lowercase letter and contain only "
                "lowercase letters, numbers, and underscores."
            )
        return normalized

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name cannot be empty.")
        return normalized

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("api_url must start with http:// or https://.")
        return normalized

    @model_validator(mode="after")
    def validate_unique_parameter_names(self) -> "UpdateToolRequest":
        if self.parameters is None:
            return self
        names = [param.name for param in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("Parameter names must be unique within a tool.")
        return self


class GetToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(..., min_length=1)


class DeleteToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(..., min_length=1)


class ListToolsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)
    include_inactive: bool = False
