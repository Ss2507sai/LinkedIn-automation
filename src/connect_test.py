"""Run a 3-profile blocker test: connection-only prompt, no voice mode, note paste."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from chatgpt.client import ChatGPTClient
from config.prompts import CONNECTION_REQUEST_PROMPT_TEMPLATE, build_prompt
from config.settings import Settings, get_settings
from scrapers.linkedin_connect import LinkedInConnectSender
from scrapers.linkedin_profile import LinkedInProfileScraper
from scrapers.profile_validation import validate_profile_data
from scrapers.sales_navigator import ProspectCard, SalesNavigatorScraper
from src.browser import BrowserManager
from src.control import AutomationControl
from src.errors import ChatGPTError, ChatGPTTimeoutError, ParseError, ScrapingError
from src.logger import get_logger, setup_logging
from src.screenshots import capture_error_screenshot
from src.utils import dismiss_linkedin_popups
from storage.csv_writer import CSVWriter
from storage.database import ProspectDatabase
from storage.results import ProspectResult

logger = get_logger()


@dataclass
class ConnectTestRecord:
    index: int
    name: str = ""
    company: str = ""
    profile_url: str = ""
    connection_request: str = ""
    status: str = "pending"
    failure_reason: str = ""
    screenshots: dict[str, str] = field(default_factory=dict)
    note_field_preview: str = ""
    approval_shown: bool = False
    prompt_preview: str = ""
    raw_chatgpt_response: str = ""
    voice_mode_detected: bool = False
    prompt_uses_connection_only: bool = False


class ConnectTestRunner:
    def __init__(self, settings: Settings, output_dir: Path, limit: int = 3) -> None:
        self.settings = settings
        self.output_dir = output_dir
        self.limit = limit
        self.screenshots_dir = output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.browser = BrowserManager(settings)
        self.control = AutomationControl(approval_mode=True)
        self.records: list[ConnectTestRecord] = []
        self.db = ProspectDatabase(output_dir / "blocker_test.db")
        self.csv_path = output_dir / "blocker_test_results.csv"

    def run(self) -> Path:
        logger.info("Blocker test starting — %d profiles (dry run, no send)", self.limit)
        self._save_prompt_template_evidence()

        self.browser.connect()
        sales_page = self.browser.find_page_by_url_pattern(
            self.settings.sales_nav_url_pattern
        )
        self.browser.bring_to_front(sales_page)
        scraper = SalesNavigatorScraper(sales_page, self.settings)
        connect_sender = LinkedInConnectSender(sales_page, self.settings)

        prospects = scraper.get_visible_prospects()[: self.limit]
        if len(prospects) < self.limit:
            logger.warning("Only %d prospects visible", len(prospects))

        for i, prospect in enumerate(prospects, start=1):
            record = ConnectTestRecord(
                index=i,
                name=prospect.name,
                company=prospect.company,
                profile_url=prospect.profile_url,
            )
            self._test_one(prospect, record, scraper, sales_page, connect_sender)
            self.records.append(record)

        return self._write_report()

    def _save_prompt_template_evidence(self) -> None:
        (self.output_dir / "ACTIVE_PROMPT_TEMPLATE.txt").write_text(
            CONNECTION_REQUEST_PROMPT_TEMPLATE,
            encoding="utf-8",
        )

    def _shot(self, page, record: ConnectTestRecord, key: str, label: str) -> None:
        path = capture_error_screenshot(
            page,
            Settings(screenshots_dir=self.screenshots_dir, logs_dir=self.output_dir),
            f"p{record.index:02d}_{label}",
        )
        if path:
            record.screenshots[key] = path

    def _test_one(
        self,
        prospect: ProspectCard,
        record: ConnectTestRecord,
        scraper: SalesNavigatorScraper,
        sales_page,
        connect_sender: LinkedInConnectSender,
    ) -> None:
        profile_page = None
        try:
            profile_page = scraper.open_profile_in_new_tab(prospect)
            profile_data = LinkedInProfileScraper(profile_page).extract(
                fallback_name=prospect.name,
                fallback_title=prospect.title,
                fallback_company=prospect.company,
                fallback_location=prospect.location,
                max_attempts=self.settings.profile_extraction_retries,
            )
            validation = validate_profile_data(profile_data)
            if not validation.valid:
                record.status = "failed"
                record.failure_reason = validation.message()
                return

            profile_page.close()
            profile_page = None

            structured = profile_data.to_structured_text()
            prompt = build_prompt(structured)
            record.prompt_preview = prompt[:500]
            record.prompt_uses_connection_only = (
                "generate ONLY a personalized LinkedIn connection request" in prompt
                and "MESSAGE_1" not in prompt
                and "MESSAGE_2" not in prompt
            )
            (self.output_dir / f"profile_{record.index:02d}_prompt.txt").write_text(
                prompt, encoding="utf-8"
            )

            chatgpt_page = self.browser.find_page_by_url_pattern(
                self.settings.chatgpt_url_pattern
            )
            self.browser.bring_to_front(chatgpt_page)
            client = ChatGPTClient(chatgpt_page, self.settings)

            self._shot(chatgpt_page, record, "chatgpt_before_focus", "chatgpt_before_focus")
            if client.is_voice_mode_active():
                record.voice_mode_detected = True
                raise ChatGPTError("Voice mode active before ChatGPT interaction")

            parsed, used_prompt, raw = client.generate_outreach(structured)
            record.raw_chatgpt_response = raw
            record.connection_request = parsed.connection_request
            record.name = profile_data.full_name or prospect.name
            record.company = profile_data.company_name or prospect.company

            self._shot(chatgpt_page, record, "chatgpt_after_submit", "chatgpt_after_submit")
            if client.is_voice_mode_active():
                record.voice_mode_detected = True
                raise ChatGPTError("Voice mode activated during ChatGPT interaction")

            (self.output_dir / f"profile_{record.index:02d}_parsed.json").write_text(
                json.dumps(
                    {
                        "connection_request": parsed.connection_request,
                        "char_count": len(parsed.connection_request),
                        "valid": parsed.is_valid(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            self.db.save_generated(
                name=record.name,
                title=profile_data.current_job_title or prospect.title,
                company=record.company,
                location=profile_data.location or prospect.location,
                profile_url=profile_data.profile_url or prospect.profile_url,
                connection_request=record.connection_request,
            )
            result = ProspectResult.create(
                name=record.name,
                title=profile_data.current_job_title or prospect.title,
                company=record.company,
                location=profile_data.location or prospect.location,
                profile_url=profile_data.profile_url or prospect.profile_url,
                connection_request=record.connection_request,
                status="Generated",
            )
            CSVWriter(self.csv_path).append(result)

            self.browser.bring_to_front(sales_page)
            dismiss_linkedin_popups(sales_page)

            def screenshot_cb(label: str) -> None:
                self._shot(sales_page, record, label, label)

            connect_sender.open_connect_dialog(prospect, screenshot_cb=screenshot_cb)

            self.control.update(
                approval_pending=True,
                prospect_name=record.name,
                company=record.company,
                pending_connection_request=record.connection_request,
            )
            time.sleep(1)
            self._shot(sales_page, record, "approval_mode", "approval_pending")
            record.approval_shown = True
            self.control.button_approve_send()
            time.sleep(0.5)

            note = record.connection_request
            connect_sender.paste_connection_note(note)
            self._shot(sales_page, record, "note_field_populated", "note_populated")
            record.note_field_preview = connect_sender.get_note_field_preview()

            pasted_ok = (
                note.strip()[:40] in record.note_field_preview
                or record.note_field_preview.strip()[:40] in note.strip()
            )
            if not pasted_ok:
                record.status = "failed"
                record.failure_reason = (
                    f"Paste verification failed. Expected start: {note[:60]!r}, "
                    f"got: {record.note_field_preview[:60]!r}"
                )
                connect_sender.close_dialog()
                return

            connect_sender.close_dialog()
            record.status = "success"
        except (ScrapingError, ChatGPTError, ChatGPTTimeoutError, ParseError) as exc:
            record.status = "failed"
            record.failure_reason = str(exc)
            connect_sender.close_dialog()
            self._shot(profile_page or sales_page, record, "error", "error")
        except Exception as exc:
            record.status = "failed"
            record.failure_reason = str(exc)
            connect_sender.close_dialog()
            self._shot(profile_page or sales_page, record, "error", "error")
        finally:
            if profile_page:
                try:
                    profile_page.close()
                except Exception:
                    pass

    def _write_report(self) -> Path:
        success = sum(1 for r in self.records if r.status == "success")
        data = {
            "generated_at": datetime.now().isoformat(),
            "limit": self.limit,
            "success": success,
            "total": len(self.records),
            "dry_run": True,
            "blockers": {
                "connection_request_only": all(r.prompt_uses_connection_only for r in self.records),
                "voice_mode_clear": not any(r.voice_mode_detected for r in self.records),
                "note_paste": success == len(self.records),
            },
            "records": [asdict(r) for r in self.records],
        }
        (self.output_dir / "blocker_test_results.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        lines = [
            "# Blocker Test Report",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Success:** {success}/{len(self.records)}",
            f"**Dry run:** Yes (no invitations sent)",
            "",
            "## Blocker 1: Connection Request Only",
            f"- Active template saved: `ACTIVE_PROMPT_TEMPLATE.txt`",
            f"- All prompts connection-only: {all(r.prompt_uses_connection_only for r in self.records)}",
            "",
            "## Blocker 2: Voice Mode",
            f"- Voice mode detected on any profile: {any(r.voice_mode_detected for r in self.records)}",
            "",
            "## Blocker 3: Note Field Paste",
            f"- Paste success: {success}/{len(self.records)}",
            "",
            "## Per-Profile Results",
            "",
        ]

        for r in self.records:
            lines.append(f"### {r.index}. {r.name} — {r.status.upper()}")
            if r.failure_reason:
                lines.append(f"- **Failure:** {r.failure_reason}")
            lines.append(f"- **Connection request:** {r.connection_request[:100]}...")
            lines.append(f"- **Note preview:** {r.note_field_preview[:100]}...")
            lines.append(f"- **Voice mode:** {r.voice_mode_detected}")
            for key, path in r.screenshots.items():
                lines.append(f"- **Screenshot ({key}):** `{path}`")
            lines.append("")

        report_path = self.output_dir / "BLOCKER_TEST_REPORT.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        self.browser.close()
        logger.info("Blocker test report: %s", report_path)
        return report_path


def run_connect_test(limit: int = 3) -> Path:
    settings = get_settings()
    settings.connect_dry_run = True
    settings.test_mode = True
    settings.test_mode_limit = limit
    settings.approval_mode = True
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = settings.project_root / "audits" / f"blocker_test_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    settings.log_file = output_dir / "blocker_test.log"
    setup_logging(settings)
    return ConnectTestRunner(settings, output_dir, limit=limit).run()
