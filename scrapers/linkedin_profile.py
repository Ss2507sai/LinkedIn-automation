"""LinkedIn profile data extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from src.control import is_valid_profile_name
from src.errors import ScrapingError
from scrapers.profile_validation import validate_profile_data
from src.logger import get_logger
from src.utils import clean_text, dismiss_linkedin_popups, wait_for_network_idle

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = get_logger()


@dataclass
class ProfileData:
    """Structured LinkedIn profile information."""

    full_name: str = ""
    current_job_title: str = ""
    company_name: str = ""
    headline: str = ""
    about: str = ""
    experience: str = ""
    location: str = ""
    profile_url: str = ""

    def to_structured_text(self) -> str:
        sections = [
            ("Full Name", self.full_name),
            ("Current Job Title", self.current_job_title),
            ("Company Name", self.company_name),
            ("Headline", self.headline),
            ("Location", self.location),
            ("LinkedIn Profile URL", self.profile_url),
            ("About Section", self.about),
            ("Experience Section", self.experience),
        ]
        lines = []
        for label, value in sections:
            lines.append(f"{label}:\n{value or 'N/A'}")
        return "\n\n".join(lines)

    def quality_score(self) -> int:
        score = 0
        if is_valid_profile_name(self.full_name):
            score += 2
        if self.headline:
            score += 1
        if self.about:
            score += 2
        if self.experience:
            score += 2
        if self.company_name:
            score += 1
        if self.location:
            score += 1
        if "/in/" in self.profile_url:
            score += 1
        return score


class LinkedInProfileScraper:
    """Extracts profile information from a LinkedIn profile page."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def extract(
        self,
        fallback_name: str = "",
        fallback_title: str = "",
        fallback_company: str = "",
        fallback_location: str = "",
        max_attempts: int = 3,
    ) -> ProfileData:
        """Extract profile fields, always preferring the full /in/ profile page."""
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                dismiss_linkedin_popups(self.page)
                wait_for_network_idle(self.page)

                sn_name = self._extract_sales_nav_name()
                on_sales_lead = "/sales/lead/" in self.page.url
                self._navigate_to_full_profile()
                on_sales_lead = "/sales/lead/" in self.page.url

                dismiss_linkedin_popups(self.page)
                wait_for_network_idle(self.page)

                profile = ProfileData(profile_url=self._canonical_profile_url())

                if on_sales_lead:
                    self._fill_from_sales_lead_page(profile, sn_name)
                else:
                    profile.full_name = self._extract_name()
                    profile.headline = self._extract_headline()
                    profile.location = self._extract_location()
                    profile.about = self._extract_section("about")
                    profile.experience = self._extract_section("experience")
                    profile.current_job_title, profile.company_name = self._extract_current_role()

                if not is_valid_profile_name(profile.full_name):
                    if is_valid_profile_name(sn_name):
                        profile.full_name = sn_name
                    elif is_valid_profile_name(fallback_name):
                        profile.full_name = fallback_name

                if not profile.current_job_title and fallback_title:
                    profile.current_job_title = fallback_title
                if not profile.company_name and fallback_company:
                    profile.company_name = fallback_company
                if not profile.location and fallback_location:
                    profile.location = fallback_location

                if not is_valid_profile_name(profile.full_name):
                    raise ScrapingError(
                        f"Invalid profile name extracted: {profile.full_name!r}"
                    )

                validation = validate_profile_data(profile)
                if not validation.valid:
                    raise ScrapingError(f"Profile validation failed: {validation.message()}")

                if profile.quality_score() < 3 and attempt < max_attempts:
                    logger.warning(
                        "Low quality extraction (score=%d), refreshing (attempt %d)",
                        profile.quality_score(),
                        attempt,
                    )
                    self.page.reload(wait_until="domcontentloaded")
                    self.page.wait_for_timeout(2000)
                    continue

                logger.info(
                    "Data extracted for %s at %s (quality=%d)",
                    profile.full_name,
                    profile.company_name or "unknown company",
                    profile.quality_score(),
                )
                return profile

            except Exception as exc:
                last_error = exc
                logger.warning("Extraction attempt %d failed: %s", attempt, exc)
                if attempt < max_attempts:
                    try:
                        self.page.reload(wait_until="domcontentloaded")
                        self.page.wait_for_timeout(2000)
                    except Exception:
                        pass

        raise ScrapingError(f"Profile extraction failed after {max_attempts} attempts: {last_error}")

    def _navigate_to_full_profile(self) -> None:
        """Navigate from Sales Navigator lead page to full LinkedIn /in/ profile."""
        if "/in/" in self.page.url and "/sales/" not in self.page.url:
            return

        public_url = self._find_public_profile_url()
        if public_url:
            logger.info("Navigating to full profile: %s", public_url)
            self.page.goto(public_url, wait_until="domcontentloaded", timeout=60_000)
            wait_for_network_idle(self.page)
            if "/in/" in self.page.url:
                return

        view_selectors = [
            'a[data-control-name="view_profile_via_website"]',
            'a:has-text("View LinkedIn profile")',
            'button:has-text("View LinkedIn profile")',
            'a[href*="/in/"][data-control-name]',
        ]
        for selector in view_selectors:
            try:
                link = self.page.locator(selector).first
                if link.count() and link.is_visible(timeout=2000):
                    href = link.get_attribute("href") or ""
                    if href and "/in/" in href:
                        url = urljoin("https://www.linkedin.com", href.split("?")[0])
                        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    else:
                        with self.page.expect_navigation(timeout=30_000):
                            link.click(timeout=5000)
                    wait_for_network_idle(self.page)
                    if "/in/" in self.page.url:
                        return
            except Exception:
                continue

        # Last resort: click any visible /in/ link in main content
        try:
            links = self.page.locator('main a[href*="/in/"], section a[href*="/in/"]')
            for i in range(min(links.count(), 5)):
                href = links.nth(i).get_attribute("href") or ""
                if "/in/" in href and "/company/" not in href:
                    url = urljoin("https://www.linkedin.com", href.split("?")[0])
                    self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    wait_for_network_idle(self.page)
                    if "/in/" in self.page.url:
                        return
        except Exception:
            pass

        if "/sales/lead/" in self.page.url:
            logger.warning("Staying on Sales Navigator lead page — using lead-page extraction")

    def _find_public_profile_url(self) -> str:
        patterns = [
            'a[data-control-name="view_profile_via_website"]',
            'a[href*="/in/"]',
        ]
        for selector in patterns:
            try:
                loc = self.page.locator(selector)
                for i in range(min(loc.count(), 10)):
                    href = loc.nth(i).get_attribute("href") or ""
                    if not href or "/in/" not in href:
                        continue
                    if any(x in href for x in ("/company/", "/school/", "/groups/")):
                        continue
                    match = re.search(r"(https?://[^\"']+/in/[^/?#\"']+)", href)
                    if match:
                        return match.group(1).split("?")[0]
                    return urljoin("https://www.linkedin.com", href.split("?")[0])
            except Exception:
                continue
        return ""

    def _canonical_profile_url(self) -> str:
        url = self.page.url.split("?")[0]
        if "/in/" in url:
            match = re.search(r"(https?://[^/]+/in/[^/?#]+)", url)
            if match:
                return match.group(1)
        return url

    def _fill_from_sales_lead_page(self, profile: ProfileData, sn_name: str) -> None:
        """Extract fields available on a Sales Navigator lead page."""
        profile.full_name = sn_name or self._first_visible_text('[data-anonymize="person-name"]')
        profile.headline = self._first_visible_text('[data-anonymize="headline"]')
        profile.current_job_title = self._first_visible_text('[data-anonymize="title"]')
        profile.company_name = self._first_visible_text('[data-anonymize="company-name"]')
        profile.location = self._first_visible_text('[data-anonymize="location"]')

        if not profile.headline:
            profile.headline = self._first_visible_text(
                ".profile-topcard__summary-position-title, .topcard__headline"
            )

        about_selectors = [
            "section#about-section",
            "section[data-section='about']",
            "#about-section",
            "div[data-sn-view-name='lead-about-section']",
        ]
        for selector in about_selectors:
            try:
                loc = self.page.locator(selector).first
                if loc.count():
                    profile.about = clean_text(loc.inner_text(timeout=3000))
                    if profile.about:
                        break
            except Exception:
                continue

        exp_selectors = [
            "section#experience-section",
            "section[data-section='experience']",
            "div[data-sn-view-name='lead-experience-section']",
        ]
        for selector in exp_selectors:
            try:
                loc = self.page.locator(selector).first
                if loc.count():
                    profile.experience = clean_text(loc.inner_text(timeout=3000))
                    if profile.experience:
                        break
            except Exception:
                continue

        public = self._find_public_profile_url()
        if public:
            profile.profile_url = public

    def _extract_sales_nav_name(self) -> str:
        selectors = [
            '[data-anonymize="person-name"]',
            'h1[data-anonymize="person-name"]',
            "span._name_1sdjqx",
        ]
        for selector in selectors:
            text = self._first_visible_text(selector)
            if is_valid_profile_name(text):
                return text
        return ""

    def _extract_name(self) -> str:
        selectors = [
            "h1.text-heading-xlarge",
            "h1.inline.t-24",
            "h1.v-align-middle",
            "h1",
            '[data-anonymize="person-name"]',
        ]
        for selector in selectors:
            text = self._first_visible_text(selector)
            if is_valid_profile_name(text):
                return text
        return ""

    def _extract_headline(self) -> str:
        selectors = [
            "div.text-body-medium.break-words",
            ".pv-text-details__left-panel .text-body-medium",
            '[data-generated-suggestion-target] ~ div.text-body-medium',
            "div.ph5 div.text-body-medium",
        ]
        for selector in selectors:
            text = self._first_visible_text(selector)
            if text and text.lower() != "linkedin":
                return text
        return ""

    def _extract_location(self) -> str:
        selectors = [
            "span.text-body-small.inline.t-black--light.break-words",
            ".pv-text-details__left-panel span.text-body-small",
            '[data-anonymize="location"]',
        ]
        for selector in selectors:
            text = self._first_visible_text(selector)
            if text and not text.lower().startswith("contact"):
                return text
        return ""

    def _extract_current_role(self) -> tuple[str, str]:
        title = ""
        company = ""

        try:
            experience_anchor = self.page.locator("#experience").first
            if experience_anchor.count():
                experience_anchor.scroll_into_view_if_needed(timeout=5000)
                self.page.wait_for_timeout(500)
        except Exception:
            pass

        role_selectors = [
            "section:has(#experience) li:first-child .t-bold span[aria-hidden='true']",
            "#experience ~ div li.pvs-list__paged-list-item:first-child .t-bold span[aria-hidden='true']",
            "#experience ~ div ul > li:first-child span[aria-hidden='true']",
        ]

        for selector in role_selectors:
            elements = self.page.locator(selector)
            count = min(elements.count(), 4)
            texts = []
            for i in range(count):
                text = clean_text(elements.nth(i).inner_text(timeout=2000))
                if text:
                    texts.append(text)
            if texts:
                title = texts[0]
                if len(texts) > 1:
                    company = texts[1]
                break

        if not title and self.page.locator("#experience").count():
            experience_text = self._extract_section("experience")
            lines = [line.strip() for line in experience_text.split("\n") if line.strip()]
            if lines:
                title = lines[0]
            if len(lines) > 1:
                company = lines[1]

        return title, company

    def _extract_section(self, section_id: str) -> str:
        try:
            anchor = self.page.locator(f"#{section_id}").first
            if not anchor.count():
                self._expand_section(section_id)
                anchor = self.page.locator(f"#{section_id}").first
            if not anchor.count():
                return ""

            anchor.scroll_into_view_if_needed(timeout=5000)
            self.page.wait_for_timeout(400)

            section = self.page.locator(
                f"section:has(#{section_id}), div:has(> #{section_id})"
            ).first

            if section.count():
                text = clean_text(section.inner_text(timeout=5000))
                if text:
                    return text

        except Exception as exc:
            logger.debug("Section %s extraction partial failure: %s", section_id, exc)

        return ""

    def _expand_section(self, section_id: str) -> None:
        try:
            btn = self.page.locator(
                f"section:has(#{section_id}) button:has-text('see more'), "
                f"section:has(#{section_id}) button:has-text('Show all')"
            ).first
            if btn.count() and btn.is_visible(timeout=1000):
                btn.click(timeout=2000)
                self.page.wait_for_timeout(500)
        except Exception:
            pass

    def _first_visible_text(self, selector: str) -> str:
        try:
            locator = self.page.locator(selector).first
            if locator.is_visible(timeout=3000):
                return clean_text(locator.inner_text(timeout=3000))
        except Exception:
            pass
        return ""
