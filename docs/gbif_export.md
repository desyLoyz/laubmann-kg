# GBIF export: Laubmann's own records below an estimated error of 50 %

GBIF gets a selection of the full Darwin Core Archive, not the archive itself: the records Alfred Louis
Laubmann made himself whose estimated error (`docs/record_quality.md`) is below 50 %. Two datasets, each an
Occurrence-core archive (GBIF dataset type "Occurrence"; the diaries are opportunistic observations, not a
standardised sampling protocol, so the entry is kept as `eventID` / `fieldNumber` instead of an Event core):

| Dataset | basisOfRecord | Archive |
|---|---|---|
| observations | HumanObservation | `output/gbif/laubmann_observations_dwca.zip` |
| specimens | PreservedSpecimen | `output/gbif/laubmann_specimens_dwca.zip` |

The full archive (`output/dwca/`, Event core) is not changed.

## Selection

A record of the full archive is exported when all of these hold; otherwise `exclusions.tsv` gives the first
rule it fails:

1. not published literature (`basisOfRecord` MaterialCitation or an `associatedReferences` citation);
2. `recordedBy` names Alfred Laubmann, alone or with companions ("Alfred Laubmann | Adolf Müller");
3. record type `field-observation` (his own record, not a report of others he passes on);
4. an estimate exists and `p_any` < 0.5 (estimated probability that any of existence, species, count, date,
   place, observer, record type is wrong);
5. start and end of `eventDate` within 1917–1965 (the diary period);
6. `basisOfRecord` belongs to a dataset (HumanObservation → observations, PreservedSpecimen → specimens).

All thresholds are in `configs/gbif_laubmann.yaml`.

## Result (2026-10-22, export `kg_exports_2026-10-06_regions`)

| | observations | specimens |
|---|---|---|
| records | 40,332 | 81 |
| diary entries | 6,756 | 56 |
| absences (`occurrenceStatus` absent) | 704 | 0 |
| with coordinates | 27,983 | 64 |
| with `countryCode` | 23,799 | 61 |
| expected records with a wrong field (sum of `p_any`) | 7,640 (18.9 %) | 22 (27.6 %) |

Laubmann's records left out: 5,719 with an estimated error of 50 % or more, 84 dated outside 1917–1965 (mostly
1901–1916, the period before the diaries), 1 typed as a third-party report.

## What the archives add to the records

The values of a record are those of the full archive. Added per record:

- `license` (CC BY 4.0), `rightsHolder`, `datasetName`, `language` (de, the language of the verbatim text);
- `recordedByID`: Laubmann's GND IRI (https://d-nb.info/gnd/1012394506). His companions have no identifier in
  the archive, so the list names only him;
- `countryCode` from the GeoNames country dumps (`data/cache/linking/geonames/`) when `locationID` is a GeoNames
  feature; GBIF derives the country of the other georeferenced records from the coordinates;
- `verbatimEventDate`, `fieldNumber` (volume-entry, e.g. `L02-e0096`), `samplingProtocol` from the entry;
- the error estimate: eMoF rows "estimated error probability (any field)" and "... (occurrence ...)" and
  `dynamicProperties` `estimatedErrorProbability`, `estimatedOccurrenceErrorProbability`,
  `estimatedQualityLevel` (1 < 10 %, 2 10–25 %, 3 25–50 %).

Not taken over: the entry's `fieldNotes` (the whole entry text; the record's passage is in `occurrenceRemarks`)
and its weather (`eventRemarks`). The eMoF rows of the full archive (evidence, call type, count qualifier,
breeding evidence, movement, record type, time of day, EUNIS class) are kept, joined by `occurrenceID`.

EML: GBIF metadata profile 1.3 (EML 2.2.0), validated against
http://rs.gbif.org/schema/eml-gbif-profile/1.3/eml.xsd. Creators, metadata providers and contacts are Tobias
Perschl and Alois Wieshuber (ORCID); Alfred Louis Laubmann is `associatedParty` with role `originator`; project
HistOrniGraph with the NFDI4Biodiversity funding; methods name the extraction run of the full archive, the two
checks, the selection and the expected error share.

## Reproduce

```bash
python tools/export_gbif_subset.py                         # configs/gbif_laubmann.yaml
python tools/export_gbif_subset.py --max-error 0.25        # stricter threshold
pytest tests/test_gbif_subset.py
```

Inputs: `output/dwca/` (full archive) and `data/cache/graph_check/quality/record_quality.csv` (Drive
`HistOrniGraph_Final_Graph_NoVal/quality/`). `output/gbif/summary.json` records the sha256 of both, the filter
and the counts; `output/gbif/exclusions.tsv` lists every record left out with its reason.

## Before publishing

- Upload both ZIPs to the [GBIF data validator](https://www.gbif.org/tools/data-validator).
- Publishing needs a GBIF publisher endorsed by the German node (e.g. via GFBio / NFDI4Biodiversity or an IPT
  of the publishing institution). The specimens dataset documents diary notes; GBIF expects specimens to be
  published by the collection that holds them (`institutionCode`, `catalogNumber`), which the diary does not
  give.
- `occurrenceID`s are the w3id IRIs of the graph; they must stay stable across re-publications.
