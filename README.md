# Multi-Source Candidate Data Transformer

## Overview

The **Multi-Source Candidate Data Transformer** consolidates candidate information from multiple data sources into a single canonical candidate profile.

The system processes structured and unstructured candidate data, validates the input, extracts candidate information, normalizes values, resolves duplicate candidates, merges conflicting information, tracks provenance, calculates confidence scores, and generates a validated JSON output.


---


## Tech Stack

- Python 3.11
- Pydantic
- pdfplumber
- python-docx
- spaCy
- dateparser
- pytest


---


### Supported Input Sources

- Recruiter CSV
- PDF Resume
- DOCX Resume

---

# Pipeline Flow

```
Recruiter CSV + Resume (PDF/DOCX)
                │
                ▼
         Source Readers
                │
                ▼
        Input Validation
                │
                ▼
        Field Extraction
                │
                ▼
       Canonical Mapping
                │
                ▼
         Normalization
                │
                ▼
      Identity Resolution
                │
                ▼
      Conflict Resolution
                │
                ▼
          Provenance
                │
                ▼
      Confidence Scoring
                │
                ▼
     Runtime Projection
                │
                ▼
      Output Validation
                │
                ▼
         output.json
```

---

# Project Structure

```
multi-source-candidate-data-transformer/
│
├── config/
│   ├── pipeline_config.json
│   └── projection_config.json
│
├── data/
│   ├── input/
│   │   ├── recruiter.csv
│   │   └── resumes/
│   └── output/
│
├── models/
├── pipeline/
├── tests/
├── utils/
│
├── main.py
├── requirements.txt
└── README.md
```

---



# Installation

Clone the repository


**Prerequisite:** Python 3.11 or later

```bash
git clone https://github.com/UJJWAL2282/Multi-Source-Candidate-Data-Transformer.git
```

Move to the project directory

```bash
cd "CANDIDATE-TRANSFORMATION-PIPELINE"
```

Create a virtual environment

```bash
python -m venv .venv
```

Activate the virtual environment

### Windows

```bash
.venv\Scripts\activate
```

### Linux / macOS

```bash
source .venv/bin/activate
```

Install dependencies

```bash
pip install -r requirements.txt
```

Download the spaCy English model

```bash
python -m spacy download en_core_web_sm
```

---

# Input

Place the recruiter CSV file in

```
data/input/recruiter.csv
```

Place all resumes in

```
data/input/resumes/
```

Supported resume formats

- PDF
- DOCX

---

# Configuration

Pipeline configuration

```
config/pipeline_config.json
```

Projection configuration

```
config/projection_config.json
```

The output schema can be customized through the projection configuration without modifying the pipeline implementation.

---

# Running the Project

Run using the default configuration

```bash
python main.py
```

Run using a configuration file

```bash
python main.py --config config/pipeline_config.json
```

Run with custom input and output paths

```bash
python main.py --csv data/input/recruiter.csv --resumes data/input/resumes --output data/output/output.json
```


After successful execution, the generated output is written to: data/output/output.json

---


## Sample Dataset

The repository includes sample input files used for testing:


```text
data/input/
├── recruiter.csv
└── resumes/
    ├── Aarav Sharma.pdf
    ├── Aarav SharmaD.pdf
    ├── Priya Verma.pdf
    └── Rahul Singh.pdf
```


---


## Sample Output

Running the pipeline on the provided sample dataset generates:

```
data/output/output.json
```

Example candidate record:

```json
{
  "candidate_id": "master::group::email_match::aarav.sharma_at_gmail.com",
  "full_name": "Aarav Sharma",
  "email": "aarav.sharma@gmail.com",
  "phone": "+919876543210",
  "current_title": "Software Engineer",
  "location": "Bengaluru",
  "skills": [
    "Java",
    "Python",
    "SQL",
    "AWS",
    "Docker",
    "Spring Boot",
    "Kubernetes",
    "Azure",
    "Microservices",
    "Node.js",
    "MongoDB",
    "JavaScript",
    "React"
  ],
  "confidence_score": 0.79
}
```

The complete output generated from the sample inputs is available in:

```
data/output/output.json
```



Each generated candidate record contains the following fields:

- Candidate ID
- Full Name
- Email
- Phone
- Current Title
- Location
- Skills
- Confidence Score
- Provenance

---

# Running Tests

Run all tests

```bash
pytest
```

Run with detailed output

```bash
pytest -v
```

---

# Dependencies

- Python 3.11+
- pydantic
- pdfplumber
- python-docx
- spacy
- dateparser
- pytest

---

# Features

- Supports multiple candidate data sources
- Extracts structured candidate information
- Maps data into a canonical candidate model
- Normalizes candidate information
- Resolves duplicate candidates
- Merges conflicting field values
- Tracks provenance for every output field
- Computes confidence scores
- Supports configurable output projection
- Validates the final JSON output

---

# Assumptions

- Recruiter CSV follows the expected format.
- Resume files are provided in PDF or DOCX format.
- Duplicate candidates are identified using deterministic matching rules.
- Output fields are configured through `projection_config.json`.

---

## Notes

- The pipeline supports runtime configuration through `pipeline_config.json`.
- Output fields can be customized using `projection_config.json`.
- The repository includes sample input files and the generated output for evaluation.