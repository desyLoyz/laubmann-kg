"""Typer CLI for the Laubmann knowledge graph pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer

from laubmann_kg import diary, dwca, evaluation, extraction, kg, layout, preprocessing, transcription
from laubmann_kg.logging_config import setup_logging

app = typer.Typer(
    name="laubmann-kg",
    help="Laubmann knowledge graph processing pipeline.",
    no_args_is_help=True,
)


def _run_stage(
    stage: Callable[[Path, Path, Path], None],
    config: Path,
    input_dir: Path,
    output_dir: Path,
) -> None:
    setup_logging()
    stage(config=config, input_dir=input_dir, output_dir=output_dir)


@app.command("preprocess")
def preprocess_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Preprocess input materials."""
    _run_stage(preprocessing.run, config, input_dir, output_dir)


@app.command("detect-layout")
def detect_layout_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Detect page layout in source documents."""
    _run_stage(layout.run, config, input_dir, output_dir)


@app.command("detect-entries")
def detect_entries_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Detect individual entries within layout regions."""
    _run_stage(diary.run, config, input_dir, output_dir)


@app.command("transcribe")
def transcribe_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Transcribe text from detected entries."""
    _run_stage(transcription.run, config, input_dir, output_dir)


@app.command("extract-observations")
def extract_observations_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Extract structured observations from transcriptions."""
    _run_stage(extraction.run, config, input_dir, output_dir)


@app.command("export-jsonld")
def export_jsonld_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Export observations as JSON-LD."""
    _run_stage(kg.run, config, input_dir, output_dir)


@app.command("export-dwca")
def export_dwca_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Export observations as Darwin Core Archive."""
    _run_stage(dwca.run, config, input_dir, output_dir)


@app.command("evaluate")
def evaluate_cmd(
    config: Path = typer.Option(..., "--config", help="Path to the pipeline config file."),
    input_dir: Path = typer.Option(..., "--input-dir", help="Directory containing input files."),
    output_dir: Path = typer.Option(..., "--output-dir", help="Directory for output files."),
) -> None:
    """Evaluate pipeline outputs against reference data."""
    _run_stage(evaluation.run, config, input_dir, output_dir)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
