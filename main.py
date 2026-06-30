"""Application entry point for the candidate transformation pipeline."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

from pipeline.orchestrator import CandidateTransformationPipeline
from utils.exceptions import PipelineError


LOGGER = logging.getLogger(__name__)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for pipeline execution."""
    parser = argparse.ArgumentParser(description="Run the deterministic candidate transformation pipeline.")
    parser.add_argument(
        "--config",
        default=os.environ.get("PIPELINE_CONFIG_PATH"),
        help="Path to the pipeline configuration JSON file.",
    )
    parser.add_argument("--csv", help="Override the recruiter CSV input path.")
    parser.add_argument("--resumes", help="Override the resume input directory.")
    parser.add_argument("--output", help="Override the output JSON path.")
    return parser


def resolve_config_path(config_argument: str | None) -> Path:
    """Resolve the effective pipeline configuration path."""
    project_root = Path(__file__).resolve().parent
    if config_argument:
        return Path(config_argument)
    return project_root / "config" / "pipeline_config.json"


def build_config_overrides(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    """Build config overrides from CLI arguments."""
    overrides: dict[str, dict[str, Any]] = {}
    if args.csv or args.resumes:
        overrides["input"] = {}
        if args.csv:
            overrides["input"]["recruiter_csv_path"] = args.csv
        if args.resumes:
            overrides["input"]["resume_directory"] = args.resumes
    if args.output:
        overrides["output"] = {"output_json_path": args.output}
    return overrides


def main(argv: list[str] | None = None) -> int:
    """Initialize logging, run the pipeline, and exit gracefully."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    config_path = resolve_config_path(args.config)
    config_overrides = build_config_overrides(args)

    try:
        pipeline = CandidateTransformationPipeline(
            config_path=config_path,
            config_overrides=config_overrides,
        )
        pipeline.run()
        return 0
    except PipelineError as exc:
        LOGGER.exception("Pipeline failed: %s", exc)
        return 1
    except Exception as exc:
        LOGGER.exception("Unexpected fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
