"""
src/laubmann_kg/kg/shacl_validate.py
=====================================
Validiert den generierten Knowledge Graph gegen die SHACL-Shapes.
Gibt einen kompakten, nach Severity gruppierten Report aus.

CLI-Nutzung (Standalone):
    python -m laubmann_kg.kg.shacl_validate \
        --data tests/fixtures/lkg_full.ttl \
        --ontology ontologies/laubmann.ttl \
        --shapes ontologies/shacl_shapes.ttl

Programmatische Nutzung (z.B. aus scripts/run_kg_export.py):
    from laubmann_kg.kg.shacl_validate import run_shacl_validation
    ok = run_shacl_validation(
        data_path="data/exports/rdf/entries.ttl",
        ontology_path="ontologies/laubmann.ttl",
        shapes_path="ontologies/shacl_shapes.ttl",
    )
    if not ok:
        raise SystemExit("SHACL-Validierung fehlgeschlagen – Export abgebrochen.")
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Namespace, RDF
from pyshacl import validate

SH = Namespace("http://www.w3.org/ns/shacl#")


def run_validation(data_path: str, ontology_path: str, shapes_path: str) -> Graph:
    """Lädt Daten + Ontologie zusammen (für RDFS-Subklassen-Inferenz)
    und validiert gegen die SHACL-Shapes."""
    data_graph = Graph()
    data_graph.parse(data_path, format="turtle")
    data_graph.parse(ontology_path, format="turtle")

    shapes_graph = Graph()
    shapes_graph.parse(shapes_path, format="turtle")

    conforms, report_graph, _ = validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        abort_on_first=False,
        meta_shacl=False,
        debug=False,
    )
    return report_graph


def parse_results(report_graph: Graph) -> list[dict]:
    results = []
    for result in report_graph.subjects(RDF.type, SH.ValidationResult):
        severity = report_graph.value(result, SH.resultSeverity)
        focus_node = report_graph.value(result, SH.focusNode)
        path = report_graph.value(result, SH.resultPath)
        message = report_graph.value(result, SH.resultMessage)
        results.append({
            "severity": str(severity).rsplit("#", 1)[-1] if severity else "Unknown",
            "focus_node": str(focus_node) if focus_node else "-",
            "path": str(path).rsplit("#", 1)[-1] if path else "-",
            "message": str(message) if message else "-",
        })
    return results


def print_grouped_report(results: list[dict]) -> int:
    grouped = defaultdict(list)
    for r in results:
        grouped[r["severity"]].append(r)

    order = ["Violation", "Warning", "Info", "Unknown"]
    icons = {"Violation": "🔴", "Warning": "🟡", "Info": "🔵", "Unknown": "⚪"}

    print("=" * 70)
    print("SHACL VALIDIERUNGS-REPORT")
    print("=" * 70)

    for sev in order:
        items = grouped.get(sev, [])
        if not items:
            continue
        print(f"\n{icons.get(sev, '⚪')} {sev} ({len(items)}):")
        print("-" * 70)
        for i, r in enumerate(items, 1):
            print(f"  [{i}] {r['focus_node']}")
            print(f"      Path:    {r['path']}")
            print(f"      Message: {r['message']}")

    n_violations = len(grouped.get("Violation", []))
    n_warnings = len(grouped.get("Warning", []))

    print("\n" + "=" * 70)
    print(f"SUMMARY: {n_violations} Violation(s), {n_warnings} Warning(s)")
    status = "❌ FAILED (Violations gefunden)" if n_violations else "✅ PASSED"
    print(f"STATUS: {status}")
    print("=" * 70)

    return n_violations


def run_shacl_validation(data_path: str, ontology_path: str, shapes_path: str) -> bool:
    """Einstiegspunkt für programmatische Nutzung aus anderen Modulen
    (z.B. scripts/run_kg_export.py). Gibt True zurück, wenn KEINE
    sh:Violation gefunden wurde (Warnings sind erlaubt)."""
    report_graph = run_validation(data_path, ontology_path, shapes_path)
    results = parse_results(report_graph)
    n_violations = print_grouped_report(results)
    return n_violations == 0


def main():
    parser = argparse.ArgumentParser(
        description="SHACL-Validierung für laubmann-kg"
    )
    parser.add_argument(
        "--data", required=True,
        help="Pfad zu den Instanzdaten, z.B. tests/fixtures/lkg_full.ttl"
    )
    parser.add_argument(
        "--ontology", default="ontologies/laubmann.ttl",
        help="Pfad zur Ontologie (Default: ontologies/laubmann.ttl)"
    )
    parser.add_argument(
        "--shapes", default="ontologies/shacl_shapes.ttl",
        help="Pfad zu den SHACL-Shapes (Default: ontologies/shacl_shapes.ttl)"
    )
    args = parser.parse_args()

    for p in (args.data, args.ontology, args.shapes):
        if not Path(p).exists():
            print(f"❌ Datei nicht gefunden: {p}", file=sys.stderr)
            sys.exit(2)

    ok = run_shacl_validation(args.data, args.ontology, args.shapes)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
