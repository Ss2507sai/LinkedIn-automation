#!/usr/bin/env python3
"""Single-profile debug session with maximum logging and root-cause evidence."""

from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chatgpt.parser import parse_chatgpt_response
from chatgpt.waiter import _count_assistant_messages, wait_for_generation_complete
from config.prompts import CONNECTION_REQUEST_PROMPT_TEMPLATE, build_prompt
from config.settings import Settings, get_settings
from scrapers.linkedin_connect import LinkedInConnectSender
from scrapers.linkedin_profile import LinkedInProfileScraper
from scrapers.profile_validation import validate_profile_data
from scrapers.sales_navigator import ProspectCard, SalesNavigatorScraper
from src.browser import BrowserManager
from src.logger import get_logger, setup_logging
from src.screenshots import capture_error_screenshot

logger = get_logger()

ALLOWED_URL_PATTERNS = ("linkedin.com/sales", "chatgpt.com")
BLOCKED_URL_PATTERNS = ("salesql", "lusha", "apollo.io")


@dataclass
class Checkpoint:
    step: int
    name: str
    status: str = "PENDING"
    detail: str = ""


@dataclass
class TabEvent:
    timestamp: str
    action: str
    tab_index: int
    title: str
    url: str
    classification: str


@dataclass
class ClickEvent:
    timestamp: str
    action: str
    selector: str
    tag: str
    id: str
    aria_label: str
    class_name: str


@dataclass
class DebugSession:
    started_at: str = ""
    prospect_name: str = ""
    checkpoints: list[Checkpoint] = field(default_factory=list)
    tab_events: list[TabEvent] = field(default_factory=list)
    click_events: list[ClickEvent] = field(default_factory=list)
    keyboard_events: list[dict[str, str]] = field(default_factory=list)
    focus_events: list[dict[str, Any]] = field(default_factory=list)
    screenshots: dict[str, str] = field(default_factory=dict)
    prompt_template_path: str = ""
    prompt_first_500: str = ""
    profile_data_in_prompt: bool = False
    prompt_has_message_fields: bool = False
    parsed_connection_request: str = ""
    raw_chatgpt_response: str = ""
    linkedin_selectors: dict[str, str] = field(default_factory=dict)
    note_field_dom: dict[str, Any] = field(default_factory=dict)
    first_failing_step: int | None = None
    root_cause: str = ""
    issue_category: str = ""
    stopped_reason: str = ""


class DebugSessionRunner:
    def __init__(self, settings: Settings, output_dir: Path) -> None:
        self.settings = settings
        self.output_dir = output_dir
        self.shots = output_dir / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.session = DebugSession(started_at=datetime.now().isoformat())
        self.browser = BrowserManager(settings)
        self._last_action = "init"

    def run(self) -> Path:
        logger.info("=" * 70)
        logger.info("DEBUG SESSION START — single profile, maximum logging")
        logger.info("=" * 70)

        self._save_prompt_evidence()

        try:
            self.browser.connect()
            self._log_all_tabs("after_cdp_connect")

            # Checkpoint 1-2
            sn_page = self._checkpoint_sn_tab()
            self._checkpoint(2, "Correct Sales Navigator URL confirmed",
                             "linkedin.com/sales" in sn_page.url.lower(),
                             sn_page.url)

            scraper = SalesNavigatorScraper(sn_page, self.settings)
            prospects = scraper.get_visible_prospects()
            prospect = prospects[0]
            self.session.prospect_name = prospect.name

            # Checkpoint 3
            self._checkpoint(3, "Prospect card detected", bool(prospect.name and prospect.profile_url),
                             f"name={prospect.name}, url={prospect.profile_url}")
            self._screenshot(sn_page, "01_sales_nav_before_click")

            # Checkpoint 4 — card located (not clicked; profile opens via new tab)
            card_found = LinkedInConnectSender(sn_page, self.settings)._find_prospect_card(prospect) is not None
            self._checkpoint(4, "Prospect card clicked",
                             card_found,
                             "Card located on SN page (profile opens via new tab navigation)")

            # Checkpoint 5-6
            profile_page = scraper.open_profile_in_new_tab(prospect)
            self._log_tab_switch(profile_page, "open_profile_new_tab")
            self._screenshot(profile_page, "02_profile_page_opened")

            opened = profile_page.url and "linkedin.com" in profile_page.url.lower()
            self._checkpoint(5, "Profile page opened", opened, profile_page.url)

            url_ok = "/sales/lead/" in profile_page.url or "/in/" in profile_page.url
            self._checkpoint(6, "Correct profile page URL confirmed", url_ok, profile_page.url)

            # Checkpoint 7
            profile_data = LinkedInProfileScraper(profile_page).extract(
                fallback_name=prospect.name,
                fallback_title=prospect.title,
                fallback_company=prospect.company,
                fallback_location=prospect.location,
            )
            validation = validate_profile_data(profile_data)
            extracted = validation.valid
            self._checkpoint(7, "Profile data extracted", extracted,
                             validation.message() if not extracted else profile_data.to_structured_text()[:300])

            structured = profile_data.to_structured_text()
            prompt = build_prompt(structured)
            self.session.prompt_first_500 = prompt[:500]
            self.session.profile_data_in_prompt = profile_data.full_name in prompt
            self.session.prompt_has_message_fields = any(
                x in prompt for x in ("MESSAGE_1", "MESSAGE_2", "MESSAGE_3")
            )

            # Checkpoint 8-11
            chatgpt_page = self.browser.find_page_by_url_pattern(self.settings.chatgpt_url_pattern)
            self._log_tab_switch(chatgpt_page, "select_chatgpt_tab")
            self._checkpoint(8, "ChatGPT tab selected", "chatgpt.com" in chatgpt_page.url.lower(), chatgpt_page.url)
            self._checkpoint(9, "Correct ChatGPT URL confirmed", "chatgpt.com" in chatgpt_page.url.lower(), chatgpt_page.url)
            self._checkpoint(10, "Prompt built successfully", bool(prompt), f"{len(prompt)} chars")
            self._checkpoint(11, "Profile data included in prompt", self.session.profile_data_in_prompt,
                             f"name in prompt: {profile_data.full_name in prompt}")

            # ChatGPT interaction with instrumentation
            self._screenshot(chatgpt_page, "03_chatgpt_before_paste")
            self._investigate_chatgpt(chatgpt_page, prompt)

            # Checkpoint 12-15 handled inside _investigate_chatgpt

            # Return to LinkedIn
            self.browser.bring_to_front(sn_page)
            self._log_tab_switch(sn_page, "return_to_linkedin")

            # Checkpoint 16
            self._checkpoint(16, "Return to LinkedIn", "linkedin.com/sales" in sn_page.url.lower(), sn_page.url)

            connect = LinkedInConnectSender(sn_page, self.settings)
            self.session.linkedin_selectors = {
                "menu": str(connect.MENU_SELECTORS),
                "connect": str(connect.CONNECT_SELECTORS),
                "modal": str(connect.MODAL_SELECTORS),
                "note_field": str(connect.NOTE_FIELD_SELECTORS),
            }

            # Checkpoint 17-19
            card = connect._find_prospect_card(prospect)
            self._checkpoint(17, "Action menu opened", card is not None, "card located for menu click")

            if card is None:
                self._fail(17, "Could not find prospect card on SN page")
                return self._write_report()

            menu_ok = False
            for sel in connect.MENU_SELECTORS:
                try:
                    menu = card.locator(sel).first
                    if menu.count() and menu.is_visible(timeout=2000):
                        self._log_click(sn_page, "open_action_menu", sel, menu)
                        menu.click(timeout=3000)
                        menu_ok = True
                        self.session.linkedin_selectors["menu_used"] = sel
                        break
                except Exception as exc:
                    logger.debug("Menu selector %s failed: %s", sel, exc)
            sn_page.wait_for_timeout(800)
            self._screenshot(sn_page, "06_linkedin_action_menu")
            self._checkpoint(17, "Action menu opened", menu_ok, self.session.linkedin_selectors.get("menu_used", ""))

            connect_ok = False
            for sel in connect.CONNECT_SELECTORS:
                try:
                    item = sn_page.locator(sel).first
                    if item.is_visible(timeout=2000):
                        self._log_click(sn_page, "click_connect", sel, item)
                        item.click(timeout=3000)
                        connect_ok = True
                        self.session.linkedin_selectors["connect_used"] = sel
                        break
                except Exception:
                    continue
            self._checkpoint(18, "Connect clicked", connect_ok, self.session.linkedin_selectors.get("connect_used", ""))

            popup_ok = False
            try:
                connect._wait_for_invitation_popup()
                popup_ok = True
            except Exception as exc:
                self._checkpoint(19, "Invitation popup opened", False, str(exc))
            self._screenshot(sn_page, "07_invitation_popup")
            self._checkpoint(19, "Invitation popup opened", popup_ok, "Send invitation modal visible")

            # Checkpoint 20 — note field DOM
            dom = sn_page.evaluate(
                """() => {
                const modals = [...document.querySelectorAll('.artdeco-modal, [role="dialog"]')]
                    .filter(m => m.textContent && m.textContent.includes('Send invitation'));
                const modal = modals[modals.length - 1];
                if (!modal) return { error: 'no modal' };
                const ta = modal.querySelector('textarea');
                return ta ? {
                    tag: ta.tagName, id: ta.id, className: ta.className,
                    placeholder: ta.placeholder, visible: !!(ta.offsetWidth)
                } : { error: 'no textarea' };
            }"""
            )
            self.session.note_field_dom = dom
            note_detected = bool(dom.get("id") or dom.get("tag") == "TEXTAREA")
            self._screenshot(sn_page, "08_note_field")
            self._checkpoint(20, "Note field detected", note_detected, json.dumps(dom))

            # Checkpoint 21-22 — paste only if we have connection request
            if self.session.parsed_connection_request:
                try:
                    connect.paste_connection_note(self.session.parsed_connection_request)
                    preview = connect.get_note_field_preview()
                    pasted = self.session.parsed_connection_request[:40] in preview
                    self._screenshot(sn_page, "08_note_field_after_paste")
                    self._checkpoint(21, "Connection request pasted", pasted, preview[:200])
                    self._checkpoint(22, "Pasted text verified", pasted,
                                     f"expected={self.session.parsed_connection_request[:60]!r}, got={preview[:60]!r}")
                except Exception as exc:
                    self._checkpoint(21, "Connection request pasted", False, str(exc))
                    self._checkpoint(22, "Pasted text verified", False, str(exc))
            else:
                self._checkpoint(21, "Connection request pasted", False, "No connection request to paste")
                self._checkpoint(22, "Pasted text verified", False, "Skipped — no parsed request")

            connect.close_dialog()

        except Exception as exc:
            self.session.stopped_reason = str(exc)
            logger.exception("Debug session stopped: %s", exc)
            if self.session.first_failing_step is None:
                self.session.root_cause = str(exc)
                self.session.issue_category = "unexpected_error"

        return self._write_report()

    def _save_prompt_evidence(self) -> None:
        path = self.output_dir / "ACTIVE_PROMPT_TEMPLATE.txt"
        path.write_text(CONNECTION_REQUEST_PROMPT_TEMPLATE, encoding="utf-8")
        self.session.prompt_template_path = str(path)
        self.session.prompt_has_message_fields = any(
            x in CONNECTION_REQUEST_PROMPT_TEMPLATE for x in ("MESSAGE_1", "MESSAGE_2", "MESSAGE_3")
        )

    def _checkpoint_sn_tab(self):
        page = self.browser.find_page_by_url_pattern(self.settings.sales_nav_url_pattern)
        self._log_tab_switch(page, "select_sales_nav_tab")
        ok = "linkedin.com/sales" in page.url.lower()
        self._checkpoint(1, "Sales Navigator tab detected", ok, page.url)
        if not ok:
            self._fail(1, f"Wrong SN URL: {page.url}")
        return page

    def _checkpoint(self, step: int, name: str, passed: bool, detail: str = "") -> None:
        status = "PASS" if passed else "FAIL"
        cp = Checkpoint(step=step, name=name, status=status, detail=detail[:2000])
        self.session.checkpoints.append(cp)
        logger.info("CHECKPOINT %02d [%s] %s — %s", step, status, name, detail[:200])
        if not passed and self.session.first_failing_step is None:
            self.session.first_failing_step = step
            self.session.root_cause = detail or name
            self._classify_issue(step, detail)

    def _fail(self, step: int, reason: str) -> None:
        self._checkpoint(step, self._step_name(step), False, reason)
        self.session.stopped_reason = reason

    @staticmethod
    def _step_name(step: int) -> str:
        names = {
            1: "Sales Navigator tab detected",
            2: "Correct Sales Navigator URL confirmed",
        }
        return names.get(step, f"Step {step}")

    def _classify_issue(self, step: int, detail: str) -> None:
        d = detail.lower()
        if "salesql" in d:
            self.session.issue_category = "extension_issue"
        elif step in (8, 9, 10, 11, 12, 13, 14, 15):
            self.session.issue_category = "chatgpt_issue"
        elif "voice" in d or "microphone" in d or "dictat" in d:
            self.session.issue_category = "chatgpt_issue"
        elif step in (17, 18, 19, 20, 21, 22):
            self.session.issue_category = "linkedin_issue"
        elif step in (5, 6, 7):
            self.session.issue_category = "linkedin_issue"
        elif "timeout" in d or "wait" in d:
            self.session.issue_category = "timing_issue"
        elif "tab" in d:
            self.session.issue_category = "tab_switching_issue"
        else:
            self.session.issue_category = "selector_issue"

    def _log_all_tabs(self, action: str) -> None:
        for i, page in enumerate(self.browser.context.pages):
            self._record_tab(action, i, page)

    def _log_tab_switch(self, page, action: str) -> None:
        self._last_action = action
        idx = self.browser.context.pages.index(page) if page in self.browser.context.pages else -1
        self._record_tab(action, idx, page)
        self._check_tab_allowed(page, action)

    def _record_tab(self, action: str, index: int, page) -> None:
        try:
            title = page.title()
            url = page.url
        except Exception:
            title = "(unreadable)"
            url = "(unreadable)"

        classification = self._classify_url(url)
        event = TabEvent(
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            action=action,
            tab_index=index,
            title=title[:120],
            url=url[:300],
            classification=classification,
        )
        self.session.tab_events.append(event)
        logger.info(
            "TAB [%s] idx=%d class=%s title=%r url=%s",
            action, index, classification, title[:60], url[:120],
        )

    def _classify_url(self, url: str) -> str:
        lower = url.lower()
        for blocked in BLOCKED_URL_PATTERNS:
            if blocked in lower:
                return f"FAIL:blocked({blocked})"
        for allowed in ALLOWED_URL_PATTERNS:
            if allowed in lower:
                return "PASS"
        if "linkedin.com" in lower:
            return "WARN:linkedin_non_sales"
        return "FAIL:unexpected"

    def _check_tab_allowed(self, page, action: str) -> None:
        url = page.url.lower()
        for blocked in BLOCKED_URL_PATTERNS:
            if blocked in url:
                self._screenshot(page, f"09_salesql_or_blocked_{blocked}")
                msg = (
                    f"BLOCKED TAB activated during action={action!r}. "
                    f"URL={page.url}. Triggered after: {self._last_action}"
                )
                logger.error(msg)
                self.session.stopped_reason = msg
                self.session.root_cause = (
                    f"SalesQL/extension tab became active. "
                    f"Action that preceded switch: {self._last_action}. "
                    f"Likely cause: wrong tab selected or extension sidebar opened on click."
                )
                self.session.issue_category = "extension_issue"
                raise RuntimeError(msg)

    def _screenshot(self, page, label: str) -> None:
        path = capture_error_screenshot(
            page,
            Settings(screenshots_dir=self.shots, logs_dir=self.output_dir),
            label,
        )
        if path:
            self.session.screenshots[label] = path
            logger.info("SCREENSHOT %s -> %s", label, path)

    def _log_focus(self, page, label: str) -> dict:
        info = page.evaluate(
            """() => {
            const el = document.activeElement;
            if (!el) return { tag: 'none' };
            return {
                tag: el.tagName,
                id: el.id || '',
                className: (el.className || '').toString().slice(0, 120),
                ariaLabel: el.getAttribute('aria-label') || '',
                dataTestId: el.getAttribute('data-testid') || '',
                role: el.getAttribute('role') || '',
                isContentEditable: el.isContentEditable,
            };
        }"""
        )
        info["label"] = label
        info["timestamp"] = datetime.now().isoformat()
        self.session.focus_events.append(info)
        logger.info("FOCUS [%s] %s", label, json.dumps(info))
        return info

    def _log_click(self, page, action: str, selector: str, locator) -> None:
        try:
            info = locator.evaluate(
                """el => ({
                    tag: el.tagName,
                    id: el.id || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    className: (el.className || '').toString().slice(0, 120),
                })"""
            )
        except Exception:
            info = {"tag": "?", "id": "", "ariaLabel": "", "className": ""}
        ev = ClickEvent(
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            action=action,
            selector=selector,
            tag=info.get("tag", ""),
            id=info.get("id", ""),
            aria_label=info.get("ariaLabel", ""),
            class_name=info.get("className", ""),
        )
        self.session.click_events.append(ev)
        logger.info("CLICK [%s] selector=%s element=%s", action, selector, json.dumps(info))

    def _investigate_chatgpt(self, page, prompt: str) -> None:
        from chatgpt.client import (
            SUBMIT_SELECTORS,
            TEXT_INPUT_SELECTORS,
            VOICE_BUTTON_SELECTORS,
            ChatGPTClient,
        )

        client = ChatGPTClient(page, self.settings)
        self.browser.bring_to_front(page)
        self._log_tab_switch(page, "chatgpt_bring_to_front")

        voice_before = client.is_voice_mode_active()
        self._log_focus(page, "before_focus")
        if voice_before:
            self._screenshot(page, "10_voice_mode_before_interaction")
            self._checkpoint(12, "Prompt pasted into ChatGPT", False, "Voice mode already active before paste")
            self._fail(12, "Voice mode active before ChatGPT interaction")
            raise RuntimeError("Voice mode active before interaction")

        # Find input — log which selector matches
        input_el = None
        input_selector_used = ""
        composer = client._composer()
        for sel in TEXT_INPUT_SELECTORS:
            try:
                el = composer.locator(sel).first
                if el.count() and el.is_visible(timeout=1500):
                    input_el = el
                    input_selector_used = sel
                    break
            except Exception:
                continue
        if not input_el:
            self._checkpoint(12, "Prompt pasted into ChatGPT", False, "No text input found")
            raise RuntimeError("ChatGPT text input not found")

        logger.info("TEXT INPUT selector matched: %s", input_selector_used)
        self._log_click(page, "focus_text_input", input_selector_used, input_el)
        input_el.focus(timeout=3000)
        self._log_focus(page, "after_focus_text_input")

        # Check if focus landed on mic
        focus = self.session.focus_events[-1]
        mic_focus = any(
            x in (focus.get("ariaLabel", "") + focus.get("dataTestId", "")).lower()
            for x in ("voice", "speech", "dictat", "microphone", "composer-speech")
        )
        if mic_focus:
            self._screenshot(page, "10_microphone_received_focus")
            self._checkpoint(12, "Prompt pasted into ChatGPT", False,
                             f"Focus on mic/voice element: {json.dumps(focus)}")
            raise RuntimeError(f"Microphone received focus: {focus}")

        # Paste
        tag = input_el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            input_el.fill(prompt)
        else:
            input_el.focus()
            page.keyboard.insert_text(prompt)
        self._log_keyboard("insert_text", f"prompt {len(prompt)} chars via {input_selector_used}")
        self._screenshot(page, "04_chatgpt_after_paste")
        self._log_focus(page, "after_paste")

        pasted_ok = page.evaluate(
            """(sel) => {
            const el = document.querySelector(sel) || document.getElementById('prompt-textarea');
            if (!el) return false;
            const text = el.value || el.textContent || '';
            return text.length > 100;
        }""",
            input_selector_used.split()[-1].replace("#", "#") if "#" in input_selector_used else "#prompt-textarea",
        )
        # simpler check
        try:
            content = input_el.input_value(timeout=2000) if tag == "textarea" else input_el.inner_text(timeout=2000)
            pasted_ok = len(content) > 100
        except Exception:
            pasted_ok = False

        self._checkpoint(12, "Prompt pasted into ChatGPT", pasted_ok,
                         f"selector={input_selector_used}, len check passed={pasted_ok}")

        # Submit — log which method
        baseline = _count_assistant_messages(page)
        submitted = False
        submit_method = ""
        for sel in SUBMIT_SELECTORS:
            try:
                btn = composer.locator(sel).first
                if btn.is_visible(timeout=1500) and btn.is_enabled():
                    self._log_click(page, "submit_prompt", sel, btn)
                    self._log_focus(page, "before_submit_click")
                    btn.click(timeout=3000)
                    submitted = True
                    submit_method = f"click:{sel}"
                    break
            except Exception:
                continue
        if not submitted:
            self._log_keyboard("Enter", "submit fallback")
            self._log_focus(page, "before_enter_submit")
            page.keyboard.press("Enter")
            submit_method = "keyboard:Enter"

        self._log_focus(page, "after_submit")
        voice_after = client.is_voice_mode_active()
        if voice_after:
            self._screenshot(page, "10_voice_mode_after_submit")
            for sel in VOICE_BUTTON_SELECTORS:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=500):
                        self._log_click(page, "voice_button_visible", sel, btn)
                except Exception:
                    pass

        self._checkpoint(13, "Prompt submitted", True, submit_method)

        if voice_after:
            self._checkpoint(14, "ChatGPT response received", False, "Voice mode activated after submit")
            raise RuntimeError(f"Voice mode activated after submit via {submit_method}")

        try:
            raw = wait_for_generation_complete(page, self.settings, baseline_message_count=baseline)
            self.session.raw_chatgpt_response = raw
            self._screenshot(page, "05_chatgpt_response")
            self._checkpoint(14, "ChatGPT response received", bool(raw), f"{len(raw)} chars")
        except Exception as exc:
            self._checkpoint(14, "ChatGPT response received", False, str(exc))
            raise

        try:
            parsed = parse_chatgpt_response(raw)
            self.session.parsed_connection_request = parsed.connection_request
            self._checkpoint(15, "CONNECTION_REQUEST parsed", parsed.is_valid(),
                             parsed.connection_request[:200])
        except Exception as exc:
            self._checkpoint(15, "CONNECTION_REQUEST parsed", False, str(exc))

    def _log_keyboard(self, key: str, detail: str) -> None:
        ev = {"timestamp": datetime.now().isoformat(), "key": key, "detail": detail}
        self.session.keyboard_events.append(ev)
        logger.info("KEYBOARD %s — %s", key, detail)

    def _write_report(self) -> Path:
        report = self.output_dir / "DEBUG_SESSION_REPORT.md"
        lines = [
            "# Single Profile Debug Session Report",
            "",
            f"**Started:** {self.session.started_at}",
            f"**Prospect:** {self.session.prospect_name}",
            f"**Stopped:** {self.session.stopped_reason or 'completed'}",
            "",
            "## Checkpoints",
            "",
            "| Step | Status | Name | Detail |",
            "|------|--------|------|--------|",
        ]
        for cp in self.session.checkpoints:
            detail = cp.detail.replace("|", "/").replace("\n", " ")[:120]
            lines.append(f"| {cp.step} | **{cp.status}** | {cp.name} | {detail} |")

        lines.extend(["", "## Tab Tracking", ""])
        for t in self.session.tab_events:
            lines.append(
                f"- `{t.timestamp}` **{t.action}** idx={t.tab_index} "
                f"[{t.classification}] {t.title!r} — {t.url[:100]}"
            )

        lines.extend(["", "## Click Events", ""])
        for c in self.session.click_events:
            lines.append(
                f"- `{c.timestamp}` **{c.action}** `{c.selector}` → "
                f"<{c.tag}> id={c.id!r} aria-label={c.aria_label!r}"
            )

        lines.extend(["", "## Focus Events", ""])
        for f in self.session.focus_events:
            lines.append(f"- **{f.get('label')}**: `{json.dumps(f)}`")

        lines.extend(["", "## Keyboard Events", ""])
        for k in self.session.keyboard_events:
            lines.append(f"- `{k['timestamp']}` **{k['key']}** — {k['detail']}")

        lines.extend([
            "",
            "## Prompt Investigation",
            f"- Template: `{self.session.prompt_template_path}`",
            f"- MESSAGE_1/2/3 in template: **{self.session.prompt_has_message_fields}**",
            f"- Profile data in prompt: **{self.session.profile_data_in_prompt}**",
            "",
            "### First 500 chars of generated prompt",
            "```",
            self.session.prompt_first_500,
            "```",
            "",
            f"- Parsed CONNECTION_REQUEST: {self.session.parsed_connection_request[:300]}",
            "",
            "## LinkedIn Selectors",
            "",
        ])
        for k, v in self.session.linkedin_selectors.items():
            lines.append(f"- **{k}**: `{v[:200]}`")
        lines.append(f"\n- **Note field DOM**: `{json.dumps(self.session.note_field_dom)}`")

        lines.extend([
            "",
            "## Screenshots",
            "",
        ])
        for label, path in self.session.screenshots.items():
            lines.append(f"- **{label}**: `{path}`")

        lines.extend([
            "",
            "## Root Cause Analysis",
            "",
            f"1. **First failing step:** {self.session.first_failing_step or 'None (all passed)'}",
            f"2. **Root cause:** {self.session.root_cause or 'N/A'}",
            f"3. **Issue category:** {self.session.issue_category or 'N/A'}",
            "",
        ])

        report.write_text("\n".join(lines), encoding="utf-8")
        (self.output_dir / "debug_session.json").write_text(
            json.dumps(asdict(self.session), indent=2, default=str),
            encoding="utf-8",
        )
        self.browser.close()
        logger.info("Debug report written: %s", report)
        return report


def run_debug_session() -> Path:
    settings = get_settings()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = settings.project_root / "audits" / f"debug_session_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)
    settings.log_file = output_dir / "debug_session.log"
    setup_logging(settings)
    return DebugSessionRunner(settings, output_dir).run()


if __name__ == "__main__":
    path = run_debug_session()
    print(f"Debug session complete: {path}")
