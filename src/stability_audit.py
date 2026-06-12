"""Run a multi-profile stability audit of the core outreach workflow."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from chatgpt.client import ChatGPTClient
from chatgpt.parser import parse_chatgpt_response
from config.prompts import build_prompt
from config.settings import Settings, get_settings
from scrapers.linkedin_profile import LinkedInProfileScraper
from scrapers.sales_navigator import ProspectCard, SalesNavigatorScraper
from src.browser import BrowserManager
from src.errors import ChatGPTError, ChatGPTTimeoutError, ParseError, ScrapingError
from src.logger import get_logger, setup_logging
from scrapers.profile_validation import validate_profile_data
from src.screenshots import capture_error_screenshot

logger = get_logger()

AUDIT_PROFILE_LIMIT = 20


@dataclass
class ProfileAuditRecord:
    index: int
    card_name: str = ""
    profile_url: str = ""
    status: str = "pending"
    failure_stage: str = ""
    failure_reason: str = ""
    screenshot: str = ""
    extracted_name: str = ""
    extracted_title: str = ""
    extracted_company: str = ""
    extracted_location: str = ""
    extracted_headline: str = ""
    extracted_about: str = ""
    extracted_experience: str = ""
    extraction_valid: bool = False
    extraction_errors: list[str] = field(default_factory=list)
    chatgpt_input: str = ""
    chatgpt_output: str = ""
    parsed_connection_request: str = ""
    parse_valid: bool = False


@dataclass
class AuditSummary:
    total: int = 0
    full_success: int = 0
    extraction_failures: int = 0
    navigation_failures: int = 0
    chatgpt_failures: int = 0
    parsing_failures: int = 0
    validation_failures: int = 0
    skipped: int = 0

    @property
    def success_rate(self) -> float:
        return (self.full_success / self.total * 100) if self.total else 0.0

    @property
    def failure_rate(self) -> float:
        return 100.0 - self.success_rate


class StabilityAuditor:
    def __init__(self, settings: Settings, output_dir: Path) -> None:
        self.settings = settings
        self.output_dir = output_dir
        self.screenshots_dir = output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.browser = BrowserManager(settings)
        self.records: list[ProfileAuditRecord] = []
        self.summary = AuditSummary()

    def run(self, limit: int = AUDIT_PROFILE_LIMIT) -> Path:
        logger.info("Stability audit starting — target %d profiles", limit)
        self.browser.connect()
        sales_page = self.browser.find_page_by_url_pattern(
            self.settings.sales_nav_url_pattern
        )
        self.browser.bring_to_front(sales_page)
        scraper = SalesNavigatorScraper(sales_page, self.settings)

        prospects = self._collect_prospects(scraper, sales_page, limit)
        self.summary.total = len(prospects)
        logger.info("Collected %d prospects for audit", len(prospects))

        for i, prospect in enumerate(prospects, start=1):
            record = ProfileAuditRecord(
                index=i,
                card_name=prospect.name,
                profile_url=prospect.public_profile_url or prospect.profile_url,
            )
            self._audit_one(prospect, record, scraper, sales_page)
            self.records.append(record)
            self._save_intermediate()

        report_path = self._write_report()
        logger.info("Audit complete — report at %s", report_path)
        self.browser.close()
        return report_path

    def _collect_prospects(
        self,
        scraper: SalesNavigatorScraper,
        sales_page,
        limit: int,
    ) -> list[ProspectCard]:
        collected: list[ProspectCard] = []
        seen: set[str] = set()

        while len(collected) < limit:
            for p in scraper.get_visible_prospects():
                key = p.profile_url
                if key not in seen:
                    seen.add(key)
                    collected.append(p)
                    if len(collected) >= limit:
                        break
            if len(collected) >= limit:
                break
            if not scraper.click_next_page():
                break
            sales_page.wait_for_timeout(2000)

        return collected[:limit]

    def _audit_one(
        self,
        prospect: ProspectCard,
        record: ProfileAuditRecord,
        scraper: SalesNavigatorScraper,
        sales_page,
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

            record.extracted_name = profile_data.full_name
            record.extracted_title = profile_data.current_job_title
            record.extracted_company = profile_data.company_name
            record.extracted_location = profile_data.location
            record.extracted_headline = profile_data.headline
            record.extracted_about = profile_data.about
            record.extracted_experience = profile_data.experience

            validation = validate_profile_data(profile_data)
            record.extraction_valid = validation.valid
            record.extraction_errors = validation.errors

            if not validation.valid:
                record.status = "failed"
                record.failure_stage = "extraction_validation"
                record.failure_reason = validation.message()
                self.summary.validation_failures += 1
                self.summary.extraction_failures += 1
                self._screenshot(profile_page, record, "validation")
                return

            profile_page.close()
            profile_page = None

            structured = profile_data.to_structured_text()
            record.chatgpt_input = build_prompt(structured)

            chatgpt_page = self.browser.find_page_by_url_pattern(
                self.settings.chatgpt_url_pattern
            )
            client = ChatGPTClient(chatgpt_page, self.settings)
            self.browser.bring_to_front(chatgpt_page)

            try:
                parsed, prompt, raw = client.generate_outreach(structured)
                record.chatgpt_input = prompt
                record.chatgpt_output = raw
            except (ChatGPTError, ChatGPTTimeoutError) as exc:
                record.status = "failed"
                record.failure_stage = "chatgpt"
                record.failure_reason = str(exc)
                self.summary.chatgpt_failures += 1
                self._screenshot(chatgpt_page, record, "chatgpt")
                return

            record.parsed_connection_request = parsed.connection_request
            record.parse_valid = parsed.is_valid()

            if not record.parse_valid:
                record.status = "failed"
                record.failure_stage = "parsing"
                record.failure_reason = "Parsed response missing required fields"
                self.summary.parsing_failures += 1
                self._screenshot(chatgpt_page, record, "parse")
                return

            record.status = "success"
            self.summary.full_success += 1
            self.browser.bring_to_front(sales_page)

        except ScrapingError as exc:
            record.status = "failed"
            record.failure_reason = str(exc)
            if "navigat" in str(exc).lower() or "profile" in str(exc).lower():
                record.failure_stage = "extraction"
                self.summary.extraction_failures += 1
            else:
                record.failure_stage = "extraction"
                self.summary.extraction_failures += 1
            self._screenshot(profile_page or sales_page, record, "extraction")
        except ParseError as exc:
            record.status = "failed"
            record.failure_stage = "parsing"
            record.failure_reason = str(exc)
            self.summary.parsing_failures += 1
            self._screenshot(sales_page, record, "parse")
        except Exception as exc:
            record.status = "failed"
            record.failure_stage = "navigation"
            record.failure_reason = str(exc)
            self.summary.navigation_failures += 1
            self._screenshot(profile_page or sales_page, record, "navigation")
        finally:
            if profile_page:
                try:
                    profile_page.close()
                except Exception:
                    pass

    def _screenshot(self, page, record: ProfileAuditRecord, label: str) -> None:
        path = capture_error_screenshot(
            page,
            Settings(
                screenshots_dir=self.screenshots_dir,
                logs_dir=self.output_dir,
            ),
            f"audit_{record.index:02d}_{label}_{record.card_name}",
        )
        if path:
            record.screenshot = path

    def _save_intermediate(self) -> None:
        data = {
            "generated_at": datetime.now().isoformat(),
            "summary": asdict(self.summary),
            "records": [asdict(r) for r in self.records],
        }
        (self.output_dir / "audit_results.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_report(self) -> Path:
        self._save_intermediate()
        root_causes = self._analyze_root_causes()
        fixes = self._recommended_fixes(root_causes)

        lines = [
            "# Stability Audit Report",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Profiles tested:** {self.summary.total}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Full workflow success | {self.summary.full_success}/{self.summary.total} ({self.summary.success_rate:.1f}%) |",
            f"| Failure rate | {self.summary.failure_rate:.1f}% |",
            f"| Extraction failures | {self.summary.extraction_failures} |",
            f"| Validation failures | {self.summary.validation_failures} |",
            f"| Navigation failures | {self.summary.navigation_failures} |",
            f"| ChatGPT failures | {self.summary.chatgpt_failures} |",
            f"| Parsing failures | {self.summary.parsing_failures} |",
            "",
            "## Accuracy (Extraction)",
            "",
        ]

        ext_ok = sum(1 for r in self.records if r.extraction_valid)
        ext_rate = (ext_ok / len(self.records) * 100) if self.records else 0
        lines.extend([
            f"- **Extraction validation pass rate:** {ext_ok}/{len(self.records)} ({ext_rate:.1f}%)",
            f"- **Target:** 95%",
            f"- **Meets target:** {'YES' if ext_rate >= 95 else 'NO'}",
            "",
            "## Per-Profile Results",
            "",
        ])

        for r in self.records:
            icon = "PASS" if r.status == "success" else "FAIL"
            lines.append(f"### {r.index}. {r.card_name} — {icon}")
            lines.append(f"- **Status:** {r.status}")
            if r.failure_stage:
                lines.append(f"- **Failure stage:** {r.failure_stage}")
                lines.append(f"- **Reason:** {r.failure_reason}")
            lines.append(f"- **Name:** {r.extracted_name or '(empty)'}")
            lines.append(f"- **Title:** {r.extracted_title or '(empty)'}")
            lines.append(f"- **Company:** {r.extracted_company or '(empty)'}")
            lines.append(f"- **Location:** {r.extracted_location or '(empty)'}")
            lines.append(f"- **About length:** {len(r.extracted_about)} chars")
            lines.append(f"- **Experience length:** {len(r.extracted_experience)} chars")
            if r.screenshot:
                lines.append(f"- **Screenshot:** `{r.screenshot}`")
            lines.append("")

        lines.extend(["## Root Causes", ""])
        for cause in root_causes:
            lines.append(f"- {cause}")

        lines.extend(["", "## Recommended Code Changes", ""])
        for fix in fixes:
            lines.append(f"- {fix}")

        report_path = self.output_dir / "STABILITY_REPORT.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")

        accuracy_path = self.output_dir / "ACCURACY_REPORT.md"
        accuracy_path.write_text(self._accuracy_report(ext_ok, ext_rate), encoding="utf-8")

        return report_path

    def _analyze_root_causes(self) -> list[str]:
        causes: list[str] = []
        error_counts: dict[str, int] = {}

        for r in self.records:
            if r.status == "success":
                continue
            key = f"{r.failure_stage}: {r.failure_reason[:120]}"
            error_counts[key] = error_counts.get(key, 0) + 1

        for err, count in sorted(error_counts.items(), key=lambda x: -x[1]):
            causes.append(f"({count}x) {err}")

        if not causes:
            causes.append("No failures recorded.")

        sn_lead = sum(1 for r in self.records if "/sales/lead/" in r.profile_url)
        if sn_lead > 0:
            causes.append(
                f"({sn_lead}/{len(self.records)}) profiles opened as Sales Navigator "
                "lead URLs — full /in/ profile navigation unavailable"
            )

        empty_about = sum(1 for r in self.records if r.extraction_valid and not r.extracted_about)
        if empty_about:
            causes.append(f"({empty_about}x) valid extractions missing About section content")

        return causes

    def _recommended_fixes(self, root_causes: list[str]) -> list[str]:
        fixes = [
            "Fix `launch_chrome.sh` to use non-default Chrome profile for CDP (Chrome 149+ blocks default path).",
            "Improve SN lead → /in/ profile resolution (lead pages expose 0 public /in/ links in testing).",
            "Expand SN lead-page selectors for about/experience sections.",
            "Add card-level title/company fallback when lead-page fields are sparse.",
            "Prioritize active Sales Navigator search tab when multiple SN tabs are open.",
            "Auto-open saved search if results list is empty on start.",
        ]
        if any("chatgpt" in c.lower() for c in root_causes):
            fixes.append("Increase ChatGPT timeout and add conversation-tab selection logic.")
        if any("empty job title" in c.lower() or "empty company" in c.lower() for c in root_causes):
            fixes.append("Merge Sales Navigator card metadata before validation when lead-page fields are empty.")
        return fixes

    def _accuracy_report(self, ext_ok: int, ext_rate: float) -> str:
        lines = [
            "# Accuracy Report",
            "",
            f"**Extraction validation pass rate:** {ext_ok}/{len(self.records)} ({ext_rate:.1f}%)",
            f"**Full pipeline pass rate:** {self.summary.full_success}/{self.summary.total} ({self.summary.success_rate:.1f}%)",
            "",
            "## Field Population (successful extractions only)",
            "",
        ]
        ok_records = [r for r in self.records if r.extraction_valid]
        if ok_records:
            for field_name, getter in [
                ("Name", lambda r: r.extracted_name),
                ("Title", lambda r: r.extracted_title),
                ("Company", lambda r: r.extracted_company),
                ("Location", lambda r: r.extracted_location),
                ("Headline", lambda r: r.extracted_headline),
                ("About", lambda r: r.extracted_about),
                ("Experience", lambda r: r.extracted_experience),
            ]:
                populated = sum(1 for r in ok_records if getter(r).strip())
                pct = populated / len(ok_records) * 100
                lines.append(f"- **{field_name}:** {populated}/{len(ok_records)} ({pct:.0f}%)")
        else:
            lines.append("No valid extractions to analyze.")

        lines.extend([
            "",
            "## Validation Rules Applied",
            "",
            "- Reject empty names",
            '- Reject "Sales Navigator Lead Page"',
            "- Reject empty company names",
            "- Reject empty job titles",
            "",
            f"## 95% Target: {'MET' if ext_rate >= 95 else 'NOT MET'}",
        ])
        return "\n".join(lines)


def run_stability_audit(limit: int = AUDIT_PROFILE_LIMIT) -> Path:
    settings = get_settings()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = settings.project_root / "audits" / f"stability_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    settings.log_file = output_dir / "audit.log"
    setup_logging(settings)
    auditor = StabilityAuditor(settings, output_dir)
    return auditor.run(limit=limit)


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else AUDIT_PROFILE_LIMIT
    path = run_stability_audit(limit=limit)
    print(f"Report written to {path}")
