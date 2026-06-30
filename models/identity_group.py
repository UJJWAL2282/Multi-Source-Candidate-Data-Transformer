"""Identity resolution aggregate models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.normalized_candidate_record import NormalizedCandidateRecord


class MatchEvidence(BaseModel):
    """Evidence supporting a candidate identity match."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rule_name: str = Field(..., description="Name of the identity resolution rule that matched.")
    matched_fields: list[str] = Field(
        default_factory=list,
        description="List of normalized fields that contributed to the match decision.",
    )
    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Confidence assigned to this individual match rule outcome.",
    )
    notes: str | None = Field(
        default=None,
        description="Optional explanation for debugging or audit purposes.",
    )


class IdentityGroup(BaseModel):
    """Cluster of normalized records believed to represent the same person."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    group_id: str = Field(..., description="Internal identifier for the identity group.")
    group_key: str = Field(
        ...,
        description="Deterministic grouping key used during identity resolution.",
    )
    records: list[NormalizedCandidateRecord] = Field(
        default_factory=list,
        description="Normalized candidate records belonging to this identity cluster.",
    )
    match_evidence: list[MatchEvidence] = Field(
        default_factory=list,
        description="Evidence collected while grouping records into the cluster.",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible aggregate metadata related to the identity cluster.",
    )

    @field_validator("records")
    @classmethod
    def validate_records_not_empty(
        cls,
        value: list[NormalizedCandidateRecord],
    ) -> list[NormalizedCandidateRecord]:
        """Require at least one normalized record in each identity group."""
        if not value:
            raise ValueError("records must contain at least one normalized candidate record.")
        return value

    def record_ids(self) -> list[str]:
        """Return normalized record identifiers in stable order."""
        return [record.normalized_id for record in self.records]

    def size(self) -> int:
        """Return the number of grouped records."""
        return len(self.records)
