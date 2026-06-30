"""Static skill dictionary and canonicalization helpers."""

from __future__ import annotations

import re


SKILL_DICTIONARY: dict[str, tuple[str, ...]] = {
    "programming_languages": (
        "Python",
        "Java",
        "JavaScript",
        "TypeScript",
        "C++",
        "C#",
        "Go",
        "Scala",
        "Ruby",
        "PHP",
        "R",
    ),
    "data": (
        "SQL",
        "Pandas",
        "NumPy",
        "Spark",
        "Hadoop",
        "Airflow",
        "dbt",
        "Snowflake",
        "Redshift",
        "Tableau",
        "Power BI",
    ),
    "cloud_devops": (
        "AWS",
        "Azure",
        "GCP",
        "Docker",
        "Kubernetes",
        "Terraform",
        "Jenkins",
        "GitHub Actions",
    ),
    "backend_platform": (
        "Node.js",
        "Express.js",
        "Spring Boot",
        "Microservices",
        "MongoDB",
        "Redux",
        "React",
    ),
    "ml_ai": (
        "Machine Learning",
        "Deep Learning",
        "PyTorch",
        "TensorFlow",
        "Scikit-Learn",
        "NLP",
        "spaCy",
    ),
}

SKILL_ALIASES: dict[str, str] = {
    "python": "Python",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "c++": "C++",
    "c#": "C#",
    "go": "Go",
    "scala": "Scala",
    "ruby": "Ruby",
    "php": "PHP",
    "r": "R",
    "sql": "SQL",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "spark": "Spark",
    "hadoop": "Hadoop",
    "airflow": "Airflow",
    "dbt": "dbt",
    "snowflake": "Snowflake",
    "redshift": "Redshift",
    "tableau": "Tableau",
    "power bi": "Power BI",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "terraform": "Terraform",
    "jenkins": "Jenkins",
    "github actions": "GitHub Actions",
    "react": "React",
    "redux": "Redux",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "node js": "Node.js",
    "express.js": "Express.js",
    "expressjs": "Express.js",
    "express js": "Express.js",
    "spring boot": "Spring Boot",
    "microservices": "Microservices",
    "mongodb": "MongoDB",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "scikit-learn": "Scikit-Learn",
    "scikit learn": "Scikit-Learn",
    "sklearn": "Scikit-Learn",
    "nlp": "NLP",
    "spacy": "spaCy",
}

SKILL_ALIAS_MAP: dict[str, str] = {alias.casefold(): canonical for alias, canonical in SKILL_ALIASES.items()}
CANONICAL_SKILL_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(skill for category_skills in SKILL_DICTIONARY.values() for skill in category_skills)
)
ALL_SKILLS: tuple[str, ...] = CANONICAL_SKILL_NAMES
SKILL_LOOKUP_TERMS: tuple[str, ...] = tuple(sorted(SKILL_ALIAS_MAP.keys(), key=len, reverse=True))


def canonicalize_skill_name(value: str) -> str:
    """Return the canonical skill name when the value is known."""
    normalized = value.strip()
    canonical = SKILL_ALIAS_MAP.get(normalized.casefold())
    if canonical:
        return canonical
    return normalized


def is_known_skill(value: str) -> bool:
    """Return whether a value is a known canonical or alias skill string."""
    return value.strip().casefold() in SKILL_ALIAS_MAP


def extract_canonical_skills(text: str) -> list[str]:
    """Extract canonical skills from free text using deterministic alias matching."""
    lowered = f" {text.casefold()} "
    matches: list[str] = []
    seen: set[str] = set()
    for term in SKILL_LOOKUP_TERMS:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        if not re.search(pattern, lowered, flags=re.IGNORECASE):
            continue
        canonical = SKILL_ALIAS_MAP[term]
        key = canonical.casefold()
        if key in seen:
            continue
        seen.add(key)
        matches.append(canonical)
    return matches
