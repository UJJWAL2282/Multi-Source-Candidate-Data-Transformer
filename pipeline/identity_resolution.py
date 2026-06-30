"""Deterministic identity resolution for normalized candidate records."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from models.identity_group import IdentityGroup, MatchEvidence
from models.normalized_candidate_record import NormalizedCandidateRecord
from utils.exceptions import IdentityResolutionError
from utils.logger import get_logger


LOGGER = get_logger(__name__)


class IdentityResolver:
    """Resolve normalized candidate records into deterministic identity groups."""

    def resolve_many(self, records: Iterable[NormalizedCandidateRecord]) -> list[IdentityGroup]:
        """Resolve multiple normalized candidate records into identity groups."""
        normalized_records = self._coerce_records(records)
        groups: list[IdentityGroup] = []
        assigned_ids: set[str] = set()

        email_groups = self._bucket_records(normalized_records, self._email_key)
        groups.extend(self._build_rule_groups(email_groups, assigned_ids, "email_match", ["contact.email"]))

        phone_groups = self._bucket_records(self._unassigned(normalized_records, assigned_ids), self._phone_key)
        groups.extend(self._build_rule_groups(phone_groups, assigned_ids, "phone_match", ["contact.phone"]))

        name_location_groups = self._bucket_records(
            self._unassigned(normalized_records, assigned_ids),
            self._name_location_key,
        )
        groups.extend(
            self._build_rule_groups(
                name_location_groups,
                assigned_ids,
                "name_location_match",
                ["full_name", "location.raw_location"],
            )
        )

        remaining_records = self._unassigned(normalized_records, assigned_ids)
        ambiguous_name_groups = self._bucket_records(remaining_records, self._name_key)
        groups.extend(self._build_ambiguous_groups(ambiguous_name_groups, assigned_ids))

        final_remaining = self._unassigned(normalized_records, assigned_ids)
        groups.extend(self._build_no_match_groups(final_remaining))

        LOGGER.info(
            "Resolved %s normalized records into %s identity groups",
            len(normalized_records),
            len(groups),
        )
        return groups

    def _coerce_records(self, records: Iterable[NormalizedCandidateRecord]) -> list[NormalizedCandidateRecord]:
        """Validate top-level identity resolution input."""
        if records is None:
            raise IdentityResolutionError("records must not be None.")
        if isinstance(records, (str, bytes)):
            raise IdentityResolutionError("records must be an iterable of NormalizedCandidateRecord objects.")

        try:
            normalized_records = list(records)
        except TypeError as exc:
            raise IdentityResolutionError(
                "records must be an iterable of NormalizedCandidateRecord objects."
            ) from exc

        for record in normalized_records:
            if not isinstance(record, NormalizedCandidateRecord):
                raise IdentityResolutionError(
                    "All items in records must be NormalizedCandidateRecord instances."
                )

        return normalized_records

    def _bucket_records(
        self,
        records: Iterable[NormalizedCandidateRecord],
        key_builder,
    ) -> dict[str, list[NormalizedCandidateRecord]]:
        """Bucket records by a deterministic identity key."""
        buckets: dict[str, list[NormalizedCandidateRecord]] = defaultdict(list)
        for record in records:
            key = key_builder(record)
            if key is None:
                continue
            buckets[key].append(record)
        return dict(buckets)

    def _build_rule_groups(
        self,
        buckets: dict[str, list[NormalizedCandidateRecord]],
        assigned_ids: set[str],
        rule_name: str,
        matched_fields: list[str],
    ) -> list[IdentityGroup]:
        """Build deterministic multi-record groups for a specific rule."""
        groups: list[IdentityGroup] = []
        for bucket_key in sorted(buckets):
            bucket_records = [record for record in buckets[bucket_key] if record.normalized_id not in assigned_ids]
            if len(bucket_records) < 2:
                continue

            for record in bucket_records:
                assigned_ids.add(record.normalized_id)

            groups.append(
                IdentityGroup(
                    group_id=self._group_id(rule_name, bucket_key),
                    group_key=bucket_key,
                    records=bucket_records,
                    match_evidence=[
                        MatchEvidence(
                            rule_name=rule_name,
                            matched_fields=matched_fields,
                            confidence=1.0,
                            notes=f"Exact deterministic match on {', '.join(matched_fields)}.",
                        )
                    ],
                    attributes={
                        "resolution_status": "matched",
                        "resolution_rule": rule_name,
                    },
                )
            )
        return groups

    def _build_ambiguous_groups(
        self,
        buckets: dict[str, list[NormalizedCandidateRecord]],
        assigned_ids: set[str],
    ) -> list[IdentityGroup]:
        """Build singleton groups for ambiguous same-name records."""
        groups: list[IdentityGroup] = []
        for bucket_key in sorted(buckets):
            bucket_records = [record for record in buckets[bucket_key] if record.normalized_id not in assigned_ids]
            if len(bucket_records) < 2:
                continue

            for record in bucket_records:
                assigned_ids.add(record.normalized_id)
                groups.append(
                    IdentityGroup(
                        group_id=self._group_id("ambiguous", record.normalized_id),
                        group_key=f"ambiguous::{bucket_key}",
                        records=[record],
                        match_evidence=[
                            MatchEvidence(
                                rule_name="ambiguous",
                                matched_fields=["full_name"],
                                confidence=1.0,
                                notes="Same normalized name appears multiple times without an exact email, phone, or name+location match.",
                            )
                        ],
                        attributes={
                            "resolution_status": "ambiguous",
                            "resolution_rule": "ambiguous",
                            "ambiguous_key": bucket_key,
                        },
                    )
                )
        return groups

    def _build_no_match_groups(self, records: list[NormalizedCandidateRecord]) -> list[IdentityGroup]:
        """Build singleton groups for records with no deterministic match."""
        groups: list[IdentityGroup] = []
        for record in records:
            groups.append(
                IdentityGroup(
                    group_id=self._group_id("no_match", record.normalized_id),
                    group_key=f"no_match::{record.normalized_id}",
                    records=[record],
                    match_evidence=[
                        MatchEvidence(
                            rule_name="no_match",
                            matched_fields=[],
                            confidence=1.0,
                            notes="No deterministic identity rule matched this record to any other record.",
                        )
                    ],
                    attributes={
                        "resolution_status": "no_match",
                        "resolution_rule": "no_match",
                    },
                )
            )
        return groups

    def _unassigned(
        self,
        records: list[NormalizedCandidateRecord],
        assigned_ids: set[str],
    ) -> list[NormalizedCandidateRecord]:
        """Return records not yet assigned to an identity group."""
        return [record for record in records if record.normalized_id not in assigned_ids]

    def _email_key(self, record: NormalizedCandidateRecord) -> str | None:
        """Build an exact email match key."""
        return record.primary_email.casefold() if record.primary_email else None

    def _phone_key(self, record: NormalizedCandidateRecord) -> str | None:
        """Build an exact phone match key."""
        return record.contact.phone if record.contact.phone else None

    def _name_location_key(self, record: NormalizedCandidateRecord) -> str | None:
        """Build an exact name plus location match key."""
        name = record.full_name.casefold() if record.full_name else None
        location = self._location_key(record)
        if not name or not location:
            return None
        return f"name_location::{name}::{location}"

    def _name_key(self, record: NormalizedCandidateRecord) -> str | None:
        """Build an exact full-name key."""
        return f"name::{record.full_name.casefold()}" if record.full_name else None

    def _location_key(self, record: NormalizedCandidateRecord) -> str | None:
        """Build a deterministic location key."""
        if record.location.raw_location:
            return record.location.raw_location.casefold()

        parts = [
            value.casefold()
            for value in (
                record.location.city,
                record.location.state_or_region,
                record.location.country,
            )
            if value
        ]
        return "::".join(parts) if parts else None

    def _group_id(self, prefix: str, key: str) -> str:
        """Build a stable group identifier."""
        sanitized = key.replace(" ", "_").replace("@", "_at_").replace("::", "__")
        return f"group::{prefix}::{sanitized}"


def resolve_identities(records: Iterable[NormalizedCandidateRecord]) -> list[IdentityGroup]:
    """Convenience function for identity resolution."""
    return IdentityResolver().resolve_many(records)


__all__ = [
    "IdentityResolver",
    "resolve_identities",
]
