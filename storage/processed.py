"""Track processed LinkedIn profile URLs for duplicate prevention and resume."""

from __future__ import annotations

import json
from pathlib import Path

from src.logger import get_logger
from src.utils import normalize_linkedin_url

logger = get_logger()


class ProcessedProfilesStore:
    """Persists processed profile URLs to JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._urls: set[str] = set()
        self.load()

    def load(self) -> None:
        """Load processed URLs from disk."""
        if not self.path.exists():
            self._urls = set()
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            urls = data.get("processed_urls", [])
            self._urls = {normalize_linkedin_url(u) for u in urls if u}
            logger.info("Loaded %d processed profiles", len(self._urls))
        except Exception as exc:
            logger.error("Failed to load processed profiles: %s", exc)
            self._urls = set()

    def save(self) -> None:
        """Persist processed URLs to disk."""
        payload = {
            "processed_urls": sorted(self._urls),
            "count": len(self._urls),
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def is_processed(self, url: str) -> bool:
        """Check if a profile URL has already been processed."""
        return normalize_linkedin_url(url) in self._urls

    def mark_processed(self, url: str) -> None:
        """Mark a profile URL as processed and save immediately."""
        normalized = normalize_linkedin_url(url)
        if normalized:
            self._urls.add(normalized)
            self.save()

    @property
    def count(self) -> int:
        return len(self._urls)
