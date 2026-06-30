"""Mastered candidate aggregate models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.identity_group import MatchEvidence
from models.normalized_candidate_record import NormalizedCandidateRecord


class ProvenanceEntry(BaseModel):
    """Traceability record linking mastered fields back to source candidates."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    field_name: str = Field(..., description="Master field populated from a source record.")
    source_record_id: str = Field(..., description="Raw or normalized source record identifier.")
    source_name: str = Field(..., description="Human-readable name of the contributing source.")
    source_type: str = Field(..., description="Normalized source type for the contributing record.")
    method: str = Field(
        ...,
        description="Method used to populate the mastered field.",
    )
    source_value: Any = Field(..., description="Original source value that informed the mastered field.")


class ConfidenceBreakdown(BaseModel):
    """Explainable confidence scores for mastering decisions."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    overall_score: float = Field(
        ...,
        ge=0,
        le=1,
        description="Overall confidence score for the mastered candidate record.",
    )
    skill_confidence: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence contribution based on extracted and merged skills.",
    )
    extraction_reliability_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence contribution based on provenance extraction methods.",
    )
    source_agreement_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence contribution based on agreement between contributing sources.",
    )
    identity_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence that grouped source records belong to the same person.",
    )
    completeness_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence contribution based on record completeness.",
    )
    consistency_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence contribution based on cross-source consistency.",
    )
    conflict_outcome_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence contribution based on how conflicts were resolved.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Short explanatory notes supporting the confidence assessment.",
    )


class MasterCandidateRecord(BaseModel):
    """Resolved golden-record representation of a candidate."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    master_candidate_id: str = Field(
        ...,
        description="Stable internal identifier for the mastered candidate record.",
    )
    identity_group_id: str = Field(
        ...,
        description="Identity group identifier used to produce this mastered record.",
    )
    canonical_profile: NormalizedCandidateRecord = Field(
        ...,
        description="Resolved canonical profile selected for downstream consumption.",
    )
    provenance: list[ProvenanceEntry] = Field(
        default_factory=list,
        description="Field-level traceability entries for the mastered candidate.",
    )
    confidence: ConfidenceBreakdown = Field(
        ...,
        description="Explainable confidence assessment for the mastered profile.",
    )
    match_evidence: list[MatchEvidence] = Field(
        default_factory=list,
        description="Identity matching evidence retained from the grouping phase.",
    )
    merged_record_ids: list[str] = Field(
        default_factory=list,
        description="Normalized record identifiers merged into this mastered profile.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the master candidate record was created.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the master candidate record was last updated.",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible mastered attributes not yet promoted to first-class fields.",
    )

    @field_validator("merged_record_ids")
    @classmethod
    def validate_merged_record_ids(cls, value: list[str]) -> list[str]:
        """Prevent duplicate merged identifiers in the mastered record."""
        if len(value) != len(set(value)):
            raise ValueError("merged_record_ids must not contain duplicates.")
        return value

    def is_high_confidence(self, threshold: float = 0.8) -> bool:
        """Return whether the master candidate exceeds the configured threshold."""
        return self.confidence.overall_score >= threshold

    def source_record_count(self) -> int:
        """Return the number of merged normalized records."""
        return len(self.merged_record_ids)
