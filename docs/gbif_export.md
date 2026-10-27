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
| with coordinates | 27,848 (27,983 before the georeference check) | 64 |
| with `countryCode` | 21,571 (no code from rivers/lakes, see below) | 54 |
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

## GBIF data validator (2026-10-22)

`laubmann_observations_dwca.zip` (export above), report `fcf5580b-5fa2-4a1e-a023-9ee3c8956b91` on
tools.gbif.org (kept by GBIF for one month): **"The file can be indexed by GBIF"**. `eml.xml`, `meta.xml` and
`measurementorfact.txt` have no issues; all 40,332 records are indexed. The specimens ZIP is not validated yet.

Issues in `occurrence.txt` (all warnings of the GBIF occurrence interpretation, none blocks indexing):

| Issue | Records | Cause | Proposed handling |
|---|---|---|---|
| Taxon ID not found | 40,271 | `taxonID` is a GBIF species URL (`https://www.gbif.org/species/2495455`); GBIF looks the value up as an identifier of its checklist and does not resolve URLs. It falls back to `scientificName` + classification, so the taxa are matched anyway. All records with a `taxonID` (61 have none). | Leave out `taxonID` in the GBIF archives (keep it in the full archive), or write the bare key (`2495455`) and re-validate. |
| Continent derived from coordinates | 27,972 | No `continent` given; information only. | None, or write `continent` = Europe for records with `countryCode`. |
| Country derived from coordinates | 4,184 | Georeferenced, but the place is not a GeoNames feature, so no `countryCode` (2,754 place links from the machine review, 1,430 Nominatim matches). GBIF fills in the country; information only. | None, or derive `countryCode` from the Nominatim cache. |
| Country coordinate mismatch | 9 | `countryCode` AT from a GeoNames river (Loisach 2772288, Tiroler Achen 2783037) that flows through Austria and Bavaria; the coordinates are in Bavaria. | Take no `countryCode` from GeoNames hydrographic features (class H); check the coordinates (see below). |
| Taxon match higherrank | 9 | Name not in the GBIF backbone at its rank: hybrids, a subspecies, `Lophura imperialis` (now mostly treated as a hybrid). GBIF matched the genus or species. | Check the names (see below); hybrids could go to `verbatimIdentification` with the parent species in `scientificName`. |

### Checklist

- [x] **`taxonID`** (2026-10-26): the bare GBIF key (`2495455`) instead of the species URL
  (`gbif.taxon_key`); re-validate (the warning should disappear for all 40,271 records).
- [x] **Country coordinate mismatch** (2026-10-26): no `countryCode` from GeoNames hydrographic features
  (class H: rivers, lakes; `NO_COUNTRY_FEATURE_CLASSES`), GBIF derives the country from the coordinates. Original
  finding (9 records, all with `countryCode` AT and coordinates in Bavaria); check
  per entry the place and whether the GeoNames river point is acceptable as georeference:
  - Loisach, "Loisach bei der ersten Überfahrt, dem Ausfluß aus dem Kochelsee", 47.9333 / 11.4500
    (GeoNames 2772288): `L02-e0117` (1919-02-16; Zwergtaucher `obs_b87c9271ed4c`, Wasseramsel `obs_2120a2b211ef`,
    Bläßhuhn `obs_6266f571eb56`), `L05-e0212` (1927-05-08; Berglaubsänger `obs_58a5ead3c67e`), `L30-e0088`
    (1956-07-21; Zwergrohrdommel `obs_f93397693e12`). The GeoNames point lies about 30 km north of the outflow
    of the Kochelsee (about 47.66 / 11.34).
  - Tiroler Achen, "Achen-Einmündung", 47.8500 / 12.5000 (GeoNames 2783037): `L06-e0147` (1928-08-28;
    Stockente `obs_13685b0ec105`, Zwergtaucher `obs_c3ac6687139a`, Gimpel `obs_c15abb601f6d`, Rotschenkel
    `obs_90b7cb6d7e3b`). The point is close to the mouth into the Chiemsee; only the
    country is wrong.
- [ ] **Taxon match higherrank** (9 records). The validator names five; the other four are the remaining
  hybrids and the second *armorica* record (no GBIF `taxonID`, same names). Check identification and name:
  - `L15-e0183` 1938-05-11 Kaiserfasan, *Lophura imperialis* (`obs_4203b5b1b144`) — named sample;
  - `L15-e0185` 1938-05-12 Provence-Grasmücke, *Sylvia undata armorica* (`obs_10b0f3e2eeaf`) — named sample;
  - `L15-e0186` 1938-05-12 same name (`obs_a30213bd4dd1`);
  - `L25-e0151` 1953-03-01 Bastardkrähe, *Corvus corone x Corvus cornix* (`obs_8d4c58479602`) — named sample;
  - `L32-e0211` 1960-05-23 Grünfink x Zeisig, *Chloris chloris x Spinus spinus* (`obs_b4c907f5d1d3`);
  - `L32-e0226` 1960-06-23 Zeisig-Grünfink-Bastard, *Spinus spinus x Chloris chloris* (`obs_cd1e9516b982`);
  - `L32-e0229` 1960-06-30 Stieglitz-Grünfink-Bastard, *Carduelis carduelis x Chloris chloris*
    (`obs_3e5a0261cd94`) — named sample;
  - `L32-e0230` 1960-07-02 same name (`obs_52f378cedb0f`) — named sample;
  - ninth record: the validator does not name it; remaining candidate without a GBIF `taxonID` and with a
    non-backbone name is `L32-e0209` 1960-05-19 (`obs_d3c9999fe02e`, *Aves*, remarks mention a Bastard).
- [ ] **Country / continent derived** (4,184 / 27,972): accept as information, or fill `countryCode` and
  `continent` in the export.
- [x] **EML identifiers** (2026-10-26): ORCID and GND in `<userId>` as bare identifiers with the directory
  attribute (GBIF metadata profile), not as full URLs.
- [x] **Georeferences** (2026-10-26): see "Georeference check" below.
- [ ] Re-validate both ZIPs after these changes.
- [ ] Validate `laubmann_specimens_dwca.zip`.

Record IDs are abbreviated; the full `occurrenceID` is `https://w3id.org/laubmann-kg/data/obs_…`.

## Georeference check (2026-10-26)

Reviewing the archive showed places linked to a namesake far away: local names at the Ismaning reservoir
("Tafelberg", 391 records, placed near Mühldorf; "Oberbecken" and "Keilberg" in the Spessart; "Verbindungskanal"
at Mannheim), the Ionian island Kalamos in Attica, "Tietzing" in Hungary, "Hinterbrühl" (Munich) near Vienna.
`tools/validation_ui/machine_review/georef_check.py` selects every place whose coordinates lie far from the rest of
its entries (median > 60 km; 702 places) or from the records of the surrounding days (> 100 km; 197 more), and two
Claude judges decide independently from the diary passages, the entries' other places and the GeoNames namesakes
nearby: correct, another GeoNames feature, inside a larger place of the entry, remove the coordinates, or unsure.

| | places | records (full archive) |
|---|---|---|
| checked | 899 | 5,604 |
| coordinates confirmed (both judges, or first judge with no second look) | 614 | 3,330 |
| relocated (both judges, same point within 5 km) | 88 | 869 |
| coordinates removed (both find them wrong, no agreed replacement) | 111 | 699 |
| open: the judges disagree or are unsure (`data/review/machine/georef_open.csv`) | 86 | 706 |

Control: of 60 places the first judge found correct, the second agreed on 56. The decisions are in
`data/review/machine/georef_machine.csv` (contract of `review/identities.csv`, confidence 1 − (1 − c1)(1 − c2),
agreement 2); 142 of 199 rows reach confidence 0.9 and are applied: by the pipeline at the next rebuild
(`review.machine.georef`, before `identities_machine.csv`; a human row in `identities.csv` still wins) and by this
export already (`place_corrections` in `configs/gbif_laubmann.yaml`; `summary.json` counts the corrected records).
In the observations archive 390 records got new coordinates and 135 lost theirs; relocated records carry
`georeferenceProtocol` "georeference check: was …". A relocation onto a river's GeoNames point is not taken (the
point can lie 40 km from the stretch meant, e.g. Lech); those coordinates are removed instead. Labels that stand for
several real places (Obersee, Eching, Hintersee, Bodman) need decisions per mention and are left open.

## Before publishing

- Upload both ZIPs to the [GBIF data validator](https://www.gbif.org/tools/data-validator) (observations done,
  see above).
- Publishing needs a GBIF publisher endorsed by the German node (e.g. via GFBio / NFDI4Biodiversity or an IPT
  of the publishing institution). The specimens dataset documents diary notes; GBIF expects specimens to be
  published by the collection that holds them (`institutionCode`, `catalogNumber`), which the diary does not
  give.
- `occurrenceID`s are the w3id IRIs of the graph; they must stay stable across re-publications.
