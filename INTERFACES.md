# Interfaces

Two upstream contracts this builder depends on. A later run against the
deduplicated corpus and the real index-linker output should be a **config
change**, not a code change. Loaders use tolerant `.get()` access so extra or
missing optional columns do not break the pipeline.

## 1. Corpus interface (HistOrniGraph → laubmann-kg)

Configured via `corpus.entries` and `corpus.multimodal` in `configs/sample.yaml`
(or `--input-dir` pointing at a directory containing `entries.csv`).

### `entries.csv` — one row per detected diary entry

Primary key: `entry_uid` (e.g. `e_11a2c65ce9d1`). Join keys: `page_uid`
(`p_...`), `region_uid` (`r_...`).

**Columns present in the delivered sample** (verified against the 34-volume,
11,218-entry corpus of 2026-07-22):

```
entry_id, volume, scan, page_id, image, region_id, region_type,
reading_order, date_raw, date_norm, year, location_raw, variant,
n_chars, n_words, preview, text_clean, entry_uid, page_uid, region_uid,
month_source, year_form, loc_source
```

`text_clean` is the extraction input; hyphenated line breaks are already joined.

A 34-volume dump belongs at `data/corpus/entries.csv` (gitignored), not in
`data/review/` (that directory is the linking/QA decision tables). Subsets are
selected in config, not by copying a second CSV:

```
sample:
  volume: 2                 # optional; null = all volumes
  entry_id_from: L02-e0001  # inclusive, Lxx-eNNNN string order
  entry_id_to: L02-e0020
  entry_ids: [L02-e0001]    # optional explicit list (intersects the range)
  offset: 0
  limit: 0                  # 0 = no cap; still the smoke-test "first N"
```

See `configs/sample_range.yaml` (Gemini `observation_extraction` by default;
`configs/sample_range_offline.yaml` for the rule-based gazetteer). Each export
writes `html/graph.json` for the explorer (`tools/Laubmann-KG_Explorer.html`).

**Deltas from the frozen contract in the task brief** (handled, not blocking):

- Delivered file has `preview`; the brief did not list it. Ignored by the loader.
- Brief lists `stream_start`, `stream_end`, `text_raw`; these are **absent** in
  the delivered CSV. The loader falls back `text_clean → text_raw → ""`, so a
  deduped corpus that (re)adds `text_raw` needs no change.
- The brief also referenced `entries.jsonl`; only `entries.csv` was delivered.

### Multimodal regions

Delivered as `multimodal.md` (a Markdown catalogue; structured fields live in its
`<!-- mm ... -->` HTML comments). The loader (`io/metadata.py`) also accepts a
`multimodal.csv` per the frozen contract. Fields consumed:
`region_uid, page_uid, region_type, reading_order, insert_id, insert_state,
entry_uid, volume, scan, crop, description, visible_text`. Join to observations
is by `entry_uid`; `crop` is the image path used as the DwC-A media identifier.

## 2. Index-linker interface (`links_long`)

Configured via `taxa.links_long_path` (default `null` → offline seed gazetteer).
Consumed by `normalization/taxa.LinksLongTaxonResolver`. Documented columns:

```
species (German headword), resolved_corpus_page (page_uid),
reference_source ∈ {index_validated, index_resolved_unvalidated,
                    index_unresolved, index_no_refs, corpus_recall},
nom_match_method, nom_score, nom_ambiguous, resolve_method,
resolve_confidence, scientific_name, author_year, terra_typica, taxon_iri
```

Resolution policy:

- Only `reference_source ∈ {index_validated, index_resolved_unvalidated}` yields
  a scientific name / taxon IRI from the table.
- Other sources (or a missing name) fall back to the seed gazetteer and record
  the source as unverified in a `skos:note`.
- A taxon IRI is **never** fabricated. When evidence is weak, the observation
  keeps the verbatim German name and `taxon_iri` stays null.

This workstream's runnable pipeline is not guaranteed to exist yet; the resolver
degrades to the offline gazetteer until `taxa.links_long_path` points at a file.
