"""Raw source record models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class SourceType(str, Enum):
    """Supported upstream source types."""

    RECRUITER_CSV = "recruiter_csv"
    RESUME_PDF = "resume_pdf"
    RESUME_DOCX = "resume_docx"
    RESUME_TXT = "resume_txt"
    API = "api"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class SourceFileReference(BaseModel):
    """Metadata about a file-based source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    file_name: str = Field(..., description="Original file name provided by the source system.")
    file_path: str | None = Field(
        default=None,
        description="Optional relative or absolute file path used during ingestion.",
    )
    mime_type: str | None = Field(
        default=None,
        description="Detected or declared MIME type for the source file.",
    )
    checksum_sha256: str | None = Field(
        default=None,
        description="Optional SHA-256 checksum for verifying file integrity.",
    )


class SourceMetadata(BaseModel):
    """Operational metadata captured at ingestion time."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_name: str = Field(..., description="Human-readable source system or file name.")
    source_type: SourceType = Field(..., description="Normalized source type for this record.")
    external_id: str | None = Field(
        default=None,
        description="Optional upstream identifier if the source system provides one.",
    )
    batch_id: str | None = Field(
        default=None,
        description="Optional ingestion batch identifier for traceability.",
    )
    ingestion_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the record entered the system.",
    )
    source_url: HttpUrl | None = Field(
        default=None,
        description="Optional source URL for API or remote file-based records.",
    )
    file_reference: SourceFileReference | None = Field(
        default=None,
        description="Optional metadata for file-based sources.",
    )


class CandidateRecord(BaseModel):
    """Immutable raw candidate payload received from an upstream source."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    record_id: str = Field(
        default_factory=lambda: f"raw_{uuid4().hex}",
        description="Internal unique identifier for the raw candidate record.",
    )
    source: SourceMetadata = Field(
        ...,
        description="Normalized metadata describing the upstream source of the record.",
    )
    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured raw payload as received from the source system.",
    )
    raw_text: str | None = Field(
        default=None,
        description="Plain-text representation of the source content when available.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Optional non-authoritative labels attached during ingestion.",
    )

    @field_validator("raw_payload")
    @classmethod
    def validate_raw_payload_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Ensure the source record contains at least some useful content."""
        if not value:
            raise ValueError("raw_payload must contain at least one field.")
        return value

    def primary_source_label(self) -> str:
        """Return a compact label suitable for provenance displays."""
        return f"{self.source.source_type.value}:{self.source.source_name}"

