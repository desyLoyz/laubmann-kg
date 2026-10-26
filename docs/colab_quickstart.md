# Colab quickstart — build the KG for one volume end-to-end

Runs the corpus → knowledge-graph → Darwin Core Archive pipeline for a single
volume (default: Vol. 2) on Google Colab. The corpus files themselves are **not**
in the repo (they are large and gitignored); you supply `entries.csv` and
`multimodal.md` from your Google Drive.

## 1. Clone and install

```python
# Colab cell
!git clone https://github.com/desyLoyz/laubmann-kg.git
%cd laubmann-kg_TP
!pip -q install -e .
```

## 2. Provide the corpus (from Google Drive)

Mount Drive and copy the two files into `data/corpus/`. Rename them to exactly
`entries.csv` and `multimodal.md` if they have different names on Drive.

```python
from google.colab import drive
drive.mount('/content/drive')

import shutil, pathlib
pathlib.Path('data/corpus').mkdir(parents=True, exist_ok=True)
# adjust these two source paths to where the files live on your Drive:
shutil.copy('/content/drive/MyDrive/laubmann/entries.csv',    'data/corpus/entries.csv')
shutil.copy('/content/drive/MyDrive/laubmann/multimodal.md',  'data/corpus/multimodal.md')
```

(Alternatively, use the Colab file uploader: `from google.colab import files; files.upload()`
and move the files into `data/corpus/`.)

## 3. Choose the volume

`configs/sample.yaml` builds Vol. 2 by default. To build a different clean
volume, edit `sample.volume`; set it to `null` to build the whole corpus.

```python
# optional: build a different volume
!sed -i 's/^  volume: 2/  volume: 2/' configs/sample.yaml   # change the number here
```

## 4. Run both exports

```python
# Knowledge graph (Turtle + JSON-LD, SHACL-validated) + Darwin Core Archive
# (event + occurrence + measurementOrFact + multimedia, zipped) from one pipeline run
!laubmann-kg export-all --config configs/sample.yaml --input-dir data/corpus --output-dir data/exports
# (export-jsonld / export-dwca produce just one of the two)
```

Outputs land in:

- `data/exports/rdf/laubmann_sample.ttl`
- `data/exports/jsonld/laubmann_sample.jsonld`
- `data/exports/dwca/laubmann_sample_dwca.zip`

## 5. Inspect / download

```python
from laubmann_kg.kg.sparql import load_graph, run_query
g = load_graph('data/exports/rdf/laubmann_sample.ttl')
for row in run_query(g, 'CQ1_species_frequency')[:15]:
    print(row['n'], row['vernacular'])

from google.colab import files
files.download('data/exports/dwca/laubmann_sample_dwca.zip')
```

## LLM extraction backend (Gemini)

The default build uses deterministic rule-based extraction. To use Gemini instead
(higher recall on rare species, extracts counts/behaviour the rules miss):

```python
# install the Gemini SDK and set your key
!pip -q install -e ".[llm]"
import os
os.environ['GOOGLE_API_KEY'] = 'YOUR_API_KEY'   # from https://aistudio.google.com/apikey

# run with the LLM config (adjust extraction.model to an available Gemini model)
!laubmann-kg export-all --config configs/sample_llm.yaml --input-dir data/corpus --output-dir data/exports
```

- Calls run at temperature 0 and are cached under `data/cache/llm/`, so re-runs
  are free and reproducible. Mount that folder to Drive to persist the cache
  across Colab sessions.
- One LLM call per entry (~233 for Vol. 2), so a full-volume run is cheap.
- Scientific names the model returns are kept, but a taxon IRI is only taken from
  the resolver — the model never invents IRIs. Names it cannot resolve keep the
  verbatim German term with an uncertainty note.
- Tune quality by editing `prompts/observation_extraction.md` (add few-shot
  examples from real entries), or set `extraction.model` to a stronger model
  (e.g. `gemini-1.5-pro`) in `configs/sample_llm.yaml`.

## Notes

- The default build is deterministic and offline (rule-based extraction, no API key).
- SHACL warnings for entries with no matched bird name are expected (weather- or
  travel-only entries); they are warnings, not errors.
- To resolve taxa via the Vol. 35 index linker later, set `taxa.links_long_path`
  in the config to the linker's `links_long` table. See `INTERFACES.md`.
