"""Browser connection and tab management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config.settings import Settings
from src.errors import BrowserConnectionError, TabNotFoundError
from src.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger()


class BrowserManager:
    """Manages Playwright connection to an existing Chrome session."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._owns_browser = False

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise BrowserConnectionError("Browser is not connected")
        return self._context

    def connect(self) -> BrowserContext:
        """Attach to Chrome via CDP or launch persistent context."""
        self._playwright = sync_playwright().start()

        try:
            logger.info("Connecting to Chrome via CDP at %s", self.settings.cdp_url)
            self._browser = self._playwright.chromium.connect_over_cdp(
                self.settings.cdp_url
            )
            self._owns_browser = False

            if not self._browser.contexts:
                raise BrowserConnectionError(
                    "No browser contexts found. Ensure Chrome is running with "
                    "--remote-debugging-port=9222"
                )

            self._context = self._browser.contexts[0]
            logger.info(
                "Connected to Chrome (%d open pages)",
                len(self._context.pages),
            )
            return self._context

        except Exception as cdp_error:
            logger.warning("CDP connection failed: %s", cdp_error)
            logger.info("Attempting persistent Chrome profile launch...")

            try:
                profile_dir = self.settings.chrome_automation_profile_dir
                profile_dir.mkdir(parents=True, exist_ok=True)

                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel=self.settings.browser_channel,
                    headless=self.settings.headless,
                    no_viewport=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                self._owns_browser = True
                logger.info(
                    "Launched Chrome with automation profile at %s",
                    profile_dir,
                )
                logger.warning(
                    "Automation profile is not your daily Chrome session. "
                    "For logged-in tabs, quit Chrome and relaunch with "
                    "./scripts/launch_chrome.sh"
                )
                return self._context
            except Exception as launch_error:
                raise BrowserConnectionError(
                    "Could not connect to Chrome. Quit Chrome completely, then relaunch with:\n"
                    '/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome '
                    '--remote-debugging-port=9222\n'
                    f"CDP error: {cdp_error}\n"
                    f"Launch error: {launch_error}"
                ) from launch_error

    def find_page_by_url_pattern(self, pattern: str) -> Page:
        """Find an open tab whose URL contains the given pattern."""
        pattern_lower = pattern.lower()
        for page in self.context.pages:
            if pattern_lower in page.url.lower():
                return page

        raise TabNotFoundError(
            f"No open tab matching '{pattern}'. "
            f"Open tabs: {[p.url for p in self.context.pages]}"
        )

    def bring_to_front(self, page: Page) -> None:
        """Focus a browser tab."""
        page.bring_to_front()
        page.wait_for_timeout(300)

    def reconnect(self, max_attempts: int = 3) -> BrowserContext:
        """Reconnect to Chrome after a dropped CDP session."""
        self.close()
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self.connect()
            except Exception as exc:
                last_error = exc
                logger.warning("Reconnect attempt %d failed: %s", attempt, exc)
                import time

                time.sleep(2 * attempt)
        raise BrowserConnectionError(f"Could not reconnect to browser: {last_error}")

    def close(self) -> None:
        """Disconnect from browser without closing user's Chrome."""
        if self._owns_browser and self._context:
            try:
                self._context.close()
            except Exception:
                pass

        if self._browser and not self._owns_browser:
            try:
                self._browser.close()
            except Exception:
                pass

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass

        self._playwright = None
        self._browser = None
        self._context = None
