"""Evaluate pipeline outputs."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run(config: Path, input_dir: Path, output_dir: Path) -> None:
    """Run the evaluation pipeline stage."""
    logger.info(
        "evaluation: config=%s input_dir=%s output_dir=%s",
        config,
        input_dir,
        output_dir,
    )
    raise NotImplementedError("evaluation is not yet implemented")
