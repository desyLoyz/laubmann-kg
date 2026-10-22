"""GBIF subsets of the Darwin Core Archive: Laubmann's own records below an error threshold.

The full archive (Event core, ``laubmann_kg.dwca.archive``) holds every record
of the graph. GBIF gets a selection of it: the records Alfred Laubmann made
himself (``recordedBy`` names him, alone or with companions) whose estimated
probability of an error in any field (``record_quality.csv``,
docs/record_quality.md) is below a threshold and whose date lies in the diary
period. Each selected dataset is written as an Occurrence-core archive (GBIF
dataset type "Occurrence": the diaries are opportunistic, not a standardised
sampling protocol); the entry is kept as ``eventID`` / ``fieldNumber``.

Every function here is pure except the readers/writers at the bottom. The
filter never changes a value of a record: it adds the GBIF columns
(``license``, ``rightsHolder``, ``datasetName``, ``recordedByID``,
``countryCode``) and publishes the error estimate with the record.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

from pydantic import BaseModel, Field

from laubmann_kg.dwca.archive import _LICENSE_LINKS
from laubmann_kg.dwca.event import dumps_properties
from laubmann_kg.dwca.meta_xml import DWC, FileSpec, ROW_TYPES, build_meta_xml

GND = "https://d-nb.info/gnd/"
ORCID = "https://orcid.org/"
LITERATURE_BASIS = "MaterialCitation"

# ------------------------------------------------------------------ configuration


class FilterConfig(BaseModel):
    observer: str = "Alfred Laubmann"
    error_measure: str = "p_any"
    max_error: float = 0.5
    year_from: int = 1917
    year_to: int = 1965
    include_literature: bool = False
    record_types: list[str] = Field(default_factory=lambda: ["field-observation"])


class DatasetConfig(BaseModel):
    basis_of_record: list[str]
    package_id: str
    zip_name: str
    title: str
    abstract: str


class Person(BaseModel):
    given_name: str
    sur_name: str
    email: Optional[str] = None
    orcid: Optional[str] = None
    gnd: Optional[str] = None
    organization: Optional[str] = None

    @property
    def name(self) -> str:
        return f"{self.given_name} {self.sur_name}"


class Project(BaseModel):
    title: str
    funding: str


class Metadata(BaseModel):
    license: str = "CC-BY-4.0"
    rights_holder: str
    language: str = "en"
    data_language: str = "de"
    creators: list[Person]
    originator: Person
    project: Project
    keywords: list[str] = Field(default_factory=list)
    homepage: Optional[str] = None


class GbifConfig(BaseModel):
    source_dwca: Path
    quality: Path
    geonames_dir: Optional[Path] = None
    output_dir: Path
    filter: FilterConfig = Field(default_factory=FilterConfig)
    datasets: dict[str, DatasetConfig]
    metadata: Metadata


# ------------------------------------------------------------------ selection

OCCURRENCE_FIELDS = [
    "occurrenceID", "eventID", "basisOfRecord", "license", "rightsHolder", "datasetName", "language",
    "kingdom", "class", "order", "family", "scientificName", "taxonRank", "vernacularName", "taxonID",
    "individualCount", "occurrenceStatus", "sex", "lifeStage", "reproductiveCondition", "vitality",
    "behavior", "identificationQualifier", "identificationRemarks", "verbatimIdentification",
    "countryCode", "locality", "verbatimLocality", "locationID", "decimalLatitude", "decimalLongitude",
    "geodeticDatum", "coordinateUncertaintyInMeters", "georeferenceSources", "georeferenceProtocol",
    "minimumElevationInMeters", "maximumElevationInMeters",
    "eventDate", "eventTime", "verbatimEventDate", "fieldNumber", "samplingProtocol", "habitat",
    "occurrenceRemarks", "recordedBy", "recordedByID", "dynamicProperties",
]

MOF_FIELDS = [
    "occurrenceID", "measurementID", "measurementType", "measurementTypeID", "measurementValue",
    "measurementValueID", "measurementMethod",
]

# Columns taken from the event row (the diary entry) into the occurrence row.
EVENT_COLUMNS = ("verbatimEventDate", "fieldNumber", "samplingProtocol")

QUALITY_METHOD = (
    "estimated by tools/validation_ui/graph_check/record_quality.py from two machine checks of the "
    "record (record check, blind check), calibrated on the blind model audit of 2026-10-03 "
    "(docs/record_quality.md)"
)

_YEAR = re.compile(r"^(\d{4})")


def year_span(event_date: str) -> Optional[tuple[int, int]]:
    """(first year, last year) of an ISO date or interval ("1917-04-07", "1917-04-07/1917-04-09")."""
    parts = [p for p in (event_date or "").split("/") if p]
    years = [int(m.group(1)) for m in (_YEAR.match(p) for p in parts) if m]
    if not years or len(years) != len(parts):
        return None
    return min(years), max(years)


def is_literature(row: dict) -> bool:
    return row.get("basisOfRecord") == LITERATURE_BASIS or bool(row.get("associatedReferences"))


def names_observer(recorded_by: str, observer: str) -> bool:
    return observer in [name.strip() for name in (recorded_by or "").split("|")]


def exclusion_reason(row: dict, quality: Optional[dict], filt: FilterConfig,
                     record_type: Optional[str] = None) -> Optional[str]:
    """Why a record of the full archive is not exported (None = it passes the filter).

    The order is fixed so every excluded record has exactly one reason: published
    literature, another observer, record type (his own field record, not a report he
    passes on), no estimate, estimated error, date outside the period.
    """
    if not filt.include_literature and is_literature(row):
        return "published literature"
    if not names_observer(row.get("recordedBy", ""), filt.observer):
        return "other or no observer"
    if filt.record_types and record_type not in filt.record_types:
        return f"record type {record_type or 'missing'}"
    if quality is None or not quality.get(filt.error_measure):
        return "no error estimate"
    if float(quality[filt.error_measure]) >= filt.max_error:
        return f"estimated error >= {filt.max_error:g}"
    span = year_span(row.get("eventDate", ""))
    if span is None:
        return "no date"
    if span[0] < filt.year_from or span[1] > filt.year_to:
        return f"date outside {filt.year_from}-{filt.year_to}"
    return None


def record_type(mof: Iterable[dict]) -> Optional[str]:
    """The record type of a record from its eMoF rows (measurementType recordType)."""
    return next((m["measurementValue"] for m in mof if m.get("measurementType") == "recordType"), None)


def dataset_for(row: dict, datasets: dict[str, DatasetConfig]) -> Optional[str]:
    for name, ds in datasets.items():
        if row.get("basisOfRecord") in ds.basis_of_record:
            return name
    return None


def geonames_id(location_id: str) -> Optional[str]:
    m = re.match(r"^https?://sws\.geonames\.org/(\d+)/?$", location_id or "")
    return m.group(1) if m else None


def occurrence_row(occ: dict, event: Optional[dict], quality: dict, dataset: DatasetConfig,
                   meta: Metadata, countries: dict[str, str]) -> dict:
    """The GBIF occurrence row of one record: its own columns, the entry's columns
    it lacks, the GBIF record-level columns and the error estimate."""
    row = {k: occ.get(k, "") for k in OCCURRENCE_FIELDS if k in occ}
    for column in EVENT_COLUMNS:
        row[column] = (event or {}).get(column, "")
    url = _LICENSE_LINKS.get(meta.license, (meta.license, ""))[0]
    row.update({
        "license": url,
        "rightsHolder": meta.rights_holder,
        "datasetName": dataset.title,
        "language": meta.data_language,
        "countryCode": countries.get(geonames_id(occ.get("locationID", "")) or "", ""),
        # dwc:recordedByID lists the identifiers of the recorders it can name; only
        # Laubmann has one in the archive (his companions keep their names only)
        "recordedByID": GND + meta.originator.gnd if meta.originator.gnd else "",
    })
    props = json.loads(occ["dynamicProperties"]) if occ.get("dynamicProperties") else {}
    props.update({
        "estimatedErrorProbability": round(float(quality["p_any"]), 3),
        "estimatedOccurrenceErrorProbability": round(float(quality["p_occurrence"]), 3),
        "estimatedQualityLevel": int(quality["level"]),
    })
    row["dynamicProperties"] = dumps_properties(props)
    return row


def mof_rows(source_rows: Iterable[dict], quality: dict) -> list[dict]:
    """eMoF rows of one record for an Occurrence core (joined by occurrenceID) plus
    two rows with its estimated error probabilities."""
    rows = [{k: r.get(k, "") for k in MOF_FIELDS} for r in source_rows]
    oid = quality["occurrenceID"]
    for key, label in (("p_any", "estimated error probability (any field)"),
                       ("p_occurrence", "estimated error probability (occurrence: existence, species, count, date)")):
        rows.append({"occurrenceID": oid, "measurementID": f"{oid}:{key}", "measurementType": label,
                     "measurementTypeID": "", "measurementValue": f"{float(quality[key]):.3f}",
                     "measurementValueID": "", "measurementMethod": QUALITY_METHOD})
    return rows


# ------------------------------------------------------------------ EML (GBIF metadata profile 1.3, EML 2.2.0)


def _person_xml(p: Person, tag: str, role: Optional[str] = None) -> str:
    parts = [f"<individualName><givenName>{escape(p.given_name)}</givenName>"
             f"<surName>{escape(p.sur_name)}</surName></individualName>"]
    if p.organization:
        parts.append(f"<organizationName>{escape(p.organization)}</organizationName>")
    if p.email:
        parts.append(f"<electronicMailAddress>{escape(p.email)}</electronicMailAddress>")
    if p.orcid:
        parts.append(f'<userId directory="{ORCID}">{escape(ORCID + p.orcid)}</userId>')
    elif p.gnd:
        parts.append(f'<userId directory="{GND}">{escape(GND + p.gnd)}</userId>')
    if role:
        parts.append(f"<role>{escape(role)}</role>")
    return f"<{tag}>" + "".join(parts) + f"</{tag}>"


def coverage(rows: list[dict]) -> dict:
    lats = [float(r["decimalLatitude"]) for r in rows if r.get("decimalLatitude") and r.get("decimalLongitude")]
    longs = [float(r["decimalLongitude"]) for r in rows if r.get("decimalLatitude") and r.get("decimalLongitude")]
    dates = [d for r in rows for d in (r.get("eventDate") or "").split("/") if d]
    return {"west": min(longs, default=None), "east": max(longs, default=None),
            "south": min(lats, default=None), "north": max(lats, default=None),
            "begin": min(dates, default=None), "end": max(dates, default=None)}


def build_eml(dataset: DatasetConfig, meta: Metadata, rows: list[dict], methods: list[str],
              today: _dt.date) -> str:
    cov = coverage(rows)
    url, title = _LICENSE_LINKS.get(meta.license, (meta.license, meta.license))
    geo = ""
    if cov["west"] is not None:
        geo = ("<geographicCoverage><geographicDescription>Localities named in the diary entries, "
               "georeferenced to settlement or locality centroids (coordinateUncertaintyInMeters gives "
               "the radius)</geographicDescription><boundingCoordinates>"
               f"<westBoundingCoordinate>{cov['west']:.4f}</westBoundingCoordinate>"
               f"<eastBoundingCoordinate>{cov['east']:.4f}</eastBoundingCoordinate>"
               f"<northBoundingCoordinate>{cov['north']:.4f}</northBoundingCoordinate>"
               f"<southBoundingCoordinate>{cov['south']:.4f}</southBoundingCoordinate>"
               "</boundingCoordinates></geographicCoverage>")
    temporal = ""
    if cov["begin"]:
        temporal = (f"<temporalCoverage><rangeOfDates><beginDate><calendarDate>{escape(cov['begin'][:10])}"
                    f"</calendarDate></beginDate><endDate><calendarDate>{escape(cov['end'][:10])}"
                    "</calendarDate></endDate></rangeOfDates></temporalCoverage>")
    keywords = "".join(f"<keyword>{escape(k)}</keyword>" for k in meta.keywords)
    steps = "".join(f"<methodStep><description><para>{escape(m)}</para></description></methodStep>"
                    for m in methods[:-1])
    authors = ", ".join(f"{p.sur_name} {p.given_name[0]}" for p in meta.creators)
    citation = f"{authors} ({today.year}). {dataset.title}. {meta.rights_holder}. Occurrence dataset."
    creators = "".join(_person_xml(p, "creator") for p in meta.creators)
    providers = "".join(_person_xml(p, "metadataProvider") for p in meta.creators)
    contacts = "".join(_person_xml(p, "contact") for p in meta.creators)
    personnel = "".join(_person_xml(p, "personnel", "principalInvestigator") for p in meta.creators)
    homepage = (f"<distribution scope=\"document\"><online><url function=\"information\">"
                f"{escape(meta.homepage)}</url></online></distribution>") if meta.homepage else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<eml:eml xmlns:eml="https://eml.ecoinformatics.org/eml-2.2.0"\n'
        '         xmlns:dc="http://purl.org/dc/terms/"\n'
        '         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '         xsi:schemaLocation="https://eml.ecoinformatics.org/eml-2.2.0 '
        'http://rs.gbif.org/schema/eml-gbif-profile/1.3/eml.xsd"\n'
        f'         packageId={quoteattr(dataset.package_id)} system="http://gbif.org" scope="system"\n'
        f'         xml:lang="{escape(meta.language)}">\n'
        "  <dataset>\n"
        f"    <alternateIdentifier>{escape(dataset.package_id)}</alternateIdentifier>\n"
        f"    <title xml:lang=\"en\">{escape(dataset.title)}</title>\n"
        f"    {creators}\n"
        f"    {providers}\n"
        f"    {_person_xml(meta.originator, 'associatedParty', 'originator')}\n"
        f"    <pubDate>{today.isoformat()}</pubDate>\n"
        f"    <language>{escape(meta.data_language)}</language>\n"
        f"    <abstract><para>{escape(dataset.abstract)}</para><para>{escape(meta.project.funding)}</para></abstract>\n"
        f"    <keywordSet>{keywords}<keywordThesaurus>N/A</keywordThesaurus></keywordSet>\n"
        "    <keywordSet><keyword>Occurrence</keyword><keywordThesaurus>GBIF Dataset Type Vocabulary: "
        "http://rs.gbif.org/vocabulary/gbif/dataset_type_2015-07-10.xml</keywordThesaurus></keywordSet>\n"
        f'    <intellectualRights><para>This work is licensed under a <ulink url="{escape(url)}">'
        f"<citetitle>{escape(title)}</citetitle></ulink> License.</para></intellectualRights>\n"
        f"    {homepage}\n"
        f"    <coverage>{geo}{temporal}<taxonomicCoverage><generalTaxonomicCoverage>Birds (class Aves); "
        "birds the diarist named without a resolvable species are published as class Aves with his "
        "name in vernacularName</generalTaxonomicCoverage><taxonomicClassification>"
        "<taxonRankName>class</taxonRankName><taxonRankValue>Aves</taxonRankValue><commonName>Vögel"
        "</commonName></taxonomicClassification></taxonomicCoverage></coverage>\n"
        f"    {contacts}\n"
        f"    <methods>{steps}<sampling><studyExtent><description><para>The 34 field diaries of Alfred Louis "
        "Laubmann, 1917–1965; one record per bird taxon named in a dated entry.</para></description>"
        "</studyExtent><samplingDescription><para>Opportunistic field observations as noted by the "
        "diarist; no standardised effort.</para></samplingDescription></sampling>"
        f"<qualityControl><description><para>{escape(methods[-1])}</para></description></qualityControl>"
        "</methods>\n"
        f"    <project><title>{escape(meta.project.title)}</title>{personnel}"
        f"<funding><para>{escape(meta.project.funding)}</para></funding></project>\n"
        "  </dataset>\n"
        "  <additionalMetadata><metadata><gbif>"
        f"<dateStamp>{today.isoformat()}T00:00:00</dateStamp><hierarchyLevel>dataset</hierarchyLevel>"
        f"<citation>{escape(citation)}</citation>"
        "</gbif></metadata></additionalMetadata>\n"
        "</eml:eml>\n"
    )


def methods_text(source_method: str, filt: FilterConfig, kept: int, expected_wrong: float,
                 source: str) -> list[str]:
    """Method steps (the last one is the quality-control paragraph)."""
    share = 100 * expected_wrong / kept if kept else 0.0
    return [
        source_method,
        "Every record was checked twice by language models looking at the page scans: a record check "
        "that saw the values of the record and a blind check that read the passage without them. From "
        "the two verdicts and a blind audit of 734 records, the probability that any field of the record "
        "(existence, species, count, date, place, observer, record type) is wrong was estimated per record "
        "(docs/record_quality.md in the project repository).",
        f"Selection for this dataset from the full archive ({source}): records whose recordedBy names "
        f"{filt.observer} (alone or with companions), estimated error of any field below "
        f"{100 * filt.max_error:g} %, date within {filt.year_from}–{filt.year_to}, record type "
        f"{' or '.join(filt.record_types)}; published literature and reports by other people are excluded.",
        f"Each record carries its estimated error probabilities (MeasurementOrFact 'estimated error "
        f"probability (any field)' and '... (occurrence ...)', dynamicProperties estimatedErrorProbability). "
        f"Summed over the {kept:,} records, about {expected_wrong:,.0f} ({share:.1f} %) are expected to "
        "have at least one wrong field. The estimate is a probability for records like this one, not a "
        "verdict on the record; users can select a stricter threshold.",
    ]


# ------------------------------------------------------------------ validation

_ISO_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?(/\d{4}(-\d{2}(-\d{2})?)?)?$")
_DWCA_NS = "{http://rs.tdwg.org/dwc/text/}"


def validate_rows(rows: list[dict], mof: list[dict], dataset: DatasetConfig, filt: FilterConfig) -> list[str]:
    """Problems of an Occurrence-core GBIF archive's tables (empty = valid)."""
    problems: list[str] = []
    ids = [r.get("occurrenceID", "") for r in rows]
    if not rows:
        problems.append("occurrence core is empty")
    if "" in ids:
        problems.append("occurrence without occurrenceID")
    if len(set(ids)) != len(ids):
        problems.append("duplicate occurrenceID values")
    for i, r in enumerate(rows):
        where = r.get("occurrenceID") or f"row {i + 2}"
        if r.get("basisOfRecord") not in dataset.basis_of_record:
            problems.append(f"{where}: basisOfRecord {r.get('basisOfRecord')!r}")
        if not r.get("scientificName"):
            problems.append(f"{where}: no scientificName")
        if not _ISO_DATE.match(r.get("eventDate", "")):
            problems.append(f"{where}: eventDate {r.get('eventDate')!r} not ISO 8601")
        if r.get("occurrenceStatus") not in ("present", "absent"):
            problems.append(f"{where}: occurrenceStatus {r.get('occurrenceStatus')!r}")
        if r.get("individualCount") == "0" and r.get("occurrenceStatus") != "absent":
            problems.append(f"{where}: individualCount 0 but present")
        lat, lon = r.get("decimalLatitude", ""), r.get("decimalLongitude", "")
        if bool(lat) != bool(lon):
            problems.append(f"{where}: only one of decimalLatitude / decimalLongitude")
        elif lat and not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
            problems.append(f"{where}: coordinates out of range")
        if r.get("countryCode") and not re.fullmatch(r"[A-Z]{2}", r["countryCode"]):
            problems.append(f"{where}: countryCode {r['countryCode']!r}")
        if not names_observer(r.get("recordedBy", ""), filt.observer):
            problems.append(f"{where}: recordedBy does not name {filt.observer}")
        if is_literature(r) and not filt.include_literature:
            problems.append(f"{where}: published literature")
        props = json.loads(r.get("dynamicProperties") or "{}")
        if props.get("estimatedErrorProbability", 1.0) >= filt.max_error:
            problems.append(f"{where}: estimated error not below {filt.max_error}")
        span = year_span(r.get("eventDate", ""))
        if span is None or span[0] < filt.year_from or span[1] > filt.year_to:
            problems.append(f"{where}: date outside {filt.year_from}-{filt.year_to}")
    known = set(ids)
    orphans = {m["occurrenceID"] for m in mof} - known
    if orphans:
        problems.append(f"measurementorfact: {len(orphans)} occurrenceID(s) not in the core")
    mids = [m["measurementID"] for m in mof]
    if len(set(mids)) != len(mids):
        problems.append("measurementorfact: duplicate measurementID values")
    return problems


def validate_files(archive_dir: Path) -> list[str]:
    """meta.xml and eml.xml of a written archive."""
    problems: list[str] = []
    try:
        root = ElementTree.parse(archive_dir / "meta.xml").getroot()
        core = root.find(_DWCA_NS + "core")
        if core is None or core.get("rowType") != ROW_TYPES["occurrence"]:
            problems.append("meta.xml: core is not dwc:Occurrence")
        elif DWC + "occurrenceID" not in {f.get("term") for f in core.findall(_DWCA_NS + "field")}:
            problems.append("meta.xml: core does not declare dwc:occurrenceID")
    except ElementTree.ParseError as exc:
        problems.append(f"meta.xml not well-formed: {exc}")
    try:
        dataset = ElementTree.parse(archive_dir / "eml.xml").getroot().find("dataset")
        for tag in ("title", "creator", "pubDate", "abstract", "intellectualRights", "contact"):
            if dataset is None or dataset.find(tag) is None:
                problems.append(f"eml.xml: no <{tag}>")
    except ElementTree.ParseError as exc:
        problems.append(f"eml.xml not well-formed: {exc}")
    return problems


# ------------------------------------------------------------------ I/O


def read_tsv(path: Path) -> list[dict]:
    import csv
    csv.field_size_limit(10 * 1024 * 1024)
    with Path(path).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h, delimiter="\t", quoting=csv.QUOTE_NONE))


def read_csv(path: Path) -> list[dict]:
    import csv
    with Path(path).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def country_codes(geonames_dir: Optional[Path], wanted: set[str]) -> dict[str, str]:
    """GeoNames id -> ISO country code from the cached country dumps (<CC>.zip with <CC>.txt)."""
    found: dict[str, str] = {}
    if not geonames_dir or not Path(geonames_dir).is_dir() or not wanted:
        return found
    for path in sorted(Path(geonames_dir).glob("*.zip")):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".txt") and not n.startswith("readme")]
            for name in names:
                with z.open(name) as h:
                    for raw in h:
                        gid, _, rest = raw.partition(b"\t")
                        key = gid.decode()
                        if key in wanted:
                            cols = rest.split(b"\t")
                            if len(cols) > 7:
                                found[key] = cols[7].decode()
        if len(found) == len(wanted):
            break
    return found


def source_method(source_dwca: Path) -> str:
    """The extraction method paragraph of the full archive's EML (model, prompt, sha256)."""
    try:
        root = ElementTree.parse(Path(source_dwca) / "eml.xml").getroot()
        para = root.find("dataset/methods/methodStep/description/para")
        if para is not None and para.text:
            return " ".join(para.text.split())
    except (OSError, ElementTree.ParseError):
        pass
    return "Records were extracted from the transcribed diary text by a documented LLM pipeline."


def export(cfg: GbifConfig, root: Path, today: Optional[_dt.date] = None) -> dict:
    """Write one Occurrence-core archive per dataset of ``cfg`` and the exclusion report."""
    from laubmann_kg.io.csv import write_rows

    today = today or _dt.date.today()
    resolve = lambda p: p if Path(p).is_absolute() else Path(root) / p   # noqa: E731
    src, quality_path, out = resolve(cfg.source_dwca), resolve(cfg.quality), resolve(cfg.output_dir)
    occurrences = read_tsv(src / "occurrence.txt")
    events = {e["eventID"]: e for e in read_tsv(src / "event.txt")}
    quality = {q["occurrenceID"]: q for q in read_csv(quality_path)}
    mof_by_occ: dict[str, list[dict]] = {}
    for m in read_tsv(src / "measurementorfact.txt"):
        mof_by_occ.setdefault(m["occurrenceID"], []).append(m)

    selected: dict[str, list[dict]] = {name: [] for name in cfg.datasets}
    exclusions: list[dict] = []
    for occ in occurrences:
        q = quality.get(occ["occurrenceID"])
        reason = exclusion_reason(occ, q, cfg.filter, record_type(mof_by_occ.get(occ["occurrenceID"], [])))
        name = dataset_for(occ, cfg.datasets) if reason is None else None
        if reason is None and name is None:
            reason = f"basisOfRecord {occ.get('basisOfRecord')} not exported"
        if reason is not None:
            exclusions.append({"occurrenceID": occ["occurrenceID"], "eventID": occ["eventID"],
                               "basisOfRecord": occ.get("basisOfRecord", ""), "recordedBy": occ.get("recordedBy", ""),
                               "eventDate": occ.get("eventDate", ""),
                               "p_any": (q or {}).get("p_any", ""), "reason": reason})
            continue
        selected[name].append(occ)

    wanted = {gid for rows in selected.values() for o in rows if (gid := geonames_id(o.get("locationID", "")))}
    countries = country_codes(resolve(cfg.geonames_dir) if cfg.geonames_dir else None, wanted)
    method = source_method(src)
    summary: dict = {"date": today.isoformat(), "source": {
        "dwca": str(cfg.source_dwca), "occurrence.txt sha256": sha256(src / "occurrence.txt"),
        "quality": str(cfg.quality), "quality sha256": sha256(quality_path),
        "records": len(occurrences)}, "filter": cfg.filter.model_dump(), "datasets": {}}
    for name, ds in cfg.datasets.items():
        rows = [occurrence_row(o, events.get(o["eventID"]), quality[o["occurrenceID"]], ds, cfg.metadata, countries)
                for o in selected[name]]
        mof = [m for o in selected[name] for m in mof_rows(mof_by_occ.get(o["occurrenceID"], []), quality[o["occurrenceID"]])]
        problems = validate_rows(rows, mof, ds, cfg.filter)
        expected = sum(float(quality[o["occurrenceID"]]["p_any"]) for o in selected[name])
        d = out / name
        write_rows(d / "occurrence.txt", rows, OCCURRENCE_FIELDS)
        write_rows(d / "measurementorfact.txt", mof, MOF_FIELDS)
        meta_xml = build_meta_xml(FileSpec("occurrence", "occurrence.txt", OCCURRENCE_FIELDS),
                                  [FileSpec("measurement_or_fact", "measurementorfact.txt", MOF_FIELDS)])
        (d / "meta.xml").write_text(meta_xml, encoding="utf-8")
        methods = methods_text(method, cfg.filter, len(rows), expected,
                               f"{cfg.source_dwca}, {len(occurrences):,} records")
        (d / "eml.xml").write_text(build_eml(ds, cfg.metadata, rows, methods, today), encoding="utf-8")
        problems += validate_files(d)
        with zipfile.ZipFile(out / ds.zip_name, "w", zipfile.ZIP_DEFLATED) as z:
            for f in ("occurrence.txt", "measurementorfact.txt", "meta.xml", "eml.xml"):
                z.write(d / f, arcname=f)
        summary["datasets"][name] = {
            "zip": str(cfg.output_dir / ds.zip_name), "records": len(rows), "events": len({r["eventID"] for r in rows}),
            "absent": sum(r["occurrenceStatus"] == "absent" for r in rows),
            "with coordinates": sum(bool(r.get("decimalLatitude")) for r in rows),
            "with countryCode": sum(bool(r.get("countryCode")) for r in rows),
            "measurements": len(mof), "expected wrong (any field)": round(expected),
            "expected share wrong %": round(100 * expected / len(rows), 1) if rows else None,
            "problems": problems}
    observer_rows = [e for e in exclusions if names_observer(e["recordedBy"], cfg.filter.observer)]
    summary["excluded"] = dict(Counter(e["reason"] for e in exclusions))
    summary[f"excluded records of {cfg.filter.observer}"] = dict(Counter(e["reason"] for e in observer_rows))
    write_rows(out / "exclusions.tsv", exclusions,
               ["occurrenceID", "eventID", "basisOfRecord", "recordedBy", "eventDate", "p_any", "reason"])
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
