"""Production orchestration layer for the candidate transformation pipeline."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable

from models.candidate_record import CandidateRecord
from models.extracted_fields import ExtractedFields
from models.identity_group import IdentityGroup
from models.master_candidate_record import MasterCandidateRecord
from models.normalized_candidate_record import NormalizedCandidateRecord
from models.pipeline_config import PipelineConfig
from models.projected_candidate import ProjectedCandidate
from pipeline.canonical_mapping import map_extracted_fields_batch
from pipeline.confidence import assess_confidence_batch
from pipeline.conflict_resolution import resolve_conflicts_batch
from pipeline.field_extraction import extract_resume_fields_batch, extract_structured_fields_batch
from pipeline.identity_resolution import resolve_identities
from pipeline.input_validation import InputValidator, ValidationReport, ValidationSeverity
from pipeline.normalization import normalize_candidate_records
from pipeline.output_validation import validate_output
from pipeline.projection import project_candidates
from pipeline.provenance import build_provenance_batch
from pipeline.source_readers import read_recruiter_csv, read_resumes
from utils.exceptions import PipelineError
from utils.logger import get_logger


LOGGER = get_logger(__name__)


class CandidateTransformationPipeline:
    """Production orchestrator for the deterministic candidate transformation pipeline."""

    def __init__(self, config_path: str | Path, config_overrides: dict[str, dict[str, Any]] | None = None) -> None:
        self.config_path = Path(config_path)
        self.project_root = Path(__file__).resolve().parent.parent
        self.config_overrides = config_overrides or {}
        self.config: PipelineConfig | None = None
        self.projection_config: dict[str, Any] = {}
        self.raw_records: list[CandidateRecord] = []
        self.validated_records: list[CandidateRecord] = []
        self.validation_report = ValidationReport()
        self.extracted_fields: list[ExtractedFields] = []
        self.canonical_records: list[CandidateRecord] = []
        self.normalized_records: list[NormalizedCandidateRecord] = []
        self.identity_groups: list[IdentityGroup] = []
        self.master_records: list[MasterCandidateRecord] = []
        self.projected_candidates: list[ProjectedCandidate] = []
        self.final_json: str = ""

    def load_configuration(self) -> PipelineConfig:
        """Load and validate the pipeline configuration."""
        started_at = time.perf_counter()
        LOGGER.info("Loading configuration...")

        if not self.config_path.exists():
            raise PipelineError(f"Missing configuration file: {self.config_path}")

        try:
            raw_config = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._apply_config_overrides(raw_config)
            self.config = PipelineConfig(**raw_config)
        except Exception as exc:
            raise PipelineError(f"Invalid pipeline configuration: {exc}") from exc

        projection_path = self._resolve_path(self.config.projection.config_path)
        if not projection_path.exists():
            raise PipelineError(f"Missing projection configuration file: {projection_path}")

        try:
            self.projection_config = json.loads(projection_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PipelineError(f"Invalid projection configuration: {exc}") from exc

        output_path = self._resolve_path(self.config.output.output_json_path)
        output_parent = output_path.parent
        try:
            output_parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PipelineError(f"Invalid output directory: {output_parent}") from exc

        logging.getLogger().setLevel(getattr(logging, self.config.logging.level.upper(), logging.INFO))
        self._log_stage_completed("Configuration", 1, started_at)
        return self.config

    def load_sources(self) -> list[CandidateRecord]:
        """Load structured and unstructured candidate sources."""
        config = self._require_config()
        started_at = time.perf_counter()
        LOGGER.info("Loading sources...")

        recruiter_records: list[CandidateRecord] = []
        if config.sources.enable_recruiter_csv:
            csv_path = self._resolve_path(config.input.recruiter_csv_path)
            LOGGER.info("Reading recruiter CSV...")
            recruiter_records = read_recruiter_csv(csv_path)
            LOGGER.info("Loaded %s recruiter records.", len(recruiter_records))

        resume_records: list[CandidateRecord] = []
        if config.sources.enable_resumes:
            resume_dir = self._resolve_path(config.input.resume_directory)
            LOGGER.info("Reading resumes...")
            resume_records = read_resumes(resume_dir)
            LOGGER.info("Loaded %s resumes.", len(resume_records))

        self.raw_records = recruiter_records + resume_records
        self._log_stage_completed("Source Loading", len(self.raw_records), started_at)
        return self.raw_records

    def run_validation(self) -> list[CandidateRecord]:
        """Run input validation and keep processable records."""
        started_at = time.perf_counter()
        LOGGER.info("Running validation...")

        validator = InputValidator()
        report = validator.validate_candidate_records(self.raw_records)
        self.validation_report = report
        self.validated_records = [
            record
            for record in self.raw_records
            if record.record_id
            not in {
                issue.record_id for issue in report.issues if issue.severity == ValidationSeverity.FATAL and issue.record_id
            }
        ]

        if not self.validated_records:
            LOGGER.warning("No processable candidate records remained after validation.")

        self._log_stage_completed("Validation", len(self.validated_records), started_at)
        return self.validated_records

    def run_field_extraction(self) -> list[ExtractedFields]:
        """Run field extraction for structured recruiter rows and resumes."""
        started_at = time.perf_counter()
        LOGGER.info("Running extraction...")

        recruiter_records = [record for record in self.validated_records if "recruiter" in record.tags]
        resume_records = [record for record in self.validated_records if "resume" in record.tags]

        structured_extracted: list[ExtractedFields] = []
        for batch in self._batched(recruiter_records):
            if batch:
                structured_extracted.extend(extract_structured_fields_batch(batch))
        resume_extracted: list[ExtractedFields] = []
        for batch in self._batched(resume_records):
            if batch:
                resume_extracted.extend(extract_resume_fields_batch(batch))

        self.extracted_fields = structured_extracted + resume_extracted
        self._log_stage_completed("Field Extraction", len(self.extracted_fields), started_at)
        return self.extracted_fields

    def run_canonical_mapping(self) -> list[CandidateRecord]:
        """Run canonical mapping."""
        started_at = time.perf_counter()
        LOGGER.info("Running canonical mapping...")

        self.canonical_records = []
        for batch in self._batched(self.extracted_fields):
            if batch:
                self.canonical_records.extend(map_extracted_fields_batch(batch))

        self._log_stage_completed("Canonical Mapping", len(self.canonical_records), started_at)
        return self.canonical_records

    def run_normalization(self) -> list[NormalizedCandidateRecord]:
        """Run normalization."""
        started_at = time.perf_counter()
        LOGGER.info("Running normalization...")

        self.normalized_records = []
        for batch in self._batched(self.canonical_records):
            if batch:
                self.normalized_records.extend(normalize_candidate_records(batch))

        self._log_stage_completed("Normalization", len(self.normalized_records), started_at)
        return self.normalized_records

    def run_identity_resolution(self) -> list[IdentityGroup]:
        """Run identity resolution."""
        started_at = time.perf_counter()
        LOGGER.info("Running identity resolution...")

        self.identity_groups = resolve_identities(self.normalized_records)
        self._log_stage_completed("Identity Resolution", len(self.identity_groups), started_at)
        return self.identity_groups

    def run_conflict_resolution(self) -> list[MasterCandidateRecord]:
        """Run conflict resolution."""
        started_at = time.perf_counter()
        LOGGER.info("Running conflict resolution...")

        self.master_records = resolve_conflicts_batch(self.identity_groups)
        self._log_stage_completed("Conflict Resolution", len(self.master_records), started_at)
        return self.master_records

    def run_provenance(self) -> list[MasterCandidateRecord]:
        """Run provenance building."""
        started_at = time.perf_counter()
        LOGGER.info("Running provenance...")

        self.master_records = build_provenance_batch(self.master_records)
        self._log_stage_completed("Provenance", len(self.master_records), started_at)
        return self.master_records

    def run_confidence(self) -> list[MasterCandidateRecord]:
        """Run confidence assessment."""
        started_at = time.perf_counter()
        LOGGER.info("Running confidence...")

        self.master_records = assess_confidence_batch(self.master_records)
        self._log_stage_completed("Confidence", len(self.master_records), started_at)
        return self.master_records

    def run_projection(self) -> list[ProjectedCandidate]:
        """Run schema projection."""
        started_at = time.perf_counter()
        LOGGER.info("Running projection...")

        self.projected_candidates = project_candidates(self.master_records, self.projection_config)
        self._log_stage_completed("Projection", len(self.projected_candidates), started_at)
        return self.projected_candidates

    def run_output_validation(self) -> str:
        """Run output validation and build final JSON."""
        started_at = time.perf_counter()
        LOGGER.info("Running output validation...")

        config = self._require_config()
        output_validation_config = {
            "required_fields": config.output_validation.required_fields,
            "allow_unknown_fields": config.output_validation.allow_unknown_fields,
            "pretty": config.output_validation.pretty,
            "projection": self.projection_config,
        }
        self.final_json = validate_output(self.projected_candidates, output_validation_config)
        self._log_stage_completed("Output Validation", len(self.projected_candidates), started_at)
        return self.final_json

    def write_output(self) -> Path:
        """Write the final JSON output."""
        config = self._require_config()
        started_at = time.perf_counter()
        LOGGER.info("Writing output.json...")

        output_path = self._resolve_path(config.output.output_json_path)
        output_path.write_text(self.final_json, encoding="utf-8")
        self._log_stage_completed("Write Output", len(self.projected_candidates), started_at)
        return output_path

    def run(self) -> Path:
        """Run the complete candidate transformation pipeline."""
        pipeline_started = time.perf_counter()
        self.load_configuration()
        self.load_sources()
        self.run_validation()
        self.run_field_extraction()
        self.run_canonical_mapping()
        self.run_normalization()
        self.run_identity_resolution()
        self.run_conflict_resolution()
        self.run_provenance()
        self.run_confidence()
        self.run_projection()
        self.run_output_validation()
        output_path = self.write_output()
        self._log_execution_summary(output_path=output_path, started_at=pipeline_started)
        return output_path

    def _resolve_path(self, configured_path: str) -> Path:
        """Resolve a configured path relative to the project root when needed."""
        path = Path(configured_path)
        return path if path.is_absolute() else self.project_root / path

    def _require_config(self) -> PipelineConfig:
        """Return the loaded config or raise if initialization did not run."""
        if self.config is None:
            raise PipelineError("Pipeline configuration has not been loaded.")
        return self.config

    def _apply_config_overrides(self, raw_config: dict[str, Any]) -> None:
        """Apply CLI-supplied config overrides to the raw configuration payload."""
        for section, values in self.config_overrides.items():
            if not values:
                continue
            target = raw_config.setdefault(section, {})
            if not isinstance(target, dict):
                raise PipelineError(f"Cannot override non-mapping configuration section '{section}'.")
            target.update(values)

    def _batched(self, items: list[Any]) -> Iterable[list[Any]]:
        """Yield items in configured batches."""
        batch_size = self._require_config().processing.batch_size
        for index in range(0, len(items), batch_size):
            yield items[index : index + batch_size]

    def _log_stage_completed(self, stage_name: str, record_count: int, started_at: float) -> None:
        """Log stage completion with record count and duration."""
        duration_seconds = time.perf_counter() - started_at
        LOGGER.info("%s completed. Records: %s. Duration: %.2fs", stage_name, record_count, duration_seconds)

    def _log_execution_summary(self, output_path: Path, started_at: float) -> None:
        """Log a professional execution summary after a successful pipeline run."""
        recruiter_loaded = sum(1 for record in self.raw_records if "recruiter" in record.tags)
        resumes_loaded = sum(1 for record in self.raw_records if "resume" in record.tags)
        duration_seconds = time.perf_counter() - started_at
        LOGGER.info(
            "\nPipeline Summary\n"
            "Recruiter Records Loaded: %s\n"
            "Resume Records Loaded: %s\n"
            "Validation Warnings: %s\n"
            "Validation Errors: %s\n"
            "Validation Fatal Issues: %s\n"
            "Identity Groups: %s\n"
            "Master Candidate Records: %s\n"
            "Output Records: %s\n"
            "Execution Time: %.2fs\n"
            "Output File Location: %s",
            recruiter_loaded,
            resumes_loaded,
            self.validation_report.warning_count(),
            self.validation_report.error_count(),
            self.validation_report.fatal_count(),
            len(self.identity_groups),
            len(self.master_records),
            len(self.projected_candidates),
            duration_seconds,
            output_path,
        )
