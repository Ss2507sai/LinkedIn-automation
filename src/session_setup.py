"""Startup verification and single-session tab setup."""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from chatgpt.client import ChatGPTClient
from config.settings import Settings
from src.browser import BrowserManager
from src.errors import BrowserConnectionError, ChatGPTError, TabNotFoundError
from src.logger import get_logger
from src.tab_registry import TabRegistry
if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = get_logger()


def verify_cdp(settings: Settings) -> None:
    """Verify Chrome CDP endpoint responds."""
    url = settings.cdp_url.rstrip("/") + "/json/version"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status != 200:
                raise BrowserConnectionError(f"CDP returned status {resp.status}")
        logger.info("CDP verified at %s", settings.cdp_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BrowserConnectionError(
            f"Chrome CDP not reachable at {settings.cdp_url}. "
            f"Run ./scripts/launch_chrome.sh first. ({exc})"
        ) from exc


def _is_sales_nav_logged_in(page: Page) -> bool:
    url = page.url.lower()
    if "linkedin.com/sales" not in url:
        return False
    if "/login" in url or "checkpoint" in url:
        return False
    try:
        if page.locator('input[name="session_key"]').is_visible(timeout=1000):
            return False
    except Exception:
        pass
    return True


def _is_chatgpt_logged_in(page: Page) -> bool:
    url = page.url.lower()
    if "chatgpt.com" not in url:
        return False
    if "/auth/" in url or "login" in url:
        return False
    try:
        if page.locator("#prompt-textarea, div#prompt-textarea").first.is_visible(timeout=3000):
            return True
    except Exception:
        pass
    return "chatgpt.com" in url


def _pick_sales_nav_tab(browser: BrowserManager) -> Page:
    """Prefer SN search/results tab over other sales URLs."""
    candidates = [
        p
        for p in browser.context.pages
        if "linkedin.com/sales" in p.url.lower() and _is_sales_nav_logged_in(p)
    ]
    if not candidates:
        raise TabNotFoundError(
            "No logged-in Sales Navigator tab found. "
            "Open your saved search in Sales Navigator."
        )

    for page in candidates:
        if "/sales/search" in page.url.lower():
            logger.info("Selected SN saved search tab: %s", page.url[:100])
            return page

    raise TabNotFoundError(
        "No Sales Navigator saved search tab found. "
        "Open your saved search results page (URL must contain /sales/search). "
        f"Open tabs: {[p.url[:80] for p in candidates]}"
    )


def _ensure_single_chatgpt_tab(browser: BrowserManager) -> Page:
    """Keep one ChatGPT tab; close extras."""
    chatgpt_pages = [p for p in browser.context.pages if "chatgpt.com" in p.url.lower()]
    if not chatgpt_pages:
        raise TabNotFoundError("No ChatGPT tab open. Open and log into chatgpt.com.")

    primary = chatgpt_pages[0]
    for extra in chatgpt_pages[1:]:
        try:
            logger.info("Closing extra ChatGPT tab: %s", extra.url[:80])
            extra.close()
        except Exception as exc:
            logger.warning("Could not close extra ChatGPT tab: %s", exc)

    if not _is_chatgpt_logged_in(primary):
        raise TabNotFoundError("ChatGPT tab is not logged in")

    return primary


def setup_session(
    browser: BrowserManager,
    registry: TabRegistry,
    settings: Settings,
) -> ChatGPTClient:
    """
    Verify environment and prepare pinned tabs + ChatGPT conversation.

    Returns configured ChatGPTClient bound to the pinned tab.
    """
    verify_cdp(settings)
    browser.connect()
    registry.log_all_tabs(browser.context, "after_connect")

    sn_page = _pick_sales_nav_tab(browser)
    registry.pin_sales_nav(sn_page)
    browser.bring_to_front(sn_page)

    if not _is_sales_nav_logged_in(sn_page):
        raise TabNotFoundError("LinkedIn Sales Navigator is not logged in")

    logger.info("Sales Navigator login verified")

    chatgpt_page = _ensure_single_chatgpt_tab(browser)
    registry.pin_chatgpt(chatgpt_page)
    browser.bring_to_front(chatgpt_page)

    if not _is_chatgpt_logged_in(chatgpt_page):
        raise TabNotFoundError("ChatGPT is not logged in")

    logger.info("ChatGPT login verified")

    client = ChatGPTClient(chatgpt_page, settings)
    client.setup_conversation()
    registry.save()
    return client
