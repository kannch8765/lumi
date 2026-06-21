"""Pydantic schemas for the resource-catalog MCP server.

These schemas define the tool-input and tool-output contracts for the
resource-catalog MCP server. They are the single source of truth for
what data crosses the MCP boundary (ARCHITECTURE.md §Two-Layer model —
Pydantic schemas have dual citizenship in Layer A L1 + Layer B L1).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchInput(BaseModel):
    """Input for the search_catalog tool."""

    query: str = Field(min_length=1)
    types: list[str] | None = None
    language: str | None = None
    max_results: int = Field(default=10, ge=1, le=50)


class GetByIdInput(BaseModel):
    """Input for the get_resource_by_id tool."""

    resource_id: str = Field(min_length=1)


class ListByTypeInput(BaseModel):
    """Input for the list_by_type tool."""

    resource_type: str = Field(min_length=1)
    max_results: int = Field(default=20, ge=1, le=50)


class ResourceOutput(BaseModel):
    """Output schema for a single catalog resource.

    All optional fields default to safe empty values so callers always
    receive a complete record even when the catalog entry omits them.
    """

    id: str
    name: str
    type: str
    url: str
    level: str | None = None
    language: str | None = None
    prerequisites: list[str] = Field(default_factory=list)
    geo_restrictions: list[str] = Field(default_factory=list)
    age_requirement: int | None = None
    institution_requirement: str | None = None
    last_verified_free: str | None = None
    tags: list[str] = Field(default_factory=list)
    description: str
