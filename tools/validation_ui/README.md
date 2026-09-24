# Validation UI

Standalone HTML page (German) for reviewing an export by hand: merge candidates,
norm-data links (GBIF, Wikidata, GND, GeoNames, EUNIS), QA flags and per-entry
corrections of misread species/place names. Every item shows the diary passages
where the name occurs and a link to the page scan on Google Drive.

The page runs from a local file (no server). Decisions are kept in the browser
(localStorage) and exported as a ZIP whose `review/*.csv` files have the
pipeline's review format:

| file in the ZIP | goes to | read by |
|---|---|---|
| `review/{taxon,person,place,habitat}_merges.csv` | `data/review/` | `resolution.*.reviewed_csv` |
| `review/{place,habitat}_link_review.csv` | `data/review/` | `linking.*.reviewed_csv` (y/n, corrected rows) |
| `review/{taxon,person}_link_review.csv` | `data/review/` | `linking.*.reviewed_csv` (y rows; persons: `qid` and/or `gnd`) |
| `review/value_corrections.csv` | `data/review/` | `corrections.csv` (applied before QA) |
| `review/qa_flags.csv` | — | not read by the pipeline yet (decision + correction columns) |

Merge decisions already present in the export's `review/reviewed/` (the
machine-adjudicated baseline) are kept unless the reviewer decides otherwise.

## Build

The page is built from one export folder (`rdf/laubmann_sample.ttl` + `review/`):

```bash
python tools/validation_ui/load.py <export>/rdf/laubmann_sample.ttl triples.pkl      # ~70 s
python tools/validation_ui/build_payload.py <export>/review --triples triples.pkl --built 2026-09-24
python tools/validation_ui/assemble.py payload.b64 HistOrniGraph_Validierung.html
```

`drive_pages.json` maps page ids to the Drive file ids of
`HistOrniGraph_output/Laubmann_XX_gemini/pages/<page id>.png`. Scan previews
only load for Google accounts with access to that folder. The built page
contains the full entry texts; it is not committed.

Live lookups (GBIF, Wikidata, lobid GND, Nominatim) and the Esri basemap need
network access; everything else works offline.

## Smoke tests

Playwright + Chromium, not part of the pytest suite:

```bash
pip install playwright && playwright install chromium
HOG_UI=HistOrniGraph_Validierung.html python tools/validation_ui/tests/smoke_basic.py
```

`smoke_corrections.py`, `smoke_normdata.py` and `smoke_lookups.py` cover value
corrections, norm-data search/export and the live APIs.
