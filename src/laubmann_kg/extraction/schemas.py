"""Pydantic models for LLM extraction of diary entries and observations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlaceModel(BaseModel):
    name: str = Field(
        ...,
        description="Standardisierter Name des Ortes (z.B. 'München', 'Zwiefaltendorf').",
    )
    verbatim_locality: str | None = Field(
        None,
        description="Der exakte Textausschnitt, wie der Ort im Tagebuch genannt wird (dwc:verbatimLocality).",
    )


class TaxonModel(BaseModel):
    vernacular_name_de: str = Field(
        ...,
        description="Deutscher Trivialname des Vogels (z.B. 'Kiebitz', 'Wachtelkönig').",
    )
    scientific_name: str | None = Field(
        None,
        description="Wissenschaftlicher (lateinischer) Name, falls im Text genannt oder eindeutig bestimmbar (z.B. 'Vanellus vanellus').",
    )


class TimeEstimateModel(BaseModel):
    beginning: datetime = Field(
        ...,
        description="Geschätzter Startzeitpunkt (ISO 8601, z.B. '1925-05-29T17:00:00').",
    )
    end: datetime = Field(
        ...,
        description="Geschätzter Endzeitpunkt (ISO 8601, z.B. '1925-05-29T18:30:00').",
    )
    note: str = Field(
        ...,
        description="Begründung/Herleitung der Schätzung (skos:note, z.B. 'Abfahrt München 17:00 Uhr; Mering ca. 60 min später').",
    )


class BirdCallModel(BaseModel):
    call_type: Literal["song", "call", "alarm", "drumming", "unknown"] = Field(
        "unknown",
        description="Art des Rufs (z.B. 'song' für Gesang, 'call' für Ruf).",
    )
    call_transcription: str | None = Field(
        None,
        description="Lautmalerische Umschrift aus dem Text (z.B. 'pich pich', 'Schnarren').",
    )


class EvidenceModel(BaseModel):
    type: Literal["visual", "auditory", "specimen", "nest", "other"] = Field(
        ...,
        description="Art des Belegs (Sichtbeobachtung, Gehört, Balg/Spezimen, Nestfund).",
    )
    bird_call: BirdCallModel | None = Field(
        None,
        description="Details zum Ruf, falls es sich um einen akustischen Beleg handelt.",
    )


class BehaviourNoteModel(BaseModel):
    description: str = Field(
        ...,
        description="Beschreibung des Verhaltens (z.B. 'brütend', 'flügge Junge eingesandt').",
    )
    reproductive_condition: Literal["breeding", "non-breeding"] | None = Field(
        None,
        description="Fortpflanzungsstatus (dwc:reproductiveCondition).",
    )


class TravelLegModel(BaseModel):
    transport_mode: Literal["train", "foot", "carriage", "boat", "car", "unknown"] = Field(
        ...,
        description="Transportmittel (lkg:transportMode).",
    )
    departure_place: PlaceModel = Field(..., description="Startpunkt des Abschnitts.")
    arrival_place: PlaceModel = Field(..., description="Endpunkt des Abschnitts.")
    departure_time: datetime | None = Field(
        None,
        description="Abfahrtszeit, falls bekannt oder schätzbar.",
    )
    arrival_time: datetime | None = Field(
        None,
        description="Ankunftszeit, falls bekannt oder schätzbar.",
    )
    via_places: list[PlaceModel] = Field(
        default_factory=list,
        description="Orte, die auf dem Weg passiert wurden.",
    )


class TravelEventModel(BaseModel):
    label: str = Field(
        ...,
        description="Titel der Reise (z.B. 'Reise München – Gammertingen').",
    )
    legs: list[TravelLegModel] = Field(..., description="Die einzelnen Abschnitte der Reise.")


class ObservationEventModel(BaseModel):
    model_config = ConfigDict(title="Observation")

    label: str = Field(
        ...,
        description="Kurzer Titel der Beobachtung (z.B. 'Kiebitz-Beobachtung bei Mering').",
    )
    observed_taxon: TaxonModel = Field(...)
    observed_at: PlaceModel = Field(..., description="Ort der Beobachtung.")
    verbatim_notes: str = Field(
        ...,
        description="Der originale Textausschnitt zur Beobachtung (lkg:verbatimNotes).",
    )
    count_qualifier: Literal[
        "exact",
        "minimum",
        "approximate",
        "plural-unspecified",
        "single",
    ] = Field(
        "plural-unspecified",
        description="Mengenangabe-Klassifikation (z.B. 'plural-unspecified' bei 'einige').",
    )
    individual_count: int | None = Field(
        None,
        description="Genaue Anzahl Individuen, falls exakt beziffert.",
    )
    evidence: EvidenceModel | None = Field(None)
    behaviour: BehaviourNoteModel | None = Field(None)
    time_estimate: TimeEstimateModel | None = Field(
        None,
        description="Zeitschätzung für die Beobachtung.",
    )


class DiaryEntryModel(BaseModel):
    model_config = ConfigDict(title="DiaryEntry")

    entry_date: date = Field(
        ...,
        description="Das Datum des Eintrags im Format YYYY-MM-DD (lkg:entryDate).",
    )
    label: str = Field(
        ...,
        description="Titel des Eintrags (z.B. 'Tagebucheintrag 29. Mai 1925').",
    )
    raw_text: str = Field(..., description="Der rohe, transkribierte Text dieses Eintrags.")
    travel_event: TravelEventModel | None = Field(
        None,
        description="Die im Eintrag beschriebene Reise.",
    )
    observations: list[ObservationEventModel] = Field(
        default_factory=list,
        description="Alle im Eintrag erwähnten Vogelbeobachtungen.",
    )


class ExtractionProvenance(BaseModel):
    """Provenance metadata attached to an extraction result (not filled by the LLM)."""

    source_path: str
    volume: str | None = None
    page: str | None = None
    side: str | None = None
    region: str | None = None
    text_span: str | None = None
    model: str
    provider: str
    prompt_id: str
    prompt_version: str
    confidence: float | None = None
    extracted_at: datetime


class ExtractedDocument(BaseModel):
    """Diary entry plus pipeline provenance for JSON export."""

    provenance: ExtractionProvenance
    diary_entry: DiaryEntryModel
