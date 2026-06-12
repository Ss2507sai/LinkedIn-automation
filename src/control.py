"""Runtime control plane for pause/resume, commands, and approval mode."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.errors import AutomationError


class AutomationCommand(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    SKIP = "skip"
    RETRY = "retry"
    REGENERATE = "regenerate"
    OPEN_PROFILE = "open current profile"
    SAVE_AND_STOP = "save and stop"
    NEXT_PAGE = "process next page"
    CHANGE_PROMPT = "change prompt"
    APPROVE_SEND = "approve and send"
    EDIT = "edit"
    APPROVAL_SKIP = "skip"


INVALID_PROFILE_NAMES = frozenset(
    {
        "sales navigator lead page",
        "linkedin",
        "unknown",
        "search",
        "sales navigator",
    }
)


def is_valid_profile_name(name: str) -> bool:
    cleaned = (name or "").strip()
    if len(cleaned) < 2:
        return False
    return cleaned.lower() not in INVALID_PROFILE_NAMES


@dataclass
class ControlState:
    profile_number: int = 0
    prospect_name: str = ""
    company: str = ""
    step: str = "Idle"
    success_count: int = 0
    failure_count: int = 0
    page_number: int = 1
    mode: str = "APPROVAL"
    current_profile_url: str = ""
    last_prompt: str = ""
    last_response: str = ""
    approval_pending: bool = False
    pending_connection_request: str = ""
    connection_status: str = ""


class AutomationControl:
    """Thread-safe control surface shared by orchestrator and UI."""

    def __init__(self, approval_mode: bool = True) -> None:
        self.approval_mode = approval_mode
        self.state = ControlState(mode="APPROVAL" if approval_mode else "AUTO")
        self._lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop = False
        self._skip = False
        self._retry = False
        self._regenerate = False
        self._save_and_stop = False
        self._next_page = False
        self._open_profile = False
        self._custom_prompt: str | None = None
        self._approval_event = threading.Event()
        self._approval_decision: str | None = None
        self._edited_connection_request: str | None = None

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, value)

    def snapshot(self) -> ControlState:
        with self._lock:
            return ControlState(**vars(self.state))

    def set_edited_connection_request(self, text: str) -> None:
        with self._lock:
            self._edited_connection_request = text.strip()
            self.state.pending_connection_request = self._edited_connection_request

    def get_connection_request_for_send(self) -> str:
        with self._lock:
            if self._edited_connection_request:
                return self._edited_connection_request
            return self.state.pending_connection_request

    def submit_command(self, raw: str) -> str:
        cmd = raw.strip().lower()
        if not cmd:
            return "No command"

        if cmd in {AutomationCommand.PAUSE, "p"}:
            self._pause_event.clear()
            self.update(step="Paused")
            return "Paused"

        if cmd in {AutomationCommand.RESUME, "r"}:
            self._pause_event.set()
            return "Resumed"

        if cmd in {AutomationCommand.STOP, "quit", "exit"}:
            self._stop = True
            self._pause_event.set()
            self._approval_event.set()
            return "Stop requested"

        if cmd in {AutomationCommand.SKIP, "s", AutomationCommand.APPROVAL_SKIP}:
            self._skip = True
            self._pause_event.set()
            self._approval_event.set()
            return "Skip requested"

        if cmd in {AutomationCommand.RETRY, "try again"}:
            self._retry = True
            self._pause_event.set()
            return "Retry requested"

        if cmd in {AutomationCommand.REGENERATE, "regen"}:
            self._regenerate = True
            self._pause_event.set()
            self._approval_event.set()
            return "Regenerate requested"

        if cmd in {AutomationCommand.APPROVE_SEND, "approve", "approve and send", "a"}:
            self._set_approval("approve_send")
            return "Approve & Send requested"

        if cmd in {AutomationCommand.OPEN_PROFILE, "open profile"}:
            self._open_profile = True
            return "Open profile requested"

        if cmd in {AutomationCommand.SAVE_AND_STOP, "save"}:
            self._save_and_stop = True
            self._stop = True
            self._pause_event.set()
            self._approval_event.set()
            return "Save and stop requested"

        if cmd in {AutomationCommand.NEXT_PAGE, "next page"}:
            self._next_page = True
            return "Next page requested"

        if cmd.startswith("change prompt") or cmd.startswith("prompt "):
            prompt = raw.split(":", 1)[-1].strip()
            if cmd.startswith("prompt "):
                prompt = raw[len("prompt ") :].strip()
            if not prompt:
                return "Usage: change prompt: <text> or prompt <text>"
            self._custom_prompt = prompt
            return "Custom prompt set"

        return f"Unknown command: {raw}"

    def button_pause(self) -> None:
        self.submit_command("pause")

    def button_resume(self) -> None:
        self.submit_command("resume")

    def button_stop(self) -> None:
        self.submit_command("stop")

    def button_skip(self) -> None:
        self.submit_command("skip")

    def button_retry(self) -> None:
        self.submit_command("retry")

    def button_open_profile(self) -> None:
        self.submit_command("open current profile")

    def button_save_and_stop(self) -> None:
        self.submit_command("save and stop")

    def button_approve_send(self) -> None:
        self.submit_command("approve and send")

    def button_regenerate(self) -> None:
        self.submit_command("regenerate")

    def button_approval_skip(self) -> None:
        self.submit_command("skip")

    def get_custom_prompt(self) -> str | None:
        with self._lock:
            prompt = self._custom_prompt
            self._custom_prompt = None
            return prompt

    def wait_if_paused(self) -> None:
        while not self._pause_event.is_set():
            if self._stop:
                raise StopAutomation()
            time.sleep(0.2)

    def check_checkpoint(self, checkpoint: str) -> None:
        self.update(step=checkpoint)
        self.wait_if_paused()

        if self._stop:
            raise StopAutomation()
        if self._save_and_stop:
            raise SaveAndStop()
        if self._skip:
            self._skip = False
            raise SkipProspect()
        if self._next_page:
            self._next_page = False
            raise ProcessNextPage()
        if self._open_profile:
            self._open_profile = False
            raise OpenProfileRequest()
        if self._retry:
            self._retry = False
            raise RetryProspect()

    def consume_regenerate(self) -> bool:
        with self._lock:
            if self._regenerate:
                self._regenerate = False
                return True
            return False

    def wait_for_connection_approval(
        self,
        *,
        prospect_name: str,
        company: str,
        connection_request: str,
    ) -> str:
        """Block until user approves send, edits, regenerates, or skips."""
        with self._lock:
            self._edited_connection_request = None

        self.update(
            approval_pending=True,
            prospect_name=prospect_name,
            company=company,
            pending_connection_request=connection_request,
            step="Awaiting approval — connection request ready",
        )
        self._approval_event.clear()
        self._approval_decision = None

        while not self._approval_event.is_set():
            if self._stop:
                raise StopAutomation()
            if self._save_and_stop:
                raise SaveAndStop()
            if self._skip:
                self._skip = False
                self.update(approval_pending=False)
                raise SkipProspect()
            if self._regenerate:
                self._regenerate = False
                self.update(approval_pending=False)
                return "regenerate"
            time.sleep(0.2)

        decision = self._approval_decision or "approve_send"
        self.update(approval_pending=False)
        return decision

    def _set_approval(self, decision: str) -> None:
        self._approval_decision = decision
        self._approval_event.set()
        self._pause_event.set()


class StopAutomation(AutomationError):
    """User requested stop."""


class SaveAndStop(AutomationError):
    """User requested save and stop."""


class SkipProspect(AutomationError):
    """User requested skip current prospect."""


class RetryProspect(AutomationError):
    """User requested retry current prospect."""


class ProcessNextPage(AutomationError):
    """User requested pagination."""


class OpenProfileRequest(AutomationError):
    """User requested opening current profile in browser."""
