"""Canonical mapping from extracted resume fields to candidate records."""

from __future__ import annotations

from typing import Any, Iterable

from models.candidate_record import CandidateRecord
from models.extracted_fields import ExtractedEducationItem, ExtractedExperienceItem, ExtractedFields
from utils.exceptions import CanonicalMappingError
from utils.logger import get_logger


LOGGER = get_logger(__name__)

CANONICAL_FIELD_NAMES: dict[str, str] = {
    "name": "full_name",
    "emails": "email_addresses",
    "phone_numbers": "phone_numbers",
    "skills": "skills",
    "education": "education",
    "experience": "experience",
    "organizations": "organizations",
    "locations": "locations",
    "urls": "urls",
}


class CanonicalCandidateMapper:
    """Map extracted resume fields into the canonical candidate record schema."""

    def map_one(self, extracted_fields: ExtractedFields) -> CandidateRecord:
        """Map one extracted resume payload into a canonical candidate record."""
        self._validate_extracted_fields(extracted_fields)

        canonical_payload = {
            "source_record_id": extracted_fields.record_id,
            "source_name": extracted_fields.source_name,
            "canonical_schema_version": "1.0",
            "full_name": extracted_fields.name,
            "email_addresses": list(extracted_fields.emails),
            "phone_numbers": list(extracted_fields.phone_numbers),
            "skills": list(extracted_fields.skills),
            "education": [self._map_education_item(item) for item in extracted_fields.education],
            "experience": [self._map_experience_item(item) for item in extracted_fields.experience],
            "organizations": list(extracted_fields.organizations),
            "locations": list(extracted_fields.locations),
            "urls": list(extracted_fields.urls),
            "sentences": list(extracted_fields.sentences),
        }

        candidate_record = CandidateRecord(
            record_id=extracted_fields.record_id,
            source=extracted_fields.source_metadata.model_copy(deep=True),
            raw_payload=canonical_payload,
            raw_text="\n".join(extracted_fields.sentences) if extracted_fields.sentences else None,
            tags=["canonical", "mapped_from_extracted_fields"],
        )

        LOGGER.info(
            "Mapped extracted fields to canonical candidate record record_id=%s source=%s",
            extracted_fields.record_id,
            extracted_fields.source_name,
        )
        return candidate_record

    def map_many(self, extracted_records: Iterable[ExtractedFields]) -> list[CandidateRecord]:
        """Map multiple extracted field payloads into canonical candidate records."""
        records = self._coerce_extracted_records(extracted_records)
        return [self.map_one(extracted_fields=record) for record in records]

    def _coerce_extracted_records(self, extracted_records: Iterable[ExtractedFields]) -> list[ExtractedFields]:
        """Validate the top-level extracted records input."""
        if extracted_records is None:
            raise CanonicalMappingError("extracted_records must not be None.")
        if isinstance(extracted_records, (str, bytes)):
            raise CanonicalMappingError("extracted_records must be an iterable of ExtractedFields objects.")

        try:
            records = list(extracted_records)
        except TypeError as exc:
            raise CanonicalMappingError(
                "extracted_records must be an iterable of ExtractedFields objects."
            ) from exc

        for record in records:
            self._validate_extracted_fields(record)

        return records

    def _validate_extracted_fields(self, extracted_fields: ExtractedFields) -> None:
        """Validate that the mapper received the expected extracted fields object."""
        if not isinstance(extracted_fields, ExtractedFields):
            raise CanonicalMappingError("Canonical mapping requires an ExtractedFields instance.")
        if not extracted_fields.record_id:
            raise CanonicalMappingError("ExtractedFields.record_id must not be empty.")
        if not extracted_fields.source_name:
            raise CanonicalMappingError("ExtractedFields.source_name must not be empty.")
        if extracted_fields.source_metadata.source_name != extracted_fields.source_name:
            raise CanonicalMappingError("ExtractedFields source metadata must match source_name.")

    def _map_education_item(self, item: ExtractedEducationItem) -> dict[str, Any]:
        """Map one extracted education item into the canonical field structure."""
        return {
            "raw_text": item.text,
            "institution_name": item.institution,
            "degree_name": item.degree,
            "field_of_study": item.field_of_study,
            "date_text": item.date_text,
        }

    def _map_experience_item(self, item: ExtractedExperienceItem) -> dict[str, Any]:
        """Map one extracted experience item into the canonical field structure."""
        return {
            "raw_text": item.text,
            "job_title": item.title,
            "organization_name": item.organization,
            "date_range_text": item.date_range_text,
        }


def map_extracted_fields(extracted_fields: ExtractedFields) -> CandidateRecord:
    """Convenience function for mapping one extracted payload."""
    return CanonicalCandidateMapper().map_one(extracted_fields)


def map_extracted_fields_batch(extracted_records: Iterable[ExtractedFields]) -> list[CandidateRecord]:
    """Convenience function for mapping multiple extracted payloads."""
    return CanonicalCandidateMapper().map_many(extracted_records)


__all__ = [
    "CANONICAL_FIELD_NAMES",
    "CanonicalCandidateMapper",
    "map_extracted_fields",
    "map_extracted_fields_batch",
]
