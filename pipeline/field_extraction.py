"""Deterministic field extraction for resume and structured candidate records."""

from __future__ import annotations

import importlib
import re
from typing import Any, Iterable

from models.candidate_record import CandidateRecord, SourceType
from models.extracted_fields import (
    ExtractedEducationItem,
    ExtractedExperienceItem,
    ExtractedFields,
)
from pipeline.source_readers import ResumeCandidateReader
from utils.exceptions import FieldExtractionError
from utils.logger import get_logger
from utils.regex_patterns import (
    DATE_RANGE_PATTERN,
    EMAIL_PATTERN,
    PHONE_PATTERN,
    URL_PATTERN,
    WHITESPACE_PATTERN,
    YEAR_PATTERN,
)
from utils.skill_dictionary import canonicalize_skill_name, extract_canonical_skills, is_known_skill


LOGGER = get_logger(__name__)

STRUCTURED_SOURCE_TYPES = {SourceType.RECRUITER_CSV}
RESUME_SOURCE_TYPES = {SourceType.RESUME_PDF, SourceType.RESUME_DOCX, SourceType.RESUME_TXT}
EDUCATION_KEYWORDS = ("education", "university", "college", "bachelor", "master", "phd", "b.tech", "m.tech", "mba")
EXPERIENCE_KEYWORDS = ("experience", "worked", "engineer", "developer", "manager", "analyst", "consultant")
DEGREE_KEYWORDS = ("bachelor", "master", "phd", "b.tech", "m.tech", "mba", "b.sc", "m.sc", "bs", "ms")
TITLE_KEYWORDS = ("engineer", "developer", "manager", "analyst", "consultant", "scientist", "architect", "lead")
LOCATION_PREPOSITIONS = {"in", "at", "from", "based"}
FALLBACK_SENTENCE_PATTERN = re.compile(r"(?<=[.!?\n])\s+")
SECTION_HEADER_PATTERN = re.compile(
    r"^(summary|profile|experience|work experience|projects|education|skills|certifications|contact)\b",
    re.IGNORECASE,
)
SECTION_NAME_MAP = {
    "summary": "summary",
    "profile": "summary",
    "experience": "experience",
    "work experience": "experience",
    "projects": "projects",
    "education": "education",
    "skills": "skills",
    "certifications": "certifications",
    "contact": "contact",
}
LOCATION_LABEL_PATTERN = re.compile(
    r"\b(?:location|city|based in|located in|address)\s*[:\-]?\s*([A-Za-z][A-Za-z\s,.-]{1,80})",
    re.IGNORECASE,
)
LOCATION_TOKEN_PATTERN = re.compile(r"[A-Za-z]+")
INSTITUTION_KEYWORDS = {"university", "college", "school", "institute", "academy", "faculty", "campus"}
CERTIFICATION_KEYWORDS = {"certified", "certification", "fundamentals", "associate", "professional"}
URL_CLASSIFIERS = {
    "linkedin.com": "linkedin",
    "github.com": "github",
    "gitlab.com": "github",
}
DATE_PREFIX_PATTERN = re.compile(r"^(?:19|20)\d{2}\s+")
TITLE_ORG_PATTERN = re.compile(
    r"^(?P<title>[A-Za-z][A-Za-z/&,\-.\s]{1,80}?),\s*(?P<organization>[A-Za-z][A-Za-z0-9&.,\- ]{1,80}?)(?:\s+(?P<dates>(?:19|20)\d{2}.*|[A-Za-z]{3,9}\s+\d{4}.*))?$"
)
AT_FROM_PATTERN = re.compile(
    r"\b(?:at|from)\s+(?P<value>[A-Za-z][A-Za-z0-9&.,\- ]{1,100})",
    re.IGNORECASE,
)
WORKED_AT_PATTERN = re.compile(
    r"\bworked\s+at\s+(?P<organization>[A-Za-z][A-Za-z0-9&.,\- ]{1,80}?)(?:\s+from\s+(?P<dates>.+))?$",
    re.IGNORECASE,
)
EXPERIENCE_BULLET_PREFIX = ("-", "–", "•", "*")


class _FallbackSpan:
    """Minimal span object for deterministic fallback sentence segmentation."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FallbackDoc:
    """Minimal document object compatible with the extractor's needs."""

    def __init__(self, text: str) -> None:
        self.ents: list[object] = []
        self.sents = [_FallbackSpan(sentence) for sentence in FALLBACK_SENTENCE_PATTERN.split(text) if sentence.strip()]


class _FallbackNlpPipeline:
    """Deterministic fallback pipeline when spaCy is unavailable."""

    def __call__(self, text: str) -> _FallbackDoc:
        return _FallbackDoc(text)


class ResumeFieldExtractor:
    """Extract fields from resume candidate records using deterministic rules."""

    def __init__(self) -> None:
        self._nlp = self._build_nlp_pipeline()
        self._resume_reader = ResumeCandidateReader()

    def extract_from_path(self, resume_path: str) -> ExtractedFields:
        """Read a single resume document and extract fields from it."""
        record = self._resume_reader.read_one(resume_path)
        if record is None:
            raise FieldExtractionError(f"Unable to extract from resume path: {resume_path}")
        return self.extract_one(record)

    def extract_from_paths(self, resume_paths: Iterable[str]) -> list[ExtractedFields]:
        """Read and extract fields from multiple resume documents."""
        extracted_records: list[ExtractedFields] = []
        for resume_path in resume_paths:
            extracted_records.append(self.extract_from_path(resume_path))
        return extracted_records

    def extract_many(self, records: Iterable[CandidateRecord]) -> list[ExtractedFields]:
        """Extract fields from multiple resume candidate records."""
        extracted_records: list[ExtractedFields] = []
        for record in records:
            extracted_records.append(self.extract_one(record))
        return extracted_records

    def extract_one(self, record: CandidateRecord) -> ExtractedFields:
        """Extract fields from a single resume candidate record."""
        self._validate_record(record)
        raw_text = record.raw_text or ""
        lines = self._split_lines(raw_text)
        sections = self._extract_sections(lines)
        sentences = self._segment_sentences(raw_text)
        entities = self._extract_entities(sentences)
        urls = self._extract_urls(raw_text)

        extracted = ExtractedFields(
            record_id=record.record_id,
            source_name=record.source.source_name,
            source_metadata=record.source.model_copy(deep=True),
            name=self._extract_name(raw_text, entities["persons"]),
            emails=self._regex_matches(EMAIL_PATTERN, raw_text),
            phone_numbers=self._clean_phone_matches(self._regex_matches(PHONE_PATTERN, raw_text)),
            skills=self._extract_skills(raw_text),
            education=self._extract_education(lines, sections, entities["organizations"]),
            experience=self._extract_experience(lines, sections, entities["organizations"]),
            organizations=entities["organizations"],
            locations=self._extract_locations(lines, sentences, entities),
            urls=urls,
            sentences=sentences,
        )
        LOGGER.info(
            "Extracted resume fields for record_id=%s source=%s",
            record.record_id,
            record.source.source_name,
        )
        return extracted

    def _build_nlp_pipeline(self):
        """Build a rule-based spaCy pipeline with sentence segmentation and optional NER."""
        try:
            spacy = importlib.import_module("spacy")
        except Exception as exc:
            LOGGER.warning("spaCy is unavailable, using deterministic fallback sentence segmentation: %s", exc)
            return _FallbackNlpPipeline()

        for model_name in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
            try:
                nlp = spacy.load(model_name, disable=["parser", "lemmatizer", "textcat"])
                if "sentencizer" not in nlp.pipe_names:
                    nlp.add_pipe("sentencizer")
                return nlp
            except Exception:
                continue

        nlp = spacy.blank("en")
        if "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")

        ruler = nlp.add_pipe("entity_ruler")
        ruler.add_patterns(self._entity_patterns())
        return nlp

    def _entity_patterns(self) -> list[dict[str, object]]:
        """Return deterministic entity ruler patterns."""
        return [
            {"label": "EDU", "pattern": [{"LOWER": {"IN": ["bachelor", "master", "mba", "phd", "university", "college"]}}]},
            {"label": "ORG_HINT", "pattern": [{"IS_TITLE": True}, {"IS_TITLE": True}]},
            {"label": "LOC_HINT", "pattern": [{"LOWER": {"IN": ["new", "san", "los"]}}, {"IS_TITLE": True}]},
            {"label": "PERSON_HINT", "pattern": [{"IS_TITLE": True}, {"IS_TITLE": True}]},
        ]

    def _validate_record(self, record: CandidateRecord) -> None:
        """Validate that a candidate record can be processed by the resume extractor."""
        if not isinstance(record, CandidateRecord):
            raise FieldExtractionError("Field extraction requires a CandidateRecord instance.")
        if record.source.source_type not in RESUME_SOURCE_TYPES:
            raise FieldExtractionError(
                f"Field extraction supports resume records only, got '{record.source.source_type.value}'."
            )
        if not record.raw_text or not record.raw_text.strip():
            raise FieldExtractionError("Resume record does not contain extractable raw_text.")

    def _segment_sentences(self, text: str) -> list[str]:
        """Split resume text into stable sentence units with spaCy sentencizer."""
        document = self._nlp(text)
        sentences = [self._normalize_whitespace(sentence.text) for sentence in document.sents]
        return [sentence for sentence in sentences if sentence]

    def _extract_entities(self, sentences: list[str]) -> dict[str, list[str]]:
        """Extract deterministic entity candidates from segmented sentences."""
        persons: list[str] = []
        organizations: list[str] = []
        locations: list[str] = []

        for sentence in sentences:
            document = self._nlp(sentence)
            persons.extend(self._person_candidates(document))
            organizations.extend(self._organization_candidates(sentence, document))
            locations.extend(self._location_candidates(sentence, document))

        return {
            "persons": self._deduplicate(persons),
            "organizations": self._deduplicate(organizations),
            "locations": self._deduplicate(locations),
        }

    def _person_candidates(self, document) -> list[str]:
        """Return person-like candidates from the first lines of a resume."""
        candidates: list[str] = []
        for entity in document.ents:
            if entity.label_ in {"PERSON", "PERSON_HINT"}:
                candidates.append(entity.text)
        return candidates

    def _organization_candidates(self, sentence: str, document: Any | None = None) -> list[str]:
        """Return organization-like candidates from a sentence."""
        candidates: list[str] = []
        if document is not None:
            for entity in document.ents:
                if entity.label_ == "ORG":
                    candidates.append(entity.text)
        tokens = sentence.split()
        for index in range(len(tokens) - 1):
            pair = f"{tokens[index]} {tokens[index + 1]}"
            if tokens[index][0:1].isupper() and tokens[index + 1][0:1].isupper():
                if any(keyword in pair.lower() for keyword in ("inc", "llc", "corp", "technologies", "systems", "labs")):
                    candidates.append(pair)
        return candidates

    def _location_candidates(self, sentence: str, document: Any | None = None) -> list[str]:
        """Return location-like candidates from a sentence."""
        candidates: list[str] = []
        if document is not None:
            for entity in document.ents:
                if entity.label_ in {"GPE", "LOC"}:
                    candidates.append(entity.text)
        tokens = sentence.split()
        for index, token in enumerate(tokens[:-1]):
            if token.lower() in LOCATION_PREPOSITIONS:
                next_token = tokens[index + 1].strip(",")
                if next_token[:1].isupper():
                    candidate = next_token
                    if index + 2 < len(tokens) and tokens[index + 2][:1].isupper():
                        candidate = f"{candidate} {tokens[index + 2].strip(',')}"
                    candidates.append(candidate)
        for match in LOCATION_LABEL_PATTERN.finditer(sentence):
            candidates.append(match.group(1))
        return candidates

    def _extract_name(self, raw_text: str, person_candidates: list[str]) -> str | None:
        """Extract a resume name using top-line heuristics and spaCy person hints."""
        lines = [self._normalize_whitespace(line) for line in raw_text.splitlines()]
        non_empty_lines = [line for line in lines if line]

        for line in non_empty_lines[:3]:
            if "@" in line or any(character.isdigit() for character in line):
                continue
            words = line.split()
            if 1 < len(words) <= 4 and all(word[:1].isupper() for word in words if word.isalpha() or word.replace(".", "").isalpha()):
                return line

        return person_candidates[0] if person_candidates else None

    def _extract_skills(self, raw_text: str) -> list[str]:
        """Extract skills using deterministic dictionary matching."""
        return self._deduplicate(extract_canonical_skills(raw_text))

    def _extract_education(
        self,
        lines: list[str],
        sections: dict[str, list[str]],
        organization_candidates: list[str],
    ) -> list[ExtractedEducationItem]:
        """Extract education evidence from education lines and section-aware fallbacks."""
        education_items: list[ExtractedEducationItem] = []
        education_lines = sections.get("education") or lines
        for sentence in education_lines:
            lowered = sentence.casefold()
            if not any(keyword in lowered for keyword in EDUCATION_KEYWORDS):
                continue
            institution = self._extract_institution(sentence, organization_candidates)
            degree = next((keyword for keyword in DEGREE_KEYWORDS if keyword in lowered), None)
            date_text = self._first_regex_match(DATE_RANGE_PATTERN, sentence) or self._first_regex_match(YEAR_PATTERN, sentence)
            field_of_study = self._extract_field_of_study(sentence, degree)
            if not any([institution, degree, field_of_study, date_text]):
                continue
            education_items.append(
                ExtractedEducationItem(
                    text=sentence,
                    institution=institution,
                    degree=degree,
                    field_of_study=field_of_study,
                    date_text=date_text,
                )
            )
        return education_items

    def _extract_experience(
        self,
        lines: list[str],
        sections: dict[str, list[str]],
        organization_candidates: list[str],
    ) -> list[ExtractedExperienceItem]:
        """Extract experience evidence from experience lines and section-aware fallbacks."""
        experience_items: list[ExtractedExperienceItem] = []
        experience_lines = sections.get("experience") or lines
        for sentence in experience_lines:
            lowered = sentence.casefold()
            if sentence.startswith(EXPERIENCE_BULLET_PREFIX):
                continue
            if not any(keyword in lowered for keyword in EXPERIENCE_KEYWORDS) and not DATE_RANGE_PATTERN.search(sentence):
                continue
            title, organization, date_range_text = self._parse_experience_line(sentence, organization_candidates)
            if not any([organization, title, date_range_text]):
                continue
            experience_items.append(
                ExtractedExperienceItem(
                    text=sentence,
                    title=title,
                    organization=organization,
                    date_range_text=date_range_text,
                )
            )
        return experience_items

    def _first_matching_candidate(self, sentence: str, candidates: list[str]) -> str | None:
        """Return the first candidate that appears in the sentence."""
        lowered_sentence = sentence.lower()
        for candidate in candidates:
            if candidate.lower() in lowered_sentence:
                return candidate
        return None

    def _regex_matches(self, pattern, text: str) -> list[str]:
        """Return deduplicated regex matches."""
        if not text:
            return []
        return self._deduplicate([self._normalize_whitespace(match) for match in pattern.findall(text)])

    def _extract_urls(self, text: str) -> list[str]:
        """Extract and minimally normalize URLs."""
        urls = self._regex_matches(URL_PATTERN, text)
        normalized_urls: list[str] = []
        for url in urls:
            normalized_urls.append(url if "://" in url else f"https://{url}")
        return self._deduplicate(normalized_urls)

    def _first_regex_match(self, pattern, text: str) -> str | None:
        """Return the first regex match if available."""
        match = pattern.search(text)
        return self._normalize_whitespace(match.group(0)) if match else None

    def _clean_phone_matches(self, matches: list[str]) -> list[str]:
        """Return phone matches with normalized spacing preserved minimally."""
        cleaned: list[str] = []
        for match in matches:
            normalized = self._normalize_whitespace(match).strip(".,;")
            digits = "".join(character for character in normalized if character.isdigit())
            if len(digits) < 7 or len(digits) > 15:
                continue
            cleaned.append(normalized.lstrip(":").strip())
        return self._deduplicate(cleaned)

    def _normalize_whitespace(self, value: str) -> str:
        """Collapse consecutive whitespace deterministically."""
        return WHITESPACE_PATTERN.sub(" ", value).strip()

    def _split_lines(self, raw_text: str) -> list[str]:
        """Split raw text into normalized non-empty lines."""
        return [self._normalize_whitespace(line) for line in raw_text.splitlines() if self._normalize_whitespace(line)]

    def _extract_sections(self, lines: list[str]) -> dict[str, list[str]]:
        """Group resume lines under deterministic section headers when present."""
        sections: dict[str, list[str]] = {}
        current_section: str | None = None
        for line in lines:
            header_match = SECTION_HEADER_PATTERN.match(line)
            if header_match:
                current_section = SECTION_NAME_MAP.get(header_match.group(1).casefold())
                if current_section is not None:
                    sections.setdefault(current_section, [])
                continue
            if current_section is not None:
                sections.setdefault(current_section, []).append(line)
        return sections

    def _extract_locations(self, lines: list[str], sentences: list[str], entities: dict[str, list[str]]) -> list[str]:
        """Extract location candidates using deterministic priority and filtering."""
        candidates: list[str] = []
        candidates.extend(self._header_location_candidates(lines))
        candidates.extend(self._explicit_location_candidates(lines))
        candidates.extend(entities["locations"])
        candidates.extend(self._section_location_candidates(sentences, EXPERIENCE_KEYWORDS))
        candidates.extend(self._section_location_candidates(sentences, EDUCATION_KEYWORDS))

        valid_candidates = [candidate for candidate in candidates if self._is_valid_location_candidate(candidate)]
        return self._deduplicate(valid_candidates)

    def _header_location_candidates(self, lines: list[str]) -> list[str]:
        """Extract location candidates from the header contact block."""
        candidates: list[str] = []
        header_lines: list[str] = []
        for line in lines[:6]:
            if SECTION_HEADER_PATTERN.match(line):
                break
            header_lines.append(line)

        for line in header_lines:
            scrubbed = EMAIL_PATTERN.sub(" ", line)
            scrubbed = PHONE_PATTERN.sub(" ", scrubbed)
            scrubbed = URL_PATTERN.sub(" ", scrubbed)
            for segment in re.split(r"[|/]", scrubbed):
                if "," in segment:
                    candidates.append(segment.strip(" -,:"))
        return candidates

    def _explicit_location_candidates(self, lines: list[str]) -> list[str]:
        """Extract candidates from explicit location labels."""
        candidates: list[str] = []
        for line in lines:
            for match in LOCATION_LABEL_PATTERN.finditer(line):
                candidates.append(match.group(1).strip(" -,:"))
        return candidates

    def _section_location_candidates(self, sentences: list[str], keywords: tuple[str, ...]) -> list[str]:
        """Extract location candidates from prioritized sections."""
        candidates: list[str] = []
        for sentence in sentences:
            lowered = sentence.casefold()
            if not any(keyword in lowered for keyword in keywords):
                continue
            for match in LOCATION_LABEL_PATTERN.finditer(sentence):
                candidates.append(match.group(1).strip(" -,:"))
            parts = [part.strip() for part in sentence.split(",") if part.strip()]
            if len(parts) >= 2:
                candidates.append(", ".join(parts[-2:]))
        return candidates

    def _is_valid_location_candidate(self, value: str) -> bool:
        """Validate that a candidate looks like a geographic location and not a skill or institution."""
        text = self._normalize_whitespace(value)
        if not text:
            return False
        if any(marker in text.casefold() for marker in ("http://", "https://", "@")):
            return False
        if len(text.split()) > 6:
            return False

        tokens = [token.casefold() for token in LOCATION_TOKEN_PATTERN.findall(text)]
        if not tokens:
            return False
        if all(is_known_skill(token) for token in tokens):
            return False
        if any(token in INSTITUTION_KEYWORDS for token in tokens):
            return False
        if any(token in CERTIFICATION_KEYWORDS for token in tokens):
            return False
        if any(token in DEGREE_KEYWORDS for token in tokens):
            return False
        if len(tokens) == 1 and is_known_skill(tokens[0]):
            return False
        if text.isupper() and len(tokens) <= 2:
            return False
        return any(character.isalpha() for character in text)

    def _extract_field_of_study(self, sentence: str, degree_keyword: str | None) -> str | None:
        """Extract field-of-study text from an education sentence."""
        lowered = sentence.casefold()
        if degree_keyword is None or degree_keyword not in lowered:
            return None
        start_index = lowered.find(degree_keyword) + len(degree_keyword)
        tail = sentence[start_index:]
        tail = re.split(r"\b(?:at|from|in)\b", tail, maxsplit=1, flags=re.IGNORECASE)[0]
        tail = YEAR_PATTERN.split(tail, maxsplit=1)[0]
        normalized = self._normalize_whitespace(tail.strip(" ,:-"))
        if not normalized:
            return None
        if len(normalized.split()) > 6:
            return None
        return normalized

    def _extract_institution(self, sentence: str, organization_candidates: list[str]) -> str | None:
        """Extract an institution from an education line using deterministic delimiters."""
        match = AT_FROM_PATTERN.search(sentence)
        if match:
            institution = self._clean_entity_candidate(match.group("value"))
            if self._is_valid_entity_candidate(institution, entity_kind="institution"):
                return institution

        for candidate in organization_candidates:
            if candidate.casefold() in sentence.casefold():
                cleaned = self._clean_entity_candidate(candidate)
                if self._is_valid_entity_candidate(cleaned, entity_kind="institution"):
                    return cleaned
        return None

    def _parse_experience_line(
        self,
        sentence: str,
        organization_candidates: list[str],
    ) -> tuple[str | None, str | None, str | None]:
        """Parse a structured experience header line into title, organization, and dates."""
        normalized = self._normalize_whitespace(sentence)
        date_range_text = self._first_regex_match(DATE_RANGE_PATTERN, normalized)
        working_text = normalized
        if date_range_text and date_range_text in working_text:
            working_text = working_text.replace(date_range_text, "").strip(" ,-")

        match = TITLE_ORG_PATTERN.match(working_text)
        if match:
            title = self._clean_entity_candidate(match.group("title"))
            organization = self._clean_entity_candidate(match.group("organization"))
            if self._is_valid_entity_candidate(organization, entity_kind="organization"):
                return title, organization, date_range_text or match.group("dates")

        worked_match = WORKED_AT_PATTERN.search(normalized)
        if worked_match:
            organization = self._clean_entity_candidate(worked_match.group("organization"))
            if self._is_valid_entity_candidate(organization, entity_kind="organization"):
                return None, organization, date_range_text or worked_match.group("dates")

        organization = self._first_matching_candidate(normalized, organization_candidates)
        if organization:
            cleaned = self._clean_entity_candidate(organization)
            if self._is_valid_entity_candidate(cleaned, entity_kind="organization"):
                title = self._extract_title_from_experience_line(working_text, cleaned)
                return title, cleaned, date_range_text

        return None, None, date_range_text

    def _extract_title_from_experience_line(self, sentence: str, organization: str) -> str | None:
        """Extract a title from an experience line after organization parsing."""
        lowered_sentence = sentence.casefold()
        organization_index = lowered_sentence.find(organization.casefold())
        if organization_index > 0:
            prefix = sentence[:organization_index].strip(" ,-")
            if prefix and len(prefix.split()) <= 8:
                return prefix
        return None

    def _clean_entity_candidate(self, value: str | None) -> str | None:
        """Trim section spillover and punctuation from extracted entity candidates."""
        if value is None:
            return None
        cleaned = DATE_PREFIX_PATTERN.sub("", value).strip(" ,:-")
        cleaned = re.split(
            r"\b(?:skills|certifications|projects|education|summary|profile|work experience|experience|last updated)\b",
            cleaned,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,:-")
        return self._normalize_whitespace(cleaned) or None

    def _is_valid_entity_candidate(self, value: str | None, entity_kind: str) -> bool:
        """Validate that an extracted institution or organization is not actually a skill-like term."""
        if value is None:
            return False
        tokens = [token.casefold() for token in LOCATION_TOKEN_PATTERN.findall(value)]
        if not tokens:
            return False
        if all(is_known_skill(token) for token in tokens):
            return False
        if any(token in CERTIFICATION_KEYWORDS for token in tokens):
            return False
        if any(token in DEGREE_KEYWORDS for token in tokens):
            return False
        if entity_kind == "institution" and len(tokens) == 1 and is_known_skill(tokens[0]):
            return False
        if entity_kind == "organization" and len(tokens) == 1 and is_known_skill(tokens[0]):
            return False
        return True

    def _deduplicate(self, values: list[str]) -> list[str]:
        """Deduplicate values while preserving order."""
        seen: set[str] = set()
        output: list[str] = []
        for value in values:
            key = value.casefold()
            if not value or key in seen:
                continue
            seen.add(key)
            output.append(value)
        return output


class StructuredFieldExtractor:
    """Extract fields deterministically from structured recruiter candidate records."""

    def extract_many(self, records: Iterable[CandidateRecord]) -> list[ExtractedFields]:
        """Extract fields from multiple structured candidate records."""
        return [self.extract_one(record) for record in records]

    def extract_one(self, record: CandidateRecord) -> ExtractedFields:
        """Extract fields from a single structured recruiter record."""
        self._validate_record(record)
        raw = record.raw_payload
        skills_value = raw.get("skills")
        skills = self._split_skills(skills_value)
        experience = self._build_experience(record)
        organizations = [raw["company"]] if isinstance(raw.get("company"), str) and raw.get("company") else []
        locations = [raw["location"]] if isinstance(raw.get("location"), str) and raw.get("location") else []
        emails = [raw["email"]] if isinstance(raw.get("email"), str) and raw.get("email") else []
        phone_numbers = [raw["phone"]] if isinstance(raw.get("phone"), str) and raw.get("phone") else []

        extracted = ExtractedFields(
            record_id=record.record_id,
            source_name=record.source.source_name,
            source_metadata=record.source.model_copy(deep=True),
            name=raw.get("name"),
            emails=emails,
            phone_numbers=phone_numbers,
            skills=skills,
            education=[],
            experience=experience,
            organizations=organizations,
            locations=locations,
            urls=[],
            sentences=[record.raw_text] if record.raw_text else [],
        )
        LOGGER.info(
            "Extracted structured fields for record_id=%s source=%s",
            record.record_id,
            record.source.source_name,
        )
        return extracted

    def _validate_record(self, record: CandidateRecord) -> None:
        """Validate that the record is a supported structured candidate record."""
        if not isinstance(record, CandidateRecord):
            raise FieldExtractionError("Structured field extraction requires a CandidateRecord instance.")
        if record.source.source_type not in STRUCTURED_SOURCE_TYPES:
            raise FieldExtractionError(
                f"Structured field extraction supports recruiter CSV records only, got '{record.source.source_type.value}'."
            )

    def _split_skills(self, skills_value: object) -> list[str]:
        """Split recruiter CSV skill text deterministically."""
        if not isinstance(skills_value, str):
            return []
        return [canonicalize_skill_name(skill.strip()) for skill in skills_value.split(",") if skill.strip()]

    def _build_experience(self, record: CandidateRecord) -> list[ExtractedExperienceItem]:
        """Build structured experience items from recruiter CSV fields."""
        raw = record.raw_payload
        if not raw.get("company") and not raw.get("title"):
            return []
        return [
            ExtractedExperienceItem(
                text=record.raw_text or "",
                title=raw.get("title"),
                organization=raw.get("company"),
                date_range_text=None,
            )
        ]


def extract_resume_fields(record: CandidateRecord) -> ExtractedFields:
    """Convenience function for extracting fields from one resume record."""
    return ResumeFieldExtractor().extract_one(record)


def extract_resume_fields_batch(records: Iterable[CandidateRecord]) -> list[ExtractedFields]:
    """Convenience function for extracting fields from multiple resume records."""
    return ResumeFieldExtractor().extract_many(records)


def extract_resume_fields_from_path(resume_path: str) -> ExtractedFields:
    """Convenience function for extracting fields from one resume path."""
    return ResumeFieldExtractor().extract_from_path(resume_path)


def extract_resume_fields_from_paths(resume_paths: Iterable[str]) -> list[ExtractedFields]:
    """Convenience function for extracting fields from multiple resume paths."""
    return ResumeFieldExtractor().extract_from_paths(resume_paths)


def extract_structured_fields(record: CandidateRecord) -> ExtractedFields:
    """Convenience function for extracting fields from one structured record."""
    return StructuredFieldExtractor().extract_one(record)


def extract_structured_fields_batch(records: Iterable[CandidateRecord]) -> list[ExtractedFields]:
    """Convenience function for extracting fields from multiple structured records."""
    return StructuredFieldExtractor().extract_many(records)


__all__ = [
    "ResumeFieldExtractor",
    "StructuredFieldExtractor",
    "extract_resume_fields",
    "extract_resume_fields_batch",
    "extract_resume_fields_from_path",
    "extract_resume_fields_from_paths",
    "extract_structured_fields",
    "extract_structured_fields_batch",
]
