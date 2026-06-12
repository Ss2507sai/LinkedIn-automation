"""Pinned tab management for single-session automation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.errors import TabNotFoundError
from src.logger import get_logger

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from config.settings import Settings

logger = get_logger()


@dataclass
class PinnedTabs:
    sales_nav_url: str = ""
    chatgpt_url: str = ""


class TabRegistry:
    """Track exactly one Sales Navigator tab and one ChatGPT tab."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sales_nav_page: Page | None = None
        self._chatgpt_page: Page | None = None

    @property
    def sales_nav_page(self) -> Page:
        if self._sales_nav_page is None:
            raise TabNotFoundError("Sales Navigator tab not pinned")
        return self._sales_nav_page

    @property
    def chatgpt_page(self) -> Page:
        if self._chatgpt_page is None:
            raise TabNotFoundError("ChatGPT tab not pinned")
        return self._chatgpt_page

    def pin_sales_nav(self, page: Page) -> None:
        self._sales_nav_page = page
        logger.info("Pinned Sales Navigator tab: %s", page.url[:120])

    def pin_chatgpt(self, page: Page) -> None:
        self._chatgpt_page = page
        logger.info("Pinned ChatGPT tab: %s", page.url[:120])

    def save(self) -> None:
        path = self.settings.pinned_tabs_json
        data = PinnedTabs(
            sales_nav_url=self._sales_nav_page.url if self._sales_nav_page else "",
            chatgpt_url=self._chatgpt_page.url if self._chatgpt_page else "",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(data), indent=2), encoding="utf-8")

    def log_all_tabs(self, context, action: str) -> None:
        for i, page in enumerate(context.pages):
            try:
                title = page.title()
                url = page.url
            except Exception:
                title, url = "?", "?"
            logger.info("TAB [%s] idx=%d title=%r url=%s", action, i, title[:60], url[:120])
