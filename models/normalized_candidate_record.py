"""Canonical normalized candidate models."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    computed_field,
    field_validator,
)


EmailAddress = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$",
        strip_whitespace=True,
    ),
]


class ContactInfo(BaseModel):
    """Normalized candidate contact attributes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailAddress | None = Field(default=None, description="Primary normalized email address.")
    phone: str | None = Field(default=None, description="Normalized primary phone number.")
    alternate_emails: list[EmailAddress] = Field(
        default_factory=list,
        description="Additional normalized email addresses discovered across sources.",
    )
    alternate_phones: list[str] = Field(
        default_factory=list,
        description="Additional normalized phone numbers discovered across sources.",
    )
    linkedin_url: HttpUrl | None = Field(
        default=None,
        description="Normalized LinkedIn profile URL when available.",
    )

    @field_validator("phone")
    @classmethod
    def validate_primary_phone(cls, value: str | None) -> str | None:
        """Ensure phone values are normalized E.164-compatible strings."""
        if value is None:
            return value
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) < 7:
            raise ValueError("phone must contain at least 7 digits after normalization.")
        return f"+{digits}" if value.startswith("+") else digits

    @field_validator("alternate_phones")
    @classmethod
    def validate_alternate_phones(cls, values: list[str]) -> list[str]:
        """Normalize alternate phone values to E.164-compatible strings."""
        normalized: list[str] = []
        for value in values:
            digits = "".join(character for character in value if character.isdigit())
            if len(digits) < 7:
                raise ValueError("alternate phone values must contain at least 7 digits.")
            normalized.append(f"+{digits}" if value.startswith("+") else digits)
        return normalized


class LocationInfo(BaseModel):
    """Normalized geographic information for the candidate."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    city: str | None = Field(default=None, description="Candidate city of residence.")
    state_or_region: str | None = Field(default=None, description="Candidate state or region.")
    country: str | None = Field(default=None, description="Candidate country.")
    postal_code: str | None = Field(default=None, description="Candidate postal code.")
    raw_location: str | None = Field(
        default=None,
        description="Original location text retained for auditability.",
    )


class EmploymentRecord(BaseModel):
    """Single normalized employment entry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_name: str = Field(..., description="Employer name.")
    title: str | None = Field(default=None, description="Job title held at the employer.")
    start_date: date | None = Field(default=None, description="Employment start date when known.")
    end_date: date | None = Field(default=None, description="Employment end date when known.")
    is_current: bool = Field(default=False, description="Whether this role is current.")
    description: str | None = Field(
        default=None,
        description="Normalized summary of responsibilities or achievements.",
    )


class EducationRecord(BaseModel):
    """Single normalized education entry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    institution_name: str = Field(..., description="Educational institution name.")
    degree: str | None = Field(default=None, description="Degree earned or pursued.")
    field_of_study: str | None = Field(default=None, description="Primary field of study.")
    graduation_date: date | None = Field(default=None, description="Graduation date if known.")


class SkillRecord(BaseModel):
    """Normalized skill signal with optional evidence."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., description="Normalized skill name.")
    category: str | None = Field(default=None, description="Optional skill category or taxonomy node.")
    years_of_experience: float | None = Field(
        default=None,
        ge=0,
        description="Estimated years of experience using this skill.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Short evidence snippets or source hints supporting the skill extraction.",
    )


class NormalizedCandidateRecord(BaseModel):
    """Canonical candidate representation after extraction and normalization."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    normalized_id: str = Field(
        ...,
        description="Internal identifier for the canonical normalized candidate record.",
    )
    full_name: str | None = Field(default=None, description="Normalized full candidate name.")
    first_name: str | None = Field(default=None, description="Normalized first name.")
    last_name: str | None = Field(default=None, description="Normalized last name.")
    headline: str | None = Field(
        default=None,
        description="Short professional headline or current role summary.",
    )
    summary: str | None = Field(
        default=None,
        description="Normalized free-text profile summary.",
    )
    contact: ContactInfo = Field(
        default_factory=ContactInfo,
        description="Normalized contact information for the candidate.",
    )
    location: LocationInfo = Field(
        default_factory=LocationInfo,
        description="Normalized location information for the candidate.",
    )
    skills: list[SkillRecord] = Field(
        default_factory=list,
        description="Normalized candidate skills.",
    )
    work_experience: list[EmploymentRecord] = Field(
        default_factory=list,
        description="Normalized employment history.",
    )
    education: list[EducationRecord] = Field(
        default_factory=list,
        description="Normalized education history.",
    )
    certifications: list[str] = Field(
        default_factory=list,
        description="Normalized certification names.",
    )
    languages: list[str] = Field(
        default_factory=list,
        description="Languages reported or inferred for the candidate.",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible normalized attributes not yet promoted to first-class fields.",
    )

    @computed_field(return_type=str | None)
    @property
    def primary_email(self) -> str | None:
        """Expose the primary email directly for convenience."""
        return str(self.contact.email) if self.contact.email is not None else None

    def primary_identifier(self) -> str | None:
        """Return the strongest normalized identifier available for matching."""
        if self.contact.email is not None:
            return str(self.contact.email).lower()
        if self.contact.phone is not None:
            return self.contact.phone
        return self.full_name

    def has_minimum_identity_data(self) -> bool:
        """Check whether the record contains enough identity data for grouping."""
        return any([self.full_name, self.contact.email, self.contact.phone])
