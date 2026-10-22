"""Generate the DwC-A meta.xml descriptor for an Event-core star schema."""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

DWC = "http://rs.tdwg.org/dwc/terms/"
DC = "http://purl.org/dc/terms/"
OBIS = "http://rs.iobis.org/obis/terms/"

ROW_TYPES = {
    "event": DWC + "Event",
    "occurrence": DWC + "Occurrence",
    "measurement_or_fact": OBIS + "ExtendedMeasurementOrFact",
    "multimedia": "http://rs.gbif.org/terms/1.0/Multimedia",
}

# Term URI per field name; anything not listed is a Darwin Core term.
# Multimedia uses Dublin Core terms; the eMoF *ID terms are OBIS terms (the
# extension predates any DwC equivalent).
TERM_URI = {
    "identifier": DC + "identifier",
    "type": DC + "type",
    "format": DC + "format",
    "title": DC + "title",
    "description": DC + "description",
    "license": DC + "license",
    "rightsHolder": DC + "rightsHolder",
    "language": DC + "language",
    "measurementTypeID": OBIS + "measurementTypeID",
    "measurementValueID": OBIS + "measurementValueID",
    "measurementUnitID": OBIS + "measurementUnitID",
}


def _term(field: str) -> str:
    return TERM_URI.get(field, DWC + field)


@dataclass
class FileSpec:
    kind: str            # key into ROW_TYPES
    filename: str
    fields: list[str]    # index 0 must be the join key (eventID)


def _field_elements(fields: list[str], is_core: bool) -> str:
    lines = []
    for index, field in enumerate(fields):
        if index == 0 and not is_core:
            continue  # extensions: the coreid column carries no term
        # core: GBIF/IPT convention -- the id column is ALSO declared as a
        # term (dwc:eventID) so it is interpreted, not just used for joining
        lines.append(f'    <field index="{index}" term={quoteattr(_term(field))}/>')
    return "\n".join(lines)


def _table(spec: FileSpec, is_core: bool) -> str:
    tag = "core" if is_core else "extension"
    id_tag = "id" if is_core else "coreid"
    attrs = ('encoding="UTF-8" fieldsTerminatedBy="\\t" linesTerminatedBy="\\n" '
             'fieldsEnclosedBy="" ignoreHeaderLines="1"')
    return (
        f'  <{tag} {attrs} rowType={quoteattr(ROW_TYPES[spec.kind])}>\n'
        f'    <files><location>{spec.filename}</location></files>\n'
        f'    <{id_tag} index="0"/>\n'
        f'{_field_elements(spec.fields, is_core)}\n'
        f'  </{tag}>'
    )


def build_meta_xml(core: FileSpec, extensions: list[FileSpec],
                   metadata: str = "eml.xml") -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<archive xmlns="http://rs.tdwg.org/dwc/text/" metadata="{metadata}">',
             _table(core, is_core=True)]
    parts.extend(_table(ext, is_core=False) for ext in extensions)
    parts.append("</archive>")
    return "\n".join(parts) + "\n"
