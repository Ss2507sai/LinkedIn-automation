"""Main automation orchestration loop — single Chrome session, no approval."""

from __future__ import annotations

import signal
import subprocess
from typing import TYPE_CHECKING

from config.settings import Settings
from scrapers.linkedin_connect import LinkedInConnectSender
from scrapers.linkedin_profile import LinkedInProfileScraper, ProfileData
from scrapers.sales_navigator import ProspectCard, SalesNavigatorScraper
from src.browser import BrowserManager
from src.control import (
    AutomationControl,
    OpenProfileRequest,
    ProcessNextPage,
    RetryProspect,
    SaveAndStop,
    SkipProspect,
    StopAutomation,
)
from src.errors import (
    AutomationError,
    BrowserConnectionError,
    ChatGPTError,
    ChatGPTTimeoutError,
    ParseError,
    ScrapingError,
    TabNotFoundError,
)
from src.logger import get_logger
from src.screenshots import capture_error_screenshot
from src.session_setup import setup_session
from src.sn_investigation import diagnose_sn_page
from src.tab_registry import TabRegistry
from src.utils import dismiss_linkedin_popups, human_delay, wait_for_network_idle
from storage.result_storage import ResultStorage
from storage.results import ProspectResult
from storage.status import CONNECTION_SENT, GENERATED

if TYPE_CHECKING:
    from chatgpt.client import ChatGPTClient
    from playwright.sync_api import Page

logger = get_logger()


class AutomationOrchestrator:
    """Single-session workflow: one SN tab, one ChatGPT conversation, auto-send."""

    def __init__(
        self,
        settings: Settings,
        control: AutomationControl | None = None,
    ) -> None:
        self.settings = settings
        self.control = control or AutomationControl(approval_mode=False)
        self.browser = BrowserManager(settings)
        self.registry = TabRegistry(settings)
        self.storage = ResultStorage(settings)
        self.chatgpt_client: ChatGPTClient | None = None
        self._running = True
        self._processed_this_session = 0
        self._profile_index = 0
        self._current_profile_page: Page | None = None
        self._current_profile_url = ""

    def run(self) -> None:
        self.settings.ensure_directories()
        logger.info(
            "Automation started (test_mode=%s, limit=%s, connect_dry_run=%s)",
            self.settings.test_mode,
            self.settings.test_mode_limit if self.settings.test_mode else "none",
            self.settings.connect_dry_run,
        )
        self.control.update(mode="AUTO")

        try:
            self.chatgpt_client = setup_session(self.browser, self.registry, self.settings)
            sales_nav_page = self.registry.sales_nav_page
            self.browser.bring_to_front(sales_nav_page)
            sales_scraper = SalesNavigatorScraper(sales_nav_page, self.settings)
            self._update_page_number(sales_scraper)
            diagnose_sn_page(sales_nav_page, "session_start")

            while self._running:
                try:
                    self.control.check_checkpoint("Reading Sales Navigator results")
                    diagnose_sn_page(sales_nav_page, "loop_iteration_before_scrape")
                    prospects = self._get_prospects_with_recovery(sales_scraper, sales_nav_page)
                    unprocessed = [
                        p
                        for p in prospects
                        if not self.storage.is_connection_sent(p.profile_url)
                    ]

                    if not unprocessed:
                        if self._try_scroll_for_unprocessed(sales_scraper):
                            continue

                        logger.info("All visible prospects processed — attempting pagination")
                        self.control.check_checkpoint("Paginating")
                        if not sales_scraper.click_next_page():
                            logger.info("No more pages. Waiting before recheck...")
                            sales_nav_page.wait_for_timeout(10_000)
                            continue
                        self._update_page_number(sales_scraper)
                        continue

                    for prospect in unprocessed:
                        if not self._running:
                            break
                        if self._should_stop():
                            logger.info("Profile limit reached — stopping")
                            return

                        try:
                            self._process_prospect(
                                prospect=prospect,
                                sales_nav_page=sales_nav_page,
                                sales_scraper=sales_scraper,
                            )
                        except SkipProspect:
                            logger.info("Skipped prospect: %s", prospect.name)
                            continue
                        except ProcessNextPage:
                            if sales_scraper.click_next_page():
                                self._update_page_number(sales_scraper)
                            break
                        except (StopAutomation, SaveAndStop):
                            logger.info("Stop requested")
                            return

                except (BrowserConnectionError, TabNotFoundError) as exc:
                    logger.warning("Browser/tab error: %s — attempting reconnect", exc)
                    self.browser.reconnect(self.settings.browser_reconnect_retries)
                    self.chatgpt_client = setup_session(
                        self.browser, self.registry, self.settings
                    )
                    sales_nav_page = self.registry.sales_nav_page
                    sales_scraper = SalesNavigatorScraper(sales_nav_page, self.settings)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except (StopAutomation, SaveAndStop):
            logger.info("Automation stopped by user")
        except (BrowserConnectionError, TabNotFoundError):
            raise
        except Exception as exc:
            logger.exception("Fatal error: %s", exc)
            raise
        finally:
            self.browser.close()
            logger.info(
                "Automation stopped. Processed %d profiles this session.",
                self._processed_this_session,
            )

    def stop(self) -> None:
        self._running = False
        self.control.button_stop()

    def _get_prospects_with_recovery(
        self,
        sales_scraper: SalesNavigatorScraper,
        sales_nav_page: Page,
    ) -> list[ProspectCard]:
        try:
            return sales_scraper.get_visible_prospects()
        except ScrapingError as exc:
            logger.warning("Results scrape failed: %s — refreshing page", exc)
            diagnose_sn_page(sales_nav_page, "before_refresh_on_scrape_fail")
            sales_nav_page.reload(wait_until="domcontentloaded")
            wait_for_network_idle(sales_nav_page)
            dismiss_linkedin_popups(sales_nav_page)
            diagnose_sn_page(sales_nav_page, "after_refresh_on_scrape_fail")
            return sales_scraper.get_visible_prospects()

    def _try_scroll_for_unprocessed(
        self,
        sales_scraper: SalesNavigatorScraper,
    ) -> bool:
        """
        Scroll the SN results pane until an eligible prospect appears.

        Returns True when scrolling revealed a new unprocessed prospect.
        """
        max_attempts = 30
        for _ in range(max_attempts):
            if self._should_stop():
                return False

            logger.info("No eligible visible prospects - scrolling results pane")
            previous_count = sales_scraper.get_result_card_count()
            did_scroll, at_end = sales_scraper.scroll_results_pane()

            if not did_scroll:
                if at_end:
                    logger.info("End of results reached")
                return False

            human_delay(self.settings)
            sales_scraper.wait_for_new_cards_after_scroll(previous_count)

            prospects = sales_scraper.get_visible_prospects()
            unprocessed = [
                p
                for p in prospects
                if not self.storage.is_connection_sent(p.profile_url)
            ]
            if unprocessed:
                return True

            if at_end or sales_scraper.is_results_pane_at_end():
                logger.info("End of results reached")
                return False

        logger.info("End of results reached")
        return False

    def _update_page_number(self, sales_scraper: SalesNavigatorScraper) -> None:
        self.control.update(page_number=sales_scraper.get_current_page_number())

    def _should_stop(self) -> bool:
        return (
            self.settings.test_mode
            and self._processed_this_session >= self.settings.test_mode_limit
        )

    def _process_prospect(
        self,
        *,
        prospect: ProspectCard,
        sales_nav_page: Page,
        sales_scraper: SalesNavigatorScraper,
    ) -> None:
        if self.storage.is_connection_sent(prospect.profile_url):
            logger.info("Skipping duplicate (connection sent): %s", prospect.name)
            return

        self._profile_index += 1
        self.control.update(
            profile_number=self._profile_index,
            prospect_name=prospect.name,
            company=prospect.company,
            step="Starting prospect",
            current_profile_url=prospect.public_profile_url or prospect.profile_url,
        )

        profile_page: Page | None = None
        connect_sender = LinkedInConnectSender(sales_nav_page, self.settings)
        max_attempts = self.settings.retry_count + 1

        while True:
            try:
                for attempt in range(max_attempts):
                    try:
                        logger.info("Step: select prospect %s", prospect.name)
                        self.control.check_checkpoint("Opening profile")
                        profile_page = sales_scraper.open_profile_in_new_tab(prospect)
                        self._current_profile_page = profile_page
                        self._current_profile_url = profile_page.url

                        self.control.check_checkpoint("Extracting profile")
                        try:
                            profile_data = LinkedInProfileScraper(profile_page).extract(
                                fallback_name=prospect.name,
                                fallback_title=prospect.title,
                                fallback_company=prospect.company,
                                fallback_location=prospect.location,
                                max_attempts=self.settings.profile_extraction_retries,
                            )
                        except ScrapingError as extract_exc:
                            if profile_page:
                                try:
                                    profile_page.close()
                                except Exception:
                                    pass
                                profile_page = None
                            if attempt < max_attempts - 1:
                                logger.info(
                                    "Extraction failed for %s (attempt %d), retrying: %s",
                                    prospect.name,
                                    attempt + 1,
                                    extract_exc,
                                )
                                human_delay(self.settings)
                                continue
                            logger.warning(
                                "Skipping %s after extraction failures: %s",
                                prospect.name,
                                extract_exc,
                            )
                            failure = ProspectResult.create(
                                name=prospect.name,
                                title=prospect.title,
                                company=prospect.company,
                                location=prospect.location,
                                profile_url=prospect.profile_url,
                                status=f"skipped: {extract_exc}",
                            )
                            self.storage.save_failure(
                                failure, prospect.profile_url, mark_processed=True
                            )
                            self._processed_this_session += 1
                            self.browser.bring_to_front(sales_nav_page)
                            return

                        self._merge_card_metadata(profile_data, prospect)
                        prospect_name = profile_data.full_name or prospect.name
                        company = profile_data.company_name or prospect.company
                        logger.info(
                            "Step: profile extracted — name=%r title=%r company=%r",
                            prospect_name,
                            profile_data.current_job_title or prospect.title,
                            company,
                        )
                        self.control.update(
                            prospect_name=prospect_name,
                            company=company,
                            current_profile_url=profile_data.profile_url,
                        )

                        parsed, prompt, raw_response = self._generate_connection_request(
                            profile_data,
                            prospect_name=prospect_name,
                        )
                        connection_request = parsed.connection_request
                        logger.info("Step: CONNECTION_REQUEST parsed (%d chars)", len(connection_request))
                        logger.debug("ChatGPT raw response: %s", raw_response[:500])

                        self.storage.save_generated(
                            name=prospect_name,
                            title=profile_data.current_job_title or prospect.title,
                            company=company,
                            location=profile_data.location or prospect.location,
                            profile_url=profile_data.profile_url or prospect.profile_url,
                            connection_request=connection_request,
                        )

                        if profile_page:
                            profile_page.close()
                            profile_page = None
                            self._current_profile_page = None

                        self.browser.bring_to_front(sales_nav_page)
                        dismiss_linkedin_popups(sales_nav_page)
                        sales_nav_page.wait_for_timeout(1000)

                        diagnose_sn_page(sales_nav_page, "before_invitation_send")
                        logger.info("Step: open three-dot menu → Connect")
                        self.control.check_checkpoint("Opening connect dialog")
                        connect_sender.open_connect_dialog(prospect)
                        logger.info("Step: Send Invitation modal + textarea detected")

                        self.control.check_checkpoint("Pasting connection request")
                        connect_sender.paste_connection_note(connection_request)
                        logger.info("Step: note pasted")
                        connect_sender.verify_note_pasted(connection_request)
                        logger.info("Step: note verified")

                        status = GENERATED
                        if self.settings.connect_dry_run:
                            logger.info(
                                "Dry run — note pasted but not sent for %s",
                                prospect_name,
                            )
                            connect_sender.close_dialog()
                            diagnose_sn_page(sales_nav_page, "after_invitation_dry_run_close")
                        else:
                            self.control.check_checkpoint("Sending connection invitation")
                            connect_sender.send_invitation()
                            diagnose_sn_page(sales_nav_page, "after_invitation_send")
                            status = CONNECTION_SENT
                            self.storage.save_connection_sent(
                                name=prospect_name,
                                title=profile_data.current_job_title or prospect.title,
                                company=company,
                                location=profile_data.location or prospect.location,
                                profile_url=profile_data.profile_url or prospect.profile_url,
                                connection_request=connection_request,
                            )

                        result = ProspectResult.create(
                            name=prospect_name,
                            title=profile_data.current_job_title or prospect.title,
                            company=company,
                            location=profile_data.location or prospect.location,
                            profile_url=profile_data.profile_url or prospect.profile_url,
                            connection_request=connection_request,
                            status=status,
                        )
                        self.storage.save_success(
                            result,
                            profile_data.profile_url or prospect.profile_url,
                            mark_processed=(status == CONNECTION_SENT),
                        )
                        self._processed_this_session += 1
                        self.control.update(
                            success_count=self.control.snapshot().success_count + 1,
                            connection_status=status,
                            last_prompt=prompt,
                            last_response=raw_response,
                        )

                        self.browser.bring_to_front(sales_nav_page)
                        diagnose_sn_page(sales_nav_page, "after_profile_complete_before_next")
                        self.control.check_checkpoint("Ready for next prospect")
                        human_delay(self.settings)
                        return

                    except RetryProspect:
                        logger.info("Retry requested for %s", prospect.name)
                        connect_sender.close_dialog()
                        if profile_page:
                            try:
                                profile_page.close()
                            except Exception:
                                pass
                            profile_page = None
                        continue

                    except OpenProfileRequest:
                        self._open_current_profile()
                        continue

                    except (
                        ChatGPTError,
                        ChatGPTTimeoutError,
                        ParseError,
                        ScrapingError,
                        AutomationError,
                    ) as exc:
                        logger.error(
                            "Error processing %s (attempt %d/%d): %s",
                            prospect.name,
                            attempt + 1,
                            max_attempts,
                            exc,
                        )
                        connect_sender.close_dialog()
                        self._capture_failure_screenshot(
                            profile_page, sales_nav_page, prospect.name
                        )
                        if profile_page:
                            try:
                                profile_page.close()
                            except Exception:
                                pass
                            profile_page = None

                        if attempt < max_attempts - 1:
                            logger.info("Retrying %s...", prospect.name)
                            human_delay(self.settings)
                            continue

                        self._record_failure(prospect, exc)
                        self.browser.bring_to_front(sales_nav_page)
                        if not self.settings.connect_dry_run:
                            logger.error(
                                "Live run failure on %s — stopping automation",
                                prospect.name,
                            )
                            self._running = False
                        return

                return

            except SkipProspect:
                connect_sender.close_dialog()
                if profile_page:
                    try:
                        profile_page.close()
                    except Exception:
                        pass
                raise

    def _generate_connection_request(
        self,
        profile_data: ProfileData,
        *,
        prospect_name: str = "",
    ):
        """Submit profile to pinned ChatGPT conversation — never reload or new tab."""
        if self.chatgpt_client is None:
            raise ChatGPTError("ChatGPT client not initialized")

        self.control.check_checkpoint("Submitting profile to ChatGPT")
        self.browser.bring_to_front(self.registry.chatgpt_page)

        return self.chatgpt_client.submit_profile(
            profile_data.to_structured_text(),
            prospect_label=prospect_name or profile_data.full_name,
        )

    @staticmethod
    def _merge_card_metadata(profile_data: ProfileData, prospect: ProspectCard) -> None:
        if not profile_data.current_job_title and prospect.title:
            profile_data.current_job_title = prospect.title
        if not profile_data.company_name and prospect.company:
            profile_data.company_name = prospect.company
        if not profile_data.location and prospect.location:
            profile_data.location = prospect.location
        if not profile_data.profile_url:
            profile_data.profile_url = prospect.public_profile_url or prospect.profile_url

    def _open_current_profile(self) -> None:
        url = self._current_profile_url or self.control.snapshot().current_profile_url
        if not url:
            logger.warning("No current profile URL to open")
            return
        subprocess.run(["open", url], check=False)

    def _capture_failure_screenshot(self, profile_page, sales_nav_page, name: str) -> None:
        error_page = profile_page or sales_nav_page
        try:
            error_page = self.registry.chatgpt_page
        except TabNotFoundError:
            pass
        capture_error_screenshot(error_page, self.settings, f"error_{name}")

    def _record_failure(self, prospect: ProspectCard, exc: Exception) -> None:
        failure = ProspectResult.create(
            name=prospect.name,
            title=prospect.title,
            company=prospect.company,
            location=prospect.location,
            profile_url=prospect.profile_url,
            status=f"failed: {exc}",
        )
        self.storage.save_failure(failure, prospect.profile_url)
        self._processed_this_session += 1
        self.control.update(failure_count=self.control.snapshot().failure_count + 1)


def install_signal_handlers(orchestrator: AutomationOrchestrator) -> None:
    def _handler(signum, frame):  # noqa: ARG001
        logger.info("Received signal %s — shutting down...", signum)
        orchestrator.stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
