"""Sales Navigator page-state diagnostics (investigation only — no workflow changes)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from scrapers.sales_navigator import SalesNavigatorScraper
from src.logger import get_logger

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from config.settings import Settings

logger = get_logger()

INVESTIGATION_DIR = Path(__file__).resolve().parent.parent / "audits" / "sn_investigation"


def diagnose_sn_page(page: Page, label: str) -> dict:
    """Log URL, saved-search detection, and per-selector card counts."""
    url = page.url
    is_search = "/sales/search" in url.lower()
    saved_search = any(p in url.lower() for p in SalesNavigatorScraper.SEARCH_URL_PATTERNS)

    selector_counts: dict[str, int] = {}
    for selector in SalesNavigatorScraper.CARD_SELECTORS:
        try:
            selector_counts[selector] = page.locator(selector).count()
        except Exception:
            selector_counts[selector] = -1

    extra_counts = {}
    for selector in (
        '[data-anonymize="person-name"]',
        "li.artdeco-list__item",
        ".artdeco-modal",
        '[role="dialog"]',
    ):
        try:
            extra_counts[selector] = page.locator(selector).count()
        except Exception:
            extra_counts[selector] = -1

    total_cards = max(selector_counts.values()) if selector_counts else 0
    winning_selector = max(selector_counts, key=selector_counts.get) if selector_counts else ""

    logger.info(
        "SN_DIAG [%s] url=%s | saved_search=%s | is_search_url=%s | "
        "max_card_count=%d | winning_selector=%r",
        label,
        url[:160],
        saved_search,
        is_search,
        total_cards,
        winning_selector,
    )
    for sel, cnt in selector_counts.items():
        logger.info("SN_DIAG [%s] selector %r => count=%d", label, sel, cnt)
    for sel, cnt in extra_counts.items():
        logger.info("SN_DIAG [%s] extra %r => count=%d", label, sel, cnt)

    return {
        "label": label,
        "url": url,
        "saved_search": saved_search,
        "is_search_url": is_search,
        "selector_counts": selector_counts,
        "extra_counts": extra_counts,
        "max_card_count": total_cards,
        "winning_selector": winning_selector,
    }


def capture_sn_failure_artifacts(page: Page, settings: Settings, label: str) -> tuple[str, str]:
    """Save screenshot and HTML dump when SN detection fails."""
    INVESTIGATION_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = label.replace(" ", "_").replace("/", "_")[:40]
    screenshot_path = INVESTIGATION_DIR / f"{ts}_{safe_label}.png"
    html_path = INVESTIGATION_DIR / f"{ts}_{safe_label}.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.info("SN_DIAG artifact screenshot: %s", screenshot_path)
    except Exception as exc:
        logger.warning("SN_DIAG screenshot failed: %s", exc)
        screenshot_path = Path("")

    try:
        html = page.content()
        html_path.write_text(html, encoding="utf-8")
        logger.info("SN_DIAG artifact HTML: %s (%d bytes)", html_path, len(html))
    except Exception as exc:
        logger.warning("SN_DIAG HTML dump failed: %s", exc)
        html_path = Path("")

    return str(screenshot_path), str(html_path)
