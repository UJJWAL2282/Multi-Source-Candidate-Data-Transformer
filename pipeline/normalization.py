"""Deterministic normalization from canonical candidate records to normalized records."""

from __future__ import annotations

import importlib
import re
from typing import Any, Iterable

from models.candidate_record import CandidateRecord
from models.normalized_candidate_record import (
    ContactInfo,
    EducationRecord,
    EmploymentRecord,
    LocationInfo,
    NormalizedCandidateRecord,
    SkillRecord,
)
from utils.country_dictionary import COUNTRY_ALIASES
from utils.exceptions import NormalizationError
from utils.logger import get_logger
from utils.skill_dictionary import canonicalize_skill_name, is_known_skill


LOGGER = get_logger(__name__)

WHITESPACE_PATTERN = re.compile(r"\s+")
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PHONE_STRIP_PATTERN = re.compile(r"\D")
TITLE_WORDS = {"jr", "sr", "ii", "iii", "iv"}
SOURCE_PRIORITY_BY_TYPE = {
    "recruiter_csv": 10,
    "resume_docx": 40,
    "resume_pdf": 50,
    "resume_txt": 60,
    "api": 70,
    "manual": 80,
    "unknown": 90,
}


class CandidateRecordNormalizer:
    """Normalize canonical candidate records into normalized candidate records."""

    def normalize_one(self, candidate_record: CandidateRecord) -> NormalizedCandidateRecord:
        """Normalize one canonical candidate record."""
        self._validate_candidate_record(candidate_record)
        payload = candidate_record.raw_payload

        full_name = self._normalize_name(payload.get("full_name"))
        first_name, last_name = self._split_name(full_name)
        email_addresses = self._normalize_email_list(payload.get("email_addresses"))
        phone_numbers = self._normalize_phone_list(payload.get("phone_numbers"))
        locations = self._normalize_string_list(payload.get("locations"))
        skills = self._normalize_skill_records(payload.get("skills"))
        education = self._normalize_education(payload.get("education"))
        experience = self._normalize_experience(payload.get("experience"))
        primary_location = locations[0] if locations else None

        normalized_record = NormalizedCandidateRecord(
            normalized_id=self._build_normalized_id(candidate_record),
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            headline=self._derive_headline(experience),
            summary=self._normalize_text(payload.get("summary")),
            contact=ContactInfo(
                email=email_addresses[0] if email_addresses else None,
                phone=phone_numbers[0] if phone_numbers else None,
                alternate_emails=email_addresses[1:],
                alternate_phones=phone_numbers[1:],
                linkedin_url=self._extract_linkedin_url(payload.get("urls")),
            ),
            location=self._normalize_location(primary_location),
            skills=skills,
            work_experience=experience,
            education=education,
            certifications=self._deduplicate_strings(self._normalize_string_list(payload.get("certifications"))),
            languages=self._deduplicate_strings(self._normalize_string_list(payload.get("languages"))),
            attributes=self._build_attributes(candidate_record, payload),
        )

        LOGGER.info(
            "Normalized candidate record record_id=%s normalized_id=%s",
            candidate_record.record_id,
            normalized_record.normalized_id,
        )
        return normalized_record

    def normalize_many(self, candidate_records: Iterable[CandidateRecord]) -> list[NormalizedCandidateRecord]:
        """Normalize multiple canonical candidate records."""
        records = self._coerce_candidate_records(candidate_records)
        return [self.normalize_one(record) for record in records]

    def _coerce_candidate_records(self, candidate_records: Iterable[CandidateRecord]) -> list[CandidateRecord]:
        """Validate top-level normalization input."""
        if candidate_records is None:
            raise NormalizationError("candidate_records must not be None.")
        if isinstance(candidate_records, (str, bytes)):
            raise NormalizationError("candidate_records must be an iterable of CandidateRecord objects.")

        try:
            records = list(candidate_records)
        except TypeError as exc:
            raise NormalizationError(
                "candidate_records must be an iterable of CandidateRecord objects."
            ) from exc

        for record in records:
            self._validate_candidate_record(record)

        return records

    def _validate_candidate_record(self, candidate_record: CandidateRecord) -> None:
        """Validate that the candidate record contains canonical mapping output."""
        if not isinstance(candidate_record, CandidateRecord):
            raise NormalizationError("Normalization requires a CandidateRecord instance.")
        if not isinstance(candidate_record.raw_payload, dict):
            raise NormalizationError("CandidateRecord.raw_payload must be a mapping.")
        if "canonical_schema_version" not in candidate_record.raw_payload:
            raise NormalizationError(
                "CandidateRecord.raw_payload must contain canonical mapping output before normalization."
            )

    def _normalize_name(self, value: Any) -> str | None:
        """Normalize whitespace and capitalization for full names without inventing content."""
        text = self._normalize_text(value)
        if text is None:
            return None

        normalized_parts: list[str] = []
        for part in text.split():
            lowercase = part.casefold().strip(".")
            if lowercase in TITLE_WORDS:
                normalized_parts.append(part.upper().rstrip("."))
            elif part.isupper() and len(part) <= 3:
                normalized_parts.append(part)
            else:
                normalized_parts.append(part[:1].upper() + part[1:].lower())
        return " ".join(normalized_parts)

    def _split_name(self, full_name: str | None) -> tuple[str | None, str | None]:
        """Split a normalized full name into first and last names when possible."""
        if not full_name:
            return None, None
        parts = full_name.split()
        if len(parts) == 1:
            return parts[0], None
        return parts[0], parts[-1]

    def _normalize_email_list(self, value: Any) -> list[str]:
        """Normalize email list values."""
        emails = self._normalize_string_list(value)
        valid_emails = [email.casefold() for email in emails if EMAIL_PATTERN.fullmatch(email)]
        return self._deduplicate_strings(valid_emails)

    def _normalize_phone_list(self, value: Any) -> list[str]:
        """Normalize phone list values to deterministic E.164-compatible strings."""
        phones = self._normalize_string_list(value)
        normalized_phones: list[str] = []
        for phone in phones:
            normalized = self._normalize_phone(phone)
            if normalized is not None:
                normalized_phones.append(normalized)
        return self._deduplicate_strings(normalized_phones)

    def _normalize_string_list(self, value: Any) -> list[str]:
        """Normalize whitespace for a list of strings."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise NormalizationError("Expected a list value during normalization.")

        normalized_values: list[str] = []
        for item in value:
            text = self._normalize_text(item)
            if text:
                normalized_values.append(text)
        return normalized_values

    def _normalize_skill_records(self, value: Any) -> list[SkillRecord]:
        """Normalize skill names and deduplicate skill arrays."""
        skills = self._normalize_string_list(value)
        canonical_skills = [canonicalize_skill_name(skill) for skill in skills]
        deduplicated = self._deduplicate_strings(canonical_skills)
        return [
            SkillRecord(
                name=skill,
                evidence=[],
            )
            for skill in deduplicated
        ]

    def _normalize_education(self, value: Any) -> list[EducationRecord]:
        """Normalize education entries and parse dates where available."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise NormalizationError("Education must be a list in canonical payload.")

        normalized_items: list[EducationRecord] = []
        for item in value:
            if not isinstance(item, dict):
                raise NormalizationError("Education items must be mappings.")
            institution_name = self._normalize_text(item.get("institution_name"))
            if not institution_name:
                continue
            normalized_items.append(
                EducationRecord(
                    institution_name=institution_name,
                    degree=self._normalize_text(item.get("degree_name")),
                    field_of_study=self._normalize_text(item.get("field_of_study")),
                    graduation_date=self._parse_date(item.get("date_text")),
                )
            )
        return normalized_items

    def _normalize_experience(self, value: Any) -> list[EmploymentRecord]:
        """Normalize experience entries and parse date ranges where available."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise NormalizationError("Experience must be a list in canonical payload.")

        normalized_items: list[EmploymentRecord] = []
        for item in value:
            if not isinstance(item, dict):
                raise NormalizationError("Experience items must be mappings.")
            company_name = self._normalize_text(item.get("organization_name"))
            if not company_name:
                continue

            start_date, end_date, is_current = self._parse_date_range(item.get("date_range_text"))
            normalized_items.append(
                EmploymentRecord(
                    company_name=company_name,
                    title=self._normalize_text(item.get("job_title")),
                    start_date=start_date,
                    end_date=end_date,
                    is_current=is_current,
                    description=self._normalize_text(item.get("raw_text")),
                )
            )
        return normalized_items

    def _normalize_location(self, location_text: str | None) -> LocationInfo:
        """Normalize whitespace and country names from a raw location string."""
        normalized_text = self._normalize_text(location_text)
        if normalized_text is None:
            return LocationInfo()

        if is_known_skill(normalized_text):
            return LocationInfo()

        parts = [part.strip() for part in normalized_text.split(",") if part.strip()]
        city = parts[0] if parts else None
        state_or_region = parts[1] if len(parts) > 2 else (parts[1] if len(parts) == 2 else None)
        country = self._normalize_country(parts[-1]) if parts else None

        if len(parts) == 2 and country is not None:
            city = parts[0]
            state_or_region = None

        return LocationInfo(
            city=city,
            state_or_region=state_or_region,
            country=country,
            raw_location=normalized_text,
        )

    def _normalize_country(self, value: str | None) -> str | None:
        """Normalize country aliases without inventing a country when none is known."""
        text = self._normalize_text(value)
        if text is None:
            return None
        return COUNTRY_ALIASES.get(text.casefold(), text if text in COUNTRY_ALIASES.values() else None)

    def _derive_headline(self, experience: list[EmploymentRecord]) -> str | None:
        """Use the first experience title as a deterministic headline when available."""
        for item in experience:
            if item.title:
                return item.title
        return None

    def _extract_linkedin_url(self, value: Any):
        """Return the first LinkedIn URL if present."""
        urls = self._normalize_url_list(value) if isinstance(value, list) else []
        for url in urls:
            if "linkedin.com" in url.casefold():
                return url
        return None

    def _build_attributes(self, candidate_record: CandidateRecord, payload: dict[str, Any]) -> dict[str, Any]:
        """Preserve canonical fields that do not yet map to first-class normalized fields."""
        attributes: dict[str, Any] = {}
        attributes["source_record_id"] = payload.get("source_record_id") or candidate_record.record_id
        attributes["source_name"] = payload.get("source_name") or candidate_record.source.source_name
        attributes["source_type"] = candidate_record.source.source_type.value

        sentences = payload.get("sentences")
        if isinstance(sentences, list):
            normalized_sentences = self._deduplicate_strings(self._normalize_string_list(sentences))
            if normalized_sentences:
                attributes["source_sentences"] = normalized_sentences

        urls = payload.get("urls")
        if isinstance(urls, list):
            normalized_urls = self._deduplicate_strings(self._normalize_url_list(urls))
            if normalized_urls:
                attributes["urls"] = normalized_urls
                for url in normalized_urls:
                    lowered = url.casefold()
                    if "github.com" in lowered and "github_url" not in attributes:
                        attributes["github_url"] = url
                    elif "linkedin.com" in lowered and "linkedin_url" not in attributes:
                        attributes["linkedin_url"] = url
                    elif self._is_personal_website(url) and "personal_website_url" not in attributes:
                        attributes["personal_website_url"] = url

        organizations = payload.get("organizations")
        if isinstance(organizations, list):
            normalized_organizations = self._deduplicate_strings(self._normalize_string_list(organizations))
            if normalized_organizations:
                attributes["organizations"] = normalized_organizations

        attributes["source_priority"] = SOURCE_PRIORITY_BY_TYPE.get(candidate_record.source.source_type.value, 100)

        return attributes

    def _normalize_text(self, value: Any) -> str | None:
        """Collapse whitespace without changing semantic content."""
        if not isinstance(value, str):
            return None
        normalized = WHITESPACE_PATTERN.sub(" ", value).strip()
        return normalized or None

    def _deduplicate_strings(self, values: list[str]) -> list[str]:
        """Deduplicate a string array while preserving order."""
        seen: set[str] = set()
        output: list[str] = []
        for value in values:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            output.append(value)
        return output

    def _normalize_phone(self, value: str) -> str | None:
        """Normalize a phone number to a stable E.164-compatible string when possible."""
        text = self._normalize_text(value)
        if text is None:
            return None

        has_plus_prefix = text.lstrip().startswith("+")
        digits = PHONE_STRIP_PATTERN.sub("", text)
        if len(digits) < 7 or len(digits) > 15:
            return None
        if has_plus_prefix:
            return f"+{digits}"
        if digits.startswith("00") and len(digits) > 9:
            return f"+{digits[2:]}"
        if 11 <= len(digits) <= 15:
            return f"+{digits}"
        return digits

    def _normalize_url_list(self, value: Any) -> list[str]:
        """Normalize URL lists with a deterministic scheme policy."""
        urls = self._normalize_string_list(value)
        normalized_urls: list[str] = []
        for url in urls:
            normalized_urls.append(url if "://" in url else f"https://{url}")
        return normalized_urls

    def _is_personal_website(self, url: str) -> bool:
        """Return whether a URL looks like a non-social personal website or portfolio."""
        lowered = url.casefold()
        return all(domain not in lowered for domain in ("linkedin.com", "github.com", "gitlab.com"))

    def _parse_date(self, value: Any):
        """Parse a single date string deterministically with dateparser when available."""
        text = self._normalize_text(value)
        if text is None:
            return None
        if re.fullmatch(r"(?:19|20)\d{2}", text):
            return self._year_only_date(text)

        try:
            dateparser = importlib.import_module("dateparser")
        except ModuleNotFoundError as exc:
            raise NormalizationError("dateparser is required for date normalization.") from exc

        parsed = dateparser.parse(
            text,
            settings={
                "PREFER_DAY_OF_MONTH": "first",
                "PREFER_DATES_FROM": "past",
                "STRICT_PARSING": True,
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        return parsed.date() if parsed else None

    def _year_only_date(self, year_text: str):
        """Return a deterministic first-of-year date for year-only values."""
        from datetime import date

        return date(int(year_text), 1, 1)

    def _parse_date_range(self, value: Any):
        """Parse a date range into start date, end date, and current-role flag."""
        text = self._normalize_text(value)
        if text is None:
            return None, None, False

        separators = [" - ", " to ", "-", "–", "—"]
        start_text = text
        end_text = None
        for separator in separators:
            if separator in text:
                start_text, end_text = [part.strip() for part in text.split(separator, 1)]
                break

        start_date = self._parse_date(start_text)
        is_current = False
        end_date = None
        if end_text:
            if end_text.casefold() in {"present", "current", "now"}:
                is_current = True
            else:
                end_date = self._parse_date(end_text)
        return start_date, end_date, is_current

    def _build_normalized_id(self, candidate_record: CandidateRecord) -> str:
        """Build a stable normalized record identifier."""
        external_id = candidate_record.raw_payload.get("source_record_id")
        if isinstance(external_id, str) and external_id.strip():
            return f"normalized::{external_id.strip()}"
        return f"normalized::{candidate_record.record_id}"


def normalize_candidate_record(candidate_record: CandidateRecord) -> NormalizedCandidateRecord:
    """Convenience function for normalizing one candidate record."""
    return CandidateRecordNormalizer().normalize_one(candidate_record)


def normalize_candidate_records(
    candidate_records: Iterable[CandidateRecord],
) -> list[NormalizedCandidateRecord]:
    """Convenience function for normalizing multiple candidate records."""
    return CandidateRecordNormalizer().normalize_many(candidate_records)


__all__ = [
    "CandidateRecordNormalizer",
    "normalize_candidate_record",
    "normalize_candidate_records",
]
