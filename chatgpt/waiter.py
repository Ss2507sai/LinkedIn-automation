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


def _effective_min_index(page: Page, baseline: int, *, generation_done: bool) -> int:
    """
    Resolve which assistant message index to read.

    ChatGPT may stop adding new DOM nodes after a few turns (count plateaus).
    When baseline equals the visible count but generation finished, read the
    latest visible assistant message (index count - 1).
    """
    count = _count_assistant_messages(page)
    if count > baseline:
        return baseline
    if generation_done and count > 0:
        return count - 1
    return baseline


def _get_all_assistant_texts(page: Page) -> list[str]:
    """Return inner text for every assistant message (primary selector)."""
    texts: list[str] = []
    selector = RESPONSE_SELECTORS[0]
    try:
        messages = page.locator(selector)
        count = messages.count()
        for i in range(count):
            try:
                text = clean_text(messages.nth(i).inner_text(timeout=2000))
                if text:
                    texts.append(text)
            except Exception:
                continue
    except Exception:
        pass
    return texts


def wait_for_generation_complete(
    page: Page,
    settings: Settings,
    *,
    baseline_message_count: int | None = None,
    require_marker: str | None = "CONNECTION_REQUEST",
    pre_submit_latest_text: str = "",
    metrics: object | None = None,
) -> str:
    """
    Wait until ChatGPT finishes generating a NEW assistant message.

    When require_marker is set, the latest message must contain that text
    (e.g. CONNECTION_REQUEST) to avoid correlating with stale responses.
    """
    from datetime import datetime, timezone

    start = time.time()
    timeout = settings.chatgpt_response_timeout_sec
    stability_checks = settings.chatgpt_stability_checks
    stability_interval = settings.chatgpt_stability_interval_sec
    min_index = baseline_message_count or 0

    def _utc() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    logger.info(
        "Waiting for ChatGPT response (baseline=%d, marker=%r)...",
        min_index,
        require_marker,
    )

    generation_started = False
    generation_start_ts: str | None = None
    while time.time() - start < min(timeout, 45):
        if _is_generating(page):
            generation_started = True
            generation_start_ts = _utc()
            logger.info("CGPT_DIAG generation_start detected (stop-button visible) at %s", generation_start_ts)
            break
        if _count_assistant_messages(page) > min_index:
            generation_started = True
            generation_start_ts = _utc()
            logger.info(
                "CGPT_DIAG generation_start detected (new assistant message count=%d) at %s",
                _count_assistant_messages(page),
                generation_start_ts,
            )
            break
        page.wait_for_timeout(500)

    if not generation_started:
        logger.warning("CGPT_DIAG generation_start NOT detected within 45s; continuing to monitor")

    if metrics is not None:
        metrics.generation_started = generation_started
        metrics.generation_start_ts = generation_start_ts

    while time.time() - start < timeout:
        if not _is_generating(page):
            break
        page.wait_for_timeout(500)

    generation_complete_ts = _utc() if generation_started else None
    generation_done = False
    if generation_started:
        generation_done = True
        logger.info(
            "CGPT_DIAG generation_complete (stop-button gone) at %s (%.1fs after wait start)",
            generation_complete_ts,
            time.time() - start,
        )
        if metrics is not None:
            metrics.generation_completed = True
            metrics.generation_complete_ts = generation_complete_ts

    previous_text = ""
    stable_count = 0
    last_marker_miss_log = 0.0
    plateau_logged = False

    while time.time() - start < timeout:
        if _is_generating(page):
            stable_count = 0
            previous_text = ""
            generation_done = False
            page.wait_for_timeout(500)
            continue

        current_count = _count_assistant_messages(page)
        read_index = _effective_min_index(
            page, min_index, generation_done=generation_done
        )
        if current_count <= min_index and not generation_done:
            page.wait_for_timeout(int(stability_interval * 1000))
            continue

        if current_count <= min_index and generation_done and not plateau_logged:
            logger.warning(
                "CGPT_DIAG assistant count plateau at %d (baseline=%d) — "
                "correlating via latest visible message index %d",
                current_count,
                min_index,
                read_index,
            )
            plateau_logged = True

        current_text = _get_latest_response_text(page, min_index=read_index)

        if not current_text:
            page.wait_for_timeout(int(stability_interval * 1000))
            continue

        if pre_submit_latest_text and current_text == pre_submit_latest_text:
            page.wait_for_timeout(int(stability_interval * 1000))
            continue

        if require_marker and require_marker not in current_text:
            if time.time() - last_marker_miss_log > 30:
                logger.warning(
                    "CGPT_DIAG marker %r missing in latest message (%d chars, count=%d) — still waiting",
                    require_marker,
                    len(current_text),
                    current_count,
                )
                last_marker_miss_log = time.time()
            page.wait_for_timeout(int(stability_interval * 1000))
            continue

        if current_text == previous_text:
            stable_count += 1
            if stable_count >= stability_checks:
                elapsed = time.time() - start
                logger.info("ChatGPT response stable (%d chars)", len(current_text))
                logger.info(
                    "CGPT_DIAG response_stable at %.1fs — marker=%s, assistant_count=%d",
                    elapsed,
                    require_marker in current_text if require_marker else True,
                    current_count,
                )
                if metrics is not None:
                    metrics.time_to_response_sec = round(elapsed, 2)
                    metrics.response_chars = len(current_text)
                    metrics.has_connection_request_marker = (
                        not require_marker or require_marker in current_text
                    )
                return current_text
        else:
            stable_count = 0
            previous_text = current_text

        page.wait_for_timeout(int(stability_interval * 1000))

    still_generating = _is_generating(page)
    read_index = _effective_min_index(
        page, min_index, generation_done=generation_done
    )
    partial = _get_latest_response_text(page, min_index=read_index)
    if not partial:
        partial = _get_latest_response_text(page, min_index=0)

    if metrics is not None:
        metrics.still_generating_at_timeout = still_generating
        metrics.response_chars = len(partial) if partial else 0
        metrics.has_connection_request_marker = bool(
            partial and require_marker and require_marker in partial
        )

    logger.error(
        "CGPT_DIAG timeout after %.1fs — generating=%s, assistant_count=%d, "
        "partial_chars=%d, marker_present=%s",
        time.time() - start,
        still_generating,
        _count_assistant_messages(page),
        len(partial) if partial else 0,
        metrics.has_connection_request_marker if metrics else None,
    )

    if partial and (not require_marker or require_marker in partial):
        logger.warning("ChatGPT timeout with partial response (%d chars)", len(partial))
        return partial

    raise ChatGPTTimeoutError(
        f"ChatGPT did not complete within {timeout} seconds"
    )
