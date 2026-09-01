# laubmann-kg

Pipeline for digitizing, transcribing, and publishing the Laubmann ornithological diary as a knowledge graph and Darwin Core Archive.

## Layout

- `configs/` — pipeline, model, ontology, DwC-A, and prompt configuration
- `HistOrniGraph_addons/` — corpus builder (`build_corpus.py`, `laubmann_corpus/`) and page-dedup toolchain (`dedup/`)
- `notebooks/` — evaluation notebooks + Colab workflows (`07_full_workflow_colab.ipynb` runs corpus → dedup → KG for all 34 volumes)
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

## Sample range (ontology / prompt review)

Place the corpus CSV at `data/corpus/entries.csv` (not under `data/review/`).
Default extractor is Gemini (`prompts/observation_extraction.md`), same as the
full run. Requires `pip install -e ".[dev,llm]"` and `GOOGLE_API_KEY` in `.env` (loaded
automatically from the project directory). Edit the inclusive `entry_id_from` /
`entry_id_to` in `configs/sample_range.yaml`, then:

```bash
laubmann-kg export-all \
  --config configs/sample_range.yaml \
  --input-dir data/corpus \
  --output-dir data/exports/sample_runs/llm-L02-e0001-e0020
```

Calls are cached under `data/cache/llm_sample`. For a network-free gazetteer
pass use `configs/sample_range_offline.yaml`. Open `tools/Laubmann-KG_Explorer.html`,
load each run’s `html/graph.json` as A and B, and switch to **compare**.

## CLI

```bash
laubmann-kg --help
laubmann-kg preprocess --config configs/pipeline.yaml --input-dir data/raw/vol01/images --output-dir data/processed/vol01/images
```

## Full 34-volume workflow (Colab)

Open `notebooks/07_full_workflow_colab.ipynb` in Colab. It mounts Drive and runs:

1. **Corpus build** — `HistOrniGraph_addons/build_corpus.py` over the `Laubmann_NN_gemini/` region JSONs
2. **Dedup** — `dedup/detect_duplicates.py` → human review via `review.html` → `dedup/apply_dedup.py` writes `corpus_*_dedup/` (non-destructive, manifest of every dropped page)
3. **Knowledge graph** — `laubmann-kg export-all --config configs/full_llm.yaml --input-dir <corpus_dedup> --output-dir <exports>` (Gemini extraction → volume-coverage date repair → QA → GBIF/Wikidata linking + georeferencing (Nominatim/GeoNames/Wikidata) → entity resolution → EUNIS habitat classes → RDF/JSON-LD + SHACL + Darwin Core Archive from one pipeline run; resumable via the on-Drive LLM cache; `export-jsonld` / `export-dwca` still produce one of the two)

## Pipeline stages

1. `preprocess` — split, deskew, enhance, and crop page images
2. `detect-layout` — detect layout regions and reading order
3. `detect-entries` — detect and link diary entries
4. `transcribe` — transcribe text from regions
5. `extract-observations` — extract structured observations
6. `export-jsonld` — export the RDF/JSON-LD knowledge graph (SHACL-validated)
7. `export-dwca` — export the Darwin Core Archive
8. `export-all` — both from one pipeline run (consistent graph and archive)
9. `evaluate` — compare outputs to gold annotations
