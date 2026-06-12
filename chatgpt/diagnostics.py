"""ChatGPT reliability diagnostics — logging and timeout artifact capture."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.logger import get_logger
from src.screenshots import capture_error_screenshot

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from config.settings import Settings

from chatgpt.waiter import (
    _count_assistant_messages,
    _get_all_assistant_texts,
    _get_latest_response_text,
    _is_generating,
)

logger = get_logger()

DIAG_PREFIX = "CGPT_DIAG"


@dataclass
class ChatGPTRunMetrics:
    """Per-profile ChatGPT interaction metrics."""

    prospect_label: str = ""
    submission_ts: str = ""
    assistant_count_before: int = 0
    assistant_count_after_submit: int = 0
    generation_start_ts: str | None = None
    generation_complete_ts: str | None = None
    generation_started: bool = False
    generation_completed: bool = False
    time_to_response_sec: float | None = None
    response_chars: int = 0
    connection_request_chars: int = 0
    has_connection_request_marker: bool = False
    still_generating_at_timeout: bool = False
    outcome: str = "pending"
    error: str = ""
    extra: dict = field(default_factory=dict)

    def log_summary(self) -> None:
        payload = asdict(self)
        logger.info("%s %s", DIAG_PREFIX, json.dumps(payload, default=str))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def snapshot_conversation_state(page: Page) -> dict:
    """Capture current ChatGPT DOM conversation state for debugging."""
    assistant_count = _count_assistant_messages(page)
    latest = _get_latest_response_text(page, min_index=0)
    all_texts = _get_all_assistant_texts(page)
    return {
        "url": page.url,
        "generating": _is_generating(page),
        "assistant_message_count": assistant_count,
        "latest_assistant_chars": len(latest),
        "latest_assistant_preview": latest[:500] if latest else "",
        "latest_has_connection_request": "CONNECTION_REQUEST" in latest if latest else False,
        "all_assistant_lengths": [len(t) for t in all_texts],
        "all_assistant_previews": [t[:200] for t in all_texts[-5:]],
    }


def capture_timeout_artifacts(
    page: Page,
    settings: Settings,
    *,
    prospect_label: str,
    metrics: ChatGPTRunMetrics,
    baseline_message_count: int,
) -> Path | None:
    """Screenshot + JSON state dump when ChatGPT wait times out."""
    settings.ensure_directories()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in prospect_label)[:60]
    audit_dir = settings.project_root / "audits" / "chatgpt_investigation"
    audit_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path = capture_error_screenshot(
        page, settings, f"chatgpt_timeout_{safe_label}"
    )

    latest = _get_latest_response_text(page, min_index=baseline_message_count)
    if not latest:
        latest = _get_latest_response_text(page, min_index=0)

    state = snapshot_conversation_state(page)
    state["baseline_message_count"] = baseline_message_count
    state["latest_assistant_full"] = latest
    state["metrics"] = asdict(metrics)
    state["screenshot"] = screenshot_path

    out_path = audit_dir / f"{timestamp}_{safe_label}_timeout.json"
    out_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    logger.error("%s timeout artifacts saved: %s", DIAG_PREFIX, out_path)

    if latest:
        logger.error(
            "%s latest assistant message (%d chars, marker=%s): %s",
            DIAG_PREFIX,
            len(latest),
            "CONNECTION_REQUEST" in latest,
            latest[:800],
        )
    else:
        logger.error("%s no assistant message text found at timeout", DIAG_PREFIX)

    return out_path


def capture_parse_failure_artifacts(
    page: Page,
    settings: Settings,
    *,
    prospect_label: str,
    raw_response: str,
    metrics: ChatGPTRunMetrics,
) -> Path | None:
    """Capture state when response arrived but parsing failed."""
    settings.ensure_directories()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in prospect_label)[:60]
    audit_dir = settings.project_root / "audits" / "chatgpt_investigation"
    audit_dir.mkdir(parents=True, exist_ok=True)

    capture_error_screenshot(page, settings, f"chatgpt_parse_fail_{safe_label}")

    state = snapshot_conversation_state(page)
    state["raw_response"] = raw_response
    state["metrics"] = asdict(metrics)

    out_path = audit_dir / f"{timestamp}_{safe_label}_parse_fail.json"
    out_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    logger.error("%s parse-fail artifacts saved: %s", DIAG_PREFIX, out_path)
    return out_path
