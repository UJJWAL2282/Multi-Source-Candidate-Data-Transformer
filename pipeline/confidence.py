"""Deterministic confidence assessment for mastered candidate records."""

from __future__ import annotations

from typing import Iterable

from models.master_candidate_record import ConfidenceBreakdown, MasterCandidateRecord
from utils.exceptions import ConfidenceAssessmentError
from utils.logger import get_logger


LOGGER = get_logger(__name__)


class ConfidenceAssessor:
    """Assess confidence for mastered candidate records using deterministic rules."""

    def assess_one(self, master_record: MasterCandidateRecord) -> MasterCandidateRecord:
        """Compute deterministic confidence scores for one master record."""
        self._validate_master_record(master_record)

        skill_confidence = self._score_skill_confidence(master_record)
        extraction_reliability_score = self._score_extraction_reliability(master_record)
        source_agreement_score = self._score_source_agreement(master_record)
        identity_score = self._score_identity_certainty(master_record)
        conflict_outcome_score = self._score_conflict_outcome(master_record)
        completeness_score = self._score_completeness(master_record)
        consistency_score = self._score_consistency(master_record)

        component_scores = [
            skill_confidence,
            extraction_reliability_score,
            source_agreement_score,
            identity_score,
            conflict_outcome_score,
            completeness_score,
            consistency_score,
        ]
        overall_score = round(sum(component_scores) / len(component_scores), 2)

        confidence = ConfidenceBreakdown(
            overall_score=overall_score,
            skill_confidence=skill_confidence,
            extraction_reliability_score=extraction_reliability_score,
            source_agreement_score=source_agreement_score,
            identity_score=identity_score,
            completeness_score=completeness_score,
            consistency_score=consistency_score,
            conflict_outcome_score=conflict_outcome_score,
            notes=self._build_notes(
                master_record,
                skill_confidence=skill_confidence,
                extraction_reliability_score=extraction_reliability_score,
                source_agreement_score=source_agreement_score,
                identity_score=identity_score,
                conflict_outcome_score=conflict_outcome_score,
                completeness_score=completeness_score,
                consistency_score=consistency_score,
            ),
        )

        updated_record = master_record.model_copy(update={"confidence": confidence})
        LOGGER.info(
            "Assessed confidence for master candidate %s overall_score=%s",
            updated_record.master_candidate_id,
            updated_record.confidence.overall_score,
        )
        return updated_record

    def assess_many(self, master_records: Iterable[MasterCandidateRecord]) -> list[MasterCandidateRecord]:
        """Compute deterministic confidence scores for multiple master records."""
        records = self._coerce_master_records(master_records)
        return [self.assess_one(record) for record in records]

    def _coerce_master_records(
        self,
        master_records: Iterable[MasterCandidateRecord],
    ) -> list[MasterCandidateRecord]:
        """Validate top-level confidence assessment input."""
        if master_records is None:
            raise ConfidenceAssessmentError("master_records must not be None.")
        if isinstance(master_records, (str, bytes)):
            raise ConfidenceAssessmentError(
                "master_records must be an iterable of MasterCandidateRecord objects."
            )
        try:
            records = list(master_records)
        except TypeError as exc:
            raise ConfidenceAssessmentError(
                "master_records must be an iterable of MasterCandidateRecord objects."
            ) from exc

        for record in records:
            self._validate_master_record(record)
        return records

    def _validate_master_record(self, master_record: MasterCandidateRecord) -> None:
        """Validate that a master record can be scored."""
        if not isinstance(master_record, MasterCandidateRecord):
            raise ConfidenceAssessmentError(
                "Confidence assessment requires a MasterCandidateRecord instance."
            )

    def _score_skill_confidence(self, master_record: MasterCandidateRecord) -> float:
        """Score skill confidence from skill count and provenance support."""
        skill_count = len(master_record.canonical_profile.skills)
        skill_entries = [entry for entry in master_record.provenance if entry.field_name == "skills"]
        if skill_count == 0:
            return 0.0
        if skill_count >= 5 and len(skill_entries) >= 3:
            return 1.0
        if skill_count >= 3 and len(skill_entries) >= 2:
            return 0.8
        if skill_count >= 1 and len(skill_entries) >= 1:
            return 0.6
        return 0.4

    def _score_extraction_reliability(self, master_record: MasterCandidateRecord) -> float:
        """Score extraction reliability from provenance methods."""
        methods = {entry.method for entry in master_record.provenance}
        if not methods:
            return 0.0
        if methods == {"direct_extraction"}:
            return 1.0
        if "default_value" in methods:
            return 0.4
        if "conflict_resolution" in methods and "merged" in methods:
            return 0.8
        if "merged" in methods or "conflict_resolution" in methods:
            return 0.7
        return 0.6

    def _score_source_agreement(self, master_record: MasterCandidateRecord) -> float:
        """Score agreement between merged sources."""
        source_names = {entry.source_name for entry in master_record.provenance if entry.source_name != "system"}
        merged_count = len(master_record.merged_record_ids)
        if merged_count <= 1:
            return 0.8
        if len(source_names) <= 1:
            return 1.0
        if len(source_names) == 2:
            return 0.8
        return 0.6

    def _score_identity_certainty(self, master_record: MasterCandidateRecord) -> float:
        """Score identity certainty from retained identity evidence."""
        statuses = {master_record.attributes.get("resolution_status")}
        rule_names = {evidence.rule_name for evidence in master_record.match_evidence}
        if "matched" in statuses and ("email_match" in rule_names or "phone_match" in rule_names):
            return 1.0
        if "matched" in statuses and "name_location_match" in rule_names:
            return 0.8
        if "ambiguous" in statuses:
            return 0.3
        if "no_match" in statuses:
            return 0.6
        return 0.5

    def _score_conflict_outcome(self, master_record: MasterCandidateRecord) -> float:
        """Score how well conflicts were resolved."""
        methods = [entry.method for entry in master_record.provenance]
        merged_count = methods.count("merged")
        conflict_count = methods.count("conflict_resolution")
        default_count = methods.count("default_value")
        if default_count > 0:
            return 0.5
        if merged_count > 0 and conflict_count > 0:
            return 0.9
        if merged_count > 0:
            return 0.8
        if conflict_count > 0:
            return 0.7
        return 1.0

    def _score_completeness(self, master_record: MasterCandidateRecord) -> float:
        """Score completeness based on key profile fields."""
        profile = master_record.canonical_profile
        present_fields = 0
        total_fields = 8
        checks = [
            profile.full_name,
            profile.contact.email,
            profile.contact.phone,
            profile.headline,
            profile.location.raw_location,
            profile.skills,
            profile.work_experience,
            profile.education,
        ]
        for value in checks:
            if value:
                present_fields += 1
        return round(present_fields / total_fields, 2)

    def _score_consistency(self, master_record: MasterCandidateRecord) -> float:
        """Score consistency from alternate-contact spread and ambiguity."""
        profile = master_record.canonical_profile
        if master_record.attributes.get("resolution_status") == "ambiguous":
            return 0.3

        contact_variants = len(profile.contact.alternate_emails) + len(profile.contact.alternate_phones)
        if contact_variants == 0:
            return 1.0
        if contact_variants <= 2:
            return 0.8
        return 0.6

    def _build_notes(
        self,
        master_record: MasterCandidateRecord,
        *,
        skill_confidence: float,
        extraction_reliability_score: float,
        source_agreement_score: float,
        identity_score: float,
        conflict_outcome_score: float,
        completeness_score: float,
        consistency_score: float,
    ) -> list[str]:
        """Build deterministic explanation notes for the assessed confidence."""
        return [
            f"Skill confidence derived from {len(master_record.canonical_profile.skills)} mastered skills: {skill_confidence}.",
            f"Extraction reliability derived from provenance methods: {extraction_reliability_score}.",
            f"Source agreement derived from {len(master_record.merged_record_ids)} merged records: {source_agreement_score}.",
            f"Identity certainty derived from resolution status '{master_record.attributes.get('resolution_status', 'unknown')}': {identity_score}.",
            f"Conflict outcome derived from merge/default provenance distribution: {conflict_outcome_score}.",
            f"Completeness derived from populated canonical profile fields: {completeness_score}.",
            f"Consistency derived from alternate contact spread and ambiguity state: {consistency_score}.",
        ]


def assess_confidence(master_record: MasterCandidateRecord) -> MasterCandidateRecord:
    """Convenience function for scoring one master candidate record."""
    return ConfidenceAssessor().assess_one(master_record)


def assess_confidence_batch(
    master_records: Iterable[MasterCandidateRecord],
) -> list[MasterCandidateRecord]:
    """Convenience function for scoring multiple master candidate records."""
    return ConfidenceAssessor().assess_many(master_records)


__all__ = [
    "ConfidenceAssessor",
    "assess_confidence",
    "assess_confidence_batch",
]
