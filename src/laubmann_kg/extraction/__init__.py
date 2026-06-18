"""Extract structured observations."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run(config: Path, input_dir: Path, output_dir: Path) -> None:
    """Run the extraction pipeline stage."""
    logger.info(
        "extraction: config=%s input_dir=%s output_dir=%s",
        config,
        input_dir,
        output_dir,
    )
    raise NotImplementedError("extraction is not yet implemented")
