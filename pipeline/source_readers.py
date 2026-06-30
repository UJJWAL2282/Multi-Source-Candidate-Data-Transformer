"""Source readers for recruiter CSV files and resume documents."""

from __future__ import annotations

import csv
import hashlib
import mimetypes
import importlib
from pathlib import Path
from typing import Any

from models.candidate_record import (
    CandidateRecord,
    SourceFileReference,
    SourceMetadata,
    SourceType,
)
from utils.exceptions import (
    CsvInputError,
    ResumeReaderError,
    ResumeSourceError,
    SourceReaderError,
)
from utils.logger import get_logger


LOGGER = get_logger(__name__)

SUPPORTED_RESUME_SUFFIXES: dict[str, SourceType] = {
    ".pdf": SourceType.RESUME_PDF,
    ".docx": SourceType.RESUME_DOCX,
}


class CsvCandidateReader:
    """Read recruiter candidate data from CSV files."""

    REQUIRED_COLUMNS = {"name", "email", "phone", "company", "title", "skills", "location"}

    def read(self, csv_path: str | Path, batch_id: str | None = None) -> list[CandidateRecord]:
        """Read candidate records from a recruiter CSV file."""
        path = Path(csv_path)
        print(f"Reading recruiter CSV from: {csv_path}")
        if not path.exists():
            LOGGER.warning("Recruiter CSV file is missing: %s", path)
            return []
        if not path.is_file():
            raise CsvInputError(f"Expected a file path for recruiter CSV, got: {path}")

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = self._validate_header(reader.fieldnames, path)
                records: list[CandidateRecord] = []
                row_number = 2
                while True:
                    try:
                        row = next(reader)
                    except StopIteration:
                        break
                    except csv.Error as exc:
                        LOGGER.warning("Skipping malformed recruiter CSV row %s in %s: %s", row_number, path, exc)
                        row_number += 1
                        continue

                    if row is None:
                        LOGGER.warning("Skipping empty recruiter CSV row %s in %s", row_number, path)
                        row_number += 1
                        continue

                    if self._is_malformed_row(row):
                        LOGGER.warning("Skipping malformed recruiter CSV row %s in %s", row_number, path)
                        row_number += 1
                        continue

                    cleaned_row = self._clean_row(row)
                    if not any(cleaned_row.values()):
                        LOGGER.warning("Skipping blank recruiter CSV row %s in %s", row_number, path)
                        row_number += 1
                        continue

                    records.append(
                        CandidateRecord(
                            source=self._build_source_metadata(
                                path=path,
                                source_type=SourceType.RECRUITER_CSV,
                                batch_id=batch_id,
                            ),
                            raw_payload={
                                "row_number": row_number,
                                "fieldnames": fieldnames,
                                **cleaned_row,
                            },
                            raw_text=self._row_to_raw_text(cleaned_row),
                            tags=["csv", "recruiter"],
                        )
                    )
                    row_number += 1
        except UnicodeDecodeError as exc:
            raise CsvInputError(f"Unable to decode recruiter CSV file: {path}") from exc
        except csv.Error as exc:
            raise CsvInputError(f"Malformed recruiter CSV file: {path}") from exc
        except OSError as exc:
            raise CsvInputError(f"Unable to read recruiter CSV file: {path}") from exc

        return records

    def _validate_header(self, fieldnames: list[str] | None, path: Path) -> list[str]:
        """Validate that a recruiter CSV has a usable header."""
        if not fieldnames:
            raise CsvInputError(f"Recruiter CSV is missing a header row: {path}")

        normalized = [fieldname.strip() for fieldname in fieldnames if fieldname and fieldname.strip()]
        if not normalized:
            raise CsvInputError(f"Recruiter CSV has an empty header row: {path}")

        missing_columns = sorted(self.REQUIRED_COLUMNS.difference(normalized))
        if missing_columns:
            raise CsvInputError(
                f"Recruiter CSV is missing required columns {missing_columns}: {path}"
            )

        return normalized

    def _clean_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalize whitespace in CSV rows without applying business normalization."""
        cleaned: dict[str, Any] = {}
        for key, value in row.items():
            normalized_key = key.strip() if isinstance(key, str) else key
            if isinstance(value, str):
                cleaned[normalized_key] = value.strip()
            else:
                cleaned[normalized_key] = value
        return cleaned

    def _is_malformed_row(self, row: dict[str | None, Any]) -> bool:
        """Return whether a parsed CSV row is structurally malformed."""
        return None in row or any(key is None for key in row)

    def _row_to_raw_text(self, row: dict[str, Any]) -> str:
        """Build a plain-text representation of a raw recruiter CSV row."""
        parts = [f"{key}: {value}" for key, value in row.items() if value not in (None, "")]
        return "\n".join(parts)

    def _build_source_metadata(
        self,
        path: Path,
        source_type: SourceType,
        batch_id: str | None,
    ) -> SourceMetadata:
        """Build source metadata for a file-backed record."""
        return SourceMetadata(
            source_name=path.name,
            source_type=source_type,
            batch_id=batch_id,
            file_reference=SourceFileReference(
                file_name=path.name,
                file_path=str(path),
                mime_type=self._detect_mime_type(path),
                checksum_sha256=self._checksum(path),
            ),
        )

    def _detect_mime_type(self, path: Path) -> str | None:
        """Best-effort MIME type detection."""
        mime_type, _ = mimetypes.guess_type(path.name)
        return mime_type

    def _checksum(self, path: Path) -> str | None:
        """Calculate a SHA-256 checksum for traceability."""
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(8192), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError as exc:
            LOGGER.warning("Failed to compute checksum for %s: %s", path, exc)
            return None


class ResumeCandidateReader:
    """Read resume documents from a directory or individual file paths."""

    def read_many(self, resumes_path: str | Path, batch_id: str | None = None) -> list[CandidateRecord]:
        """Read all supported resumes from a directory or a single file path."""
        path = Path(resumes_path)
        if not path.exists():
            LOGGER.warning("Resume path is missing: %s", path)
            return []

        if path.is_file():
            record = self.read_one(path, batch_id=batch_id)
            return [record] if record is not None else []

        if not path.is_dir():
            raise ResumeSourceError(f"Resume path is neither a file nor directory: {path}")

        records: list[CandidateRecord] = []
        for file_path in sorted(path.iterdir()):
            if not file_path.is_file():
                continue
            record = self.read_one(file_path, batch_id=batch_id)
            if record is not None:
                records.append(record)
        return records

    def read_one(self, resume_path: str | Path, batch_id: str | None = None) -> CandidateRecord | None:
        """Read a single resume file into a raw candidate record."""
        path = Path(resume_path)
        if not path.exists():
            LOGGER.warning("Resume file is missing: %s", path)
            return None
        if not path.is_file():
            raise ResumeSourceError(f"Expected a resume file path, got: {path}")

        source_type = SUPPORTED_RESUME_SUFFIXES.get(path.suffix.lower())
        if source_type is None:
            LOGGER.warning("Skipping unsupported resume format: %s", path)
            return None

        try:
            raw_text = self._extract_text(path, source_type)
        except ResumeReaderError as exc:
            LOGGER.warning("Skipping unreadable resume %s: %s", path, exc)
            return None

        if not raw_text or not raw_text.strip():
            LOGGER.warning("Skipping empty resume: %s", path)
            return None

        return CandidateRecord(
            source=self._build_source_metadata(path=path, source_type=source_type, batch_id=batch_id),
            raw_payload={
                "file_name": path.name,
                "file_extension": path.suffix.lower(),
                "text_length": len(raw_text),
            },
            raw_text=raw_text,
            tags=["resume", source_type.value],
        )

    def _extract_text(self, path: Path, source_type: SourceType) -> str:
        """Dispatch extraction based on the resume source type."""
        if source_type == SourceType.RESUME_PDF:
            return self._extract_pdf_text(path)
        if source_type == SourceType.RESUME_DOCX:
            return self._extract_docx_text(path)
        raise ResumeReaderError(f"Unsupported resume source type: {source_type}")

    def _extract_pdf_text(self, path: Path) -> str:
        """Extract raw text from a PDF resume."""
        try:
            pdfplumber = importlib.import_module("pdfplumber")
        except ModuleNotFoundError as exc:
            raise ResumeReaderError("pdfplumber is required to read PDF resumes.") from exc

        try:
            with pdfplumber.open(path) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
        except Exception as exc:
            raise ResumeReaderError(f"Corrupted or unreadable PDF: {path}") from exc

        return "\n".join(page.strip() for page in pages if page.strip())

    def _extract_docx_text(self, path: Path) -> str:
        """Extract raw text from a DOCX resume."""
        try:
            docx_module = importlib.import_module("docx")
        except ModuleNotFoundError as exc:
            raise ResumeReaderError("python-docx is required to read DOCX resumes.") from exc

        try:
            document = docx_module.Document(path)
        except Exception as exc:
            raise ResumeReaderError(f"Unreadable DOCX document: {path}") from exc

        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n".join(paragraphs)

    def _build_source_metadata(
        self,
        path: Path,
        source_type: SourceType,
        batch_id: str | None,
    ) -> SourceMetadata:
        """Build source metadata for a resume file."""
        mime_type, _ = mimetypes.guess_type(path.name)
        checksum_sha256 = self._checksum(path)
        return SourceMetadata(
            source_name=path.name,
            source_type=source_type,
            batch_id=batch_id,
            file_reference=SourceFileReference(
                file_name=path.name,
                file_path=str(path),
                mime_type=mime_type,
                checksum_sha256=checksum_sha256,
            ),
        )

    def _checksum(self, path: Path) -> str | None:
        """Calculate a SHA-256 checksum for traceability."""
        try:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(8192), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError as exc:
            LOGGER.warning("Failed to compute checksum for %s: %s", path, exc)
            return None


def read_recruiter_csv(csv_path: str | Path, batch_id: str | None = None) -> list[CandidateRecord]:
    """Convenience function for reading recruiter CSV records."""
    return CsvCandidateReader().read(csv_path=csv_path, batch_id=batch_id)


def read_resumes(resumes_path: str | Path, batch_id: str | None = None) -> list[CandidateRecord]:
    """Convenience function for reading resume records."""
    return ResumeCandidateReader().read_many(resumes_path=resumes_path, batch_id=batch_id)


__all__ = [
    "CsvCandidateReader",
    "ResumeCandidateReader",
    "read_recruiter_csv",
    "read_resumes",
    "SourceReaderError",
    "CsvInputError",
    "ResumeSourceError",
    "ResumeReaderError",
]
