"""Wait for ChatGPT response generation to complete."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.errors import ChatGPTTimeoutError
from src.logger import get_logger
from src.utils import clean_text

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from config.settings import Settings

logger = get_logger()

GENERATING_INDICATORS = [
    'button[data-testid="stop-button"]',
    'button[aria-label="Stop generating"]',
    'button:has-text("Stop generating")',
    'button:has-text("Stop")',
]

RESPONSE_SELECTORS = [
    '[data-message-author-role="assistant"]',
    "div.markdown",
    "article[data-testid^='conversation-turn']",
]


def _is_generating(page: Page) -> bool:
    for selector in GENERATING_INDICATORS:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=300):
                return True
        except Exception:
            continue
    return False


def _count_assistant_messages(page: Page) -> int:
    for selector in RESPONSE_SELECTORS:
        try:
            count = page.locator(selector).count()
            if count:
                return count
        except Exception:
            continue
    return 0


def _get_latest_response_text(page: Page, *, min_index: int = 0) -> str:
    for selector in RESPONSE_SELECTORS:
        try:
            messages = page.locator(selector)
            count = messages.count()
            if count <= min_index:
                continue

            latest = messages.nth(count - 1)
            if latest.is_visible(timeout=1000):
                text = clean_text(latest.inner_text(timeout=3000))
                if text:
                    return text
        except Exception:
            continue
    return ""


def wait_for_generation_complete(
    page: Page,
    settings: Settings,
    *,
    baseline_message_count: int | None = None,
    require_marker: str | None = "CONNECTION_REQUEST",
) -> str:
    """
    Wait until ChatGPT finishes generating a NEW assistant message.

    When require_marker is set, the latest message must contain that text
    (e.g. CONNECTION_REQUEST) to avoid correlating with stale responses.
    """
    start = time.time()
    timeout = settings.chatgpt_response_timeout_sec
    stability_checks = settings.chatgpt_stability_checks
    stability_interval = settings.chatgpt_stability_interval_sec
    min_index = baseline_message_count or 0

    logger.info(
        "Waiting for ChatGPT response (baseline=%d, marker=%r)...",
        min_index,
        require_marker,
    )

    generation_started = False
    while time.time() - start < min(timeout, 45):
        if _is_generating(page):
            generation_started = True
            break
        if _count_assistant_messages(page) > min_index:
            generation_started = True
            break
        page.wait_for_timeout(500)

    if not generation_started:
        logger.warning("Generation start not detected; monitoring for new assistant message")

    while time.time() - start < timeout:
        if not _is_generating(page):
            break
        page.wait_for_timeout(500)

    previous_text = ""
    stable_count = 0

    while time.time() - start < timeout:
        if _is_generating(page):
            stable_count = 0
            previous_text = ""
            page.wait_for_timeout(500)
            continue

        current_count = _count_assistant_messages(page)
        if current_count <= min_index:
            page.wait_for_timeout(int(stability_interval * 1000))
            continue

        current_text = _get_latest_response_text(page, min_index=min_index)

        if not current_text:
            page.wait_for_timeout(int(stability_interval * 1000))
            continue

        if require_marker and require_marker not in current_text:
            page.wait_for_timeout(int(stability_interval * 1000))
            continue

        if current_text == previous_text:
            stable_count += 1
            if stable_count >= stability_checks:
                logger.info("ChatGPT response stable (%d chars)", len(current_text))
                return current_text
        else:
            stable_count = 0
            previous_text = current_text

        page.wait_for_timeout(int(stability_interval * 1000))

    partial = _get_latest_response_text(page, min_index=min_index)
    if partial and (not require_marker or require_marker in partial):
        logger.warning("ChatGPT timeout with partial response (%d chars)", len(partial))
        return partial

    raise ChatGPTTimeoutError(
        f"ChatGPT did not complete within {timeout} seconds"
    )
