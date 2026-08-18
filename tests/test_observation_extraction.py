from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from laubmann_kg.extraction.observations import extract_from_text, run
from laubmann_kg.extraction.schemas import (
    DiaryEntryModel,
    ObservationEventModel,
    PlaceModel,
    TaxonModel,
)
from laubmann_kg.llm.prompts import load_prompt


SAMPLE_ENTRY = """# 29. Mai 1925

Abfahrt München 17.00 Uhr mit der Bahn über Mering nach Gammertingen, Ankunft 24.00 Uhr,
danach noch ½ Std. zu Fuß nach Zwiefaltendorf.

Bei Mering einige Kiebitze (Vanellus vanellus) im Fluge.
In der Dämmerung schwirrt der Wachtelkönig.
Flügge Junge der Amsel eingesandt an die Zool. Sammlung.
"""


class FakeStructuredClient:
    def complete_structured(self, *, system_prompt, user_prompt, response_model, model):
        assert response_model is DiaryEntryModel
        assert "Kiebitze" in user_prompt
        assert system_prompt
        assert model
        return DiaryEntryModel(
            entry_date=date(1925, 5, 29),
            label="Tagebucheintrag 29. Mai 1925",
            raw_text=SAMPLE_ENTRY,
            observations=[
                ObservationEventModel(
                    label="Kiebitz-Beobachtung bei Mering",
                    observed_taxon=TaxonModel(
                        vernacular_name_de="Kiebitz",
                        scientific_name="Vanellus vanellus",
                    ),
                    observed_at=PlaceModel(name="Mering", verbatim_locality="Bei Mering"),
                    verbatim_notes="Bei Mering einige Kiebitze (Vanellus vanellus) im Fluge.",
                    count_qualifier="plural-unspecified",
                )
            ],
        )


def test_diary_entry_json_roundtrip() -> None:
    entry = DiaryEntryModel(
        entry_date=date(1925, 5, 29),
        label="Tagebucheintrag 29. Mai 1925",
        raw_text="Abfahrt München 17.00 Uhr.",
        observations=[],
    )
    restored = DiaryEntryModel.model_validate_json(entry.model_dump_json())
    assert restored.entry_date == entry.entry_date
    assert restored.raw_text == entry.raw_text
    assert restored.observations == []


def test_observation_event_schema_title() -> None:
    schema = ObservationEventModel.model_json_schema()
    assert schema["title"] == "Observation"
    assert "observed_taxon" in schema["properties"]
    assert "verbatim_notes" in schema["properties"]


def test_extract_from_text_uses_structured_client(tmp_path: Path) -> None:
    entry = extract_from_text(
        SAMPLE_ENTRY,
        client=FakeStructuredClient(),
        prompt=load_prompt(Path("prompts/extraction_prompt.yaml")),
        provider="google",
        model="gemini-3.5-flash",
        cache_dir=tmp_path / "cache",
    )
    assert entry.entry_date == date(1925, 5, 29)
    assert len(entry.observations) == 1
    assert entry.observations[0].observed_taxon.vernacular_name_de == "Kiebitz"


def test_extract_from_text_reads_llm_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    first = extract_from_text(
        SAMPLE_ENTRY,
        client=FakeStructuredClient(),
        prompt=load_prompt(Path("prompts/extraction_prompt.yaml")),
        model="gemini-3.5-flash",
        cache_dir=cache_dir,
    )

    class FailingClient:
        def complete_structured(self, **kwargs):
            raise AssertionError("cache miss: LLM should not be called")

    cached = extract_from_text(
        SAMPLE_ENTRY,
        client=FailingClient(),
        prompt=load_prompt(Path("prompts/extraction_prompt.yaml")),
        model="gemini-3.5-flash",
        cache_dir=cache_dir,
    )
    assert cached == first


def test_run_writes_extracted_json(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "vol01_page_012.md").write_text(SAMPLE_ENTRY, encoding="utf-8")

    monkeypatch.setattr(
        "laubmann_kg.extraction.observations.build_client",
        lambda provider: FakeStructuredClient(),
    )
    monkeypatch.setattr(
        "laubmann_kg.extraction.observations.extract_from_text",
        lambda text, **kwargs: FakeStructuredClient().complete_structured(
            system_prompt="s",
            user_prompt=text,
            response_model=DiaryEntryModel,
            model="test",
        ),
    )

    run(Path("configs/pipeline.yaml"), input_dir, output_dir)
    result_path = output_dir / "vol01_page_012.json"
    assert result_path.exists()
    payload = result_path.read_text(encoding="utf-8")
    assert "Kiebitz" in payload
    assert "gemini-3.5-flash" in payload or "prompt_version" in payload
    assert "vol01" in payload


def test_extraction_prompt_is_versioned() -> None:
    prompt = load_prompt(Path("prompts/extraction_prompt.yaml"))
    assert prompt.id == "observation_extraction"
    assert prompt.version == "1.0.0"
    assert "TimeEstimate" in prompt.system or "Zeitschätz" in prompt.system
    assert "auditory" in prompt.system
    assert "specimen" in prompt.system
    rendered = prompt.render_user("Hallo")
    assert "Hallo" in rendered
