"""Conflict resolution and master candidate construction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from models.identity_group import IdentityGroup
from models.master_candidate_record import ConfidenceBreakdown, MasterCandidateRecord, ProvenanceEntry
from models.normalized_candidate_record import (
    ContactInfo,
    EducationRecord,
    EmploymentRecord,
    LocationInfo,
    NormalizedCandidateRecord,
    SkillRecord,
)
from utils.exceptions import ConflictResolutionError
from utils.logger import get_logger


LOGGER = get_logger(__name__)


class ConflictResolver:
    """Resolve field-level conflicts inside deterministic identity groups."""

    def resolve_one(self, identity_group: IdentityGroup) -> MasterCandidateRecord:
        """Resolve one identity group into a master candidate record."""
        self._validate_identity_group(identity_group)
        ordered_records = self._order_records_by_priority(identity_group.records)
        provenance: list[ProvenanceEntry] = []
        multi_source_group = len(ordered_records) > 1

        full_name = self._pick_first_value(ordered_records, "full_name", provenance, multi_source_group=multi_source_group)
        first_name = self._pick_first_value(ordered_records, "first_name", provenance, multi_source_group=multi_source_group)
        last_name = self._pick_first_value(ordered_records, "last_name", provenance, multi_source_group=multi_source_group)
        headline = self._pick_first_value(
            ordered_records,
            "headline",
            provenance,
            field_name="headline",
            multi_source_group=multi_source_group,
        )
        summary = self._pick_first_value(ordered_records, "summary", provenance, multi_source_group=multi_source_group)

        emails = self._merge_unique_values(ordered_records, self._email_values, "contact.email", provenance)
        phones = self._merge_unique_values(ordered_records, self._phone_values, "contact.phone", provenance)
        skills = self._merge_skills(ordered_records, provenance)
        education = self._merge_education(ordered_records, provenance)
        experience = self._merge_experience(ordered_records, provenance)
        certifications = self._merge_unique_scalar_lists(ordered_records, "certifications", provenance)
        languages = self._merge_unique_scalar_lists(ordered_records, "languages", provenance)
        location = self._merge_location(ordered_records, provenance)
        attributes = self._merge_attributes(ordered_records, provenance)

        canonical_profile = NormalizedCandidateRecord(
            normalized_id=self._master_normalized_id(identity_group),
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            headline=headline,
            summary=summary,
            contact=ContactInfo(
                email=emails[0] if emails else None,
                phone=phones[0] if phones else None,
                alternate_emails=emails[1:],
                alternate_phones=phones[1:],
                linkedin_url=self._pick_linkedin_url(
                    ordered_records,
                    provenance,
                    multi_source_group=multi_source_group,
                ),
            ),
            location=location,
            skills=skills,
            work_experience=experience,
            education=education,
            certifications=certifications,
            languages=languages,
            attributes=attributes,
        )

        master_record = MasterCandidateRecord(
            master_candidate_id=self._master_candidate_id(identity_group),
            identity_group_id=identity_group.group_id,
            canonical_profile=canonical_profile,
            provenance=provenance,
            confidence=self._initial_confidence(),
            match_evidence=list(identity_group.match_evidence),
            merged_record_ids=identity_group.record_ids(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            attributes={
                "resolution_status": identity_group.attributes.get("resolution_status"),
                "resolution_rule": identity_group.attributes.get("resolution_rule"),
                "group_size": identity_group.size(),
            },
        )

        LOGGER.info(
            "Resolved identity group %s into master candidate %s",
            identity_group.group_id,
            master_record.master_candidate_id,
        )
        return master_record

    def resolve_many(self, identity_groups: Iterable[IdentityGroup]) -> list[MasterCandidateRecord]:
        """Resolve multiple identity groups into master candidate records."""
        groups = self._coerce_identity_groups(identity_groups)
        return [self.resolve_one(group) for group in groups]

    def _coerce_identity_groups(self, identity_groups: Iterable[IdentityGroup]) -> list[IdentityGroup]:
        """Validate top-level conflict resolution input."""
        if identity_groups is None:
            raise ConflictResolutionError("identity_groups must not be None.")
        if isinstance(identity_groups, (str, bytes)):
            raise ConflictResolutionError("identity_groups must be an iterable of IdentityGroup objects.")

        try:
            groups = list(identity_groups)
        except TypeError as exc:
            raise ConflictResolutionError(
                "identity_groups must be an iterable of IdentityGroup objects."
            ) from exc

        for group in groups:
            self._validate_identity_group(group)

        return groups

    def _validate_identity_group(self, identity_group: IdentityGroup) -> None:
        """Validate that the resolver received an identity group."""
        if not isinstance(identity_group, IdentityGroup):
            raise ConflictResolutionError("Conflict resolution requires an IdentityGroup instance.")
        if not identity_group.records:
            raise ConflictResolutionError("IdentityGroup.records must not be empty.")

    def _order_records_by_priority(
        self,
        records: list[NormalizedCandidateRecord],
    ) -> list[NormalizedCandidateRecord]:
        """Apply deterministic source-priority ordering."""
        return sorted(
            records,
            key=lambda record: (
                self._source_priority(record),
                record.normalized_id,
            ),
        )

    def _source_priority(self, record: NormalizedCandidateRecord) -> int:
        """Return a deterministic source priority for conflict selection."""
        priority = record.attributes.get("source_priority")
        if isinstance(priority, int):
            return priority
        return 100

    def _pick_first_value(
        self,
        records: list[NormalizedCandidateRecord],
        attribute_name: str,
        provenance: list[ProvenanceEntry],
        field_name: str | None = None,
        multi_source_group: bool = False,
    ) -> str | None:
        """Pick the first non-empty scalar value by source priority."""
        output_field = field_name or attribute_name
        for record in records:
            value = getattr(record, attribute_name, None)
            if isinstance(value, str) and value:
                method = "conflict_resolution" if multi_source_group else "direct_extraction"
                provenance.append(self._provenance_entry(output_field, record, value, method=method))
                return value
        return None

    def _pick_linkedin_url(
        self,
        records: list[NormalizedCandidateRecord],
        provenance: list[ProvenanceEntry],
        multi_source_group: bool = False,
    ):
        """Pick the first LinkedIn URL by source priority."""
        for record in records:
            value = record.contact.linkedin_url
            if value:
                method = "conflict_resolution" if multi_source_group else "direct_extraction"
                provenance.append(
                    self._provenance_entry("contact.linkedin_url", record, str(value), method=method)
                )
                return value
        return None

    def _email_values(self, record: NormalizedCandidateRecord) -> list[str]:
        """Return all email values from a normalized record."""
        emails: list[str] = []
        if record.contact.email:
            emails.append(str(record.contact.email))
        emails.extend(str(email) for email in record.contact.alternate_emails)
        return emails

    def _phone_values(self, record: NormalizedCandidateRecord) -> list[str]:
        """Return all phone values from a normalized record."""
        phones: list[str] = []
        if record.contact.phone:
            phones.append(record.contact.phone)
        phones.extend(record.contact.alternate_phones)
        return phones

    def _merge_unique_values(
        self,
        records: list[NormalizedCandidateRecord],
        value_getter,
        field_name: str,
        provenance: list[ProvenanceEntry],
    ) -> list[str]:
        """Merge and deduplicate scalar values while preserving provenance."""
        seen: set[str] = set()
        merged: list[str] = []
        for record in records:
            for value in value_getter(record):
                key = value.casefold()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(value)
                provenance.append(self._provenance_entry(field_name, record, value, method="merged"))
        return merged

    def _merge_unique_scalar_lists(
        self,
        records: list[NormalizedCandidateRecord],
        attribute_name: str,
        provenance: list[ProvenanceEntry],
    ) -> list[str]:
        """Merge and deduplicate scalar arrays."""
        seen: set[str] = set()
        merged: list[str] = []
        for record in records:
            values = getattr(record, attribute_name, [])
            for value in values:
                key = value.casefold()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(value)
                provenance.append(self._provenance_entry(attribute_name, record, value, method="merged"))
        return merged

    def _merge_skills(
        self,
        records: list[NormalizedCandidateRecord],
        provenance: list[ProvenanceEntry],
    ) -> list[SkillRecord]:
        """Merge skill arrays by union."""
        seen: set[str] = set()
        merged: list[SkillRecord] = []
        for record in records:
            for skill in record.skills:
                key = skill.name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(skill)
                provenance.append(
                    self._provenance_entry("skills", record, skill.model_dump(mode="json"), method="merged")
                )
        return merged

    def _merge_experience(
        self,
        records: list[NormalizedCandidateRecord],
        provenance: list[ProvenanceEntry],
    ) -> list[EmploymentRecord]:
        """Merge experience entries by unique company-title-date tuple."""
        seen: set[tuple[Any, ...]] = set()
        merged: list[EmploymentRecord] = []
        for record in records:
            for item in record.work_experience:
                key = (
                    item.company_name.casefold(),
                    (item.title or "").casefold(),
                    item.start_date.isoformat() if item.start_date else "",
                    item.end_date.isoformat() if item.end_date else "",
                    item.is_current,
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                provenance.append(
                    self._provenance_entry("work_experience", record, item.model_dump(mode="json"), method="merged")
                )
        return merged

    def _merge_education(
        self,
        records: list[NormalizedCandidateRecord],
        provenance: list[ProvenanceEntry],
    ) -> list[EducationRecord]:
        """Merge education entries by unique institution-degree-date tuple."""
        seen: set[tuple[Any, ...]] = set()
        merged: list[EducationRecord] = []
        for record in records:
            for item in record.education:
                key = (
                    item.institution_name.casefold(),
                    (item.degree or "").casefold(),
                    item.graduation_date.isoformat() if item.graduation_date else "",
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                provenance.append(
                    self._provenance_entry("education", record, item.model_dump(mode="json"), method="merged")
                )
        return merged

    def _merge_location(
        self,
        records: list[NormalizedCandidateRecord],
        provenance: list[ProvenanceEntry],
    ) -> LocationInfo:
        """Populate missing location fields from source-priority records."""
        city = None
        state_or_region = None
        country = None
        postal_code = None
        raw_location = None

        for record in records:
            location = record.location
            if city is None and location.city:
                city = location.city
                provenance.append(
                    self._provenance_entry("location.city", record, city, method=self._selection_method(records))
                )
            if state_or_region is None and location.state_or_region:
                state_or_region = location.state_or_region
                provenance.append(
                    self._provenance_entry(
                        "location.state_or_region",
                        record,
                        state_or_region,
                        method=self._selection_method(records),
                    )
                )
            if country is None and location.country:
                country = location.country
                provenance.append(
                    self._provenance_entry("location.country", record, country, method=self._selection_method(records))
                )
            if postal_code is None and location.postal_code:
                postal_code = location.postal_code
                provenance.append(
                    self._provenance_entry(
                        "location.postal_code",
                        record,
                        postal_code,
                        method=self._selection_method(records),
                    )
                )
            if raw_location is None and location.raw_location:
                raw_location = location.raw_location
                provenance.append(
                    self._provenance_entry(
                        "location.raw_location",
                        record,
                        raw_location,
                        method=self._selection_method(records),
                    )
                )

        return LocationInfo(
            city=city,
            state_or_region=state_or_region,
            country=country,
            postal_code=postal_code,
            raw_location=raw_location,
        )

    def _merge_attributes(
        self,
        records: list[NormalizedCandidateRecord],
        provenance: list[ProvenanceEntry],
    ) -> dict[str, Any]:
        """Merge residual attributes deterministically, preserving unique arrays."""
        merged: dict[str, Any] = {}
        for record in records:
            for key, value in record.attributes.items():
                if key in {"source_record_id", "source_name", "source_type", "source_priority"}:
                    continue
                if key not in merged:
                    merged[key] = value
                    provenance.append(
                        self._provenance_entry(
                            f"attributes.{key}",
                            record,
                            value,
                            method=self._selection_method(records),
                        )
                    )
                    continue
                if isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = self._merge_attribute_lists(merged[key], value)
                elif merged[key] in (None, "", []):
                    merged[key] = value
        return merged

    def _merge_attribute_lists(self, left: list[Any], right: list[Any]) -> list[Any]:
        """Merge attribute lists without duplicating values."""
        merged = list(left)
        for value in right:
            if value not in merged:
                merged.append(value)
        return merged

    def _provenance_entry(
        self,
        field_name: str,
        record: NormalizedCandidateRecord,
        source_value: Any,
        method: str,
    ) -> ProvenanceEntry:
        """Build one provenance entry from a normalized source record."""
        return ProvenanceEntry(
            field_name=field_name,
            source_record_id=str(record.attributes.get("source_record_id", record.normalized_id)),
            source_name=str(record.attributes.get("source_name", record.normalized_id)),
            source_type=str(record.attributes.get("source_type", "unknown")),
            method=method,
            source_value=source_value,
        )

    def _selection_method(self, records: list[NormalizedCandidateRecord]) -> str:
        """Return the deterministic provenance method for first-value population."""
        return "conflict_resolution" if len(records) > 1 else "direct_extraction"

    def _initial_confidence(self) -> ConfidenceBreakdown:
        """Return a placeholder confidence object for later assessment."""
        return ConfidenceBreakdown(
            overall_score=0.0,
            skill_confidence=0.0,
            extraction_reliability_score=0.0,
            source_agreement_score=0.0,
            identity_score=0.0,
            completeness_score=0.0,
            consistency_score=0.0,
            conflict_outcome_score=0.0,
            notes=["Confidence assessment pending standalone scoring stage."],
        )

    def _master_candidate_id(self, identity_group: IdentityGroup) -> str:
        """Build a stable master candidate identifier."""
        return f"master::{identity_group.group_id}"

    def _master_normalized_id(self, identity_group: IdentityGroup) -> str:
        """Build the canonical profile identifier for the mastered record."""
        return f"master_profile::{identity_group.group_id}"


def resolve_conflicts(identity_group: IdentityGroup) -> MasterCandidateRecord:
    """Convenience function for resolving one identity group."""
    return ConflictResolver().resolve_one(identity_group)


def resolve_conflicts_batch(identity_groups: Iterable[IdentityGroup]) -> list[MasterCandidateRecord]:
    """Convenience function for resolving multiple identity groups."""
    return ConflictResolver().resolve_many(identity_groups)


__all__ = [
    "ConflictResolver",
    "resolve_conflicts",
    "resolve_conflicts_batch",
]
