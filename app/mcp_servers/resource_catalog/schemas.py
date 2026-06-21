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

    Field caps close DoS surfaces flagged by the L4 prompt-injection
    suite: a malicious catalog entry (or a jailbroken LLM forging one)
    cannot inject megabyte-sized strings or unbounded lists into the
    pipeline.
    """

    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=50)
    url: str = Field(min_length=1, max_length=500)
    level: str | None = Field(default=None, max_length=50)
    language: str | None = Field(default=None, max_length=10)
    prerequisites: list[str] = Field(default_factory=list, max_length=50)
    geo_restrictions: list[str] = Field(default_factory=list, max_length=50)
    age_requirement: int | None = Field(default=None, ge=0, le=120)
    institution_requirement: str | None = Field(default=None, max_length=200)
    last_verified_free: str | None = Field(default=None, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
