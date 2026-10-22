"""GBIF Darwin Core Archives of Alfred Laubmann's own records below an error threshold.

    python tools/export_gbif_subset.py                       # configs/gbif_laubmann.yaml
    python tools/export_gbif_subset.py --config my.yaml --max-error 0.25

Reads the full archive (source_dwca) and record_quality.csv, writes per dataset
output_dir/<name>/ (occurrence.txt, measurementorfact.txt, meta.xml, eml.xml) and
output_dir/<zip_name>, plus output_dir/exclusions.tsv (one row per record left
out, with its reason) and output_dir/summary.json. See docs/gbif_export.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from laubmann_kg.dwca.gbif import GbifConfig, export  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=ROOT / "configs" / "gbif_laubmann.yaml")
    ap.add_argument("--max-error", type=float, help="override filter.max_error")
    args = ap.parse_args()
    cfg = GbifConfig.model_validate(yaml.safe_load(args.config.read_text(encoding="utf-8")))
    if args.max_error is not None:
        cfg.filter.max_error = args.max_error
    summary = export(cfg, ROOT)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if any(d["problems"] for d in summary["datasets"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
