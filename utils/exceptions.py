"""Custom exceptions for the candidate transformation pipeline."""


class PipelineError(Exception):
    """Base exception for pipeline-related failures."""


class SourceReaderError(PipelineError):
    """Base exception for source reader failures."""


class CsvInputError(SourceReaderError):
    """Raised when recruiter CSV input is malformed or unreadable."""


class ResumeSourceError(SourceReaderError):
    """Raised when a resume path is invalid for ingestion."""


class ResumeReaderError(SourceReaderError):
    """Raised when a resume file cannot be parsed."""


class InputValidationError(PipelineError):
    """Raised when input validation cannot be executed safely."""


class ConfigurationValidationError(PipelineError):
    """Raised when configuration validation encounters a fatal error."""


class FieldExtractionError(PipelineError):
    """Raised when field extraction cannot be executed safely."""


class CanonicalMappingError(PipelineError):
    """Raised when canonical mapping cannot be executed safely."""


class NormalizationError(PipelineError):
    """Raised when normalization cannot be executed safely."""


class IdentityResolutionError(PipelineError):
    """Raised when identity resolution cannot be executed safely."""


class ConflictResolutionError(PipelineError):
    """Raised when conflict resolution cannot be executed safely."""


class ProvenanceError(PipelineError):
    """Raised when provenance construction cannot be executed safely."""


class ConfidenceAssessmentError(PipelineError):
    """Raised when confidence assessment cannot be executed safely."""


class ProjectionError(PipelineError):
    """Raised when schema projection cannot be executed safely."""


class OutputValidationError(PipelineError):
    """Raised when projected output validation fails."""
