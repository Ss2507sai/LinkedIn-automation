"""LinkedIn Sales Navigator connection invitation automation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scrapers.sales_navigator import ProspectCard
from src.errors import ScrapingError
from src.logger import get_logger
from src.utils import clean_text, dismiss_linkedin_popups, human_delay

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

    from config.settings import Settings

logger = get_logger()


class LinkedInConnectSender:
    """Connect workflow from SN search results: three-dot menu → Connect → Send Invitation modal."""

    # Three-dot overflow menu on prospect card (SN search results).
    MENU_SELECTORS = [
        'button[aria-label*="See more actions"]',
        'button[aria-label*="More actions"]',
        'button[aria-label*="Open actions"]',
        "button.artdeco-dropdown__trigger",
    ]

    CONNECT_SELECTORS = [
        'div[aria-label="Connect"]',
        '[data-control-name="connect"]',
        'span.artdeco-dropdown__item-text:has-text("Connect")',
        'div.artdeco-dropdown__item:has-text("Connect")',
        'button:has-text("Connect")',
        'span:has-text("Connect")',
    ]

    MODAL_HEADING = "Send invitation"

    PERSONAL_MESSAGE_SELECTORS = [
        "#connect-cta-form__invitation",
        "textarea#connect-cta-form__invitation",
        'textarea[placeholder*="personal message"]',
        'textarea[placeholder*="Personal message"]',
        'textarea[name="message"]',
    ]

    ADD_NOTE_SELECTORS = [
        'button:has-text("Add a note")',
        'button[aria-label="Add a note"]',
    ]

    SEND_SELECTORS = [
        'button[aria-label="Send invitation"]',
        'button[aria-label="Send now"]',
        'button:has-text("Send invitation")',
    ]

    def __init__(self, page: Page, settings: Settings) -> None:
        self.page = page
        self.settings = settings

    def open_connect_dialog(self, prospect: ProspectCard, screenshot_cb=None) -> None:
        """
        SN search results flow:
        1. Three-dot menu on prospect card
        2. Click Connect
        3. Wait for Send Invitation modal
        4. Ensure personal message textarea is visible
        """
        dismiss_linkedin_popups(self.page)
        self.page.bring_to_front()

        card = self._find_prospect_card(prospect)
        if card is None:
            raise ScrapingError(f"Could not find prospect card for {prospect.name}")

        if screenshot_cb:
            screenshot_cb("01_prospect_card")

        self._open_three_dot_menu(card, prospect.name)
        if screenshot_cb:
            screenshot_cb("02_action_menu")

        self._click_connect(card, prospect.name)
        self.wait_for_send_invitation_modal()
        if screenshot_cb:
            screenshot_cb("03_invitation_popup")

        self._wait_for_personal_message_textarea()

        if screenshot_cb:
            screenshot_cb("04_note_field_ready")

        logger.info("Send Invitation modal ready for %s", prospect.name)

    def wait_for_send_invitation_modal(self) -> None:
        """Wait for the Send Invitation modal to appear."""
        try:
            heading = self.page.get_by_role("heading", name=self.MODAL_HEADING).first
            heading.wait_for(state="visible", timeout=self.settings.page_load_timeout_ms)
            logger.info("Send Invitation modal detected")
            return
        except Exception:
            pass

        modal = self.page.locator(".artdeco-modal").filter(has_text=self.MODAL_HEADING).last
        try:
            modal.wait_for(state="visible", timeout=self.settings.page_load_timeout_ms)
            logger.info("Send Invitation modal detected (artdeco-modal)")
            return
        except Exception as exc:
            raise ScrapingError("Send Invitation modal did not appear") from exc

    def detect_personal_message_textarea(self) -> bool:
        """Return True if the personal message textarea is visible in the modal."""
        try:
            self._wait_for_personal_message_textarea()
            return True
        except ScrapingError:
            return False

    def _wait_for_personal_message_textarea(self) -> None:
        """Wait for #connect-cta-form__invitation in the Send Invitation modal."""
        self._click_add_note_if_needed()

        for selector in self.PERSONAL_MESSAGE_SELECTORS:
            try:
                field = self.page.locator(selector).first
                field.wait_for(state="visible", timeout=10_000)
                logger.info("Personal message textarea ready via %s", selector)
                return
            except Exception:
                continue

        raise ScrapingError("Personal message textarea not found in Send Invitation modal")

    def paste_connection_note(self, note: str) -> None:
        """Paste connection request into the personal message textarea."""
        field = self._get_note_field()
        text = note[:300]
        tag = field.evaluate("el => el.tagName.toLowerCase()")

        field.focus(timeout=5000)
        if tag in ("textarea", "input"):
            field.fill(text)
        else:
            field.evaluate(
                """(el, value) => {
                    el.focus();
                    el.textContent = value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }""",
                text,
            )

        self.page.evaluate(
            """(value) => {
                const modals = [...document.querySelectorAll('.artdeco-modal, [role="dialog"]')]
                    .filter(m => m.textContent && m.textContent.includes('Send invitation'));
                const modal = modals[modals.length - 1];
                if (!modal) return false;
                const el = modal.querySelector(
                    '#connect-cta-form__invitation, textarea, [contenteditable="true"], input[type="text"]'
                );
                if (!el) return false;
                if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                    el.value = value;
                } else {
                    el.textContent = value;
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }""",
            text,
        )
        human_delay(self.settings)
        logger.info("Connection note pasted (%d chars)", len(text))

    def verify_note_pasted(self, expected: str, *, min_chars: int = 15) -> None:
        """Confirm pasted text matches generated connection request."""
        preview = self.get_note_field_preview()
        expected_clean = clean_text(expected)
        preview_clean = clean_text(preview)

        if len(preview_clean) < min_chars:
            raise ScrapingError(
                f"Note field empty or too short ({len(preview_clean)} chars). "
                f"Preview: {preview_clean[:80]!r}"
            )

        if expected_clean[:30] not in preview_clean:
            raise ScrapingError(
                f"Note verification failed. Expected start: {expected_clean[:40]!r}, "
                f"got: {preview_clean[:40]!r}"
            )

        logger.info("Note verified — pasted text matches generated request (%d chars)", len(preview_clean))

    def paste_and_verify_note(self, note: str) -> None:
        self.paste_connection_note(note)
        self.verify_note_pasted(note)

    def send_invitation(self) -> None:
        """Click Send Invitation (skipped in dry-run)."""
        for selector in self.SEND_SELECTORS:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=2000) and btn.is_enabled():
                    btn.click(timeout=3000)
                    self.page.wait_for_timeout(1500)
                    logger.info("Send invitation clicked")
                    return
            except Exception:
                continue
        raise ScrapingError("Could not click Send invitation")

    def close_dialog(self) -> None:
        for selector in [
            'button[aria-label="Dismiss"]',
            'button[aria-label="Close"]',
            'button.artdeco-modal__dismiss',
            'button:has-text("Cancel")',
        ]:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=2000)
                    return
            except Exception:
                continue

    def _open_three_dot_menu(self, card: Locator, prospect_name: str) -> None:
        for selector in self.MENU_SELECTORS:
            try:
                menu = card.locator(selector).first
                if menu.count() and menu.is_visible(timeout=2000):
                    menu.click(timeout=3000)
                    self.page.wait_for_timeout(500)
                    logger.info("Three-dot menu opened for %s", prospect_name)
                    return
            except Exception:
                continue
        raise ScrapingError(f"Could not open three-dot menu for {prospect_name}")

    def _click_connect(self, card: Locator, prospect_name: str) -> None:
        """Click Connect in the open three-dot dropdown."""
        self.page.wait_for_timeout(600)

        # SN search results: Connect appears as visible page text after menu opens.
        try:
            connect_items = self.page.get_by_text("Connect", exact=True)
            for i in range(connect_items.count()):
                item = connect_items.nth(i)
                if item.is_visible(timeout=1000):
                    item.click(timeout=3000)
                    logger.info("Connect clicked for %s via visible text", prospect_name)
                    return
        except Exception:
            pass

        for scope in (card, self.page):
            for selector in self.CONNECT_SELECTORS:
                try:
                    item = scope.locator(selector).first
                    if item.is_visible(timeout=1500):
                        item.click(timeout=3000)
                        logger.info("Connect clicked for %s via %s", prospect_name, selector)
                        return
                except Exception:
                    continue

        raise ScrapingError(f"Could not click Connect for {prospect_name}")

    def _click_add_note_if_needed(self) -> None:
        for selector in self.ADD_NOTE_SELECTORS:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    btn.click(timeout=2000)
                    self.page.wait_for_timeout(500)
                    logger.info("Add a note clicked")
                    return
            except Exception:
                continue

    def _find_prospect_card(self, prospect: ProspectCard) -> Locator | None:
        lead_id = (
            prospect.profile_url.split("/sales/lead/")[-1].split(",")[0]
            if "/sales/lead/" in prospect.profile_url
            else ""
        )
        selectors = [
            f'a[href*="{lead_id}"]' if lead_id else "",
            f'a[href*="{prospect.profile_url.split("?")[0].split("/")[-1]}"]',
        ]
        for selector in selectors:
            if not selector:
                continue
            try:
                link = self.page.locator(selector).first
                if link.count():
                    return link.locator(
                        "xpath=ancestor::li[contains(@class, 'artdeco-list__item')][1]"
                    )
            except Exception:
                continue

        if prospect.name and prospect.name != "Unknown":
            try:
                name_el = self.page.locator(
                    f'[data-anonymize="person-name"]:has-text("{prospect.name}")'
                ).first
                if name_el.count():
                    return name_el.locator(
                        "xpath=ancestor::li[contains(@class, 'artdeco-list__item')][1]"
                    )
            except Exception:
                pass

        return None

    def _invite_modal(self):
        try:
            heading = self.page.get_by_role("heading", name=self.MODAL_HEADING).first
            if heading.is_visible(timeout=2000):
                return heading.locator(
                    "xpath=ancestor::div[contains(@class, 'artdeco-modal') or @role='dialog'][1]"
                )
        except Exception:
            pass
        return self.page.locator(".artdeco-modal").filter(has_text=self.MODAL_HEADING).last

    def _get_note_field(self):
        for selector in self.PERSONAL_MESSAGE_SELECTORS:
            try:
                field = self.page.locator(selector).first
                if field.is_visible(timeout=3000):
                    return field
            except Exception:
                continue

        modal = self._invite_modal()
        for locator in (
            modal.locator("textarea"),
            modal.get_by_role("textbox"),
        ):
            try:
                field = locator.first
                if field.is_visible(timeout=2000):
                    return field
            except Exception:
                continue

        raise ScrapingError("Personal message textarea not found")

    def get_note_field_preview(self) -> str:
        try:
            value = self.page.evaluate(
                """() => {
                const modals = [...document.querySelectorAll('.artdeco-modal, [role="dialog"]')]
                    .filter(m => m.textContent && m.textContent.includes('Send invitation'));
                const modal = modals[modals.length - 1];
                if (!modal) return '';
                const el = modal.querySelector(
                    '#connect-cta-form__invitation, textarea, [contenteditable="true"], input[type="text"]'
                );
                if (!el) return '';
                return el.value || el.textContent || '';
            }"""
            )
            return clean_text(value)
        except Exception:
            try:
                return clean_text(self._get_note_field().input_value(timeout=2000))
            except Exception:
                return ""
