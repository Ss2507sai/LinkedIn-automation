"""Screenshot capture on errors."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from src.logger import get_logger

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from config.settings import Settings


logger = get_logger()


def capture_error_screenshot(
    page: Page | None,
    settings: Settings,
    label: str,
) -> str | None:
    """Capture a timestamped screenshot when an error occurs."""
    if page is None:
        return None

    settings.ensure_directories()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:60]
    path = settings.screenshots_dir / f"{timestamp}_{safe_label}.png"

    try:
        page.screenshot(path=str(path), full_page=True)
        logger.error("Screenshot saved: %s", path)
        return str(path)
    except Exception as exc:
        logger.error("Failed to capture screenshot: %s", exc)
        return None
