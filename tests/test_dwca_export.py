import csv
import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from laubmann_kg.dwca import export
from laubmann_kg.dwca.validate import validate_archive


def _tsv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        # QUOTE_NONE: read verbatim, like a fieldsEnclosedBy="" DwC-A reader.
        return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))


def test_dwca_export_produces_valid_archive(sample_config, tmp_path: Path) -> None:
    summary = export(sample_config, None, tmp_path, validate=True)
    assert summary["valid"] is True
    assert summary["problems"] == []

    dwca_dir = tmp_path / "dwca"
    for name in ("meta.xml", "event.txt", "occurrence.txt",
                 "measurementorfact.txt", "multimedia.txt", "eml.xml"):
        assert (dwca_dir / name).exists()

    ElementTree.parse(dwca_dir / "meta.xml")  # well-formed
    assert validate_archive(dwca_dir) == []

    # meta.xml declares linesTerminatedBy="\n": no \r may reach the data files.
    for name in ("event.txt", "occurrence.txt"):
        assert b"\r" not in (dwca_dir / name).read_bytes()


def test_occurrence_event_join_integrity(sample_config, tmp_path: Path) -> None:
    export(sample_config, None, tmp_path, validate=False)
    dwca_dir = tmp_path / "dwca"
    event_ids = {r["eventID"] for r in _tsv(dwca_dir / "event.txt")}
    occ = _tsv(dwca_dir / "occurrence.txt")
    assert occ, "expected at least one occurrence"
    assert all(r["eventID"] in event_ids for r in occ)
    assert len({r["occurrenceID"] for r in occ}) == len(occ)


def test_column_contract_and_headers(sample_config, tmp_path: Path) -> None:
    # Column contract: eventID first everywhere (join key = meta.xml index 0);
    # the event core keeps its legacy prefix and its two trailing weather
    # columns (pinned by test_weather_extraction), new columns in between; the
    # occurrence extension is the documented DwC column set; eMoF/multimedia
    # as declared. Headers on disk == FIELDS.
    from laubmann_kg.dwca.event import FIELDS as EVENT_FIELDS
    from laubmann_kg.dwca.measurement_or_fact import FIELDS as MOF_FIELDS
    from laubmann_kg.dwca.multimedia import FIELDS as MM_FIELDS
    from laubmann_kg.dwca.occurrence import FIELDS as OCC_FIELDS

    assert EVENT_FIELDS[:9] == [
        "eventID", "eventDate", "verbatimEventDate", "locality",
        "decimalLatitude", "decimalLongitude", "samplingProtocol",
        "fieldNumber", "fieldNotes"]
    assert EVENT_FIELDS[9:] == ["verbatimLocality", "geodeticDatum",
                                "coordinateUncertaintyInMeters", "georeferenceSources", "georeferenceProtocol", "locationID",
                                "eventRemarks", "dynamicProperties"]
    assert OCC_FIELDS == [
        "eventID", "occurrenceID", "basisOfRecord",
        "kingdom", "class", "order", "family", "scientificName", "taxonRank", "vernacularName", "taxonID",
        "individualCount", "organismQuantity", "organismQuantityType",
        "occurrenceStatus", "sex", "lifeStage", "reproductiveCondition", "vitality",
        "behavior", "identificationQualifier", "identificationRemarks", "verbatimIdentification",
        "locality", "locationID", "verbatimLocality", "coordinateUncertaintyInMeters",
        "eventDate", "eventTime", "habitat", "samplingProtocol",
        "occurrenceRemarks", "recordedBy", "associatedMedia", "associatedReferences",
        "dynamicProperties"]
    assert MOF_FIELDS == [
        "eventID", "occurrenceID", "measurementID", "measurementType",
        "measurementTypeID", "measurementValue", "measurementValueID",
        "measurementMethod"]
    assert MM_FIELDS == ["eventID", "identifier", "type", "format", "title", "description"]
    for fields in (EVENT_FIELDS, OCC_FIELDS, MOF_FIELDS, MM_FIELDS):
        assert fields[0] == "eventID"
        assert len(set(fields)) == len(fields)

    summary = export(sample_config, None, tmp_path, validate=True)
    assert summary["valid"] is True
    dwca_dir = tmp_path / "dwca"
    for name, fields in (("occurrence.txt", OCC_FIELDS), ("event.txt", EVENT_FIELDS),
                         ("measurementorfact.txt", MOF_FIELDS),
                         ("multimedia.txt", MM_FIELDS)):
        with (dwca_dir / name).open(encoding="utf-8") as handle:
            assert handle.readline().rstrip("\n").split("\t") == fields


def _weather_result():
    from laubmann_kg.kg.model import DiaryEntry, WeatherReport
    from laubmann_kg.pipeline import ExtractionResult

    entry = DiaryEntry(
        entry_uid="e_weather01", entry_id="L02-e9001", volume=2,
        page_uid="p_w1", page_id="pageid-w1", region_uid=None, scan=None,
        entry_date="1918-05-01",
        verbatim_event_date='1. Mai 1918, ein "Regentag"',
        location_raw="München",
        text_clean="Wetter: trüb, Regen den ganzen Tag.",
        weather=WeatherReport(verbatim="trüb, Regen", temperature_value=7.5,
                              temperature_unit="C", precipitation="rain",
                              sky="overcast"),
    )
    return ExtractionResult(entries=[entry])


def test_raw_bytes_verbatim_for_conformant_readers(tmp_path: Path) -> None:
    # meta.xml declares fieldsEnclosedBy="" and linesTerminatedBy="\n", so the
    # data files must carry field bytes verbatim: no CSV quote-wrapping, no
    # doubled inner quotes, no \r.
    from laubmann_kg.dwca.archive import build_archive

    dwca_dir = tmp_path / "dwca"
    build_archive(_weather_result(), dwca_dir)

    raw = (dwca_dir / "event.txt").read_bytes()
    assert b"\r" not in raw
    assert b"\r" not in (dwca_dir / "occurrence.txt").read_bytes()

    header, row = raw.decode("utf-8").split("\n")[:2]
    fields = dict(zip(header.split("\t"), row.split("\t")))

    # A literal double quote survives byte-verbatim, neither wrapped nor doubled.
    assert fields["verbatimEventDate"] == '1. Mai 1918, ein "Regentag"'

    # dynamicProperties JSON parses straight off the raw tab-split line.
    assert '""' not in fields["dynamicProperties"]
    assert json.loads(fields["dynamicProperties"]) == {
        "temperatureValue": 7.5, "temperatureUnit": "C",
        "precipitation": "rain", "skyCondition": "overcast"}

    assert validate_archive(dwca_dir) == []


def test_archive_zip_contains_all_members(sample_config, tmp_path: Path) -> None:
    summary = export(sample_config, None, tmp_path, validate=False)
    with ZipFile(summary["zip"]) as archive:
        names = set(archive.namelist())
    assert {"meta.xml", "event.txt", "occurrence.txt", "multimedia.txt",
            "measurementorfact.txt", "eml.xml"} <= names
