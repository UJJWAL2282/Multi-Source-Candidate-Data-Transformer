from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

try:
    import docx
except ModuleNotFoundError:
    docx = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.orchestrator import CandidateTransformationPipeline


def _write_docx(path: Path, lines: list[str]) -> None:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(path)


def _write_minimal_pdf(path: Path, text: str) -> None:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    pdf = [
        "%PDF-1.4\n",
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n",
        f"4 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj\n",
        "5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    offsets = []
    body = ""
    for part in pdf:
        offsets.append(len(body))
        body += part
    xref_start = len(body)
    xref = "xref\n0 6\n0000000000 65535 f \n"
    for offset in offsets:
        xref += f"{offset:010d} 00000 n \n"
    trailer = "trailer << /Root 1 0 R /Size 6 >>\nstartxref\n" + str(xref_start) + "\n%%EOF"
    path.write_text(body + xref + trailer, encoding="utf-8")


def _build_test_files(
    base_dir: Path,
    include_docx: bool,
    include_empty_docx: bool,
) -> tuple[Path, Path, Path, Path]:
    config_dir = base_dir / "config"
    input_dir = base_dir / "data" / "input"
    output_dir = base_dir / "data" / "output"
    resume_dir = input_dir / "resumes"
    config_dir.mkdir(parents=True, exist_ok=True)
    resume_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    recruiter_csv = input_dir / "recruiter.csv"
    recruiter_csv.write_text(
        "\n".join(
            [
                "name,email,phone,company,title,skills,location",
                "Jane Doe,jane.doe@example.com,+1 (415) 555-0101,Acme,Senior Data Engineer,\"Python, SQL, AWS\",\"San Francisco, United States\"",
                "Jane Doe,jane.doe@example.com,,Acme,Lead Data Engineer,\"Python, Docker\",\"San Francisco, United States\"",
                "John Smith,,+1 (646) 555-0199,Globex,ML Engineer,\"Python, Spark\",\"New York, United States\"",
                "Broken Row,junk@example.com",
            ]
        ),
        encoding="utf-8",
    )

    if include_docx:
        _write_docx(
            resume_dir / "jane_resume.docx",
            [
                "Jane Doe",
                "Senior Data Engineer",
                "Email: jane.doe@example.com",
                "Phone: +1 415 555 0101",
                "Skills: Python, SQL, AWS, Docker",
                "Worked at Acme Technologies from Jan 2020 - Present",
                "University of California",
                "San Francisco, United States",
                "https://www.linkedin.com/in/janedoe",
            ],
        )
        _write_docx(
            resume_dir / "jane_resume_duplicate.docx",
            [
                "Jane Doe",
                "Lead Data Engineer",
                "Email: jane.doe@example.com",
                "Phone: +1 415 555 0101",
                "Skills: Python, Kubernetes",
                "Worked at Acme Technologies from Jan 2020 - Present",
            ],
        )
    if include_empty_docx:
        _write_docx(resume_dir / "empty_resume.docx", [])

    _write_minimal_pdf(
        resume_dir / "john_resume.pdf",
        "John Smith Email john.smith@example.com Phone +1 646 555 0199 Skills Python Spark Docker New York",
    )
    (resume_dir / "corrupted_resume.pdf").write_text("not a real pdf", encoding="utf-8")

    projection_config = config_dir / "projection_config.json"
    projection_config.write_text(
        json.dumps(
            {
                "field_selection": [
                    "master_candidate_id",
                    "canonical_profile.full_name",
                    "canonical_profile.contact.email",
                    "canonical_profile.contact.phone",
                    "canonical_profile.headline",
                    "canonical_profile.location.raw_location",
                    "canonical_profile.skills",
                ],
                "field_renames": {
                    "master_candidate_id": "candidate_id",
                    "canonical_profile.headline": "current_title",
                    "canonical_profile.location.raw_location": "location",
                },
                "include_confidence": True,
                "include_provenance": True,
                "missing_value_policy": "omit",
                "ordering": [
                    "candidate_id",
                    "full_name",
                    "email",
                    "phone",
                    "current_title",
                    "location",
                    "skills",
                    "confidence_score",
                    "provenance",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    pipeline_config = config_dir / "pipeline_config.json"
    pipeline_config.write_text(
        json.dumps(
            {
                "input": {
                    "recruiter_csv_path": str(recruiter_csv),
                    "resume_directory": str(resume_dir),
                },
                "output": {
                    "output_json_path": str(output_dir / "output.json"),
                },
                "projection": {
                    "config_path": str(projection_config),
                },
                "logging": {
                    "level": "INFO",
                },
                "processing": {
                    "batch_size": 2,
                },
                "sources": {
                    "enable_recruiter_csv": True,
                    "enable_resumes": True,
                    "github": False,
                    "linkedin": False,
                    "ats_json": False,
                },
                "output_validation": {
                    "required_fields": ["candidate_id"],
                    "allow_unknown_fields": True,
                    "pretty": True,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return pipeline_config, recruiter_csv, resume_dir, output_dir / "output.json"


def test_pipeline_runs_with_csv_and_pdf_without_docx_dependency(tmp_path: Path) -> None:
    config_path, _, _, output_path = _build_test_files(
        tmp_path,
        include_docx=False,
        include_empty_docx=False,
    )

    pipeline = CandidateTransformationPipeline(config_path=config_path)
    result_path = pipeline.run()

    assert result_path == output_path
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) >= 2
    assert all("candidate_id" in record for record in payload)
    assert any(record.get("full_name") == "John Smith" for record in payload)
    assert any(record.get("confidence_score") is not None for record in payload)


@pytest.mark.skipif(docx is None, reason="python-docx is required for DOCX-specific integration tests.")
def test_pipeline_merges_duplicate_candidates_from_docx_and_csv(tmp_path: Path) -> None:
    config_path, _, _, output_path = _build_test_files(
        tmp_path,
        include_docx=True,
        include_empty_docx=False,
    )

    pipeline = CandidateTransformationPipeline(config_path=config_path)
    pipeline.run()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    jane_records = [record for record in payload if record.get("full_name") == "Jane Doe"]
    assert len(jane_records) == 1
    jane_record = jane_records[0]
    skill_names = {
        skill["name"] if isinstance(skill, dict) else skill
        for skill in jane_record.get("skills", [])
    }
    assert {"Python", "SQL", "AWS"} & skill_names
    assert jane_record.get("provenance")


@pytest.mark.skipif(docx is None, reason="python-docx is required for DOCX-specific integration tests.")
def test_pipeline_skips_empty_docx_and_corrupted_pdf(tmp_path: Path) -> None:
    config_path, _, resume_dir, output_path = _build_test_files(
        tmp_path,
        include_docx=True,
        include_empty_docx=True,
    )

    pipeline = CandidateTransformationPipeline(config_path=config_path)
    pipeline.run()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    processed_source_names = {
        entry["source_name"]
        for record in payload
        for entry in record.get("provenance", [])
        if isinstance(entry, dict) and "source_name" in entry
    }
    assert "corrupted_resume.pdf" not in processed_source_names
    assert "empty_resume.docx" not in processed_source_names
    assert (resume_dir / "john_resume.pdf").exists()
