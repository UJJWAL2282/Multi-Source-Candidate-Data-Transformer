"""Pipeline configuration models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InputConfig(BaseModel):
    """Input source paths."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recruiter_csv_path: str = Field(..., description="Path to the recruiter CSV input file.")
    resume_directory: str = Field(..., description="Path to the input resume directory.")


class OutputConfig(BaseModel):
    """Output target paths."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    output_json_path: str = Field(..., description="Path to the final output JSON file.")


class ProjectionFileConfig(BaseModel):
    """Projection configuration file reference."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    config_path: str = Field(..., description="Path to the projection configuration JSON file.")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    level: str = Field(default="INFO", description="Root logging level for pipeline execution.")


class ProcessingConfig(BaseModel):
    """Batch-processing configuration."""

    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(default=100, ge=1, description="Batch size used in orchestration stages.")


class SourceFlags(BaseModel):
    """Source enablement flags for current and future sources."""

    model_config = ConfigDict(extra="allow")

    enable_recruiter_csv: bool = Field(default=True, description="Enable recruiter CSV ingestion.")
    enable_resumes: bool = Field(default=True, description="Enable resume ingestion.")


class OutputValidationSettings(BaseModel):
    """Configuration for final output validation."""

    model_config = ConfigDict(extra="forbid")

    required_fields: list[str] = Field(
        default_factory=lambda: ["candidate_id"],
        description="Required fields in the final JSON output.",
    )
    allow_unknown_fields: bool = Field(
        default=True,
        description="Whether final output may contain fields outside the expected schema.",
    )
    pretty: bool = Field(default=True, description="Whether final JSON should be pretty printed.")


class PipelineConfig(BaseModel):
    """Top-level pipeline configuration."""

    model_config = ConfigDict(extra="forbid")

    input: InputConfig
    output: OutputConfig
    projection: ProjectionFileConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    sources: SourceFlags = Field(default_factory=SourceFlags)
    output_validation: OutputValidationSettings = Field(default_factory=OutputValidationSettings)
