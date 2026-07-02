# Changelog

Alle wesentlichen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added

- Python-Paket `laubmann_kg` mit `src`-Layout und `pyproject.toml` (Hatchling, Python ≥ 3.10)
- Typer-CLI `laubmann-kg` mit acht Pipeline-Befehlen: `preprocess`, `detect-layout`, `detect-entries`, `transcribe`, `extract-observations`, `export-jsonld`, `export-dwca`, `evaluate`
- Gemeinsame CLI-Optionen `--config`, `--input-dir`, `--output-dir` für alle Stages
- Paketstruktur mit Modulen für `io`, `preprocessing`, `llm`, `layout`, `diary`, `transcription`, `extraction`, `normalization`, `kg`, `dwca`, `evaluation` und `review`
- Stage-Orchestrierung über `run(config, input_dir, output_dir)` in den jeweiligen Subpackages
- Zentrale Logging-Konfiguration (`logging_config.py`) mit strukturierten Log-Ausgaben
- Konfigurationsdateien unter `configs/` (`pipeline.yaml`, `models.yaml`, `ontology.yaml`, `dwca.yaml`, `prompts.yaml`)
- Datenverzeichnis-Struktur unter `data/` (raw, processed, annotations, exports, cache) mit `.gitkeep`
- Dokumentations-Stubs unter `docs/`
- Prompt-Vorlagen unter `prompts/`
- JSON-Schema-Stubs unter `schemas/`
- Ontologie-Stubs unter `ontologies/` (Turtle)
- Jupyter-Notebooks für Exploration und Evaluation unter `notebooks/`
- Stage-Runner-Skripte unter `scripts/`
- Erste Tests unter `tests/` (Schema-Validierung, Placeholder für Export-Stages)
- `README.md`, `.gitignore`, `.env.example`
- Dev-Abhängigkeiten: `pytest` (optional via `[dev]`)

### Changed

- Flache Stage-Module (`preprocess.py`, `detect_layout.py` usw.) in thematische Subpackages überführt
- CLI importiert Stage-Funktionen aus den neuen Subpackages (`preprocessing`, `layout`, `diary` usw.)
- `.cursorrules`: Regel ergänzt, dass der Nutzer Commits selbst pusht

## [0.1.0] - 2026-06-18

### Added

- Erstes Projekt-Scaffolding und CLI-Grundgerüst

[Unreleased]: https://github.com/desyLoyz/laubmann-kg/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/desyLoyz/laubmann-kg/releases/tag/v0.1.0
