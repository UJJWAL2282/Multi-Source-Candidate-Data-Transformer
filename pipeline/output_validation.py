"""Final output validation and JSON serialization."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from models.projected_candidate import ProjectedCandidate
from pipeline.projection import ProjectionConfig
from utils.exceptions import OutputValidationError
from utils.logger import get_logger


LOGGER = get_logger(__name__)

BASE_PROJECTED_FIELDS = {
    "candidate_id",
    "full_name",
    "email",
    "phone",
    "current_title",
    "current_company",
    "location",
    "skills",
    "confidence_score",
    "attributes",
}


class OutputValidationConfig(BaseModel):
    """Configuration for final output validation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    required_fields: list[str] = Field(
        default_factory=lambda: ["candidate_id"],
        description="Fields that must be present in every projected record.",
    )
    allow_unknown_fields: bool = Field(
        default=True,
        description="Whether fields outside the projected schema are permitted.",
    )
    expected_fields: list[str] = Field(
        default_factory=list,
        description="Explicit target fields expected in the final output schema.",
    )
    ordering: list[str] = Field(
        default_factory=list,
        description="Optional explicit final field ordering.",
    )
    pretty: bool = Field(
        default=True,
        description="Whether the returned JSON should be indented for readability.",
    )

    @field_validator("required_fields", "expected_fields", "ordering")
    @classmethod
    def validate_string_lists(cls, values: list[str]) -> list[str]:
        """Ensure configured field-name collections contain non-empty strings."""
        invalid = [value for value in values if not isinstance(value, str) or not value.strip()]
        if invalid:
            raise ValueError("Field configuration lists must contain only non-empty strings.")
        return values


class OutputValidator:
    """Validate projected candidate output and return final JSON."""

    def validate_and_serialize(
        self,
        projected_candidates: Iterable[ProjectedCandidate | Mapping[str, Any]],
        configuration: Mapping[str, Any] | str,
    ) -> str:
        """Validate projected candidates and return the final JSON payload."""
        candidates = self._coerce_candidates(projected_candidates)
        config = self._parse_configuration(configuration)

        output_records: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_dict = candidate.to_output_dict()
            self._validate_required_fields(candidate_dict, config.required_fields)
            self._validate_types(candidate_dict)
            self._validate_unknown_fields(candidate_dict, config)
            ordered = self._apply_ordering(candidate_dict, config.ordering)
            output_records.append(ordered)

        indent = 2 if config.pretty else None
        final_json = json.dumps(output_records, indent=indent, ensure_ascii=True)
        LOGGER.info("Validated and serialized %s projected candidate records", len(output_records))
        return final_json

    def _coerce_candidates(
        self,
        projected_candidates: Iterable[ProjectedCandidate | Mapping[str, Any]],
    ) -> list[ProjectedCandidate]:
        """Validate and coerce projected output records."""
        if projected_candidates is None:
            raise OutputValidationError("projected_candidates must not be None.")
        if isinstance(projected_candidates, (str, bytes)):
            raise OutputValidationError(
                "projected_candidates must be an iterable of ProjectedCandidate objects or mappings."
            )

        try:
            raw_candidates = list(projected_candidates)
        except TypeError as exc:
            raise OutputValidationError(
                "projected_candidates must be an iterable of ProjectedCandidate objects or mappings."
            ) from exc

        candidates: list[ProjectedCandidate] = []
        for candidate in raw_candidates:
            if isinstance(candidate, ProjectedCandidate):
                candidates.append(candidate)
                continue
            if isinstance(candidate, Mapping):
                try:
                    candidates.append(ProjectedCandidate(**dict(candidate)))
                except ValidationError as exc:
                    raise OutputValidationError(f"Projected candidate schema is invalid: {exc}") from exc
                continue
            raise OutputValidationError(
                "Each projected candidate must be a ProjectedCandidate or a mapping."
            )
        return candidates

    def _parse_configuration(self, configuration: Mapping[str, Any] | str) -> OutputValidationConfig:
        """Parse output validation configuration, optionally deriving schema fields from projection config."""
        parsed = self._parse_mapping(configuration)

        projection_expected_fields = self._projection_expected_fields(parsed)
        if projection_expected_fields and "expected_fields" not in parsed:
            parsed["expected_fields"] = projection_expected_fields
        if "ordering" not in parsed and isinstance(parsed.get("projection"), Mapping):
            ordering = parsed["projection"].get("ordering")
            if isinstance(ordering, list):
                parsed["ordering"] = ordering
        parsed.pop("projection", None)

        try:
            return OutputValidationConfig(**parsed)
        except Exception as exc:
            raise OutputValidationError(f"Output validation configuration is invalid: {exc}") from exc

    def _parse_mapping(self, configuration: Mapping[str, Any] | str) -> dict[str, Any]:
        """Parse a configuration mapping or JSON string."""
        if isinstance(configuration, str):
            try:
                parsed = json.loads(configuration)
            except json.JSONDecodeError as exc:
                raise OutputValidationError("Output validation configuration JSON is invalid.") from exc
        elif isinstance(configuration, Mapping):
            parsed = dict(configuration)
        else:
            raise OutputValidationError("Configuration must be a mapping or JSON string.")
        return parsed

    def _projection_expected_fields(self, parsed_config: dict[str, Any]) -> list[str]:
        """Derive expected output fields from an embedded projection configuration when present."""
        projection_config_raw = parsed_config.get("projection")
        if not isinstance(projection_config_raw, Mapping):
            return []
        try:
            projection_config = ProjectionConfig(**dict(projection_config_raw))
        except Exception as exc:
            raise OutputValidationError(f"Embedded projection configuration is invalid: {exc}") from exc

        expected_fields: list[str] = []
        for field in projection_config.fields:
            expected_fields.append(field.target or field.source.split(".")[-1])
        for field in projection_config.field_selection:
            renamed = projection_config.field_renames.get(field)
            expected_fields.append(renamed or field.split(".")[-1])
        if projection_config.include_confidence:
            expected_fields.append("confidence_score")
        if projection_config.include_provenance:
            expected_fields.append("provenance")
        if "candidate_id" not in expected_fields:
            expected_fields.append("candidate_id")

        deduplicated: list[str] = []
        for field in expected_fields:
            if field not in deduplicated:
                deduplicated.append(field)
        return deduplicated

    def _validate_required_fields(self, candidate_dict: dict[str, Any], required_fields: list[str]) -> None:
        """Validate presence of required output fields."""
        missing = [field for field in required_fields if field not in candidate_dict]
        if missing:
            raise OutputValidationError(f"Projected candidate is missing required fields: {missing}")

    def _validate_types(self, candidate_dict: dict[str, Any]) -> None:
        """Validate final output value types against the schema contract."""
        candidate_id = candidate_dict.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise OutputValidationError("Projected candidate field 'candidate_id' must be a non-empty string.")

        full_name = candidate_dict.get("full_name")
        if full_name is not None and not isinstance(full_name, str):
            raise OutputValidationError("Projected candidate field 'full_name' must be a string when present.")

        email = candidate_dict.get("email")
        if email is not None and not isinstance(email, str):
            raise OutputValidationError("Projected candidate field 'email' must be a string when present.")

        phone = candidate_dict.get("phone")
        if phone is not None and not isinstance(phone, str):
            raise OutputValidationError("Projected candidate field 'phone' must be a string when present.")

        skills = candidate_dict.get("skills")
        if skills is not None:
            if not isinstance(skills, list) or any(not isinstance(item, str) for item in skills):
                raise OutputValidationError("Projected candidate field 'skills' must be a list of strings.")

        confidence_score = candidate_dict.get("confidence_score")
        if confidence_score is not None and not isinstance(confidence_score, (int, float)):
            raise OutputValidationError(
                "Projected candidate field 'confidence_score' must be numeric when present."
            )

    def _validate_unknown_fields(
        self,
        candidate_dict: dict[str, Any],
        config: OutputValidationConfig,
    ) -> None:
        """Validate unknown fields against the expected schema."""
        expected_fields = set(config.expected_fields) if config.expected_fields else set(BASE_PROJECTED_FIELDS)
        if config.allow_unknown_fields:
            return
        unknown_fields = sorted(field for field in candidate_dict if field not in expected_fields)
        if unknown_fields:
            raise OutputValidationError(f"Projected candidate contains unknown fields: {unknown_fields}")

    def _apply_ordering(self, candidate_dict: dict[str, Any], ordering: list[str]) -> dict[str, Any]:
        """Apply final output ordering."""
        if not ordering:
            return candidate_dict

        ordered: dict[str, Any] = {}
        for field in ordering:
            if field in candidate_dict:
                ordered[field] = candidate_dict[field]
        for field, value in candidate_dict.items():
            if field not in ordered:
                ordered[field] = value
        return ordered


def validate_output(
    projected_candidates: Iterable[ProjectedCandidate | Mapping[str, Any]],
    configuration: Mapping[str, Any] | str,
) -> str:
    """Convenience function for validating projected output and returning final JSON."""
    return OutputValidator().validate_and_serialize(projected_candidates, configuration)


__all__ = [
    "OutputValidationConfig",
    "OutputValidator",
    "validate_output",
]
