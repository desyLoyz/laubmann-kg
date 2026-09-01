#!/usr/bin/env python
"""Run rule-based extraction directly on .md files, bypassing entries.csv."""

from dataclasses import asdict
from pathlib import Path
import json

from laubmann_kg.kg.model import DiaryEntry
from laubmann_kg.normalization.taxa import build_resolver
from laubmann_kg.extraction.observations import extract_observations

# --- Anpassen ---
VOLUME = 1  # Bandnummer -- DiaryEntry.volume ist Pflichtfeld (int)
INPUT_DIR = Path("data/examples/raw/md")
OUTPUT_DIR = Path("data/examples/extracted")
# Optional: links_long_path setzen, falls ihr eine Index-Tabelle habt, z.B.
# resolver = build_resolver({"links_long_path": "data/index/links_long.csv"})
resolver = build_resolver()  # -> SeedTaxonResolver (nutzt BIRD_GAZETTEER)
# ----------------

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for md_file in sorted(INPUT_DIR.glob("*.md")):
    text = md_file.read_text(encoding="utf-8")

    entry = DiaryEntry(
        entry_uid=md_file.stem,
        entry_id=md_file.stem,
        volume=VOLUME,
        page_uid=md_file.stem,
        page_id=md_file.stem,
        region_uid=None,
        scan=None,
        entry_date=None,
        verbatim_event_date=None,
        location_raw=None,
        text_clean=text,
    )

    observations = extract_observations(entry, resolver)
    entry.observations = observations

    out_path = OUTPUT_DIR / f"{md_file.stem}.json"
    payload = {
        "entry": {k: v for k, v in asdict(entry).items() if k != "observations"},
        "observations": [asdict(obs) for obs in observations],
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"✔ {md_file.name}: {len(observations)} Beobachtung(en)")
