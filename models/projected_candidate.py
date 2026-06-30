"""Output projection models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectedCandidate(BaseModel):
    """Final candidate payload prepared for an output contract."""

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    candidate_id: str = Field(..., description="Output-facing candidate identifier.")
    full_name: str | None = Field(default=None, description="Projected full candidate name.")
    email: str | None = Field(default=None, description="Projected primary email address.")
    phone: str | None = Field(default=None, description="Projected primary phone number.")
    current_title: str | None = Field(default=None, description="Projected current job title.")
    current_company: str | None = Field(default=None, description="Projected current employer name.")
    location: str | None = Field(default=None, description="Projected candidate location string.")
    skills: list[str] = Field(default_factory=list, description="Projected skill names.")
    confidence_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Projected overall confidence score.",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional output attributes defined by configuration.",
    )

    def to_output_dict(self) -> dict[str, Any]:
        """Return a stable dictionary representation for downstream serialization."""
        return self.model_dump(mode="json", exclude_none=True)
