"""Input validation for raw candidate records and configuration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from models.candidate_record import CandidateRecord, SourceType
from utils.exceptions import ConfigurationValidationError, InputValidationError
from utils.logger import get_logger


LOGGER = get_logger(__name__)

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9().\-\s]{7,}$")
SUPPORTED_RESUME_EXTENSIONS = {".pdf", ".docx"}
SUPPORTED_SOURCE_TYPES = {
    SourceType.RECRUITER_CSV,
    SourceType.RESUME_PDF,
    SourceType.RESUME_DOCX,
    SourceType.RESUME_TXT,
    SourceType.API,
    SourceType.MANUAL,
    SourceType.UNKNOWN,
}
REQUIRED_CSV_COLUMNS = {"name", "email", "phone", "company", "title", "skills", "location"}
REQUIRED_CSV_VALUES = {"name", "email"}


class ValidationSeverity(str):
    """Validation severity levels."""

    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    """Single validation finding."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(..., description="Stable issue code for programmatic handling.")
    severity: str = Field(..., description="Validation severity level.")
    message: str = Field(..., description="Human-readable description of the validation finding.")
    record_id: str | None = Field(
        default=None,
        description="Candidate record identifier associated with the issue, when applicable.",
    )
    field_name: str | None = Field(
        default=None,
        description="Field associated with the issue, when applicable.",
    )
    source_name: str | None = Field(
        default=None,
        description="Source file or source system name, when applicable.",
    )


class ValidationReport(BaseModel):
    """Structured validation report for input data or configuration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    validated_records: int = Field(
        default=0,
        ge=0,
        description="Number of candidate records that were checked.",
    )
    valid_records: int = Field(
        default=0,
        ge=0,
        description="Number of candidate records without validation errors.",
    )
    invalid_records: int = Field(
        default=0,
        ge=0,
        description="Number of candidate records with one or more validation errors.",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="Detailed validation findings.",
    )

    def add_issue(self, issue: ValidationIssue) -> None:
        """Append a validation issue to the report."""
        self.issues.append(issue)

    def has_errors(self) -> bool:
        """Return whether the report contains one or more errors."""
        return any(issue.severity in {ValidationSeverity.FATAL, ValidationSeverity.ERROR} for issue in self.issues)

    def has_fatals(self) -> bool:
        """Return whether the report contains one or more fatal issues."""
        return any(issue.severity == ValidationSeverity.FATAL for issue in self.issues)

    def fatal_count(self) -> int:
        """Return the total number of fatal issues."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.FATAL)

    def error_count(self) -> int:
        """Return the total number of errors."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.ERROR)

    def warning_count(self) -> int:
        """Return the total number of warnings."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.WARNING)

    def info_count(self) -> int:
        """Return the total number of informational findings."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.INFO)


class InputValidator:
    """Validator for raw candidate records and configuration payloads."""

    def validate_candidate_records(self, records: Iterable[CandidateRecord]) -> ValidationReport:
        """Validate source records without modifying them."""
        candidate_records = self._coerce_records(records)
        report = ValidationReport(validated_records=len(candidate_records))

        for record in candidate_records:
            record_issues = self._validate_record(record)
            if any(issue.severity == ValidationSeverity.FATAL for issue in record_issues):
                report.invalid_records += 1
            else:
                report.valid_records += 1

            for issue in record_issues:
                report.add_issue(issue)

        LOGGER.info(
            "Validated %s candidate records: %s processable, %s blocked, %s warnings, %s errors, %s fatals",
            report.validated_records,
            report.valid_records,
            report.invalid_records,
            report.warning_count(),
            report.error_count(),
            report.fatal_count(),
        )
        return report

    def validate_configuration(self, config: Mapping[str, Any]) -> ValidationReport:
        """Validate pipeline configuration without mutating it."""
        if not isinstance(config, Mapping):
            raise ConfigurationValidationError("Configuration must be a mapping object.")

        report = ValidationReport(validated_records=1, valid_records=1)
        output_fields = config.get("output_fields")

        if output_fields is None:
            report.valid_records = 0
            report.invalid_records = 1
            report.add_issue(
                ValidationIssue(
                    code="config_missing_output_fields",
                    severity=ValidationSeverity.ERROR,
                    message="Configuration must include 'output_fields'.",
                    field_name="output_fields",
                )
            )
        elif not isinstance(output_fields, list):
            raise ConfigurationValidationError("'output_fields' must be a list of field names.")
        elif not output_fields:
            report.valid_records = 0
            report.invalid_records = 1
            report.add_issue(
                ValidationIssue(
                    code="config_empty_output_fields",
                    severity=ValidationSeverity.ERROR,
                    message="'output_fields' must not be empty.",
                    field_name="output_fields",
                )
            )
        else:
            invalid_fields = [field for field in output_fields if not isinstance(field, str) or not field.strip()]
            if invalid_fields:
                raise ConfigurationValidationError(
                    "'output_fields' must contain only non-empty string values."
                )

        LOGGER.info(
            "Validated configuration: %s warnings, %s errors",
            report.warning_count(),
            report.error_count(),
        )
        return report

    def _coerce_records(self, records: Iterable[CandidateRecord]) -> list[CandidateRecord]:
        """Validate the top-level records input."""
        if records is None:
            raise InputValidationError("records must not be None.")

        if isinstance(records, (str, bytes)):
            raise InputValidationError("records must be an iterable of CandidateRecord objects.")

        try:
            candidate_records = list(records)
        except TypeError as exc:
            raise InputValidationError("records must be an iterable of CandidateRecord objects.") from exc

        for record in candidate_records:
            if not isinstance(record, CandidateRecord):
                raise InputValidationError("All items in records must be CandidateRecord instances.")

        return candidate_records

    def _validate_record(self, record: CandidateRecord) -> list[ValidationIssue]:
        """Run all relevant validations for a single record."""
        issues: list[ValidationIssue] = []
        issues.extend(self._validate_source_type(record))
        issues.extend(self._validate_supported_file_type(record))
        issues.extend(self._validate_empty_record(record))

        if record.source.source_type == SourceType.RECRUITER_CSV:
            issues.extend(self._validate_required_columns(record))
            issues.extend(self._validate_missing_values(record))
            issues.extend(self._validate_email_field(record, field_name="email"))
            issues.extend(self._validate_phone_field(record, field_name="phone"))

        return issues

    def _validate_source_type(self, record: CandidateRecord) -> list[ValidationIssue]:
        """Ensure the source type is one of the supported enum values."""
        if record.source.source_type in SUPPORTED_SOURCE_TYPES:
            return []

        return [
            self._issue(
                code="unsupported_source_type",
                severity=ValidationSeverity.FATAL,
                message=f"Unsupported source type '{record.source.source_type}'.",
                record=record,
                field_name="source.source_type",
            )
        ]

    def _validate_supported_file_type(self, record: CandidateRecord) -> list[ValidationIssue]:
        """Validate file type support for file-backed records."""
        file_reference = record.source.file_reference
        if file_reference is None:
            return []

        extension = Path(file_reference.file_name).suffix.lower()
        if record.source.source_type == SourceType.RECRUITER_CSV and extension not in {".csv"}:
            return [
                self._issue(
                    code="unsupported_csv_file_type",
                    severity=ValidationSeverity.FATAL,
                    message=f"Recruiter source must be a CSV file, received '{extension or 'unknown'}'.",
                    record=record,
                    field_name="source.file_reference.file_name",
                )
            ]

        if record.source.source_type in {SourceType.RESUME_PDF, SourceType.RESUME_DOCX, SourceType.RESUME_TXT}:
            if extension not in SUPPORTED_RESUME_EXTENSIONS:
                return [
                    self._issue(
                        code="unsupported_resume_file_type",
                        severity=ValidationSeverity.FATAL,
                        message=f"Unsupported resume file type '{extension or 'unknown'}'.",
                        record=record,
                        field_name="source.file_reference.file_name",
                    )
                ]

        return []

    def _validate_empty_record(self, record: CandidateRecord) -> list[ValidationIssue]:
        """Detect empty source payloads or empty resume text."""
        if record.raw_payload and (record.raw_text is None or record.raw_text.strip()):
            return []

        return [
            self._issue(
                code="empty_record",
                severity=ValidationSeverity.FATAL,
                message="Record does not contain usable raw payload or raw text.",
                record=record,
            )
        ]

    def _validate_required_columns(self, record: CandidateRecord) -> list[ValidationIssue]:
        """Validate recruiter CSV column presence."""
        fieldnames = record.raw_payload.get("fieldnames")
        if fieldnames is None:
            return [
                self._issue(
                    code="missing_csv_fieldnames",
                    severity=ValidationSeverity.FATAL,
                    message="Recruiter CSV record is missing header metadata.",
                    record=record,
                    field_name="raw_payload.fieldnames",
                )
            ]

        if not isinstance(fieldnames, list):
            raise InputValidationError("Recruiter CSV record fieldnames must be provided as a list.")

        missing = sorted(REQUIRED_CSV_COLUMNS.difference({str(field).strip() for field in fieldnames}))
        if not missing:
            return []

        return [
            self._issue(
                code="missing_required_columns",
                severity=ValidationSeverity.FATAL,
                message=f"Recruiter CSV record is missing required columns: {missing}.",
                record=record,
                field_name="raw_payload.fieldnames",
            )
        ]

    def _validate_missing_values(self, record: CandidateRecord) -> list[ValidationIssue]:
        """Validate required recruiter fields are present and non-empty."""
        issues: list[ValidationIssue] = []
        for field_name in REQUIRED_CSV_VALUES:
            value = record.raw_payload.get(field_name)
            if isinstance(value, str) and value.strip():
                continue
            if value not in (None, "") and not isinstance(value, str):
                continue
            issues.append(
                self._issue(
                    code="missing_required_value",
                    severity=ValidationSeverity.ERROR,
                    message=f"Required field '{field_name}' is missing or empty.",
                    record=record,
                    field_name=field_name,
                )
            )
        return issues

    def _validate_email_field(self, record: CandidateRecord, field_name: str) -> list[ValidationIssue]:
        """Validate email syntax when an email field is present."""
        value = record.raw_payload.get(field_name)
        if value in (None, ""):
            return []
        if isinstance(value, str) and EMAIL_PATTERN.fullmatch(value.strip()):
            return []
        return [
            self._issue(
                code="malformed_email",
                severity=ValidationSeverity.ERROR,
                message=f"Field '{field_name}' contains an invalid email address.",
                record=record,
                field_name=field_name,
            )
        ]

    def _validate_phone_field(self, record: CandidateRecord, field_name: str) -> list[ValidationIssue]:
        """Validate phone syntax when a phone field is present."""
        value = record.raw_payload.get(field_name)
        if value in (None, ""):
            return []
        if not isinstance(value, str):
            return [
                self._issue(
                    code="malformed_phone_number",
                    severity=ValidationSeverity.ERROR,
                    message=f"Field '{field_name}' must be a string phone number.",
                    record=record,
                    field_name=field_name,
                )
            ]
        if not PHONE_PATTERN.fullmatch(value.strip()):
            return [
                self._issue(
                    code="malformed_phone_number",
                    severity=ValidationSeverity.ERROR,
                    message=f"Field '{field_name}' contains an invalid phone number.",
                    record=record,
                    field_name=field_name,
                )
            ]

        digits = "".join(character for character in value if character.isdigit())
        if len(digits) < 7:
            return [
                self._issue(
                    code="malformed_phone_number",
                    severity=ValidationSeverity.ERROR,
                    message=f"Field '{field_name}' must contain at least 7 digits.",
                    record=record,
                    field_name=field_name,
                )
            ]
        return []

    def _issue(
        self,
        code: str,
        severity: str,
        message: str,
        record: CandidateRecord,
        field_name: str | None = None,
    ) -> ValidationIssue:
        """Create and log a validation issue."""
        if severity == ValidationSeverity.FATAL:
            log_method = LOGGER.critical
        elif severity == ValidationSeverity.ERROR:
            log_method = LOGGER.error
        elif severity == ValidationSeverity.WARNING:
            log_method = LOGGER.warning
        else:
            log_method = LOGGER.info
        log_method("%s | record_id=%s | source=%s", message, record.record_id, record.source.source_name)
        return ValidationIssue(
            code=code,
            severity=severity,
            message=message,
            record_id=record.record_id,
            field_name=field_name,
            source_name=record.source.source_name,
        )


def validate_candidate_records(records: Iterable[CandidateRecord]) -> ValidationReport:
    """Convenience function for validating candidate records."""
    return InputValidator().validate_candidate_records(records)


def validate_configuration(config: Mapping[str, Any]) -> ValidationReport:
    """Convenience function for validating configuration."""
    return InputValidator().validate_configuration(config)


__all__ = [
    "InputValidator",
    "ValidationIssue",
    "ValidationReport",
    "ValidationSeverity",
    "validate_candidate_records",
    "validate_configuration",
]
