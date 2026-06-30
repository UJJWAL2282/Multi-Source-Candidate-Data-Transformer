"""Extracted raw fields from source documents."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from models.candidate_record import SourceMetadata


class ExtractedEducationItem(BaseModel):
    """Raw education evidence extracted from a resume."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(..., description="Original education text span extracted from the resume.")
    institution: str | None = Field(default=None, description="Institution name if identified.")
    degree: str | None = Field(default=None, description="Degree text if identified.")
    field_of_study: str | None = Field(default=None, description="Field of study text if identified.")
    date_text: str | None = Field(default=None, description="Raw date text associated with the education entry.")


class ExtractedExperienceItem(BaseModel):
    """Raw experience evidence extracted from a resume."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(..., description="Original experience text span extracted from the resume.")
    title: str | None = Field(default=None, description="Job title if identified.")
    organization: str | None = Field(default=None, description="Organization name if identified.")
    date_range_text: str | None = Field(default=None, description="Raw date range text if identified.")


class ExtractedFields(BaseModel):
    """Deterministic extracted fields from a source document."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

    record_id: str = Field(..., description="Source candidate record identifier.")
    source_name: str = Field(..., description="Source resume file name.")
    source_metadata: SourceMetadata = Field(
        ...,
        description="Original source metadata carried forward for provenance-safe canonical mapping.",
    )
    name: str | None = Field(default=None, description="Candidate name extracted from the resume.")
    emails: list[str] = Field(default_factory=list, description="Email addresses extracted from the resume.")
    phone_numbers: list[str] = Field(default_factory=list, description="Phone numbers extracted from the resume.")
    skills: list[str] = Field(default_factory=list, description="Skills matched from the static skill dictionary.")
    education: list[ExtractedEducationItem] = Field(
        default_factory=list,
        description="Education entries extracted from the resume.",
    )
    experience: list[ExtractedExperienceItem] = Field(
        default_factory=list,
        description="Experience entries extracted from the resume.",
    )
    organizations: list[str] = Field(
        default_factory=list,
        description="Organization names extracted from the resume.",
    )
    locations: list[str] = Field(default_factory=list, description="Location strings extracted from the resume.")
    urls: list[str] = Field(default_factory=list, description="URLs extracted from the resume.")
    sentences: list[str] = Field(
        default_factory=list,
        description="Sentence-segmented resume text used during deterministic extraction.",
    )

    def has_contact_details(self) -> bool:
        """Return whether contact details were extracted."""
        return bool(self.emails or self.phone_numbers)
