#!/usr/bin/env python3
"""Run the layout detection stage."""

from __future__ import annotations

import argparse
from pathlib import Path

from laubmann_kg.layout import run
from laubmann_kg.logging_config import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the layout detection stage.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    setup_logging()
    run(config=args.config, input_dir=args.input_dir, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
