"""Schema projection engine for mastered candidate records."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.master_candidate_record import MasterCandidateRecord
from models.projected_candidate import ProjectedCandidate
from utils.exceptions import ProjectionError
from utils.logger import get_logger


LOGGER = get_logger(__name__)

SUPPORTED_MISSING_VALUE_POLICIES = {"omit", "null", "empty_string", "empty_list"}

DEFAULT_FIELD_ALIASES: dict[str, str] = {
    "master_candidate_id": "candidate_id",
    "canonical_profile.full_name": "full_name",
    "canonical_profile.contact.email": "email",
    "canonical_profile.contact.phone": "phone",
    "canonical_profile.headline": "current_title",
    "canonical_profile.location.raw_location": "location",
    "confidence.overall_score": "confidence_score",
}


class ProjectionFieldConfig(BaseModel):
    """Configuration for projecting one field."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: str = Field(..., description="Dot-path source field on MasterCandidateRecord.")
    target: str | None = Field(
        default=None,
        description="Optional target field name in the projected output.",
    )
    include_if_missing: bool = Field(
        default=False,
        description="Whether to include the field even when its value is missing.",
    )
    missing_value: Any = Field(
        default=None,
        description="Optional per-field fallback value used when the source value is missing.",
    )


class ProjectionConfig(BaseModel):
    """Projection configuration for schema output."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fields: list[ProjectionFieldConfig] = Field(
        default_factory=list,
        description="Explicit field projections in the output.",
    )
    field_selection: list[str] = Field(
        default_factory=list,
        description="Simple source field-selection shorthand.",
    )
    field_renames: dict[str, str] = Field(
        default_factory=dict,
        description="Optional source-to-target field rename map.",
    )
    ordering: list[str] = Field(
        default_factory=list,
        description="Target-field ordering for final output.",
    )
    missing_value_policy: str = Field(
        default="omit",
        description="Global missing-value policy for projected fields.",
    )
    include_confidence: bool = Field(
        default=False,
        description="Whether to include the overall confidence score by default.",
    )
    include_provenance: bool = Field(
        default=False,
        description="Whether to include provenance by default.",
    )

    @field_validator("missing_value_policy")
    @classmethod
    def validate_missing_value_policy(cls, value: str) -> str:
        """Ensure the missing-value policy is supported."""
        if value not in SUPPORTED_MISSING_VALUE_POLICIES:
            raise ValueError(
                f"missing_value_policy must be one of {sorted(SUPPORTED_MISSING_VALUE_POLICIES)}."
            )
        return value


class ProjectionEngine:
    """Project mastered candidate records into configurable output schemas."""

    def project_one(
        self,
        master_record: MasterCandidateRecord,
        configuration: Mapping[str, Any] | str,
    ) -> ProjectedCandidate:
        """Project one master candidate record into the configured output schema."""
        self._validate_master_record(master_record)
        config = self._parse_configuration(configuration)
        field_specs = self._build_field_specs(config)

        projected_data: dict[str, Any] = {}
        for field_config in field_specs:
            target = field_config.target or self._default_target(field_config.source)
            raw_value = self._resolve_path(master_record, field_config.source)
            final_value, include_field = self._apply_missing_policy(
                raw_value=raw_value,
                field_config=field_config,
                policy=config.missing_value_policy,
            )
            if include_field:
                projected_data[target] = self._serialize_value(final_value)

        if "candidate_id" not in projected_data:
            projected_data["candidate_id"] = master_record.master_candidate_id

        ordered_data = self._order_output(projected_data, config.ordering)
        projected_candidate = ProjectedCandidate(**ordered_data)
        LOGGER.info(
            "Projected master candidate %s into output with %s fields",
            master_record.master_candidate_id,
            len(ordered_data),
        )
        return projected_candidate

    def project_many(
        self,
        master_records: Iterable[MasterCandidateRecord],
        configuration: Mapping[str, Any] | str,
    ) -> list[ProjectedCandidate]:
        """Project multiple master candidate records using the same configuration."""
        records = self._coerce_master_records(master_records)
        config = self._parse_configuration(configuration)
        return [self.project_one(record, config.model_dump(mode="python")) for record in records]

    def _coerce_master_records(
        self,
        master_records: Iterable[MasterCandidateRecord],
    ) -> list[MasterCandidateRecord]:
        """Validate top-level projection input."""
        if master_records is None:
            raise ProjectionError("master_records must not be None.")
        if isinstance(master_records, (str, bytes)):
            raise ProjectionError("master_records must be an iterable of MasterCandidateRecord objects.")
        try:
            records = list(master_records)
        except TypeError as exc:
            raise ProjectionError(
                "master_records must be an iterable of MasterCandidateRecord objects."
            ) from exc

        for record in records:
            self._validate_master_record(record)
        return records

    def _validate_master_record(self, master_record: MasterCandidateRecord) -> None:
        """Validate that the projection engine received a master record."""
        if not isinstance(master_record, MasterCandidateRecord):
            raise ProjectionError("Projection requires a MasterCandidateRecord instance.")

    def _parse_configuration(self, configuration: Mapping[str, Any] | str) -> ProjectionConfig:
        """Parse configuration JSON or mapping into a validated config model."""
        if isinstance(configuration, str):
            try:
                parsed = json.loads(configuration)
            except json.JSONDecodeError as exc:
                raise ProjectionError("Configuration JSON is invalid.") from exc
        elif isinstance(configuration, Mapping):
            parsed = dict(configuration)
        else:
            raise ProjectionError("Configuration must be a mapping or JSON string.")

        try:
            return ProjectionConfig(**parsed)
        except Exception as exc:
            raise ProjectionError(f"Projection configuration is invalid: {exc}") from exc

    def _build_field_specs(self, config: ProjectionConfig) -> list[ProjectionFieldConfig]:
        """Build the effective field projection list."""
        field_specs: list[ProjectionFieldConfig] = list(config.fields)

        existing_sources = {field.source for field in field_specs}
        for source in config.field_selection:
            if source not in existing_sources:
                field_specs.append(
                    ProjectionFieldConfig(
                        source=source,
                        target=config.field_renames.get(source),
                    )
                )
                existing_sources.add(source)

        if config.include_confidence and "confidence.overall_score" not in existing_sources:
            field_specs.append(
                ProjectionFieldConfig(
                    source="confidence.overall_score",
                    target="confidence_score",
                )
            )
            existing_sources.add("confidence.overall_score")

        if config.include_provenance and "provenance" not in existing_sources:
            field_specs.append(
                ProjectionFieldConfig(
                    source="provenance",
                    target="provenance",
                    include_if_missing=True,
                    missing_value=[],
                )
            )

        if not field_specs:
            field_specs = self._default_field_specs(config)

        return field_specs

    def _default_field_specs(self, config: ProjectionConfig) -> list[ProjectionFieldConfig]:
        """Return a sensible default projection when no explicit fields are provided."""
        default_sources = [
            "master_candidate_id",
            "canonical_profile.full_name",
            "canonical_profile.contact.email",
            "canonical_profile.contact.phone",
            "canonical_profile.headline",
            "canonical_profile.location.raw_location",
            "canonical_profile.skills",
        ]
        if config.include_confidence:
            default_sources.append("confidence.overall_score")
        if config.include_provenance:
            default_sources.append("provenance")

        return [
            ProjectionFieldConfig(
                source=source,
                target=config.field_renames.get(source) or self._default_target(source),
            )
            for source in default_sources
        ]

    def _default_target(self, source: str) -> str:
        """Resolve the default target field name for a source path."""
        return DEFAULT_FIELD_ALIASES.get(source, source.split(".")[-1])

    def _resolve_path(self, master_record: MasterCandidateRecord, source: str) -> Any:
        """Resolve a dot-path against the master candidate record."""
        current: Any = master_record
        for part in source.split("."):
            if isinstance(current, Mapping):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                raise ProjectionError(f"Projection source path '{source}' is invalid.")
        return current

    def _apply_missing_policy(
        self,
        *,
        raw_value: Any,
        field_config: ProjectionFieldConfig,
        policy: str,
    ) -> tuple[Any, bool]:
        """Apply per-field and global missing-value policy."""
        if not self._is_missing(raw_value):
            return raw_value, True

        if field_config.missing_value is not None:
            return field_config.missing_value, True

        if field_config.include_if_missing:
            return self._policy_value(policy), True

        if policy == "omit":
            return None, False
        return self._policy_value(policy), True

    def _policy_value(self, policy: str) -> Any:
        """Return the configured missing-value representation."""
        if policy == "null":
            return None
        if policy == "empty_string":
            return ""
        if policy == "empty_list":
            return []
        if policy == "omit":
            return None
        raise ProjectionError(f"Unsupported missing value policy '{policy}'.")

    def _serialize_value(self, value: Any) -> Any:
        """Serialize model values for projection output."""
        if isinstance(value, list) and value and all(hasattr(item, "name") for item in value):
            return [getattr(item, "name") for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._serialize_value(item) for key, item in value.items()}
        return value

    def _is_missing(self, value: Any) -> bool:
        """Return whether a value should be treated as missing."""
        if value is None:
            return True
        if isinstance(value, str):
            return value == ""
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) == 0
        return False

    def _order_output(self, projected_data: dict[str, Any], ordering: list[str]) -> dict[str, Any]:
        """Apply explicit output ordering while preserving unspecified fields."""
        if not ordering:
            return projected_data

        ordered: dict[str, Any] = {}
        for field_name in ordering:
            if field_name in projected_data:
                ordered[field_name] = projected_data[field_name]

        for field_name, value in projected_data.items():
            if field_name not in ordered:
                ordered[field_name] = value
        return ordered


def project_candidate(
    master_record: MasterCandidateRecord,
    configuration: Mapping[str, Any] | str,
) -> ProjectedCandidate:
    """Convenience function for projecting one master candidate record."""
    return ProjectionEngine().project_one(master_record, configuration)


def project_candidates(
    master_records: Iterable[MasterCandidateRecord],
    configuration: Mapping[str, Any] | str,
) -> list[ProjectedCandidate]:
    """Convenience function for projecting multiple master candidate records."""
    return ProjectionEngine().project_many(master_records, configuration)


__all__ = [
    "ProjectionConfig",
    "ProjectionEngine",
    "ProjectionFieldConfig",
    "project_candidate",
    "project_candidates",
]
