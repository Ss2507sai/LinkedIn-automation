"""Shared utility helpers."""

from __future__ import annotations

import random
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from config.settings import Settings


def human_delay(settings: Settings) -> None:
    """Sleep for a random duration within the configured range."""
    delay = random.uniform(settings.delay_min, settings.delay_max)
    time.sleep(delay)


def normalize_linkedin_url(url: str) -> str:
    """Normalize LinkedIn profile URLs for duplicate detection."""
    if not url:
        return ""

    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")

    # Strip query params and fragments; keep scheme + netloc + path
    clean = urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))
    return clean.lower()


def clean_text(text: str | None) -> str:
    """Collapse whitespace and strip text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def wait_for_network_idle(page: Page, timeout_ms: int = 15_000) -> None:
    """Wait until the page network activity settles."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # LinkedIn pages often never reach true networkidle
        page.wait_for_timeout(1500)


def dismiss_linkedin_popups(page: Page) -> None:
    """Attempt to close common LinkedIn modal overlays."""
    selectors = [
        'button[aria-label="Dismiss"]',
        'button[aria-label="Close"]',
        'button.artdeco-modal__dismiss',
        'button[data-test-modal-close-btn]',
        'button:has-text("Not now")',
        'button:has-text("Got it")',
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=500):
                button.click(timeout=2000)
                page.wait_for_timeout(400)
        except Exception:
            continue
