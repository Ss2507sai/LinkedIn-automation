"""Sales Navigator search results scraping and pagination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from src.errors import ScrapingError
from src.logger import get_logger
from src.utils import clean_text, dismiss_linkedin_popups, human_delay, wait_for_network_idle

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

    from config.settings import Settings

logger = get_logger()


@dataclass
class ProspectCard:
    """A prospect visible on the Sales Navigator results page."""

    name: str
    profile_url: str
    title: str = ""
    company: str = ""
    location: str = ""
    public_profile_url: str = ""


class SalesNavigatorScraper:
    """Reads prospect cards and handles pagination on Sales Navigator."""

    SEARCH_URL_PATTERNS = ("/sales/search",)

    CARD_SELECTORS = [
        "ol.artdeco-list li.artdeco-list__item",
        "div[data-x--search-results-container] li",
        "div.search-results__result-list li",
        "ul.artdeco-list li.artdeco-list__item",
        "div.search-results-container li.artdeco-list__item",
    ]

    def __init__(self, page: Page, settings: Settings) -> None:
        self.page = page
        self.settings = settings

    def is_search_results_page(self) -> bool:
        url = self.page.url.lower()
        return any(p in url for p in self.SEARCH_URL_PATTERNS)

    def ensure_search_results_page(self) -> None:
        """Require saved search results URL (prospect cards list)."""
        if not self.is_search_results_page():
            raise ScrapingError(
                f"Not on Sales Navigator search results page. "
                f"Open your saved search. Current URL: {self.page.url[:120]}"
            )

    def get_first_visible_prospect(self) -> ProspectCard:
        """Return the first prospect card on the current search results page."""
        prospects = self.get_visible_prospects()
        if not prospects:
            raise ScrapingError("No prospect cards on search results page")
        logger.info("Selected first prospect: %s (%s)", prospects[0].name, prospects[0].company)
        return prospects[0]

    def wait_for_results(self) -> None:
        """Wait until search results are visible."""
        self.ensure_search_results_page()
        dismiss_linkedin_popups(self.page)
        wait_for_network_idle(self.page, timeout_ms=15_000)

        for selector in self.CARD_SELECTORS:
            try:
                self.page.locator(selector).first.wait_for(state="visible", timeout=15_000)
                return
            except Exception:
                continue

        raise ScrapingError("Sales Navigator results not found on page")

    def get_visible_prospects(self) -> list[ProspectCard]:
        """Collect all visible prospect cards on the current page."""
        self.wait_for_results()
        cards: list[ProspectCard] = []
        seen_urls: set[str] = set()

        list_items = self._find_result_items()
        count = list_items.count()

        if count == 0:
            raise ScrapingError("No prospect cards found on Sales Navigator page")

        logger.info("Found %d prospect cards on current page", count)

        for i in range(count):
            item = list_items.nth(i)
            try:
                card = self._parse_card(item)
                if card and card.profile_url and card.profile_url not in seen_urls:
                    seen_urls.add(card.profile_url)
                    cards.append(card)
            except Exception as exc:
                logger.warning("Failed to parse card %d: %s", i, exc)

        return cards

    def open_profile_in_new_tab(self, prospect: ProspectCard) -> Page:
        """Open a prospect profile in a new browser tab."""
        context = self.page.context
        profile_page = context.new_page()

        target_url = prospect.public_profile_url or prospect.profile_url
        logger.info("Profile opened: %s (%s)", prospect.name, target_url)
        profile_page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=self.settings.page_load_timeout_ms,
        )
        human_delay(self.settings)
        return profile_page

    def get_current_page_number(self) -> int:
        """Best-effort current pagination page number."""
        selectors = [
            "li.artdeco-pagination__indicator--number.active button",
            "li.artdeco-pagination__indicator--number.active",
            'button[aria-current="true"]',
        ]
        for selector in selectors:
            try:
                el = self.page.locator(selector).first
                if el.count():
                    text = clean_text(el.inner_text(timeout=1000))
                    if text.isdigit():
                        return int(text)
            except Exception:
                continue
        return 1

    def click_next_page(self) -> bool:
        """Click the Next pagination button. Returns False if unavailable."""
        dismiss_linkedin_popups(self.page)
        self.page.bring_to_front()

        next_selectors = [
            'button[aria-label="Next"]',
            'button.artdeco-pagination__button--next',
            'button:has-text("Next")',
            'li.artdeco-pagination__indicator--number + li button',
        ]

        for selector in next_selectors:
            try:
                button = self.page.locator(selector).first
                if not button.is_visible(timeout=3000):
                    continue

                disabled = button.get_attribute("disabled")
                aria_disabled = button.get_attribute("aria-disabled")
                if disabled is not None or aria_disabled == "true":
                    logger.info("Next button is disabled — no more pages")
                    return False

                current_url = self.page.url
                button.click(timeout=5000)
                logger.info("Pagination: clicked Next")

                self.page.wait_for_timeout(1000)
                wait_for_network_idle(self.page)

                if self.page.url != current_url:
                    return True

                # URL may not change; wait for list refresh
                self.wait_for_results()
                return True

            except Exception:
                continue

        logger.info("Next button not found — pagination complete")
        return False

    def _find_result_items(self) -> Locator:
        for selector in self.CARD_SELECTORS:
            items = self.page.locator(selector)
            if items.count() > 0:
                return items
        return self.page.locator("li.artdeco-list__item")

    def _parse_card(self, item: Locator) -> ProspectCard | None:
        link_selectors = [
            'a[href*="/sales/lead/"]',
            'a[href*="/in/"]',
            'a[data-control-name="view_lead_panel_via_search_lead"]',
            'a[data-anonymize="person-name"]',
        ]

        profile_url = ""
        name = ""

        name = self._extract_card_field(
            item,
            [
                '[data-anonymize="person-name"]',
                "span[data-anonymize='person-name']",
                ".artdeco-entity-lockup__title",
            ],
        )

        for selector in link_selectors:
            link = item.locator(selector).first
            if link.count() == 0:
                continue
            try:
                href = link.get_attribute("href") or ""
                if not href:
                    continue
                profile_url = self._normalize_profile_url(href)
                if not name:
                    name = clean_text(link.inner_text(timeout=2000))
                if profile_url:
                    break
            except Exception:
                continue

        if not profile_url:
            return None

        title = self._extract_card_field(
            item,
            [
                '[data-anonymize="title"]',
                ".artdeco-entity-lockup__subtitle",
                "span[data-anonymize='job-title']",
            ],
        )
        company = self._extract_card_field(
            item,
            [
                '[data-anonymize="company-name"]',
                "a[data-anonymize='company-name']",
                ".artdeco-entity-lockup__caption",
            ],
        )
        location = self._extract_card_field(
            item,
            [
                '[data-anonymize="location"]',
                ".artdeco-entity-lockup__metadata",
            ],
        )

        public_url = ""
        try:
            in_link = item.locator('a[href*="/in/"]').first
            if in_link.count():
                href = in_link.get_attribute("href") or ""
                if "/in/" in href and "/company/" not in href:
                    public_url = urljoin("https://www.linkedin.com", href.split("?")[0])
        except Exception:
            public_url = ""

        if not name:
            name = "Unknown"

        return ProspectCard(
            name=name,
            profile_url=profile_url,
            title=title,
            company=company,
            location=location,
            public_profile_url=public_url,
        )

    def _extract_card_field(self, item: Locator, selectors: list[str]) -> str:
        for selector in selectors:
            try:
                locator = item.locator(selector).first
                if locator.count() and locator.is_visible(timeout=1000):
                    return clean_text(locator.inner_text(timeout=2000))
            except Exception:
                continue
        return ""

    def _normalize_profile_url(self, href: str) -> str:
        url = urljoin("https://www.linkedin.com", href.split("?")[0])

        # Convert Sales Navigator lead URLs to public profile when possible
        if "/sales/lead/" in url:
            return url

        if "/in/" in url:
            return url.split("?")[0]

        return url
