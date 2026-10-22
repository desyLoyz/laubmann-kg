"""GBIF subset of the Darwin Core Archive (laubmann_kg.dwca.gbif)."""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from laubmann_kg.dwca import gbif
from laubmann_kg.dwca.gbif import (DatasetConfig, FilterConfig, GbifConfig, Metadata, exclusion_reason,
                                   occurrence_row, validate_rows, year_span)
from laubmann_kg.io.csv import write_rows

FILT = FilterConfig()
OBS = DatasetConfig(basis_of_record=["HumanObservation"], package_id="p-obs", zip_name="obs.zip",
                    title="Observations", abstract="Abstract.")
SPEC = DatasetConfig(basis_of_record=["PreservedSpecimen"], package_id="p-spec", zip_name="spec.zip",
                     title="Specimens", abstract="Abstract.")
META = Metadata.model_validate({
    "rights_holder": "HistOrniGraph / Laubmann KG Project",
    "creators": [{"given_name": "Tobias", "sur_name": "Perschl", "email": "Tobias.Perschl@uni-passau.de",
                  "orcid": "0009-0008-7070-8705", "organization": "Universität Passau"}],
    "originator": {"given_name": "Alfred Louis", "sur_name": "Laubmann", "gnd": "1012394506"},
    "project": {"title": "HistOrniGraph", "funding": "Funded by NFDI4Biodiversity."},
    "keywords": ["ornithology"],
})
D = "https://w3id.org/laubmann-kg/data/"


def occ(n: int, **kw) -> dict:
    row = {"eventID": D + "entry_1", "occurrenceID": D + f"obs_{n}", "basisOfRecord": "HumanObservation",
           "kingdom": "Animalia", "class": "Aves", "scientificName": "Cyanistes caeruleus", "taxonRank": "species",
           "vernacularName": "Blaumeise", "individualCount": "2", "occurrenceStatus": "present",
           "locality": "Englischer Garten", "locationID": "https://sws.geonames.org/2867714/",
           "decimalLatitude": "48.1649", "decimalLongitude": "11.6064", "geodeticDatum": "WGS84",
           "eventDate": "1918-12-26", "occurrenceRemarks": "noch sehr viele Blaumeisen",
           "recordedBy": "Alfred Laubmann", "associatedReferences": "", "dynamicProperties": ""}
    row.update(kw)
    return row


def q(n: int, p: float = 0.1) -> dict:
    return {"occurrenceID": D + f"obs_{n}", "p_any": f"{p:.3f}", "p_occurrence": "0.040", "level": "1"}


# ------------------------------------------------------------------ selection rules


@pytest.mark.parametrize("value,expected", [
    ("1918-12-26", (1918, 1918)), ("1917-04-07/1917-04-09", (1917, 1917)), ("1916-12-30/1917-01-02", (1916, 1917)),
    ("1930-05", (1930, 1930)), ("", None), ("undated", None),
])
def test_year_span(value, expected) -> None:
    assert year_span(value) == expected


def test_observer_must_be_named_alone_or_with_companions() -> None:
    assert gbif.names_observer("Alfred Laubmann", "Alfred Laubmann")
    assert gbif.names_observer("Alfred Laubmann | Adolf Müller", "Alfred Laubmann")
    assert not gbif.names_observer("Walter Wüst", "Alfred Laubmann")
    assert not gbif.names_observer("", "Alfred Laubmann")
    assert not gbif.names_observer("Alfred Laubmann jun.", "Alfred Laubmann")


@pytest.mark.parametrize("row,quality,rtype,reason", [
    (occ(1), q(1), "field-observation", None),
    (occ(1, recordedBy="Alfred Laubmann | Adolf Müller"), q(1), "field-observation", None),
    (occ(1, basisOfRecord="MaterialCitation", associatedReferences="Anz. orn. Ges."), q(1), "field-observation",
     "published literature"),
    (occ(1, associatedReferences="Verh. orn. Ges. Bayern"), q(1), "field-observation", "published literature"),
    (occ(1, recordedBy="Walter Wüst"), q(1), "field-observation", "other or no observer"),
    (occ(1, recordedBy=""), q(1), "field-observation", "other or no observer"),
    (occ(1), q(1), "third-party-report", "record type third-party-report"),
    (occ(1), q(1), None, "record type missing"),
    (occ(1), None, "field-observation", "no error estimate"),
    (occ(1), q(1, 0.5), "field-observation", "estimated error >= 0.5"),
    (occ(1), q(1, 0.499), "field-observation", None),
    (occ(1, eventDate="1916-05-01"), q(1), "field-observation", "date outside 1917-1965"),
    (occ(1, eventDate="1965-12-30/1966-01-02"), q(1), "field-observation", "date outside 1917-1965"),
    (occ(1, eventDate=""), q(1), "field-observation", "no date"),
])
def test_exclusion_reason(row, quality, rtype, reason) -> None:
    assert exclusion_reason(row, quality, FILT, rtype) == reason


def test_literature_wins_over_every_other_reason() -> None:
    row = occ(1, basisOfRecord="MaterialCitation", recordedBy="Walter Wüst", eventDate="1900-01-01")
    assert exclusion_reason(row, None, FILT, None) == "published literature"
    assert exclusion_reason(row, None, FILT.model_copy(update={"include_literature": True}), None) == \
        "other or no observer"


def test_dataset_by_basis_of_record() -> None:
    sets = {"observations": OBS, "specimens": SPEC}
    assert gbif.dataset_for(occ(1), sets) == "observations"
    assert gbif.dataset_for(occ(1, basisOfRecord="PreservedSpecimen"), sets) == "specimens"
    assert gbif.dataset_for(occ(1, basisOfRecord="MachineObservation"), sets) is None


def test_record_type_from_measurements() -> None:
    assert gbif.record_type([{"measurementType": "evidenceKind", "measurementValue": "visual"},
                             {"measurementType": "recordType", "measurementValue": "field-observation"}]) == \
        "field-observation"
    assert gbif.record_type([]) is None


# ------------------------------------------------------------------ row mapping


def test_occurrence_row_keeps_values_and_adds_gbif_columns() -> None:
    source = occ(1, dynamicProperties='{"microhabitat": "Hecke"}')
    event = {"eventID": D + "entry_1", "verbatimEventDate": "26. December 1918", "fieldNumber": "L02-e0096",
             "samplingProtocol": "diary observation", "fieldNotes": "whole entry text"}
    row = occurrence_row(source, event, q(1, 0.083), OBS, META, {"2867714": "DE"})
    for key in ("occurrenceID", "eventID", "scientificName", "eventDate", "decimalLatitude", "recordedBy",
                "occurrenceRemarks"):
        assert row[key] == source[key]
    assert row["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert row["rightsHolder"] == "HistOrniGraph / Laubmann KG Project"
    assert row["datasetName"] == "Observations"
    assert row["countryCode"] == "DE"
    assert row["recordedByID"] == "https://d-nb.info/gnd/1012394506"
    assert (row["fieldNumber"], row["verbatimEventDate"]) == ("L02-e0096", "26. December 1918")
    assert "fieldNotes" not in row and "associatedReferences" not in row
    props = json.loads(row["dynamicProperties"])
    assert props == {"microhabitat": "Hecke", "estimatedErrorProbability": 0.083,
                     "estimatedOccurrenceErrorProbability": 0.04, "estimatedQualityLevel": 1}
    assert set(row) <= set(gbif.OCCURRENCE_FIELDS)


def test_country_code_only_from_a_geonames_location() -> None:
    row = occurrence_row(occ(1, locationID="https://www.openstreetmap.org/node/1"), None, q(1), OBS, META,
                         {"2867714": "DE"})
    assert row["countryCode"] == ""


def test_mof_rows_drop_event_id_and_add_the_estimates() -> None:
    src = [{"eventID": D + "entry_1", "occurrenceID": D + "obs_1", "measurementID": D + "obs_1:recordType:0",
            "measurementType": "recordType", "measurementValue": "field-observation"}]
    rows = gbif.mof_rows(src, q(1, 0.2))
    assert all("eventID" not in r for r in rows)
    assert [r["measurementValue"] for r in rows] == ["field-observation", "0.200", "0.040"]
    assert len({r["measurementID"] for r in rows}) == 3


# ------------------------------------------------------------------ validation and EML


def test_validate_rows_flags_records_outside_the_filter() -> None:
    good = occurrence_row(occ(1), None, q(1), OBS, META, {})
    assert validate_rows([good], [], OBS, FILT) == []
    bad = [occurrence_row(occ(2, recordedBy="Walter Wüst"), None, q(2), OBS, META, {}),
           occurrence_row(occ(3), None, q(3, 0.7), OBS, META, {}),
           occurrence_row(occ(4, eventDate="1912-05-01"), None, q(4), OBS, META, {}),
           occurrence_row(occ(5, basisOfRecord="PreservedSpecimen"), None, q(5), OBS, META, {}),
           occurrence_row(occ(6, decimalLongitude=""), None, q(6), OBS, META, {}),
           occurrence_row(occ(1), None, q(1), OBS, META, {})]
    problems = " ".join(validate_rows([good, *bad], [{"occurrenceID": D + "obs_99", "measurementID": "x"}],
                                      OBS, FILT))
    for text in ("does not name Alfred Laubmann", "not below 0.5", "date outside", "basisOfRecord",
                 "only one of decimalLatitude", "duplicate occurrenceID", "not in the core"):
        assert text in problems


def test_eml_names_creators_originator_funding_and_licence() -> None:
    rows = [occurrence_row(occ(1), None, q(1), OBS, META, {})]
    eml = gbif.build_eml(OBS, META, rows, ["extraction", "quality"], dt.date(2026, 10, 22))
    root = ElementTree.fromstring(eml.encode())
    ds = root.find("dataset")
    assert root.tag == "{https://eml.ecoinformatics.org/eml-2.2.0}eml"
    assert ds.findtext("creator/userId") == "https://orcid.org/0009-0008-7070-8705"
    assert ds.findtext("associatedParty/role") == "originator"
    assert ds.findtext("associatedParty/userId") == "https://d-nb.info/gnd/1012394506"
    assert "NFDI4Biodiversity" in ds.findtext("project/funding/para")
    assert ds.find("intellectualRights/para/ulink").get("url") == "https://creativecommons.org/licenses/by/4.0/"
    assert ds.findtext("methods/qualityControl/description/para") == "quality"
    assert ds.findtext("coverage/temporalCoverage/rangeOfDates/beginDate/calendarDate") == "1918-12-26"


# ------------------------------------------------------------------ end to end


def test_export_writes_occurrence_core_archives_and_exclusions(tmp_path: Path) -> None:
    src = tmp_path / "dwca"
    occs = [occ(1), occ(2, recordedBy="Walter Wüst"), occ(3), occ(4, basisOfRecord="PreservedSpecimen"),
            occ(5, basisOfRecord="MaterialCitation", associatedReferences="Lit.")]
    write_rows(src / "occurrence.txt", occs, list(occs[0]))
    write_rows(src / "event.txt", [{"eventID": D + "entry_1", "fieldNumber": "L02-e0096"}], ["eventID", "fieldNumber"])
    mof = [{"eventID": D + "entry_1", "occurrenceID": o["occurrenceID"], "measurementID": o["occurrenceID"] + ":rt",
            "measurementType": "recordType", "measurementValue": "field-observation"} for o in occs]
    write_rows(src / "measurementorfact.txt", mof, list(mof[0]))
    quality = [q(1, 0.1), q(2, 0.1), q(3, 0.6), q(4, 0.2), q(5, 0.1)]
    (tmp_path / "quality.csv").write_text(
        "occurrenceID,p_any,p_occurrence,level\n" + "".join(
            f"{r['occurrenceID']},{r['p_any']},{r['p_occurrence']},{r['level']}\n" for r in quality), encoding="utf-8")
    cfg = GbifConfig(source_dwca=src, quality=tmp_path / "quality.csv", output_dir=tmp_path / "gbif",
                     datasets={"observations": OBS, "specimens": SPEC}, metadata=META)

    summary = gbif.export(cfg, tmp_path, today=dt.date(2026, 10, 22))

    assert summary["datasets"]["observations"]["records"] == 1
    assert summary["datasets"]["specimens"]["records"] == 1
    assert all(not d["problems"] for d in summary["datasets"].values())
    assert summary["excluded"] == {"other or no observer": 1, "estimated error >= 0.5": 1, "published literature": 1}
    with zipfile.ZipFile(tmp_path / "gbif" / "obs.zip") as z:
        assert sorted(z.namelist()) == ["eml.xml", "measurementorfact.txt", "meta.xml", "occurrence.txt"]
        meta = ElementTree.fromstring(z.read("meta.xml"))
        assert meta.find("{http://rs.tdwg.org/dwc/text/}core").get("rowType") == "http://rs.tdwg.org/dwc/terms/Occurrence"
        lines = z.read("occurrence.txt").decode().splitlines()
        assert len(lines) == 2 and D + "obs_1" in lines[1] and "L02-e0096" in lines[1]
    excluded = (tmp_path / "gbif" / "exclusions.tsv").read_text(encoding="utf-8").splitlines()
    assert len(excluded) == 4
    assert (src / "occurrence.txt").read_text(encoding="utf-8").count("\n") == 6   # source untouched
