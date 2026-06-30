"""Provenance builder for mastered candidate records."""

from __future__ import annotations

from typing import Any, Iterable

from models.master_candidate_record import MasterCandidateRecord, ProvenanceEntry
from utils.exceptions import ProvenanceError
from utils.logger import get_logger


LOGGER = get_logger(__name__)

SUPPORTED_METHODS = {
    "direct_extraction",
    "merged",
    "conflict_resolution",
    "default_value",
}


class ProvenanceBuilder:
    """Build and backfill provenance for mastered candidate records."""

    def build_one(self, master_record: MasterCandidateRecord) -> MasterCandidateRecord:
        """Return a master record with completed provenance metadata."""
        self._validate_master_record(master_record)
        provenance = list(master_record.provenance)
        existing_keys = {
            (entry.field_name, entry.source_record_id, entry.source_name, entry.method)
            for entry in provenance
        }

        for field_name, field_value in self._iter_master_fields(master_record):
            if self._has_provenance_for_field(provenance, field_name):
                continue
            if self._is_empty(field_value):
                entry = self._default_value_entry(field_name)
                key = (entry.field_name, entry.source_record_id, entry.source_name, entry.method)
                if key not in existing_keys:
                    provenance.append(entry)
                    existing_keys.add(key)
                continue

            entry = self._system_resolution_entry(field_name, field_value)
            key = (entry.field_name, entry.source_record_id, entry.source_name, entry.method)
            if key not in existing_keys:
                provenance.append(entry)
                existing_keys.add(key)

        updated_record = master_record.model_copy(update={"provenance": provenance})
        LOGGER.info(
            "Built provenance for master candidate %s with %s entries",
            updated_record.master_candidate_id,
            len(updated_record.provenance),
        )
        return updated_record

    def build_many(self, master_records: Iterable[MasterCandidateRecord]) -> list[MasterCandidateRecord]:
        """Build provenance for multiple master records."""
        records = self._coerce_master_records(master_records)
        return [self.build_one(record) for record in records]

    def _coerce_master_records(
        self,
        master_records: Iterable[MasterCandidateRecord],
    ) -> list[MasterCandidateRecord]:
        """Validate top-level provenance input."""
        if master_records is None:
            raise ProvenanceError("master_records must not be None.")
        if isinstance(master_records, (str, bytes)):
            raise ProvenanceError("master_records must be an iterable of MasterCandidateRecord objects.")

        try:
            records = list(master_records)
        except TypeError as exc:
            raise ProvenanceError(
                "master_records must be an iterable of MasterCandidateRecord objects."
            ) from exc

        for record in records:
            self._validate_master_record(record)
        return records

    def _validate_master_record(self, master_record: MasterCandidateRecord) -> None:
        """Validate a single master record and its provenance methods."""
        if not isinstance(master_record, MasterCandidateRecord):
            raise ProvenanceError("Provenance builder requires a MasterCandidateRecord instance.")
        for entry in master_record.provenance:
            if entry.method not in SUPPORTED_METHODS:
                raise ProvenanceError(f"Unsupported provenance method '{entry.method}'.")

    def _iter_master_fields(self, master_record: MasterCandidateRecord) -> list[tuple[str, Any]]:
        """Return the mastered fields that should have provenance coverage."""
        profile = master_record.canonical_profile
        return [
            ("full_name", profile.full_name),
            ("first_name", profile.first_name),
            ("last_name", profile.last_name),
            ("headline", profile.headline),
            ("summary", profile.summary),
            ("contact.email", profile.contact.email),
            ("contact.phone", profile.contact.phone),
            ("contact.alternate_emails", profile.contact.alternate_emails),
            ("contact.alternate_phones", profile.contact.alternate_phones),
            ("contact.linkedin_url", profile.contact.linkedin_url),
            ("location.city", profile.location.city),
            ("location.state_or_region", profile.location.state_or_region),
            ("location.country", profile.location.country),
            ("location.postal_code", profile.location.postal_code),
            ("location.raw_location", profile.location.raw_location),
            ("skills", profile.skills),
            ("work_experience", profile.work_experience),
            ("education", profile.education),
            ("certifications", profile.certifications),
            ("languages", profile.languages),
        ]

    def _has_provenance_for_field(self, provenance: list[ProvenanceEntry], field_name: str) -> bool:
        """Check whether a field already has provenance coverage."""
        return any(entry.field_name == field_name for entry in provenance)

    def _default_value_entry(self, field_name: str) -> ProvenanceEntry:
        """Create a default-value provenance entry for an empty mastered field."""
        return ProvenanceEntry(
            field_name=field_name,
            source_record_id="system",
            source_name="system",
            source_type="system",
            method="default_value",
            source_value=None,
        )

    def _system_resolution_entry(self, field_name: str, field_value: Any) -> ProvenanceEntry:
        """Create a fallback provenance entry when a mastered field lacks explicit source provenance."""
        return ProvenanceEntry(
            field_name=field_name,
            source_record_id="system",
            source_name="system",
            source_type="system",
            method="conflict_resolution",
            source_value=field_value,
        )

    def _is_empty(self, value: Any) -> bool:
        """Return whether a mastered field should be treated as empty."""
        if value is None:
            return True
        if isinstance(value, str):
            return value == ""
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) == 0
        return False


def build_provenance(master_record: MasterCandidateRecord) -> MasterCandidateRecord:
    """Convenience function for enriching one master record with provenance."""
    return ProvenanceBuilder().build_one(master_record)


def build_provenance_batch(
    master_records: Iterable[MasterCandidateRecord],
) -> list[MasterCandidateRecord]:
    """Convenience function for enriching multiple master records with provenance."""
    return ProvenanceBuilder().build_many(master_records)


__all__ = [
    "ProvenanceBuilder",
    "build_provenance",
    "build_provenance_batch",
]
