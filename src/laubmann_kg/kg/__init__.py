"""Export knowledge graph artifacts (RDF/Turtle + JSON-LD), SHACL-validated."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from laubmann_kg.kg.jsonld import write_jsonld
from laubmann_kg.kg.rdf import build_graph, serialize_turtle
from laubmann_kg.kg.shacl_validate import run_shacl_validation

logger = logging.getLogger(__name__)


def export(config: dict, input_dir: Optional[Path], output_dir: Path,
           validate: bool = True, result=None) -> dict:
    """RDF/Turtle + JSON-LD (+ SHACL) of ``result``; runs the pipeline when no
    result is passed. ``export_all`` shares one pipeline run with the DwC-A."""
    if result is None:
        from laubmann_kg.pipeline import run_pipeline
        result = run_pipeline(config, input_dir)

    output_dir = Path(output_dir)
    if result.qa_flags:
        from laubmann_kg.qa import write_review_table
        write_review_table(result.qa_flags, output_dir / "review" / "qa_flags.csv")

    graph = build_graph(result)
    ttl_path = output_dir / "rdf" / "laubmann_sample.ttl"
    jsonld_path = output_dir / "jsonld" / "laubmann_sample.jsonld"
    serialize_turtle(graph, ttl_path)
    context = config.get("paths", {}).get("jsonld_context", "schemas/jsonld_context.json")
    write_jsonld(graph, jsonld_path, Path(context))

    from laubmann_kg.kg.explorer import write_explorer
    explorer_meta = {
        "source": ttl_path.name,
        "ontology": (config.get("paths") or {}).get("ontology", "ontologies/laubmann.ttl"),
        "triples": len(graph),
        "sample": config.get("sample") or {},
        "backend": (result.provenance or {}).get("backend"),
        "model": (result.provenance or {}).get("model"),
        "prompt_sha256": (result.provenance or {}).get("prompt_sha256"),
        "started_at": (result.provenance or {}).get("started_at"),
    }
    explorer = write_explorer(result, output_dir, meta=explorer_meta)
    (output_dir / "run.json").write_text(
        json.dumps({**explorer_meta, "entries": len(result.entries),
                     "observations": len(result.observations),
                     "ttl": str(ttl_path), "explorer": explorer},
                    ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    conforms = True
    if validate and config.get("validate", True):
        paths = config.get("paths", {})
        conforms = run_shacl_validation(
            data_path=str(ttl_path),
            ontology_path=paths.get("ontology", "ontologies/laubmann.ttl"),
            shapes_path=paths.get("shapes", "ontologies/shacl_shapes.ttl"),
        )
        if not conforms:
            raise SystemExit("SHACL validation failed (violations) – export aborted.")

    return {
        "entries": len(result.entries),
        "observations": len(result.observations),
        "triples": len(graph),
        "ttl": str(ttl_path),
        "jsonld": str(jsonld_path),
        "shacl_conforms": conforms,
        "explorer": explorer,
    }


def export_all(config: dict, input_dir: Optional[Path], output_dir: Path, validate: bool = True) -> dict:
    """One pipeline run -> RDF/JSON-LD (+ SHACL) and the Darwin Core Archive.
    The two exports are consistent by construction (a live LLM call for an
    uncached entry is made once, not once per export)."""
    from laubmann_kg.dwca import export as export_dwca
    from laubmann_kg.pipeline import run_pipeline
    result = run_pipeline(config, input_dir)
    summary = export(config, input_dir, output_dir, validate=validate, result=result)
    summary["dwca"] = export_dwca(config, input_dir, output_dir, validate=validate, result=result)
    return summary


def run(config: Path, input_dir: Path, output_dir: Path) -> None:
    """Run the kg export pipeline stage."""
    from laubmann_kg.pipeline import load_config
    logger.info("kg export: config=%s input_dir=%s output_dir=%s", config, input_dir, output_dir)
    summary = export(load_config(config), input_dir, output_dir)
    logger.info("kg export summary: %s", summary)


def run_all(config: Path, input_dir: Path, output_dir: Path) -> None:
    """Run RDF/JSON-LD + SHACL + DwC-A from one pipeline run."""
    from laubmann_kg.pipeline import load_config
    logger.info("kg+dwca export: config=%s input_dir=%s output_dir=%s", config, input_dir, output_dir)
    summary = export_all(load_config(config), input_dir, output_dir)
    logger.info("kg+dwca export summary: %s", summary)
