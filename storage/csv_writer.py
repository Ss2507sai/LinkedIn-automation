"""CSV export for prospect results."""

from __future__ import annotations

import csv
from pathlib import Path

from src.logger import get_logger
from storage.results import COLUMNS, ProspectResult

logger = get_logger()


class CSVWriter:
    """Append prospect results to a CSV file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, result: ProspectResult) -> None:
        """Append a single result row."""
        file_exists = self.path.exists()
        row = result.to_row()

        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        logger.info("CSV saved: %s", self.path)
