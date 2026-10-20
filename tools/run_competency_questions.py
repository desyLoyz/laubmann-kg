"""Run the competency-question SPARQL queries (docs/competency_questions.md) on an exported graph.

    python tools/run_competency_questions.py output/jsonld/laubmann_kg.jsonld
    python tools/run_competency_questions.py graph.ttl --only CQ1 CQ4 --limit 5
    python tools/run_competency_questions.py graph.ttl --ontology ontologies/laubmann.ttl --check-terms

Per question: number of result rows, the first rows, run time. A question that
returns 0 rows is reported as EMPTY (not necessarily wrong: the data may not
contain the pattern); a query that raises is reported as ERROR.

--check-terms additionally lists every lkg: term used in the queries that the
ontology does not declare, i.e. a query that is out of date with the ontology.
The graph format is taken from the file suffix (.ttl, .jsonld, .nt).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from rdflib import Graph, Namespace, RDF, OWL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from laubmann_kg.kg.sparql import QUERIES  # noqa: E402

LKG = Namespace("https://w3id.org/laubmann-kg/ontology#")
FORMATS = {".ttl": "turtle", ".jsonld": "json-ld", ".json": "json-ld", ".nt": "nt"}


def load(path: Path) -> Graph:
    g = Graph()
    t0 = time.time()
    g.parse(str(path), format=FORMATS.get(path.suffix.lower(), "turtle"))
    print(f"loaded {path} : {len(g):,} triples in {time.time() - t0:.0f} s")
    return g


def undeclared_terms(ontology: Path, vocab: Path | None) -> dict[str, list[str]]:
    """lkg: terms used in the queries but not defined in the ontology / vocabularies."""
    og = Graph()
    og.parse(str(ontology), format="turtle")
    if vocab and vocab.exists():
        og.parse(str(vocab), format="turtle")
    declared = {str(s) for s in og.subjects() if str(s).startswith(str(LKG))}
    out: dict[str, list[str]] = {}
    for key, q in QUERIES.items():
        used = {LKG[m] for m in re.findall(r"lkg:([A-Za-z0-9_]+)", q)}
        missing = sorted(str(u).removeprefix(str(LKG)) for u in used if str(u) not in declared)
        if missing:
            out[key] = missing
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("graph", type=Path, nargs="?", help="exported graph (.ttl / .jsonld / .nt)")
    ap.add_argument("--only", nargs="*", help="question ids, e.g. CQ1 CQ4 (default: all)")
    ap.add_argument("--limit", type=int, default=3, help="rows to print per question (default 3)")
    ap.add_argument("--check-terms", action="store_true", help="check the lkg: terms of the queries against the ontology")
    ap.add_argument("--ontology", type=Path, default=ROOT / "ontologies" / "laubmann.ttl")
    ap.add_argument("--vocabularies", type=Path, default=ROOT / "ontologies" / "controlled_vocabularies.ttl")
    args = ap.parse_args()

    rc = 0
    if args.check_terms:
        bad = undeclared_terms(args.ontology, args.vocabularies)
        print("== lkg: terms used in the queries and not declared in the ontology ==")
        if bad:
            rc = 1
            for k, v in bad.items():
                print(f"  {k}: {', '.join(v)}")
        else:
            print("  none")
    if not args.graph:
        return rc

    keys = [k for k in QUERIES if not args.only or any(k.startswith(o + "_") or k == o for o in args.only)]
    g = load(args.graph)
    print(f"\n{'question':36s} {'status':6s} {'rows':>8s} {'sec':>6s}")
    for key in keys:
        t0 = time.time()
        try:
            res = g.query(QUERIES[key])
            rows = list(res)
            status = "OK" if rows else "EMPTY"
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            print(f"{key:36s} ERROR  {exc}")
            rc = 1
            continue
        print(f"{key:36s} {status:6s} {len(rows):8d} {time.time() - t0:6.1f}")
        for row in rows[: args.limit]:
            print("    " + " | ".join(f"{v}={str(row[v])[:60]}" for v in res.vars))
        if status == "EMPTY":
            rc = rc or 2
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
