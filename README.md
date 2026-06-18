# laubmann-kg

Pipeline for digitizing, transcribing, and publishing the Laubmann ornithological diary as a knowledge graph and Darwin Core Archive.

## Layout

- `configs/` — pipeline, model, ontology, DwC-A, and prompt configuration
- `data/` — raw scans, processed images, annotations, exports, and LLM cache
- `docs/` — methodology, data model, and evaluation documentation
- `prompts/` — LLM prompt templates per pipeline stage
- `schemas/` — JSON schemas for intermediate and export artifacts
- `ontologies/` — project ontology and SHACL shapes
- `src/laubmann_kg/` — Python package
- `scripts/` — stage runner scripts
- `tests/` — unit and integration tests

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## CLI

```bash
laubmann-kg --help
laubmann-kg preprocess --config configs/pipeline.yaml --input-dir data/raw/vol01/images --output-dir data/processed/vol01/images
```

## Pipeline stages

1. `preprocess` — split, deskew, enhance, and crop page images
2. `detect-layout` — detect layout regions and reading order
3. `detect-entries` — detect and link diary entries
4. `transcribe` — transcribe text from regions
5. `extract-observations` — extract structured observations
6. `export-jsonld` — export JSON-LD knowledge graph
7. `export-dwca` — export Darwin Core Archive
8. `evaluate` — compare outputs to gold annotations
