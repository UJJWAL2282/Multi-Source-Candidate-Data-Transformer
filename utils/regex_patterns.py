"""Reusable regex patterns for deterministic field extraction."""

from __future__ import annotations

import re


EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d().\-\s]{7,}\d)")
URL_PATTERN = re.compile(r"\b(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
DATE_RANGE_PATTERN = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}\s*[-to]+\s*"
    r"(?:(?:present|current)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)
